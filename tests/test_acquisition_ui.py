"""Tests fonctionnels ciblés de l'onglet Acquisition."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from physalix.acquisition import (
    AcquisitionConfig, AcquisitionResult, AcquisitionState, DataBatch,
    DigitalStepConfig, FirmwareInfo, SERIAL_RESOURCE_DISCONNECTED_MESSAGE,
)
from physalix.ui.acquisition_tab import AcquisitionTab, adc_to_volts
from physalix.ui.main_window import MainWindow


class FakeController(QObject):
    state_changed = Signal(object)
    ready = Signal(object)
    configuration_accepted = Signal(object)
    data_batch_received = Signal(object)
    acquisition_finished = Signal(object)
    error_occurred = Signal(str)

    def __init__(self):
        super().__init__()
        self.state = AcquisitionState.DISCONNECTED
        self.config = None
        self.samples = []
        self.opened_port = None
        self.stop_calls = 0

    def set_state(self, state):
        self.state = state
        self.state_changed.emit(state)

    def open(self, port_name):
        self.opened_port = port_name
        self.set_state(AcquisitionState.WAITING_HANDSHAKE)
        return True

    def close(self):
        self.set_state(AcquisitionState.DISCONNECTED)

    def configure(self, config):
        self.config = config

    def start(self):
        self.set_state(AcquisitionState.ACQUIRING)
        return 42

    def stop(self):
        if self.state is not AcquisitionState.ACQUIRING:
            return False
        self.stop_calls += 1
        self.set_state(AcquisitionState.STOPPING)
        return True


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

    def store(self, samples, period_us=2500, complete=True):
        self.controller.config = AcquisitionConfig(
            period_us, max(2, len(samples)), 0, DigitalStepConfig(8, False, True, 0))
        self.controller.samples[:] = samples
        self.tab._store_result(complete, "Fin normale" if complete else "Arrêt manuel")

    def test_complete_transfer_uses_applied_period_units_and_creates_graph(self):
        self.assertFalse(self.tab.transfer_button.isEnabled())
        self.store([0, 512, 1023], period_us=2500)
        self.assertTrue(self.tab.transfer_button.isEnabled())
        columns, graph = self.tab.transfer_result()
        model = self.window.data_tab.model
        self.assertEqual(columns, (2, 3))
        self.assertEqual(model.names[2:4], ["Temps", "Uc"])
        self.assertEqual(model.units[2:4], ["s", "V"])
        self.assertEqual([row[2] for row in model.rows[:3]], ["0", "0.0025", "0.005"])
        self.assertAlmostEqual(float(model.rows[1][3]), adc_to_volts(512))
        self.assertEqual([graph.series[0].x_choice.currentData(),
                          graph.series[0].y_choice.currentData()], list(columns))
        self.assertIs(self.window.tabs.currentWidget(), self.window.graph_tab)
        self.assertFalse(self.tab.transfer_button.isEnabled())

    def test_second_transfer_uses_suffixes_and_new_column_indices(self):
        self.store([1, 2])
        self.tab.transfer_result()
        self.store([3, 4], period_us=1000)
        columns, graph = self.tab.transfer_result()
        model = self.window.data_tab.model
        self.assertEqual(model.names[4:6], ["Temps_2", "Uc_2"])
        self.assertEqual(columns, (4, 5))
        self.assertEqual(graph.series[0].x_choice.currentData(), 4)
        self.assertEqual(graph.series[0].y_choice.currentData(), 5)

    def test_partial_transfer_only_uses_received_points(self):
        self.store([100, 200], complete=False)
        self.assertIn("Données partielles", self.tab.result_status.text())
        self.assertTrue(self.tab.transfer_button.isEnabled())
        self.tab.transfer_result()
        self.assertEqual(len([row for row in self.window.data_tab.model.rows
                              if row[2] != ""]), 2)

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
        original = self.window.graph_tab.add_data_graph
        calls = 0

        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("graphe indisponible")
            return original(*args, **kwargs)

        self.window.graph_tab.add_data_graph = fail_once
        from unittest.mock import patch
        with patch("physalix.ui.acquisition_tab.QMessageBox.warning"):
            self.assertIsNone(self.tab.transfer_result())
        self.assertEqual(self.window.data_tab.model.columnCount(), 4)
        self.assertTrue(self.tab.transfer_button.isEnabled())
        self.tab.transfer_result()
        self.assertEqual(self.window.data_tab.model.columnCount(), 4)
        self.assertFalse(self.tab.transfer_button.isEnabled())

    def test_transferred_measurements_are_in_normal_project_snapshot(self):
        from physalix.ui.project_state import snapshot
        self.store([0, 1023])
        self.tab.transfer_result()
        state = snapshot(self.window)
        self.assertEqual(state["table"]["names"][2:4], ["Temps", "Uc"])
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
