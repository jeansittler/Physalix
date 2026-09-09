"""Tangente locale, paliers garantis et gestes des guides du graphique."""
import os
import unittest
import numpy as np
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication
from physalix.curve_guides import curve_interpolator, tangent_at, model_plateau
from physalix.ui.main_window import MainWindow
from physalix.fitting import fit_model


class CurveGuidesMathTests(unittest.TestCase):
    def test_tangent_to_affine_and_endpoint(self):
        curve = curve_interpolator([3, 0, 1, 2], [7, 1, 3, 5])
        self.assertEqual(tangent_at(curve, 0), (1, 2))
        self.assertEqual(tangent_at(curve, 1.5), (4, 2))
        with self.assertRaises(ValueError):
            tangent_at(curve, -1)
        with self.assertRaises(ValueError):
            curve_interpolator([1, 1, 2], [0, 1, 2])

    def test_charge_and_discharge_limits(self):
        self.assertEqual(model_plateau('charge', {'A': 5, 'c': 1, 'tau': 2}), 6)
        self.assertEqual(model_plateau('discharge', {'A': 5, 'c': 1, 'tau': 2}), 1)
        self.assertEqual(model_plateau('exponential', {'c': 3, 'k': -2}), 3)
        self.assertIsNone(model_plateau('exponential', {'c': 3, 'k': 2}))
        self.assertIsNone(model_plateau('charge', {'A': 5, 'c': 1, 'tau': -2}))
        self.assertIsNone(model_plateau('affine', {'a': 2, 'b': 1}))


class CurveGuidesUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.graph = self.window.graph_tab
        self.window.tabs.setCurrentWidget(self.graph)
        self.model = self.window.data_tab.model
        self.model.units = ['s', 'V']
        self.model.rows = [[str(x), str(2*x+1)] for x in range(6)]
        self.graph.sync_columns()
        self.tool = self.graph.curve_guides_tool
        self.app.processEvents()

    def tearDown(self):
        self.window._discard_on_close = True
        self.window.close()
        self.app.processEvents()

    def test_click_tangent_and_horizontal_line_together(self):
        self.tool.open_tool('tangent')
        self.assertEqual(self.tool.tangent_result, (0, 1, 2))
        self.assertTrue(self.tool.pick.isChecked())
        self.app.processEvents()
        view = self.graph.plot.getViewBox()
        accepted = []
        event = SimpleNamespace(button=lambda: Qt.MouseButton.LeftButton,
                                scenePos=lambda: view.mapViewToScene(QPointF(2, 5)),
                                accept=lambda: accepted.append(True))
        self.tool.scene_clicked(event)
        self.assertEqual(accepted, [True])
        self.assertAlmostEqual(self.tool.x.value(), 2)
        self.assertFalse(self.tool.pick.isChecked())
        self.tool.open_tool('asymptote')
        self.assertTrue(self.tool.tangent.isVisible())
        self.assertTrue(self.tool.asymptote.isVisible())
        self.assertIn('Palier manuel', self.tool.hint.text())
        self.tool.asymptote.setValue(9)
        self.assertEqual(self.tool.level.value(), 9)
        self.assertIn('y = 9 V', self.tool.readout.text())
        before = self.graph.plot.viewRange()
        self.tool.level.setValue(100)
        self.assertEqual(self.graph.plot.viewRange(), before)
        self.tool.close_tool()
        self.assertTrue(all(not i.isVisible() for i in self.tool.items))

    def test_invalid_abscissa_and_new_data(self):
        self.tool.open_tool('tangent')
        self.tool.x.setValue(100)
        self.assertIsNone(self.tool.tangent_result)
        self.assertFalse(self.tool.tangent.isVisible())
        self.tool.x.setValue(1)
        self.model.setData(self.model.index(3, 1), '4')
        self.app.processEvents()
        self.assertEqual(self.tool.tangent_result[1], 4)
        self.graph.series[0].visible.setChecked(False)
        self.assertTrue(all(not i.isVisible() for i in self.tool.items))

    def test_model_plateau_and_exclusive_other_tools(self):
        xs = np.linspace(0, 8, 20)
        ys = 1 + 5*(1-np.exp(-xs/2))
        self.model.rows = [[str(x), str(y)] for x,y in zip(xs,ys)]
        self.graph.refresh_plot()
        result = fit_model(xs, ys, 'charge')
        fit = self.graph.set_model(self.graph.series[0], result, 'charge')
        self.tool.open_tool('asymptote')
        self.tool.source.setCurrentIndex(1)
        self.assertTrue(self.tool.plateau_button.isEnabled())
        self.tool.plateau_button.click()
        self.assertAlmostEqual(self.tool.level.value(), 6, places=5)
        self.assertTrue(self.tool.plateau_linked)
        self.tool.open_tool('tangent')
        self.assertAlmostEqual(self.tool.tangent_result[2], 2.5, places=3)
        self.graph.clear_model(self.graph.series[0], fit)
        self.assertFalse(self.tool.asymptote.isVisible())
        self.tool.source.setCurrentIndex(0)
        self.graph.conductimetry_tool.open_tool()
        self.assertFalse(self.tool.active)
