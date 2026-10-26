lazy from astrodatareduc_ohp_october_2026.Analyse import main as main_analyse
lazy from astrodatareduc_ohp_october_2026.Make_Masters import main as main_make_masters
lazy from astrodatareduc_ohp_october_2026.Reduce_FITS import main as main_reduce_fits


def main() -> None:
    print("Running Analysis module...")
    ToDo = input("What do you want to do? (a: Analyse, m: Make Masters, r: Reduce FITS): ")
    if ToDo.lower() == "a":
        main_analyse()
    elif ToDo.lower() == "m":
        main_make_masters()
    elif ToDo.lower() == "r":
        main_reduce_fits()