lazy import glob
lazy import os

from .Utils.Utils import *

def main() -> None:
    datadir = tk_window_folder_selection()
    files = sorted(glob.glob(os.path.join(datadir, '*.fits')))
    if not files:
        print("No FITS files found in the selected directory.")
        return
    file_input = input("Enter the number of the FITS file to analyze (or press Enter to use the first file): ")
    if file_input == "":
        file_to_analyze = files[0]
        plot_fits(file_to_analyze)
        ADU_px_hist(file_to_analyze)
        print_header(file_to_analyze, keywords_list=['OBJECT', 'TM-EXPOS'], l=0)
    elif file_input.lower() == "all":
        for file in files:
            plot_fits(file)
            # ADU_px_hist(file)
            print_header(file, keywords_list=['OBJECT', 'TM-EXPOS'], l=0)
    else:
        try:
            file_to_analyze = files[int(file_input)]
        except (ValueError, IndexError) as exc:
            raise ValueError(f"Invalid FITS file index: {file_input!r}") from exc
        plot_fits(file_to_analyze)
        ADU_px_hist(file_to_analyze)
        print_header(file_to_analyze, keywords_list=['OBJECT', 'TM-EXPOS'], l=0)
    
    
    