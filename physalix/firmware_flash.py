"""Service Qt asynchrone de flash du firmware officiel Arduino Uno."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
import re
from typing import Callable

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from physalix.firmware_resources import (
    FirmwareManifest,
    FirmwareResourceError,
    FirmwareResources,
    UNO_RESOURCE_DIRECTORY,
)


AVR_PART = "atmega328p"
AVR_PROGRAMMER = "arduino"
AVR_BAUD_RATE = 115200
FLASH_TIMEOUT_MS = 120_000
PROCESS_KILL_GRACE_MS = 2_000
TECHNICAL_LOG_LIMIT = 64 * 1024

_PORT_RE = re.compile(r"COM([1-9]\d{0,2})", re.IGNORECASE)


class FlashState(Enum):
    IDLE = auto()
    VALIDATING = auto()
    FLASHING = auto()
    WAITING_FOR_FIRMWARE = auto()
    VERIFYING_FIRMWARE = auto()
    SUCCESS = auto()
    FAILED = auto()


class FlashErrorKind(Enum):
    FIRMWARE_RESOURCES = auto()
    UPLOADER_RESOURCES = auto()
    INVALID_PORT = auto()
    START_FAILED = auto()
    TIMEOUT = auto()
    AVRDUDE_FAILED = auto()
    PROCESS_CRASHED = auto()
    INTERRUPTED = auto()
    FIRMWARE_MISMATCH = auto()


class FirmwareCompatibility(Enum):
    COMPATIBLE = auto()
    OLDER = auto()
    NEWER = auto()
    PROTOCOL_INCOMPATIBLE = auto()
    MISSING_CAPABILITIES = auto()


class FirmwareFlashBusyError(RuntimeError):
    """Un second flash a été demandé alors que le premier est encore actif."""


@dataclass(frozen=True)
class FlashFailure:
    kind: FlashErrorKind
    user_message: str
    technical_details: str


@dataclass(frozen=True)
class FlashCommand:
    program: Path
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class FirmwareCompatibilityResult:
    status: FirmwareCompatibility
    expected_version: tuple[int, int, int]
    actual_version: tuple[int, int, int]
    missing_capabilities: int = 0


def validate_port_name(port_name: str) -> str:
    if not isinstance(port_name, str):
        raise ValueError("Le port série sélectionné est invalide.")
    match = _PORT_RE.fullmatch(port_name)
    if match is None or int(match.group(1)) > 256:
        raise ValueError("Le port série sélectionné est invalide.")
    return f"COM{int(match.group(1))}"


def build_avrdude_command(resources: FirmwareResources, port_name: str) -> FlashCommand:
    port = validate_port_name(port_name)
    return FlashCommand(resources.uploader_executable, (
        "-C", str(resources.uploader_config),
        "-p", AVR_PART,
        "-c", AVR_PROGRAMMER,
        "-P", port,
        "-b", str(AVR_BAUD_RATE),
        "-D",
        "-U", f"flash:w:{resources.firmware}:i",
    ))


def compare_firmware(manifest: FirmwareManifest,
                     firmware_version: tuple[int, int, int],
                     protocol_version: int,
                     capabilities: int) -> FirmwareCompatibilityResult:
    expected = tuple(int(part) for part in manifest.firmware_version.split("."))
    actual = tuple(firmware_version)
    if (len(actual) != 3 or any(type(part) is not int or not 0 <= part <= 255
                               for part in actual)):
        raise ValueError("Version firmware reçue invalide.")
    if type(protocol_version) is not int or not 0 <= protocol_version <= 255:
        raise ValueError("Version de protocole reçue invalide.")
    if type(capabilities) is not int or not 0 <= capabilities <= 0xFFFFFFFF:
        raise ValueError("Capacités firmware reçues invalides.")
    if protocol_version != manifest.protocol_version:
        status = FirmwareCompatibility.PROTOCOL_INCOMPATIBLE
        missing = 0
    else:
        missing = manifest.required_capabilities & ~capabilities
        if missing:
            status = FirmwareCompatibility.MISSING_CAPABILITIES
        elif actual < expected:
            status = FirmwareCompatibility.OLDER
        elif actual > expected:
            status = FirmwareCompatibility.NEWER
        else:
            status = FirmwareCompatibility.COMPATIBLE
    return FirmwareCompatibilityResult(status, expected, actual, missing)


class FirmwareFlash(QObject):
    """Pilote AVRDUDE sans bloquer la boucle événementielle Qt."""

    state_changed = Signal(object)
    phase_changed = Signal(str)
    technical_output = Signal(str)
    upload_verified = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object)
    process_settled = Signal()

    def __init__(self, parent: QObject | None = None, *,
                 resource_directory: Path = UNO_RESOURCE_DIRECTORY,
                 process_factory: Callable[[QObject], QProcess] | None = None,
                 timeout_ms: int = FLASH_TIMEOUT_MS,
                 log_limit: int = TECHNICAL_LOG_LIMIT) -> None:
        super().__init__(parent)
        if timeout_ms <= 0 or log_limit <= 0:
            raise ValueError("Les limites temporelle et de journal doivent être positives.")
        self.resource_directory = Path(resource_directory)
        self.process_factory = process_factory or (lambda owner: QProcess(owner))
        self.timeout_ms = timeout_ms
        self.log_limit = log_limit
        self.state = FlashState.IDLE
        self.resources: FirmwareResources | None = None
        self._process = None
        self._technical_log = ""
        self._failure_committed = False
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(timeout_ms)
        self._timeout.timeout.connect(self._on_timeout)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.setInterval(PROCESS_KILL_GRACE_MS)
        self._kill_timer.timeout.connect(self._force_kill)

    @property
    def technical_log(self) -> str:
        return self._technical_log

    @property
    def active(self) -> bool:
        return self._process_running() or self.state in {
            FlashState.VALIDATING, FlashState.FLASHING,
            FlashState.WAITING_FOR_FIRMWARE, FlashState.VERIFYING_FIRMWARE,
        }

    def start_flash(self, port_name: str) -> bool:
        if self.active:
            raise FirmwareFlashBusyError("Une installation du firmware est déjà en cours.")
        self._prepare_attempt()
        self._set_state(FlashState.VALIDATING)
        try:
            port = validate_port_name(port_name)
        except ValueError as error:
            self._fail(FlashErrorKind.INVALID_PORT,
                       "Le port série sélectionné est invalide.", str(error))
            return False
        try:
            manifest = FirmwareManifest.load(self.resource_directory / "manifest.json")
            firmware = manifest.verify_hex(self.resource_directory)
        except FirmwareResourceError as error:
            self._fail(FlashErrorKind.FIRMWARE_RESOURCES,
                       "Les ressources du firmware sont invalides.", str(error))
            return False
        try:
            executable, config = manifest.verify_uploader(self.resource_directory)
        except FirmwareResourceError as error:
            self._fail(FlashErrorKind.UPLOADER_RESOURCES,
                       "Les ressources AVRDUDE sont absentes ou corrompues.", str(error))
            return False
        self.resources = FirmwareResources(manifest, firmware, executable, config)
        command = build_avrdude_command(self.resources, port)
        process = self.process_factory(self)
        self._process = process
        process.started.connect(self._on_started)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.errorOccurred.connect(self._on_process_error)
        process.finished.connect(self._on_finished)
        self.phase_changed.emit("Démarrage d’AVRDUDE…")
        self._timeout.start()
        try:
            process.start(str(command.program), list(command.arguments))
        except (OSError, RuntimeError) as error:
            self._fail(FlashErrorKind.START_FAILED,
                       "Impossible de démarrer AVRDUDE.", str(error))
            return False
        return True

    def confirm_firmware(self, firmware_version: tuple[int, int, int],
                         protocol_version: int, capabilities: int) -> bool:
        if self.state is not FlashState.WAITING_FOR_FIRMWARE or self.resources is None:
            raise RuntimeError("La vérification firmware n’est pas attendue.")
        self._set_state(FlashState.VERIFYING_FIRMWARE)
        try:
            result = compare_firmware(self.resources.manifest, firmware_version,
                                      protocol_version, capabilities)
        except ValueError as error:
            self._fail(FlashErrorKind.FIRMWARE_MISMATCH,
                       "Le firmware installé n’a pas pu être validé.", str(error))
            return False
        if result.status is not FirmwareCompatibility.COMPATIBLE:
            self._fail(FlashErrorKind.FIRMWARE_MISMATCH,
                       "Le firmware installé n’a pas pu être validé.", result.status.name)
            return False
        self._set_state(FlashState.SUCCESS)
        self.phase_changed.emit("Firmware Physalix vérifié après reconnexion.")
        self.succeeded.emit(result)
        return True

    def fail_post_flash_verification(self, user_message: str,
                                     technical_details: str) -> None:
        """Terminer un upload dont la reconnexion/identification a échoué."""
        if self.state not in (FlashState.WAITING_FOR_FIRMWARE,
                              FlashState.VERIFYING_FIRMWARE):
            raise RuntimeError("La vérification firmware n’est pas attendue.")
        self._fail(FlashErrorKind.FIRMWARE_MISMATCH,
                   user_message, technical_details)

    def shutdown(self) -> None:
        if self._process_running():
            self._fail(FlashErrorKind.INTERRUPTED,
                       "L’installation du firmware a été interrompue.",
                       "Arrêt de Physalix pendant l’exécution d’AVRDUDE.")
            self._process.terminate()
            self._kill_timer.start()
        else:
            self._timeout.stop()
            self._kill_timer.stop()

    def _prepare_attempt(self) -> None:
        self._timeout.stop()
        self._kill_timer.stop()
        self.resources = None
        self._process = None
        self._technical_log = ""
        self._failure_committed = False

    def _set_state(self, state: FlashState) -> None:
        if state is self.state:
            return
        self.state = state
        self.state_changed.emit(state)

    def _on_started(self) -> None:
        if self._failure_committed:
            return
        self._set_state(FlashState.FLASHING)
        self.phase_changed.emit("Écriture et vérification du flash par AVRDUDE…")

    def _read_stdout(self) -> None:
        if self._process is not None:
            self._append_output("stdout", bytes(self._process.readAllStandardOutput()))

    def _read_stderr(self) -> None:
        if self._process is not None:
            self._append_output("stderr", bytes(self._process.readAllStandardError()))

    def _append_output(self, channel: str, data: bytes) -> None:
        if not data:
            return
        text = data.decode("utf-8", errors="replace")
        entry = f"[{channel}] {text}"
        self._technical_log = (self._technical_log + entry)[-self.log_limit:]
        self.technical_output.emit(entry)

    def _on_process_error(self, error) -> None:
        self._append_output("process", str(error).encode())
        if error == QProcess.ProcessError.FailedToStart:
            self._fail(FlashErrorKind.START_FAILED,
                       "Impossible de démarrer AVRDUDE.", str(error))
        elif error == QProcess.ProcessError.Crashed:
            self._fail(FlashErrorKind.PROCESS_CRASHED,
                       "AVRDUDE s’est arrêté brutalement.", str(error))

    def _on_finished(self, exit_code: int, exit_status) -> None:
        self._timeout.stop()
        self._kill_timer.stop()
        self._read_stdout()
        self._read_stderr()
        self._process = None
        if self._failure_committed:
            self.process_settled.emit()
            return
        if exit_status == QProcess.ExitStatus.CrashExit:
            self._fail(FlashErrorKind.PROCESS_CRASHED,
                       "AVRDUDE s’est arrêté brutalement.",
                       f"exit_code={exit_code}, exit_status={exit_status}")
        elif exit_code != 0:
            self._fail(FlashErrorKind.AVRDUDE_FAILED,
                       "L’installation du firmware a échoué.",
                       f"AVRDUDE a retourné le code {exit_code}.")
        else:
            self._set_state(FlashState.WAITING_FOR_FIRMWARE)
            self.phase_changed.emit(
                "Flash écrit et vérifié ; reconnexion et identification du firmware requises.")
            self.upload_verified.emit(self.resources.manifest)

    def _on_timeout(self) -> None:
        if self.state not in (FlashState.VALIDATING, FlashState.FLASHING):
            return
        self._fail(FlashErrorKind.TIMEOUT,
                   "AVRDUDE ne répond plus ; l’installation a été interrompue.",
                   f"Délai dépassé après {self.timeout_ms} ms.")
        if self._process_running():
            self._process.terminate()
            self._kill_timer.start()

    def _force_kill(self) -> None:
        if self._process_running():
            self._process.kill()

    def _process_running(self) -> bool:
        return (self._process is not None
                and self._process.state() != QProcess.ProcessState.NotRunning)

    def _fail(self, kind: FlashErrorKind, user_message: str,
              technical_details: str) -> None:
        if self._failure_committed:
            return
        self._failure_committed = True
        self._timeout.stop()
        self._append_output("error", technical_details.encode("utf-8", errors="replace"))
        self._set_state(FlashState.FAILED)
        self.phase_changed.emit(user_message)
        self.failed.emit(FlashFailure(kind, user_message, technical_details))
