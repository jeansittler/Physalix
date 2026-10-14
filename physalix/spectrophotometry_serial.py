"""Contrôleur série Qt non bloquant du spectrophotomètre Physalix."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import math

from PySide6.QtCore import QIODeviceBase, QObject, QTimer, Signal
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from physalix.acquisition import Frame, FrameParser, PROTOCOL_VERSION
from physalix.spectrophotometry_protocol import (
    AS7341Gain,
    SpectroConfig,
    SpectroData,
    SpectroErrorPayload,
    SpectroFirmwareInfo,
    SpectroIllumination,
    SpectroMeasureRequest,
    SpectroMessageType,
    SpectroStopRequest,
    SpectrophotometryProtocolError,
    decode_config_ack,
    decode_data,
    decode_error,
    decode_hello_ack,
    decode_stop_ack,
    encode_config,
    encode_hello,
    encode_measure,
    encode_spectro_frame,
    encode_stop,
)


SPECTRO_BAUD_RATE = 115200
SPECTRO_FIRMWARE_MIN_VERSION = (1, 0, 0)
SPECTRO_REQUIRED_CAPABILITIES = 0x0000001F
SPECTRO_RESOURCE_DISCONNECTED_MESSAGE = "Spectrophotomètre déconnecté."


class SpectroSerialError(ValueError):
    """Erreur de transport, de protocole ou de commande Spectro."""


class SpectroStateError(SpectroSerialError):
    """Opération incompatible avec l'état courant du contrôleur."""


class SpectroControllerState(Enum):
    DISCONNECTED = auto()
    WAITING_HANDSHAKE = auto()
    READY = auto()
    CONFIGURING = auto()
    CONFIGURED = auto()
    MEASURING = auto()
    STOPPING = auto()
    ERROR = auto()


class _PendingCommand(Enum):
    CONFIG = auto()
    MEASURE = auto()
    STOP = auto()


@dataclass(frozen=True)
class SerialPortDescriptor:
    name: str
    description: str
    manufacturer: str
    serial_number: str
    vendor_id: int | None
    product_id: int | None


_TRANSITIONS = {
    SpectroControllerState.DISCONNECTED: {
        SpectroControllerState.WAITING_HANDSHAKE,
        SpectroControllerState.ERROR,
    },
    SpectroControllerState.WAITING_HANDSHAKE: {
        SpectroControllerState.READY,
        SpectroControllerState.ERROR,
        SpectroControllerState.DISCONNECTED,
    },
    SpectroControllerState.READY: {
        SpectroControllerState.CONFIGURING,
        SpectroControllerState.ERROR,
        SpectroControllerState.DISCONNECTED,
    },
    SpectroControllerState.CONFIGURING: {
        SpectroControllerState.READY,
        SpectroControllerState.CONFIGURED,
        SpectroControllerState.ERROR,
        SpectroControllerState.DISCONNECTED,
    },
    SpectroControllerState.CONFIGURED: {
        SpectroControllerState.CONFIGURING,
        SpectroControllerState.MEASURING,
        SpectroControllerState.ERROR,
        SpectroControllerState.DISCONNECTED,
    },
    SpectroControllerState.MEASURING: {
        SpectroControllerState.CONFIGURED,
        SpectroControllerState.STOPPING,
        SpectroControllerState.ERROR,
        SpectroControllerState.DISCONNECTED,
    },
    SpectroControllerState.STOPPING: {
        SpectroControllerState.CONFIGURED,
        SpectroControllerState.ERROR,
        SpectroControllerState.DISCONNECTED,
    },
    SpectroControllerState.ERROR: {
        SpectroControllerState.DISCONNECTED,
    },
}


_FIRMWARE_ERROR_MESSAGES = {
    1: "version de protocole incompatible",
    2: "payload invalide",
    3: "commande inconnue",
    4: "configuration AS7341 invalide",
    5: "capteur AS7341 indisponible",
    6: "échec d'application de la configuration",
    7: "identifiant de configuration incorrect",
    8: "spectrophotomètre occupé",
    9: "démarrage de mesure impossible",
    10: "délai de mesure expiré dans le firmware",
    11: "erreur I²C",
    12: "CRC invalide reçu par le firmware",
    13: "payload supérieur à 512 octets",
}


class SpectrophotometrySerialController(QObject):
    """Machine à états Qt indépendante, avec une seule commande en attente."""

    state_changed = Signal(object)
    ready = Signal(object)
    configuration_accepted = Signal(object)
    measurement_received = Signal(object)
    measurement_failed = Signal(int, str)
    stopped = Signal(int)
    firmware_error = Signal(object)
    response_ignored = Signal(str)
    error_occurred = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        serial_port=None,
        handshake_timeout_ms: int = 5000,
        hello_interval_ms: int = 250,
        config_timeout_ms: int = 3000,
        stop_timeout_ms: int = 2500,
        measurement_margin_ms: int = 5000,
        minimum_measurement_timeout_ms: int = 4000,
    ) -> None:
        super().__init__(parent)
        self.serial = serial_port or QSerialPort(self)
        self.parser = FrameParser()
        self.state = SpectroControllerState.DISCONNECTED
        self.firmware_info: SpectroFirmwareInfo | None = None
        self.config: SpectroConfig | None = None
        self.requested_config: SpectroConfig | None = None
        self.last_measurement: SpectroData | None = None
        self._pending_command: _PendingCommand | None = None
        self._pending_request_id: int | None = None
        self._next_request_id = 1
        self._used_config_ids: set[int] = set()
        self._config_timeout_ms = config_timeout_ms
        self._stop_timeout_ms = stop_timeout_ms
        self._measurement_margin_ms = measurement_margin_ms
        self._minimum_measurement_timeout_ms = minimum_measurement_timeout_ms

        self.handshake_timeout = QTimer(self)
        self.handshake_timeout.setSingleShot(True)
        self.handshake_timeout.setInterval(handshake_timeout_ms)
        self.handshake_timeout.timeout.connect(self._handshake_timed_out)
        self.hello_timer = QTimer(self)
        self.hello_timer.setInterval(hello_interval_ms)
        self.hello_timer.timeout.connect(self._send_hello)
        self.command_timeout = QTimer(self)
        self.command_timeout.setSingleShot(True)
        self.command_timeout.timeout.connect(self._command_timed_out)
        self.serial.readyRead.connect(self._on_ready_read)
        self.serial.errorOccurred.connect(self._on_serial_error)

    @staticmethod
    def available_ports() -> tuple[SerialPortDescriptor, ...]:
        """Lister les ports sans tenter de les ouvrir ni de les réserver."""
        ports = []
        for info in QSerialPortInfo.availablePorts():
            ports.append(SerialPortDescriptor(
                name=info.portName(),
                description=info.description(),
                manufacturer=info.manufacturer(),
                serial_number=info.serialNumber(),
                vendor_id=info.vendorIdentifier() if info.hasVendorIdentifier() else None,
                product_id=info.productIdentifier() if info.hasProductIdentifier() else None,
            ))
        return tuple(ports)

    def _set_state(self, state: SpectroControllerState) -> None:
        if state is self.state:
            return
        if state not in _TRANSITIONS[self.state]:
            raise SpectroStateError(
                f"Transition interdite : {self.state.name} -> {state.name}."
            )
        self.state = state
        self.state_changed.emit(state)

    def _stop_timers(self) -> None:
        self.handshake_timeout.stop()
        self.hello_timer.stop()
        self.command_timeout.stop()

    def _clear_pending(self) -> None:
        self.command_timeout.stop()
        self._pending_command = None
        self._pending_request_id = None
        self.requested_config = None

    def _reset_connection_data(self) -> None:
        self._stop_timers()
        self._clear_pending()
        self.parser.clear()
        self.firmware_info = None
        self.config = None
        self.last_measurement = None
        self._next_request_id = 1
        self._used_config_ids.clear()

    def open(self, port_name: str, baud_rate: int = SPECTRO_BAUD_RATE) -> bool:
        if self.state not in (
            SpectroControllerState.DISCONNECTED,
            SpectroControllerState.ERROR,
        ):
            raise SpectroStateError("Le port doit être fermé avant son ouverture.")
        if self.state is SpectroControllerState.ERROR:
            self._set_state(SpectroControllerState.DISCONNECTED)
        self.serial.setPortName(port_name)
        self.serial.setBaudRate(baud_rate)
        self.serial.setDataBits(QSerialPort.DataBits.Data8)
        self.serial.setParity(QSerialPort.Parity.NoParity)
        self.serial.setStopBits(QSerialPort.StopBits.OneStop)
        self.serial.setFlowControl(QSerialPort.FlowControl.NoFlowControl)
        if not self.serial.open(QIODeviceBase.OpenModeFlag.ReadWrite):
            self._fail(f"Impossible d'ouvrir {port_name} : {self.serial.errorString()}")
            return False
        self._reset_connection_data()
        self._set_state(SpectroControllerState.WAITING_HANDSHAKE)
        self._send_hello()
        if self.state is SpectroControllerState.WAITING_HANDSHAKE:
            self.hello_timer.start()
            self.handshake_timeout.start()
            return True
        return False

    def close(self) -> None:
        self._reset_connection_data()
        if self.serial.isOpen():
            self.serial.close()
        if self.state is not SpectroControllerState.DISCONNECTED:
            self._set_state(SpectroControllerState.DISCONNECTED)

    def configure(self, config: SpectroConfig) -> None:
        if self.state not in (
            SpectroControllerState.READY,
            SpectroControllerState.CONFIGURED,
        ):
            raise SpectroStateError("CONFIG exige un spectrophotomètre prêt.")
        if self._pending_command is not None:
            raise SpectroStateError("Une commande Spectro est déjà en attente.")
        payload = encode_config(config)
        if config.config_id in self._used_config_ids:
            raise SpectroStateError(
                "Un config_id ne peut pas être réutilisé pendant la même connexion."
            )
        previous_state = self.state
        self._write(SpectroMessageType.SPECTRO_CONFIG, payload)
        self._used_config_ids.add(config.config_id)
        self.requested_config = config
        self._pending_command = _PendingCommand.CONFIG
        if previous_state is SpectroControllerState.CONFIGURED:
            self.config = None
        self._set_state(SpectroControllerState.CONFIGURING)
        self.command_timeout.setInterval(self._config_timeout_ms)
        self.command_timeout.start()

    def _allocate_request_id(self) -> int:
        if self._next_request_id > 0xFFFF:
            raise SpectroStateError(
                "Tous les request_id sont épuisés ; reconnectez le spectrophotomètre."
            )
        request_id = self._next_request_id
        self._next_request_id += 1
        return request_id

    def measurement_timeout_ms(self, config: SpectroConfig | None = None) -> int:
        selected = config or self.config
        if selected is None:
            raise SpectroStateError("Le délai de mesure exige une configuration acceptée.")
        cycles = (selected.atime + 1) * (selected.astep + 1)
        integration_ms = math.ceil(cycles * 2 * 2.78 / 1000)
        return max(
            self._minimum_measurement_timeout_ms,
            integration_ms + self._measurement_margin_ms,
        )

    def measure(self, illumination: SpectroIllumination) -> int:
        if self.state is not SpectroControllerState.CONFIGURED or self.config is None:
            raise SpectroStateError("MEASURE exige une configuration acceptée.")
        if self._pending_command is not None:
            raise SpectroStateError("Une commande Spectro est déjà en attente.")
        if not isinstance(illumination, SpectroIllumination):
            raise SpectrophotometryProtocolError("Mode d'illumination invalide.")
        request_id = self._allocate_request_id()
        request = SpectroMeasureRequest(request_id, self.config.config_id, illumination)
        self._write(SpectroMessageType.SPECTRO_MEASURE, encode_measure(request))
        self._pending_command = _PendingCommand.MEASURE
        self._pending_request_id = request_id
        self._set_state(SpectroControllerState.MEASURING)
        self.command_timeout.setInterval(self.measurement_timeout_ms())
        self.command_timeout.start()
        return request_id

    def measure_dark(self) -> int:
        return self.measure(SpectroIllumination.LED_OFF)

    def measure_lit(self) -> int:
        return self.measure(SpectroIllumination.LED_ON)

    def stop(self) -> bool:
        if self.state is SpectroControllerState.STOPPING:
            return False
        if (
            self.state is not SpectroControllerState.MEASURING
            or self._pending_command is not _PendingCommand.MEASURE
            or self._pending_request_id is None
        ):
            return False
        self._send_stop(self._pending_request_id)
        return True

    def _send_stop(self, request_id: int) -> None:
        self._write(
            SpectroMessageType.SPECTRO_STOP,
            encode_stop(SpectroStopRequest(request_id)),
        )
        self._pending_command = _PendingCommand.STOP
        self._set_state(SpectroControllerState.STOPPING)
        self.command_timeout.setInterval(self._stop_timeout_ms)
        self.command_timeout.start()

    def process_bytes(self, data: bytes) -> None:
        """Injecter des octets reçus, notamment dans les tests sans matériel."""
        for frame in self.parser.feed(data):
            try:
                self._handle_frame(frame)
            except (SpectroSerialError, SpectrophotometryProtocolError) as error:
                self._fail(str(error))
                break

    def _write(self, message_type: SpectroMessageType, payload: bytes = b"") -> None:
        if not self.serial.isOpen():
            raise SpectroSerialError("Le port série du spectrophotomètre est fermé.")
        frame = encode_spectro_frame(message_type, payload)
        if self.serial.write(frame) < 0:
            raise SpectroSerialError(
                f"Échec d'écriture série : {self.serial.errorString()}"
            )

    def _send_hello(self) -> None:
        if self.state is SpectroControllerState.WAITING_HANDSHAKE:
            try:
                self._write(SpectroMessageType.SPECTRO_HELLO, encode_hello())
            except SpectroSerialError as error:
                self._fail(str(error))

    def _on_ready_read(self) -> None:
        self.process_bytes(bytes(self.serial.readAll()))

    def _handshake_timed_out(self) -> None:
        if self.state is SpectroControllerState.WAITING_HANDSHAKE:
            self._fail("Délai du handshake spectrophotomètre expiré.")

    def _command_timed_out(self) -> None:
        pending = self._pending_command
        if pending is _PendingCommand.CONFIG:
            self._clear_pending()
            self._set_state(SpectroControllerState.READY)
            self.error_occurred.emit("Délai expiré en attente de SPECTRO_CONFIG_ACK.")
        elif pending is _PendingCommand.MEASURE and self._pending_request_id is not None:
            request_id = self._pending_request_id
            self.error_occurred.emit(
                f"Délai expiré pour la mesure {request_id} ; arrêt demandé."
            )
            try:
                self._send_stop(request_id)
            except SpectroSerialError as error:
                self._fail(str(error))
        elif pending is _PendingCommand.STOP:
            self._fail("Délai expiré en attente de SPECTRO_STOP_ACK.")

    def _on_serial_error(self, error) -> None:
        if error == QSerialPort.SerialPortError.ResourceError:
            self._fail(SPECTRO_RESOURCE_DISCONNECTED_MESSAGE)

    def _fail(self, message: str) -> None:
        failed_request = self._pending_request_id
        self._stop_timers()
        self._clear_pending()
        self.parser.clear()
        if self.serial.isOpen():
            self.serial.close()
        if self.state is not SpectroControllerState.ERROR:
            self._set_state(SpectroControllerState.ERROR)
        if failed_request is not None:
            self.measurement_failed.emit(failed_request, message)
        self.error_occurred.emit(message)

    def _ignore(self, message: str) -> None:
        self.response_ignored.emit(message)

    def _handle_frame(self, frame: Frame) -> None:
        if frame.version != PROTOCOL_VERSION:
            raise SpectroSerialError(
                f"Version de protocole incompatible : {frame.version}."
            )
        try:
            message_type = SpectroMessageType(frame.message_type)
        except ValueError:
            raise SpectroSerialError(
                f"Type de message Spectro inconnu : {frame.message_type}."
            ) from None

        if message_type is SpectroMessageType.SPECTRO_HELLO_ACK:
            self._handle_hello_ack(frame.payload)
        elif message_type is SpectroMessageType.SPECTRO_CONFIG_ACK:
            self._handle_config_ack(frame.payload)
        elif message_type is SpectroMessageType.SPECTRO_DATA:
            self._handle_data(frame.payload)
        elif message_type is SpectroMessageType.SPECTRO_ERROR:
            self._handle_firmware_error(frame.payload)
        elif message_type is SpectroMessageType.SPECTRO_STOP_ACK:
            self._handle_stop_ack(frame.payload)
        else:
            raise SpectroSerialError(
                f"Message {message_type.name} invalide dans le sens firmware vers PC."
            )

    def _handle_hello_ack(self, payload: bytes) -> None:
        if self.state is not SpectroControllerState.WAITING_HANDSHAKE:
            self._ignore("SPECTRO_HELLO_ACK tardif ignoré.")
            return
        info = decode_hello_ack(payload)
        if info.version < SPECTRO_FIRMWARE_MIN_VERSION:
            raise SpectroSerialError(
                "Firmware Spectro trop ancien : " + ".".join(map(str, info.version))
            )
        missing = SPECTRO_REQUIRED_CAPABILITIES & ~info.capabilities
        if missing:
            raise SpectroSerialError(
                f"Capacités Spectro requises absentes : 0x{missing:08X}."
            )
        self.firmware_info = info
        self.handshake_timeout.stop()
        self.hello_timer.stop()
        self._set_state(SpectroControllerState.READY)
        self.ready.emit(info)

    def _handle_config_ack(self, payload: bytes) -> None:
        applied = decode_config_ack(payload)
        if (
            self.state is not SpectroControllerState.CONFIGURING
            or self._pending_command is not _PendingCommand.CONFIG
            or self.requested_config is None
        ):
            self._ignore("SPECTRO_CONFIG_ACK sans CONFIG en attente ignoré.")
            return
        if applied.config_id != self.requested_config.config_id:
            self._ignore(
                f"SPECTRO_CONFIG_ACK obsolète pour config_id={applied.config_id}."
            )
            return
        self.command_timeout.stop()
        self.config = applied
        self._clear_pending()
        self._set_state(SpectroControllerState.CONFIGURED)
        self.configuration_accepted.emit(applied)

    def _handle_data(self, payload: bytes) -> None:
        result = decode_data(payload)
        if (
            self.state is not SpectroControllerState.MEASURING
            or self._pending_command is not _PendingCommand.MEASURE
            or self._pending_request_id is None
            or self.config is None
        ):
            self._ignore(
                f"SPECTRO_DATA tardif pour request_id={result.request_id} ignoré."
            )
            return
        if (
            result.request_id != self._pending_request_id
            or result.config_id != self.config.config_id
        ):
            self._ignore(
                "SPECTRO_DATA obsolète "
                f"(request_id={result.request_id}, config_id={result.config_id}) ignoré."
            )
            return
        self.command_timeout.stop()
        self.last_measurement = result
        self._clear_pending()
        self._set_state(SpectroControllerState.CONFIGURED)
        self.measurement_received.emit(result)

    def _handle_stop_ack(self, payload: bytes) -> None:
        ack = decode_stop_ack(payload)
        if (
            self.state is not SpectroControllerState.STOPPING
            or self._pending_command is not _PendingCommand.STOP
            or self._pending_request_id is None
        ):
            self._ignore(
                f"SPECTRO_STOP_ACK tardif pour request_id={ack.request_id} ignoré."
            )
            return
        if ack.request_id != self._pending_request_id:
            self._ignore(
                f"SPECTRO_STOP_ACK obsolète pour request_id={ack.request_id} ignoré."
            )
            return
        request_id = ack.request_id
        self.command_timeout.stop()
        self._clear_pending()
        self._set_state(SpectroControllerState.CONFIGURED)
        self.stopped.emit(request_id)

    def _handle_firmware_error(self, payload: bytes) -> None:
        error = decode_error(payload)
        if not self._firmware_error_matches_pending(error):
            self._ignore(
                f"SPECTRO_ERROR obsolète pour request_id={error.request_id} ignoré."
            )
            return
        pending = self._pending_command
        request_id = self._pending_request_id
        message = _FIRMWARE_ERROR_MESSAGES.get(
            error.error_code,
            f"erreur firmware inconnue {error.error_code}",
        )
        self._clear_pending()
        if pending is _PendingCommand.CONFIG:
            self._set_state(SpectroControllerState.READY)
        elif pending in (_PendingCommand.MEASURE, _PendingCommand.STOP):
            self._set_state(SpectroControllerState.CONFIGURED)
        self.firmware_error.emit(error)
        if request_id is not None:
            self.measurement_failed.emit(request_id, message)
        self.error_occurred.emit(f"Erreur firmware Spectro : {message}.")

    def _firmware_error_matches_pending(self, error: SpectroErrorPayload) -> bool:
        if self._pending_command is _PendingCommand.CONFIG:
            return error.request_id == 0
        if self._pending_request_id is not None:
            return error.request_id == self._pending_request_id
        return error.request_id == 0
