"""Interface simple d'acquisition RC, indépendante du document Physalix."""

from __future__ import annotations

from dataclasses import dataclass
import math

import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtSerialPort import QSerialPortInfo
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from physalix.acquisition import (
    AcquisitionConfig, AcquisitionController, AcquisitionResult, AcquisitionState,
    DataBatch, DigitalStepConfig, SERIAL_RESOURCE_DISCONNECTED_MESSAGE,
)
from physalix.ui.components import label, page_header, panel, workspace_layout
from physalix.ui.theme import LIGHT


ADC_REFERENCE_V = 5.0
ADC_MAX_CODE = 1023
PLOT_REFRESH_MS = 40


@dataclass(frozen=True)
class AcquisitionPageResult:
    """Résultat conservé localement, sans écriture dans MeasurementsModel."""

    sampling_period_us: int
    times_s: tuple[float, ...]
    voltages_v: tuple[float, ...]
    complete: bool
    status: str


def adc_to_volts(code: int, reference_v: float = ADC_REFERENCE_V) -> float:
    """Convertir un code Uno 10 bits avec une référence explicite, non calibrée."""
    return code * reference_v / ADC_MAX_CODE


class AcquisitionTab(QWidget):
    """Piloter une acquisition et afficher une courbe temporaire Uc(t)."""

    def __init__(self, controller: AcquisitionController | None = None, data_tab=None,
                 graph_workspace=None, show_graph=None, parent=None):
        super().__init__(parent)
        self.controller = controller or AcquisitionController(self)
        self.data_tab = data_tab
        self.graph_workspace = graph_workspace
        self.show_graph = show_graph
        self.results: list[AcquisitionPageResult] = []
        self.times_s: list[float] = []
        self.voltages_v: list[float] = []
        self._start_after_configuration = False
        self._plot_dirty = False
        self._transferred = False
        self._transfer_columns = None
        self._build_ui()
        self._connect_controller()
        self.plot_timer = QTimer(self)
        self.plot_timer.setInterval(PLOT_REFRESH_MS)
        self.plot_timer.timeout.connect(self.refresh_plot)
        self.plot_timer.start()
        self.refresh_ports()
        self._update_requested_values()
        self._update_controls(self.controller.state)

    def _build_ui(self):
        layout = workspace_layout(self, 760, 610)
        layout.addWidget(page_header(
            "Acquisition", "Mesurer la tension Uc d'un circuit RC avec un Arduino Physalix."))

        connection, connection_layout = panel("Connexion", horizontal=True)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(260)
        self.refresh_button = QPushButton("Actualiser")
        self.connect_button = QPushButton("Connecter")
        self.connection_status = QLabel("Déconnecté")
        connection_layout.addWidget(label("Port série", "fieldLabel"))
        connection_layout.addWidget(self.port_combo, 1)
        connection_layout.addWidget(self.refresh_button)
        connection_layout.addWidget(self.connect_button)
        connection_layout.addWidget(self.connection_status)
        layout.addWidget(connection)

        settings, settings_layout = panel("Paramètres — Acquisition V1")
        grid = QGridLayout()
        input_form = QFormLayout()
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("A0", 0)
        self.quantity_label = QLabel("Uc")
        self.unit_label = QLabel("V")
        input_form.addRow("Voie", self.channel_combo)
        input_form.addRow("Grandeur", self.quantity_label)
        input_form.addRow("Unité", self.unit_label)
        grid.addLayout(input_form, 0, 0)

        acquisition_form = QFormLayout()
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
        acquisition_form.addRow("Durée", self.duration_spin)
        acquisition_form.addRow("Nombre de points", self.points_spin)
        acquisition_form.addRow("Te calculé", self.requested_te_label)
        acquisition_form.addRow("Fe calculée", self.requested_fe_label)
        grid.addLayout(acquisition_form, 0, 1)

        generation_form = QFormLayout()
        self.output_pin = QSpinBox()
        self.output_pin.setRange(2, 13)
        self.output_pin.setValue(8)
        generation_form.addRow("Sortie numérique", self.output_pin)
        generation_form.addRow("Niveau initial", QLabel("0 V"))
        generation_form.addRow("Niveau final", QLabel("5 V"))
        generation_form.addRow("Déclenchement", QLabel("Synchronisé avec l'acquisition"))
        grid.addLayout(generation_form, 0, 2)
        settings_layout.addLayout(grid)
        self.applied_values_label = label("Valeurs réellement appliquées : en attente.", "muted")
        settings_layout.addWidget(self.applied_values_label)
        layout.addWidget(settings)

        actions = QHBoxLayout()
        self.start_button = QPushButton("Démarrer")
        self.stop_button = QPushButton("Arrêter")
        self.transfer_button = QPushButton("Envoyer vers Données et Graphique")
        actions.addStretch(1)
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        actions.addWidget(self.transfer_button)
        layout.addLayout(actions)

        plot_panel, plot_layout = panel("Courbe temporaire — Uc(t)")
        self.plot = pg.PlotWidget(background=LIGHT.surface)
        self.plot.setLabel("bottom", "Temps", units="s")
        self.plot.setLabel("left", "Uc", units="V")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.curve = self.plot.plot([], [], pen=pg.mkPen(LIGHT.primary, width=2))
        plot_layout.addWidget(self.plot, 1)
        self.result_status = label("Aucune acquisition.", "muted")
        plot_layout.addWidget(self.result_status)
        layout.addWidget(plot_panel, 1)

        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.duration_spin.valueChanged.connect(self._update_requested_values)
        self.points_spin.valueChanged.connect(self._update_requested_values)
        self.start_button.clicked.connect(self.start_acquisition)
        self.stop_button.clicked.connect(self.controller.stop)
        self.transfer_button.clicked.connect(self.transfer_result)

    def _connect_controller(self):
        self.controller.state_changed.connect(self._update_controls)
        self.controller.ready.connect(self._controller_ready)
        self.controller.configuration_accepted.connect(self._configuration_accepted)
        self.controller.data_batch_received.connect(self._data_received)
        self.controller.acquisition_finished.connect(self._acquisition_finished)
        self.controller.error_occurred.connect(self._controller_error)

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
        if self.controller.state in (AcquisitionState.ACQUIRING, AcquisitionState.STOPPING):
            self.controller.stop()
            self._preserve_partial(reason)
        self._start_after_configuration = False
        self.controller.close()

    def requested_period_us(self) -> int:
        intervals = self.points_spin.value() - 1
        return max(1, round(self.duration_spin.value() * 1_000_000 / intervals))

    def requested_config(self) -> AcquisitionConfig:
        return AcquisitionConfig(
            self.requested_period_us(), self.points_spin.value(),
            self.channel_combo.currentData(),
            DigitalStepConfig(self.output_pin.value(), False, True, 0),
        )

    def _update_requested_values(self, *args):
        period_us = self.requested_period_us()
        self.requested_te_label.setText(self._format_period(period_us))
        self.requested_fe_label.setText(self._format_frequency(period_us))

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

    def start_acquisition(self):
        if self.controller.state not in (AcquisitionState.READY, AcquisitionState.CONFIGURED):
            return
        self.times_s.clear()
        self.voltages_v.clear()
        self.curve.setData([], [])
        self.result_status.setText("Configuration de l'acquisition…")
        self._transferred = False
        self._transfer_columns = None
        self._start_after_configuration = True
        self.controller.configure(self.requested_config())
        self._update_controls(self.controller.state)

    def _controller_ready(self, firmware_info):
        version = ".".join(map(str, firmware_info.version))
        self.connection_status.setText(f"Arduino détecté / Prêt — firmware {version}")

    def _configuration_accepted(self, config: AcquisitionConfig):
        duration_s = (config.sample_count - 1) * config.sampling_period_us / 1_000_000
        self.applied_values_label.setText(
            f"Valeurs réellement appliquées : Te = {self._format_period(config.sampling_period_us)}, "
            f"Fe = {self._format_frequency(config.sampling_period_us)}, durée = {duration_s:g} s.")
        if self._start_after_configuration:
            self._start_after_configuration = False
            self.controller.start()

    def _data_received(self, batch: DataBatch):
        config = self.controller.config
        if config is None:
            return
        period_s = config.sampling_period_us / 1_000_000
        self.times_s.extend((batch.first_sample_index + offset) * period_s
                            for offset in range(len(batch.values)))
        self.voltages_v.extend(adc_to_volts(value) for value in batch.values)
        self._plot_dirty = True

    def refresh_plot(self):
        if self._plot_dirty:
            self.curve.setData(self.times_s, self.voltages_v)
            self._plot_dirty = False

    def _acquisition_finished(self, result: AcquisitionResult):
        self._store_result(result.complete, result.reason or "Acquisition terminée.")

    def _preserve_partial(self, reason: str):
        if self.controller.samples and not (
                self.results and len(self.results[-1].voltages_v) == len(self.controller.samples)
                and not self.results[-1].complete):
            self._store_result(False, reason)

    def _store_result(self, complete: bool, status: str):
        config = self.controller.config
        if config is None:
            return
        samples = tuple(self.controller.samples)
        period_s = config.sampling_period_us / 1_000_000
        stored = AcquisitionPageResult(
            config.sampling_period_us,
            tuple(index * period_s for index in range(len(samples))),
            tuple(adc_to_volts(value) for value in samples), complete, status,
        )
        self.results.append(stored)
        self._transferred = False
        self._transfer_columns = None
        qualifier = "terminée" if complete else "incomplète — Données partielles"
        self.result_status.setText(
            f"Acquisition {qualifier} — {len(samples)} point(s) reçus. {status}")
        self.times_s[:] = stored.times_s
        self.voltages_v[:] = stored.voltages_v
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
                period_s = result.sampling_period_us / 1_000_000
                rows = [[self._numeric_text(index * period_s), self._numeric_text(voltage)]
                        for index, voltage in enumerate(result.voltages_v)]
                self._transfer_columns = self.data_tab.append_measurements(
                    ["Temps", "Uc"], ["s", "V"], rows)
            graph = self.graph_workspace.add_data_graph(
                *self._transfer_columns, title="Uc en fonction de Temps")
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
        display_message = message
        if (message == SERIAL_RESOURCE_DISCONNECTED_MESSAGE
                and self.controller.config is not None and self.controller.samples):
            display_message += " Les données déjà acquises ont été conservées."
        self._preserve_partial(display_message)
        self.connection_status.setText(f"Erreur — {display_message}")
        self._update_controls(AcquisitionState.ERROR)

    def _update_controls(self, state: AcquisitionState):
        labels = {
            AcquisitionState.DISCONNECTED: "Déconnecté",
            AcquisitionState.WAITING_HANDSHAKE: "Connexion…",
            AcquisitionState.READY: "Arduino détecté / Prêt",
            AcquisitionState.CONFIGURED: "Arduino détecté / Prêt",
            AcquisitionState.ACQUIRING: "Acquisition en cours",
            AcquisitionState.STOPPING: "Arrêt…",
            AcquisitionState.ERROR: "Erreur",
        }
        if state is not AcquisitionState.ERROR or not self.connection_status.text().startswith("Erreur —"):
            self.connection_status.setText(labels[state])
        disconnected = state in (AcquisitionState.DISCONNECTED, AcquisitionState.ERROR)
        active = state in (AcquisitionState.ACQUIRING, AcquisitionState.STOPPING)
        self.connect_button.setText("Connecter" if disconnected else "Déconnecter")
        self.port_combo.setEnabled(disconnected)
        self.refresh_button.setEnabled(disconnected)
        self.start_button.setEnabled(state in (AcquisitionState.READY, AcquisitionState.CONFIGURED)
                                     and not self._start_after_configuration)
        self.stop_button.setEnabled(active)
        transferable = (not active and not self._start_after_configuration and
                        bool(self.results) and bool(self.results[-1].voltages_v) and
                        not self._transferred and self.data_tab is not None and
                        self.graph_workspace is not None)
        self.transfer_button.setEnabled(transferable)
        for widget in (self.duration_spin, self.points_spin, self.channel_combo, self.output_pin):
            widget.setEnabled(not active and not self._start_after_configuration)

    def shutdown(self):
        """Arrêter raisonnablement puis libérer le port sans bloquer la fermeture."""
        self.plot_timer.stop()
        if self.controller.state in (AcquisitionState.ACQUIRING, AcquisitionState.STOPPING):
            self.controller.stop()
            self._preserve_partial("Acquisition interrompue à la fermeture.")
        self.controller.close()
