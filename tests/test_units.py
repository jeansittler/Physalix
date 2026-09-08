"""Saisie des unités sans déplacer ni modifier les mesures."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox

from physlab.ui.data_tab import DataTab


class UnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = DataTab()
        self.tab.show()
        self.app.processEvents()
        self.table = self.tab.table
        self.model = self.tab.model

    def tearDown(self):
        self.tab.close()
        self.app.processEvents()

    def open_unit(self):
        position = self.table.visualRect(self.model.index(1, 0)).center()
        QTest.mouseClick(self.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
        self.app.processEvents()
        return next(e for e in self.table.findChildren(QComboBox) if e.isVisible())

    def test_custom_unit_enter_and_measurement_preserved(self):
        self.model.setData(self.model.index(2, 0), "12,5")
        editor = self.open_unit()
        editor.setEditText("kg·m²/s³")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.model.units[0], "kg·m²/s³")
        self.assertEqual(self.table.currentIndex(), self.model.index(2, 0))
        self.assertEqual(self.model.rows[0][0], "12,5")
        self.assertEqual(self.model.headerData(2, Qt.Orientation.Vertical), "1")

    def test_choose_suggestion_and_tab(self):
        editor = self.open_unit()
        editor.showPopup()
        self.app.processEvents()
        index = editor.model().index(editor.findText("mL"), 0)
        editor.view().scrollTo(index)
        self.app.processEvents()
        QTest.mouseClick(editor.view().viewport(), Qt.MouseButton.LeftButton,
                         pos=editor.view().visualRect(index).center())
        QTest.keyClick(editor, Qt.Key.Key_Tab)
        self.app.processEvents()
        self.assertEqual(self.model.units[0], "mL")
        self.assertEqual(self.table.currentIndex(), self.model.index(1, 1))

    def test_escape_and_new_column(self):
        self.model.setData(self.model.index(1, 0), "Sans unité")
        editor = self.open_unit()
        editor.setEditText("m")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertEqual(self.model.units[0], "Sans unité")
        self.model.add_quantity()
        self.assertEqual(self.model.units, ["Sans unité", "", ""])
        self.assertEqual(self.model.rowCount(), 22)


if __name__ == "__main__":
    unittest.main()
