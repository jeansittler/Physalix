"""Réglages indépendants d'une série superposée sur le graphique."""

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtGui import QColor, QIcon, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QFrame, QHBoxLayout,
    QLabel, QListView, QPushButton, QSizePolicy, QStyle, QVBoxLayout, QWidget,
)
import pyqtgraph as pg
from physalix.ui.components import WheelSafeComboBox, role
from physalix.ui.theme import LIGHT


class PopupComboBox(WheelSafeComboBox):
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
        self._finish_popup_geometry()
        QTimer.singleShot(0, self._finish_popup_geometry)

    def _finish_popup_geometry(self):
        view = self.view()
        container = view.parentWidget()
        if container is None or not view.isVisible():
            return
        # Qt positions the list inside private popup margins only after showPopup.
        # Reserve those margins explicitly and keep the view anchored instead of
        # letting the private layout centre and clip it when the model is long.
        popup_inset = (
            self.style().pixelMetric(QStyle.PixelMetric.PM_MenuVMargin, None, self)
            + container.frameWidth()
        )
        if self.count() > self.maxVisibleItems():
            popup_inset += self.style().pixelMetric(
                QStyle.PixelMetric.PM_MenuScrollerHeight, None, self
            )
        container.setFixedHeight(view.height() + 2 * popup_inset)
        view.move(view.x(), popup_inset)
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            popup = container.frameGeometry()
            combo_top = self.mapToGlobal(self.rect().topLeft()).y()
            combo_bottom = self.mapToGlobal(self.rect().bottomLeft()).y()
            if popup.height() > available.bottom() - combo_bottom:
                top = max(available.top(), combo_top - popup.height())
            else:
                top = min(max(popup.top(), available.top()),
                          available.bottom() - popup.height() + 1)
            container.move(popup.x(), top)


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
        self.display_number = number
        self.default_color = color
        self.color = QColor(color)
        self._styles = {}
        role(self, "seriesEditor")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(LIGHT.section, LIGHT.small, LIGHT.section, LIGHT.small)
        layout.setSpacing(LIGHT.related)
        axis_row = QHBoxLayout()
        axis_row.setSpacing(LIGHT.section)
        self.visible = QCheckBox(f"Série {number}")
        self.visible.setChecked(True)
        self.visible.setToolTip("Afficher ou masquer cette série")
        self.x_choice, self.y_choice = PopupComboBox(), PopupComboBox()
        for name, title, hint, accessible, combo in (
                ("x", "Grandeur en abscisse", "Axe horizontal",
                 "Grandeur en abscisse (axe horizontal)", self.x_choice),
                ("y", "Grandeur en ordonnée", "Axe vertical",
                 "Grandeur en ordonnée (axe vertical)", self.y_choice)):
            group = role(QFrame(), "optionArea")
            group.setObjectName(f"{name}AxisBlock")
            group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            fields = QVBoxLayout(group)
            fields.setContentsMargins(LIGHT.group, LIGHT.small, 0, LIGHT.small)
            fields.setSpacing(LIGHT.small)
            heading = QHBoxLayout()
            heading.setSpacing(LIGHT.related)
            caption = role(QLabel(title), "fieldLabel")
            caption.setObjectName(f"{name}ChoiceLabel")
            caption.setBuddy(combo)
            axis_hint = role(QLabel(hint), "muted")
            axis_hint.setObjectName(f"{name}AxisHint")
            heading.addWidget(caption)
            heading.addWidget(axis_hint)
            heading.addStretch()
            fields.addLayout(heading)
            fields.addWidget(combo)
            axis_row.addWidget(group, 1)
            combo.setAccessibleName(accessible)
            combo.setMinimumWidth(160)
            combo.setMinimumContentsLength(8)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            configure_popup(combo, LIGHT.field_medium)
            combo.currentIndexChanged.connect(self.update_relation)
            combo.currentIndexChanged.connect(self.changed)
        layout.addLayout(axis_row)

        secondary = QHBoxLayout()
        secondary.setSpacing(LIGHT.related)
        self.relation_label = role(QLabel("Tracé : grandeurs à choisir"), "fieldLabel")
        self.relation_label.setObjectName("seriesRelation")
        self.relation_label.setTextFormat(Qt.TextFormat.PlainText)
        self.relation_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        secondary.addWidget(self.relation_label, 1)
        secondary.addWidget(self.visible)
        self.connect_points = QCheckBox("Relier")
        self.connect_points.setToolTip("Relier les points dans l’ordre du tableau")
        secondary.addWidget(self.connect_points)
        self.y_axis = PopupComboBox()
        self.y_axis.addItems(["Y gauche", "Y droite"])
        configure_popup(self.y_axis)
        update_popup_height(self.y_axis)
        self.y_axis.setAccessibleName("Axe des ordonnées de la série")
        self.y_axis.setToolTip("Y droite utilise une échelle indépendante ; les abscisses restent communes.")
        self.y_axis.currentIndexChanged.connect(self.changed)
        secondary.addWidget(self.y_axis)
        self.color_button = QPushButton("Couleur…")
        self.color_button.clicked.connect(self.choose_color)
        secondary.addWidget(self.color_button)
        self.remove_button = role(QPushButton("Retirer"), "danger")
        self.remove_button.setToolTip("Retirer cette série du graphique sans effacer les données")
        self.remove_button.clicked.connect(self.remove_requested)
        secondary.addWidget(self.remove_button)
        layout.addLayout(secondary)

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

    def set_display_number(self, number):
        self.display_number = number
        self.visible.setText(f"Série {number}")

    def update_relation(self, *args):
        def selected_label(combo):
            if hasattr(self, "_axis_label") and combo.currentData() is not None:
                return self._axis_label(combo.currentData())
            return combo.currentText().partition(" — ")[2] or "grandeur à choisir"

        self.relation_label.setText(
            f"Tracé : {selected_label(self.y_choice)} en fonction de "
            f"{selected_label(self.x_choice)}"
        )

    def sync_columns(self, model, axis_label, x_default=0, y_default=1):
        self._axis_label = axis_label
        for combo, default in ((self.x_choice, x_default), (self.y_choice, y_default)):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for column in range(model.columnCount()):
                combo.addItem(f"{column + 1} — {axis_label(column)}", column)
            update_popup_height(combo)
            combo.setCurrentIndex(min(default if selected is None else selected, combo.count() - 1))
            combo.blockSignals(False)
        self.update_relation()

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
        color = QColorDialog.getColor(
            self.color, self, f"Couleur de la série {self.display_number}"
        )
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
