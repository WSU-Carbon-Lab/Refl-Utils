import os
from pathlib import Path
from shutil import copy2
from tqdm import tqdm
from tkinter import *
from astropy.io import fits


def restartable(func):
    def wrapper(*args, **kwargs) -> None:
        answer = "y"
        while answer == "y":
            func(*args, **kwargs)
            while True:
                answer = input("Restart?  y/n:")
                if answer in ("y", "n"):
                    break
                else:
                    print("invalid answer")

    return wrapper


def check_parent(dir: Path) -> None:
    """
    Makes a new directory for the sorted data

    Parameters
    ----------
    dir : pathlib.Path
        Directory of the data that you want sorted
    """
    p_dir = dir.parent
    Directories = [x[0] for x in os.walk(p_dir)]
    sort_path = p_dir / "Sorted"
    if not sort_path.exists():
        sort_path.mkdir()
    else:
        print(
            "The sorted directory already exists - Checking for energy sub-directories"
        )
    return


@restartable
def xrr_sorter() -> None:
    """
    Collects the energies each fits was collected at and makes subfolder for each energy
    Generates a dictionary containing the current file location, and its destination.

    Parameters
    ----------
    dir : pathlib.Path
        Directory of the data that you want sorted
    """

    # get the data directory from user input using tkinter
    from tkinter import filedialog

    root = Tk()
    root.withdraw()
    directory = Path(filedialog.askdirectory())

    # check if the parent directory exist
    check_parent(directory)

    # Make a list of all fits files and their full path
    files = list(directory.glob("*fits"))
    sort_dir = directory.parent / "Sorted"

    i = 0
    for file in tqdm(files):
        # Opens the file nad reads the energy; round the energy to the nearest energy resolvable by the device
        with fits.open(file) as headers:
            new_en = round(headers[0].header[49], 1)

        # determine the ending location
        dest = sort_dir / str(new_en)

        # makes a new directory for the new energy
        if not dest.exists():
            dest.mkdir()

        # copies the file to the new directory
        copy2(file, dest)
        i += 1
    return


if __name__ == "__main__":
    xrr_sorter()
