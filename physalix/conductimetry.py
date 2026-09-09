"""Intersection de deux ajustements affines pour un titrage conductimétrique."""
from dataclasses import dataclass
import numpy as np


@dataclass
class AffineBranch:
    slope: float
    intercept: float
    center_x: float
    center_y: float
    count: int
    r2: float | None
    bounds: tuple

    def at(self, x):
        return self.center_y + self.slope * (np.asarray(x) - self.center_x)


@dataclass
class ConductimetryResult:
    branches: tuple
    volume: float
    ordinate: float
    warning: str


def fit_equivalence(xs, ys, first, second):
    x, y = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    if x.ndim != 1 or x.shape != y.shape or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("Les mesures doivent être des couples de nombres finis.")
    if not all(np.isfinite(v) for v in (*first, *second)) or not first[0] < first[1] < second[0] < second[1]:
        raise ValueError("Les zones doivent être distinctes et ordonnées : zone 1 à gauche, zone 2 à droite.")
    branches = []
    for number, bounds in enumerate((first, second), 1):
        keep = (x >= bounds[0]) & (x <= bounds[1])
        vx, vy = x[keep], y[keep]
        if len(vx) < 2 or len(np.unique(vx)) < 2:
            raise ValueError(f"Zone {number} : choisissez au moins deux points de volumes distincts.")
        center_x, center_y = float(np.mean(vx)), float(np.mean(vy))
        scale = float(np.max(np.abs(vx - center_x)))
        dx = (vx - center_x) / scale
        slope = float(np.dot(dx, vy - center_y) / np.dot(dx, dx) / scale)
        residual = vy - (center_y + slope * (vx - center_x))
        total = float(np.sum((vy - center_y)**2))
        r2 = 1 - float(np.dot(residual, residual)) / total if total > 0 else None
        branches.append(AffineBranch(slope, center_y - slope * center_x, center_x, center_y,
                                     len(vx), r2, tuple(bounds)))
    a, b = branches
    difference = a.slope - b.slope
    if abs(difference) <= 1e-8 * max(abs(a.slope), abs(b.slope), np.finfo(float).tiny):
        raise ValueError("Les droites sont parallèles ou presque parallèles : intersection non déterminable de façon fiable.")
    reference = a.center_x / 2 + b.center_x / 2
    volume = float(reference + (b.at(reference) - a.at(reference)) / difference)
    ordinate = float(a.at(volume))
    if not all(np.isfinite(v) for v in (volume, ordinate, a.slope, b.slope, a.intercept, b.intercept)):
        raise ValueError("Ces valeurs dépassent la plage de calcul numérique.")
    warnings = []
    if not first[1] <= volume <= second[0]:
        warnings.append("Intersection hors de l'espace entre les deux zones : vérifiez les portions choisies.")
    if min(a.count, b.count) == 2:
        warnings.append("Une zone ne contient que deux points : ajoutez des mesures pour évaluer la qualité de l'ajustement.")
    return ConductimetryResult(tuple(branches), volume, ordinate, " ".join(warnings))
