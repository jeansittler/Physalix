"""Graphiques indépendants en onglets, comparaison ou fenêtres libres."""
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QMdiArea,
                               QMdiSubWindow, QPushButton, QStackedWidget, QTabBar, QVBoxLayout, QWidget)
from physlab.ui.graph_tab import GraphTab
from physlab.ui.modeling_tab import ModelingTab


class GraphWindow(QMdiSubWindow):
    def __init__(self, owner, graph):
        super().__init__()
        self.owner, self.graph = owner, graph
        self.setWidget(graph)
        from physlab.ui.icons import icon
        self.setWindowIcon(icon('graph'))
        self.setWindowFlags(Qt.WindowType.SubWindow | Qt.WindowType.CustomizeWindowHint |
                            Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def closeEvent(self, event):
        if len(self.owner.windows) == 1:
            event.ignore()
            return
        self.owner.windows.remove(self)
        self.owner.graph_removed.emit(self.graph)
        if self.owner.arrangement.currentIndex() in (1, 2):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self.owner.arrange)
        event.accept()


class GraphWorkspace(QWidget):
    graph_added = Signal(object)
    graph_removed = Signal(object)
    graph_activated = Signal(object)
    modeling_requested = Signal()

    def __init__(self, model):
        super().__init__()
        self.model, self.windows, self.number = model, [], 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 6, 12, 0)
        self.add_button = QPushButton('Nouveau graphique')
        self.add_button.clicked.connect(self.add_graph)
        bar.addWidget(self.add_button)
        bar.addWidget(QLabel('Disposition'))
        self.arrangement = QComboBox()
        self.arrangement.addItems(['Onglets', 'Côte à côte', 'Superposés', 'Libre'])
        self.arrangement.currentIndexChanged.connect(self.arrange)
        bar.addWidget(self.arrangement)
        rename = QPushButton('Renommer')
        rename.clicked.connect(self.rename_graph)
        bar.addWidget(rename)
        bar.addStretch()
        layout.addLayout(bar)
        self.area = QMdiArea()
        self.area.setTabsMovable(True)
        self.area.setTabsClosable(True)
        self.area.setDocumentMode(True)
        self.area.setViewMode(QMdiArea.ViewMode.TabbedView)
        self.area.subWindowActivated.connect(self.activated)
        layout.addWidget(self.area, 1)
        self.add_graph()

    @property
    def active_graph(self):
        area = self.__dict__.get('area')
        window = area.activeSubWindow() if area is not None else None
        if window is not None and window in self.windows:
            return window.graph
        return self.windows[0].graph if self.windows else None

    def __getattr__(self, name):
        # Les commandes existantes de l'application ciblent le graphique actif.
        if 'windows' in self.__dict__ and self.windows:
            graph = self.active_graph
            if graph is not None:
                return getattr(graph, name)
        raise AttributeError(name)

    def add_graph(self):
        graph = GraphTab(self.model)
        self.number += 1
        window = GraphWindow(self, graph)
        window.setWindowTitle(f'Graphique {self.number}')
        self.windows.append(window)
        self.area.addSubWindow(window)
        graph.settings_requested.connect(lambda: self.edit_graph(graph))
        graph.modeling_requested.connect(lambda: self.request_modeling(graph))
        self.graph_added.emit(graph)
        window.show()
        self.area.setActiveSubWindow(window)
        self.arrange()
        return graph

    def activated(self, window):
        if window is not None and window in self.windows:
            self.graph_activated.emit(window.graph)

    def edit_graph(self, graph):
        window = next(w for w in self.windows if w.graph is graph)
        self.area.setActiveSubWindow(window)
        self.arrangement.setCurrentIndex(0)

    def request_modeling(self, graph):
        self.edit_graph(graph)
        self.modeling_requested.emit()

    def rename_graph(self):
        window = next(w for w in self.windows if w.graph is self.active_graph)
        title, accepted = QInputDialog.getText(self, 'Nom du graphique', 'Nom :', text=window.windowTitle())
        if accepted and title.strip():
            window.setWindowTitle(title.strip())

    def arrange(self, *args):
        mode = self.arrangement.currentIndex()
        active = self.active_graph
        self.area.setViewMode(QMdiArea.ViewMode.TabbedView if mode == 0 else QMdiArea.ViewMode.SubWindowView)
        self.area.setTabsClosable(len(self.windows) > 1)
        tab_bar = self.area.findChild(QTabBar)
        if tab_bar is not None:
            tab_bar.setExpanding(False)
        for window in self.windows:
            window.graph.set_compact(mode != 0)
            if mode != 0:
                window.showNormal()
        if mode in (1, 2):
            size = self.area.viewport().size()
            count = len(self.windows)
            for i, window in enumerate(self.windows):
                if mode == 1:
                    start, end = i * size.width() // count, (i + 1) * size.width() // count
                    window.setGeometry(QRect(start, 0, end-start, size.height()))
                else:
                    start, end = i * size.height() // count, (i + 1) * size.height() // count
                    window.setGeometry(QRect(0, start, size.width(), end-start))
        elif mode == 3:
            self.area.cascadeSubWindows()
        if active is not None:
            self.area.setActiveSubWindow(next(w for w in self.windows if w.graph is active))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.__dict__.get('area') is not None and self.arrangement.currentIndex() in (1, 2):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self.arrange)


class ModelingWorkspace(QStackedWidget):
    graph_requested = Signal()

    def __init__(self, graphs):
        super().__init__()
        self.graphs, self.pages = graphs, {}
        for window in graphs.windows:
            self.add_graph(window.graph)
        graphs.graph_added.connect(self.add_graph)
        graphs.graph_removed.connect(self.remove_graph)
        graphs.graph_activated.connect(self.activate)
        self.activate(graphs.active_graph)

    def __getattr__(self, name):
        if self.__dict__.get('pages'):
            page = self.currentWidget()
            if page is not None:
                return getattr(page, name)
        raise AttributeError(name)

    def add_graph(self, graph):
        page = ModelingTab(graph)
        window = next(w for w in self.graphs.windows if w.graph is graph)
        caption = QLabel('Graphique actif : ' + window.windowTitle())
        caption.setTextFormat(Qt.TextFormat.PlainText)
        page.layout().insertWidget(0, caption)
        window.windowTitleChanged.connect(lambda title: caption.setText('Graphique actif : ' + title))
        self.pages[graph] = page
        self.addWidget(page)
        page.graph_requested.connect(lambda: self.show_graph(graph))

    def remove_graph(self, graph):
        page = self.pages.pop(graph)
        self.removeWidget(page)
        page.deleteLater()

    def activate(self, graph):
        if graph in self.pages:
            self.setCurrentWidget(self.pages[graph])

    def show_graph(self, graph):
        self.graphs.edit_graph(graph)
        self.graph_requested.emit()
