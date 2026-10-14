"""Interface du mode Spectre du spectrophotomètre Physalix."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QBrush, QFont, QLinearGradient, QPainterPath, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGraphicsPathItem,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from scipy.interpolate import PchipInterpolator

from physalix.spectrophotometry import (
    VISIBLE_WAVELENGTHS_NM,
    AbsorbanceSpectrum,
    BandInvalidity,
    MeasurementKind,
    SpectroCalibration,
    SpectroMeasurement,
    calculate_absorbance,
)
from physalix.spectrophotometry_protocol import AS7341Gain, SpectroConfig
from physalix.spectrophotometry_beer_lambert import (
    CONCENTRATION_UNITS,
    BeerLambertError,
    BeerLambertStandard,
    band_absorbance,
    calculate_unknown_concentration,
    fit_beer_lambert,
    format_absorbance,
    format_concentration,
    parse_concentration,
)
from physalix.spectrophotometry_serial import (
    SpectroControllerState,
    SpectroSerialError,
    SpectrophotometrySerialController,
)
from physalix.ui.components import (
    ask_yes_no,
    label,
    page_header,
    page_layout,
    panel,
    role,
)
from physalix.ui.graph_series import (
    PopupComboBox,
    configure_popup,
    update_popup_height,
)
from physalix.ui.theme import LIGHT, SERIES_COLORS


DISCONNECT_TIMEOUT_MS = 3500
_SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def _format_projection_concentration(value):
    """Afficher les cartouches avec trois chiffres significatifs si nécessaire."""
    absolute = abs(float(value))
    if absolute and (absolute < 1e-3 or absolute >= 1e4):
        exponent = int(np.floor(np.log10(absolute)))
        mantissa = value / (10**exponent)
        decimals = 1 if np.isclose(mantissa, round(mantissa), atol=1e-2) else 2
        text = f"{mantissa:.{decimals}f}".replace(".", ",")
        return f"{text} × 10{str(exponent).translate(_SUPERSCRIPT)}"
    return format_concentration(value)


class MeasurementPreparationDialog(QDialog):
    """Présenter la préparation physique avant une mesure de référence."""

    def __init__(self, kind: MeasurementKind, parent=None):
        super().__init__(parent)
        if kind is MeasurementKind.DARK:
            title = "Mesure du noir"
            explanation = (
                "Cette mesure détermine le signal du capteur en absence d'éclairage."
            )
            instruction = "Retirez la cuve du spectrophotomètre."
            information = "La LED restera éteinte pendant cette mesure."
        elif kind is MeasurementKind.WHITE:
            title = "Mesure du blanc"
            explanation = (
                "Cette mesure définit la référence lumineuse utilisée pour "
                "calculer l'absorbance."
            )
            instruction = (
                "Insérez une cuve contenant de l'eau distillée ou le solvant "
                "de référence."
            )
            information = None
        else:
            raise ValueError("Ce dialogue est réservé aux mesures noire et blanche.")

        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setMaximumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(LIGHT.section, LIGHT.section, LIGHT.section, LIGHT.section)
        layout.setSpacing(LIGHT.group)
        layout.addWidget(label(title, "sectionTitle"))
        layout.addWidget(label(explanation, "muted"))
        layout.addWidget(label(instruction, "context"))
        if information is not None:
            layout.addWidget(label(information, "muted"))

        self.buttons = QDialogButtonBox()
        self.cancel_button = self.buttons.addButton(
            "Annuler", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.accept_button = role(
            self.buttons.addButton(
                "Valider et mesurer", QDialogButtonBox.ButtonRole.AcceptRole
            ),
            "primary",
        )
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)


class StandardEditorDialog(QDialog):
    """Saisir explicitement le nom et la concentration d'un étalon."""

    def __init__(self, unit: str, standard=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier l'étalon" if standard else "Ajouter un étalon")
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setMaximumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(LIGHT.section, LIGHT.section, LIGHT.section, LIGHT.section)
        layout.setSpacing(LIGHT.group)
        layout.addWidget(label(self.windowTitle(), "sectionTitle"))
        form = QFormLayout()
        self.name_edit = QLineEdit(standard.name if standard else "")
        self.concentration_edit = QLineEdit(
            f"{standard.concentration:g}" if standard else ""
        )
        self.concentration_edit.setPlaceholderText("Ex. 0,001")
        form.addRow("Nom", self.name_edit)
        form.addRow(f"Concentration ({unit})", self.concentration_edit)
        layout.addLayout(form)
        self.error_label = label("", "danger")
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox()
        self.cancel_button = self.buttons.addButton(
            "Annuler", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.accept_button = role(
            self.buttons.addButton(
                "Valider", QDialogButtonBox.ButtonRole.AcceptRole
            ),
            "primary",
        )
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self._validate)
        layout.addWidget(self.buttons)
        self.concentration = None

    def _validate(self):
        name = self.name_edit.text().strip()
        if not name:
            self.error_label.setText("Le nom de l'étalon est obligatoire.")
            return
        try:
            self.concentration = parse_concentration(self.concentration_edit.text())
        except BeerLambertError as error:
            self.error_label.setText(str(error))
            return
        self.accept()


class BeerLambertPreparationDialog(QDialog):
    """Présenter la cuve requise avant une mesure Beer-Lambert."""

    def __init__(self, standard=None, *, unit="mol/L", parent=None):
        super().__init__(parent)
        if standard is None:
            title = "Mesure de l'inconnue"
            instruction = (
                "Insérez la cuve contenant la solution de concentration inconnue."
            )
        else:
            title = "Mesure de l'étalon"
            instruction = (
                "Insérez la cuve contenant la solution étalon "
                f"{standard.name}, de concentration {standard.concentration:g} {unit}."
            )
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setMaximumWidth(620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(LIGHT.section, LIGHT.section, LIGHT.section, LIGHT.section)
        layout.setSpacing(LIGHT.group)
        layout.addWidget(label(title, "sectionTitle"))
        layout.addWidget(label(instruction, "context"))
        self.buttons = QDialogButtonBox()
        self.cancel_button = self.buttons.addButton(
            "Annuler", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.accept_button = role(
            self.buttons.addButton(
                "Valider et mesurer", QDialogButtonBox.ButtonRole.AcceptRole
            ),
            "primary",
        )
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)


@dataclass
class SpectrumDisplay:
    spectrum: AbsorbanceSpectrum
    name: str
    color: str
    visible: bool = True
    list_item: QListWidgetItem | None = None
    experimental_item: pg.PlotDataItem | None = None
    interpolation_items: list[pg.PlotDataItem] = field(default_factory=list)
    fill_items: list[QGraphicsPathItem] = field(default_factory=list)


class BeerLambertStandardsTable(QTableWidget):
    """Table compacte dont les quatre colonnes suivent la largeur disponible."""

    COLUMN_WEIGHTS = (0.32, 0.20, 0.23, 0.25)

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(28)
        self.verticalHeader().setMinimumSectionSize(28)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_columns_to_viewport()

    def resize_columns_to_viewport(self):
        """Répartir toute la largeur en garantissant la place des en-têtes."""

        # Qt peut réserver la barre verticale après le premier layout. Partir de
        # la largeur du widget en la réservant systématiquement évite ce décalage.
        available = (
            self.width()
            - 2 * self.frameWidth()
            - self.verticalScrollBar().sizeHint().width()
        )
        if available <= 0:
            return
        metrics = self.horizontalHeader().fontMetrics()
        minimums = [
            max(50, metrics.horizontalAdvance(self.horizontalHeaderItem(index).text()) + 12)
            for index in range(self.columnCount())
        ]
        minimum_total = sum(minimums)
        if available <= minimum_total:
            widths = minimums
        else:
            extra = available - minimum_total
            widths = [
                minimum + int(extra * weight)
                for minimum, weight in zip(minimums, self.COLUMN_WEIGHTS)
            ]
            widths[-1] += available - sum(widths)
        for index, width in enumerate(widths):
            self.setColumnWidth(index, width)


class SpectrophotometryTab(QWidget):
    """Piloter le Nano Spectro et conserver les spectres de la session courante."""

    def __init__(
        self,
        controller=None,
        parent=None,
        *,
        data_tab=None,
        graph_workspace=None,
        show_graph=None,
        disconnect_timeout_ms=DISCONNECT_TIMEOUT_MS,
    ):
        super().__init__(parent)
        self.controller = controller or SpectrophotometrySerialController(self)
        self.data_tab = data_tab
        self.graph_workspace = graph_workspace
        self.show_graph = show_graph
        self.session_id: str | None = None
        self.applied_config: SpectroConfig | None = None
        self.dark_measurement: SpectroMeasurement | None = None
        self.white_measurement: SpectroMeasurement | None = None
        self.calibration: SpectroCalibration | None = None
        self.spectra: list[SpectrumDisplay] = []
        self.absorbance_spectrum: AbsorbanceSpectrum | None = None
        self._pending_absorbance = False
        self._absorbance_recalibration_expanded = False
        self.beer_standards: list[BeerLambertStandard] = []
        self.beer_unknown_spectrum: AbsorbanceSpectrum | None = None
        self.beer_regression = None
        self._pending_beer_target = None
        self._beer_previous_unit_index = 0
        self._beer_transfer_columns = {}
        self._beer_last_transferred_signature = None
        self._pending_kind: MeasurementKind | None = None
        self._next_config_id = 1
        self._configuration_dirty = True
        self._disconnect_pending = False
        self._closing = False

        self._build_ui()
        self._connect_controller()
        self.disconnect_timer = QTimer(self)
        self.disconnect_timer.setSingleShot(True)
        self.disconnect_timer.setInterval(disconnect_timeout_ms)
        self.disconnect_timer.timeout.connect(self._force_disconnect)
        self.refresh_ports()
        self._update_calibration_status()
        self._update_controls()

    def _build_ui(self):
        layout = page_layout(QVBoxLayout(self))
        layout.addWidget(
            page_header(
                "Spectrophotométrie",
                "Mesurer huit absorbances visibles avec le spectrophotomètre Physalix.",
            )
        )

        connection, connection_layout = panel(kind="toolbar")
        connection.setObjectName("spectrophotometryConnectionBar")
        row = QHBoxLayout()
        row.setSpacing(LIGHT.related)
        row.addWidget(label("Connexion", "toolbarLabel"))
        row.addWidget(label("Port", "fieldLabel"))
        self.port_combo = PopupComboBox()
        self.port_combo.setMinimumWidth(230)
        configure_popup(self.port_combo, 320)
        self.refresh_button = QPushButton("Actualiser")
        self.connect_button = QPushButton("Connecter")
        self.connection_status = QLabel("Déconnecté")
        row.addWidget(self.port_combo, 1)
        row.addWidget(self.refresh_button)
        row.addWidget(self.connect_button)
        row.addWidget(self.connection_status)
        row.addSpacing(LIGHT.group)
        row.addWidget(label("Mode", "fieldLabel"))
        self.mode_combo = PopupComboBox()
        self.mode_combo.addItem("Spectre", "spectrum")
        self.mode_combo.addItem("Absorbance", "absorbance")
        self.mode_combo.addItem("Beer-Lambert", "beer_lambert")
        self.mode_combo.setMinimumWidth(150)
        configure_popup(self.mode_combo, 220)
        update_popup_height(self.mode_combo)
        row.addWidget(self.mode_combo)
        connection_layout.addLayout(row)
        layout.addWidget(connection)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("spectrophotometryMainSplitter")
        self.main_splitter.setChildrenCollapsible(False)

        plot_panel, plot_layout = panel("Spectres d'absorbance")
        plot_panel.setMinimumSize(470, 330)
        plot_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        plot_layout.setContentsMargins(LIGHT.small, LIGHT.small, LIGHT.small, LIGHT.small)
        self.plot = pg.PlotWidget(
            background=self.palette().color(QPalette.ColorRole.Base)
        )
        self.plot.setLabel("bottom", "Longueur d'onde", units="nm")
        self.plot.setLabel("left", "Absorbance")
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.setXRange(400, 695, padding=0)
        self.plot.addLegend(offset=(8, 8))
        self._apply_plot_palette()
        plot_layout.addWidget(self.plot, 1)
        plot_layout.addWidget(
            label(
                "Les marqueurs sont les huit mesures ; les lignes sont des "
                "interpolations PCHIP et le remplissage repère les longueurs d'onde.",
                "caption",
            )
        )
        self.main_splitter.addWidget(plot_panel)

        self.settings_column = QWidget()
        self.settings_column.setMinimumWidth(340)
        self.settings_column.setMaximumWidth(520)
        settings_column_layout = QVBoxLayout(self.settings_column)
        settings_column_layout.setContentsMargins(0, 0, 0, 0)
        settings_column_layout.setSpacing(LIGHT.related)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        settings_content = QWidget()
        settings_content.setMinimumWidth(0)
        settings_content.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setContentsMargins(0, 0, LIGHT.small, 0)
        settings_layout.setSpacing(LIGHT.related)
        self.settings_scroll.setWidget(settings_content)
        settings_column_layout.addWidget(self.settings_scroll, 1)

        calibration_panel, calibration_layout = panel("Étalonnage")
        self.calibration_status = label("Noir manquant", "context")
        calibration_layout.addWidget(self.calibration_status)
        self.workflow_label = label(
            "1. Mesurer le noir.  2. Placer la référence et mesurer le blanc.  "
            "3. Placer l'échantillon.",
            "muted",
        )
        calibration_layout.addWidget(self.workflow_label)
        self.applied_values_label = QLabel(
            "ATIME 100 · ASTEP 999 · gain 8× · PWM 255"
        )
        self.applied_values_label.setWordWrap(True)
        calibration_layout.addWidget(self.applied_values_label)
        settings_layout.addWidget(calibration_panel)

        advanced_panel, advanced_layout = panel("Paramètres avancés")
        self.advanced_toggle = QPushButton("Afficher les paramètres")
        self.advanced_toggle.setCheckable(True)
        advanced_layout.addWidget(self.advanced_toggle)
        self.advanced_content = QWidget()
        advanced_form = QFormLayout(self.advanced_content)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.atime_spin = QSpinBox()
        self.atime_spin.setRange(0, 255)
        self.atime_spin.setValue(100)
        self.astep_spin = QSpinBox()
        self.astep_spin.setRange(0, 65535)
        self.astep_spin.setValue(999)
        self.gain_combo = PopupComboBox()
        for gain in AS7341Gain:
            text = gain.name.removeprefix("GAIN_").replace("_", ",").replace("X", "×")
            self.gain_combo.addItem(text, gain)
        self.gain_combo.setCurrentIndex(self.gain_combo.findData(AS7341Gain.GAIN_8X))
        configure_popup(self.gain_combo, 150)
        update_popup_height(self.gain_combo)
        self.pwm_spin = QSpinBox()
        self.pwm_spin.setRange(0, 255)
        self.pwm_spin.setValue(255)
        self.apply_config_button = QPushButton("Appliquer les paramètres")
        advanced_form.addRow("ATIME", self.atime_spin)
        advanced_form.addRow("ASTEP", self.astep_spin)
        advanced_form.addRow("Gain", self.gain_combo)
        advanced_form.addRow("LED PWM", self.pwm_spin)
        advanced_form.addRow(self.apply_config_button)
        self.advanced_content.hide()
        advanced_layout.addWidget(self.advanced_content)
        settings_layout.addWidget(advanced_panel)

        spectra_panel, spectra_layout = panel("Spectres conservés")
        self.spectra_list = QListWidget()
        self.spectra_list.setMinimumHeight(120)
        self.spectra_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.remove_spectrum_button = role(QPushButton("Supprimer le spectre"), "danger")
        spectra_layout.addWidget(self.spectra_list)
        spectra_layout.addWidget(self.remove_spectrum_button)
        settings_layout.addWidget(spectra_panel)
        settings_layout.addStretch(1)

        actions_panel, actions_layout = panel("Mesures")
        self.dark_button = QPushButton("Mesurer le noir")
        self.white_button = QPushButton("Mesurer le blanc")
        self.sample_button = role(QPushButton("Mesurer l'échantillon"), "primary")
        actions_layout.addWidget(self.dark_button)
        actions_layout.addWidget(self.white_button)
        actions_layout.addWidget(self.sample_button)
        self.measurement_status = label("Connectez le spectrophotomètre.", "muted")
        actions_layout.addWidget(self.measurement_status)
        settings_column_layout.addWidget(actions_panel)

        self.main_splitter.addWidget(self.settings_column)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setSizes([760, 500])
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self.main_splitter)
        self._build_absorbance_ui()
        self.mode_stack.addWidget(self.absorbance_page)
        self._build_beer_lambert_ui()
        self.mode_stack.addWidget(self.beer_main_splitter)
        layout.addWidget(self.mode_stack, 1)

        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.apply_config_button.clicked.connect(self.apply_configuration)
        self.dark_button.clicked.connect(
            lambda: self.request_measurement(MeasurementKind.DARK)
        )
        self.white_button.clicked.connect(
            lambda: self.request_measurement(MeasurementKind.WHITE)
        )
        self.sample_button.clicked.connect(
            lambda: self.request_measurement(MeasurementKind.SAMPLE)
        )
        self.remove_spectrum_button.clicked.connect(self.remove_selected_spectrum)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        for widget in (self.atime_spin, self.astep_spin, self.gain_combo, self.pwm_spin):
            signal = (
                widget.currentIndexChanged
                if isinstance(widget, QComboBox)
                else widget.valueChanged
            )
            signal.connect(self._parameters_changed)

    def _build_absorbance_ui(self):
        self.absorbance_page = QWidget()
        page = QVBoxLayout(self.absorbance_page)
        page.setContentsMargins(LIGHT.page, LIGHT.section, LIGHT.page, LIGHT.section)
        page.setSpacing(LIGHT.section)
        page.addStretch(1)

        card, card_layout = panel("Mesure d'absorbance")
        card.setObjectName("singleAbsorbanceCard")
        card.setMinimumWidth(480)
        card.setMaximumWidth(760)

        selector_row = QHBoxLayout()
        selector_row.addStretch(1)
        selector_row.addWidget(label("Longueur d'onde", "fieldLabel"))
        self.absorbance_band_combo = PopupComboBox()
        for index, wavelength in enumerate(VISIBLE_WAVELENGTHS_NM, start=1):
            self.absorbance_band_combo.addItem(
                f"{wavelength} nm (F{index})", index - 1
            )
        self.absorbance_band_combo.setCurrentIndex(3)
        self.absorbance_band_combo.setMinimumWidth(170)
        configure_popup(self.absorbance_band_combo, 220)
        update_popup_height(self.absorbance_band_combo)
        selector_row.addWidget(self.absorbance_band_combo)
        selector_row.addStretch(1)
        card_layout.addLayout(selector_row)

        self.absorbance_calibration_status = label("Noir manquant", "context")
        self.absorbance_calibration_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.absorbance_calibration_status)
        calibration_actions = QHBoxLayout()
        self.absorbance_dark_button = QPushButton("Mesurer le noir")
        self.absorbance_white_button = QPushButton("Mesurer le blanc")
        calibration_actions.addStretch(1)
        calibration_actions.addWidget(self.absorbance_dark_button)
        calibration_actions.addWidget(self.absorbance_white_button)
        calibration_actions.addStretch(1)
        card_layout.addLayout(calibration_actions)
        self.absorbance_recalibrate_button = role(
            QPushButton("Recalibrer"), "quiet"
        )
        self.absorbance_recalibrate_button.setMaximumWidth(180)
        card_layout.addWidget(
            self.absorbance_recalibrate_button, 0, Qt.AlignmentFlag.AlignHCenter
        )

        card_layout.addSpacing(LIGHT.section + LIGHT.group)
        heading = label("Absorbance mesurée", "sectionTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(heading)
        self.absorbance_value_label = QLabel("—")
        self.absorbance_value_label.setObjectName("singleAbsorbanceValue")
        self.absorbance_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_font = self.absorbance_value_label.font()
        value_font.setFamily("Segoe UI")
        value_font.setPointSize(60)
        value_font.setWeight(QFont.Weight.DemiBold)
        self._absorbance_numeric_font = QFont(value_font)
        invalid_font = QFont(value_font)
        invalid_font.setPointSize(32)
        self._absorbance_invalid_font = invalid_font
        self.absorbance_value_label.setFont(self._absorbance_numeric_font)
        self.absorbance_value_label.setMinimumHeight(116)
        card_layout.addWidget(self.absorbance_value_label)
        self.absorbance_wavelength_label = QLabel("515 nm (F4)")
        self.absorbance_wavelength_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wavelength_font = self.absorbance_wavelength_label.font()
        wavelength_font.setPixelSize(20)
        wavelength_font.setWeight(QFont.Weight.DemiBold)
        self.absorbance_wavelength_label.setFont(wavelength_font)
        card_layout.addWidget(self.absorbance_wavelength_label)
        self.absorbance_result_status = label(
            "Effectuez un étalonnage noir et blanc avant la mesure.", "muted"
        )
        self.absorbance_result_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.absorbance_result_status)
        card_layout.addSpacing(LIGHT.group)
        self.absorbance_measure_button = role(
            QPushButton("Mesurer l'absorbance"), "primary"
        )
        self.absorbance_measure_button.setMinimumHeight(44)
        self.absorbance_measure_button.setMaximumWidth(340)
        card_layout.addWidget(
            self.absorbance_measure_button, 0, Qt.AlignmentFlag.AlignHCenter
        )
        self.absorbance_acquisition_status = label("", "muted")
        self.absorbance_acquisition_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.absorbance_acquisition_status)

        page.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        page.addStretch(1)

        self.absorbance_band_combo.currentIndexChanged.connect(
            self._refresh_absorbance_ui
        )
        self.absorbance_dark_button.clicked.connect(
            lambda: self.request_measurement(MeasurementKind.DARK)
        )
        self.absorbance_white_button.clicked.connect(
            lambda: self.request_measurement(MeasurementKind.WHITE)
        )
        self.absorbance_recalibrate_button.clicked.connect(
            self._show_absorbance_recalibration
        )
        self.absorbance_measure_button.clicked.connect(self.measure_absorbance)
        self._update_absorbance_calibration_controls()
        self._refresh_absorbance_ui()

    def _build_beer_lambert_ui(self):
        self.beer_main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.beer_main_splitter.setObjectName("beerLambertMainSplitter")
        self.beer_main_splitter.setChildrenCollapsible(False)

        plot_panel, plot_layout = panel("Beer-Lambert — A = f(c)")
        plot_panel.setMinimumSize(470, 330)
        plot_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plot_layout.setContentsMargins(LIGHT.small, LIGHT.small, LIGHT.small, LIGHT.small)
        self.beer_plot = pg.PlotWidget(
            background=self.palette().color(QPalette.ColorRole.Base)
        )
        self.beer_plot.setLabel("bottom", "Concentration", units="mol/L")
        self.beer_plot.setLabel("left", "Absorbance")
        self.beer_plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.beer_plot.getAxis("left").enableAutoSIPrefix(False)
        self.beer_plot.showGrid(x=True, y=True, alpha=0.18)
        self.beer_plot.addLegend(offset=(8, 8))
        beer_view = self.beer_plot.getViewBox()
        beer_view.sigRangeChanged.connect(self._position_beer_projection_labels)
        beer_view.sigResized.connect(self._position_beer_projection_labels)
        plot_layout.addWidget(self.beer_plot, 1)
        plot_layout.addWidget(
            label(
                "Les points sont expérimentaux ; le segment représente l'ajustement "
                "linéaire sur la seule gamme mesurée.",
                "caption",
            )
        )
        self.beer_main_splitter.addWidget(plot_panel)

        settings_column = QWidget()
        self.beer_settings_column = settings_column
        settings_column.setMinimumWidth(350)
        settings_column.setMaximumWidth(520)
        column_layout = QVBoxLayout(settings_column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(LIGHT.related)
        self.beer_settings_scroll = QScrollArea()
        self.beer_settings_scroll.setWidgetResizable(True)
        self.beer_settings_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, LIGHT.small, 0)
        content_layout.setSpacing(LIGHT.related)
        self.beer_settings_scroll.setWidget(content)
        column_layout.addWidget(self.beer_settings_scroll, 1)

        parameters_panel, parameters_layout = panel("Paramètres d'analyse")
        parameters_form = QFormLayout()
        self.beer_unit_combo = PopupComboBox()
        self.beer_unit_combo.addItems(CONCENTRATION_UNITS)
        configure_popup(self.beer_unit_combo, 180)
        update_popup_height(self.beer_unit_combo)
        self.beer_band_combo = PopupComboBox()
        for index, wavelength in enumerate(VISIBLE_WAVELENGTHS_NM, start=1):
            self.beer_band_combo.addItem(f"{wavelength} nm (F{index})", index - 1)
        self.beer_band_combo.setCurrentIndex(4)
        configure_popup(self.beer_band_combo, 220)
        update_popup_height(self.beer_band_combo)
        parameters_form.addRow("Unité", self.beer_unit_combo)
        parameters_form.addRow("Bande", self.beer_band_combo)
        parameters_layout.addLayout(parameters_form)
        self.beer_calibration_status = label("Noir manquant", "context")
        parameters_layout.addWidget(self.beer_calibration_status)
        content_layout.addWidget(parameters_panel)

        standards_panel, standards_layout = panel("Gamme d'étalonnage")
        self.beer_table = BeerLambertStandardsTable()
        self.beer_table.setHorizontalHeaderLabels(
            ("Solution", "c (mol/L)", "A (555 nm)", "État")
        )
        self.beer_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.beer_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.beer_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.beer_table.setMinimumHeight(155)
        self.beer_table.resize_columns_to_viewport()
        standards_layout.addWidget(self.beer_table)
        edit_row = QHBoxLayout()
        self.beer_add_button = QPushButton("Ajouter")
        self.beer_edit_button = QPushButton("Modifier")
        self.beer_delete_button = role(QPushButton("Supprimer"), "danger")
        edit_row.addWidget(self.beer_add_button)
        edit_row.addWidget(self.beer_edit_button)
        edit_row.addWidget(self.beer_delete_button)
        standards_layout.addLayout(edit_row)
        self.beer_measure_standard_button = role(
            QPushButton("Mesurer l'étalon sélectionné"), "primary"
        )
        standards_layout.addWidget(self.beer_measure_standard_button)
        content_layout.addWidget(standards_panel)

        regression_panel, regression_layout = panel("Régression linéaire")
        self.beer_equation_label = label("Régression indisponible", "context")
        self.beer_r_squared_label = QLabel("R² : —")
        self.beer_regression_warning = label(
            "Au moins deux étalons valides de concentrations distinctes sont requis.",
            "muted",
        )
        regression_layout.addWidget(self.beer_equation_label)
        regression_layout.addWidget(self.beer_r_squared_label)
        regression_layout.addWidget(self.beer_regression_warning)
        content_layout.addWidget(regression_panel)

        unknown_panel, unknown_layout = panel("Solution inconnue")
        self.beer_measure_unknown_button = QPushButton("Mesurer l'inconnue")
        self.beer_unknown_absorbance_label = QLabel("Absorbance : —")
        self.beer_unknown_result_label = label("Concentration : —", "context")
        self.beer_unknown_band_label = QLabel("Bande utilisée : 555 nm (F5)")
        self.beer_unknown_warning = label("", "muted")
        unknown_layout.addWidget(self.beer_measure_unknown_button)
        unknown_layout.addWidget(self.beer_unknown_absorbance_label)
        unknown_layout.addWidget(self.beer_unknown_result_label)
        unknown_layout.addWidget(self.beer_unknown_band_label)
        unknown_layout.addWidget(self.beer_unknown_warning)
        content_layout.addWidget(unknown_panel)
        content_layout.addStretch(1)

        transfer_panel, transfer_layout = panel("Export")
        self.beer_transfer_button = role(
            QPushButton("Transférer vers Graphique"), "primary"
        )
        self.beer_transfer_status = label("", "muted")
        transfer_layout.addWidget(self.beer_transfer_button)
        transfer_layout.addWidget(self.beer_transfer_status)
        column_layout.addWidget(transfer_panel)

        self.beer_main_splitter.addWidget(settings_column)
        self.beer_main_splitter.setStretchFactor(0, 3)
        self.beer_main_splitter.setStretchFactor(1, 2)
        self.beer_main_splitter.setSizes([760, 500])

        self.beer_unit_combo.currentIndexChanged.connect(self._beer_unit_changed)
        self.beer_band_combo.currentIndexChanged.connect(self._refresh_beer_ui)
        self.beer_table.itemSelectionChanged.connect(self._update_controls)
        self.beer_add_button.clicked.connect(self.add_beer_standard)
        self.beer_edit_button.clicked.connect(self.edit_selected_beer_standard)
        self.beer_delete_button.clicked.connect(self.delete_selected_beer_standard)
        self.beer_measure_standard_button.clicked.connect(
            self.measure_selected_beer_standard
        )
        self.beer_measure_unknown_button.clicked.connect(self.measure_beer_unknown)
        self.beer_transfer_button.clicked.connect(self.transfer_beer_to_graph)
        self._apply_beer_plot_palette()
        self._refresh_beer_ui()

    def _connect_controller(self):
        self.controller.state_changed.connect(self._state_changed)
        self.controller.ready.connect(self._controller_ready)
        self.controller.configuration_accepted.connect(self._configuration_accepted)
        self.controller.measurement_received.connect(self._measurement_received)
        self.controller.measurement_failed.connect(self._measurement_failed)
        self.controller.stopped.connect(self._stopped)
        self.controller.error_occurred.connect(self._controller_error)

    def _apply_plot_palette(self):
        palette = self.palette()
        self.plot.setBackground(palette.color(QPalette.ColorRole.Base))
        axis_pen = pg.mkPen(palette.color(QPalette.ColorRole.Mid))
        text_pen = pg.mkPen(palette.color(QPalette.ColorRole.Text))
        for name in ("bottom", "left"):
            axis = self.plot.getAxis(name)
            axis.setPen(axis_pen)
            axis.setTextPen(text_pen)

    def _apply_beer_plot_palette(self):
        palette = self.palette()
        self.beer_plot.setBackground(palette.color(QPalette.ColorRole.Base))
        axis_pen = pg.mkPen(palette.color(QPalette.ColorRole.Mid))
        text_pen = pg.mkPen(palette.color(QPalette.ColorRole.Text))
        for name in ("bottom", "left"):
            axis = self.beer_plot.getAxis(name)
            axis.setPen(axis_pen)
            axis.setTextPen(text_pen)
        self._style_beer_projection_labels()

    def _style_beer_projection_labels(self):
        orange = "#F57C00"
        background = QColor(self.palette().color(QPalette.ColorRole.Base))
        background.setAlpha(235)
        border = QColor(orange)
        border.setAlpha(210)
        for value_label in (
            getattr(self, "beer_unknown_x_label", None),
            getattr(self, "beer_unknown_y_label", None),
        ):
            if value_label is not None:
                value_label.setColor(orange)
                value_label.fill = pg.mkBrush(background)
                value_label.border = pg.mkPen(border, width=1)
                value_label.update()

    def _position_beer_projection_labels(self, *args):
        x_label = getattr(self, "beer_unknown_x_label", None)
        y_label = getattr(self, "beer_unknown_y_label", None)
        result = getattr(self, "beer_unknown_display_result", None)
        if x_label is None or y_label is None or result is None:
            return
        view = self.beer_plot.getViewBox()
        x_range, y_range = view.viewRange()
        x_span = x_range[1] - x_range[0]
        y_span = y_range[1] - y_range[0]
        x_pixels, y_pixels = max(view.width(), 1), max(view.height(), 1)
        x_padding = x_label.boundingRect().width() * x_span / (2 * x_pixels)
        y_padding = y_label.boundingRect().height() * y_span / (2 * y_pixels)
        edge_x = x_range[0] + 4 * x_span / x_pixels
        edge_y = y_range[0] + 4 * y_span / y_pixels
        label_x = min(
            max(result.concentration, x_range[0] + x_padding),
            x_range[1] - x_padding,
        )
        label_y = min(
            max(result.absorbance, y_range[0] + y_padding),
            y_range[1] - y_padding,
        )
        x_label.setPos(label_x, edge_y)
        y_label.setPos(edge_x, label_y)

    def changeEvent(self, event):
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        ) and hasattr(self, "plot"):
            self._apply_plot_palette()
            if hasattr(self, "beer_plot"):
                self._apply_beer_plot_palette()
        super().changeEvent(event)

    def _mode_changed(self, index):
        self.mode_stack.setCurrentIndex(index)
        self._update_controls()

    def absorbance_band_index(self):
        return int(self.absorbance_band_combo.currentData())

    def _show_absorbance_recalibration(self):
        self._absorbance_recalibration_expanded = True
        self._update_absorbance_calibration_controls()

    def _update_absorbance_calibration_controls(self):
        if not hasattr(self, "absorbance_recalibrate_button"):
            return
        calibration_ready = self.calibration is not None
        show_reference_actions = (
            not calibration_ready or self._absorbance_recalibration_expanded
        )
        self.absorbance_dark_button.setVisible(show_reference_actions)
        self.absorbance_white_button.setVisible(show_reference_actions)
        self.absorbance_recalibrate_button.setVisible(
            calibration_ready and not self._absorbance_recalibration_expanded
        )

    def _set_absorbance_display(self, text, *, invalid=False):
        self.absorbance_value_label.setFont(
            self._absorbance_invalid_font if invalid else self._absorbance_numeric_font
        )
        self.absorbance_value_label.setText(text)

    def measure_absorbance(self):
        if self.calibration is None:
            self._show_error("Un étalonnage noir et blanc valide est requis.")
            self.absorbance_acquisition_status.setText(
                "Étalonnage requis avant la mesure."
            )
            return
        if not self._controller_allows_measurement():
            self._show_error("Le spectrophotomètre n'est pas prêt pour cette mesure.")
            self.absorbance_acquisition_status.setText(
                "Le spectrophotomètre n'est pas prêt."
            )
            return
        self._pending_absorbance = True
        self.request_measurement(MeasurementKind.SAMPLE)
        if self._pending_kind is None:
            self._pending_absorbance = False
            return
        # Dès que la nouvelle acquisition est réellement lancée, ne plus laisser
        # l'ancien nombre visible comme s'il s'agissait du résultat attendu.
        self.absorbance_spectrum = None
        self._refresh_absorbance_ui()
        self.absorbance_acquisition_status.setText("Mesure en cours…")

    def _refresh_absorbance_ui(self):
        if not hasattr(self, "absorbance_band_combo"):
            return
        index = self.absorbance_band_index()
        wavelength = VISIBLE_WAVELENGTHS_NM[index]
        self.absorbance_wavelength_label.setText(f"{wavelength} nm (F{index + 1})")
        spectrum = self.absorbance_spectrum
        if spectrum is None:
            self._set_absorbance_display("—")
            self.absorbance_result_status.setText(
                "Aucune mesure d'absorbance disponible."
                if self.calibration is not None
                else "Effectuez un étalonnage noir et blanc avant la mesure."
            )
            return
        if not self._spectrum_uses_active_calibration(spectrum):
            self._set_absorbance_display("—")
            self.absorbance_result_status.setText(
                "Résultat associé à une référence devenue inactive."
            )
            return
        band = spectrum.bands[index]
        if not band.is_valid:
            self._set_absorbance_display("Indisponible", invalid=True)
            self.absorbance_result_status.setText(
                self._absorbance_invalidity_text(band.invalidities)
            )
            return
        value = 0.0 if band.absorbance == 0 else band.absorbance
        self._set_absorbance_display(format(value, ".6g").replace(".", ","))
        self.absorbance_result_status.setText(
            "Valeur expérimentale de la bande sélectionnée, sans interpolation."
        )

    @staticmethod
    def _absorbance_invalidity_text(invalidities):
        messages = {
            BandInvalidity.MISSING_CALIBRATION: "Étalonnage manquant.",
            BandInvalidity.SESSION_MISMATCH: "Mesure issue d'une autre session.",
            BandInvalidity.ACQUISITION_PARAMETERS_MISMATCH: (
                "Réglages matériels incompatibles avec l'étalonnage."
            ),
            BandInvalidity.DARK_SATURATED: "Bande saturée pendant la mesure noire.",
            BandInvalidity.WHITE_SATURATED: "Bande saturée pendant la mesure blanche.",
            BandInvalidity.SAMPLE_SATURATED: "Bande saturée pendant la mesure de la solution.",
            BandInvalidity.REFERENCE_NOT_ABOVE_DARK: (
                "Référence blanche insuffisante sur cette bande."
            ),
            BandInvalidity.SAMPLE_NOT_ABOVE_DARK: (
                "Signal de la solution inférieur ou égal au noir."
            ),
        }
        return " ".join(messages.get(item, "Bande invalide.") for item in invalidities)

    def beer_band_index(self):
        return int(self.beer_band_combo.currentData())

    def beer_wavelength(self):
        return VISIBLE_WAVELENGTHS_NM[self.beer_band_index()]

    def _beer_unit_changed(self, index):
        if index == self._beer_previous_unit_index:
            return
        if self.beer_standards or self.beer_unknown_spectrum is not None:
            answer = QMessageBox.question(
                self,
                "Changer l'unité de concentration",
                "Changer d'unité nécessite de réinitialiser la gamme et la mesure "
                "de l'inconnue. Continuer ?\n\nAucune conversion automatique ne sera faite.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.beer_unit_combo.blockSignals(True)
                self.beer_unit_combo.setCurrentIndex(self._beer_previous_unit_index)
                self.beer_unit_combo.blockSignals(False)
                return
            self.beer_standards.clear()
            self.beer_unknown_spectrum = None
            self._beer_transfer_columns.clear()
            self._beer_last_transferred_signature = None
        self._beer_previous_unit_index = index
        self._refresh_beer_ui()

    def _selected_beer_standard(self):
        row = self.beer_table.currentRow()
        if 0 <= row < len(self.beer_standards):
            return self.beer_standards[row]
        return None

    def add_beer_standard(self, name=None, concentration_text=None):
        if name is None or concentration_text is None:
            dialog = StandardEditorDialog(self.beer_unit_combo.currentText(), parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            name = dialog.name_edit.text().strip()
            concentration = dialog.concentration
        else:
            try:
                concentration = parse_concentration(str(concentration_text))
            except BeerLambertError as error:
                self._show_error(str(error))
                return None
        try:
            standard = BeerLambertStandard(uuid4().hex, str(name), concentration)
        except BeerLambertError as error:
            self._show_error(str(error))
            return None
        self.beer_standards.append(standard)
        self._beer_last_transferred_signature = None
        self._refresh_beer_ui()
        self.beer_table.selectRow(len(self.beer_standards) - 1)
        return standard

    def edit_selected_beer_standard(self):
        standard = self._selected_beer_standard()
        if standard is None:
            return
        dialog = StandardEditorDialog(
            self.beer_unit_combo.currentText(), standard, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        standard.name = dialog.name_edit.text().strip()
        standard.concentration = dialog.concentration
        self._beer_last_transferred_signature = None
        self._refresh_beer_ui()

    def delete_selected_beer_standard(self):
        standard = self._selected_beer_standard()
        if standard is None:
            return
        answer = QMessageBox.question(
            self,
            "Supprimer l'étalon",
            f"Supprimer « {standard.name} » et sa mesure ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.beer_standards.remove(standard)
        self._beer_last_transferred_signature = None
        self._refresh_beer_ui()

    def _confirm_beer_measurement(self, standard=None):
        dialog = BeerLambertPreparationDialog(
            standard, unit=self.beer_unit_combo.currentText(), parent=self
        )
        return dialog.exec() == QDialog.DialogCode.Accepted

    def measure_selected_beer_standard(self):
        standard = self._selected_beer_standard()
        if standard is None:
            self._show_error("Sélectionnez un étalon à mesurer.")
            return
        self._start_beer_measurement(("standard", standard.identifier), standard)

    def measure_beer_unknown(self):
        self._start_beer_measurement(("unknown", None), None)

    def _start_beer_measurement(self, target, standard):
        if self.calibration is None:
            self._show_error("Un étalonnage noir et blanc valide est requis.")
            return
        if not self._controller_allows_measurement():
            self._show_error("Le spectrophotomètre n'est pas prêt pour cette mesure.")
            return
        if not self._confirm_beer_measurement(standard):
            return
        if self.calibration is None or not self._controller_allows_measurement():
            self._show_error("L'état du spectrophotomètre a changé ; mesure annulée.")
            return
        self._pending_beer_target = target
        self.request_measurement(MeasurementKind.SAMPLE)
        if self._pending_kind is None:
            self._pending_beer_target = None
            return
        self.measurement_status.setText(
            "Mesure de l'étalon en cours…"
            if target[0] == "standard"
            else "Mesure de l'inconnue en cours…"
        )

    def _spectrum_uses_active_calibration(self, spectrum):
        return (
            spectrum is not None
            and self.calibration is not None
            and spectrum.calibration.reference_id == self.calibration.reference_id
        )

    def _beer_absorbance(self, spectrum):
        if not self._spectrum_uses_active_calibration(spectrum):
            return None
        return band_absorbance(spectrum, self.beer_band_index())

    def _beer_valid_points(self):
        points = []
        for standard in self.beer_standards:
            absorbance = self._beer_absorbance(standard.spectrum)
            if absorbance is not None:
                points.append((standard.concentration, absorbance))
        return points

    @staticmethod
    def _numeric_text(value):
        return format(float(value), ".17g")

    def _refresh_beer_ui(self):
        if not hasattr(self, "beer_table"):
            return
        unit = self.beer_unit_combo.currentText()
        wavelength = self.beer_wavelength()
        selected = self._selected_beer_standard()
        selected_id = selected.identifier if selected else None
        self.beer_table.setRowCount(len(self.beer_standards))
        self.beer_table.setHorizontalHeaderLabels(
            ("Solution", f"c ({unit})", f"A ({wavelength} nm)", "État")
        )
        self.beer_table.resize_columns_to_viewport()
        for row, standard in enumerate(self.beer_standards):
            absorbance = self._beer_absorbance(standard.spectrum)
            if standard.spectrum is None:
                state = "À mesurer"
            elif not self._spectrum_uses_active_calibration(standard.spectrum):
                state = "Référence inactive"
            elif absorbance is None:
                state = "Bande indisponible"
            else:
                state = "Valide"
            values = (
                standard.name,
                format_concentration(standard.concentration),
                "—" if absorbance is None else format_absorbance(absorbance),
                state,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                alignment = (
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    if column in (1, 2)
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                item.setTextAlignment(alignment)
                self.beer_table.setItem(row, column, item)
            if standard.identifier == selected_id:
                self.beer_table.selectRow(row)

        self.beer_plot.clear()
        legend = self.beer_plot.getPlotItem().legend
        if legend is not None:
            legend.clear()
        self.beer_points_item = None
        self.beer_regression_item = None
        self.beer_unknown_item = None
        self.beer_unknown_horizontal = None
        self.beer_unknown_vertical = None
        self.beer_unknown_x_label = None
        self.beer_unknown_y_label = None
        self.beer_unknown_display_result = None
        points = self._beer_valid_points()
        if points:
            xs, ys = zip(*points)
            self.beer_points_item = self.beer_plot.plot(
                xs,
                ys,
                pen=None,
                symbol="o",
                symbolSize=10,
                symbolPen=pg.mkPen(SERIES_COLORS[0], width=1.5),
                symbolBrush=pg.mkBrush(SERIES_COLORS[0]),
                name="Points expérimentaux",
            )
            self.beer_points_item.setZValue(10)
        try:
            self.beer_regression = fit_beer_lambert(points)
        except BeerLambertError as error:
            self.beer_regression = None
            self.beer_equation_label.setText("Régression indisponible")
            self.beer_r_squared_label.setText("R² : —")
            self.beer_regression_warning.setText(str(error))
        else:
            regression = self.beer_regression
            x_values = np.array([0.0, regression.concentration_max])
            y_values = regression.slope * x_values
            self.beer_regression_item = self.beer_plot.plot(
                x_values,
                y_values,
                pen=pg.mkPen(SERIES_COLORS[1], width=2),
                name="Régression A = k × c",
            )
            self.beer_regression_item.setZValue(5)
            self.beer_equation_label.setText(
                f"A = {format(regression.slope, '.6g').replace('.', ',')} × c"
            )
            r_squared = (
                "—"
                if regression.r_squared is None
                else format(regression.r_squared, ".6g").replace(".", ",")
            )
            self.beer_r_squared_label.setText(f"R² : {r_squared}")
            self.beer_regression_warning.setText(
                "Deux points seulement : la linéarité reste à confirmer."
                if regression.two_point_only
                else f"Ajustement sur {regression.point_count} points valides."
            )
        self.beer_plot.setLabel("bottom", "Concentration", units=unit)

        self.beer_unknown_band_label.setText(
            f"Bande utilisée : {wavelength} nm (F{self.beer_band_index() + 1})"
        )
        unknown_absorbance = self._beer_absorbance(self.beer_unknown_spectrum)
        self.beer_unknown_absorbance_label.setText(
            "Absorbance : —"
            if unknown_absorbance is None
            else f"Absorbance : {format_absorbance(unknown_absorbance)}"
        )
        unknown_result = None
        if unknown_absorbance is None:
            self.beer_unknown_result_label.setText("Concentration : —")
            if self.beer_unknown_spectrum is None:
                warning = ""
            elif not self._spectrum_uses_active_calibration(self.beer_unknown_spectrum):
                warning = "Mesure associée à une référence inactive."
            else:
                warning = "Bande indisponible pour cette mesure."
            self.beer_unknown_warning.setText(warning)
        elif self.beer_regression is None:
            self.beer_unknown_result_label.setText("Concentration : —")
            self.beer_unknown_warning.setText("Régression invalide : aucun résultat calculé.")
        else:
            try:
                result = calculate_unknown_concentration(
                    unknown_absorbance, self.beer_regression
                )
            except BeerLambertError as error:
                self.beer_unknown_result_label.setText("Concentration : —")
                self.beer_unknown_warning.setText(str(error))
            else:
                unknown_result = result
                self.beer_unknown_result_label.setText(
                    f"Concentration : {format_concentration(result.concentration)} {unit}"
                )
                self.beer_unknown_warning.setText(
                    "Attention : résultat hors de la gamme d'étalonnage."
                    if result.extrapolated
                    else "Résultat compris dans la gamme d'étalonnage."
                )

        if unknown_result is not None:
            concentration = unknown_result.concentration
            absorbance = unknown_result.absorbance
            orange = "#F57C00"
            projection_pen = pg.mkPen(
                orange, width=1.4, style=Qt.PenStyle.DashLine
            )
            self.beer_unknown_horizontal = self.beer_plot.plot(
                [0.0, concentration], [absorbance, absorbance], pen=projection_pen
            )
            self.beer_unknown_vertical = self.beer_plot.plot(
                [concentration, concentration], [0.0, absorbance], pen=projection_pen
            )
            self.beer_unknown_item = self.beer_plot.plot(
                [concentration],
                [absorbance],
                pen=None,
                symbol="t" if unknown_result.extrapolated else "d",
                symbolSize=13,
                symbolPen=pg.mkPen(orange, width=2),
                symbolBrush=pg.mkBrush(orange),
                name=(
                    "Inconnue — extrapolation"
                    if unknown_result.extrapolated
                    else "Inconnue"
                ),
            )
            self.beer_unknown_horizontal.setZValue(3)
            self.beer_unknown_vertical.setZValue(3)
            self.beer_unknown_item.setZValue(12)
            self.beer_unknown_display_result = unknown_result
            self.beer_unknown_x_label = pg.TextItem(
                text=(
                    f"c = {_format_projection_concentration(concentration)} "
                    f"{unit}"
                ),
                anchor=(0.5, 1),
            )
            self.beer_unknown_y_label = pg.TextItem(
                text=f"A = {format_absorbance(absorbance)}",
                anchor=(0, 0.5),
            )
            for value_label in (
                self.beer_unknown_x_label,
                self.beer_unknown_y_label,
            ):
                self.beer_plot.addItem(value_label, ignoreBounds=True)
                value_label.setZValue(20)
            self._style_beer_projection_labels()

        x_candidates = [x for x, _ in points]
        y_candidates = [y for _, y in points]
        if self.beer_regression is not None:
            x_candidates.append(self.beer_regression.concentration_max)
            y_candidates.append(
                self.beer_regression.slope * self.beer_regression.concentration_max
            )
        if unknown_result is not None:
            x_candidates.append(unknown_result.concentration)
            y_candidates.append(unknown_result.absorbance)
        positive_x = max((value for value in x_candidates if value > 0), default=1.0)
        x_max = max(x_candidates, default=positive_x)
        y_min = min([0.0, *y_candidates])
        y_max = max([0.0, *y_candidates])
        y_span = y_max - y_min
        self.beer_plot.setRange(
            xRange=(0.0, x_max + max(positive_x * 0.08, 1e-12)),
            yRange=(
                y_min - (y_span * 0.06 if y_min < 0 else 0.0),
                y_max + max(y_span * 0.08, 1e-6),
            ),
            padding=0,
        )
        self._position_beer_projection_labels()
        self._update_controls()

    def _beer_transfer_signature(self):
        points = tuple(sorted(self._beer_valid_points()))
        if self.calibration is None:
            return None
        return (
            self.calibration.reference_id,
            self.beer_unit_combo.currentText(),
            self.beer_wavelength(),
            points,
        )

    def _confirm_beer_transfer(self):
        return ask_yes_no(
            self,
            "Transférer vers Graphique",
            "Les concentrations et les absorbances mesurées seront transférées "
            "dans Données. Un graphique avec la droite d'étalonnage sera "
            "automatiquement créé.\n\nVoulez-vous continuer ?",
        )

    def transfer_beer_to_graph(self):
        signature = self._beer_transfer_signature()
        if (
            signature is None
            or self.beer_regression is None
            or self.data_tab is None
            or self.graph_workspace is None
        ):
            self.beer_transfer_status.setText("Transfert indisponible.")
            self._update_controls()
            return None
        _, unit, wavelength, points = signature
        try:
            columns = self._beer_transfer_columns.get(signature)
            if columns is None:
                if not self._confirm_beer_transfer():
                    self.beer_transfer_status.setText("Transfert annulé.")
                    return None
                rows = [
                    [self._numeric_text(concentration), self._numeric_text(absorbance)]
                    for concentration, absorbance in points
                ]
                columns = self.data_tab.append_measurements(
                    [f"Concentration BL {wavelength} nm", f"Absorbance {wavelength} nm"],
                    [unit, ""],
                    rows,
                )
                self._beer_transfer_columns[signature] = columns
            graph, _fit = self.graph_workspace.add_data_graph_with_model(
                columns[0],
                columns[1],
                "linear",
                title=f"Beer-Lambert à {wavelength} nm",
            )
        except Exception as error:
            QMessageBox.warning(
                self,
                "Transfert impossible",
                "Les données n'ont pas pu être entièrement transférées : "
                f"{error}\nLa gamme est conservée et le transfert peut être réessayé.",
            )
            self.beer_transfer_status.setText("Échec du transfert.")
            self._update_controls()
            return None
        self._beer_last_transferred_signature = signature
        self.beer_transfer_status.setText(
            f"{len(points)} point(s) transféré(s) — graphique créé."
        )
        self._update_controls()
        if self.show_graph is not None:
            self.show_graph()
        return columns, graph

    def refresh_ports(self):
        current = self.port_combo.currentData()
        self.port_combo.clear()
        for port in self.controller.available_ports():
            details = f" — {port.description}" if port.description else ""
            self.port_combo.addItem(f"{port.name}{details}", port.name)
        if current is not None:
            index = self.port_combo.findData(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        update_popup_height(self.port_combo)
        self._update_controls()

    def toggle_connection(self):
        if self.controller.state in (
            SpectroControllerState.DISCONNECTED,
            SpectroControllerState.ERROR,
        ):
            self.connect_selected_port()
        else:
            self.disconnect()

    def connect_selected_port(self):
        port_name = self.port_combo.currentData()
        if not port_name:
            self._show_error("Sélectionnez un port série avant la connexion.")
            return
        self.session_id = uuid4().hex
        self._next_config_id = 1
        self._clear_active_calibration()
        self._configuration_dirty = True
        try:
            if not self.controller.open(port_name):
                self.session_id = None
        except (SpectroSerialError, ValueError) as error:
            self.session_id = None
            self._show_error(str(error))
        self._update_controls()

    def disconnect(self):
        if self._disconnect_pending:
            return
        if self.controller.state is SpectroControllerState.STOPPING:
            self._disconnect_pending = True
            self.measurement_status.setText("Attente de l'arrêt avant déconnexion…")
            self.disconnect_timer.start()
            self._update_controls()
            return
        if self.controller.state is SpectroControllerState.MEASURING:
            self._disconnect_pending = True
            self.measurement_status.setText("Arrêt de la mesure avant déconnexion…")
            if self.controller.stop():
                self.disconnect_timer.start()
                self._update_controls()
                return
        self._finish_disconnect()

    def _force_disconnect(self):
        self.measurement_status.setText(
            "Déconnexion forcée aprè expiration du délai d'arrêt."
        )
        self._finish_disconnect()

    def _finish_disconnect(self):
        self.disconnect_timer.stop()
        self._disconnect_pending = False
        self._pending_kind = None
        self._pending_absorbance = False
        self._pending_beer_target = None
        self.controller.close()
        self.session_id = None
        self.applied_config = None
        self._configuration_dirty = True
        self._clear_active_calibration()
        self.absorbance_acquisition_status.setText("Spectrophotomètre déconnecté.")
        self._update_controls()

    def _controller_ready(self, firmware_info):
        version = ".".join(map(str, firmware_info.version))
        self.connection_status.setText(f"Spectro {version} détecté")
        self.apply_configuration()

    def requested_config(self) -> SpectroConfig:
        if self._next_config_id > 0xFFFF:
            raise ValueError("Identifiants de configuration épuisés ; reconnectez l'appareil.")
        return SpectroConfig(
            self._next_config_id,
            self.atime_spin.value(),
            self.astep_spin.value(),
            self.gain_combo.currentData(),
            self.pwm_spin.value(),
        )

    def apply_configuration(self):
        try:
            requested = self.requested_config()
            self.controller.configure(requested)
            self._next_config_id += 1
            self.measurement_status.setText("Configuration du capteur…")
        except (SpectroSerialError, ValueError) as error:
            self._show_error(str(error))
        self._update_controls()

    def _configuration_accepted(self, applied: SpectroConfig):
        if self.applied_config is not None and not self._same_parameters(
            self.applied_config, applied
        ):
            self._clear_active_calibration()
        self.applied_config = applied
        for widget in (self.atime_spin, self.astep_spin, self.gain_combo, self.pwm_spin):
            widget.blockSignals(True)
        self.atime_spin.setValue(applied.atime)
        self.astep_spin.setValue(applied.astep)
        self.gain_combo.setCurrentIndex(self.gain_combo.findData(applied.gain))
        self.pwm_spin.setValue(applied.led_pwm)
        for widget in (self.atime_spin, self.astep_spin, self.gain_combo, self.pwm_spin):
            widget.blockSignals(False)
        self._configuration_dirty = False
        self.applied_values_label.setText(
            f"ATIME {applied.atime} · ASTEP {applied.astep} · "
            f"gain {self._gain_text(applied.gain)} · PWM {applied.led_pwm}"
        )
        self.measurement_status.setText("Capteur configuré. Mesurez le noir.")
        self._update_calibration_status()
        self._update_controls()

    def _parameters_changed(self):
        if self.applied_config is None:
            self._configuration_dirty = True
        else:
            current = SpectroConfig(
                self.applied_config.config_id,
                self.atime_spin.value(),
                self.astep_spin.value(),
                self.gain_combo.currentData(),
                self.pwm_spin.value(),
            )
            self._configuration_dirty = not self._same_parameters(
                current, self.applied_config
            )
        if self._configuration_dirty and self.calibration is not None:
            self._clear_active_calibration()
            self.measurement_status.setText(
                "Paramètres modifiés : appliquez-les puis refaites l'étalonnage."
            )
        self._update_controls()

    def request_measurement(self, kind: MeasurementKind):
        if self._pending_kind is not None or self._disconnect_pending:
            return
        if kind is MeasurementKind.WHITE and self.dark_measurement is None:
            self._show_error("Mesurez d'abord le noir.")
            return
        if kind is MeasurementKind.SAMPLE and self.calibration is None:
            self._show_error("Un étalonnage noir et blanc valide est requis.")
            return
        if not self._controller_allows_measurement():
            self._show_error("Le spectrophotomètre n'est pas prêt pour cette mesure.")
            return
        if kind in (MeasurementKind.DARK, MeasurementKind.WHITE):
            if not self._confirm_measurement_preparation(kind):
                return
            if not self._controller_allows_measurement():
                self._show_error(
                    "L'état du spectrophotomètre a changé ; mesure annulée."
                )
                return
        try:
            self._pending_kind = kind
            if kind is MeasurementKind.DARK:
                self.controller.measure_dark()
                text = "Mesure noire en cours…"
            else:
                self.controller.measure_lit()
                text = (
                    "Mesure blanche en cours…"
                    if kind is MeasurementKind.WHITE
                    else "Mesure de l'échantillon en cours…"
                )
            self.measurement_status.setText(text)
        except (SpectroSerialError, ValueError) as error:
            self._pending_kind = None
            self._show_error(str(error))
        self._update_controls()

    def _controller_allows_measurement(self):
        return (
            self.controller.state is SpectroControllerState.CONFIGURED
            and self.applied_config is not None
            and not self._configuration_dirty
            and self._pending_kind is None
            and not self._disconnect_pending
        )

    def _confirm_measurement_preparation(self, kind: MeasurementKind) -> bool:
        dialog = MeasurementPreparationDialog(kind, self)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _measurement_received(self, data):
        kind = self._pending_kind
        absorbance_target = self._pending_absorbance
        beer_target = self._pending_beer_target
        self._pending_kind = None
        self._pending_absorbance = False
        self._pending_beer_target = None
        if kind is None or self.applied_config is None or self.session_id is None:
            self._show_error("Mesure reçue sans contexte scientifique actif.")
            return
        try:
            measured = SpectroMeasurement(
                kind, data, self.applied_config, self.session_id
            )
            if kind is MeasurementKind.DARK:
                self.dark_measurement = measured
                self.white_measurement = None
                self.calibration = None
                self.measurement_status.setText(
                    "Noir mesuré. Placez la cuve de référence."
                )
            elif kind is MeasurementKind.WHITE:
                self.white_measurement = measured
                candidate = SpectroCalibration(
                    uuid4().hex, self.dark_measurement, self.white_measurement
                )
                usable = self._usable_reference_band_count(candidate)
                if usable:
                    self.calibration = candidate
                    self._absorbance_recalibration_expanded = False
                    suffix = "" if usable == 8 else f" ({usable}/8 bandes exploitables)"
                    self.measurement_status.setText(
                        f"Étalonnage prêt{suffix}. Placez l'échantillon."
                    )
                else:
                    self.calibration = None
                    self.measurement_status.setText(
                        "Référence invalide : aucune bande visible exploitable."
                    )
            else:
                spectrum = calculate_absorbance(measured, self.calibration)
                if absorbance_target:
                    self.absorbance_spectrum = spectrum
                    self.absorbance_acquisition_status.setText("Mesure terminée.")
                elif beer_target is None:
                    self.add_spectrum(spectrum)
                elif beer_target[0] == "unknown":
                    self.beer_unknown_spectrum = spectrum
                    self._beer_last_transferred_signature = None
                else:
                    standard = next(
                        (
                            item
                            for item in self.beer_standards
                            if item.identifier == beer_target[1]
                        ),
                        None,
                    )
                    if standard is None:
                        raise ValueError("L'étalon mesuré n'existe plus.")
                    standard.spectrum = spectrum
                    self._beer_last_transferred_signature = None
                unavailable = sum(not band.is_valid for band in spectrum.bands)
                suffix = (
                    ""
                    if unavailable == 0
                    else f" · {unavailable} bande(s) indisponible(s)"
                )
                self.measurement_status.setText(f"Spectre mesuré{suffix}.")
        except (TypeError, ValueError) as error:
            self._show_error(str(error))
        self._update_calibration_status()
        self._refresh_absorbance_ui()
        self._refresh_beer_ui()
        self._update_controls()

    def _measurement_failed(self, request_id, message):
        self._pending_kind = None
        self._pending_absorbance = False
        self._pending_beer_target = None
        self.absorbance_acquisition_status.setText(
            f"Mesure impossible : {message}"
        )
        self._show_error(f"Mesure {request_id} impossible : {message}")

    def _stopped(self, request_id):
        self._pending_kind = None
        self._pending_absorbance = False
        self._pending_beer_target = None
        if self._disconnect_pending:
            self._finish_disconnect()
        else:
            self.measurement_status.setText(f"Mesure {request_id} arrêtée.")
            self.absorbance_acquisition_status.setText("Mesure arrêtée.")
            self._update_controls()

    def _controller_error(self, message):
        self._pending_kind = None
        self._pending_absorbance = False
        self._pending_beer_target = None
        if self._disconnect_pending:
            self._finish_disconnect()
            return
        self.session_id = None
        self.applied_config = None
        self._configuration_dirty = True
        self._clear_active_calibration()
        self.absorbance_acquisition_status.setText(f"Erreur — {message}")
        self._show_error(message)

    def _state_changed(self, state):
        labels = {
            SpectroControllerState.DISCONNECTED: "Déconnecté",
            SpectroControllerState.WAITING_HANDSHAKE: "Connexion…",
            SpectroControllerState.READY: "Prêt à configurer",
            SpectroControllerState.CONFIGURING: "Configuration…",
            SpectroControllerState.CONFIGURED: "Prêt",
            SpectroControllerState.MEASURING: "Mesure en cours",
            SpectroControllerState.STOPPING: "Arrêt…",
            SpectroControllerState.ERROR: "Erreur",
        }
        self.connection_status.setText(labels[state])
        self._update_controls()

    def _clear_active_calibration(self):
        self.dark_measurement = None
        self.white_measurement = None
        self.calibration = None
        self._update_calibration_status()

    def _update_calibration_status(self):
        if self.dark_measurement is None:
            text = "Noir manquant"
        elif self.white_measurement is None:
            text = "Blanc manquant"
        elif self.calibration is None:
            text = "Référence invalide"
        else:
            usable = self._usable_reference_band_count(self.calibration)
            text = (
                "Étalonnage prêt"
                if usable == 8
                else f"Étalonnage partiel · {usable}/8 bandes"
            )
        self.calibration_status.setText(text)
        if hasattr(self, "absorbance_calibration_status"):
            self.absorbance_calibration_status.setText(
                f"✓ {text}" if self.calibration is not None else text
            )
            self._update_absorbance_calibration_controls()
            self._refresh_absorbance_ui()
        if hasattr(self, "beer_calibration_status"):
            self.beer_calibration_status.setText(text)
            self._refresh_beer_ui()

    @staticmethod
    def _usable_reference_band_count(calibration):
        return sum(
            calibration.white.bands[index] > calibration.dark.bands[index]
            and not calibration.white.data.is_saturated(index)
            and not calibration.dark.data.is_saturated(index)
            for index in range(8)
        )

    @staticmethod
    def _same_parameters(first, second):
        return (
            first.atime,
            first.astep,
            first.gain,
            first.led_pwm,
        ) == (
            second.atime,
            second.astep,
            second.gain,
            second.led_pwm,
        )

    @staticmethod
    def _gain_text(gain):
        return gain.name.removeprefix("GAIN_").replace("_", ",").replace("X", "×")

    def _toggle_advanced(self, checked):
        self.advanced_content.setVisible(checked)
        self.advanced_toggle.setText(
            "Masquer les paramètres" if checked else "Afficher les paramètres"
        )

    def add_spectrum(self, spectrum: AbsorbanceSpectrum):
        display = SpectrumDisplay(
            spectrum=spectrum,
            name=f"Spectre {len(self.spectra) + 1}",
            color=SERIES_COLORS[len(self.spectra) % len(SERIES_COLORS)],
        )
        self.spectra.append(display)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, display)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(LIGHT.small, 0, LIGHT.small, 0)
        visible = QCheckBox()
        visible.setChecked(True)
        visible.setToolTip("Afficher ou masquer ce spectre")
        name = QLineEdit(display.name)
        color = QLabel("●")
        color.setStyleSheet(f"color: {display.color}; font-size: 18px;")
        row_layout.addWidget(visible)
        row_layout.addWidget(color)
        row_layout.addWidget(name, 1)
        item.setSizeHint(row.sizeHint())
        self.spectra_list.addItem(item)
        self.spectra_list.setItemWidget(item, row)
        self.spectra_list.setCurrentItem(item)
        display.list_item = item
        visible.toggled.connect(
            lambda checked, selected=display: self._set_spectrum_visible(
                selected, checked
            )
        )
        name.textChanged.connect(
            lambda text, selected=display: self._rename_spectrum(selected, text)
        )
        self.refresh_plot()
        self._update_controls()

    def _rename_spectrum(self, display, text):
        display.name = text.strip() or "Spectre sans nom"
        self.refresh_plot()

    def _set_spectrum_visible(self, display, visible):
        display.visible = visible
        self.refresh_plot()

    def remove_selected_spectrum(self):
        item = self.spectra_list.currentItem()
        if item is None:
            return
        display = item.data(Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(
            self,
            "Supprimer le spectre",
            f"Supprimer « {display.name} » ?\n\nL'étalonnage actif sera conservé.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.spectra.remove(display)
        self.spectra_list.takeItem(self.spectra_list.row(item))
        self.refresh_plot()
        self._update_controls()

    def refresh_plot(self):
        self.plot.clear()
        legend = self.plot.getPlotItem().legend
        if legend is not None:
            legend.clear()
        for display in self.spectra:
            display.experimental_item = None
            display.interpolation_items.clear()
            display.fill_items.clear()
            if not display.visible:
                continue
            valid = [band for band in display.spectrum.bands if band.is_valid]
            xs = [band.wavelength_nm for band in valid]
            ys = [band.absorbance for band in valid]
            display.experimental_item = self.plot.plot(
                xs,
                ys,
                pen=None,
                symbol="o",
                symbolSize=9,
                symbolPen=pg.mkPen(display.color, width=1.5),
                symbolBrush=pg.mkBrush(display.color),
                name=f"{display.name} — points mesurés",
            )
            display.experimental_item.setZValue(20)
            for run_index, run in enumerate(self._valid_runs(display.spectrum)):
                if len(run) < 2:
                    continue
                run_x = np.array([band.wavelength_nm for band in run], dtype=float)
                run_y = np.array([band.absorbance for band in run], dtype=float)
                smooth_x = np.linspace(run_x[0], run_x[-1], max(40, len(run) * 30))
                smooth_y = PchipInterpolator(run_x, run_y)(smooth_x)
                fill = self._create_spectrum_fill(smooth_x, smooth_y)
                self.plot.addItem(fill)
                display.fill_items.append(fill)
                curve = self.plot.plot(
                    smooth_x,
                    smooth_y,
                    pen=pg.mkPen(display.color, width=1.8),
                    name=(
                        f"{display.name} — interpolation PCHIP"
                        if run_index == 0
                        else None
                    ),
                )
                curve.setZValue(10)
                display.interpolation_items.append(curve)
        self.plot.setXRange(400, 695, padding=0)
        self.plot.enableAutoRange(axis="y", enable=True)

    def _create_spectrum_fill(self, xs, ys):
        path = QPainterPath()
        path.moveTo(float(xs[0]), 0.0)
        path.lineTo(float(xs[0]), float(ys[0]))
        for x, y in zip(xs[1:], ys[1:]):
            path.lineTo(float(x), float(y))
        path.lineTo(float(xs[-1]), 0.0)
        path.closeSubpath()

        gradient = QLinearGradient(415.0, 0.0, 680.0, 0.0)
        dark_background = (
            self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        )
        alpha = 120 if dark_background else 160
        for wavelength, color_name in (
            (415, "#6F2DBD"),
            (445, "#2455D6"),
            (480, "#009FE3"),
            (515, "#00A651"),
            (555, "#F0D000"),
            (590, "#FF8C00"),
            (630, "#E32636"),
            (680, "#A4142D"),
        ):
            color = QColor(color_name)
            color.setAlpha(alpha)
            gradient.setColorAt((wavelength - 415) / (680 - 415), color)

        item = QGraphicsPathItem(path)
        item.setPen(Qt.PenStyle.NoPen)
        item.setBrush(QBrush(gradient))
        item.setZValue(-20)
        return item

    @staticmethod
    def _valid_runs(spectrum):
        runs = []
        current = []
        for band in spectrum.bands:
            if band.is_valid:
                current.append(band)
            elif current:
                runs.append(current)
                current = []
        if current:
            runs.append(current)
        return runs

    def _show_error(self, message):
        self.measurement_status.setText(f"Erreur — {message}")
        self._update_controls()

    def _update_controls(self):
        state = self.controller.state
        disconnected = state in (
            SpectroControllerState.DISCONNECTED,
            SpectroControllerState.ERROR,
        )
        busy = state in (
            SpectroControllerState.WAITING_HANDSHAKE,
            SpectroControllerState.CONFIGURING,
            SpectroControllerState.MEASURING,
            SpectroControllerState.STOPPING,
        ) or (
            self._pending_kind is not None
            or self._pending_absorbance
            or self._pending_beer_target is not None
        )
        configured = (
            state is SpectroControllerState.CONFIGURED
            and self.applied_config is not None
            and not self._configuration_dirty
            and not self._disconnect_pending
        )
        self.connect_button.setText("Connecter" if disconnected else "Déconnecter")
        self.connect_button.setEnabled(not self._disconnect_pending)
        self.port_combo.setEnabled(disconnected)
        self.refresh_button.setEnabled(disconnected)
        self.mode_combo.setEnabled(not busy)
        self.apply_config_button.setEnabled(
            state in (SpectroControllerState.READY, SpectroControllerState.CONFIGURED)
            and not busy
        )
        for widget in (self.atime_spin, self.astep_spin, self.gain_combo, self.pwm_spin):
            widget.setEnabled(not busy and not disconnected)
        self.dark_button.setEnabled(configured)
        self.white_button.setEnabled(configured and self.dark_measurement is not None)
        self.sample_button.setEnabled(configured and self.calibration is not None)
        self.remove_spectrum_button.setEnabled(
            self.spectra_list.currentItem() is not None
        )
        if hasattr(self, "absorbance_measure_button"):
            self.absorbance_band_combo.setEnabled(not busy)
            self.absorbance_dark_button.setEnabled(configured)
            self.absorbance_white_button.setEnabled(
                configured and self.dark_measurement is not None
            )
            self.absorbance_measure_button.setEnabled(
                configured and self.calibration is not None
            )
        if hasattr(self, "beer_table"):
            selected = self._selected_beer_standard() is not None
            self.beer_unit_combo.setEnabled(not busy)
            self.beer_band_combo.setEnabled(not busy)
            self.beer_add_button.setEnabled(not busy)
            self.beer_edit_button.setEnabled(not busy and selected)
            self.beer_delete_button.setEnabled(not busy and selected)
            self.beer_measure_standard_button.setEnabled(
                configured and self.calibration is not None and selected
            )
            self.beer_measure_unknown_button.setEnabled(
                configured and self.calibration is not None
            )
            signature = self._beer_transfer_signature()
            self.beer_transfer_button.setEnabled(
                not busy
                and self.data_tab is not None
                and self.graph_workspace is not None
                and self.beer_regression is not None
                and signature is not None
                and signature != self._beer_last_transferred_signature
            )

    def shutdown(self):
        """Nettoyer timers, calibration et port lors d'une fermeture globale."""

        if self._closing:
            return
        self._closing = True
        self.disconnect_timer.stop()
        if self.controller.state is SpectroControllerState.MEASURING:
            try:
                self.controller.stop()
            except (SpectroSerialError, ValueError):
                pass
        self.controller.close()
        self._pending_kind = None
        self._pending_absorbance = False
        self._pending_beer_target = None
        self.session_id = None
        self.applied_config = None
        self._clear_active_calibration()
