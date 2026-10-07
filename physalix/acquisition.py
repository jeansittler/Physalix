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
import math
import secrets
import struct

from PySide6.QtCore import QIODeviceBase, QObject, QTimer, Signal
from PySide6.QtSerialPort import QSerialPort


MAGIC = b"\xa5\x5a"
PROTOCOL_VERSION = 1
CAPABILITY_ANALOG_A0 = 0x00000001
CAPABILITY_DIGITAL_STEP = 0x00000002
CAPABILITY_TIMER1_ADC_IRQ = 0x00000004
CAPABILITY_SQUARE_BURST = 0x00000008
CAPABILITY_CONTINUOUS_SQUARE = 0x00000010
REQUIRED_FIRMWARE_CAPABILITIES = (
    CAPABILITY_ANALOG_A0 | CAPABILITY_DIGITAL_STEP | CAPABILITY_TIMER1_ADC_IRQ
)
MAX_PAYLOAD_SIZE = 512
MAX_PARSER_BUFFER = 2 * (len(MAGIC) + 6 + MAX_PAYLOAD_SIZE)
MAX_SAMPLE_COUNT = 1_000_000
SERIAL_RESOURCE_DISCONNECTED_MESSAGE = "Arduino déconnecté."
UNO_LOGIC_LOW_VOLTS = 0.0
UNO_LOGIC_HIGH_VOLTS = 5.0
CONTINUOUS_SQUARE_MIN_FREQUENCY_HZ = 0.1
CONTINUOUS_SQUARE_MAX_FREQUENCY_HZ = 1000.0
TIMER2_CLOCK_HZ = 16_000_000
TIMER2_PRESCALER = 64
TIMER2_TICK_S = TIMER2_PRESCALER / TIMER2_CLOCK_HZ
TIMER2_MIN_HALF_PERIOD_TICKS = 125
TIMER2_MAX_HALF_PERIOD_TICKS = 1_250_000
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
    GEN_CONFIG = 10
    GEN_CONFIG_ACK = 11
    GEN_START = 12
    GEN_START_ACK = 13
    GEN_STOP = 14
    GEN_STOP_ACK = 15
    GEN_STATUS = 16
    GEN_STATUS_ACK = 17
    GEN_KEEPALIVE = 18
    ACQ_STARTED = 19
    DATA_GBF = 20


class AcquisitionState(Enum):
    DISCONNECTED = auto()
    WAITING_HANDSHAKE = auto()
    READY = auto()
    CONFIGURED = auto()
    ACQUIRING = auto()
    STOPPING = auto()
    ERROR = auto()


class GeneratorState(IntEnum):
    """État indépendant du générateur ; UNKNOWN est réservé au suivi côté PC."""

    STOPPED = 0
    RUNNING = 1
    UNKNOWN = 2


class GenerationType(IntEnum):
    STEP = 0
    SQUARE_BURST = 1


class AcquisitionError(ValueError):
    """Configuration, message ou opération d'acquisition invalide."""


class StateTransitionError(AcquisitionError):
    """Transition incohérente du contrôleur."""


@dataclass(frozen=True)
class ContinuousSquareConfig:
    """Demande utilisateur V1 : carré continu 0/5 V, D8 et rapport cyclique 50 %."""

    requested_frequency_hz: float
    pin: int = 8
    low_high: bool = False
    high_high: bool = True

    def validate(self) -> None:
        frequency = self.requested_frequency_hz
        if (isinstance(frequency, bool) or not isinstance(frequency, (int, float))
                or not math.isfinite(frequency)
                or not CONTINUOUS_SQUARE_MIN_FREQUENCY_HZ <= frequency
                <= CONTINUOUS_SQUARE_MAX_FREQUENCY_HZ):
            raise AcquisitionError(
                "La fréquence du carré continu doit être comprise entre 0,1 Hz et 1000 Hz."
            )
        if self.pin != 8:
            raise AcquisitionError("Le carré continu V1 utilise exclusivement la broche D8.")
        if self.low_high is not False or self.high_high is not True:
            raise AcquisitionError("Le carré continu V1 doit utiliser LOW puis HIGH.")

    @property
    def duty_cycle(self) -> float:
        return 0.5


@dataclass(frozen=True)
class ContinuousSquareTimerConfig:
    """Paramètres entiers suffisants pour programmer et relire Timer2."""

    pin: int
    low_high: bool
    high_high: bool
    prescaler: int
    half_period_ticks: int

    def validate(self) -> None:
        if self.pin != 8 or self.low_high is not False or self.high_high is not True:
            raise AcquisitionError("Configuration logique du carré continu invalide.")
        if self.prescaler != TIMER2_PRESCALER:
            raise AcquisitionError("Le carré continu V1 exige le préscaler Timer2 égal à 64.")
        if not (TIMER2_MIN_HALF_PERIOD_TICKS <= self.half_period_ticks
                <= TIMER2_MAX_HALF_PERIOD_TICKS):
            raise AcquisitionError("La demi-période Timer2 est hors de la plage GBF V1.")


@dataclass(frozen=True)
class ContinuousSquarePlan:
    """Demande et paramètres réellement applicables sur Timer2 à 16 MHz."""

    requested: ContinuousSquareConfig
    timer: ContinuousSquareTimerConfig
    applied_frequency_hz: float
    applied_period_s: float

    @property
    def requested_frequency_hz(self) -> float:
        return self.requested.requested_frequency_hz


def plan_continuous_square(config: ContinuousSquareConfig) -> ContinuousSquarePlan:
    """Quantifier la fréquence sur la grille Timer2 V1 de 4 µs."""
    config.validate()
    timer_rate_hz = TIMER2_CLOCK_HZ // TIMER2_PRESCALER
    half_period_ticks = math.floor(
        timer_rate_hz / (2 * config.requested_frequency_hz) + 0.5)
    timer = ContinuousSquareTimerConfig(
        config.pin, config.low_high, config.high_high,
        TIMER2_PRESCALER, half_period_ticks,
    )
    timer.validate()
    applied_frequency_hz = timer_rate_hz / (2 * half_period_ticks)
    return ContinuousSquarePlan(
        config, timer, applied_frequency_hz, 1.0 / applied_frequency_hz)


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

    @property
    def generation_type(self) -> GenerationType:
        return GenerationType.STEP


@dataclass(frozen=True)
class SquareBurstConfig:
    """Carré fini, dont chaque demi-période contient un nombre entier d'intervalles Te."""

    pin: int
    low_high: bool = False
    high_high: bool = True
    period_count: int = 1
    half_period_samples: int = 1

    def validate(self, sample_count: int) -> None:
        if not 2 <= self.pin <= 13:
            raise AcquisitionError("La broche numérique Uno doit être comprise entre 2 et 13.")
        if self.low_high is not False or self.high_high is not True:
            raise AcquisitionError("Le carré Uno doit utiliser LOW comme niveau bas et HIGH comme niveau haut.")
        if self.period_count < 1:
            raise AcquisitionError("Le nombre de périodes du carré doit être au moins égal à 1.")
        if self.half_period_samples < 1:
            raise AcquisitionError("La demi-période du carré doit contenir au moins un intervalle.")
        expected_count = 2 * self.period_count * self.half_period_samples + 1
        if sample_count != expected_count:
            raise AcquisitionError(
                f"Le carré exige exactement {expected_count} points pour finir après "
                f"{self.period_count} période(s)."
            )

    @property
    def generation_type(self) -> GenerationType:
        return GenerationType.SQUARE_BURST


DigitalGenerationConfig = DigitalStepConfig | SquareBurstConfig


@dataclass(frozen=True)
class AcquisitionConfig:
    sampling_period_us: int
    sample_count: int
    analog_channel: int
    generation: DigitalGenerationConfig

    def validate(self) -> None:
        if not 1 <= self.sampling_period_us <= 0xFFFFFFFF:
            raise AcquisitionError("La période d'échantillonnage doit être positive.")
        if not 1 <= self.sample_count <= MAX_SAMPLE_COUNT:
            raise AcquisitionError(f"Le nombre de points doit être compris entre 1 et {MAX_SAMPLE_COUNT}.")
        if not 0 <= self.analog_channel <= 5:
            raise AcquisitionError("La voie analogique doit être comprise entre A0 et A5.")
        if not isinstance(self.generation, (DigitalStepConfig, SquareBurstConfig)):
            raise AcquisitionError("Type de génération numérique inconnu.")
        self.generation.validate(self.sample_count)

    @property
    def digital_step(self) -> DigitalStepConfig:
        """Alias de compatibilité pour le modèle historique spécialisé."""
        if not isinstance(self.generation, DigitalStepConfig):
            raise AcquisitionError("Cette configuration ne contient pas d'échelon numérique.")
        return self.generation


@dataclass(frozen=True)
class SquareBurstPlan:
    """Choix utilisateur et configuration carrée rendue compatible avec l'échantillonnage."""

    requested_duration_s: float
    requested_sample_count: int
    config: AcquisitionConfig

    @property
    def applied_sample_count(self) -> int:
        return self.config.sample_count

    @property
    def requested_sampling_period_us(self) -> int:
        return self.config.sampling_period_us

    @property
    def half_period_samples(self) -> int:
        generation = self.config.generation
        assert isinstance(generation, SquareBurstConfig)
        return generation.half_period_samples


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
class GbfDataBatch:
    """Mesures ADC et niveau E capturé au même index d'échantillonnage."""

    session_id: int
    sequence_number: int
    first_sample_index: int
    values: tuple[int, ...]
    generated_high: tuple[bool, ...]


@dataclass(frozen=True)
class AcquisitionStarted:
    """Le front montant de t=0 est appliqué et la conversion k=0 déclenchée."""

    session_id: int


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


_LEGACY_CONFIG = struct.Struct("<IIBBBI")
_EXTENDED_CONFIG = struct.Struct("<IIBBBBII")
_HELLO_ACK = struct.Struct("<BBBI")
_DATA_HEADER = struct.Struct("<IIIH")
_GENERATOR_CONFIG = struct.Struct("<BBHI")
_GENERATOR_STATE = struct.Struct("<B")
_ACQUISITION_STARTED = struct.Struct("<I")
_SESSION = struct.Struct("<I")
_END = struct.Struct("<II")


def _encoded_levels(low_high: bool, high_high: bool) -> int:
    return int(low_high) | (int(high_high) << 1)


def encode_gen_config(config: ContinuousSquareTimerConfig) -> bytes:
    """Encoder uniquement les paramètres entiers nécessaires à Timer2."""
    config.validate()
    return _GENERATOR_CONFIG.pack(
        config.pin, _encoded_levels(config.low_high, config.high_high),
        config.prescaler, config.half_period_ticks)


def decode_gen_config(payload: bytes) -> ContinuousSquareTimerConfig:
    if len(payload) != _GENERATOR_CONFIG.size:
        raise AcquisitionError("Payload GEN_CONFIG invalide.")
    pin, levels, prescaler, half_period_ticks = _GENERATOR_CONFIG.unpack(payload)
    if levels & ~0x03:
        raise AcquisitionError("Niveaux GEN_CONFIG invalides.")
    config = ContinuousSquareTimerConfig(
        pin, bool(levels & 1), bool(levels & 2), prescaler, half_period_ticks)
    config.validate()
    return config


def encode_gen_config_ack(config: ContinuousSquareTimerConfig) -> bytes:
    return encode_gen_config(config)


def decode_gen_config_ack(payload: bytes) -> ContinuousSquareTimerConfig:
    try:
        return decode_gen_config(payload)
    except AcquisitionError as error:
        raise AcquisitionError(str(error).replace("GEN_CONFIG", "GEN_CONFIG_ACK")) from None


def _decode_empty_generator_command(payload: bytes, name: str) -> None:
    if payload:
        raise AcquisitionError(f"Payload {name} invalide.")


def encode_gen_start() -> bytes:
    return b""


def decode_gen_start(payload: bytes) -> None:
    _decode_empty_generator_command(payload, "GEN_START")


def encode_gen_stop() -> bytes:
    return b""


def decode_gen_stop(payload: bytes) -> None:
    _decode_empty_generator_command(payload, "GEN_STOP")


def encode_gen_status() -> bytes:
    return b""


def decode_gen_status(payload: bytes) -> None:
    _decode_empty_generator_command(payload, "GEN_STATUS")


def encode_gen_keepalive() -> bytes:
    return b""


def decode_gen_keepalive(payload: bytes) -> None:
    _decode_empty_generator_command(payload, "GEN_KEEPALIVE")


def _encode_generator_wire_state(state: GeneratorState) -> bytes:
    if state not in (GeneratorState.STOPPED, GeneratorState.RUNNING):
        raise AcquisitionError("UNKNOWN est un état local et ne peut pas être transmis.")
    return _GENERATOR_STATE.pack(state)


def _decode_generator_wire_state(payload: bytes, name: str) -> GeneratorState:
    if len(payload) != _GENERATOR_STATE.size:
        raise AcquisitionError(f"Payload {name} invalide.")
    try:
        state = GeneratorState(_GENERATOR_STATE.unpack(payload)[0])
    except ValueError:
        raise AcquisitionError(f"État {name} inconnu.") from None
    if state is GeneratorState.UNKNOWN:
        raise AcquisitionError("UNKNOWN est un état local et ne peut pas être reçu.")
    return state


def encode_gen_start_ack() -> bytes:
    return _encode_generator_wire_state(GeneratorState.RUNNING)


def decode_gen_start_ack(payload: bytes) -> GeneratorState:
    state = _decode_generator_wire_state(payload, "GEN_START_ACK")
    if state is not GeneratorState.RUNNING:
        raise AcquisitionError("GEN_START_ACK doit confirmer l'état RUNNING.")
    return state


def encode_gen_stop_ack() -> bytes:
    return _encode_generator_wire_state(GeneratorState.STOPPED)


def decode_gen_stop_ack(payload: bytes) -> GeneratorState:
    state = _decode_generator_wire_state(payload, "GEN_STOP_ACK")
    if state is not GeneratorState.STOPPED:
        raise AcquisitionError("GEN_STOP_ACK doit confirmer l'état STOPPED.")
    return state


def encode_gen_status_ack(state: GeneratorState) -> bytes:
    return _encode_generator_wire_state(state)


def decode_gen_status_ack(payload: bytes) -> GeneratorState:
    return _decode_generator_wire_state(payload, "GEN_STATUS_ACK")


def encode_acquisition_started(started: AcquisitionStarted) -> bytes:
    _check_uint32(started.session_id, "session_id")
    return _ACQUISITION_STARTED.pack(started.session_id)


def decode_acquisition_started(payload: bytes) -> AcquisitionStarted:
    if len(payload) != _ACQUISITION_STARTED.size:
        raise AcquisitionError("Payload ACQ_STARTED invalide.")
    return AcquisitionStarted(_ACQUISITION_STARTED.unpack(payload)[0])


def encode_config(config: AcquisitionConfig, *, extended: bool | None = None) -> bytes:
    """Encoder CONFIG, en conservant par défaut les 15 octets du STEP historique."""
    config.validate()
    generation = config.generation
    if isinstance(generation, DigitalStepConfig) and extended is not True:
        return _LEGACY_CONFIG.pack(
            config.sampling_period_us, config.sample_count, config.analog_channel,
            generation.pin, _encoded_levels(generation.initial_high, generation.final_high),
            generation.transition_sample_index,
        )
    if extended is False:
        raise AcquisitionError("SQUARE_BURST exige le format CONFIG étendu.")
    if isinstance(generation, DigitalStepConfig):
        first_parameter = generation.transition_sample_index
        second_parameter = 0
        low_high = generation.initial_high
        high_high = generation.final_high
    else:
        first_parameter = generation.half_period_samples
        second_parameter = generation.period_count
        low_high = generation.low_high
        high_high = generation.high_high
    return _EXTENDED_CONFIG.pack(
        config.sampling_period_us, config.sample_count, config.analog_channel,
        generation.generation_type, generation.pin,
        _encoded_levels(low_high, high_high), first_parameter, second_parameter,
    )


def decode_config(payload: bytes) -> AcquisitionConfig:
    if len(payload) == _LEGACY_CONFIG.size:
        period, count, channel, pin, levels, transition = _LEGACY_CONFIG.unpack(payload)
        generation: DigitalGenerationConfig = DigitalStepConfig(
            pin, bool(levels & 1), bool(levels & 2), transition)
    elif len(payload) == _EXTENDED_CONFIG.size:
        period, count, channel, generation_value, pin, levels, first, second = (
            _EXTENDED_CONFIG.unpack(payload)
        )
        try:
            generation_type = GenerationType(generation_value)
        except ValueError:
            raise AcquisitionError("Type de génération CONFIG inconnu.") from None
        if generation_type is GenerationType.STEP:
            if second != 0:
                raise AcquisitionError("Paramètre réservé STEP invalide.")
            generation = DigitalStepConfig(pin, bool(levels & 1), bool(levels & 2), first)
        else:
            generation = SquareBurstConfig(
                pin, bool(levels & 1), bool(levels & 2), second, first)
    else:
        raise AcquisitionError("Payload CONFIG invalide.")
    if levels & ~0x03:
        raise AcquisitionError("Niveaux numériques CONFIG invalides.")
    config = AcquisitionConfig(period, count, channel, generation)
    config.validate()
    return config


def plan_square_burst(duration_s: float, requested_sample_count: int, period_count: int,
                      *, pin: int = 8, low_high: bool = False,
                      high_high: bool = True, analog_channel: int = 0) -> SquareBurstPlan:
    """Ajuster les points au carré fini le plus proche et calculer Te en microsecondes."""
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise AcquisitionError("La durée demandée doit être finie et strictement positive.")
    if requested_sample_count < 2:
        raise AcquisitionError("Le nombre de points demandé doit être au moins égal à 2.")
    if period_count < 1:
        raise AcquisitionError("Le nombre de périodes du carré doit être au moins égal à 1.")
    half_period_samples = max(1, round((requested_sample_count - 1) / (2 * period_count)))
    applied_sample_count = 2 * period_count * half_period_samples + 1
    sampling_period_us = max(1, round(duration_s * 1_000_000 / (applied_sample_count - 1)))
    generation = SquareBurstConfig(
        pin, low_high, high_high, period_count, half_period_samples)
    config = AcquisitionConfig(
        sampling_period_us, applied_sample_count, analog_channel, generation)
    config.validate()
    return SquareBurstPlan(duration_s, requested_sample_count, config)


def applied_duration_s(config: AcquisitionConfig) -> float:
    config.validate()
    return (config.sample_count - 1) * config.sampling_period_us / 1_000_000


def applied_square_period_s(config: AcquisitionConfig) -> float:
    config.validate()
    generation = config.generation
    if not isinstance(generation, SquareBurstConfig):
        raise AcquisitionError("La période carrée exige une configuration SQUARE_BURST.")
    return 2 * generation.half_period_samples * config.sampling_period_us / 1_000_000


def applied_square_frequency_hz(config: AcquisitionConfig) -> float:
    return 1.0 / applied_square_period_s(config)


def generated_level(config: AcquisitionConfig, sample_index: int) -> bool:
    """Niveau logique appliqué avant l'échantillon d'index donné."""
    config.validate()
    if not 0 <= sample_index < config.sample_count:
        raise AcquisitionError("L'index demandé doit appartenir à l'acquisition.")
    generation = config.generation
    if isinstance(generation, DigitalStepConfig):
        return (generation.initial_high if sample_index < generation.transition_sample_index
                else generation.final_high)
    last_index = 2 * generation.period_count * generation.half_period_samples
    if sample_index == last_index:
        return generation.low_high
    phase = sample_index // generation.half_period_samples
    return generation.high_high if phase % 2 == 0 else generation.low_high


def generated_voltage(config: AcquisitionConfig, sample_index: int, *,
                      low_volts: float = UNO_LOGIC_LOW_VOLTS,
                      high_volts: float = UNO_LOGIC_HIGH_VOLTS) -> float:
    return high_volts if generated_level(config, sample_index) else low_volts


def generated_voltage_series(config: AcquisitionConfig, count: int | None = None, *,
                             low_volts: float = UNO_LOGIC_LOW_VOLTS,
                             high_volts: float = UNO_LOGIC_HIGH_VOLTS) -> tuple[float, ...]:
    config.validate()
    count = config.sample_count if count is None else count
    if not 0 <= count <= config.sample_count:
        raise AcquisitionError("La série générée dépasse le nombre de points configuré.")
    return tuple(generated_voltage(config, index, low_volts=low_volts,
                                   high_volts=high_volts) for index in range(count))


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


def encode_gbf_data(batch: GbfDataBatch) -> bytes:
    """Encoder ADC puis E, avec bit 0 du premier octet associé au premier point.

    Le futur firmware doit capturer E_k dans l'ISR Timer1, avant de déclencher
    la conversion ADC de l'échantillon k. Le bitmap décrit donc le niveau
    généré exactement à t_k, et non un niveau relu plus tard dans l'ISR ADC.
    """
    for value, name in ((batch.session_id, "session_id"),
                        (batch.sequence_number, "sequence_number"),
                        (batch.first_sample_index, "first_sample_index")):
        _check_uint32(value, name)
    count = len(batch.values)
    if not count:
        raise AcquisitionError("Un lot DATA_GBF ne peut pas être vide.")
    if len(batch.generated_high) != count:
        raise AcquisitionError("Le bitmap E doit contenir un niveau par mesure ADC.")
    if any(not 0 <= value <= 1023 for value in batch.values):
        raise AcquisitionError("Une valeur ADC doit être comprise entre 0 et 1023.")
    if any(type(level) is not bool for level in batch.generated_high):
        raise AcquisitionError("Les niveaux E doivent être booléens.")
    bitmap_size = (count + 7) // 8
    payload_size = _DATA_HEADER.size + 2 * count + bitmap_size
    if payload_size > MAX_PAYLOAD_SIZE:
        raise AcquisitionError("Le lot DATA_GBF dépasse la taille maximale d'une trame.")
    bitmap = bytearray(bitmap_size)
    for index, high in enumerate(batch.generated_high):
        if high:
            bitmap[index // 8] |= 1 << (index % 8)
    return (_DATA_HEADER.pack(batch.session_id, batch.sequence_number,
                              batch.first_sample_index, count)
            + struct.pack(f"<{count}H", *batch.values) + bitmap)


def decode_gbf_data(payload: bytes) -> GbfDataBatch:
    if len(payload) < _DATA_HEADER.size:
        raise AcquisitionError("Payload DATA_GBF tronqué.")
    session_id, sequence, first_index, count = _DATA_HEADER.unpack_from(payload)
    bitmap_size = (count + 7) // 8
    expected_size = _DATA_HEADER.size + 2 * count + bitmap_size
    if not count or len(payload) != expected_size:
        raise AcquisitionError("Nombre de valeurs DATA_GBF incohérent.")
    values = struct.unpack_from(f"<{count}H", payload, _DATA_HEADER.size)
    if any(value > 1023 for value in values):
        raise AcquisitionError("Valeur ADC DATA_GBF invalide.")
    bitmap_offset = _DATA_HEADER.size + 2 * count
    bitmap = payload[bitmap_offset:]
    used_bits = count % 8
    if used_bits and bitmap[-1] & ~((1 << used_bits) - 1):
        raise AcquisitionError("Bits réservés du bitmap E non nuls.")
    generated_high = tuple(
        bool(bitmap[index // 8] & (1 << (index % 8))) for index in range(count)
    )
    return GbfDataBatch(session_id, sequence, first_index, values, generated_high)


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
