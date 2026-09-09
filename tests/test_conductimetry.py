"""Régressions conductimétriques et réglage des deux zones du graphique."""
import os
import unittest
import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from physalix.conductimetry import fit_equivalence
from physalix.ui.main_window import MainWindow


class ConductimetryMathTests(unittest.TestCase):
    def test_exact_intersection_and_unsorted_values(self):
        x = np.arange(21.)
        y = np.where(x <= 10, 30 - 2*x, x)
        result = fit_equivalence(x[::-1], y[::-1], (0, 7), (13, 20))
        self.assertAlmostEqual(result.volume, 10)
        self.assertAlmostEqual(result.ordinate, 10)
        self.assertEqual([b.count for b in result.branches], [8, 8])
        self.assertAlmostEqual(result.branches[0].slope, -2)
        self.assertAlmostEqual(result.branches[1].slope, 1)
        self.assertEqual(result.branches[0].r2, 1)
        self.assertEqual(result.warning, '')

    def test_two_increasing_branches_and_large_offset(self):
        x = np.arange(21.)
        y = np.where(x <= 10, x + 5, 3*x - 15)
        result = fit_equivalence(x + 1e9, y, (1e9, 1e9+7), (1e9+13, 1e9+20))
        self.assertAlmostEqual(result.volume, 1e9+10)
        self.assertAlmostEqual(result.ordinate, 15)

    def test_invalid_regions_parallel_and_duplicate_volumes(self):
        for x, y, first, second in (([0,1,2,3], [0,1,2,3], (0,1), (2,3)),
                                     ([0,1,2,3], [2,1,1,2], (0,2), (1,3)),
                                     ([0,0,2,3], [2,1,1,2], (0,1), (2,3)),
                                     ([0,1,2,3], [2,1,np.nan,2], (0,1), (2,3))):
            with self.assertRaises(ValueError):
                fit_equivalence(x, y, first, second)

    def test_outside_intersection_and_two_point_warning(self):
        result = fit_equivalence([0,1,2,3], [0,1,10,12], (0,1), (2,3))
        self.assertAlmostEqual(result.volume, -6)
        self.assertIn('hors', result.warning)
        self.assertIn('deux points', result.warning)


class ConductimetryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.graph = self.window.graph_tab
        self.window.tabs.setCurrentWidget(self.graph)
        self.model = self.window.data_tab.model
        self.model.units = ['mL', 'mS/cm']
        self.model.rows = [[str(x), str(30-2*x if x <= 10 else x)] for x in range(21)]
        self.graph.sync_columns()
        self.tool = self.graph.conductimetry_tool
        self.app.processEvents()

    def tearDown(self):
        self.window._discard_on_close = True
        self.window.close()
        self.app.processEvents()

    def test_open_adjust_preserve_zoom_and_reopen(self):
        next(a for a in self.graph.context_menu.actions() if a.text() == 'Titrage conductimétrique…').trigger()
        self.assertTrue(self.tool.active)
        self.assertFalse(self.graph.settings_button.isChecked())
        self.assertAlmostEqual(self.tool.result.volume, 10)
        self.assertIn('10 mL', self.tool.readout.text())
        self.assertTrue(all(line.isVisible() for line in self.tool.lines))
        self.assertTrue(all(region.isVisible() for region in self.tool.regions))
        self.graph.plot.setRange(xRange=(3, 17), yRange=(5, 25), padding=0)
        self.app.processEvents()
        before = self.graph.plot.viewRange()
        self.tool.regions[0].setRegion((0, 6))
        self.assertEqual(self.graph.plot.viewRange(), before)
        self.assertEqual(self.tool.result.branches[0].count, 7)
        self.assertEqual(list(self.tool.extensions[0].getData()[0]), [6, 10])
        self.tool.close_tool()
        self.assertTrue(self.graph.settings_button.isChecked())
        self.assertTrue(all(not item.isVisible() for item in self.tool.items))
        self.tool.open_tool()
        self.assertTrue(all(region.isVisible() for region in self.tool.regions))
        self.assertEqual(self.tool.regions[0].getRegion(), (0, 6))

    def test_errors_hide_stale_result_and_data_refresh(self):
        self.tool.open_tool()
        self.tool.regions[1].setRegion((5, 20))
        self.assertIsNone(self.tool.result)
        self.assertTrue(all(not item.isVisible() for item in self.tool.items))
        self.assertFalse(self.tool.frame_button.isEnabled())
        self.tool.regions[1].setRegion((13,20))
        self.assertIsNotNone(self.tool.result)
        self.model.setData(self.model.index(2, 1), '31')
        self.app.processEvents()
        self.assertNotEqual(self.tool.result.volume, 10)
        self.assertEqual(self.tool.regions[1].getRegion(), (13,20))
        self.graph.series[0].visible.setChecked(False)
        self.assertIsNone(self.tool.result)
        self.assertTrue(all(not r.isVisible() for r in self.tool.regions))

    def test_tools_exclusive_and_empty_series_recovers(self):
        self.tool.open_tool()
        self.graph.tangent_tool.open_tool()
        self.assertFalse(self.tool.active)
        self.tool.open_tool()
        self.assertFalse(self.graph.tangent_tool.active)
        self.model.rows = [['', '']] * 20
        self.graph.refresh_plot()
        self.assertIsNone(self.tool.result)
        self.tool.reset_regions()
        self.model.rows = [[str(x), str(30-2*x if x <= 10 else x)] for x in range(21)]
        self.graph.refresh_plot()
        self.assertAlmostEqual(self.tool.result.volume, 10)
