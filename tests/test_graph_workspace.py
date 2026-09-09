"""Comparaison des graphiques et indépendance des deux échelles verticales."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from physalix.ui.main_window import MainWindow
from physalix.fitting import fit_model


class GraphWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.resize(1200, 820)
        self.window.show()
        self.workspace = self.window.graph_tab
        self.window.tabs.setCurrentWidget(self.workspace)
        self.model = self.window.data_tab.model
        self.model.add_quantity()
        self.model.names = ['Temps', 'Tension', 'Courant']
        self.model.units = ['s', 'V', 'mA']
        self.model.rows = [['0','1','1000'], ['1','2','2000'], ['2','3','3000']]
        self.workspace.sync_columns()
        self.app.processEvents()

    def tearDown(self):
        self.window._discard_on_close = True
        self.window.close()
        self.app.processEvents()

    def test_independent_graphs_arrangements_and_modeling(self):
        first = self.workspace.active_graph
        first.plot.setRange(xRange=(0, 1), yRange=(1, 2), padding=0)
        second = self.workspace.add_graph()
        second.series[0].y_choice.setCurrentIndex(2)
        self.assertEqual(first.series[0].key(), (0, 1))
        self.assertEqual(second.series[0].key(), (0, 2))
        self.assertIs(self.window.modeling_tab.currentWidget().graph, second)
        for arrangement in (1, 2, 3, 0):
            self.workspace.arrangement.setCurrentIndex(arrangement)
            self.app.processEvents()
            self.assertEqual(first.series[0].key(), (0,1))
            self.assertEqual(second.series[0].key(), (0,2))
        self.workspace.edit_graph(first)
        self.assertIs(self.workspace.active_graph, first)
        self.assertIs(self.window.modeling_tab.currentWidget().graph, first)
        first.set_model(first.series[0], fit_model([0,1,2], [1,2,3], 'affine'), 'affine')
        self.assertEqual(len(second.series[0].fits), 0)
        self.model.setData(self.model.index(2, 1), '4')
        self.app.processEvents()
        self.assertEqual(list(first.series[0].points.getData()[1]), [4,2,3])
        self.assertEqual(list(second.series[0].points.getData()[1]), [1000,2000,3000])
        next(w for w in self.workspace.windows if w.graph is second).close()
        self.app.processEvents()
        self.assertEqual(len(self.workspace.windows), 1)
        self.assertNotIn(second, self.window.modeling_tab.pages)
        self.workspace.windows[0].close()
        self.assertEqual(len(self.workspace.windows), 1)

    def test_right_axis_bounds_models_and_return_to_left(self):
        graph = self.workspace.active_graph
        right = graph.add_series()
        right.y_axis.setCurrentIndex(1)
        self.app.processEvents()
        self.assertTrue(graph.plot.getAxis('right').isVisible())
        self.assertLess(graph.plot.viewRange()[1][1], 10)
        self.assertGreater(graph.right_view.viewRange()[1][1], 3000)
        self.assertIs(right.points.getViewBox(), graph.right_view)
        self.assertEqual(graph.plot.viewRange()[0], graph.right_view.viewRange()[0])
        fit = graph.set_model(right, fit_model([0,1,2], [1000,2000,3000], 'affine'), 'affine')
        self.assertIs(fit.curve.getViewBox(), graph.right_view)
        graph.curve_guides_tool.open_tool('tangent')
        graph.curve_guides_tool.source.setCurrentIndex(1)
        self.assertIs(graph.curve_guides_tool.tangent.getViewBox(), graph.right_view)
        self.assertAlmostEqual(graph.curve_guides_tool.tangent_result[2], 1000)
        right.y_axis.setCurrentIndex(0)
        self.app.processEvents()
        self.assertFalse(graph.plot.getAxis('right').isVisible())
        self.assertIs(right.points.getViewBox(), graph.plot.getViewBox())
        self.assertGreater(graph.plot.viewRange()[1][1], 3000)
        graph.remove_series(right)
        self.assertNotIn(right.points, graph.plot.getPlotItem().items)

    def test_conductimetry_uses_right_coordinates(self):
        graph = self.workspace.active_graph
        self.model.rows = [[str(x), str(x*.01), str((30-2*x if x<=10 else x)*1000)] for x in range(21)]
        graph.sync_columns()
        right = graph.add_series()
        right.y_axis.setCurrentIndex(1)
        tool = graph.conductimetry_tool
        tool.open_tool()
        self.assertAlmostEqual(tool.result.volume, 10)
        self.assertAlmostEqual(tool.result.ordinate, 10000)
        self.assertIs(tool.lines[0].getViewBox(), graph.right_view)
        low = graph.right_view.viewRange()[1][0]
        self.assertAlmostEqual(tool.projection.getData()[1][0], low)
        left_range = graph.plot.viewRange()[1][:]
        graph.right_view.setYRange(5000,35000,padding=0)
        self.assertEqual(graph.plot.viewRange()[1], left_range)
        self.assertAlmostEqual(tool.projection.getData()[1][0], 5000)
