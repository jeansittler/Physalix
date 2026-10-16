"""Tests ciblés des données et échéances cinétiques."""

import unittest

from physalix.spectrophotometry import (
    MeasurementKind,
    SpectroCalibration,
    SpectroMeasurement,
    calculate_absorbance,
)
from physalix.spectrophotometry_kinetics import (
    KineticExperiment,
    estimated_measurement_seconds,
)
from physalix.spectrophotometry_protocol import (
    AS7341Gain,
    SpectroConfig,
    SpectroData,
    SpectroIllumination,
)


def make_measurement(kind, values, request_id, *, flags=0, timestamp_ms=1234):
    config = SpectroConfig(1, 100, 999, AS7341Gain.GAIN_8X, 255)
    illumination = (
        SpectroIllumination.LED_OFF
        if kind is MeasurementKind.DARK
        else SpectroIllumination.LED_ON
    )
    values = values if isinstance(values, tuple) else (values,) * 8
    return SpectroMeasurement(
        kind,
        SpectroData(
            request_id,
            1,
            illumination,
            values,
            123,
            45,
            flags,
            timestamp_ms,
        ),
        config,
        "session",
    )


def make_calibration():
    return SpectroCalibration(
        "reference",
        make_measurement(MeasurementKind.DARK, 0, 1),
        make_measurement(MeasurementKind.WHITE, 100, 2),
    )


def make_spectrum(values=10, *, flags=0, timestamp_ms=4321):
    calibration = make_calibration()
    sample = make_measurement(
        MeasurementKind.SAMPLE,
        values,
        3,
        flags=flags,
        timestamp_ms=timestamp_ms,
    )
    return calculate_absorbance(sample, calibration)


class KineticExperimentTests(unittest.TestCase):
    def test_current_settings_fit_five_second_interval(self):
        config = SpectroConfig(1, 100, 999, AS7341Gain.GAIN_8X, 255)
        self.assertAlmostEqual(estimated_measurement_seconds(config), 0.56156)
        self.assertLess(estimated_measurement_seconds(config), 5)

    def test_real_completion_time_and_full_spectrum_are_preserved(self):
        spectrum = make_spectrum(timestamp_ms=9876)
        experiment = KineticExperiment("exp", spectrum.calibration, 10.0, 60, 5)

        self.assertIsNone(experiment.add_spectrum(spectrum, 10.0))
        point = experiment.add_spectrum(spectrum, 10.625)

        self.assertEqual(point.sequence, 1)
        self.assertEqual(point.elapsed_seconds, 0.625)
        self.assertIs(point.spectrum, spectrum)
        self.assertEqual(point.arduino_timestamp_ms, 9876)
        self.assertEqual(point.spectrum.measurement.data.bands, (10,) * 8)
        self.assertEqual(point.spectrum.measurement.data.clear, 123)
        self.assertEqual(point.spectrum.measurement.data.nir, 45)

    def test_late_deadlines_are_skipped_without_cumulative_drift(self):
        spectrum = make_spectrum()
        experiment = KineticExperiment("exp", spectrum.calibration, 100.0, 900, 5)

        self.assertEqual(experiment.next_due_monotonic(100.6), 105.0)
        self.assertEqual(experiment.next_due_monotonic(112.2), 115.0)
        self.assertEqual(experiment.next_due_monotonic(119.99), 120.0)

    def test_invalid_band_keeps_a_gap_and_is_excluded_from_transfer(self):
        valid = make_spectrum()
        invalid = make_spectrum(flags=1 << 6)
        experiment = KineticExperiment("exp", valid.calibration, 10.0, 60, 5)
        experiment.add_spectrum(valid, 11.0)
        # Les calibrations ont le même identifiant scientifique.
        experiment.add_spectrum(invalid, 16.0)

        self.assertEqual(experiment.band_values(6), ((1.0, 1.0), (6.0, None)))
        self.assertEqual(experiment.valid_band_values(6), ((1.0, 1.0),))

    def test_completion_after_duration_is_not_recorded(self):
        spectrum = make_spectrum()
        experiment = KineticExperiment("exp", spectrum.calibration, 10.0, 60, 5)

        self.assertIsNone(experiment.add_spectrum(spectrum, 70.001))
        self.assertEqual(experiment.points, [])


if __name__ == "__main__":
    unittest.main()
