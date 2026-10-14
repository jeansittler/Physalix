"""Tests ciblés du calcul Beer-Lambert indépendant de Qt."""

import math
import unittest

from physalix.spectrophotometry_beer_lambert import (
    CONCENTRATION_UNITS,
    BeerLambertError,
    BeerLambertStandard,
    calculate_unknown_concentration,
    fit_beer_lambert,
    format_absorbance,
    format_concentration,
    parse_concentration,
)


class ConcentrationTests(unittest.TestCase):
    def test_units_are_exact_and_ordered(self):
        self.assertEqual(CONCENTRATION_UNITS, ("mol/L", "mmol/L", "g/L", "mg/L"))

    def test_french_decimal_separator_and_zero_are_accepted(self):
        self.assertEqual(parse_concentration("0"), 0.0)
        self.assertEqual(parse_concentration(" 1,25 "), 1.25)
        self.assertEqual(parse_concentration("1\u00a0234,5"), 1234.5)

    def test_negative_non_finite_and_invalid_values_are_rejected(self):
        for text in ("-0,1", "nan", "inf", "-inf", "abc", ""):
            with self.subTest(text=text), self.assertRaises(BeerLambertError):
                parse_concentration(text)

    def test_standard_preserves_name_concentration_and_spectrum_slot(self):
        standard = BeerLambertStandard("id-1", "  S1  ", 0.0)
        self.assertEqual(standard.name, "S1")
        self.assertEqual(standard.concentration, 0.0)
        self.assertIsNone(standard.spectrum)

    def test_scientific_display_uses_french_comma_without_changing_value(self):
        concentration = 6.0e-5
        self.assertEqual(format_concentration(concentration), "6,0 × 10⁻⁵")
        self.assertEqual(format_concentration(0.01234), "0,01234")
        self.assertEqual(format_absorbance(0.14494), "0,1449")
        self.assertEqual(concentration, 6.0e-5)


class RegressionTests(unittest.TestCase):
    def test_least_squares_is_constrained_to_origin(self):
        result = fit_beer_lambert(((0.0, 0.2), (1.0, 2.2), (2.0, 4.2)))
        self.assertAlmostEqual(result.slope, 10.6 / 5.0)
        self.assertEqual(result.intercept, 0.0)
        self.assertLess(result.r_squared, 1.0)
        self.assertEqual((result.concentration_min, result.concentration_max), (0, 2))

    def test_two_points_are_valid_but_identified(self):
        result = fit_beer_lambert(((0.0, 0.1), (2.0, 1.1)))
        self.assertTrue(result.two_point_only)
        self.assertLess(result.r_squared, 1.0)

    def test_non_perfect_regression_has_expected_r_squared(self):
        result = fit_beer_lambert(((0, 0.1), (1, 1.2), (2, 1.9), (3, 3.3)))
        self.assertGreater(result.r_squared, 0.97)
        self.assertLess(result.r_squared, 1.0)

    def test_too_few_or_identical_concentrations_are_rejected(self):
        for points in (((1, 2),), ((1, 2), (1, 3))):
            with self.subTest(points=points), self.assertRaises(BeerLambertError):
                fit_beer_lambert(points)

    def test_zero_or_numerically_tiny_slope_is_rejected(self):
        for points in (
            ((0, 1), (1, 1), (2, 1)),
            ((0, 0), (1, 1e-15), (2, 2e-15)),
        ):
            with self.subTest(points=points), self.assertRaises(BeerLambertError):
                fit_beer_lambert(points)

    def test_non_finite_points_are_rejected(self):
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(value=bad), self.assertRaises(BeerLambertError):
                fit_beer_lambert(((0, 0), (1, bad)))

    def test_unknown_concentration_and_extrapolation(self):
        regression = fit_beer_lambert(((0, 0), (1, 2), (2, 4)))
        inside = calculate_unknown_concentration(2, regression)
        outside = calculate_unknown_concentration(6, regression)
        self.assertAlmostEqual(inside.concentration, 1.0)
        self.assertFalse(inside.extrapolated)
        self.assertAlmostEqual(outside.concentration, 3.0)
        self.assertTrue(outside.extrapolated)

    def test_negative_unknown_is_rejected_as_non_physical(self):
        regression = fit_beer_lambert(((0, 0), (1, 2)))
        with self.assertRaises(BeerLambertError):
            calculate_unknown_concentration(-0.1, regression)


if __name__ == "__main__":
    unittest.main()
