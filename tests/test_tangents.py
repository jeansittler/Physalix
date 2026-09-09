import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import numpy as np
from physalix.tangents import parallel_tangents
from PySide6.QtWidgets import QApplication
from physalix.ui.main_window import MainWindow

class TangentsTests(unittest.TestCase):
    def test_symmetry_and_true_parallel_contacts(self):
        x = np.linspace(0, 20, 81)
        for direction in (1, -1):
            y = 7 + direction*5*np.tanh((x-10)/1.5)
            for fraction in (.1, .25, .6):
                r = parallel_tangents(x[::-1], y[::-1], fraction)
                self.assertAlmostEqual(r.volume, 10, places=8)
                for contact in r.contacts:
                    self.assertAlmostEqual(float(r.curve.derivative()(contact)), r.slope, places=8)
                self.assertAlmostEqual(r.ph, r.slope*r.volume+np.mean(r.intercepts), places=8)

    def test_invalid_curves(self):
        for x, y in [(np.arange(5), np.arange(5)), (np.arange(10), np.ones(10)),
                     (np.arange(10), np.arange(10)), ([0,1,2,3,4,5,5], [1,2,3,4,5,6,7])]:
            with self.assertRaises(ValueError):
                parallel_tangents(x, y)

    def test_interval_selects_one_jump(self):
        x = np.linspace(0, 30, 151)
        y = 4 + 2*np.tanh(x-8) + 3*np.tanh(x-22)
        self.assertAlmostEqual(parallel_tangents(x,y,interval=(16,28)).volume, 22, places=5)

    def test_ui_updates_and_perpendicular_in_pixels(self):
        app = QApplication.instance() or QApplication([])
        from physalix.ui.theme import apply_theme
        apply_theme(app)
        window = MainWindow()
        window.resize(1100, 800)
        window.show()
        window.tabs.setCurrentIndex(1)
        graph = window.graph_tab
        model = window.data_tab.model
        model.names[:2] = ['V', 'pH']
        model.units[:2] = ['mL', 'Sans unité']
        x = np.linspace(0,20,81)
        model.rows = [[str(v), str(7+5*np.tanh((v-10)/1.5))] for v in x]
        graph.refresh_plot()
        tool = graph.tangent_tool
        tool.open_tool()
        app.processEvents()
        self.assertAlmostEqual(tool.result.volume,10)
        self.assertIn('mL', tool.readout.text())
        tool.slope.setValue(40)
        graph.plot.setRange(xRange=(2,18),yRange=(0,14),padding=0)
        app.processEvents()
        dx, dy = graph.plot.getViewBox().viewPixelSize()
        nx, ny = tool.normal.getData()
        dot = (nx[1]-nx[0])/dx + tool.result.slope*dx/dy*(ny[1]-ny[0])/dy
        self.assertAlmostEqual(dot,0,places=6)
        window.grab().save('artifacts/tangents-review.png')
        model.rows = [['0','7'],['1','8']]
        graph.refresh_plot()
        self.assertIsNone(tool.result)
        self.assertFalse(tool.label.isVisible())
        tool.close_tool()
        self.assertFalse(tool.region.isVisible())
        window._discard_on_close = True
        window.close()
        app.processEvents()
