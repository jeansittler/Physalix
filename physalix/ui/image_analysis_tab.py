"""Onglet pedagogique d'analyse de profils d'intensite sur une image."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import (
    QAbstractTableModel, QByteArray, QBuffer, QIODevice, QModelIndex, QPointF,
    QLocale, QSize, Qt, Signal,
)
from PySide6.QtGui import QColor, QImage, QImageReader, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTabWidget,
    QTableView, QVBoxLayout, QWidget,
)

from physalix.image_analysis import (
    MAX_PROFILES, ImageCalibration, IntensityProfile, MeasurementPoint,
    ProfileMeasurement, extract_profile, fraction_value, local_extremum_index,
    measurement_result,
)
from physalix.ui.components import page_layout, panel, refresh_style, role
from physalix.ui.graph_series import PopupComboBox, configure_popup, update_popup_height
from physalix.ui.image_analysis_canvas import ImageAnalysisCanvas
from physalix.ui.theme import LIGHT, SERIES_COLORS
from physalix.ui.video_tracking import CalibrationLengthSpinBox


MAX_IMAGE_FILE_SIZE = 64 * 1024**2
MAX_IMAGE_PIXELS = 50_000_000
MAX_PROJECT_IMAGE_SIZE = 256 * 1024**2
IMAGE_ANALYSIS_VERSION = 1


def qimage_grayscale(image):
    converted = image.convertToFormat(QImage.Format.Format_Grayscale8)
    view = np.frombuffer(converted.bits(), dtype=np.uint8, count=converted.sizeInBytes())
    return view.reshape(converted.height(), converted.bytesPerLine())[:, :converted.width()].copy()


def portable_png(image):
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
        raise ValueError("Impossible d'encoder l'image pour le projet.")
    result = bytes(data)
    if len(result) > MAX_PROJECT_IMAGE_SIZE:
        raise ValueError("L'image integree depasse la limite de 256 Mo.")
    return result


def number(value):
    return format(float(value), ".7g").replace(".", ",")


class ElidedLabel(QLabel):
    """Libellé sur une ligne, tronqué sans perdre le texte complet."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        text = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, max(0, self.width() - 2))
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


def compact_page_header(title, description):
    header = role(QWidget(), "pageHeader")
    row = QHBoxLayout(header)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(LIGHT.related)
    accent = role(QFrame(), "pageAccent")
    accent.setFixedSize(5, 30)
    row.addWidget(accent)
    row.addWidget(role(QLabel(title), "pageTitle"))
    subtitle = role(ElidedLabel(description), "pageSubtitle")
    subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    row.addWidget(subtitle, 1)
    return header


class KnownValueSpinBox(CalibrationLengthSpinBox):
    """Champ positif optionnel : minimum vide, saisie française virgule ou point."""

    def textFromValue(self, value):
        if value <= self.minimum():
            return ""
        return super().textFromValue(value)


class ProfileTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = None
        self.axis_name, self.unit = "x", "px"

    def set_samples(self, samples, axis_name="x", unit="px"):
        self.beginResetModel()
        self.samples, self.axis_name, self.unit = samples, axis_name, unit
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or self.samples is None else len(self.samples.axis)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 2

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.samples is None:
            return None
        value = self.samples.axis[index.row()] if index.column() == 0 else self.samples.intensity[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return number(value)
        if role == Qt.ItemDataRole.UserRole:
            return float(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return (self.axis_name + (f" [{self.unit}]" if self.unit else "")) if section == 0 else "Niveau de gris"


class ProfileTableView(QTableView):
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            indexes = sorted(self.selectedIndexes(), key=lambda item: (item.row(), item.column()))
            rows = {}
            for index in indexes:
                rows.setdefault(index.row(), {})[index.column()] = index.data()
            text = "\n".join("\t".join(values.get(column, "") for column in range(2))
                             for values in rows.values())
            QApplication.clipboard().setText(text)
            return
        super().keyPressEvent(event)


class ImageProfilePlot(pg.PlotWidget):
    """Acheminer le clic droit vers le menu pédagogique du profil."""

    menu_requested = Signal(object)

    def contextMenuEvent(self, event):
        self.menu_requested.emit(event.globalPos())
        event.accept()

    def sizeHint(self):
        return QSize(640, 240)


class ImageProfileViewBox(pg.ViewBox):
    """Neutraliser le menu technique natif de PyQtGraph."""

    menu_requested = Signal(object)
    rectangle_zoom_finished = Signal()

    def mouseClickEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            self.menu_requested.emit(event.screenPos().toPoint())
            return
        super().mouseClickEvent(event)

    def mouseDragEvent(self, event, axis=None):
        rectangle_zoom = (self.state["mouseMode"] == pg.ViewBox.RectMode
                          and event.button() == Qt.MouseButton.LeftButton)
        super().mouseDragEvent(event, axis=axis)
        if rectangle_zoom and event.isFinish():
            self.rectangle_zoom_finished.emit()


class ImageAnalysisTab(QWidget):
    """Analyser plusieurs coupes independantes sur une image unique."""

    def __init__(self, data_tab, graph_workspace, show_graph, parent=None):
        super().__init__(parent)
        self.data_tab = data_tab
        self.graph_workspace = graph_workspace
        self.show_graph = show_graph
        self.image = QImage()
        self.gray = None
        self.image_bytes = None
        self.image_name = None
        self.profiles = []
        self.active_identifier = None
        self.calibration = ImageCalibration()
        self.distance_reference = None
        self.spectral_points = [None, None]
        self.calibration_reference = None
        self.calibration_horizontal_preference = False
        self.profile_horizontal_default = False
        self.samples = {}
        self.measurement = ProfileMeasurement()
        self.measure_mode = None
        self.selected_measurement_point = None
        self.measurement_items = []
        self._restored_legacy_markers = False
        self._refreshing = False
        self._setting_plot_range = False
        self._plot_user_zoomed = False
        self.plot_reticle_mode = "hidden"
        self.plot_reticle_user_choice = False
        self.rectangle_zoom_pending = False
        self.selected_sample_identity = None
        self.tracked_reticle_sample = None

        layout = page_layout(QVBoxLayout(self))
        layout.addWidget(compact_page_header(
            "Analyse d'images",
            "Profils d'intensité pour interférences, diffraction et spectroscopie",
        ))

        toolbar, tools = panel(kind="toolbar", horizontal=True)
        self.open_button = role(QPushButton("Ouvrir une image…"), "primary")
        self.open_button.setToolTip("Ouvrir une photographie JPG, PNG ou BMP.")
        self.open_button.clicked.connect(self.choose_image)
        tools.addWidget(self.open_button)
        self.fit_button = QPushButton("Image entière")
        self.fit_button.setToolTip("Afficher l’intégralité de la photographie.")
        self.fit_button.clicked.connect(lambda: self.canvas.fit_to_window())
        tools.addWidget(self.fit_button)
        self.frame_segment_button = QPushButton("Cadrer le profil")
        self.frame_segment_button.setToolTip(
            "Cadrer le profil actif sans couper ses extrémités, avec une marge confortable.")
        self.frame_segment_button.clicked.connect(self.frame_active_profile)
        tools.addWidget(self.frame_segment_button)
        tools.addStretch()
        layout.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(LIGHT.related)
        self.canvas = ImageAnalysisCanvas()
        self.canvas.segment_drawn.connect(self.add_profile)
        self.canvas.profile_selected.connect(self.activate_profile)
        self.canvas.profile_changed.connect(self.profile_geometry_changed)
        self.canvas.distance_reference_drawn.connect(self.distance_reference_drawn)
        self.canvas.spectral_reference_chosen.connect(self.spectral_reference_chosen)
        self.canvas.calibration_reference_changed.connect(self.calibration_reference_changed)
        self.canvas.pointer_moved.connect(self.pointer_moved)
        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self.canvas)

        self.results = QTabWidget()
        self.profile_view_box = ImageProfileViewBox()
        self.plot = ImageProfilePlot(viewBox=self.profile_view_box)
        self.plot.setBackground(LIGHT.surface)
        self.plot.showGrid(x=True, y=True, alpha=.18)
        self.plot.setLabel("left", "Niveau de gris relatif")
        self.plot.addLegend(offset=(-10, 10))
        self.plot.getPlotItem().setMenuEnabled(False, enableViewBoxMenu=False)
        self.profile_view_box.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.scene().sigMouseClicked.connect(self.plot_clicked)
        self.profile_view_box.sigRangeChanged.connect(self.plot_range_changed)
        self.profile_view_box.rectangle_zoom_finished.connect(self.finish_rectangle_zoom)
        self.selection_line = pg.InfiniteLine(angle=90, movable=False,
                                             pen=pg.mkPen(LIGHT.muted, width=1, style=Qt.PenStyle.DotLine))
        self.selection_dot = pg.ScatterPlotItem(size=9, brush=LIGHT.navy, pen="w")
        self.plot.addItem(self.selection_line, ignoreBounds=True)
        self.plot.addItem(self.selection_dot, ignoreBounds=True)
        self.selection_line.hide()
        self.selection_dot.hide()
        self.cross_x = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen("#64748b", style=Qt.PenStyle.DashLine))
        self.cross_y = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen("#64748b", style=Qt.PenStyle.DashLine))
        for line in (self.cross_x, self.cross_y):
            line.setZValue(10)
            line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.plot.addItem(line, ignoreBounds=True)
            line.hide()
        label_style = (
            f"QLabel {{ color: {LIGHT.text}; background: {LIGHT.surface}; "
            f"border: 1px solid {LIGHT.border_strong}; border-radius: 3px; "
            "padding: 1px 4px; }")
        self.cross_x_label = QLabel()
        self.cross_y_label = QLabel()
        for label in (self.cross_x_label, self.cross_y_label):
            label.setStyleSheet(label_style)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.hide()
        plot_page = QWidget()
        plot_layout = QVBoxLayout(plot_page)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(0)
        self.fit_plot_button = QPushButton("Ajuster la vue")
        self.fit_plot_button.setToolTip("Afficher toutes les courbes visibles et l’ensemble de leurs valeurs.")
        self.fit_plot_button.clicked.connect(self.fit_profile_plot)
        plot_shell = QWidget()
        plot_grid = QGridLayout(plot_shell)
        plot_grid.setContentsMargins(0, 0, 0, 0)
        plot_grid.setHorizontalSpacing(2)
        plot_grid.setVerticalSpacing(1)
        self.cross_y_lane = QWidget()
        self.cross_y_lane.setFixedWidth(58)
        self.cross_y_label.setParent(self.cross_y_lane)
        self.cross_x_lane = QWidget()
        self.cross_x_lane.setFixedHeight(22)
        self.cross_x_label.setParent(self.cross_x_lane)
        plot_grid.addWidget(self.cross_y_lane, 0, 0)
        plot_grid.addWidget(self.plot, 0, 1)
        plot_grid.addWidget(self.cross_x_lane, 1, 1)
        plot_grid.setRowStretch(0, 1)
        plot_grid.setColumnStretch(1, 1)
        plot_layout.addWidget(plot_shell, 1)
        self.plot_coordinates = role(
            ElidedLabel("Réticule désactivé — clic droit pour l’activer."), "caption")
        self.plot_coordinates.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._build_plot_context_menu()
        self.plot.menu_requested.connect(self.show_plot_context_menu)
        self.profile_view_box.menu_requested.connect(self.show_plot_context_menu)
        self.plot.scene().sigMouseMoved.connect(self.track_plot_cursor)
        self.plot.viewport().setMouseTracking(True)
        self.results.addTab(plot_page, "Profils")
        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_actions = QHBoxLayout()
        self.copy_button = QPushButton("Copier la selection")
        self.copy_button.clicked.connect(self.copy_table_selection)
        self.export_button = QPushButton("Exporter en CSV…")
        self.export_button.clicked.connect(self.export_csv)
        table_actions.addWidget(self.copy_button)
        table_actions.addWidget(self.export_button)
        table_actions.addStretch()
        table_layout.addLayout(table_actions)
        self.table_model = ProfileTableModel(self)
        self.table = ProfileTableView()
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self.table_row_changed)
        table_layout.addWidget(self.table)
        self.results.addTab(table_page, "Liste des coordonnées")
        self.results.setCornerWidget(self.fit_plot_button, Qt.Corner.TopRightCorner)
        self.content_splitter.addWidget(self.results)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes([360, 250])
        left_layout.addWidget(self.content_splitter, 1)
        splitter.addWidget(left)

        self.side_scroll = QScrollArea()
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.side_scroll.setMinimumWidth(350)
        self.side_scroll.setMaximumWidth(430)
        side = QWidget()
        side.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(LIGHT.small, 0, LIGHT.small, LIGHT.related)
        side_layout.setSpacing(LIGHT.related)
        self.side_scroll.setWidget(side)
        splitter.addWidget(self.side_scroll)
        splitter.setStretchFactor(0, 1)
        layout.addWidget(splitter, 1)

        workflow_hint = role(QLabel("Ouvrir  →  Échelle  →  Profil  →  Mesurer  →  Transférer"), "caption")
        workflow_hint.setWordWrap(True)
        side_layout.addWidget(workflow_hint)
        self.workflow = QTabWidget()
        side_layout.addWidget(self.workflow, 1)

        scale_page = QWidget()
        scale_layout = QVBoxLayout(scale_page)
        scale_layout.setContentsMargins(LIGHT.small, LIGHT.small, LIGHT.small, LIGHT.small)
        self.calibration_status = role(QLabel("Abscisse en pixels."), "context")
        self.calibration_status.setTextFormat(Qt.TextFormat.RichText)
        self.calibration_status.setWordWrap(True)
        scale_layout.addWidget(self.calibration_status)
        self.define_calibration_button = role(QPushButton("Définir l’échelle"), "primary")
        self.define_calibration_button.clicked.connect(self.begin_calibration)
        scale_layout.addWidget(self.define_calibration_button)
        self.calibration_applied_actions = QWidget()
        applied_actions = QHBoxLayout(self.calibration_applied_actions)
        applied_actions.setContentsMargins(0, 0, 0, 0)
        self.modify_calibration_button = QPushButton("Modifier")
        self.delete_calibration_button = role(QPushButton("Supprimer"), "danger")
        self.modify_calibration_button.clicked.connect(self.begin_calibration)
        self.delete_calibration_button.clicked.connect(self.reset_calibration)
        applied_actions.addWidget(self.modify_calibration_button)
        applied_actions.addWidget(self.delete_calibration_button)
        scale_layout.addWidget(self.calibration_applied_actions)

        self.calibration_editor = QWidget()
        editor_layout = QVBoxLayout(self.calibration_editor)
        editor_layout.setContentsMargins(0, LIGHT.small, 0, 0)
        type_form = QFormLayout()
        self.calibration_mode = PopupComboBox()
        self.calibration_mode.addItem("Distance réelle", "distance")
        self.calibration_mode.addItem("Écart spectral", "spectral")
        configure_popup(self.calibration_mode, 240)
        update_popup_height(self.calibration_mode)
        self.calibration_mode.currentIndexChanged.connect(self.calibration_kind_changed)
        type_form.addRow("Type :", self.calibration_mode)
        editor_layout.addLayout(type_form)
        self.spectral_method_row = QWidget()
        method_form = QFormLayout(self.spectral_method_row)
        method_form.setContentsMargins(0, 0, 0, 0)
        self.spectral_method = PopupComboBox()
        self.spectral_method.addItem("Méthode 1 — Écart connu", "known_gap")
        self.spectral_method.addItem("Méthode 2 — Deux longueurs d’onde", "two_points")
        configure_popup(self.spectral_method, 310)
        update_popup_height(self.spectral_method)
        self.spectral_method.currentIndexChanged.connect(self.spectral_method_changed)
        method_form.addRow("Méthode :", self.spectral_method)
        editor_layout.addWidget(self.spectral_method_row)
        self.distance_button = QPushButton("Tracer le segment étalon")
        self.distance_button.setCheckable(True)
        self.distance_button.clicked.connect(self.start_calibration_segment)
        editor_layout.addWidget(self.distance_button)
        self.calibration_horizontal = QCheckBox("Forcer l’horizontalité")
        self.calibration_horizontal.toggled.connect(self.calibration_horizontal_changed)
        editor_layout.addWidget(self.calibration_horizontal)
        self.calibration_tip = role(QLabel(
            "Tracez entre deux repères, puis ajustez les poignées. La longueur en pixels est calculée automatiquement."),
            "caption")
        self.calibration_tip.setWordWrap(True)
        editor_layout.addWidget(self.calibration_tip)
        self.calibration_segment_values = QWidget()
        value_form = QFormLayout(self.calibration_segment_values)
        value_form.setContentsMargins(0, 0, 0, 0)
        self.calibration_pixel_length = role(QLabel("Segment non tracé"), "caption")
        value_form.addRow("Longueur mesurée :", self.calibration_pixel_length)
        self.distance_value = KnownValueSpinBox()
        self.distance_value.setLocale(QLocale(QLocale.Language.French))
        self.distance_value.setDecimals(6)
        self.distance_value.setRange(0, 1e12)
        self.distance_value.setValue(0)
        self.distance_value.lineEdit().setPlaceholderText("À saisir")
        self.distance_value.lineEdit().clear()
        self.distance_value.valueChanged.connect(self.update_calibration_length)
        self.distance_unit = PopupComboBox()
        self.distance_unit.addItems(["cm", "mm", "µm", "nm", "pm", "Å", "m"])
        configure_popup(self.distance_unit, 120)
        update_popup_height(self.distance_unit)
        self.distance_unit.currentTextChanged.connect(self.spectral_unit_changed)
        value_row = QWidget()
        value_layout = QHBoxLayout(value_row)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.addWidget(self.distance_value, 1)
        value_layout.addWidget(self.distance_unit)
        value_form.addRow("Écart connu :", value_row)
        editor_layout.addWidget(self.calibration_segment_values)
        self.spectral_options = QWidget()
        spectral_layout = QVBoxLayout(self.spectral_options)
        spectral_layout.setContentsMargins(0, 0, 0, 0)
        self.known_gap_options = QWidget()
        spectral_form = QFormLayout(self.known_gap_options)
        spectral_form.setContentsMargins(0, 0, 0, 0)
        self.absolute_reference = QCheckBox("Définir une longueur d’onde absolue")
        self.absolute_reference.toggled.connect(self.calibration_kind_changed)
        spectral_form.addRow("", self.absolute_reference)
        self.absolute_reference_endpoint = PopupComboBox()
        self.absolute_reference_endpoint.addItem("Référence au point A", "A")
        self.absolute_reference_endpoint.addItem("Référence au point B", "B")
        configure_popup(self.absolute_reference_endpoint, 260)
        update_popup_height(self.absolute_reference_endpoint)
        self.absolute_reference_endpoint.currentIndexChanged.connect(
            self.absolute_reference_endpoint_changed)
        spectral_form.addRow("Référence :", self.absolute_reference_endpoint)
        self.absolute_value_label = QLabel(
            "Longueur d’onde au point A (λ<sub>A</sub>)")
        self.absolute_value_label.setTextFormat(Qt.TextFormat.RichText)
        self.absolute_value_label.setWordWrap(True)
        self.absolute_value_label.setMinimumHeight(self.absolute_value_label.sizeHint().height())
        self.absolute_value_label.setAccessibleName("Longueur d’onde au point A (lambda A)")
        spectral_form.addRow(self.absolute_value_label)
        self.absolute_value = KnownValueSpinBox()
        self.absolute_value.setLocale(QLocale(QLocale.Language.French))
        self.absolute_value.setDecimals(6)
        self.absolute_value.setRange(0, 1e9)
        self.absolute_value.lineEdit().setPlaceholderText("À saisir")
        self.absolute_value.lineEdit().clear()
        self.absolute_value.valueChanged.connect(self.update_calibration_length)
        self.absolute_value.setSuffix(" nm")
        self.absolute_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        spectral_form.addRow(self.absolute_value)
        self.spectral_direction = PopupComboBox()
        self.spectral_direction.addItem("Croissante vers la droite", 1)
        self.spectral_direction.addItem("Croissante vers la gauche", -1)
        configure_popup(self.spectral_direction, 250)
        update_popup_height(self.spectral_direction)
        spectral_form.addRow("Sens de l’axe :", self.spectral_direction)
        spectral_layout.addWidget(self.known_gap_options)

        self.two_point_options = QWidget()
        two_point_layout = QVBoxLayout(self.two_point_options)
        two_point_layout.setContentsMargins(0, 0, 0, 0)
        point_actions = QHBoxLayout()
        self.place_spectral_a_button = QPushButton("Placer le point A")
        self.place_spectral_b_button = QPushButton("Placer le point B")
        self.place_spectral_a_button.clicked.connect(lambda: self.start_spectral_point(0))
        self.place_spectral_b_button.clicked.connect(lambda: self.start_spectral_point(1))
        point_actions.addWidget(self.place_spectral_a_button)
        point_actions.addWidget(self.place_spectral_b_button)
        two_point_layout.addLayout(point_actions)
        self.two_point_status = role(QLabel("Points A et B non placés."), "caption")
        self.two_point_status.setTextFormat(Qt.TextFormat.RichText)
        self.two_point_status.setWordWrap(True)
        two_point_layout.addWidget(self.two_point_status)
        two_point_form = QFormLayout()
        self.first_wavelength_label = QLabel("Longueur d’onde au point A (λ<sub>A</sub>)")
        self.second_wavelength_label = QLabel("Longueur d’onde au point B (λ<sub>B</sub>)")
        for label in (self.first_wavelength_label, self.second_wavelength_label):
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            label.setMinimumHeight(label.sizeHint().height())
        self.first_wavelength = KnownValueSpinBox()
        self.second_wavelength = KnownValueSpinBox()
        for field in (self.first_wavelength, self.second_wavelength):
            field.setLocale(QLocale(QLocale.Language.French))
            field.setDecimals(6)
            field.setRange(0, 1e9)
            field.setSuffix(" nm")
            field.lineEdit().setPlaceholderText("À saisir")
            field.lineEdit().clear()
            field.valueChanged.connect(self.update_calibration_length)
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        two_point_form.addRow(self.first_wavelength_label)
        two_point_form.addRow(self.first_wavelength)
        two_point_form.addRow(self.second_wavelength_label)
        two_point_form.addRow(self.second_wavelength)
        two_point_layout.addLayout(two_point_form)
        spectral_layout.addWidget(self.two_point_options)
        editor_layout.addWidget(self.spectral_options)
        editor_actions = QHBoxLayout()
        self.apply_calibration_button = role(QPushButton("Valider l’échelle"), "primary")
        self.cancel_calibration_button = QPushButton("Annuler")
        self.apply_calibration_button.clicked.connect(self.apply_calibration)
        self.cancel_calibration_button.clicked.connect(self.cancel_calibration)
        editor_actions.addWidget(self.apply_calibration_button)
        editor_actions.addWidget(self.cancel_calibration_button)
        editor_layout.addLayout(editor_actions)
        scale_layout.addWidget(self.calibration_editor)
        scale_layout.addStretch()
        self.workflow.addTab(scale_page, "1 · Échelle")

        profiles_page = QWidget()
        profiles_page_layout = QVBoxLayout(profiles_page)
        profiles_page_layout.setContentsMargins(LIGHT.small, LIGHT.small, LIGHT.small, LIGHT.small)
        self.draw_button = role(QPushButton("Tracer un profil"), "primary")
        self.draw_button.setCheckable(True)
        self.draw_button.setToolTip(
            "Tracer un nouveau segment de profil ; il redevient directement manipulable ensuite.")
        self.draw_button.clicked.connect(lambda: self.set_mode("draw"))
        profiles_page_layout.addWidget(self.draw_button)
        self.profile_horizontal = QCheckBox("Forcer l’horizontalité")
        self.profile_horizontal.toggled.connect(self.profile_horizontal_changed)
        profiles_page_layout.addWidget(self.profile_horizontal)
        self.profile_empty_label = role(QLabel("Tracez un segment sur l’image pour créer un profil."), "context")
        self.profile_empty_label.setWordWrap(True)
        profiles_page_layout.addWidget(self.profile_empty_label)
        self.profile_editor = QWidget()
        profiles_layout = QVBoxLayout(self.profile_editor)
        profiles_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.profile_choice = PopupComboBox()
        configure_popup(self.profile_choice, 260)
        self.profile_choice.currentIndexChanged.connect(self.profile_selected)
        form.addRow("Profil actif :", self.profile_choice)
        self.profile_name = QLineEdit()
        self.profile_name.editingFinished.connect(self.rename_profile)
        form.addRow("Nom :", self.profile_name)
        self.profile_visible = QCheckBox("Afficher dans la comparaison")
        self.profile_visible.toggled.connect(self.profile_visibility_changed)
        form.addRow("", self.profile_visible)
        self.profile_width = QSpinBox()
        self.profile_width.setRange(1, 51)
        self.profile_width.setSuffix(" px")
        self.profile_width.valueChanged.connect(self.profile_width_changed)
        form.addRow("Largeur moyennée :", self.profile_width)
        profiles_layout.addLayout(form)
        self.geometry_label = role(QLabel("Aucun segment."), "caption")
        self.geometry_label.setWordWrap(True)
        profiles_layout.addWidget(self.geometry_label)
        self.delete_profile_button = role(QPushButton("Supprimer le profil"), "danger")
        self.delete_profile_button.clicked.connect(self.delete_profile)
        profiles_layout.addWidget(self.delete_profile_button)
        profiles_page_layout.addWidget(self.profile_editor)
        profiles_page_layout.addStretch()
        self.workflow.addTab(profiles_page, "2 · Profil")

        markers_page = QWidget()
        markers_layout = QVBoxLayout(markers_page)
        markers_layout.setContentsMargins(LIGHT.small, LIGHT.small, LIGHT.small, LIGHT.small)
        marker_actions = QHBoxLayout()
        self.gap_button = QPushButton("Mesurer un écart")
        self.interfringe_button = QPushButton("Mesurer l’interfrange")
        for button in (self.gap_button, self.interfringe_button):
            button.setCheckable(True)
        self.measurement_button_group = QButtonGroup(self)
        self.measurement_button_group.setExclusive(True)
        self.measurement_button_group.addButton(self.gap_button)
        self.measurement_button_group.addButton(self.interfringe_button)
        self.gap_button.clicked.connect(lambda: self.start_measurement("gap"))
        self.interfringe_button.clicked.connect(lambda: self.start_measurement("interfringe"))
        marker_actions.addWidget(self.gap_button)
        marker_actions.addWidget(self.interfringe_button)
        markers_layout.addLayout(marker_actions)
        measure_form = QFormLayout()
        self.snap_choice = PopupComboBox()
        self.snap_choice.addItem("Libre sur la courbe", "manual")
        self.snap_choice.addItem("Minimum proche", "minimum")
        self.snap_choice.addItem("Maximum proche", "maximum")
        configure_popup(self.snap_choice, 280)
        update_popup_height(self.snap_choice)
        self.snap_choice.currentIndexChanged.connect(self.measurement_snap_changed)
        measure_form.addRow("Positionnement :", self.snap_choice)
        self.intervals_spin = QSpinBox()
        self.intervals_spin.setRange(1, 999)
        self.intervals_spin.setValue(1)
        self.intervals_spin.setFixedWidth(68)
        self.intervals_spin.valueChanged.connect(self.measurement_intervals_changed)
        self.intervals_label = role(QLabel("Nombre d'interfranges"), "fieldLabel")
        intervals_row = QHBoxLayout()
        intervals_row.setContentsMargins(0, 0, 0, 0)
        intervals_row.addWidget(self.intervals_label)
        intervals_row.addStretch()
        intervals_row.addWidget(self.intervals_spin)
        measure_form.addRow(intervals_row)
        markers_layout.addLayout(measure_form)
        self.measurement_instruction = role(QLabel("Choisissez un type de mesure."), "caption")
        self.measurement_instruction.setWordWrap(True)
        markers_layout.addWidget(self.measurement_instruction)
        self.measurement_points_label = QLabel("A : —\nB : —")
        self.measurement_points_label.setWordWrap(True)
        markers_layout.addWidget(self.measurement_points_label)
        self.measurement_label = role(QLabel("Aucune mesure."), "context")
        self.measurement_label.setWordWrap(True)
        markers_layout.addWidget(self.measurement_label)
        marker_edit_actions = QHBoxLayout()
        self.delete_marker_button = role(QPushButton("Supprimer un repère"), "danger")
        self.clear_measurement_button = QPushButton("Effacer la mesure")
        self.delete_marker_button.clicked.connect(self.delete_selected_measurement_point)
        self.clear_measurement_button.clicked.connect(self.clear_measurement)
        marker_edit_actions.addWidget(self.delete_marker_button)
        marker_edit_actions.addWidget(self.clear_measurement_button)
        markers_layout.addLayout(marker_edit_actions)
        markers_layout.addStretch()
        self.workflow.addTab(markers_page, "3 · Mesurer")
        self.workflow.currentChanged.connect(self.workflow_page_changed)

        transfer_panel, transfer_layout = panel("4 · Transférer")
        self.transfer_button = role(QPushButton("Transférer le profil actif"), "primary")
        self.transfer_visible_button = QPushButton("Transférer les profils visibles")
        self.transfer_button.clicked.connect(self.transfer_active)
        self.transfer_visible_button.clicked.connect(self.transfer_visible)
        transfer_layout.addWidget(self.transfer_button)
        transfer_layout.addWidget(self.transfer_visible_button)
        side_layout.addWidget(transfer_panel)

        compact_status = QHBoxLayout()
        compact_status.setContentsMargins(0, 0, 0, 0)
        compact_status.setSpacing(LIGHT.group)
        compact_status.addWidget(self.plot_coordinates, 2)
        self.image_info = role(ElidedLabel("Aucune image"), "caption")
        self.image_info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        compact_status.addWidget(self.image_info, 1)
        self.status = role(ElidedLabel("Ouvrez une image pour commencer."), "caption")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        compact_status.addWidget(self.status, 2)
        layout.addLayout(compact_status)
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.activated.connect(self.cancel_current_action)
        self.calibration_editor.hide()
        self.update_measurement_buttons()
        self.set_mode("normal")
        self.refresh_controls()
        self.workflow_page_changed(self.workflow.currentIndex())

    def active_profile(self):
        return next((item for item in self.profiles if item.identifier == self.active_identifier), None)

    def workflow_page_changed(self, index):
        """Les repères orange n'appartiennent qu'à l'étape d'étalonnage."""
        scale_page = index == 0
        self.canvas.set_calibration_visible(scale_page)
        if not scale_page and self.canvas.mode in (
                "calibration_draw", "calibration_edit", "distance", "spectral"):
            self.set_mode("normal")
        elif scale_page and self.calibration_editor.isVisible():
            if self.calibration_reference and all(
                    point is not None for point in self.calibration_reference):
                self.set_mode("calibration_edit")
            elif not self._uses_two_spectral_points():
                self.set_mode("calibration_draw")

    def _build_plot_context_menu(self):
        self.plot_context_menu = QMenu(self)
        self.quick_reticle_action = self.plot_context_menu.addAction(
            "Afficher le réticule", self.toggle_plot_reticle)
        font = self.quick_reticle_action.font()
        font.setBold(True)
        self.quick_reticle_action.setFont(font)
        self.plot_context_menu.addSeparator()
        self.plot_context_menu.addAction("Ajuster la vue", self.fit_profile_plot)
        self.plot_context_menu.addAction("Zoom avant", lambda: self.zoom_profile_plot(.5))
        self.plot_context_menu.addAction("Zoom arrière", lambda: self.zoom_profile_plot(2))
        self.plot_context_menu.aboutToShow.connect(self.update_quick_reticle_action)

    def update_quick_reticle_action(self):
        self.quick_reticle_action.setText(
            "Masquer le réticule"
            if self.plot_reticle_mode != "hidden" else "Afficher le réticule")

    def toggle_plot_reticle(self):
        if self.plot_reticle_mode == "hidden":
            self.set_plot_reticle_mode("curve")
        else:
            self.set_plot_reticle_mode("hidden")

    def show_plot_context_menu(self, position):
        if self.plot_context_menu.isVisible():
            return
        self.hide_plot_crosshair()
        self.update_quick_reticle_action()
        self.plot_context_menu.popup(position)

    def zoom_profile_plot(self, factor):
        self.profile_view_box.scaleBy((factor, factor))

    def start_rectangle_zoom(self):
        self.rectangle_zoom_pending = True
        self.hide_plot_crosshair()
        self.profile_view_box.setMouseMode(pg.ViewBox.RectMode)

    def finish_rectangle_zoom(self):
        if self.rectangle_zoom_pending:
            self.rectangle_zoom_pending = False
            self.profile_view_box.setMouseMode(pg.ViewBox.PanMode)

    def set_plot_reticle_mode(self, mode, user_choice=True):
        if mode not in ("hidden", "free", "curve"):
            mode = "hidden"
        if user_choice:
            self.plot_reticle_user_choice = True
        self.plot_reticle_mode = mode
        self.update_quick_reticle_action()
        self.hide_plot_crosshair()

    def update_default_plot_reticle(self):
        has_profile = any(
            profile.visible and self.samples.get(profile.identifier) is not None
            for profile in self.profiles)
        if has_profile and not self.plot_reticle_user_choice and self.plot_reticle_mode == "hidden":
            self.set_plot_reticle_mode("curve", user_choice=False)
        elif not has_profile and not self.plot_reticle_user_choice:
            self.set_plot_reticle_mode("hidden", user_choice=False)

    def hide_plot_crosshair(self, *args):
        self.tracked_reticle_sample = None
        for item in (self.cross_x, self.cross_y, self.cross_x_label, self.cross_y_label):
            item.hide()
        self.canvas.set_hover_sample_marker()
        message = {
            "hidden": "Réticule désactivé — clic droit pour l’activer.",
            "free": "Réticule libre — survolez le graphique pour lire les coordonnées.",
            "curve": "Réticule sur une courbe — survolez le graphique.",
        }[self.plot_reticle_mode]
        self.plot_coordinates.setText(message)

    def nearest_visible_profile_sample(self, scene_position):
        """Choisir l'échantillon rendu le plus proche sans ambiguïté d'abscisse."""
        best = None
        ambiguous = False
        pointer = self.profile_view_box.mapSceneToView(scene_position)
        x_range, y_range = self.profile_view_box.viewRange()
        x_scale = self.profile_view_box.width() / max(abs(x_range[1] - x_range[0]), 1e-12)
        y_scale = self.profile_view_box.height() / max(abs(y_range[1] - y_range[0]), 1e-12)
        for profile in self.profiles:
            samples = self.samples.get(profile.identifier)
            if not profile.visible or samples is None or not len(samples.axis):
                continue
            distances = ((samples.axis - pointer.x()) * x_scale) ** 2 + (
                (samples.intensity - pointer.y()) * y_scale) ** 2
            finite = np.isfinite(distances)
            if not np.any(finite):
                continue
            index = int(np.nanargmin(np.where(finite, distances, np.nan)))
            point = QPointF(float(samples.axis[index]), float(samples.intensity[index]))
            distance = float(distances[index])
            if best is None or distance < best[0] - 1e-9:
                best = distance, profile, samples, index, point
                ambiguous = False
            elif abs(distance - best[0]) <= 1e-9:
                if profile.identifier == self.active_identifier:
                    best = distance, profile, samples, index, point
                    ambiguous = False
                elif best[1].identifier != self.active_identifier:
                    ambiguous = True
        return None if ambiguous else best

    def track_plot_cursor(self, scene_position):
        if (self.plot_reticle_mode == "hidden" or self.plot_context_menu.isVisible()
                or not self.profile_view_box.sceneBoundingRect().contains(scene_position)):
            self.hide_plot_crosshair()
            return
        point = self.profile_view_box.mapSceneToView(scene_position)
        profile = None
        if self.plot_reticle_mode == "curve":
            nearest = self.nearest_visible_profile_sample(scene_position)
            if nearest is None:
                self.hide_plot_crosshair()
                return
            _, profile, samples, index, point = nearest
            self.tracked_reticle_sample = profile.identifier, index
            self.canvas.set_hover_sample_marker(
                (float(samples.x[index]), float(samples.y[index])), profile.color)
        else:
            self.tracked_reticle_sample = None
            self.canvas.set_hover_sample_marker()
        x_value, y_value = point.x(), point.y()
        self.cross_x.setPos(x_value)
        self.cross_y.setPos(y_value)
        self.cross_x.show()
        self.cross_y.show()
        x_text, y_text = number(x_value), number(y_value)
        self.cross_x_label.setText(x_text)
        self.cross_y_label.setText(y_text)
        self.cross_x_label.adjustSize()
        self.cross_y_label.adjustSize()
        plot_point = self.plot.mapFromScene(
            self.profile_view_box.mapViewToScene(QPointF(x_value, y_value)))
        x_left = min(max(0, round(plot_point.x() - self.cross_x_label.width() / 2)),
                     max(0, self.cross_x_lane.width() - self.cross_x_label.width()))
        y_top = min(max(0, round(plot_point.y() - self.cross_y_label.height() / 2)),
                    max(0, self.cross_y_lane.height() - self.cross_y_label.height()))
        self.cross_x_label.move(x_left, 0)
        self.cross_y_label.move(
            max(0, self.cross_y_lane.width() - self.cross_y_label.width()), y_top)
        self.cross_x_label.show()
        self.cross_y_label.show()
        unit = self.calibration.unit
        axis = self.calibration.axis_name
        x_caption = f"{axis} = {x_text}" + (f" {unit}" if unit else "")
        prefix = f"{profile.name} · " if profile is not None else ""
        self.plot_coordinates.setText(
            f"{prefix}{x_caption} · Intensité = {y_text}")

    def set_mode(self, mode, spectral_target=0):
        if mode in ("pan", "edit"):
            mode = "normal"
        if mode != "pan" and self.image.isNull():
            return
        if mode == "draw" and self.measure_mode is not None:
            self.measure_mode = None
            self.update_measurement_buttons()
            self.measurement_instruction.setText(
                "Mesure conservée. Terminez le tracé du nouveau profil, puis reprenez-la si nécessaire.")
        self.draw_button.blockSignals(True)
        self.draw_button.setChecked(mode == "draw")
        self.draw_button.blockSignals(False)
        if hasattr(self, "distance_button"):
            self.distance_button.blockSignals(True)
            self.distance_button.setChecked(mode in ("calibration_draw", "calibration_edit"))
            self.distance_button.blockSignals(False)
        self.canvas.set_horizontal_constraints(
            self.profile_horizontal.isChecked() if hasattr(self, "profile_horizontal") else False,
            self.calibration_horizontal.isChecked() if hasattr(self, "calibration_horizontal") else False,
        )
        self.canvas.set_mode(mode, spectral_target)
        hints = {
            "normal": "Glissez un segment ou ses extrémités. Molette : zoom ; bouton central ou Espace + glisser : déplacer l’image.",
            "draw": "Cliquez sur A, déplacez la souris, puis cliquez sur B pour tracer le profil.",
            "distance": "Cliquez sur A, puis sur B pour tracer le segment correspondant à la distance connue.",
            "calibration_draw": "Cliquez sur A, puis sur B pour tracer le segment étalon.",
            "calibration_edit": "Ajustez les extrémités du segment étalon, puis validez l’échelle.",
            "spectral": f"Cliquez sur la position réelle du point {'A' if spectral_target == 0 else 'B'}.",
        }
        self.status.setText(hints.get(mode, ""))

    def cancel_current_action(self):
        if self.calibration_editor.isVisible():
            self.cancel_calibration()
        elif self.measure_mode is not None:
            self.measure_mode = None
            self.update_measurement_buttons()
            self.measurement_instruction.setText("Mesure conservée. Déplacez A ou B, ou recommencez une mesure.")
        else:
            self.canvas.drag_start = self.canvas.preview_end = None
            self.set_mode("normal")

    def frame_active_profile(self):
        profile = self.active_profile()
        if profile:
            self.canvas.frame_segment(profile.start, profile.end)

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir une image", "", "Images (*.jpg *.jpeg *.png *.bmp)")
        if path:
            self.open_image(path)

    def open_image(self, path):
        path = Path(path)
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp"):
            QMessageBox.warning(self, "Format non pris en charge", "Choisissez une image JPG, PNG ou BMP.")
            return False
        try:
            if path.stat().st_size > MAX_IMAGE_FILE_SIZE:
                raise ValueError("L'image depasse la taille maximale de 64 Mo.")
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Ouverture impossible", str(error))
            return False
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            QMessageBox.critical(self, "Ouverture impossible", reader.errorString())
            return False
        if image.width() * image.height() > MAX_IMAGE_PIXELS:
            QMessageBox.warning(self, "Image trop grande", "L'image depasse la limite de 50 millions de pixels.")
            return False
        try:
            encoded = portable_png(image)
        except ValueError as error:
            QMessageBox.critical(self, "Image impossible a integrer", str(error))
            return False
        self.load_image(image, encoded, path.name)
        self.status.setText("Image intégrée au projet.")
        return True

    def load_image(self, image, encoded, name):
        self.image, self.image_bytes, self.image_name = QImage(image), bytes(encoded), str(name)
        self.image_info.setText(
            f"{self.image_name} · {self.image.width()} × {self.image.height()} px")
        self.gray = qimage_grayscale(self.image)
        self.profiles = []
        self.active_identifier = None
        self.samples = {}
        self.measurement = ProfileMeasurement()
        self.measure_mode = None
        self.selected_measurement_point = None
        self.selected_sample_identity = None
        self.canvas.set_hover_sample_marker()
        self.canvas.set_selected_sample_marker()
        self._plot_user_zoomed = False
        self.reset_calibration()
        self.canvas.set_image(self.image)
        self.sync_profile_choice()
        self.refresh_profiles()
        self.workflow.setCurrentIndex(0)
        self.set_mode("normal")

    def add_profile(self, start, end):
        if len(self.profiles) >= MAX_PROFILES:
            QMessageBox.warning(self, "Trop de profils", f"Un maximum de {MAX_PROFILES} profils est autorise.")
            return
        number_value = len(self.profiles) + 1
        profile = IntensityProfile(
            f"Profil {number_value}", (start.x(), start.y()), (end.x(), end.y()),
            color=SERIES_COLORS[len(self.profiles) % len(SERIES_COLORS)],
            horizontal=self.profile_horizontal.isChecked(),
        )
        self.profiles.append(profile)
        self.active_identifier = profile.identifier
        self.sync_profile_choice()
        self.refresh_profiles()
        self.workflow.setCurrentIndex(1)
        self.set_mode("normal")

    def sync_profile_choice(self):
        self.profile_choice.blockSignals(True)
        self.profile_choice.clear()
        for profile in self.profiles:
            self.profile_choice.addItem(profile.name, profile.identifier)
        index = self.profile_choice.findData(self.active_identifier)
        self.profile_choice.setCurrentIndex(index)
        self.profile_choice.blockSignals(False)
        update_popup_height(self.profile_choice)

    def profile_selected(self, index):
        identifier = self.profile_choice.itemData(index)
        if identifier is not None:
            self.activate_profile(identifier)

    def activate_profile(self, identifier):
        if not any(profile.identifier == identifier for profile in self.profiles):
            return
        self.active_identifier = identifier
        index = self.profile_choice.findData(identifier)
        self.profile_choice.blockSignals(True)
        self.profile_choice.setCurrentIndex(index)
        self.profile_choice.blockSignals(False)
        self.canvas.set_profiles(self.profiles, self.active_identifier)
        self.refresh_profiles(fit_plot=False)

    def rename_profile(self):
        profile = self.active_profile()
        if profile is None:
            return
        name = self.profile_name.text().strip()
        if not name:
            self.profile_name.setText(profile.name)
            return
        profile.name = name[:200]
        self.sync_profile_choice()
        self.refresh_plot(fit=False)
        self.refresh_measurement()

    def profile_visibility_changed(self, checked):
        if self._refreshing:
            return
        profile = self.active_profile()
        if profile:
            profile.visible = checked
            self.canvas.update()
            self.refresh_plot(fit=True)
            self.refresh_measurement()

    def profile_width_changed(self, value):
        if self._refreshing:
            return
        profile = self.active_profile()
        if profile:
            profile.width = value
            self.profile_geometry_changed(profile.identifier)

    def profile_horizontal_changed(self, checked):
        if self._refreshing:
            return
        self.profile_horizontal_default = bool(checked)
        profile = self.active_profile()
        if profile is not None:
            profile.horizontal = bool(checked)
            if checked and profile.end[1] != profile.start[1]:
                profile.end = profile.end[0], profile.start[1]
                self.profile_geometry_changed(profile.identifier)
            else:
                self.canvas.update()
        self.canvas.set_horizontal_constraints(
            checked, self.calibration_horizontal.isChecked())

    def delete_profile(self):
        profile = self.active_profile()
        if profile is None:
            return
        if (self.selected_sample_identity is not None
                and self.selected_sample_identity[0] == profile.identifier):
            self.selected_sample_identity = None
            self.canvas.set_selected_sample_marker()
        self.profiles.remove(profile)
        self.samples.pop(profile.identifier, None)
        first_removed = (self.measurement.first is not None
                         and self.measurement.first.profile_identifier == profile.identifier)
        second_removed = (self.measurement.second is not None
                          and self.measurement.second.profile_identifier == profile.identifier)
        if first_removed:
            self.measurement.first = None if second_removed else self.measurement.second
            self.measurement.second = None
        elif second_removed:
            self.measurement.second = None
        if first_removed or second_removed:
            self.selected_measurement_point = "A" if self.measurement.first else None
            self.measure_mode = self.measurement.mode if self.measurement.first else None
            self.measurement_instruction.setText(
                "Point A conservé. Cliquez sur un nouveau point B."
                if self.measurement.first else "La mesure associée au profil supprimé a été effacée.")
            self.update_measurement_buttons()
        self.active_identifier = self.profiles[0].identifier if self.profiles else None
        self.sync_profile_choice()
        self.refresh_profiles(fit_plot=not self._plot_user_zoomed)

    def profile_geometry_changed(self, identifier):
        profile = next((item for item in self.profiles if item.identifier == identifier), None)
        if profile is None:
            return
        try:
            self.samples[identifier] = extract_profile(self.gray, profile, self.calibration)
        except ValueError as error:
            self.status.setText(str(error))
        self.refresh_profiles(fit_plot=not self._plot_user_zoomed)

    def begin_calibration(self):
        if self.image.isNull():
            return
        self.workflow.setCurrentIndex(0)
        self.calibration_editor.show()
        self.define_calibration_button.hide()
        self.calibration_applied_actions.hide()
        if self.calibration.mode != "none":
            self.calibration_mode.setCurrentIndex(self.calibration_mode.findData(self.calibration.mode))
            self.calibration_reference = (self.calibration.first, self.calibration.second)
            self.calibration_horizontal.blockSignals(True)
            self.calibration_horizontal.setChecked(self.calibration.horizontal)
            self.calibration_horizontal.blockSignals(False)
            self.distance_unit.setCurrentText(self.calibration.unit)
            if self.calibration.mode == "spectral":
                self.spectral_method.blockSignals(True)
                self.spectral_method.setCurrentIndex(
                    self.spectral_method.findData(self.calibration.spectral_method))
                self.spectral_method.blockSignals(False)
                self.spectral_points = [self.calibration.first, self.calibration.second]
                self.distance_value.setValue(abs(
                    self.calibration.second_value - self.calibration.first_value))
                self.absolute_reference.setChecked(self.calibration.absolute)
                self.absolute_reference_endpoint.setCurrentIndex(
                    self.absolute_reference_endpoint.findData(
                        self.calibration.reference_endpoint))
                reference_value = (self.calibration.first_value
                                   if self.calibration.reference_endpoint == "A"
                                   else self.calibration.second_value)
                self.absolute_value.setValue(reference_value)
                self.first_wavelength.setValue(self.calibration.first_value)
                self.second_wavelength.setValue(self.calibration.second_value)
                slope = (self.calibration.second_value - self.calibration.first_value) / (
                    self.calibration.second[0] - self.calibration.first[0])
                self.spectral_direction.setCurrentIndex(0 if slope > 0 else 1)
            else:
                self.distance_value.setValue(self.calibration.first_value)
        else:
            self.calibration_reference = None
            self.spectral_points = [None, None]
            self.distance_value.setValue(0)
            self.distance_value.lineEdit().clear()
            self.absolute_reference.setChecked(False)
        self.canvas.set_calibration_reference(
            self.calibration_reference, self._uses_two_spectral_points())
        self.calibration_kind_changed()
        self.update_calibration_length()
        self.set_mode("calibration_edit" if self.calibration_reference else
                      ("normal" if self._uses_two_spectral_points() else "calibration_draw"))

    def _uses_two_spectral_points(self):
        return (self.calibration_mode.currentData() == "spectral"
                and self.spectral_method.currentData() == "two_points")

    def calibration_kind_changed(self, *args):
        spectral = self.calibration_mode.currentData() == "spectral"
        two_points = spectral and self._uses_two_spectral_points()
        segment_based = not spectral or not two_points
        self.spectral_method_row.setVisible(spectral)
        self.distance_button.setVisible(segment_based)
        self.calibration_horizontal.setVisible(segment_based)
        self.calibration_tip.setVisible(segment_based)
        self.calibration_segment_values.setVisible(segment_based)
        self.spectral_options.setVisible(spectral)
        self.known_gap_options.setVisible(spectral and not two_points)
        self.two_point_options.setVisible(two_points)
        absolute = spectral and not two_points and self.absolute_reference.isChecked()
        self.absolute_reference_endpoint.setVisible(absolute)
        endpoint_label = self.known_gap_options.layout().labelForField(
            self.absolute_reference_endpoint)
        if endpoint_label is not None:
            endpoint_label.setVisible(absolute)
        self.absolute_value.setVisible(absolute)
        self.absolute_value_label.setVisible(absolute)
        if spectral and self.distance_unit.currentText() not in ("nm", "pm", "Å"):
            self.distance_unit.setCurrentText("nm")
        if two_points:
            self.distance_unit.setCurrentText("nm")
        self.calibration_tip.setText(
            "Pour un spectre, seule la projection horizontale Δx du segment est utilisée. "
            "L’écart saisi ne devient une longueur d’onde absolue que si la référence λ est activée."
            if spectral else
            "La longueur euclidienne du segment est utilisée. Tracez-le entre deux repères de distance connue.")
        self.update_calibration_length()
        if self.calibration_editor.isVisible() and self.calibration_reference is None:
            if two_points and self.canvas.mode == "calibration_draw":
                self.set_mode("normal")
            elif segment_based and self.canvas.mode == "normal":
                self.set_mode("calibration_draw")

    def spectral_method_changed(self, *args):
        self.calibration_reference = None
        self.spectral_points = [None, None]
        self.canvas.set_calibration_reference(None, self._uses_two_spectral_points())
        self.calibration_kind_changed()
        self.set_mode("normal" if self._uses_two_spectral_points() else "calibration_draw")

    def absolute_reference_endpoint_changed(self, *args):
        endpoint = self.absolute_reference_endpoint.currentData() or "A"
        self.absolute_value_label.setText(
            f"Longueur d’onde au point {endpoint} (λ<sub>{endpoint}</sub>)")
        self.absolute_value_label.setAccessibleName(
            f"Longueur d’onde au point {endpoint} (lambda {endpoint})")

    def calibration_horizontal_changed(self, checked):
        self.calibration_horizontal_preference = bool(checked)
        self.canvas.set_horizontal_constraints(
            self.profile_horizontal.isChecked(), checked)
        if (checked and self.calibration_reference
                and all(point is not None for point in self.calibration_reference)):
            first, second = self.calibration_reference
            if first[1] != second[1]:
                self.calibration_reference = (first, (second[0], first[1]))
                if self.calibration.mode != "none":
                    self.calibration = ImageCalibration()
                    self.distance_reference = None
                    self.canvas.set_calibration(self.calibration)
                    self.refresh_profiles(fit_plot=False)
                    self.status.setText(
                        "Le segment étalon a été rendu horizontal : validez de nouveau l’échelle.")
                self.canvas.set_calibration_reference(
                    self.calibration_reference, self._uses_two_spectral_points())
                self.update_calibration_length()

    def spectral_unit_changed(self, unit):
        self.absolute_value.setSuffix(f" {unit}")

    def start_calibration_segment(self):
        self.calibration_reference = None
        self.spectral_points = [None, None]
        self.canvas.set_calibration_reference(None, False)
        self.set_mode("calibration_draw")

    def calibration_reference_changed(self, start, end):
        if self.calibration_horizontal.isChecked() and not self._uses_two_spectral_points():
            end.setY(start.y())
        self.calibration_reference = ((start.x(), start.y()), (end.x(), end.y()))
        if self.calibration_mode.currentData() == "spectral":
            self.spectral_points = list(self.calibration_reference)
        self.canvas.set_calibration_reference(
            self.calibration_reference, self._uses_two_spectral_points())
        self.update_calibration_length()
        if self.canvas.mode != "calibration_edit":
            self.set_mode("calibration_edit")

    def update_calibration_length(self):
        if self._uses_two_spectral_points():
            points = self.spectral_points
            placed = sum(point is not None for point in points)
            self.two_point_status.setText(
                "Points A et B placés. Ajustez les poignées si nécessaire."
                if placed == 2 else
                ("Point A placé ; placez le point B." if points[0] is not None else
                 "Point B placé ; placez le point A." if points[1] is not None else
                 "Points A et B non placés."))
            valid_points = (placed == 2 and abs(points[1][0] - points[0][0]) >= 1)
            valid_values = (self.first_wavelength.value() > 0
                            and self.second_wavelength.value() > 0
                            and self.first_wavelength.value() != self.second_wavelength.value())
            if valid_points and valid_values:
                signed_gap = self.second_wavelength.value() - self.first_wavelength.value()
                factor = signed_gap / (points[1][0] - points[0][0])
                direction = ("droite" if factor > 0 else "gauche")
                self.two_point_status.setText(
                    "Points A et B placés · "
                    f"λ<sub>B</sub> − λ<sub>A</sub> = {number(signed_gap)} nm · "
                    f"|Δλ| = {number(abs(signed_gap))} nm · "
                    f"{number(factor)} nm/px · croissante vers la {direction}.")
            self.apply_calibration_button.setEnabled(valid_points and valid_values)
            return
        if not self.calibration_reference:
            self.calibration_pixel_length.setText("Segment non tracé")
            self.distance_button.setText("Tracer le segment étalon")
            self.apply_calibration_button.setEnabled(False)
            return
        first, second = self.calibration_reference
        if self.calibration_mode.currentData() == "spectral":
            length = abs(second[0] - first[0])
            text = f"{number(length)} px horizontalement"
        else:
            length = np.hypot(second[0] - first[0], second[1] - first[1])
            text = f"{number(length)} px"
        self.calibration_pixel_length.setText(text)
        self.distance_button.setText("Retracer le segment étalon")
        absolute_valid = (not self.absolute_reference.isChecked()
                          or self.absolute_value.value() > 0)
        self.apply_calibration_button.setEnabled(
            length >= 1 and self.distance_value.value() > 0 and absolute_valid)

    def apply_calibration(self):
        two_points = self._uses_two_spectral_points()
        if two_points:
            self.calibration_reference = tuple(self.spectral_points)
        if (not self.calibration_reference or any(point is None for point in self.calibration_reference)
                or (not two_points and self.distance_value.value() <= 0)):
            self.status.setText("Tracez le segment étalon et saisissez un écart connu positif.")
            return
        if (two_points and (self.first_wavelength.value() <= 0
                            or self.second_wavelength.value() <= 0)):
            self.status.setText("Saisissez deux longueurs d’onde positives.")
            return
        mode = self.calibration_mode.currentData()
        first, second = self.calibration_reference
        try:
            if mode == "distance":
                calibration = ImageCalibration(
                    "distance", self.distance_unit.currentText(), first, second,
                    self.distance_value.value(), horizontal=self.calibration_horizontal.isChecked())
                self.distance_reference = self.calibration_reference
                self.spectral_points = [None, None]
            elif not two_points:
                gap = self.distance_value.value()
                direction = self.spectral_direction.currentData()
                signed_gap = direction * (1 if second[0] > first[0] else -1) * gap
                endpoint = self.absolute_reference_endpoint.currentData() or "A"
                reference_value = self.absolute_value.value()
                if not self.absolute_reference.isChecked():
                    first_value, second_value, endpoint = 0.0, signed_gap, "A"
                elif endpoint == "A":
                    first_value, second_value = reference_value, reference_value + signed_gap
                else:
                    second_value, first_value = reference_value, reference_value - signed_gap
                calibration = ImageCalibration(
                    "spectral", self.distance_unit.currentText(), first, second,
                    first_value, second_value, self.absolute_reference.isChecked(),
                    "known_gap", endpoint, self.calibration_horizontal.isChecked())
                self.spectral_points = [first, second]
                self.distance_reference = None
            else:
                calibration = ImageCalibration(
                    "spectral", "nm", first, second,
                    self.first_wavelength.value(), self.second_wavelength.value(),
                    True, "two_points", "A", False)
                self.spectral_points = [first, second]
                self.distance_reference = None
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.calibration = calibration
        self.calibration_reference = None
        self.canvas.set_calibration_reference(None, False)
        self.calibration_editor.hide()
        self.refresh_profiles()
        self.set_mode("normal")

    def cancel_calibration(self):
        self.calibration_reference = None
        self.canvas.set_calibration_reference(None, False)
        self.calibration_editor.hide()
        self.refresh_controls()
        self.set_mode("normal")

    def distance_reference_drawn(self, start, end):
        if not self.calibration_editor.isVisible():
            self.begin_calibration()
        self.calibration_mode.setCurrentIndex(self.calibration_mode.findData("distance"))
        self.calibration_reference_changed(start, end)

    def apply_distance_calibration(self, *args):
        self.apply_calibration()

    def spectral_reference_chosen(self, index, point):
        points = list(self.spectral_points)
        points[index] = (point.x(), point.y())
        self.spectral_points = points
        self.calibration_reference = tuple(points)
        self.canvas.set_calibration_reference(self.calibration_reference, True)
        if all(points):
            self.calibration_reference_changed(QPointF(*points[0]), QPointF(*points[1]))
        else:
            self.update_calibration_length()
            self.set_mode("normal")

    def start_spectral_point(self, index):
        if self._uses_two_spectral_points():
            self.set_mode("spectral", index)

    def apply_spectral_calibration(self, *args):
        self.apply_calibration()

    def reset_calibration(self):
        self.calibration = ImageCalibration()
        self.distance_reference = None
        self.spectral_points = [None, None]
        self.calibration_reference = None
        if hasattr(self, "canvas"):
            self.canvas.set_calibration(self.calibration)
            self.canvas.set_calibration_reference(None, False)
        if hasattr(self, "calibration_editor"):
            self.calibration_editor.hide()
        if hasattr(self, "profiles"):
            self.refresh_profiles()

    def refresh_profiles(self, fit_plot=True):
        if not hasattr(self, "canvas"):
            return
        self.canvas.set_profiles(self.profiles, self.active_identifier)
        self.canvas.set_calibration(self.calibration)
        if self.gray is not None:
            for profile in self.profiles:
                try:
                    self.samples[profile.identifier] = extract_profile(self.gray, profile, self.calibration)
                except ValueError:
                    self.samples.pop(profile.identifier, None)
        profile = self.active_profile()
        self._refreshing = True
        try:
            self.profile_name.setText(profile.name if profile else "")
            self.profile_visible.setChecked(profile.visible if profile else False)
            self.profile_width.setValue(profile.width if profile else 1)
            self.profile_horizontal.setChecked(
                profile.horizontal if profile else self.profile_horizontal_default)
        finally:
            self._refreshing = False
        if profile:
            length = np.hypot(profile.end[0] - profile.start[0], profile.end[1] - profile.start[1])
            self.geometry_label.setText(f"Longueur : {number(length)} px")
        else:
            self.geometry_label.setText("Aucun segment.")
        mode = self.calibration.mode
        if mode == "none":
            calibration_text = "Abscisse en pixels. Définissez une échelle si le TP l’exige."
        elif mode == "distance":
            pixels = np.hypot(self.calibration.second[0] - self.calibration.first[0],
                              self.calibration.second[1] - self.calibration.first[1])
            calibration_text = (f"Échelle active : {number(pixels)} px = "
                                f"{number(self.calibration.first_value)} {self.calibration.unit}.")
        else:
            gap = abs(self.calibration.second_value - self.calibration.first_value)
            pixels = abs(self.calibration.second[0] - self.calibration.first[0])
            kind = "λ absolue" if self.calibration.absolute else "écart spectral relatif Δλ"
            direction = ("croissant vers la droite"
                         if ((self.calibration.second_value - self.calibration.first_value)
                             / (self.calibration.second[0] - self.calibration.first[0])) > 0
                         else "croissant vers la gauche")
            references = (
                f"λ<sub>A</sub> = {number(self.calibration.first_value)} {self.calibration.unit} · "
                f"λ<sub>B</sub> = {number(self.calibration.second_value)} {self.calibration.unit} · "
                if self.calibration.absolute else "")
            calibration_text = (f"{kind} : {references}{number(pixels)} px horizontaux = "
                                f"{number(gap)} {self.calibration.unit} · axe {direction}.")
        self.calibration_status.setText(calibration_text)
        self.refresh_plot(fit=fit_plot)
        self.refresh_table()
        self.refresh_measurement()
        self.refresh_controls()

    def refresh_plot(self, fit=True):
        self.measurement_items = []
        previous_range = self.plot.plotItem.vb.viewRange() if not fit else None
        self.plot.clear()
        for item in (self.selection_line, self.selection_dot, self.cross_x, self.cross_y):
            self.plot.addItem(item, ignoreBounds=True)
        self.selection_line.hide()
        self.selection_dot.hide()
        self.hide_plot_crosshair()
        for profile in self.profiles:
            samples = self.samples.get(profile.identifier)
            if not profile.visible or samples is None:
                continue
            self.plot.plot(samples.axis, samples.intensity, name=profile.name,
                           pen=pg.mkPen(profile.color, width=3 if profile.identifier == self.active_identifier else 1.8))
        self.update_default_plot_reticle()
        unit = self.calibration.unit
        self.plot.setLabel("bottom", self.calibration.axis_name, units=unit if unit != "px" else "px")
        self.plot.setLabel("left", "Niveau de gris relatif")
        if fit:
            self.fit_profile_plot()
        elif previous_range:
            self._setting_plot_range = True
            try:
                self.plot.setRange(xRange=previous_range[0], yRange=previous_range[1], padding=0)
            finally:
                self._setting_plot_range = False
        self.restore_selected_sample()

    def plot_range_changed(self, *args):
        if not self._setting_plot_range:
            self._plot_user_zoomed = True
        self.hide_plot_crosshair()

    def fit_profile_plot(self):
        visible = [self.samples.get(profile.identifier) for profile in self.profiles if profile.visible]
        visible = [samples for samples in visible if samples is not None]
        if not visible:
            return
        xs = np.concatenate([samples.axis[np.isfinite(samples.axis)] for samples in visible])
        ys = np.concatenate([samples.intensity[np.isfinite(samples.intensity)] for samples in visible])
        if not len(xs) or not len(ys):
            return
        x_low, x_high = float(np.min(xs)), float(np.max(xs))
        x_margin = max((x_high - x_low) * .035, 1e-6)
        if x_low == x_high:
            x_margin = max(abs(x_low) * .05, .5)
        y_low, y_high = float(np.min(ys)), float(np.max(ys))
        y_margin = max((y_high - y_low) * .06, 2.0)
        if y_low == y_high:
            y_margin = 5.0
        y_low, y_high = max(0.0, y_low - y_margin), min(255.0, y_high + y_margin)
        if y_high <= y_low:
            y_low, y_high = max(0.0, y_low - 1), min(255.0, y_high + 1)
        self._setting_plot_range = True
        try:
            self.plot.setRange(xRange=(x_low - x_margin, x_high + x_margin),
                               yRange=(y_low, y_high), padding=0)
        finally:
            self._setting_plot_range = False
        self._plot_user_zoomed = False

    def refresh_table(self):
        profile = self.active_profile()
        samples = self.samples.get(profile.identifier) if profile else None
        self.table_model.set_samples(samples, self.calibration.axis_name, self.calibration.unit)

    def plot_clicked(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.measure_mode is not None:
            if (self.profile_view_box.sceneBoundingRect().contains(event.scenePos())
                    and not self.measurement_marker_at(event.scenePos())):
                self.measurement_click()
            return
        if not self.plot.sceneBoundingRect().contains(event.scenePos()):
            return
        nearest = self.nearest_visible_profile_sample(event.scenePos())
        if nearest is None or nearest[0] > 30 ** 2:
            return
        _, profile, _, row, _ = nearest
        if profile.identifier != self.active_identifier:
            self.activate_profile(profile.identifier)
        self.table.selectRow(row)
        self.results.setCurrentIndex(0)
        self.show_selected_sample(row)

    def table_row_changed(self, current, previous):
        if current.isValid():
            self.show_selected_sample(current.row())

    def show_selected_sample(self, row):
        profile = self.active_profile()
        samples = self.samples.get(profile.identifier) if profile else None
        if samples is None or not 0 <= row < len(samples.axis):
            return
        self.selected_sample_identity = profile.identifier, row
        x, y = float(samples.axis[row]), float(samples.intensity[row])
        self.selection_line.setPos(x)
        self.selection_dot.setData([x], [y])
        self.selection_line.show()
        self.selection_dot.show()
        self.canvas.set_selected_sample_marker(
            (float(samples.x[row]), float(samples.y[row])), profile.color)

    def restore_selected_sample(self):
        if self.selected_sample_identity is None:
            self.canvas.set_selected_sample_marker()
            return
        identifier, row = self.selected_sample_identity
        profile = next((item for item in self.profiles
                        if item.identifier == identifier and item.visible), None)
        samples = self.samples.get(identifier)
        if profile is None or samples is None or not 0 <= row < len(samples.axis):
            self.canvas.set_selected_sample_marker()
            return
        x, y = float(samples.axis[row]), float(samples.intensity[row])
        self.selection_line.setPos(x)
        self.selection_dot.setData([x], [y])
        self.selection_line.show()
        self.selection_dot.show()
        self.canvas.set_selected_sample_marker(
            (float(samples.x[row]), float(samples.y[row])), profile.color)

    def copy_table_selection(self):
        indexes = sorted(self.table.selectedIndexes(), key=lambda item: (item.row(), item.column()))
        rows = {}
        for index in indexes:
            rows.setdefault(index.row(), {})[index.column()] = index.data()
        QApplication.clipboard().setText(
            "\n".join("\t".join(values.get(column, "") for column in range(2))
                      for values in rows.values()))

    def export_csv(self):
        profile = self.active_profile()
        samples = self.samples.get(profile.identifier) if profile else None
        if samples is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter le profil", f"{profile.name}.csv", "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream, delimiter=";")
                writer.writerow([f"{self.calibration.axis_name} [{self.calibration.unit}]", "Niveau de gris"])
                writer.writerows([[format(x, ".12g").replace(".", ","),
                                   format(y, ".12g").replace(".", ",")]
                                  for x, y in zip(samples.axis, samples.intensity)])
            self.status.setText(f"Profil exporte : {path}")
        except OSError as error:
            QMessageBox.critical(self, "Export impossible", str(error))

    def start_measurement(self, mode):
        if not self.profiles:
            return
        self.set_mode("normal")
        first = self.measurement.first
        second = self.measurement.second
        self.measurement = ProfileMeasurement(
            mode=mode, first=first, second=second,
            intervals=self.intervals_spin.value(), snap=self.snap_choice.currentData())
        self.measure_mode = mode if second is None else None
        if self.selected_measurement_point == "A" and first is None:
            self.selected_measurement_point = None
        elif self.selected_measurement_point == "B" and second is None:
            self.selected_measurement_point = "A" if first is not None else None
        self.workflow.setCurrentIndex(2)
        self.update_measurement_buttons()
        self.refresh_measurement()

    def update_measurement_buttons(self):
        has_measurement = self.measurement.first is not None or self.measurement.second is not None
        active_mode = self.measure_mode or (self.measurement.mode if has_measurement else None)
        self.measurement_button_group.setExclusive(False)
        for button, mode in ((self.gap_button, "gap"), (self.interfringe_button, "interfringe")):
            button.blockSignals(True)
            active = active_mode == mode
            button.setChecked(active)
            button.blockSignals(False)
            button.setProperty("role", "primary" if active else "")
            refresh_style(button)
        self.measurement_button_group.setExclusive(True)
        interfringe = self.measurement.mode == "interfringe"
        self.intervals_spin.setVisible(interfringe)
        self.intervals_label.setVisible(interfringe)

    def update_measurement_instruction(self):
        """Décrire l'étape courante sans ajouter de panneau ni de dialogue."""
        if self.measurement.first is None:
            if self.measure_mode is None:
                text = "Choisissez un type de mesure."
            else:
                text = "Placez le réticule sur le premier point, puis cliquez pour définir A."
        elif self.measurement.second is None:
            text = "Point A placé. Choisissez le second point, puis cliquez pour définir B."
        elif self.measurement.mode == "interfringe":
            text = (f"Mesure terminée sur N = {self.measurement.intervals} intervalles entre "
                    "des franges de même nature. L’interfrange moyen est affiché ci-dessous.")
        else:
            text = "Mesure terminée. L’écart entre A et B est affiché ci-dessous."
        if (self.measurement.mode == "interfringe"
                and self.measurement.second is None and self.measure_mode is not None):
            text += " Choisissez deux franges de même nature et indiquez explicitement N."
        self.measurement_instruction.setText(text)

    def measurement_snap_changed(self, *args):
        self.measurement.snap = self.snap_choice.currentData()

    def measurement_intervals_changed(self, value):
        self.measurement.intervals = value
        self.refresh_measurement()

    def snapped_sample_index(self, samples, index):
        snap = self.measurement.snap
        return index if snap == "manual" else local_extremum_index(samples.intensity, index, snap, radius=12)

    def measurement_marker_at(self, scene_position):
        """Laisser les lignes A/B traiter elles-mêmes clics et déplacements."""
        for point in (self.measurement.first, self.measurement.second):
            samples = self.samples.get(point.profile_identifier) if point else None
            if samples is None:
                continue
            x, _ = fraction_value(samples, point.fraction)
            marker_scene = self.profile_view_box.mapViewToScene(QPointF(x, 0))
            if abs(marker_scene.x() - scene_position.x()) <= 7:
                return True
        return False

    def measurement_click(self):
        if self.tracked_reticle_sample is None:
            self.status.setText("Placez d’abord le réticule sur une courbe visible.")
            return
        identifier, index = self.tracked_reticle_sample
        profile = next((item for item in self.profiles
                        if item.identifier == identifier and item.visible), None)
        samples = self.samples.get(identifier)
        if profile is None or samples is None or not 0 <= index < len(samples.axis):
            self.tracked_reticle_sample = None
            self.status.setText("Le profil suivi par le réticule n’est plus disponible.")
            return
        index = self.snapped_sample_index(samples, index)
        point = MeasurementPoint(profile.identifier, index / (len(samples.axis) - 1))
        if self.measurement.first is None:
            self.measurement.first = point
            self.selected_measurement_point = "A"
        else:
            candidate = ProfileMeasurement(
                self.measurement.mode, self.measurement.first, point,
                self.measurement.intervals, self.measurement.snap)
            try:
                measurement_result(candidate, self.samples)
            except ValueError as error:
                self.status.setText(str(error))
                return
            self.measurement.second = point
            self.selected_measurement_point = "B"
            self.measure_mode = None
            self.update_measurement_buttons()
        self.refresh_measurement()

    def select_measurement_point(self, label):
        self.selected_measurement_point = label
        self.refresh_measurement()

    def measurement_line_moved(self, line):
        label = line.measurement_label
        point = self.measurement.first if label == "A" else self.measurement.second
        samples = self.samples.get(point.profile_identifier) if point else None
        if point is None or samples is None:
            return
        index = int(np.argmin(np.abs(samples.axis - line.value())))
        index = self.snapped_sample_index(samples, index)
        other = self.measurement.second if label == "A" else self.measurement.first
        candidate = MeasurementPoint(point.profile_identifier, index / (len(samples.axis) - 1))
        trial = ProfileMeasurement(
            self.measurement.mode,
            candidate if label == "A" else other,
            other if label == "A" else candidate,
            self.measurement.intervals, self.measurement.snap)
        try:
            measurement_result(trial, self.samples)
        except ValueError as error:
            self.status.setText(str(error))
            self.refresh_measurement()
            return
        if label == "A":
            self.measurement.first = candidate
        else:
            self.measurement.second = candidate
        self.selected_measurement_point = label
        self.refresh_measurement()

    def delete_selected_measurement_point(self):
        if self.selected_measurement_point == "A":
            self.measurement.first = self.measurement.second
            self.measurement.second = None
        elif self.selected_measurement_point == "B":
            self.measurement.second = None
        else:
            return
        self.selected_measurement_point = "A" if self.measurement.first else None
        self.measure_mode = self.measurement.mode
        self.update_measurement_buttons()
        self.refresh_measurement()

    def clear_measurement(self):
        mode = self.measurement.mode
        snap = self.measurement.snap
        intervals = self.measurement.intervals
        self.measurement = ProfileMeasurement(mode, intervals=intervals, snap=snap)
        self.measure_mode = mode
        self.selected_measurement_point = None
        self.update_measurement_buttons()
        self.refresh_measurement()

    def refresh_measurement(self):
        for item in self.measurement_items:
            self.plot.removeItem(item)
        self.measurement_items = []
        lines = []
        for label, point, color in (("A", self.measurement.first, LIGHT.warning),
                                    ("B", self.measurement.second, LIGHT.success)):
            if point is None:
                lines.append(f"{label} : —")
                continue
            profile = next((item for item in self.profiles
                            if item.identifier == point.profile_identifier), None)
            samples = self.samples.get(point.profile_identifier)
            if profile is None or samples is None:
                lines.append(f"{label} : profil indisponible")
                continue
            x, intensity = fraction_value(samples, point.fraction)
            lines.append(f"{label} — {profile.name} : {number(x)} {self.calibration.unit} ; I = {number(intensity)}")
            if profile.visible:
                selected = label == self.selected_measurement_point
                low, high = sorted((float(np.min(samples.axis)), float(np.max(samples.axis))))
                line = pg.InfiniteLine(
                    x, angle=90, movable=True, bounds=(low, high),
                    pen=pg.mkPen(color, width=3 if selected else 2),
                    hoverPen=pg.mkPen(color, width=4))
                line.measurement_label = label
                line.sigPositionChangeFinished.connect(
                    lambda changed=line: self.measurement_line_moved(changed))
                line.sigClicked.connect(lambda *args, chosen=label: self.select_measurement_point(chosen))
                dot = pg.ScatterPlotItem([x], [intensity], size=12, brush=color, pen="w")
                dot.sigClicked.connect(lambda *args, chosen=label: self.select_measurement_point(chosen))
                text = pg.TextItem(f"{label} · {profile.name}", color=color, anchor=(0, 1))
                text.setPos(x, intensity)
                for item in (line, dot, text):
                    self.plot.addItem(item, ignoreBounds=True)
                    self.measurement_items.append(item)
        self.measurement_points_label.setText("\n".join(lines))
        try:
            result = measurement_result(self.measurement, self.samples)
        except ValueError as error:
            self.measurement_label.setText(str(error))
            result = None
        if result:
            first, second, total, average = result
            delta = "Δλ" if self.calibration.mode == "spectral" else "Δx"
            if self.measurement.mode == "interfringe":
                self.measurement_label.setText(
                    f"{delta} total = {number(total)} {self.calibration.unit}\n"
                    f"N = {self.measurement.intervals} · i = {number(average)} {self.calibration.unit}")
            else:
                self.measurement_label.setText(
                    f"A = {number(first)} {self.calibration.unit} · B = {number(second)} {self.calibration.unit}\n"
                    f"{delta} = {number(total)} {self.calibration.unit}")
        elif self.measurement.first is None:
            self.measurement_label.setText("Aucune mesure.")
        elif self.measurement.second is None:
            self.measurement_label.setText("Sélectionnez le point B.")
        self.update_measurement_instruction()
        self.delete_marker_button.setText(
            f"Supprimer {self.selected_measurement_point}"
            if self.selected_measurement_point in ("A", "B") else "Supprimer un repère")
        self.delete_marker_button.setEnabled(self.selected_measurement_point is not None)
        self.clear_measurement_button.setEnabled(
            self.measurement.first is not None or self.measurement.second is not None)

    def pointer_moved(self, point):
        if point is not None:
            self.canvas.setToolTip(f"Pixel : {number(point.x())} ; {number(point.y())}")

    def transfer_profiles(self, profiles):
        entries = [(profile, self.samples.get(profile.identifier)) for profile in profiles]
        entries = [(profile, samples) for profile, samples in entries if samples is not None]
        if not entries:
            return
        axis_name, unit = self.calibration.axis_name, self.calibration.unit
        same_axis = all(len(samples.axis) == len(entries[0][1].axis)
                        and np.allclose(samples.axis, entries[0][1].axis, rtol=0, atol=1e-10)
                        for _, samples in entries[1:])
        created = []
        if len(entries) > 1 and same_axis:
            rows = [[format(entries[0][1].axis[row], ".12g"),
                     *[format(samples.intensity[row], ".12g") for _, samples in entries]]
                    for row in range(len(entries[0][1].axis))]
            names = [axis_name] + [f"I_{profile.name}" for profile, _ in entries]
            columns = self.data_tab.append_measurements(names, [unit] + [""] * len(entries), rows)
            self.graph_workspace.add_data_graph_series(columns[0], columns[1:], title="Comparaison de profils")
            created.append(columns)
        else:
            for profile, samples in entries:
                rows = [[format(x, ".12g"), format(y, ".12g")]
                        for x, y in zip(samples.axis, samples.intensity)]
                columns = self.data_tab.append_measurements(
                    [axis_name, f"I_{profile.name}"], [unit, ""], rows)
                self.graph_workspace.add_data_graph(
                    *columns, title=f"Intensité — {profile.name}", connect_points=True)
                created.append(columns)
        self.show_graph()
        self.status.setText(f"{len(entries)} profil(s) transfere(s) dans Donnees et Graphique.")
        return created

    def transfer_active(self):
        profile = self.active_profile()
        return self.transfer_profiles([profile] if profile else [])

    def transfer_visible(self):
        return self.transfer_profiles([profile for profile in self.profiles if profile.visible])

    def refresh_controls(self):
        ready = not self.image.isNull()
        active = self.active_profile() is not None
        for button in (self.fit_button, self.draw_button, self.fit_plot_button):
            button.setEnabled(ready)
        for widget in (self.frame_segment_button, self.gap_button,
                       self.interfringe_button, self.transfer_button):
            widget.setEnabled(active)
        self.transfer_visible_button.setEnabled(any(item.visible for item in self.profiles))
        self.export_button.setEnabled(active)
        self.copy_button.setEnabled(active)
        self.profile_editor.setVisible(active)
        self.profile_empty_label.setVisible(not active)
        editing = self.calibration_editor.isVisible()
        calibrated = self.calibration.mode != "none"
        self.define_calibration_button.setVisible(ready and not calibrated and not editing)
        self.calibration_applied_actions.setVisible(calibrated and not editing)

    def project_image_asset(self):
        return self.image_bytes

    def snapshot_state(self):
        calibration = {
            "mode": self.calibration.mode, "unit": self.calibration.unit,
            "first": self.calibration.first, "second": self.calibration.second,
            "first_value": self.calibration.first_value, "second_value": self.calibration.second_value,
            "absolute": self.calibration.absolute,
            "spectral_method": self.calibration.spectral_method,
            "reference_endpoint": self.calibration.reference_endpoint,
            "horizontal": self.calibration.horizontal,
        }
        return {
            "version": IMAGE_ANALYSIS_VERSION,
            "image": None if self.image_bytes is None else {
                "name": self.image_name,
                "sha256": hashlib.sha256(self.image_bytes).hexdigest(),
            },
            "calibration": calibration,
            "distance_reference": self.distance_reference,
            "spectral_points": self.spectral_points,
            "spectral_method": self.spectral_method.currentData(),
            "calibration_horizontal": self.calibration_horizontal_preference,
            "profile_horizontal_default": self.profile_horizontal_default,
            "profiles": [{
                "identifier": profile.identifier, "name": profile.name,
                "start": profile.start, "end": profile.end, "width": profile.width,
                "color": profile.color, "visible": profile.visible,
                "horizontal": profile.horizontal,
            } for profile in self.profiles],
            "active_identifier": self.active_identifier,
            "measurement": {
                "mode": self.measurement.mode,
                "intervals": self.measurement.intervals,
                "snap": self.measurement.snap,
                "first": None if self.measurement.first is None else {
                    "profile_identifier": self.measurement.first.profile_identifier,
                    "fraction": self.measurement.first.fraction,
                },
                "second": None if self.measurement.second is None else {
                    "profile_identifier": self.measurement.second.profile_identifier,
                    "fraction": self.measurement.second.fraction,
                },
            },
        }

    def restore_state(self, saved, image_bytes=None):
        if type(saved) is not dict or saved.get("version") != IMAGE_ANALYSIS_VERSION:
            raise ValueError("Version des donnees Analyse d'images non prise en charge.")
        image_state = saved.get("image")
        if image_state is None:
            raw_calibration = saved.get("calibration", {"mode": "none"})
            raw_measurement = saved.get("measurement", {})
            has_orphaned_data = (
                bool(saved.get("profiles"))
                or saved.get("active_identifier") is not None
                or saved.get("distance_reference") is not None
                or any(point is not None for point in saved.get("spectral_points", [None, None]))
                or type(raw_calibration) is not dict
                or raw_calibration.get("mode", "none") != "none"
                or type(raw_measurement) is not dict
                or raw_measurement.get("first") is not None
                or raw_measurement.get("second") is not None
            )
            if has_orphaned_data:
                raise ValueError("Donnees Analyse d'images presentes sans image integree.")
            return
        if type(image_state) is not dict or not image_bytes:
            raise ValueError("Image du projet manquante.")
        if len(image_bytes) > MAX_PROJECT_IMAGE_SIZE or hashlib.sha256(image_bytes).hexdigest() != image_state.get("sha256"):
            raise ValueError("Image du projet invalide ou alteree.")
        image = QImage.fromData(image_bytes, "PNG")
        if image.isNull() or image.width() * image.height() > MAX_IMAGE_PIXELS:
            raise ValueError("Image du projet illisible ou trop grande.")
        self.image, self.image_bytes = image, bytes(image_bytes)
        self.image_name = str(image_state.get("name") or "image.png")[:500]
        self.gray = qimage_grayscale(image)
        raw_calibration = saved.get("calibration", {"mode": "none"})
        if type(raw_calibration) is not dict:
            raise ValueError("Etalonnage d'image invalide.")
        self.calibration = ImageCalibration(**raw_calibration)
        method = saved.get("spectral_method", self.calibration.spectral_method)
        if method not in ("known_gap", "two_points"):
            raise ValueError("Methode d'etalonnage spectral invalide.")
        self.spectral_method.blockSignals(True)
        self.spectral_method.setCurrentIndex(self.spectral_method.findData(method))
        self.spectral_method.blockSignals(False)
        self.calibration_horizontal_preference = bool(
            saved.get("calibration_horizontal", self.calibration.horizontal))
        self.profile_horizontal_default = bool(saved.get("profile_horizontal_default", False))
        self.calibration_horizontal.blockSignals(True)
        self.calibration_horizontal.setChecked(self.calibration_horizontal_preference)
        self.calibration_horizontal.blockSignals(False)
        self.distance_reference = saved.get("distance_reference")
        points = saved.get("spectral_points", [None, None])
        if type(points) is not list or len(points) != 2:
            raise ValueError("References spectrales invalides.")
        self.spectral_points = points
        raw_profiles = saved.get("profiles", [])
        if type(raw_profiles) is not list or len(raw_profiles) > MAX_PROFILES:
            raise ValueError("Liste de profils invalide.")
        profiles = []
        identifiers = set()
        for raw in raw_profiles:
            if type(raw) is not dict or raw.get("identifier") in identifiers:
                raise ValueError("Profil d'image invalide ou repete.")
            profile = IntensityProfile(
                raw["name"], raw["start"], raw["end"], raw["width"], raw["color"],
                raw["visible"], raw["identifier"], raw.get("horizontal", False),
            )
            if not QColor(profile.color).isValid():
                raise ValueError("Couleur de profil invalide.")
            extract_profile(self.gray, profile, self.calibration)
            identifiers.add(profile.identifier)
            profiles.append(profile)
        self.profiles = profiles
        self._restored_legacy_markers = any(raw.get("markers") for raw in raw_profiles)
        if "measurement" not in saved:
            self.measurement = ProfileMeasurement()
        else:
            raw_measurement = saved.get("measurement", {})
            if type(raw_measurement) is not dict:
                raise ValueError("Mesure d'image invalide.")
            def restore_point(key):
                raw = raw_measurement.get(key)
                if raw is None:
                    return None
                if type(raw) is not dict or raw.get("profile_identifier") not in identifiers:
                    raise ValueError("Repere de mesure invalide.")
                return MeasurementPoint(**raw)
            self.measurement = ProfileMeasurement(
                raw_measurement.get("mode", "gap"), restore_point("first"),
                restore_point("second"), raw_measurement.get("intervals", 1),
                raw_measurement.get("snap", "manual"))
        self.measure_mode = None
        self.selected_measurement_point = None
        active = saved.get("active_identifier")
        self.active_identifier = active if active in identifiers else (profiles[0].identifier if profiles else None)
        self.canvas.set_image(image)
        if self.calibration.mode != "none":
            self.calibration_mode.blockSignals(True)
            self.calibration_mode.setCurrentIndex(self.calibration_mode.findData(self.calibration.mode))
            self.calibration_mode.blockSignals(False)
            known = (abs(self.calibration.second_value - self.calibration.first_value)
                     if self.calibration.mode == "spectral" else self.calibration.first_value)
            self.distance_value.setValue(known)
            self.distance_unit.setCurrentText(self.calibration.unit)
            if self.calibration.mode == "spectral":
                self.absolute_reference.setChecked(self.calibration.absolute)
                self.absolute_reference_endpoint.setCurrentIndex(
                    self.absolute_reference_endpoint.findData(
                        self.calibration.reference_endpoint))
                self.absolute_value.setValue(
                    self.calibration.first_value if self.calibration.reference_endpoint == "A"
                    else self.calibration.second_value)
                self.first_wavelength.setValue(self.calibration.first_value)
                self.second_wavelength.setValue(self.calibration.second_value)
        self.sync_profile_choice()
        self.refresh_profiles()
        self.set_mode("normal")
        self.snap_choice.setCurrentIndex(self.snap_choice.findData(self.measurement.snap))
        self.intervals_spin.setValue(self.measurement.intervals)
        self.update_measurement_buttons()
        if self._restored_legacy_markers:
            self.status.setText(
                "Les anciens curseurs ont été ignorés : ils ne définissaient pas de points A–B fiables.")
