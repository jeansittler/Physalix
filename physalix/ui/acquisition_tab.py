"""Interface simple d'acquisition RC, indépendante du document Physalix."""

from __future__ import annotations

from dataclasses import dataclass
import math

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtSerialPort import QSerialPortInfo
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
    QVBoxLayout, QWidget,
)

from physalix.acquisition import (
    AcquisitionConfig, AcquisitionController, AcquisitionError, AcquisitionResult,
    AcquisitionState,
    CAPABILITY_CONTINUOUS_SQUARE, CAPABILITY_SQUARE_BURST, ContinuousSquareConfig,
    ContinuousSquarePlan, DataBatch, DigitalGenerationConfig, DigitalStepConfig,
    GbfDataBatch, GenerationType, GeneratorState, PROTOCOL_VERSION,
    SERIAL_RESOURCE_DISCONNECTED_MESSAGE, SquareBurstConfig, SquareBurstPlan,
    applied_duration_s, applied_square_frequency_hz, applied_square_period_s,
    generated_voltage_series, plan_square_burst,
)
from physalix.firmware_flash import (
    FirmwareCompatibility, FirmwareFlash, FlashErrorKind, compare_firmware,
)
from physalix.firmware_resources import FirmwareResourceError, load_uno_resources
from physalix.ui.components import (WheelSafeComboBox, label, page_header,
                                    page_layout, panel, role)
from physalix.ui.graph_series import PopupComboBox, configure_popup, update_popup_height
from physalix.ui.theme import LIGHT


ADC_REFERENCE_V = 5.0
ADC_MAX_CODE = 1023
PLOT_REFRESH_MS = 40
PORT_RELEASE_DELAY_MS = 300
RECONNECT_RETRY_MS = 600
RECONNECT_TIMEOUT_MS = 20_000
CONTINUOUS_SQUARE_MODE = "continuous_square"


@dataclass(frozen=True)
class AcquisitionPageResult:
    """Résultat conservé localement, sans écriture dans MeasurementsModel."""

    sampling_period_us: int
    generation: DigitalGenerationConfig
    times_s: tuple[float, ...]
    voltages_v: tuple[float, ...]
    generated_voltages_v: tuple[float, ...]
    complete: bool
    status: str
    generator_plan: ContinuousSquarePlan | None = None


def adc_to_volts(code: int, reference_v: float = ADC_REFERENCE_V) -> float:
    """Convertir un code Uno 10 bits avec une référence explicite, non calibrée."""
    return code * reference_v / ADC_MAX_CODE


class AcquisitionTab(QWidget):
    """Piloter une acquisition et afficher une courbe temporaire Uc(t)."""

    def __init__(self, controller: AcquisitionController | None = None, data_tab=None,
                 graph_workspace=None, show_graph=None, parent=None, *,
                 firmware_flash=None, firmware_resource_loader=load_uno_resources,
                 port_release_delay_ms: int = PORT_RELEASE_DELAY_MS,
                 reconnect_retry_ms: int = RECONNECT_RETRY_MS,
                 reconnect_timeout_ms: int = RECONNECT_TIMEOUT_MS):
        super().__init__(parent)
        self.controller = controller or AcquisitionController(self)
        self.firmware_flash = firmware_flash or FirmwareFlash(self)
        try:
            self.firmware_resources = firmware_resource_loader()
            self._firmware_resource_error = ""
        except FirmwareResourceError as error:
            self.firmware_resources = None
            self._firmware_resource_error = str(error)
        self.data_tab = data_tab
        self.graph_workspace = graph_workspace
        self.show_graph = show_graph
        self.results: list[AcquisitionPageResult] = []
        self.times_s: list[float] = []
        self.voltages_v: list[float] = []
        self.generated_voltages_v: list[float] = []
        self._start_after_configuration = False
        self._plot_dirty = False
        self._transferred = False
        self._transfer_columns = None
        self._session_uses_gbf = False
        self._generator_start_pending = False
        self._generator_stop_pending = False
        self._disconnect_after_generator_stop = False
        self._applied_generator_plan: ContinuousSquarePlan | None = None
        self._applied_acquisition_period_us: int | None = None
        self._configured_requested_period_us: int | None = None
        self._firmware_mode = "absent"
        self._detected_firmware_info = None
        self._flash_workflow_active = False
        self._flash_port = None
        self._reconnect_opened = False
        self._build_ui()
        self._connect_controller()
        self._connect_firmware_flash()
        self.port_release_timer = QTimer(self)
        self.port_release_timer.setSingleShot(True)
        self.port_release_timer.setInterval(port_release_delay_ms)
        self.port_release_timer.timeout.connect(self._start_flash_after_release)
        self.reconnect_retry_timer = QTimer(self)
        self.reconnect_retry_timer.setSingleShot(True)
        self.reconnect_retry_timer.setInterval(reconnect_retry_ms)
        self.reconnect_retry_timer.timeout.connect(self._attempt_flash_reconnect)
        self.reconnect_timeout_timer = QTimer(self)
        self.reconnect_timeout_timer.setSingleShot(True)
        self.reconnect_timeout_timer.setInterval(reconnect_timeout_ms)
        self.reconnect_timeout_timer.timeout.connect(self._flash_reconnect_timed_out)
        self.plot_timer = QTimer(self)
        self.plot_timer.setInterval(PLOT_REFRESH_MS)
        self.plot_timer.timeout.connect(self.refresh_plot)
        self.plot_timer.start()
        self.refresh_ports()
        self._sync_generation_ui()
        self._update_requested_values()
        self._update_controls(self.controller.state)

    def _build_ui(self):
        layout = page_layout(QVBoxLayout(self))
        layout.addWidget(page_header(
            "Acquisition", "Mesurer la tension Uc d'un circuit RC avec un Arduino Physalix."))

        connection, connection_layout = panel(kind="toolbar")
        connection.setObjectName("acquisitionConnectionBar")
        connection_layout.setSpacing(LIGHT.small)
        connection_row = QHBoxLayout()
        connection_row.setSpacing(LIGHT.related)
        connection_row.addWidget(label("Connexion", "toolbarLabel"))
        self.port_combo = WheelSafeComboBox()
        self.port_combo.setMinimumWidth(260)
        self.refresh_button = QPushButton("Actualiser")
        self.connect_button = QPushButton("Connecter")
        self.connection_status = QLabel("Déconnecté")
        self.connection_status.setWordWrap(False)
        connection_row.addWidget(label("Port", "fieldLabel"))
        connection_row.addWidget(self.port_combo, 1)
        connection_row.addWidget(self.refresh_button)
        connection_row.addWidget(self.connect_button)
        connection_layout.addLayout(connection_row)
        firmware_row = QHBoxLayout()
        firmware_row.setSpacing(LIGHT.related)
        firmware_row.addWidget(self.connection_status, 1)
        firmware_row.addWidget(label("Firmware", "fieldLabel"))
        self.firmware_status = QLabel("Firmware non détecté")
        self.firmware_status.setWordWrap(False)
        firmware_row.addWidget(self.firmware_status)
        self.firmware_button = QPushButton("Installer le firmware Physalix…")
        firmware_row.addWidget(self.firmware_button)
        connection_layout.addLayout(firmware_row)
        layout.addWidget(connection)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("acquisitionMainSplitter")
        self.main_splitter.setChildrenCollapsible(False)

        plot_panel, plot_layout = panel("E(t) et uC(t)")
        plot_panel.setObjectName("acquisitionPlotPanel")
        plot_panel.setMinimumSize(460, 320)
        plot_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        plot_layout.setContentsMargins(LIGHT.small, LIGHT.small,
                                       LIGHT.small, LIGHT.small)
        self.plot = pg.PlotWidget(background=LIGHT.surface)
        self.plot.setLabel("bottom", "Temps", units="s")
        self.plot.setLabel("left", "Tension", units="V")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.addLegend(offset=(8, 8))
        self.curve = self.plot.plot(
            [], [], pen=pg.mkPen(LIGHT.primary, width=2), name="uC — signal mesuré")
        self.generated_curve = self.plot.plot(
            [], [], pen=pg.mkPen("#d84315", width=2), name="E — signal généré")
        plot_layout.addWidget(self.plot, 1)
        self.main_splitter.addWidget(plot_panel)

        self.settings_column = QWidget()
        self.settings_column.setObjectName("acquisitionSettingsColumn")
        self.settings_column.setMinimumWidth(330)
        self.settings_column.setMaximumWidth(460)
        settings_column_layout = QVBoxLayout(self.settings_column)
        settings_column_layout.setContentsMargins(0, 0, 0, 0)
        settings_column_layout.setSpacing(LIGHT.related)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("acquisitionSettingsScroll")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_content = QWidget()
        settings_content.setMinimumWidth(0)
        settings_content.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setContentsMargins(0, 0, LIGHT.small, 0)
        settings_layout.setSpacing(LIGHT.related)
        self.settings_scroll.setWidget(settings_content)
        settings_column_layout.addWidget(self.settings_scroll, 1)

        acquisition_panel, acquisition_layout = panel("Acquisition")
        acquisition_form = QFormLayout()
        acquisition_form.setContentsMargins(0, 0, 0, 0)
        acquisition_form.setHorizontalSpacing(LIGHT.small)
        acquisition_form.setVerticalSpacing(LIGHT.small)
        acquisition_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        acquisition_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.channel_combo = WheelSafeComboBox()
        self.channel_combo.addItem("A0", 0)
        self.quantity_label = QLabel("Uc")
        self.unit_label = QLabel("V")
        measurement_widget = QWidget()
        measurement_row = QHBoxLayout(measurement_widget)
        measurement_row.setContentsMargins(0, 0, 0, 0)
        measurement_row.setSpacing(LIGHT.related)
        measurement_row.addWidget(self.quantity_label)
        measurement_row.addWidget(label("·", "muted"))
        measurement_row.addWidget(self.unit_label)
        measurement_row.addStretch(1)
        acquisition_form.addRow("Voie", self.channel_combo)
        acquisition_form.addRow("Mesure", measurement_widget)
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.001, 3600.0)
        self.duration_spin.setDecimals(3)
        self.duration_spin.setValue(1.0)
        self.duration_spin.setSuffix(" s")
        self.points_spin = QSpinBox()
        self.points_spin.setRange(2, 1_000_000)
        self.points_spin.setValue(101)
        self.requested_te_label = QLabel()
        self.requested_fe_label = QLabel()
        sampling_widget = QWidget()
        sampling_row = QGridLayout(sampling_widget)
        sampling_row.setContentsMargins(0, 0, 0, 0)
        sampling_row.setHorizontalSpacing(LIGHT.related)
        sampling_row.setVerticalSpacing(0)
        sampling_row.addWidget(label("Te", "caption"), 0, 0)
        sampling_row.addWidget(self.requested_te_label, 0, 1)
        sampling_row.addWidget(label("Fe", "caption"), 0, 2)
        sampling_row.addWidget(self.requested_fe_label, 0, 3)
        sampling_row.setColumnStretch(1, 1)
        sampling_row.setColumnStretch(3, 1)
        acquisition_form.addRow("Durée", self.duration_spin)
        acquisition_form.addRow("Points", self.points_spin)
        acquisition_form.addRow("Échantillonnage", sampling_widget)
        acquisition_layout.addLayout(acquisition_form)
        settings_layout.addWidget(acquisition_panel)

        generation_panel, generation_layout = panel("Génération")
        generation_form = QFormLayout()
        generation_form.setContentsMargins(0, 0, 0, 0)
        generation_form.setHorizontalSpacing(LIGHT.small)
        generation_form.setVerticalSpacing(LIGHT.small)
        generation_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        generation_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.generation_type_combo = PopupComboBox()
        self.generation_type_combo.addItem("Échelon", GenerationType.STEP)
        self.generation_type_combo.addItem("Carré — N périodes", GenerationType.SQUARE_BURST)
        self.generation_type_combo.addItem("GBF continu", CONTINUOUS_SQUARE_MODE)
        # Le popup conserve sa largeur confortable, tandis que le champ peut
        # se resserrer dans la colonne latérale sans rogner son libellé.
        self.generation_type_combo.setMinimumWidth(150)
        self.generation_type_combo.setMaximumWidth(LIGHT.field_medium)
        self.generation_type_combo.setMinimumContentsLength(8)
        self.generation_type_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        configure_popup(self.generation_type_combo, LIGHT.field_medium)
        update_popup_height(self.generation_type_combo)
        self.output_pin = QSpinBox()
        self.output_pin.setRange(2, 13)
        self.output_pin.setValue(8)
        generation_form.addRow("Mode de génération", self.generation_type_combo)
        generation_form.addRow("Sortie numérique", self.output_pin)
        self.step_initial_value = QLabel("0 V")
        self.step_final_value = QLabel("5 V")
        self.step_trigger_value = QLabel("Synchronisé avec l'acquisition")
        generation_form.addRow("Niveau initial", self.step_initial_value)
        generation_form.addRow("Niveau final", self.step_final_value)
        generation_form.addRow("Déclenchement", self.step_trigger_value)
        self.square_minimum_value = QLabel("0,0 V")
        self.square_maximum_value = QLabel("5,0 V")
        self.square_periods_spin = QSpinBox()
        self.square_periods_spin.setRange(1, 500_000)
        self.square_periods_spin.setValue(2)
        self.square_requested_period_label = QLabel()
        self.square_requested_frequency_label = QLabel()
        generation_form.addRow("Minimum", self.square_minimum_value)
        generation_form.addRow("Maximum", self.square_maximum_value)
        generation_form.addRow("Nombre de périodes", self.square_periods_spin)
        generation_form.addRow("Période calculée", self.square_requested_period_label)
        generation_form.addRow("Fréquence calculée", self.square_requested_frequency_label)
        self.square_requirement_label = label("", "muted")
        generation_form.addRow(self.square_requirement_label)
        self.gbf_shape_value = QLabel("Carré")
        self.gbf_output_value = QLabel("D8")
        self.gbf_minimum_value = QLabel("0,0 V")
        self.gbf_maximum_value = QLabel("5,0 V")
        self.gbf_frequency_spin = QDoubleSpinBox()
        self.gbf_frequency_spin.setRange(0.1, 1000.0)
        self.gbf_frequency_spin.setDecimals(3)
        self.gbf_frequency_spin.setSingleStep(0.1)
        self.gbf_frequency_spin.setValue(10.0)
        self.gbf_frequency_spin.setSuffix(" Hz")
        self.gbf_applied_frequency_label = QLabel("En attente de configuration")
        self.gbf_applied_period_label = QLabel("En attente de configuration")
        self.gbf_duty_value = QLabel("50 %")
        self.gbf_sampling_quality_label = label("—", "muted")
        self.gbf_state_label = QLabel("État inconnu")
        self.gbf_start_button = QPushButton("Démarrer le générateur")
        self.gbf_stop_button = QPushButton("Arrêter le générateur")
        gbf_actions_widget = QWidget()
        self.gbf_actions_layout = QVBoxLayout(gbf_actions_widget)
        self.gbf_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.gbf_actions_layout.setSpacing(LIGHT.small)
        self.gbf_actions_layout.addWidget(self.gbf_start_button)
        self.gbf_actions_layout.addWidget(self.gbf_stop_button)
        generation_form.addRow("Forme", self.gbf_shape_value)
        generation_form.addRow("Sortie", self.gbf_output_value)
        generation_form.addRow("Minimum", self.gbf_minimum_value)
        generation_form.addRow("Maximum", self.gbf_maximum_value)
        generation_form.addRow("Fréquence demandée", self.gbf_frequency_spin)
        generation_form.addRow("Fréquence appliquée", self.gbf_applied_frequency_label)
        generation_form.addRow("Période appliquée", self.gbf_applied_period_label)
        generation_form.addRow("Rapport cyclique", self.gbf_duty_value)
        generation_form.addRow("Échantillonnage", self.gbf_sampling_quality_label)
        generation_form.addRow("État du générateur", self.gbf_state_label)
        generation_form.addRow(gbf_actions_widget)
        self.gbf_requirement_label = label("", "muted")
        generation_form.addRow(self.gbf_requirement_label)
        self._step_generation_widgets = (
            self.step_initial_value, self.step_final_value, self.step_trigger_value)
        self._square_generation_widgets = (
            self.square_minimum_value, self.square_maximum_value, self.square_periods_spin,
            self.square_requested_period_label, self.square_requested_frequency_label)
        self._gbf_generation_widgets = (
            self.gbf_shape_value, self.gbf_output_value, self.gbf_minimum_value,
            self.gbf_maximum_value, self.gbf_frequency_spin,
            self.gbf_applied_frequency_label, self.gbf_applied_period_label,
            self.gbf_duty_value, self.gbf_sampling_quality_label,
            self.gbf_state_label, gbf_actions_widget)
        self._generation_form = generation_form
        generation_layout.addLayout(generation_form)
        settings_layout.addWidget(generation_panel)

        applied_panel, applied_layout = panel("Valeurs appliquées")
        self.applied_values_label = label("En attente de configuration.", "muted")
        applied_layout.addWidget(self.applied_values_label)
        settings_layout.addWidget(applied_panel)
        settings_layout.addStretch(1)

        actions_panel, actions_layout = panel("Actions")
        actions_panel.setObjectName("acquisitionActionsPanel")
        self.result_status = label("Aucune acquisition.", "muted")
        actions_layout.addWidget(self.result_status)
        main_actions = QHBoxLayout()
        main_actions.setSpacing(LIGHT.related)
        self.start_button = role(QPushButton("Démarrer"), "primary")
        self.stop_button = role(QPushButton("Arrêter"), "danger")
        self.transfer_button = QPushButton("Envoyer vers Données et Graphique")
        main_actions.addWidget(self.start_button, 1)
        main_actions.addWidget(self.stop_button, 1)
        actions_layout.addLayout(main_actions)
        actions_layout.addWidget(self.transfer_button)
        settings_column_layout.addWidget(actions_panel)

        self.main_splitter.addWidget(self.settings_column)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([900, 360])
        layout.addWidget(self.main_splitter, 1)

        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.port_combo.currentIndexChanged.connect(self._update_firmware_offer)
        self.firmware_button.clicked.connect(self.request_firmware_installation)
        self.duration_spin.valueChanged.connect(self._update_requested_values)
        self.points_spin.valueChanged.connect(self._update_requested_values)
        self.generation_type_combo.currentIndexChanged.connect(self._generation_type_changed)
        self.square_periods_spin.valueChanged.connect(self._update_requested_values)
        self.gbf_start_button.clicked.connect(self.start_generator)
        self.gbf_stop_button.clicked.connect(self.stop_generator)
        self.start_button.clicked.connect(self.start_acquisition)
        self.stop_button.clicked.connect(self.controller.stop)
        self.transfer_button.clicked.connect(self.transfer_result)

        self.setTabOrder(self.port_combo, self.refresh_button)
        self.setTabOrder(self.refresh_button, self.connect_button)
        self.setTabOrder(self.connect_button, self.firmware_button)
        self.setTabOrder(self.firmware_button, self.channel_combo)
        self.setTabOrder(self.channel_combo, self.duration_spin)
        self.setTabOrder(self.duration_spin, self.points_spin)
        self.setTabOrder(self.points_spin, self.generation_type_combo)
        self.setTabOrder(self.generation_type_combo, self.output_pin)
        self.setTabOrder(self.output_pin, self.square_periods_spin)
        self.setTabOrder(self.square_periods_spin, self.gbf_frequency_spin)
        self.setTabOrder(self.gbf_frequency_spin, self.gbf_start_button)
        self.setTabOrder(self.gbf_start_button, self.gbf_stop_button)
        self.setTabOrder(self.gbf_stop_button, self.start_button)
        self.setTabOrder(self.start_button, self.stop_button)
        self.setTabOrder(self.stop_button, self.transfer_button)

    def _connect_controller(self):
        self.controller.state_changed.connect(self._update_controls)
        self.controller.ready.connect(self._controller_ready)
        self.controller.configuration_accepted.connect(self._configuration_accepted)
        self.controller.data_batch_received.connect(self._data_received)
        self.controller.acquisition_finished.connect(self._acquisition_finished)
        self.controller.generator_state_changed.connect(self._generator_state_changed)
        self.controller.generator_configured.connect(self._generator_configured)
        self.controller.acquisition_armed.connect(self._acquisition_armed)
        self.controller.acquisition_triggered.connect(self._acquisition_triggered)
        self.controller.error_occurred.connect(self._controller_error)

    def _connect_firmware_flash(self):
        self.firmware_flash.upload_verified.connect(self._flash_upload_verified)
        self.firmware_flash.succeeded.connect(self._flash_succeeded)
        self.firmware_flash.failed.connect(self._flash_failed)
        self.firmware_flash.process_settled.connect(self._flash_process_settled)

    def refresh_ports(self):
        selected = self.port_combo.currentData()
        self.port_combo.clear()
        for info in QSerialPortInfo.availablePorts():
            details = [info.portName()]
            if info.description():
                details.append(info.description())
            if info.manufacturer():
                details.append(info.manufacturer())
            self.port_combo.addItem(" — ".join(details), info.portName())
        if selected is not None:
            index = self.port_combo.findData(selected)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        self._update_firmware_offer()

    def toggle_connection(self):
        if self.controller.state in (AcquisitionState.DISCONNECTED, AcquisitionState.ERROR):
            port_name = self.port_combo.currentData()
            if not port_name:
                self.connection_status.setText("Erreur — aucun port sélectionné")
                return
            self.controller.open(port_name)
        else:
            self.disconnect()

    def disconnect(self, reason="Acquisition interrompue par la déconnexion."):
        if self.controller.state in (AcquisitionState.ARMED, AcquisitionState.ACQUIRING,
                                     AcquisitionState.STOPPING):
            self.controller.stop()
            self._preserve_partial(reason)
        self._start_after_configuration = False
        if self.controller.generator_state is GeneratorState.RUNNING:
            self._disconnect_after_generator_stop = True
            try:
                if not self.controller.request_generator_shutdown():
                    self.connection_status.setText("Arrêt du générateur avant déconnexion…")
                    self._update_controls(self.controller.state)
                    return
            except Exception:
                # La fermeture immédiate reste sûre grâce au bail firmware de 2,5 s.
                pass
        self._disconnect_after_generator_stop = False
        self.controller.close()

    def _update_firmware_offer(self, *args):
        if self.firmware_resources is None:
            self.firmware_status.setText("Ressources firmware invalides")
            self.firmware_button.hide()
            return
        labels = {
            "absent": "Installer le firmware Physalix…",
            "older": "Mettre à jour le firmware…",
            "incompatible": "Réinstaller le firmware…",
        }
        visible = self._firmware_mode in labels
        self.firmware_button.setText(labels.get(self._firmware_mode, ""))
        self.firmware_button.setVisible(visible)
        controller_busy = self.controller.state in {
            AcquisitionState.WAITING_HANDSHAKE, AcquisitionState.ARMED,
            AcquisitionState.ACQUIRING, AcquisitionState.STOPPING,
        }
        generator_blocks_flash = (self._gbf_supported()
                                  and not self.controller.generator_ready_for_flash)
        enabled = (visible and bool(self.port_combo.currentData())
                   and not controller_busy and not self._start_after_configuration
                   and not self._flash_workflow_active
                   and not self.firmware_flash.active and not generator_blocks_flash)
        self.firmware_button.setEnabled(enabled)
        self.firmware_button.setToolTip(
            "Arrêtez le générateur avant de mettre à jour le firmware."
            if generator_blocks_flash else "")

    def _display_detected_firmware(self, firmware_info):
        self._detected_firmware_info = firmware_info
        result = compare_firmware(
            self.firmware_resources.manifest, firmware_info.version,
            PROTOCOL_VERSION, firmware_info.capabilities)
        version = ".".join(map(str, firmware_info.version))
        if result.status is FirmwareCompatibility.COMPATIBLE:
            self._firmware_mode = "current"
            self.firmware_status.setText(f"Firmware {version} — à jour")
        elif result.status is FirmwareCompatibility.OLDER:
            self._firmware_mode = "older"
            self.firmware_status.setText(
                f"Firmware {version} — mise à jour disponible")
        elif result.status is FirmwareCompatibility.NEWER:
            self._firmware_mode = "newer"
            self.firmware_status.setText(f"Firmware {version} — compatible")
        else:
            self._firmware_mode = "incompatible"
            self.firmware_status.setText("Firmware Physalix incompatible")
        self._update_firmware_offer()

    def request_firmware_installation(self):
        if not self.firmware_button.isEnabled():
            if (self._gbf_supported()
                    and not self.controller.generator_ready_for_flash):
                self.result_status.setText(
                    "Arrêtez le générateur avant de mettre à jour le firmware.")
            return
        port = self.port_combo.currentData()
        if not port or not self._confirm_firmware_installation(port):
            return
        self._flash_port = port
        self._flash_workflow_active = True
        self._reconnect_opened = False
        self._start_after_configuration = False
        self.firmware_status.setText("Installation du firmware…")
        self.controller.close()
        self._update_controls(self.controller.state)
        self.port_release_timer.start()

    def _confirm_firmware_installation(self, port: str) -> bool:
        text = self._firmware_confirmation_text(port)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Installer le firmware Physalix")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(text)
        install = dialog.addButton("Installer", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        return dialog.clickedButton() is install

    def _firmware_confirmation_text(self, port: str) -> str:
        target = self.firmware_resources.manifest.firmware_version
        if self._firmware_mode == "older" and self._detected_firmware_info is not None:
            current = ".".join(map(str, self._detected_firmware_info.version))
            return (f"Mettre à jour le firmware Physalix de {current} vers {target} "
                    f"sur {port} ?\n\nLe programme actuellement présent sera remplacé.")
        return (
            "L’installation du firmware Physalix remplacera le programme "
            "actuellement présent sur cette carte.\n\n"
            f"Port : {port}\n\n"
            "Vérifiez qu’il s’agit bien d’une Arduino Uno R3 / "
            "ATmega328P compatible.")

    def _start_flash_after_release(self):
        if not self._flash_workflow_active or not self._flash_port:
            return
        self.firmware_status.setText("Installation du firmware…")
        if not self.firmware_flash.start_flash(self._flash_port):
            # Le service émet normalement failed de façon synchrone.
            if self._flash_workflow_active:
                self._finish_flash_failure("Installation échouée")

    def _flash_upload_verified(self, manifest):
        if not self._flash_workflow_active:
            return
        self.firmware_status.setText("Redémarrage de l’Arduino…")
        self._reconnect_opened = False
        self.reconnect_timeout_timer.start()
        self.reconnect_retry_timer.start()

    def _attempt_flash_reconnect(self):
        if not self._flash_workflow_active or not self._flash_port:
            return
        if self.controller.state not in (AcquisitionState.DISCONNECTED,
                                         AcquisitionState.ERROR):
            return
        self.firmware_status.setText("Vérification du firmware…")
        if self.controller.open(self._flash_port):
            self._reconnect_opened = True
        else:
            self.reconnect_retry_timer.start()

    def _flash_reconnect_timed_out(self):
        if not self._flash_workflow_active:
            return
        self.reconnect_retry_timer.stop()
        self.controller.close()
        if self._reconnect_opened:
            message = "Arduino revenue mais firmware Physalix non détecté."
        else:
            message = "L’Arduino n’est pas revenue après l’installation."
        try:
            self.firmware_flash.fail_post_flash_verification(
                message, "Délai global de reconnexion dépassé.")
        except RuntimeError:
            self._finish_flash_failure(message)

    def _flash_succeeded(self, result):
        version = ".".join(map(str, result.actual_version))
        self._stop_flash_timers()
        self._flash_workflow_active = False
        self._firmware_mode = "current"
        self.firmware_status.setText(f"Firmware {version} — installé et prêt")
        self._update_controls(self.controller.state)

    def _flash_failed(self, failure):
        message = failure.user_message
        if failure.kind is FlashErrorKind.AVRDUDE_FAILED:
            message += " Vérifiez que l’Arduino est toujours connectée."
        self._finish_flash_failure(message)

    def _flash_process_settled(self):
        if not self._flash_workflow_active:
            self._update_controls(self.controller.state)

    def _finish_flash_failure(self, message: str):
        self._stop_flash_timers()
        self._flash_workflow_active = False
        self.firmware_status.setText(f"Installation échouée — {message}")
        self._firmware_mode = "absent" if self._detected_firmware_info is None else self._firmware_mode
        self._update_controls(self.controller.state)

    def _stop_flash_timers(self):
        self.port_release_timer.stop()
        self.reconnect_retry_timer.stop()
        self.reconnect_timeout_timer.stop()

    def generation_type(self) -> GenerationType | str:
        value = self.generation_type_combo.currentData()
        return value if value == CONTINUOUS_SQUARE_MODE else GenerationType(value)

    def _square_supported(self) -> bool:
        return (self._detected_firmware_info is not None
                and bool(self._detected_firmware_info.capabilities
                         & CAPABILITY_SQUARE_BURST))

    def _gbf_supported(self) -> bool:
        return (self._detected_firmware_info is not None
                and bool(self._detected_firmware_info.capabilities
                         & CAPABILITY_CONTINUOUS_SQUARE))

    def _generation_available(self) -> bool:
        mode = self.generation_type()
        if mode is GenerationType.STEP:
            return True
        if mode is GenerationType.SQUARE_BURST:
            return self._square_supported()
        return (self._gbf_supported()
                and self.controller.generator_state is GeneratorState.RUNNING)

    def _set_generation_field_visible(self, widget: QWidget, visible: bool):
        widget.setVisible(visible)
        field_label = self._generation_form.labelForField(widget)
        if field_label is not None:
            field_label.setVisible(visible)

    def _generation_type_changed(self, *args):
        self._sync_generation_ui()
        self._update_requested_values()
        self._update_controls(self.controller.state)

    def _sync_generation_ui(self):
        mode = self.generation_type()
        square = mode is GenerationType.SQUARE_BURST
        gbf = mode == CONTINUOUS_SQUARE_MODE
        for widget in self._step_generation_widgets:
            self._set_generation_field_visible(widget, not square and not gbf)
        for widget in self._square_generation_widgets:
            self._set_generation_field_visible(widget, square)
        for widget in self._gbf_generation_widgets:
            self._set_generation_field_visible(widget, gbf)
        self._set_generation_field_visible(self.output_pin, not gbf)
        if square and not self._square_supported():
            if self._detected_firmware_info is None:
                message = "Connectez un firmware Physalix compatible pour utiliser le mode carré."
            else:
                message = "Le mode carré nécessite le firmware Physalix 1.1.0 ou supérieur."
            self.square_requirement_label.setText(message)
            self.square_requirement_label.show()
        else:
            self.square_requirement_label.hide()
        if gbf and not self._gbf_supported():
            self.gbf_requirement_label.setText(
                "Le mode GBF continu nécessite un firmware Physalix compatible GBF.")
            self.gbf_requirement_label.show()
        else:
            self.gbf_requirement_label.hide()

    def requested_period_us(self) -> int:
        if self.generation_type() is GenerationType.SQUARE_BURST:
            return self.requested_square_plan().requested_sampling_period_us
        intervals = self.points_spin.value() - 1
        return max(1, round(self.duration_spin.value() * 1_000_000 / intervals))

    def requested_square_plan(self) -> SquareBurstPlan:
        return plan_square_burst(
            self.duration_spin.value(), self.points_spin.value(),
            self.square_periods_spin.value(), pin=self.output_pin.value(),
            analog_channel=self.channel_combo.currentData())

    def requested_config(self) -> AcquisitionConfig:
        if self.generation_type() is GenerationType.SQUARE_BURST:
            return self.requested_square_plan().config
        output_pin = (8 if self.generation_type() == CONTINUOUS_SQUARE_MODE
                      else self.output_pin.value())
        return AcquisitionConfig(
            self.requested_period_us(), self.points_spin.value(),
            self.channel_combo.currentData(),
            DigitalStepConfig(output_pin, False, True, 0),
        )

    def _update_requested_values(self, *args):
        period_us = self.requested_period_us()
        self.requested_te_label.setText(self._format_period(period_us))
        self.requested_fe_label.setText(self._format_frequency(period_us))
        if self.generation_type() is GenerationType.SQUARE_BURST:
            config = self.requested_square_plan().config
            self.square_requested_period_label.setText(
                self._format_seconds(applied_square_period_s(config)))
            self.square_requested_frequency_label.setText(
                self._format_hertz(applied_square_frequency_hz(config)))
        self._update_gbf_sampling_quality()

    @staticmethod
    def _sampling_quality(samples_per_period: float) -> str:
        if samples_per_period >= 100:
            return "excellent"
        if samples_per_period >= 50:
            return "très bon"
        if samples_per_period >= 20:
            return "correct"
        if samples_per_period >= 10:
            return "limité"
        return "faible"

    @staticmethod
    def _format_samples_per_period(value: float) -> str:
        rounded = round(value, 1)
        if rounded.is_integer():
            return str(int(rounded))
        return f"{rounded:.1f}".replace(".", ",")

    def _update_gbf_sampling_quality(self):
        plan = self._applied_generator_plan
        if plan is None or plan.applied_frequency_hz <= 0:
            self.gbf_sampling_quality_label.setText("—")
            return
        requested_period_us = self.requested_period_us()
        period_us = requested_period_us
        if (self._applied_acquisition_period_us is not None
                and self._configured_requested_period_us == requested_period_us):
            period_us = self._applied_acquisition_period_us
        acquisition_frequency_hz = 1_000_000 / period_us
        samples_per_period = acquisition_frequency_hz / plan.applied_frequency_hz
        value = self._format_samples_per_period(samples_per_period)
        quality = self._sampling_quality(samples_per_period)
        self.gbf_sampling_quality_label.setText(
            f"{value} pts/période — {quality}")

    def start_generator(self):
        if self.generation_type() != CONTINUOUS_SQUARE_MODE:
            return
        if not self._gbf_supported():
            self.result_status.setText(
                "Le mode GBF continu nécessite un firmware Physalix compatible GBF.")
            return
        if self.controller.generator_state is not GeneratorState.STOPPED:
            return
        try:
            config = ContinuousSquareConfig(self.gbf_frequency_spin.value())
            self._generator_start_pending = True
            self._applied_generator_plan = None
            self.gbf_applied_frequency_label.setText("En attente de configuration")
            self.gbf_applied_period_label.setText("En attente de configuration")
            self._update_gbf_sampling_quality()
            self.gbf_state_label.setText("Configuration…")
            self.result_status.setText("Configuration du générateur…")
            self.controller.configure_generator(config)
        except (AcquisitionError, ValueError) as error:
            self._generator_start_pending = False
            self.result_status.setText(str(error))
        self._update_controls(self.controller.state)

    def _generator_configured(self, plan: ContinuousSquarePlan):
        self._applied_generator_plan = plan
        self.gbf_applied_frequency_label.setText(
            self._format_hertz(plan.applied_frequency_hz))
        self.gbf_applied_period_label.setText(
            self._format_seconds(plan.applied_period_s))
        self._update_gbf_sampling_quality()
        if self._generator_start_pending:
            self.gbf_state_label.setText("Démarrage…")
            try:
                self.controller.start_generator()
            except (AcquisitionError, ValueError) as error:
                self._generator_start_pending = False
                self.result_status.setText(str(error))
        self._update_controls(self.controller.state)

    def stop_generator(self):
        try:
            if self.controller.stop_generator():
                self._generator_stop_pending = True
                self.gbf_state_label.setText("Arrêt…")
        except (AcquisitionError, ValueError) as error:
            self.result_status.setText(str(error))
        self._update_controls(self.controller.state)

    def _generator_state_changed(self, state: GeneratorState):
        labels = {
            GeneratorState.STOPPED: "Arrêté",
            GeneratorState.RUNNING: "En fonctionnement",
            GeneratorState.UNKNOWN: "État inconnu",
        }
        self.gbf_state_label.setText(labels[state])
        if state in (GeneratorState.STOPPED, GeneratorState.RUNNING):
            self._generator_start_pending = False
            self._generator_stop_pending = False
        if state is GeneratorState.RUNNING:
            if self.controller.state not in (
                    AcquisitionState.ARMED, AcquisitionState.ACQUIRING,
                    AcquisitionState.STOPPING):
                self.result_status.setText("Générateur en fonctionnement.")
        elif state is GeneratorState.STOPPED:
            if self.controller.state is AcquisitionState.ACQUIRING:
                self.result_status.setText(
                    "Acquisition en cours — générateur arrêté, E reste à 0 V.")
            elif self.controller.state is not AcquisitionState.STOPPING:
                self.result_status.setText("Générateur arrêté.")
            if self._disconnect_after_generator_stop:
                self._disconnect_after_generator_stop = False
                self.controller.close()
                return
        self._update_controls(self.controller.state)

    def _acquisition_armed(self, session_id):
        self.result_status.setText(
            "Acquisition armée — attente du prochain front montant…")
        self._update_controls(AcquisitionState.ARMED)

    def _acquisition_triggered(self, started):
        self.result_status.setText("Acquisition en cours — front montant reçu à t = 0.")
        self._update_controls(AcquisitionState.ACQUIRING)

    @staticmethod
    def _format_period(period_us: int) -> str:
        if period_us < 1000:
            return f"{period_us} µs"
        if period_us < 1_000_000:
            return f"{period_us / 1000:g} ms"
        return f"{period_us / 1_000_000:g} s"

    @staticmethod
    def _format_frequency(period_us: int) -> str:
        frequency = 1_000_000 / period_us
        return f"{frequency / 1000:g} kHz" if frequency >= 1000 else f"{frequency:g} Hz"

    @classmethod
    def _format_seconds(cls, seconds: float) -> str:
        return cls._format_period(round(seconds * 1_000_000))

    @staticmethod
    def _format_hertz(frequency: float) -> str:
        return f"{frequency / 1000:g} kHz" if frequency >= 1000 else f"{frequency:g} Hz"

    def start_acquisition(self):
        if self.controller.state not in (AcquisitionState.READY, AcquisitionState.CONFIGURED):
            return
        if not self._generation_available():
            if self.generation_type() == CONTINUOUS_SQUARE_MODE:
                self.result_status.setText(
                    "Démarrez le générateur GBF avant de lancer l’acquisition."
                    if self._gbf_supported() else
                    "Le mode GBF continu nécessite un firmware Physalix compatible GBF.")
            else:
                self.result_status.setText(
                    "Le mode carré nécessite le firmware Physalix 1.1.0 ou supérieur.")
            return
        self.times_s.clear()
        self.voltages_v.clear()
        self.generated_voltages_v.clear()
        self.curve.setData([], [])
        self.generated_curve.setData([], [])
        self.result_status.setText("Configuration de l'acquisition…")
        self._transferred = False
        self._transfer_columns = None
        self._session_uses_gbf = self.generation_type() == CONTINUOUS_SQUARE_MODE
        self._start_after_configuration = True
        self.controller.configure(self.requested_config())
        self._update_controls(self.controller.state)

    def _controller_ready(self, firmware_info):
        self._detected_firmware_info = firmware_info
        version = ".".join(map(str, firmware_info.version))
        self.connection_status.setText(f"Arduino détecté / Prêt — firmware {version}")
        if self._flash_workflow_active:
            self.reconnect_retry_timer.stop()
            self._display_detected_firmware(firmware_info)
            self.firmware_status.setText("Vérification du firmware…")
            self.firmware_flash.confirm_firmware(
                firmware_info.version, PROTOCOL_VERSION, firmware_info.capabilities)
        elif self.firmware_resources is not None:
            self._display_detected_firmware(firmware_info)
        self._generator_state_changed(self.controller.generator_state)
        self._generation_type_changed()

    def _configuration_accepted(self, config: AcquisitionConfig):
        self._configured_requested_period_us = self.requested_period_us()
        self._applied_acquisition_period_us = config.sampling_period_us
        parts = (
            f"{config.sample_count} pts",
            f"Te {self._format_period(config.sampling_period_us)}",
            f"Fe {self._format_frequency(config.sampling_period_us)}",
            f"durée {applied_duration_s(config):g} s",
        )
        if isinstance(config.generation, SquareBurstConfig):
            parts += (
                f"période {self._format_seconds(applied_square_period_s(config))}",
                f"fréquence {self._format_hertz(applied_square_frequency_hz(config))}",
            )
        self.applied_values_label.setText(" · ".join(parts))
        self._update_gbf_sampling_quality()
        if self._start_after_configuration:
            self._start_after_configuration = False
            self.controller.start()

    def _data_received(self, batch: DataBatch | GbfDataBatch):
        config = self.controller.config
        if config is None:
            return
        period_s = config.sampling_period_us / 1_000_000
        self.times_s.extend((batch.first_sample_index + offset) * period_s
                            for offset in range(len(batch.values)))
        self.voltages_v.extend(adc_to_volts(value) for value in batch.values)
        if isinstance(batch, GbfDataBatch):
            self.generated_voltages_v.extend(
                5.0 if high else 0.0 for high in batch.generated_high)
        else:
            self.generated_voltages_v[:] = generated_voltage_series(
                config, len(self.voltages_v))
        self._plot_dirty = True

    @staticmethod
    def _step_plot_data(times_s, values_v):
        if not times_s:
            return (), ()
        plot_times = [times_s[0]]
        plot_values = [values_v[0]]
        for index in range(1, len(times_s)):
            plot_times.extend((times_s[index], times_s[index]))
            plot_values.extend((values_v[index - 1], values_v[index]))
        return tuple(plot_times), tuple(plot_values)

    def refresh_plot(self):
        if self._plot_dirty:
            self.curve.setData(self.times_s, self.voltages_v)
            generated_times, generated_values = self._step_plot_data(
                self.times_s, self.generated_voltages_v)
            self.generated_curve.setData(generated_times, generated_values)
            self._plot_dirty = False

    def _acquisition_finished(self, result: AcquisitionResult):
        self._store_result(
            result.complete, result.reason or "Acquisition terminée.",
            result.generated_high)

    def _preserve_partial(self, reason: str):
        if self.controller.samples and not (
                self.results and len(self.results[-1].voltages_v) == len(self.controller.samples)
                and not self.results[-1].complete):
            self._store_result(False, reason, self.controller.generated_high)

    def _store_result(self, complete: bool, status: str,
                      generated_high: tuple[bool, ...] = ()):
        config = self.controller.config
        if config is None:
            return
        samples = tuple(self.controller.samples)
        if not samples:
            self._session_uses_gbf = False
            self.result_status.setText(status)
            self._update_controls(self.controller.state)
            return
        period_s = config.sampling_period_us / 1_000_000
        uses_gbf = self._session_uses_gbf or bool(generated_high)
        if uses_gbf:
            levels = tuple(generated_high or self.controller.generated_high)
            if len(levels) != len(samples):
                self.result_status.setText(
                    "Acquisition conservée, mais les séries Uc et E ne sont pas alignées.")
                return
            generated_voltages = tuple(5.0 if high else 0.0 for high in levels)
        else:
            generated_voltages = generated_voltage_series(config, len(samples))
        stored = AcquisitionPageResult(
            config.sampling_period_us, config.generation,
            tuple(index * period_s for index in range(len(samples))),
            tuple(adc_to_volts(value) for value in samples), generated_voltages,
            complete, status, self._applied_generator_plan if uses_gbf else None,
        )
        self.results.append(stored)
        self._transferred = False
        self._transfer_columns = None
        qualifier = "terminée" if complete else "incomplète — Données partielles"
        self.result_status.setText(
            f"Acquisition {qualifier} — {len(samples)} point(s) reçus. {status}")
        self.times_s[:] = stored.times_s
        self.voltages_v[:] = stored.voltages_v
        self.generated_voltages_v[:] = stored.generated_voltages_v
        self._session_uses_gbf = False
        self._plot_dirty = True
        self._update_controls(self.controller.state)

    @staticmethod
    def _numeric_text(value: float) -> str:
        """Produire une valeur finie, indépendante de la locale du poste."""
        if not math.isfinite(value):
            raise ValueError("L'acquisition contient une valeur non finie.")
        return format(value, ".15g")

    def transfer_result(self):
        """Ajouter le dernier résultat au document puis créer son graphique."""
        if self._transferred or not self.results or not self.results[-1].voltages_v:
            return None
        if self.data_tab is None or self.graph_workspace is None:
            return None
        result = self.results[-1]
        try:
            if self._transfer_columns is None:
                if not (len(result.times_s) == len(result.voltages_v)
                        == len(result.generated_voltages_v)):
                    raise ValueError("Les séries Temps, Uc et E ne sont pas alignées.")
                rows = [
                    [self._numeric_text(time_s), self._numeric_text(voltage),
                     self._numeric_text(generated_voltage)]
                    for time_s, voltage, generated_voltage in zip(
                        result.times_s, result.voltages_v, result.generated_voltages_v)
                ]
                self._transfer_columns = self.data_tab.append_measurements(
                    ["Temps", "Uc", "E"], ["s", "V", "V"], rows)
            time_column, uc_column, generated_column = self._transfer_columns
            graph = self.graph_workspace.add_data_graph_series(
                time_column, (uc_column, generated_column),
                title="Uc et E en fonction de Temps")
        except Exception as error:
            QMessageBox.warning(
                self, "Transfert impossible",
                f"Les données n'ont pas pu être entièrement transférées : {error}\n"
                "L'acquisition est conservée et le transfert peut être réessayé.")
            self._update_controls(self.controller.state)
            return None
        self._transferred = True
        qualifier = "partielles " if not result.complete else ""
        self.result_status.setText(
            f"Données {qualifier}transférées — {len(result.voltages_v)} point(s), graphique créé.")
        self._update_controls(self.controller.state)
        if self.show_graph is not None:
            self.show_graph()
        return self._transfer_columns, graph

    def _controller_error(self, message: str):
        self._start_after_configuration = False
        self._generator_start_pending = False
        self._generator_stop_pending = False
        protocol_incompatible = "protocole incompatible" in message.lower()
        if "déclenchement de l'acquisition annulé" in message.lower():
            self._session_uses_gbf = False
            self.result_status.setText(
                "Le déclenchement de l’acquisition a été annulé avant le front montant. "
                "Aucune donnée n’a été créée.")
            self._update_controls(self.controller.state)
            return
        if "délai expiré en attente de gen_" in message.lower():
            self.result_status.setText(
                "Le générateur ne répond plus ; son état est inconnu.")
            if self._disconnect_after_generator_stop:
                self._disconnect_after_generator_stop = False
                self.controller.close()
                return
            self._update_controls(self.controller.state)
            return
        if self._flash_workflow_active and self.reconnect_timeout_timer.isActive():
            if protocol_incompatible:
                self.controller.close()
                self.firmware_flash.fail_post_flash_verification(
                    "Le firmware installé utilise un protocole incompatible.", message)
                return
            self.controller.close()
            self.firmware_status.setText("Redémarrage de l’Arduino…")
            self.reconnect_retry_timer.start()
            self._update_controls(self.controller.state)
            return
        display_message = message
        if (message == SERIAL_RESOURCE_DISCONNECTED_MESSAGE
                and self.controller.config is not None and self.controller.samples):
            display_message += " Les données déjà acquises ont été conservées."
        self._preserve_partial(display_message)
        self.connection_status.setText(f"Erreur — {display_message}")
        self._update_controls(AcquisitionState.ERROR)
        if protocol_incompatible and self.firmware_resources is not None:
            self._firmware_mode = "incompatible"
            self.firmware_status.setText("Firmware Physalix incompatible")
            self._update_firmware_offer()

    def _update_controls(self, state: AcquisitionState):
        labels = {
            AcquisitionState.DISCONNECTED: "Déconnecté",
            AcquisitionState.WAITING_HANDSHAKE: "Connexion…",
            AcquisitionState.READY: "Arduino détecté / Prêt",
            AcquisitionState.CONFIGURED: "Arduino détecté / Prêt",
            AcquisitionState.ARMED: "Acquisition armée — attente du front montant",
            AcquisitionState.ACQUIRING: "Acquisition en cours",
            AcquisitionState.STOPPING: "Arrêt…",
            AcquisitionState.ERROR: "Erreur",
        }
        if state is not AcquisitionState.ERROR or not self.connection_status.text().startswith("Erreur —"):
            self.connection_status.setText(labels[state])
        if (not self._flash_workflow_active
                and state in (AcquisitionState.DISCONNECTED, AcquisitionState.ERROR)):
            self._detected_firmware_info = None
            if self.firmware_resources is not None:
                self._firmware_mode = "absent"
                if not self.firmware_status.text().startswith("Installation échouée"):
                    self.firmware_status.setText("Firmware non détecté")
        flash_active = self._flash_workflow_active or self.firmware_flash.active
        disconnected = state in (AcquisitionState.DISCONNECTED, AcquisitionState.ERROR)
        active = state in (AcquisitionState.ARMED, AcquisitionState.ACQUIRING,
                           AcquisitionState.STOPPING)
        generator_running = self.controller.generator_state is GeneratorState.RUNNING
        generator_pending = self._generator_start_pending or self._generator_stop_pending
        self.connect_button.setText("Connecter" if disconnected else "Déconnecter")
        self.connect_button.setEnabled(not flash_active)
        self.port_combo.setEnabled(disconnected and not flash_active)
        self.refresh_button.setEnabled(disconnected and not flash_active)
        self.start_button.setEnabled(
            state in (AcquisitionState.READY, AcquisitionState.CONFIGURED)
            and self._generation_available()
            and not self._start_after_configuration and not flash_active)
        self.stop_button.setEnabled(active and not flash_active)
        transferable = (not active and not self._start_after_configuration and
                        bool(self.results) and bool(self.results[-1].voltages_v) and
                        not self._transferred and self.data_tab is not None and
                        self.graph_workspace is not None and not flash_active)
        self.transfer_button.setEnabled(transferable)
        for widget in (self.duration_spin, self.points_spin, self.channel_combo,
                       self.output_pin, self.square_periods_spin):
            widget.setEnabled(not active and not self._start_after_configuration
                              and not flash_active)
        self.generation_type_combo.setEnabled(
            not active and not self._start_after_configuration and not flash_active
            and not generator_running and not generator_pending)
        self.gbf_frequency_spin.setEnabled(
            not active and not flash_active and not generator_running
            and not generator_pending)
        gbf_selected = self.generation_type() == CONTINUOUS_SQUARE_MODE
        self.gbf_start_button.setEnabled(
            gbf_selected and self._gbf_supported()
            and self.controller.generator_state is GeneratorState.STOPPED
            and not active and not flash_active and not generator_pending)
        self.gbf_stop_button.setEnabled(
            self._gbf_supported() and generator_running
            and not flash_active and not generator_pending)
        self._sync_generation_ui()
        self._update_firmware_offer()

    def shutdown(self):
        """Arrêter raisonnablement puis libérer le port sans bloquer la fermeture."""
        self.plot_timer.stop()
        self._stop_flash_timers()
        self.firmware_flash.shutdown()
        if self.controller.state in (AcquisitionState.ARMED, AcquisitionState.ACQUIRING,
                                     AcquisitionState.STOPPING):
            self.controller.stop()
            self._preserve_partial("Acquisition interrompue à la fermeture.")
        if self.controller.generator_state is GeneratorState.RUNNING:
            try:
                self.controller.request_generator_shutdown()
            except (AcquisitionError, ValueError):
                pass
        self.controller.close()
