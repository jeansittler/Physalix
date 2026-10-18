"""Intégration UI, transfert et projet de l'Analyse d'images."""

import gc
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QLocale, QPoint, QPointF, Qt, qInstallMessageHandler
from PySide6.QtGui import QColor, QContextMenuEvent, QImage, QValidator, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QPushButton

from physalix.project import IMAGE_ANALYSIS_ENTRY, read_project, write_project
from physalix.image_analysis import fraction_value, measurement_result
from physalix.ui.graph_series import PopupComboBox
from physalix.ui.main_window import MainWindow
from physalix.ui.project_state import restore, snapshot
from physalix.ui.theme import LIGHT, SERIES_COLORS


class ImageAnalysisUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.windows = [self.window]
        self.tab = self.window.image_analysis_tab
        image = QImage(80, 40, QImage.Format.Format_RGB32)
        for y in range(image.height()):
            for x in range(image.width()):
                image.setPixelColor(x, y, QColor(x * 3, x * 3, x * 3))
        self.tab.load_image(image, self._png(image), "spectre.png")
        self.tab.add_profile(QPointF(5, 10), QPointF(70, 10))
        self.app.processEvents()

    def tearDown(self):
        for window in self.windows:
            window._discard_on_close = True
            window.close()
            window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        gc.collect()

    @staticmethod
    def _png(image):
        from physalix.ui.image_analysis_tab import portable_png
        return portable_png(image)

    def _type_known_value(self, text):
        self.window.show()
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        editor = self.tab.distance_value.lineEdit()
        QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=editor.rect().center())
        self.assertTrue(editor.hasFocus())
        QTest.keyClicks(self.tab.distance_value, text)
        QTest.keyClick(self.tab.distance_value, Qt.Key.Key_Return)
        self.app.processEvents()

    def _type_absolute_value(self, text, paste=False):
        self.window.show()
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        editor = self.tab.absolute_value.lineEdit()
        QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=editor.rect().center())
        self.assertTrue(editor.hasFocus())
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        if paste:
            QApplication.clipboard().setText(text)
            QTest.keyClick(editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        else:
            QTest.keyClicks(editor, text)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()

    def _type_spin_value(self, field, text):
        self.window.show()
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        editor = field.lineEdit()
        QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=editor.rect().center())
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(editor, text)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()

    def _click_profile_sample(self, profile, index, click_y=None):
        """Clique réellement dans le viewport pyqtgraph à la position d'un échantillon."""
        self.window.show()
        self.window.resize(1500, 850)
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        samples = self.tab.samples[profile.identifier]
        point = QPointF(float(samples.axis[index]), float(samples.intensity[index]))
        scene_point = self.tab.plot.plotItem.vb.mapViewToScene(point)
        if click_y is not None:
            bounds = self.tab.profile_view_box.sceneBoundingRect()
            scene_point.setY(bounds.top() + click_y * bounds.height())
        viewport_point = self.tab.plot.mapFromScene(scene_point)
        QTest.mouseMove(self.tab.plot.viewport(), viewport_point)
        self.app.processEvents()
        QTest.mouseClick(
            self.tab.plot.viewport(), Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier, viewport_point,
        )
        self.app.processEvents()

    def _show_canvas(self):
        self.window.show()
        self.window.resize(1500, 850)
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        return self.tab.canvas

    def _drag_canvas(self, start, end, button=Qt.MouseButton.LeftButton):
        canvas = self._show_canvas()
        start = canvas.screen_point(start).toPoint()
        end = canvas.screen_point(end).toPoint()
        QTest.mousePress(canvas, button, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(canvas, end, 20)
        QTest.mouseRelease(canvas, button, Qt.KeyboardModifier.NoModifier, end)
        self.app.processEvents()

    def _draw_canvas_segment(self, start, end):
        """Tracer par deux clics réels avec aperçu lors du déplacement libre."""
        canvas = self._show_canvas()
        start_position = canvas.screen_point(start).toPoint()
        end_position = canvas.screen_point(end).toPoint()
        original_pan = QPointF(canvas.pan)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, start_position)
        self.app.processEvents()
        self.assertIsNotNone(canvas.drag_start)
        # QTest peut conserver le pointeur global d'une fenêtre hors écran
        # précédente. Forcer une position intermédiaire garantit un vrai move.
        QTest.mouseMove(canvas, QPoint(end_position.x() - 1, end_position.y()), 5)
        QTest.mouseMove(canvas, end_position, 20)
        self.app.processEvents()
        self.assertIsNotNone(canvas.preview_end)
        self.assertEqual(canvas.pan, original_pan)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, end_position)
        self.app.processEvents()

    def test_navigation_and_harmonized_selectors(self):
        self.assertIs(self.window.tabs.widget(self.window.tabs.count() - 1), self.tab)
        self.assertEqual(self.window.tabs.tabText(self.window.tabs.count() - 1), "Analyse d'images")
        self.assertIsInstance(self.tab.profile_choice, PopupComboBox)
        self.assertIsInstance(self.tab.calibration_mode, PopupComboBox)
        self.assertEqual(self.tab.workflow.count(), 3)
        self.assertEqual(self.tab.gap_button.text(), "Mesurer un écart")
        self.assertEqual(self.tab.interfringe_button.text(), "Mesurer l’interfrange")
        self.assertTrue(self.tab.measurement_button_group.exclusive())
        self.assertEqual(self.tab.snap_choice.itemText(0), "Libre sur la courbe")
        self.assertEqual(self.tab.snap_choice.itemText(1), "Minimum proche")
        self.assertEqual(self.tab.snap_choice.itemText(2), "Maximum proche")
        self.assertTrue(any(label.text() == "Positionnement :"
                            for label in self.tab.workflow.widget(2).findChildren(QLabel)))
        self.assertFalse(hasattr(self.tab, "marker_table"))
        self.assertFalse(hasattr(self.tab, "pan_button"))
        self.assertFalse(hasattr(self.tab, "edit_button"))
        self.assertEqual(self.tab.draw_button.text(), "Tracer un profil")
        self.assertEqual(self.tab.define_calibration_button.text(), "Définir l’échelle")
        self.assertTrue(self.tab.workflow.widget(1).isAncestorOf(self.tab.draw_button))
        toolbar = self.tab.open_button.parentWidget()
        toolbar_buttons = [button.text() for button in toolbar.findChildren(
            QPushButton, options=Qt.FindChildOption.FindDirectChildrenOnly)]
        self.assertEqual(toolbar_buttons, ["Ouvrir une image…", "Image entière", "Cadrer le profil"])
        self.assertFalse(any(button.text() == "Afficher l’aide"
                             for button in self.tab.findChildren(QPushButton)))

    def test_calibration_references_are_visible_only_on_scale_page(self):
        self.tab.begin_calibration()
        self.tab.calibration_reference_changed(QPointF(10, 30), QPointF(60, 30))
        self.tab.distance_value.setValue(5)
        self.tab.distance_unit.setCurrentText("cm")
        self.tab.apply_calibration()
        canvas = self._show_canvas()
        self.assertEqual(set(canvas.calibration_label_rects()), {"A", "B"})
        original = (self.tab.calibration.first, self.tab.calibration.second,
                    self.tab.calibration.first_value, self.tab.calibration.unit)

        self.tab.workflow.setCurrentIndex(1)
        self.app.processEvents()
        self.assertFalse(canvas.calibration_visible)
        self.assertEqual(canvas.calibration_label_rects(), {})
        self.assertEqual(canvas.mode, "normal")
        self._drag_canvas((10, 30), (15, 34))
        self.assertEqual((self.tab.calibration.first, self.tab.calibration.second,
                          self.tab.calibration.first_value, self.tab.calibration.unit), original)

        self.tab.workflow.setCurrentIndex(2)
        self.assertEqual(canvas.calibration_label_rects(), {})
        self.tab.workflow.setCurrentIndex(0)
        self.app.processEvents()
        self.assertTrue(canvas.calibration_visible)
        self.assertEqual(set(canvas.calibration_label_rects()), {"A", "B"})
        self.assertEqual((self.tab.calibration.first, self.tab.calibration.second,
                          self.tab.calibration.first_value, self.tab.calibration.unit), original)

    def test_profile_plot_uses_only_the_compact_french_context_menu(self):
        self.window.show()
        self.window.resize(1500, 850)
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        viewport = self.tab.plot.viewport()
        local = viewport.rect().center()
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, local, viewport.mapToGlobal(local))
        QApplication.sendEvent(viewport, event)
        self.app.processEvents()
        self.assertTrue(event.isAccepted())
        self.assertTrue(self.tab.plot_context_menu.isVisible())
        labels = [action.text() for action in self.tab.plot_context_menu.actions()
                  if not action.isSeparator()]
        self.assertEqual(labels, [
            "Masquer le réticule", "Ajuster la vue", "Zoom avant", "Zoom arrière",
        ])
        self.assertTrue(self.tab.plot_context_menu.actions()[0].font().bold())
        self.assertTrue(all(action.menu() is None
                            for action in self.tab.plot_context_menu.actions()))
        self.assertFalse(self.tab.plot.getPlotItem().menuEnabled())
        self.tab.plot_context_menu.hide()

    def test_curve_reticle_is_default_and_manual_disable_is_respected(self):
        self.assertEqual(self.tab.plot_reticle_mode, "curve")
        self.tab.load_image(self.tab.image, self.tab.image_bytes, "spectre.png")
        self.assertEqual(self.tab.plot_reticle_mode, "hidden")
        self.tab.add_profile(QPointF(5, 10), QPointF(70, 10))
        self.assertEqual(self.tab.plot_reticle_mode, "curve")
        self.tab.update_quick_reticle_action()
        self.assertEqual(self.tab.plot_context_menu.actions()[0].text(), "Masquer le réticule")
        self.tab.plot_context_menu.actions()[0].trigger()
        self.assertEqual(self.tab.plot_reticle_mode, "hidden")
        self.assertTrue(self.tab.plot_reticle_user_choice)
        self.tab.add_profile(QPointF(10, 30), QPointF(75, 30))
        self.assertEqual(self.tab.plot_reticle_mode, "hidden")
        self.tab.update_quick_reticle_action()
        self.assertEqual(self.tab.plot_context_menu.actions()[0].text(), "Afficher le réticule")
        self.tab.plot_context_menu.actions()[0].trigger()
        self.assertEqual(self.tab.plot_reticle_mode, "curve")

    def test_graph_and_table_samples_are_marked_at_exact_image_coordinates(self):
        profile = self.tab.active_profile()
        samples = self.tab.samples[profile.identifier]
        row = 23
        scene_point = self.tab.profile_view_box.mapViewToScene(QPointF(
            float(samples.axis[row]), float(samples.intensity[row])))
        self.tab.track_plot_cursor(scene_point)
        marker, color = self.tab.canvas.hover_sample_marker
        self.assertAlmostEqual(marker[0], float(samples.x[row]))
        self.assertAlmostEqual(marker[1], float(samples.y[row]))
        self.assertEqual(color, profile.color)

        self.tab.table.selectRow(row)
        self.app.processEvents()
        selected, selected_color = self.tab.canvas.selected_sample_marker
        self.assertAlmostEqual(selected[0], float(samples.x[row]))
        self.assertAlmostEqual(selected[1], float(samples.y[row]))
        self.assertEqual(selected_color, profile.color)
        self.tab.hide_plot_crosshair()
        self.assertIsNone(self.tab.canvas.hover_sample_marker)
        self.assertIsNotNone(self.tab.canvas.selected_sample_marker)

        clicked_row = 37
        self._click_profile_sample(profile, clicked_row)
        self.assertEqual(self.tab.selected_sample_identity,
                         (profile.identifier, clicked_row))
        clicked, _ = self.tab.canvas.selected_sample_marker
        self.assertAlmostEqual(clicked[0], float(samples.x[clicked_row]))
        self.assertAlmostEqual(clicked[1], float(samples.y[clicked_row]))

    def test_sample_marker_is_exact_for_oblique_reversed_and_spectral_profiles(self):
        cases = [
            ((8, 6), (70, 32), None),
            ((70, 32), (8, 6), None),
            ((70, 30), (8, 10), "increasing"),
            ((70, 30), (8, 10), "decreasing"),
        ]
        for start, end, spectral in cases:
            with self.subTest(start=start, end=end, spectral=spectral):
                self.tab.load_image(self.tab.image, self.tab.image_bytes, "spectre.png")
                if spectral:
                    self.tab.begin_calibration()
                    self.tab.calibration_mode.setCurrentIndex(
                        self.tab.calibration_mode.findData("spectral"))
                    self.tab.distance_value.setValue(20)
                    self.tab.distance_unit.setCurrentText("nm")
                    self.tab.spectral_direction.setCurrentIndex(
                        0 if spectral == "increasing" else 1)
                    self.tab.calibration_reference_changed(QPointF(15, 5), QPointF(65, 5))
                    self.tab.apply_calibration()
                self.tab.add_profile(QPointF(*start), QPointF(*end))
                profile = self.tab.active_profile()
                samples = self.tab.samples[profile.identifier]
                row = len(samples.axis) // 3
                scene = self.tab.profile_view_box.mapViewToScene(QPointF(
                    float(samples.axis[row]), float(samples.intensity[row])))
                self.tab.track_plot_cursor(scene)
                marker, _ = self.tab.canvas.hover_sample_marker
                self.assertAlmostEqual(marker[0], float(samples.x[row]), places=6)
                self.assertAlmostEqual(marker[1], float(samples.y[row]), places=6)

    def test_spectral_duplicate_abscissas_keep_the_real_sample_index(self):
        image = QImage(80, 40, QImage.Format.Format_RGB32)
        for y in range(image.height()):
            value = min(255, y * 6)
            for x in range(image.width()):
                image.setPixelColor(x, y, QColor(value, value, value))
        self.tab.load_image(image, self._png(image), "vertical.png")
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(
            self.tab.calibration_mode.findData("spectral"))
        self.tab.distance_value.setValue(20)
        self.tab.distance_unit.setCurrentText("nm")
        self.tab.calibration_reference_changed(QPointF(10, 5), QPointF(60, 5))
        self.tab.apply_calibration()
        self.tab.add_profile(QPointF(40, 4), QPointF(40, 35))
        profile = self.tab.active_profile()
        samples = self.tab.samples[profile.identifier]
        self.assertTrue(np.allclose(samples.axis, samples.axis[0]))
        row = 19
        scene = self.tab.profile_view_box.mapViewToScene(QPointF(
            float(samples.axis[row]), float(samples.intensity[row])))
        self.tab.track_plot_cursor(scene)
        marker, _ = self.tab.canvas.hover_sample_marker
        self.assertAlmostEqual(marker[0], float(samples.x[row]), places=6)
        self.assertAlmostEqual(marker[1], float(samples.y[row]), places=6)

    def test_reticle_labels_stay_in_axis_margins_at_extrema_and_edges(self):
        self.window.show()
        self.window.resize(1500, 850)
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        profile = self.tab.active_profile()
        samples = self.tab.samples[profile.identifier]
        rows = {0, len(samples.axis) - 1,
                int(np.nanargmin(samples.intensity)), int(np.nanargmax(samples.intensity))}
        for row in rows:
            with self.subTest(row=row):
                point = QPointF(float(samples.axis[row]), float(samples.intensity[row]))
                scene = self.tab.profile_view_box.mapViewToScene(point)
                self.tab.track_plot_cursor(scene)
                self.assertTrue(self.tab.cross_x_label.isVisible())
                self.assertTrue(self.tab.cross_y_label.isVisible())
                x_rect = self.tab.cross_x_label.geometry()
                y_rect = self.tab.cross_y_label.geometry()
                self.assertTrue(self.tab.cross_x_lane.rect().contains(x_rect))
                self.assertTrue(self.tab.cross_y_lane.rect().contains(y_rect))
                plot_point = self.tab.plot.mapFromScene(scene)
                x_in_tab = self.tab.plot.mapTo(self.tab, plot_point).x()
                y_in_tab = self.tab.plot.mapTo(self.tab, plot_point).y()
                x_label_in_tab = self.tab.cross_x_label.mapTo(self.tab, QPoint())
                y_label_in_tab = self.tab.cross_y_label.mapTo(self.tab, QPoint())
                self.assertLessEqual(x_label_in_tab.x(), x_in_tab)
                self.assertGreaterEqual(
                    x_label_in_tab.x() + self.tab.cross_x_label.width(), x_in_tab)
                self.assertLessEqual(y_label_in_tab.y(), y_in_tab)
                self.assertGreaterEqual(
                    y_label_in_tab.y() + self.tab.cross_y_label.height(), y_in_tab)
                point_in_x_label = self.tab.cross_x_label.mapFrom(
                    self.tab.plot, plot_point)
                point_in_y_label = self.tab.cross_y_label.mapFrom(
                    self.tab.plot, plot_point)
                self.assertFalse(self.tab.cross_x_label.rect().contains(point_in_x_label))
                self.assertFalse(self.tab.cross_y_label.rect().contains(point_in_y_label))
        self.assertIn("px", self.tab.plot_coordinates.text())

        self.tab.begin_calibration()
        self.tab.calibration_reference_changed(QPointF(10, 5), QPointF(60, 5))
        self.tab.distance_value.setValue(5)
        self.tab.distance_unit.setCurrentText("cm")
        self.tab.apply_calibration()
        samples = self.tab.samples[profile.identifier]
        self.tab.track_plot_cursor(self.tab.profile_view_box.mapViewToScene(QPointF(
            float(samples.axis[10]), float(samples.intensity[10]))))
        self.assertIn("cm", self.tab.plot_coordinates.text())

        self.tab.reset_calibration()
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(
            self.tab.calibration_mode.findData("spectral"))
        self.tab.distance_value.setValue(20)
        self.tab.distance_unit.setCurrentText("nm")
        self.tab.calibration_reference_changed(QPointF(10, 5), QPointF(60, 5))
        self.tab.apply_calibration()
        samples = self.tab.samples[profile.identifier]
        self.tab.track_plot_cursor(self.tab.profile_view_box.mapViewToScene(QPointF(
            float(samples.axis[10]), float(samples.intensity[10]))))
        self.assertIn("nm", self.tab.plot_coordinates.text())

    def test_reticle_label_qss_emits_no_parse_warning(self):
        messages = []
        previous = qInstallMessageHandler(
            lambda message_type, context, message: messages.append(message))
        try:
            window = MainWindow()
            self.windows.append(window)
            tab = window.image_analysis_tab
            image = QImage(80, 40, QImage.Format.Format_RGB32)
            image.fill(QColor("white"))
            tab.load_image(image, self._png(image), "qss.png")
            tab.add_profile(QPointF(5, 10), QPointF(70, 10))
            window.resize(1500, 850)
            window.show()
            window.tabs.setCurrentWidget(tab)
            self.app.processEvents()
            samples = tab.samples[tab.active_identifier]
            for row in (0, len(samples.axis) // 2, len(samples.axis) - 1):
                tab.track_plot_cursor(tab.profile_view_box.mapViewToScene(QPointF(
                    float(samples.axis[row]), float(samples.intensity[row]))))
                self.app.processEvents()
            tab.refresh_plot(fit=False)
            self.app.processEvents()
        finally:
            qInstallMessageHandler(previous)
        parse_warnings = [message for message in messages
                          if "Could not parse stylesheet" in message]
        self.assertEqual(parse_warnings, [])

    def test_compact_layout_remains_separated_at_supported_window_sizes(self):
        self.window.show()
        self.window.tabs.setCurrentWidget(self.tab)
        header = self.tab.layout().itemAt(0).widget()
        for width, height in ((1280, 800), (1366, 768), (1600, 900), (1920, 1080)):
            with self.subTest(size=(width, height)):
                self.window.resize(width, height)
                self.app.processEvents()
                canvas_geometry = self.tab.canvas.geometry()
                results_geometry = self.tab.results.geometry()
                self.assertLessEqual(canvas_geometry.bottom(), results_geometry.top())
                self.assertGreater(self.tab.canvas.height(), 200)
                self.assertGreater(self.tab.results.height(), 150)
                self.assertLessEqual(header.height(), 44)
                self.assertIs(self.tab.fit_plot_button.parentWidget(), self.tab.results)
                status_y = {widget.mapTo(self.tab, QPoint()).y() for widget in (
                    self.tab.plot_coordinates, self.tab.image_info, self.tab.status)}
                self.assertEqual(len(status_y), 1)

    def test_profile_plot_zoom_and_reticles_preserve_measurement(self):
        self.window.show()
        self.window.resize(1500, 850)
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        first = self.tab.active_profile()
        self.tab.add_profile(QPointF(10, 30), QPointF(75, 30))
        second = self.tab.active_profile()
        self.tab.start_measurement("gap")
        self._click_profile_sample(first, 10)
        self._click_profile_sample(first, 40)
        fractions = (self.tab.measurement.first.fraction,
                     self.tab.measurement.second.fraction)
        samples = self.tab.samples[second.identifier]
        curve_scene = self.tab.profile_view_box.mapViewToScene(
            QPointF(float(samples.axis[25]), float(samples.intensity[25])))
        curve_viewport = self.tab.plot.mapFromScene(curve_scene)
        QTest.mouseClick(self.tab.plot.viewport(), Qt.MouseButton.RightButton,
                         Qt.KeyboardModifier.NoModifier, curve_viewport)
        self.app.processEvents()
        self.assertEqual((self.tab.measurement.first.fraction,
                          self.tab.measurement.second.fraction), fractions)
        self.tab.plot_context_menu.hide()

        before_x, before_y = self.tab.profile_view_box.viewRange()
        self.tab.zoom_profile_plot(.5)
        zoomed_x, zoomed_y = self.tab.profile_view_box.viewRange()
        self.assertLess(zoomed_x[1] - zoomed_x[0], before_x[1] - before_x[0])
        self.assertLess(zoomed_y[1] - zoomed_y[0], before_y[1] - before_y[0])
        self.tab.zoom_profile_plot(2)

        self.tab.set_plot_reticle_mode("free")
        free_point = self.tab.profile_view_box.mapViewToScene(QPointF(25, 100))
        self.tab.track_plot_cursor(free_point)
        self.assertTrue(self.tab.cross_x.isVisible())
        self.assertIn("Intensité", self.tab.plot_coordinates.text())

        index = 25
        curve_point = self.tab.profile_view_box.mapViewToScene(
            QPointF(float(samples.axis[index]), float(samples.intensity[index])))
        self.tab.set_plot_reticle_mode("curve")
        QTest.mouseMove(self.tab.plot.viewport(), self.tab.plot.mapFromScene(curve_point))
        self.app.processEvents()
        self.assertTrue(self.tab.cross_x.isVisible())
        self.assertAlmostEqual(self.tab.cross_x.value(), float(samples.axis[index]))
        self.assertIn(second.name, self.tab.plot_coordinates.text())
        self.assertIn(self.tab.calibration.unit, self.tab.plot_coordinates.text())
        image_marker, marker_color = self.tab.canvas.hover_sample_marker
        self.assertAlmostEqual(image_marker[0], float(samples.x[index]))
        self.assertAlmostEqual(image_marker[1], float(samples.y[index]))
        self.assertEqual(marker_color, second.color)
        self.tab.set_plot_reticle_mode("hidden")
        self.assertFalse(self.tab.cross_x.isVisible())
        self.assertEqual((self.tab.measurement.first.fraction,
                          self.tab.measurement.second.fraction), fractions)

        self.tab.start_rectangle_zoom()
        self.assertEqual(self.tab.profile_view_box.state["mouseMode"], pg.ViewBox.RectMode)
        viewport = self.tab.plot.viewport()
        bounds = self.tab.profile_view_box.sceneBoundingRect()
        start = self.tab.plot.mapFromScene(QPointF(
            bounds.left() + bounds.width() * .25,
            bounds.top() + bounds.height() * .25))
        end = self.tab.plot.mapFromScene(QPointF(
            bounds.left() + bounds.width() * .75,
            bounds.top() + bounds.height() * .75))
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(viewport, end, 20)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, end)
        # Le backend Qt offscreen ne transmet pas toujours le relâchement au
        # QGraphicsItem ; le signal est celui émis par le ViewBox en usage réel.
        if self.tab.rectangle_zoom_pending:
            self.tab.profile_view_box.rectangle_zoom_finished.emit()
        self.app.processEvents()
        self.assertEqual(self.tab.profile_view_box.state["mouseMode"], pg.ViewBox.PanMode)
        self.assertFalse(self.tab.rectangle_zoom_pending)

    def test_calibration_editor_has_no_tp_specific_defaults(self):
        self.tab.begin_calibration()
        self.assertEqual(self.tab.distance_value.value(), 0)
        self.assertEqual(self.tab.distance_value.text(), "")
        self.assertEqual(self.tab.distance_value.lineEdit().placeholderText(), "À saisir")
        self.assertFalse(self.tab.absolute_reference.isChecked())
        self.assertNotIn("592", self.tab.calibration_status.text())
        self.assertNotIn("590", self.tab.calibration_status.text())

    def test_calibration_fields_follow_the_pedagogical_order(self):
        self.tab.begin_calibration()
        self._show_canvas()

        def top(widget):
            return widget.mapTo(self.tab.calibration_editor, QPoint()).y()

        self.assertLess(top(self.tab.calibration_mode), top(self.tab.distance_button))
        self.assertLess(top(self.tab.distance_button), top(self.tab.calibration_pixel_length))
        self.assertLess(top(self.tab.calibration_pixel_length), top(self.tab.distance_value))
        self.assertLess(top(self.tab.distance_value), top(self.tab.apply_calibration_button))
        self.tab.calibration_mode.setCurrentIndex(
            self.tab.calibration_mode.findData("spectral"))
        self.tab.absolute_reference.setChecked(True)
        self.assertEqual(
            self.tab.absolute_value_label.text(),
            "Longueur d’onde au point A (λ<sub>A</sub>)",
        )
        self.assertLess(top(self.tab.absolute_value_label), top(self.tab.absolute_value))
        self.assertLess(top(self.tab.distance_value), top(self.tab.spectral_options))
        self.assertLess(top(self.tab.spectral_options), top(self.tab.apply_calibration_button))

    def test_calibration_labels_follow_handles_zoom_and_pan(self):
        self.tab.begin_calibration()
        self.tab.calibration_reference_changed(QPointF(12, 8), QPointF(65, 28))
        canvas = self._show_canvas()
        before = canvas.calibration_label_rects()
        self.assertEqual(set(before), {"A", "B"})
        self.assertFalse(before["A"].contains(canvas.screen_point((12, 8))))
        self.assertFalse(before["B"].contains(canvas.screen_point((65, 28))))
        self._drag_canvas((12, 8), (18, 12))
        moved = canvas.calibration_label_rects()
        self.assertNotEqual(moved["A"].center(), before["A"].center())
        self.assertFalse(moved["A"].contains(canvas.screen_point((18, 12))))
        self.assertFalse(moved["B"].contains(canvas.screen_point((65, 28))))
        canvas.zoom = 1.8
        canvas.pan = QPointF(20, -10)
        zoomed = canvas.calibration_label_rects()
        self.assertNotEqual(zoomed["A"].center(), moved["A"].center())
        self.assertNotEqual(zoomed["B"].center(), moved["B"].center())
        canvas.zoom = 1
        canvas.pan = QPointF()
        self.tab.calibration_reference_changed(QPointF(0, 0), QPointF(79, 39))
        edge = canvas.calibration_label_rects()
        self.assertFalse(edge["A"].contains(canvas.screen_point((0, 0))))
        self.assertFalse(edge["B"].contains(canvas.screen_point((79, 39))))

    def test_absolute_spectral_reference_is_always_attached_to_endpoint_a(self):
        for first_x, second_x, direction in (
                (20, 60, 1), (60, 20, 1), (20, 60, -1), (60, 20, -1)):
            with self.subTest(first_x=first_x, second_x=second_x, direction=direction):
                self.tab.reset_calibration()
                self.tab.begin_calibration()
                self.tab.calibration_mode.setCurrentIndex(
                    self.tab.calibration_mode.findData("spectral"))
                self.tab.absolute_reference.setChecked(True)
                self.tab.absolute_value.setValue(500)
                self.tab.distance_value.setValue(2)
                self.tab.distance_unit.setCurrentText("nm")
                self.tab.spectral_direction.setCurrentIndex(
                    self.tab.spectral_direction.findData(direction))
                self.tab.calibration_reference_changed(
                    QPointF(first_x, 8), QPointF(second_x, 18))
                self.tab.apply_calibration()
                expected_b = 500 + direction * (1 if second_x > first_x else -1) * 2
                self.assertEqual(self.tab.calibration.first_value, 500)
                self.assertEqual(self.tab.calibration.second_value, expected_b)
                self.assertIn("λ<sub>A</sub> = 500 nm", self.tab.calibration_status.text())
                self.assertIn(
                    f"λ<sub>B</sub> = {expected_b:g} nm",
                    self.tab.calibration_status.text(),
                )

    def test_known_gap_absolute_reference_can_be_attached_to_endpoint_b(self):
        for first_x, second_x, direction in (
                (20, 60, 1), (60, 20, 1), (20, 60, -1), (60, 20, -1)):
            with self.subTest(first_x=first_x, second_x=second_x, direction=direction):
                self.tab.reset_calibration()
                self.tab.begin_calibration()
                self.tab.calibration_mode.setCurrentIndex(
                    self.tab.calibration_mode.findData("spectral"))
                self.tab.absolute_reference.setChecked(True)
                self.tab.absolute_reference_endpoint.setCurrentIndex(
                    self.tab.absolute_reference_endpoint.findData("B"))
                self.tab.absolute_value.setValue(590)
                self.tab.distance_value.setValue(2)
                self.tab.spectral_direction.setCurrentIndex(
                    self.tab.spectral_direction.findData(direction))
                self.tab.calibration_reference_changed(
                    QPointF(first_x, 8), QPointF(second_x, 18))
                self.tab.apply_calibration()
                signed_gap = direction * (1 if second_x > first_x else -1) * 2
                self.assertEqual(self.tab.calibration.second_value, 590)
                self.assertEqual(self.tab.calibration.first_value, 590 - signed_gap)
                self.assertEqual(self.tab.calibration.reference_endpoint, "B")
                self.assertIn("λ<sub>B</sub> = 590 nm", self.tab.calibration_status.text())

    def test_two_point_spectral_calibration_uses_real_clicks_and_updates_profiles(self):
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(
            self.tab.calibration_mode.findData("spectral"))
        self.tab.spectral_method.setCurrentIndex(
            self.tab.spectral_method.findData("two_points"))
        canvas = self._show_canvas()
        QTest.mouseClick(self.tab.place_spectral_a_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=canvas.screen_point((20, 8)).toPoint())
        self._type_spin_value(self.tab.first_wavelength, "592,136")
        QTest.mouseClick(self.tab.place_spectral_b_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=canvas.screen_point((60, 25)).toPoint())
        self._type_spin_value(self.tab.second_wavelength, "590.101")
        self.assertTrue(self.tab.apply_calibration_button.isEnabled())
        self.assertIn("λ<sub>B</sub> − λ<sub>A</sub> = -2,035 nm",
                      self.tab.two_point_status.text())
        self.assertIn("croissante vers la gauche", self.tab.two_point_status.text())
        QTest.mouseClick(self.tab.apply_calibration_button, Qt.MouseButton.LeftButton)
        calibration = self.tab.calibration
        self.assertEqual(calibration.spectral_method, "two_points")
        self.assertEqual(calibration.first_value, 592.136)
        self.assertEqual(calibration.second_value, 590.101)
        self.assertLess((calibration.second_value - calibration.first_value)
                        / (calibration.second[0] - calibration.first[0]), 0)
        samples_before = self.tab.samples[self.tab.active_identifier].axis.copy()
        self.tab.begin_calibration()
        self._drag_canvas((20, 8), (25, 12))
        self.tab.apply_calibration()
        samples_after = self.tab.samples[self.tab.active_identifier].axis
        self.assertFalse(np.allclose(samples_before, samples_after))

    def test_two_point_spectral_calibration_rejects_degenerate_references(self):
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(
            self.tab.calibration_mode.findData("spectral"))
        self.tab.spectral_method.setCurrentIndex(
            self.tab.spectral_method.findData("two_points"))
        self.tab.spectral_points = [(30, 5), (30, 25)]
        self.tab.calibration_reference = tuple(self.tab.spectral_points)
        self.tab.first_wavelength.setValue(592.136)
        self.tab.second_wavelength.setValue(590.101)
        self.tab.update_calibration_length()
        self.assertFalse(self.tab.apply_calibration_button.isEnabled())
        self.tab.apply_calibration()
        self.assertIn("abscisses", self.tab.status.text())
        self.tab.spectral_points = [(20, 5), (60, 25)]
        self.tab.calibration_reference = tuple(self.tab.spectral_points)
        self.tab.second_wavelength.setValue(592.136)
        self.tab.update_calibration_length()
        self.assertFalse(self.tab.apply_calibration_button.isEnabled())
        self.tab.apply_calibration()
        self.assertIn("valeurs distinctes", self.tab.status.text())

    def test_switching_spectral_method_does_not_reuse_incompatible_references(self):
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(
            self.tab.calibration_mode.findData("spectral"))
        self.tab.calibration_reference_changed(QPointF(10, 5), QPointF(60, 25))
        self.assertIsNotNone(self.tab.calibration_reference)
        self.tab.spectral_method.setCurrentIndex(
            self.tab.spectral_method.findData("two_points"))
        self.assertIsNone(self.tab.calibration_reference)
        self.assertEqual(self.tab.spectral_points, [None, None])
        self.assertFalse(self.tab.two_point_options.isHidden())
        self.assertTrue(self.tab.distance_button.isHidden())

    def test_absolute_wavelength_accepts_keyboard_and_paste_decimal_separators(self):
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(
            self.tab.calibration_mode.findData("spectral"))
        self.tab.absolute_reference.setChecked(True)
        field = self.tab.absolute_value
        self.assertEqual(field.locale().language(), QLocale.Language.French)
        self.assertEqual(field.decimals(), 6)
        for text, paste in (("650.035", False), ("650,035", False), ("650.035", True)):
            with self.subTest(text=text, paste=paste):
                self._type_absolute_value(text, paste=paste)
                self.assertAlmostEqual(field.value(), 650.035, places=6)
                self.assertIn("650,035", field.text())
        self.tab.distance_value.setValue(2.035)
        self.tab.distance_unit.setCurrentText("nm")
        self.tab.calibration_reference_changed(QPointF(10, 5), QPointF(60, 25))
        self.tab.apply_calibration()
        self.assertAlmostEqual(self.tab.calibration.first_value, 650.035, places=6)

    def test_distance_value_is_validated_after_drawing_reference(self):
        self.tab.begin_calibration()
        self.tab.workflow.setCurrentIndex(0)
        QTest.mouseClick(self.tab.distance_button, Qt.MouseButton.LeftButton)
        self._draw_canvas_segment((10, 8), (60, 8))
        first, second = self.tab.calibration_reference
        length = np.hypot(second[0] - first[0], second[1] - first[1])
        self.assertGreater(length, 49)
        self.assertIn("px", self.tab.calibration_pixel_length.text())
        self._type_known_value("5")
        self.tab.distance_unit.setCurrentText("cm")
        self.assertTrue(self.tab.apply_calibration_button.isEnabled())
        QTest.mouseClick(self.tab.apply_calibration_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.calibration.mode, "distance")
        self.assertEqual(self.tab.calibration.first_value, 5)

    def test_known_gap_accepts_real_french_keyboard_input_and_applies(self):
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(self.tab.calibration_mode.findData("spectral"))
        self.tab.calibration_reference_changed(QPointF(10, 5), QPointF(60, 25))
        field = self.tab.distance_value
        self.assertTrue(field.isEnabled())
        self.assertFalse(field.isReadOnly())
        self.assertEqual(field.locale().language(), QLocale.Language.French)
        self.assertEqual(field.decimals(), 6)
        for text in ("2,035", "2.035"):
            self.assertEqual(field.validate(text, len(text))[0], QValidator.State.Acceptable)
        self._type_known_value("2,035")
        self.assertAlmostEqual(field.value(), 2.035, places=6)
        self.assertIn(",", field.text())
        self.assertTrue(self.tab.apply_calibration_button.isEnabled())
        QTest.mouseClick(self.tab.apply_calibration_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.tab.calibration.mode, "spectral")
        self.assertAlmostEqual(abs(self.tab.calibration.second_value
                                   - self.tab.calibration.first_value), 2.035, places=6)
        self.tab.reset_calibration()
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(self.tab.calibration_mode.findData("spectral"))
        self.tab.calibration_reference_changed(QPointF(10, 5), QPointF(60, 25))
        self._type_known_value("2.035")
        self.assertAlmostEqual(self.tab.distance_value.value(), 2.035, places=6)

    def test_calibration_segment_is_directly_adjustable_without_selecting_profile(self):
        profile = self.tab.active_profile()
        profile_geometry = profile.start, profile.end
        self.tab.begin_calibration()
        self.tab.calibration_reference_changed(QPointF(10, 5), QPointF(60, 25))
        canvas = self._show_canvas()
        self.assertEqual(canvas.mode, "calibration_edit")
        self._drag_canvas((10, 5), (14, 8))
        first, second = self.tab.calibration_reference
        self.assertAlmostEqual(first[0], 14, delta=.5)
        self.assertAlmostEqual(first[1], 8, delta=.5)
        self.assertEqual(second, (60.0, 25.0))
        self.assertEqual((profile.start, profile.end), profile_geometry)

    def test_calibration_horizontal_constraint_applies_to_drawing_and_handles(self):
        self.tab.begin_calibration()
        self.tab.calibration_horizontal.setChecked(True)
        self._draw_canvas_segment((10, 8), (60, 25))
        first, second = self.tab.calibration_reference
        self.assertEqual(first[1], second[1])
        self._drag_canvas(second, (68, 30))
        first, second = self.tab.calibration_reference
        self.assertEqual(first[1], second[1])
        midpoint = ((first[0] + second[0]) / 2, first[1])
        old_y = first[1]
        self._drag_canvas(midpoint, (midpoint[0] + 2, midpoint[1] + 5))
        first, second = self.tab.calibration_reference
        self.assertAlmostEqual(first[1], old_y + 5, delta=.6)
        self.assertEqual(first[1], second[1])
        self.tab.calibration_horizontal.setChecked(False)
        self._drag_canvas(second, (68, 30))
        first, second = self.tab.calibration_reference
        self.assertNotEqual(first[1], second[1])

    def test_horizontalizing_a_validated_scale_invalidates_it_until_revalidated(self):
        self.tab.begin_calibration()
        self.tab.calibration_reference_changed(QPointF(10, 8), QPointF(60, 25))
        self.tab.distance_value.setValue(5)
        self.tab.apply_calibration()
        self.assertEqual(self.tab.calibration.mode, "distance")
        self.tab.begin_calibration()
        self.tab.calibration_horizontal.setChecked(True)
        self.assertEqual(self.tab.calibration.mode, "none")
        first, second = self.tab.calibration_reference
        self.assertEqual(first[1], second[1])
        self.assertTrue(self.tab.apply_calibration_button.isEnabled())
        self.tab.apply_calibration()
        self.assertEqual(self.tab.calibration.mode, "distance")
        self.assertTrue(self.tab.calibration.horizontal)

    def test_bmp_import_preserves_original_pixel_coordinates(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "image.bmp"
        image = QImage(23, 17, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(str(path)))
        self.assertTrue(self.tab.open_image(path))
        self.assertEqual((self.tab.image.width(), self.tab.image.height()), (23, 17))

    def test_image_zoom_under_pointer_and_segment_framing_are_independent(self):
        self.assertEqual(self.tab.fit_button.text(), "Image entière")
        self.assertEqual(self.tab.frame_segment_button.text(), "Cadrer le profil")
        self.assertEqual(self.tab.fit_plot_button.text(), "Ajuster la vue")
        self.assertIn("photographie", self.tab.fit_button.toolTip())
        self.assertIn("extrémités", self.tab.frame_segment_button.toolTip())
        self.assertIn("courbes visibles", self.tab.fit_plot_button.toolTip())
        canvas = self.tab.canvas
        canvas.resize(800, 300)
        canvas.fit_to_window()
        pointer = QPointF(400, 150)
        before = canvas.image_point(pointer)
        event = QWheelEvent(pointer, pointer, QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        canvas.wheelEvent(event)
        after = canvas.image_point(pointer)
        self.assertAlmostEqual(before.x(), after.x(), places=6)
        self.assertAlmostEqual(before.y(), after.y(), places=6)
        plot_range = self.tab.plot.plotItem.vb.viewRange()
        self.tab.fit_button.click()
        self.assertEqual(canvas.zoom, 1)
        self.assertEqual(plot_range, self.tab.plot.plotItem.vb.viewRange())
        self.tab.frame_segment_button.click()
        start = canvas.screen_point(self.tab.active_profile().start)
        end = canvas.screen_point(self.tab.active_profile().end)
        for point in (start, end):
            self.assertGreaterEqual(point.x(), 30)
            self.assertLessEqual(point.x(), canvas.width() - 30)
            self.assertGreaterEqual(point.y(), 30)
            self.assertLessEqual(point.y(), canvas.height() - 30)
        self.assertEqual(plot_range, self.tab.plot.plotItem.vb.viewRange())
        canvas_state = canvas.zoom, canvas.pan.x(), canvas.pan.y()
        self.tab.plot.setRange(xRange=(20, 30), yRange=(50, 100), padding=0)
        self.tab.fit_plot_button.click()
        samples = self.tab.samples[self.tab.active_identifier]
        fitted_x, fitted_y = self.tab.plot.plotItem.vb.viewRange()
        self.assertLessEqual(fitted_x[0], float(np.min(samples.axis)))
        self.assertGreaterEqual(fitted_x[1], float(np.max(samples.axis)))
        self.assertLessEqual(fitted_y[0], float(np.min(samples.intensity)))
        self.assertGreaterEqual(fitted_y[1], float(np.max(samples.intensity)))
        self.assertEqual(canvas_state, (canvas.zoom, canvas.pan.x(), canvas.pan.y()))

    def test_direct_profile_creation_endpoint_and_body_dragging(self):
        self.tab.load_image(self.tab.image, self.tab.image_bytes, "spectre.png")
        canvas = self._show_canvas()
        self.tab.workflow.setCurrentIndex(1)
        QTest.mouseClick(self.tab.draw_button, Qt.MouseButton.LeftButton)
        self.assertEqual(canvas.mode, "draw")
        self._draw_canvas_segment((10, 12), (65, 12))
        self.assertEqual(len(self.tab.profiles), 1)
        profile = self.tab.active_profile()
        self.assertEqual(canvas.mode, "normal")
        self.assertFalse(self.tab.draw_button.isChecked())
        samples = self.tab.samples[profile.identifier]
        x_range, y_range = self.tab.plot.plotItem.vb.viewRange()
        self.assertLessEqual(x_range[0], float(np.min(samples.axis)))
        self.assertGreaterEqual(x_range[1], float(np.max(samples.axis)))
        self.assertLessEqual(y_range[0], float(np.min(samples.intensity)))
        self.assertGreaterEqual(y_range[1], float(np.max(samples.intensity)))

        self._drag_canvas(profile.start, (14, 17))
        self.assertAlmostEqual(profile.start[0], 14, delta=.5)
        self.assertAlmostEqual(profile.start[1], 17, delta=.5)
        self._drag_canvas(profile.end, (70, 18))
        self.assertAlmostEqual(profile.end[0], 70, delta=.5)
        self.assertAlmostEqual(profile.end[1], 18, delta=.5)

        old_start, old_end = profile.start, profile.end
        midpoint = ((old_start[0] + old_end[0]) / 2, (old_start[1] + old_end[1]) / 2)
        self._drag_canvas(midpoint, (midpoint[0] + 4, midpoint[1] + 6))
        self.assertAlmostEqual(profile.start[0], old_start[0] + 4, delta=.6)
        self.assertAlmostEqual(profile.start[1], old_start[1] + 6, delta=.6)
        self.assertAlmostEqual(profile.end[0], old_end[0] + 4, delta=.6)
        self.assertAlmostEqual(profile.end[1], old_end[1] + 6, delta=.6)

    def test_profile_preview_uses_the_final_color_handles_and_render(self):
        self.tab.load_image(self.tab.image, self.tab.image_bytes, "spectre.png")
        canvas = self._show_canvas()
        self.tab.workflow.setCurrentIndex(1)
        QTest.mouseClick(self.tab.draw_button, Qt.MouseButton.LeftButton)
        start = canvas.screen_point((10, 12)).toPoint()
        end = canvas.screen_point((65, 26)).toPoint()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=start)
        self.assertEqual(len(self.tab.profiles), 0)
        self.assertEqual(canvas.preview_segment_style(), (SERIES_COLORS[0], 2, True))

        QTest.mouseMove(canvas, QPoint(end.x() - 1, end.y()), 5)
        QTest.mouseMove(canvas, end, 20)
        self.app.processEvents()
        preview = canvas.grab().toImage()
        self.assertEqual(len(self.tab.profiles), 0)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
        self.app.processEvents()
        profile = self.tab.active_profile()
        self.assertEqual(profile.color, SERIES_COLORS[0])
        self.assertEqual(preview, canvas.grab().toImage())

        QTest.mouseClick(self.tab.draw_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=canvas.screen_point((15, 30)).toPoint())
        self.assertEqual(canvas.preview_segment_style(), (SERIES_COLORS[1], 2, True))
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertEqual(len(self.tab.profiles), 1)

    def test_calibration_preview_uses_final_handles_labels_and_render(self):
        self.tab.begin_calibration()
        QTest.mouseClick(self.tab.distance_button, Qt.MouseButton.LeftButton)
        canvas = self._show_canvas()
        start = canvas.screen_point((10, 8)).toPoint()
        end = canvas.screen_point((60, 25)).toPoint()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=start)
        self.assertIsNone(self.tab.calibration_reference)
        self.assertEqual(set(canvas.preview_calibration_label_rects()), {"A"})

        QTest.mouseMove(canvas, QPoint(end.x() - 1, end.y()), 5)
        QTest.mouseMove(canvas, end, 20)
        self.app.processEvents()
        preview = canvas.grab().toImage()
        self.assertEqual(canvas.preview_segment_style(), (LIGHT.warning, 2, True))
        self.assertEqual(set(canvas.preview_calibration_label_rects()), {"A", "B"})
        for rectangle in canvas.preview_calibration_label_rects().values():
            self.assertTrue(canvas.rect().contains(rectangle.toAlignedRect()))
        self.assertIsNone(self.tab.calibration_reference)

        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
        self.app.processEvents()
        self.assertIsNotNone(self.tab.calibration_reference)
        self.assertEqual(set(canvas.calibration_label_rects()), {"A", "B"})
        self.assertEqual(preview, canvas.grab().toImage())

    def test_profile_horizontal_constraint_applies_to_drawing_and_handles(self):
        self.tab.profile_horizontal.setChecked(True)
        self.tab.workflow.setCurrentIndex(1)
        QTest.mouseClick(self.tab.draw_button, Qt.MouseButton.LeftButton)
        self._draw_canvas_segment((10, 18), (65, 30))
        profile = self.tab.active_profile()
        self.assertTrue(profile.horizontal)
        self.assertEqual(profile.start[1], profile.end[1])
        self._drag_canvas(profile.end, (72, 30))
        self.assertEqual(profile.start[1], profile.end[1])
        midpoint = ((profile.start[0] + profile.end[0]) / 2, profile.start[1])
        old_y = profile.start[1]
        self._drag_canvas(midpoint, (midpoint[0] + 2, midpoint[1] + 5))
        self.assertAlmostEqual(profile.start[1], old_y + 5, delta=.6)
        self.assertEqual(profile.start[1], profile.end[1])
        self.tab.profile_horizontal.setChecked(False)
        self._drag_canvas(profile.end, (72, 30))
        self.assertFalse(profile.horizontal)
        self.assertNotEqual(profile.start[1], profile.end[1])

    def test_direct_click_selects_profile_without_moving_it(self):
        first = self.tab.profiles[0]
        self.tab.add_profile(QPointF(5, 30), QPointF(70, 30))
        self.assertNotEqual(self.tab.active_identifier, first.identifier)
        original = first.start, first.end
        canvas = self._show_canvas()
        midpoint = QPointF((first.start[0] + first.end[0]) / 2,
                           (first.start[1] + first.end[1]) / 2)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, canvas.screen_point(midpoint).toPoint())
        self.app.processEvents()
        self.assertEqual(self.tab.active_identifier, first.identifier)
        self.assertEqual((first.start, first.end), original)

    def test_middle_and_space_drag_pan_without_changing_profile(self):
        canvas = self._show_canvas()
        canvas.zoom = 2
        canvas.pan = QPointF()
        canvas.update()
        profile = self.tab.active_profile()
        geometry = profile.start, profile.end
        QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=QPoint(300, 160))
        QTest.mouseMove(canvas, QPoint(340, 185), 20)
        QTest.mouseRelease(canvas, Qt.MouseButton.MiddleButton, pos=QPoint(340, 185))
        self.assertAlmostEqual(canvas.pan.x(), 40, delta=1)
        self.assertAlmostEqual(canvas.pan.y(), 25, delta=1)

        QTest.keyPress(canvas, Qt.Key.Key_Space)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(340, 185))
        QTest.mouseMove(canvas, QPoint(320, 200), 20)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(320, 200))
        QTest.keyRelease(canvas, Qt.Key.Key_Space)
        self.app.processEvents()
        self.assertAlmostEqual(canvas.pan.x(), 20, delta=1)
        self.assertAlmostEqual(canvas.pan.y(), 40, delta=1)
        self.assertEqual((profile.start, profile.end), geometry)

    def test_left_drag_pans_free_image_area_with_hand_cursors(self):
        canvas = self._show_canvas()
        canvas.zoom = 2
        canvas.pan = QPointF()
        canvas.update()
        self.app.processEvents()
        start = canvas.screen_point((40, 24)).toPoint()
        end = start + QPoint(28, 18)
        QTest.mouseMove(canvas, start)
        self.assertEqual(canvas.cursor().shape(), Qt.CursorShape.OpenHandCursor)
        before = QPointF(canvas.pan)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=start)
        self.assertEqual(canvas.pan, before)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        self.assertEqual(canvas.cursor().shape(), Qt.CursorShape.ClosedHandCursor)
        QTest.mouseMove(canvas, end, 20)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
        self.app.processEvents()
        self.assertAlmostEqual(canvas.pan.x(), before.x() + 28, delta=1)
        self.assertAlmostEqual(canvas.pan.y(), before.y() + 18, delta=1)
        self.assertEqual(canvas.cursor().shape(), Qt.CursorShape.OpenHandCursor)

    def test_escape_cancels_profile_drawing(self):
        canvas = self._show_canvas()
        QTest.mouseClick(self.tab.gap_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.measure_mode, "gap")
        self.tab.workflow.setCurrentIndex(1)
        QTest.mouseClick(self.tab.draw_button, Qt.MouseButton.LeftButton)
        self.assertIsNone(self.tab.measure_mode)
        start = canvas.screen_point((15, 20)).toPoint()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, canvas.screen_point((40, 20)).toPoint(), 20)
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertEqual(canvas.mode, "normal")
        self.assertIsNone(canvas.drag_start)
        self.assertEqual(len(self.tab.profiles), 1)

    def test_pan_gestures_do_not_finish_a_two_click_profile(self):
        self.tab.workflow.setCurrentIndex(1)
        QTest.mouseClick(self.tab.draw_button, Qt.MouseButton.LeftButton)
        canvas = self._show_canvas()
        initial_count = len(self.tab.profiles)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=canvas.screen_point((12, 22)).toPoint())
        anchor = QPointF(canvas.drag_start)

        pointer = canvas.screen_point((35, 22))
        zoom_event = QWheelEvent(
            pointer, pointer, QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        canvas.wheelEvent(zoom_event)
        self.assertGreater(canvas.zoom, 1)
        self.assertEqual(canvas.drag_start, anchor)
        self.assertEqual(len(self.tab.profiles), initial_count)

        QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=QPoint(300, 160))
        QTest.mouseMove(canvas, QPoint(325, 175), 20)
        QTest.mouseRelease(canvas, Qt.MouseButton.MiddleButton, pos=QPoint(325, 175))
        self.assertEqual(canvas.drag_start, anchor)
        self.assertEqual(len(self.tab.profiles), initial_count)

        QTest.keyPress(canvas, Qt.Key.Key_Space)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(325, 175))
        QTest.mouseMove(canvas, QPoint(310, 180), 20)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(310, 180))
        QTest.keyRelease(canvas, Qt.Key.Key_Space)
        self.assertEqual(canvas.drag_start, anchor)
        self.assertEqual(len(self.tab.profiles), initial_count)

        end = canvas.screen_point((65, 28)).toPoint()
        QTest.mouseMove(canvas, end, 20)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
        self.app.processEvents()
        self.assertEqual(len(self.tab.profiles), initial_count + 1)
        self.assertEqual(canvas.mode, "normal")

    def test_interfringe_label_is_explicit_and_readable_at_1366(self):
        self.window.show()
        self.window.resize(1366, 768)
        self.window.tabs.setCurrentWidget(self.tab)
        self.tab.workflow.setCurrentIndex(2)
        QTest.mouseClick(self.tab.interfringe_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.tab.intervals_label.text(), "Nombre d'interfranges")
        self.assertTrue(self.tab.intervals_label.isVisible())
        self.assertGreaterEqual(
            self.tab.intervals_label.width(), self.tab.intervals_label.sizeHint().width())

    def test_manual_graph_zoom_survives_active_profile_switch(self):
        self.tab.add_profile(QPointF(5, 30), QPointF(70, 30))
        self.tab.plot.setRange(xRange=(20, 30), yRange=(50, 100), padding=0)
        expected = self.tab.plot.plotItem.vb.viewRange()
        self.tab.profile_choice.setCurrentIndex(0)
        actual = self.tab.plot.plotItem.vb.viewRange()
        for expected_axis, actual_axis in zip(expected, actual):
            self.assertTrue(np.allclose(expected_axis, actual_axis))

    def test_manual_graph_zoom_survives_profile_geometry_change(self):
        profile = self.tab.active_profile()
        self.tab.plot.setRange(xRange=(20, 30), yRange=(50, 100), padding=0)
        expected = self.tab.plot.plotItem.vb.viewRange()
        self._drag_canvas(profile.end, (72, 14))
        actual = self.tab.plot.plotItem.vb.viewRange()
        for expected_axis, actual_axis in zip(expected, actual):
            self.assertTrue(np.allclose(expected_axis, actual_axis))

    def test_measurement_click_validates_the_sample_followed_by_the_reticle(self):
        self.window.show()
        self.window.resize(1500, 850)
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        profile = self.tab.active_profile()
        samples = self.tab.samples[profile.identifier]
        QTest.mouseClick(self.tab.gap_button, Qt.MouseButton.LeftButton)
        self.assertEqual(
            self.tab.measurement_instruction.text(),
            "Placez le réticule sur le premier point, puis cliquez pour définir A.")
        self.assertTrue(self.tab.gap_button.isChecked())
        self.assertFalse(self.tab.interfringe_button.isChecked())
        self.assertEqual(self.tab.gap_button.property("role"), "primary")

        def aim_then_click(index, vertical_fraction):
            curve = QPointF(float(samples.axis[index]), float(samples.intensity[index]))
            scene = self.tab.profile_view_box.mapViewToScene(curve)
            bounds = self.tab.profile_view_box.sceneBoundingRect()
            scene.setY(bounds.top() + vertical_fraction * bounds.height())
            viewport = self.tab.plot.mapFromScene(scene)
            QTest.mouseMove(self.tab.plot.viewport(), viewport)
            self.app.processEvents()
            followed = self.tab.tracked_reticle_sample
            self.assertIsNotNone(followed)
            QTest.mouseClick(self.tab.plot.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, viewport)
            self.app.processEvents()
            return followed

        first_identifier, first_index = aim_then_click(12, .08)
        self.assertEqual(self.tab.measurement.first.profile_identifier, first_identifier)
        self.assertAlmostEqual(
            self.tab.measurement.first.fraction, first_index / (len(samples.axis) - 1))
        self.assertEqual(
            self.tab.measurement_instruction.text(),
            "Point A placé. Choisissez le second point, puis cliquez pour définir B.")
        self.assertEqual(self.tab.delete_marker_button.text(), "Supprimer A")

        # Un clic sur la ligne/poignée A reste réservé à ce repère et ne place pas B.
        first_x, _ = fraction_value(samples, self.tab.measurement.first.fraction)
        marker_scene = self.tab.profile_view_box.mapViewToScene(QPointF(first_x, 128))
        marker_viewport = self.tab.plot.mapFromScene(marker_scene)
        QTest.mouseMove(self.tab.plot.viewport(), marker_viewport)
        QTest.mouseClick(self.tab.plot.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, marker_viewport)
        self.app.processEvents()
        self.assertIsNone(self.tab.measurement.second)

        second_identifier, second_index = aim_then_click(52, .92)
        self.assertEqual(self.tab.measurement.second.profile_identifier, second_identifier)
        self.assertAlmostEqual(
            self.tab.measurement.second.fraction, second_index / (len(samples.axis) - 1))
        self.assertIn("Mesure terminée", self.tab.measurement_instruction.text())
        self.assertEqual(self.tab.delete_marker_button.text(), "Supprimer B")

        saved = (self.tab.measurement.first, self.tab.measurement.second)
        self.tab.intervals_spin.setValue(4)
        QTest.mouseClick(self.tab.interfringe_button, Qt.MouseButton.LeftButton)
        self.assertEqual((self.tab.measurement.first, self.tab.measurement.second), saved)
        self.assertFalse(self.tab.gap_button.isChecked())
        self.assertTrue(self.tab.interfringe_button.isChecked())
        self.assertNotEqual(self.tab.gap_button.property("role"), "primary")
        self.assertEqual(self.tab.interfringe_button.property("role"), "primary")
        self.assertIn("N = 4", self.tab.measurement_instruction.text())
        self.assertIn("franges de même nature", self.tab.measurement_instruction.text())
        self.assertIn("N = 4", self.tab.measurement_label.text())

        QTest.mouseClick(self.tab.delete_marker_button, Qt.MouseButton.LeftButton)
        self.assertIsNone(self.tab.measurement.second)
        self.assertEqual(self.tab.delete_marker_button.text(), "Supprimer A")
        self.tab.select_measurement_point(None)
        self.assertEqual(self.tab.delete_marker_button.text(), "Supprimer un repère")

    def test_measurement_refuses_an_ambiguous_unselected_profile(self):
        first = self.tab.active_profile()
        self.tab.add_profile(QPointF(*first.start), QPointF(*first.end))
        samples = self.tab.samples[first.identifier]
        self.tab.active_identifier = None
        self.tab.start_measurement("gap")
        point = QPointF(float(samples.axis[20]), float(samples.intensity[20]))
        scene = self.tab.profile_view_box.mapViewToScene(point)
        self.tab.track_plot_cursor(scene)
        self.assertIsNone(self.tab.tracked_reticle_sample)
        self.tab.measurement_click()
        self.assertIsNone(self.tab.measurement.first)
        self.assertIn("réticule", self.tab.status.text())

    def test_all_show_fits_every_visible_profile(self):
        self.tab.add_profile(QPointF(10, 30), QPointF(75, 30))
        self.tab.plot.setRange(xRange=(20, 25), yRange=(80, 90), padding=0)
        QTest.mouseClick(self.tab.fit_plot_button, Qt.MouseButton.LeftButton)
        x_range, y_range = self.tab.plot.plotItem.vb.viewRange()
        for profile in self.tab.profiles:
            samples = self.tab.samples[profile.identifier]
            self.assertLessEqual(x_range[0], float(np.min(samples.axis)))
            self.assertGreaterEqual(x_range[1], float(np.max(samples.axis)))
            self.assertLessEqual(y_range[0], float(np.min(samples.intensity)))
            self.assertGreaterEqual(y_range[1], float(np.max(samples.intensity)))

    def test_canvas_interaction_preserves_graph_measurement(self):
        profile = self.tab.active_profile()
        QTest.mouseClick(self.tab.gap_button, Qt.MouseButton.LeftButton)
        self._click_profile_sample(profile, 10)
        self._click_profile_sample(profile, 40)
        before = measurement_result(self.tab.measurement, self.tab.samples)
        first_fraction = self.tab.measurement.first.fraction
        second_fraction = self.tab.measurement.second.fraction
        midpoint = ((profile.start[0] + profile.end[0]) / 2,
                    (profile.start[1] + profile.end[1]) / 2)
        self._drag_canvas(midpoint, (midpoint[0], midpoint[1] + 5))
        after = measurement_result(self.tab.measurement, self.tab.samples)
        self.assertEqual(self.tab.measurement.first.fraction, first_fraction)
        self.assertEqual(self.tab.measurement.second.fraction, second_fraction)
        self.assertTrue(np.allclose(before[:3], after[:3]))

    def test_spectral_calibration_profiles_share_the_global_image_axis(self):
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(self.tab.calibration_mode.findData("spectral"))
        self.tab.distance_value.setValue(2.035)
        self.tab.distance_unit.setCurrentText("nm")
        self.tab.spectral_direction.setCurrentIndex(1)
        self.tab.calibration_reference_changed(QPointF(10, 5), QPointF(60, 25))
        self.tab.apply_calibration()
        first = self.tab.active_profile()
        self.tab.add_profile(QPointF(15, 30), QPointF(75, 30))
        second = self.tab.active_profile()
        self.assertEqual(len(self.tab.plot.plotItem.legend.items), 2)
        self.assertGreater(self.tab.samples[first.identifier].axis[0],
                           self.tab.samples[first.identifier].axis[-1])
        self.assertEqual(self.tab.calibration.axis_name, "Δλ")
        first_samples = self.tab.samples[first.identifier]
        second_samples = self.tab.samples[second.identifier]
        first_value = first_samples.axis[np.argmin(abs(first_samples.x - 30))]
        second_value = second_samples.axis[np.argmin(abs(second_samples.x - 30))]
        self.assertAlmostEqual(float(first_value), float(second_value), places=6)

    def test_scenario_a_interferences_full_profile_and_interfringe(self):
        image = QImage(330, 70, QImage.Format.Format_RGB32)
        for y in range(image.height()):
            for x in range(image.width()):
                level = int(128 + 100 * np.cos(2 * np.pi * x / 40))
                image.setPixelColor(x, y, QColor(level, level, level))
        self.tab.load_image(image, self._png(image), "interferences-synthetiques.png")
        self.tab.begin_calibration()
        self.tab.calibration_reference_changed(QPointF(10, 8), QPointF(300, 8))
        self._type_known_value("5")
        self.tab.distance_unit.setCurrentText("cm")
        self.tab.apply_calibration()
        self.tab.add_profile(QPointF(10, 35), QPointF(310, 35))
        profile = self.tab.active_profile()
        samples = self.tab.samples[profile.identifier]
        self.assertAlmostEqual(samples.axis[-1], 300 * 5 / 290, places=6)
        x_range, y_range = self.tab.plot.plotItem.vb.viewRange()
        self.assertLessEqual(x_range[0], float(np.min(samples.axis)))
        self.assertGreaterEqual(x_range[1], float(np.max(samples.axis)))
        self.assertLessEqual(y_range[0], float(np.min(samples.intensity)))
        self.assertGreaterEqual(y_range[1], float(np.max(samples.intensity)))
        self.assertGreaterEqual(y_range[0], 0)
        self.tab.snap_choice.setCurrentIndex(self.tab.snap_choice.findData("maximum"))
        self.tab.intervals_spin.setValue(5)
        QTest.mouseClick(self.tab.interfringe_button, Qt.MouseButton.LeftButton)
        first_index = int(np.argmin(abs(samples.x - 50)))
        second_index = int(np.argmin(abs(samples.x - 250)))
        self._click_profile_sample(profile, first_index)
        self._click_profile_sample(profile, second_index)
        self.assertIsNotNone(self.tab.measurement.first)
        self.assertIsNotNone(self.tab.measurement.second)
        first, second, total, average = measurement_result(
            self.tab.measurement, self.tab.samples)
        self.assertAlmostEqual(total, 200 * 5 / 290, places=2)
        self.assertAlmostEqual(average, 40 * 5 / 290, places=2)
        self.assertIn("N = 5", self.tab.measurement_label.text())
        self.assertEqual(self.tab.selected_measurement_point, "B")
        self._click_profile_sample(profile, first_index)
        self.assertEqual(self.tab.selected_measurement_point, "A")

        # Le changement de mode conserve les deux repères lorsqu'ils restent valides.
        self.tab.snap_choice.setCurrentIndex(self.tab.snap_choice.findData("manual"))
        previous_points = (self.tab.measurement.first, self.tab.measurement.second)
        QTest.mouseClick(self.tab.gap_button, Qt.MouseButton.LeftButton)
        self.assertEqual((self.tab.measurement.first, self.tab.measurement.second),
                         previous_points)
        self.assertEqual(self.tab.measurement.mode, "gap")

        # Effacer relance le placement ; deux clics identiques ne fabriquent pas
        # artificiellement une mesure nulle.
        QTest.mouseClick(self.tab.clear_measurement_button, Qt.MouseButton.LeftButton)
        self._click_profile_sample(profile, first_index)
        self._click_profile_sample(profile, first_index)
        self.assertIsNotNone(self.tab.measurement.first)
        self.assertIsNone(self.tab.measurement.second)
        self.assertEqual(self.tab.measure_mode, "gap")

    def test_scenario_b_relative_jupiter_comparison(self):
        image = QImage(220, 70, QImage.Format.Format_RGB32)
        for y in range(image.height()):
            shift = 0 if y < 35 else 4
            for x in range(image.width()):
                dip = 150 * np.exp(-((x - 90 - shift) / 4) ** 2)
                level = max(0, min(255, int(220 - dip)))
                image.setPixelColor(x, y, QColor(level, level, level))
        self.tab.load_image(image, self._png(image), "jupiter-synthetique.png")
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(self.tab.calibration_mode.findData("spectral"))
        self.tab.calibration_reference_changed(QPointF(50, 8), QPointF(150, 28))
        self._type_known_value("2,035")
        self.tab.distance_unit.setCurrentText("nm")
        self.tab.apply_calibration()
        self.tab.add_profile(QPointF(5, 20), QPointF(205, 20))
        first = self.tab.active_profile()
        self.tab.add_profile(QPointF(20, 50), QPointF(215, 50))
        second = self.tab.active_profile()
        self.assertEqual(self.tab.calibration.axis_name, "Δλ")
        self.assertEqual(len(self.tab.plot.plotItem.legend.items), 2)
        first_samples, second_samples = self.tab.samples[first.identifier], self.tab.samples[second.identifier]
        first_min = float(first_samples.axis[np.argmin(first_samples.intensity)])
        second_min = float(second_samples.axis[np.argmin(second_samples.intensity)])
        self.assertAlmostEqual(abs(second_min - first_min), 4 * 2.035 / 100, places=6)
        self.tab.snap_choice.setCurrentIndex(self.tab.snap_choice.findData("minimum"))
        QTest.mouseClick(self.tab.gap_button, Qt.MouseButton.LeftButton)
        self._click_profile_sample(first, int(np.argmin(first_samples.intensity)))
        self._click_profile_sample(second, int(np.argmin(second_samples.intensity)))
        self.assertEqual(self.tab.measurement.first.profile_identifier, first.identifier)
        self.assertEqual(self.tab.measurement.second.profile_identifier, second.identifier)
        _, _, measured_gap, _ = measurement_result(self.tab.measurement, self.tab.samples)
        self.assertAlmostEqual(measured_gap, 4 * 2.035 / 100, places=6)
        self.assertIn(first.name, self.tab.measurement_points_label.text())
        self.assertIn(second.name, self.tab.measurement_points_label.text())
        at_first = first_samples.axis[np.argmin(abs(first_samples.x - 50))]
        at_second = second_samples.axis[np.argmin(abs(second_samples.x - 150))]
        self.assertAlmostEqual(abs(float(at_second - at_first)), 2.035, places=6)
        x_range = self.tab.plot.plotItem.vb.viewRange()[0]
        for samples in (first_samples, second_samples):
            self.assertLessEqual(x_range[0], float(np.min(samples.axis)))
            self.assertGreaterEqual(x_range[1], float(np.max(samples.axis)))
        self.assertEqual(self.tab.selected_measurement_point, "B")
        self.tab.select_measurement_point("A")
        self.assertEqual(self.tab.selected_measurement_point, "A")
        QTest.mouseClick(self.tab.delete_marker_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.measurement.first.profile_identifier, second.identifier)
        self.assertIsNone(self.tab.measurement.second)
        self.assertEqual(self.tab.measure_mode, "gap")

    def test_transfer_uses_existing_data_and_graph_apis(self):
        columns = self.tab.transfer_active()[0]
        self.assertEqual(len(columns), 2)
        self.assertTrue(self.window.data_tab.model.names[columns[1]].startswith("I_Profil"))
        self.assertIs(self.window.tabs.currentWidget(), self.window.graph_tab)
        self.assertTrue(self.window.graph_tab.active_graph.series[0].connect_points.isChecked())
        default_graph = self.window.graph_tab.add_data_graph(*columns)
        self.assertFalse(default_graph.series[0].connect_points.isChecked())

    def test_visible_profiles_with_common_axis_share_one_graph(self):
        self.tab.add_profile(QPointF(5, 30), QPointF(70, 30))
        before = len(self.window.graph_tab.windows)
        columns = self.tab.transfer_visible()[0]
        self.assertEqual(len(columns), 3)
        self.assertEqual(len(self.window.graph_tab.windows), before + 1)
        self.assertEqual(len(self.window.graph_tab.active_graph.series), 2)
        self.assertTrue(all(series.connect_points.isChecked()
                            for series in self.window.graph_tab.active_graph.series))

    def test_repeated_transfer_survives_project_roundtrip(self):
        first = self.tab.transfer_active()[0]
        second = self.tab.transfer_active()[0]
        self.assertTrue(set(first).isdisjoint(second))
        names = list(self.window.data_tab.model.names)
        rows = [list(row) for row in self.window.data_tab.model.rows]

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "transferts.physalix"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
            self.assertTrue(self.window.save_project())
        restored = MainWindow()
        self.windows.append(restored)
        restore(restored, read_project(path), path)
        self.assertEqual(restored.data_tab.model.names, names)
        self.assertEqual(restored.data_tab.model.rows, rows)
        transferred = restored.graph_tab.windows[-2:]
        self.assertTrue(all(window.graph.series[0].connect_points.isChecked()
                            for window in transferred))

    def test_reference_layout_keeps_local_side_scroll(self):
        self.window.show()
        self.window.tabs.setCurrentWidget(self.tab)
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(
            self.tab.calibration_mode.findData("spectral"))
        self.tab.absolute_reference.setChecked(True)
        for width, height in ((1366, 768), (1600, 900), (1920, 1080)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.assertGreaterEqual(self.tab.canvas.height(), 220)
            self.assertGreaterEqual(self.tab.plot.height(), 120)
            self.assertEqual(self.tab.side_scroll.horizontalScrollBar().maximum(), 0)
            self.assertTrue(self.tab.absolute_value_label.isVisible())
            self.assertGreater(
                self.tab.absolute_value.mapTo(self.tab.spectral_options, QPoint()).y(),
                self.tab.absolute_value_label.mapTo(self.tab.spectral_options, QPoint()).y(),
            )
            self.assertGreaterEqual(
                self.tab.absolute_value_label.height(),
                self.tab.absolute_value_label.sizeHint().height(),
            )

    def test_project_roundtrip_embeds_image_and_state(self):
        self.tab.load_image(self.tab.image, self.tab.image_bytes, "spectre.png")
        self.tab.workflow.setCurrentIndex(1)
        QTest.mouseClick(self.tab.draw_button, Qt.MouseButton.LeftButton)
        self._draw_canvas_segment((5, 10), (70, 10))
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(self.tab.calibration_mode.findData("spectral"))
        self.tab.distance_value.setValue(2.035)
        self.tab.distance_unit.setCurrentText("nm")
        self.tab.calibration_reference_changed(QPointF(10, 4), QPointF(60, 20))
        self.tab.apply_calibration()
        profile = self.tab.active_profile()
        QTest.mouseClick(self.tab.gap_button, Qt.MouseButton.LeftButton)
        self._click_profile_sample(profile, 10)
        self._click_profile_sample(profile, 40)
        expected = measurement_result(self.tab.measurement, self.tab.samples)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "analyse.physalix"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
            self.assertTrue(self.window.save_project())
        import zipfile
        with zipfile.ZipFile(path) as archive:
            self.assertIn(IMAGE_ANALYSIS_ENTRY, archive.namelist())
        restored = MainWindow()
        self.windows.append(restored)
        restore(restored, read_project(path), path)
        restored_tab = restored.image_analysis_tab
        self.assertEqual(restored_tab.image_name, "spectre.png")
        self.assertEqual(len(restored_tab.profiles), 1)
        self.assertIsNotNone(restored_tab.measurement.first)
        self.assertIsNotNone(restored_tab.measurement.second)
        self.assertEqual(measurement_result(restored_tab.measurement, restored_tab.samples), expected)
        self.assertEqual(restored_tab.calibration.axis_name, "Δλ")
        self.assertFalse(restored_tab.calibration.absolute)
        self.assertFalse(restored_tab.image.isNull())

    def test_new_project_discards_previous_image_analysis_state(self):
        previous_tab = self.tab
        self.window._discard_on_close = True
        self.window.new_project()
        current = self.window.image_analysis_tab
        self.assertIsNot(current, previous_tab)
        self.assertTrue(current.image.isNull())
        self.assertEqual(current.profiles, [])
        self.assertEqual(current.calibration.mode, "none")
        self.assertIsNone(current.measurement.first)
        self.assertIsNone(current.measurement.second)

    def test_state_with_scientific_data_but_no_image_is_rejected(self):
        state = self.tab.snapshot_state()
        state["image"] = None
        restored = MainWindow()
        self.windows.append(restored)
        with self.assertRaisesRegex(ValueError, "sans image integree"):
            restored.image_analysis_tab.restore_state(state)

    def test_missing_or_altered_project_image_is_rejected(self):
        state = snapshot(self.window)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "image-invalide.physalix"
        restored = MainWindow()
        self.windows.append(restored)

        write_project(path, state)
        with self.assertRaisesRegex(ValueError, "manquante"):
            restore(restored, read_project(path), path)

        write_project(path, state, image_asset=b"not the saved image")
        with self.assertRaisesRegex(ValueError, "invalide ou alteree"):
            restore(restored, read_project(path), path)

    def test_two_point_and_horizontal_preferences_survive_project_roundtrip(self):
        self.tab.profile_horizontal.setChecked(True)
        self.tab.begin_calibration()
        self.tab.calibration_mode.setCurrentIndex(
            self.tab.calibration_mode.findData("spectral"))
        self.tab.spectral_method.setCurrentIndex(
            self.tab.spectral_method.findData("two_points"))
        self.tab.spectral_points = [(20, 8), (60, 25)]
        self.tab.calibration_reference = tuple(self.tab.spectral_points)
        self.tab.first_wavelength.setValue(592.136)
        self.tab.second_wavelength.setValue(590.101)
        self.tab.apply_calibration()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "deux-references.physalix"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
            self.assertTrue(self.window.save_project())
        restored = MainWindow()
        self.windows.append(restored)
        restore(restored, read_project(path), path)
        restored_tab = restored.image_analysis_tab
        self.assertEqual(restored_tab.calibration.spectral_method, "two_points")
        self.assertEqual(restored_tab.calibration.first_value, 592.136)
        self.assertEqual(restored_tab.calibration.second_value, 590.101)
        self.assertEqual(restored_tab.spectral_points, [[20, 8], [60, 25]])
        self.assertTrue(restored_tab.profiles[0].horizontal)
        self.assertTrue(restored_tab.profile_horizontal_default)

    def test_state_without_new_calibration_preferences_remains_compatible(self):
        state = self.tab.snapshot_state()
        for key in ("spectral_method", "calibration_horizontal", "profile_horizontal_default"):
            state.pop(key)
        for key in ("spectral_method", "reference_endpoint", "horizontal"):
            state["calibration"].pop(key)
        for profile in state["profiles"]:
            profile.pop("horizontal")
        restored = MainWindow()
        self.windows.append(restored)
        restored.image_analysis_tab.restore_state(state, self.tab.image_bytes)
        self.assertEqual(restored.image_analysis_tab.calibration.spectral_method, "known_gap")
        self.assertFalse(restored.image_analysis_tab.profiles[0].horizontal)

    def test_legacy_marker_state_is_loaded_with_explicit_migration(self):
        state = self.tab.snapshot_state()
        state["version"] = 1
        state.pop("measurement")
        state["profiles"][0]["markers"] = [
            {"fraction": 0.5, "kind": "minimum", "order": 18},
        ]
        restored = MainWindow()
        self.windows.append(restored)
        restored_tab = restored.image_analysis_tab
        restored_tab.restore_state(state, self.tab.image_bytes)
        self.assertIsNone(restored_tab.measurement.first)
        self.assertIsNone(restored_tab.measurement.second)
        self.assertIn("anciens curseurs", restored_tab.status.text())


if __name__ == "__main__":
    unittest.main()
