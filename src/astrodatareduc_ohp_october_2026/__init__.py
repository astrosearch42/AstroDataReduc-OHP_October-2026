lazy from .align_images import main as main_align_images
lazy from .analyse import main as main_analyse
lazy from .gui import main as main_gui
lazy from .make_masters import main as main_make_masters
lazy from .reduce_fits import main as main_reduce_fits
lazy from .stack_images import main as main_stack_images


def main() -> None:
    print("Lancement du module d'analyse...")
    ToDo = input("Que voulez-vous faire ? (a : analyser, m : créer les masters, r : réduire les FITS, align : aligner les images, stack : empiler les images, gui : lancer l'interface graphique) : ")
    if ToDo.lower() == "a":
        main_analyse()
    elif ToDo.lower() == "m":
        main_make_masters()
    elif ToDo.lower() == "r":
        main_reduce_fits()
    elif ToDo.lower() == "align":
        main_align_images()
    elif ToDo.lower() == "stack":
        main_stack_images()
    elif ToDo.lower() == "gui":
        main_gui()