"""Copier-coller de tableaux via les raccourcis Qt et le presse-papiers."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from physlab.ui.data_tab import DataTab


class ClipboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = DataTab()
        self.model = self.tab.model
        self.table = self.tab.table
        self.tab.show()
        self.app.processEvents()

    def tearDown(self):
        self.tab.close()

    def paste(self, text, row=2, column=0):
        self.table.selectionModel().setCurrentIndex(
            self.model.index(row, column), QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.app.clipboard().setText(text)
        QTest.keyClick(self.table, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)

    def test_excel_round_trip_and_empty_cells(self):
        self.paste("1,2\t\r\n-3e-2\t4.5\r\n")
        self.assertEqual(self.model.rows[:2], [["1,2", ""], ["-3e-2", "4.5"]])
        QTest.keyClick(self.table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.app.clipboard().text(), "1,2\t\n-3e-2\t4.5\n")
        self.table.selectionModel().setCurrentIndex(
            self.model.index(4, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
        QTest.keyClick(self.table, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.model.rows[2:4], self.model.rows[:2])

    def test_grows_in_both_dimensions(self):
        self.paste("1;2;3\n4;5;6\n7;8;9", row=21, column=1)
        self.assertEqual(self.model.columnCount(), 4)
        self.assertEqual(self.model.rows[19:22], [["", "1", "2", "3"],
                                                ["", "4", "5", "6"],
                                                ["", "7", "8", "9"]])
        self.assertEqual(self.model.rows[22], [""] * 4)

    def test_headers_and_units(self):
        self.paste("Temps\tPosition\ns\tm\n0\t1,5\n", row=0)
        self.assertEqual(self.model.names, ["Temps", "Position"])
        self.assertEqual(self.model.units, ["s", "m"])
        self.assertEqual(self.model.rows[0], ["0", "1,5"])

    @patch("physlab.ui.data_tab.QMessageBox.warning")
    def test_invalid_paste_is_atomic(self, warning):
        self.model.rows[19][1] = "42"
        self.paste("1\t2\n3\tinvalide", row=21, column=1)
        warning.assert_called_once()
        self.assertEqual(self.model.columnCount(), 2)
        self.assertEqual(self.model.rowCount(), 22)
        self.assertEqual(self.model.rows[19][1], "42")

    @patch("physlab.ui.data_tab.QMessageBox.warning")
    def test_calculated_column_is_protected(self, warning):
        self.model.calculated_columns.add(1)
        self.paste("1\t2")
        warning.assert_called_once()
        self.assertEqual(self.model.rows[0], ["", ""])

    def test_selection_top_left_is_paste_origin(self):
        self.table.setCurrentIndex(self.model.index(5, 1))
        self.table.selectionModel().select(
            QItemSelection(self.model.index(2, 0), self.model.index(5, 1)),
            QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.app.clipboard().setText("7")
        self.table.paste_clipboard()
        self.assertEqual(self.model.rows[0][0], "7")
        self.assertEqual(self.model.rows[3][1], "")


if __name__ == "__main__":
    unittest.main()
