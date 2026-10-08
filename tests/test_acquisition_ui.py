"""Tests fonctionnels ciblés de l'onglet Acquisition."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QSplitter, QVBoxLayout

from physalix.acquisition import (
    AcquisitionConfig, AcquisitionResult, AcquisitionStarted, AcquisitionState,
    CAPABILITY_CONTINUOUS_SQUARE, CAPABILITY_SQUARE_BURST, ContinuousSquareConfig,
    DataBatch, DigitalStepConfig, FirmwareInfo, GbfDataBatch, GenerationType,
    GeneratorState, SERIAL_RESOURCE_DISCONNECTED_MESSAGE, SquareBurstConfig,
    plan_continuous_square,
)
from physalix.ui.acquisition_tab import (
    CONTINUOUS_SQUARE_MODE, AcquisitionTab, adc_to_volts,
)
from physalix.ui.graph_series import PopupComboBox
from physalix.ui.main_window import MainWindow
from physalix.ui.theme import LIGHT


class FakeController(QObject):
    state_changed = Signal(object)
    ready = Signal(object)
    configuration_accepted = Signal(object)
    data_batch_received = Signal(object)
    acquisition_finished = Signal(object)
    generator_state_changed = Signal(object)
    generator_configured = Signal(object)
    acquisition_armed = Signal(object)
    acquisition_triggered = Signal(object)
    error_occurred = Signal(str)

    def __init__(self):
        super().__init__()
        self.state = AcquisitionState.DISCONNECTED
        self.config = None
        self.samples = []
        self.generated_high = []
        self.generator_state = GeneratorState.UNKNOWN
        self.generator_plan = None
        self.opened_port = None
        self.stop_calls = 0
        self.configure_generator_calls = []
        self.start_generator_calls = 0
        self.stop_generator_calls = 0
        self.shutdown_generator_calls = 0

    def set_state(self, state):
        self.state = state
        self.state_changed.emit(state)

    def open(self, port_name):
        self.opened_port = port_name
        self.set_state(AcquisitionState.WAITING_HANDSHAKE)
        return True

    def close(self):
        self.generator_state = GeneratorState.UNKNOWN
        self.generator_state_changed.emit(self.generator_state)
        self.set_state(AcquisitionState.DISCONNECTED)

    def configure(self, config):
        self.config = config

    def start(self):
        if self.generator_state is GeneratorState.RUNNING:
            self.set_state(AcquisitionState.ARMED)
            self.acquisition_armed.emit(42)
        else:
            self.set_state(AcquisitionState.ACQUIRING)
        return 42

    def stop(self):
        if self.state not in (AcquisitionState.ARMED, AcquisitionState.ACQUIRING):
            return False
        self.stop_calls += 1
        self.set_state(AcquisitionState.STOPPING)
        return True

    @property
    def generator_ready_for_flash(self):
        return self.generator_state is GeneratorState.STOPPED

    def set_generator_state(self, state):
        self.generator_state = state
        self.generator_state_changed.emit(state)

    def configure_generator(self, config):
        self.configure_generator_calls.append(config)

    def start_generator(self):
        self.start_generator_calls += 1

    def stop_generator(self):
        if self.generator_state is not GeneratorState.RUNNING:
            return False
        self.stop_generator_calls += 1
        return True

    def request_generator_shutdown(self):
        self.shutdown_generator_calls += 1
        return self.generator_state is GeneratorState.STOPPED


class AcquisitionTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = FakeController()
        self.tab = AcquisitionTab(self.controller)

    def tearDown(self):
        self.tab.shutdown()
        self.tab.deleteLater()
        self.app.processEvents()

    def make_ready(self):
        self.controller.set_state(AcquisitionState.READY)
        self.controller.ready.emit(FirmwareInfo((1, 0, 0), 0))

    def test_layout_keeps_plot_fixed_beside_locally_scrollable_settings(self):
        self.assertIsInstance(self.tab.main_splitter, QSplitter)
        self.assertEqual(self.tab.main_splitter.orientation(), Qt.Orientation.Horizontal)
        self.assertEqual(self.tab.main_splitter.count(), 2)
        self.assertIs(self.tab.main_splitter.widget(1), self.tab.settings_column)
        self.assertIsInstance(self.tab.settings_scroll, QScrollArea)
        self.assertTrue(self.tab.settings_scroll.widgetResizable())
        self.assertFalse(
            self.tab.settings_scroll.widget().isAncestorOf(self.tab.start_button))
        self.assertEqual(self.tab.findChildren(QScrollArea), [self.tab.settings_scroll])

        for width, height in ((1366, 768), (1920, 1080)):
            with self.subTest(size=(width, height)):
                self.tab.resize(width, height)
                self.tab.show()
                self.app.processEvents()
                plot_width = self.tab.main_splitter.widget(0).width()
                settings_width = self.tab.main_splitter.widget(1).width()
                self.assertGreater(plot_width, settings_width)
                self.assertGreaterEqual(self.tab.plot.height(), 300)
                self.assertTrue(self.tab.start_button.isVisible())
                self.assertTrue(self.tab.transfer_button.isVisible())

    def accept_config(self, period_us=10_000, count=101):
        config = AcquisitionConfig(period_us, count, 0, DigitalStepConfig(8, False, True, 0))
        self.controller.config = config
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.configuration_accepted.emit(config)
        return config

    def test_duration_points_period_and_frequency(self):
        self.tab.duration_spin.setValue(2.0)
        self.tab.points_spin.setValue(201)
        self.assertEqual(self.tab.requested_period_us(), 10_000)
        self.assertEqual(self.tab.requested_config().sample_count, 201)
        self.assertEqual(self.tab.requested_te_label.text(), "10 ms")
        self.assertEqual(self.tab.requested_fe_label.text(), "100 Hz")

    def test_applied_period_is_displayed_and_used(self):
        self.make_ready()
        self.tab.start_button.click()
        self.accept_config(10_004, 101)
        self.assertEqual(self.controller.state, AcquisitionState.ACQUIRING)
        self.assertIn("10.004 ms", self.tab.applied_values_label.text())
        self.assertIn("99.96", self.tab.applied_values_label.text())
        self.assertIn("1.0004 s", self.tab.applied_values_label.text())

    def test_commands_follow_controller_state_and_stop_is_single(self):
        self.assertFalse(self.tab.start_button.isEnabled())
        self.assertFalse(self.tab.stop_button.isEnabled())
        self.make_ready()
        self.assertTrue(self.tab.start_button.isEnabled())
        self.tab.start_button.click()
        self.accept_config()
        self.assertFalse(self.tab.start_button.isEnabled())
        self.assertFalse(self.tab.duration_spin.isEnabled())
        self.assertTrue(self.tab.stop_button.isEnabled())
        self.tab.stop_button.click()
        self.tab.stop_button.click()
        self.assertEqual(self.controller.stop_calls, 1)

    def test_data_accumulates_and_converts_without_document_model(self):
        self.make_ready()
        self.tab.start_button.click()
        self.accept_config(1000, 4)
        self.controller.samples.extend((0, 512, 1023))
        self.controller.data_batch_received.emit(DataBatch(42, 0, 0, (0, 512, 1023)))
        self.assertEqual(self.tab.times_s, [0.0, 0.001, 0.002])
        self.assertEqual(self.tab.voltages_v[0], 0.0)
        self.assertAlmostEqual(self.tab.voltages_v[1], 512 * 5.0 / 1023)
        self.assertEqual(self.tab.voltages_v[2], 5.0)
        self.assertFalse(hasattr(self.tab, "model"))
        self.assertAlmostEqual(adc_to_volts(1023), 5.0)

    def test_complete_and_partial_results_are_kept(self):
        self.make_ready()
        self.tab.start_button.click()
        self.accept_config(1000, 2)
        self.controller.samples.extend((100, 200))
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.acquisition_finished.emit(AcquisitionResult(42, (100, 200), True, ""))
        self.assertTrue(self.tab.results[-1].complete)
        self.assertEqual(len(self.tab.results[-1].times_s), 2)

        self.controller.samples[:] = [300]
        self.controller.set_state(AcquisitionState.ACQUIRING)
        self.tab.disconnect()
        self.assertFalse(self.tab.results[-1].complete)
        self.assertIn("déconnexion", self.tab.results[-1].status)
        self.assertEqual(self.controller.state, AcquisitionState.DISCONNECTED)

    def test_error_disconnect_preserves_partial_and_allows_reconnect(self):
        self.controller.config = AcquisitionConfig(
            1000, 2, 0, DigitalStepConfig(8, False, True, 0))
        self.controller.samples[:] = [400]
        self.controller.set_state(AcquisitionState.ACQUIRING)
        self.controller.set_state(AcquisitionState.ERROR)
        self.controller.error_occurred.emit(SERIAL_RESOURCE_DISCONNECTED_MESSAGE)
        self.assertFalse(self.tab.results[-1].complete)
        self.assertEqual(self.tab.results[-1].voltages_v, (400 * 5.0 / 1023,))
        self.assertEqual(self.tab.connect_button.text(), "Connecter")
        self.assertEqual(
            self.tab.connection_status.text(),
            "Erreur — Arduino déconnecté. Les données déjà acquises ont été conservées.",
        )
        self.tab.port_combo.addItem("COM9", "COM9")
        self.tab.connect_button.click()
        self.assertEqual(self.controller.state, AcquisitionState.WAITING_HANDSHAKE)

    def test_error_disconnect_without_acquisition_has_clean_message(self):
        self.make_ready()
        self.controller.set_state(AcquisitionState.ERROR)
        self.controller.error_occurred.emit(SERIAL_RESOURCE_DISCONNECTED_MESSAGE)

        self.assertEqual(self.tab.connection_status.text(), "Erreur — Arduino déconnecté.")
        self.assertEqual(self.tab.results, [])


class SquareBurstUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = FakeController()
        self.tab = AcquisitionTab(self.controller)

    def tearDown(self):
        self.tab.shutdown()
        self.tab.deleteLater()
        self.app.processEvents()

    def ready(self, version=(1, 1, 0), capabilities=0x0F):
        self.controller.set_state(AcquisitionState.READY)
        self.controller.ready.emit(FirmwareInfo(version, capabilities))

    def select_square(self):
        self.tab.generation_type_combo.setCurrentIndex(1)
        self.assertEqual(self.tab.generation_type(), GenerationType.SQUARE_BURST)

    def accept(self, config):
        self.controller.config = config
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.configuration_accepted.emit(config)

    def configure_square(self, *, duration=0.008, points=9, periods=2,
                         period_us=1000, half_samples=2):
        self.ready()
        self.select_square()
        self.tab.duration_spin.setValue(duration)
        self.tab.points_spin.setValue(points)
        self.tab.square_periods_spin.setValue(periods)
        self.tab.start_button.click()
        config = AcquisitionConfig(
            period_us, 2 * periods * half_samples + 1, 0,
            SquareBurstConfig(8, False, True, periods, half_samples))
        self.accept(config)
        return config

    def test_step_remains_default_and_switching_toggles_specific_fields(self):
        self.ready()
        self.assertEqual(self.tab.generation_type(), GenerationType.STEP)
        self.assertFalse(self.tab.step_initial_value.isHidden())
        self.assertTrue(self.tab.square_periods_spin.isHidden())
        self.assertIsInstance(self.tab.square_minimum_value, QLabel)
        self.assertIsInstance(self.tab.square_maximum_value, QLabel)

        self.select_square()
        self.assertTrue(self.tab.step_initial_value.isHidden())
        self.assertFalse(self.tab.square_periods_spin.isHidden())
        self.assertEqual(self.tab.square_minimum_value.text(), "0,0 V")
        self.assertEqual(self.tab.square_maximum_value.text(), "5,0 V")

        self.tab.generation_type_combo.setCurrentIndex(0)
        self.assertEqual(self.tab.generation_type(), GenerationType.STEP)
        self.assertFalse(self.tab.step_initial_value.isHidden())
        self.assertTrue(self.tab.square_periods_spin.isHidden())
        self.assertIsInstance(self.tab.requested_config().generation, DigitalStepConfig)

    def test_generation_type_uses_graph_popup_and_supports_keyboard_and_mouse(self):
        combo = self.tab.generation_type_combo
        self.assertIsInstance(combo, PopupComboBox)
        self.assertEqual(combo.maxVisibleItems(), 8)
        self.assertGreaterEqual(combo.view().minimumWidth(), LIGHT.field_medium)
        row_height = combo.view().sizeHintForRow(0)
        self.assertEqual(
            combo.view().height(),
            3 * row_height + 2 * (LIGHT.small + combo.view().frameWidth()),
        )

        combo.setFocus()
        QTest.keyClick(combo, Qt.Key.Key_Down)
        self.assertEqual(combo.currentData(), GenerationType.SQUARE_BURST)

        combo.setCurrentIndex(0)
        combo.showPopup()
        self.app.processEvents()
        square_index = combo.model().index(1, 0)
        QTest.mouseClick(
            combo.view().viewport(), Qt.MouseButton.LeftButton,
            pos=combo.view().visualRect(square_index).center(),
        )
        self.assertEqual(combo.currentData(), GenerationType.SQUARE_BURST)

    def test_requested_square_uses_plan_and_adjusts_points(self):
        self.ready()
        self.select_square()
        self.tab.duration_spin.setValue(2.0)
        self.tab.points_spin.setValue(200)
        self.tab.square_periods_spin.setValue(2)

        config = self.tab.requested_config()

        self.assertIsInstance(config.generation, SquareBurstConfig)
        self.assertEqual(config.generation.period_count, 2)
        self.assertEqual(config.generation.half_period_samples, 50)
        self.assertEqual(config.sample_count, 201)
        self.assertEqual(config.sampling_period_us, 10_000)
        self.assertEqual(self.tab.square_requested_period_label.text(), "1 s")
        self.assertEqual(self.tab.square_requested_frequency_label.text(), "1 Hz")

    def test_square_capability_gates_start_without_blocking_step(self):
        self.ready((1, 0, 0), 0x07)
        self.assertTrue(self.tab.start_button.isEnabled())
        self.assertEqual(self.tab._firmware_mode, "older")
        self.assertIn("mise à jour disponible", self.tab.firmware_status.text())

        self.select_square()
        self.assertFalse(self.tab.start_button.isEnabled())
        self.assertIn("1.1.0", self.tab.square_requirement_label.text())

        self.controller.ready.emit(FirmwareInfo((1, 1, 0), 0x07 | CAPABILITY_SQUARE_BURST))
        self.assertTrue(self.tab.start_button.isEnabled())
        self.assertTrue(self.tab.square_requirement_label.isHidden())

    def test_square_config_is_sent_then_applied_values_drive_start(self):
        self.ready()
        self.select_square()
        self.tab.duration_spin.setValue(2.0)
        self.tab.points_spin.setValue(200)
        self.tab.square_periods_spin.setValue(2)

        self.tab.start_button.click()
        requested = self.controller.config
        self.assertIsInstance(requested.generation, SquareBurstConfig)
        self.assertEqual(requested.sample_count, 201)
        self.assertEqual(requested.generation.half_period_samples, 50)
        self.assertEqual(self.controller.state, AcquisitionState.READY)

        applied = AcquisitionConfig(
            10_004, 201, 0, SquareBurstConfig(8, False, True, 2, 50))
        self.accept(applied)

        self.assertEqual(self.controller.state, AcquisitionState.ACQUIRING)
        text = self.tab.applied_values_label.text()
        self.assertIn("201 pts", text)
        self.assertIn("Te 10.004 ms", text)
        self.assertIn("durée 2.0008 s", text)
        self.assertIn("période 1.0004 s", text)
        self.assertIn("fréquence 0.9996", text)

    def test_complete_generated_signal_is_stored_and_drawn_as_steps(self):
        config = self.configure_square()
        samples = tuple(range(config.sample_count))
        self.controller.samples.extend(samples)
        self.controller.data_batch_received.emit(DataBatch(42, 0, 0, samples))
        self.tab.refresh_plot()

        expected = (5.0, 5.0, 0.0, 0.0, 5.0, 5.0, 0.0, 0.0, 0.0)
        self.assertEqual(tuple(self.tab.generated_voltages_v), expected)
        plot_x, plot_y = self.tab.generated_curve.getData()
        self.assertEqual(len(plot_x), 2 * len(expected) - 1)
        for index in range(1, len(plot_y)):
            if plot_y[index] != plot_y[index - 1]:
                self.assertEqual(plot_x[index], plot_x[index - 1])

        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.acquisition_finished.emit(
            AcquisitionResult(42, samples, True, ""))
        self.assertEqual(self.tab.results[-1].generated_voltages_v, expected)

    def test_partial_signal_and_stored_config_survive_widget_changes(self):
        config = self.configure_square()
        samples = (100, 200, 300, 400, 500)
        self.controller.samples.extend(samples)
        self.controller.data_batch_received.emit(DataBatch(42, 0, 0, samples))
        self.controller.set_state(AcquisitionState.STOPPING)
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.acquisition_finished.emit(
            AcquisitionResult(42, samples, False, "Arrêt manuel"))

        stored = self.tab.results[-1]
        self.assertFalse(stored.complete)
        self.assertEqual(stored.generated_voltages_v, (5.0, 5.0, 0.0, 0.0, 5.0))
        self.assertEqual(stored.generation, config.generation)

        self.tab.square_periods_spin.setValue(5)
        self.tab.duration_spin.setValue(3.0)
        self.tab.generation_type_combo.setCurrentIndex(0)
        self.assertEqual(stored.generated_voltages_v, (5.0, 5.0, 0.0, 0.0, 5.0))
        self.assertEqual(stored.generation, config.generation)

    def test_disconnect_preserves_only_received_generated_points(self):
        self.configure_square()
        samples = (100, 200, 300)
        self.controller.samples.extend(samples)
        self.controller.data_batch_received.emit(DataBatch(42, 0, 0, samples))
        self.controller.set_state(AcquisitionState.ERROR)
        self.controller.error_occurred.emit(SERIAL_RESOURCE_DISCONNECTED_MESSAGE)

        stored = self.tab.results[-1]
        self.assertFalse(stored.complete)
        self.assertEqual(stored.generated_voltages_v, (5.0, 5.0, 0.0))
        self.assertEqual(len(stored.generated_voltages_v), len(stored.voltages_v))

    def test_successive_square_then_step_results_keep_their_generation(self):
        square = self.configure_square()
        first_samples = tuple(range(square.sample_count))
        self.controller.samples.extend(first_samples)
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.acquisition_finished.emit(
            AcquisitionResult(42, first_samples, True, ""))

        self.tab.generation_type_combo.setCurrentIndex(0)
        self.controller.set_state(AcquisitionState.READY)
        self.tab.start_button.click()
        step = AcquisitionConfig(1000, 2, 0, DigitalStepConfig(8, False, True, 0))
        self.accept(step)
        self.controller.samples[:] = [10, 20]
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.acquisition_finished.emit(
            AcquisitionResult(43, (10, 20), True, ""))

        self.assertIsInstance(self.tab.results[-2].generation, SquareBurstConfig)
        self.assertIsInstance(self.tab.results[-1].generation, DigitalStepConfig)
        self.assertEqual(self.tab.results[-1].generated_voltages_v, (5.0, 5.0))


class ContinuousSquareUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = FakeController()
        self.tab = AcquisitionTab(self.controller)

    def tearDown(self):
        self.tab.shutdown()
        self.tab.deleteLater()
        self.app.processEvents()

    def ready(self, capabilities=0x0F | CAPABILITY_CONTINUOUS_SQUARE):
        self.controller.set_state(AcquisitionState.READY)
        self.controller.ready.emit(FirmwareInfo((1, 1, 0), capabilities))
        if capabilities & CAPABILITY_CONTINUOUS_SQUARE:
            self.controller.set_generator_state(GeneratorState.STOPPED)

    def select_gbf(self):
        self.tab.generation_type_combo.setCurrentIndex(2)
        self.assertEqual(self.tab.generation_type(), CONTINUOUS_SQUARE_MODE)

    def start_generator(self, frequency=12.345):
        self.ready()
        self.select_gbf()
        self.tab.gbf_frequency_spin.setValue(frequency)
        self.tab.gbf_start_button.click()
        plan = plan_continuous_square(ContinuousSquareConfig(frequency))
        self.controller.generator_plan = plan
        self.controller.generator_configured.emit(plan)
        self.controller.set_generator_state(GeneratorState.RUNNING)
        return plan

    def arm_acquisition(self, count=4, period_us=1000):
        self.tab.points_spin.setValue(count)
        self.tab.start_button.click()
        config = AcquisitionConfig(
            period_us, count, 0, DigitalStepConfig(8, False, True, 0))
        self.controller.config = config
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.configuration_accepted.emit(config)
        return config

    def test_mode_is_gated_by_capability_and_uses_fixed_v1_parameters(self):
        self.ready(0x0F)
        self.select_gbf()
        self.assertFalse(self.tab.start_button.isEnabled())
        self.assertFalse(self.tab.gbf_start_button.isEnabled())
        self.assertIn("firmware Physalix compatible GBF",
                      self.tab.gbf_requirement_label.text())
        self.assertEqual(self.tab.gbf_shape_value.text(), "Carré")
        self.assertEqual(self.tab.gbf_output_value.text(), "D8")
        self.assertEqual(self.tab.gbf_minimum_value.text(), "0,0 V")
        self.assertEqual(self.tab.gbf_maximum_value.text(), "5,0 V")
        self.assertEqual(self.tab.gbf_duty_value.text(), "50 %")

    def test_generator_config_then_start_uses_only_ack_for_applied_values(self):
        self.ready()
        self.select_gbf()
        self.tab.gbf_frequency_spin.setValue(12.345)
        self.tab.gbf_start_button.click()
        self.assertEqual(len(self.controller.configure_generator_calls), 1)
        self.assertEqual(self.controller.start_generator_calls, 0)
        self.assertEqual(self.tab.gbf_applied_frequency_label.text(),
                         "En attente de configuration")

        plan = plan_continuous_square(ContinuousSquareConfig(12.345))
        self.controller.generator_configured.emit(plan)
        self.assertEqual(self.controller.start_generator_calls, 1)
        self.assertEqual(self.tab.gbf_applied_frequency_label.text(),
                         self.tab._format_hertz(plan.applied_frequency_hz))
        self.assertEqual(self.tab.gbf_applied_period_label.text(),
                         self.tab._format_seconds(plan.applied_period_s))

        self.controller.set_generator_state(GeneratorState.RUNNING)
        self.assertFalse(self.tab.generation_type_combo.isEnabled())
        self.assertFalse(self.tab.gbf_frequency_spin.isEnabled())
        self.assertTrue(self.tab.gbf_stop_button.isEnabled())
        self.assertTrue(self.tab.start_button.isEnabled())

        self.tab.gbf_stop_button.click()
        self.controller.set_generator_state(GeneratorState.STOPPED)
        self.assertTrue(self.tab.generation_type_combo.isEnabled())
        self.assertTrue(self.tab.gbf_frequency_spin.isEnabled())
        self.assertTrue(self.tab.gbf_start_button.isEnabled())

    def test_sampling_quality_is_neutral_until_generator_config_ack(self):
        self.ready()
        self.select_gbf()
        self.tab.duration_spin.setValue(1.0)
        self.tab.points_spin.setValue(101)
        self.assertEqual(self.tab.gbf_sampling_quality_label.text(), "—")

        self.tab.gbf_start_button.click()
        self.assertEqual(self.tab.gbf_sampling_quality_label.text(), "—")

    def test_sampling_quality_thresholds_follow_acquisition_settings(self):
        self.ready()
        self.select_gbf()
        self.tab.duration_spin.setValue(1.0)
        plan = plan_continuous_square(ContinuousSquareConfig(1.0))
        self.controller.generator_configured.emit(plan)

        expected_by_points = {
            201: "200 pts/période — excellent",
            76: "75 pts/période — très bon",
            41: "40 pts/période — correct",
            16: "15 pts/période — limité",
            5: "4 pts/période — faible",
        }
        for points, expected in expected_by_points.items():
            with self.subTest(points=points):
                self.tab.points_spin.setValue(points)
                self.assertEqual(
                    self.tab.gbf_sampling_quality_label.text(), expected)

    def test_sampling_quality_uses_applied_generator_and_acquisition_values(self):
        self.ready()
        self.select_gbf()
        self.tab.duration_spin.setValue(1.0)
        self.tab.points_spin.setValue(201)

        plan = plan_continuous_square(ContinuousSquareConfig(1.0))
        self.controller.generator_configured.emit(plan)
        self.assertEqual(
            self.tab.gbf_sampling_quality_label.text(),
            "200 pts/période — excellent")

        plan = plan_continuous_square(ContinuousSquareConfig(4.0))
        self.controller.generator_configured.emit(plan)
        self.assertEqual(
            self.tab.gbf_sampling_quality_label.text(),
            "50 pts/période — très bon")

        config = AcquisitionConfig(
            10_000, 201, 0, DigitalStepConfig(8, False, True, 0))
        self.controller.config = config
        self.controller.configuration_accepted.emit(config)
        self.assertEqual(
            self.tab.gbf_sampling_quality_label.text(),
            "25 pts/période — correct")

    def test_low_sampling_quality_does_not_block_acquisition(self):
        self.ready()
        self.select_gbf()
        self.tab.duration_spin.setValue(1.0)
        self.tab.points_spin.setValue(5)
        plan = plan_continuous_square(ContinuousSquareConfig(1.0))
        self.controller.generator_configured.emit(plan)
        self.controller.set_generator_state(GeneratorState.RUNNING)

        self.assertEqual(
            self.tab.gbf_sampling_quality_label.text(),
            "4 pts/période — faible")
        self.assertTrue(self.tab.start_button.isEnabled())
        self.tab.start_button.click()
        self.assertIsNotNone(self.controller.config)

    def test_gbf_actions_are_stacked_and_labels_fit_the_side_panel(self):
        self.ready()
        self.select_gbf()
        self.tab.resize(1366, 768)
        self.tab.show()
        self.app.processEvents()

        self.assertIsInstance(self.tab.gbf_actions_layout, QVBoxLayout)
        self.assertIs(self.tab.gbf_actions_layout.itemAt(0).widget(),
                      self.tab.gbf_start_button)
        self.assertIs(self.tab.gbf_actions_layout.itemAt(1).widget(),
                      self.tab.gbf_stop_button)
        for button in (self.tab.gbf_start_button, self.tab.gbf_stop_button):
            self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())
        expected_labels = {
            self.tab.generation_type_combo: "Mode de génération",
            self.tab.gbf_frequency_spin: "Fréquence demandée",
            self.tab.gbf_applied_frequency_label: "Fréquence appliquée",
            self.tab.gbf_applied_period_label: "Période appliquée",
            self.tab.gbf_duty_value: "Rapport cyclique",
            self.tab.gbf_state_label: "État du générateur",
        }
        for field, expected in expected_labels.items():
            form_label = self.tab._generation_form.labelForField(field)
            self.assertEqual(form_label.text(), expected)
            self.assertTrue(form_label.isVisible())

    def test_supported_frequency_range_is_forwarded_without_fake_applied_value(self):
        self.ready()
        self.select_gbf()
        for frequency in (0.1, 0.5, 1, 10, 50, 100, 500, 1000):
            with self.subTest(frequency=frequency):
                self.tab.gbf_frequency_spin.setValue(frequency)
                self.tab.gbf_start_button.click()
                self.assertEqual(
                    self.controller.configure_generator_calls[-1].requested_frequency_hz,
                    frequency)
                self.assertEqual(self.tab.gbf_applied_frequency_label.text(),
                                 "En attente de configuration")
                self.tab._generator_start_pending = False
                self.tab._update_controls(self.controller.state)

    def test_gbf_acquisition_cannot_start_while_generator_is_stopped(self):
        self.ready()
        self.select_gbf()
        self.assertFalse(self.tab.start_button.isEnabled())
        self.tab.start_acquisition()
        self.assertIsNone(self.controller.config)
        self.assertIn("Démarrez le générateur GBF", self.tab.result_status.text())

    def test_armed_trigger_and_raw_data_gbf_drive_live_step_curve(self):
        self.start_generator()
        self.arm_acquisition(4)
        self.assertEqual(self.controller.state, AcquisitionState.ARMED)
        self.assertIn("attente du prochain front montant", self.tab.result_status.text())
        self.assertTrue(self.tab.stop_button.isEnabled())

        self.controller.set_state(AcquisitionState.ACQUIRING)
        self.controller.acquisition_triggered.emit(AcquisitionStarted(42))
        self.controller.samples.extend((0, 100, 200, 300))
        self.controller.generated_high.extend((True, False, True, False))
        self.controller.data_batch_received.emit(
            GbfDataBatch(42, 0, 0, (0, 100, 200, 300),
                         (True, False, True, False)))
        self.tab.refresh_plot()
        self.assertEqual(self.tab.generated_voltages_v, [5.0, 0.0, 5.0, 0.0])
        plot_x, _ = self.tab.generated_curve.getData()
        self.assertEqual(len(plot_x), 7)

    def test_generator_can_stop_during_acquisition_without_changing_session_type(self):
        plan = self.start_generator()
        self.arm_acquisition(3)
        self.controller.set_state(AcquisitionState.ACQUIRING)
        self.tab.gbf_stop_button.click()
        self.assertEqual(self.controller.stop_generator_calls, 1)
        self.controller.set_generator_state(GeneratorState.STOPPED)
        self.assertEqual(self.controller.state, AcquisitionState.ACQUIRING)

        self.controller.samples[:] = [100, 200, 300]
        self.controller.generated_high[:] = [True, False, False]
        self.controller.data_batch_received.emit(
            GbfDataBatch(42, 0, 0, (100, 200, 300), (True, False, False)))
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.acquisition_finished.emit(
            AcquisitionResult(42, (100, 200, 300), True, "",
                              (True, False, False), 1000))
        stored = self.tab.results[-1]
        self.assertEqual(stored.generated_voltages_v, (5.0, 0.0, 0.0))
        self.assertEqual(stored.generator_plan, plan)
        self.assertEqual(self.controller.generator_state, GeneratorState.STOPPED)

    def test_end_does_not_stop_a_running_generator(self):
        self.start_generator()
        self.arm_acquisition(2)
        self.controller.set_state(AcquisitionState.ACQUIRING)
        self.controller.samples[:] = [100, 200]
        self.controller.generated_high[:] = [True, False]
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.acquisition_finished.emit(
            AcquisitionResult(42, (100, 200), True, "", (True, False), 1000))
        self.assertEqual(self.controller.generator_state, GeneratorState.RUNNING)
        self.assertEqual(self.tab.gbf_state_label.text(), "En fonctionnement")
        self.assertEqual(self.controller.stop_generator_calls, 0)
        self.assertTrue(self.tab.transfer_button.isEnabled() is False)

    def test_stop_while_armed_with_no_point_creates_no_result(self):
        self.start_generator()
        self.arm_acquisition(3)
        self.tab.stop_button.click()
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.acquisition_finished.emit(
            AcquisitionResult(42, (), False, "Arrêt manuel", (), 1000))
        self.assertEqual(self.tab.results, [])
        self.assertIn("Arrêt manuel", self.tab.result_status.text())

    def test_trigger_cancel_unknown_disconnect_and_flash_safety(self):
        self.start_generator()
        self.arm_acquisition(3)
        self.controller.set_generator_state(GeneratorState.STOPPED)
        self.controller.set_state(AcquisitionState.CONFIGURED)
        self.controller.error_occurred.emit(
            "Déclenchement de l'acquisition annulé : trigger cancelled")
        self.assertEqual(self.tab.results, [])
        self.assertIn("aucune donnée", self.tab.result_status.text().lower())

        self.controller.set_generator_state(GeneratorState.UNKNOWN)
        self.assertEqual(self.tab.gbf_state_label.text(), "État inconnu")
        self.assertFalse(self.tab.gbf_start_button.isEnabled())

        self.controller.set_generator_state(GeneratorState.RUNNING)
        self.tab._firmware_mode = "older"
        self.tab._update_firmware_offer()
        self.assertFalse(self.tab.firmware_button.isEnabled())
        self.tab.disconnect()
        self.assertEqual(self.controller.shutdown_generator_calls, 1)
        self.assertNotEqual(self.controller.state, AcquisitionState.DISCONNECTED)
        self.controller.set_generator_state(GeneratorState.STOPPED)
        self.assertEqual(self.controller.state, AcquisitionState.DISCONNECTED)


class AcquisitionTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.tab = self.window.acquisition_tab
        self.controller = self.tab.controller

    def tearDown(self):
        self.window._discard_on_close = True
        self.window.close()
        self.app.processEvents()

    def store(self, samples, period_us=2500, complete=True, generation=None,
              sample_count=None):
        self.controller.config = AcquisitionConfig(
            period_us, sample_count or max(2, len(samples)), 0,
            generation or DigitalStepConfig(8, False, True, 0))
        self.controller.samples[:] = samples
        self.tab._store_result(complete, "Fin normale" if complete else "Arrêt manuel")

    def test_complete_step_transfer_includes_generated_signal_and_creates_one_graph(self):
        self.assertFalse(self.tab.transfer_button.isEnabled())
        self.store([0, 512, 1023], period_us=2500)
        self.assertTrue(self.tab.transfer_button.isEnabled())
        columns, graph = self.tab.transfer_result()
        model = self.window.data_tab.model
        self.assertEqual(columns, (2, 3, 4))
        self.assertEqual(model.names[2:5], ["Temps", "Uc", "E"])
        self.assertEqual(model.units[2:5], ["s", "V", "V"])
        self.assertEqual([row[2] for row in model.rows[:3]], ["0", "0.0025", "0.005"])
        self.assertAlmostEqual(float(model.rows[1][3]), adc_to_volts(512))
        self.assertEqual([row[4] for row in model.rows[:3]], ["5", "5", "5"])
        self.assertEqual([series.key() for series in graph.series], [(2, 3), (2, 4)])
        self.assertTrue(all(series.connect_points.isChecked() for series in graph.series))
        self.assertTrue(all(series.visible.isChecked() for series in graph.series))
        self.assertTrue(all(series.y_axis.currentIndex() == 0 for series in graph.series))
        self.assertEqual(len(self.window.graph_tab.windows), 2)
        graph_window = next(window for window in self.window.graph_tab.windows
                            if window.graph is graph)
        self.assertEqual(graph_window.windowTitle(), "Uc et E en fonction de Temps")
        self.assertIs(self.window.tabs.currentWidget(), self.window.graph_tab)
        self.assertFalse(self.tab.transfer_button.isEnabled())

    def test_complete_square_transfer_uses_exact_stored_generated_values(self):
        generation = SquareBurstConfig(8, False, True, 2, 2)
        self.store(list(range(9)), period_us=1000, generation=generation)

        columns, graph = self.tab.transfer_result()

        model = self.window.data_tab.model
        expected = ["5", "5", "0", "0", "5", "5", "0", "0", "0"]
        self.assertEqual(columns, (2, 3, 4))
        self.assertEqual([row[4] for row in model.rows[:9]], expected)
        self.assertEqual(len([row for row in model.rows if row[2] != ""]), 9)
        self.assertEqual(len([row for row in model.rows if row[3] != ""]), 9)
        self.assertEqual(len([row for row in model.rows if row[4] != ""]), 9)
        self.assertEqual([series.key() for series in graph.series], [(2, 3), (2, 4)])

    def test_gbf_transfer_uses_raw_captured_e_values(self):
        plan = plan_continuous_square(ContinuousSquareConfig(10.0))
        self.controller.config = AcquisitionConfig(
            1000, 4, 0, DigitalStepConfig(8, False, True, 0))
        self.controller.samples[:] = [100, 200, 300, 400]
        self.tab._session_uses_gbf = True
        self.tab._applied_generator_plan = plan
        self.tab._store_result(True, "Fin normale", (True, False, False, True))

        columns, graph = self.tab.transfer_result()

        model = self.window.data_tab.model
        self.assertEqual(columns, (2, 3, 4))
        self.assertEqual([row[4] for row in model.rows[:4]], ["5", "0", "0", "5"])
        self.assertEqual(self.tab.results[-1].generator_plan, plan)
        self.assertEqual([series.key() for series in graph.series], [(2, 3), (2, 4)])

    def test_second_transfer_uses_suffixes_and_new_column_indices(self):
        self.store([1, 2])
        self.tab.transfer_result()
        self.store([3, 4], period_us=1000)
        columns, graph = self.tab.transfer_result()
        model = self.window.data_tab.model
        self.assertEqual(model.names[5:8], ["Temps_2", "Uc_2", "E_2"])
        self.assertEqual(columns, (5, 6, 7))
        self.assertEqual([series.key() for series in graph.series], [(5, 6), (5, 7)])

    def test_partial_transfer_only_uses_received_points(self):
        self.store(
            [100, 200, 300], complete=False,
            generation=SquareBurstConfig(8, False, True, 2, 2),
            sample_count=9,
        )
        self.assertIn("Données partielles", self.tab.result_status.text())
        self.assertTrue(self.tab.transfer_button.isEnabled())
        self.tab.transfer_result()
        model = self.window.data_tab.model
        self.assertEqual([len([row for row in model.rows if row[column] != ""])
                          for column in (2, 3, 4)], [3, 3, 3])
        self.assertEqual([row[4] for row in model.rows[:3]], ["5", "5", "0"])

    def test_no_duplicate_and_new_acquisition_resets_state(self):
        self.store([10])
        self.tab.transfer_result()
        count = self.window.data_tab.model.columnCount()
        self.assertIsNone(self.tab.transfer_result())
        self.assertEqual(self.window.data_tab.model.columnCount(), count)
        self.controller.state = AcquisitionState.READY
        from unittest.mock import patch
        with patch.object(self.controller, "configure"):
            self.tab.start_acquisition()
        self.assertFalse(self.tab.transfer_button.isEnabled())
        self.tab._start_after_configuration = False
        self.controller.state = AcquisitionState.CONFIGURED
        self.store([20])
        self.assertTrue(self.tab.transfer_button.isEnabled())

    def test_graph_failure_retry_does_not_append_data_twice(self):
        self.store([10, 20])
        original = self.window.graph_tab.add_data_graph_series
        calls = 0

        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("graphe indisponible")
            return original(*args, **kwargs)

        self.window.graph_tab.add_data_graph_series = fail_once
        from unittest.mock import patch
        with patch("physalix.ui.acquisition_tab.QMessageBox.warning"):
            self.assertIsNone(self.tab.transfer_result())
        self.assertEqual(self.window.data_tab.model.columnCount(), 5)
        self.assertTrue(self.tab.transfer_button.isEnabled())
        self.tab.transfer_result()
        self.assertEqual(self.window.data_tab.model.columnCount(), 5)
        self.assertFalse(self.tab.transfer_button.isEnabled())

    def test_transferred_measurements_are_in_normal_project_snapshot(self):
        from physalix.ui.project_state import snapshot
        self.store([0, 1023])
        self.tab.transfer_result()
        state = snapshot(self.window)
        self.assertEqual(state["table"]["names"][2:5], ["Temps", "Uc", "E"])
        self.assertNotIn("acquisition", state)


class AcquisitionNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_acquisition_is_last_and_does_not_touch_measurements(self):
        window = MainWindow()
        try:
            count_before = window.data_tab.model.columnCount()
            self.assertIs(window.tabs.widget(window.tabs.count() - 1), window.acquisition_tab)
            self.assertEqual(window.tabs.tabText(window.tabs.count() - 1), "Acquisition")
            self.assertEqual(window.navigation_buttons[-1].toolTip(), "Acquisition")
            self.assertFalse(window.navigation_buttons[-1].icon().isNull())
            self.assertEqual(window.data_tab.model.columnCount(), count_before)
        finally:
            window._discard_on_close = True
            window.close()


if __name__ == "__main__":
    unittest.main()
