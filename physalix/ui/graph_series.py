"""Réglages indépendants d'une série superposée sur le graphique."""

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QIcon, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget,
)
import pyqtgraph as pg
from physalix.ui.components import role


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
        role(self, "panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        self.visible = QCheckBox(f"Série {number}")
        self.visible.setChecked(True)
        self.visible.setToolTip("Afficher ou masquer cette série")
        row.addWidget(self.visible)
        self.x_choice, self.y_choice = QComboBox(), QComboBox()
        for label, combo in (("X", self.x_choice), ("Y", self.y_choice)):
            caption = QLabel(label)
            caption.setBuddy(combo)
            row.addWidget(caption)
            row.addWidget(combo, 1)
            combo.setMinimumContentsLength(8)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.currentIndexChanged.connect(self.changed)
        self.connect_points = QCheckBox("Relier")
        self.connect_points.setToolTip("Relier les points dans l’ordre du tableau")
        row.addWidget(self.connect_points)
        self.y_axis = QComboBox()
        self.y_axis.addItems(["Y gauche", "Y droite"])
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
