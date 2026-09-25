"""Réglages indépendants d'une série superposée sur le graphique."""

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QIcon, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QHBoxLayout, QLabel,
    QListView, QPushButton, QSizePolicy, QWidget,
)
import pyqtgraph as pg
from physalix.ui.components import role
from physalix.ui.theme import LIGHT


class PopupComboBox(QComboBox):
    """Keep Qt's popup container aligned with the bounded list view."""

    def showPopup(self):
        update_popup_height(self)
        view = self.view()
        container = view.parentWidget()
        if container is not None:
            margins = container.layout().contentsMargins() if container.layout() else None
            vertical_margins = margins.top() + margins.bottom() if margins else 0
            container.setFixedHeight(
                view.height() + 2 * container.frameWidth() + vertical_margins
            )
        super().showPopup()


def configure_popup(combo, minimum_width=None):
    """Use the same bounded, fully padded popup for series selectors."""
    combo.setMaxVisibleItems(8)
    view = QListView(combo)
    combo.setView(view)
    if minimum_width is not None:
        view.setMinimumWidth(minimum_width)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setUniformItemSizes(True)


def update_popup_height(combo):
    """Fit every visible row plus the popup padding, capped at maxVisibleItems."""
    if not combo.count():
        return
    row_height = combo.view().sizeHintForRow(0)
    if row_height <= 0:
        return
    visible_rows = min(combo.count(), combo.maxVisibleItems())
    height = visible_rows * row_height + 2 * (LIGHT.small + combo.view().frameWidth())
    combo.view().setFixedHeight(height)


class GraphSeries(QWidget):
    """Une paire de colonnes, ses points, ses segments et ses contrôles."""

    changed = Signal()
    style_changed = Signal()
    remove_requested = Signal()

    def __init__(self, number, color, parent=None):
        super().__init__(parent)
        self.number = number
        self.default_color = color
        self.color = QColor(color)
        self._styles = {}
        role(self, "seriesEditor")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(LIGHT.section, LIGHT.small, LIGHT.section, LIGHT.small)
        row.setSpacing(LIGHT.related)
        self.visible = QCheckBox(f"Série {number}")
        self.visible.setChecked(True)
        self.visible.setToolTip("Afficher ou masquer cette série")
        row.addWidget(self.visible)
        self.x_choice, self.y_choice = PopupComboBox(), PopupComboBox()
        for name, label, combo in (("x", "Grandeur en abscisse (X)", self.x_choice),
                                   ("y", "Grandeur en ordonnée (Y)", self.y_choice)):
            group = QWidget()
            group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            fields = QHBoxLayout(group)
            fields.setContentsMargins(0, 0, 0, 0)
            fields.setSpacing(LIGHT.related)
            caption = QLabel(label)
            caption.setObjectName(f"{name}ChoiceLabel")
            caption.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            caption.setMaximumWidth(caption.sizeHint().width())
            caption.setBuddy(combo)
            fields.addWidget(caption)
            fields.addWidget(combo, 1)
            row.addWidget(group, 1)
            combo.setMinimumWidth(180)
            combo.setMaximumWidth(LIGHT.field_medium)
            combo.setMinimumContentsLength(8)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            configure_popup(combo, LIGHT.field_medium)
            combo.currentIndexChanged.connect(self.changed)
        self.connect_points = QCheckBox("Relier")
        self.connect_points.setToolTip("Relier les points dans l’ordre du tableau")
        row.addWidget(self.connect_points)
        self.y_axis = PopupComboBox()
        self.y_axis.addItems(["Y gauche", "Y droite"])
        configure_popup(self.y_axis)
        update_popup_height(self.y_axis)
        self.y_axis.setAccessibleName("Axe des ordonnées de la série")
        self.y_axis.setToolTip("Y droite utilise une échelle indépendante ; les abscisses restent communes.")
        self.y_axis.currentIndexChanged.connect(self.changed)
        row.addWidget(self.y_axis)
        self.color_button = QPushButton("Couleur…")
        self.color_button.clicked.connect(self.choose_color)
        row.addWidget(self.color_button)
        self.remove_button = role(QPushButton("Retirer"), "danger")
        self.remove_button.setToolTip("Retirer cette série du graphique sans effacer les données")
        self.remove_button.clicked.connect(self.remove_requested)
        row.addWidget(self.remove_button)

        cross = QPainterPath()
        cross.moveTo(-0.5, 0)
        cross.lineTo(0.5, 0)
        cross.moveTo(0, -0.5)
        cross.lineTo(0, 0.5)
        self.points = pg.ScatterPlotItem(symbol=cross, size=11, brush=None, pxMode=True)
        self.points.setZValue(1)
        self.line = pg.PlotCurveItem()
        self.connect_points.toggled.connect(self.apply_style)
        self.visible.toggled.connect(self.changed)

    def sync_columns(self, model, axis_label, x_default=0, y_default=1):
        for combo, default in ((self.x_choice, x_default), (self.y_choice, y_default)):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for column in range(model.columnCount()):
                combo.addItem(f"{column + 1} — {axis_label(column)}", column)
            update_popup_height(combo)
            combo.setCurrentIndex(min(default if selected is None else selected, combo.count() - 1))
            combo.blockSignals(False)

    def restore_style(self):
        color, connected = self._styles.get(self.key(), (self.default_color, False))
        self.color = QColor(color)
        self.connect_points.blockSignals(True)
        self.connect_points.setChecked(connected)
        self.connect_points.blockSignals(False)
        self.apply_style()

    def key(self):
        return self.x_choice.currentData(), self.y_choice.currentData()

    def choose_color(self):
        color = QColorDialog.getColor(self.color, self, f"Couleur de la série {self.number}")
        if color.isValid():
            self.set_curve_color(color)

    def set_curve_color(self, color):
        self.color = QColor(color)
        self.apply_style()

    def apply_style(self, *args):
        self.points.setPen(pg.mkPen(self.color, width=1.8))
        self.line.setPen(pg.mkPen(self.color, width=1.5))
        self.points.setVisible(self.visible.isChecked())
        self.line.setVisible(self.visible.isChecked() and self.connect_points.isChecked())
        swatch = QPixmap(16, 16)
        swatch.fill(self.color)
        self.color_button.setIcon(QIcon(swatch))
        self._styles[self.key()] = (self.color.name(), self.connect_points.isChecked())
        self.style_changed.emit()
