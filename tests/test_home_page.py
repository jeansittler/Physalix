"""Tests Qt ciblés de la galerie d'accueil."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QPushButton

from physalix.ui.home_page import HomePage, TOOLS
from physalix.ui.main_window import MainWindow


class HomePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget._discard_on_close = True
            widget.close()
        self.app.processEvents()

    def test_gallery_contains_the_ten_tools_with_historical_tab_mapping(self):
        page = HomePage()
        self.assertEqual(len(page.cards), 10)
        self.assertEqual([tool[0] for tool in TOOLS][7:],
                         ["Analyse d’images", "Acquisition Arduino", "Spectrophotométrie"])
        self.assertEqual([tool[3] for tool in TOOLS][7:], [9, 7, 8])

    def test_gallery_uses_balanced_two_four_or_five_column_rows(self):
        page = HomePage()
        self.assertEqual(page._column_count(700), 2)
        self.assertEqual(page._column_count(1000), 4)
        self.assertEqual(page._column_count(1366), 5)
        self.assertEqual(page._column_count(1920), 5)
        page._arrange(4)
        self.assertEqual(page.grid.getItemPosition(8)[1:], (1, 1, 1))
        self.assertEqual(page.grid.getItemPosition(9)[1:], (2, 1, 1))

    def test_card_is_keyboard_activatable(self):
        page = HomePage()
        requested = []
        page.module_requested.connect(requested.append)
        page.cards[7].setFocus()
        QTest.keyClick(page.cards[7], Qt.Key.Key_Return)
        self.assertEqual(requested, [9])

    def test_home_navigation_preserves_the_active_project(self):
        window = MainWindow()
        model = window.data_tab.model
        model.setData(model.index(2, 0), "1.25")
        window.show_module(4)
        self.assertIs(window.workspace_stack.currentWidget(), window.tabs)
        self.assertIs(window.tabs.currentWidget(), window.calculations_tab)
        self.assertEqual([button.isChecked() for button in window.navigation_buttons].count(True), 1)
        self.assertTrue(window.navigation_buttons[4].isChecked())

        window.show_home()

        self.assertIs(window.workspace_stack.currentWidget(), window.home_page)
        self.assertFalse(any(button.isChecked() for button in window.navigation_buttons))
        self.assertTrue(window.home_button.property("homeActive"))
        self.assertEqual(model.rows[0][0], "1.25")
        window.home_page.cards[7].activated.emit(9)
        self.assertIs(window.tabs.currentWidget(), window.image_analysis_tab)
        self.assertEqual(model.rows[0][0], "1.25")

    def test_each_home_card_opens_its_historical_module(self):
        window = MainWindow()
        for card, tool in zip(window.home_page.cards, TOOLS):
            with self.subTest(module=tool[0]):
                window.show_home()
                card.activated.emit(card.tab_index)
                self.assertIs(window.workspace_stack.currentWidget(), window.tabs)
                self.assertEqual(window.tabs.currentIndex(), tool[3])
                self.assertEqual(
                    [button.isChecked() for button in window.navigation_buttons].count(True), 1)
                self.assertTrue(window.navigation_buttons[tool[3]].isChecked())

    def test_header_project_actions_reuse_existing_callbacks(self):
        page = HomePage()
        requested = []
        page.new_project_requested.connect(lambda: requested.append("new"))
        page.open_project_requested.connect(lambda: requested.append("open"))
        buttons = {button.text(): button for button in page.findChildren(QPushButton)}
        buttons["Nouveau projet"].click()
        buttons["Ouvrir un projet…"].click()
        self.assertEqual(requested, ["new", "open"])

    def test_csv_import_from_home_opens_data_module(self):
        window = MainWindow()
        window.show_home()
        with patch.object(QFileDialog, "getOpenFileName", return_value=("mesures.csv", "")), \
                patch("physalix.ui.project_files.CsvImportDialog") as dialog_class:
            dialog_class.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_class.return_value.data = {
                "names": ["temps", "tension"], "units": ["s", "V"],
                "rows": [["0", "1.2"], ["1", "2.4"]],
            }
            window.import_csv()
        self.assertIs(window.workspace_stack.currentWidget(), window.tabs)
        self.assertIs(window.tabs.currentWidget(), window.data_tab)

    def test_project_replacement_keeps_home_callbacks_bound(self):
        window = MainWindow()
        self.assertTrue(window.replace_project())
        window.home_page.cards[8].activated.emit(7)
        self.assertIs(window.workspace_stack.currentWidget(), window.tabs)
        self.assertIs(window.tabs.currentWidget(), window.acquisition_tab)
        window.home_button.click()
        self.assertIs(window.workspace_stack.currentWidget(), window.home_page)


if __name__ == "__main__":
    unittest.main()
