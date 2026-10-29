import tempfile
import unittest
from pathlib import Path

import numpy as np
from astropy.io import fits

from astrodatareduc_ohp_october_2026.Stack_images import stack_images
from astrodatareduc_ohp_october_2026.Utils.Utils import (
    image_group_key,
    write_fits_image,
)


class PipelineTests(unittest.TestCase):
    def test_group_key_normalizes_filter_and_object(self):
        header = fits.Header(
            {
                "OBJECT": "M1 / R Cousins / 60 s",
                "FLTRNM": " R Cousins ",
                "TM-EXPOS": 60.0,
            }
        )
        self.assertEqual(image_group_key(header), ("M1", "R", 60.0))

    def test_stack_creates_one_output_per_scientific_group(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            header = fits.Header(
                {
                    "OBJECT": "M1 / R Cousins / 1 s",
                    "FLTRNM": " R Cousins ",
                    "TM-EXPOS": 1.0,
                }
            )
            for index in range(2):
                write_fits_image(
                    directory / f"r{index}_R_reduced_aligned.fits",
                    np.full((4, 4), index, dtype=np.float64),
                    header,
                )
            other_header = header.copy()
            other_header["FLTRNM"] = " V Cousins "
            write_fits_image(
                directory / "v_V_reduced_aligned.fits",
                np.ones((4, 4)),
                other_header,
            )

            outputs = stack_images(directory)

            self.assertEqual(len(outputs), 2)
            self.assertTrue(any("_R_" in output.name for output in outputs))
            self.assertTrue(any("_V_" in output.name for output in outputs))


if __name__ == "__main__":
    unittest.main()
