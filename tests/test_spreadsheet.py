"""Gestes du tableur, historique et formules liées aux mesures."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from physalix.spreadsheet import CellFormula, column_label, translate_formula
from physalix.ui.main_window import MainWindow


class SpreadsheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.resize(1000, 720)
        self.window.show()
        self.tab = self.window.data_tab
        self.model, self.table = self.tab.model, self.tab.table
        self.app.processEvents()

    def tearDown(self):
        self.window._discard_on_close = True
        self.window.close()
        self.app.processEvents()

    def select(self, row, column, bottom=None, right=None):
        first = self.model.index(row, column)
        self.table.setCurrentIndex(first)
        self.table.selectionModel().select(QItemSelection(first, self.model.index(
            bottom if bottom is not None else row, right if right is not None else column)),
            QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def put(self, row, column, value):
        self.model.edit_cells({(row + 2, column): value})

    def test_delete_selection_undo_redo_restores_formulas_and_graph(self):
        self.put(0, 0, "3")
        self.put(0, 1, "=A1*2")
        self.put(1, 0, "4")
        self.put(1, 1, "=A2*2")
        self.select(2, 0, 3, 1)
        QTest.keyClick(self.table, Qt.Key.Key_Delete)
        self.assertEqual(self.model.rows[:2], [["", ""], ["", ""]])
        QTest.keyClick(self.table, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.model.rows[:2], [["3", "6"], ["4", "8"]])
        self.assertEqual(self.model.index(2, 1).data(Qt.ItemDataRole.EditRole), "=A1*2")
        self.app.processEvents()
        self.assertEqual(list(self.window.graph_tab.series[0].points.getData()[1]), [6, 8])
        QTest.keyClick(self.table, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.model.rows[:2], [["", ""], ["", ""]])

    def test_formula_bar_and_cell_editor(self):
        self.put(0, 0, "5")
        self.select(2, 1)
        self.tab.formula_bar.setText("=A1+1")
        QTest.keyClick(self.tab.formula_bar, Qt.Key.Key_Return)
        self.assertEqual(self.model.rows[0][1], "6")
        self.assertEqual(self.tab.cell_address.text(), "B1")
        self.table.edit(self.model.index(2, 1))
        editor = self.table.findChild(QLineEdit)
        self.assertEqual(editor.text(), "=A1+1")
        editor.setText("=A1*3")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(self.model.rows[0][1], "15")
        self.model.undo_stack.undo()
        self.assertEqual(self.model.rows[0][1], "6")

    def test_formula_fill_is_relative_and_one_undo(self):
        for row in range(5):
            self.put(row, 0, str(row + 1))
        self.put(0, 1, "=A1+$A$1")
        self.select(2, 1)
        self.app.processEvents()
        viewport = self.table.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=self.table.fill_handle_rect().center())
        target = self.table.visualRect(self.model.index(6, 1)).center()
        QTest.mouseMove(viewport, target)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=target)
        self.assertEqual([row[1] for row in self.model.rows[:5]], ["2", "3", "4", "5", "6"])
        self.assertEqual(self.model.formulas[4, 1], "=A5+$A$1")
        self.model.undo_stack.undo()
        self.assertEqual([row[1] for row in self.model.rows[:5]], ["2", "", "", "", ""])
        self.model.undo_stack.redo()
        self.put(0, 0, "10")
        self.assertEqual(self.model.rows[4][1], "15")

    def test_column_move_preserves_formulas_graph_and_visual_clipboard(self):
        self.model.add_quantity()
        self.put(0, 0, "2")
        self.put(0, 1, "=A1*3")
        self.put(0, 2, "9")
        self.app.processEvents()
        key = self.window.graph_tab.series[0].key()
        header = self.table.horizontalHeader()
        header.moveSection(0, 2)
        self.assertEqual([header.logicalIndex(v) for v in range(3)], [1, 2, 0])
        self.assertEqual(self.model.rows[0], ["2", "6", "9"])
        self.assertEqual(self.window.graph_tab.series[0].key(), key)
        self.select(2, 0, 2, 2)
        self.table.copy_selection()
        self.assertEqual(self.app.clipboard().text(), "6\t9\t2\n")
        self.select(3, 1)
        self.app.clipboard().setText("10\t11\t12")
        self.table.paste_clipboard()
        self.assertEqual(self.model.rows[1], ["12", "10", "11"])
        self.model.undo_stack.undo()
        self.assertEqual(self.model.rows[1], ["", "", ""])
        self.model.undo_stack.undo()
        self.assertEqual([header.logicalIndex(v) for v in range(3)], [0, 1, 2])

    def test_internal_formula_copy_and_external_formula_paste(self):
        self.put(0, 0, "2")
        self.put(1, 0, "4")
        self.put(0, 1, "=A1*2")
        self.select(2, 1)
        self.table.copy_selection()
        self.select(3, 1)
        self.table.paste_clipboard()
        self.assertEqual(self.model.formulas[1, 1], "=A2*2")
        self.assertEqual(self.model.rows[1][1], "8")
        self.select(4, 1)
        self.app.clipboard().setText("=SOMME(A1:A2;3)")
        self.table.paste_clipboard()
        self.assertEqual(self.model.rows[2][1], "9")

    def test_errors_recovery_and_cross_calculation_cycles(self):
        self.put(0, 0, "=1/0")
        self.assertEqual(self.model.rows[0][0], "#DIV/0!")
        self.put(0, 0, "=B1")
        self.put(0, 1, "=A1")
        self.assertEqual(self.model.rows[0], ["#CYCLE!", "#CYCLE!"])
        self.put(0, 1, "2")
        self.assertEqual(self.model.rows[0], ["2", "2"])
        self.window.calculations_tab.engine.add("double", "", expression="C1*2")
        self.put(0, 1, "=C1+1")
        self.assertEqual(self.model.rows[0][1], "#CYCLE!")
        self.put(0, 0, "3")
        self.app.processEvents()
        self.assertEqual(self.model.rows[0], ["3", "7", "6"])
        self.put(0, 0, "=Z1")
        self.assertEqual(self.model.rows[0][0], "#REF!")

    def test_deleted_column_adjusts_formula_references(self):
        self.model.add_quantity()
        self.put(0, 1, "4")
        self.put(0, 2, "=$B$1*2")
        self.model.remove_quantity(0)
        self.assertEqual(self.model.formulas[0, 1], "=$A$1*2")
        self.assertEqual(self.model.rows[0], ["4", "8"])
        self.model.remove_quantity(0)
        self.assertEqual(self.model.rows[0], ["#REF!"])

    def test_blank_ranges_new_column_and_redo_branch(self):
        self.put(0, 0, "2")
        self.put(2, 0, "4")
        self.put(0, 1, "=MOYENNE(A1:A3)")
        self.assertEqual(self.model.rows[0][1], "3")
        self.put(0, 1, "=C1+1")
        self.assertEqual(self.model.rows[0][1], "#REF!")
        self.model.add_quantity()
        self.assertEqual(self.model.rows[0][1], "1")
        self.model.undo_stack.undo()
        self.assertEqual(self.model.rows[0][1], "3")
        self.put(0, 0, "6")
        self.assertEqual(self.model.rows[0][1], "5")
        self.assertFalse(self.model.undo_stack.canRedo())


class FormulaSyntaxTests(unittest.TestCase):
    def test_safe_functions_french_decimals_and_references(self):
        self.assertEqual(CellFormula("=RACINE(A1^2)+1,5").evaluate(lambda r, c: 3), 4.5)
        self.assertEqual(CellFormula("=LOG10(100)").evaluate(lambda r, c: 0), 2)
        self.assertEqual(column_label(26), "AA")
        self.assertEqual(translate_formula("=A1+$B1+C$1+$D$1+LOG10(A1)", 2, 1),
                         "=B3+$B3+D$1+$D$1+LOG10(B3)")
        self.assertEqual(translate_formula("=A1", -1), "=#REF!")
        for text in ("=__import__('os')", "=A1.real", "=[1,2]", "=open(1)", "=2**1000"):
            with self.subTest(text=text), self.assertRaises((ValueError, ArithmeticError)):
                CellFormula(text).evaluate(lambda r, c: 0)
