"""Accès aux outils lors du redimensionnement de l'interface thémée."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QBoxLayout, QFrame, QPushButton, QScrollArea
from physalix.ui.components import ResponsiveCards
from physalix.ui.main_window import MainWindow
from physalix.ui.theme import LIGHT, apply_theme, stylesheet


class ThemeLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        self.window = MainWindow()
        self.window.show()

    def tearDown(self):
        self.window._discard_on_close = True
        self.window.close()
        self.app.processEvents()

    def test_tools_remain_reachable_in_small_window(self):
        self.window.resize(640, 420)
        for tab, button in ((self.window.video_tab, self.window.video_tab.next),
                            (self.window.graph_tab, self.window.graph_tab.series[0].remove_button),
                            (self.window.modeling_tab, self.window.modeling_tab.fit_button),
                            (self.window.calculations_tab, self.window.calculations_tab.formula_button),
                            (self.window.statistics_tab, self.window.statistics_tab.copy_button)):
            with self.subTest(tab=type(tab).__name__):
                self.window.tabs.setCurrentWidget(tab)
                QTest.qWait(20)
                scroll = tab.findChild(QScrollArea)
                ancestor = button.parentWidget()
                while ancestor is not None and ancestor is not tab:
                    if isinstance(ancestor, QScrollArea):
                        ancestor.ensureWidgetVisible(button)
                    ancestor = ancestor.parentWidget()
                scroll.ensureWidgetVisible(button)
                self.app.processEvents()
                center = button.mapTo(scroll.viewport(), button.rect().center())
                self.assertTrue(scroll.viewport().rect().contains(center))
                self.assertGreaterEqual(button.height(), 30)

    def test_design_tokens_and_interaction_states_are_centralized(self):
        self.assertNotEqual(LIGHT.background, LIGHT.surface)
        self.assertNotEqual(LIGHT.border, LIGHT.border_strong)
        self.assertGreaterEqual(LIGHT.control_height, 32)
        self.assertGreaterEqual(LIGHT.wide_layout, 1100)
        self.assertNotEqual(LIGHT.navy, LIGHT.primary)
        self.assertNotEqual(LIGHT.table_header, LIGHT.table_metadata)
        qss = stylesheet()
        for state in (":hover", ":focus", ":pressed", ":selected", ":disabled"):
            self.assertIn(state, qss)
        for role in ('role="primary"', 'role="danger"', 'role="card"'):
            self.assertIn(role, qss)

    def test_reference_views_use_cards_and_clear_action_hierarchy(self):
        data = self.window.data_tab
        modeling = self.window.modeling_tab
        self.assertTrue(data.table.alternatingRowColors())
        data_roles = {w.property("role") for w in data.findChildren(QFrame)}
        self.assertTrue({"help", "toolbar"}.issubset(data_roles))
        self.assertEqual(modeling.fit_button.property("role"), "primary")
        self.assertEqual(modeling.remove_button.property("role"), "quiet")
        self.assertEqual(modeling.result_panel.property("role"), "card")
        responsive = modeling.findChild(ResponsiveCards)
        scroll = modeling.findChild(QScrollArea)
        for size, direction in (((1280, 800), QBoxLayout.Direction.LeftToRight),
                                ((1920, 1080), QBoxLayout.Direction.LeftToRight),
                                ((900, 700), QBoxLayout.Direction.TopToBottom)):
            self.window.resize(*size)
            self.window.tabs.setCurrentWidget(modeling)
            QTest.qWait(20)
            self.assertEqual(responsive.cards.direction(), direction)
            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)

    def test_focus_and_modeling_disabled_states_remain_explicit(self):
        data = self.window.data_tab
        modeling = self.window.modeling_tab
        self.window.tabs.setCurrentWidget(data)
        data.formula_bar.setFocus()
        self.app.processEvents()
        self.assertTrue(data.formula_bar.hasFocus())
        self.assertGreater(data.table.verticalScrollBar().maximum(), 0)
        self.assertFalse(modeling.minimum.isEnabled())
        self.assertFalse(modeling.range_fields.property("active"))
        modeling.range_check.setChecked(True)
        self.assertTrue(modeling.minimum.isEnabled())
        self.assertTrue(modeling.range_fields.property("active"))
        model = data.model
        metadata = model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole)
        model.calculated_columns.add(1)
        calculated = model.data(model.index(2, 1), Qt.ItemDataRole.BackgroundRole)
        self.assertEqual(metadata.color().name(), LIGHT.table_metadata.lower())
        self.assertEqual(calculated.color().name(), LIGHT.primary_soft.lower())

    def test_navigation_and_plot_after_resize(self):
        for size in ((1366, 700), (1920, 1000), (900, 620), (1366, 700)):
            self.window.resize(*size)
            for index in range(6):
                self.window.tabs.setCurrentIndex(index)
                self.app.processEvents()
                self.assertEqual(self.window.tabs.currentIndex(), index)
                self.assertFalse(self.window.tabs.tabIcon(index).isNull())
            self.window.tabs.setCurrentWidget(self.window.graph_tab)
            QTest.qWait(20)
            self.assertGreaterEqual(self.window.graph_tab.plot.height(), 220)

    def test_data_help_preserves_table_access(self):
        self.window.resize(900, 620)
        tab = self.window.data_tab
        toggle = next(b for b in tab.findChildren(QPushButton) if b.isCheckable())
        toggle.click()
        self.app.processEvents()
        self.assertTrue(toggle.isChecked())
        self.assertGreater(tab.table.viewport().height(), 80)
        toggle.click()
        self.app.processEvents()
        self.assertGreater(tab.table.viewport().height(), 200)


if __name__ == "__main__":
    unittest.main()
