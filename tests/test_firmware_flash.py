"""Tests du moteur de flash, exclusivement avec un faux QProcess."""

from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication, QObject, QProcess, Signal

from physalix.firmware_flash import (
    AVR_BAUD_RATE,
    FirmwareCompatibility,
    FirmwareFlash,
    FirmwareFlashBusyError,
    FlashErrorKind,
    FlashState,
    build_avrdude_command,
    compare_firmware,
)
from physalix.firmware_resources import (
    AVRDUDE_CONFIG,
    AVRDUDE_EXECUTABLE,
    UNO_HEX_FILE,
    FirmwareManifest,
    FirmwareResources,
    FirmwareSourceMetadata,
    create_manifest,
    manifest_bytes,
)


class FakeProcess(QObject):
    started = Signal()
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    errorOccurred = Signal(object)
    finished = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.program = None
        self.arguments = None
        self._state = QProcess.ProcessState.NotRunning
        self.stdout = b""
        self.stderr = b""
        self.terminate_count = 0
        self.kill_count = 0

    def start(self, program, arguments):
        self.program = program
        self.arguments = list(arguments)
        self._state = QProcess.ProcessState.Starting

    def state(self):
        return self._state

    def readAllStandardOutput(self):
        data, self.stdout = self.stdout, b""
        return data

    def readAllStandardError(self):
        data, self.stderr = self.stderr, b""
        return data

    def simulate_started(self):
        self._state = QProcess.ProcessState.Running
        self.started.emit()

    def simulate_output(self, *, stdout=b"", stderr=b""):
        if stdout:
            self.stdout += stdout
            self.readyReadStandardOutput.emit()
        if stderr:
            self.stderr += stderr
            self.readyReadStandardError.emit()

    def simulate_finished(self, code=0, status=QProcess.ExitStatus.NormalExit):
        self._state = QProcess.ProcessState.NotRunning
        self.finished.emit(code, status)

    def terminate(self):
        self.terminate_count += 1

    def kill(self):
        self.kill_count += 1
        self._state = QProcess.ProcessState.NotRunning


class FirmwareFlashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="Physalix flash éspace ")
        self.directory = Path(self.temporary.name)
        self.hex_path = self.directory / UNO_HEX_FILE
        self.exe_path = self.directory / AVRDUDE_EXECUTABLE
        self.conf_path = self.directory / AVRDUDE_CONFIG
        self.exe_path.parent.mkdir()
        self.hex_path.write_bytes(b":00000001FF\n")
        self.exe_path.write_bytes(b"fake executable")
        self.conf_path.write_bytes(b"fake configuration")
        self.metadata = FirmwareSourceMetadata("1.0.0", 1, 7)
        self.manifest = create_manifest(self.hex_path, self.metadata, self.directory)
        (self.directory / "manifest.json").write_bytes(manifest_bytes(self.manifest))
        self.processes = []

        def factory(parent):
            process = FakeProcess(parent)
            self.processes.append(process)
            return process

        self.service = FirmwareFlash(resource_directory=self.directory,
                                     process_factory=factory, timeout_ms=100,
                                     log_limit=80)
        self.failures = []
        self.service.failed.connect(self.failures.append)

    def tearDown(self):
        self.service.shutdown()
        self.temporary.cleanup()

    def resources(self):
        return FirmwareResources(self.manifest, self.hex_path,
                                 self.exe_path, self.conf_path)

    def start_running(self, port="COM12"):
        self.assertTrue(self.service.start_flash(port))
        process = self.processes[-1]
        process.simulate_started()
        self.assertEqual(self.service.state, FlashState.FLASHING)
        return process

    def test_exact_command_has_verify_and_only_application_flash(self):
        command = build_avrdude_command(self.resources(), "com3")
        self.assertEqual(command.program, self.exe_path)
        self.assertEqual(command.arguments, (
            "-C", str(self.conf_path), "-p", "atmega328p", "-c", "arduino",
            "-P", "COM3", "-b", str(AVR_BAUD_RATE), "-D", "-U",
            f"flash:w:{self.hex_path}:i",
        ))
        self.assertNotIn("-V", command.arguments)
        self.assertNotIn("eeprom", " ".join(command.arguments).lower())
        self.assertNotIn("fuse", " ".join(command.arguments).lower())

    def test_command_preserves_high_com_port_and_paths_with_spaces_accents(self):
        command = build_avrdude_command(self.resources(), "COM12")
        self.assertEqual(command.arguments[7], "COM12")
        self.assertEqual(command.arguments[1], str(self.conf_path))
        self.assertEqual(command.arguments[-1], f"flash:w:{self.hex_path}:i")

    def test_invalid_port_prevents_process_creation(self):
        self.assertFalse(self.service.start_flash("../COM3 & erase"))
        self.assertFalse(self.processes)
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.INVALID_PORT)

    def test_corrupted_firmware_prevents_start(self):
        self.hex_path.write_bytes(b"corrupted")
        self.assertFalse(self.service.start_flash("COM3"))
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.FIRMWARE_RESOURCES)

    def test_corrupted_uploader_prevents_start(self):
        self.exe_path.write_bytes(b"corrupted")
        self.assertFalse(self.service.start_flash("COM3"))
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.UPLOADER_RESOURCES)

    def test_success_waits_for_physalix_firmware_confirmation(self):
        states = []
        uploads = []
        successes = []
        self.service.state_changed.connect(states.append)
        self.service.upload_verified.connect(uploads.append)
        self.service.succeeded.connect(successes.append)
        process = self.start_running()
        process.simulate_output(stdout=b"writing\n", stderr=b"verifying\n")
        process.simulate_finished()
        self.assertEqual(self.service.state, FlashState.WAITING_FOR_FIRMWARE)
        self.assertEqual(len(uploads), 1)
        self.assertFalse(successes)
        self.assertTrue(self.service.confirm_firmware((1, 0, 0), 1, 7))
        self.assertEqual(self.service.state, FlashState.SUCCESS)
        self.assertEqual(len(successes), 1)
        self.assertIn(FlashState.FLASHING, states)

    def test_nonzero_exit_is_reported(self):
        process = self.start_running()
        process.simulate_finished(2)
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.AVRDUDE_FAILED)

    def test_process_crash_signal_is_reported(self):
        process = self.start_running()
        process.errorOccurred.emit(QProcess.ProcessError.Crashed)
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.PROCESS_CRASHED)

    def test_failed_to_start(self):
        self.assertTrue(self.service.start_flash("COM3"))
        self.processes[-1].errorOccurred.emit(QProcess.ProcessError.FailedToStart)
        self.assertEqual(self.service.state, FlashState.FAILED)
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.START_FAILED)

    def test_timeout_terminates_then_can_force_kill(self):
        process = self.start_running()
        settled = []
        self.service.process_settled.connect(lambda: settled.append(True))
        self.service._on_timeout()
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.TIMEOUT)
        self.assertEqual(process.terminate_count, 1)
        self.service._force_kill()
        self.assertEqual(process.kill_count, 1)
        process.simulate_finished(-1, QProcess.ExitStatus.CrashExit)
        self.assertEqual(settled, [True])

    def test_timeout_also_covers_process_startup(self):
        self.assertTrue(self.service.start_flash("COM3"))
        process = self.processes[-1]
        self.assertEqual(self.service.state, FlashState.VALIDATING)
        self.service._on_timeout()
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.TIMEOUT)
        self.assertEqual(process.terminate_count, 1)

    def test_shutdown_warns_and_cleans_up_running_process(self):
        process = self.start_running()
        self.service.shutdown()
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.INTERRUPTED)
        self.assertEqual(process.terminate_count, 1)

    def test_second_flash_is_rejected_without_stopping_first(self):
        process = self.start_running()
        with self.assertRaises(FirmwareFlashBusyError):
            self.service.start_flash("COM4")
        self.assertEqual(self.service.state, FlashState.FLASHING)
        self.assertEqual(process.terminate_count, 0)

    def test_stdout_stderr_and_log_are_bounded(self):
        outputs = []
        self.service.technical_output.connect(outputs.append)
        process = self.start_running()
        process.simulate_output(stdout=b"a" * 60, stderr=b"b" * 60)
        self.assertEqual(len(outputs), 2)
        self.assertLessEqual(len(self.service.technical_log), 80)
        self.assertIn("b", self.service.technical_log)

    def test_firmware_comparison_all_outcomes_and_final_mismatch(self):
        cases = (
            ((1, 0, 0), 1, 7, FirmwareCompatibility.COMPATIBLE),
            ((0, 9, 0), 1, 7, FirmwareCompatibility.OLDER),
            ((1, 1, 0), 1, 7, FirmwareCompatibility.NEWER),
            ((1, 0, 0), 2, 7, FirmwareCompatibility.PROTOCOL_INCOMPATIBLE),
            ((1, 0, 0), 1, 1, FirmwareCompatibility.MISSING_CAPABILITIES),
        )
        for version, protocol, capabilities, expected in cases:
            with self.subTest(expected=expected):
                result = compare_firmware(self.manifest, version, protocol, capabilities)
                self.assertEqual(result.status, expected)
        process = self.start_running()
        process.simulate_finished()
        self.assertFalse(self.service.confirm_firmware((1, 1, 0), 1, 7))
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.FIRMWARE_MISMATCH)

    def test_optional_new_capability_keeps_older_firmware_updatable(self):
        target = create_manifest(
            self.hex_path, FirmwareSourceMetadata("1.1.0", 1, 15), self.directory)
        self.assertEqual(
            compare_firmware(target, (1, 0, 0), 1, 7).status,
            FirmwareCompatibility.OLDER,
        )
        self.assertEqual(
            compare_firmware(target, (1, 1, 0), 1, 7).status,
            FirmwareCompatibility.MISSING_CAPABILITIES,
        )
        self.assertEqual(
            compare_firmware(target, (1, 1, 0), 1, 15).status,
            FirmwareCompatibility.COMPATIBLE,
        )

    def test_post_flash_reconnection_failure_can_close_workflow(self):
        process = self.start_running()
        process.simulate_finished()
        self.service.fail_post_flash_verification(
            "L’Arduino n’est pas revenue.", "Délai de reconnexion dépassé.")
        self.assertEqual(self.service.state, FlashState.FAILED)
        self.assertEqual(self.failures[-1].kind, FlashErrorKind.FIRMWARE_MISMATCH)


if __name__ == "__main__":
    unittest.main()
