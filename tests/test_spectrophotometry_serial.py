"""Tests ciblés du contrôleur série du spectrophotomètre."""

import os
import math
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtSerialPort import QSerialPort
from PySide6.QtWidgets import QApplication

from physalix.acquisition import FrameParser
from physalix.spectrophotometry_protocol import (
    AS7341Gain,
    SpectroConfig,
    SpectroData,
    SpectroErrorPayload,
    SpectroFirmwareInfo,
    SpectroIllumination,
    SpectroMeasureRequest,
    SpectroMessageType,
    SpectroSensorType,
    SpectroStopRequest,
    encode_config_ack,
    encode_data,
    encode_error,
    encode_hello_ack,
    encode_measure,
    encode_spectro_frame,
    encode_stop_ack,
)
from physalix.spectrophotometry_serial import (
    SPECTRO_REQUIRED_CAPABILITIES,
    SPECTRO_RESOURCE_DISCONNECTED_MESSAGE,
    SpectroControllerState,
    SpectrophotometrySerialController,
    SpectroStateError,
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
        self.data_bits = None
        self.parity = None
        self.stop_bits = None
        self.flow_control = None

    def setPortName(self, name):
        self.port_name = name

    def setBaudRate(self, rate):
        self.baud_rate = rate

    def setDataBits(self, value):
        self.data_bits = value

    def setParity(self, value):
        self.parity = value

    def setStopBits(self, value):
        self.stop_bits = value

    def setFlowControl(self, value):
        self.flow_control = value

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


def selected_config(config_id=7):
    return SpectroConfig(config_id, 100, 999, AS7341Gain.GAIN_8X, 255)


def firmware_info(*, version=(1, 0, 0), capabilities=SPECTRO_REQUIRED_CAPABILITIES):
    return SpectroFirmwareInfo(version, SpectroSensorType.AS7341, capabilities)


def measurement(request_id, config_id=7, illumination=SpectroIllumination.LED_ON):
    return SpectroData(
        request_id,
        config_id,
        illumination,
        (3175, 26177, 9618, 19108, 21899, 18696, 13496, 5221),
        65535,
        2429,
        0x0100,
        123456,
    )


class SpectrophotometrySerialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.serial = FakeSerial()
        self.controller = SpectrophotometrySerialController(
            serial_port=self.serial,
            handshake_timeout_ms=100,
            hello_interval_ms=20,
            config_timeout_ms=100,
            stop_timeout_ms=100,
            measurement_margin_ms=500,
            minimum_measurement_timeout_ms=100,
        )

    def tearDown(self):
        self.controller.close()

    def last_frame(self):
        frames = FrameParser().feed(self.serial.writes[-1])
        self.assertEqual(len(frames), 1)
        return frames[0]

    def feed_frame(self, message_type, payload=b""):
        self.controller.process_bytes(encode_spectro_frame(message_type, payload))

    def handshake(self, info=None):
        received = []
        self.controller.ready.connect(received.append)
        self.assertTrue(self.controller.open("COM4"))
        self.feed_frame(
            SpectroMessageType.SPECTRO_HELLO_ACK,
            encode_hello_ack(info or firmware_info()),
        )
        self.assertEqual(self.controller.state, SpectroControllerState.READY)
        return received

    def configure(self, config=None, applied=None):
        requested = config or selected_config()
        self.controller.configure(requested)
        self.feed_frame(
            SpectroMessageType.SPECTRO_CONFIG_ACK,
            encode_config_ack(applied or requested),
        )
        self.assertEqual(self.controller.state, SpectroControllerState.CONFIGURED)
        return requested

    def connect_and_configure(self):
        self.handshake()
        return self.configure()

    def test_open_uses_115200_8n1_and_repeats_hello_for_nano_reset(self):
        self.assertTrue(self.controller.open("COM4"))
        self.assertEqual(self.serial.port_name, "COM4")
        self.assertEqual(self.serial.baud_rate, 115200)
        self.assertEqual(self.serial.data_bits, QSerialPort.DataBits.Data8)
        self.assertEqual(self.serial.parity, QSerialPort.Parity.NoParity)
        self.assertEqual(self.serial.stop_bits, QSerialPort.StopBits.OneStop)
        self.assertEqual(self.serial.flow_control, QSerialPort.FlowControl.NoFlowControl)
        self.assertEqual(self.last_frame().message_type, SpectroMessageType.SPECTRO_HELLO)
        self.controller._send_hello()
        self.assertEqual(len(self.serial.writes), 2)
        self.assertTrue(self.controller.hello_timer.isActive())
        self.assertTrue(self.controller.handshake_timeout.isActive())

    def test_open_failure_does_not_try_another_port(self):
        errors = []
        self.serial.open_result = False
        self.controller.error_occurred.connect(errors.append)
        self.assertFalse(self.controller.open("COM9"))
        self.assertEqual(self.serial.port_name, "COM9")
        self.assertEqual(self.controller.state, SpectroControllerState.ERROR)
        self.assertEqual(self.serial.writes, [])
        self.assertIn("Impossible d'ouvrir COM9", errors[0])

    def test_valid_handshake_checks_identity_version_and_capabilities(self):
        received = self.handshake(firmware_info(version=(1, 2, 3)))
        self.assertEqual(received, [firmware_info(version=(1, 2, 3))])
        self.assertFalse(self.controller.hello_timer.isActive())
        self.assertFalse(self.controller.handshake_timeout.isActive())

    def test_wrong_signature_sensor_old_version_and_capabilities_fail(self):
        invalid_payloads = (
            b"BAD!" + encode_hello_ack(firmware_info())[4:],
            bytes.fromhex("535043540100000200000000"),
            encode_hello_ack(firmware_info(version=(0, 9, 9))),
            encode_hello_ack(firmware_info(capabilities=0x01)),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.tearDown()
                self.setUp()
                self.controller.open("COM4")
                self.feed_frame(SpectroMessageType.SPECTRO_HELLO_ACK, payload)
                self.assertEqual(self.controller.state, SpectroControllerState.ERROR)
                self.assertFalse(self.serial.isOpen())

    def test_handshake_timeout_closes_connection_and_can_reconnect(self):
        errors = []
        self.controller.error_occurred.connect(errors.append)
        self.controller.open("COM4")
        self.controller._handshake_timed_out()
        self.assertEqual(self.controller.state, SpectroControllerState.ERROR)
        self.assertFalse(self.serial.isOpen())
        self.assertIn("handshake", errors[0])
        self.assertTrue(self.controller.open("COM4"))
        self.assertEqual(self.controller.state, SpectroControllerState.WAITING_HANDSHAKE)

    def test_config_and_ack_keep_applied_values(self):
        accepted = []
        self.handshake()
        self.controller.configuration_accepted.connect(accepted.append)
        requested = selected_config()
        applied = SpectroConfig(7, 100, 999, AS7341Gain.GAIN_4X, 240)
        self.controller.configure(requested)
        frame = self.last_frame()
        self.assertEqual(frame.message_type, SpectroMessageType.SPECTRO_CONFIG)
        self.assertEqual(self.controller.state, SpectroControllerState.CONFIGURING)
        self.feed_frame(
            SpectroMessageType.SPECTRO_CONFIG_ACK,
            encode_config_ack(applied),
        )
        self.assertEqual(self.controller.config, applied)
        self.assertEqual(accepted, [applied])

    def test_config_id_is_not_reused_within_connection(self):
        self.handshake()
        self.configure()
        with self.assertRaisesRegex(SpectroStateError, "réutilisé"):
            self.controller.configure(selected_config())

    def test_config_timeout_returns_to_ready(self):
        errors = []
        self.handshake()
        self.controller.error_occurred.connect(errors.append)
        self.controller.configure(selected_config())
        self.controller._command_timed_out()
        self.assertEqual(self.controller.state, SpectroControllerState.READY)
        self.assertIsNone(self.controller.config)
        self.assertIn("CONFIG_ACK", errors[0])

    def test_dark_and_lit_measurements_expose_all_channels(self):
        results = []
        self.connect_and_configure()
        self.controller.measurement_received.connect(results.append)
        for illumination in (SpectroIllumination.LED_OFF, SpectroIllumination.LED_ON):
            request_id = self.controller.measure(illumination)
            frame = self.last_frame()
            self.assertEqual(frame.message_type, SpectroMessageType.SPECTRO_MEASURE)
            self.assertEqual(
                frame.payload,
                encode_measure(SpectroMeasureRequest(request_id, 7, illumination)),
            )
            result = measurement(request_id, illumination=illumination)
            self.feed_frame(SpectroMessageType.SPECTRO_DATA, encode_data(result))
            self.assertEqual(self.controller.last_measurement, result)
        self.assertEqual([item.illumination for item in results], [
            SpectroIllumination.LED_OFF,
            SpectroIllumination.LED_ON,
        ])
        self.assertEqual(results[-1].bands[4], 21899)
        self.assertEqual(results[-1].clear, 65535)
        self.assertEqual(results[-1].nir, 2429)
        self.assertEqual(results[-1].saturation_flags, 0x0100)

    def test_measurement_timeout_scales_with_two_integration_groups(self):
        self.handshake()
        selected = SpectroConfig(9, 255, 65534, AS7341Gain.GAIN_1X, 0)
        self.configure(selected)
        expected_integration_ms = math.ceil(256 * 65535 * 2 * 2.78 / 1000)
        self.assertEqual(
            self.controller.measurement_timeout_ms(),
            expected_integration_ms + 500,
        )

    def test_fragmented_and_concatenated_frames(self):
        self.controller.open("COM4")
        hello = encode_spectro_frame(
            SpectroMessageType.SPECTRO_HELLO_ACK,
            encode_hello_ack(firmware_info()),
        )
        self.controller.process_bytes(hello[:4])
        self.assertEqual(self.controller.state, SpectroControllerState.WAITING_HANDSHAKE)
        self.controller.process_bytes(hello[4:])
        self.controller.configure(selected_config())
        config_ack = encode_spectro_frame(
            SpectroMessageType.SPECTRO_CONFIG_ACK,
            encode_config_ack(selected_config()),
        )
        late_hello = encode_spectro_frame(
            SpectroMessageType.SPECTRO_HELLO_ACK,
            encode_hello_ack(firmware_info()),
        )
        self.controller.process_bytes(late_hello + config_ack)
        self.assertEqual(self.controller.state, SpectroControllerState.CONFIGURED)

    def test_invalid_crc_is_discarded_then_valid_frame_is_processed(self):
        self.controller.open("COM4")
        corrupt = bytearray(encode_spectro_frame(
            SpectroMessageType.SPECTRO_HELLO_ACK,
            encode_hello_ack(firmware_info()),
        ))
        corrupt[-1] ^= 0xFF
        self.controller.process_bytes(bytes(corrupt))
        self.assertEqual(self.controller.state, SpectroControllerState.WAITING_HANDSHAKE)
        self.feed_frame(
            SpectroMessageType.SPECTRO_HELLO_ACK,
            encode_hello_ack(firmware_info()),
        )
        self.assertEqual(self.controller.state, SpectroControllerState.READY)

    def test_obsolete_data_ids_are_ignored_without_completing_measurement(self):
        ignored = []
        self.connect_and_configure()
        self.controller.response_ignored.connect(ignored.append)
        request_id = self.controller.measure_lit()
        self.feed_frame(
            SpectroMessageType.SPECTRO_DATA,
            encode_data(measurement(request_id + 1)),
        )
        self.feed_frame(
            SpectroMessageType.SPECTRO_DATA,
            encode_data(measurement(request_id, config_id=99)),
        )
        self.assertEqual(self.controller.state, SpectroControllerState.MEASURING)
        self.assertEqual(len(ignored), 2)
        self.feed_frame(
            SpectroMessageType.SPECTRO_DATA,
            encode_data(measurement(request_id)),
        )
        self.assertEqual(self.controller.state, SpectroControllerState.CONFIGURED)

    def test_timeout_requests_stop_and_late_data_cannot_match_next_measurement(self):
        ignored = []
        self.connect_and_configure()
        self.controller.response_ignored.connect(ignored.append)
        old_request = self.controller.measure_lit()
        self.controller._command_timed_out()
        self.assertEqual(self.controller.state, SpectroControllerState.STOPPING)
        self.assertEqual(self.last_frame().message_type, SpectroMessageType.SPECTRO_STOP)
        self.feed_frame(
            SpectroMessageType.SPECTRO_DATA,
            encode_data(measurement(old_request)),
        )
        self.feed_frame(
            SpectroMessageType.SPECTRO_STOP_ACK,
            encode_stop_ack(SpectroStopRequest(old_request)),
        )
        new_request = self.controller.measure_lit()
        self.assertNotEqual(new_request, old_request)
        self.feed_frame(
            SpectroMessageType.SPECTRO_DATA,
            encode_data(measurement(old_request)),
        )
        self.assertEqual(self.controller.state, SpectroControllerState.MEASURING)
        self.assertGreaterEqual(len(ignored), 2)

    def test_correlated_firmware_error_is_recoverable_and_stale_error_is_ignored(self):
        failures = []
        firmware_errors = []
        ignored = []
        self.connect_and_configure()
        self.controller.measurement_failed.connect(lambda request, text: failures.append(
            (request, text)
        ))
        self.controller.firmware_error.connect(firmware_errors.append)
        self.controller.response_ignored.connect(ignored.append)
        request_id = self.controller.measure_dark()
        self.feed_frame(
            SpectroMessageType.SPECTRO_ERROR,
            encode_error(SpectroErrorPayload(request_id + 1, 11)),
        )
        self.assertEqual(self.controller.state, SpectroControllerState.MEASURING)
        self.feed_frame(
            SpectroMessageType.SPECTRO_ERROR,
            encode_error(SpectroErrorPayload(request_id, 11)),
        )
        self.assertEqual(self.controller.state, SpectroControllerState.CONFIGURED)
        self.assertEqual(firmware_errors, [SpectroErrorPayload(request_id, 11)])
        self.assertEqual(failures[0][0], request_id)
        self.assertIn("I²C", failures[0][1])
        self.assertEqual(len(ignored), 1)

    def test_resource_disconnect_during_measurement_cleans_everything(self):
        failures = []
        errors = []
        self.connect_and_configure()
        self.controller.measurement_failed.connect(lambda request, text: failures.append(
            (request, text)
        ))
        self.controller.error_occurred.connect(errors.append)
        request_id = self.controller.measure_lit()
        self.serial.errorOccurred.emit(QSerialPort.SerialPortError.ResourceError)
        self.assertEqual(self.controller.state, SpectroControllerState.ERROR)
        self.assertFalse(self.serial.isOpen())
        self.assertFalse(self.controller.command_timeout.isActive())
        self.assertEqual(failures, [(request_id, SPECTRO_RESOURCE_DISCONNECTED_MESSAGE)])
        self.assertEqual(errors, [SPECTRO_RESOURCE_DISCONNECTED_MESSAGE])

    def test_stop_ack_and_duplicate_stop(self):
        stopped = []
        self.connect_and_configure()
        self.controller.stopped.connect(stopped.append)
        request_id = self.controller.measure_lit()
        self.assertTrue(self.controller.stop())
        self.assertFalse(self.controller.stop())
        frame = self.last_frame()
        self.assertEqual(frame.message_type, SpectroMessageType.SPECTRO_STOP)
        self.feed_frame(
            SpectroMessageType.SPECTRO_STOP_ACK,
            encode_stop_ack(SpectroStopRequest(request_id)),
        )
        self.assertEqual(self.controller.state, SpectroControllerState.CONFIGURED)
        self.assertEqual(stopped, [request_id])

    def test_stop_timeout_is_fatal_because_device_state_is_unknown(self):
        self.connect_and_configure()
        self.controller.measure_lit()
        self.controller.stop()
        self.controller._command_timed_out()
        self.assertEqual(self.controller.state, SpectroControllerState.ERROR)
        self.assertFalse(self.serial.isOpen())

    def test_close_clears_timers_parser_requests_and_state(self):
        self.connect_and_configure()
        self.controller.measure_lit()
        self.controller.parser.feed(b"\xa5")
        self.controller.close()
        self.assertEqual(self.controller.state, SpectroControllerState.DISCONNECTED)
        self.assertFalse(self.serial.isOpen())
        self.assertFalse(self.controller.handshake_timeout.isActive())
        self.assertFalse(self.controller.hello_timer.isActive())
        self.assertFalse(self.controller.command_timeout.isActive())
        self.assertEqual(self.controller.parser.buffered_bytes, 0)
        self.assertIsNone(self.controller.config)
        self.assertIsNone(self.controller.firmware_info)

    def test_invalid_api_state_transitions_do_not_write(self):
        with self.assertRaises(SpectroStateError):
            self.controller.configure(selected_config())
        with self.assertRaises(SpectroStateError):
            self.controller.measure_lit()
        self.assertFalse(self.controller.stop())
        self.assertEqual(self.serial.writes, [])
        self.controller.open("COM4")
        writes = len(self.serial.writes)
        with self.assertRaises(SpectroStateError):
            self.controller.open("COM5")
        self.assertEqual(len(self.serial.writes), writes)


if __name__ == "__main__":
    unittest.main()
