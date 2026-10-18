"""Calculs scientifiques pour les profils d'intensite d'une image."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot, isfinite
from uuid import uuid4

import numpy as np
from scipy import ndimage, signal


MAX_PROFILE_WIDTH = 51
MAX_PROFILES = 32
SNAP_MODES = ("manual", "minimum", "maximum")


def _point(value):
    if hasattr(value, "x"):
        value = value.x(), value.y()
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("Un point doit contenir deux coordonnees.")
    result = float(value[0]), float(value[1])
    if not all(isfinite(item) for item in result):
        raise ValueError("Les coordonnees doivent etre finies.")
    return result


@dataclass
class ImageCalibration:
    """Etalonnage spatial isotrope ou spectral horizontal."""

    mode: str = "none"
    unit: str = "px"
    first: tuple[float, float] | None = None
    second: tuple[float, float] | None = None
    first_value: float | None = None
    second_value: float | None = None
    absolute: bool = True
    spectral_method: str = "known_gap"
    reference_endpoint: str = "A"
    horizontal: bool = False

    def __post_init__(self):
        if self.mode not in ("none", "distance", "spectral"):
            raise ValueError("Mode d'etalonnage inconnu.")
        if self.spectral_method not in ("known_gap", "two_points"):
            raise ValueError("Methode d'etalonnage spectral inconnue.")
        if self.reference_endpoint not in ("A", "B"):
            raise ValueError("Point de reference spectral inconnu.")
        self.horizontal = bool(self.horizontal)
        if self.mode == "none":
            self.unit = "px"
            return
        self.first, self.second = _point(self.first), _point(self.second)
        self.first_value = float(self.first_value)
        if not isfinite(self.first_value):
            raise ValueError("Valeur d'etalonnage invalide.")
        if self.mode == "distance":
            if self.first_value <= 0 or hypot(
                    self.second[0] - self.first[0], self.second[1] - self.first[1]) < 1:
                raise ValueError("L'etalon doit mesurer au moins un pixel et sa longueur doit etre positive.")
            if not self.unit or self.unit == "px":
                raise ValueError("Une unite de distance est necessaire.")
            self.second_value = None
        else:
            self.second_value = float(self.second_value)
            if (not isfinite(self.second_value) or abs(self.second[0] - self.first[0]) < 1
                    or self.first_value == self.second_value):
                raise ValueError("Les deux references spectrales doivent avoir des abscisses et valeurs distinctes.")
            if not self.unit or self.unit == "px":
                raise ValueError("Une unite spectrale est necessaire.")
            self.absolute = bool(self.absolute)

    @property
    def axis_name(self):
        if self.mode == "none":
            return "x"
        if self.mode == "distance":
            return "distance"
        return "λ" if self.absolute else "Δλ"

    def axis_values(self, distances, xs):
        distances = np.asarray(distances, dtype=float)
        if self.mode == "none":
            return distances
        if self.mode == "distance":
            pixels = hypot(self.second[0] - self.first[0], self.second[1] - self.first[1])
            return distances * self.first_value / pixels
        xs = np.asarray(xs, dtype=float)
        slope = (self.second_value - self.first_value) / (self.second[0] - self.first[0])
        return self.first_value + (xs - self.first[0]) * slope


@dataclass
class MeasurementPoint:
    profile_identifier: str
    fraction: float

    def __post_init__(self):
        if not isinstance(self.profile_identifier, str) or not self.profile_identifier:
            raise ValueError("Profil de mesure invalide.")
        self.fraction = float(self.fraction)
        if not isfinite(self.fraction) or not 0 <= self.fraction <= 1:
            raise ValueError("Position de repere invalide.")


@dataclass
class ProfileMeasurement:
    mode: str = "gap"
    first: MeasurementPoint | None = None
    second: MeasurementPoint | None = None
    intervals: int = 1
    snap: str = "manual"

    def __post_init__(self):
        if self.mode not in ("gap", "interfringe"):
            raise ValueError("Mode de mesure inconnu.")
        self.intervals = int(self.intervals)
        if self.intervals < 1:
            raise ValueError("Le nombre d'interfranges doit etre positif.")
        if self.snap not in SNAP_MODES:
            raise ValueError("Mode d'aimantation inconnu.")


@dataclass
class IntensityProfile:
    name: str
    start: tuple[float, float]
    end: tuple[float, float]
    width: int = 1
    color: str = "#168AFB"
    visible: bool = True
    identifier: str = field(default_factory=lambda: uuid4().hex)
    horizontal: bool = False

    def __post_init__(self):
        self.start, self.end = _point(self.start), _point(self.end)
        self.horizontal = bool(self.horizontal)
        self.width = int(self.width)
        if hypot(self.end[0] - self.start[0], self.end[1] - self.start[1]) < 1:
            raise ValueError("Le segment doit mesurer au moins un pixel.")
        if not 1 <= self.width <= MAX_PROFILE_WIDTH:
            raise ValueError(f"La largeur doit etre comprise entre 1 et {MAX_PROFILE_WIDTH} pixels.")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 200:
            raise ValueError("Nom de profil invalide.")


@dataclass(frozen=True)
class ProfileSamples:
    pixel_distance: np.ndarray
    axis: np.ndarray
    intensity: np.ndarray
    x: np.ndarray
    y: np.ndarray


def extract_profile(image, profile, calibration=None):
    """Echantillonner un segment et moyenner les paralleles de sa bande."""
    array = np.asarray(image)
    if array.ndim != 2 or not array.size:
        raise ValueError("Une image en niveaux de gris non vide est attendue.")
    if not isinstance(profile, IntensityProfile):
        raise TypeError("Un profil d'intensite est attendu.")
    height, width = array.shape
    x0, y0 = profile.start
    x1, y1 = profile.end
    if not (0 <= x0 < width and 0 <= x1 < width and 0 <= y0 < height and 0 <= y1 < height):
        raise ValueError("Le segment doit rester dans l'image.")
    length = hypot(x1 - x0, y1 - y0)
    count = max(2, int(np.ceil(length)) + 1)
    distances = np.linspace(0.0, length, count)
    fraction = distances / length
    xs = x0 + fraction * (x1 - x0)
    ys = y0 + fraction * (y1 - y0)
    normal_x, normal_y = -(y1 - y0) / length, (x1 - x0) / length
    offsets = np.arange(profile.width, dtype=float) - (profile.width - 1) / 2
    sample_x = xs[None, :] + offsets[:, None] * normal_x
    sample_y = ys[None, :] + offsets[:, None] * normal_y
    values = ndimage.map_coordinates(
        array.astype(np.float32, copy=False),
        (sample_y, sample_x), order=1, mode="constant", cval=np.nan,
    )
    valid = np.isfinite(values)
    totals = np.nansum(values, axis=0)
    counts = valid.sum(axis=0)
    intensities = np.divide(totals, counts, out=np.full(count, np.nan), where=counts > 0)
    calibration = calibration or ImageCalibration()
    axis = calibration.axis_values(distances, xs)
    return ProfileSamples(distances, axis, intensities, xs, ys)


def fraction_value(samples, fraction):
    """Interpoler les coordonnees d'un profil a une fraction de son segment."""
    fraction = float(fraction)
    if not 0 <= fraction <= 1:
        raise ValueError("Position de repere invalide.")
    position = fraction * (len(samples.axis) - 1)
    left = int(np.floor(position))
    right = min(left + 1, len(samples.axis) - 1)
    weight = position - left
    axis = (1 - weight) * samples.axis[left] + weight * samples.axis[right]
    intensity = (1 - weight) * samples.intensity[left] + weight * samples.intensity[right]
    return float(axis), float(intensity)


def local_extremum_index(values, index, kind, radius=12):
    """Trouver l'extremum local le plus proche, dans un voisinage strictement borne."""
    if kind not in ("minimum", "maximum"):
        raise ValueError("Type d'extremum inconnu.")
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values):
        raise ValueError("Profil vide.")
    index = min(len(values) - 1, max(0, int(index)))
    radius = min(100, max(1, int(radius)))
    start, stop = max(0, index - radius), min(len(values), index + radius + 1)
    window = values[start:stop]
    if not np.all(np.isfinite(window)):
        return index
    smooth = ndimage.gaussian_filter1d(window, 1.0, mode="nearest")
    # Une légère proéminence écarte les micro-extrema dus au bruit de capteur,
    # sans jamais élargir la recherche au-delà du voisinage demandé.
    prominence = max(float(np.ptp(smooth)) * 0.03, np.finfo(float).eps)
    candidates, _ = signal.find_peaks(
        -smooth if kind == "minimum" else smooth, prominence=prominence)
    if not len(candidates):
        return index
    absolute = start + candidates
    return int(absolute[np.argmin(np.abs(absolute - index))])


def measurement_result(measurement, samples_by_profile):
    """Retourner xA, xB, ecart et eventuel interfrange moyen."""
    if not isinstance(measurement, ProfileMeasurement):
        raise TypeError("Mesure de profil attendue.")
    if measurement.first is None or measurement.second is None:
        return None
    first_samples = samples_by_profile.get(measurement.first.profile_identifier)
    second_samples = samples_by_profile.get(measurement.second.profile_identifier)
    if first_samples is None or second_samples is None:
        raise ValueError("Le profil associe a un repere n'existe plus.")
    first_x, _ = fraction_value(first_samples, measurement.first.fraction)
    second_x, _ = fraction_value(second_samples, measurement.second.fraction)
    total = abs(second_x - first_x)
    if np.isclose(total, 0.0, rtol=0, atol=1e-12):
        raise ValueError("Les reperes A et B doivent avoir des abscisses distinctes.")
    average = total / measurement.intervals if measurement.mode == "interfringe" else None
    return first_x, second_x, total, average
