"""Accès aux outils lors du redimensionnement de l'interface thémée."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QFrame, QPushButton, QScrollArea, QSizePolicy, QTabBar,
)
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
        self.assertIn(f"QScrollBar:vertical {{ background: {LIGHT.border}; width: 14px", qss)
        self.assertIn(f"QScrollBar::handle {{ background: {LIGHT.muted}", qss)

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

    def test_graph_workspace_prioritizes_plot_height(self):
        workspace = self.window.graph_tab
        self.window.tabs.setCurrentWidget(workspace)
        management = workspace.layout().itemAt(0).widget()
        for width, height, minimum_plot_height in (
                (1366, 768, 350), (1600, 900, 480), (1920, 1080, 650)):
            with self.subTest(size=(width, height)):
                self.window.resize(width, height)
                QTest.qWait(20)
                graph_tabs = workspace.area.findChild(QTabBar, "graphTabs")
                self.assertIsNotNone(graph_tabs)
                self.assertLessEqual(management.height(), 42)
                self.assertLessEqual(graph_tabs.height(), 44)
                self.assertGreaterEqual(workspace.plot.height(), minimum_plot_height)
                self.assertEqual(workspace.plot.sizePolicy().verticalPolicy(),
                                 QSizePolicy.Policy.Expanding)
                scroll = workspace.active_graph.findChild(QScrollArea)
                self.assertEqual(scroll.verticalScrollBar().maximum(), 0)

    def test_video_workspace_prioritizes_canvas_height(self):
        video = self.window.video_tab
        self.window.tabs.setCurrentWidget(video)
        heights = []
        for width, height, minimum_canvas_height in (
                (1280, 720, 325), (1366, 768, 370),
                (1600, 900, 500), (1920, 1080, 680)):
            with self.subTest(size=(width, height)):
                self.window.resize(width, height)
                QTest.qWait(20)
                scroll = video.findChild(QScrollArea)
                heights.append(video.screen.height())
                self.assertEqual(scroll.verticalScrollBar().maximum(), 0)
                self.assertGreaterEqual(video.screen.height(), minimum_canvas_height)
                self.assertEqual(video.screen.sizePolicy().verticalPolicy(),
                                 QSizePolicy.Policy.Expanding)
        self.assertGreater(heights[-1], heights[0] + 350)

    def test_hidden_graph_settings_leave_only_compact_restore_control(self):
        graph = self.window.graph_tab.active_graph
        self.window.tabs.setCurrentWidget(self.window.graph_tab)
        self.window.resize(1366, 768)
        QTest.qWait(20)
        visible_height = graph.plot.height()
        graph.settings_button.setChecked(False)
        QTest.qWait(20)
        self.assertFalse(graph.series_label.isVisible())
        self.assertFalse(graph.series_choice.isVisible())
        self.assertFalse(graph.series_stack.isVisible())
        self.assertTrue(graph.settings_button.isVisible())
        self.assertGreater(graph.plot.height(), visible_height)

    def test_all_tabs_fit_reference_resolutions(self):
        for width, height in ((1280, 800), (1920, 1080)):
            self.window.resize(width, height)
            for index in range(self.window.tabs.count()):
                with self.subTest(size=(width, height), tab=self.window.tabs.tabText(index)):
                    page = self.window.tabs.widget(index)
                    self.window.tabs.setCurrentIndex(index)
                    QTest.qWait(20)
                    for scroll in page.findChildren(QScrollArea):
                        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
            self.assertEqual(self.window.calculations_tab.tools.cards.direction(),
                             QBoxLayout.Direction.LeftToRight)
            self.assertEqual(self.window.video_tab.workflow_cards.cards.direction(),
                             QBoxLayout.Direction.LeftToRight)
            self.assertLessEqual(self.window.graph_tab.add_button.width(), LIGHT.action_compact)
            self.assertLessEqual(self.window.graph_tab.arrangement.width(), LIGHT.field_compact)
            self.assertLessEqual(self.window.graph_tab.rename_button.width(), LIGHT.action_compact)
            self.assertLessEqual(self.window.video_tab.open_button.width(), LIGHT.action_compact)
            self.assertLessEqual(self.window.video_tab.axes_choice.width(), LIGHT.field_compact)
            if width == 1280:
                self.assertGreaterEqual(self.window.graph_tab.plot.height(), 320)
                self.assertGreaterEqual(self.window.video_tab.screen.height(), 320)
                self.assertLessEqual(self.window.video_tab.screen.mapTo(
                    self.window.video_tab, self.window.video_tab.screen.rect().topLeft()).y(), 270)
                modeling = self.window.modeling_tab.currentWidget()
                self.assertLessEqual(modeling.result_panel.y(), 370)
                self.assertLessEqual(self.window.calculations_tab.history.mapTo(
                    self.window.calculations_tab,
                    self.window.calculations_tab.history.rect().topLeft()).y(), 580)
                self.assertGreaterEqual(self.window.statistics_tab.table.height(), 320)
            else:
                self.assertGreaterEqual(self.window.graph_tab.plot.height(), 600)
                self.assertGreaterEqual(self.window.video_tab.screen.height(), 600)
                self.assertGreaterEqual(self.window.statistics_tab.table.height(), 600)

        self.window.resize(900, 700)
        for index in range(self.window.tabs.count()):
            page = self.window.tabs.widget(index)
            self.window.tabs.setCurrentIndex(index)
            QTest.qWait(20)
            for scroll in page.findChildren(QScrollArea):
                self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(self.window.calculations_tab.tools.cards.direction(),
                         QBoxLayout.Direction.TopToBottom)
        self.assertEqual(self.window.video_tab.workflow_cards.cards.direction(),
                         QBoxLayout.Direction.TopToBottom)

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
