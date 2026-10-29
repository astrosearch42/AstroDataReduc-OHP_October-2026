import os
from pathlib import Path
import glob
from .Utils.Utils import *

### Load DOF

def make_master_offset():
    files = sorted(glob.glob(os.path.join(OFFSET_DIR, '*.fits')))
    # Load all offset files and compute the master offset
    nfiles=len(files)
    assert nfiles>0, "No offset files found in the specified directory."
    data, header_ori = read_raw_image(files[0], get_header=1)
    if data.ndim != 2:
        raise ValueError("Offset images must be two-dimensional")
    datastore = np.empty((nfiles, *data.shape), dtype=np.float64)
    for i, file in enumerate(files):
        current = read_raw_image(file)
        if current.shape != data.shape:
            raise ValueError(f"Offset images have inconsistent shapes: {file}")
        datastore[i] = current
    result = np.median(datastore, axis=0)
    master_bias_file=os.path.join(MASTER_DIR, 'master_bias.fits')
    header = header_ori
    header['OBJECT'] = 'MASTER_BIAS'
    for keyword in ('FLTRNM', 'TM-EXPOS', 'EXPTIME'):
        header.remove(keyword, ignore_missing=True)
    header['CALIBRAT'] = 'BIAS'
    header['COMBINE'] = 'MEDIAN'
    header['NCOMBINE'] = nfiles
    write_fits_image(master_bias_file, result, header)
    print(f'Master offset created and saved to {master_bias_file}')
    return master_bias_file

def make_master_flat(master_bias_file=None):
    if master_bias_file is None:
        master_bias_file = os.path.join(MASTER_DIR, 'master_bias.fits')
    if not os.path.exists(master_bias_file):
        raise FileNotFoundError("Master bias file not found. Create it first.")
    master_bias=read_raw_image(master_bias_file)
    master_flat_file = None

    for filter in sorted(ALL_FLAT_DIR):
        filter_dir = os.path.join(FLAT_DIR, filter)
        if not os.path.isdir(filter_dir):
            continue
        files = sorted(
            file for file in glob.glob(os.path.join(filter_dir, '*.fits'))
            if not Path(file).stem.endswith('_norm')
        )
        nfiles=len(files)
        if nfiles == 0:
            raise FileNotFoundError(f"No raw flats found for filter {filter}")
        data, header_ori = read_raw_image(files[0], get_header=1)
        if data.shape != master_bias.shape:
            raise ValueError(f"Flat and bias shapes differ for filter {filter}")
        normalized = np.full((nfiles, *data.shape), np.nan, dtype=np.float64)
        for i, file in enumerate(files):
            current = np.asarray(read_raw_image(file), dtype=np.float64)
            if current.shape != data.shape:
                raise ValueError(f"Flat images have inconsistent shapes: {file}")
            current[current >= 65535] = np.nan
            current -= master_bias
            current[current <= 0] = np.nan
            level = np.nanmedian(current)
            if not np.isfinite(level) or level <= 0:
                raise ValueError(f"Flat has no valid signal after bias subtraction: {file}")
            normalized[i] = current / level
        result = np.nanmedian(normalized, axis=0)
        result /= np.nanmedian(result)
        master_flat_file = os.path.join(MASTER_DIR, f'master_flat_{filter}.fits')
        header=header_ori
        header['OBJECT']='MASTER_FLAT'
        header['CALIBRAT'] = 'FLAT'
        header['COMBINE'] = 'MEDIAN'
        header['NCOMBINE'] = nfiles
        write_fits_image(master_flat_file,result,header)
        print(f'Master flat created and saved to {master_flat_file}')
    return master_flat_file

def main():
    master_bias = make_master_offset()
    make_master_flat(master_bias)
    