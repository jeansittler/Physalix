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
    DataBatch,
    DigitalStepConfig,
    FrameParser,
    MAGIC,
    MAX_PARSER_BUFFER,
    MAX_PAYLOAD_SIZE,
    MessageType,
    PROTOCOL_VERSION,
    SERIAL_RESOURCE_DISCONNECTED_MESSAGE,
    decode_config,
    encode_config,
    encode_data,
    encode_frame,
    encode_hello_ack,
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


if __name__ == "__main__":
    unittest.main()
