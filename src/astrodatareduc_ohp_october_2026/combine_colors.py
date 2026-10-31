from __future__ import annotations


from .align_images import align_selected_images
from .Utils.Utils import (
    FITS_SUFFIXES,
    FLTRNM_OHP,
    Path,
    fits,
    np,
    read_raw_image,
    write_fits_image,
)


def _channel_from_filter(raw_filter: object) -> str | None:
    if raw_filter is None:
        return None
    filter_name = str(raw_filter).strip()
    if not filter_name:
        return None
    canonical_name = FLTRNM_OHP.get(filter_name, filter_name)
    channel = canonical_name.upper().replace("III", "3")
    if channel == "V":
        channel = "G"
    return channel if channel in {"R", "G", "B"} else None


def _narrowband_from_filter(raw_filter: object) -> str | None:
    if raw_filter is None:
        return None
    filter_name = str(raw_filter).strip()
    canonical_name = FLTRNM_OHP.get(filter_name, filter_name).upper()
    compact_name = canonical_name.replace(" ", "")
    if compact_name in {"HA", "HALPHA"}:
        return "HA"
    if compact_name in {"O3", "OIII"}:
        return "OIII"
    if compact_name in {"S2", "SII"}:
        return "SII"
    return None


def detect_channel_files(
    directory: str | Path,
    filter_keyword: str = "FLTRNM",
    mode: str = "RGB",
) -> dict[str, tuple[Path, str]]:
    """Trouve les fichiers et filtres requis par une recombinaison."""
    input_dir = Path(directory)
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Dossier FITS introuvable : {input_dir}")
    keyword = filter_keyword.strip()
    if not keyword:
        raise ValueError("Le nom de la clé FITS ne peut pas être vide.")
    candidates = detect_channel_candidates(directory, filter_keyword, mode)
    channels: dict[str, tuple[Path, str]] = {}
    for channel, values in candidates.items():
        if len(values) > 1:
            raise ValueError(
                f"Plusieurs fichiers correspondent au canal {channel} : "
                + ", ".join(path.name for path, _, _ in values)
            )
        path, raw_filter, _ = values[0]
        channels[channel] = (path, raw_filter)

    required_filters = _required_filters(mode)
    missing = sorted(set(required_filters) - channels.keys())
    if missing:
        raise ValueError(
            f"Canal(s) manquant(s) dans {input_dir} : {', '.join(missing)}."
        )
    return channels


def _required_filters(mode: str) -> dict[str, str]:
    if mode not in {"RGB", "HOO", "SHO", "RGB+Ha", "RGB+HOO", "RGB+SHO"}:
        raise ValueError(f"Mode de recombinaison inconnu : {mode}")
    return {
        "RGB": {"R": "R", "G": "G", "B": "B"},
        "HOO": {"R": "HA", "G": "OIII"},
        "SHO": {"R": "SII", "G": "HA", "B": "OIII"},
        "RGB+Ha": {"R": "R", "G": "G", "B": "B", "HA": "HA"},
        "RGB+HOO": {"R": "R", "G": "G", "B": "B", "HA": "HA", "OIII": "OIII"},
        "RGB+SHO": {
            "R": "R", "G": "G", "B": "B",
            "SII": "SII", "HA": "HA", "OIII": "OIII",
        },
    }[mode]


def detect_channel_candidates(
    directory: str | Path,
    filter_keyword: str = "FLTRNM",
    mode: str = "RGB",
) -> dict[str, list[tuple[Path, str, fits.Header]]]:
    """Retourne tous les fichiers candidats, y compris les doublons."""
    input_dir = Path(directory)
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Dossier FITS introuvable : {input_dir}")
    keyword = filter_keyword.strip()
    if not keyword:
        raise ValueError("Le nom de la clé FITS ne peut pas être vide.")
    required_filters = _required_filters(mode)
    candidates: dict[str, list[tuple[Path, str, fits.Header]]] = {}
    for path in sorted(input_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in FITS_SUFFIXES:
            continue
        _, header = read_raw_image(path, get_header=1)
        raw_filter = str(header.get(keyword, "")).strip()
        if mode in {"RGB", "RGB+Ha", "RGB+HOO", "RGB+SHO"}:
            filter_name = _channel_from_filter(raw_filter)
            if filter_name is None and mode in {"RGB+Ha", "RGB+HOO", "RGB+SHO"}:
                filter_name = _narrowband_from_filter(raw_filter)
        else:
            filter_name = _narrowband_from_filter(raw_filter)
        if filter_name is None:
            continue
        channel = next(
            (name for name, required in required_filters.items() if required == filter_name),
            None,
        )
        if channel is None:
            continue
        candidates.setdefault(channel, []).append((path, raw_filter, header))
    missing = sorted(set(required_filters) - candidates.keys())
    if missing:
        raise ValueError(
            f"Canal(s) manquant(s) dans {input_dir} : {', '.join(missing)}."
        )
    return candidates


def find_rgb_files(
    directory: str | Path,
    filter_keyword: str = "FLTRNM",
) -> dict[str, Path]:
    """Compatibilité : trouve les fichiers des trois canaux RGB."""
    return {
        channel: path
        for channel, (path, _) in detect_channel_files(directory, filter_keyword, "RGB").items()
    }


def combine_channels(
    directory: str | Path,
    filter_keyword: str = "FLTRNM",
    mode: str = "RGB",
    narrowband_coefficients: dict[str, float] | None = None,
    selected_files: dict[str, Path] | None = None,
    output_file: str | Path | None = None,
) -> Path:
    """Combine des images mono en cube RGB, HOO ou SHO."""
    channels = resolve_channel_files(
        directory, filter_keyword, mode, selected_files
    )
    source_paths = list({path for path, _ in channels.values()})
    aligned_dir = Path(directory) / ".recombination_aligned"
    expected_aligned = {
        aligned_dir / f"{path.stem}_aligned{path.suffix}"
        for path in source_paths
    }
    existing_aligned = (
        set(aligned_dir.iterdir()) if aligned_dir.is_dir() else set()
    )
    if not expected_aligned.issubset(existing_aligned):
        aligned_paths = align_selected_images(
            source_paths,
            aligned_dir,
            reference_file=channels["R"][0],
        )
        aligned_by_source = {
            source.resolve(): aligned
            for source, aligned in zip(source_paths, aligned_paths)
        }
    else:
        aligned_by_source = {
            source.resolve(): aligned_dir / f"{source.stem}_aligned{source.suffix}"
            for source in source_paths
        }
    data_by_channel: dict[str, np.ndarray] = {}
    headers: dict[str, fits.Header] = {}
    shape: tuple[int, ...] | None = None

    for channel in ("R", "G", "B"):
        if channel not in channels:
            source_channel = "G" if mode == "HOO" and channel == "B" else channel
            channels[channel] = channels[source_channel]
        source_path, _ = channels[channel]
        path = aligned_by_source[source_path.resolve()]
        data, header = read_raw_image(path, get_header=1)
        if data.ndim != 2:
            raise ValueError(
                f"L'image du canal {channel} doit être 2D : {path.name}."
            )
        if shape is None:
            shape = data.shape
        elif data.shape != shape:
            raise ValueError(
                "Les trois images doivent avoir la même taille : "
                f"{path.name} a la forme {data.shape}, "
                f"attendu {shape}."
            )
        data_by_channel[channel] = np.asarray(data, dtype=np.float32)
        headers[channel] = header

    assert shape is not None
    if mode in {"RGB+Ha", "RGB+HOO", "RGB+SHO"}:
        coefficients = narrowband_coefficients or {"R": 0.5, "G": 0.5, "B": 0.5}
        if set(coefficients) != {"R", "G", "B"} or any(
            not 0 <= value <= 1 for value in coefficients.values()
        ):
            raise ValueError(
                "Les coefficients narrowband doivent être compris entre 0 et 1 "
                "pour les canaux R, G et B."
            )
        extra_channels = (
            ("HA",)
            if mode == "RGB+Ha"
            else ("HA", "OIII")
            if mode == "RGB+HOO"
            else ("SII", "HA", "OIII")
        )
        for channel in ("R", "G", "B", *extra_channels):
            data = data_by_channel.get(channel)
            if data is None:
                path = aligned_by_source[channels[channel][0].resolve()]
                data, header = read_raw_image(path, get_header=1)
                if data.ndim != 2 or data.shape != shape:
                    raise ValueError(
                        f"L'image du canal {channel} doit avoir la forme {shape}."
                    )
                data_by_channel[channel] = np.asarray(data, dtype=np.float32)
                headers[channel] = header
            finite = data[np.isfinite(data)]
            positive = finite[finite > 0]
            median = np.nanmedian(positive) if positive.size else np.nan
            if not np.isfinite(median) or median == 0:
                raise ValueError(
                    f"Impossible de normaliser le canal {channel} : "
                    "médiane invalide ou nulle."
                )
            data_by_channel[channel] = data / median

        if mode == "RGB+Ha":
            data_by_channel["R"] = (
                (1 - coefficients["R"]) * data_by_channel["R"]
                + coefficients["R"] * data_by_channel["HA"]
            )
        elif mode == "RGB+HOO":
            data_by_channel["R"] = (
                (1 - coefficients["R"]) * data_by_channel["R"]
                + coefficients["R"] * data_by_channel["HA"]
            )
            data_by_channel["G"] = (
                (1 - coefficients["G"]) * data_by_channel["G"]
                + coefficients["G"] * data_by_channel["OIII"]
            )
            data_by_channel["B"] = (
                (1 - coefficients["B"]) * data_by_channel["B"]
                + coefficients["B"] * data_by_channel["OIII"]
            )
        else:
            data_by_channel["R"] = (
                (1 - coefficients["R"]) * data_by_channel["R"]
                + coefficients["R"] * data_by_channel["SII"]
            )
            data_by_channel["G"] = (
                (1 - coefficients["G"]) * data_by_channel["G"]
                + coefficients["G"] * data_by_channel["HA"]
            )
            data_by_channel["B"] = (
                (1 - coefficients["B"]) * data_by_channel["B"]
                + coefficients["B"] * data_by_channel["OIII"]
            )

    output_path = (
        Path(output_file)
        if output_file is not None
        else Path(directory) / f"{mode.lower().replace('+', '_').replace(' ', '_')}_recombined.fits"
    )
    header = headers["R"].copy()
    header["RGBORDER"] = "RGB"
    header["RGBMODE"] = mode
    header["RGBFILE"] = f"{mode} FITS recombination"
    header["FLTRKEY"] = filter_keyword.strip()
    header[filter_keyword.strip()] = mode
    if mode in {"RGB+Ha", "RGB+HOO", "RGB+SHO"}:
        header["NBCR"] = (float(coefficients["R"]), "NB coefficient R")
        header["NBCG"] = (float(coefficients["G"]), "NB coefficient G")
        header["NBCB"] = (float(coefficients["B"]), "NB coefficient B")
    object_name = str(header.get("OBJECT", "")).strip()
    header["OBJECT"] = f"{mode}_{object_name}" if object_name else mode
    cube = np.stack(
        [data_by_channel["R"], data_by_channel["G"], data_by_channel["B"]],
        axis=0,
    )
    write_fits_image(output_path, cube, header)
    print(f"Image {mode} créée : {output_path}")
    return output_path


def resolve_channel_files(
    directory: str | Path,
    filter_keyword: str,
    mode: str,
    selected_files: dict[str, Path] | None = None,
) -> dict[str, tuple[Path, str]]:
    candidates = detect_channel_candidates(directory, filter_keyword, mode)
    channels: dict[str, tuple[Path, str]] = {}
    for channel, values in candidates.items():
        selected = selected_files.get(channel) if selected_files else None
        matching = next(
            (
                value for value in values
                if selected is not None and value[0].resolve() == selected.resolve()
            ),
            None,
        )
        if matching is None and len(values) == 1:
            matching = values[0]
        if matching is None:
            raise ValueError(
                f"Plusieurs fichiers correspondent au canal {channel} : "
                + ", ".join(value[0].name for value in values)
            )
        channels[channel] = (matching[0], matching[1])
    return channels


def align_channels(
    directory: str | Path,
    filter_keyword: str = "FLTRNM",
    mode: str = "RGB",
    selected_files: dict[str, Path] | None = None,
) -> Path:
    """Aligne les fichiers sélectionnés et conserve les résultats temporaires."""
    channels = resolve_channel_files(
        directory, filter_keyword, mode, selected_files
    )
    print(f"[Alignement RGB] Mode : {mode}")
    print(f"[Alignement RGB] Clé de filtre : {filter_keyword}")
    for channel, (path, raw_filter) in sorted(channels.items()):
        print(
            f"[Alignement RGB] Canal {channel} : {path.name} "
            f"(filtre header : {raw_filter.strip() or 'absent'})"
        )
    source_paths = list({path for path, _ in channels.values()})
    aligned_dir = Path(directory) / ".recombination_aligned"
    print(
        f"[Alignement RGB] Les images seront alignées sur le canal R "
        f"dans {aligned_dir}."
    )
    align_selected_images(
        source_paths,
        aligned_dir,
        reference_file=channels["R"][0],
    )
    print("[Alignement RGB] Étape d'alignement terminée.")
    return aligned_dir


def combine_colors(
    directory: str | Path,
    filter_keyword: str = "FLTRNM",
    output_file: str | Path | None = None,
) -> Path:
    """Compatibilité : combine les trois images FITS RGB."""
    return combine_channels(
        directory,
        filter_keyword,
        "RGB",
        output_file=output_file,
    )
