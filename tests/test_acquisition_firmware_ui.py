"""Workflow UI du flash firmware, sans AVRDUDE ni matériel."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from physalix.acquisition import AcquisitionState, FirmwareInfo
from physalix.firmware_flash import (
    FirmwareCompatibility, FlashErrorKind, FlashFailure, compare_firmware,
)
from physalix.firmware_resources import load_uno_resources
from physalix.firmware_resources import FirmwareResourceError
from physalix.ui.acquisition_tab import AcquisitionTab


class FakeController(QObject):
    state_changed = Signal(object)
    ready = Signal(object)
    configuration_accepted = Signal(object)
    data_batch_received = Signal(object)
    acquisition_finished = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, events):
        super().__init__()
        self.events = events
        self.state = AcquisitionState.DISCONNECTED
        self.config = None
        self.samples = []
        self.opened_port = None

    def set_state(self, state):
        self.state = state
        self.state_changed.emit(state)

    def open(self, port):
        self.events.append(("open", port))
        self.opened_port = port
        self.set_state(AcquisitionState.WAITING_HANDSHAKE)
        return True

    def close(self):
        self.events.append(("close", self.opened_port))
        self.set_state(AcquisitionState.DISCONNECTED)

    def stop(self):
        return False

    def configure(self, config):
        self.config = config


class FakeFirmwareFlash(QObject):
    upload_verified = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object)
    process_settled = Signal()
    phase_changed = Signal(str)
    technical_output = Signal(str)

    def __init__(self, resources, events):
        super().__init__()
        self.resources = resources
        self.events = events
        self.active = False
        self.start_calls = []
        self.shutdown_calls = 0

    def start_flash(self, port):
        self.events.append(("flash", port))
        self.start_calls.append(port)
        self.active = True
        return True

    def emit_upload_verified(self):
        self.upload_verified.emit(self.resources.manifest)

    def confirm_firmware(self, version, protocol, capabilities):
        result = compare_firmware(self.resources.manifest, version,
                                  protocol, capabilities)
        self.active = False
        if result.status is FirmwareCompatibility.COMPATIBLE:
            self.succeeded.emit(result)
            return True
        self.failed.emit(FlashFailure(
            FlashErrorKind.FIRMWARE_MISMATCH,
            "Le firmware installé n’a pas pu être validé.", result.status.name))
        return False

    def fail_post_flash_verification(self, message, details):
        self.active = False
        self.failed.emit(FlashFailure(
            FlashErrorKind.FIRMWARE_MISMATCH, message, details))

    def emit_flash_failure(self, kind=FlashErrorKind.AVRDUDE_FAILED):
        self.active = False
        self.failed.emit(FlashFailure(kind, "L’installation du firmware a échoué.",
                                      "fake technical detail"))

    def emit_pending_timeout(self):
        self.failed.emit(FlashFailure(
            FlashErrorKind.TIMEOUT, "AVRDUDE ne répond plus.",
            "fake process is terminating"))

    def shutdown(self):
        self.shutdown_calls += 1
        self.active = False


class AcquisitionFirmwareUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.resources = load_uno_resources()

    def setUp(self):
        self.events = []
        self.controller = FakeController(self.events)
        self.flash = FakeFirmwareFlash(self.resources, self.events)
        self.tab = AcquisitionTab(
            self.controller, firmware_flash=self.flash,
            firmware_resource_loader=lambda: self.resources,
            port_release_delay_ms=60_000,
            reconnect_retry_ms=60_000,
            reconnect_timeout_ms=60_000,
        )
        self.tab.port_combo.addItem("COM12 — Arduino Uno", "COM12")
        self.tab.port_combo.setCurrentIndex(self.tab.port_combo.count() - 1)

    def tearDown(self):
        self.tab.shutdown()
        self.tab.deleteLater()
        self.app.processEvents()

    def emit_ready(self, version=(1, 0, 0), capabilities=7):
        self.controller.set_state(AcquisitionState.READY)
        self.controller.ready.emit(FirmwareInfo(version, capabilities))

    def accept_installation(self):
        with patch.object(self.tab, "_confirm_firmware_installation", return_value=True):
            self.tab.firmware_button.click()
        self.tab.port_release_timer.stop()
        self.tab._start_flash_after_release()

    def test_firmware_display_current_older_newer_and_incompatible(self):
        cases = (
            ((1, 0, 0), 7, "Firmware 1.0.0 — à jour", True),
            ((0, 9, 0), 7, "mise à jour disponible", False),
            ((1, 1, 0), 7, "Firmware 1.1.0 — compatible", True),
            ((1, 0, 0), 1, "Firmware Physalix incompatible", False),
        )
        for version, capabilities, text, hidden in cases:
            with self.subTest(version=version, capabilities=capabilities):
                self.emit_ready(version, capabilities)
                self.assertIn(text, self.tab.firmware_status.text())
                self.assertEqual(self.tab.firmware_button.isHidden(), hidden)

    def test_absent_handshake_requires_explicit_port(self):
        self.assertEqual(self.tab.firmware_status.text(), "Firmware non détecté")
        self.assertTrue(self.tab.firmware_button.isEnabled())
        self.tab.port_combo.setCurrentIndex(-1)
        self.assertFalse(self.tab.firmware_button.isEnabled())

    def test_invalid_embedded_resources_hide_install_action(self):
        def invalid_resources():
            raise FirmwareResourceError("hash invalide")

        controller = FakeController([])
        flash = FakeFirmwareFlash(self.resources, [])
        tab = AcquisitionTab(
            controller, firmware_flash=flash,
            firmware_resource_loader=invalid_resources)
        try:
            tab.port_combo.addItem("COM8", "COM8")
            self.assertEqual(tab.firmware_status.text(),
                             "Ressources firmware invalides")
            self.assertTrue(tab.firmware_button.isHidden())
            self.assertFalse(flash.start_calls)
        finally:
            tab.shutdown()
            tab.deleteLater()

    def test_protocol_incompatible_response_offers_reinstallation(self):
        self.controller.set_state(AcquisitionState.ERROR)
        self.controller.error_occurred.emit("Version de protocole incompatible : 2.")
        self.assertEqual(self.tab.firmware_status.text(),
                         "Firmware Physalix incompatible")
        self.assertEqual(self.tab.firmware_button.text(),
                         "Réinstaller le firmware…")
        self.assertTrue(self.tab.firmware_button.isEnabled())

    def test_confirmation_text_is_strong_for_unknown_board_and_short_for_update(self):
        text = self.tab._firmware_confirmation_text("COM12")
        self.assertIn("remplacera le programme", text)
        self.assertIn("Port : COM12", text)
        self.assertIn("Arduino Uno R3 / ATmega328P", text)
        self.emit_ready((0, 9, 0), 7)
        text = self.tab._firmware_confirmation_text("COM12")
        self.assertIn("de 0.9.0 vers 1.0.0", text)
        self.assertIn("programme actuellement présent sera remplacé", text)

    def test_cancelled_confirmation_does_not_close_port_or_start_flash(self):
        with patch.object(self.tab, "_confirm_firmware_installation", return_value=False):
            self.tab.firmware_button.click()
        self.assertFalse(self.events)
        self.assertFalse(self.flash.start_calls)

    def test_port_is_closed_before_flash_and_controls_are_disabled(self):
        self.accept_installation()
        self.assertEqual(self.events[:2], [("close", None), ("flash", "COM12")])
        self.assertFalse(self.tab.connect_button.isEnabled())
        self.assertFalse(self.tab.start_button.isEnabled())
        self.assertFalse(self.tab.duration_spin.isEnabled())
        self.assertFalse(self.tab.firmware_button.isEnabled())
        self.assertEqual(self.tab.firmware_status.text(), "Installation du firmware…")

    def test_avrdude_success_is_not_final_success_then_reconnects_same_port(self):
        self.accept_installation()
        self.flash.emit_upload_verified()
        self.assertEqual(self.tab.firmware_status.text(), "Redémarrage de l’Arduino…")
        self.assertTrue(self.tab._flash_workflow_active)
        self.tab.reconnect_retry_timer.stop()
        self.tab._attempt_flash_reconnect()
        self.assertEqual(self.events[-1], ("open", "COM12"))
        self.assertEqual(self.tab.firmware_status.text(), "Vérification du firmware…")

    def test_correct_final_handshake_is_only_final_success(self):
        self.accept_installation()
        self.flash.emit_upload_verified()
        self.tab.reconnect_retry_timer.stop()
        self.tab._attempt_flash_reconnect()
        self.controller.ready.emit(FirmwareInfo((1, 0, 0), 7))
        self.assertFalse(self.tab._flash_workflow_active)
        self.assertEqual(
            self.tab.firmware_status.text(), "Firmware 1.0.0 — installé et prêt")
        self.assertTrue(self.tab.connect_button.isEnabled())

    def test_incorrect_final_handshake_fails_and_returns_to_usable_ui(self):
        self.accept_installation()
        self.flash.emit_upload_verified()
        self.tab.reconnect_retry_timer.stop()
        self.tab._attempt_flash_reconnect()
        self.controller.ready.emit(FirmwareInfo((1, 1, 0), 7))
        self.assertFalse(self.tab._flash_workflow_active)
        self.assertIn("Installation échouée", self.tab.firmware_status.text())
        self.assertTrue(self.tab.connect_button.isEnabled())

    def test_incompatible_protocol_after_flash_fails_immediately(self):
        self.accept_installation()
        self.flash.emit_upload_verified()
        self.tab.reconnect_retry_timer.stop()
        self.tab._attempt_flash_reconnect()
        self.controller.set_state(AcquisitionState.ERROR)
        self.controller.error_occurred.emit("Version de protocole incompatible : 2.")
        self.assertFalse(self.tab._flash_workflow_active)
        self.assertIn("protocole incompatible", self.tab.firmware_status.text())

    def test_handshake_error_retries_until_global_timeout(self):
        self.accept_installation()
        self.flash.emit_upload_verified()
        self.tab.reconnect_retry_timer.stop()
        self.tab._attempt_flash_reconnect()
        self.controller.set_state(AcquisitionState.ERROR)
        self.controller.error_occurred.emit("Délai du handshake expiré.")
        self.assertTrue(self.tab.reconnect_retry_timer.isActive())
        self.assertTrue(self.tab._flash_workflow_active)

    def test_reconnect_timeout_distinguishes_returned_but_unidentified_board(self):
        self.accept_installation()
        self.flash.emit_upload_verified()
        self.tab.reconnect_retry_timer.stop()
        self.tab._attempt_flash_reconnect()
        self.tab._flash_reconnect_timed_out()
        self.assertIn("firmware Physalix non détecté", self.tab.firmware_status.text())
        self.assertFalse(self.tab._flash_workflow_active)
        self.assertTrue(self.tab.connect_button.isEnabled())

    def test_reconnect_timeout_reports_board_that_never_returned(self):
        self.accept_installation()
        self.flash.emit_upload_verified()
        self.tab._flash_reconnect_timed_out()
        self.assertIn("n’est pas revenue", self.tab.firmware_status.text())
        self.assertFalse(self.tab._flash_workflow_active)

    def test_flash_failure_is_concise_and_restores_controls(self):
        self.accept_installation()
        self.flash.emit_flash_failure()
        self.assertIn("Installation échouée", self.tab.firmware_status.text())
        self.assertIn("toujours connectée", self.tab.firmware_status.text())
        self.assertFalse(self.tab._flash_workflow_active)
        self.assertTrue(self.tab.port_combo.isEnabled())

    def test_controls_wait_until_timed_out_process_is_settled(self):
        self.accept_installation()
        self.flash.emit_pending_timeout()
        self.assertFalse(self.tab.connect_button.isEnabled())
        self.flash.active = False
        self.flash.process_settled.emit()
        self.assertTrue(self.tab.connect_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
