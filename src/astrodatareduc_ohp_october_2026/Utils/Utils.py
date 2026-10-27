import os

lazy import matplotlib.pyplot as plt
lazy import numpy as np
lazy from astropy.io import fits
lazy from matplotlib import cm
lazy from matplotlib.colors import LogNorm
lazy from pathlib import Path

### Path
OFFSET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'photo', 'offsets'))
FLAT_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'photo', 'flats'))
ALL_FLAT_DIR = os.listdir(FLAT_DIR)

MASTER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'photo', 'masters'))


FLTRNM_OHP = {
    'R Cousins': 'R',
    'V Cousins': 'V',
    'B Cousins': 'B',
    'H Alpha ohp 6565': 'Ha',
    'O3 ohp 5007': 'O3',
}

def tk_window_folder_selection():
    """
    Ouvre une fenêtre Tkinter pour sélectionner un dossier.
    Retourne le chemin du dossier sélectionné.
    """
    import os
    import sys
    import tkinter as tk
    from pathlib import Path
    from tkinter import filedialog

    def prepare_dialog_root(root):
        root.withdraw()
        root.update_idletasks()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.geometry(f"1x1+{(screen_width - 1) // 2}+{(screen_height - 1) // 2}")
        root.attributes("-alpha", 0.0)
        root.deiconify()
        root.update()
    
    # CHARGEMENT DONNÉES
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    DEFAULT_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", '..'))
    root = tk.Tk()
    prepare_dialog_root(root)
    # Toujours au premier plan
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    # Ouvre la boîte de dialogue
    config_file = Path(os.path.join(SCRIPT_DIR, "misc", ".LAST_PATH_analyse_ppt.last_path"))
    default_path = Path(DEFAULT_PATH)
    if config_file.exists():
        last_path = Path(config_file.read_text().strip())
    else:
        last_path = default_path
    folder_name = filedialog.askdirectory(
        parent=root,
        initialdir=str(last_path),
        title="Sélectionnez un dossier"
    )
    if not folder_name:
        print("Sélection annulée.")
        sys.exit()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(folder_name)
    root.destroy()
    return folder_name

def get_scaling(data):
    # useful to set vmin,vmax in plt.imshow
    vmin=np.average(data)-2.*np.std(data)
    vmax=np.average(data)+2.*np.std(data)
    return vmin,vmax 

def get_stats(file):
    # returns 
    # filename, number of pixels (nx*ny), mean, dispersion (sigma), min, max
    data=read_raw_image(file)
    nx,ny=np.shape(data)
    return [file,nx*ny,np.average(data),np.std(data),np.min(data),np.max(data)]

def read_raw_image(fits_file, get_header=0):
    # Copy the data and header before closing the FITS file so Windows can
    # replace the file later.
    with fits.open(fits_file) as hdulist:
        data = hdulist[0].data.copy()
        header = hdulist[0].header.copy()
    if get_header == 0:
        return data
    if get_header == 1:
        return data, header
    raise ValueError("get_header must be 0 or 1")

def write_fits_image(target_file, image, header):
    target_path = Path(target_file)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    hdu = fits.PrimaryHDU(data=image, header=header)
    hdul = fits.HDUList([hdu])
    hdul.writeto(target_path, overwrite=True)
  
def plot_image(data):
    plt.figure(figsize=(7,7))
    vmin,vmax=get_scaling(data)
    plt.imshow(data,origin='lower',aspect='auto',vmin=vmin,vmax=vmax)
    plt.show()

def plot_fits(file, exp=None):
    data = read_raw_image(file)
    plt.figure(figsize=(7,7))
    if exp is None:
        exp = input('Enter scaling (linear, log, autostretch): ') or 'autostretch'
    else:
        pass # Use the provided exp value
    if exp.lower() == 'linear':
        plt.imshow(data,cmap=cm.gray,norm=None,origin='lower',aspect='auto')
    elif exp.lower() == 'log':
        plt.imshow(data,cmap=cm.gray,norm=LogNorm(),origin='lower',aspect='auto')
    elif exp.lower() == 'autostretch':
        vmin,vmax=get_scaling(data)
        plt.imshow(data,cmap=cm.gray,norm=None,origin='lower',aspect='auto',vmin=vmin,vmax=vmax)
        plt.colorbar()
    plt.show()

def ADU_px_hist(file):
    data = read_raw_image(file)
    bins=np.linspace(0.,65000.,200)
    plt.figure(figsize=(8,5))
    h,bins=np.histogram(data.flatten(),bins)
    plt.plot(bins[:-1],h)
    plt.yscale('log')
    #plt.xscale('log')
    plt.title('Pixels histogram')
    plt.xlabel('ADU')
    plt.ylabel('counts')
    plt.grid(True)
    plt.show()

def print_header(file, keywords_list = None, l=0):
    print(f'File: {file.split("\\")[-1]}')
    with fits.open(file) as fits_file:
        header = fits_file[0].header
        # print ALL:
        if l == 1:
            print(repr(header))
        else:
            result = ''
            for keyword in keywords_list:
                if keyword in header:
                    result = result + ' ' + str(header[keyword])
                else:
                    print(f'{keyword:8s} = Not found in header')
            print(result)    