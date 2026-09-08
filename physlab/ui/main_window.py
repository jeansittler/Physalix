"""Fenêtre principale et navigation de Physalyx."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout
from physlab.ui.components import label, role
from physlab.ui.icons import icon

from physlab.ui.data_tab import DataTab
from physlab.ui.graph_tab import GraphTab
from physlab.ui.modeling_tab import ModelingTab
from physlab.ui.video_tab import VideoTab
from physlab.ui.calculations_tab import CalculationsTab
from physlab.ui.statistics_tab import StatisticsTab
from physlab.ui.graph_workspace import GraphWorkspace, ModelingWorkspace
from physlab.ui.project_files import ProjectFiles


class MainWindow(QMainWindow, ProjectFiles):
    """Accueillir les espaces de travail de l'application."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Physalyx")
        self.resize(1280, 760)
        self.setMinimumSize(640, 420)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setIconSize(QSize(20, 20))
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setUsesScrollButtons(True)
        brand = role(QWidget(), "brand")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(24, 8, 24, 8)
        brand_layout.setSpacing(0)
        brand_layout.addWidget(label("Physalyx", "brandTitle"))
        tagline = label("Observer • Mesurer • Comprendre", "muted")
        tagline.setWordWrap(False)
        brand_layout.addWidget(tagline)
        self.tabs.setCornerWidget(brand, Qt.Corner.TopLeftCorner)
        self.data_tab = DataTab()
        self.graph_tab = GraphWorkspace(self.data_tab.model)
        self.tabs.addTab(self.data_tab, "Données / Tableur")
        self.tabs.addTab(self.graph_tab, "Graphique")
        self.modeling_tab = ModelingWorkspace(self.graph_tab)
        self.tabs.addTab(self.modeling_tab, "Modélisation")
        self.graph_tab.modeling_requested.connect(lambda: self.tabs.setCurrentWidget(self.modeling_tab))
        self.modeling_tab.graph_requested.connect(lambda: self.tabs.setCurrentWidget(self.graph_tab))
        self.video_tab = VideoTab(self.data_tab.model)
        self.tabs.addTab(self.video_tab, "Pointage vidéo")
        self.calculations_tab = CalculationsTab(self.data_tab.model)
        self.tabs.addTab(self.calculations_tab, "Calculs")
        self.statistics_tab = StatisticsTab(self.data_tab)
        self.tabs.addTab(self.statistics_tab, "Statistiques")
        self.tabs.currentChanged.connect(self.update_navigation)
        self.update_navigation()
        self.setCentralWidget(self.tabs)

        self.statusBar().showMessage("Physalyx — Prêt")
        self.setup_files()

    def update_navigation(self, *args):
        for index, name in enumerate(("data", "graph", "model", "video", "calculations", "statistics")):
            self.tabs.setTabIcon(index, icon(name, index == self.tabs.currentIndex()))

    def closeEvent(self, event):
        if not self.confirm_save():
            event.ignore()
            return
        self.video_tab.shutdown()
        super().closeEvent(event)
