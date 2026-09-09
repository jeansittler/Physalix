"""Vérifier les couples, les choix d'axes et les limites visibles."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QColor, QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from physalix.ui.main_window import MainWindow
from physalix.ui.graph_tab import paired_values


class GraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.window.tabs.setCurrentIndex(1)
        self.graph = self.window.graph_tab
        self.model = self.window.data_tab.model
        self.app.processEvents()

    def tearDown(self):
        self.window._discard_on_close = True
        self.window.close()
        self.app.processEvents()

    def test_missing_values_do_not_shift_pairs(self):
        self.assertEqual(
            paired_values([["0", "7,2"], ["1", ""], ["", "9"],
                           ["2", "1e1"], ["", ""], ["NaN", "3"]], 0, 1),
            ([0.0, 2.0], [7.2, 10.0], 3),
        )

    def test_legend_avoids_points_and_preserves_manual_placement(self):
        graph = self.graph
        self.model.rows = [[str(x), str(y)] for x in (1, 2, 3, 4) for y in (8, 8.5, 9)]
        graph.refresh_plot()
        graph.plot.setRange(xRange=(0, 10), yRange=(0, 10), padding=0)
        self.app.processEvents()
        legend = graph.legend
        legend.place()
        view = graph.plot.getViewBox()
        area = legend.mapRectToParent(legend.boundingRect()).adjusted(-7, -7, 7, 7)
        for row in self.model.rows:
            point = view.mapFromView(QPointF(*map(float, row)))
            self.assertFalse(area.contains(point))
        # Simuler un déplacement manuel puis une reconstruction de la légende.
        from PySide6.QtCore import Qt
        class Drag:
            def button(self): return Qt.MouseButton.LeftButton
            def accept(self): pass
            def pos(self): return QPointF(50, 80)
            def lastPos(self): return QPointF(0, 0)
        legend.mouseDragEvent(Drag())
        position = legend.pos()
        right_gap = view.width()-position.x()
        graph.update_legend()
        graph.zoom_by(0.5)
        self.app.processEvents()
        self.assertTrue(legend.manual)
        self.assertAlmostEqual(view.width()-legend.pos().x(), right_gap, delta=1)
        self.assertEqual(legend.pos().y(), position.y())
        legend.reset_placement()
        self.app.processEvents()
        self.assertFalse(legend.manual)

    def test_axis_titles_and_arrows_stay_at_visible_ends(self):
        graph = self.graph
        bottom, left = graph.plot.getAxis('bottom'), graph.plot.getAxis('left')
        for size, ranges in (((1000, 680), ((0, 1), (0, 1))),
                             ((740, 520), ((-500, -200), (100, 1000))),
                             ((1100, 800), ((2, 2.01), (-0.001, 0.001)))):
            self.window.resize(*size)
            graph.plot.setRange(xRange=ranges[0], yRange=ranges[1], padding=0)
            self.app.processEvents()
            for axis in (bottom, left):
                self.assertEqual(axis.label.rotation(), 0)
                self.assertTrue(axis.arrow.isVisible())
                tip = axis.arrow.path().elementAt(1)
                self.assertAlmostEqual(tip.x, axis.size().width()-1)
                self.assertEqual(tip.y, 0)
            self.assertAlmostEqual(bottom.label.pos().x()+bottom.label.boundingRect().width(),
                                   bottom.size().width())
            self.assertLess(left.label.pos().y()+left.label.boundingRect().height(), 0)
            self.assertGreater(bottom.arrow.path().elementAt(1).x, bottom.arrow.path().elementAt(0).x)
            self.assertLess(left.arrow.path().elementAt(1).y, left.arrow.path().elementAt(0).y)

    def test_six_columns_and_preserved_choices(self):
        for _ in range(4):
            self.model.add_quantity()
        self.app.processEvents()
        self.assertEqual(self.graph.series[0].x_choice.count(), 6)
        self.graph.series[0].x_choice.setCurrentIndex(4)
        self.graph.series[0].y_choice.setCurrentIndex(5)
        for column, name, unit in ((4, "Volume", "mL"), (5, "pH", "Sans unité")):
            self.model.setData(self.model.index(0, column), name)
            self.model.setData(self.model.index(1, column), unit)
        self.model.setData(self.model.index(2, 4), "10")
        self.model.setData(self.model.index(2, 5), "7,2")
        self.app.processEvents()
        self.assertEqual(self.graph.series[0].x_choice.currentData(), 4)
        self.assertEqual(self.graph.series[0].y_choice.currentData(), 5)
        self.assertEqual(self.graph.plot.getAxis("bottom").labelText, "Volume (mL)")
        self.assertEqual(self.graph.plot.getAxis("left").labelText, "pH")
        xs, ys = self.graph.series[0].points.getData()
        self.assertEqual(list(xs), [10.0])
        self.assertEqual(list(ys), [7.2])
        self.graph.series[0].x_choice.setCurrentIndex(5)
        self.graph.series[0].y_choice.setCurrentIndex(4)
        xs, ys = self.graph.series[0].points.getData()
        self.assertEqual((list(xs), list(ys)), ([7.2], [10.0]))

    def test_connection_order_color_and_style_per_pair(self):
        self.model.rows = [["2", "4"], ["0", "1"], ["1", "3"]]
        self.graph.refresh_plot()
        self.assertFalse(self.graph.series[0].line.isVisible())
        self.graph.series[0].connect_points.setChecked(True)
        self.graph.series[0].set_curve_color(QColor("#b72244"))
        self.assertTrue(self.graph.series[0].line.isVisible())
        xs, ys = self.graph.series[0].line.getData()
        self.assertEqual(list(xs), [2, 0, 1])
        self.assertEqual(list(ys), [4, 1, 3])
        self.assertEqual(self.graph.series[0].line.opts['pen'].color().name(), '#b72244')
        self.assertEqual(self.graph.series[0].points.opts['pen'].color().name(), '#b72244')
        self.graph.series[0].x_choice.setCurrentIndex(1)
        self.assertFalse(self.graph.series[0].connect_points.isChecked())
        self.graph.series[0].x_choice.setCurrentIndex(0)
        self.assertTrue(self.graph.series[0].connect_points.isChecked())
        self.assertEqual(self.graph.series[0].color.name(), '#b72244')

    def test_multiple_series_independent_styles_and_bounds(self):
        self.model.add_quantity()
        self.model.names = ["Temps", "Position", "Vitesse"]
        self.model.rows = [["0", "1", "100"], ["1", "2", "200"], ["2", "", "300"]]
        self.graph.sync_columns()
        first = self.graph.series[0]
        second = self.graph.add_series()
        self.assertEqual(second.key(), (0, 2))
        first.connect_points.setChecked(True)
        first.set_curve_color(QColor('#ff0000'))
        second.set_curve_color(QColor('#008800'))
        self.assertFalse(second.line.isVisible())
        self.assertTrue(first.line.isVisible())
        self.assertEqual(first.points.opts['pen'].color().name(), '#ff0000')
        self.assertEqual(second.points.opts['pen'].color().name(), '#008800')
        self.assertEqual(len(first.points.data), 2)
        self.assertEqual(len(second.points.data), 3)
        self.app.processEvents()
        self.assertGreater(self.graph.plot.viewRange()[1][1], 300)
        self.assertEqual(len(self.graph.legend.items), 2)
        second.visible.setChecked(False)
        self.app.processEvents()
        self.assertLess(self.graph.plot.viewRange()[1][1], 10)
        self.assertFalse(second.points.isVisible())
        self.assertEqual(len(self.graph.legend.items), 1)
        second.visible.setChecked(True)
        self.assertEqual(second.color.name(), '#008800')
        self.graph.remove_series(second)
        self.assertEqual(len(self.graph.series), 1)
        self.assertNotIn(second.points, self.graph.plot.getPlotItem().items)
        self.assertEqual(self.model.rows[2][2], '300')
        self.assertFalse(first.remove_button.isEnabled())

    def test_multiple_abscissas_renaming_and_updates(self):
        for _ in range(4):
            self.model.add_quantity()
        self.model.rows = [["0", "1", "2", "3", "4", "5"]]
        self.graph.sync_columns()
        second = self.graph.add_series()
        second.x_choice.setCurrentIndex(4)
        second.y_choice.setCurrentIndex(5)
        for _ in range(4):
            self.graph.add_series()
        self.model.setData(self.model.index(0, 4), 'Volume')
        self.model.setData(self.model.index(1, 4), 'mL')
        self.model.setData(self.model.index(2, 5), '7,5')
        self.app.processEvents()
        self.assertEqual(second.key(), (4, 5))
        self.assertIn('Volume (mL)', second.x_choice.currentText())
        xs, ys = second.points.getData()
        self.assertEqual((list(xs), list(ys)), ([4], [7.5]))
        self.assertEqual(len(self.graph.legend.items), 6)
        for item in self.graph.series:
            item.visible.setChecked(False)
        self.assertEqual(self.graph.plot.viewRange(), [[0, 1], [0, 1]])
        self.assertEqual(len(self.graph.legend.items), 0)

    def test_series_selector_preserves_plot_space_zoom_and_settings(self):
        graph = self.graph
        self.window.resize(1000, 700)
        self.model.rows = [["0", "1"], ["1", "2"]]
        graph.refresh_plot()
        self.app.processEvents()
        height = graph.plot.height()
        first = graph.series[0]
        first.connect_points.setChecked(True)
        for _ in range(8):
            last = graph.add_series()
        self.app.processEvents()
        self.assertEqual(graph.plot.height(), height)
        self.assertEqual(graph.series_stack.currentWidget(), last)
        self.assertEqual(graph.series_choice.currentIndex(), 8)
        graph.plot.setRange(xRange=(0.2, 0.8), yRange=(1.2, 1.8), padding=0)
        self.app.processEvents()
        zoom = graph.plot.viewRange()
        graph.series_choice.setCurrentIndex(0)
        self.app.processEvents()
        self.assertEqual(graph.plot.viewRange(), zoom)
        self.assertEqual(graph.series_stack.currentWidget(), first)
        self.assertTrue(first.connect_points.isChecked())
        self.assertTrue(all(item.points.isVisible() for item in graph.series))
        graph.settings_button.click()
        self.app.processEvents()
        self.assertFalse(graph.series_stack.isVisible())
        self.assertGreater(graph.plot.height(), height)
        graph.settings_button.click()
        self.app.processEvents()
        self.assertEqual(graph.plot.height(), height)
        first.visible.setChecked(False)
        self.assertIn("masquée", graph.series_choice.itemText(0))
        graph.remove_series(first)
        self.assertEqual(graph.series_choice.count(), 8)
        self.assertEqual(graph.series_stack.currentWidget(), graph.series[graph.series_choice.currentIndex()])
        self.assertTrue(all(item.points.isVisible() for item in graph.series))

    def test_context_menu_zoom_and_reticle_without_click(self):
        graph = self.graph
        view = graph.plot.getViewBox()
        viewport = graph.plot.viewport()
        point = graph.plot.mapFromScene(view.sceneBoundingRect().center())
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point,
                                  viewport.mapToGlobal(point))
        QApplication.sendEvent(viewport, event)
        self.assertTrue(graph.context_menu.isVisible())
        self.assertIn('Zoom par rectangle', [a.text() for a in graph.context_menu.actions()])
        graph.context_menu.hide()
        before = graph.plot.viewRange()[0]
        next(a for a in graph.context_menu.actions() if a.text() == 'Zoom avant').trigger()
        after = graph.plot.viewRange()[0]
        self.assertAlmostEqual(after[1] - after[0], (before[1] - before[0]) / 2)
        graph.reticle_action.setChecked(True)
        QTest.mouseMove(viewport, point)
        QTest.qWait(30)
        self.assertTrue(graph.cross_x.isVisible())
        expected = view.mapSceneToView(graph.plot.mapToScene(point))
        self.assertAlmostEqual(graph.cross_x.value(), expected.x())
        self.assertAlmostEqual(graph.cross_y.value(), expected.y())
        self.assertIn('X —', graph.coordinates.text())
        # Les réticules ne doivent pas changer le cadrage automatique.
        graph.track_cursor(view.mapViewToScene(QPointF(0.6, 0.7)))
        graph.fit_points()
        self.assertEqual(graph.plot.viewRange(), [[0, 1], [0, 1]])
        QApplication.sendEvent(viewport, QEvent(QEvent.Type.Leave))
        self.assertFalse(graph.cross_x.isVisible())
        graph.reticle_action.setChecked(False)
        self.assertIn('désactivé', graph.coordinates.text())

    def test_fit_constant_and_spread_data_then_clear(self):
        for samples in ([(0, 0)], [(2, 7), (2, 7)], [(-100, -50), (400, 800)]):
            self.model.rows = [[str(x), str(y)] for x, y in samples] + [["", ""]]
            self.graph.refresh_plot()
            self.app.processEvents()
            bounds = self.graph.plot.viewRange()
            for dimension in range(2):
                low, high = bounds[dimension]
                self.assertLess(low, min(p[dimension] for p in samples))
                self.assertGreater(high, max(p[dimension] for p in samples))
        self.model.rows = [["", ""]]
        self.graph.refresh_plot()
        self.assertEqual(len(self.graph.series[0].points.data), 0)
        self.assertIn("Aucun point", self.graph.status.text())


if __name__ == "__main__":
    unittest.main()
