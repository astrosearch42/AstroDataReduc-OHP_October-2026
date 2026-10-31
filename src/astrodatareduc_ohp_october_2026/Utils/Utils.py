lazy import os
lazy import sys
lazy from pathlib import Path

lazy import matplotlib.pyplot as plt
lazy import numpy as np
lazy from astropy.io import fits
lazy from matplotlib import cm
lazy from matplotlib.colors import LogNorm

### Chemins utiles pour l'utilisation du code en mode non gui
OFFSET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'photo', 'offsets'))
FLAT_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'photo', 'flats'))
ALL_FLAT_DIR = os.listdir(FLAT_DIR)
MASTER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'photo', 'masters'))

### Chemins utiles pour l'utilisation du code en mode gui
DATADIR_GUI = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'OBJ'))

### Dictionnaires utiles à modifier si nécessaire
FLTRNM_OHP = {
    'R Cousins': 'R',
    'V Cousins': 'V',
    'B Cousins': 'B',
    'H Alpha ohp 6565': 'Ha',
    'O3 ohp 5007': 'O3',
}
FITS_SUFFIXES = (".fit", ".fits")

### Fonctions
def processing_workers(requested=None):
    """Retourne un nombre prudent de workers pour traiter de grandes images FITS."""
    if requested is not None:
        if requested < 1:
            raise ValueError("Le nombre de workers doit être au moins égal à un")
        return requested
    configured = os.environ.get("ASTRODATAREDUC_WORKERS")
    if configured:
        try:
            requested = int(configured)
        except ValueError as exc:
            raise ValueError(
                "ASTRODATAREDUC_WORKERS doit être un entier positif"
            ) from exc
        if requested < 1:
            raise ValueError("ASTRODATAREDUC_WORKERS doit être au moins égal à un")
        return requested
    return max(1, min(4, os.cpu_count() or 1))

def iter_fits_files(directory):
    """Retourne tous les fichiers FITS d'un dossier avec l'une des extensions acceptées."""
    directory = Path(directory)
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in FITS_SUFFIXES
    )

def iter_fits_files_recursive(directory):
    """Retourne les fichiers FITS directement dans un dossier ou dans ses sous-dossiers."""
    directory = Path(directory)
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in FITS_SUFFIXES
    )

def fits_path(directory, stem):
    """Retourne le chemin FITS existant correspondant au nom demandé."""
    directory = Path(directory)
    for suffix in reversed(FITS_SUFFIXES):
        candidate = directory / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    return directory / f"{stem}.fits"

def filter_name_from_header(header):
    """Retourne le nom canonique du filtre stocké dans un header FITS OHP."""
    raw_filter = header.get("FLTRNM")
    if raw_filter is None:
        return None
    filter_name = raw_filter.strip()
    if not filter_name:
        return None
    try:
        return FLTRNM_OHP[filter_name]
    except KeyError as exc:
        raise ValueError(f"Nom de filtre OHP inconnu : {filter_name!r}") from exc

def image_group_key(header):
    """Retourne l'identité objet/filtre/pose utilisée pour l'empilement."""
    object_name = str(header.get("OBJECT", "")).strip().split(" / ")[0]
    filter_name = filter_name_from_header(header)
    exposure = header.get("TM-EXPOS", header.get("EXPTIME"))
    return object_name, filter_name, exposure

def existing_master_files(directory):
    """Retourne les fichiers master déjà présents dans un dossier."""
    if not Path(directory).is_dir():
        return []
    return sorted(
        path
        for path in iter_fits_files(directory)
        if path.stem.lower().startswith("master_")
    )

def existing_master_files_by_type(directory):
    """Retourne séparément les masters bias, flat et dark existants."""
    masters = existing_master_files(directory)
    return {
        "bias": [
            path for path in masters
            if path.stem.lower() == "master_bias"
        ],
        "flat": [
            path for path in masters
            if path.stem.lower().startswith("master_flat")
        ],
        "dark": [
            path for path in masters
            if path.stem.lower() == "master_dark"
        ],
    }

def debayer_bilinear(data, bayer_pattern):
    """Convertit une image Bayer 2D en plans RGB par interpolation bilinéaire."""
    if data.ndim != 2:
        raise ValueError("Le débayering nécessite une image Bayer en deux dimensions")
    pattern = str(bayer_pattern or "").upper()
    if len(pattern) != 4 or set(pattern) != {"R", "G", "B"}:
        raise ValueError(f"Motif Bayer non pris en charge : {bayer_pattern!r}")

    height, width = data.shape
    yy, xx = np.indices((height, width))
    colors = np.array(list(pattern)).reshape(2, 2)
    color_map = colors[yy % 2, xx % 2]
    planes = []
    padded_data = np.pad(np.asarray(data, dtype=np.float32), 1, mode="edge")
    for color in ("R", "G", "B"):
        mask = (color_map == color).astype(np.float32)
        padded_mask = np.pad(mask, 1, mode="edge")
        values = np.zeros_like(mask)
        weights = np.zeros_like(mask)
        for dy in range(3):
            for dx in range(3):
                values += (
                    padded_data[dy:dy + height, dx:dx + width]
                    * padded_mask[dy:dy + height, dx:dx + width]
                )
                weights += padded_mask[dy:dy + height, dx:dx + width]
        planes.append(values / np.maximum(weights, 1))
    return np.stack(planes, axis=0)

def balance_rgb_channels(data):
    """Met les plans RGB à l'échelle d'un niveau médian robuste commun."""
    if data.ndim != 3 or data.shape[0] != 3:
        raise ValueError("L'équilibrage des canaux RGB nécessite une image à trois plans")
    medians = np.array(
        [np.nanmedian(channel) for channel in data],
        dtype=np.float32,
    )
    target = np.nanmedian(medians)
    if not np.all(np.isfinite(medians)) or target <= 0:
        raise ValueError("Impossible d'équilibrer les canaux RGB avec des médianes invalides")
    return data * (target / medians)[:, None, None]

def get_scaling(data):
    """Valeurs utiles pour définir vmin et vmax dans plt.imshow."""
    vmin=np.average(data)-2.*np.std(data)
    vmax=np.average(data)+2.*np.std(data)
    return vmin,vmax 

def get_stats(file):
    """Retourne le nom du fichier, le nombre de pixels (nx*ny), la moyenne, la dispersion (sigma), le minimum et le maximum."""
    data=read_raw_image(file)
    nx,ny=np.shape(data)
    return [file,nx*ny,np.average(data),np.std(data),np.min(data),np.max(data)]

def read_raw_image(fits_file, get_header=0):
    """Copie les données et l'header avant de fermer le fichier FITS afin que Windows puisse le remplacer ultérieurement."""
    with fits.open(fits_file) as hdulist:
        data = hdulist[0].data.copy()
        header = hdulist[0].header.copy()
    if data is None:
        raise ValueError(f"Le fichier FITS ne contient aucune image primaire : {fits_file}")
    if get_header == 0:
        return data
    if get_header == 1:
        return data, header
    raise ValueError("get_header doit être égal à 0 ou 1")

def read_fits_metadata(fits_file):
    """Lit une copie de l'header primaire FITS et la forme de l'image sans charger les pixels."""
    with fits.open(fits_file, memmap=False) as hdulist:
        data = hdulist[0].data
        header = hdulist[0].header.copy()
        shape = None if data is None else data.shape
    if shape is None:
        raise ValueError(f"Le fichier FITS ne contient aucune image primaire : {fits_file}")
    return shape, header

def write_fits_image(target_file, image, header):
    """Écrit une image FITS avec un header donné, en créant les dossiers parents si nécessaire."""
    target_path = Path(target_file)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    hdu = fits.PrimaryHDU(data=image, header=header)
    hdul = fits.HDUList([hdu])
    hdul.writeto(target_path, overwrite=True)
  
def plot_image(data):
    """Affiche une image 2D avec une échelle automatique."""
    plt.figure(figsize=(7,7))
    vmin,vmax=get_scaling(data)
    plt.imshow(data,origin='lower',aspect='auto',vmin=vmin,vmax=vmax)
    plt.show()

def plot_fits(file, exp=None):
    """Affiche une image FITS avec une échelle spécifiée (linear, log, autostretch)."""
    data = read_raw_image(file)
    plt.figure(figsize=(7,7))
    if exp is None:
        exp = input("Entrez l'échelle (linear, log, autostretch) : ") or 'autostretch'
    else:
        pass  # Utilise la valeur exp fournie.
    if exp.lower() == 'linear':
        plt.imshow(data,cmap=cm.gray,norm=None,origin='lower',aspect='auto')
    elif exp.lower() == 'log':
        plt.imshow(data,cmap=cm.gray,norm=LogNorm(),origin='lower',aspect='auto')
    elif exp.lower() == 'autostretch':
        vmin,vmax=get_scaling(data)
        plt.imshow(data,cmap=cm.gray,norm=None,origin='lower',aspect='auto',vmin=vmin,vmax=vmax)
        plt.colorbar()
    else:
        raise ValueError("exp doit être 'linear', 'log' ou 'autostretch'")
    plt.show()

def plot_fits_all(files, exp=None):
    """Affiche toutes les images FITS d'une liste avec une échelle spécifiée (linear, log, autostretch)."""
    n = len(files)
    ncols = 3
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 5 * nrows))
    axes = np.array(axes).flatten()
    if exp is None:
        exp = input("Entrez l'échelle (linear, log, autostretch) : ") or 'autostretch'
    for i, file in enumerate(files):
        data = read_raw_image(file)
        ax = axes[i]
        if exp.lower() == 'linear':
            im = ax.imshow(data, cmap=cm.gray, norm=None, origin='lower', aspect='auto')
        elif exp.lower() == 'log':
            im = ax.imshow(data, cmap=cm.gray, norm=LogNorm(), origin='lower', aspect='auto')
        elif exp.lower() == 'autostretch':
            vmin, vmax = get_scaling(data)
            im = ax.imshow(data, cmap=cm.gray, origin='lower', aspect='auto', vmin=vmin, vmax=vmax)
        else:
            raise ValueError("exp doit être 'linear', 'log' ou 'autostretch'")
        ax.set_title(Path(file).name)
        fig.colorbar(im, ax=ax)
    for ax in axes[n:]:
        ax.set_visible(False)
    plt.tight_layout()
    plt.show()

def ADU_px_hist(file):
    """Affiche l'histogramme des pixels d'une image FITS avec une échelle logarithmique sur l'axe des ordonnées."""
    data = read_raw_image(file)
    bins=np.linspace(0.,65000.,200)
    plt.figure(figsize=(8,5))
    h,bins=np.histogram(data.flatten(),bins)
    plt.plot(bins[:-1],h)
    plt.yscale('log')
    #plt.xscale('log')
    plt.title('Histogramme des pixels')
    plt.xlabel('ADU')
    plt.ylabel('comptage')
    plt.grid(True)
    plt.show()

def ADU_px_hist_all(files):
    """Affiche les histogrammes des pixels de plusieurs images FITS avec une échelle logarithmique sur l'axe des ordonnées."""
    n = len(files)
    ncols = 3
    nrows = int(np.ceil(n / ncols))
    _, axes = plt.subplots(nrows, ncols, figsize=(15, 4 * nrows))
    axes = np.array(axes).flatten()
    bins = np.linspace(0., 65000., 200)
    for i, file in enumerate(files):
        data = read_raw_image(file)
        h, edges = np.histogram(data.flatten(), bins=bins)
        axes[i].plot(edges[:-1], h)
        axes[i].set_yscale('log')
        axes[i].set_title(Path(file).name)
        axes[i].set_xlabel('ADU')
        axes[i].set_ylabel('Comptage')
        axes[i].grid(True)
    for ax in axes[n:]:
        ax.set_visible(False)
    plt.tight_layout()
    plt.show()

def print_header(file, keywords_list = None, l=0):
    """Affiche l'header d'un fichier FITS. Si keywords_list est fourni, affiche uniquement les mots-clés spécifiés."""
    with fits.open(file) as fits_file:
        header = fits_file[0].header
        # Affiche tout l'header.
        if l == 1:
            print(repr(header))
        else:
            for keyword in keywords_list:
                if keyword in header:
                    result = ' '.join(str(header[keyword]).split())
                    print(f'Fichier : {Path(file).name} | {keyword:8s} = {result}')
                else:
                    print(f"{keyword:8s} = Introuvable dans l'header")

### Code annexe
def tk_window_folder_selection():
    """
    Ouvre une fenêtre Tkinter pour sélectionner un dossier.
    Retourne le chemin du dossier sélectionné.
    """
    import os
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
    
    # Chargement des données.
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    DEFAULT_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", '..'))
    root = tk.Tk()
    prepare_dialog_root(root)
    # Toujours au premier plan.
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    # Ouvre la boîte de dialogue.
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
