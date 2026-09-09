"""Choix des axes et nuage de points lié au tableau de mesures."""

from dataclasses import dataclass
from itertools import combinations
from html import escape
import numpy as np
from math import isfinite

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMenu, QPushButton, QStackedWidget, QVBoxLayout, QWidget, QSizePolicy,
)
import pyqtgraph as pg

from physalix.ui.graph_series import GraphSeries
from physalix.ui.graph_axis import EndAxis
from physalix.ui.graph_legend import SmartLegend
from physalix.ui.theme import LIGHT, SERIES_COLORS
from physalix.ui.components import workspace_layout, role, panel as make_panel


@dataclass(eq=False)
class GraphFit:
    number: int
    result: object
    kind: str
    settings: dict
    curve: object
    extension: object
    color: str


def paired_values(rows, x_column, y_column):
    """Lire les couples sur la même ligne, sans décaler les valeurs manquantes."""
    xs, ys = [], []
    skipped = 0
    if x_column is None or y_column is None or x_column < 0 or y_column < 0:
        return xs, ys, skipped
    for row in rows:
        x_text, y_text = row[x_column], row[y_column]
        if not x_text and not y_text:
            continue
        try:
            x, y = float(x_text.replace(",", ".")), float(y_text.replace(",", "."))
            if not (isfinite(x) and isfinite(y)):
                raise ValueError("Valeur non finie")
        except ValueError:
            skipped += 1
            continue
        xs.append(x)
        ys.append(y)
    return xs, ys, skipped


class InteractivePlot(pg.PlotWidget):
    """Remplacer le menu technique de PyQtGraph par les outils de Physalix."""

    menu_requested = Signal(object)

    def contextMenuEvent(self, event):
        self.menu_requested.emit(event.globalPos())
        event.accept()


class GraphTab(QWidget):
    """Superposer des séries indépendantes dans un repère commun."""

    changed = Signal()
    modeling_requested = Signal()
    settings_requested = Signal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.series = []
        self._next_number = 1
        layout = workspace_layout(self, 760, 520)
        self.content = layout.parentWidget()
        self.workspace_layout = layout
        toolbar = QHBoxLayout()
        add = role(QPushButton("Ajouter une série"), "primary")
        add.clicked.connect(lambda: self.add_series())
        toolbar.addWidget(add)
        model_button = QPushButton("Modéliser…")
        model_button.clicked.connect(self.modeling_requested)
        toolbar.addWidget(model_button)
        toolbar.addStretch()
        reset = QPushButton("Ajuster la vue")
        reset.clicked.connect(self.fit_points)
        toolbar.addWidget(reset)
        layout.addLayout(toolbar)
        self.interval_tools = QWidget()
        interval_layout = QVBoxLayout(self.interval_tools)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        self.interval_hint = QLabel("Déplacez les bornes, puis validez pour calculer la modélisation.")
        self.interval_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.interval_hint.setWordWrap(True)
        interval_layout.addWidget(self.interval_hint)
        interval_actions = QHBoxLayout()
        self.calculate_interval_button = QPushButton("Valider l’intervalle et calculer")
        self.hide_interval_button = QPushButton("Masquer la sélection")
        interval_actions.addWidget(self.calculate_interval_button)
        interval_actions.addWidget(self.hide_interval_button)
        interval_actions.addStretch()
        interval_layout.addLayout(interval_actions)
        self.interval_tools.hide()
        layout.addWidget(self.interval_tools)
        series_row = QHBoxLayout()
        series_label = QLabel("Série à régler")
        self.series_choice = QComboBox()
        self.series_choice.setAccessibleName("Série à régler")
        self.series_choice.setMinimumContentsLength(18)
        self.series_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.series_choice.setMaxVisibleItems(10)
        series_label.setBuddy(self.series_choice)
        self.series_choice.setToolTip("Choisir les réglages d'une série sans masquer les autres courbes")
        self.settings_button = QPushButton("Masquer les réglages")
        self.settings_button.setCheckable(True)
        self.settings_button.setChecked(True)
        self.settings_button.toggled.connect(self.toggle_series_settings)
        series_row.addWidget(series_label)
        series_row.addWidget(self.series_choice, 1)
        series_row.addWidget(self.settings_button)
        layout.addLayout(series_row)
        self.series_stack = QStackedWidget()
        self.series_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.series_choice.currentIndexChanged.connect(self.select_series)
        layout.addWidget(self.series_stack)

        self.plot = InteractivePlot(background=LIGHT.surface, axisItems={
            'bottom': EndAxis('bottom'), 'left': EndAxis('left'), 'right': EndAxis('right')})
        self.right_view = pg.ViewBox()
        self.plot.scene().addItem(self.right_view)
        self.right_view.setZValue(-1)
        self.plot.getAxis('right').linkToView(self.right_view)
        self.right_view.setXLink(self.plot.getViewBox())
        self._item_views = {}
        self.plot.getViewBox().sigResized.connect(self.resize_right_view)
        self.plot.hideAxis('right')
        self.plot.setMinimumSize(200, 220)
        self.plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.plot.getPlotItem().layout.setContentsMargins(8, 40, 20, 8)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.showGrid(x=True, y=True, alpha=0.10)
        for axis_name in ("bottom", "left", "right"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(LIGHT.muted))
            axis.setTextPen(pg.mkPen(LIGHT.text))
            axis.enableAutoSIPrefix(False)
        self.legend = SmartLegend(self.plot.getViewBox(), lambda: self.series)
        self.plot.getPlotItem().legend = self.legend
        self.fit_region = pg.LinearRegionItem(brush=pg.mkBrush(21, 101, 192, 25))
        self.plot.addItem(self.fit_region, ignoreBounds=True)
        self.fit_region.hide()
        self.cross_x = pg.InfiniteLine(angle=90, movable=False,
                                       pen=pg.mkPen("#64748b", style=Qt.PenStyle.DashLine))
        self.cross_y = pg.InfiniteLine(angle=0, movable=False,
                                       pen=pg.mkPen("#64748b", style=Qt.PenStyle.DashLine))
        for line in (self.cross_x, self.cross_y):
            self.plot.addItem(line, ignoreBounds=True)
            line.setZValue(10)
            line.hide()
        plot_panel, plot_layout = make_panel()
        self.plot_panel = plot_panel
        plot_layout.setContentsMargins(4, 4, 4, 4)
        plot_layout.addWidget(self.plot)
        layout.addWidget(plot_panel, 1)
        from physalix.ui.tangent_tool import TangentTool
        self.tangent_tool = TangentTool(self)
        layout.addWidget(self.tangent_tool)
        from physalix.ui.conductimetry_tool import ConductimetryTool
        self.conductimetry_tool = ConductimetryTool(self)
        layout.addWidget(self.conductimetry_tool)
        from physalix.ui.curve_guides_tool import CurveGuidesTool
        self.curve_guides_tool = CurveGuidesTool(self)
        layout.addWidget(self.curve_guides_tool)
        self.coordinates = QLabel("Réticule désactivé — clic droit pour l’activer.")
        self.coordinates.setTextFormat(Qt.TextFormat.PlainText)
        self.coordinates.setWordWrap(False)
        self.coordinates.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        messages = QHBoxLayout()
        messages.addWidget(self.coordinates, 1)
        self.status = QLabel()
        self.status.setWordWrap(False)
        messages.addWidget(self.status)
        layout.addLayout(messages)
        hint = QLabel("Molette : zoomer · Clic droit : zoom, déplacement et réticule.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._build_menu()
        tools = QPushButton("Outils du graphique")
        tools.setMenu(self.context_menu)
        toolbar.insertWidget(2, tools)
        for message in (self.coordinates, self.status, hint):
            role(message, "muted")
        self.plot.menu_requested.connect(self.show_context_menu)
        self.plot.scene().sigMouseMoved.connect(self.track_cursor)
        self.plot.viewport().setMouseTracking(True)
        self.plot.viewport().installEventFilter(self)
        self.plot.getViewBox().sigRangeChanged.connect(self.hide_crosshair)

        # Regrouper les modifications successives, notamment lors d'une recopie.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.sync_columns)
        for signal in (model.dataChanged, model.columnsInserted, model.rowsInserted, model.modelReset):
            signal.connect(self.schedule_refresh)
        model.columnsRemoved.connect(self.columns_removed)
        self.add_series()
        self.compact_button = QPushButton('Réglages de ce graphique')
        self.compact_button.clicked.connect(self.settings_requested)
        self.compact_button.hide()
        layout.insertWidget(0, self.compact_button)
        self._compact_hidden = []
        self.resize_right_view()

    def resize_right_view(self):
        self.right_view.setGeometry(self.plot.getViewBox().sceneBoundingRect())
        self.right_view.linkedViewChanged(self.plot.getViewBox(), self.right_view.XAxis)

    def view_for_series(self, series):
        return self.right_view if series is not None and series.y_axis.currentIndex() == 1 else self.plot.getViewBox()

    def place_items(self, items, series):
        target = self.view_for_series(series)
        for item in items:
            old = self._item_views.get(item, self.plot.getViewBox())
            if old is target:
                continue
            if old is self.plot.getViewBox():
                self.plot.removeItem(item)
            else:
                old.removeItem(item)
            if target is self.plot.getViewBox():
                bounded = any(item is s.points or item is s.line or any(item is f.curve for f in s.fits) for s in self.series)
                self.plot.addItem(item, ignoreBounds=not bounded)
            else:
                target.addItem(item, ignoreBounds=True)
            self._item_views[item] = target

    def remove_plot_item(self, item):
        view = self._item_views.pop(item, self.plot.getViewBox())
        if view is self.plot.getViewBox():
            self.plot.removeItem(item)
        else:
            view.removeItem(item)

    def set_compact(self, compact):
        if compact and not self._compact_hidden:
            def hide_items(layout):
                for i in range(layout.count()):
                    item = layout.itemAt(i)
                    widget = item.widget()
                    if widget is not None and widget not in (self.plot_panel, self.compact_button) and not widget.isHidden():
                        widget.hide()
                        self._compact_hidden.append(widget)
                    elif item.layout():
                        hide_items(item.layout())
            hide_items(self.workspace_layout)
            self.content.setMinimumSize(0, 0)
            self.plot.setMinimumSize(140, 140)
            self.compact_button.show()
        elif not compact:
            for widget in self._compact_hidden:
                widget.show()
            self._compact_hidden.clear()
            self.compact_button.hide()
            self.content.setMinimumSize(760, 520)
            self.plot.setMinimumSize(200, 220)

    def columns_removed(self, parent, first, last):
        count = last - first + 1
        for item in self.series:
            for combo in (item.x_choice, item.y_choice):
                combo.blockSignals(True)
                for index in range(combo.count()):
                    column = combo.itemData(index)
                    combo.setItemData(index, -1 if first <= column <= last else
                                      column - (count if column > last else 0))
                combo.blockSignals(False)
            item._styles = {(x - (count if x > last else 0), y - (count if y > last else 0)): style
                            for (x, y), style in item._styles.items()
                            if x is not None and y is not None and not first <= x <= last and not first <= y <= last}
        self.schedule_refresh()

    def schedule_refresh(self, *args):
        self._refresh_timer.start(0)

    def showEvent(self, event):
        super().showEvent(event)
        self.legend.schedule()

    def set_interval_editing(self, editing):
        if editing:
            self.tangent_tool.close_tool()
            self.conductimetry_tool.close_tool()
            self.curve_guides_tool.close_tool()
        self.fit_region.setVisible(editing)
        self.interval_tools.setVisible(editing)
        if editing:
            self.interval_hint.setText("Déplacez les bornes, puis validez pour calculer la modélisation.")

    def axis_label(self, column):
        if column is None or not 0 <= column < self.model.columnCount():
            return "Grandeur à choisir"
        name = self.model.names[column] or f"Grandeur {column + 1}"
        unit = self.model.units[column]
        return f"{name} ({unit})" if unit and unit != "Sans unité" else name

    def toggle_series_settings(self, visible):
        self.series_stack.setVisible(visible)
        self.settings_button.setText("Masquer les réglages" if visible else "Afficher les réglages")

    def select_series(self, index):
        if 0 <= index < len(self.series):
            self.series_stack.setCurrentWidget(self.series[index])

    def update_series_choice(self):
        current = self.series_stack.currentWidget()
        self.series_choice.blockSignals(True)
        self.series_choice.clear()
        for item in self.series:
            x, y = item.key()
            hidden = " · masquée" if not item.visible.isChecked() else ""
            title = f"S{item.number} : {self.axis_label(y)} en fonction de {self.axis_label(x)}{hidden}"
            self.series_choice.addItem(item.color_button.icon(), title)
            self.series_choice.setItemData(self.series_choice.count() - 1, title, Qt.ItemDataRole.ToolTipRole)
        if current in self.series:
            self.series_choice.setCurrentIndex(self.series.index(current))
        self.series_choice.blockSignals(False)

    def add_series(self):
        palette = SERIES_COLORS
        x = self.series[-1].x_choice.currentData() if self.series else 0
        used = {item.y_choice.currentData() for item in self.series}
        candidates = [c for c in range(self.model.columnCount()) if c != x and c not in used]
        y = candidates[0] if candidates else min(1, self.model.columnCount() - 1)
        item = GraphSeries(self._next_number, palette[(self._next_number - 1) % len(palette)])
        item.fits = []
        item.next_fit_number = 1
        item.fit_signature = None
        self._next_number += 1
        item.sync_columns(self.model, self.axis_label, x, y)
        self.series.append(item)
        self.series_stack.addWidget(item)
        self.series_stack.setCurrentWidget(item)
        self.settings_button.setChecked(True)
        self.plot.addItem(item.line)
        self.plot.addItem(item.points)
        item.changed.connect(self.refresh_plot)
        item.style_changed.connect(self.update_legend)
        item.remove_requested.connect(lambda: self.remove_series(item))
        for entry in self.series:
            entry.remove_button.setEnabled(len(self.series) > 1)
        self.refresh_plot()
        return item

    def remove_series(self, item):
        if len(self.series) <= 1 or item not in self.series:
            return
        self.series.remove(item)
        self.remove_plot_item(item.points)
        self.remove_plot_item(item.line)
        for fit in item.fits:
            self.remove_plot_item(fit.curve)
            self.remove_plot_item(fit.extension)
        self.series_stack.removeWidget(item)
        item.deleteLater()
        for entry in self.series:
            entry.remove_button.setEnabled(len(self.series) > 1)
        self.refresh_plot()

    def sync_columns(self):
        for item in self.series:
            item.sync_columns(self.model, self.axis_label)
        self.refresh_plot()

    def axis_caption(self, dimension, side=None):
        columns = list(dict.fromkeys(item.key()[dimension] for item in self.series
                                    if item.visible.isChecked() and (side is None or item.y_axis.currentIndex() == side)))
        labels = [self.axis_label(column) for column in columns]
        if len(labels) <= 2:
            return " · ".join(labels) or ("Abscisse" if dimension == 0 else "Ordonnée")
        return "Abscisses (échelle commune)" if dimension == 0 else "Ordonnées (échelle commune)"

    def update_legend(self):
        self.update_series_choice()
        self.legend.clear()
        for item in self.series:
            if item.visible.isChecked():
                x, y = item.key()
                side = " · axe droit" if item.y_axis.currentIndex() else ""
                label = f"S{item.number} : {self.axis_label(y)} en fonction de {self.axis_label(x)}{side}"
                self.legend.addItem(item.points, escape(label))
            for fit in item.fits:
                fit.curve.setVisible(item.visible.isChecked())
                fit.extension.setVisible(item.visible.isChecked() and fit.settings.get('extend', False))
                if item.visible.isChecked():
                    self.legend.addItem(fit.curve, f"S{item.number} · Modélisation {fit.number}")
        self.legend.schedule()

    def data_signature(self, item):
        x, y = item.key()
        if x is None or y is None or not (0 <= x < self.model.columnCount() and 0 <= y < self.model.columnCount()):
            return None
        return (item.key(), self.axis_label(x), self.axis_label(y),
                tuple((row[x], row[y]) for row in self.model.rows))

    def clear_model(self, item, fit=None):
        removed = list(item.fits) if fit is None else [fit]
        for entry in removed:
            if entry in item.fits:
                self.remove_plot_item(entry.curve)
                self.remove_plot_item(entry.extension)
                item.fits.remove(entry)
        if not item.fits:
            item.fit_signature = None
        self.update_legend()

        if hasattr(self, 'curve_guides_tool'):
            self.curve_guides_tool.sync()

    def draw_model(self, item, fit):
        self.place_items((fit.curve, fit.extension), item)
        result = fit.result
        fit.curve.setData(result.x, result.y)
        fit.extension.clear()
        if fit.kind == 'affine' and fit.settings.get('extend', False):
            xs, _, _ = paired_values(self.model.rows, *item.key())
            if xs:
                # Deux segments séparés : la zone ajustée garde son propre trait.
                x = np.array([min(xs), result.x[0], np.nan, result.x[-1], max(xs)])
                fit.extension.setData(x, result.parameters['a']*x+result.parameters['b'], connect='finite')
        self.update_legend()
        if hasattr(self, 'curve_guides_tool'):
            self.curve_guides_tool.sync()

    def set_model(self, item, result, kind='', settings=None, fit=None):
        if fit is None:
            palette = ('#d84315', '#2e7d32', '#7b1fa2', '#00838f', '#ad1457', '#1565c0')
            color = palette[(item.next_fit_number-1) % len(palette)]
            fit = GraphFit(item.next_fit_number, result, kind, settings or {},
                           pg.PlotCurveItem(pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine)),
                           pg.PlotCurveItem(pen=pg.mkPen(color, width=1.5, style=Qt.PenStyle.DotLine)), color)
            item.next_fit_number += 1
            item.fits.append(fit)
            self.plot.addItem(fit.curve)
            self.plot.addItem(fit.extension, ignoreBounds=True)
        else:
            fit.result, fit.kind, fit.settings = result, kind, settings or {}
        item.fit_signature = self.data_signature(item)
        self.draw_model(item, fit)
        self.fit_points()
        return fit

    def refresh_plot(self, *args):
        messages = []
        for item in self.series:
            self.place_items((item.points, item.line, *(f.curve for f in item.fits), *(f.extension for f in item.fits)), item)
            if item.fits and item.fit_signature != self.data_signature(item):
                self.clear_model(item)
            x, y = item.key()
            xs, ys, skipped = paired_values(self.model.rows, x, y)
            item.points.setData(x=xs, y=ys)
            item.line.setData(x=xs, y=ys)
            item.restore_style()
            if item.visible.isChecked():
                detail = f"S{item.number} : {len(xs)} point(s)"
                if skipped:
                    detail += f", {skipped} ligne(s) ignorée(s)"
                messages.append(detail)
        self.plot.setLabel("bottom", escape(self.axis_caption(0)))
        self.plot.setLabel("left", escape(self.axis_caption(1, 0)))
        self.plot.setLabel("right", escape(self.axis_caption(1, 1)))
        self.plot.showAxis('right', any(s.visible.isChecked() and s.y_axis.currentIndex() == 1 for s in self.series))
        self.update_legend()
        visible_count = sum(item.visible.isChecked() for item in self.series)
        text = f"{visible_count} / {len(self.series)} série(s) visible(s)."
        if not any(item.visible.isChecked() and len(item.points.data) for item in self.series):
            text += " Aucun point à afficher."
        self.status.setText(text)
        scales = ("Abscisses communes ; échelles Y gauche et droite indépendantes, sans conversion d’unité."
                  if any(s.visible.isChecked() and s.y_axis.currentIndex() for s in self.series)
                  else "Échelles communes, valeurs sans conversion d’unité.")
        self.status.setToolTip("\n".join(messages + [scales]))
        self.tangent_tool.sync()
        self.conductimetry_tool.sync()
        self.curve_guides_tool.sync()
        self.hide_crosshair()
        self.fit_points()
        self.changed.emit()

    def fit_points(self):
        if any(s.y_axis.currentIndex() == 1 for s in self.series):
            xs_all = []
            for side, view in ((0, self.plot.getViewBox()), (1, self.right_view)):
                values = []
                for item in self.series:
                    if not item.visible.isChecked() or item.y_axis.currentIndex() != side:
                        continue
                    xs, ys, _ = paired_values(self.model.rows, *item.key())
                    xs_all.extend(xs)
                    values.extend(ys)
                    for fit in item.fits:
                        for curve in (fit.curve, fit.extension):
                            if curve.isVisible():
                                cx, cy = curve.getData()
                                if cy is not None:
                                    values.extend(float(y) for y in cy if np.isfinite(y))
                view.setYRange(min(values), max(values), padding=.08) if values else view.setYRange(0, 1, padding=0)
            self.plot.setXRange(min(xs_all), max(xs_all), padding=.08) if xs_all else self.plot.setXRange(0, 1, padding=0)
            return
        if any(item.visible.isChecked() and len(item.points.data) for item in self.series):
            self.plot.autoRange(padding=0.08)
            # Une intersection peut se trouver sous les mesures, entre deux intervalles.
            # L’inclure dans la vue sans cadrer les extrémités éloignées des prolongements.
            low, high = self.plot.viewRange()[1]
            intersections = []
            for item in self.series:
                if not item.visible.isChecked():
                    continue
                xs, _, _ = paired_values(self.model.rows, *item.key())
                if not xs:
                    continue
                fits = [f for f in item.fits if f.kind == 'affine' and f.settings.get('extend')]
                for first, second in combinations(fits, 2):
                    a, b = first.result.parameters['a'], first.result.parameters['b']
                    c, d = second.result.parameters['a'], second.result.parameters['b']
                    if a == c:
                        continue
                    x = (d-b)/(a-c)
                    y = a*x+b
                    if isfinite(x) and isfinite(y) and min(xs) <= x <= max(xs):
                        intersections.append(y)
            if intersections and (min(intersections) < low or max(intersections) > high):
                self.plot.setYRange(min(low, *intersections), max(high, *intersections), padding=0.08)
        else:
            self.plot.setRange(xRange=(0, 1), yRange=(0, 1), padding=0)

    def _build_menu(self):
        self.context_menu = QMenu(self)
        self.context_menu.addAction("Ajuster la vue", self.fit_points)
        self.context_menu.addAction("Modéliser…", self.modeling_requested.emit)
        self.context_menu.addAction("Méthode des tangentes…", self.tangent_tool.open_tool)
        self.context_menu.addAction("Titrage conductimétrique…", self.conductimetry_tool.open_tool)
        self.context_menu.addAction("Tangente en un point…", lambda: self.curve_guides_tool.open_tool('tangent'))
        self.context_menu.addAction("Asymptote horizontale…", lambda: self.curve_guides_tool.open_tool('asymptote'))
        self.context_menu.addAction("Replacer la légende automatiquement", self.legend.reset_placement)
        self.context_menu.addAction("Zoom avant", lambda: self.zoom_by(0.5))
        self.context_menu.addAction("Zoom arrière", lambda: self.zoom_by(2))
        self.context_menu.addSeparator()
        group = QActionGroup(self)
        group.setExclusive(True)
        for label, mode in (("Déplacer la vue", pg.ViewBox.PanMode),
                            ("Zoom par rectangle", pg.ViewBox.RectMode)):
            action = self.context_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == pg.ViewBox.PanMode)
            group.addAction(action)
            action.triggered.connect(lambda checked, chosen=mode: self.plot.getViewBox().setMouseMode(chosen))
        self.context_menu.addSeparator()
        self.reticle_action = QAction("Réticule", self, checkable=True)
        self.reticle_action.toggled.connect(self.hide_crosshair)
        self.context_menu.addAction(self.reticle_action)

    def show_context_menu(self, position):
        self.hide_crosshair()
        self.context_menu.popup(position)

    def zoom_by(self, factor):
        self.plot.getViewBox().scaleBy((factor, factor))

    def track_cursor(self, scene_position):
        view = self.plot.getViewBox()
        if (not self.reticle_action.isChecked() or self.context_menu.isVisible()
                or not view.sceneBoundingRect().contains(scene_position)):
            self.hide_crosshair()
            return
        position = view.mapSceneToView(scene_position)
        self.cross_x.setPos(position.x())
        self.cross_y.setPos(position.y())
        self.cross_x.show()
        self.cross_y.show()
        x = format(position.x(), ".7g").replace(".", ",")
        y = format(position.y(), ".7g").replace(".", ",")
        self.coordinates.setText(
            f"X — {self.axis_caption(0)} : {x}    |    "
            f"Y — {self.axis_caption(1)} : {y}")
        if self.plot.getAxis('right').isVisible():
            right_y = self.right_view.mapSceneToView(scene_position).y()
            self.coordinates.setText(f"X : {x} | Y gauche : {y} | Y droite : {right_y:.7g}".replace('.', ','))
        self.coordinates.setToolTip(self.coordinates.text())

    def hide_crosshair(self, *args):
        self.cross_x.hide()
        self.cross_y.hide()
        self.coordinates.setText(
            "Réticule activé — survolez le graphique pour lire les coordonnées."
            if self.reticle_action.isChecked() else
            "Réticule désactivé — clic droit pour l’activer.")
        self.coordinates.setToolTip(self.coordinates.text())

    def eventFilter(self, watched, event):
        if watched is self.plot.viewport() and event.type() == QEvent.Type.Leave:
            self.hide_crosshair()
        return super().eventFilter(watched, event)
