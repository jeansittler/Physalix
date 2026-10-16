"""Sauvegarde portable des quatre modes Spectrophotométrie."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from physalix.project import read_project, write_project
from physalix.spectrophotometry import (
    MeasurementKind,
    SpectroCalibration,
    SpectroMeasurement,
    calculate_absorbance,
)
from physalix.spectrophotometry_beer_lambert import BeerLambertStandard
from physalix.spectrophotometry_kinetics import KineticExperiment, KineticPoint
from physalix.spectrophotometry_protocol import (
    AS7341Gain,
    SpectroConfig,
    SpectroData,
    SpectroIllumination,
)
from physalix.spectrophotometry_serial import SpectroControllerState
from physalix.ui.main_window import MainWindow
from physalix.ui.project_state import restore, snapshot


class SpectrophotometryProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.windows = []
        self.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.path = Path(self.directory.name) / "experience-spectro.physalix"

    def tearDown(self):
        for window in self.windows:
            window._discard_on_close = True
            window.close()
        self.app.processEvents()
        self.directory.cleanup()

    def window(self):
        value = MainWindow()
        self.windows.append(value)
        return value

    @staticmethod
    def calibration():
        config = SpectroConfig(17, 100, 999, AS7341Gain.GAIN_8X, 255)

        def measurement(kind, values, request_id, timestamp):
            illumination = (
                SpectroIllumination.LED_OFF
                if kind is MeasurementKind.DARK
                else SpectroIllumination.LED_ON
            )
            data = SpectroData(
                request_id,
                config.config_id,
                illumination,
                tuple(values),
                54321,
                2345,
                0,
                timestamp,
            )
            return SpectroMeasurement(kind, data, config, "session-materielle-1")

        dark = measurement(MeasurementKind.DARK, (0,) * 8, 1, 100)
        white = measurement(MeasurementKind.WHITE, (100,) * 8, 2, 200)
        return SpectroCalibration("reference-historique-1", dark, white)

    @staticmethod
    def spectrum(calibration, values, request_id, timestamp):
        data = SpectroData(
            request_id,
            calibration.applied_config.config_id,
            SpectroIllumination.LED_ON,
            tuple(values),
            50000,
            2000,
            0,
            timestamp,
        )
        measurement = SpectroMeasurement(
            MeasurementKind.SAMPLE,
            data,
            calibration.applied_config,
            calibration.session_id,
        )
        return calculate_absorbance(measurement, calibration)

    def populated_window(self):
        window = self.window()
        tab = window.spectrophotometry_tab
        calibration = self.calibration()
        tab.calibration = calibration
        tab.dark_measurement = calibration.dark
        tab.white_measurement = calibration.white

        spectrum = self.spectrum(
            calibration, (80, 70, 60, 50, 40, 30, 20, 10), 3, 300
        )
        tab.add_spectrum(
            spectrum, name="Permanganate", color="#123456", visible=False
        )
        tab.absorbance_spectrum = spectrum
        tab.absorbance_band_combo.setCurrentIndex(
            tab.absorbance_band_combo.findData(3)
        )

        standard_zero = BeerLambertStandard(
            "standard-0", "Blanc", 0.0,
            self.spectrum(calibration, (100,) * 8, 4, 400),
        )
        standard_one = BeerLambertStandard(
            "standard-1", "Étalon 1", 1.0,
            self.spectrum(calibration, (10,) * 8, 5, 500),
        )
        tab.beer_standards = [standard_zero, standard_one]
        tab.beer_unknown_spectrum = self.spectrum(
            calibration, (50,) * 8, 6, 600
        )
        tab.beer_band_combo.setCurrentIndex(tab.beer_band_combo.findData(3))
        tab._refresh_beer_ui()

        history_spectrum = self.spectrum(calibration, (75,) * 8, 7, 700)
        history = KineticExperiment(
            "kinetic-history",
            calibration,
            10.0,
            60,
            5,
            [KineticPoint(1, 5.0, history_spectrum)],
            "Arrêt utilisateur.",
        )
        points = []
        for sequence in range(1, 181):
            value = max(1, 100 - sequence // 2)
            measured = self.spectrum(
                calibration,
                (value,) * 8,
                100 + sequence,
                1_000 + sequence * 5_000,
            )
            points.append(KineticPoint(sequence, sequence * 5.0, measured))
        current = KineticExperiment(
            "kinetic-current",
            calibration,
            20.0,
            900,
            5,
            points,
            "Durée programmée atteinte.",
        )
        tab.kinetic_history = [history]
        tab.kinetic_experiment = current
        tab.kinetic_band_combo.setCurrentIndex(tab.kinetic_band_combo.findData(3))
        tab.kinetic_duration_spin.setValue(15)
        tab.kinetic_interval_combo.setCurrentIndex(
            tab.kinetic_interval_combo.findData(5)
        )
        tab._refresh_kinetic_ui()

        beer_signature = tab._beer_transfer_signature()
        kinetic_signature = tab._kinetic_transfer_signature()
        tab._beer_transfer_columns[beer_signature] = (0, 1)
        tab._beer_completed_transfers.add(beer_signature)
        tab._beer_last_transferred_signature = beer_signature
        tab._kinetic_transfer_columns[kinetic_signature] = (0, 1)
        tab._kinetic_completed_transfers.add(kinetic_signature)
        tab._kinetic_last_transferred_signature = kinetic_signature
        tab.mode_combo.setCurrentIndex(tab.mode_combo.findData("kinetics"))
        tab._update_controls()
        return window

    def test_real_project_roundtrip_restores_all_modes_without_active_calibration(self):
        source = self.populated_window()
        source.spectrophotometry_tab.spectrum_display_combo.setCurrentIndex(
            source.spectrophotometry_tab.spectrum_display_combo.findData("interpolated")
        )
        source.data_tab.model.setData(source.data_tab.model.index(2, 0), "42")
        state = snapshot(source)
        json.dumps(state, ensure_ascii=False, allow_nan=False)
        self.assertEqual(len(state["spectrophotometry"]["calibrations"]), 1)
        write_project(self.path, state)

        restored = self.window()
        restore(restored, read_project(self.path), self.path)
        tab = restored.spectrophotometry_tab

        self.assertEqual(restored.data_tab.model.rows[0][0], "42")
        self.assertEqual(tab.controller.state, SpectroControllerState.DISCONNECTED)
        self.assertIsNone(tab.session_id)
        self.assertIsNone(tab.applied_config)
        self.assertIsNone(tab.calibration)
        self.assertIsNone(tab.dark_measurement)
        self.assertIsNone(tab.white_measurement)
        self.assertFalse(tab.absorbance_measure_button.isEnabled())
        self.assertFalse(tab.kinetic_start_button.isEnabled())
        self.assertEqual(tab.spectrum_display_combo.currentData(), "interpolated")

        self.assertEqual(len(tab.spectra), 1)
        display = tab.spectra[0]
        self.assertEqual(display.name, "Permanganate")
        self.assertEqual(display.color, "#123456")
        self.assertFalse(display.visible)
        self.assertEqual(display.spectrum.measurement.data.timestamp_ms, 300)
        self.assertEqual(len(display.spectrum.bands), 8)

        self.assertEqual(tab.absorbance_value_label.text(), "0,30103")
        self.assertIn("historique", tab.absorbance_result_status.text())
        tab.absorbance_band_combo.setCurrentIndex(
            tab.absorbance_band_combo.findData(7)
        )
        self.assertEqual(tab.absorbance_value_label.text(), "1")

        self.assertEqual(len(tab.beer_standards), 2)
        self.assertEqual(tab.beer_table.item(0, 3).text(), "Historique")
        self.assertIsNotNone(tab.beer_regression)
        self.assertIsNotNone(tab.beer_unknown_display_result)
        self.assertIn("historique", tab.beer_unknown_warning.text().lower())

        self.assertEqual(len(tab.kinetic_history), 1)
        self.assertEqual(len(tab.kinetic_experiment.points), 180)
        self.assertEqual(tab.kinetic_experiment.points[-1].elapsed_seconds, 900.0)
        self.assertEqual(len(tab.kinetic_experiment.points[-1].spectrum.bands), 8)
        self.assertEqual(
            tab.kinetic_experiment.points[-1].arduino_timestamp_ms, 901_000
        )
        self.assertFalse(tab._kinetic_active)
        self.assertFalse(tab.kinetic_transfer_button.isEnabled())
        self.assertFalse(tab.beer_transfer_button.isEnabled())

        columns = restored.data_tab.model.columnCount()
        graphs = len(restored.graph_tab.windows)
        self.assertIsNone(tab.transfer_beer_to_graph())
        self.assertIsNone(tab.transfer_kinetics_to_graph())
        self.assertEqual(restored.data_tab.model.columnCount(), columns)
        self.assertEqual(len(restored.graph_tab.windows), graphs)

    def test_old_project_without_spectrophotometry_remains_readable(self):
        source = self.window()
        state = snapshot(source)
        state.pop("spectrophotometry")
        restored = self.window()
        restore(restored, state)
        tab = restored.spectrophotometry_tab
        self.assertEqual(tab.spectra, [])
        self.assertIsNone(tab.absorbance_spectrum)
        self.assertEqual(tab.beer_standards, [])
        self.assertIsNone(tab.kinetic_experiment)

    def test_old_spectro_project_without_display_preference_keeps_pchip(self):
        source = self.populated_window()
        state = snapshot(source)
        state["spectrophotometry"].pop("spectrum_display_mode")
        state["spectrophotometry"]["spectra"][0]["visible"] = True

        restored = self.window()
        restore(restored, state)

        tab = restored.spectrophotometry_tab
        self.assertEqual(tab.spectrum_display_combo.currentData(), "interpolated")
        display = tab.spectra[0]
        self.assertEqual(len(display.interpolation_items), 1)
        self.assertEqual(len(display.fill_items), 1)

    def test_points_display_preference_survives_save_and_reopen(self):
        source = self.populated_window()
        self.assertEqual(
            source.spectrophotometry_tab.spectrum_display_combo.currentData(),
            "points",
        )
        write_project(self.path, snapshot(source))

        restored = self.window()
        restore(restored, read_project(self.path), self.path)

        tab = restored.spectrophotometry_tab
        self.assertEqual(tab.spectrum_display_combo.currentData(), "points")
        self.assertIsNotNone(tab.spectrum_band_item)

    def test_corrupt_or_incomplete_spectro_state_is_rejected(self):
        source = self.populated_window()
        state = snapshot(source)
        corrupt = copy.deepcopy(state)
        del corrupt["spectrophotometry"]["spectra"][0]["spectrum"]["bands"][3]
        target = self.window()
        with self.assertRaisesRegex(ValueError, "huit"):
            restore(target, corrupt)

        incomplete = copy.deepcopy(state)
        del incomplete["spectrophotometry"]["calibrations"][0]["white"]
        target = self.window()
        with self.assertRaisesRegex(ValueError, "incomplète"):
            restore(target, incomplete)

    def test_spectro_results_mark_project_dirty_and_replace_is_confirmed(self):
        window = self.window()
        initial = window.document_signature()
        calibration = self.calibration()
        window.spectrophotometry_tab.add_spectrum(
            self.spectrum(calibration, (50,) * 8, 3, 300)
        )
        self.assertNotEqual(window.document_signature(), initial)

        with patch.object(window, "confirm_save", return_value=False) as confirm:
            self.assertFalse(window.replace_project())
        confirm.assert_called_once_with()
        self.assertEqual(len(window.spectrophotometry_tab.spectra), 1)

        with patch.object(window, "confirm_save", return_value=True):
            self.assertTrue(window.replace_project())
        self.assertEqual(window.spectrophotometry_tab.spectra, [])
        self.assertIsNone(window.spectrophotometry_tab.calibration)


if __name__ == "__main__":
    unittest.main()
