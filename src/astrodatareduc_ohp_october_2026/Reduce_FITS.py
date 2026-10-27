import os
import glob
from pathlib import Path

from .Utils.Utils import *

# Now reduce the observed images:
# 1=> subtract bias
# 2=> divide by flat WITH THE CORRESPONDING FILTER!!
DATADIR = tk_window_folder_selection()
files=glob.glob(os.path.join(DATADIR, '*.fits'))

def reduce_images(files):
    reduced_file = None
    for file in files:
        data,header=read_raw_image(file,get_header=1)
        filter_name=FLTRNM_OHP[header['FLTRNM'].strip()]
        master_bias=read_raw_image(os.path.join(MASTER_DIR, 'master_bias.fits'))
        master_flat=read_raw_image(os.path.join(MASTER_DIR, f'master_flat_{filter_name}.fits'))
        # THE IMPORTANT, KEY PART!!!
        ##########################
        reduced=(data-master_bias)/master_flat
        ##########################
        reduced_file=Path(file).stem+f'_{filter_name}_reduced'+Path(file).suffix
        reduced_file=os.path.join(DATADIR, reduced_file)
        write_fits_image(reduced_file,reduced,header)
        print('Reduced file written to ',reduced_file)
    return reduced_file
    

# do this for each filter or automatize

def main() -> None:
    # Example usage
    reduced_file=reduce_images(files)
    data_reduced=read_raw_image(reduced_file)
    plot_image(data_reduced)