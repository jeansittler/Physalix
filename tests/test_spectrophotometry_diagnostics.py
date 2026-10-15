"""Tests ciblés du journal diagnostic des cinétiques Spectro."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from physalix.spectrophotometry import (
    MeasurementKind,
    SpectroCalibration,
    SpectroMeasurement,
    calculate_absorbance,
)
from physalix.spectrophotometry_diagnostics import KineticDiagnosticJournal
from physalix.spectrophotometry_kinetics import KineticExperiment
from physalix.spectrophotometry_protocol import (
    AS7341Gain,
    SpectroConfig,
    SpectroData,
    SpectroFirmwareInfo,
    SpectroIllumination,
    SpectroSensorType,
)


def raw_measurement(kind, request_id, values, config, *, flags=0, timestamp=None):
    illumination = (
        SpectroIllumination.LED_OFF
        if kind is MeasurementKind.DARK
        else SpectroIllumination.LED_ON
    )
    return SpectroMeasurement(
        kind,
        SpectroData(
            request_id,
            config.config_id,
            illumination,
            tuple(values),
            12345 + request_id,
            2345 + request_id,
            flags,
            timestamp if timestamp is not None else request_id * 100,
        ),
        config,
        "session-test",
    )


class KineticDiagnosticJournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temporary.name)
        self.config = SpectroConfig(7, 100, 999, AS7341Gain.GAIN_8X, 255)
        self.dark = raw_measurement(
            MeasurementKind.DARK, 1, (10,) * 8, self.config, timestamp=111
        )
        self.white = raw_measurement(
            MeasurementKind.WHITE, 2, (1010,) * 8, self.config, timestamp=222
        )
        self.calibration = SpectroCalibration("calibration-test", self.dark, self.white)
        self.experiment = KineticExperiment(
            "experiment-test", self.calibration, 100.0, 900, 5
        )
        self.now = datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc)
        self.journal = KineticDiagnosticJournal(
            self.experiment,
            firmware=SpectroFirmwareInfo(
                (1, 0, 0), SpectroSensorType.AS7341, 0x1F
            ),
            base_directory=self.root,
            wall_clock=lambda: self.now,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def add_point(self, request_id, elapsed, values, *, flags=0):
        measured = raw_measurement(
            MeasurementKind.SAMPLE,
            request_id,
            values,
            self.config,
            flags=flags,
            timestamp=50_000 + request_id,
        )
        spectrum = calculate_absorbance(measured, self.calibration)
        point = self.experiment.add_spectrum(spectrum, 100.0 + elapsed)
        self.assertIsNotNone(point)
        self.journal.record_measurement_command(
            request_id, 100.0 + elapsed - 0.125, sequence=point.sequence
        )
        result = self.journal.record_measurement(
            point, completed_monotonic=100.0 + elapsed
        )
        return point, result

    def events(self):
        return [
            json.loads(line)
            for line in self.journal.events_path.read_text(encoding="utf-8").splitlines()
        ]

    def test_creates_three_files_with_real_configuration_and_calibration(self):
        self.assertEqual(
            {path.name for path in self.journal.directory.iterdir()},
            {"metadata.json", "measurements.csv", "events.jsonl"},
        )
        metadata = json.loads(self.journal.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["configuration"]["atime"], 100)
        self.assertEqual(metadata["configuration"]["astep"], 999)
        self.assertEqual(metadata["configuration"]["gain_name"], "GAIN_8X")
        self.assertEqual(metadata["configuration"]["led_pwm_command"], 255)
        self.assertEqual(metadata["calibration"]["dark"]["bands"], [10] * 8)
        self.assertEqual(metadata["firmware"]["sensor_type"], "AS7341")
        self.assertIn("non disponible", metadata["availability"]["measured_light_power"])
        with self.journal.measurements_path.open(encoding="utf-8") as stream:
            self.assertNotIn("measured_light_power", csv.DictReader(stream).fieldnames)

    def test_records_180_progressive_measurements_with_original_values(self):
        for index in range(180):
            values = tuple(500 + index + band for band in range(8))
            self.add_point(index + 10, 0.5 + index * 5, values)

        with self.journal.measurements_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 180)
        self.assertEqual(rows[0]["raw_f1"], "500")
        self.assertEqual(rows[-1]["raw_f8"], str(500 + 179 + 7))
        self.assertEqual(rows[0]["arduino_timestamp_ms"], "50010")
        self.assertEqual(rows[0]["command_response_latency_seconds"], "0.125")
        self.assertEqual(rows[0]["calibration_id"], "calibration-test")
        self.assertEqual(rows[0]["dark_f1"], "10")
        self.assertEqual(rows[0]["white_f8"], "1010")
        self.assertNotEqual(rows[0]["absorbance_f1"], "")
        metadata = json.loads(self.journal.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["measurement_count"], 180)
        self.assertEqual(metadata["status"], "in_progress")

    def test_validity_saturation_and_invalidity_are_explicit(self):
        _, written = self.add_point(20, 5.0, (500,) * 8, flags=(1 << 2) | (1 << 8))
        self.assertTrue(written)
        with self.journal.measurements_path.open(encoding="utf-8", newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["saturated_f3"], "True")
        self.assertEqual(row["valid_f3"], "False")
        self.assertIn("sample_saturated", row["invalidities_f3"])
        self.assertEqual(row["saturated_clear"], "True")
        self.assertEqual(row["valid_clear"], "False")
        self.assertIn("saturation_detected", [event["type"] for event in self.events()])

    def test_partial_journal_survives_without_finish(self):
        self.add_point(30, 5.0, (450,) * 8)
        with self.journal.measurements_path.open(encoding="utf-8") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 1)
        metadata = json.loads(self.journal.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "in_progress")
        self.assertEqual(metadata["measurement_count"], 1)
        self.assertGreater(self.journal.events_path.stat().st_size, 0)

    def test_normal_and_premature_finish_are_persisted(self):
        self.add_point(40, 5.0, (500,) * 8)
        self.journal.finish("Durée programmée atteinte.", status="completed")
        metadata = json.loads(self.journal.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "completed")
        self.assertEqual(metadata["stop_reason"], "Durée programmée atteinte.")

        second = KineticExperiment("premature", self.calibration, 200.0, 900, 5)
        other = KineticDiagnosticJournal(second, base_directory=self.root)
        other.record_event("communication_error", message="port déconnecté")
        other.finish("Connexion interrompue.", status="interrupted")
        other_metadata = json.loads(other.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(other_metadata["status"], "interrupted")
        self.assertIn("communication_error", [
            json.loads(line)["type"]
            for line in other.events_path.read_text(encoding="utf-8").splitlines()
        ])

    def test_simultaneous_jump_is_logged_without_modifying_points(self):
        first, _ = self.add_point(50, 5.0, (700,) * 8)
        second, _ = self.add_point(51, 10.0, (500,) * 8)
        event = next(
            item
            for item in self.events()
            if item["type"] == "simultaneous_absorbance_discontinuity"
        )
        self.assertEqual(event["sequence"], 2)
        self.assertGreaterEqual(len(event["absorbance_deltas"]), 3)
        self.assertIn("Aucune cause", event["interpretation"])
        self.assertEqual(self.experiment.points, [first, second])

    def test_write_error_does_not_affect_acquired_point(self):
        measured = raw_measurement(
            MeasurementKind.SAMPLE, 60, (500,) * 8, self.config
        )
        point = self.experiment.add_spectrum(
            calculate_absorbance(measured, self.calibration), 105.0
        )
        self.journal.record_measurement_command(60, 104.9, sequence=1)
        with patch("pathlib.Path.open", side_effect=OSError("disque indisponible")):
            written = self.journal.record_measurement(point, completed_monotonic=105.0)
        self.assertFalse(written)
        self.assertEqual(len(self.experiment.points), 1)
        self.assertTrue(self.journal.errors)

    def test_exports_only_the_three_diagnostic_files(self):
        self.add_point(70, 5.0, (500,) * 8)
        self.journal.finish("Arrêt manuel.", status="stopped")
        archive = self.journal.export_zip(self.root / "export-sans-extension")
        self.assertEqual(archive.suffix, ".zip")
        with zipfile.ZipFile(archive) as zipped:
            self.assertEqual(
                set(zipped.namelist()),
                {"metadata.json", "measurements.csv", "events.jsonl"},
            )


if __name__ == "__main__":
    unittest.main()
