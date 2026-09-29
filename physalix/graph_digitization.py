"""Calibration et extraction conservatrice de points depuis une image de graphique."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite

import numpy as np
from scipy import ndimage


class CalibrationError(ValueError):
    """Signaler une calibration géométriquement inexploitable."""


def calibration_decimal_places(texts, guard_digits=1, maximum=8):
    """Déduire une précision d'affichage simple des valeurs saisies pour un axe."""
    places = []
    for text in texts:
        try:
            value = Decimal(str(text).strip().replace(",", "."))
        except InvalidOperation as error:
            raise ValueError("Valeur de calibration invalide.") from error
        if not value.is_finite():
            raise ValueError("Valeur de calibration non finie.")
        places.append(max(0, -value.as_tuple().exponent))
    return min(maximum, max(places, default=0) + guard_digits)


def format_digitized_value(value, decimal_places):
    """Arrondir uniquement la représentation, sans altérer la calibration interne."""
    rendered = format(float(value), f".{int(decimal_places)}f").rstrip("0").rstrip(".")
    return "0" if rendered in ("", "-0") else rendered


def _xy(point):
    if hasattr(point, "x"):
        return float(point.x()), float(point.y())
    return float(point[0]), float(point[1])


@dataclass(frozen=True)
class CalibrationMark:
    pixel: tuple[float, float]
    value: float

    def __post_init__(self):
        pixel = _xy(self.pixel)
        value = float(self.value)
        if not all(isfinite(item) for item in (*pixel, value)):
            raise CalibrationError("Les points et valeurs de calibration doivent être finis.")
        object.__setattr__(self, "pixel", pixel)
        object.__setattr__(self, "value", value)


class AxisCalibration:
    """Transformer les pixels en valeurs par deux fonctions affines indépendantes."""

    def __init__(self, x_marks, y_marks):
        if len(x_marks) != 2 or len(y_marks) != 2:
            raise CalibrationError("Deux points sont nécessaires sur chaque axe.")
        self.x_marks = tuple(mark if isinstance(mark, CalibrationMark) else CalibrationMark(*mark)
                             for mark in x_marks)
        self.y_marks = tuple(mark if isinstance(mark, CalibrationMark) else CalibrationMark(*mark)
                             for mark in y_marks)
        if self.x_marks[0].value == self.x_marks[1].value or self.y_marks[0].value == self.y_marks[1].value:
            raise CalibrationError("Les deux valeurs d'un même axe doivent être différentes.")
        self.x_coefficients = self._coefficients(self.x_marks, self.y_marks)
        self.y_coefficients = self._coefficients(self.y_marks, self.x_marks)

    @staticmethod
    def _coefficients(value_marks, constant_marks):
        first, second = value_marks
        constant_first, constant_second = constant_marks
        u1, v1 = first.pixel
        u2, v2 = second.pixel
        cu1, cv1 = constant_first.pixel
        cu2, cv2 = constant_second.pixel
        matrix = np.asarray([
            [u1, v1, 1.0],
            [u2, v2, 1.0],
            [cu2 - cu1, cv2 - cv1, 0.0],
        ], dtype=float)
        values = np.asarray([first.value, second.value, 0.0], dtype=float)
        try:
            condition = np.linalg.cond(matrix)
            if not isfinite(condition) or condition > 1e10:
                raise np.linalg.LinAlgError
            return np.linalg.solve(matrix, values)
        except np.linalg.LinAlgError as error:
            raise CalibrationError(
                "Les directions des axes sont confondues ou les points sont trop proches."
            ) from error

    def convert(self, point):
        u, v = _xy(point)
        vector = np.asarray([u, v, 1.0])
        x = float(self.x_coefficients @ vector)
        y = float(self.y_coefficients @ vector)
        return x, y

    def data_bounds(self):
        """Retourner les intervalles couverts par les graduations de calibration."""
        return (
            tuple(sorted(mark.value for mark in self.x_marks)),
            tuple(sorted(mark.value for mark in self.y_marks)),
        )

    def value_margin(self, pixel_margin):
        """Convertir une petite marge en pixels dans les unités des deux axes."""
        pixel_margin = max(0.0, float(pixel_margin))
        return (
            pixel_margin * float(np.linalg.norm(self.x_coefficients[:2])),
            pixel_margin * float(np.linalg.norm(self.y_coefficients[:2])),
        )


@dataclass
class DigitizedPoint:
    identifier: int
    pixel: tuple[float, float]
    validated: bool = True
    automatic: bool = False
    rejected: bool = False


class DigitizationSession:
    """Conserver les choix provisoires sans toucher au tableur."""

    def __init__(self):
        self.roi = None
        self.calibration = None
        self.x_marks = []
        self.y_marks = []
        self.points = []
        self._next_identifier = 1

    def reset(self):
        self.__init__()

    def set_roi(self, rectangle):
        x, y, width, height = map(float, rectangle)
        if width < 2 or height < 2:
            raise ValueError("La zone du graphique est trop petite.")
        self.roi = x, y, width, height
        self.calibration = None
        self.x_marks.clear()
        self.y_marks.clear()
        self.points.clear()

    def set_axis_marks(self, axis, marks):
        converted = [mark if isinstance(mark, CalibrationMark) else CalibrationMark(*mark)
                     for mark in marks]
        if len(converted) > 2:
            raise CalibrationError("Deux points au maximum sont attendus par axe.")
        if axis == "x":
            self.x_marks = converted
        elif axis == "y":
            self.y_marks = converted
        else:
            raise ValueError("Axe inconnu.")
        self.calibration = None
        if len(self.x_marks) == len(self.y_marks) == 2:
            self.calibration = AxisCalibration(self.x_marks, self.y_marks)
        return self.calibration

    def add_point(self, pixel, validated=True, automatic=False):
        pixel = _xy(pixel)
        if self.roi is not None:
            x, y, width, height = self.roi
            if not (x <= pixel[0] <= x + width and y <= pixel[1] <= y + height):
                raise ValueError("Le point doit appartenir à la zone du graphique.")
        point = DigitizedPoint(self._next_identifier, pixel, bool(validated), bool(automatic))
        self._next_identifier += 1
        self.points.append(point)
        return point

    def add_candidates(self, pixels):
        return [self.add_point(pixel, validated=False, automatic=True) for pixel in pixels]

    def point(self, identifier):
        return next((point for point in self.points if point.identifier == identifier), None)

    def move_point(self, identifier, pixel):
        point = self.point(identifier)
        if point is None:
            raise KeyError(identifier)
        new_pixel = _xy(pixel)
        if self.roi is not None:
            x, y, width, height = self.roi
            if not (x <= new_pixel[0] <= x + width and y <= new_pixel[1] <= y + height):
                raise ValueError("Le point doit appartenir à la zone du graphique.")
        point.pixel = new_pixel

    def remove_point(self, identifier):
        point = self.point(identifier)
        if point is None:
            return False
        self.points.remove(point)
        return True

    def set_validated(self, identifier, validated):
        point = self.point(identifier)
        if point is None:
            raise KeyError(identifier)
        point.validated = bool(validated)
        if point.validated:
            point.rejected = False

    def converted_points(self, validated_only=True):
        if self.calibration is None:
            raise CalibrationError("Terminez la calibration des deux axes.")
        points = [point for point in self.points if point.validated or not validated_only]
        return sorted(((self.calibration.convert(point.pixel), point) for point in points),
                      key=lambda item: (item[0][0], item[0][1], item[1].identifier))


def _component_statistics(labels, label_index, component_slice):
    rows, columns = np.nonzero(labels[component_slice] == label_index)
    area = len(rows)
    height = component_slice[0].stop - component_slice[0].start
    width = component_slice[1].stop - component_slice[1].start
    component = labels[component_slice] == label_index
    boundary = component & ~ndimage.binary_erosion(component)
    perimeter = max(1, int(boundary.sum()))
    return {
        "area": area,
        "width": width,
        "height": height,
        "aspect": width / height,
        "fill": area / (width * height),
        "compactness": 4 * np.pi * area / (perimeter * perimeter),
        "thickness": float(ndimage.distance_transform_edt(component).max()),
        "center": (
            component_slice[1].start + float(columns.mean()),
            component_slice[0].start + float(rows.mean()),
        ),
    }


def _refined_sample(array, sample_rgb, sample_point, tolerance):
    """Éviter qu'un pixel d'anticrénelage peu saturé définisse toute la couleur."""
    sample = np.asarray(sample_rgb, dtype=float)[:3]
    if sample_point is None:
        return sample
    initial_chromaticity = sample / max(float(sample.sum()), 1.0)
    if float(np.linalg.norm(initial_chromaticity - 1 / 3)) >= .18:
        return sample
    column, row = (int(round(value)) for value in _xy(sample_point))
    radius = 7
    top = max(0, row - radius)
    bottom = min(array.shape[0], row + radius + 1)
    left = max(0, column - radius)
    right = min(array.shape[1], column + radius + 1)
    pixels = array[top:bottom, left:right, :3].reshape(-1, 3).astype(float)
    totals = np.maximum(pixels.sum(axis=1, keepdims=True), 1.0)
    chromaticity = pixels / totals
    sample_chromaticity = initial_chromaticity
    saturation = np.linalg.norm(chromaticity - 1 / 3, axis=1)
    same_color = (
        np.linalg.norm(chromaticity - sample_chromaticity, axis=1) * 255
        <= float(tolerance)
    )
    candidates = np.nonzero(same_color & (pixels.mean(axis=1) >= 12))[0]
    if len(candidates) < 3:
        return sample
    cutoff = float(np.percentile(saturation[candidates], 75))
    saturated = candidates[saturation[candidates] >= cutoff]
    return np.median(pixels[saturated], axis=0) if len(saturated) else sample


def _matches_reference(component, reference):
    """Rejeter seulement une petite composante manifestement étrangère."""
    if component["area"] < max(8, reference["area"] * .06):
        return False
    if min(component["width"], component["height"]) < 2:
        return False
    if not .06 <= component["aspect"] <= 16:
        return False
    if component["area"] < reference["area"] * .75:
        aspect_ratio = component["aspect"] / max(reference["aspect"], 1e-9)
        fill_ratio = component["fill"] / max(reference["fill"], 1e-9)
        if not .72 <= aspect_ratio <= 2.5 or fill_ratio > 2.0:
            return False
    return True


def _nearest_marker_reference(components, sample_point, roi):
    """Trouver la composante représentative proche du pixel réellement cliqué."""
    if not components or sample_point is None:
        return None
    sample = np.asarray(_xy(sample_point), dtype=float)
    search_radius = max(12.0, min(float(roi[2]), float(roi[3])) * .04)
    nearby = []
    for component in components:
        distance = float(np.linalg.norm(np.asarray(component["global_center"]) - sample))
        if distance <= search_radius:
            nearby.append((component["area"], -distance, component))
    if nearby:
        return max(nearby, key=lambda item: (item[0], item[1]))[2]
    return min(
        components,
        key=lambda component: np.linalg.norm(
            np.asarray(component["global_center"]) - sample
        ),
    )


def _typical_marker_reference(components, clicked_reference):
    """Estimer une taille robuste malgré fragments, perspective et quelques amas."""
    if not components:
        return clicked_reference
    areas = np.asarray([component["area"] for component in components], dtype=float)
    upper_area = float(np.median(areas))
    if clicked_reference is not None:
        upper_area = max(upper_area, float(clicked_reference["area"]))
    comparable = [
        component for component in components
        if upper_area * .4 <= component["area"] <= upper_area * 2.5
    ]
    if not comparable:
        comparable = [clicked_reference] if clicked_reference is not None else components
    return {
        key: float(np.median([component[key] for component in comparable]))
        for key in ("area", "width", "height", "aspect", "fill", "compactness", "thickness")
    }


def _split_marker_cluster(labels, component, reference):
    """Extraire des maxima de densité d'un amas sans supposer la forme du marqueur."""
    component_slice = component["slice"]
    binary = labels[component_slice] == component["label"]
    marker_span = max(reference["width"], reference["height"])
    density = ndimage.distance_transform_edt(binary)
    density = ndimage.gaussian_filter(density, sigma=1.0)
    minimum_distance = max(2, int(marker_span * .42))
    local_maximum = ndimage.maximum_filter(
        density, size=2 * minimum_distance + 1, mode="constant"
    )
    minimum_density = max(1.25, reference["thickness"] * .35)
    peak_mask = (density == local_maximum) & (density >= minimum_density)
    peak_labels, peak_count = ndimage.label(peak_mask)
    if peak_count == 0:
        return []
    centers = []
    for peak_index in range(1, peak_count + 1):
        rows, columns = np.nonzero(peak_labels == peak_index)
        weights = density[rows, columns]
        centers.append((
            component_slice[1].start + float(np.average(columns, weights=weights)),
            component_slice[0].start + float(np.average(rows, weights=weights)),
            float(weights.max()),
        ))
    maximum_centers = max(1, int(np.ceil(component["area"] / (reference["area"] * .35))))
    centers = sorted(centers, key=lambda center: center[2], reverse=True)[:maximum_centers]
    return [(center[0], center[1]) for center in centers]


def detect_colored_markers(
    image, roi, sample_rgb, tolerance=65, minimum_area=8, maximum_area=None,
    *, sample_point=None, calibration=None,
):
    """Détecter des marqueurs dans le rectangle choisi, indépendamment de l'échelle.

    Le paramètre calibration est conservé pour les appelants existants ; ses
    graduations ne bornent pas les données et la conversion peut extrapoler.
    """
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] < 3:
        raise ValueError("Une image RVB est attendue.")
    sample = np.asarray(sample_rgb, dtype=float)[:3]
    if sample.shape != (3,) or not np.isfinite(sample).all():
        raise ValueError("La couleur de référence est invalide.")
    x, y, width, height = (int(round(value)) for value in roi)
    x = max(0, x)
    y = max(0, y)
    right = min(array.shape[1], x + max(0, width))
    bottom = min(array.shape[0], y + max(0, height))
    if right - x < 2 or bottom - y < 2:
        raise ValueError("La zone du graphique est vide.")
    sample = _refined_sample(array, sample, sample_point, tolerance)
    crop = array[y:bottom, x:right, :3].astype(np.float32)
    # Comparer les proportions de couleur plutôt que la luminosité brute : une photo de
    # page présente souvent une ombre progressive sur une même série de marqueurs.
    sample_chromaticity = sample / max(float(sample.sum()), 1.0)
    totals = np.maximum(crop.sum(axis=2, keepdims=True), 1.0)
    chromaticity = crop / totals
    distance = np.linalg.norm(chromaticity - sample_chromaticity, axis=2) * 255
    sample_saturation = float(np.linalg.norm(sample_chromaticity - 1 / 3))
    if sample_saturation < .08:
        raise ValueError(
            "La couleur choisie est trop proche du gris. Ajoutez ces points manuellement."
        )
    saturation = np.linalg.norm(chromaticity - 1 / 3, axis=2)
    mask = ((distance <= float(tolerance)) & (saturation >= sample_saturation * .35)
            & (crop.mean(axis=2) >= 12))
    mask = ndimage.binary_closing(mask, structure=np.ones((3, 3), dtype=bool))
    labels, count = ndimage.label(mask)
    if maximum_area is None:
        maximum_area = max(400, int(mask.size * .01))
    slices = ndimage.find_objects(labels)
    clicked_reference = None
    if sample_point is not None:
        sample_x, sample_y = _xy(sample_point)
        sample_column = int(round(sample_x)) - x
        sample_row = int(round(sample_y)) - y
        if not (0 <= sample_column < mask.shape[1] and 0 <= sample_row < mask.shape[0]):
            raise ValueError("Le marqueur choisi doit appartenir à la zone du graphique.")
        reference_label = int(labels[sample_row, sample_column])
        if reference_label and slices[reference_label - 1] is not None:
            clicked_reference = _component_statistics(
                labels, reference_label, slices[reference_label - 1]
            )

    components = []
    for label_index, component_slice in enumerate(slices, start=1):
        if component_slice is None:
            continue
        component = _component_statistics(labels, label_index, component_slice)
        if component["area"] < minimum_area:
            continue
        if min(component["width"], component["height"]) < 2:
            continue
        center = x + component["center"][0], y + component["center"][1]
        component["global_center"] = center
        component["label"] = label_index
        component["slice"] = component_slice
        components.append(component)

    clicked_reference = _nearest_marker_reference(components, sample_point, roi)
    # Les composantes proviennent déjà du recadrage au rectangle utilisateur.
    # Les graduations de calibration définissent seulement la conversion affine.
    effective_reference = _typical_marker_reference(components, clicked_reference)
    result = []
    for component in components:
        if effective_reference is not None and not _matches_reference(component, effective_reference):
            continue
        oversized = effective_reference is not None and (
            component["area"] > effective_reference["area"] * 1.5
            or component["width"] > effective_reference["width"] * 1.6
            or component["height"] > effective_reference["height"] * 1.6
        )
        if not oversized:
            result.append(component["global_center"])
            continue
        centers = _split_marker_cluster(labels, component, effective_reference)
        if len(centers) == 1 and not .25 <= component["aspect"] <= 4:
            continue
        result.extend((x + center[0], y + center[1]) for center in centers)
    return sorted(result, key=lambda point: (point[0], point[1]))
