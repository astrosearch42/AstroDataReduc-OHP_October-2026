from pathlib import Path

from .Utils.Utils import (
    MASTER_DIR,
    np,
    filter_name_from_header,
    plot_image,
    read_raw_image,
    tk_window_folder_selection,
    write_fits_image,
)


def reduce_images(files, master_dark=None):
    """Reduce raw science images with the matching bias and normalized flat."""
    input_files = [Path(file) for file in files]
    if not input_files:
        raise ValueError("No FITS science images were provided")

    master_bias = read_raw_image(Path(MASTER_DIR) / "master_bias.fits")
    dark_data = read_raw_image(master_dark) if master_dark is not None else None
    reduced_files = []

    for file in input_files:
        if file.stem.lower().endswith("_reduced"):
            continue
        data, header = read_raw_image(file, get_header=1)
        filter_name = filter_name_from_header(header)
        master_flat = read_raw_image(
            Path(MASTER_DIR) / f"master_flat_{filter_name}.fits"
        )
        if data.shape != master_bias.shape or data.shape != master_flat.shape:
            raise ValueError(f"Calibration shape mismatch for {file}")
        if dark_data is not None and dark_data.shape != data.shape:
            raise ValueError(f"Dark shape mismatch for {file}")

        calibrated = data.astype(np.float64) - master_bias
        if dark_data is not None:
            calibrated -= dark_data
        with np.errstate(divide="ignore", invalid="ignore"):
            reduced = calibrated / master_flat
        reduced[~np.isfinite(reduced)] = np.nan

        output = file.with_name(f"{file.stem}_{filter_name}_reduced{file.suffix}")
        header["CALIBRAT"] = "BIAS+FLAT" if dark_data is None else "BIAS+DARK+FLAT"
        header["FLTRCAL"] = filter_name
        write_fits_image(output, reduced, header)
        print("Reduced file written to", output)
        reduced_files.append(output)

    return reduced_files


def main() -> None:
    data_dir = Path(tk_window_folder_selection())
    files = sorted(
        path for path in data_dir.glob("*.fits")
        if not path.stem.lower().endswith("_reduced")
    )
    reduced_files = reduce_images(files)
    if reduced_files:
        plot_image(read_raw_image(reduced_files[-1]))
