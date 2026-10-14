"""Moteur scientifique de spectrophotométrie de Physalix.

Ce module est indépendant du transport série et de l'interface graphique. Il
conserve les données brutes du protocole et produit les huit points expérimentaux
d'absorbance sans interpolation ni arrondi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import log10

from physalix.spectrophotometry_protocol import (
    SpectroConfig,
    SpectroData,
    SpectroIllumination,
)


VISIBLE_WAVELENGTHS_NM = (415, 445, 480, 515, 555, 590, 630, 680)


class MeasurementKind(Enum):
    """Rôle scientifique d'une acquisition brute."""

    DARK = "dark"
    WHITE = "white"
    SAMPLE = "sample"


class BandInvalidity(Enum):
    """Motif explicite rendant une absorbance indisponible."""

    MISSING_CALIBRATION = "missing_calibration"
    SESSION_MISMATCH = "session_mismatch"
    ACQUISITION_PARAMETERS_MISMATCH = "acquisition_parameters_mismatch"
    DARK_SATURATED = "dark_saturated"
    WHITE_SATURATED = "white_saturated"
    SAMPLE_SATURATED = "sample_saturated"
    REFERENCE_NOT_ABOVE_DARK = "reference_not_above_dark"
    SAMPLE_NOT_ABOVE_DARK = "sample_not_above_dark"


class CalibrationCompatibilityError(ValueError):
    """Les mesures ne peuvent pas constituer une calibration cohérente."""


def acquisition_parameters_match(first: SpectroConfig, second: SpectroConfig) -> bool:
    """Comparer les paramètres physiques, indépendamment de ``config_id``."""

    return (
        first.atime == second.atime
        and first.astep == second.astep
        and first.gain == second.gain
        and first.led_pwm == second.led_pwm
    )


@dataclass(frozen=True)
class SpectroMeasurement:
    """Mesure brute accompagnée de toute sa provenance scientifique."""

    kind: MeasurementKind
    data: SpectroData
    applied_config: SpectroConfig
    session_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MeasurementKind):
            raise TypeError("kind doit être un MeasurementKind.")
        if not isinstance(self.data, SpectroData):
            raise TypeError("data doit être un SpectroData.")
        if not isinstance(self.applied_config, SpectroConfig):
            raise TypeError("applied_config doit être un SpectroConfig.")
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id doit être une chaîne non vide.")
        if self.data.config_id != self.applied_config.config_id:
            raise ValueError(
                "Le config_id de la mesure ne correspond pas à la configuration "
                "appliquée."
            )

        expected_illumination = (
            SpectroIllumination.LED_OFF
            if self.kind is MeasurementKind.DARK
            else SpectroIllumination.LED_ON
        )
        if self.data.illumination is not expected_illumination:
            raise ValueError("L'illumination ne correspond pas au rôle de la mesure.")

    @property
    def bands(self) -> tuple[int, int, int, int, int, int, int, int]:
        return self.data.bands

    @property
    def clear(self) -> int:
        return self.data.clear

    @property
    def nir(self) -> int:
        return self.data.nir

    @property
    def saturation_flags(self) -> int:
        return self.data.saturation_flags


@dataclass(frozen=True)
class SpectroCalibration:
    """Références noire et blanche immuables d'une session matérielle."""

    reference_id: str
    dark: SpectroMeasurement
    white: SpectroMeasurement

    def __post_init__(self) -> None:
        if not isinstance(self.reference_id, str) or not self.reference_id:
            raise ValueError("reference_id doit être une chaîne non vide.")
        if not isinstance(self.dark, SpectroMeasurement) or not isinstance(
            self.white, SpectroMeasurement
        ):
            raise TypeError("dark et white doivent être des SpectroMeasurement.")
        if self.dark.kind is not MeasurementKind.DARK:
            raise CalibrationCompatibilityError("La référence noire est invalide.")
        if self.white.kind is not MeasurementKind.WHITE:
            raise CalibrationCompatibilityError("La référence blanche est invalide.")
        if self.dark.session_id != self.white.session_id:
            raise CalibrationCompatibilityError(
                "Les références noire et blanche proviennent de sessions différentes."
            )
        if not acquisition_parameters_match(
            self.dark.applied_config, self.white.applied_config
        ):
            raise CalibrationCompatibilityError(
                "Les références noire et blanche utilisent des paramètres "
                "d'acquisition différents."
            )

    @property
    def session_id(self) -> str:
        return self.dark.session_id

    @property
    def applied_config(self) -> SpectroConfig:
        return self.white.applied_config


@dataclass(frozen=True)
class AbsorbanceBandResult:
    """Résultat scientifique pour une bande visible de l'AS7341."""

    wavelength_nm: int
    sample_intensity: int
    dark_intensity: int | None
    white_intensity: int | None
    transmission: float | None
    absorbance: float | None
    invalidities: tuple[BandInvalidity, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.invalidities


@dataclass(frozen=True)
class AbsorbanceSpectrum:
    """Huit points d'absorbance avec leurs données brutes et leur provenance."""

    measurement: SpectroMeasurement
    calibration: SpectroCalibration | None
    bands: tuple[
        AbsorbanceBandResult,
        AbsorbanceBandResult,
        AbsorbanceBandResult,
        AbsorbanceBandResult,
        AbsorbanceBandResult,
        AbsorbanceBandResult,
        AbsorbanceBandResult,
        AbsorbanceBandResult,
    ]

    @property
    def wavelengths_nm(self) -> tuple[int, ...]:
        return tuple(band.wavelength_nm for band in self.bands)

    @property
    def absorbances(self) -> tuple[float | None, ...]:
        return tuple(band.absorbance for band in self.bands)

    @property
    def is_valid(self) -> bool:
        return all(band.is_valid for band in self.bands)

    @property
    def calibration_reference_id(self) -> str | None:
        return self.calibration.reference_id if self.calibration is not None else None


def calculate_absorbance(
    sample: SpectroMeasurement,
    calibration: SpectroCalibration | None,
) -> AbsorbanceSpectrum:
    """Calculer les huit absorbances, sans arrondi ni valeur de remplacement."""

    if not isinstance(sample, SpectroMeasurement):
        raise TypeError("sample doit être un SpectroMeasurement.")
    if sample.kind is not MeasurementKind.SAMPLE:
        raise ValueError("Seule une mesure d'échantillon peut être calculée.")
    if calibration is not None and not isinstance(calibration, SpectroCalibration):
        raise TypeError("calibration doit être un SpectroCalibration ou None.")

    global_invalidities: list[BandInvalidity] = []
    if calibration is None:
        global_invalidities.append(BandInvalidity.MISSING_CALIBRATION)
    else:
        if sample.session_id != calibration.session_id:
            global_invalidities.append(BandInvalidity.SESSION_MISMATCH)
        if not acquisition_parameters_match(
            sample.applied_config, calibration.applied_config
        ):
            global_invalidities.append(
                BandInvalidity.ACQUISITION_PARAMETERS_MISMATCH
            )

    results: list[AbsorbanceBandResult] = []
    for index, (wavelength_nm, sample_intensity) in enumerate(
        zip(VISIBLE_WAVELENGTHS_NM, sample.bands)
    ):
        invalidities = list(global_invalidities)
        if sample.data.is_saturated(index):
            invalidities.append(BandInvalidity.SAMPLE_SATURATED)

        dark_intensity = None
        white_intensity = None
        transmission = None
        absorbance = None

        if calibration is not None:
            dark_intensity = calibration.dark.bands[index]
            white_intensity = calibration.white.bands[index]

            if calibration.dark.data.is_saturated(index):
                invalidities.append(BandInvalidity.DARK_SATURATED)
            if calibration.white.data.is_saturated(index):
                invalidities.append(BandInvalidity.WHITE_SATURATED)
            if white_intensity <= dark_intensity:
                invalidities.append(BandInvalidity.REFERENCE_NOT_ABOVE_DARK)
            if sample_intensity <= dark_intensity:
                invalidities.append(BandInvalidity.SAMPLE_NOT_ABOVE_DARK)

            if not invalidities:
                transmission = (sample_intensity - dark_intensity) / (
                    white_intensity - dark_intensity
                )
                absorbance = -log10(transmission)

        results.append(
            AbsorbanceBandResult(
                wavelength_nm=wavelength_nm,
                sample_intensity=sample_intensity,
                dark_intensity=dark_intensity,
                white_intensity=white_intensity,
                transmission=transmission,
                absorbance=absorbance,
                invalidities=tuple(invalidities),
            )
        )

    return AbsorbanceSpectrum(sample, calibration, tuple(results))


@dataclass(frozen=True)
class SpectroSeries:
    """Collection immuable de spectres rattachés à une même calibration."""

    calibration: SpectroCalibration
    spectra: tuple[AbsorbanceSpectrum, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.calibration, SpectroCalibration):
            raise TypeError("calibration doit être un SpectroCalibration.")
        if type(self.spectra) is not tuple or any(
            not isinstance(spectrum, AbsorbanceSpectrum)
            or spectrum.calibration is not self.calibration
            for spectrum in self.spectra
        ):
            raise ValueError(
                "Tous les spectres de la série doivent utiliser sa calibration."
            )

    def add_measurement(self, sample: SpectroMeasurement) -> SpectroSeries:
        """Retourner une nouvelle série contenant le spectre de ``sample``."""

        spectrum = calculate_absorbance(sample, self.calibration)
        return SpectroSeries(self.calibration, self.spectra + (spectrum,))
