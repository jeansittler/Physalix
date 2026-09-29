"""Calibration, détection et session de numérisation sans interface."""

import unittest

import numpy as np

from physalix.graph_digitization import (
    AxisCalibration, CalibrationError, CalibrationMark, DigitizationSession,
    calibration_decimal_places, detect_colored_markers, format_digitized_value,
)


class CalibrationTests(unittest.TestCase):
    def test_display_precision_uses_calibration_decimals_plus_one_guard_digit(self):
        self.assertEqual(calibration_decimal_places(["0", "30"]), 1)
        self.assertEqual(format_digitized_value(1.30385842036, 1), "1.3")
        self.assertEqual(calibration_decimal_places(["0,00", "30.00"]), 3)
        self.assertEqual(format_digitized_value(1.30385842036, 3), "1.304")
        self.assertEqual(format_digitized_value(-0.00001, 1), "0")

    def test_axis_aligned_conversion(self):
        calibration = AxisCalibration(
            [CalibrationMark((10, 100), 0), CalibrationMark((110, 100), 10)],
            [CalibrationMark((10, 100), 0), CalibrationMark((10, 0), 20)],
        )
        origin = calibration.convert((10, 100))
        self.assertAlmostEqual(origin[0], 0)
        self.assertAlmostEqual(origin[1], 0)
        x, y = calibration.convert((60, 50))
        self.assertAlmostEqual(x, 5)
        self.assertAlmostEqual(y, 10)

    def test_oblique_axes_recover_affine_coordinates(self):
        def expected(point):
            u, v = point
            return 2 * u + .5 * v - 3, -.25 * u + 1.5 * v + 4

        x_pixels = [(5, 7), (65, 17)]  # déplacement (60, 10), y constant
        y_pixels = [(5, 7), (20, -53)]  # déplacement (15, -60), x constant
        calibration = AxisCalibration(
            [CalibrationMark(pixel, expected(pixel)[0]) for pixel in x_pixels],
            [CalibrationMark(pixel, expected(pixel)[1]) for pixel in y_pixels],
        )
        for pixel in ((0, 0), (22, 31), (100, -8)):
            converted = calibration.convert(pixel)
            wanted = expected(pixel)
            self.assertAlmostEqual(converted[0], wanted[0])
            self.assertAlmostEqual(converted[1], wanted[1])

    def test_parallel_calibration_directions_are_rejected(self):
        with self.assertRaises(CalibrationError):
            AxisCalibration(
                [CalibrationMark((0, 0), 0), CalibrationMark((10, 0), 1)],
                [CalibrationMark((0, 5), 0), CalibrationMark((10, 5), 1)],
            )


class DetectionTests(unittest.TestCase):
    @staticmethod
    def draw_cross(image, point, color=(220, 45, 35), radius=5, thickness=1):
        x, y = point
        image[y - radius:y + radius + 1, x - thickness:x + thickness + 1] = color
        image[y - thickness:y + thickness + 1, x - radius:x + radius + 1] = color

    @staticmethod
    def draw_disk(image, point, radius, color=(220, 45, 35)):
        x, y = point
        rows, columns = np.ogrid[:image.shape[0], :image.shape[1]]
        image[(columns - x) ** 2 + (rows - y) ** 2 <= radius ** 2] = color

    def test_colored_crosses_are_found_among_gray_grid_lines(self):
        image = np.full((120, 160, 3), 245, dtype=np.uint8)
        image[::20, :, :] = 185
        image[:, ::20, :] = 185
        expected = [(31, 29), (74, 61), (128, 92)]
        for x, y in expected:
            self.draw_cross(image, (x, y))
        found = detect_colored_markers(
            image, (5, 5, 150, 110), (220, 45, 35), tolerance=30,
            sample_point=expected[1],
        )
        self.assertEqual(len(found), len(expected))
        for actual, wanted in zip(found, expected):
            self.assertLess(np.linalg.norm(np.asarray(actual) - wanted), 1)

    def test_gray_sample_is_rejected_instead_of_selecting_grid_and_text(self):
        image = np.full((20, 20, 3), 220, dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, "trop proche du gris"):
            detect_colored_markers(image, (0, 0, 20, 20), (35, 35, 35))

    def test_candidates_outside_user_rectangle_are_rejected(self):
        image = np.full((180, 180, 3), 245, dtype=np.uint8)
        expected = [(40, 140), (90, 90), (140, 40), (90, 143)]
        outside = [(90, 160), (18, 90), (160, 90), (90, 18)]
        for point in expected + outside:
            self.draw_cross(image, point)
        calibration = AxisCalibration(
            [CalibrationMark((40, 140), 0), CalibrationMark((140, 140), 10)],
            [CalibrationMark((40, 140), 0), CalibrationMark((40, 40), 10)],
        )
        found = detect_colored_markers(
            image, (30, 30, 120, 120), (220, 45, 35), tolerance=30,
            sample_point=(90, 90), calibration=calibration,
        )
        self.assertEqual(len(found), len(expected))
        for wanted in expected:
            self.assertTrue(any(np.linalg.norm(np.asarray(actual) - wanted) < 1 for actual in found))

    def test_oblique_calibration_does_not_limit_detection_to_its_intervals(self):
        image = np.full((200, 200, 3), 245, dtype=np.uint8)
        origin = np.asarray((35.0, 155.0))
        x_vector = np.asarray((115.0, 12.0))
        y_vector = np.asarray((18.0, -115.0))

        def pixel(x, y):
            return tuple(np.rint(origin + x * x_vector + y * y_vector).astype(int))

        inside = [pixel(0, 0), pixel(.5, .5), pixel(1, 1)]
        extrapolated = [pixel(.5, -.18), pixel(-.18, .5), pixel(1.18, .5)]
        for point in inside + extrapolated:
            self.draw_cross(image, point)
        calibration = AxisCalibration(
            [CalibrationMark(pixel(0, 0), 0), CalibrationMark(pixel(1, 0), 10)],
            [CalibrationMark(pixel(0, 0), 0), CalibrationMark(pixel(0, 1), 10)],
        )
        found = detect_colored_markers(
            image, (0, 0, 200, 200), (220, 45, 35), tolerance=30,
            sample_point=inside[1], calibration=calibration,
        )
        self.assertEqual(len(found), len(inside + extrapolated))
        for wanted in inside + extrapolated:
            self.assertTrue(any(np.linalg.norm(np.asarray(actual) - wanted) < 1 for actual in found))

    def test_markers_beyond_x_and_y_calibration_values_are_accepted(self):
        image = np.full((220, 260, 3), 245, dtype=np.uint8)
        reference = (100, 100)
        beyond_x = (210, 100)  # X = 19 avec une calibration de 0 à 16.
        beyond_y = (100, 30)  # Y = 275 avec une calibration de 50 à 230.
        expected = [reference, beyond_x, beyond_y]
        for point in expected:
            self.draw_cross(image, point)
        calibration = AxisCalibration(
            [CalibrationMark((20, 180), 0), CalibrationMark((180, 180), 16)],
            [CalibrationMark((20, 180), 50), CalibrationMark((20, 60), 230)],
        )
        found = detect_colored_markers(
            image, (10, 10, 230, 190), (220, 45, 35), tolerance=30,
            sample_point=reference, calibration=calibration,
        )
        self.assertEqual(len(found), len(expected))
        for wanted in expected:
            self.assertTrue(any(np.linalg.norm(np.asarray(actual) - wanted) < 1 for actual in found))
        self.assertAlmostEqual(calibration.convert(beyond_x)[0], 19)
        self.assertAlmostEqual(calibration.convert(beyond_y)[1], 275)
        without_calibration = detect_colored_markers(
            image, (10, 10, 230, 190), (220, 45, 35), tolerance=30,
            sample_point=reference,
        )
        self.assertEqual(found, without_calibration)

    def test_text_like_color_fragments_are_rejected_by_reference_shape(self):
        image = np.full((140, 180, 3), 245, dtype=np.uint8)
        markers = [(45, 100), (90, 75), (135, 50)]
        for point in markers:
            self.draw_cross(image, point)
        # Fragments minces qui franchissaient les anciens seuils aire/aspect.
        image[62:69, 62:64] = (220, 45, 35)
        image[82:92, 118:121] = (220, 45, 35)
        calibration = AxisCalibration(
            [CalibrationMark((30, 115), 0), CalibrationMark((150, 115), 12)],
            [CalibrationMark((30, 115), 0), CalibrationMark((30, 35), 8)],
        )
        found = detect_colored_markers(
            image, (10, 20, 160, 110), (220, 45, 35), tolerance=30,
            sample_point=markers[1], calibration=calibration,
        )
        self.assertEqual(len(found), len(markers))

    def test_progressive_marker_sizes_are_preserved(self):
        image = np.full((160, 240, 3), 245, dtype=np.uint8)
        expected = [(25, 130), (60, 112), (95, 94), (130, 76), (165, 58), (205, 40)]
        for point, radius in zip(expected, (3, 4, 4, 5, 6, 7)):
            self.draw_disk(image, point, radius)
        calibration = AxisCalibration(
            [CalibrationMark((10, 145), 0), CalibrationMark((225, 145), 21.5)],
            [CalibrationMark((10, 145), 0), CalibrationMark((10, 20), 12.5)],
        )
        found = detect_colored_markers(
            image, (0, 0, 240, 160), (220, 45, 35), tolerance=30,
            sample_point=expected[2], calibration=calibration,
        )
        self.assertEqual(len(found), len(expected))

    def test_connected_clusters_of_two_three_and_five_markers_are_split(self):
        image = np.full((240, 360, 3), 245, dtype=np.uint8)
        isolated = [(25 + 25 * index, 210 - index % 3 * 18) for index in range(10)]
        clusters = [
            [(250, 150), (259, 150)],
            [(250, 110), (259, 110), (268, 110)],
            [(240, 60), (249, 60), (258, 60), (267, 60), (276, 60)],
        ]
        expected = isolated + [point for cluster in clusters for point in cluster]
        for point in expected:
            self.draw_disk(image, point, 5)
        calibration = AxisCalibration(
            [CalibrationMark((10, 225), 0), CalibrationMark((340, 225), 33)],
            [CalibrationMark((10, 225), 0), CalibrationMark((10, 20), 20.5)],
        )
        found = detect_colored_markers(
            image, (0, 0, 360, 240), (220, 45, 35), tolerance=30,
            sample_point=isolated[3], calibration=calibration,
        )
        self.assertEqual(len(found), len(expected))
        for wanted in expected:
            self.assertTrue(any(np.linalg.norm(np.asarray(actual) - wanted) < 3 for actual in found))

    def test_large_colored_text_like_bar_is_not_split_into_points(self):
        image = np.full((140, 240, 3), 245, dtype=np.uint8)
        markers = [(30, 100), (60, 80), (90, 60), (120, 45)]
        for point in markers:
            self.draw_disk(image, point, 5)
        image[85:92, 145:225] = (220, 45, 35)
        calibration = AxisCalibration(
            [CalibrationMark((10, 120), 0), CalibrationMark((230, 120), 22)],
            [CalibrationMark((10, 120), 0), CalibrationMark((10, 20), 10)],
        )
        found = detect_colored_markers(
            image, (0, 0, 240, 140), (220, 45, 35), tolerance=30,
            sample_point=markers[1], calibration=calibration,
        )
        self.assertEqual(len(found), len(markers))


class SessionTests(unittest.TestCase):
    def calibrated_session(self):
        session = DigitizationSession()
        session.set_roi((0, 0, 120, 120))
        session.set_axis_marks("x", [((10, 100), 0), ((110, 100), 10)])
        session.set_axis_marks("y", [((10, 100), 0), ((10, 0), 20)])
        return session

    def test_add_move_validate_remove_and_sorted_conversion(self):
        session = self.calibrated_session()
        second = session.add_point((80, 50))
        first = session.add_point((30, 75), validated=False, automatic=True)
        session.set_validated(first.identifier, True)
        session.move_point(second.identifier, (70, 50))
        converted = session.converted_points()
        self.assertEqual([point.identifier for values, point in converted],
                         [first.identifier, second.identifier])
        self.assertAlmostEqual(converted[0][0][0], 2)
        self.assertAlmostEqual(converted[1][0][0], 6)
        self.assertTrue(session.remove_point(first.identifier))
        self.assertFalse(session.remove_point(999))
        self.assertEqual(len(session.points), 1)

    def test_candidates_are_not_validated_by_default(self):
        session = self.calibrated_session()
        session.add_candidates([(20, 80), (40, 60)])
        self.assertFalse(any(point.validated for point in session.points))
        self.assertFalse(any(point.rejected for point in session.points))
        self.assertEqual(session.converted_points(), [])


if __name__ == "__main__":
    unittest.main()
