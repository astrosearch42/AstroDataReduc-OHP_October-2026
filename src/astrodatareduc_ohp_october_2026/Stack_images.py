from pathlib import Path

import numpy as np

from .Utils.Utils import (
    image_group_key,
    read_raw_image,
    tk_window_folder_selection,
    write_fits_image,
)


def aligned_fits_files(directory: Path) -> list[Path]:
    """Return FITS files whose name contains ``_aligned``."""
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".fits"
        and "_aligned" in path.stem.lower()
    )


def stack_images(lights_dir: str | Path, output_dir: str | Path | None = None) -> list[Path]:
    """Median-stack aligned FITS images from ``lights_dir``.

    The result is written in the selected directory as
    ``stacked_<directory-name>.fits``.
    """
    input_dir = Path(lights_dir)
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Dossier FITS introuvable : {input_dir}")

    output_path = Path(output_dir) if output_dir is not None else input_dir
    output_path.mkdir(parents=True, exist_ok=True)
    files = aligned_fits_files(input_dir)
    if not files:
        print(
            "Aucun fichier FITS aligné (*_aligned*.fits) trouvé "
            f"dans {input_dir}."
        )
        return []

    groups = {}
    for file in files:
        _, header = read_raw_image(file, get_header=1)
        groups.setdefault(image_group_key(header), []).append(file)

    output_files = []
    for group, group_files in sorted(groups.items(), key=lambda item: item[0]):
        first_data, header = read_raw_image(group_files[0], get_header=1)
        if first_data.ndim != 2:
            raise ValueError(f"Image FITS invalide : {group_files[0]}")
        image_shape = first_data.shape
        data_stack = np.empty((len(group_files), *image_shape), dtype=np.float32)
        data_stack[0] = np.asarray(first_data, dtype=np.float32)
        for index, file in enumerate(group_files[1:], start=1):
            data = read_raw_image(file)
            if data.ndim != 2 or data.shape != image_shape:
                raise ValueError(
                    f"Les images doivent avoir la même forme 2D : "
                    f"{file} ({data.shape} au lieu de {image_shape})."
                )
            data_stack[index] = np.asarray(data, dtype=np.float32)

        with np.errstate(invalid="ignore"):
            center = np.nanmedian(data_stack, axis=0)
            spread = np.nanstd(data_stack, axis=0)
            valid = np.abs(data_stack - center) <= 3 * spread
            valid |= spread == 0
            clipped_stack = np.where(valid, data_stack, np.nan)
            stacked_data = np.nanmedian(clipped_stack, axis=0)
        object_name, filter_name, exposure = group
        safe_exposure = str(exposure).replace(".", "p")
        output_file = output_path / (
            f"stacked_{object_name}_{filter_name}_{safe_exposure}s.fits"
        )
        header["OBJECT"] = f"STACKED_{object_name}_{filter_name}"
        header["STACKN"] = len(group_files)
        write_fits_image(output_file, stacked_data, header)
        print(f"Image empilée créée : {output_file}")
        output_files.append(output_file)
    return output_files


def main() -> None:
    lights_dir = tk_window_folder_selection()
    stack_images(lights_dir)