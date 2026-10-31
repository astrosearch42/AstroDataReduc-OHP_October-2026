from concurrent.futures import ThreadPoolExecutor

import astroalign as aa

from .Utils.Utils import (
    FITS_SUFFIXES,
    Path,
    image_group_key,
    np,
    processing_workers,
    read_raw_image,
    tk_window_folder_selection,
    write_fits_image,
)

ALIGNED_SUFFIX = "_aligned"
REDUCED_MARKER = "_reduced"


def fits_files(directory: Path) -> list[Path]:
    """Retourne les fichiers FITS réduits, en excluant les sorties d'alignement."""
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() in FITS_SUFFIXES
        and REDUCED_MARKER in path.stem.lower()
        and not path.stem.lower().endswith(ALIGNED_SUFFIX)
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
    workers: int | None = None,
) -> list[Path]:
    """Aligne chaque image FITS de ``lights_dir`` sur une image de référence.

    La référence est par défaut le premier fichier FITS dans l'ordre alphabétique.
    Les fichiers alignés reçoivent le suffixe ``_aligned`` et l'en-tête FITS
    original est conservé.
    """
    input_dir = Path(lights_dir)
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Dossier lights introuvable : {input_dir}")

    files = fits_files(input_dir)
    if not files:
        print(
            "Aucun fichier FITS réduit (*_reduced*.fit ou *.fits) trouvé. "
            "Il faut réduire les données avant de les aligner."
        )
        return []

    if reference_file is not None:
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
    print(f"[Alignement] Dossier source : {input_dir}")
    print(f"[Alignement] Dossier de sortie : {destination_dir}")
    print(f"[Alignement] Fichiers détectés : {len(files)}")

    if reference_file is None:
        groups = {}
        for path in files:
            _, header = read_raw_image(path, get_header=1)
            groups.setdefault(image_group_key(header), []).append(path)
        reference_groups = [
            (group_files[0], group_files)
            for group_files in groups.values()
        ]
    else:
        _, reference_header = read_image(reference_path)
        reference_group = image_group_key(reference_header)
        group_files = [
            path for path in files
            if image_group_key(read_raw_image(path, get_header=1)[1]) == reference_group
        ]
        reference_groups = [(reference_path, group_files)]

    aligned_files: list[Path] = []
    total_files = sum(len(group_files) for _, group_files in reference_groups)
    print(
        f"Les calculs en cours : alignement astroalign de {total_files} image(s) "
        f"dans {len(reference_groups)} groupe(s)."
    )
    def align_group(group_reference, group_files):
        print(
            f"Référence d'alignement : {group_reference.name} "
            f"({len(group_files)} image(s))."
        )
        print(
            "[Alignement] La référence est chargée ; astroalign cherchera "
            "les étoiles communes dans chaque autre image."
        )
        reference_data, _ = read_image(group_reference)

        def align_one(source_path):
            print(f"[Alignement] Lecture de {source_path.name}...")
            source_data, header = read_image(source_path)
            if source_path.resolve() == group_reference.resolve():
                aligned_data = source_data
                print(
                    f"[Alignement] {source_path.name} est la référence : "
                    "aucune transformation nécessaire."
                )
            else:
                try:
                    print(
                        f"[Alignement] Recherche de la transformation "
                        f"{source_path.name} -> {group_reference.name}..."
                    )
                    aligned_data, _ = aa.register(source_data, reference_data)
                    print(
                        f"[Alignement] Transformation trouvée pour "
                        f"{source_path.name}; reprojection terminée."
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"Impossible d'aligner {source_path.name} sur "
                        f"{group_reference.name} : {exc}"
                    ) from exc

            destination = destination_dir / (
                f"{source_path.stem}{ALIGNED_SUFFIX}{source_path.suffix}"
            )
            header["ALIGNREF"] = group_reference.name
            for keyword in (
                "WCSAXES", "CTYPE1", "CTYPE2", "CRPIX1", "CRPIX2",
                "CRVAL1", "CRVAL2", "CDELT1", "CDELT2",
            ):
                header.remove(keyword, ignore_missing=True)
            write_fits_image(destination, aligned_data, header)
            print(
                f"[Alignement] Écriture de l'image alignée : "
                f"{destination.name}"
            )
            return destination

        with ThreadPoolExecutor(
            max_workers=processing_workers(workers)
        ) as executor:
            futures = [executor.submit(align_one, path) for path in group_files]
            return [future.result() for future in futures]

    for group_reference, group_files in reference_groups:
        group_outputs = align_group(group_reference, group_files)
        aligned_files.extend(group_outputs)
        for destination in group_outputs:
            print(f"Image alignée écrite : {destination.name}")

    print(f"Alignement terminé : {len(aligned_files)} image(s) produite(s).")
    return aligned_files


def align_selected_images(
    files: list[str | Path],
    output_dir: str | Path,
    reference_file: str | Path | None = None,
) -> list[Path]:
    """Aligne une sélection d'images 2D sur une référence commune."""
    input_files = [Path(file) for file in files]
    if not input_files:
        raise ValueError("Aucun fichier FITS à aligner.")
    if any(not file.is_file() for file in input_files):
        missing = next(file for file in input_files if not file.is_file())
        raise FileNotFoundError(f"Fichier FITS introuvable : {missing}")

    reference_path = (
        Path(reference_file) if reference_file is not None else input_files[0]
    )
    if reference_path.resolve() not in {file.resolve() for file in input_files}:
        raise ValueError("La référence doit faire partie des fichiers à aligner.")

    reference_data, _ = read_image(reference_path)
    print(
        f"[Alignement] Référence : {reference_path.name} "
        f"(dimensions : {reference_data.shape})."
    )
    print(
        f"[Alignement] {len(input_files)} fichier(s) vont être traité(s) "
        "séquentiellement."
    )
    destination_dir = Path(output_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    aligned_files = []
    for source_path in input_files:
        print(f"[Alignement] Lecture de {source_path.name}...")
        source_data, header = read_image(source_path)
        if source_path.resolve() == reference_path.resolve():
            aligned_data = source_data
            print(
                f"[Alignement] {source_path.name} est la référence : "
                "copie sans transformation."
            )
        else:
            try:
                print(
                    f"[Alignement] Astroalign recherche les étoiles communes "
                    f"pour {source_path.name} -> {reference_path.name}..."
                )
                aligned_data, _ = aa.register(source_data, reference_data)
                print(
                    f"[Alignement] Astroalign a terminé la reprojection de "
                    f"{source_path.name}."
                )
            except ValueError as exc:
                raise ValueError(
                    f"Impossible d'aligner {source_path.name} sur "
                    f"{reference_path.name} : {exc}"
                ) from exc
        destination = destination_dir / (
            f"{source_path.stem}{ALIGNED_SUFFIX}{source_path.suffix}"
        )
        header["ALIGNREF"] = reference_path.name
        for keyword in (
            "WCSAXES", "CTYPE1", "CTYPE2", "CRPIX1", "CRPIX2",
            "CRVAL1", "CRVAL2", "CDELT1", "CDELT2",
        ):
            header.remove(keyword, ignore_missing=True)
        write_fits_image(destination, aligned_data, header)
        print(f"[Alignement] Fichier écrit : {destination.name}")
        aligned_files.append(destination)
    print(f"Alignement terminé : {len(aligned_files)} image(s) produite(s).")
    return aligned_files


def main() -> None:
    lights_dir = tk_window_folder_selection()
    aligned_files = align_images(lights_dir)
    if aligned_files:
        print(f"{len(aligned_files)} image(s) alignée(s) dans {lights_dir}")
