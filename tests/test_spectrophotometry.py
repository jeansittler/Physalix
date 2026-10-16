"""Tests ciblés du moteur scientifique de spectrophotométrie."""

import math
import unittest

from physalix.spectrophotometry import (
    VISIBLE_WAVELENGTHS_NM,
    AbsorbanceSpectrum,
    BandInvalidity,
    CalibrationCompatibilityError,
    MeasurementKind,
    SpectroCalibration,
    SpectroMeasurement,
    SpectroSeries,
    calculate_absorbance,
)
from physalix.spectrophotometry_protocol import (
    AS7341Gain,
    SpectroConfig,
    SpectroData,
    SpectroIllumination,
)


def config(
    config_id=1,
    *,
    atime=100,
    astep=999,
    gain=AS7341Gain.GAIN_8X,
    led_pwm=255,
):
    return SpectroConfig(config_id, atime, astep, gain, led_pwm)


def measurement(
    kind,
    value,
    *,
    request_id=1,
    applied_config=None,
    session_id="session-a",
    saturation_flags=0,
    clear=1234,
    nir=567,
    timestamp_ms=1000,
):
    applied_config = applied_config or config()
    values = value if isinstance(value, tuple) else (value,) * 8
    illumination = (
        SpectroIllumination.LED_OFF
        if kind is MeasurementKind.DARK
        else SpectroIllumination.LED_ON
    )
    data = SpectroData(
        request_id=request_id,
        config_id=applied_config.config_id,
        illumination=illumination,
        bands=values,
        clear=clear,
        nir=nir,
        saturation_flags=saturation_flags,
        timestamp_ms=timestamp_ms,
    )
    return SpectroMeasurement(kind, data, applied_config, session_id)


def calibration(*, dark=0, white=100, dark_flags=0, white_flags=0):
    return SpectroCalibration(
        "calibration-1",
        measurement(
            MeasurementKind.DARK,
            dark,
            request_id=10,
            saturation_flags=dark_flags,
        ),
        measurement(
            MeasurementKind.WHITE,
            white,
            request_id=11,
            saturation_flags=white_flags,
        ),
    )


class AbsorbanceCalculationTests(unittest.TestCase):
    def test_dark_zero_white_100_sample_10_gives_absorbance_one(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 10), calibration()
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.wavelengths_nm, VISIBLE_WAVELENGTHS_NM)
        self.assertEqual(result.absorbances, (1.0,) * 8)
        self.assertEqual(tuple(b.transmission for b in result.bands), (0.1,) * 8)

    def test_sample_equal_to_white_gives_valid_zero(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 100), calibration()
        )

        self.assertEqual(result.absorbances, (0.0,) * 8)
        self.assertTrue(all(band.is_valid for band in result.bands))

    def test_sample_above_white_keeps_negative_absorbance(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 200), calibration()
        )

        expected = -math.log10(2.0)
        self.assertTrue(all(value == expected for value in result.absorbances))
        self.assertTrue(result.is_valid)

    def test_white_equal_to_dark_invalidates_only_the_affected_band(self):
        dark = (5, 0, 0, 0, 0, 0, 0, 0)
        white = (5, 100, 100, 100, 100, 100, 100, 100)
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 10),
            calibration(dark=dark, white=white),
        )

        self.assertEqual(result.bands[0].absorbance, None)
        self.assertEqual(
            result.bands[0].invalidities,
            (BandInvalidity.REFERENCE_NOT_ABOVE_DARK,),
        )
        self.assertTrue(all(band.is_valid for band in result.bands[1:]))

    def test_sample_corrected_intensity_zero_is_not_infinity(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 5), calibration(dark=5, white=100)
        )

        self.assertTrue(all(band.absorbance is None for band in result.bands))
        self.assertTrue(
            all(
                BandInvalidity.SAMPLE_NOT_ABOVE_DARK in band.invalidities
                for band in result.bands
            )
        )

    def test_sample_corrected_intensity_negative_is_invalid(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 4), calibration(dark=5, white=100)
        )

        self.assertEqual(result.absorbances, (None,) * 8)
        self.assertTrue(
            all(
                band.invalidities == (BandInvalidity.SAMPLE_NOT_ABOVE_DARK,)
                for band in result.bands
            )
        )

    def test_white_below_dark_is_invalid(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 20),
            calibration(dark=10, white=9),
        )

        self.assertEqual(result.absorbances, (None,) * 8)
        self.assertTrue(
            all(
                band.invalidities == (BandInvalidity.REFERENCE_NOT_ABOVE_DARK,)
                for band in result.bands
            )
        )

    def test_single_spectral_saturation_invalidates_only_that_band(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 10, saturation_flags=1 << 3),
            calibration(),
        )

        self.assertEqual(
            result.bands[3].invalidities, (BandInvalidity.SAMPLE_SATURATED,)
        )
        self.assertIsNone(result.bands[3].absorbance)
        self.assertTrue(all(band.is_valid for band in result.bands[:3]))
        self.assertTrue(all(band.is_valid for band in result.bands[4:]))

    def test_dark_and_white_saturations_have_distinct_reasons(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 10),
            calibration(dark_flags=1 << 1, white_flags=1 << 2),
        )

        self.assertIn(BandInvalidity.DARK_SATURATED, result.bands[1].invalidities)
        self.assertIn(BandInvalidity.WHITE_SATURATED, result.bands[2].invalidities)

    def test_clear_and_nir_saturation_do_not_invalidate_visible_bands(self):
        result = calculate_absorbance(
            measurement(
                MeasurementKind.SAMPLE,
                10,
                saturation_flags=(1 << 8) | (1 << 9),
            ),
            calibration(white_flags=1 << 8),
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.absorbances, (1.0,) * 8)

    def test_missing_calibration_produces_no_artificial_values(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 10), None
        )

        self.assertIsNone(result.calibration_reference_id)
        self.assertEqual(result.absorbances, (None,) * 8)
        self.assertTrue(
            all(
                band.invalidities == (BandInvalidity.MISSING_CALIBRATION,)
                for band in result.bands
            )
        )


class CompatibilityTests(unittest.TestCase):
    def test_changed_acquisition_parameter_invalidates_sample(self):
        for changed_config in (
            config(2, atime=101),
            config(2, astep=1000),
            config(2, gain=AS7341Gain.GAIN_16X),
            config(2, led_pwm=254),
        ):
            with self.subTest(config=changed_config):
                result = calculate_absorbance(
                    measurement(
                        MeasurementKind.SAMPLE,
                        10,
                        applied_config=changed_config,
                    ),
                    calibration(),
                )
                self.assertTrue(
                    all(
                        BandInvalidity.ACQUISITION_PARAMETERS_MISMATCH
                        in band.invalidities
                        for band in result.bands
                    )
                )
                self.assertEqual(result.absorbances, (None,) * 8)

    def test_config_id_alone_is_not_a_physical_incompatibility(self):
        result = calculate_absorbance(
            measurement(
                MeasurementKind.SAMPLE,
                10,
                applied_config=config(config_id=99),
            ),
            calibration(),
        )

        self.assertTrue(result.is_valid)

    def test_different_hardware_session_invalidates_sample(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 10, session_id="session-b"),
            calibration(),
        )

        self.assertTrue(
            all(
                band.invalidities == (BandInvalidity.SESSION_MISMATCH,)
                for band in result.bands
            )
        )

    def test_calibration_rejects_references_from_different_sessions(self):
        with self.assertRaises(CalibrationCompatibilityError):
            SpectroCalibration(
                "bad",
                measurement(MeasurementKind.DARK, 0, session_id="session-a"),
                measurement(MeasurementKind.WHITE, 100, session_id="session-b"),
            )

    def test_calibration_rejects_incompatible_reference_parameters(self):
        with self.assertRaises(CalibrationCompatibilityError):
            SpectroCalibration(
                "bad",
                measurement(MeasurementKind.DARK, 0),
                measurement(
                    MeasurementKind.WHITE,
                    100,
                    applied_config=config(2, gain=AS7341Gain.GAIN_16X),
                ),
            )


class ProvenanceAndSeriesTests(unittest.TestCase):
    def test_raw_values_metadata_and_calibration_are_preserved(self):
        raw = (11, 12, 13, 14, 15, 16, 17, 18)
        sample = measurement(
            MeasurementKind.SAMPLE,
            raw,
            request_id=42,
            clear=65535,
            nir=2429,
            saturation_flags=1 << 8,
            timestamp_ms=123456,
        )
        reference = calibration()

        result = calculate_absorbance(sample, reference)

        self.assertIs(result.measurement, sample)
        self.assertIs(result.calibration, reference)
        self.assertEqual(result.calibration_reference_id, "calibration-1")
        self.assertEqual(result.measurement.bands, raw)
        self.assertEqual(result.measurement.clear, 65535)
        self.assertEqual(result.measurement.nir, 2429)
        self.assertEqual(result.measurement.data.timestamp_ms, 123456)
        self.assertEqual(result.measurement.applied_config, config())
        self.assertEqual(result.measurement.session_id, "session-a")

    def test_series_keeps_multiple_spectra_and_original_provenance(self):
        first_reference = calibration()
        first_sample = measurement(MeasurementKind.SAMPLE, 10, request_id=20)
        second_sample = measurement(MeasurementKind.SAMPLE, 20, request_id=21)

        empty_series = SpectroSeries(first_reference)
        one_spectrum = empty_series.add_measurement(first_sample)
        two_spectra = one_spectrum.add_measurement(second_sample)

        self.assertEqual(empty_series.spectra, ())
        self.assertEqual(len(two_spectra.spectra), 2)
        self.assertIs(two_spectra.spectra[0].measurement, first_sample)
        self.assertIs(two_spectra.spectra[1].measurement, second_sample)
        self.assertTrue(
            all(item.calibration is first_reference for item in two_spectra.spectra)
        )

    def test_new_calibration_does_not_recalculate_existing_spectrum(self):
        original = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 10), calibration(white=100)
        )
        replacement = calibration(white=200)

        self.assertEqual(original.absorbances, (1.0,) * 8)
        self.assertIsNot(original.calibration, replacement)
        self.assertEqual(original.calibration.white.bands, (100,) * 8)

    def test_result_contains_exactly_eight_band_results(self):
        result = calculate_absorbance(
            measurement(MeasurementKind.SAMPLE, 10), calibration()
        )

        self.assertIsInstance(result, AbsorbanceSpectrum)
        self.assertEqual(len(result.bands), 8)


class MeasurementValidationTests(unittest.TestCase):
    def test_measurement_requires_matching_config_id(self):
        raw = SpectroData(
            request_id=1,
            config_id=2,
            illumination=SpectroIllumination.LED_ON,
            bands=(1,) * 8,
            clear=1,
            nir=1,
            saturation_flags=0,
            timestamp_ms=1,
        )

        with self.assertRaises(ValueError):
            SpectroMeasurement(
                MeasurementKind.SAMPLE, raw, config(config_id=1), "session-a"
            )

    def test_measurement_requires_illumination_matching_its_role(self):
        raw = SpectroData(
            request_id=1,
            config_id=1,
            illumination=SpectroIllumination.LED_OFF,
            bands=(1,) * 8,
            clear=1,
            nir=1,
            saturation_flags=0,
            timestamp_ms=1,
        )

        with self.assertRaises(ValueError):
            SpectroMeasurement(
                MeasurementKind.SAMPLE, raw, config(), "session-a"
            )


if __name__ == "__main__":
    unittest.main()
