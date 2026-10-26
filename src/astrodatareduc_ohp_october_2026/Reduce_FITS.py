import os
import glob
from pathlib import Path

from .Utils.Utils import *

# Now reduce the observed images:
# 1=> subtract bias
# 2=> divide by flat WITH THE CORRESPONDING FILTER!!
DATADIR = tk_window_folder_selection()
MASTER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'photo', 'masters'))

files=glob.glob(os.path.join(DATADIR, 'p439*.fits'))

def reduce_images(files, filter_name):
    for file in files:
        data,header=read_raw_image(file,get_header=1)
        filter_obs=header['FLTRNM']
        if(filter_obs.find(f"{filter_name} Cousins")>=0): # this checks that the filters match
            print('Reducing ',file, filter_obs)
            master_bias=read_raw_image(os.path.join(MASTER_DIR, 'master_bias.fits'))
            master_flat=read_raw_image(os.path.join(MASTER_DIR, f'master_flat_{filter_name}.fits'))
            # THE IMPORTANT, KEY PART!!!
            ##########################
            reduced=(data-master_bias)/master_flat
            ##########################
            reduced_file=Path(file).stem+'_reduced'+Path(file).suffix
            reduced_file=os.path.join(DATADIR, f'{filter_name}', reduced_file)
            write_fits_image(reduced_file,reduced,header)
            print('Reduced file written to ',reduced_file)
    return reduced_file

# do this for each filter or automatize

def main() -> None:
    # Example usage
    reduced_file=reduce_images(files, filter_name='B')
    data_reduced=read_raw_image(reduced_file)
    plot_image(data_reduced)