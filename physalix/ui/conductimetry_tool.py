"""Deux zones affines réglables et lecture du volume équivalent sur le graphique."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)
from physalix.conductimetry import fit_equivalence


class ConductimetryTool(QWidget):
    colors = ('#d97706', '#7c3aed')

    def __init__(self, graph):
        super().__init__(graph)
        self.graph, self.active, self.result = graph, False, None
        self.source = None
        self.restore_settings = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        title = QLabel('Conductimétrie')
        row.addWidget(title)
        self.series = QComboBox()
        self.series.setAccessibleName('Série du titrage conductimétrique')
        row.addWidget(self.series, 1)
        self.bounds_button = QPushButton('Intervalles…')
        self.bounds_button.clicked.connect(self.edit_bounds)
        row.addWidget(self.bounds_button)
        reset = QPushButton('Réinitialiser les zones')
        reset.clicked.connect(self.reset_regions)
        row.addWidget(reset)
        close = QPushButton('Masquer')
        close.clicked.connect(self.close_tool)
        row.addWidget(close)
        layout.addLayout(row)
        result_row = QHBoxLayout()
        self.readout = QLabel()
        self.readout.setTextFormat(Qt.TextFormat.PlainText)
        self.readout.setWordWrap(True)
        self.readout.setStyleSheet('font-size: 16px; font-weight: 600; color: #0f766e;')
        result_row.addWidget(self.readout, 1)
        self.frame_button = QPushButton('Cadrer le résultat')
        self.frame_button.clicked.connect(self.frame_result)
        result_row.addWidget(self.frame_button)
        layout.addLayout(result_row)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.warning = QLabel()
        self.warning.setTextFormat(Qt.TextFormat.PlainText)
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet('color: #9a5800;')
        layout.addWidget(self.warning)
        self.setToolTip('Déplacez les zones colorées ou leurs bornes : orange avant l’équivalence, violet après. '
                        'Traits pleins : ajustements ; pointillés : prolongements. Choisissez le volume en X.')
        self.regions, self.items = [], []
        self.lines, self.extensions = [], []
        for color in self.colors:
            shade = QColor(color)
            shade.setAlpha(20)
            region = pg.LinearRegionItem(brush=pg.mkBrush(shade), pen=pg.mkPen(color, width=1.5))
            graph.plot.addItem(region, ignoreBounds=True)
            region.setZValue(-4)
            region.sigRegionChanged.connect(self.calculate)
            self.regions.append(region)
            self.lines.append(self.line(color, 3))
            self.extensions.append(self.line(color, 2, Qt.PenStyle.DashLine))
        self.projection = self.line('#0f766e', 2, Qt.PenStyle.DotLine)
        self.dot = pg.ScatterPlotItem(size=11, brush='#0f766e', pen='w')
        self.label = pg.TextItem(anchor=(0, 1), color='#0f766e', fill=pg.mkBrush(255, 255, 255, 240))
        for item in (self.dot, self.label):
            graph.plot.addItem(item, ignoreBounds=True)
            item.setZValue(9)
            self.items.append(item)
        self.series.currentIndexChanged.connect(self.selection_changed)
        graph.plot.getViewBox().sigRangeChanged.connect(self.draw)
        graph.right_view.sigRangeChanged.connect(self.draw)
        self.close_tool()

    def line(self, color, width, style=Qt.PenStyle.SolidLine):
        line = pg.PlotCurveItem(pen=pg.mkPen(color, width=width, style=style))
        self.graph.plot.addItem(line, ignoreBounds=True)
        line.setZValue(5)
        self.items.append(line)
        return line

    def open_tool(self):
        if hasattr(self.graph, 'curve_guides_tool'):
            self.graph.curve_guides_tool.close_tool()
        self.graph.tangent_tool.close_tool()
        self.graph.set_interval_editing(False)
        if not self.active:
            self.restore_settings = self.graph.settings_button.isChecked()
            self.graph.settings_button.setChecked(False)
        self.active = True
        self.show()
        self.sync()

    def close_tool(self):
        if self.active and self.restore_settings:
            self.graph.settings_button.setChecked(True)
        self.active = False
        self.hide()
        for item in (*self.regions, *self.items):
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
            current = self.graph.series_stack.currentWidget()
            index = max(0, self.series.findData(current))
        self.series.setCurrentIndex(index)
        self.series.blockSignals(False)
        self.selection_changed()

    def values(self):
        from physalix.ui.graph_tab import paired_values
        series = self.series.currentData()
        return paired_values(self.graph.model.rows, *series.key()) if series else ([], [], 0)

    def selection_changed(self, *args):
        series = self.series.currentData()
        identity = (series.number, series.key()) if series else None
        if identity != self.source:
            self.source = identity
            self.reset_regions()
        else:
            self.calculate()

    def reset_regions(self):
        xs, _, _ = self.values()
        unique = np.unique(xs)
        if len(unique) < 4:
            self.source = None
            for region in self.regions:
                region.hide()
            self.fail('Choisissez une série avec au moins quatre volumes distincts, en X, et la conductivité en Y.')
            return
        split = max(1, int((len(unique) - 1) * .35))
        bounds = ((unique[0], unique[split]), (unique[-split-1], unique[-1]))
        for region, interval in zip(self.regions, bounds):
            region.blockSignals(True)
            region.setRegion(interval)
            region.blockSignals(False)
            region.show()
        self.calculate()

    def fail(self, message):
        self.result = None
        self.readout.setText(message)
        self.details.clear()
        self.warning.hide()
        self.frame_button.setEnabled(False)
        for item in self.items:
            item.hide()

    def calculate(self, *args):
        if not self.active:
            return
        xs, ys, skipped = self.values()
        if self.series.currentData() is None:
            for region in self.regions:
                region.hide()
            self.fail('Affichez une série avec le volume en X et la conductivité en Y.')
            return
        for region in self.regions:
            region.show()
        self.graph.place_items((*self.regions, *self.items), self.series.currentData())
        try:
            self.result = fit_equivalence(xs, ys, *(region.getRegion() for region in self.regions))
        except ValueError as error:
            self.fail(str(error))
            return
        series = self.series.currentData()
        unit = self.graph.model.units[series.key()[0]]
        unit = '' if unit == 'Sans unité' else unit
        self.caption = f'Véq ≈ {self.result.volume:.6g} {unit}'.strip().replace('.', ',')
        self.readout.setText(self.caption)
        texts = []
        for color, branch in zip(('Orange', 'Violet'), self.result.branches):
            quality = f'{branch.r2:.5g}' if branch.r2 is not None else 'non défini (Y constant)'
            texts.append(f'{color} : Y = {branch.slope:.5g} × V {branch.intercept:+.5g} · '
                         f'n = {branch.count} · R² = {quality}')
        self.details.setText('\n'.join(texts).replace('.', ','))
        self.details.setToolTip('Déplacez les zones colorées pour choisir les portions rectilignes. '
                                'Les bornes sont incluses. R² décrit la qualité de chaque ajustement.')
        self.warning.setText(self.result.warning + (f' {skipped} ligne(s) incomplète(s) ignorée(s).' if skipped else ''))
        self.warning.setVisible(bool(self.warning.text()))
        self.frame_button.setEnabled(True)
        self.draw()

    def draw(self, *args):
        if not self.active or self.result is None:
            return
        result = self.result
        for item in self.items:
            item.show()
        for line, extension, branch in zip(self.lines, self.extensions, result.branches):
            ends = np.array(branch.bounds)
            line.setData(ends, branch.at(ends))
            near = min(ends, key=lambda x: abs(x - result.volume))
            extension.setData([near, result.volume], branch.at([near, result.volume]))
        view = self.graph.view_for_series(self.series.currentData())
        low, high = view.viewRange()[1]
        self.projection.setData([result.volume, result.volume], [low, result.ordinate])
        self.dot.setData([result.volume], [result.ordinate])
        self.label.setText(self.caption)
        xlow, xhigh = view.viewRange()[0]
        self.label.setAnchor((1, 1) if result.volume > (xlow + xhigh)/2 else (0, 1))
        self.label.setPos(result.volume, low + .04 * (high - low))

    def frame_result(self):
        if self.result is None:
            return
        xs, ys, _ = self.values()
        self.graph.view_for_series(self.series.currentData()).setRange(xRange=(min(*xs, self.result.volume), max(*xs, self.result.volume)),
                                 yRange=(min(*ys, self.result.ordinate), max(*ys, self.result.ordinate)), padding=.08)

    def edit_bounds(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Intervalles du titrage conductimétrique')
        layout = QFormLayout(dialog)
        series = self.series.currentData()
        if series is not None:
            caption = QLabel(f'Bornes en abscisse : {self.graph.axis_label(series.key()[0])}')
            caption.setTextFormat(Qt.TextFormat.PlainText)
            layout.addRow(caption)
        controls = []
        for name, region in zip(('Zone 1 · orange', 'Zone 2 · violette'), self.regions):
            for title, value in zip(('début', 'fin'), region.getRegion()):
                spin = QDoubleSpinBox()
                spin.setDecimals(9)
                spin.setRange(-1e12, 1e12)
                spin.setValue(value)
                layout.addRow(f'{name} · {title}', spin)
                controls.append(spin)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            for index, region in enumerate(self.regions):
                region.blockSignals(True)
                region.setRegion([controls[index*2].value(), controls[index*2+1].value()])
                region.blockSignals(False)
                region.show()
            self.calculate()
