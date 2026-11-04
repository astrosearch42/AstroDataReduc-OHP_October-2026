from .Utils.Utils import (
    ADU_px_hist,
    ADU_px_hist_all,
    Path,
    iter_fits_files,
    plot_fits,
    plot_fits_all,
    print_header,
    tk_window_folder_selection,
    modify_header,
)


def main() -> None:
    datadir = tk_window_folder_selection()
    files = iter_fits_files(datadir)
    if not files:
        print("Aucun fichier FITS trouvé dans le dossier sélectionné.")
        return
    file_input = input("Entrez le numéro du fichier FITS à analyser (ou appuyez sur Entrée pour utiliser le premier fichier) : ")
    show_info = input("Voulez-vous afficher toutes les informations de l'header ? (o/n) : ").strip().lower() in {'o', 'y'}
    if show_info:
        l = 1
    else:
        l = 0
        
    print("\n============================== ANALYSE FITS ===============================\n")
    if file_input == "":
        file_to_analyze = files[0]
        print(f"Analyse du premier fichier FITS : {Path(file_to_analyze).name}")
        plot_fits(file_to_analyze)
        ADU_px_hist(file_to_analyze)
        print_header(file_to_analyze, keywords_list=['OBJECT', 'EXPTIME'], l=0)
    elif file_input.lower() in {"all", "tous"}:
        # plot_fits_all(files)
        # ADU_px_hist_all(files)
        for file in files:
            print("\n---------------------------------------------------------------------------")
            print(f"Analyse du fichier FITS : {Path(file).name}\n")
            print_header(file, keywords_list=['OBJECT', 'EXPTIME','FILTER'], l=l)
        modify_header_bool = input("Voulez-vous modifier un mot-clé dans l'header de tous les fichiers FITS ? (o/n) : ").strip().lower() in {'o', 'y'}
        if modify_header_bool:
            keyword = input("Entrez le mot-clé à modifier : ").strip()
            value = input(f"Entrez la nouvelle valeur pour le mot-clé '{keyword}' : ").strip()
            for file in files:
                modify_header(file, keyword, value)
                print(f"Mot-clé '{keyword}' modifié dans l'header du fichier {Path(file).name}.")
    else:
        try:
            file_to_analyze = files[int(file_input)]
        except (ValueError, IndexError) as exc:
            raise ValueError(f"Indice de fichier FITS invalide : {file_input!r}") from exc
        print(f"Analyse du fichier FITS : {Path(file_to_analyze).name}")
        plot_fits(file_to_analyze)
        ADU_px_hist(file_to_analyze)
        print_header(file_to_analyze, keywords_list=['OBJECT', 'FILTER'], l=l)


