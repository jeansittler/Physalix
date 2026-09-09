"""Tangente à une interpolation PCHIP et paliers des modèles usuels."""
import numpy as np
from scipy.interpolate import PchipInterpolator


def curve_interpolator(xs, ys):
    x, y = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    if x.ndim != 1 or x.shape != y.shape or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('La courbe doit contenir des couples de valeurs finies.')
    order = np.argsort(x)
    x, y = x[order], y[order]
    if len(x) < 2 or np.any(np.diff(x) <= 0):
        raise ValueError('Pour la tangente, il faut au moins deux abscisses distinctes, sans doublon.')
    return PchipInterpolator(x, y, extrapolate=False)


def tangent_at(curve, x):
    if not np.isfinite(x) or not curve.x[0] <= x <= curve.x[-1]:
        raise ValueError('Choisissez une abscisse dans le domaine de la courbe.')
    y, slope = float(curve(x)), float(curve.derivative()(x))
    if not np.isfinite([y, slope]).all():
        raise ValueError('La tangente ne peut pas être calculée à cette abscisse.')
    return y, slope


def model_plateau(kind, parameters):
    """Limite en +∞, uniquement lorsque la forme du modèle la garantit."""
    if kind == 'charge' and parameters.get('tau', 0) > 0:
        value = parameters['c'] + parameters['A']
    elif kind == 'discharge' and parameters.get('tau', 0) > 0:
        value = parameters['c']
    elif kind == 'exponential' and parameters.get('k', 0) < 0:
        value = parameters['c']
    elif kind == 'constant':
        value = parameters['c']
    else:
        return None
    return float(value) if np.isfinite(value) else None
