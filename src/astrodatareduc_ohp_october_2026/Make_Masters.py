import os
from pathlib import Path
import glob
from .Utils.Utils import *

### Load DOF

def make_master_offset():
    files = glob.glob(os.path.join(OFFSET_DIR, '*.fits'))
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

def make_master_flat():
    master_bias=read_raw_image(os.path.join(MASTER_DIR, 'master_bias.fits'))
    
    for filter in ALL_FLAT_DIR:
        files = glob.glob(os.path.join(FLAT_DIR, f'{filter}', '*.fits')) 
        nfiles=len(files)
        assert nfiles>0, "No flat files found in the specified directory."
        if not os.path.exists(os.path.join(MASTER_DIR, 'master_bias.fits')):
            raise FileNotFoundError("Master bias file not found. Please create it first.")
        
        # Remove the master_bias from each flat and compute the normalized flats, where earch flat is divided by its median:
        for file in files :
            data,header=read_raw_image(file,get_header=1)
            data=data-master_bias # Bias subtraction!
            data=data/np.median(data) # rescaling so that median(data)=1
            
            newfile=Path(file).stem+'_norm'+Path(file).suffix
            newfile=os.path.join(FLAT_DIR, f'{filter}', newfile)
            write_fits_image(newfile,data,header)
            
        # Now median the normalized flats to get the master_flat in the considered filter
        data,header_ori=read_raw_image(files[0],get_header=1)
        nx,ny=np.shape(data)
        datastore=np.full((nx,ny,nfiles),0.)
        # store individual images into an array
        for i in range(nfiles):
            datastore[:,:,i]=read_raw_image(files[i])
            
        # compute median of nfiles images
        result=np.median(datastore,axis=2)
        master_flat_file = os.path.join(MASTER_DIR, f'master_flat_{filter}.fits')
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
    flat_bool = False
    offset_bool = False
    
    if not flat_bool and not offset_bool:
        print("Both flat and offset creation are set to False. Masters Creation Cancelled.")
        return
    
    # Offset
    if offset_bool:
        master_file = make_master_offset()
        plot_fits(master_file, exp='autostretch')
    
    # Flat
    if flat_bool:
        master_file = make_master_flat()
        plot_fits(master_file, exp='autostretch')
    