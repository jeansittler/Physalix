"""Vérifier la progression numérique et le geste réel de recopie Qt."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from physalix.ui.data_tab import DataTab
from physalix.ui.fill_table import extend_series


class SeriesTests(unittest.TestCase):
    def test_steps(self):
        self.assertEqual(extend_series(["0", "1"], 4), ["2", "3", "4", "5"])
        self.assertEqual(extend_series(["0", "0,1"], 3), ["0,2", "0,3", "0,4"])
        self.assertEqual(extend_series(["5", "3"], 3), ["1", "-1", "-3"])
        self.assertEqual(extend_series(["1e-3", "2e-3"], 1), ["0.003"])
        self.assertEqual(extend_series(["7"], 2), ["7", "7"])

    def test_invalid_seeds(self):
        for texts in ([], ["", "1"], ["Volume", "1"], ["NaN"], ["0", "1", "3"]):
            with self.assertRaises(ValueError):
                extend_series(texts, 1)


class FillGestureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = DataTab()
        self.tab.resize(800, 600)
        self.tab.show()
        self.app.processEvents()
        self.table = self.tab.table
        self.model = self.tab.model
        self.model.setData(self.model.index(2, 0), "0")
        self.model.setData(self.model.index(3, 0), "1")

    def tearDown(self):
        self.tab.close()
        self.app.processEvents()

    def select_seed(self):
        # Sélection avec la souris, comme l'utilisateur.
        viewport = self.table.viewport()
        first = self.table.visualRect(self.model.index(2, 0)).center()
        second = self.table.visualRect(self.model.index(3, 0)).center()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=first)
        QTest.mouseMove(viewport, second)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=second)
        self.app.processEvents()
        self.assertFalse(self.table.fill_handle_rect().isEmpty())

    def test_drag_fills_only_selected_column(self):
        self.model.setData(self.model.index(6, 1), "7,2")
        self.select_seed()
        viewport = self.table.viewport()
        handle = self.table.fill_handle_rect().center()
        target = self.table.visualRect(self.model.index(7, 0)).center()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=handle)
        QTest.mouseMove(viewport, target)
        self.assertEqual(self.model.rows[2][0], "")  # aperçu sans modification
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=target)
        self.assertEqual([r[0] for r in self.model.rows[:6]], ["0", "1", "2", "3", "4", "5"])
        self.assertEqual(self.model.rows[4][1], "7,2")

    def test_escape_cancels(self):
        self.select_seed()
        viewport = self.table.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton,
                         pos=self.table.fill_handle_rect().center())
        target = self.table.visualRect(self.model.index(7, 0)).center()
        QTest.mouseMove(viewport, target)
        QTest.keyClick(self.table, Qt.Key.Key_Escape)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=target)
        self.assertEqual(self.model.rows[2][0], "")
        self.assertFalse(self.table._scroll_timer.isActive())

    def test_scroll_and_extend_past_last_row(self):
        self.select_seed()
        viewport = self.table.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton,
                         pos=self.table.fill_handle_rect().center())
        target = QPoint(100, viewport.height() + 20)
        QTest.mouseMove(viewport, target)
        for _ in range(35):
            self.table._auto_scroll()
            self.app.processEvents()
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=target)
        self.assertGreater(self.model.rowCount(), 22)
        self.assertEqual(self.model.rows[20][0], "20")

    def test_no_handle_on_names_or_multiple_columns(self):
        for top, bottom, right in ((0, 3, 0), (1, 3, 0), (2, 3, 1)):
            area = QItemSelection(self.model.index(top, 0), self.model.index(bottom, right))
            self.table.selectionModel().select(area, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.assertTrue(self.table.fill_handle_rect().isEmpty())


if __name__ == "__main__":
    unittest.main()
