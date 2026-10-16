"""Codec du protocole binaire V1 du spectrophotomètre Physalix.

Le framing (signature, version, longueur et CRC) reste celui de l'Acquisition.
Ce module ne contient volontairement ni transport série, ni temporisation, ni
logique métier concernant le noir, le blanc, les étalons ou les inconnus.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct

from physalix.acquisition import (
    PROTOCOL_VERSION,
    AcquisitionError,
    encode_frame,
)


SPECTRO_SIGNATURE = b"SPCT"
SPECTRO_DATA_CHANNEL_COUNT = 8
SPECTRO_SATURATION_MASK = 0x03FF


class SpectroMessageType(IntEnum):
    SPECTRO_HELLO = 32
    SPECTRO_HELLO_ACK = 33
    SPECTRO_CONFIG = 34
    SPECTRO_CONFIG_ACK = 35
    SPECTRO_MEASURE = 36
    SPECTRO_DATA = 37
    SPECTRO_ERROR = 38
    SPECTRO_STOP = 39
    SPECTRO_STOP_ACK = 40


class SpectroSensorType(IntEnum):
    AS7341 = 1


class AS7341Gain(IntEnum):
    """Valeurs du champ AGAIN de l'AS7341, de 0,5x à 512x."""

    GAIN_0_5X = 0
    GAIN_1X = 1
    GAIN_2X = 2
    GAIN_4X = 3
    GAIN_8X = 4
    GAIN_16X = 5
    GAIN_32X = 6
    GAIN_64X = 7
    GAIN_128X = 8
    GAIN_256X = 9
    GAIN_512X = 10


class SpectroIllumination(IntEnum):
    LED_OFF = 0
    LED_ON = 1


class SpectrophotometryProtocolError(AcquisitionError):
    """Payload ou valeur invalide pour le protocole spectrophotomètre."""


@dataclass(frozen=True)
class SpectroFirmwareInfo:
    version: tuple[int, int, int]
    sensor_type: SpectroSensorType
    capabilities: int


@dataclass(frozen=True)
class SpectroConfig:
    config_id: int
    atime: int
    astep: int
    gain: AS7341Gain
    led_pwm: int


@dataclass(frozen=True)
class SpectroMeasureRequest:
    request_id: int
    config_id: int
    illumination: SpectroIllumination


@dataclass(frozen=True)
class SpectroData:
    request_id: int
    config_id: int
    illumination: SpectroIllumination
    bands: tuple[int, int, int, int, int, int, int, int]
    clear: int
    nir: int
    saturation_flags: int
    timestamp_ms: int

    def is_saturated(self, channel_index: int) -> bool:
        """Indiquer la saturation de F1..F8 (0..7), Clear (8) ou NIR (9)."""
        _check_uint(channel_index, 4, "channel_index")
        if channel_index > 9:
            raise SpectrophotometryProtocolError(
                "channel_index doit désigner F1 à F8, Clear ou NIR."
            )
        return bool(self.saturation_flags & (1 << channel_index))


@dataclass(frozen=True)
class SpectroErrorPayload:
    request_id: int
    error_code: int


@dataclass(frozen=True)
class SpectroStopRequest:
    request_id: int


_HELLO_ACK = struct.Struct("<4sBBBBI")
_CONFIG = struct.Struct("<HBHBB")
_MEASURE = struct.Struct("<HHB")
_DATA = struct.Struct("<HHB10HHI")
_ERROR = struct.Struct("<HB")
_STOP = struct.Struct("<H")

HELLO_PAYLOAD_SIZE = 0
HELLO_ACK_PAYLOAD_SIZE = _HELLO_ACK.size
CONFIG_PAYLOAD_SIZE = _CONFIG.size
MEASURE_PAYLOAD_SIZE = _MEASURE.size
DATA_PAYLOAD_SIZE = _DATA.size
ERROR_PAYLOAD_SIZE = _ERROR.size
STOP_PAYLOAD_SIZE = _STOP.size


def _check_uint(value: int, bits: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= (1 << bits) - 1:
        raise SpectrophotometryProtocolError(
            f"{name} doit être un entier non signé sur {bits} bits."
        )


def _check_payload(payload: bytes, expected_size: int, name: str) -> None:
    if type(payload) is not bytes or len(payload) != expected_size:
        raise SpectrophotometryProtocolError(f"Payload {name} invalide.")


def _check_version(version: tuple[int, int, int]) -> None:
    if (
        type(version) is not tuple
        or len(version) != 3
        or any(type(item) is not int or not 0 <= item <= 0xFF for item in version)
    ):
        raise SpectrophotometryProtocolError("Version de firmware spectro invalide.")


def _check_gain(gain: AS7341Gain) -> None:
    if not isinstance(gain, AS7341Gain):
        raise SpectrophotometryProtocolError("Code de gain AS7341 invalide.")


def _check_illumination(illumination: SpectroIllumination) -> None:
    if not isinstance(illumination, SpectroIllumination):
        raise SpectrophotometryProtocolError("Mode d'illumination invalide.")


def encode_spectro_frame(message_type: SpectroMessageType, payload: bytes = b"") -> bytes:
    """Encoder une trame spectro avec le framing partagé de l'Acquisition."""
    if not isinstance(message_type, SpectroMessageType):
        raise SpectrophotometryProtocolError("Type de message spectro invalide.")
    if type(payload) is not bytes:
        raise SpectrophotometryProtocolError("Le payload spectro doit être de type bytes.")
    return encode_frame(message_type, payload, version=PROTOCOL_VERSION)


def encode_hello() -> bytes:
    return b""


def decode_hello(payload: bytes) -> None:
    _check_payload(payload, HELLO_PAYLOAD_SIZE, "SPECTRO_HELLO")


def encode_hello_ack(info: SpectroFirmwareInfo) -> bytes:
    if not isinstance(info, SpectroFirmwareInfo):
        raise SpectrophotometryProtocolError("Informations firmware spectro invalides.")
    _check_version(info.version)
    if info.sensor_type is not SpectroSensorType.AS7341:
        raise SpectrophotometryProtocolError("Type de capteur spectro incompatible.")
    _check_uint(info.capabilities, 32, "capabilities")
    return _HELLO_ACK.pack(
        SPECTRO_SIGNATURE,
        *info.version,
        info.sensor_type,
        info.capabilities,
    )


def decode_hello_ack(payload: bytes) -> SpectroFirmwareInfo:
    _check_payload(payload, HELLO_ACK_PAYLOAD_SIZE, "SPECTRO_HELLO_ACK")
    signature, major, minor, patch, sensor_value, capabilities = _HELLO_ACK.unpack(payload)
    if signature != SPECTRO_SIGNATURE:
        raise SpectrophotometryProtocolError("Signature firmware spectro incompatible.")
    try:
        sensor_type = SpectroSensorType(sensor_value)
    except ValueError:
        raise SpectrophotometryProtocolError("Type de capteur spectro incompatible.") from None
    if sensor_type is not SpectroSensorType.AS7341:
        raise SpectrophotometryProtocolError("Type de capteur spectro incompatible.")
    return SpectroFirmwareInfo((major, minor, patch), sensor_type, capabilities)


def _validate_config(config: SpectroConfig) -> None:
    if not isinstance(config, SpectroConfig):
        raise SpectrophotometryProtocolError("Configuration spectro invalide.")
    _check_uint(config.config_id, 16, "config_id")
    _check_uint(config.atime, 8, "atime")
    _check_uint(config.astep, 16, "astep")
    _check_gain(config.gain)
    _check_uint(config.led_pwm, 8, "led_pwm")


def encode_config(config: SpectroConfig) -> bytes:
    _validate_config(config)
    return _CONFIG.pack(
        config.config_id,
        config.atime,
        config.astep,
        config.gain,
        config.led_pwm,
    )


def decode_config(payload: bytes) -> SpectroConfig:
    _check_payload(payload, CONFIG_PAYLOAD_SIZE, "SPECTRO_CONFIG")
    config_id, atime, astep, gain_value, led_pwm = _CONFIG.unpack(payload)
    try:
        gain = AS7341Gain(gain_value)
    except ValueError:
        raise SpectrophotometryProtocolError("Code de gain AS7341 invalide.") from None
    return SpectroConfig(config_id, atime, astep, gain, led_pwm)


def encode_config_ack(config: SpectroConfig) -> bytes:
    return encode_config(config)


def decode_config_ack(payload: bytes) -> SpectroConfig:
    try:
        return decode_config(payload)
    except SpectrophotometryProtocolError as error:
        raise SpectrophotometryProtocolError(
            str(error).replace("SPECTRO_CONFIG", "SPECTRO_CONFIG_ACK")
        ) from None


def _validate_measure_request(request: SpectroMeasureRequest) -> None:
    if not isinstance(request, SpectroMeasureRequest):
        raise SpectrophotometryProtocolError("Demande de mesure spectro invalide.")
    _check_uint(request.request_id, 16, "request_id")
    _check_uint(request.config_id, 16, "config_id")
    _check_illumination(request.illumination)


def encode_measure(request: SpectroMeasureRequest) -> bytes:
    _validate_measure_request(request)
    return _MEASURE.pack(request.request_id, request.config_id, request.illumination)


def decode_measure(payload: bytes) -> SpectroMeasureRequest:
    _check_payload(payload, MEASURE_PAYLOAD_SIZE, "SPECTRO_MEASURE")
    request_id, config_id, illumination_value = _MEASURE.unpack(payload)
    try:
        illumination = SpectroIllumination(illumination_value)
    except ValueError:
        raise SpectrophotometryProtocolError("Mode d'illumination invalide.") from None
    return SpectroMeasureRequest(request_id, config_id, illumination)


def _validate_data(data: SpectroData) -> None:
    if not isinstance(data, SpectroData):
        raise SpectrophotometryProtocolError("Données spectro invalides.")
    _check_uint(data.request_id, 16, "request_id")
    _check_uint(data.config_id, 16, "config_id")
    _check_illumination(data.illumination)
    if type(data.bands) is not tuple or len(data.bands) != SPECTRO_DATA_CHANNEL_COUNT:
        raise SpectrophotometryProtocolError("DATA doit contenir exactement F1 à F8.")
    for index, value in enumerate(data.bands, start=1):
        _check_uint(value, 16, f"F{index}")
    _check_uint(data.clear, 16, "Clear")
    _check_uint(data.nir, 16, "NIR")
    _check_uint(data.saturation_flags, 16, "saturation_flags")
    if data.saturation_flags & ~SPECTRO_SATURATION_MASK:
        raise SpectrophotometryProtocolError("Bits réservés des flags de saturation non nuls.")
    _check_uint(data.timestamp_ms, 32, "timestamp_ms")


def encode_data(data: SpectroData) -> bytes:
    _validate_data(data)
    return _DATA.pack(
        data.request_id,
        data.config_id,
        data.illumination,
        *data.bands,
        data.clear,
        data.nir,
        data.saturation_flags,
        data.timestamp_ms,
    )


def decode_data(payload: bytes) -> SpectroData:
    _check_payload(payload, DATA_PAYLOAD_SIZE, "SPECTRO_DATA")
    unpacked = _DATA.unpack(payload)
    request_id, config_id, illumination_value = unpacked[:3]
    try:
        illumination = SpectroIllumination(illumination_value)
    except ValueError:
        raise SpectrophotometryProtocolError("Mode d'illumination invalide.") from None
    data = SpectroData(
        request_id=request_id,
        config_id=config_id,
        illumination=illumination,
        bands=unpacked[3:11],
        clear=unpacked[11],
        nir=unpacked[12],
        saturation_flags=unpacked[13],
        timestamp_ms=unpacked[14],
    )
    _validate_data(data)
    return data


def encode_error(error: SpectroErrorPayload) -> bytes:
    if not isinstance(error, SpectroErrorPayload):
        raise SpectrophotometryProtocolError("Erreur spectro invalide.")
    _check_uint(error.request_id, 16, "request_id")
    _check_uint(error.error_code, 8, "error_code")
    return _ERROR.pack(error.request_id, error.error_code)


def decode_error(payload: bytes) -> SpectroErrorPayload:
    _check_payload(payload, ERROR_PAYLOAD_SIZE, "SPECTRO_ERROR")
    return SpectroErrorPayload(*_ERROR.unpack(payload))


def encode_stop(request: SpectroStopRequest) -> bytes:
    if not isinstance(request, SpectroStopRequest):
        raise SpectrophotometryProtocolError("Demande d'arrêt spectro invalide.")
    _check_uint(request.request_id, 16, "request_id")
    return _STOP.pack(request.request_id)


def decode_stop(payload: bytes) -> SpectroStopRequest:
    _check_payload(payload, STOP_PAYLOAD_SIZE, "SPECTRO_STOP")
    return SpectroStopRequest(_STOP.unpack(payload)[0])


def encode_stop_ack(request: SpectroStopRequest) -> bytes:
    return encode_stop(request)


def decode_stop_ack(payload: bytes) -> SpectroStopRequest:
    try:
        return decode_stop(payload)
    except SpectrophotometryProtocolError as error:
        raise SpectrophotometryProtocolError(
            str(error).replace("SPECTRO_STOP", "SPECTRO_STOP_ACK")
        ) from None
