"""Tests ciblés du protocole binaire du spectrophotomètre."""

import struct
import unittest

from physalix.acquisition import FrameParser, PROTOCOL_VERSION
from physalix.spectrophotometry_protocol import (
    AS7341Gain,
    CONFIG_PAYLOAD_SIZE,
    DATA_PAYLOAD_SIZE,
    ERROR_PAYLOAD_SIZE,
    HELLO_ACK_PAYLOAD_SIZE,
    HELLO_PAYLOAD_SIZE,
    MEASURE_PAYLOAD_SIZE,
    SPECTRO_SIGNATURE,
    SPECTRO_SATURATION_MASK,
    STOP_PAYLOAD_SIZE,
    SpectroConfig,
    SpectroData,
    SpectroErrorPayload,
    SpectroFirmwareInfo,
    SpectroIllumination,
    SpectroMeasureRequest,
    SpectroMessageType,
    SpectroSensorType,
    SpectroStopRequest,
    SpectrophotometryProtocolError,
    decode_config,
    decode_config_ack,
    decode_data,
    decode_error,
    decode_hello,
    decode_hello_ack,
    decode_measure,
    decode_stop,
    decode_stop_ack,
    encode_config,
    encode_config_ack,
    encode_data,
    encode_error,
    encode_hello,
    encode_hello_ack,
    encode_measure,
    encode_spectro_frame,
    encode_stop,
    encode_stop_ack,
)


def firmware_info() -> SpectroFirmwareInfo:
    return SpectroFirmwareInfo((1, 2, 0), SpectroSensorType.AS7341, 0x12345678)


def config() -> SpectroConfig:
    return SpectroConfig(0x1234, 100, 999, AS7341Gain.GAIN_8X, 255)


def measure() -> SpectroMeasureRequest:
    return SpectroMeasureRequest(0xABCD, 0x1234, SpectroIllumination.LED_ON)


def data() -> SpectroData:
    return SpectroData(
        request_id=0xABCD,
        config_id=0x1234,
        illumination=SpectroIllumination.LED_ON,
        bands=(3175, 26177, 9618, 19108, 21899, 18696, 13496, 5221),
        clear=65535,
        nir=2429,
        saturation_flags=(1 << 1) | (1 << 8),
        timestamp_ms=0x12345678,
    )


class ProtocolLayoutTests(unittest.TestCase):
    def test_message_ids_are_exact_and_unique(self):
        self.assertEqual(
            {message.name: int(message) for message in SpectroMessageType},
            {
                "SPECTRO_HELLO": 32,
                "SPECTRO_HELLO_ACK": 33,
                "SPECTRO_CONFIG": 34,
                "SPECTRO_CONFIG_ACK": 35,
                "SPECTRO_MEASURE": 36,
                "SPECTRO_DATA": 37,
                "SPECTRO_ERROR": 38,
                "SPECTRO_STOP": 39,
                "SPECTRO_STOP_ACK": 40,
            },
        )
        self.assertEqual(len(set(SpectroMessageType)), len(SpectroMessageType))

    def test_payload_sizes_are_exact(self):
        self.assertEqual(
            (
                HELLO_PAYLOAD_SIZE,
                HELLO_ACK_PAYLOAD_SIZE,
                CONFIG_PAYLOAD_SIZE,
                MEASURE_PAYLOAD_SIZE,
                DATA_PAYLOAD_SIZE,
                ERROR_PAYLOAD_SIZE,
                STOP_PAYLOAD_SIZE,
            ),
            (0, 12, 7, 5, 31, 3, 2),
        )

    def test_all_payloads_use_little_endian(self):
        self.assertEqual(
            encode_config(config()),
            b"\x34\x12\x64\xe7\x03\x04\xff",
        )
        self.assertEqual(
            encode_measure(measure()),
            b"\xcd\xab\x34\x12\x01",
        )
        encoded = encode_data(data())
        self.assertEqual(encoded[:5], b"\xcd\xab\x34\x12\x01")
        self.assertEqual(encoded[-6:-4], b"\x02\x01")
        self.assertEqual(encoded[-4:], b"\x78\x56\x34\x12")


class PayloadRoundTripTests(unittest.TestCase):
    def test_hello_and_hello_ack_round_trip(self):
        self.assertEqual(encode_hello(), b"")
        self.assertIsNone(decode_hello(encode_hello()))
        encoded = encode_hello_ack(firmware_info())
        self.assertEqual(encoded[:4], SPECTRO_SIGNATURE)
        self.assertEqual(decode_hello_ack(encoded), firmware_info())

    def test_config_and_ack_round_trip(self):
        self.assertEqual(decode_config(encode_config(config())), config())
        self.assertEqual(decode_config_ack(encode_config_ack(config())), config())

    def test_measure_round_trip_preserves_ids(self):
        self.assertEqual(decode_measure(encode_measure(measure())), measure())

    def test_data_round_trip_preserves_all_channels_and_metadata(self):
        selected = data()
        decoded = decode_data(encode_data(selected))
        self.assertEqual(decoded, selected)
        self.assertEqual(len(decoded.bands), 8)
        self.assertEqual(decoded.clear, 65535)
        self.assertEqual(decoded.nir, 2429)

    def test_error_stop_and_stop_ack_round_trip(self):
        error = SpectroErrorPayload(0xFFFF, 0xFF)
        stop = SpectroStopRequest(0xBEEF)
        self.assertEqual(decode_error(encode_error(error)), error)
        self.assertEqual(decode_stop(encode_stop(stop)), stop)
        self.assertEqual(decode_stop_ack(encode_stop_ack(stop)), stop)


class IdentificationAndGainTests(unittest.TestCase):
    def test_rejects_wrong_signature_and_acquisition_identity(self):
        wrong_signature = struct.pack("<4sBBBBI", b"ACQ1", 1, 2, 0, 1, 0)
        with self.assertRaisesRegex(SpectrophotometryProtocolError, "Signature"):
            decode_hello_ack(wrong_signature)

        acquisition_hello_ack = struct.pack("<BBBI", 1, 2, 0, 0x1F)
        with self.assertRaises(SpectrophotometryProtocolError):
            decode_hello_ack(acquisition_hello_ack)

    def test_rejects_unknown_sensor_identity(self):
        unknown_sensor = struct.pack("<4sBBBBI", SPECTRO_SIGNATURE, 1, 2, 0, 2, 0)
        with self.assertRaisesRegex(SpectrophotometryProtocolError, "capteur"):
            decode_hello_ack(unknown_sensor)

    def test_as7341_gain_codes_cover_only_datasheet_values(self):
        self.assertEqual([int(gain) for gain in AS7341Gain], list(range(11)))
        for gain in AS7341Gain:
            selected = SpectroConfig(1, 0, 0, gain, 0)
            self.assertEqual(decode_config(encode_config(selected)), selected)
        invalid_gain = struct.pack("<HBHBB", 1, 0, 0, 11, 0)
        with self.assertRaisesRegex(SpectrophotometryProtocolError, "gain"):
            decode_config(invalid_gain)


class StrictValidationTests(unittest.TestCase):
    def test_rejects_wrong_payload_sizes_and_types(self):
        decoders_and_sizes = (
            (decode_hello, HELLO_PAYLOAD_SIZE),
            (decode_hello_ack, HELLO_ACK_PAYLOAD_SIZE),
            (decode_config, CONFIG_PAYLOAD_SIZE),
            (decode_config_ack, CONFIG_PAYLOAD_SIZE),
            (decode_measure, MEASURE_PAYLOAD_SIZE),
            (decode_data, DATA_PAYLOAD_SIZE),
            (decode_error, ERROR_PAYLOAD_SIZE),
            (decode_stop, STOP_PAYLOAD_SIZE),
            (decode_stop_ack, STOP_PAYLOAD_SIZE),
        )
        for decoder, size in decoders_and_sizes:
            with self.subTest(decoder=decoder.__name__), self.assertRaises(
                SpectrophotometryProtocolError
            ):
                decoder(b"\x00" * (size + 1))
        with self.assertRaises(SpectrophotometryProtocolError):
            decode_config(bytearray(CONFIG_PAYLOAD_SIZE))

    def test_uint_boundaries_are_accepted(self):
        boundary_config = SpectroConfig(0xFFFF, 0xFF, 0xFFFF, AS7341Gain.GAIN_512X, 0xFF)
        self.assertEqual(decode_config(encode_config(boundary_config)), boundary_config)
        boundary_data = SpectroData(
            0xFFFF,
            0xFFFF,
            SpectroIllumination.LED_OFF,
            (0, 0xFFFF, 0, 0xFFFF, 0, 0xFFFF, 0, 0xFFFF),
            0xFFFF,
            0,
            SPECTRO_SATURATION_MASK,
            0xFFFFFFFF,
        )
        self.assertEqual(decode_data(encode_data(boundary_data)), boundary_data)

    def test_rejects_out_of_range_and_boolean_integer_fields(self):
        invalid_configs = (
            SpectroConfig(-1, 0, 0, AS7341Gain.GAIN_1X, 0),
            SpectroConfig(0x10000, 0, 0, AS7341Gain.GAIN_1X, 0),
            SpectroConfig(1, 0x100, 0, AS7341Gain.GAIN_1X, 0),
            SpectroConfig(1, 0, 0x10000, AS7341Gain.GAIN_1X, 0),
            SpectroConfig(1, 0, 0, AS7341Gain.GAIN_1X, 0x100),
            SpectroConfig(True, 0, 0, AS7341Gain.GAIN_1X, 0),
        )
        for invalid in invalid_configs:
            with self.subTest(config=invalid), self.assertRaises(
                SpectrophotometryProtocolError
            ):
                encode_config(invalid)

        with self.assertRaises(SpectrophotometryProtocolError):
            encode_error(SpectroErrorPayload(1, 0x100))
        with self.assertRaises(SpectrophotometryProtocolError):
            encode_data(data().__class__(**{**data().__dict__, "timestamp_ms": 0x100000000}))

    def test_rejects_invalid_request_and_configuration_ids(self):
        invalid_requests = (
            SpectroMeasureRequest(-1, 1, SpectroIllumination.LED_ON),
            SpectroMeasureRequest(1, 0x10000, SpectroIllumination.LED_ON),
            SpectroMeasureRequest(True, 1, SpectroIllumination.LED_ON),
        )
        for invalid in invalid_requests:
            with self.subTest(request=invalid), self.assertRaises(
                SpectrophotometryProtocolError
            ):
                encode_measure(invalid)
        for invalid_id in (-1, 0x10000, True):
            with self.subTest(request_id=invalid_id), self.assertRaises(
                SpectrophotometryProtocolError
            ):
                encode_stop(SpectroStopRequest(invalid_id))

    def test_rejects_invalid_illumination_and_band_values(self):
        with self.assertRaises(SpectrophotometryProtocolError):
            encode_measure(SpectroMeasureRequest(1, 1, 1))
        invalid_wire_illumination = struct.pack("<HHB", 1, 1, 2)
        with self.assertRaisesRegex(SpectrophotometryProtocolError, "illumination"):
            decode_measure(invalid_wire_illumination)

        with self.assertRaises(SpectrophotometryProtocolError):
            encode_data(data().__class__(**{**data().__dict__, "bands": data().bands[:7]}))
        invalid_bands = list(data().bands)
        invalid_bands[4] = 0x10000
        with self.assertRaises(SpectrophotometryProtocolError):
            encode_data(data().__class__(**{**data().__dict__, "bands": tuple(invalid_bands)}))

    def test_saturation_flags_have_defined_bits_only(self):
        selected = data()
        self.assertFalse(selected.is_saturated(0))
        self.assertTrue(selected.is_saturated(1))
        self.assertTrue(selected.is_saturated(8))
        self.assertFalse(selected.is_saturated(9))
        with self.assertRaises(SpectrophotometryProtocolError):
            selected.is_saturated(10)
        with self.assertRaises(SpectrophotometryProtocolError):
            encode_data(
                data().__class__(**{**data().__dict__, "saturation_flags": 1 << 10})
            )
        invalid_wire_flags = bytearray(encode_data(data()))
        invalid_wire_flags[-6:-4] = struct.pack("<H", 1 << 10)
        with self.assertRaisesRegex(SpectrophotometryProtocolError, "réservés"):
            decode_data(bytes(invalid_wire_flags))


class SharedFramingTests(unittest.TestCase):
    def test_frame_round_trip_uses_shared_v1_parser(self):
        payload = encode_data(data())
        frame = encode_spectro_frame(SpectroMessageType.SPECTRO_DATA, payload)
        parsed = FrameParser().feed(frame)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].version, PROTOCOL_VERSION)
        self.assertEqual(parsed[0].message_type, SpectroMessageType.SPECTRO_DATA)
        self.assertEqual(decode_data(parsed[0].payload), data())

    def test_fragmented_and_concatenated_frames(self):
        hello = encode_spectro_frame(SpectroMessageType.SPECTRO_HELLO, encode_hello())
        config_frame = encode_spectro_frame(
            SpectroMessageType.SPECTRO_CONFIG, encode_config(config())
        )
        parser = FrameParser()
        self.assertEqual(parser.feed(hello[:3]), [])
        frames = parser.feed(hello[3:] + config_frame)
        self.assertEqual(
            [frame.message_type for frame in frames],
            [SpectroMessageType.SPECTRO_HELLO, SpectroMessageType.SPECTRO_CONFIG],
        )

    def test_invalid_crc_is_rejected_and_next_frame_is_recovered(self):
        corrupt = bytearray(
            encode_spectro_frame(SpectroMessageType.SPECTRO_MEASURE, encode_measure(measure()))
        )
        corrupt[-1] ^= 0xFF
        valid = encode_spectro_frame(SpectroMessageType.SPECTRO_STOP, encode_stop(
            SpectroStopRequest(7)
        ))
        frames = FrameParser().feed(bytes(corrupt) + valid)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].message_type, SpectroMessageType.SPECTRO_STOP)
        self.assertEqual(decode_stop(frames[0].payload), SpectroStopRequest(7))

    def test_frame_encoder_rejects_non_spectro_types_and_non_bytes_payload(self):
        with self.assertRaises(SpectrophotometryProtocolError):
            encode_spectro_frame(32, b"")
        with self.assertRaises(SpectrophotometryProtocolError):
            encode_spectro_frame(SpectroMessageType.SPECTRO_HELLO, bytearray())


if __name__ == "__main__":
    unittest.main()
