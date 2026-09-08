"""Construction interactive des tangentes parallèles."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSlider, QPushButton
from physlab.tangents import parallel_tangents


class TangentTool(QWidget):
    def __init__(self, graph):
        super().__init__(graph)
        self.graph, self.result, self.signature = graph, None, None
        self.active = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        row.addWidget(QLabel('Tangentes · pH = f(V)'))
        self.series = QComboBox()
        row.addWidget(self.series)
        row.addWidget(QLabel('Inclinaison'))
        self.slope = QSlider(Qt.Orientation.Horizontal)
        self.slope.setRange(5, 85)
        self.slope.setValue(25)
        self.slope.setToolTip('Pente commune en pourcentage de la pente maximale du saut')
        row.addWidget(self.slope, 1)
        close = QPushButton('Masquer')
        close.clicked.connect(self.close_tool)
        row.addWidget(close)
        layout.addLayout(row)
        self.readout = QLabel()
        self.readout.setWordWrap(True)
        self.readout.setTextFormat(Qt.TextFormat.PlainText)
        self.readout.setStyleSheet('font-weight: 600; color: #0f766e;')
        layout.addWidget(self.readout)
        hint = QLabel('Déplacez les bornes pour isoler un saut, puis réglez l’inclinaison. Orange : tangentes · Vert : parallèle médiane et équivalence. Courbe interpolée ; estimation à vérifier sur les mesures.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.region = pg.LinearRegionItem(brush=pg.mkBrush(15, 118, 110, 12))
        graph.plot.addItem(self.region, ignoreBounds=True)
        self.region.setZValue(-5)
        self.items = []
        self.interpolation = self.line('#64748b', 1)
        self.tangents = [self.line('#d97706', 2) for _ in range(2)]
        self.middle = self.line('#0f766e', 2, Qt.PenStyle.DashLine)
        self.normal = self.line('#64748b', 1, Qt.PenStyle.DashLine)
        self.projection = self.line('#0f766e', 2, Qt.PenStyle.DotLine)
        self.dots = pg.ScatterPlotItem(size=9, brush='#0f766e', pen='w')
        self.label = pg.TextItem(anchor=(0, 1), color='#0f766e', fill=pg.mkBrush(255, 255, 255, 235))
        for item in (self.dots, self.label):
            graph.plot.addItem(item, ignoreBounds=True)
            self.items.append(item)
            item.setZValue(8)
        self.region.sigRegionChanged.connect(self.calculate)
        self.slope.valueChanged.connect(self.calculate)
        self.series.currentIndexChanged.connect(self.selection_changed)
        graph.plot.getViewBox().sigRangeChanged.connect(self.draw)
        graph.right_view.sigRangeChanged.connect(self.draw)
        graph.plot.getViewBox().sigResized.connect(self.draw)
        self.close_tool()

    def line(self, color, width, style=Qt.PenStyle.SolidLine):
        item = pg.PlotCurveItem(pen=pg.mkPen(color, width=width, style=style))
        self.graph.plot.addItem(item, ignoreBounds=True)
        item.setZValue(4)
        self.items.append(item)
        return item

    def open_tool(self):
        if hasattr(self.graph, 'curve_guides_tool'):
            self.graph.curve_guides_tool.close_tool()
        if hasattr(self.graph, 'conductimetry_tool'):
            self.graph.conductimetry_tool.close_tool()
        self.active = True
        self.show()
        self.region.show()
        self.sync()

    def close_tool(self):
        self.active = False
        self.hide()
        self.region.hide()
        for item in self.items:
            item.hide()

    def sync(self):
        if not self.active:
            return
        selected = self.series.currentData()
        self.series.blockSignals(True)
        self.series.clear()
        for series in self.graph.series:
            if series.visible.isChecked():
                self.series.addItem(f'S{series.number} · {self.graph.axis_label(series.key()[1])}', series)
        index = self.series.findData(selected)
        if index < 0:
            index = next((i for i in range(self.series.count()) if 'ph' in self.series.itemText(i).lower()), 0)
        self.series.setCurrentIndex(index)
        self.series.blockSignals(False)
        self.selection_changed()

    def selection_changed(self, *args):
        from physlab.ui.graph_tab import paired_values
        series = self.series.currentData()
        if series is None:
            self.fail('Affichez une série avec le volume en X et le pH en Y.')
            return
        xs, ys, _ = paired_values(self.graph.model.rows, *series.key())
        signature = (series.number, series.key(), tuple(xs), tuple(ys))
        if signature != self.signature:
            self.signature = signature
            self.region.blockSignals(True)
            if xs and min(xs) < max(xs):
                self.region.setBounds((min(xs), max(xs)))
                self.region.setRegion((min(xs), max(xs)))
            self.region.blockSignals(False)
        self.calculate()

    def fail(self, message):
        self.result = None
        self.readout.setText(message)
        for item in self.items:
            item.hide()

    def calculate(self, *args):
        if not self.active:
            return
        from physlab.ui.graph_tab import paired_values
        series = self.series.currentData()
        if series is None:
            return
        self.graph.place_items((self.region, *self.items), series)
        xs, ys, skipped = paired_values(self.graph.model.rows, *series.key())
        try:
            self.result = parallel_tangents(xs, ys, self.slope.value()/100, self.region.getRegion())
        except ValueError as error:
            self.fail(str(error))
            return
        unit = self.graph.model.units[series.key()[0]]
        unit = '' if unit == 'Sans unité' else unit
        self.caption = f'Véq ≈ {self.result.volume:.4g} {unit}'.strip().replace('.', ',')
        self.readout.setText(f'{self.caption}   ·   pH ≈ {self.result.ph:.4g}   ·   Inclinaison : {self.slope.value()} %' + (f'   ·   {skipped} ligne(s) ignorée(s)' if skipped else ''))
        self.draw()

    def draw(self, *args):
        if not self.active or self.result is None:
            return
        r = self.result
        for item in self.items:
            item.show()
        x = np.linspace(r.curve.x[0], r.curve.x[-1], 600)
        self.interpolation.setData(x, r.curve(x))
        a, b = r.contacts
        ends = np.array([a-(b-a)*0.3, b+(b-a)*0.3])
        for line, intercept in zip(self.tangents, r.intercepts):
            line.setData(ends, r.slope*ends+intercept)
        self.middle.setData(ends, r.slope*ends+np.mean(r.intercepts))
        view = self.graph.view_for_series(self.series.currentData())
        dx, dy = view.viewPixelSize()
        nx, ny = -r.slope*dx*dx, dy*dy
        offsets = (np.asarray(r.intercepts)-np.mean(r.intercepts))/(ny-r.slope*nx)
        self.normal.setData(r.volume+offsets*nx, r.ph+offsets*ny)
        self.projection.setData([r.volume, r.volume], [view.viewRange()[1][0], r.ph])
        self.dots.setData([a, b, r.volume], [float(r.curve(a)), float(r.curve(b)), r.ph])
        self.label.setText(self.caption)
        self.label.setPos(r.volume, view.viewRange()[1][0]+0.04*(view.viewRange()[1][1]-view.viewRange()[1][0]))
