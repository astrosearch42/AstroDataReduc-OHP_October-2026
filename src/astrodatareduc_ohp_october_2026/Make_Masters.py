from .Utils.Utils import (
    FLAT_DIR,
    MASTER_DIR,
    OFFSET_DIR,
    Path,
    existing_master_files_by_type,
    filter_name_from_header,
    fits_path,
    iter_fits_files,
    iter_fits_files_recursive,
    np,
    os,
    read_raw_image,
    write_fits_image,
)

### Chargement des offsets

def make_master_offset(offset_dir=OFFSET_DIR, output_dir=MASTER_DIR):
    files = iter_fits_files(offset_dir)
    # Charge tous les offsets et calcule le master bias.
    nfiles=len(files)
    assert nfiles > 0, "Aucun fichier d'offset trouvé dans le dossier indiqué."
    data, header_ori = read_raw_image(files[0], get_header=1)
    if data.ndim != 2:
        raise ValueError("Les images d'offset doivent être en deux dimensions")
    datastore = np.empty((nfiles, *data.shape), dtype=np.float32)
    for i, file in enumerate(files):
        current = np.asarray(read_raw_image(file), dtype=np.float32)
        if current.shape != data.shape:
            raise ValueError(f"Les images d'offset ont des dimensions incompatibles : {file}")
        datastore[i] = current
        print(f"Bias en cours : {i + 1}/{nfiles}")
    result = np.median(datastore, axis=0)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    master_bias_file=os.path.join(str(output_dir), 'master_bias.fits')
    header = header_ori
    header['OBJECT'] = 'MASTER_BIAS'
    for keyword in ('FLTRNM', 'TM-EXPOS', 'EXPTIME'):
        header.remove(keyword, ignore_missing=True)
    header['CALIBRAT'] = 'BIAS'
    header['COMBINE'] = 'MEDIAN'
    header['NCOMBINE'] = nfiles
    write_fits_image(master_bias_file, result.astype(np.float32), header)
    print(f'Master bias créé et enregistré dans {master_bias_file}')
    return master_bias_file

def make_master_flat(flat_dir=FLAT_DIR, master_bias_file=None, output_dir=MASTER_DIR):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if master_bias_file is None:
        master_bias_file = fits_path(output_dir, "master_bias")
    if not os.path.exists(master_bias_file):
        raise FileNotFoundError("Fichier master bias introuvable. Créez-le d'abord.")
    master_bias=read_raw_image(master_bias_file)
    master_flat_file = None

    flat_dir = Path(flat_dir)
    direct_files = iter_fits_files(flat_dir)
    nested_files = iter_fits_files_recursive(flat_dir)
    files = nested_files if any(file.parent != flat_dir for file in nested_files) else direct_files
    files = [file for file in files if not Path(file).stem.endswith("_norm")]
    files_by_filter = {}
    for file in files:
        _, header = read_raw_image(file, get_header=1)
        filter_name = filter_name_from_header(header)
        files_by_filter.setdefault(filter_name, []).append(file)

    if not files_by_filter:
        raise FileNotFoundError(f"Aucun flat brut trouvé dans {flat_dir}")

    for filter_name, filter_files in sorted(
        files_by_filter.items(), key=lambda item: item[0] or ""
    ):
        nfiles = len(filter_files)
        data, header_ori = read_raw_image(filter_files[0], get_header=1)
        if data.shape != master_bias.shape:
            raise ValueError(f"Les dimensions du flat et du bias diffèrent pour le filtre {filter_name or 'inconnu'}")
        normalized = np.full((nfiles, *data.shape), np.nan, dtype=np.float32)
        for i, file in enumerate(filter_files):
            current = np.asarray(read_raw_image(file), dtype=np.float32)
            if current.shape != data.shape:
                raise ValueError(f"Les images flat ont des dimensions incompatibles : {file}")
            current[current >= 65535] = np.nan
            current -= master_bias
            current[current <= 0] = np.nan
            level = np.nanmedian(current)
            if not np.isfinite(level) or level <= 0:
                raise ValueError(f"Le flat ne contient aucun signal valide après soustraction du bias : {file}")
            normalized[i] = current / level
            print(
                f"Flat {filter_name or 'général'} en cours : "
                f"{i + 1}/{nfiles}"
            )
        result = np.nanmedian(normalized, axis=0)
        result /= np.nanmedian(result)
        master_stem = "master_flat" if filter_name is None else f"master_flat_{filter_name}"
        master_flat_file = os.path.join(str(output_dir), f"{master_stem}.fits")
        header=header_ori
        header['OBJECT']='MASTER_FLAT'
        if filter_name is None:
            header.remove("FLTRNM", ignore_missing=True)
        else:
            header["FLTRCAL"] = filter_name
        header['CALIBRAT'] = 'FLAT'
        header['COMBINE'] = 'MEDIAN'
        header['NCOMBINE'] = nfiles
        write_fits_image(master_flat_file, result.astype(np.float32), header)
        print(f'Master flat créé et enregistré dans {master_flat_file}')
    return master_flat_file


def make_master_dark(dark_dir, output_dir=MASTER_DIR):
    """Crée un master dark médian incluant le niveau de bias de la caméra."""
    files = iter_fits_files(dark_dir)
    if not files:
        raise FileNotFoundError(f"Aucune image dark trouvée dans {dark_dir}")
    first, header = read_raw_image(files[0], get_header=1)
    if first.ndim != 2:
        raise ValueError("Les images dark doivent être en deux dimensions")
    stack = np.empty((len(files), *first.shape), dtype=np.float32)
    for index, file in enumerate(files):
        data = np.asarray(read_raw_image(file), dtype=np.float32)
        if data.shape != first.shape:
            raise ValueError(f"Les images dark ont des dimensions incompatibles : {file}")
        stack[index] = data
        print(f"Dark en cours : {index + 1}/{len(files)}")
    result = np.median(stack, axis=0)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output = Path(output_dir) / "master_dark.fits"
    header["OBJECT"] = "MASTER_DARK"
    header["CALIBRAT"] = "BIAS+DARK"
    header["COMBINE"] = "MEDIAN"
    header["NCOMBINE"] = len(files)
    write_fits_image(output, result, header)
    print(f"Master dark créé et enregistré dans {output}")
    return output


def main():
    existing = existing_master_files_by_type(MASTER_DIR)
    decisions = {}
    for master_type, label in (
        ("bias", "bias"),
        ("flat", "flat"),
        ("dark", "dark"),
    ):
        if existing[master_type]:
            answer = input(
                f"Le master {label} existe déjà. Voulez-vous le recréer ? [o/N] "
            ).strip().lower()
            decisions[master_type] = answer in {"o", "oui", "y", "yes"}
        else:
            decisions[master_type] = True

    if decisions["bias"]:
        master_bias = make_master_offset()
    else:
        master_bias = fits_path(MASTER_DIR, "master_bias")

    if decisions["flat"]:
        make_master_flat(master_bias_file=master_bias)
    if decisions["dark"]:
        dark_dir = Path(os.path.join(os.path.dirname(FLAT_DIR), "darks"))
        if dark_dir.is_dir():
            make_master_dark(dark_dir)
    