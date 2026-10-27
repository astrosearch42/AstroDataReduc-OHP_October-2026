from pathlib import Path

import numpy as np

from .Utils.Utils import (
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


def stack_images(lights_dir: str | Path) -> Path | None:
    """Median-stack aligned FITS images from ``lights_dir``.

    The result is written in the selected directory as
    ``stacked_<directory-name>.fits``.
    """
    input_dir = Path(lights_dir)
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Dossier FITS introuvable : {input_dir}")

    files = aligned_fits_files(input_dir)
    if not files:
        print(
            "Aucun fichier FITS aligné (*_aligned*.fits) trouvé "
            f"dans {input_dir}."
        )
        return None

    first_data, header = read_raw_image(files[0], get_header=1)
    if first_data is None or first_data.ndim != 2:
        raise ValueError(f"Image FITS invalide : {files[0]}")

    image_shape = first_data.shape
    data_stack = np.empty((len(files), *image_shape), dtype=np.float32)
    data_stack[0] = np.asarray(first_data, dtype=np.float32)

    for index, file in enumerate(files[1:], start=1):
        data = read_raw_image(file)
        if data is None or data.ndim != 2 or data.shape != image_shape:
            raise ValueError(
                f"Les images doivent avoir la même forme 2D : "
                f"{file} ({getattr(data, 'shape', None)} au lieu de {image_shape})."
            )
        data_stack[index] = np.asarray(data, dtype=np.float32)

    stacked_data = np.median(data_stack, axis=0)
    output_file = input_dir / f"stacked_{input_dir.name}.fits"
    header["OBJECT"] = f"STACKED_{input_dir.name}"
    write_fits_image(output_file, stacked_data, header)
    print(f"Image empilée créée : {output_file}")
    return output_file


def main() -> None:
    lights_dir = tk_window_folder_selection()
    stack_images(lights_dir)