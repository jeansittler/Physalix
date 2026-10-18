"""Calculs scientifiques ciblés de l'analyse d'images."""

import unittest

import numpy as np

from physalix.image_analysis import (
    ImageCalibration, IntensityProfile, MeasurementPoint, ProfileMeasurement,
    extract_profile, local_extremum_index, measurement_result,
)


class ImageProfileTests(unittest.TestCase):
    def test_horizontal_vertical_and_oblique_uniform_profiles(self):
        image = np.full((30, 40), 137, dtype=np.uint8)
        for start, end, width in (((2, 5), (32, 5), 1),
                                  ((8, 2), (8, 25), 3),
                                  ((1, 1), (35, 24), 5)):
            with self.subTest(start=start, end=end, width=width):
                samples = extract_profile(image, IntensityProfile("P", start, end, width))
                self.assertTrue(np.allclose(samples.intensity, 137))
                self.assertEqual(samples.axis[0], 0)
                self.assertAlmostEqual(samples.axis[-1], np.hypot(end[0]-start[0], end[1]-start[1]))

    def test_width_average_and_boundary_ignore_outside_pixels(self):
        image = np.tile(np.arange(20, dtype=np.uint8)[:, None], (1, 30))
        middle = extract_profile(image, IntensityProfile("P", (2, 10), (27, 10), 5))
        boundary = extract_profile(np.full((20, 30), 80, dtype=np.uint8),
                                   IntensityProfile("P", (2, 0), (27, 0), 5))
        self.assertTrue(np.allclose(middle.intensity, 10))
        self.assertTrue(np.allclose(boundary.intensity, 80))

    def test_spatial_and_reversed_spectral_calibration(self):
        image = np.zeros((20, 50), dtype=np.uint8)
        profile = IntensityProfile("Spectre", (5, 10), (35, 10))
        spatial = ImageCalibration("distance", "mm", (0, 0), (10, 0), 2)
        distance = extract_profile(image, profile, spatial)
        self.assertAlmostEqual(distance.axis[-1], 6)
        spectral = ImageCalibration("spectral", "nm", (10, 4), (30, 15), 592.136, 590.101)
        wavelengths = extract_profile(image, profile, spectral)
        self.assertGreater(wavelengths.axis[0], wavelengths.axis[-1])
        lambda1 = wavelengths.axis[np.argmin(abs(wavelengths.x - 10))]
        lambda2 = wavelengths.axis[np.argmin(abs(wavelengths.x - 30))]
        self.assertAlmostEqual(lambda1, 592.136, places=6)
        self.assertAlmostEqual(lambda2, 590.101, places=6)
        self.assertAlmostEqual(lambda1 - lambda2, 2.035, places=6)

        relative = ImageCalibration("spectral", "nm", (10, 4), (30, 15), 0, 2.035, False)
        offsets = extract_profile(image, profile, relative)
        self.assertEqual(relative.axis_name, "Δλ")
        at_first = offsets.axis[np.argmin(abs(offsets.x - 10))]
        at_second = offsets.axis[np.argmin(abs(offsets.x - 30))]
        self.assertAlmostEqual(at_second - at_first, 2.035, places=6)

    def test_two_point_spectral_direction_is_independent_from_endpoint_order(self):
        for first_x, second_x, first_value, second_value, expected_sign in (
                (20, 60, 590, 592, 1),
                (20, 60, 592, 590, -1),
                (60, 20, 590, 592, -1),
                (60, 20, 592, 590, 1)):
            with self.subTest(first_x=first_x, second_x=second_x,
                              first_value=first_value, second_value=second_value):
                calibration = ImageCalibration(
                    "spectral", "nm", (first_x, 5), (second_x, 25),
                    first_value, second_value, True, "two_points")
                values = calibration.axis_values([0, 0], [10, 70])
                self.assertEqual(np.sign(values[1] - values[0]), expected_sign)
                self.assertAlmostEqual(
                    calibration.axis_values([0], [first_x])[0], first_value)
                self.assertAlmostEqual(
                    calibration.axis_values([0], [second_x])[0], second_value)

    def test_interfringe_uses_explicit_interval_count(self):
        samples = extract_profile(np.zeros((5, 21), dtype=np.uint8),
                                  IntensityProfile("P", (0, 2), (20, 2)))
        measurement = ProfileMeasurement(
            "interfringe",
            MeasurementPoint("P", 0.1),
            MeasurementPoint("P", 0.7),
            intervals=3,
        )
        first, second, total, average = measurement_result(measurement, {"P": samples})
        self.assertAlmostEqual(first, 2)
        self.assertAlmostEqual(second, 14)
        self.assertAlmostEqual(total, 12)
        self.assertAlmostEqual(average, 4)
        measurement.second = MeasurementPoint("P", 0.1)
        with self.assertRaisesRegex(ValueError, "distinctes"):
            measurement_result(measurement, {"P": samples})

    def test_local_extremum_snapping_stays_near_the_click(self):
        rng = np.random.default_rng(42)
        values = 140 + rng.normal(0, 1.5, 120)
        values[47:54] = (125, 105, 78, 35, 74, 106, 126)
        values[98] = 0  # Minimum global volontairement hors du voisinage du clic.
        self.assertEqual(local_extremum_index(values, 46, "minimum", radius=10), 50)
        maximum = 80 + rng.normal(0, 1.5, 120)
        maximum[57:64] = (90, 115, 160, 220, 158, 116, 92)
        maximum[5] = 255
        self.assertEqual(local_extremum_index(maximum, 65, "maximum", radius=10), 60)

    def test_cross_profile_spectral_measurement_uses_global_image_x(self):
        image = np.zeros((70, 230), dtype=np.uint8)
        calibration = ImageCalibration(
            "spectral", "nm", (50, 8), (150, 28), 0, 2.035, False)
        first = IntensityProfile("P1", (5, 20), (205, 20))
        second = IntensityProfile("P2", (20, 50), (215, 50))
        samples = {
            first.identifier: extract_profile(image, first, calibration),
            second.identifier: extract_profile(image, second, calibration),
        }
        first_index = int(np.argmin(abs(samples[first.identifier].x - 90)))
        second_index = int(np.argmin(abs(samples[second.identifier].x - 94)))
        measurement = ProfileMeasurement(
            "gap",
            MeasurementPoint(first.identifier, first_index / (len(samples[first.identifier].axis) - 1)),
            MeasurementPoint(second.identifier, second_index / (len(samples[second.identifier].axis) - 1)),
        )
        first_value, second_value, total, average = measurement_result(measurement, samples)
        self.assertAlmostEqual(total, 4 * 2.035 / 100, places=6)
        self.assertIsNone(average)
        self.assertAlmostEqual(first_value, samples[first.identifier].axis[first_index])
        self.assertAlmostEqual(second_value, samples[second.identifier].axis[second_index])


if __name__ == "__main__":
    unittest.main()
