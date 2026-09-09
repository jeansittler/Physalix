"""Tangente simple et droite horizontale, superposables sur une même courbe."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from physalix.curve_guides import curve_interpolator, model_plateau, tangent_at


class CurveGuidesTool(QWidget):
    def __init__(self, graph):
        super().__init__(graph)
        self.graph, self.active, self.curve = graph, False, None
        self.identity = None
        self.restore_settings = False
        self.tangent_result = None
        self.plateau_linked = False
        self.sources = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        row.addWidget(QLabel('Courbe'))
        self.source = QComboBox()
        self.source.setMinimumContentsLength(16)
        self.source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.source, 1)
        self.tangent_on = QCheckBox('Tangente')
        self.asymptote_on = QCheckBox('Asymptote horizontale')
        row.addWidget(self.tangent_on)
        row.addWidget(self.asymptote_on)
        close = QPushButton('Masquer')
        close.clicked.connect(self.close_tool)
        row.addWidget(close)
        layout.addLayout(row)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('x₀'))
        self.x = self.spin('Abscisse du point de tangence')
        controls.addWidget(self.x)
        self.pick = QPushButton('Choisir un point')
        self.pick.setCheckable(True)
        self.pick.setToolTip('Cliquez près de la courbe pour choisir le point de tangence. Échap annule ce choix.')
        controls.addWidget(self.pick)
        controls.addWidget(QLabel('y∞'))
        self.level = self.spin('Valeur de l’asymptote horizontale')
        controls.addWidget(self.level)
        self.plateau_button = QPushButton('Palier du modèle')
        self.plateau_button.clicked.connect(self.use_plateau)
        controls.addWidget(self.plateau_button)
        layout.addLayout(controls)
        self.readout = QLabel()
        self.readout.setTextFormat(Qt.TextFormat.PlainText)
        self.readout.setWordWrap(True)
        self.readout.setStyleSheet('font-weight: 600;')
        layout.addWidget(self.readout)
        self.hint = QLabel()
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.tangent = pg.PlotCurveItem(pen=pg.mkPen('#d97706', width=2.5))
        self.interpolation = pg.PlotCurveItem(pen=pg.mkPen('#64748b', width=1))
        self.marker = pg.ScatterPlotItem(size=10, brush='#d97706', pen='w')
        self.asymptote = pg.InfiniteLine(angle=0, movable=True,
                                       pen=pg.mkPen('#7c3aed', width=2, style=Qt.PenStyle.DashLine),
                                       hoverPen=pg.mkPen('#7c3aed', width=3))
        self.tangent_label = pg.TextItem(color='#b45309', anchor=(0, 1), fill=pg.mkBrush(255,255,255,235))
        self.level_label = pg.TextItem(color='#7c3aed', anchor=(1, 1), fill=pg.mkBrush(255,255,255,235))
        self.items = (self.interpolation, self.tangent, self.marker, self.asymptote, self.tangent_label, self.level_label)
        for item in self.items:
            graph.plot.addItem(item, ignoreBounds=True)
            item.setZValue(7)
        self.interpolation.setZValue(2)
        self.source.currentIndexChanged.connect(self.selection_changed)
        self.x.valueChanged.connect(self.calculate)
        self.level.valueChanged.connect(self.level_edited)
        self.asymptote.sigPositionChanged.connect(self.line_dragged)
        self.tangent_on.toggled.connect(self.calculate)
        self.asymptote_on.toggled.connect(self.calculate)
        self.pick.toggled.connect(self.calculate)
        graph.plot.scene().sigMouseClicked.connect(self.scene_clicked)
        graph.plot.getViewBox().sigRangeChanged.connect(self.draw)
        graph.right_view.sigRangeChanged.connect(self.draw)
        from PySide6.QtGui import QKeySequence, QShortcut
        shortcut = QShortcut(QKeySequence('Escape'), graph)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(lambda: self.pick.setChecked(False))
        self.close_tool()

    @staticmethod
    def spin(name):
        spin = QDoubleSpinBox()
        spin.setDecimals(9)
        spin.setRange(-1e100, 1e100)
        spin.setAccessibleName(name)
        spin.setMaximumWidth(160)
        spin.setKeyboardTracking(False)
        return spin

    def open_tool(self, mode):
        self.graph.tangent_tool.close_tool()
        self.graph.conductimetry_tool.close_tool()
        self.graph.set_interval_editing(False)
        if not self.active:
            self.restore_settings = self.graph.settings_button.isChecked()
            self.graph.settings_button.setChecked(False)
        self.active = True
        self.show()
        (self.tangent_on if mode == 'tangent' else self.asymptote_on).setChecked(True)
        self.sync()
        if mode == 'tangent':
            self.pick.setChecked(True)

    def close_tool(self):
        if self.active and self.restore_settings:
            self.graph.settings_button.setChecked(True)
        self.active = False
        self.pick.setChecked(False)
        self.hide()
        for item in self.items:
            item.hide()

    def selected(self):
        index = self.source.currentIndex()
        return self.sources[index] if 0 <= index < len(self.sources) else (None, None)

    def sync(self):
        if not self.active:
            return
        previous = self.selected()
        self.source.blockSignals(True)
        self.source.clear()
        self.sources = []
        for series in self.graph.series:
            if not series.visible.isChecked():
                continue
            self.sources.append((series, None))
            self.source.addItem(f'S{series.number} · mesures · {self.graph.axis_label(series.key()[1])}')
            for fit in series.fits:
                self.sources.append((series, fit))
                self.source.addItem(f'S{series.number} · modélisation {fit.number}')
        index = next((i for i, (s, f) in enumerate(self.sources) if s is previous[0] and f is previous[1]), -1)
        if index < 0 and (previous[1] is not None or (self.identity is not None and self.identity[2] is not None)):
            # Une modélisation supprimée ne doit pas être remplacée silencieusement.
            index = -1
        elif index < 0:
            current = self.graph.series_stack.currentWidget()
            index = next((i for i, (s, f) in enumerate(self.sources) if s is current), 0)
        self.source.setCurrentIndex(index)
        self.source.blockSignals(False)
        self.selection_changed()

    def selection_changed(self, *args):
        from physalix.ui.graph_tab import paired_values
        series, fit = self.selected()
        if series is None:
            self.curve = None
            self.calculate()
            return
        identity = (series.number, series.key(), fit.number if fit else None)
        xs, ys = (fit.result.x, fit.result.y) if fit else paired_values(self.graph.model.rows, *series.key())[:2]
        try:
            self.curve = curve_interpolator(xs, ys)
            self.curve_error = ''
        except ValueError as error:
            self.curve = None
            self.curve_error = str(error)
        if identity != self.identity:
            self.identity = identity
            self.plateau_linked = False
            self.x.blockSignals(True)
            self.x.setValue(float(min(xs)) if len(xs) else 0)
            self.x.blockSignals(False)
            self.level.blockSignals(True)
            self.level.setValue(float(ys[int(np.argmax(xs))]) if len(xs) else 0)
            self.level.blockSignals(False)
        if self.plateau_linked and fit:
            value = model_plateau(fit.kind, fit.result.parameters)
            if value is not None:
                self.level.blockSignals(True)
                self.level.setValue(value)
                self.level.blockSignals(False)
            else:
                self.plateau_linked = False
        self.calculate()

    def level_edited(self, *args):
        self.plateau_linked = False
        self.calculate()

    def line_dragged(self, *args):
        if not self.active:
            return
        self.level.blockSignals(True)
        self.level.setValue(self.asymptote.value())
        self.level.blockSignals(False)
        self.level_edited()

    def use_plateau(self):
        _, fit = self.selected()
        value = model_plateau(fit.kind, fit.result.parameters) if fit else None
        if value is not None:
            self.level.blockSignals(True)
            self.level.setValue(value)
            self.level.blockSignals(False)
            self.plateau_linked = True
            self.calculate()

    def calculate(self, *args):
        if not self.active:
            return
        series, fit = self.selected()
        self.tangent_result = None
        self.x.setEnabled(self.tangent_on.isChecked() and series is not None)
        self.pick.setEnabled(self.tangent_on.isChecked() and self.curve is not None)
        self.level.setEnabled(self.asymptote_on.isChecked() and series is not None)
        self.plateau_button.setEnabled(self.asymptote_on.isChecked() and fit is not None
                                      and model_plateau(fit.kind, fit.result.parameters) is not None)
        messages, hints = [], []
        if series is None:
            self.readout.setText('Choisissez une courbe visible dans la liste.')
            self.hint.clear()
            for item in self.items:
                item.hide()
            return
        xunit, yunit = [self.graph.model.units[c] for c in series.key()]
        self.graph.place_items(self.items, series)
        xunit, yunit = [u if u != 'Sans unité' else '' for u in (xunit, yunit)]
        if self.tangent_on.isChecked():
            try:
                if self.curve is None:
                    raise ValueError(self.curve_error)
                y, slope = tangent_at(self.curve, self.x.value())
                self.tangent_result = self.x.value(), y, slope
                slope_unit = f'{yunit or "1"}/({xunit})' if xunit else yunit
                messages.append(f'Tangente : x₀ = {self.x.value():.6g} {xunit} · y₀ = {y:.6g} {yunit} · pente ≈ {slope:.6g} {slope_unit}')
                hints.append('Tangente à l’interpolation de la modélisation.' if fit else 'Tangente estimée par interpolation des mesures (sensible au bruit).')
            except ValueError as error:
                messages.append(str(error))
        if self.asymptote_on.isChecked():
            messages.append(f'Asymptote horizontale : y = {self.level.value():.6g} {yunit}')
            hints.append('Palier lié au modèle en +∞.' if self.plateau_linked else
                         'Palier manuel : déplacez la droite violette ou saisissez y∞ ; sa valeur est à valider.')
        if self.pick.isChecked() and self.tangent_on.isChecked():
            hints.insert(0, 'Cliquez près de la courbe pour placer la tangente.')
        self.readout.setText('\n'.join(messages).replace('.', ','))
        self.hint.setText(' '.join(hints))
        self.draw()

    def scene_clicked(self, event):
        if not self.active or not self.pick.isChecked() or not self.tangent_on.isChecked() or self.curve is None:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        view = self.graph.view_for_series(self.selected()[0])
        if not view.sceneBoundingRect().contains(event.scenePos()):
            return
        position = view.mapSceneToView(event.scenePos())
        x = float(np.clip(position.x(), self.curve.x[0], self.curve.x[-1]))
        from PySide6.QtCore import QPointF
        delta = view.mapViewToScene(QPointF(x, float(self.curve(x)))) - event.scenePos()
        if delta.x()**2 + delta.y()**2 > 18**2:
            return
        self.x.setValue(x)
        self.pick.setChecked(False)
        event.accept()

    def draw(self, *args):
        if not self.active or self.selected()[0] is None:
            return
        tangent_visible = self.tangent_on.isChecked() and self.tangent_result is not None
        self.interpolation.setVisible(tangent_visible and self.selected()[1] is None)
        if tangent_visible and self.selected()[1] is None:
            samples = np.linspace(self.curve.x[0], self.curve.x[-1], 500)
            self.interpolation.setData(samples, self.curve(samples))
        for item in (self.tangent, self.marker, self.tangent_label):
            item.setVisible(tangent_visible)
        xmin, xmax = self.graph.view_for_series(self.selected()[0]).viewRange()[0]
        if tangent_visible:
            x, y, slope = self.tangent_result
            ends = np.array([xmin, xmax])
            self.tangent.setData(ends, y + slope*(ends-x))
            self.marker.setData([x], [y])
            self.tangent_label.setText(f'Tangente · pente ≈ {slope:.5g}'.replace('.', ','))
            self.tangent_label.setAnchor((1, 1) if x > (xmin+xmax)/2 else (0, 1))
            self.tangent_label.setPos(x, y)
        visible = self.asymptote_on.isChecked()
        self.asymptote.setVisible(visible)
        self.level_label.setVisible(visible)
        if visible:
            self.asymptote.blockSignals(True)
            self.asymptote.setValue(self.level.value())
            self.asymptote.blockSignals(False)
            self.level_label.setText(f'y∞ = {self.level.value():.6g}'.replace('.', ','))
            self.level_label.setPos(xmax - .02*(xmax-xmin), self.level.value())
