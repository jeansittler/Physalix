"""Tests Qt ciblés de l'interface Spectre."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, QTimer, Signal
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
    SpectroData,
    SpectroFirmwareInfo,
    SpectroIllumination,
    SpectroSensorType,
)
from physalix.spectrophotometry_serial import SpectroControllerState
from physalix.ui.graph_series import PopupComboBox
from physalix.ui.main_window import MainWindow
from physalix.ui.spectrophotometry_tab import (
    BeerLambertPreparationDialog,
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


class SpectrophotometryTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
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
        )
        self.tab._confirm_measurement_preparation = lambda kind: True
        self.tab._confirm_beer_transfer = lambda: True

    def tearDown(self):
        self.tab.shutdown()
        self.tab.deleteLater()
        self.app.processEvents()

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

    def test_creation_is_idle_and_uses_expected_layout_components(self):
        self.assertIsNone(self.controller.opened_port)
        self.assertEqual(self.tab.port_combo.currentData(), "COM4")
        self.assertIsInstance(self.tab.port_combo, PopupComboBox)
        self.assertIsInstance(self.tab.mode_combo, PopupComboBox)
        self.assertTrue(self.tab.mode_combo.model().item(1).isEnabled())
        self.assertTrue(self.tab.mode_combo.model().item(2).isEnabled())
        self.assertEqual(self.tab.mode_combo.count(), 3)
        self.assertFalse(self.tab.advanced_content.isVisible())
        self.assertEqual(self.tab.main_splitter.count(), 2)
        self.assertCountEqual(
            self.tab.findChildren(QScrollArea),
            [self.tab.settings_scroll, self.tab.beer_settings_scroll],
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

    def test_dark_white_sample_workflow_creates_eight_points(self):
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
        self.assertEqual(len(display.interpolation_items), 1)
        self.assertEqual(len(display.fill_items), 1)
        self.assertEqual(display.fill_items[0].path().boundingRect().left(), 415)
        self.assertEqual(display.fill_items[0].path().boundingRect().right(), 680)
        self.assertGreater(display.experimental_item.zValue(), display.fill_items[0].zValue())
        self.assertGreater(display.interpolation_items[0].zValue(), display.fill_items[0].zValue())

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

    def test_multiple_spectra_can_be_renamed_and_hidden(self):
        self.connect_and_configure()
        self.calibrate()
        self.measure_sample(10)
        self.measure_sample(20)

        self.assertEqual(len(self.tab.spectra), 2)
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

        self.tab.shutdown()

        self.assertEqual(self.controller.state, SpectroControllerState.DISCONNECTED)
        self.assertFalse(self.tab.disconnect_timer.isActive())
        self.assertIsNone(self.tab.calibration)

    def test_absorbance_is_the_second_mode_with_eight_real_bands(self):
        self.assertEqual(
            [self.tab.mode_combo.itemText(i) for i in range(3)],
            ["Spectre", "Absorbance", "Beer-Lambert"],
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

    def test_project_replacement_shuts_down_old_spectro_tab(self):
        window = MainWindow()
        old_tab = window.spectrophotometry_tab
        try:
            with patch.object(old_tab, "shutdown", wraps=old_tab.shutdown) as shutdown:
                self.assertTrue(window.replace_project())
                shutdown.assert_called_once_with()
            self.assertIsNot(window.spectrophotometry_tab, old_tab)
        finally:
            window._discard_on_close = True
            window.close()


if __name__ == "__main__":
    unittest.main()
