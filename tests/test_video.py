"""Vidéos synthétiques : décodage, temps variables et commandes du lecteur."""

import os
import time
import unittest
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from physalix.video import prepare_video
from physalix.ui.main_window import MainWindow


def make_video(path, codec="ffv1", timestamps=(0, 40, 120, 160)):
    with av.open(str(path), "w") as output:
        stream = output.add_stream(codec, rate=25)
        stream.width, stream.height = 64, 48
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        for i, timestamp in enumerate(timestamps):
            pixels = np.full((48, 64, 3), 30 + i * 50, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = timestamp, Fraction(1, 1000)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)


class VideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "vidéo test.mkv"
        make_video(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_formats_order_and_timestamps(self):
        for extension, codec in (("mkv", "ffv1"), ("avi", "mpeg4"), ("mp4", "mpeg4"), ("mpg", "mpeg2video")):
            with self.subTest(extension=extension):
                path = Path(self.temp.name) / f"sample.{extension}"
                make_video(path, codec)
                cache = prepare_video(path)
                try:
                    self.assertEqual(len(cache.times), 4)
                    values = [QImage(cache.path(i)).pixelColor(0, 0).red() for i in range(4)]
                    self.assertEqual(values, sorted(values))
                    self.assertGreater(values[-1] - values[0], 100)
                    self.assertEqual(cache.times[0], 0)
                    if extension == "mkv":
                        for actual, expected in zip(cache.times, (0, .04, .12, .16)):
                            self.assertAlmostEqual(actual, expected, places=5)
                finally:
                    directory = cache.directory.name
                    cache.close()
                self.assertFalse(Path(directory).exists())

    def test_cancel_invalid_and_cache_limit(self):
        self.assertIsNone(prepare_video(self.path, cancelled=lambda: True))
        with self.assertRaises(ValueError):
            prepare_video(self.path, max_bytes=1)
        invalid = Path(self.temp.name) / "bad.avi"
        invalid.write_text("not a video")
        with self.assertRaises(Exception):
            prepare_video(invalid)

    def wait_loaded(self, tab):
        deadline = time.monotonic() + 10
        while tab.loader is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(tab.loader)

    def test_navigation_playback_and_failed_replacement(self):
        window = MainWindow()
        try:
            window.show()
            window.tabs.setCurrentWidget(window.video_tab)
            tab = window.video_tab
            tab.open_video(self.path)
            self.wait_loaded(tab)
            self.assertIsNotNone(tab.cache, tab.status.text())
            self.assertFalse(tab.previous.isEnabled())
            tab.next.click()
            self.assertEqual(tab.index, 1)
            tab.previous.click()
            self.assertEqual(tab.index, 0)
            tab.slider.setValue(3)
            self.assertEqual(tab.index, 3)
            self.assertFalse(tab.next.isEnabled())
            tab.toggle_play()
            QTest.qWait(300)
            self.assertEqual(tab.index, 3)
            self.assertFalse(tab.playing)
            tab.seek(1)
            image = tab.pixmap.toImage()
            tab.seek(3)
            tab.seek(1)
            self.assertEqual(image, tab.pixmap.toImage())
            old_cache = tab.cache
            tab.open_video(Path(self.temp.name) / "missing.avi")
            self.wait_loaded(tab)
            self.assertIs(tab.cache, old_cache)
            self.assertIn("Impossible", tab.status.text())
            self.assertTrue(tab.next.isEnabled())
        finally:
            window._discard_on_close = True
            window.close()
        self.assertIsNone(tab.cache)

    def test_close_while_loading(self):
        window = MainWindow()
        window.video_tab.open_video(self.path)
        window._discard_on_close = True
        window.close()
        self.app.processEvents()
        self.assertIsNone(window.video_tab.loader)


if __name__ == "__main__":
    unittest.main()
