"""Tests Qt ciblés de l'interface Spectre."""

import os
import csv
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import zipfile

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QWidget,
)

from physalix.spectrophotometry import MeasurementKind
from physalix.spectrophotometry_protocol import (
    AS7341Gain,
    SpectroConfig,
    SpectroData,
    SpectroErrorPayload,
    SpectroFirmwareInfo,
    SpectroIllumination,
    SpectroSensorType,
)
from physalix.spectrophotometry_serial import SpectroControllerState
from physalix.firmware_flash import (
    FirmwareCompatibility,
    NanoBootloader,
    compare_firmware,
)
from physalix.firmware_resources import load_nano_resources
from physalix.ui.graph_series import PopupComboBox
from physalix.ui.main_window import MainWindow
from physalix.ui.spectrophotometry_tab import (
    BeerLambertPreparationDialog,
    KineticsPreparationDialog,
    MeasurementPreparationDialog,
    StandardEditorDialog,
    SpectrophotometryTab,
)


class FakeSpectroController(QObject):
    state_changed = Signal(object)
    ready = Signal(object)
    configuration_accepted = Signal(object)
    measurement_received = Signal(object)
    measurement_failed = Signal(int, str)
    stopped = Signal(int)
    firmware_error = Signal(object)
    response_ignored = Signal(str)
    error_occurred = Signal(str)

    def __init__(self):
        super().__init__()
        self.state = SpectroControllerState.DISCONNECTED
        self.config = None
        self.opened_port = None
        self.configurations = []
        self.measurements = []
        self.stop_calls = 0
        self.close_calls = 0
        self.next_request_id = 1

    @staticmethod
    def available_ports():
        return (
            SimpleNamespace(
                name="COM4",
                description="Arduino Nano",
                manufacturer="Arduino",
                serial_number="test",
                vendor_id=1,
                product_id=2,
            ),
        )

    def set_state(self, state):
        self.state = state
        self.state_changed.emit(state)

    def open(self, port_name):
        self.opened_port = port_name
        self.set_state(SpectroControllerState.WAITING_HANDSHAKE)
        return True

    def emit_ready(self):
        self.set_state(SpectroControllerState.READY)
        self.ready.emit(
            SpectroFirmwareInfo((1, 0, 0), SpectroSensorType.AS7341, 0x1F)
        )

    def configure(self, config):
        self.configurations.append(config)
        self.set_state(SpectroControllerState.CONFIGURING)

    def accept_configuration(self):
        self.config = self.configurations[-1]
        self.set_state(SpectroControllerState.CONFIGURED)
        self.configuration_accepted.emit(self.config)

    def _measure(self, illumination):
        request_id = self.next_request_id
        self.next_request_id += 1
        self.measurements.append((request_id, illumination))
        self.set_state(SpectroControllerState.MEASURING)
        return request_id

    def measure_dark(self):
        return self._measure(SpectroIllumination.LED_OFF)

    def measure_lit(self):
        return self._measure(SpectroIllumination.LED_ON)

    def emit_measurement(self, value, *, saturation_flags=0):
        request_id, illumination = self.measurements[-1]
        result = SpectroData(
            request_id=request_id,
            config_id=self.config.config_id,
            illumination=illumination,
            bands=tuple(value) if not isinstance(value, (int, float)) else (value,) * 8,
            clear=65535,
            nir=2429,
            saturation_flags=saturation_flags,
            timestamp_ms=request_id * 100,
        )
        self.set_state(SpectroControllerState.CONFIGURED)
        self.measurement_received.emit(result)

    def stop(self):
        if self.state is not SpectroControllerState.MEASURING:
            return False
        self.stop_calls += 1
        self.set_state(SpectroControllerState.STOPPING)
        return True

    def acknowledge_stop(self):
        request_id = self.measurements[-1][0]
        self.set_state(SpectroControllerState.CONFIGURED)
        self.stopped.emit(request_id)

    def close(self):
        self.close_calls += 1
        self.set_state(SpectroControllerState.DISCONNECTED)


class FakeSpectroFirmwareFlash(QObject):
    upload_verified = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object)
    process_settled = Signal()

    def __init__(self):
        super().__init__()
        self.resources = load_nano_resources()
        self.active = False
        self.start_calls = []
        self.confirm_calls = []
        self.verification_failures = []
        self.shutdown_calls = 0

    def start_flash(self, port, bootloader):
        self.start_calls.append((port, bootloader))
        self.active = True
        return True

    def emit_upload_verified(self):
        self.upload_verified.emit(self.resources.manifest)

    def confirm_firmware(self, version, protocol, capabilities):
        self.confirm_calls.append((version, protocol, capabilities))
        result = compare_firmware(
            self.resources.manifest, version, protocol, capabilities
        )
        if result.status is FirmwareCompatibility.COMPATIBLE:
            self.active = False
            self.succeeded.emit(result)
            return True
        return False

    def fail_post_flash_verification(self, message, details):
        self.verification_failures.append((message, details))

    def shutdown(self):
        self.shutdown_calls += 1
        self.active = False


class FakeDataTab:
    def __init__(self):
        self.calls = []

    def append_measurements(self, names, units, rows):
        self.calls.append((names, units, rows))
        return (6, 7)


class FakeGraphWorkspace:
    def __init__(self):
        self.calls = []

    def add_data_graph_with_model(
        self, x_column, y_column, model_kind, title=None
    ):
        self.calls.append((x_column, y_column, model_kind, title))
        return SimpleNamespace(title=title), SimpleNamespace(kind=model_kind)

    def add_data_graph(self, x_column, y_column, title=None):
        self.calls.append((x_column, y_column, title))
        return SimpleNamespace(title=title)


class SpectrophotometryTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.diagnostic_temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.clock = [100.0]
        self.controller = FakeSpectroController()
        self.data_tab = FakeDataTab()
        self.graph_workspace = FakeGraphWorkspace()
        self.show_graph = Mock()
        self.tab = SpectrophotometryTab(
            self.controller,
            data_tab=self.data_tab,
            graph_workspace=self.graph_workspace,
            show_graph=self.show_graph,
            disconnect_timeout_ms=20,
            monotonic_clock=lambda: self.clock[0],
            diagnostic_root=self.diagnostic_temporary.name,
        )
        self.tab._confirm_measurement_preparation = lambda kind: True
        self.tab._confirm_beer_transfer = lambda: True
        self.tab._confirm_kinetic_preparation = lambda: True

    def tearDown(self):
        self.tab.shutdown()
        self.tab.deleteLater()
        self.app.processEvents()
        self.diagnostic_temporary.cleanup()

    def connect_and_configure(self):
        self.tab.connect_button.click()
        self.controller.emit_ready()
        self.controller.accept_configuration()

    def calibrate(self):
        self.tab.dark_button.click()
        self.controller.emit_measurement(0)
        self.tab.white_button.click()
        self.controller.emit_measurement(100)

    def measure_sample(self, value=10, *, saturation_flags=0):
        self.tab.sample_button.click()
        self.controller.emit_measurement(value, saturation_flags=saturation_flags)

    def add_and_measure_standard(self, name, concentration, value, *, saturation_flags=0):
        standard = self.tab.add_beer_standard(name, str(concentration))
        self.tab.beer_table.selectRow(len(self.tab.beer_standards) - 1)
        self.tab._confirm_beer_measurement = Mock(return_value=True)
        self.tab.measure_selected_beer_standard()
        self.controller.emit_measurement(value, saturation_flags=saturation_flags)
        return standard

    def start_kinetic(self):
        self.tab.mode_combo.setCurrentIndex(3)
        self.tab.kinetic_duration_spin.setValue(1)
        self.tab.kinetic_start_button.click()

    def test_creation_is_idle_and_uses_expected_layout_components(self):
        self.assertIsNone(self.controller.opened_port)
        self.assertEqual(self.tab.port_combo.currentData(), "COM4")
        self.assertIsInstance(self.tab.port_combo, PopupComboBox)
        self.assertIsInstance(self.tab.mode_combo, PopupComboBox)
        self.assertTrue(self.tab.mode_combo.model().item(1).isEnabled())
        self.assertTrue(self.tab.mode_combo.model().item(2).isEnabled())
        self.assertTrue(self.tab.mode_combo.model().item(3).isEnabled())
        self.assertEqual(self.tab.mode_combo.count(), 4)
        self.assertFalse(self.tab.advanced_content.isVisible())
        self.assertEqual(
            [
                self.tab.spectrum_display_combo.itemText(index)
                for index in range(self.tab.spectrum_display_combo.count())
            ],
            ["Points mesurés", "Courbe interpolée (PCHIP)"],
        )
        self.assertEqual(self.tab.spectrum_display_combo.currentData(), "points")
        self.assertEqual(self.tab.main_splitter.count(), 2)
        self.assertCountEqual(
            self.tab.findChildren(QScrollArea),
            [
                self.tab.settings_scroll,
                self.tab.beer_settings_scroll,
                self.tab.kinetic_settings_scroll,
            ],
        )

    def test_layout_keeps_plot_larger_and_actions_visible(self):
        for width, height in ((1366, 768), (1600, 900)):
            with self.subTest(size=(width, height)):
                self.tab.resize(width, height)
                self.tab.show()
                self.app.processEvents()
                self.assertGreater(self.tab.plot.width(), self.tab.settings_column.width())
                self.assertGreaterEqual(self.tab.plot.height(), 300)
                self.assertTrue(self.tab.sample_button.isVisible())
                self.assertFalse(hasattr(self.tab, "spectrum_bar"))

    def test_beer_layout_keeps_plot_larger_at_target_resolutions(self):
        self.tab.mode_combo.setCurrentIndex(2)
        for width, height in ((1366, 768), (1600, 900)):
            with self.subTest(size=(width, height)):
                self.tab.resize(width, height)
                self.tab.show()
                self.app.processEvents()
                self.assertGreater(
                    self.tab.beer_plot.width(), self.tab.beer_settings_column.width()
                )
                self.assertGreaterEqual(self.tab.beer_plot.height(), 300)
                self.assertTrue(self.tab.beer_transfer_button.isVisible())

    def test_beer_table_headers_fit_without_horizontal_scroll(self):
        self.tab.mode_combo.setCurrentIndex(2)
        expected = ["Solution", "c (mol/L)", "A (555 nm)", "État"]
        for width in (1280, 1366, 1600):
            with self.subTest(width=width):
                self.tab.resize(width, 900)
                self.tab.show()
                self.app.processEvents()
                self.tab.beer_table.resize_columns_to_viewport()
                header = self.tab.beer_table.horizontalHeader()
                self.assertEqual(
                    [header.model().headerData(i, header.orientation()) for i in range(4)],
                    expected,
                )
                for column, text in enumerate(expected):
                    required = header.fontMetrics().horizontalAdvance(text) + 12
                    self.assertGreaterEqual(header.sectionSize(column), required)
                self.assertLessEqual(
                    sum(header.sectionSize(i) for i in range(4)),
                    self.tab.beer_table.viewport().width(),
                )
                self.assertEqual(self.tab.beer_table.horizontalScrollBar().maximum(), 0)

    def test_beer_table_headers_follow_unit_and_band(self):
        self.tab.beer_unit_combo.setCurrentIndex(1)
        self.tab.beer_band_combo.setCurrentIndex(1)
        header = self.tab.beer_table.horizontalHeader()

        self.assertEqual(
            [header.model().headerData(i, header.orientation()) for i in range(4)],
            ["Solution", "c (mmol/L)", "A (445 nm)", "État"],
        )

    def test_kinetic_mode_defaults_and_layout(self):
        self.tab.mode_combo.setCurrentIndex(3)

        self.assertIs(
            self.tab.mode_stack.currentWidget(), self.tab.kinetic_main_splitter
        )
        self.assertEqual(self.tab.kinetic_band_combo.currentData(), 6)
        self.assertEqual(self.tab.kinetic_duration_spin.value(), 15)
        self.assertEqual(self.tab.kinetic_interval_combo.currentData(), 5)
        for width, height in ((1280, 800), (1366, 768), (1600, 900)):
            with self.subTest(size=(width, height)):
                self.tab.resize(width, height)
                self.tab.show()
                self.app.processEvents()
                self.assertGreater(
                    self.tab.kinetic_plot.width(),
                    self.tab.kinetic_settings_column.width(),
                )
                self.assertTrue(self.tab.kinetic_start_button.isVisible())
                self.assertTrue(self.tab.kinetic_transfer_button.isVisible())
                self.assertNotIn(
                    "Exporter le diagnostic",
                    [button.text() for button in self.tab.findChildren(QPushButton)],
                )

    def test_kinetic_start_requires_calibration(self):
        self.connect_and_configure()
        count = len(self.controller.measurements)

        self.tab.mode_combo.setCurrentIndex(3)
        self.tab.start_kinetics()

        self.assertIsNone(self.tab.kinetic_experiment)
        self.assertEqual(len(self.controller.measurements), count)
        self.assertIn("Étalonnage requis", self.tab.kinetic_action_status.text())

    def test_cancelled_kinetic_preparation_starts_no_measurement(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab._confirm_kinetic_preparation = Mock(return_value=False)
        count = len(self.controller.measurements)

        self.tab.start_kinetics()

        self.assertIsNone(self.tab.kinetic_experiment)
        self.assertEqual(len(self.controller.measurements), count)
        self.assertEqual(self.tab.kinetic_action_status.text(), "Démarrage annulé.")

    def test_kinetic_rejects_interval_shorter_than_integration(self):
        self.connect_and_configure()
        self.calibrate()
        slow = SpectroConfig(
            self.tab.applied_config.config_id,
            255,
            65535,
            self.tab.applied_config.gain,
            self.tab.applied_config.led_pwm,
        )
        self.tab.applied_config = slow
        self.controller.config = slow

        self.tab.start_kinetics()

        self.assertIsNone(self.tab.kinetic_experiment)
        self.assertEqual(self.tab.kinetic_action_status.text(), "Intervalle incompatible.")

    def test_kinetic_reuses_shared_calibration_controls(self):
        self.connect_and_configure()
        self.tab.mode_combo.setCurrentIndex(3)
        self.assertFalse(self.tab.kinetic_dark_button.isHidden())

        self.calibrate()

        self.assertIn("Étalonnage prêt", self.tab.kinetic_calibration_status.text())
        self.assertTrue(self.tab.kinetic_dark_button.isHidden())
        self.assertTrue(self.tab.kinetic_white_button.isHidden())
        self.assertFalse(self.tab.kinetic_recalibrate_button.isHidden())

    def test_kinetic_uses_real_completion_time_and_never_overlaps(self):
        self.connect_and_configure()
        self.calibrate()

        self.start_kinetic()
        measurement_count = len(self.controller.measurements)
        self.tab._kinetic_due()
        self.assertEqual(len(self.controller.measurements), measurement_count)

        self.clock[0] = 100.65
        self.controller.emit_measurement(10)

        point = self.tab.kinetic_experiment.points[0]
        self.assertAlmostEqual(point.elapsed_seconds, 0.65)
        self.assertGreater(point.elapsed_seconds, 0)
        self.assertEqual(point.arduino_timestamp_ms, 300)
        self.assertTrue(self.tab.kinetic_schedule_timer.isActive())
        self.assertEqual(len(self.controller.measurements), measurement_count)

    def test_kinetic_uses_plus_markers_for_180_exact_measurements(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab.mode_combo.setCurrentIndex(3)
        self.tab.kinetic_duration_spin.setValue(15)
        self.tab.kinetic_start_button.click()

        for index in range(180):
            self.clock[0] = 100.5 + index * 5
            self.controller.emit_measurement(20 + index)
            self.tab.kinetic_schedule_timer.stop()
            if index < 179:
                self.clock[0] = 105.0 + index * 5
                self.tab._kinetic_due()
        self.tab.stop_kinetics()

        xs, ys = self.tab.kinetic_curve.getData()
        expected = self.tab.kinetic_experiment.band_values(6)
        self.assertEqual(self.tab.kinetic_curve.opts["symbol"], "+")
        self.assertEqual(len(self.tab.kinetic_curve.scatter.points()), 180)
        self.assertEqual(list(xs), [item[0] for item in expected])
        self.assertEqual(list(ys), [item[1] for item in expected])
        self.assertEqual(len(self.tab.kinetic_experiment.points), 180)

    def test_kinetic_reticle_selects_only_recorded_points_and_follows_view(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        self.clock[0] = 100.5
        self.controller.emit_measurement(10)
        self.tab.kinetic_schedule_timer.stop()
        self.clock[0] = 105.0
        self.tab._kinetic_due()
        self.clock[0] = 105.5
        self.controller.emit_measurement(20)
        self.tab.stop_kinetics()
        self.tab.show()
        self.app.processEvents()

        self.assertTrue(self.tab._select_kinetic_point(1))
        selected = self.tab.kinetic_experiment.points[0]
        absorbance = selected.spectrum.bands[6].absorbance
        view = self.tab.kinetic_plot.getViewBox()
        view.setRange(xRange=(0.0, 6.0), yRange=(0.0, 1.2), padding=0)
        self.tab._position_kinetic_reticle()
        horizontal_x, horizontal_y = self.tab.kinetic_projection_horizontal.getData()
        vertical_x, vertical_y = self.tab.kinetic_projection_vertical.getData()
        self.assertEqual(horizontal_x[-1], selected.elapsed_seconds)
        self.assertEqual(horizontal_y[-1], absorbance)
        self.assertEqual(vertical_x[-1], selected.elapsed_seconds)
        self.assertEqual(vertical_y[-1], absorbance)
        self.assertIn("A = ", self.tab.kinetic_absorbance_projection_label.toPlainText())
        self.assertIn("t = 0,5 s", self.tab.kinetic_time_label.toPlainText())
        self.assertTrue(self.tab.kinetic_time_label.isVisible())

        initial_y = self.tab.kinetic_time_label.pos().y()
        self.tab.resize(1280, 800)
        view.setRange(xRange=(0.0, 2.0), yRange=(0.8, 1.1), padding=0)
        self.app.processEvents()
        self.tab._position_kinetic_reticle()
        self.assertNotEqual(self.tab.kinetic_time_label.pos().y(), initial_y)
        x_range, y_range = view.viewRange()
        self.assertGreaterEqual(self.tab.kinetic_time_label.pos().x(), x_range[0])
        self.assertLessEqual(self.tab.kinetic_time_label.pos().x(), x_range[1])
        self.assertGreaterEqual(
            self.tab.kinetic_absorbance_projection_label.pos().y(), y_range[0]
        )
        self.assertLessEqual(
            self.tab.kinetic_absorbance_projection_label.pos().y(), y_range[1]
        )

        fake_point = SimpleNamespace(pos=lambda: QPointF(5.5, 0.0))
        self.tab._kinetic_points_clicked(None, [fake_point], None)
        self.assertEqual(self.tab._kinetic_selected_sequence, 2)

    def test_kinetic_reticle_follows_latest_point_and_updates_with_band(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        self.clock[0] = 100.5
        self.controller.emit_measurement((10, 20, 30, 40, 50, 60, 70, 80))

        self.assertEqual(self.tab._kinetic_selected_sequence, 1)
        first_text = self.tab.kinetic_absorbance_projection_label.toPlainText()
        measurement_count = len(self.controller.measurements)
        self.tab.kinetic_band_combo.setCurrentIndex(0)
        self.assertEqual(len(self.controller.measurements), measurement_count)
        self.assertEqual(self.tab._kinetic_selected_sequence, 1)
        self.assertNotEqual(
            self.tab.kinetic_absorbance_projection_label.toPlainText(), first_text
        )

        self.tab.kinetic_schedule_timer.stop()
        self.clock[0] = 105.0
        self.tab._kinetic_due()
        self.clock[0] = 105.5
        self.controller.emit_measurement((20, 30, 40, 50, 60, 70, 80, 90))
        self.assertEqual(self.tab._kinetic_selected_sequence, 2)

    def test_kinetic_elapsed_display_combines_seconds_and_minutes(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab.mode_combo.setCurrentIndex(3)
        self.tab.kinetic_duration_spin.setValue(15)
        self.tab.kinetic_start_button.click()

        for elapsed, expected in (
            (65.0, "65,0 s (1 min 05 s)"),
            (330.0, "330,0 s (5 min 30 s)"),
            (900.0, "900,0 s (15 min 00 s)"),
        ):
            with self.subTest(elapsed=elapsed):
                self.clock[0] = 100.0 + elapsed
                self.tab._refresh_kinetic_clock()
                self.assertEqual(
                    self.tab.kinetic_elapsed_label.text(),
                    f"Temps écoulé : {expected}",
                )

    def test_kinetic_reticle_cartouches_follow_light_and_dark_palettes(self):
        dark_palette = QPalette(self.tab.palette())
        dark_palette.setColor(QPalette.ColorRole.Base, QColor("#20242a"))
        dark_palette.setColor(QPalette.ColorRole.Text, QColor("#f4f5f6"))
        self.tab.setPalette(dark_palette)
        self.tab._apply_kinetic_plot_palette()

        dark_fill = self.tab.kinetic_time_label.fill.color()
        self.assertEqual(dark_fill.name(), "#20242a")
        self.assertEqual(dark_fill.alpha(), 235)

        light_palette = QPalette(dark_palette)
        light_palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        light_palette.setColor(QPalette.ColorRole.Text, QColor("#10243e"))
        self.tab.setPalette(light_palette)
        self.tab._apply_kinetic_plot_palette()
        self.assertEqual(
            self.tab.kinetic_time_label.fill.color().name(), "#ffffff"
        )

    def test_kinetic_late_schedule_skips_missed_deadlines_without_burst(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        self.clock[0] = 100.6
        self.controller.emit_measurement(10)
        initial_count = len(self.controller.measurements)
        self.tab.kinetic_schedule_timer.stop()

        self.clock[0] = 112.2
        self.tab._kinetic_due()
        self.assertEqual(len(self.controller.measurements), initial_count + 1)
        self.clock[0] = 112.8
        self.controller.emit_measurement(10)

        self.assertEqual(len(self.controller.measurements), initial_count + 1)
        self.assertGreaterEqual(self.tab.kinetic_schedule_timer.interval(), 2200)
        self.assertLessEqual(self.tab.kinetic_schedule_timer.interval(), 2201)

    def test_kinetic_manual_stop_uses_stop_and_preserves_points(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        self.clock[0] = 100.7
        self.controller.emit_measurement(10)
        self.clock[0] = 105.0
        self.tab._kinetic_due()

        self.tab.kinetic_stop_button.click()

        self.assertEqual(self.controller.stop_calls, 1)
        self.assertEqual(len(self.tab.kinetic_experiment.points), 1)
        self.controller.acknowledge_stop()
        self.assertFalse(self.tab._kinetic_active)
        self.assertFalse(self.tab._kinetic_stopping)
        self.assertEqual(len(self.tab.kinetic_experiment.points), 1)

    def test_kinetic_diagnostic_tracks_command_response_and_manual_stop(self):
        self.connect_and_configure()
        self.calibrate()

        self.start_kinetic()
        journal = self.tab.kinetic_journal
        self.assertIsNotNone(journal)
        self.clock[0] = 100.75
        self.controller.emit_measurement((20, 21, 22, 23, 24, 25, 26, 27))
        self.tab.stop_kinetics()

        with journal.measurements_path.open(encoding="utf-8", newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["request_id"], "3")
        self.assertEqual(row["raw_f1"], "20")
        self.assertEqual(row["raw_f8"], "27")
        self.assertEqual(row["command_response_latency_seconds"], "0.75")
        events = [
            json.loads(line)["type"]
            for line in journal.events_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn("measurement_command", events)
        self.assertIn("measurement_response", events)
        self.assertIn("stop_requested", events)
        self.assertTrue(journal.finished)
        self.assertTrue(self.tab.kinetic_diagnostic_export_available())

    def test_kinetic_automatic_stop_uses_stop_for_pending_measurement(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()

        self.tab._kinetic_duration_reached()

        self.assertEqual(self.controller.stop_calls, 1)
        self.assertTrue(self.tab._kinetic_stopping)
        self.controller.acknowledge_stop()
        self.assertFalse(self.tab._kinetic_active)
        self.assertIn("Durée programmée", self.tab.kinetic_action_status.text())

    def test_kinetic_late_completion_after_duration_is_ignored(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()

        self.clock[0] = 160.01
        self.controller.emit_measurement(10)

        self.assertEqual(self.tab.kinetic_experiment.points, [])
        self.assertFalse(self.tab._kinetic_active)
        self.assertIn("hors de la durée", self.tab.kinetic_action_status.text())

    def test_kinetic_band_change_reuses_data_and_keeps_invalid_gap(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        self.clock[0] = 100.6
        self.controller.emit_measurement((10, 10, 10, 10, 10, 50, 10, 10))
        self.clock[0] = 105.0
        self.tab._kinetic_due()
        self.clock[0] = 105.6
        self.controller.emit_measurement(10, saturation_flags=1 << 6)
        count = len(self.controller.measurements)
        _, before = self.tab.kinetic_curve.getData()

        self.tab.kinetic_band_combo.setCurrentIndex(5)
        _, after = self.tab.kinetic_curve.getData()

        self.assertEqual(len(self.controller.measurements), count)
        self.assertNotEqual(list(before[:1]), list(after[:1]))
        self.tab.kinetic_band_combo.setCurrentIndex(6)
        _, invalid = self.tab.kinetic_curve.getData()
        self.assertTrue(np.isnan(invalid[1]))

    def test_kinetic_disconnect_stops_and_keeps_experiment(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        experiment = self.tab.kinetic_experiment

        self.tab.disconnect()
        self.controller.acknowledge_stop()

        self.assertIs(self.tab.kinetic_experiment, experiment)
        self.assertFalse(self.tab.kinetic_schedule_timer.isActive())
        self.assertFalse(self.tab.kinetic_duration_timer.isActive())
        self.assertEqual(self.controller.state, SpectroControllerState.DISCONNECTED)
        self.assertIsNone(self.tab.calibration)
        self.assertTrue(self.tab.kinetic_journal.finished)
        self.assertTrue(self.tab.kinetic_diagnostic_export_available())
        event_types = [
            json.loads(line)["type"]
            for line in self.tab.kinetic_journal.events_path.read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        self.assertIn("disconnection_requested", event_types)
        self.assertIn("experiment_interrupted", event_types)

    def test_kinetic_serial_error_is_logged_and_does_not_remove_diagnostic(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        journal = self.tab.kinetic_journal

        self.controller.set_state(SpectroControllerState.ERROR)
        self.controller.error_occurred.emit("port série perdu")

        self.assertTrue(journal.finished)
        self.assertEqual(journal.metadata["status"], "interrupted")
        event_types = [event["type"] for event in (
            json.loads(line)
            for line in journal.events_path.read_text(encoding="utf-8").splitlines()
        )]
        self.assertIn("connection_state_changed", event_types)
        self.assertIn("experiment_interrupted", event_types)
        self.assertTrue(self.tab.kinetic_diagnostic_export_available())

    def test_kinetic_timeout_firmware_error_and_ignored_response_are_logged(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        journal = self.tab.kinetic_journal
        request_id = self.controller.measurements[-1][0]

        self.controller.firmware_error.emit(SpectroErrorPayload(request_id, 7))
        self.controller.response_ignored.emit("réponse tardive ignorée")
        self.controller.set_state(SpectroControllerState.CONFIGURED)
        self.controller.measurement_failed.emit(request_id, "délai expiré")

        self.assertTrue(journal.finished)
        event_types = [
            json.loads(line)["type"]
            for line in journal.events_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn("firmware_error", event_types)
        self.assertIn("serial_response_ignored", event_types)
        self.assertIn("measurement_error", event_types)

    def test_kinetic_diagnostic_export_uses_selected_zip(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        self.clock[0] = 100.5
        self.controller.emit_measurement(20)
        self.tab.stop_kinetics()
        destination = Path(self.diagnostic_temporary.name) / "diagnostic-exporte.zip"

        with patch(
            "physalix.ui.spectrophotometry_tab.QFileDialog.getSaveFileName",
            return_value=(str(destination), "Archive ZIP (*.zip)"),
        ):
            result = self.tab.export_kinetic_diagnostic()

        self.assertEqual(result, destination)
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"metadata.json", "measurements.csv", "events.jsonl"},
            )
        self.assertIn("Diagnostic exporté", self.tab.kinetic_action_status.text())

    def test_new_kinetic_experiment_archives_previous_data(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        self.clock[0] = 100.5
        self.controller.emit_measurement(10)
        self.tab.stop_kinetics()
        previous = self.tab.kinetic_experiment

        with patch(
            "physalix.ui.spectrophotometry_tab.ask_yes_no", return_value=True
        ):
            self.tab.new_kinetic_experiment()

        self.assertIsNone(self.tab.kinetic_experiment)
        self.assertEqual(self.tab.kinetic_history, [previous])

    def test_kinetic_transfer_excludes_invalid_values_and_opens_graph(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        self.clock[0] = 100.5
        self.controller.emit_measurement(10)
        self.clock[0] = 105.0
        self.tab._kinetic_due()
        self.clock[0] = 105.5
        self.controller.emit_measurement(10, saturation_flags=1 << 6)
        self.tab.stop_kinetics()

        with patch(
            "physalix.ui.spectrophotometry_tab.ask_yes_no", return_value=True
        ):
            result = self.tab.transfer_kinetics_to_graph()

        self.assertEqual(result[0], (6, 7))
        names, units, rows = self.data_tab.calls[0]
        self.assertIn("630 nm", names[0])
        self.assertEqual(units, ["s", ""])
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            self.graph_workspace.calls, [(6, 7, "Cinétique à 630 nm")]
        )
        self.show_graph.assert_called_once_with()
        self.assertFalse(self.tab.kinetic_transfer_button.isEnabled())

    def test_kinetic_transfer_retry_does_not_duplicate_columns(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()
        self.clock[0] = 100.5
        self.controller.emit_measurement(10)
        self.tab.stop_kinetics()
        original = self.graph_workspace.add_data_graph
        self.graph_workspace.add_data_graph = Mock(side_effect=RuntimeError("échec"))

        with (
            patch("physalix.ui.spectrophotometry_tab.ask_yes_no", return_value=True),
            patch("physalix.ui.spectrophotometry_tab.QMessageBox.warning"),
        ):
            self.assertIsNone(self.tab.transfer_kinetics_to_graph())
        self.assertEqual(len(self.data_tab.calls), 1)

        self.graph_workspace.add_data_graph = original
        self.assertIsNotNone(self.tab.transfer_kinetics_to_graph())
        self.assertEqual(len(self.data_tab.calls), 1)

    def test_connection_is_explicit_and_each_configuration_id_is_unique(self):
        self.tab.connect_button.click()
        self.assertEqual(self.controller.opened_port, "COM4")
        self.assertIsNotNone(self.tab.session_id)
        self.controller.emit_ready()
        self.assertEqual(self.controller.configurations[-1].config_id, 1)
        self.controller.accept_configuration()

        self.tab.advanced_toggle.setChecked(True)
        self.tab.atime_spin.setValue(101)
        self.tab.apply_config_button.click()

        self.assertEqual(self.controller.configurations[-1].config_id, 2)
        self.assertEqual(self.controller.configurations[-1].atime, 101)

    def test_cancelling_preparation_does_not_start_dark_measurement(self):
        self.connect_and_configure()
        self.tab._confirm_measurement_preparation = Mock(return_value=False)

        self.tab.dark_button.click()

        self.assertEqual(self.controller.measurements, [])
        self.assertIsNone(self.tab._pending_kind)

    def test_controller_state_is_rechecked_after_confirmation(self):
        self.connect_and_configure()

        def disconnect_during_dialog(kind):
            self.controller.set_state(SpectroControllerState.DISCONNECTED)
            return True

        self.tab._confirm_measurement_preparation = disconnect_during_dialog
        self.tab.dark_button.click()

        self.assertEqual(self.controller.measurements, [])
        self.assertIn("état du spectrophotomètre a changé", self.tab.measurement_status.text())

    def test_incompatible_state_does_not_open_preparation_or_measure(self):
        confirmation = Mock(return_value=True)
        self.tab._confirm_measurement_preparation = confirmation

        self.tab.request_measurement(MeasurementKind.DARK)

        confirmation.assert_not_called()
        self.assertEqual(self.controller.measurements, [])

    def test_sample_measurement_does_not_use_preparation_dialog(self):
        self.connect_and_configure()
        self.calibrate()
        confirmation = Mock(return_value=True)
        self.tab._confirm_measurement_preparation = confirmation

        self.measure_sample()

        confirmation.assert_not_called()
        self.assertEqual(len(self.tab.spectra), 1)

    def test_default_spectrum_display_shows_only_eight_measured_points(self):
        self.connect_and_configure()
        self.assertTrue(self.tab.dark_button.isEnabled())
        self.assertFalse(self.tab.white_button.isEnabled())
        self.calibrate()

        self.assertIsNotNone(self.tab.calibration)
        self.assertTrue(self.tab.sample_button.isEnabled())
        self.assertIn("Étalonnage prêt", self.tab.calibration_status.text())
        self.measure_sample()

        self.assertEqual(len(self.tab.spectra), 1)
        display = self.tab.spectra[0]
        self.assertEqual(len(display.spectrum.bands), 8)
        self.assertEqual(len(display.experimental_item.xData), 8)
        self.assertEqual(tuple(display.experimental_item.xData), (415, 445, 480, 515, 555, 590, 630, 680))
        self.assertIsNone(display.experimental_item.opts["pen"])
        self.assertEqual(display.interpolation_items, [])
        self.assertEqual(display.fill_items, [])
        self.assertEqual(self.tab.spectrum_display_combo.currentData(), "points")
        self.assertIsNotNone(self.tab.spectrum_band_item)
        bounds = self.tab.spectrum_band_item.path().boundingRect()
        self.assertEqual(bounds.left(), 415)
        self.assertEqual(bounds.right(), 680)

    def test_interpolated_mode_keeps_pchip_curve_and_spectral_fill(self):
        self.connect_and_configure()
        self.calibrate()
        self.measure_sample()
        display = self.tab.spectra[0]
        measurement_count = len(self.controller.measurements)
        spectrum = display.spectrum

        self.tab.spectrum_display_combo.setCurrentIndex(
            self.tab.spectrum_display_combo.findData("interpolated")
        )

        self.assertEqual(len(self.controller.measurements), measurement_count)
        self.assertIs(display.spectrum, spectrum)
        self.assertEqual(len(display.experimental_item.xData), 8)
        self.assertEqual(len(display.interpolation_items), 1)
        self.assertEqual(len(display.fill_items), 1)
        self.assertIsNone(self.tab.spectrum_band_item)
        self.assertEqual(display.fill_items[0].path().boundingRect().left(), 415)
        self.assertEqual(display.fill_items[0].path().boundingRect().right(), 680)
        self.assertGreater(display.experimental_item.zValue(), display.fill_items[0].zValue())
        self.assertGreater(display.interpolation_items[0].zValue(), display.fill_items[0].zValue())
        self.assertIn("pics", self.tab.spectrum_display_note.text())

    def test_parameter_change_invalidates_active_calibration_but_keeps_spectra(self):
        self.connect_and_configure()
        self.calibrate()
        self.measure_sample()

        self.tab.atime_spin.setValue(101)

        self.assertIsNone(self.tab.calibration)
        self.assertFalse(self.tab.sample_button.isEnabled())
        self.assertEqual(len(self.tab.spectra), 1)
        self.assertIn("Noir manquant", self.tab.calibration_status.text())

    def test_invalid_band_is_not_drawn_or_interpolated_across(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab.spectrum_display_combo.setCurrentIndex(
            self.tab.spectrum_display_combo.findData("interpolated")
        )
        self.measure_sample(saturation_flags=1 << 3)

        display = self.tab.spectra[0]
        self.assertEqual(len(display.experimental_item.xData), 7)
        self.assertNotIn(515, display.experimental_item.xData)
        self.assertEqual(len(display.interpolation_items), 2)
        self.assertEqual(len(display.fill_items), 2)
        self.assertLessEqual(max(display.interpolation_items[0].xData), 480)
        self.assertGreaterEqual(min(display.interpolation_items[1].xData), 555)
        self.assertLessEqual(display.fill_items[0].path().boundingRect().right(), 480)
        self.assertGreaterEqual(display.fill_items[1].path().boundingRect().left(), 555)
        self.assertIn("1 bande(s) indisponible(s)", self.tab.measurement_status.text())

    def test_invalid_band_is_omitted_in_points_mode_without_segments(self):
        self.connect_and_configure()
        self.calibrate()
        self.measure_sample(saturation_flags=1 << 3)

        display = self.tab.spectra[0]
        self.assertEqual(len(display.experimental_item.xData), 7)
        self.assertNotIn(515, display.experimental_item.xData)
        self.assertIsNone(display.experimental_item.opts["pen"])
        self.assertEqual(display.interpolation_items, [])
        self.assertEqual(display.fill_items, [])

    def test_points_mode_rainbow_band_tracks_zoom_resize_and_theme(self):
        self.tab.resize(1280, 800)
        self.tab.show()
        self.app.processEvents()
        item = self.tab.spectrum_band_item
        self.assertIsNotNone(item)

        self.tab.plot.setRange(xRange=(430, 610), yRange=(-0.2, 1.8), padding=0)
        self.tab.resize(1600, 900)
        self.app.processEvents()
        bounds = item.path().boundingRect()
        y_range = self.tab.plot.viewRange()[1]
        self.assertEqual((bounds.left(), bounds.right()), (415, 680))
        self.assertGreaterEqual(bounds.top(), y_range[0])
        self.assertLess(bounds.bottom(), y_range[0] + 0.08 * (y_range[1] - y_range[0]))

        dark_palette = QPalette(self.tab.palette())
        dark_palette.setColor(QPalette.ColorRole.Base, QColor("#20242a"))
        self.tab.setPalette(dark_palette)
        self.tab._apply_plot_palette()
        dark_alphas = [color.alpha() for _, color in item.brush().gradient().stops()]
        self.assertTrue(dark_alphas and all(alpha == 185 for alpha in dark_alphas))

        light_palette = QPalette(dark_palette)
        light_palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        self.tab.setPalette(light_palette)
        self.tab._apply_plot_palette()
        light_alphas = [color.alpha() for _, color in item.brush().gradient().stops()]
        self.assertTrue(light_alphas and all(alpha == 215 for alpha in light_alphas))

    def test_multiple_spectra_can_be_renamed_and_hidden(self):
        self.connect_and_configure()
        self.calibrate()
        self.measure_sample(10)
        self.measure_sample(20)

        self.assertEqual(len(self.tab.spectra), 2)
        self.assertNotEqual(self.tab.spectra[0].color, self.tab.spectra[1].color)
        first_row = self.tab.spectra_list.itemWidget(self.tab.spectra_list.item(0))
        first_row.findChild(QLineEdit).setText("Permanganate")
        first_row.findChild(QCheckBox).setChecked(False)

        self.assertEqual(self.tab.spectra[0].name, "Permanganate")
        self.assertFalse(self.tab.spectra[0].visible)
        self.assertIsNone(self.tab.spectra[0].experimental_item)
        self.assertEqual(self.tab.spectra[0].fill_items, [])
        self.assertIsNotNone(self.tab.spectra[1].experimental_item)

    def test_spectrum_removal_keeps_calibration(self):
        self.connect_and_configure()
        self.calibrate()
        self.measure_sample()
        reference = self.tab.calibration

        with patch(
            "physalix.ui.spectrophotometry_tab.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.tab.remove_selected_spectrum()

        self.assertEqual(self.tab.spectra, [])
        self.assertIs(self.tab.calibration, reference)

    def test_disconnect_during_measurement_waits_for_stop_then_cleans_up(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab.sample_button.click()

        self.tab.disconnect()
        self.assertEqual(self.controller.stop_calls, 1)
        self.assertEqual(self.controller.close_calls, 0)
        self.assertTrue(self.tab.disconnect_timer.isActive())

        self.controller.acknowledge_stop()
        self.assertEqual(self.controller.close_calls, 1)
        self.assertIsNone(self.tab.session_id)
        self.assertIsNone(self.tab.calibration)

    def test_shutdown_closes_controller_and_clears_timers(self):
        self.connect_and_configure()
        self.calibrate()
        self.start_kinetic()

        self.tab.shutdown()

        self.assertEqual(self.controller.state, SpectroControllerState.DISCONNECTED)
        self.assertFalse(self.tab.disconnect_timer.isActive())
        self.assertFalse(self.tab.kinetic_schedule_timer.isActive())
        self.assertFalse(self.tab.kinetic_duration_timer.isActive())
        self.assertFalse(self.tab.kinetic_clock_timer.isActive())
        self.assertIsNone(self.tab.calibration)

    def test_absorbance_is_the_second_mode_with_eight_real_bands(self):
        self.assertEqual(
            [self.tab.mode_combo.itemText(i) for i in range(4)],
            ["Spectre", "Absorbance", "Beer-Lambert", "Cinétique"],
        )
        self.tab.mode_combo.setCurrentIndex(1)
        self.assertIs(self.tab.mode_stack.currentWidget(), self.tab.absorbance_page)
        self.assertEqual(
            [self.tab.absorbance_band_combo.itemText(i) for i in range(8)],
            [
                "415 nm (F1)",
                "445 nm (F2)",
                "480 nm (F3)",
                "515 nm (F4)",
                "555 nm (F5)",
                "590 nm (F6)",
                "630 nm (F7)",
                "680 nm (F8)",
            ],
        )
        self.assertEqual(self.tab.absorbance_band_index(), 3)

    def test_absorbance_mode_shares_calibration_and_reference_actions(self):
        self.connect_and_configure()
        self.assertTrue(self.tab.absorbance_dark_button.isEnabled())
        self.assertFalse(self.tab.absorbance_white_button.isEnabled())
        self.assertFalse(self.tab.absorbance_dark_button.isHidden())
        self.assertTrue(self.tab.absorbance_recalibrate_button.isHidden())

        self.tab.absorbance_dark_button.click()
        self.controller.emit_measurement(0)
        self.tab.absorbance_white_button.click()
        self.controller.emit_measurement(100)

        self.assertIsNotNone(self.tab.calibration)
        self.assertIn("Étalonnage prêt", self.tab.absorbance_calibration_status.text())
        self.assertTrue(self.tab.absorbance_measure_button.isEnabled())
        self.assertTrue(self.tab.absorbance_dark_button.isHidden())
        self.assertTrue(self.tab.absorbance_white_button.isHidden())
        self.assertFalse(self.tab.absorbance_recalibrate_button.isHidden())

        reference = self.tab.calibration
        measurement_count = len(self.controller.measurements)
        self.tab.absorbance_recalibrate_button.click()
        self.assertFalse(self.tab.absorbance_dark_button.isHidden())
        self.assertFalse(self.tab.absorbance_white_button.isHidden())
        self.assertTrue(self.tab.absorbance_recalibrate_button.isHidden())
        self.assertIs(self.tab.calibration, reference)
        self.assertEqual(len(self.controller.measurements), measurement_count)

    def test_single_absorbance_measurement_keeps_all_bands_and_no_graph(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab.mode_combo.setCurrentIndex(1)
        values = (80, 70, 60, 50, 40, 30, 20, 10)

        self.tab.absorbance_measure_button.click()
        self.controller.emit_measurement(values)

        self.assertEqual(len(self.tab.absorbance_spectrum.bands), 8)
        self.assertAlmostEqual(
            self.tab.absorbance_spectrum.bands[3].absorbance, 0.3010299957
        )
        self.assertEqual(self.tab.absorbance_value_label.text(), "0,30103")
        self.assertEqual(self.tab.spectra, [])
        self.assertEqual(self.tab.beer_standards, [])

    def test_absorbance_band_change_reuses_measurement_without_acquisition(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab.absorbance_measure_button.click()
        self.controller.emit_measurement((100, 100, 100, 50, 10, 100, 100, 100))
        measurement_count = len(self.controller.measurements)

        self.tab.absorbance_band_combo.setCurrentIndex(4)

        self.assertEqual(len(self.controller.measurements), measurement_count)
        self.assertEqual(self.tab.absorbance_value_label.text(), "1")
        self.assertEqual(self.tab.absorbance_wavelength_label.text(), "555 nm (F5)")

    def test_new_absorbance_acquisition_does_not_present_previous_value_as_current(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab.absorbance_measure_button.click()
        self.controller.emit_measurement(50)
        self.assertNotEqual(self.tab.absorbance_value_label.text(), "—")

        self.tab.absorbance_measure_button.click()

        self.assertIsNone(self.tab.absorbance_spectrum)
        self.assertEqual(self.tab.absorbance_value_label.text(), "—")
        self.assertEqual(self.tab.absorbance_acquisition_status.text(), "Mesure en cours…")

    def test_absorbance_displays_zero_negative_and_invalid_without_substitution(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab.absorbance_measure_button.click()
        self.controller.emit_measurement(100)
        self.assertEqual(self.tab.absorbance_value_label.text(), "0")
        self.assertEqual(self.tab.absorbance_value_label.font().pointSize(), 60)

        self.tab.absorbance_measure_button.click()
        self.controller.emit_measurement(200)
        self.assertTrue(self.tab.absorbance_value_label.text().startswith("-0,30103"))

        self.tab.absorbance_measure_button.click()
        self.controller.emit_measurement(50, saturation_flags=1 << 3)
        self.assertEqual(self.tab.absorbance_value_label.text(), "Indisponible")
        self.assertEqual(self.tab.absorbance_value_label.font().pointSize(), 32)
        self.assertIn("saturée", self.tab.absorbance_result_status.text())

    def test_absorbance_requires_calibration_and_hides_stale_result_on_disconnect(self):
        self.tab.measure_absorbance()
        self.assertEqual(self.controller.measurements, [])
        self.assertEqual(self.tab.absorbance_value_label.text(), "—")

        self.connect_and_configure()
        self.calibrate()
        self.tab.absorbance_measure_button.click()
        self.controller.emit_measurement(50)
        saved = self.tab.absorbance_spectrum
        self.tab.disconnect()

        self.assertIs(self.tab.absorbance_spectrum, saved)
        self.assertEqual(self.tab.absorbance_value_label.text(), "—")
        self.assertIn("inactive", self.tab.absorbance_result_status.text())
        self.assertFalse(self.tab.absorbance_dark_button.isHidden())
        self.assertTrue(self.tab.absorbance_recalibrate_button.isHidden())

        self.tab.connect_button.click()
        self.controller.emit_ready()
        self.controller.accept_configuration()
        self.assertIsNone(self.tab.calibration)
        self.assertFalse(self.tab.absorbance_measure_button.isEnabled())
        self.assertFalse(self.tab.absorbance_dark_button.isHidden())

    def test_absorbance_layout_remains_centered_at_target_sizes(self):
        self.tab.mode_combo.setCurrentIndex(1)
        for width, height in (
            (1280, 800),
            (1366, 768),
            (1600, 900),
            (1648, 928),
        ):
            with self.subTest(size=(width, height)):
                self.tab.resize(width, height)
                self.tab.show()
                self.app.processEvents()
                card = self.tab.findChild(QWidget, "singleAbsorbanceCard")
                self.assertTrue(card.isVisible())
                self.assertLessEqual(card.width(), 760)
                self.assertGreaterEqual(self.tab.absorbance_value_label.height(), 116)
                self.assertGreaterEqual(
                    self.tab.absorbance_value_label.font().pointSize(), 52
                )
                self.assertLessEqual(
                    self.tab.absorbance_value_label.font().pointSize(), 64
                )

    def test_beer_mode_is_active_with_exact_units_and_default_band(self):
        self.tab.mode_combo.setCurrentIndex(2)

        self.assertIs(self.tab.mode_stack.currentWidget(), self.tab.beer_main_splitter)
        self.assertEqual(
            [self.tab.beer_unit_combo.itemText(i) for i in range(4)],
            ["mol/L", "mmol/L", "g/L", "mg/L"],
        )
        self.assertEqual(self.tab.beer_unit_combo.currentText(), "mol/L")
        self.assertEqual(self.tab.beer_wavelength(), 555)
        self.assertEqual(self.tab.beer_main_splitter.count(), 2)

    def test_beer_standard_accepts_french_decimal_and_zero(self):
        zero = self.tab.add_beer_standard("Blanc gamme", "0")
        standard = self.tab.add_beer_standard("Étalon 1", "1,25")

        self.assertEqual(zero.concentration, 0.0)
        self.assertEqual(standard.concentration, 1.25)
        self.assertEqual(self.tab.beer_table.rowCount(), 2)
        self.assertTrue(
            self.tab.beer_table.item(0, 0).textAlignment()
            & Qt.AlignmentFlag.AlignLeft
        )
        self.assertTrue(
            self.tab.beer_table.item(0, 1).textAlignment()
            & Qt.AlignmentFlag.AlignRight
        )
        self.assertEqual(self.tab.beer_table.verticalHeader().defaultSectionSize(), 28)
        self.assertIsNone(self.tab.add_beer_standard("Invalide", "-1"))
        self.assertEqual(self.tab.beer_table.rowCount(), 2)

    def test_beer_standard_can_be_modified_and_deleted(self):
        standard = self.tab.add_beer_standard("S1", "1")
        self.tab.beer_table.selectRow(0)
        dialog = SimpleNamespace(
            exec=Mock(return_value=QDialog.DialogCode.Accepted),
            name_edit=SimpleNamespace(text=lambda: "S1 corrigé"),
            concentration=2.5,
        )
        with patch(
            "physalix.ui.spectrophotometry_tab.StandardEditorDialog",
            return_value=dialog,
        ):
            self.tab.edit_selected_beer_standard()
        self.assertEqual((standard.name, standard.concentration), ("S1 corrigé", 2.5))

        with patch(
            "physalix.ui.spectrophotometry_tab.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.tab.delete_selected_beer_standard()
        self.assertEqual(self.tab.beer_standards, [])

    def test_beer_table_formats_small_concentration_without_changing_it(self):
        standard = self.tab.add_beer_standard("Trace", "0,00006")

        self.assertEqual(self.tab.beer_table.item(0, 1).text(), "6,0 × 10⁻⁵")
        self.assertEqual(standard.concentration, 6e-5)

    def test_cancelled_beer_dialog_starts_no_measurement(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab.add_beer_standard("S1", "1")
        self.tab.beer_table.selectRow(0)
        self.tab._confirm_beer_measurement = Mock(return_value=False)
        count = len(self.controller.measurements)

        self.tab.measure_selected_beer_standard()

        self.assertEqual(len(self.controller.measurements), count)
        self.assertIsNone(self.tab._pending_beer_target)

    def test_beer_measurement_rechecks_controller_after_confirmation(self):
        self.connect_and_configure()
        self.calibrate()
        self.tab.add_beer_standard("S1", "1")
        self.tab.beer_table.selectRow(0)

        def disconnect_during_dialog(standard):
            self.controller.set_state(SpectroControllerState.DISCONNECTED)
            return True

        self.tab._confirm_beer_measurement = disconnect_during_dialog
        count = len(self.controller.measurements)
        self.tab.measure_selected_beer_standard()

        self.assertEqual(len(self.controller.measurements), count)
        self.assertIsNone(self.tab._pending_beer_target)
        self.assertIn("état du spectrophotomètre a changé", self.tab.measurement_status.text())

    def test_standard_measurements_keep_eight_bands_and_fit_through_origin(self):
        self.connect_and_configure()
        self.calibrate()
        first = self.add_and_measure_standard("S0", 0, 100)
        second = self.add_and_measure_standard("S1", 1, 10)

        self.assertEqual(len(first.spectrum.bands), 8)
        self.assertEqual(len(second.spectrum.bands), 8)
        self.assertAlmostEqual(self.tab.beer_regression.slope, 1.0)
        self.assertAlmostEqual(self.tab.beer_regression.intercept, 0.0)
        line_x, line_y = self.tab.beer_regression_item.getData()
        self.assertEqual((line_x[0], line_y[0]), (0.0, 0.0))
        self.assertGreaterEqual(self.tab.beer_plot.viewRange()[0][0], -1e-12)
        self.assertIn("Deux points seulement", self.tab.beer_regression_warning.text())
        self.assertEqual(len(self.tab.spectra), 0)

    def test_band_change_reuses_full_measurements_and_invalid_band_is_excluded(self):
        self.connect_and_configure()
        self.calibrate()
        first_values = (100, 100, 100, 100, 100, 50, 100, 100)
        second_values = (100, 100, 100, 100, 10, 25, 100, 100)
        self.add_and_measure_standard("S0", 0, first_values)
        self.add_and_measure_standard("S1", 1, second_values)
        slope_555 = self.tab.beer_regression.slope

        self.tab.beer_band_combo.setCurrentIndex(5)

        self.assertNotAlmostEqual(self.tab.beer_regression.slope, slope_555)
        self.assertEqual(self.tab.beer_table.item(0, 3).text(), "Valide")

        self.tab.beer_band_combo.setCurrentIndex(4)
        self.tab.beer_standards[1].spectrum = None
        self.tab._refresh_beer_ui()
        self.assertIsNone(self.tab.beer_regression)

    def test_invalid_selected_band_is_reported_and_excluded(self):
        self.connect_and_configure()
        self.calibrate()
        self.add_and_measure_standard("S0", 0, 100)
        self.add_and_measure_standard("S1", 1, 10, saturation_flags=1 << 4)

        self.assertEqual(self.tab.beer_table.item(1, 3).text(), "Bande indisponible")
        self.assertIsNone(self.tab.beer_regression)

    def test_unknown_concentration_and_extrapolation_are_displayed(self):
        self.connect_and_configure()
        self.calibrate()
        self.add_and_measure_standard("S0", 0, 100)
        self.add_and_measure_standard("S1", 1, 10)
        self.tab._confirm_beer_measurement = Mock(return_value=True)

        self.tab.measure_beer_unknown()
        self.controller.emit_measurement(1)

        self.assertIn("2", self.tab.beer_unknown_result_label.text())
        self.assertIn("mol/L", self.tab.beer_unknown_result_label.text())
        self.assertIn("hors de la gamme", self.tab.beer_unknown_warning.text())
        self.assertEqual(len(self.tab.beer_unknown_spectrum.bands), 8)
        self.assertIsNotNone(self.tab.beer_unknown_item)
        self.assertIsNotNone(self.tab.beer_unknown_horizontal)
        self.assertIsNotNone(self.tab.beer_unknown_vertical)
        horizontal_x, horizontal_y = self.tab.beer_unknown_horizontal.getData()
        vertical_x, vertical_y = self.tab.beer_unknown_vertical.getData()
        self.assertEqual(list(horizontal_x), [0.0, 2.0])
        self.assertEqual(list(horizontal_y), [2.0, 2.0])
        self.assertEqual(list(vertical_x), [2.0, 2.0])
        self.assertEqual(list(vertical_y), [0.0, 2.0])
        self.assertEqual(self.tab.beer_unknown_y_label.toPlainText(), "A = 2")
        self.assertEqual(
            self.tab.beer_unknown_x_label.toPlainText(), "c = 2 mol/L"
        )

    def test_projection_labels_use_scientific_format_and_follow_view(self):
        self.connect_and_configure()
        self.calibrate()
        self.add_and_measure_standard("S0", 0, 100)
        self.add_and_measure_standard("S1", 1e-4, 10)
        self.tab._confirm_beer_measurement = Mock(return_value=True)
        self.tab.measure_beer_unknown()
        self.controller.emit_measurement(2)

        self.assertEqual(
            self.tab.beer_unknown_x_label.toPlainText(),
            "c = 1,70 × 10⁻⁴ mol/L",
        )
        self.assertEqual(self.tab.beer_unknown_y_label.toPlainText(), "A = 1,699")
        for width, height in ((900, 650), (1280, 800), (1600, 900)):
            with self.subTest(size=(width, height)):
                self.tab.resize(width, height)
                self.tab.show()
                self.app.processEvents()
                self.tab.beer_plot.setRange(
                    xRange=(0, 2.2e-4), yRange=(0, 2.1), padding=0
                )
                self.app.processEvents()
                x_range, y_range = self.tab.beer_plot.viewRange()
                x_position = self.tab.beer_unknown_x_label.pos()
                y_position = self.tab.beer_unknown_y_label.pos()
                self.assertGreaterEqual(x_position.x(), x_range[0])
                self.assertLessEqual(x_position.x(), x_range[1])
                self.assertGreaterEqual(y_position.y(), y_range[0])
                self.assertLessEqual(y_position.y(), y_range[1])
                self.assertLessEqual(
                    x_position.y(), y_range[0] + 0.05 * (y_range[1] - y_range[0])
                )
                self.assertLessEqual(
                    y_position.x(), x_range[0] + 0.05 * (x_range[1] - x_range[0])
                )

    def test_projection_labels_update_when_band_changes(self):
        self.connect_and_configure()
        self.calibrate()
        self.add_and_measure_standard("S0", 0, (100,) * 8)
        self.add_and_measure_standard(
            "S1", 1e-4, (10, 10, 10, 10, 10, 25, 10, 10)
        )
        self.tab._confirm_beer_measurement = Mock(return_value=True)
        self.tab.measure_beer_unknown()
        self.controller.emit_measurement((2, 2, 2, 2, 2, 50, 2, 2))
        previous_x = self.tab.beer_unknown_x_label.toPlainText()
        previous_y = self.tab.beer_unknown_y_label.toPlainText()

        self.tab.beer_band_combo.setCurrentIndex(5)

        self.assertNotEqual(self.tab.beer_unknown_x_label.toPlainText(), previous_x)
        self.assertNotEqual(self.tab.beer_unknown_y_label.toPlainText(), previous_y)
        self.assertIn("mol/L", self.tab.beer_unknown_x_label.toPlainText())
        self.assertIn("× 10⁻⁵", self.tab.beer_unknown_x_label.toPlainText())

    def test_negative_unknown_is_rejected_without_graphic_marker(self):
        self.connect_and_configure()
        self.calibrate()
        self.add_and_measure_standard("S0", 0, 100)
        self.add_and_measure_standard("S1", 1, 10)
        self.tab._confirm_beer_measurement = Mock(return_value=True)

        self.tab.measure_beer_unknown()
        self.controller.emit_measurement(200)

        self.assertEqual(
            self.tab.beer_unknown_result_label.text(), "Concentration : —"
        )
        self.assertIn("négative", self.tab.beer_unknown_warning.text())
        self.assertIsNone(self.tab.beer_unknown_item)
        self.assertIsNone(self.tab.beer_unknown_horizontal)
        self.assertIsNone(self.tab.beer_unknown_vertical)
        self.assertIsNone(self.tab.beer_unknown_x_label)
        self.assertIsNone(self.tab.beer_unknown_y_label)

    def test_transfer_confirmation_has_requested_text_and_french_buttons(self):
        captured = {}

        def inspect_and_reject():
            dialog = QApplication.activeModalWidget()
            captured["text"] = dialog.text()
            captured["buttons"] = {
                button.text() for button in dialog.findChildren(QPushButton)
            }
            next(
                button
                for button in dialog.findChildren(QPushButton)
                if button.text() == "Non"
            ).click()

        QTimer.singleShot(0, inspect_and_reject)
        self.assertFalse(
            SpectrophotometryTab._confirm_beer_transfer(self.tab)
        )
        self.assertEqual(
            captured["text"],
            "Les concentrations et les absorbances mesurées seront transférées "
            "dans Données. Un graphique avec la droite d'étalonnage sera "
            "automatiquement créé.\n\nVoulez-vous continuer ?",
        )
        self.assertIn("Oui", captured["buttons"])
        self.assertIn("Non", captured["buttons"])
        self.assertNotIn("Yes", captured["buttons"])
        self.assertNotIn("No", captured["buttons"])

    def test_unit_change_requires_explicit_reset_or_restores_selection(self):
        self.tab.add_beer_standard("S1", "1")
        with patch(
            "physalix.ui.spectrophotometry_tab.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            self.tab.beer_unit_combo.setCurrentIndex(1)
        self.assertEqual(self.tab.beer_unit_combo.currentText(), "mol/L")
        self.assertEqual(len(self.tab.beer_standards), 1)

        with patch(
            "physalix.ui.spectrophotometry_tab.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.tab.beer_unit_combo.setCurrentIndex(1)
        self.assertEqual(self.tab.beer_unit_combo.currentText(), "mmol/L")
        self.assertEqual(self.tab.beer_standards, [])

    def test_transfer_appends_valid_points_creates_graph_and_selects_tab(self):
        self.connect_and_configure()
        self.calibrate()
        self.add_and_measure_standard("S0", 0, 100)
        self.add_and_measure_standard("S1", 1, 10)

        result = self.tab.transfer_beer_to_graph()

        self.assertEqual(result[0], (6, 7))
        self.assertEqual(len(self.data_tab.calls), 1)
        names, units, rows = self.data_tab.calls[0]
        self.assertIn("555 nm", names[0])
        self.assertEqual(units, ["mol/L", ""])
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            self.graph_workspace.calls,
            [(6, 7, "linear", "Beer-Lambert à 555 nm")],
        )
        self.show_graph.assert_called_once_with()
        self.assertFalse(self.tab.beer_transfer_button.isEnabled())

    def test_transfer_retry_after_graph_error_does_not_duplicate_columns(self):
        self.connect_and_configure()
        self.calibrate()
        self.add_and_measure_standard("S0", 0, 100)
        self.add_and_measure_standard("S1", 1, 10)
        original = self.graph_workspace.add_data_graph_with_model
        self.graph_workspace.add_data_graph_with_model = Mock(
            side_effect=RuntimeError("échec")
        )

        with patch("physalix.ui.spectrophotometry_tab.QMessageBox.warning"):
            self.assertIsNone(self.tab.transfer_beer_to_graph())
        self.assertEqual(len(self.data_tab.calls), 1)

        self.graph_workspace.add_data_graph_with_model = original
        self.assertIsNotNone(self.tab.transfer_beer_to_graph())
        self.assertEqual(len(self.data_tab.calls), 1)

    def test_cancelled_transfer_does_not_modify_data(self):
        self.connect_and_configure()
        self.calibrate()
        self.add_and_measure_standard("S0", 0, 100)
        self.add_and_measure_standard("S1", 1, 10)
        self.tab._confirm_beer_transfer = Mock(return_value=False)

        self.assertIsNone(self.tab.transfer_beer_to_graph())
        self.assertEqual(self.data_tab.calls, [])
        self.assertEqual(self.graph_workspace.calls, [])

    def test_new_calibration_keeps_history_but_marks_it_inactive(self):
        self.connect_and_configure()
        self.calibrate()
        standard = self.add_and_measure_standard("S1", 1, 10)

        self.tab.dark_button.click()
        self.controller.emit_measurement(0)

        self.assertIsNotNone(standard.spectrum)
        self.assertEqual(self.tab.beer_table.item(0, 3).text(), "Référence inactive")
        self.assertIsNone(self.tab.beer_regression)


class MeasurementPreparationDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def texts(dialog):
        return [widget.text() for widget in dialog.findChildren(QLabel)]

    def test_dark_dialog_has_exact_preparation_content(self):
        dialog = MeasurementPreparationDialog(MeasurementKind.DARK)
        try:
            self.assertEqual(dialog.windowTitle(), "Mesure du noir")
            texts = self.texts(dialog)
            self.assertIn(
                "Cette mesure détermine le signal du capteur en absence d'éclairage.",
                texts,
            )
            self.assertIn("Retirez la cuve du spectrophotomètre.", texts)
            self.assertIn("La LED restera éteinte pendant cette mesure.", texts)
            self.assertEqual(dialog.cancel_button.text(), "Annuler")
            self.assertEqual(dialog.accept_button.text(), "Valider et mesurer")
        finally:
            dialog.deleteLater()

    def test_white_dialog_has_exact_preparation_content(self):
        dialog = MeasurementPreparationDialog(MeasurementKind.WHITE)
        try:
            self.assertEqual(dialog.windowTitle(), "Mesure du blanc")
            texts = self.texts(dialog)
            self.assertIn(
                "Cette mesure définit la référence lumineuse utilisée pour "
                "calculer l'absorbance.",
                texts,
            )
            self.assertIn(
                "Insérez une cuve contenant de l'eau distillée ou le solvant "
                "de référence.",
                texts,
            )
            self.assertNotIn("La LED restera éteinte pendant cette mesure.", texts)
        finally:
            dialog.deleteLater()

    def test_validation_accepts_dialog(self):
        dialog = MeasurementPreparationDialog(MeasurementKind.DARK)
        dialog.accept_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        dialog.deleteLater()

    def test_cancel_and_window_close_reject_dialog(self):
        for action in ("cancel", "close"):
            with self.subTest(action=action):
                dialog = MeasurementPreparationDialog(MeasurementKind.WHITE)
                dialog.show()
                self.app.processEvents()
                if action == "cancel":
                    dialog.cancel_button.click()
                else:
                    dialog.close()
                self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
                dialog.deleteLater()

    def test_kinetic_dialog_explains_time_origin_and_has_expected_actions(self):
        dialog = KineticsPreparationDialog()
        try:
            texts = self.texts(dialog)
            self.assertEqual(dialog.windowTitle(), "Démarrer la cinétique")
            self.assertTrue(any("mélange à suivre" in text for text in texts))
            self.assertTrue(any("t = 0" in text for text in texts))
            self.assertEqual(dialog.cancel_button.text(), "Annuler")
            self.assertEqual(dialog.start_button.text(), "Démarrer l'acquisition")
            dialog.cancel_button.click()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        finally:
            dialog.deleteLater()


class BeerLambertDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_standard_preparation_displays_name_concentration_and_buttons(self):
        standard = SimpleNamespace(name="S1", concentration=1.25)
        dialog = BeerLambertPreparationDialog(standard, unit="mmol/L")
        try:
            texts = [widget.text() for widget in dialog.findChildren(QLabel)]
            self.assertIn(
                "Insérez la cuve contenant la solution étalon S1, de concentration "
                "1.25 mmol/L.",
                texts,
            )
            self.assertEqual(dialog.cancel_button.text(), "Annuler")
            self.assertEqual(dialog.accept_button.text(), "Valider et mesurer")
        finally:
            dialog.deleteLater()

    def test_unknown_preparation_and_cancel(self):
        dialog = BeerLambertPreparationDialog()
        try:
            texts = [widget.text() for widget in dialog.findChildren(QLabel)]
            self.assertIn(
                "Insérez la cuve contenant la solution de concentration inconnue.",
                texts,
            )
            dialog.cancel_button.click()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        finally:
            dialog.deleteLater()

    def test_standard_editor_validates_french_concentration(self):
        dialog = StandardEditorDialog("mol/L")
        try:
            dialog.name_edit.setText("Étalon")
            dialog.concentration_edit.setText("0,25")
            dialog.accept_button.click()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.concentration, 0.25)
        finally:
            dialog.deleteLater()

    def test_standard_editor_uses_the_same_dialog_presentation(self):
        parent = QWidget()
        editor = StandardEditorDialog("mol/L", parent=parent)
        preparation = BeerLambertPreparationDialog(parent=parent)
        try:
            self.assertTrue(editor.windowFlags() & Qt.WindowType.Dialog)
            self.assertEqual(editor.parent(), parent)
            self.assertEqual(
                editor.layout().contentsMargins(),
                preparation.layout().contentsMargins(),
            )
            titles = [
                widget
                for widget in editor.findChildren(QLabel)
                if widget.property("role") == "sectionTitle"
            ]
            self.assertEqual([widget.text() for widget in titles], ["Ajouter un étalon"])
            self.assertEqual(editor.accept_button.property("role"), "primary")
            self.assertEqual(editor.cancel_button.text(), "Annuler")
        finally:
            editor.deleteLater()
            preparation.deleteLater()
            parent.deleteLater()


class SpectrophotometryNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tab_is_added_after_acquisition(self):
        window = MainWindow()
        try:
            self.assertIs(window.tabs.widget(window.tabs.count() - 2), window.acquisition_tab)
            self.assertIs(
                window.tabs.widget(window.tabs.count() - 1),
                window.spectrophotometry_tab,
            )
            self.assertEqual(
                window.tabs.tabText(window.tabs.count() - 1), "Spectrophotométrie"
            )
            self.assertEqual(
                window.navigation_buttons[-1].toolTip(), "Spectrophotométrie"
            )
            self.assertFalse(window.navigation_buttons[-1].icon().isNull())
        finally:
            window._discard_on_close = True
            window.close()


class SpectrophotometryFirmwareUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = FakeSpectroController()
        self.flash = FakeSpectroFirmwareFlash()
        self.tab = SpectrophotometryTab(
            self.controller,
            firmware_flash=self.flash,
            firmware_resource_loader=lambda: self.flash.resources,
        )

    def tearDown(self):
        self.tab.shutdown()
        self.tab.deleteLater()
        self.app.processEvents()

    def test_advanced_section_displays_target_version_and_bootloaders(self):
        self.assertEqual(self.tab.firmware_board_label.text(), "Arduino Nano · ATmega328P · 5 V")
        self.assertEqual(self.tab.firmware_embedded_label.text(), "1.0.0")
        self.assertEqual(
            [self.tab.nano_bootloader_combo.itemData(index)
             for index in range(self.tab.nano_bootloader_combo.count())],
            [NanoBootloader.RECENT, NanoBootloader.OLD],
        )
        self.tab.connect_button.click()
        self.controller.emit_ready()
        self.assertIn("à jour", self.tab.firmware_status_label.text())
        self.assertEqual(self.tab.firmware_button.text(), "Réinstaller le micrologiciel…")

    def test_confirmation_cancel_and_busy_state_start_no_flash(self):
        with patch.object(self.tab, "_confirm_firmware_flash", return_value=False):
            self.tab.firmware_button.click()
        self.assertFalse(self.flash.start_calls)
        self.tab.connect_button.click()
        self.controller.emit_ready()
        self.controller.accept_configuration()
        self.controller.set_state(SpectroControllerState.MEASURING)
        self.tab._update_controls()
        self.assertFalse(self.tab.firmware_button.isEnabled())

    def test_active_flash_can_be_cancelled_without_touching_another_port(self):
        with patch.object(self.tab, "_confirm_firmware_flash", return_value=True):
            self.tab.firmware_button.click()
        self.assertEqual(self.tab._flash_port, "COM4")
        self.tab.request_firmware_installation()
        self.assertFalse(self.tab._flash_workflow_active)
        self.assertEqual(self.flash.shutdown_calls, 1)
        self.assertIn("annulée", self.tab.firmware_status_label.text())

    def test_explicit_old_bootloader_flash_reconnects_and_invalidates_only_calibration(self):
        self.tab.nano_bootloader_combo.setCurrentIndex(1)
        preserved = object()
        self.tab.spectra = [preserved]
        with patch.object(self.tab, "_confirm_firmware_flash", return_value=True):
            self.tab.firmware_button.click()
        self.tab.firmware_port_release_timer.stop()
        self.tab._start_firmware_flash()
        self.assertEqual(
            self.flash.start_calls, [("COM4", NanoBootloader.OLD)]
        )
        self.tab.dark_measurement = object()
        self.tab.white_measurement = object()
        self.tab.calibration = object()
        self.flash.emit_upload_verified()
        self.assertIsNone(self.tab.calibration)
        self.assertEqual(self.tab.spectra, [preserved])
        self.tab.firmware_reconnect_timer.stop()
        self.tab._attempt_firmware_reconnect()
        self.controller.emit_ready()
        self.assertEqual(self.flash.confirm_calls[-1], ((1, 0, 0), 1, 0x1F))
        self.assertFalse(self.tab._flash_workflow_active)
        self.assertIn("vérifiée et prête", self.tab.firmware_status_label.text())
        self.assertIsNotNone(self.tab.session_id)
        self.controller.accept_configuration()

        # L'expérience historique reste disponible, puis la nouvelle session
        # doit pouvoir enchaîner noir, blanc et échantillon sans redémarrage.
        self.assertEqual(self.tab.spectra, [preserved])
        self.tab.spectra = []
        self.tab._confirm_measurement_preparation = lambda _kind: True
        self.tab.dark_button.click()
        self.controller.emit_measurement(0)
        self.tab.white_button.click()
        self.controller.emit_measurement(100)
        self.assertIsNotNone(self.tab.calibration)
        self.tab.sample_button.click()
        self.controller.emit_measurement(10)
        self.assertEqual(len(self.tab.spectra), 1)

    def test_missing_post_flash_handshake_is_not_reported_as_success(self):
        with patch.object(self.tab, "_confirm_firmware_flash", return_value=True):
            self.tab.firmware_button.click()
        self.tab.firmware_port_release_timer.stop()
        self.tab._start_firmware_flash()
        self.flash.emit_upload_verified()
        self.tab._flash_reconnect_opened = True
        self.tab._firmware_reconnect_timed_out()
        self.assertTrue(self.flash.verification_failures)
        self.assertIn("pas été identifié", self.flash.verification_failures[-1][0])
        self.assertIsNone(self.tab.session_id)
        self.assertEqual(self.controller.configurations, [])

class SpectrophotometryNavigationAdditionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_help_menu_contains_discreet_disabled_diagnostic_action(self):
        window = MainWindow()
        try:
            help_menu = next(
                action.menu()
                for action in window.menuBar().actions()
                if action.text() == "Aide"
            )
            tools_action = next(
                action
                for action in help_menu.actions()
                if action.text() == "Outils de diagnostic"
            )
            self.assertEqual(
                [action.text() for action in tools_action.menu().actions()],
                ["Exporter le diagnostic cinétique…"],
            )
            self.assertFalse(window.kinetic_diagnostic_export_action.isEnabled())
        finally:
            window._discard_on_close = True
            window.close()

    def test_diagnostic_menu_action_reuses_current_tab_export(self):
        window = MainWindow()
        try:
            with patch.object(
                window.spectrophotometry_tab,
                "export_kinetic_diagnostic",
            ) as export:
                window.kinetic_diagnostic_export_action.setEnabled(True)
                window.kinetic_diagnostic_export_action.trigger()
                export.assert_called_once_with()

            window.spectrophotometry_tab.kinetic_journal = SimpleNamespace(
                finished=True
            )
            window.spectrophotometry_tab._update_controls()
            self.assertTrue(window.kinetic_diagnostic_export_action.isEnabled())
            window.spectrophotometry_tab._kinetic_active = True
            window.spectrophotometry_tab._update_controls()
            self.assertFalse(window.kinetic_diagnostic_export_action.isEnabled())
            window.spectrophotometry_tab._kinetic_active = False
            window.spectrophotometry_tab.kinetic_journal = None
        finally:
            window._discard_on_close = True
            window.close()

    def test_project_replacement_shuts_down_old_spectro_tab(self):
        window = MainWindow()
        old_tab = window.spectrophotometry_tab
        try:
            with patch.object(old_tab, "shutdown", wraps=old_tab.shutdown) as shutdown:
                self.assertTrue(window.replace_project())
                shutdown.assert_called_once_with()
            self.assertIsNot(window.spectrophotometry_tab, old_tab)
            window.spectrophotometry_tab.kinetic_journal = SimpleNamespace(
                finished=True
            )
            window.spectrophotometry_tab._update_controls()
            self.assertTrue(window.kinetic_diagnostic_export_action.isEnabled())
        finally:
            window._discard_on_close = True
            window.close()


if __name__ == "__main__":
    unittest.main()
