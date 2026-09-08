"""Conventions statistiques, intervalles et liaison avec le tableur."""

import os
import math
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtWidgets import QApplication
from physlab.statistics import METRICS, describe
from physlab.ui.main_window import MainWindow


class StatisticsMathTests(unittest.TestCase):
    def test_known_series_and_french_quartiles(self):
        result, blanks, invalid, overflow = describe([[str(v)] for v in (1, 2, 3, 4)], 0)
        self.assertEqual((blanks, invalid, overflow), (0, 0, set()))
        self.assertEqual(result['count'], 4)
        self.assertEqual(result['mean'], 2.5)
        self.assertEqual(result['median'], 2.5)
        self.assertEqual((result['q1'], result['q3']), (1, 3))
        self.assertEqual((result['range'], result['iqr']), (3, 2))
        self.assertEqual(result['variance'], 1.25)
        self.assertAlmostEqual(result['stddev'], math.sqrt(1.25))
        self.assertAlmostEqual(result['sample_variance'], 5/3)
        self.assertAlmostEqual(result['sem'], math.sqrt(5/3)/2)
        self.assertEqual(result['sum'], 10)

    def test_inclusive_interval_missing_and_nonfinite(self):
        rows = [[value] for value in ("99", "1,5", "", "#DIV/0!", "NaN", "inf", "2.5", "99")]
        result, blanks, invalid, _ = describe(rows, 0, 2, 7)
        self.assertEqual((result['count'], result['mean'], blanks, invalid), (2, 2, 1, 3))
        for first, last in ((0, 2), (3, 2), (1, 9)):
            with self.assertRaises(ValueError):
                describe(rows, 0, first, last)

    def test_empty_singleton_constant_and_odd_count(self):
        empty, *_ = describe([[""]], 0)
        self.assertEqual(empty['count'], 0)
        self.assertIsNone(empty['mean'])
        one, *_ = describe([["-3"]], 0)
        self.assertEqual((one['mean'], one['stddev'], one['q1'], one['q3']), (-3, 0, -3, -3))
        self.assertIsNone(one['sample_stddev'])
        self.assertIsNone(one['sem'])
        constant, *_ = describe([["3"]] * 5, 0)
        self.assertEqual(constant['sem'], 0)
        odd, *_ = describe([[str(v)] for v in (5, 1, 4, 2, 3)], 0)
        self.assertEqual((odd['median'], odd['q1'], odd['q3']), (3, 2, 4))

    def test_extreme_values_do_not_crash(self):
        result, _, _, overflow = describe([["1e308"], ["1e308"]], 0)
        self.assertEqual(result['mean'], 1e308)
        self.assertEqual(result['median'], 1e308)
        self.assertIn('sum', overflow)
        result, _, _, overflow = describe([["-1e308"], ["1e308"]], 0)
        self.assertEqual(result['mean'], 0)
        self.assertIn('range', overflow)


class StatisticsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.model = self.window.data_tab.model
        self.tab = self.window.statistics_tab
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()

    def tearDown(self):
        self.window._discard_on_close = True
        self.window.close()
        self.app.processEvents()

    def test_live_formula_updates_interval_units_and_copy(self):
        self.model.edit_cells({(2, 0): "1", (3, 0): "3", (4, 0): "5", (1, 0): "m",
                               (2, 1): "=A1*2", (3, 1): "=A2*2"})
        self.app.processEvents()
        self.assertEqual(self.tab.results['mean'], 3)
        self.assertEqual(self.tab.table.item(1, 2).text(), 'm')
        variance_row = next(i for i, entry in enumerate(METRICS) if entry[0] == 'variance')
        self.assertEqual(self.tab.table.item(variance_row, 2).text(), '(m)²')
        self.tab.all_rows.setChecked(False)
        self.tab.first.setValue(2)
        self.tab.last.setValue(3)
        self.assertEqual(self.tab.results['mean'], 4)
        self.tab.copy_button.click()
        self.assertIn('Lignes 2 à 3 incluses', self.app.clipboard().text())
        self.assertIn('Moyenne\t4\tm', self.app.clipboard().text())
        self.tab.all_rows.setChecked(True)
        self.tab.quantity.setCurrentIndex(1)
        self.assertEqual(self.tab.results['mean'], 4)
        self.model.edit_cells({(2, 0): '2'})
        self.app.processEvents()
        self.assertEqual(self.tab.results['mean'], 5)
        self.model.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(self.tab.results['mean'], 4)

    def test_selection_and_invalid_bounds(self):
        table = self.window.data_tab.table
        self.model.rows[:3] = [['1', '2'], ['3', '4'], ['5', '6']]
        table.selectionModel().select(QItemSelection(self.model.index(3, 1), self.model.index(4, 1)),
                                      QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.tab.from_selection()
        self.assertEqual(self.tab.quantity.currentData(), 1)
        self.assertEqual((self.tab.first.value(), self.tab.last.value()), (2, 3))
        self.assertEqual(self.tab.results['mean'], 5)
        self.tab.first.setValue(4)
        self.assertIsNone(self.tab.results)
        self.assertFalse(self.tab.copy_button.isEnabled())
        table.selectionModel().select(QItemSelection(self.model.index(2, 0), self.model.index(3, 1)),
                                      QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.tab.from_selection()
        self.assertIn('une seule colonne', self.tab.summary.text())
        self.assertIsNone(self.tab.results)

    def test_column_rename_move_and_removal(self):
        self.model.edit_cells({(2, 1): '8'})
        self.tab.quantity.setCurrentIndex(1)
        self.model.edit_cells({(0, 1): 'Vitesse'})
        self.app.processEvents()
        self.assertIn('Vitesse', self.tab.quantity.currentText())
        self.window.data_tab.table.horizontalHeader().moveSection(1, 0)
        self.assertEqual(self.tab.results['mean'], 8)
        self.model.remove_quantity(0)
        self.app.processEvents()
        self.assertEqual(self.tab.quantity.currentData(), 0)
        self.assertEqual(self.tab.results['mean'], 8)
        self.model.remove_quantity(0)
        self.app.processEvents()
        self.assertIsNone(self.tab.results)
        self.assertFalse(self.tab.copy_button.isEnabled())
        self.model.add_quantity()
        self.app.processEvents()
        self.assertEqual(self.tab.results['count'], 0)
