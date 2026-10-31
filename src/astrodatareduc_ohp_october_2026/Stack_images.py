from .Utils.Utils import (
    FITS_SUFFIXES,
    Path,
    balance_rgb_channels,
    debayer_bilinear,
    image_group_key,
    np,
    read_raw_image,
    tk_window_folder_selection,
    write_fits_image,
)


def aligned_fits_files(directory: Path) -> list[Path]:
    """Retourne les fichiers FITS dont le nom contient ``_aligned``."""
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() in FITS_SUFFIXES
        and "_aligned" in path.stem.lower()
    )


def stack_images(
    lights_dir: str | Path,
    output_dir: str | Path | None = None,
    debayer: bool = False,
) -> list[Path]:
    """Empile par médiane les images FITS alignées de ``lights_dir``.

    Le résultat est écrit dans le dossier sélectionné sous le nom
    ``stacked_<nom-du-dossier>.fits``.
    """
    input_dir = Path(lights_dir)
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Dossier FITS introuvable : {input_dir}")

    output_path = Path(output_dir) if output_dir is not None else input_dir
    output_path.mkdir(parents=True, exist_ok=True)
    files = aligned_fits_files(input_dir)
    if not files:
        print(
            "Aucun fichier FITS aligné (*_aligned*.fit ou *.fits) trouvé "
            f"dans {input_dir}."
        )
        return []

    groups = {}
    for file in files:
        _, header = read_raw_image(file, get_header=1)
        groups.setdefault(image_group_key(header), []).append(file)

    output_files = []
    for group, group_files in sorted(groups.items(), key=lambda item: item[0]):
        print(
            f"Les calculs en cours : stacking médian de "
            f"{len(group_files)} image(s) pour le groupe {group}."
        )
        first_data, header = read_raw_image(group_files[0], get_header=1)
        if first_data.ndim not in {2, 3}:
            raise ValueError(f"Image FITS invalide : {group_files[0]}")
        image_shape = first_data.shape
        data_stack = np.empty((len(group_files), *image_shape), dtype=np.float32)
        data_stack[0] = np.asarray(first_data, dtype=np.float32)
        for index, file in enumerate(group_files[1:], start=1):
            data = read_raw_image(file)
            if data.ndim != first_data.ndim or data.shape != image_shape:
                raise ValueError(
                    f"Les images doivent avoir la même forme 2D : "
                    f"{file} ({data.shape} au lieu de {image_shape})."
                )
            data_stack[index] = np.asarray(data, dtype=np.float32)

        with np.errstate(invalid="ignore"):
            stacked_data = np.nanmedian(data_stack, axis=0)
        object_name, filter_name, exposure = group
        total_exposure = float(exposure or 0) * len(group_files)
        safe_exposure = str(total_exposure).replace(".", "p")
        filter_part = "" if filter_name is None else f"_{filter_name}"
        output_file = output_path / (
            f"stacked_{object_name}{filter_part}_{safe_exposure}s.fits"
        )
        if debayer:
            if stacked_data.ndim == 2:
                bayer_pattern = header.get("BAYERPAT")
                if bayer_pattern:
                    stacked_data = debayer_bilinear(stacked_data, bayer_pattern)
                    header["DEBAYER"] = "BILINEAR"
                    header.remove("BAYERPAT", ignore_missing=True)
            if stacked_data.ndim == 3:
                stacked_data = balance_rgb_channels(stacked_data)
        header["OBJECT"] = f"STACKED_{object_name}{filter_part}"
        header["STACKN"] = len(group_files)
        header["EXPTIME"] = total_exposure
        header["TOTEXP"] = total_exposure
        header["STKCOMB"] = "MEDIAN"
        write_fits_image(output_file, stacked_data, header)
        print(f"Image empilée créée : {output_file}")
        output_files.append(output_file)
    print(f"Stacking terminé : {len(output_files)} fichier(s) produit(s).")
    return output_files


def main() -> None:
    lights_dir = tk_window_folder_selection()
    answer = input("Débayeriser après empilement ? [o/N] ").strip().lower()
    stack_images(
        lights_dir,
        debayer=answer in {"o", "oui", "y", "yes"},
    )