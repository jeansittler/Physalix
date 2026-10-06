"""Socle de l'acquisition série Physalix.

Le protocole V1 utilise des entiers little-endian et la trame suivante::

    A5 5A | version:u8 | type:u8 | payload_length:u16 | payload | crc16:u16

Le CRC-16/CCITT-FALSE (initialisé à ``0xffff``) couvre version, type,
longueur et payload. La longueur maximale du payload est 512 octets. Le
parseur conserve les trames incomplètes, rejette les longueurs/CRC invalides
et recherche ensuite la prochaine signature.

Le temps n'est jamais transmis point par point : CONFIG fixe ``Te`` et DATA
porte l'identifiant de session, le numéro du lot et l'index du premier point.
Ainsi le temps du point d'index ``n`` est exactement ``n * Te``.
"""

from __future__ import annotations

import binascii
from dataclasses import dataclass
from enum import Enum, IntEnum, auto
import secrets
import struct

from PySide6.QtCore import QIODeviceBase, QObject, QTimer, Signal
from PySide6.QtSerialPort import QSerialPort


MAGIC = b"\xa5\x5a"
PROTOCOL_VERSION = 1
CAPABILITY_ANALOG_A0 = 0x00000001
CAPABILITY_DIGITAL_STEP = 0x00000002
CAPABILITY_TIMER1_ADC_IRQ = 0x00000004
REQUIRED_FIRMWARE_CAPABILITIES = (
    CAPABILITY_ANALOG_A0 | CAPABILITY_DIGITAL_STEP | CAPABILITY_TIMER1_ADC_IRQ
)
MAX_PAYLOAD_SIZE = 512
MAX_PARSER_BUFFER = 2 * (len(MAGIC) + 6 + MAX_PAYLOAD_SIZE)
MAX_SAMPLE_COUNT = 1_000_000
SERIAL_RESOURCE_DISCONNECTED_MESSAGE = "Arduino déconnecté."
_HEADER = struct.Struct("<2sBBH")
_CRC = struct.Struct("<H")


class MessageType(IntEnum):
    HELLO = 1
    HELLO_ACK = 2
    CONFIG = 3
    CONFIG_ACK = 4
    START = 5
    STOP = 6
    DATA = 7
    END = 8
    ERROR = 9


class AcquisitionState(Enum):
    DISCONNECTED = auto()
    WAITING_HANDSHAKE = auto()
    READY = auto()
    CONFIGURED = auto()
    ACQUIRING = auto()
    STOPPING = auto()
    ERROR = auto()


class AcquisitionError(ValueError):
    """Configuration, message ou opération d'acquisition invalide."""


class StateTransitionError(AcquisitionError):
    """Transition incohérente du contrôleur."""


@dataclass(frozen=True)
class DigitalStepConfig:
    """Échelon produit sur une broche numérique à un index d'échantillon."""

    pin: int
    initial_high: bool = False
    final_high: bool = True
    transition_sample_index: int = 0

    def validate(self, sample_count: int) -> None:
        if not 2 <= self.pin <= 13:
            raise AcquisitionError("La broche numérique Uno doit être comprise entre 2 et 13.")
        if not 0 <= self.transition_sample_index < sample_count:
            raise AcquisitionError("L'index de l'échelon doit appartenir à l'acquisition.")
        if self.initial_high == self.final_high:
            raise AcquisitionError("Les niveaux initial et final de l'échelon doivent différer.")


@dataclass(frozen=True)
class AcquisitionConfig:
    sampling_period_us: int
    sample_count: int
    analog_channel: int
    digital_step: DigitalStepConfig

    def validate(self) -> None:
        if not 1 <= self.sampling_period_us <= 0xFFFFFFFF:
            raise AcquisitionError("La période d'échantillonnage doit être positive.")
        if not 1 <= self.sample_count <= MAX_SAMPLE_COUNT:
            raise AcquisitionError(f"Le nombre de points doit être compris entre 1 et {MAX_SAMPLE_COUNT}.")
        if not 0 <= self.analog_channel <= 5:
            raise AcquisitionError("La voie analogique doit être comprise entre A0 et A5.")
        self.digital_step.validate(self.sample_count)


@dataclass(frozen=True)
class Frame:
    version: int
    message_type: int
    payload: bytes


@dataclass(frozen=True)
class FirmwareInfo:
    version: tuple[int, int, int]
    capabilities: int


@dataclass(frozen=True)
class DataBatch:
    session_id: int
    sequence_number: int
    first_sample_index: int
    values: tuple[int, ...]


@dataclass(frozen=True)
class AcquisitionResult:
    session_id: int | None
    samples: tuple[int, ...]
    complete: bool
    reason: str = ""


def _check_uint32(value: int, name: str) -> None:
    if not 0 <= value <= 0xFFFFFFFF:
        raise AcquisitionError(f"{name} doit être un entier non signé sur 32 bits.")


def encode_frame(message_type: MessageType | int, payload: bytes = b"", *,
                 version: int = PROTOCOL_VERSION) -> bytes:
    """Encoder une trame, sans sérialisation dépendante de Python ou de la locale."""
    payload = bytes(payload)
    if not 0 <= version <= 0xFF:
        raise AcquisitionError("Version de protocole invalide.")
    if not 0 <= int(message_type) <= 0xFF:
        raise AcquisitionError("Type de message invalide.")
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise AcquisitionError(f"Le payload dépasse la limite de {MAX_PAYLOAD_SIZE} octets.")
    body = struct.pack("<BBH", version, int(message_type), len(payload)) + payload
    return MAGIC + body + _CRC.pack(binascii.crc_hqx(body, 0xFFFF))


class FrameParser:
    """Parseur incrémental pur, tolérant fragmentation, concaténation et bruit."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes | bytearray | memoryview) -> list[Frame]:
        self._buffer.extend(data)
        if len(self._buffer) > MAX_PARSER_BUFFER:
            del self._buffer[:-MAX_PARSER_BUFFER]
        frames: list[Frame] = []
        while True:
            magic_index = self._buffer.find(MAGIC)
            if magic_index < 0:
                # Garder A5 : il peut être le premier octet d'une signature fragmentée.
                self._buffer[:] = MAGIC[:1] if self._buffer.endswith(MAGIC[:1]) else b""
                break
            if magic_index:
                del self._buffer[:magic_index]
            if len(self._buffer) < _HEADER.size:
                break
            _, version, message_type, payload_length = _HEADER.unpack_from(self._buffer)
            if payload_length > MAX_PAYLOAD_SIZE:
                del self._buffer[0]
                continue
            frame_length = _HEADER.size + payload_length + _CRC.size
            if len(self._buffer) < frame_length:
                break
            body = bytes(self._buffer[len(MAGIC):_HEADER.size + payload_length])
            expected_crc = _CRC.unpack_from(self._buffer, _HEADER.size + payload_length)[0]
            if binascii.crc_hqx(body, 0xFFFF) != expected_crc:
                del self._buffer[0]
                continue
            payload = bytes(self._buffer[_HEADER.size:_HEADER.size + payload_length])
            frames.append(Frame(version, message_type, payload))
            del self._buffer[:frame_length]
        return frames


_CONFIG = struct.Struct("<IIBBBI")
_HELLO_ACK = struct.Struct("<BBBI")
_DATA_HEADER = struct.Struct("<IIIH")
_SESSION = struct.Struct("<I")
_END = struct.Struct("<II")


def encode_config(config: AcquisitionConfig) -> bytes:
    config.validate()
    step = config.digital_step
    levels = int(step.initial_high) | (int(step.final_high) << 1)
    return _CONFIG.pack(config.sampling_period_us, config.sample_count,
                        config.analog_channel, step.pin, levels,
                        step.transition_sample_index)


def decode_config(payload: bytes) -> AcquisitionConfig:
    if len(payload) != _CONFIG.size:
        raise AcquisitionError("Payload CONFIG invalide.")
    period, count, channel, pin, levels, transition = _CONFIG.unpack(payload)
    if levels & ~0x03:
        raise AcquisitionError("Niveaux numériques CONFIG invalides.")
    config = AcquisitionConfig(period, count, channel,
                               DigitalStepConfig(pin, bool(levels & 1),
                                                 bool(levels & 2), transition))
    config.validate()
    return config


def encode_hello_ack(version: tuple[int, int, int], capabilities: int) -> bytes:
    if len(version) != 3 or any(not 0 <= item <= 0xFF for item in version):
        raise AcquisitionError("Version de firmware invalide.")
    _check_uint32(capabilities, "capabilities")
    return _HELLO_ACK.pack(*version, capabilities)


def decode_hello_ack(payload: bytes) -> FirmwareInfo:
    if len(payload) != _HELLO_ACK.size:
        raise AcquisitionError("Payload HELLO_ACK invalide.")
    major, minor, patch, capabilities = _HELLO_ACK.unpack(payload)
    return FirmwareInfo((major, minor, patch), capabilities)


def encode_data(batch: DataBatch) -> bytes:
    for value, name in ((batch.session_id, "session_id"),
                        (batch.sequence_number, "sequence_number"),
                        (batch.first_sample_index, "first_sample_index")):
        _check_uint32(value, name)
    if not batch.values:
        raise AcquisitionError("Un lot DATA ne peut pas être vide.")
    if len(batch.values) > (MAX_PAYLOAD_SIZE - _DATA_HEADER.size) // 2:
        raise AcquisitionError("Le lot DATA dépasse la taille maximale d'une trame.")
    if any(not 0 <= value <= 1023 for value in batch.values):
        raise AcquisitionError("Une valeur ADC doit être comprise entre 0 et 1023.")
    payload = _DATA_HEADER.pack(batch.session_id, batch.sequence_number,
                                batch.first_sample_index, len(batch.values))
    payload += struct.pack(f"<{len(batch.values)}H", *batch.values)
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise AcquisitionError("Le lot DATA dépasse la taille maximale d'une trame.")
    return payload


def decode_data(payload: bytes) -> DataBatch:
    if len(payload) < _DATA_HEADER.size:
        raise AcquisitionError("Payload DATA tronqué.")
    session_id, sequence, first_index, count = _DATA_HEADER.unpack_from(payload)
    if not count or len(payload) != _DATA_HEADER.size + count * 2:
        raise AcquisitionError("Nombre de valeurs DATA incohérent.")
    values = struct.unpack_from(f"<{count}H", payload, _DATA_HEADER.size)
    if any(value > 1023 for value in values):
        raise AcquisitionError("Valeur ADC DATA invalide.")
    return DataBatch(session_id, sequence, first_index, values)


_TRANSITIONS = {
    AcquisitionState.DISCONNECTED: {AcquisitionState.WAITING_HANDSHAKE, AcquisitionState.ERROR},
    AcquisitionState.WAITING_HANDSHAKE: {AcquisitionState.READY, AcquisitionState.ERROR,
                                         AcquisitionState.DISCONNECTED},
    AcquisitionState.READY: {AcquisitionState.CONFIGURED, AcquisitionState.ERROR,
                             AcquisitionState.DISCONNECTED},
    AcquisitionState.CONFIGURED: {AcquisitionState.ACQUIRING, AcquisitionState.READY,
                                  AcquisitionState.ERROR, AcquisitionState.DISCONNECTED},
    AcquisitionState.ACQUIRING: {AcquisitionState.STOPPING, AcquisitionState.CONFIGURED,
                                 AcquisitionState.ERROR, AcquisitionState.DISCONNECTED},
    AcquisitionState.STOPPING: {AcquisitionState.CONFIGURED, AcquisitionState.ERROR,
                                AcquisitionState.DISCONNECTED},
    AcquisitionState.ERROR: {AcquisitionState.DISCONNECTED, AcquisitionState.WAITING_HANDSHAKE},
}


class AcquisitionController(QObject):
    """Contrôleur non bloquant branché directement sur la boucle événementielle Qt."""

    state_changed = Signal(object)
    ready = Signal(object)
    configuration_accepted = Signal(object)
    data_batch_received = Signal(object)
    acquisition_finished = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None, *, serial_port=None,
                 handshake_timeout_ms: int = 4000, hello_interval_ms: int = 250) -> None:
        super().__init__(parent)
        self.serial = serial_port or QSerialPort(self)
        self.parser = FrameParser()
        self.state = AcquisitionState.DISCONNECTED
        self.config: AcquisitionConfig | None = None
        self.firmware_info: FirmwareInfo | None = None
        self.session_id: int | None = None
        self.samples: list[int] = []
        self._expected_sequence = 0
        self._expected_sample_index = 0
        self.handshake_timeout = QTimer(self)
        self.handshake_timeout.setSingleShot(True)
        self.handshake_timeout.setInterval(handshake_timeout_ms)
        self.handshake_timeout.timeout.connect(self._handshake_timed_out)
        self.hello_timer = QTimer(self)
        self.hello_timer.setInterval(hello_interval_ms)
        self.hello_timer.timeout.connect(self._send_hello)
        self.serial.readyRead.connect(self._on_ready_read)
        self.serial.errorOccurred.connect(self._on_serial_error)

    def _set_state(self, state: AcquisitionState) -> None:
        if state == self.state:
            return
        if state not in _TRANSITIONS[self.state]:
            raise StateTransitionError(f"Transition interdite : {self.state.name} -> {state.name}.")
        self.state = state
        self.state_changed.emit(state)

    def open(self, port_name: str, baud_rate: int = 115200) -> bool:
        if self.state not in (AcquisitionState.DISCONNECTED, AcquisitionState.ERROR):
            raise StateTransitionError("Le port doit être fermé avant son ouverture.")
        if self.state is AcquisitionState.ERROR:
            self._set_state(AcquisitionState.DISCONNECTED)
        self.serial.setPortName(port_name)
        self.serial.setBaudRate(baud_rate)
        if not self.serial.open(QIODeviceBase.OpenModeFlag.ReadWrite):
            self._fail(f"Impossible d'ouvrir {port_name} : {self.serial.errorString()}")
            return False
        self.parser.clear()
        self.config = None
        self.firmware_info = None
        self.session_id = None
        self.samples.clear()
        self._set_state(AcquisitionState.WAITING_HANDSHAKE)
        # L'ouverture peut réinitialiser l'Uno via DTR : HELLO est répété sans blocage.
        self._send_hello()
        self.hello_timer.start()
        self.handshake_timeout.start()
        return True

    def close(self) -> None:
        self.handshake_timeout.stop()
        self.hello_timer.stop()
        if self.serial.isOpen():
            self.serial.close()
        if self.state is not AcquisitionState.DISCONNECTED:
            self._set_state(AcquisitionState.DISCONNECTED)

    def configure(self, config: AcquisitionConfig) -> None:
        if self.state not in (AcquisitionState.READY, AcquisitionState.CONFIGURED):
            raise StateTransitionError("CONFIG exige un firmware prêt.")
        if self.state is AcquisitionState.CONFIGURED:
            self._set_state(AcquisitionState.READY)
        self._write(MessageType.CONFIG, encode_config(config))
        self.config = config

    def start(self, session_id: int | None = None) -> int:
        if self.state is not AcquisitionState.CONFIGURED:
            raise StateTransitionError("START exige une configuration acceptée.")
        session_id = secrets.randbits(32) if session_id is None else session_id
        _check_uint32(session_id, "session_id")
        self._write(MessageType.START, _SESSION.pack(session_id))
        self.session_id = session_id
        self.samples.clear()
        self._expected_sequence = 0
        self._expected_sample_index = 0
        self._set_state(AcquisitionState.ACQUIRING)
        return session_id

    def stop(self) -> bool:
        """Demander l'arrêt une seule fois ; les appels suivants sont sans effet."""
        if self.state is AcquisitionState.STOPPING:
            return False
        if self.state is not AcquisitionState.ACQUIRING:
            return False
        self._write(MessageType.STOP, _SESSION.pack(self.session_id))
        self._set_state(AcquisitionState.STOPPING)
        return True

    def process_bytes(self, data: bytes) -> None:
        """Injecter les octets reçus (également utile aux tests sans port réel)."""
        for frame in self.parser.feed(data):
            try:
                self._handle_frame(frame)
            except (AcquisitionError, StateTransitionError) as error:
                self._fail(str(error))
                break

    def partial_result(self, reason: str = "") -> AcquisitionResult:
        return AcquisitionResult(self.session_id, tuple(self.samples), False, reason)

    def _write(self, message_type: MessageType, payload: bytes = b"") -> None:
        frame = encode_frame(message_type, payload)
        if self.serial.write(frame) < 0:
            raise AcquisitionError(f"Échec d'écriture série : {self.serial.errorString()}")

    def _send_hello(self) -> None:
        if self.state is AcquisitionState.WAITING_HANDSHAKE:
            try:
                self._write(MessageType.HELLO)
            except AcquisitionError as error:
                self._fail(str(error))

    def _on_ready_read(self) -> None:
        self.process_bytes(bytes(self.serial.readAll()))

    def _handshake_timed_out(self) -> None:
        if self.state is AcquisitionState.WAITING_HANDSHAKE:
            self._fail("Délai du handshake expiré.")

    def _on_serial_error(self, error) -> None:
        if error == QSerialPort.SerialPortError.ResourceError:
            self._fail(SERIAL_RESOURCE_DISCONNECTED_MESSAGE)

    def _fail(self, message: str) -> None:
        self.handshake_timeout.stop()
        self.hello_timer.stop()
        if self.serial.isOpen():
            self.serial.close()
        if self.state is not AcquisitionState.ERROR:
            self._set_state(AcquisitionState.ERROR)
        self.error_occurred.emit(message)

    def _handle_frame(self, frame: Frame) -> None:
        if frame.version != PROTOCOL_VERSION:
            raise AcquisitionError(f"Version de protocole incompatible : {frame.version}.")
        try:
            message_type = MessageType(frame.message_type)
        except ValueError:
            raise AcquisitionError(f"Type de message inconnu : {frame.message_type}.") from None

        if message_type is MessageType.HELLO_ACK:
            if self.state is not AcquisitionState.WAITING_HANDSHAKE:
                raise StateTransitionError("HELLO_ACK reçu hors handshake.")
            self.firmware_info = decode_hello_ack(frame.payload)
            self.handshake_timeout.stop()
            self.hello_timer.stop()
            self._set_state(AcquisitionState.READY)
            self.ready.emit(self.firmware_info)
        elif message_type is MessageType.CONFIG_ACK:
            if self.state is not AcquisitionState.READY or self.config is None:
                raise StateTransitionError("CONFIG_ACK reçu sans CONFIG en attente.")
            # Le timer du microcontrôleur peut quantifier Te : conserver les valeurs
            # effectivement appliquées, pas uniquement celles demandées par le PC.
            self.config = decode_config(frame.payload)
            self._set_state(AcquisitionState.CONFIGURED)
            self.configuration_accepted.emit(self.config)
        elif message_type is MessageType.DATA:
            self._handle_data(decode_data(frame.payload))
        elif message_type is MessageType.END:
            self._handle_end(frame.payload)
        elif message_type is MessageType.ERROR:
            self._handle_device_error(frame.payload)
        else:
            raise StateTransitionError(f"{message_type.name} inattendu côté PC.")

    def _handle_data(self, batch: DataBatch) -> None:
        if self.state not in (AcquisitionState.ACQUIRING, AcquisitionState.STOPPING):
            raise StateTransitionError("DATA reçu hors acquisition.")
        if batch.session_id != self.session_id:
            raise AcquisitionError("DATA appartient à une autre session.")
        if batch.sequence_number != self._expected_sequence:
            qualifier = "dupliqué" if batch.sequence_number < self._expected_sequence else "manquant"
            raise AcquisitionError(f"Lot DATA {qualifier} ou incohérent (attendu {self._expected_sequence}, "
                                   f"reçu {batch.sequence_number}).")
        if batch.first_sample_index != self._expected_sample_index:
            raise AcquisitionError(f"Index DATA incohérent (attendu {self._expected_sample_index}, "
                                   f"reçu {batch.first_sample_index}).")
        if self.config is None or len(self.samples) + len(batch.values) > self.config.sample_count:
            raise AcquisitionError("DATA dépasse le nombre de points configuré.")
        self.samples.extend(batch.values)
        self._expected_sequence += 1
        self._expected_sample_index += len(batch.values)
        self.data_batch_received.emit(batch)

    def _handle_end(self, payload: bytes) -> None:
        if self.state not in (AcquisitionState.ACQUIRING, AcquisitionState.STOPPING):
            raise StateTransitionError("END reçu hors acquisition.")
        if len(payload) != _END.size:
            raise AcquisitionError("Payload END invalide.")
        session_id, total = _END.unpack(payload)
        if session_id != self.session_id or total != len(self.samples):
            raise AcquisitionError("Bilan END incohérent avec les données reçues.")
        complete = self.config is not None and total == self.config.sample_count
        result = AcquisitionResult(session_id, tuple(self.samples), complete,
                                   "" if complete else "Acquisition arrêtée avant le nombre demandé.")
        self._set_state(AcquisitionState.CONFIGURED)
        self.acquisition_finished.emit(result)

    def _handle_device_error(self, payload: bytes) -> None:
        if len(payload) < 2:
            raise AcquisitionError("Payload ERROR invalide.")
        code = struct.unpack_from("<H", payload)[0]
        try:
            detail = payload[2:].decode("utf-8")
        except UnicodeDecodeError:
            detail = "message illisible"
        raise AcquisitionError(f"Erreur firmware {code} : {detail}".rstrip())
