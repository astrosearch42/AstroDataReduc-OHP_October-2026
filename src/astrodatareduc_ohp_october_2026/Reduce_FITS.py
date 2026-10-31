from .Utils.Utils import (
    MASTER_DIR,
    Path,
    filter_name_from_header,
    fits_path,
    iter_fits_files,
    np,
    read_fits_metadata,
    read_raw_image,
    tk_window_folder_selection,
    write_fits_image,
)


def reduce_images(
    files,
    master_dir=MASTER_DIR,
    output_dir=None,
    calibration="bias",
):
    """Réduit les lights avec un seul master de correction sélectionné."""
    if calibration not in {"bias", "dark"}:
        raise ValueError("calibration doit être 'bias' ou 'dark'")
    input_files = [Path(file) for file in files]
    if not input_files:
        raise ValueError("Aucune image scientifique FITS n'a été fournie")

    master_dir = Path(master_dir)
    output_dir = Path(output_dir) if output_dir is not None else None
    correction_path = fits_path(master_dir, f"master_{calibration}")
    if not correction_path.exists():
        raise FileNotFoundError(
            f"Master {calibration} introuvable : {correction_path}"
        )
    correction_shape, _ = read_fits_metadata(correction_path)
    files_to_process = []
    for file in input_files:
        if file.stem.lower().endswith("_reduced"):
            continue
        data_shape, header = read_fits_metadata(file)
        filter_name = filter_name_from_header(header)
        master_stem = "master_flat" if filter_name is None else f"master_flat_{filter_name}"
        flat_path = fits_path(master_dir, master_stem)
        if not flat_path.exists():
            raise FileNotFoundError(f"Master flat introuvable : {flat_path}")
        flat_shape, _ = read_fits_metadata(flat_path)
        if data_shape != correction_shape or data_shape != flat_shape:
            raise ValueError(f"Dimensions de calibration incompatibles pour {file}")

        files_to_process.append((file, filter_name, flat_path))

    def reduce_one(item):
        file, filter_name, flat_path = item
        data, header = read_raw_image(file, get_header=1)
        correction = read_raw_image(correction_path)
        master_flat = read_raw_image(flat_path)
        flat = np.asarray(master_flat, dtype=np.float64)
        finite_flat = np.isfinite(flat)
        if not np.any(finite_flat):
            raise ValueError(f"Le master flat ne contient aucun pixel valide : {flat_path}")
        if np.any(flat[finite_flat] <= 0):
            raise ValueError(f"Le master flat contient des pixels invalides : {flat_path}")
        with np.errstate(divide="ignore", invalid="ignore"):
            reduced = (data.astype(np.float64) - correction) / flat
        reduced[~np.isfinite(reduced)] = np.nan

        destination_dir = output_dir if output_dir is not None else file.parent
        destination_dir.mkdir(parents=True, exist_ok=True)
        filter_suffix = f"_{filter_name}" if filter_name is not None else ""
        output = destination_dir / f"{file.stem}{filter_suffix}_reduced{file.suffix}"
        header["CALIBRAT"] = f"{calibration.upper()}+FLAT"
        if filter_name is not None:
            header["FLTRCAL"] = filter_name
        write_fits_image(output, reduced, header)
        return output

    reduced_files = []
    for index, item in enumerate(files_to_process, start=1):
        output = reduce_one(item)
        reduced_files.append(output)
        print(f"Réduction en cours : {index}/{len(files_to_process)} image(s) terminée(s).")
    return reduced_files


def main() -> None:
    data_dir = Path(tk_window_folder_selection())
    files = [
        path for path in iter_fits_files(data_dir)
        if not path.stem.lower().endswith("_reduced")
    ]
    reduce_images(files)
