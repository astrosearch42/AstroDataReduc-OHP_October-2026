import os
from pathlib import Path
import glob
from .Utils.Utils import *

### Load DOF
OFFSET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'photo', 'offsets'))
FLAT_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'photo', 'flats'))

MASTER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'photo', 'masters'))

def make_master_offset(files):
    # Load all offset files and compute the master offset
    nfiles=len(files)
    assert nfiles>0, "No offset files found in the specified directory."
    data,header_ori=read_raw_image(files[0],get_header=1)
    nx,ny=np.shape(data)
    datastore=np.full((nx,ny,nfiles),0.)
    # store individual images into an array
    for i in range(nfiles):
        datastore[:,:,i]=read_raw_image(files[i])
    # compute median of nfiles images
    result=np.median(datastore,axis=2)
    master_bias_file=os.path.join(MASTER_DIR, 'master_bias.fits')
    # update the OBJECT field of header
    header=header_ori
    header['OBJECT']='MASTER_BIAS'
    # write to file
    if not os.path.exists(master_bias_file):
        write_fits_image(master_bias_file,result,header)
        print(f'Master offset created and saved to {master_bias_file}')
    else:
        print(f'Master offset already exists at {master_bias_file}. Overwriting ? (y/n)')
        choice = input().lower()
        if choice == 'y':
            write_fits_image(master_bias_file,result,header)
            print(f'Master offset created and saved to {master_bias_file}')
        else:
            print('Overwriting cancelled.')
    return master_bias_file

def make_master_flat(files, filter_name='B'):
    nfiles=len(files)
    assert nfiles>0, "No flat files found in the specified directory."
    if not os.path.exists(os.path.join(MASTER_DIR, 'master_bias.fits')):
        raise FileNotFoundError("Master bias file not found. Please create it first.")
    master_bias=read_raw_image(os.path.join(MASTER_DIR, 'master_bias.fits'))
    
    
    # Remove the master_bias from each flat and compute the normalized flats, where earch flat is divided by its median:
    for file in files :
        data,header=read_raw_image(file,get_header=1)
        data=data-master_bias # Bias subtraction!
        data=data/np.median(data) # rescaling so that median(data)=1
        
        newfile=Path(file).stem+'_norm'+Path(file).suffix
        newfile=os.path.join(FLAT_DIR, f'{filter_name}', newfile)
        write_fits_image(newfile,data,header)
        print(f'Normalized flat created and saved to {newfile}')
    
    # Now median the normalized flats to get the master_flat in the considered filter
    data,header_ori=read_raw_image(files[0],get_header=1)
    nx,ny=np.shape(data)
    datastore=np.full((nx,ny,nfiles),0.)
    # store individual images into an array
    for i in range(nfiles):
        datastore[:,:,i]=read_raw_image(files[i])
        
    # compute median of nfiles images
    result=np.median(datastore,axis=2)
    master_flat_file = os.path.join(MASTER_DIR, f'master_flat_{filter_name}.fits')
    header=header_ori
    header['OBJECT']='MASTER_FLAT'
    # write to file
    if not os.path.exists(master_flat_file):
        write_fits_image(master_flat_file,result,header)
        print(f'Master flat created and saved to {master_flat_file}')
    else:
        print(f'Master flat already exists at {master_flat_file}. Overwriting ? (y/n)')
        choice = input().lower()
        if choice == 'y':
            write_fits_image(master_flat_file,result,header)
            print(f'Master flat created and saved to {master_flat_file}')
        else:
            print('Overwriting cancelled.')
    return master_flat_file

def main():
    # Offset
    offset_bool = False
    if offset_bool:
        files = glob.glob(os.path.join(OFFSET_DIR, '*.fits'))
        master_file = make_master_offset(files)
        plot_fits(master_file, exp='autostretch')
    
    # Flat
    filter_name = 'B'
    flat_bool = False
    if flat_bool:
        print(f'Looking for flat files in {FLAT_DIR}')
        files = glob.glob(os.path.join(FLAT_DIR, f'*{filter_name}', '*.fits'))
        master_file = make_master_flat(files, filter_name=filter_name)
        plot_fits(master_file, exp='autostretch')