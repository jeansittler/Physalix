"""Tests ciblés du codec, du parseur et du contrôleur d'acquisition."""

import os
import struct
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtSerialPort import QSerialPort
from PySide6.QtWidgets import QApplication

from physalix.acquisition import (
    AcquisitionConfig,
    AcquisitionController,
    AcquisitionError,
    AcquisitionState,
    AcquisitionStarted,
    CAPABILITY_CONTINUOUS_SQUARE,
    CAPABILITY_SQUARE_BURST,
    CONTINUOUS_SQUARE_MAX_FREQUENCY_HZ,
    CONTINUOUS_SQUARE_MIN_FREQUENCY_HZ,
    ContinuousSquareConfig,
    ContinuousSquareTimerConfig,
    DataBatch,
    DigitalStepConfig,
    ERR_TRIGGER_CANCELLED,
    FrameParser,
    GbfDataBatch,
    GenerationType,
    GeneratorState,
    MAGIC,
    MAX_PARSER_BUFFER,
    MAX_PAYLOAD_SIZE,
    MessageType,
    PROTOCOL_VERSION,
    REQUIRED_FIRMWARE_CAPABILITIES,
    SERIAL_RESOURCE_DISCONNECTED_MESSAGE,
    SquareBurstConfig,
    UNO_LOGIC_HIGH_VOLTS,
    UNO_LOGIC_LOW_VOLTS,
    applied_duration_s,
    applied_square_frequency_hz,
    applied_square_period_s,
    decode_config,
    decode_acquisition_started,
    decode_data,
    encode_config,
    decode_gbf_data,
    decode_gen_config,
    decode_gen_config_ack,
    decode_gen_keepalive,
    decode_gen_start,
    decode_gen_start_ack,
    decode_gen_status,
    decode_gen_status_ack,
    decode_gen_stop,
    decode_gen_stop_ack,
    encode_data,
    encode_acquisition_started,
    encode_frame,
    encode_gbf_data,
    encode_gen_config,
    encode_gen_config_ack,
    encode_gen_keepalive,
    encode_gen_start,
    encode_gen_start_ack,
    encode_gen_status,
    encode_gen_status_ack,
    encode_gen_stop,
    encode_gen_stop_ack,
    encode_hello_ack,
    generated_level,
    generated_voltage_series,
    plan_continuous_square,
    plan_square_burst,
    timer2_ctc_chunks,
)


class FakeSerial(QObject):
    readyRead = Signal()
    errorOccurred = Signal(object)

    def __init__(self):
        super().__init__()
        self.open_result = True
        self.opened = False
        self.writes = []
        self.input = bytearray()
        self.port_name = ""
        self.baud_rate = 0

    def setPortName(self, name):
        self.port_name = name

    def setBaudRate(self, rate):
        self.baud_rate = rate

    def open(self, mode):
        self.opened = self.open_result
        return self.open_result

    def close(self):
        self.opened = False

    def isOpen(self):
        return self.opened

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def readAll(self):
        data = bytes(self.input)
        self.input.clear()
        return data

    def errorString(self):
        return "erreur simulée"


def config(count=4):
    return AcquisitionConfig(1000, count, 0, DigitalStepConfig(8, False, True, 1))


class CodecParserTests(unittest.TestCase):
    def test_complete_and_configuration_round_trip(self):
        frame = encode_frame(MessageType.CONFIG, encode_config(config()))
        parsed = FrameParser().feed(frame)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].message_type, MessageType.CONFIG)
        self.assertEqual(decode_config(parsed[0].payload), config())

    def test_legacy_step_payload_is_byte_for_byte_unchanged(self):
        selected = config()
        expected = struct.pack("<IIBBBI", 1000, 4, 0, 8, 2, 1)
        self.assertEqual(len(expected), 15)
        self.assertEqual(encode_config(selected), expected)
        self.assertEqual(decode_config(expected), selected)

    def test_extended_step_and_square_round_trip(self):
        selected = config()
        extended_step = encode_config(selected, extended=True)
        self.assertEqual(len(extended_step), 20)
        self.assertEqual(extended_step, struct.pack("<IIBBBBII", 1000, 4, 0, 0, 8, 2, 1, 0))
        self.assertEqual(decode_config(extended_step), selected)

        square = AcquisitionConfig(10_000, 13, 0, SquareBurstConfig(8, False, True, 2, 3))
        encoded_square = encode_config(square)
        self.assertEqual(len(encoded_square), 20)
        self.assertEqual(
            encoded_square,
            struct.pack("<IIBBBBII", 10_000, 13, 0, 1, 8, 2, 3, 2),
        )
        self.assertEqual(decode_config(encoded_square), square)

    def test_extended_config_rejects_unknown_or_invalid_parameters(self):
        unknown = struct.pack("<IIBBBBII", 1000, 3, 0, 2, 8, 2, 1, 0)
        with self.assertRaises(AcquisitionError):
            decode_config(unknown)
        invalid_step_reserved = struct.pack("<IIBBBBII", 1000, 3, 0, 0, 8, 2, 1, 1)
        with self.assertRaises(AcquisitionError):
            decode_config(invalid_step_reserved)
        with self.assertRaises(AcquisitionError):
            encode_config(AcquisitionConfig(
                1000, 3, 0, SquareBurstConfig(8, False, True, 1, 1)), extended=False)

    def test_fragmented_frame(self):
        parser = FrameParser()
        frame = encode_frame(MessageType.HELLO)
        self.assertEqual(parser.feed(frame[:1]), [])
        self.assertEqual(parser.feed(frame[1:5]), [])
        self.assertEqual(parser.feed(frame[5:])[0].message_type, MessageType.HELLO)

    def test_concatenated_frames_and_noise(self):
        parser = FrameParser()
        frames = parser.feed(b"bruit\x00" + encode_frame(MessageType.HELLO)
                             + encode_frame(MessageType.STOP, struct.pack("<I", 7)))
        self.assertEqual([frame.message_type for frame in frames],
                         [MessageType.HELLO, MessageType.STOP])

    def test_invalid_length_corruption_and_recovery(self):
        invalid_length = MAGIC + struct.pack("<BBH", 1, MessageType.DATA,
                                              MAX_PAYLOAD_SIZE + 1) + b"junk"
        corrupt = bytearray(encode_frame(MessageType.HELLO))
        corrupt[-1] ^= 0xFF
        valid = encode_frame(MessageType.END, struct.pack("<II", 1, 0))
        parser = FrameParser()
        frames = parser.feed(invalid_length + corrupt + valid)
        self.assertEqual([frame.message_type for frame in frames], [MessageType.END])
        self.assertLessEqual(parser.buffered_bytes, MAX_PARSER_BUFFER)

    def test_maximum_payload_and_oversize_refused(self):
        payload = bytes(MAX_PAYLOAD_SIZE)
        self.assertEqual(FrameParser().feed(encode_frame(MessageType.ERROR, payload))[0].payload,
                         payload)
        with self.assertRaises(AcquisitionError):
            encode_frame(MessageType.ERROR, payload + b"x")


class GenerationModelTests(unittest.TestCase):
    def square_config(self, *, period_us=1000, periods=2, half_samples=3):
        return AcquisitionConfig(
            period_us, 2 * periods * half_samples + 1, 0,
            SquareBurstConfig(8, False, True, periods, half_samples),
        )

    def test_generation_types_and_valid_square(self):
        self.assertEqual(int(GenerationType.STEP), 0)
        self.assertEqual(int(GenerationType.SQUARE_BURST), 1)
        selected = self.square_config()
        selected.validate()
        self.assertEqual(selected.generation.generation_type, GenerationType.SQUARE_BURST)

    def test_square_rejects_invalid_period_half_period_pin_and_levels(self):
        invalid_generations = (
            SquareBurstConfig(8, False, True, 0, 1),
            SquareBurstConfig(8, False, True, 1, 0),
            SquareBurstConfig(1, False, True, 1, 1),
            SquareBurstConfig(8, False, False, 1, 1),
            SquareBurstConfig(8, 0, True, 1, 1),
            SquareBurstConfig(8, True, False, 1, 1),
        )
        for generation in invalid_generations:
            with self.subTest(generation=generation), self.assertRaises(AcquisitionError):
                AcquisitionConfig(1000, 3, 0, generation).validate()

    def test_square_sample_count_invariant_is_strict(self):
        self.square_config(periods=2, half_samples=3).validate()
        for count in (12, 14):
            with self.subTest(count=count), self.assertRaises(AcquisitionError):
                AcquisitionConfig(
                    1000, count, 0, SquareBurstConfig(8, False, True, 2, 3)).validate()

    def test_plan_adjusts_points_and_computes_requested_period(self):
        plan = plan_square_burst(2.0, 200, 2)
        self.assertEqual(plan.requested_sample_count, 200)
        self.assertEqual(plan.half_period_samples, 50)
        self.assertEqual(plan.applied_sample_count, 201)
        self.assertEqual(plan.requested_sampling_period_us, 10_000)
        self.assertEqual(plan.requested_duration_s, 2.0)

    def test_plan_rounding_and_minimum_half_period(self):
        rounded_up = plan_square_burst(1.0, 12, 2)
        self.assertEqual(rounded_up.half_period_samples, 3)
        self.assertEqual(rounded_up.applied_sample_count, 13)
        minimum = plan_square_burst(1.0, 2, 20)
        self.assertEqual(minimum.half_period_samples, 1)
        self.assertEqual(minimum.applied_sample_count, 41)
        self.assertEqual(minimum.requested_sampling_period_us, 25_000)

    def test_plan_rejects_invalid_user_values(self):
        for arguments in ((0.0, 10, 1), (1.0, 1, 1), (1.0, 10, 0)):
            with self.subTest(arguments=arguments), self.assertRaises(AcquisitionError):
                plan_square_burst(*arguments)

    def test_applied_timing_uses_ack_period(self):
        applied = self.square_config(period_us=1004, periods=2, half_samples=3)
        self.assertEqual(applied_duration_s(applied), 0.012048)
        self.assertEqual(applied_square_period_s(applied), 0.006024)
        self.assertAlmostEqual(applied_square_frequency_hz(applied), 1 / 0.006024)

    def test_square_level_reconstruction_and_partial_voltage_series(self):
        selected = self.square_config(periods=2, half_samples=2)
        expected = (True, True, False, False, True, True, False, False, False)
        self.assertEqual(tuple(generated_level(selected, index)
                               for index in range(selected.sample_count)), expected)
        self.assertTrue(generated_level(selected, 0))
        self.assertFalse(generated_level(selected, 2))
        self.assertTrue(generated_level(selected, 4))
        self.assertFalse(generated_level(selected, 8))
        self.assertEqual(
            generated_voltage_series(selected, 5),
            (UNO_LOGIC_HIGH_VOLTS, UNO_LOGIC_HIGH_VOLTS,
             UNO_LOGIC_LOW_VOLTS, UNO_LOGIC_LOW_VOLTS, UNO_LOGIC_HIGH_VOLTS),
        )

    def test_square_capability_is_optional_for_current_firmware(self):
        self.assertEqual(CAPABILITY_SQUARE_BURST, 0x00000008)
        self.assertFalse(REQUIRED_FIRMWARE_CAPABILITIES & CAPABILITY_SQUARE_BURST)
        current_firmware_capabilities = REQUIRED_FIRMWARE_CAPABILITIES
        self.assertEqual(
            current_firmware_capabilities & REQUIRED_FIRMWARE_CAPABILITIES,
            REQUIRED_FIRMWARE_CAPABILITIES,
        )


class ContinuousSquareModelTests(unittest.TestCase):
    def test_capability_and_generator_state_are_independent(self):
        self.assertEqual(CAPABILITY_CONTINUOUS_SQUARE, 0x00000010)
        self.assertFalse(REQUIRED_FIRMWARE_CAPABILITIES & CAPABILITY_CONTINUOUS_SQUARE)
        self.assertEqual(
            list(GeneratorState),
            [GeneratorState.STOPPED, GeneratorState.RUNNING, GeneratorState.UNKNOWN],
        )

    def test_timer2_quantization_for_representative_frequencies(self):
        expected_ticks = {
            0.1: 1_250_000,
            0.5: 250_000,
            1.0: 125_000,
            10.0: 12_500,
            50.0: 2_500,
            100.0: 1_250,
            500.0: 250,
            1000.0: 125,
        }
        for frequency, ticks in expected_ticks.items():
            with self.subTest(frequency=frequency):
                plan = plan_continuous_square(ContinuousSquareConfig(frequency))
                self.assertEqual(plan.requested_frequency_hz, frequency)
                self.assertEqual(plan.timer.prescaler, 64)
                self.assertEqual(plan.timer.half_period_ticks, ticks)
                self.assertEqual(plan.timer.pin, 8)
                self.assertFalse(plan.timer.low_high)
                self.assertTrue(plan.timer.high_high)
                self.assertAlmostEqual(plan.applied_frequency_hz, frequency)
                self.assertAlmostEqual(plan.applied_period_s, 1 / frequency)
                self.assertEqual(plan.requested.duty_cycle, 0.5)

    def test_timer2_quantization_for_non_exact_frequencies(self):
        for frequency, ticks in ((123.0, 1016), (333.0, 375), (997.0, 125)):
            with self.subTest(frequency=frequency):
                plan = plan_continuous_square(ContinuousSquareConfig(frequency))
                self.assertEqual(plan.timer.half_period_ticks, ticks)
                self.assertEqual(plan.applied_frequency_hz, 125_000 / ticks)
                self.assertEqual(plan.applied_period_s, 2 * ticks * 4e-6)

    def test_continuous_square_rejects_frequency_pin_and_levels(self):
        invalid_frequencies = (
            CONTINUOUS_SQUARE_MIN_FREQUENCY_HZ - 0.001,
            CONTINUOUS_SQUARE_MAX_FREQUENCY_HZ + 0.001,
            float("nan"), float("inf"), -float("inf"), True,
        )
        for frequency in invalid_frequencies:
            with self.subTest(frequency=frequency), self.assertRaises(AcquisitionError):
                plan_continuous_square(ContinuousSquareConfig(frequency))
        for config in (
            ContinuousSquareConfig(10, pin=11),
            ContinuousSquareConfig(10, low_high=True),
            ContinuousSquareConfig(10, high_high=False),
        ):
            with self.subTest(config=config), self.assertRaises(AcquisitionError):
                plan_continuous_square(config)

    def test_timer2_ctc_chunks_are_exact_and_compare_is_chunk_minus_one(self):
        for total_ticks in (1, 125, 250, 256, 257, 1250, 12500, 125000, 1250000):
            with self.subTest(total_ticks=total_ticks):
                chunks = timer2_ctc_chunks(total_ticks)
                self.assertEqual(sum(chunks), total_ticks)
                self.assertTrue(all(1 <= chunk <= 256 for chunk in chunks))
                self.assertEqual([chunk - 1 for chunk in chunks],
                                 [min(remaining, 256) - 1
                                  for remaining in range(total_ticks, 0, -256)])


class ContinuousSquareCodecTests(unittest.TestCase):
    def timer_config(self):
        return plan_continuous_square(ContinuousSquareConfig(10)).timer

    def test_all_protocol_ids_are_unique_and_framing_stays_v1(self):
        self.assertEqual(len({int(message) for message in MessageType}), len(MessageType))
        self.assertEqual(PROTOCOL_VERSION, 1)
        self.assertEqual(
            {message.name: int(message) for message in MessageType},
            {
                "HELLO": 1, "HELLO_ACK": 2, "CONFIG": 3, "CONFIG_ACK": 4,
                "START": 5, "STOP": 6, "DATA": 7, "END": 8, "ERROR": 9,
                "GEN_CONFIG": 10, "GEN_CONFIG_ACK": 11,
                "GEN_START": 12, "GEN_START_ACK": 13,
                "GEN_STOP": 14, "GEN_STOP_ACK": 15,
                "GEN_STATUS": 16, "GEN_STATUS_ACK": 17,
                "GEN_KEEPALIVE": 18, "ACQ_STARTED": 19, "DATA_GBF": 20,
            },
        )

    def test_gen_config_and_ack_round_trip_exact_integer_format(self):
        config = self.timer_config()
        expected = struct.pack("<BBHI", 8, 0x02, 64, 12_500)
        self.assertEqual(encode_gen_config(config), expected)
        self.assertEqual(decode_gen_config(expected), config)
        self.assertEqual(encode_gen_config_ack(config), expected)
        self.assertEqual(decode_gen_config_ack(expected), config)
        for invalid in (
            expected[:-1],
            struct.pack("<BBHI", 8, 0x82, 64, 12_500),
            struct.pack("<BBHI", 8, 0x02, 8, 12_500),
            struct.pack("<BBHI", 9, 0x02, 64, 12_500),
            struct.pack("<BBHI", 8, 0x02, 64, 0),
            struct.pack("<BBHI", 8, 0x02, 64, 124),
            struct.pack("<BBHI", 8, 0x02, 64, 1_250_001),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(AcquisitionError):
                decode_gen_config(invalid)

    def test_empty_start_stop_status_and_keepalive_payloads(self):
        codecs = (
            (encode_gen_start, decode_gen_start),
            (encode_gen_stop, decode_gen_stop),
            (encode_gen_status, decode_gen_status),
            (encode_gen_keepalive, decode_gen_keepalive),
        )
        for encode, decode in codecs:
            with self.subTest(codec=encode.__name__):
                self.assertEqual(encode(), b"")
                self.assertIsNone(decode(b""))
                with self.assertRaises(AcquisitionError):
                    decode(b"\x00")

    def test_start_stop_and_status_ack_states(self):
        self.assertEqual(decode_gen_start_ack(encode_gen_start_ack()), GeneratorState.RUNNING)
        self.assertEqual(decode_gen_stop_ack(encode_gen_stop_ack()), GeneratorState.STOPPED)
        for state in (GeneratorState.STOPPED, GeneratorState.RUNNING):
            with self.subTest(state=state):
                self.assertEqual(decode_gen_status_ack(encode_gen_status_ack(state)), state)
        with self.assertRaises(AcquisitionError):
            encode_gen_status_ack(GeneratorState.UNKNOWN)
        with self.assertRaises(AcquisitionError):
            decode_gen_status_ack(b"\x02")
        with self.assertRaises(AcquisitionError):
            decode_gen_start_ack(b"\x00")
        with self.assertRaises(AcquisitionError):
            decode_gen_stop_ack(b"\x01")

    def test_acquisition_started_explicitly_identifies_t0_and_session(self):
        started = AcquisitionStarted(0x12345678)
        payload = encode_acquisition_started(started)
        self.assertEqual(payload, struct.pack("<I", 0x12345678))
        self.assertEqual(decode_acquisition_started(payload), started)
        for invalid in (b"", payload[:-1], payload + b"\x00"):
            with self.subTest(invalid=invalid), self.assertRaises(AcquisitionError):
                decode_acquisition_started(invalid)

    def test_gbf_data_bitmap_round_trip_sizes_and_lsb_first_order(self):
        for count in (1, 7, 8, 9, 48):
            levels = tuple(index % 2 == 0 for index in range(count))
            batch = GbfDataBatch(42, 3, 10, tuple(range(count)), levels)
            payload = encode_gbf_data(batch)
            bitmap_size = (count + 7) // 8
            self.assertEqual(len(payload), 14 + 2 * count + bitmap_size)
            self.assertEqual(decode_gbf_data(payload), batch)
            self.assertEqual(payload[14 + 2 * count], 0x55 & ((1 << min(count, 8)) - 1))
            if count == 9:
                self.assertEqual(payload[-2:], b"\x55\x01")
            if count == 48:
                self.assertEqual(payload[-6:], b"\x55" * 6)

    def test_gbf_data_rejects_truncated_incoherent_and_reserved_bits(self):
        batch = GbfDataBatch(1, 2, 3, tuple(range(9)),
                             (True, False, True, False, True, False, True, False, True))
        payload = encode_gbf_data(batch)
        invalid_payloads = [payload[:-1], payload + b"\x00"]
        reserved = bytearray(payload)
        reserved[-1] |= 0x80
        invalid_payloads.append(bytes(reserved))
        invalid_count = bytearray(payload)
        struct.pack_into("<H", invalid_count, 12, 8)
        invalid_payloads.append(bytes(invalid_count))
        for invalid in invalid_payloads:
            with self.subTest(invalid=invalid), self.assertRaises(AcquisitionError):
                decode_gbf_data(invalid)
        with self.assertRaises(AcquisitionError):
            encode_gbf_data(GbfDataBatch(1, 0, 0, (1, 2), (True,)))
        with self.assertRaises(AcquisitionError):
            encode_gbf_data(GbfDataBatch(1, 0, 0, (1024,), (True,)))

    def test_historical_data_payload_is_strictly_unchanged(self):
        batch = DataBatch(42, 3, 10, (0, 512, 1023))
        expected = struct.pack("<IIIH3H", 42, 3, 10, 3, 0, 512, 1023)
        self.assertEqual(encode_data(batch), expected)
        self.assertEqual(decode_data(expected), batch)


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.serial = FakeSerial()
        self.controller = AcquisitionController(serial_port=self.serial)

    def handshake(self, version=PROTOCOL_VERSION):
        self.assertTrue(self.controller.open("COM9"))
        self.controller.process_bytes(encode_frame(
            MessageType.HELLO_ACK, encode_hello_ack((1, 2, 3), 5), version=version))

    def configure_and_start(self, count=4, session=42):
        self.handshake()
        selected = config(count)
        self.controller.configure(selected)
        self.assertEqual(self.controller.state, AcquisitionState.READY)
        self.controller.process_bytes(encode_frame(MessageType.CONFIG_ACK, encode_config(selected)))
        self.assertEqual(self.controller.state, AcquisitionState.CONFIGURED)
        self.assertEqual(self.controller.start(session), session)

    def test_initial_handshake_and_config_ack(self):
        self.assertEqual(self.controller.state, AcquisitionState.DISCONNECTED)
        ready = []
        accepted = []
        self.controller.ready.connect(ready.append)
        self.controller.configuration_accepted.connect(accepted.append)
        self.handshake()
        self.assertEqual(self.controller.state, AcquisitionState.READY)
        self.assertEqual(ready[0].version, (1, 2, 3))
        selected = config()
        self.controller.configure(selected)
        applied = AcquisitionConfig(1004, 4, 0, selected.digital_step)
        self.controller.process_bytes(encode_frame(MessageType.CONFIG_ACK, encode_config(applied)))
        self.assertEqual(self.controller.state, AcquisitionState.CONFIGURED)
        self.assertEqual(self.controller.config, applied)
        self.assertEqual(accepted, [applied])

    def test_extended_square_config_ack_keeps_applied_timer_period(self):
        self.handshake()
        requested = AcquisitionConfig(
            1000, 13, 0, SquareBurstConfig(8, False, True, 2, 3))
        self.controller.configure(requested)
        written = FrameParser().feed(self.serial.writes[-1])[0]
        self.assertEqual(len(written.payload), 20)
        applied = AcquisitionConfig(
            1004, 13, 0, SquareBurstConfig(8, False, True, 2, 3))
        self.controller.process_bytes(encode_frame(
            MessageType.CONFIG_ACK, encode_config(applied)))
        self.assertEqual(self.controller.config, applied)
        self.assertEqual(applied_duration_s(self.controller.config), 0.012048)

    def test_incompatible_protocol_version(self):
        errors = []
        self.controller.error_occurred.connect(errors.append)
        self.handshake(version=PROTOCOL_VERSION + 1)
        self.assertEqual(self.controller.state, AcquisitionState.ERROR)
        self.assertIn("incompatible", errors[0])

    def test_successive_data_and_end(self):
        results = []
        self.controller.acquisition_finished.connect(results.append)
        self.configure_and_start()
        first = DataBatch(42, 0, 0, (100, 200))
        second = DataBatch(42, 1, 2, (300, 400))
        self.controller.process_bytes(encode_frame(MessageType.DATA, encode_data(first))
                                      + encode_frame(MessageType.DATA, encode_data(second)))
        self.controller.process_bytes(encode_frame(MessageType.END, struct.pack("<II", 42, 4)))
        self.assertEqual(self.controller.state, AcquisitionState.CONFIGURED)
        self.assertEqual(results[0].samples, (100, 200, 300, 400))
        self.assertTrue(results[0].complete)

    def test_missing_duplicate_or_incoherent_sequence_preserves_partial(self):
        for sequence, first_index in ((2, 2), (0, 2)):
            with self.subTest(sequence=sequence, first_index=first_index):
                serial = FakeSerial()
                controller = AcquisitionController(serial_port=serial)
                controller.open("COM9")
                controller.process_bytes(encode_frame(
                    MessageType.HELLO_ACK, encode_hello_ack((1, 0, 0), 0)))
                controller.configure(config())
                controller.process_bytes(encode_frame(MessageType.CONFIG_ACK,
                                                      encode_config(config())))
                controller.start(42)
                controller.process_bytes(encode_frame(
                    MessageType.DATA, encode_data(DataBatch(42, 0, 0, (10, 20)))))
                controller.process_bytes(encode_frame(
                    MessageType.DATA, encode_data(DataBatch(42, sequence, first_index, (30, 40)))))
                self.assertEqual(controller.state, AcquisitionState.ERROR)
                self.assertEqual(controller.partial_result().samples, (10, 20))

    def test_device_error_preserves_partial(self):
        self.configure_and_start()
        self.controller.process_bytes(encode_frame(
            MessageType.DATA, encode_data(DataBatch(42, 0, 0, (10, 20)))))
        self.controller.process_bytes(encode_frame(MessageType.ERROR,
                                                   struct.pack("<H", 7) + b"ADC busy"))
        self.assertEqual(self.controller.state, AcquisitionState.ERROR)
        self.assertEqual(self.controller.samples, [10, 20])

    def test_handshake_timeout(self):
        errors = []
        self.controller.error_occurred.connect(errors.append)
        self.controller.open("COM9")
        self.controller._handshake_timed_out()
        self.assertEqual(self.controller.state, AcquisitionState.ERROR)
        self.assertFalse(self.serial.isOpen())
        self.assertEqual(errors, ["Délai du handshake expiré."])

    def test_invalid_transition_and_reconnect_after_error(self):
        with self.assertRaises(AcquisitionError):
            self.controller.start(1)
        self.controller.open("COM9")
        self.controller._handshake_timed_out()
        self.assertTrue(self.controller.open("COM9"))
        self.assertEqual(self.controller.state, AcquisitionState.WAITING_HANDSHAKE)

    def test_stop_is_idempotent_and_end_can_be_partial(self):
        results = []
        self.controller.acquisition_finished.connect(results.append)
        self.configure_and_start()
        writes_before = len(self.serial.writes)
        self.assertTrue(self.controller.stop())
        self.assertFalse(self.controller.stop())
        self.assertEqual(len(self.serial.writes), writes_before + 1)
        self.controller.process_bytes(encode_frame(MessageType.END, struct.pack("<II", 42, 0)))
        self.assertFalse(results[0].complete)

    def test_a_completed_acquisition_can_be_reconfigured(self):
        self.configure_and_start()
        self.controller.process_bytes(encode_frame(MessageType.END, struct.pack("<II", 42, 0)))
        replacement = config(count=8)
        self.controller.configure(replacement)
        self.assertEqual(self.controller.state, AcquisitionState.READY)
        self.assertEqual(self.controller.config, replacement)
        self.controller.process_bytes(encode_frame(
            MessageType.CONFIG_ACK, encode_config(replacement)))
        self.assertEqual(self.controller.state, AcquisitionState.CONFIGURED)

    def test_resource_error_disconnect_and_partial_data(self):
        errors = []
        self.controller.error_occurred.connect(errors.append)
        self.configure_and_start()
        self.controller.process_bytes(encode_frame(
            MessageType.DATA, encode_data(DataBatch(42, 0, 0, (10, 20)))))
        self.serial.errorOccurred.emit(QSerialPort.SerialPortError.ResourceError)
        self.assertEqual(self.controller.state, AcquisitionState.ERROR)
        self.assertFalse(self.serial.isOpen())
        self.assertEqual(errors, [SERIAL_RESOURCE_DISCONNECTED_MESSAGE])
        self.assertEqual(self.controller.partial_result().samples, (10, 20))
        self.assertTrue(self.controller.open("COM9"))
        self.assertEqual(self.controller.state, AcquisitionState.WAITING_HANDSHAKE)

    def test_resource_error_disconnect_without_acquisition(self):
        errors = []
        self.controller.error_occurred.connect(errors.append)
        self.handshake()

        self.serial.errorOccurred.emit(QSerialPort.SerialPortError.ResourceError)

        self.assertEqual(self.controller.state, AcquisitionState.ERROR)
        self.assertFalse(self.serial.isOpen())
        self.assertEqual(errors, [SERIAL_RESOURCE_DISCONNECTED_MESSAGE])


class GeneratorControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.serial = FakeSerial()
        self.controller = AcquisitionController(
            serial_port=self.serial, generator_command_timeout_ms=50,
            generator_keepalive_interval_ms=25, trigger_margin_ms=1000)

    def tearDown(self):
        self.controller.close()

    def last_frame(self):
        frames = FrameParser().feed(self.serial.writes[-1])
        self.assertEqual(len(frames), 1)
        return frames[0]

    def handshake_generator(self, status=GeneratorState.STOPPED):
        self.assertTrue(self.controller.open("COM9"))
        self.controller.process_bytes(encode_frame(
            MessageType.HELLO_ACK,
            encode_hello_ack((1, 2, 0),
                             REQUIRED_FIRMWARE_CAPABILITIES | CAPABILITY_CONTINUOUS_SQUARE)))
        self.assertEqual(self.last_frame().message_type, MessageType.GEN_STATUS)
        self.assertEqual(self.controller.generator_state, GeneratorState.UNKNOWN)
        self.controller.process_bytes(encode_frame(
            MessageType.GEN_STATUS_ACK, encode_gen_status_ack(status)))
        self.assertEqual(self.controller.generator_state, status)

    def configure_generator(self, frequency=10.0, *, applied_ticks=None):
        requested = self.controller.configure_generator(ContinuousSquareConfig(frequency))
        frame = self.last_frame()
        self.assertEqual(frame.message_type, MessageType.GEN_CONFIG)
        self.assertEqual(decode_gen_config(frame.payload), requested.timer)
        timer = requested.timer if applied_ticks is None else ContinuousSquareTimerConfig(
            8, False, True, 64, applied_ticks)
        self.controller.process_bytes(encode_frame(
            MessageType.GEN_CONFIG_ACK, encode_gen_config_ack(timer)))
        return requested, timer

    def start_running_generator(self, frequency=10.0):
        self.handshake_generator()
        self.configure_generator(frequency)
        self.controller.start_generator()
        self.assertEqual(self.last_frame().message_type, MessageType.GEN_START)
        self.assertEqual(self.controller.generator_state, GeneratorState.STOPPED)
        self.controller.process_bytes(encode_frame(
            MessageType.GEN_START_ACK, encode_gen_start_ack()))
        self.assertEqual(self.controller.generator_state, GeneratorState.RUNNING)

    def configure_acquisition_and_arm(self, *, frequency=10.0, count=4, session=42):
        self.start_running_generator(frequency)
        selected = config(count)
        self.controller.configure(selected)
        self.controller.process_bytes(encode_frame(
            MessageType.CONFIG_ACK, encode_config(selected)))
        self.assertEqual(self.controller.start(session), session)
        self.assertEqual(self.controller.state, AcquisitionState.ARMED)
        return selected

    def trigger(self, session=42):
        self.controller.process_bytes(encode_frame(
            MessageType.ACQ_STARTED,
            encode_acquisition_started(AcquisitionStarted(session))))

    def test_firmware_without_generator_capability_rejects_methods_without_writing(self):
        self.controller.open("COM9")
        self.controller.process_bytes(encode_frame(
            MessageType.HELLO_ACK,
            encode_hello_ack((1, 1, 0), REQUIRED_FIRMWARE_CAPABILITIES)))
        writes_before = len(self.serial.writes)
        self.assertFalse(self.controller.generator_available)
        self.assertEqual(self.controller.generator_state, GeneratorState.UNKNOWN)
        with self.assertRaisesRegex(AcquisitionError, "ne prend pas en charge"):
            self.controller.configure_generator(ContinuousSquareConfig(10))
        self.assertEqual(len(self.serial.writes), writes_before)

    def test_generator_config_ack_is_source_of_applied_frequency(self):
        configured = []
        self.controller.generator_configured.connect(configured.append)
        self.handshake_generator()
        requested, applied_timer = self.configure_generator(123.0, applied_ticks=1000)
        self.assertNotEqual(requested.timer.half_period_ticks,
                            applied_timer.half_period_ticks)
        self.assertEqual(self.controller.generator_plan.timer, applied_timer)
        self.assertAlmostEqual(self.controller.generator_plan.applied_frequency_hz, 125.0)
        self.assertEqual(configured, [self.controller.generator_plan])

    def test_start_keepalive_stop_and_ack_transitions(self):
        states = []
        self.controller.generator_state_changed.connect(states.append)
        self.handshake_generator()
        self.configure_generator()
        self.controller.start_generator()
        self.assertFalse(self.controller.generator_keepalive.isActive())
        self.controller.process_bytes(encode_frame(
            MessageType.GEN_START_ACK, encode_gen_start_ack()))
        self.assertTrue(self.controller.generator_keepalive.isActive())
        self.assertEqual(self.controller.generator_keepalive.interval(), 25)
        self.controller._send_generator_keepalive()
        self.assertEqual(self.last_frame().message_type, MessageType.GEN_KEEPALIVE)
        self.assertTrue(self.controller.stop_generator())
        self.assertEqual(self.controller.generator_state, GeneratorState.RUNNING)
        self.controller.process_bytes(encode_frame(
            MessageType.GEN_STOP_ACK, encode_gen_stop_ack()))
        self.assertEqual(self.controller.generator_state, GeneratorState.STOPPED)
        self.assertFalse(self.controller.generator_keepalive.isActive())
        self.assertIn(GeneratorState.RUNNING, states)
        self.assertEqual(states[-1], GeneratorState.STOPPED)

    def test_status_after_reconnect_restores_stopped_or_running_and_keepalive(self):
        self.handshake_generator(GeneratorState.STOPPED)
        self.assertFalse(self.controller.generator_keepalive.isActive())
        self.controller.close()
        self.assertEqual(self.controller.generator_state, GeneratorState.UNKNOWN)

        self.controller.open("COM9")
        self.controller.process_bytes(encode_frame(
            MessageType.HELLO_ACK,
            encode_hello_ack((1, 2, 0),
                             REQUIRED_FIRMWARE_CAPABILITIES | CAPABILITY_CONTINUOUS_SQUARE)))
        self.assertEqual(self.last_frame().message_type, MessageType.GEN_STATUS)
        self.controller.process_bytes(encode_frame(
            MessageType.GEN_STATUS_ACK,
            encode_gen_status_ack(GeneratorState.RUNNING)))
        self.assertEqual(self.controller.generator_state, GeneratorState.RUNNING)
        self.assertTrue(self.controller.generator_keepalive.isActive())

    def test_generator_command_timeout_is_non_destructive_and_unknown_when_needed(self):
        errors = []
        self.controller.error_occurred.connect(errors.append)
        self.controller.open("COM9")
        self.controller.process_bytes(encode_frame(
            MessageType.HELLO_ACK,
            encode_hello_ack((1, 2, 0),
                             REQUIRED_FIRMWARE_CAPABILITIES | CAPABILITY_CONTINUOUS_SQUARE)))
        self.controller._generator_command_timed_out()
        self.assertEqual(self.controller.state, AcquisitionState.READY)
        self.assertEqual(self.controller.generator_state, GeneratorState.UNKNOWN)
        self.assertTrue(self.serial.isOpen())
        self.assertIn("GEN_STATUS_ACK", errors[0])

    def test_start_with_running_generator_arms_until_acq_started(self):
        armed = []
        triggered = []
        self.controller.acquisition_armed.connect(armed.append)
        self.controller.acquisition_triggered.connect(triggered.append)
        self.configure_acquisition_and_arm()
        self.assertEqual(armed, [42])
        self.assertEqual(triggered, [])
        self.assertTrue(self.controller.armed_timeout.isActive())
        self.trigger()
        self.assertEqual(self.controller.state, AcquisitionState.ACQUIRING)
        self.assertEqual(triggered, [AcquisitionStarted(42)])
        self.assertFalse(self.controller.armed_timeout.isActive())

    def test_acq_started_wrong_session_and_duplicate_are_rejected(self):
        self.configure_acquisition_and_arm()
        self.trigger(99)
        self.assertEqual(self.controller.state, AcquisitionState.ERROR)

        self.tearDown()
        self.setUp()
        self.configure_acquisition_and_arm()
        self.trigger()
        self.trigger()
        self.assertEqual(self.controller.state, AcquisitionState.ERROR)

    def test_low_frequency_armed_timeout_sends_acquisition_stop_only(self):
        errors = []
        self.controller.error_occurred.connect(errors.append)
        self.configure_acquisition_and_arm(frequency=0.1)
        self.assertEqual(self.controller.armed_timeout.interval(), 11_000)
        writes_before = len(self.serial.writes)
        self.controller._armed_timed_out()
        self.assertEqual(self.controller.state, AcquisitionState.STOPPING)
        self.assertEqual(len(self.serial.writes), writes_before + 1)
        self.assertEqual(self.last_frame().message_type, MessageType.STOP)
        self.assertEqual(self.controller.generator_state, GeneratorState.RUNNING)
        self.controller.process_bytes(encode_frame(
            MessageType.END, struct.pack("<II", 42, 0)))
        self.assertEqual(self.controller.state, AcquisitionState.CONFIGURED)
        self.assertIn("front montant", errors[0])

    def test_stop_acquisition_while_armed_keeps_generator_running(self):
        results = []
        self.controller.acquisition_finished.connect(results.append)
        self.configure_acquisition_and_arm()
        self.assertTrue(self.controller.stop())
        self.assertEqual(self.controller.state, AcquisitionState.STOPPING)
        self.assertEqual(self.last_frame().message_type, MessageType.STOP)
        self.controller.process_bytes(encode_frame(
            MessageType.END, struct.pack("<II", 42, 0)))
        self.assertEqual(self.controller.state, AcquisitionState.CONFIGURED)
        self.assertEqual(self.controller.generator_state, GeneratorState.RUNNING)
        self.assertEqual(results[0].samples, ())
        self.assertFalse(results[0].complete)
        self.assertTrue(self.controller.generator_keepalive.isActive())

    def test_gbf_data_keeps_adc_e_alignment_and_end_keeps_generator_running(self):
        results = []
        self.controller.acquisition_finished.connect(results.append)
        self.configure_acquisition_and_arm(count=4)
        self.trigger()
        batch = GbfDataBatch(42, 0, 0, (100, 200, 300, 400),
                             (True, True, False, False))
        self.controller.process_bytes(encode_frame(
            MessageType.DATA_GBF, encode_gbf_data(batch)))
        self.controller.process_bytes(encode_frame(
            MessageType.END, struct.pack("<II", 42, 4)))
        result = results[0]
        self.assertEqual(result.samples, batch.values)
        self.assertEqual(result.generated_high, batch.generated_high)
        self.assertEqual(result.times_s, (0.0, 0.001, 0.002, 0.003))
        self.assertEqual(result.generated_voltages_v, (5.0, 5.0, 0.0, 0.0))
        self.assertEqual(self.controller.generator_state, GeneratorState.RUNNING)
        self.assertTrue(self.controller.generator_keepalive.isActive())

    def test_gbf_data_invalid_sequence_or_index_preserves_partial(self):
        for sequence, first_index in ((2, 2), (1, 3)):
            with self.subTest(sequence=sequence, first_index=first_index):
                self.tearDown()
                self.setUp()
                self.configure_acquisition_and_arm(count=4)
                self.trigger()
                first = GbfDataBatch(42, 0, 0, (10, 20), (True, False))
                self.controller.process_bytes(encode_frame(
                    MessageType.DATA_GBF, encode_gbf_data(first)))
                invalid = GbfDataBatch(42, sequence, first_index, (30, 40), (False, False))
                self.controller.process_bytes(encode_frame(
                    MessageType.DATA_GBF, encode_gbf_data(invalid)))
                self.assertEqual(self.controller.state, AcquisitionState.ERROR)
                self.assertEqual(self.controller.partial_result().samples, (10, 20))
                self.assertEqual(self.controller.partial_result().generated_high, (True, False))

    def test_generator_stop_during_acquisition_keeps_accepting_gbf_data(self):
        self.configure_acquisition_and_arm(count=2)
        self.trigger()
        self.assertTrue(self.controller.stop_generator())
        self.controller.process_bytes(encode_frame(
            MessageType.GEN_STOP_ACK, encode_gen_stop_ack()))
        self.assertEqual(self.controller.generator_state, GeneratorState.STOPPED)
        self.assertEqual(self.controller.state, AcquisitionState.ACQUIRING)
        batch = GbfDataBatch(42, 0, 0, (100, 200), (True, False))
        self.controller.process_bytes(encode_frame(
            MessageType.DATA_GBF, encode_gbf_data(batch)))
        self.controller.process_bytes(encode_frame(
            MessageType.END, struct.pack("<II", 42, 2)))
        self.assertEqual(self.controller.samples, [100, 200])
        self.assertEqual(self.controller.generated_high, [True, False])
        self.assertEqual(self.controller.generator_state, GeneratorState.STOPPED)

    def test_historical_session_rejects_gbf_data_and_historical_path_stays_unchanged(self):
        self.controller.open("COM9")
        self.controller.process_bytes(encode_frame(
            MessageType.HELLO_ACK,
            encode_hello_ack((1, 1, 0), REQUIRED_FIRMWARE_CAPABILITIES)))
        selected = config(count=2)
        self.controller.configure(selected)
        self.controller.process_bytes(encode_frame(
            MessageType.CONFIG_ACK, encode_config(selected)))
        self.controller.start(42)
        self.assertEqual(self.controller.state, AcquisitionState.ACQUIRING)
        batch = GbfDataBatch(42, 0, 0, (100, 200), (True, False))
        self.controller.process_bytes(encode_frame(
            MessageType.DATA_GBF, encode_gbf_data(batch)))
        self.assertEqual(self.controller.state, AcquisitionState.ERROR)

    def test_trigger_cancelled_is_specific_non_destructive_error(self):
        errors = []
        self.controller.error_occurred.connect(errors.append)
        self.configure_acquisition_and_arm()
        self.assertTrue(self.controller.stop_generator())
        self.controller.process_bytes(encode_frame(
            MessageType.GEN_STOP_ACK, encode_gen_stop_ack())
            + encode_frame(MessageType.ERROR,
                           struct.pack("<H", ERR_TRIGGER_CANCELLED) + b"trigger cancelled"))
        self.assertEqual(self.controller.state, AcquisitionState.CONFIGURED)
        self.assertEqual(self.controller.generator_state, GeneratorState.STOPPED)
        self.assertTrue(self.serial.isOpen())
        self.assertIn("annulé", errors[0])

    def test_resource_error_preserves_gbf_partial_and_stops_all_timers(self):
        self.configure_acquisition_and_arm(count=4)
        self.trigger()
        batch = GbfDataBatch(42, 0, 0, (10, 20), (True, False))
        self.controller.process_bytes(encode_frame(
            MessageType.DATA_GBF, encode_gbf_data(batch)))
        self.serial.errorOccurred.emit(QSerialPort.SerialPortError.ResourceError)
        self.assertEqual(self.controller.state, AcquisitionState.ERROR)
        self.assertEqual(self.controller.generator_state, GeneratorState.UNKNOWN)
        self.assertEqual(self.controller.partial_result().samples, (10, 20))
        self.assertEqual(self.controller.partial_result().generated_high, (True, False))
        for timer in (self.controller.handshake_timeout, self.controller.hello_timer,
                      self.controller.generator_command_timeout,
                      self.controller.generator_keepalive, self.controller.armed_timeout):
            self.assertFalse(timer.isActive())

    def test_close_stops_timers_and_exposes_safe_shutdown_state(self):
        self.start_running_generator()
        self.assertFalse(self.controller.generator_ready_for_flash)
        self.assertFalse(self.controller.request_generator_shutdown())
        self.controller.process_bytes(encode_frame(
            MessageType.GEN_STOP_ACK, encode_gen_stop_ack()))
        self.assertTrue(self.controller.generator_ready_for_flash)
        self.controller.start_generator()
        self.controller.process_bytes(encode_frame(
            MessageType.GEN_START_ACK, encode_gen_start_ack()))
        self.assertFalse(self.controller.request_generator_shutdown())
        self.assertTrue(self.controller.generator_command_timeout.isActive())
        self.assertTrue(self.controller.generator_keepalive.isActive())
        self.controller.close()
        self.assertEqual(self.controller.generator_state, GeneratorState.UNKNOWN)
        for timer in (self.controller.handshake_timeout, self.controller.hello_timer,
                      self.controller.generator_command_timeout,
                      self.controller.generator_keepalive, self.controller.armed_timeout):
            self.assertFalse(timer.isActive())


if __name__ == "__main__":
    unittest.main()
