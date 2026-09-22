"""Choix des axes et nuage de points lié au tableau de mesures."""

from dataclasses import dataclass
from itertools import combinations
from html import escape
import numpy as np
from math import isfinite

from PySide6.QtCore import QEvent, QPointF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMenu, QPushButton, QStackedWidget, QVBoxLayout, QWidget, QSizePolicy,
)
import pyqtgraph as pg

from physalix.fitting import evaluate_fit
from physalix.ui.graph_series import GraphSeries
from physalix.ui.graph_axis import EndAxis
from physalix.ui.graph_legend import SmartLegend
from physalix.ui.theme import LIGHT, SERIES_COLORS
from physalix.ui.components import workspace_layout, role, panel as make_panel
from physalix.ui.icons import icon


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

    def sizeHint(self):
        """Ne pas laisser le canevas imposer 480 px à la page qui le contient."""
        return QSize(640, 320)


class GraphViewBox(pg.ViewBox):
    """Acheminer tous les clics droits du canevas vers le menu Physalix."""

    menu_requested = Signal(object)

    def mouseClickEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            self.menu_requested.emit(event.screenPos().toPoint())
            return
        super().mouseClickEvent(event)


class SecondaryViewBox(pg.ViewBox):
    """Laisser le canevas au repère principal, tout en gardant l'axe Y droit autonome."""

    def __init__(self, primary):
        super().__init__()
        self.primary = primary

    def mouseDragEvent(self, event, axis=None):
        if axis is None:
            return self.primary.mouseDragEvent(event)
        return super().mouseDragEvent(event, axis=axis)

    def wheelEvent(self, event, axis=None):
        if axis is None:
            return self.primary.wheelEvent(event)
        return super().wheelEvent(event, axis=axis)


class AntialiasedInfiniteLine(pg.InfiniteLine):
    """Ligne de repère fine et antialiasée, sans interaction."""

    def paint(self, painter, *args):
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        super().paint(painter, *args)


class GraphTab(QWidget):
    """Superposer des séries indépendantes dans un repère commun."""

    ZERO_EDGE_MARGIN = 4

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
        self.content.setMinimumSize(760, 430)
        self.workspace_layout = layout
        layout.setContentsMargins(LIGHT.section, LIGHT.related, LIGHT.section, LIGHT.related)
        layout.setSpacing(LIGHT.related)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(LIGHT.related)
        add = role(QPushButton("Ajouter une série"), "primary")
        add.setIcon(icon("add"))
        add.clicked.connect(lambda: self.add_series())
        toolbar.addWidget(add)
        model_button = QPushButton("Modéliser…")
        model_button.clicked.connect(self.modeling_requested)
        toolbar.addWidget(model_button)
        toolbar.addStretch()
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
        series_row.setSpacing(LIGHT.related)
        self.series_label = role(QLabel("Série active"), "toolbarLabel")
        self.series_choice = QComboBox()
        self.series_choice.setAccessibleName("Série à régler")
        self.series_choice.setMinimumContentsLength(18)
        self.series_choice.setMaximumWidth(LIGHT.field_wide)
        self.series_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.series_choice.setMaxVisibleItems(10)
        self.series_label.setBuddy(self.series_choice)
        self.series_choice.setToolTip("Choisir les réglages d'une série sans masquer les autres courbes")
        self.settings_button = QPushButton("Masquer les réglages")
        self.settings_button.setCheckable(True)
        self.settings_button.setChecked(True)
        self.settings_button.toggled.connect(self.toggle_series_settings)
        series_row.addWidget(self.series_label)
        series_row.addWidget(self.series_choice, 1)
        series_row.addStretch()
        series_row.addWidget(self.settings_button)
        self.series_stack = QStackedWidget()
        self.series_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.series_choice.currentIndexChanged.connect(self.select_series)

        self.view_box = GraphViewBox()
        self.plot = InteractivePlot(background=LIGHT.surface, viewBox=self.view_box, axisItems={
            'bottom': EndAxis('bottom'), 'left': EndAxis('left'), 'right': EndAxis('right')})
        self.right_view = SecondaryViewBox(self.view_box)
        self.right_view.setMenuEnabled(False)
        self.plot.scene().addItem(self.right_view)
        self.right_view.setZValue(-1)
        self.plot.getAxis('right').linkToView(self.right_view)
        self.right_view.setXLink(self.plot.getViewBox())
        self._item_views = {}
        self.plot.getViewBox().sigResized.connect(self.resize_right_view)
        self.plot.hideAxis('right')
        self.plot.setMinimumSize(200, 220)
        self.plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.plot.getPlotItem().layout.setContentsMargins(8, 8, 20, 6)
        self.plot.getPlotItem().setMenuEnabled(False, enableViewBoxMenu=False)
        self.view_box.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.showGrid(x=True, y=True, alpha=0.10)
        zero_color = QColor(LIGHT.muted)
        zero_color.setAlpha(155)
        zero_pen = pg.mkPen(zero_color, width=1.4, style=Qt.PenStyle.SolidLine)
        zero_pen.setCosmetic(True)
        self.zero_x = AntialiasedInfiniteLine(pos=0, angle=90, movable=False,
                                              pen=zero_pen)
        self.zero_y = AntialiasedInfiniteLine(pos=0, angle=0, movable=False,
                                              pen=zero_pen)
        for zero_line in (self.zero_x, self.zero_y):
            self.plot.addItem(zero_line, ignoreBounds=True)
            zero_line.setZValue(-1)
            zero_line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
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
        self.cross_x_label = pg.TextItem(anchor=(0.5, 1), color=LIGHT.text,
                                         fill=pg.mkBrush(LIGHT.surface),
                                         border=pg.mkPen(LIGHT.border_strong))
        self.cross_y_label = pg.TextItem(anchor=(0, 0.5), color=LIGHT.text,
                                         fill=pg.mkBrush(LIGHT.surface),
                                         border=pg.mkPen(LIGHT.border_strong))
        for value_label in (self.cross_x_label, self.cross_y_label):
            self.plot.addItem(value_label, ignoreBounds=True)
            value_label.setZValue(1_000_000)
            value_label.hide()
        plot_panel, plot_layout = make_panel()
        self.plot_panel = plot_panel
        self.plot_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        plot_layout.setContentsMargins(LIGHT.related, LIGHT.small, LIGHT.related, LIGHT.small)
        plot_layout.setSpacing(0)
        self.fit_view_button = QPushButton("Ajuster la vue")
        self.fit_view_button.clicked.connect(self.fit_points)
        self.fit_view_button.setToolTip("Recadrer le tracé sur toutes les séries visibles")
        plot_layout.addWidget(self.plot)
        layout.addWidget(plot_panel, 1)
        layout.addLayout(series_row)
        layout.addWidget(self.series_stack)
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
        toolbar.insertWidget(3, self.fit_view_button)
        for message in (self.coordinates, self.status, hint):
            role(message, "muted")
        self.plot.menu_requested.connect(self.show_context_menu)
        self.view_box.menu_requested.connect(self.show_context_menu)
        self.plot.scene().sigMouseMoved.connect(self.track_cursor)
        self.plot.viewport().setMouseTracking(True)
        self.plot.viewport().installEventFilter(self)
        self.plot.getViewBox().sigRangeChanged.connect(self.hide_crosshair)
        self.plot.getViewBox().sigRangeChanged.connect(self.update_zero_lines)
        self.plot.getViewBox().sigResized.connect(self.update_zero_lines)

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
        self.update_zero_lines()

    def update_zero_lines(self, *args):
        view = self.plot.getViewBox()
        x_range, y_range = self.plot.viewRange()
        bounds = view.sceneBoundingRect()
        zero = view.mapViewToScene(QPointF(0, 0))
        margin = self.ZERO_EDGE_MARGIN
        self.zero_x.setVisible(
            x_range[0] <= 0 <= x_range[1]
            and bounds.left() + margin < zero.x() < bounds.right() - margin
        )
        self.zero_y.setVisible(
            y_range[0] <= 0 <= y_range[1]
            and bounds.top() + margin < zero.y() < bounds.bottom() - margin
        )

    def resize_right_view(self):
        bounds = self.plot.getViewBox().sceneBoundingRect()
        # ViewBox ajoute un demi-pixel à son contour : le retirer garde les
        # géométries gauche/droite identiques et donc les abscisses alignées.
        self.right_view.setGeometry(bounds.adjusted(0, 0, -0.5, -0.5))
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
            self.content.setMinimumSize(760, 430)
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
        self.series_label.setVisible(visible)
        self.series_choice.setVisible(visible)
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
                fit.extension.hide()
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
        fit.extension.clear()
        display_x, display_y = result.x, result.y
        xs, ys, _ = paired_values(self.model.rows, *item.key())
        if xs and (fit.kind != 'affine' or fit.settings.get('extend', False)):
            span = max(xs) - min(xs)
            margin = span * .12
            low, high = min(xs) - margin, max(xs) + margin
            if fit.kind == 'linear':
                low, high = min(low, 0), max(high, 0)
            y_values = [*ys, *result.y]
            y_low, y_high = min(y_values), max(y_values)
            y_scale = max(y_high-y_low, max(abs(y_low), abs(y_high))*.25, 1e-12)
            y_limits = ((-np.inf, np.inf) if fit.kind in ('constant', 'linear', 'affine')
                        else (y_low-2*y_scale, y_high+2*y_scale))
            axis = item.key()[0]
            axis_name = self.model.names[axis] if axis is not None else "x"

            def segment(start, end, keep_near_end):
                if start >= end:
                    return np.array([]), np.array([])
                x = np.linspace(start, end, 120)
                try:
                    y = evaluate_fit(result, x, axis_name)
                except ValueError:
                    values = []
                    for value in x:
                        try:
                            values.append(float(evaluate_fit(result, [value], axis_name)[0]))
                        except ValueError:
                            values.append(np.nan)
                    y = np.asarray(values)
                valid = np.isfinite(y) & (y >= y_limits[0]) & (y <= y_limits[1])
                invalid = np.flatnonzero(~valid)
                if len(invalid):
                    if keep_near_end:
                        valid[:invalid[-1]+1] = False
                    else:
                        valid[invalid[0]:] = False
                return x[valid], y[valid]

            left_x, left_y = segment(low, float(result.x[0]), True)
            right_x, right_y = segment(float(result.x[-1]), high, False)
            parts_x, parts_y = [result.x], [result.y]
            if len(left_x) > 1:
                parts_x.insert(0, left_x[:-1])
                parts_y.insert(0, left_y[:-1])
            if len(right_x) > 1:
                parts_x.append(right_x[1:])
                parts_y.append(right_y[1:])
            display_x, display_y = np.concatenate(parts_x), np.concatenate(parts_y)
        fit.curve.setData(display_x, display_y, connect='finite')
        fit.extension.hide()
        self.update_legend()
        if hasattr(self, 'curve_guides_tool'):
            self.curve_guides_tool.sync()

    def set_model(self, item, result, kind='', settings=None, fit=None):
        if fit is None:
            palette = ('#d84315', '#2e7d32', '#7b1fa2', '#00838f', '#ad1457', '#1565c0')
            color = palette[(item.next_fit_number-1) % len(palette)]
            model_pen = pg.mkPen(color, width=1.8)
            model_pen.setStyle(Qt.PenStyle.CustomDashLine)
            model_pen.setDashPattern([7, 3.5])
            model_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            model_pen.setCosmetic(True)
            fit = GraphFit(item.next_fit_number, result, kind, settings or {},
                           pg.PlotCurveItem(pen=model_pen, antialias=True),
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
                                if cx is not None:
                                    xs_all.extend(float(x) for x in cx if np.isfinite(x))
                                if cy is not None:
                                    values.extend(float(y) for y in cy if np.isfinite(y))
                view.setYRange(min(values), max(values), padding=.08) if values else view.setYRange(0, 1, padding=0)
            self.plot.setXRange(min(xs_all), max(xs_all), padding=.08) if xs_all else self.plot.setXRange(0, 1, padding=0)
            return
        if any(item.visible.isChecked() and len(item.points.data) for item in self.series):
            self.plot.autoRange(padding=0.08)
            x_range, y_range = self.plot.viewRange()
            extra_x, extra_y = [], []
            for item in self.series:
                if not item.visible.isChecked():
                    continue
                for fit in item.fits:
                    if fit.extension.isVisible():
                        x, y = fit.extension.getData()
                        extra_x.extend(float(value) for value in x if np.isfinite(value))
                        extra_y.extend(float(value) for value in y if np.isfinite(value))
            if extra_x or extra_y:
                self.plot.setRange(
                    xRange=(min(*x_range, *extra_x), max(*x_range, *extra_x)),
                    yRange=(min(*y_range, *extra_y), max(*y_range, *extra_y)),
                    padding=.06,
                )
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
            action.triggered.connect(
                lambda checked, chosen=mode: self.set_navigation_mode(chosen)
            )
        self.context_menu.addSeparator()
        self.reticle_action = QAction("Réticule", self, checkable=True)
        self.reticle_action.toggled.connect(self.hide_crosshair)
        self.context_menu.addAction(self.reticle_action)
        self.context_menu.addSeparator()
        options = self.context_menu.addMenu("Options du graphique")
        from pyqtgraph.graphicsItems.ViewBox.ViewBoxMenu import ViewBoxMenu
        self.native_view_menu = ViewBoxMenu(self.plot.getViewBox())
        native_actions = self.native_view_menu.actions()
        for title, action in (("Axe X", native_actions[1]),
                              ("Axe Y", native_actions[2])):
            submenu = action.menu()
            submenu.setTitle(title)
            options.addMenu(submenu)
        options.addSeparator()
        self.export_action = options.addAction("Exporter…", self.export_graph)

    def set_navigation_mode(self, mode):
        view = self.plot.getViewBox()
        view.setMouseMode(mode)
        if mode == pg.ViewBox.PanMode:
            view.setMouseEnabled(x=True, y=True)

    def export_graph(self):
        scene = self.plot.scene()
        scene.contextMenuItem = self.plot.getPlotItem()
        scene.showExportDialog()

    def show_context_menu(self, position):
        if self.context_menu.isVisible():
            return
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
        x_range, y_range = view.viewRange()
        self.cross_x_label.setText(x)
        self.cross_y_label.setText(y)
        x_span, y_span = x_range[1]-x_range[0], y_range[1]-y_range[0]
        x_pixels, y_pixels = max(view.width(), 1), max(view.height(), 1)
        x_padding = self.cross_x_label.boundingRect().width() * x_span / (2*x_pixels)
        y_padding = self.cross_y_label.boundingRect().height() * y_span / (2*y_pixels)
        edge_x = x_range[0] + 3*x_span/x_pixels
        edge_y = y_range[0] + 3*y_span/y_pixels
        label_x = min(max(position.x(), x_range[0]+x_padding), x_range[1]-x_padding)
        label_y = min(max(position.y(), y_range[0]+y_padding), y_range[1]-y_padding)
        self.cross_x_label.setPos(label_x, edge_y)
        self.cross_y_label.setPos(edge_x, label_y)
        self.cross_x_label.show()
        self.cross_y_label.show()
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
        self.cross_x_label.hide()
        self.cross_y_label.hide()
        self.coordinates.setText(
            "Réticule activé — survolez le graphique pour lire les coordonnées."
            if self.reticle_action.isChecked() else
            "Réticule désactivé — clic droit pour l’activer.")
        self.coordinates.setToolTip(self.coordinates.text())

    def eventFilter(self, watched, event):
        if watched is self.plot.viewport():
            if event.type() == QEvent.Type.ContextMenu:
                self.show_context_menu(event.globalPos())
                event.accept()
                return True
            if event.type() == QEvent.Type.Leave:
                self.hide_crosshair()
        return super().eventFilter(watched, event)
