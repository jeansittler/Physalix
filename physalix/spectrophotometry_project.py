"""État portable des expériences de spectrophotométrie.

Les références historiques servent uniquement à relire les résultats. Elles ne
deviennent jamais la calibration matérielle active du contrôleur série.
"""

from __future__ import annotations

import math
import re

from physalix.spectrophotometry import (
    AbsorbanceBandResult,
    AbsorbanceSpectrum,
    BandInvalidity,
    MeasurementKind,
    SpectroCalibration,
    SpectroMeasurement,
    VISIBLE_WAVELENGTHS_NM,
    acquisition_parameters_match,
)
from physalix.spectrophotometry_beer_lambert import (
    BeerLambertStandard,
    CONCENTRATION_UNITS,
)
from physalix.spectrophotometry_kinetics import (
    KINETIC_INTERVALS_SECONDS,
    KineticExperiment,
    KineticPoint,
)
from physalix.spectrophotometry_protocol import (
    AS7341Gain,
    SpectroConfig,
    SpectroData,
    SpectroIllumination,
    encode_config,
    encode_data,
)


SPECTRO_PROJECT_VERSION = 1
MAX_SPECTRA = 1_000
MAX_STANDARDS = 10_000
MAX_EXPERIMENTS = 100
MAX_KINETIC_POINTS = 100_000


def _mapping(value, label):
    if type(value) is not dict:
        raise ValueError(f"{label} doit être un objet.")
    return value


def _sequence(value, label, maximum):
    if type(value) is not list or len(value) > maximum:
        raise ValueError(f"{label} est invalide ou trop volumineux.")
    return value


def _integer(value, label, minimum=None, maximum=None):
    if type(value) is not int or (minimum is not None and value < minimum) or (
        maximum is not None and value > maximum
    ):
        raise ValueError(f"{label} est invalide.")
    return value


def _number(value, label, *, optional=False):
    if optional and value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label} doit être un nombre fini.")
    return float(value)


def _text(value, label, *, optional=False, maximum=2_000):
    if optional and value is None:
        return None
    if type(value) is not str or not value or len(value) > maximum:
        raise ValueError(f"{label} est invalide.")
    return value


def _config_state(config):
    return {
        "config_id": config.config_id,
        "atime": config.atime,
        "astep": config.astep,
        "gain": int(config.gain),
        "led_pwm": config.led_pwm,
    }


def _config_from_state(state):
    state = _mapping(state, "Configuration spectro")
    try:
        config = SpectroConfig(
            _integer(state["config_id"], "config_id", 0, 0xFFFF),
            _integer(state["atime"], "ATIME", 0, 0xFF),
            _integer(state["astep"], "ASTEP", 0, 0xFFFF),
            AS7341Gain(_integer(state["gain"], "Gain", 0, 10)),
            _integer(state["led_pwm"], "PWM", 0, 0xFF),
        )
    except KeyError as error:
        raise ValueError("Configuration spectro incomplète.") from error
    encode_config(config)
    return config


def _measurement_state(measurement):
    data = measurement.data
    return {
        "kind": measurement.kind.value,
        "session_id": measurement.session_id,
        "config": _config_state(measurement.applied_config),
        "data": {
            "request_id": data.request_id,
            "config_id": data.config_id,
            "illumination": int(data.illumination),
            "bands": list(data.bands),
            "clear": data.clear,
            "nir": data.nir,
            "saturation_flags": data.saturation_flags,
            "timestamp_ms": data.timestamp_ms,
        },
    }


def _measurement_from_state(state):
    state = _mapping(state, "Mesure spectro")
    try:
        config = _config_from_state(state["config"])
        raw = _mapping(state["data"], "Données brutes spectro")
        bands = tuple(
            _integer(value, f"F{index}", 0, 0xFFFF)
            for index, value in enumerate(
                _sequence(raw["bands"], "Bandes spectrales", 8), start=1
            )
        )
        if len(bands) != 8:
            raise ValueError("Une mesure spectro doit contenir huit bandes.")
        data = SpectroData(
            _integer(raw["request_id"], "request_id", 0, 0xFFFF),
            _integer(raw["config_id"], "config_id", 0, 0xFFFF),
            SpectroIllumination(
                _integer(raw["illumination"], "Illumination", 0, 1)
            ),
            bands,
            _integer(raw["clear"], "Clear", 0, 0xFFFF),
            _integer(raw["nir"], "NIR", 0, 0xFFFF),
            _integer(raw["saturation_flags"], "Saturations", 0, 0x03FF),
            _integer(raw["timestamp_ms"], "Horodatage Arduino", 0, 0xFFFFFFFF),
        )
        kind = MeasurementKind(_text(state["kind"], "Type de mesure"))
        session_id = _text(state["session_id"], "Session spectro")
    except (KeyError, ValueError) as error:
        raise ValueError(f"Mesure spectro invalide : {error}") from error
    encode_data(data)
    return SpectroMeasurement(kind, data, config, session_id)


def _calibration_state(calibration):
    return {
        "reference_id": calibration.reference_id,
        "dark": _measurement_state(calibration.dark),
        "white": _measurement_state(calibration.white),
    }


def _calibration_from_state(state):
    state = _mapping(state, "Calibration historique")
    try:
        return SpectroCalibration(
            _text(state["reference_id"], "Identifiant de calibration"),
            _measurement_from_state(state["dark"]),
            _measurement_from_state(state["white"]),
        )
    except KeyError as error:
        raise ValueError("Calibration historique incomplète.") from error


def _band_state(band):
    return {
        "wavelength_nm": band.wavelength_nm,
        "sample_intensity": band.sample_intensity,
        "dark_intensity": band.dark_intensity,
        "white_intensity": band.white_intensity,
        "transmission": band.transmission,
        "absorbance": band.absorbance,
        "invalidities": [item.value for item in band.invalidities],
    }


def _band_from_state(state, index, measurement, calibration):
    state = _mapping(state, "Résultat de bande")
    wavelength = VISIBLE_WAVELENGTHS_NM[index]
    try:
        saved_wavelength = _integer(state["wavelength_nm"], "Longueur d'onde")
        sample = _integer(state["sample_intensity"], "Intensité échantillon", 0, 0xFFFF)
        dark = state["dark_intensity"]
        white = state["white_intensity"]
        dark = None if dark is None else _integer(dark, "Intensité noire", 0, 0xFFFF)
        white = None if white is None else _integer(white, "Intensité blanche", 0, 0xFFFF)
        transmission = _number(state["transmission"], "Transmission", optional=True)
        absorbance = _number(state["absorbance"], "Absorbance", optional=True)
        invalidities = tuple(
            BandInvalidity(_text(value, "Motif d'invalidité"))
            for value in _sequence(state["invalidities"], "Invalidités", 16)
        )
    except (KeyError, ValueError) as error:
        raise ValueError(f"Résultat spectral invalide : {error}") from error
    if saved_wavelength != wavelength or sample != measurement.bands[index]:
        raise ValueError("Le résultat spectral ne correspond pas à la mesure brute.")
    expected_dark = calibration.dark.bands[index] if calibration else None
    expected_white = calibration.white.bands[index] if calibration else None
    if dark != expected_dark or white != expected_white:
        raise ValueError("Les références historiques d'une bande sont incohérentes.")
    if invalidities and (transmission is not None or absorbance is not None):
        raise ValueError("Une bande invalide ne peut pas contenir un résultat numérique.")
    if not invalidities and (transmission is None or absorbance is None):
        raise ValueError("Une bande valide doit contenir transmission et absorbance.")
    return AbsorbanceBandResult(
        wavelength, sample, dark, white, transmission, absorbance, invalidities
    )


def _spectrum_state(spectrum, register_calibration):
    reference_id = None
    if spectrum.calibration is not None:
        reference_id = spectrum.calibration.reference_id
        register_calibration(spectrum.calibration)
    return {
        "calibration_reference_id": reference_id,
        "measurement": _measurement_state(spectrum.measurement),
        "bands": [_band_state(band) for band in spectrum.bands],
    }


def _spectrum_from_state(state, calibrations):
    state = _mapping(state, "Spectre d'absorbance")
    try:
        reference_id = state["calibration_reference_id"]
        if reference_id is not None:
            reference_id = _text(reference_id, "Référence du spectre")
            if reference_id not in calibrations:
                raise ValueError("Référence historique introuvable.")
        calibration = calibrations.get(reference_id)
        measurement = _measurement_from_state(state["measurement"])
        raw_bands = _sequence(state["bands"], "Résultats spectraux", 8)
    except KeyError as error:
        raise ValueError("Spectre d'absorbance incomplet.") from error
    if len(raw_bands) != 8:
        raise ValueError("Un spectre doit contenir huit résultats de bande.")
    if measurement.kind is not MeasurementKind.SAMPLE:
        raise ValueError("Un spectre restauré doit provenir d'un échantillon.")
    if calibration is not None and (
        measurement.session_id != calibration.session_id
        or not acquisition_parameters_match(
            measurement.applied_config, calibration.applied_config
        )
    ):
        raise ValueError("La provenance du spectre est incompatible avec sa référence.")
    bands = tuple(
        _band_from_state(value, index, measurement, calibration)
        for index, value in enumerate(raw_bands)
    )
    return AbsorbanceSpectrum(measurement, calibration, bands)


def _experiment_state(experiment, spectrum_state, register_calibration):
    register_calibration(experiment.calibration)
    return {
        "identifier": experiment.identifier,
        "calibration_reference_id": experiment.calibration.reference_id,
        "duration_seconds": experiment.duration_seconds,
        "interval_seconds": experiment.interval_seconds,
        "stopped_reason": experiment.stopped_reason,
        "points": [
            {
                "sequence": point.sequence,
                "elapsed_seconds": point.elapsed_seconds,
                "spectrum": spectrum_state(point.spectrum),
            }
            for point in experiment.points
        ],
    }


def _experiment_from_state(state, calibrations):
    state = _mapping(state, "Expérience cinétique")
    try:
        identifier = _text(state["identifier"], "Identifiant cinétique")
        reference_id = _text(
            state["calibration_reference_id"], "Référence cinétique"
        )
        calibration = calibrations[reference_id]
        duration = _integer(state["duration_seconds"], "Durée cinétique", 60, 1800)
        interval = _integer(state["interval_seconds"], "Intervalle cinétique")
        if interval not in KINETIC_INTERVALS_SECONDS:
            raise ValueError("Intervalle cinétique non pris en charge.")
        reason = _text(
            state.get("stopped_reason"), "Motif d'arrêt", optional=True
        )
        raw_points = _sequence(
            state["points"], "Points cinétiques", MAX_KINETIC_POINTS
        )
    except KeyError as error:
        raise ValueError("Expérience cinétique incomplète.") from error
    points = []
    previous_elapsed = 0.0
    for index, raw in enumerate(raw_points, start=1):
        raw = _mapping(raw, "Point cinétique")
        try:
            sequence = _integer(raw["sequence"], "Ordre cinétique", 1)
            elapsed = _number(raw["elapsed_seconds"], "Temps cinétique")
            spectrum = _spectrum_from_state(raw["spectrum"], calibrations)
        except KeyError as error:
            raise ValueError("Point cinétique incomplet.") from error
        if sequence != index or elapsed <= previous_elapsed:
            raise ValueError("L'ordre ou les temps cinétiques sont incohérents.")
        if elapsed > duration or spectrum.calibration is not calibration:
            raise ValueError("Un point cinétique n'appartient pas à son expérience.")
        points.append(KineticPoint(sequence, elapsed, spectrum))
        previous_elapsed = elapsed
    return KineticExperiment(
        identifier, calibration, 0.0, duration, interval, points, reason
    )


def _signature_state(signature, columns, kind):
    if kind == "beer":
        reference_id, unit, wavelength, points = signature
        return {
            "reference_id": reference_id,
            "unit": unit,
            "wavelength_nm": wavelength,
            "points": [list(point) for point in points],
            "columns": list(columns),
        }
    identifier, band_index, values = signature
    return {
        "identifier": identifier,
        "band_index": band_index,
        "values": [list(value) for value in values],
        "columns": list(columns),
    }


def _signature_from_state(state, kind, column_count):
    state = _mapping(state, "Historique de transfert")
    try:
        columns = tuple(
            _integer(value, "Colonne transférée", 0, column_count - 1)
            for value in _sequence(state["columns"], "Colonnes transférées", 2)
        )
        if len(columns) != 2:
            raise ValueError("Deux colonnes transférées sont attendues.")
        if kind == "beer":
            points = tuple(
                tuple(_number(value, "Valeur Beer-Lambert") for value in point)
                for point in _sequence(state["points"], "Points transférés", MAX_STANDARDS)
            )
            if any(len(point) != 2 for point in points):
                raise ValueError("Point Beer-Lambert transféré invalide.")
            signature = (
                _text(state["reference_id"], "Référence transférée"),
                _text(state["unit"], "Unité transférée"),
                _integer(state["wavelength_nm"], "Longueur d'onde transférée"),
                points,
            )
        else:
            values = tuple(
                tuple(_number(value, "Valeur cinétique transférée") for value in point)
                for point in _sequence(state["values"], "Points transférés", MAX_KINETIC_POINTS)
            )
            if any(len(point) != 2 for point in values):
                raise ValueError("Point cinétique transféré invalide.")
            signature = (
                _text(state["identifier"], "Expérience transférée"),
                _integer(state["band_index"], "Bande transférée", 0, 7),
                values,
            )
    except KeyError as error:
        raise ValueError("Historique de transfert incomplet.") from error
    return signature, columns


def snapshot_spectrophotometry(tab):
    """Extraire seulement les données scientifiques et préférences portables."""

    calibrations = {}

    def register_calibration(calibration):
        state = _calibration_state(calibration)
        previous = calibrations.setdefault(calibration.reference_id, state)
        if previous != state:
            raise ValueError("Deux calibrations historiques partagent le même identifiant.")

    def spectrum_state(spectrum):
        return None if spectrum is None else _spectrum_state(spectrum, register_calibration)

    history = [
        _experiment_state(item, spectrum_state, register_calibration)
        for item in tab.kinetic_history
    ]
    current = (
        None
        if tab.kinetic_experiment is None
        else _experiment_state(tab.kinetic_experiment, spectrum_state, register_calibration)
    )
    state = {
        "version": SPECTRO_PROJECT_VERSION,
        "calibrations": list(calibrations.values()),
        "mode": tab.mode_combo.currentData(),
        "spectrum_display_mode": tab.spectrum_display_combo.currentData(),
        "spectra": [
            {
                "name": display.name,
                "color": display.color,
                "visible": display.visible,
                "spectrum": spectrum_state(display.spectrum),
            }
            for display in tab.spectra
        ],
        "absorbance": {
            "band_index": tab.absorbance_band_index(),
            "spectrum": spectrum_state(tab.absorbance_spectrum),
        },
        "beer_lambert": {
            "unit": tab.beer_unit_combo.currentText(),
            "band_index": tab.beer_band_index(),
            "standards": [
                {
                    "identifier": item.identifier,
                    "name": item.name,
                    "concentration": item.concentration,
                    "spectrum": spectrum_state(item.spectrum),
                }
                for item in tab.beer_standards
            ],
            "unknown_spectrum": spectrum_state(tab.beer_unknown_spectrum),
            "transfers": [
                _signature_state(signature, columns, "beer")
                for signature, columns in tab._beer_transfer_columns.items()
            ],
            "completed_transfers": [
                _signature_state(
                    signature, tab._beer_transfer_columns[signature], "beer"
                )
                for signature in sorted(tab._beer_completed_transfers, key=repr)
            ],
            "last_transferred": (
                None
                if tab._beer_last_transferred_signature is None
                else _signature_state(
                    tab._beer_last_transferred_signature,
                    tab._beer_transfer_columns.get(
                        tab._beer_last_transferred_signature, (-1, -1)
                    ),
                    "beer",
                )
            ),
        },
        "kinetics": {
            "band_index": tab.kinetic_band_index(),
            "duration_minutes": tab.kinetic_duration_spin.value(),
            "interval_seconds": int(tab.kinetic_interval_combo.currentData()),
            "current": current,
            "history": history,
            "transfers": [
                _signature_state(signature, columns, "kinetic")
                for signature, columns in tab._kinetic_transfer_columns.items()
            ],
            "completed_transfers": [
                _signature_state(
                    signature, tab._kinetic_transfer_columns[signature], "kinetic"
                )
                for signature in sorted(tab._kinetic_completed_transfers, key=repr)
            ],
            "last_transferred": (
                None
                if tab._kinetic_last_transferred_signature is None
                else _signature_state(
                    tab._kinetic_last_transferred_signature,
                    tab._kinetic_transfer_columns.get(
                        tab._kinetic_last_transferred_signature, (-1, -1)
                    ),
                    "kinetic",
                )
            ),
        },
    }
    # Une calibration peut n'être référencée que par les éléments parcourus après
    # la création initiale de la liste : la fixer une fois tous les objets visités.
    state["calibrations"] = list(calibrations.values())
    return state


def restore_spectrophotometry(tab, saved, column_count):
    """Restaurer des résultats historiques sans créer de session matérielle."""

    saved = _mapping(saved, "État Spectrophotométrie")
    if saved.get("version") != SPECTRO_PROJECT_VERSION:
        raise ValueError("Version des données Spectrophotométrie non prise en charge.")
    calibrations = {}
    for raw in _sequence(
        saved.get("calibrations", []), "Calibrations historiques", MAX_SPECTRA
    ):
        calibration = _calibration_from_state(raw)
        if calibration.reference_id in calibrations:
            raise ValueError("Identifiant de calibration historique répété.")
        calibrations[calibration.reference_id] = calibration

    # Les projets antérieurs à ce réglage conservent leur ancien rendu PCHIP.
    spectrum_display_mode = saved.get("spectrum_display_mode", "interpolated")
    if spectrum_display_mode not in ("points", "interpolated"):
        raise ValueError("Mode d'affichage du spectre inconnu.")
    tab.spectrum_display_combo.setCurrentIndex(
        tab.spectrum_display_combo.findData(spectrum_display_mode)
    )

    raw_spectra = _sequence(saved.get("spectra", []), "Spectres", MAX_SPECTRA)
    for raw in raw_spectra:
        raw = _mapping(raw, "Affichage de spectre")
        try:
            name = _text(raw["name"], "Nom du spectre", maximum=500)
            color = _text(raw["color"], "Couleur du spectre", maximum=16)
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                raise ValueError("Couleur de spectre invalide.")
            if type(raw["visible"]) is not bool:
                raise ValueError("Visibilité de spectre invalide.")
            spectrum = _spectrum_from_state(raw["spectrum"], calibrations)
        except KeyError as error:
            raise ValueError("Affichage de spectre incomplet.") from error
        tab.add_spectrum(spectrum, name=name, color=color, visible=raw["visible"])

    absorbance = _mapping(saved.get("absorbance", {}), "Mode Absorbance")
    absorbance_band = _integer(
        absorbance.get("band_index", 0), "Bande Absorbance", 0, 7
    )
    raw_absorbance = absorbance.get("spectrum")
    tab.absorbance_spectrum = (
        None
        if raw_absorbance is None
        else _spectrum_from_state(raw_absorbance, calibrations)
    )
    tab.absorbance_band_combo.setCurrentIndex(
        tab.absorbance_band_combo.findData(absorbance_band)
    )

    beer = _mapping(saved.get("beer_lambert", {}), "Mode Beer-Lambert")
    unit = beer.get("unit", CONCENTRATION_UNITS[0])
    if unit not in CONCENTRATION_UNITS:
        raise ValueError("Unité Beer-Lambert non prise en charge.")
    tab.beer_unit_combo.blockSignals(True)
    tab.beer_unit_combo.setCurrentIndex(tab.beer_unit_combo.findText(unit))
    tab.beer_unit_combo.blockSignals(False)
    tab._beer_previous_unit_index = tab.beer_unit_combo.currentIndex()
    beer_band = _integer(beer.get("band_index", 0), "Bande Beer-Lambert", 0, 7)
    tab.beer_band_combo.setCurrentIndex(tab.beer_band_combo.findData(beer_band))
    identifiers = set()
    for raw in _sequence(
        beer.get("standards", []), "Étalons Beer-Lambert", MAX_STANDARDS
    ):
        raw = _mapping(raw, "Étalon Beer-Lambert")
        try:
            identifier = _text(raw["identifier"], "Identifiant d'étalon")
            if identifier in identifiers:
                raise ValueError("Identifiant d'étalon répété.")
            identifiers.add(identifier)
            standard = BeerLambertStandard(
                identifier,
                _text(raw["name"], "Nom d'étalon", maximum=500),
                _number(raw["concentration"], "Concentration"),
                None
                if raw.get("spectrum") is None
                else _spectrum_from_state(raw["spectrum"], calibrations),
            )
        except KeyError as error:
            raise ValueError("Étalon Beer-Lambert incomplet.") from error
        tab.beer_standards.append(standard)
    raw_unknown = beer.get("unknown_spectrum")
    tab.beer_unknown_spectrum = (
        None
        if raw_unknown is None
        else _spectrum_from_state(raw_unknown, calibrations)
    )

    kinetics = _mapping(saved.get("kinetics", {}), "Mode Cinétique")
    kinetic_band = _integer(
        kinetics.get("band_index", 0), "Bande cinétique", 0, 7
    )
    tab.kinetic_band_combo.setCurrentIndex(
        tab.kinetic_band_combo.findData(kinetic_band)
    )
    duration = _integer(
        kinetics.get("duration_minutes", 15), "Durée cinétique", 1, 30
    )
    interval = _integer(
        kinetics.get("interval_seconds", 5), "Intervalle cinétique"
    )
    if interval not in KINETIC_INTERVALS_SECONDS:
        raise ValueError("Intervalle cinétique non pris en charge.")
    tab.kinetic_duration_spin.setValue(duration)
    tab.kinetic_interval_combo.setCurrentIndex(
        tab.kinetic_interval_combo.findData(interval)
    )
    raw_history = _sequence(
        kinetics.get("history", []), "Historique cinétique", MAX_EXPERIMENTS
    )
    tab.kinetic_history = [
        _experiment_from_state(item, calibrations) for item in raw_history
    ]
    raw_current = kinetics.get("current")
    tab.kinetic_experiment = (
        None
        if raw_current is None
        else _experiment_from_state(raw_current, calibrations)
    )
    experiments = [*tab.kinetic_history]
    if tab.kinetic_experiment is not None:
        experiments.append(tab.kinetic_experiment)
    if len({item.identifier for item in experiments}) != len(experiments):
        raise ValueError("Identifiant d'expérience cinétique répété.")
    if sum(len(item.points) for item in experiments) > MAX_KINETIC_POINTS:
        raise ValueError("Le projet contient trop de points cinétiques.")

    def restore_transfers(raw_values, kind):
        result = {}
        for raw in _sequence(raw_values, "Transferts", MAX_EXPERIMENTS * 8):
            signature, columns = _signature_from_state(raw, kind, column_count)
            if signature in result:
                raise ValueError("Signature de transfert répétée.")
            result[signature] = columns
        return result

    tab._beer_transfer_columns = restore_transfers(beer.get("transfers", []), "beer")
    tab._kinetic_transfer_columns = restore_transfers(
        kinetics.get("transfers", []), "kinetic"
    )

    def restore_completed(raw_values, kind, transfers):
        completed = set()
        for raw in _sequence(
            raw_values, "Transferts terminés", MAX_EXPERIMENTS * 8
        ):
            signature, columns = _signature_from_state(raw, kind, column_count)
            if transfers.get(signature) != columns:
                raise ValueError("Transfert terminé incohérent.")
            completed.add(signature)
        return completed

    tab._beer_completed_transfers = restore_completed(
        beer.get("completed_transfers", []), "beer", tab._beer_transfer_columns
    )
    tab._kinetic_completed_transfers = restore_completed(
        kinetics.get("completed_transfers", []),
        "kinetic",
        tab._kinetic_transfer_columns,
    )
    tab._beer_last_transferred_signature = None
    if beer.get("last_transferred") is not None:
        signature, columns = _signature_from_state(
            beer["last_transferred"], "beer", column_count
        )
        if tab._beer_transfer_columns.get(signature) != columns:
            raise ValueError("Dernier transfert Beer-Lambert incohérent.")
        tab._beer_last_transferred_signature = signature
        tab._beer_completed_transfers.add(signature)
    tab._kinetic_last_transferred_signature = None
    if kinetics.get("last_transferred") is not None:
        signature, columns = _signature_from_state(
            kinetics["last_transferred"], "kinetic", column_count
        )
        if tab._kinetic_transfer_columns.get(signature) != columns:
            raise ValueError("Dernier transfert cinétique incohérent.")
        tab._kinetic_last_transferred_signature = signature
        tab._kinetic_completed_transfers.add(signature)

    mode = saved.get("mode", "spectrum")
    if mode not in ("spectrum", "absorbance", "beer_lambert", "kinetics"):
        raise ValueError("Mode Spectrophotométrie inconnu.")
    tab.mode_combo.setCurrentIndex(tab.mode_combo.findData(mode))

    # Sécurité scientifique : uniquement des archives, jamais un état matériel.
    tab.session_id = None
    tab.applied_config = None
    tab.dark_measurement = None
    tab.white_measurement = None
    tab.calibration = None
    tab._restored_calibration_ids = set(calibrations)
    tab._configuration_dirty = True
    tab._pending_kind = None
    tab._pending_absorbance = False
    tab._pending_beer_target = None
    tab._pending_kinetic_experiment_id = None
    tab._kinetic_active = False
    tab._kinetic_stopping = False
    tab.kinetic_journal = None
    if tab.kinetic_experiment is not None:
        elapsed = (
            tab.kinetic_experiment.points[-1].elapsed_seconds
            if tab.kinetic_experiment.points
            else 0.0
        )
        tab.kinetic_experiment.start_monotonic = tab._monotonic_clock() - elapsed
        tab.kinetic_state_label.setText("Expérience restaurée — acquisition inactive")
        tab.kinetic_action_status.setText(
            "Résultats historiques consultables ; aucune acquisition n'a été reprise."
        )
    tab._update_calibration_status()
    tab._refresh_absorbance_ui()
    tab._refresh_beer_ui()
    tab._refresh_kinetic_ui()
    tab._update_controls()
