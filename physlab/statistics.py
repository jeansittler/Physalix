"""Statistiques descriptives d'une grandeur, sans modifier les mesures."""

from math import ceil, fsum, isfinite, sqrt
import statistics

from physlab.calculations import number


# Clé, libellé, puissance de l'unité, définition et effectif minimum.
METRICS = (
    ("count", "Effectif n", 0, "Nombre de valeurs numériques finies retenues.", 0),
    ("mean", "Moyenne", 1, "Somme des valeurs divisée par n.", 1),
    ("stddev", "Écart-type de la série σ", 1, "Racine de la variance de la série (diviseur n).", 1),
    ("sample_stddev", "Écart-type corrigé s", 1, "Estimation de l'écart-type d'une population à partir d'un échantillon (n − 1).", 2),
    ("sem", "Incertitude-type A de la moyenne", 1, "s / √n ; mesures répétées indépendantes d'une même grandeur.", 2),
    ("median", "Médiane", 1, "Valeur centrale ; moyenne des deux valeurs centrales si n est pair.", 1),
    ("minimum", "Minimum", 1, "Plus petite valeur.", 1),
    ("maximum", "Maximum", 1, "Plus grande valeur.", 1),
    ("range", "Étendue", 1, "Maximum − minimum.", 1),
    ("q1", "Premier quartile Q1", 1, "Valeur de rang ⌈n/4⌉ dans la série triée (rangs à partir de 1).", 1),
    ("q3", "Troisième quartile Q3", 1, "Valeur de rang ⌈3n/4⌉ dans la série triée (rangs à partir de 1).", 1),
    ("iqr", "Écart interquartile", 1, "Q3 − Q1.", 1),
    ("variance", "Variance de la série", 2, "Σ(xᵢ − moyenne)² / n.", 1),
    ("sample_variance", "Variance corrigée", 2, "Σ(xᵢ − moyenne)² / (n − 1) ; au moins 2 valeurs.", 2),
    ("sum", "Somme", 1, "Somme des valeurs retenues.", 1),
)


def describe(rows, column, first=1, last=None):
    """Bornes inclusives, numérotation des mesures visible dans le tableur."""
    last = len(rows) if last is None else last
    if first < 1 or last < first or last > len(rows):
        raise ValueError("Choisissez un intervalle de lignes valide (début ≤ fin).")
    values, blanks, invalid = [], 0, 0
    for row in rows[first - 1:last]:
        text = row[column]
        if not str(text).strip():
            blanks += 1
            continue
        value = number(text)
        if value is None:
            invalid += 1
        else:
            values.append(value)
    values.sort()
    n = len(values)
    results = {key: None for key, *_ in METRICS}
    results["count"] = n
    overflow = set()
    if n:
        q1, q3 = values[ceil(n / 4) - 1], values[ceil(3 * n / 4) - 1]
        operations = {
            "mean": lambda: statistics.mean(values),
            "median": lambda: statistics.mean(values[(n - 1) // 2:n // 2 + 1]),
            "minimum": lambda: values[0], "maximum": lambda: values[-1],
            "range": lambda: values[-1] - values[0],
            "q1": lambda: q1, "q3": lambda: q3, "iqr": lambda: q3 - q1,
            "variance": lambda: statistics.pvariance(values),
            "stddev": lambda: statistics.pstdev(values),
            "sum": lambda: fsum(values),
        }
        if n >= 2:
            operations.update(sample_variance=lambda: statistics.variance(values),
                              sample_stddev=lambda: statistics.stdev(values),
                              sem=lambda: statistics.stdev(values) / sqrt(n))
        for key, operation in operations.items():
            try:
                value = operation()
                if not isfinite(value):
                    raise OverflowError()
                results[key] = value
            except (OverflowError, ArithmeticError):
                overflow.add(key)
    return results, blanks, invalid, overflow
