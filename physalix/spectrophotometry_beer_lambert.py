"""Calculs et données du mode Beer-Lambert, indépendants de Qt."""

from __future__ import annotations

from dataclasses import dataclass
import math

from physalix.spectrophotometry import AbsorbanceSpectrum


CONCENTRATION_UNITS = ("mol/L", "mmol/L", "g/L", "mg/L")


class BeerLambertError(ValueError):
    """Données insuffisantes ou numériquement impropres au calcul."""


def parse_concentration(text: str) -> float:
    """Lire une concentration positive ou nulle avec virgule française."""

    if not isinstance(text, str):
        raise BeerLambertError("La concentration doit être saisie sous forme de texte.")
    normalized = text.strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        value = float(normalized)
    except ValueError:
        raise BeerLambertError("La concentration saisie n'est pas un nombre valide.") from None
    if not math.isfinite(value):
        raise BeerLambertError("La concentration doit être finie.")
    if value < 0:
        raise BeerLambertError("La concentration ne peut pas être négative.")
    return value


@dataclass
class BeerLambertStandard:
    """Solution étalon et mesure spectrale complète qui lui est associée."""

    identifier: str
    name: str
    concentration: float
    spectrum: AbsorbanceSpectrum | None = None

    def __post_init__(self):
        if not isinstance(self.identifier, str) or not self.identifier:
            raise BeerLambertError("L'identifiant de l'étalon est invalide.")
        self.name = self.name.strip()
        if not self.name:
            raise BeerLambertError("Le nom de l'étalon est obligatoire.")
        if not isinstance(self.concentration, (int, float)):
            raise BeerLambertError("La concentration de l'étalon est invalide.")
        self.concentration = float(self.concentration)
        if not math.isfinite(self.concentration) or self.concentration < 0:
            raise BeerLambertError(
                "La concentration de l'étalon doit être finie et positive ou nulle."
            )
        if self.spectrum is not None and not isinstance(
            self.spectrum, AbsorbanceSpectrum
        ):
            raise TypeError("spectrum doit être un AbsorbanceSpectrum ou None.")


@dataclass(frozen=True)
class BeerLambertRegression:
    slope: float
    intercept: float
    r_squared: float | None
    concentration_min: float
    concentration_max: float
    point_count: int

    @property
    def two_point_only(self) -> bool:
        return self.point_count == 2


@dataclass(frozen=True)
class UnknownConcentration:
    absorbance: float
    concentration: float
    extrapolated: bool


def fit_beer_lambert(points) -> BeerLambertRegression:
    """Ajuster ``A = k*c`` et calculer le R² centré usuel.

    Le coefficient de détermination utilise ``1-SSE/SST``, avec SST calculée
    autour de la moyenne des absorbances observées. Il peut donc être négatif
    pour un modèle contraint médiocre et reste indéfini si SST est nul.
    """

    values = tuple((float(x), float(y)) for x, y in points)
    if len(values) < 2:
        raise BeerLambertError("Au moins deux points valides sont nécessaires.")
    if any(
        not math.isfinite(x) or not math.isfinite(y) or x < 0
        for x, y in values
    ):
        raise BeerLambertError("Les couples Beer-Lambert doivent être finis.")

    xs = tuple(x for x, _ in values)
    ys = tuple(y for _, y in values)
    x_min, x_max = min(xs), max(xs)
    if x_min == x_max:
        raise BeerLambertError("Les concentrations doivent être distinctes.")

    y_mean = sum(ys) / len(ys)
    xx = sum(x * x for x in xs)
    xy = sum(x * y for x, y in values)
    slope = xy / xx
    intercept = 0.0

    y_span = max(ys) - min(ys)
    numerical_scale = max(abs(y) for y in ys) / (x_max - x_min)
    slope_tolerance = max(1e-15, numerical_scale * 1e-12)
    if not math.isfinite(slope) or slope <= slope_tolerance or y_span == 0:
        raise BeerLambertError(
            "La pente est négative, nulle ou trop faible pour être exploitable."
        )

    residual_sum = sum((y - (slope * x + intercept)) ** 2 for x, y in values)
    total_sum = sum((y - y_mean) ** 2 for y in ys)
    r_squared = None if total_sum <= 0 else 1.0 - residual_sum / total_sum
    return BeerLambertRegression(
        slope=slope,
        intercept=intercept,
        r_squared=r_squared,
        concentration_min=x_min,
        concentration_max=x_max,
        point_count=len(values),
    )


def calculate_unknown_concentration(
    absorbance: float, regression: BeerLambertRegression
) -> UnknownConcentration:
    """Calculer ``c = A/k`` sans masquer un résultat non physique."""

    if not isinstance(regression, BeerLambertRegression):
        raise TypeError("regression doit être un BeerLambertRegression.")
    absorbance = float(absorbance)
    if not math.isfinite(absorbance):
        raise BeerLambertError("L'absorbance de l'inconnue doit être finie.")
    if not math.isfinite(regression.slope) or regression.slope == 0:
        raise BeerLambertError("La régression ne permet pas de calculer l'inconnue.")
    concentration = absorbance / regression.slope
    if not math.isfinite(concentration):
        raise BeerLambertError("La concentration calculée n'est pas finie.")
    if concentration < 0:
        raise BeerLambertError("La concentration calculée est négative et non physique.")
    return UnknownConcentration(
        absorbance=absorbance,
        concentration=concentration,
        extrapolated=(
            concentration < regression.concentration_min
            or concentration > regression.concentration_max
        ),
    )


_SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def format_concentration(value: float, significant_digits: int = 4) -> str:
    """Formater une concentration pour l'écran sans modifier sa valeur."""

    value = float(value)
    if not math.isfinite(value):
        raise BeerLambertError("La concentration à afficher doit être finie.")
    if value == 0:
        return "0"
    absolute = abs(value)
    if absolute < 1e-3 or absolute >= 1e4:
        exponent = math.floor(math.log10(absolute))
        mantissa = value / (10**exponent)
        scientific_digits = min(significant_digits, 2)
        text = f"{mantissa:.{scientific_digits - 1}f}".replace(".", ",")
        return f"{text} × 10{str(exponent).translate(_SUPERSCRIPT)}"
    return format(value, f".{significant_digits}g").replace(".", ",")


def format_absorbance(value: float) -> str:
    """Limiter l'affichage d'une absorbance à quatre chiffres significatifs."""

    value = float(value)
    if not math.isfinite(value):
        raise BeerLambertError("L'absorbance à afficher doit être finie.")
    value = 0.0 if value == 0 else value
    return format(value, ".4g").replace(".", ",")


def band_absorbance(spectrum: AbsorbanceSpectrum | None, band_index: int):
    """Retourner l'absorbance expérimentale valide d'une des huit bandes."""

    if spectrum is None:
        return None
    if not isinstance(spectrum, AbsorbanceSpectrum):
        raise TypeError("spectrum doit être un AbsorbanceSpectrum ou None.")
    if type(band_index) is not int or not 0 <= band_index < 8:
        raise BeerLambertError("La bande spectrale doit être comprise entre F1 et F8.")
    band = spectrum.bands[band_index]
    return band.absorbance if band.is_valid else None
