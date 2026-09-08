"""Construction des tangentes parallèles sur une interpolation PCHIP des mesures."""
from dataclasses import dataclass
import numpy as np
from scipy.interpolate import PchipInterpolator, PPoly


@dataclass
class TangentResult:
    curve: object
    slope: float
    contacts: tuple
    intercepts: tuple
    volume: float
    ph: float


def parallel_tangents(x, y, fraction=0.25, interval=None):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.shape != y.shape or x.ndim != 1 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("Les mesures doivent être des couples de nombres finis.")
    order = np.argsort(x)
    x, y = x[order], y[order]
    if interval is not None:
        keep = (x >= min(interval)) & (x <= max(interval))
        x, y = x[keep], y[keep]
    if len(x) < 7:
        raise ValueError("Il faut au moins 7 mesures dans la zone étudiée, de part et d’autre du saut.")
    if np.any(np.diff(x) <= 0):
        raise ValueError("Chaque volume doit être unique : corrigez les volumes en double.")
    if not 0 < fraction < 1:
        raise ValueError("L’inclinaison doit être comprise entre 0 et 100 %.")
    curve = PchipInterpolator(x, y, extrapolate=False)
    derivative = curve.derivative()
    candidates = np.r_[x, derivative.derivative().roots(extrapolate=False)]
    candidates = candidates[np.isfinite(candidates)]
    peak = candidates[np.argmax(np.abs(derivative(candidates)))]
    slope = float(derivative(peak)) * fraction
    roots = derivative.solve(slope, extrapolate=False)
    roots = roots[np.isfinite(roots)]
    left, right = roots[roots < peak], roots[roots > peak]
    if not len(left) or not len(right) or abs(slope) < 1e-12:
        raise ValueError("Deux tangentes ne peuvent pas encadrer le saut. Élargissez la zone ou ajustez l’inclinaison.")
    a, b = float(max(left)), float(min(right))
    intercepts = (float(curve(a)-slope*a), float(curve(b)-slope*b))
    coefficients = curve.c.copy()
    coefficients[-2] -= slope
    coefficients[-1] -= slope*curve.x[:-1] + np.mean(intercepts)
    crossings = PPoly(coefficients, curve.x, extrapolate=False).roots(extrapolate=False)
    crossings = crossings[np.isfinite(crossings) & (crossings > a) & (crossings < b)]
    if len(crossings) != 1 or abs(intercepts[0]-intercepts[1]) < 1e-10:
        raise ValueError("Intersection ambiguë : isolez un seul saut et ajustez l’inclinaison.")
    volume = float(crossings[0])
    return TangentResult(curve, slope, (a, b), intercepts, volume, float(curve(volume)))
