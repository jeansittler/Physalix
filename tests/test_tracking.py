"""Conversion physique, conservation des données et gestes de pointage."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

import test_video
from physalix.ui.data_tab import MeasurementsModel
from physalix.ui.video_canvas import VideoCanvas
from physalix.ui.video_tracking import CalibrationDialog, TrackingSession
from physalix.ui.main_window import MainWindow


class TrackingMathTests(unittest.TestCase):
    def test_conversion_units_recalibration_and_undo(self):
        model = MeasurementsModel()
        session = TrackingSession(model)
        session.calibrate(QPointF(0, 0), QPointF(30, 40), 10, "cm")
        session.set_origin(QPointF(100, 100))
        self.assertEqual(model.names, ["x", "y", "t"])
        self.assertEqual(model.units, ["cm", "cm", "s"])
        session.record(7, QPointF(110, 80), .28)
        session.record(3, QPointF(90, 120), .12)
        self.assertEqual(model.rows[0], ["-2", "-4", "0.12"])
        self.assertEqual(model.rows[1], ["2", "4", "0.28"])
        session.record(3, QPointF(100, 100), .12)
        self.assertEqual(len(session.points), 2)
        self.assertEqual(model.rows[0][:2], ["0", "0"])
        self.assertEqual(session.undo(), 3)
        self.assertEqual(model.rows[0][:2], ["-2", "-4"])
        session.calibrate(QPointF(0, 0), QPointF(30, 40), .1, "m")
        self.assertEqual(model.units, ["m", "m", "s"])
        self.assertEqual(model.rows[0][:2], ["-0.02", "-0.04"])
        session.set_origin(QPointF(90, 120))
        self.assertEqual(model.rows[0][:2], ["0", "0"])
        session.undo()
        self.assertEqual(model.rows[0][2], "0.28")
        self.assertEqual(model.rows[1], ["", "", ""])
        session.undo()
        self.assertEqual(model.rows[0], ["", "", ""])

    def test_preserve_other_columns_and_new_session(self):
        model = MeasurementsModel()
        model.setData(model.index(2, 0), "42")
        first = TrackingSession(model)
        first.set_origin(QPointF(0, 0))
        self.assertEqual(first.columns, (2, 3, 4))
        first.calibrate(QPointF(0, 0), QPointF(10, 0), 1, "mm")
        first.record(0, QPointF(20, 10), 0)
        second = TrackingSession(model)
        second.set_origin(QPointF(0, 0))
        self.assertEqual(second.columns, (5, 6, 7))
        self.assertEqual(model.rows[0][:5], ["42", "", "2", "-1", "0"])
        self.assertEqual(len(model.names), len(set(model.names)))

    def test_reject_degenerate_calibration(self):
        session = TrackingSession(MeasurementsModel())
        for end, length in ((QPointF(0, 0), 1), (QPointF(10, 0), 0), (QPointF(10, 0), float("nan"))):
            with self.assertRaises(ValueError):
                session.calibrate(QPointF(0, 0), end, length, "cm")

    def test_grow_table_and_graph_pairs(self):
        from physalix.ui.graph_tab import paired_values
        model = MeasurementsModel()
        session = TrackingSession(model)
        session.set_origin(QPointF(0, 0))
        session.calibrate(QPointF(0, 0), QPointF(10, 0), 10, "cm")
        for i in range(25):
            session.record(i, QPointF(i, -2 * i), i * .04)
        times, ys, _ = paired_values(model.rows, 2, 1)
        self.assertEqual(len(times), 25)
        self.assertEqual(times[-1], .96)
        self.assertEqual(ys[-1], 48)
        self.assertEqual(model.rows[-1], ["", "", ""])

    def test_four_axis_directions_preserve_pixels_times_and_undo(self):
        model = MeasurementsModel()
        session = TrackingSession(model)
        session.calibrate(QPointF(0, 0), QPointF(10, 0), 1, "m")
        session.set_origin(QPointF(10, 20))
        session.record(0, QPointF(30, 50), .1)
        original = dict(session.points)
        history = list(session.history)
        for x_sign, y_sign in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            session.set_axes(x_sign, y_sign)
            self.assertEqual([float(v) for v in model.rows[0]], [2*x_sign, -3*y_sign, .1])
            self.assertEqual(session.points, original)
            self.assertEqual(session.history, history)
        session.record(0, QPointF(40, 60), .1)
        session.undo()
        self.assertEqual(model.rows[0], ["-2", "3", "0.1"])
        with self.assertRaises(ValueError):
            session.set_axes(0, 1)


class TrackingUiTests(unittest.TestCase):
    setUpClass = classmethod(test_video.VideoTests.setUpClass.__func__)
    setUp = test_video.VideoTests.setUp
    tearDown = test_video.VideoTests.tearDown
    wait_loaded = test_video.VideoTests.wait_loaded

    def test_restart_and_axis_controls(self):
        window = MainWindow()
        try:
            tab = window.video_tab
            self.assertFalse(tab.restart_button.isEnabled())
            self.assertFalse(tab.axes_choice.isEnabled())
            tab.open_video(self.path)
            self.wait_loaded(tab)
            tab.tracking.calibrate(QPointF(0,0), QPointF(10,0), 1, "m")
            tab.tracking.set_origin(QPointF(10,20))
            tab.tracking.record(1, QPointF(30,40), .04)
            points = dict(tab.tracking.points)
            for choice, directions in enumerate(((1,1), (1,-1), (-1,1), (-1,-1))):
                tab.axes_choice.setCurrentIndex(choice)
                tab._controls()
                self.assertEqual((tab.screen.x_direction, tab.screen.y_direction), directions)
                self.assertEqual([float(v) for v in tab.model.rows[0]], [2*directions[0], -2*directions[1], .04])
            tab.seek(2)
            tab.toggle_play()
            self.assertTrue(tab.playing)
            tab.restart_button.click()
            self.assertEqual(tab.index, 0)
            self.assertFalse(tab.playing)
            self.assertFalse(tab.timer.isActive())
            self.assertEqual(tab.slider.value(), 0)
            self.assertEqual(tab.tracking.points, points)
            self.assertEqual(tab.tracking.origin, QPointF(10,20))
            self.assertEqual(tab.axes_choice.currentIndex(), 3)
            tab.set_mode('track')
            tab.toggle_correction()
            tab.select_point(1)
            tab.restart_button.click()
            self.assertIsNone(tab.mode)
            self.assertIsNone(tab.correction_return)
            self.assertEqual(tab.tracking.points, points)
            tab.open_video(self.path)
            self.wait_loaded(tab)
            self.assertEqual(tab.axes_choice.currentIndex(), 0)
            self.assertEqual((tab.screen.x_direction, tab.screen.y_direction), (1,1))
        finally:
            window._discard_on_close = True
            window.close()

    def test_mapping_resize_and_letterbox(self):
        canvas = VideoCanvas()
        pixmap = QPixmap(640, 480)
        pixmap.fill(Qt.GlobalColor.white)
        canvas.setPixmap(pixmap)
        for width, height in ((1000, 500), (300, 800)):
            canvas.resize(width, height)
            point = QPointF(123.5, 234.25)
            result = canvas.image_point(canvas.screen_point(point))
            self.assertAlmostEqual(result.x(), point.x())
            self.assertAlmostEqual(result.y(), point.y())
            self.assertIsNone(canvas.image_point(QPointF(0, 0)))

    def test_click_workflow_correction_and_new_video(self):
        window = MainWindow()
        try:
            window.show()
            tab = window.video_tab
            window.tabs.setCurrentWidget(tab)
            tab.open_video(self.path)
            self.wait_loaded(tab)
            self.assertFalse(tab.track_button.isEnabled())

            def click(x, y):
                QTest.mouseClick(tab.screen, Qt.MouseButton.LeftButton,
                                 pos=tab.screen.screen_point(QPointF(x, y)).toPoint())

            def accept_dialog(dialog):
                dialog.length.setValue(10)
                dialog.unit.setCurrentText("cm")
                return QDialog.DialogCode.Accepted

            tab.calibrate_button.click()
            QTest.mouseClick(tab.screen, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
            self.assertIsNone(tab.screen.anchor)
            click(5, 20)
            tab.seek(1)
            self.assertIsNone(tab.screen.anchor)
            self.assertIsNone(tab.mode)
            tab.calibrate_button.click()
            click(5, 20)
            self.assertIsNotNone(tab.screen.anchor)
            with patch.object(CalibrationDialog, "exec", accept_dialog):
                click(55, 20)
            self.assertIsNotNone(tab.tracking.scale)
            tab.origin_button.click()
            click(30, 30)
            self.assertEqual(window.data_tab.model.names, ["x", "y", "t"])
            tab.seek(1)
            tab.track_button.click()
            click(40, 20)
            self.assertEqual(tab.index, 2)
            self.assertEqual(tab.tracking.points[1][1], .04)
            click(45, 15)
            self.assertEqual(tab.index, 3)
            click(50, 10)
            self.assertIsNone(tab.mode)
            self.assertEqual(len(tab.tracking.points), 3)
            tab.seek(1)
            tab.track_button.click()
            click(20, 40)
            self.assertEqual(len(tab.tracking.points), 3)
            self.assertLess(float(tab.model.rows[0][0]), 0)
            self.assertLess(float(tab.model.rows[0][1]), 0)
            tab.undo_button.click()
            self.assertGreater(float(tab.model.rows[0][0]), 0)
            self.assertEqual(tab.index, 1)
            tab.calibrate_button.click()
            click(5, 20)
            with patch.object(CalibrationDialog, "exec", return_value=QDialog.DialogCode.Rejected):
                click(55, 20)
            self.assertEqual(tab.tracking.unit, "cm")
            old_values = [row[:3] for row in tab.model.rows]
            tab.open_video(self.path)
            self.wait_loaded(tab)
            self.assertIsNone(tab.tracking.origin)
            self.assertFalse(tab.track_button.isEnabled())
            self.assertEqual([row[:3] for row in tab.model.rows], old_values)
        finally:
            window._discard_on_close = True
            window.close()

    def test_select_old_point_correct_cancel_and_resume(self):
        window = MainWindow()
        try:
            window.show()
            tab = window.video_tab
            window.tabs.setCurrentWidget(tab)
            tab.open_video(self.path)
            self.wait_loaded(tab)
            tab.tracking.calibrate(QPointF(0, 0), QPointF(10, 0), 10, "cm")
            tab.tracking.set_origin(QPointF(0, 0))
            tab.set_mode("track")
            for point in (QPointF(10, 10), QPointF(30, 20), QPointF(50, 30)):
                tab.image_clicked(point)
            original = dict(tab.tracking.points)
            rows = [row[:] for row in tab.model.rows]
            self.assertEqual(tab.index, 3)
            self.assertEqual(len(tab.screen.points), 3)
            self.assertEqual(tab.screen.point, original[2][0])
            tab.correct_button.click()
            self.assertEqual(tab.mode, "select")
            QTest.mouseClick(tab.screen, Qt.MouseButton.LeftButton,
                             pos=tab.screen.screen_point(original[0][0]).toPoint())
            self.assertEqual(tab.mode, "edit")
            self.assertEqual(tab.index, 0)
            self.assertEqual(tab.tracking.points, original)
            tab.image_clicked(QPointF(15, 12))
            self.assertEqual(tab.index, 0)
            self.assertEqual(tab.mode, "select")
            self.assertEqual(tab.tracking.points[0], (QPointF(15, 12), 0))
            self.assertEqual(tab.tracking.points[1], original[1])
            self.assertEqual(tab.tracking.points[2], original[2])
            self.assertEqual(tab.model.rows[1:], rows[1:])
            self.assertEqual(tab.model.rows[0], ["15", "-12", "0"])
            # La liste permet de choisir sans ambiguïté des marques superposées.
            tab.choose_point(tab.point_choice.findData(1))
            self.assertEqual(tab.index, 1)
            tab.escape_mode()
            self.assertEqual(tab.mode, "select")
            self.assertEqual(tab.tracking.points[1], original[1])
            tab.correct_button.click()
            self.assertEqual(tab.index, 3)
            self.assertEqual(tab.mode, "track")
            tab.undo_button.click()
            self.assertEqual(tab.tracking.points, original)
            self.assertEqual(tab.model.rows, rows)
        finally:
            window._discard_on_close = True
            window.close()

    def test_selection_radius_after_resize_and_overlapping_points(self):
        canvas = VideoCanvas()
        pixmap = QPixmap(640, 480)
        pixmap.fill(Qt.GlobalColor.white)
        canvas.setPixmap(pixmap)
        canvas.points = {0: QPointF(120, 230), 1: QPointF(120, 230)}
        for size in ((1000, 500), (300, 800)):
            canvas.resize(*size)
            position = canvas.screen_point(canvas.points[0])
            self.assertEqual(canvas.point_at(position + QPointF(9, 0)), 0)
            self.assertIsNone(canvas.point_at(position + QPointF(11, 0)))
            self.assertIsNone(canvas.point_at(QPointF(0, 0)))

    def test_calibration_direction_preview_measure_and_meter_default(self):
        window = MainWindow()
        try:
            tab = window.video_tab
            tab.open_video(self.path)
            self.wait_loaded(tab)
            self.assertEqual(tab.tracking.unit, "m")
            dialog = CalibrationDialog(window)
            self.assertEqual(dialog.unit.currentText(), "m")
            dialog.deleteLater()
            def accept(dialog):
                self.assertEqual(dialog.unit.currentText(), "m")
                dialog.length.setValue(1)
                return QDialog.DialogCode.Accepted
            start, raw = QPointF(10, 10), QPointF(40, 30)
            for direction, end in (("horizontal", QPointF(40, 10)),
                                   ("vertical", QPointF(10, 30)),
                                   ("free", raw)):
                tab.set_mode("scale")
                tab.image_clicked(start)
                # Changer d'orientation après le premier clic conserve l'ancrage.
                tab.screen.pointer = raw
                tab.calibration_direction.setCurrentIndex(tab.calibration_direction.findData(direction))
                self.assertEqual(tab.screen.anchor, start)
                self.assertEqual(tab.screen.calibration_point(raw), end)
                with patch.object(CalibrationDialog, "exec", accept):
                    tab.image_clicked(raw)
                self.assertEqual(tab.tracking.ruler, (start, end))
                self.assertAlmostEqual(tab.tracking.scale, 1 / ((end.x() - start.x())**2 + (end.y() - start.y())**2)**.5)
            tab.calibration_direction.setCurrentIndex(0)
            tab.set_mode("scale")
            tab.image_clicked(start)
            with patch.object(CalibrationDialog, "exec") as show:
                tab.image_clicked(QPointF(10, 40))
                show.assert_not_called()
            self.assertEqual(tab.mode, "scale")
            tab.escape_mode()
            self.assertEqual(tab.screen.calibration_point(raw), raw)
            tab.calibration_direction.setCurrentIndex(2)
            tab.open_video(self.path)
            self.wait_loaded(tab)
            self.assertEqual(tab.calibration_direction.currentData(), "horizontal")
            self.assertEqual(tab.screen.calibration_direction, "horizontal")
            self.assertEqual(tab.tracking.unit, "m")
        finally:
            window._discard_on_close = True
            window.close()
