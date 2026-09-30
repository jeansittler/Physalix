"""Fenêtre principale et navigation de Physalix."""

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)
from physalix.ui.components import role
from physalix.ui.branding import BrandLogo, application_icon
from physalix.ui.icons import icon

from physalix.ui.data_tab import DataTab
from physalix.ui.graph_tab import GraphTab
from physalix.ui.modeling_tab import ModelingTab
from physalix.ui.video_tab import VideoTab
from physalix.ui.calculations_tab import CalculationsTab
from physalix.ui.statistics_tab import StatisticsTab
from physalix.ui.graph_digitizer_tab import GraphDigitizerTab
from physalix.ui.graph_workspace import GraphWorkspace, ModelingWorkspace
from physalix.ui.project_files import ProjectFiles
from physalix.ui.updates import UpdateController
from physalix import __development__, __version__


NAVIGATION_LABELS = (
    "Données", "Graphique", "Modélisation", "Pointage", "Calculs",
    "Statistiques", "Numérisation",
)
NAVIGATION_TOOLTIPS = (
    "Données", "Graphique", "Modélisation", "Pointage vidéo", "Calculs",
    "Statistiques", "Numérisation",
)
NAVIGATION_LOGO_SIZES = {
    "normal": (100, 28), "compact": (86, 26), "icon": (70, 24),
}
NAVIGATION_CARTOUCHE_SIZES = {
    "normal": (112, 34), "compact": (96, 34), "icon": (80, 34),
}
NAVIGATION_GAP = 8


class MainWindow(QMainWindow, ProjectFiles):
    """Accueillir les espaces de travail de l'application."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Physalix — {__version__}" if __development__ else "Physalix")
        self.setWindowIcon(application_icon())
        self.resize(1280, 760)
        self.setMinimumSize(640, 420)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainPages")
        self.tabs.setDocumentMode(True)
        self._navigation_mode = None
        self.data_tab = DataTab()
        self.graph_tab = GraphWorkspace(self.data_tab.model)
        self.tabs.addTab(self.data_tab, "Données")
        self.tabs.addTab(self.graph_tab, "Graphique")
        self.modeling_tab = ModelingWorkspace(self.graph_tab)
        self.tabs.addTab(self.modeling_tab, "Modélisation")
        self.graph_tab.modeling_requested.connect(lambda: self.tabs.setCurrentWidget(self.modeling_tab))
        self.modeling_tab.graph_requested.connect(lambda: self.tabs.setCurrentWidget(self.graph_tab))
        self.video_tab = VideoTab(self.data_tab.model)
        video_index = self.tabs.addTab(self.video_tab, "Pointage")
        self.tabs.setTabToolTip(video_index, "Pointage vidéo")
        self.calculations_tab = CalculationsTab(self.data_tab.model)
        self.tabs.addTab(self.calculations_tab, "Calculs")
        self.statistics_tab = StatisticsTab(self.data_tab)
        self.tabs.addTab(self.statistics_tab, "Statistiques")
        self.digitizer_tab = GraphDigitizerTab(self.data_tab, self.graph_tab)
        self.tabs.addTab(self.digitizer_tab, "Numérisation")
        for index, tooltip in enumerate(NAVIGATION_TOOLTIPS):
            self.tabs.setTabToolTip(index, tooltip)
            self.tabs.setTabWhatsThis(index, tooltip)
        self.tabs.tabBar().hide()

        self.navigation = role(QWidget(), "mainNavigation")
        self.navigation.setObjectName("mainNavigation")
        self.navigation.setFixedHeight(44)
        self.navigation.setProperty("navigationMode", "normal")
        self.navigation_layout = QHBoxLayout(self.navigation)
        self.navigation_layout.setContentsMargins(8, 5, 8, 5)
        self.navigation_layout.setSpacing(0)
        self.brand_cartouche = role(QFrame(), "brandCartouche")
        self.brand_cartouche.setFixedSize(*NAVIGATION_CARTOUCHE_SIZES["normal"])
        cartouche_layout = QVBoxLayout(self.brand_cartouche)
        cartouche_layout.setContentsMargins(0, 0, 0, 0)
        self.brand_logo = BrandLogo()
        self.brand_logo.setDisplaySize(*NAVIGATION_LOGO_SIZES["normal"])
        cartouche_layout.addWidget(self.brand_logo, 0, Qt.AlignmentFlag.AlignCenter)
        self.navigation_layout.addWidget(self.brand_cartouche)
        self.navigation_layout.addSpacing(NAVIGATION_GAP)

        self.navigation_group = QButtonGroup(self.navigation)
        self.navigation_group.setExclusive(True)
        self.navigation_buttons = []
        for index, (label, tooltip) in enumerate(zip(NAVIGATION_LABELS, NAVIGATION_TOOLTIPS)):
            button = role(QToolButton(), "mainNavigationButton")
            button.setObjectName(f"mainNavigationButton{index}")
            button.setText(label)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setIconSize(QSize(18, 18))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setFixedHeight(34)
            button.clicked.connect(
                lambda checked=False, chosen=index, pages=self.tabs: pages.setCurrentIndex(chosen))
            self.navigation_group.addButton(button, index)
            self.navigation_buttons.append(button)
            self.navigation_layout.addWidget(button)
        self.navigation_layout.addStretch(1)

        self.main_container = QWidget()
        main_layout = QVBoxLayout(self.main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.navigation)
        main_layout.addWidget(self.tabs, 1)
        self._set_navigation_mode("normal")
        self.tabs.currentChanged.connect(self.update_navigation)
        self.update_navigation()
        self.setCentralWidget(self.main_container)

        self.statusBar().showMessage(
            f"Version de développement {__version__} · mises à jour désactivées"
            if __development__ else "Prêt"
        )
        self.setup_files()
        self.updater = UpdateController(self)
        QTimer.singleShot(0, self._update_navigation_density)

    def update_navigation(self, *args):
        current = self.tabs.currentIndex()
        for index, name in enumerate(("data", "graph", "model", "video", "calculations", "statistics", "digitizer")):
            active = index == current
            self.navigation_buttons[index].setChecked(active)
            self.navigation_buttons[index].setIcon(icon(name, active, navigation=True))
        for index, button in enumerate(self.navigation_buttons):
            button.setFocusPolicy(
                Qt.FocusPolicy.TabFocus if index == current else Qt.FocusPolicy.NoFocus)

    def _navigation_required_width(self, mode):
        """Estimer la largeur naturelle avec les métriques Qt courantes."""
        font = self.navigation_buttons[0].font()
        font.setWeight(QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        horizontal_padding = 10 if mode == "normal" else 4
        tab_chrome = 2 * horizontal_padding + 16
        if mode == "icon":
            tabs_width = len(self.navigation_buttons) * (18 + 4 + tab_chrome)
        else:
            icon_and_gap = 18 + 4
            tabs_width = sum(
                metrics.horizontalAdvance(label) + icon_and_gap + tab_chrome
                for label in NAVIGATION_LABELS
            )
        return 16 + NAVIGATION_CARTOUCHE_SIZES[mode][0] + NAVIGATION_GAP + tabs_width

    def _set_navigation_mode(self, mode):
        if mode == self._navigation_mode:
            return
        self._navigation_mode = mode
        self.navigation.setProperty("navigationMode", mode)
        self.brand_cartouche.setFixedSize(*NAVIGATION_CARTOUCHE_SIZES[mode])
        self.brand_logo.setDisplaySize(*NAVIGATION_LOGO_SIZES[mode])
        font = self.navigation_buttons[0].font()
        font.setWeight(QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        horizontal_padding = 10 if mode == "normal" else 4
        tab_chrome = 2 * horizontal_padding + 16
        for button, label in zip(self.navigation_buttons, NAVIGATION_LABELS):
            if mode == "icon":
                width = 18 + 4 + tab_chrome
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            else:
                width = metrics.horizontalAdvance(label) + 18 + 4 + tab_chrome
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setFixedWidth(width)
        for widget in (self.navigation, *self.navigation_buttons):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.updateGeometry()

    def _update_navigation_density(self):
        if not hasattr(self, "tabs"):
            return
        available = self.navigation.width()
        normal_width = self._navigation_required_width("normal")
        compact_width = self._navigation_required_width("compact")
        hysteresis = 24
        if self._navigation_mode == "normal":
            mode = ("normal" if available >= normal_width else
                    "compact" if available >= compact_width else "icon")
        elif self._navigation_mode == "compact":
            if available >= normal_width + hysteresis:
                mode = "normal"
            else:
                mode = "compact" if available >= compact_width else "icon"
        else:
            if available >= normal_width + hysteresis:
                mode = "normal"
            elif available >= compact_width + hysteresis:
                mode = "compact"
            else:
                mode = "icon"
        self._set_navigation_mode(mode)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_navigation_density()

    def closeEvent(self, event):
        if not self.confirm_save():
            event.ignore()
            return
        self.updater.stop()
        self.video_tab.shutdown()
        super().closeEvent(event)
