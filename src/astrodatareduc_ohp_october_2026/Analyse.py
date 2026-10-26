import os
lazy import glob

from .Utils.Utils import *

### Import files
DATADIR = tk_window_folder_selection()

files = glob.glob(os.path.join(DATADIR, '*.fits'))


def main() -> None:
    file_input = input("Enter the number of the FITS file to analyze (or press Enter to use the first file): ")
    if file_input == "":
        file_to_analyze = files[0]
    else:
        file_to_analyze = files[int(file_input)]
    plot_fits(file_to_analyze)
    ADU_px_hist(file_to_analyze)
    print_header(file_to_analyze, keywords_list=['OBJECT', 'TM-EXPOS'], l=0)
