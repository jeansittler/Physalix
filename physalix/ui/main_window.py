"""Fenêtre principale et navigation de Physalix."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout
from physalix.ui.components import role
from physalix.ui.branding import BrandLogo, application_icon
from physalix.ui.icons import icon

from physalix.ui.data_tab import DataTab
from physalix.ui.graph_tab import GraphTab
from physalix.ui.modeling_tab import ModelingTab
from physalix.ui.video_tab import VideoTab
from physalix.ui.calculations_tab import CalculationsTab
from physalix.ui.statistics_tab import StatisticsTab
from physalix.ui.graph_workspace import GraphWorkspace, ModelingWorkspace
from physalix.ui.project_files import ProjectFiles
from physalix.ui.updates import UpdateController
from physalix import __development__, __version__


class MainWindow(QMainWindow, ProjectFiles):
    """Accueillir les espaces de travail de l'application."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Physalix — {__version__}" if __development__ else "Physalix")
        self.setWindowIcon(application_icon())
        self.resize(1280, 760)
        self.setMinimumSize(640, 420)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainNavigation")
        self.tabs.setDocumentMode(True)
        self.tabs.setIconSize(QSize(22, 22))
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setUsesScrollButtons(True)
        brand = role(QWidget(), "brand")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(24, 0, 24, 0)
        brand_layout.setSpacing(0)
        brand_layout.addWidget(BrandLogo())
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

        self.statusBar().showMessage(
            f"Version de développement {__version__} · mises à jour désactivées"
            if __development__ else "Prêt"
        )
        self.setup_files()
        self.updater = UpdateController(self)

    def update_navigation(self, *args):
        for index, name in enumerate(("data", "graph", "model", "video", "calculations", "statistics")):
            self.tabs.setTabIcon(index, icon(name, index == self.tabs.currentIndex()))

    def closeEvent(self, event):
        if not self.confirm_save():
            event.ignore()
            return
        self.updater.stop()
        self.video_tab.shutdown()
        super().closeEvent(event)
