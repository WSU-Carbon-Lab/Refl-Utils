"""Main module."""

from numbers import Rational
import os
import numpy as np
import pandas as pd
from astropy.io import fits
import matplotlib.pyplot as plt
from uncertainties import unumpy
import glob
import json

from xrr_toolkit import *


class XRR:
    """
    Main class for processing xrr data
    """

    def __init__(self, directory: str, error_method, height, *args, **kwargs):
        # main properties
        self.directory = directory
        self.q = np.array([], dtype=np.float64)
        self.r = np.array([], dtype=np.float64)
        self.xrr = pd.DataFrame()
        self.std_err = None
        self.shot_err = None

        # hidden properties
        self._error_method = error_method

    def calc_xrr(self, *args, **kwargs):
        """Main process for loading and calculating reflectivity curves"""
        self._fits_loader()
        self._data_reduction(*args, **kwargs)
        self._normalize()
        self._stitch(*args, **kwargs)
        self.r = np.concatenate(self.r_split, axis=None)

    def _fits_loader(self) -> None:
        """Load X-ray reflectometry data from FITS files in the specified directory.

        Computing the xrr profile requires Beamline Energy, Sample Theta, and Beam Current
        Files are opened with astropy and those values are extracted from the header data
        The images are collected from the image data

        """
        file_list = sorted(glob.glob(os.path.join(self.directory, "*.fits")))

        arrays = [
            [
                fits.getheader(f, 0)["Beamline Energy"],
                fits.getheader(f, 0)["Sample Theta"],
                fits.getheader(f, 0)["Beam Current"],
            ]
            for f in file_list
        ]

        self.images = np.squeeze(np.array([[fits.getdata(f, 2) for f in file_list]]))
        (
            self.energies,
            self.sample_theta,
            self.beam_current,
        ) = np.column_stack(arrays)

        self.q = scattering_vector(self.energies, self.sample_theta)

    def _image_slicer(self):
        max_idx = np.unravel_index(image.argmax(), image.shape)
        _min = np.array(max_idx) - HEIGHT
        _max = np.array(max_idx) + HEIGHT

        correction = np.zeros(2, dtype=np.int64)
        if np.any(_min < 0):
            loc = np.where(_min < 0)
            correction[loc] = -1 * _min[loc]
        if np.any(_max > image.shape[0]):
            loc = np.where(_max > image.shape[0])
            correction[loc] = image.shape[0] - _max[loc] - 1
        else:
            pass
        new_idx = tuple(map(lambda x, y: np.int64(x + y), max_idx, correction))
        assert is_valid_index(image, new_idx)

        roi = (
            slice(new_idx[0] - HEIGHT, new_idx[0] + HEIGHT + 1),
            slice(new_idx[1] - HEIGHT, new_idx[1] + HEIGHT + 1),
        )

    def _data_reduction(self) -> None:
        bright_spots, dark_spots = zip(*[locate_spot(image) for image in self.images])
        bright_spots = np.stack(bright_spots)
        dark_spots = np.stack(dark_spots)

        bright_sum = bright_spots.sum(axis=(2, 1))
        dark_sum = dark_spots.sum(axis=(2, 1))

        dark_std = np.array([np.std(np.ravel(u)) for u in dark_spots])

        r = (bright_sum - dark_sum) / self.beam_current
        self.std_err = dark_std / np.sqrt(
            bright_spots.shape[0]
        )  # only includes std of dark not of bright spot
        self.shot_err = np.sqrt(bright_sum + dark_sum) / self.beam_current
        if self._error_method == "shot":
            self.r = unumpy.uarray(r, self.shot_err)
        elif self._error_method == "std":
            self.r = unumpy.uarray(r, self.std_err)
        else:
            raise Exception(
                'Choose "shot" for possonian statistics, or "std" for gaussian statistics'
            )
        assert self.q.size == self.r.size

    def _normalize(self):
        """
        Normalization
        """
        # find the cutoff for i_zero points
        izero_count = np.count_nonzero(self.q == 0)

        izero = uaverage(self.r[: izero_count - 1]) if izero_count > 0 else ufloat(1, 0)

        self.r = self.r[izero_count:] / izero
        self.q = self.q[izero_count:]
        self.images = self.images[izero_count:]
        assert self.r.size == self.q.size

    def _update_stats(self):
        """
        Internal function to update the stats based on the first frame in the data set.
        """
        self._repeat_index = np.where(np.absolute(np.diff(self.q)) < 1e-3)[0] + 1

    def _calculate_stitch_points(self):
        """
        Internal function for computing the stitch points in the dataset.
        The function splits self.r, self.q, and self.images into
        self.r_split, self.q_split, and self.image_split
        """

    def _stitch(self, tol=0.1):
        """
        Internal function used to stitch each of the subsets together.
        The function uses the backend intersect1d numpy function to
        determine intersct points between subsequent sets

        """
        ind = np.where(np.diff(self.q) < 0)[0] + 1

        q_split = np.split(self.q, ind)
        r_split = np.split(self.r, ind)
        self._image_split = np.split(self.images, ind)

        stitch_points = min([len(sub) for sub in q_split]) + 1

        self.q_split = [sub for sub in q_split if len(sub) > stitch_points]
        self.r_split = [sub for sub in r_split if len(sub) > stitch_points]
        self._ratios = []
        self._overlap = []
        for i, (sub_q, sub_r) in enumerate(zip(self.q_split, self.r_split)):
            if i == len(self.q_split) - 1:
                pass
            else:
                ratio = np.array([])  # keep track of where the sections overlap
                for j, q in enumerate(sub_q):
                    stitch_indices = np.where(
                        np.isclose(self.q_split[i + 1], q, rtol=tol)
                    )[0]
                    next_r_values = self.r_split[i + 1][stitch_indices]
                    r_value = sub_r[j]
                    ratio = np.append(ratio, r_value / next_r_values)
                ratio = uaverage(ratio)
                self.r_split[i + 1] = self.r_split[i + 1] * ratio
                self._ratios.append(ratio)
        self.r = np.concatenate(self.r_split)
        self.q = np.concatenate(self.q_split)
        assert self.r.size == self.q.size

    def plot(self) -> None:
        """Plot the X-ray reflectometry data and a reference curve."""
        plt.errorbar(
            self.q, unumpy.nominal_values(self.r), unumpy.std_devs(self.r), fmt="."
        )
        plt.legend()
        plt.yscale("log")
        plt.show()

    def full_plot(self):
        import seaborn as sns

        fig, axs = plt.subplots(3, 1, sharex=True)
        plt.tick_params(which="both", right=True, top=True)
        plt.minorticks_on()

        for j, method in enumerate(self.METHODS):
            self.error_method = method
            self.calc_xrr()
            for i, sub in enumerate(zip(self.q_split, self.r_split)):
                axs[1 + j].errorbar(
                    sub[0],
                    unumpy.nominal_values(sub[1]),
                    unumpy.std_devs(sub[1]),
                    fmt=".",
                    label=f"Scan = {i+1}",
                )
                axs[1 + j].set_ylabel(f"Specular Reflectivity {method}")
            axs[0].plot(self.q, unumpy.std_devs(self.r), "--", label=f"{method}")
        axs[0].set_ylabel(r"Uncertianties $\sigma_R$")

        plt.xlabel(r"q $[\AA]$")

        for i in range(len(axs)):
            axs[i].legend()
            axs[i].set_yscale("log")
        plt.legend()
        plt.show()


def multi_loader(sort=False):
    parent_dir = file_dialog()
    if sort == True:
        xrr_sorter(parent_dir)

    multi_xrr = []
    for energy in os.listdir(parent_dir):
        full_file_path = os.path.join(parent_dir, energy)
        xrr = XRR(full_file_path)
        xrr.calc_xrr()
        xrr.plot()
        multi_xrr.append(xrr)
    return multi_xrr


def locate_spot(image: np.ndarray) -> tuple:
    """
    Locate the bright and dark images of the sample.

    Parameters
    ----------
    image : np.ndarray
        Numpy array of the sample image.

    Returns
    -------
    tuple
        Tuple of the bright and dark image arrays.
    """
    HEIGHT = 4  # hard coded dimensions of the spot on the image

    # Get the indices of the maximum and minimum values in the image
    max_idx = np.unravel_index(image.argmax(), image.shape)
    _min = np.array(max_idx) - HEIGHT
    _max = np.array(max_idx) + HEIGHT

    correction = np.zeros(2, dtype=np.int64)
    if np.any(_min < 0):
        loc = np.where(_min < 0)
        correction[loc] = -1 * _min[loc]
    if np.any(_max > image.shape[0]):
        loc = np.where(_max > image.shape[0])
        correction[loc] = image.shape[0] - _max[loc] - 1
    else:
        pass
    new_idx = tuple(map(lambda x, y: np.int64(x + y), max_idx, correction))
    assert is_valid_index(image, new_idx)

    roi = (
        slice(new_idx[0] - HEIGHT, new_idx[0] + HEIGHT + 1),
        slice(new_idx[1] - HEIGHT, new_idx[1] + HEIGHT + 1),
    )

    # Define the regions of interest for the bright and dark spots
    # need to check if spot is within HEIGHT of the edges.
    # If it is, move increase/decrease

    # Extract the bright and dark spots from the image using the ROIs
    u_light = image[roi]
    u_dark = np.flip(image)[roi]
    # if np.any(correction) != 0:
    #     raise Exception("We found the image where the beam runs off!")

    return u_light, u_dark


if __name__ == "__main__":
    # multi_loader()
    dir = file_dialog()
    xrr1 = XRR(dir)
    xrr1.calc_xrr()
    xrr1.plot()
