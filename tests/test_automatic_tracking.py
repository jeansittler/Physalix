"""Suivi automatique : logique conservatrice et intégration au pointage existant."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from physalix.ui.automatic_tracking import AutomaticTracker
from physalix.ui.video_tab import VideoTab


def scene(x, y, texture, width=96, height=72):
    image = np.full((height, width), 24, dtype=np.uint8)
    h, w = texture.shape
    image[y:y + h, x:x + w] = texture
    return image


def save_gray(array, path):
    height, width = array.shape
    image = QImage(array.data, width, height, array.strides[0],
                   QImage.Format.Format_Grayscale8).copy()
    if not image.save(str(path), "PNG"):
        raise OSError(path)


class AutomaticTrackerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        rng = np.random.default_rng(1234)
        cls.texture = rng.integers(20, 240, (18, 22), dtype=np.uint8)

    def test_fixed_reference_follows_translation_and_rejects_loss(self):
        tracker = AutomaticTracker(scene(20, 24, self.texture), QRectF(20, 24, 22, 18))
        match = tracker.locate(scene(27, 29, self.texture))
        self.assertIsNotNone(match)
        self.assertEqual(match.point, QPointF(38, 38))
        self.assertEqual(tracker.rectangle.size(), QRectF(0, 0, 22, 18).size())
        self.assertIsNone(tracker.locate(np.full((72, 96), 24, dtype=np.uint8)))

    def make_tab(self, frames):
        temporary = TemporaryDirectory()
        paths = []
        for index, frame in enumerate(frames):
            path = Path(temporary.name) / f"{index}.png"
            save_gray(frame, path)
            paths.append(str(path))
        tab = VideoTab()
        tab.cache = SimpleNamespace(times=[index * .04 for index in range(len(paths))],
                                    path=lambda index: paths[index])
        tab.tracking.calibrate(QPointF(0, 0), QPointF(10, 0), 1, "m")
        tab.tracking.set_origin(QPointF(0, 0))
        tab.slider.setRange(0, len(paths) - 1)
        tab._show_frame(0)
        return temporary, tab

    def test_first_point_progression_and_normal_end_use_existing_session(self):
        frames = [scene(20 + 3 * i, 24 + 2 * i, self.texture) for i in range(3)]
        temporary, tab = self.make_tab(frames)
        try:
            tab.set_mode("auto_select")
            tab.automatic_rectangle_selected(QRectF(20, 24, 22, 18))
            self.assertEqual(tab.mode, "auto_ready")
            tab.start_automatic()
            tab.automatic_timer.stop()
            self.assertEqual(tab.tracking.points[0][0], QPointF(31, 33))
            tab._automatic_tick()
            tab.automatic_timer.stop()
            self.assertEqual(tab.index, 1)
            self.assertEqual(len(tab.tracking.points), 2)
            tab._automatic_tick()
            self.assertIsNone(tab.mode)
            self.assertEqual(len(tab.tracking.points), 3)
            self.assertEqual(tab.hint.text(), "Pointage automatique terminé.")
            self.assertEqual(tab.model.rows[2][2], "0.08")
        finally:
            tab.close()
            temporary.cleanup()

    def test_loss_adds_no_doubtful_point_then_click_allows_resume(self):
        frames = [scene(20, 24, self.texture), np.full((72, 96), 24, dtype=np.uint8)]
        temporary, tab = self.make_tab(frames)
        try:
            tab.set_mode("auto_select")
            tab.automatic_rectangle_selected(QRectF(20, 24, 22, 18))
            tab.start_automatic()
            tab.automatic_timer.stop()
            tab._automatic_tick()
            self.assertEqual(tab.mode, "auto_recover")
            self.assertEqual(set(tab.tracking.points), {0})
            self.assertEqual(tab.index, 1)
            tab.image_clicked(QPointF(50, 40))
            self.assertEqual(tab.mode, "auto_paused")
            self.assertEqual(tab.tracking.points[1][0], QPointF(50, 40))
            tab.start_automatic()
            self.assertIsNone(tab.mode)
            self.assertEqual(tab.hint.text(), "Pointage automatique terminé.")
        finally:
            tab.close()
            temporary.cleanup()

    def test_voluntary_stop_keeps_points_and_resume_skips_current_frame(self):
        frames = [scene(20 + 2 * i, 24, self.texture) for i in range(3)]
        temporary, tab = self.make_tab(frames)
        try:
            tab.set_mode("auto_select")
            tab.automatic_rectangle_selected(QRectF(20, 24, 22, 18))
            tab.start_automatic()
            tab.automatic_timer.stop()
            tab._automatic_tick()
            tab.automatic_timer.stop()
            tab.stop_automatic()
            self.assertEqual(tab.mode, "auto_paused")
            self.assertEqual(set(tab.tracking.points), {0, 1})
            tab.undo_point()
            self.assertEqual(tab.mode, "auto_paused")
            self.assertEqual(tab.index, 0)
            self.assertEqual(set(tab.tracking.points), {0})
            tab.start_automatic()
            tab.automatic_timer.stop()
            tab._automatic_tick()
            tab.automatic_timer.stop()
            self.assertEqual(set(tab.tracking.points), {0, 1})
            tab._automatic_tick()
            self.assertEqual(set(tab.tracking.points), {0, 1, 2})
        finally:
            tab.close()
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
