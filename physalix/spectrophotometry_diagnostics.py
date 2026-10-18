"""Journal persistant des expériences de cinétique spectrophotométrique."""

from __future__ import annotations

import csv
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Callable
import zipfile

from PySide6.QtCore import QStandardPaths

from physalix.spectrophotometry import AbsorbanceSpectrum, SpectroCalibration
from physalix.spectrophotometry_kinetics import KineticExperiment, KineticPoint
from physalix.spectrophotometry_protocol import SpectroConfig, SpectroFirmwareInfo


DIAGNOSTIC_SCHEMA_VERSION = 1
DIAGNOSTIC_DIRECTORY = Path("diagnostics") / "spectrophotometry" / "kinetics"
DISCONTINUITY_MINIMUM_BANDS = 3
DISCONTINUITY_ABSORBANCE_THRESHOLD = 0.08

_BANDS = tuple(f"f{index}" for index in range(1, 9))
MEASUREMENT_COLUMNS = (
    "index",
    "elapsed_seconds",
    "pc_timestamp",
    "command_pc_timestamp",
    "arduino_timestamp_ms",
    "command_response_latency_seconds",
    "request_id",
    "config_id",
    "calibration_id",
    "session_id",
    "atime",
    "astep",
    "gain_code",
    "gain_name",
    "led_pwm_command",
    *tuple(f"raw_{name}" for name in _BANDS),
    "raw_clear",
    "raw_nir",
    "saturation_flags",
    *tuple(f"absorbance_{name}" for name in _BANDS),
    *tuple(f"valid_{name}" for name in _BANDS),
    "valid_clear",
    "valid_nir",
    *tuple(f"saturated_{name}" for name in _BANDS),
    "saturated_clear",
    "saturated_nir",
    *tuple(f"invalidities_{name}" for name in _BANDS),
    *tuple(f"dark_{name}" for name in _BANDS),
    "dark_clear",
    "dark_nir",
    "dark_saturation_flags",
    *tuple(f"white_{name}" for name in _BANDS),
    "white_clear",
    "white_nir",
    "white_saturation_flags",
    "anomalies",
)


def diagnostics_root() -> Path:
    """Retourner le dossier local Physalix prévu par Qt, hors du dépôt."""

    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if not location:
        raise OSError("Qt ne fournit aucun dossier de données locales pour Physalyx.")
    return Path(location) / DIAGNOSTIC_DIRECTORY


def _iso_now(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None:
        value = value.astimezone()
    return value.isoformat(timespec="milliseconds")


def _config_dict(config: SpectroConfig) -> dict:
    return {
        "config_id": config.config_id,
        "atime": config.atime,
        "astep": config.astep,
        "gain_code": int(config.gain),
        "gain_name": config.gain.name,
        "led_pwm_command": config.led_pwm,
    }


def _raw_measurement_dict(measurement) -> dict:
    data = measurement.data
    return {
        "request_id": data.request_id,
        "config_id": data.config_id,
        "arduino_timestamp_ms": data.timestamp_ms,
        "bands": list(data.bands),
        "clear": data.clear,
        "nir": data.nir,
        "saturation_flags": data.saturation_flags,
        "session_id": measurement.session_id,
        "applied_config": _config_dict(measurement.applied_config),
    }


def _firmware_dict(firmware: SpectroFirmwareInfo | None) -> dict | None:
    if firmware is None:
        return None
    return {
        "version": ".".join(map(str, firmware.version)),
        "sensor_type": firmware.sensor_type.name,
        "sensor_type_code": int(firmware.sensor_type),
        "capabilities": firmware.capabilities,
    }


class KineticDiagnosticJournal:
    """Écrire trois fichiers progressifs sans propager les erreurs d'E/S."""

    def __init__(
        self,
        experiment: KineticExperiment,
        *,
        firmware: SpectroFirmwareInfo | None = None,
        base_directory: str | Path | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ):
        if not isinstance(experiment, KineticExperiment):
            raise TypeError("experiment doit être un KineticExperiment.")
        self.experiment = experiment
        self._clock = wall_clock or (lambda: datetime.now().astimezone())
        self._pending_commands: dict[int, tuple[float, str]] = {}
        self._last_spectrum: AbsorbanceSpectrum | None = None
        self.errors: list[str] = []
        self.finished = False

        root = Path(base_directory) if base_directory is not None else diagnostics_root()
        stamp = self._clock().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        self.directory = root / f"{stamp}_{experiment.identifier}"
        self.metadata_path = self.directory / "metadata.json"
        self.measurements_path = self.directory / "measurements.csv"
        self.events_path = self.directory / "events.jsonl"
        self.directory.mkdir(parents=True, exist_ok=False)

        self.metadata = self._initial_metadata(firmware)
        self._write_metadata()
        with self.measurements_path.open("x", encoding="utf-8", newline="") as stream:
            csv.DictWriter(stream, fieldnames=MEASUREMENT_COLUMNS).writeheader()
        self.events_path.touch(exist_ok=False)
        self.record_event(
            "experiment_started",
            experiment_id=experiment.identifier,
            duration_seconds=experiment.duration_seconds,
            interval_seconds=experiment.interval_seconds,
        )

    def _initial_metadata(self, firmware: SpectroFirmwareInfo | None) -> dict:
        calibration = self.experiment.calibration
        return {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "experiment_id": self.experiment.identifier,
            "status": "in_progress",
            "started_at": _iso_now(self._clock),
            "finished_at": None,
            "duration_seconds": self.experiment.duration_seconds,
            "interval_seconds": self.experiment.interval_seconds,
            "measurement_count": 0,
            "stop_reason": None,
            "firmware": _firmware_dict(firmware),
            "configuration": _config_dict(calibration.applied_config),
            "calibration": {
                "calibration_id": calibration.reference_id,
                "dark": _raw_measurement_dict(calibration.dark),
                "white": _raw_measurement_dict(calibration.white),
            },
            "availability": {
                "led_pwm": "commande appliquée, pas une mesure de puissance lumineuse",
                "measured_light_power": "non disponible dans le protocole",
                "sensor_temperature": "non disponible dans le protocole",
                "supply_voltage": "non disponible dans le protocole",
            },
            "discontinuity_event_rule": {
                "minimum_simultaneous_valid_bands": DISCONTINUITY_MINIMUM_BANDS,
                "minimum_absolute_absorbance_delta": DISCONTINUITY_ABSORBANCE_THRESHOLD,
                "effect": "journalisation seulement; aucune correction des mesures",
            },
            "logging_errors": [],
        }

    def _remember_error(self, operation: str, error: OSError) -> None:
        self.errors.append(f"{operation}: {error}")

    def _write_metadata(self) -> bool:
        temporary = self.metadata_path.with_suffix(".json.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(self.metadata, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, self.metadata_path)
            return True
        except OSError as error:
            self._remember_error("metadata", error)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def record_event(self, event_type: str, **details) -> bool:
        event = {
            "timestamp": _iso_now(self._clock),
            "type": event_type,
            **details,
        }
        try:
            with self.events_path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
                stream.write("\n")
            return True
        except OSError as error:
            self._remember_error("events", error)
            return False

    def record_measurement_command(
        self, request_id: int, monotonic_time: float, *, sequence: int
    ) -> bool:
        timestamp = _iso_now(self._clock)
        self._pending_commands[request_id] = (float(monotonic_time), timestamp)
        return self.record_event(
            "measurement_command",
            experiment_id=self.experiment.identifier,
            sequence=sequence,
            request_id=request_id,
            config_id=self.experiment.calibration.applied_config.config_id,
        )

    def record_measurement(
        self,
        point: KineticPoint,
        *,
        completed_monotonic: float,
        pc_timestamp: str | None = None,
    ) -> bool:
        spectrum = point.spectrum
        measurement = spectrum.measurement
        data = measurement.data
        config = measurement.applied_config
        calibration = spectrum.calibration
        command = self._pending_commands.pop(data.request_id, None)
        latency = None if command is None else float(completed_monotonic) - command[0]
        command_timestamp = None if command is None else command[1]
        received_timestamp = pc_timestamp or _iso_now(self._clock)
        saturated = tuple(data.is_saturated(index) for index in range(10))
        anomalies = self._measurement_anomalies(spectrum, saturated)

        row = {column: "" for column in MEASUREMENT_COLUMNS}
        row.update(
            {
                "index": point.sequence,
                "elapsed_seconds": point.elapsed_seconds,
                "pc_timestamp": received_timestamp,
                "command_pc_timestamp": command_timestamp,
                "arduino_timestamp_ms": data.timestamp_ms,
                "command_response_latency_seconds": latency,
                "request_id": data.request_id,
                "config_id": data.config_id,
                "calibration_id": spectrum.calibration_reference_id,
                "session_id": measurement.session_id,
                "atime": config.atime,
                "astep": config.astep,
                "gain_code": int(config.gain),
                "gain_name": config.gain.name,
                "led_pwm_command": config.led_pwm,
                "raw_clear": data.clear,
                "raw_nir": data.nir,
                "saturation_flags": data.saturation_flags,
                "valid_clear": not saturated[8],
                "valid_nir": not saturated[9],
                "saturated_clear": saturated[8],
                "saturated_nir": saturated[9],
                "anomalies": json.dumps(anomalies, ensure_ascii=False, separators=(",", ":")),
            }
        )
        for index, name in enumerate(_BANDS):
            band = spectrum.bands[index]
            row[f"raw_{name}"] = data.bands[index]
            row[f"absorbance_{name}"] = band.absorbance
            row[f"valid_{name}"] = band.is_valid
            row[f"saturated_{name}"] = saturated[index]
            row[f"invalidities_{name}"] = "|".join(
                invalidity.value for invalidity in band.invalidities
            )
        if calibration is not None:
            dark = calibration.dark.data
            white = calibration.white.data
            for index, name in enumerate(_BANDS):
                row[f"dark_{name}"] = dark.bands[index]
                row[f"white_{name}"] = white.bands[index]
            row.update(
                {
                    "dark_clear": dark.clear,
                    "dark_nir": dark.nir,
                    "dark_saturation_flags": dark.saturation_flags,
                    "white_clear": white.clear,
                    "white_nir": white.nir,
                    "white_saturation_flags": white.saturation_flags,
                }
            )

        written = False
        try:
            with self.measurements_path.open("a", encoding="utf-8", newline="") as stream:
                csv.DictWriter(stream, fieldnames=MEASUREMENT_COLUMNS).writerow(row)
            written = True
        except OSError as error:
            self._remember_error("measurements", error)

        self.record_event(
            "measurement_response",
            experiment_id=self.experiment.identifier,
            sequence=point.sequence,
            request_id=data.request_id,
            config_id=data.config_id,
            latency_seconds=latency,
            valid_band_count=sum(band.is_valid for band in spectrum.bands),
            saturation_flags=data.saturation_flags,
        )
        if data.saturation_flags:
            self.record_event(
                "saturation_detected",
                sequence=point.sequence,
                request_id=data.request_id,
                saturation_flags=data.saturation_flags,
                channels=[
                    name.upper() if name.startswith("f") else name.capitalize()
                    for name, state in zip((*_BANDS, "clear", "nir"), saturated)
                    if state
                ],
            )
        invalid = {
            f"F{index + 1}": [item.value for item in band.invalidities]
            for index, band in enumerate(spectrum.bands)
            if not band.is_valid
        }
        if invalid:
            self.record_event(
                "invalid_measurement",
                sequence=point.sequence,
                request_id=data.request_id,
                invalid_bands=invalid,
            )
        self._record_discontinuity(point)
        self._last_spectrum = spectrum
        self.metadata["measurement_count"] = point.sequence
        self.metadata["logging_errors"] = list(self.errors)
        self._write_metadata()
        return written

    def _measurement_anomalies(self, spectrum, saturated) -> list[str]:
        anomalies = []
        if any(saturated):
            anomalies.append("saturation")
        if any(not band.is_valid for band in spectrum.bands):
            anomalies.append("invalid_absorbance")
        return anomalies

    def _record_discontinuity(self, point: KineticPoint) -> None:
        previous = self._last_spectrum
        if previous is None:
            return
        deltas = {}
        for index, (before, after) in enumerate(zip(previous.bands, point.spectrum.bands)):
            if (
                before.is_valid
                and after.is_valid
                and before.absorbance is not None
                and after.absorbance is not None
            ):
                delta = after.absorbance - before.absorbance
                if abs(delta) >= DISCONTINUITY_ABSORBANCE_THRESHOLD:
                    deltas[f"F{index + 1}"] = delta
        positive = sum(value > 0 for value in deltas.values())
        negative = sum(value < 0 for value in deltas.values())
        if max(positive, negative) < DISCONTINUITY_MINIMUM_BANDS:
            return
        before_data = previous.measurement.data
        after_data = point.spectrum.measurement.data
        self.record_event(
            "simultaneous_absorbance_discontinuity",
            sequence=point.sequence,
            request_id=after_data.request_id,
            absorbance_deltas=deltas,
            raw_band_deltas={
                f"F{index + 1}": after_data.bands[index] - before_data.bands[index]
                for index in range(8)
            },
            clear_delta=after_data.clear - before_data.clear,
            nir_delta=after_data.nir - before_data.nir,
            interpretation="Aucune cause matérielle ou logicielle attribuée.",
        )

    def finish(self, reason: str, *, status: str = "completed") -> bool:
        if self.finished:
            return not self.errors
        self.finished = True
        self.metadata["status"] = status
        self.metadata["finished_at"] = _iso_now(self._clock)
        self.metadata["measurement_count"] = len(self.experiment.points)
        self.metadata["stop_reason"] = reason
        self.metadata["logging_errors"] = list(self.errors)
        self.record_event(
            "experiment_finished",
            experiment_id=self.experiment.identifier,
            status=status,
            reason=reason,
            measurement_count=len(self.experiment.points),
        )
        self.metadata["logging_errors"] = list(self.errors)
        return self._write_metadata()

    def export_zip(self, destination: str | Path) -> Path:
        target = Path(destination)
        if target.suffix.lower() != ".zip":
            target = target.with_suffix(".zip")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(
                target, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for path in (
                    self.metadata_path,
                    self.measurements_path,
                    self.events_path,
                ):
                    archive.write(path, arcname=path.name)
        except (OSError, zipfile.BadZipFile) as error:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            raise OSError(f"Impossible de créer l'archive diagnostic : {error}") from error
        return target
