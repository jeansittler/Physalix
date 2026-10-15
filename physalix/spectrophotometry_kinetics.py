"""Données et planification d'une cinétique spectrophotométrique."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from physalix.spectrophotometry import AbsorbanceSpectrum, SpectroCalibration
from physalix.spectrophotometry_protocol import SpectroConfig


KINETIC_INTERVALS_SECONDS = (5, 10, 15, 30, 60)


def estimated_measurement_seconds(config: SpectroConfig) -> float:
    """Estimer l'intégration complète des deux groupes visibles de l'AS7341."""

    if not isinstance(config, SpectroConfig):
        raise TypeError("config doit être un SpectroConfig.")
    cycles = (config.atime + 1) * (config.astep + 1)
    return cycles * 2 * 2.78 / 1_000_000


@dataclass(frozen=True)
class KineticPoint:
    """Une mesure complète datée à sa réception par l'application."""

    sequence: int
    elapsed_seconds: float
    spectrum: AbsorbanceSpectrum

    def __post_init__(self):
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("L'ordre de la mesure cinétique est invalide.")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds <= 0:
            raise ValueError("Le temps cinétique doit être fini et strictement positif.")
        if not isinstance(self.spectrum, AbsorbanceSpectrum):
            raise TypeError("spectrum doit être un AbsorbanceSpectrum.")

    @property
    def arduino_timestamp_ms(self) -> int:
        return self.spectrum.measurement.data.timestamp_ms


@dataclass
class KineticExperiment:
    """Expérience en mémoire ; aucun point théorique n'est ajouté à t=0."""

    identifier: str
    calibration: SpectroCalibration
    start_monotonic: float
    duration_seconds: int
    interval_seconds: int
    points: list[KineticPoint] = field(default_factory=list)
    stopped_reason: str | None = None

    def __post_init__(self):
        if not self.identifier:
            raise ValueError("L'identifiant de l'expérience est obligatoire.")
        if not isinstance(self.calibration, SpectroCalibration):
            raise TypeError("calibration doit être un SpectroCalibration.")
        if not math.isfinite(self.start_monotonic):
            raise ValueError("L'origine temporelle doit être monotone et finie.")
        if type(self.duration_seconds) is not int or not 60 <= self.duration_seconds <= 1800:
            raise ValueError("La durée doit être comprise entre 1 et 30 minutes.")
        if self.interval_seconds not in KINETIC_INTERVALS_SECONDS:
            raise ValueError("L'intervalle cinétique n'est pas proposé.")

    def elapsed(self, monotonic_now: float) -> float:
        value = float(monotonic_now) - self.start_monotonic
        if not math.isfinite(value):
            raise ValueError("Le temps monotone est invalide.")
        return max(0.0, value)

    def next_due_monotonic(self, monotonic_now: float) -> float:
        """Retourner la prochaine échéance future, en sautant tout retard."""

        elapsed = self.elapsed(monotonic_now)
        index = math.floor(elapsed / self.interval_seconds) + 1
        return self.start_monotonic + index * self.interval_seconds

    def add_spectrum(
        self, spectrum: AbsorbanceSpectrum, completed_monotonic: float
    ) -> KineticPoint | None:
        """Ajouter une réception réelle si elle appartient encore à la fenêtre."""

        if not isinstance(spectrum, AbsorbanceSpectrum):
            raise TypeError("spectrum doit être un AbsorbanceSpectrum.")
        if (
            spectrum.calibration is None
            or spectrum.calibration.reference_id != self.calibration.reference_id
        ):
            raise ValueError("La mesure n'utilise pas la calibration de l'expérience.")
        elapsed = self.elapsed(completed_monotonic)
        if elapsed <= 0 or elapsed > self.duration_seconds:
            return None
        point = KineticPoint(len(self.points) + 1, elapsed, spectrum)
        self.points.append(point)
        return point

    def band_values(self, band_index: int) -> tuple[tuple[float, float | None], ...]:
        """Conserver les lacunes afin de ne pas relier deux points à travers elles."""

        if type(band_index) is not int or not 0 <= band_index < 8:
            raise ValueError("La bande cinétique doit être comprise entre F1 et F8.")
        return tuple(
            (
                point.elapsed_seconds,
                point.spectrum.bands[band_index].absorbance
                if point.spectrum.bands[band_index].is_valid
                else None,
            )
            for point in self.points
        )

    def valid_band_values(self, band_index: int) -> tuple[tuple[float, float], ...]:
        return tuple(
            (elapsed, absorbance)
            for elapsed, absorbance in self.band_values(band_index)
            if absorbance is not None
        )
