from pathlib import Path

import astroalign as aa
import numpy as np

from .Utils.Utils import (
    read_raw_image,
    tk_window_folder_selection,
    write_fits_image,
)


ALIGNED_SUFFIX = "_aligned"
REDUCED_MARKER = "_reduced"


def fits_files(directory: Path) -> list[Path]:
    """Return reduced FITS files, excluding generated alignment outputs."""
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".fits"
        and REDUCED_MARKER in path.stem.lower()
        and path.stem.lower().endswith(ALIGNED_SUFFIX) is False
    )


def read_image(path: Path) -> tuple[np.ndarray, object]:
    data, header = read_raw_image(path, get_header=1)
    if data is None:
        raise ValueError(f"Le fichier FITS ne contient pas de données : {path}")
    if data.ndim != 2:
        raise ValueError(
            f"L'image FITS doit être en 2 dimensions ({path}, forme {data.shape})."
        )
    if not np.issubdtype(data.dtype, np.number):
        raise TypeError(f"Les données FITS doivent être numériques : {path}")
    return np.asarray(data, dtype=np.float32), header


def align_images(
    lights_dir: str | Path,
    reference_file: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> list[Path]:
    """Align every FITS image in ``lights_dir`` to one reference image.

    The reference defaults to the first FITS file in alphabetical order.
    Aligned files are written with the ``_aligned`` suffix and the original
    FITS header is preserved.
    """
    input_dir = Path(lights_dir)
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Dossier lights introuvable : {input_dir}")

    files = fits_files(input_dir)
    if not files:
        print(
            "Aucun fichier FITS réduit (*_reduced*.fits) trouvé. "
            "Il faut réduire les données avant de les aligner."
        )
        return []

    if reference_file is None:
        reference_path = files[0]
    else:
        reference_path = Path(reference_file)
        if not reference_path.is_absolute():
            reference_path = input_dir / reference_path
        reference_path = reference_path.resolve()
        if reference_path not in {file.resolve() for file in files}:
            raise ValueError(
                f"Le fichier de référence doit être un FITS de {input_dir} : "
                f"{reference_path}"
            )

    destination_dir = Path(output_dir) if output_dir is not None else input_dir
    destination_dir.mkdir(parents=True, exist_ok=True)

    reference_data, _ = read_image(reference_path)
    aligned_files: list[Path] = []
    for source_path in files:
        source_data, header = read_image(source_path)
        if source_path.resolve() == reference_path:
            aligned_data = source_data
        else:
            try:
                aligned_data, _ = aa.register(source_data, reference_data)
            except ValueError as exc:
                raise ValueError(
                    f"Impossible d'aligner {source_path.name} sur "
                    f"{reference_path.name} : {exc}"
                ) from exc

        destination = destination_dir / (
            f"{source_path.stem}{ALIGNED_SUFFIX}{source_path.suffix}"
        )
        write_fits_image(destination, aligned_data, header)
        aligned_files.append(destination)

    return aligned_files


def main() -> None:
    lights_dir = tk_window_folder_selection()
    aligned_files = align_images(lights_dir)
    if aligned_files:
        print(f"{len(aligned_files)} image(s) alignée(s) dans {lights_dir}")
