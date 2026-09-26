"""Suivi local conservateur d'un gabarit vidéo, sans dépendance supplémentaire."""

from dataclasses import dataclass
from math import ceil

import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage


def grayscale(image):
    """Return a compact grayscale array from a QImage or an array."""
    if isinstance(image, QImage):
        converted = image.convertToFormat(QImage.Format.Format_Grayscale8)
        view = np.frombuffer(converted.bits(), dtype=np.uint8,
                             count=converted.sizeInBytes())
        return view.reshape(converted.height(), converted.bytesPerLine())[
            :, :converted.width()].copy()
    array = np.asarray(image)
    if array.ndim != 2:
        raise ValueError("Une image en niveaux de gris est attendue.")
    return array.astype(np.uint8, copy=False)


def _correlation(template, patch):
    left = template.astype(np.float32)
    right = patch.astype(np.float32)
    left -= left.mean()
    right -= right.mean()
    denominator = float(np.sqrt(np.sum(left * left) * np.sum(right * right)))
    return float(np.sum(left * right) / denominator) if denominator > 1e-6 else -1.0


@dataclass(frozen=True)
class Match:
    point: QPointF
    score: float


class AutomaticTracker:
    """Track a fixed-size patch and therefore a stable reference within the object."""

    minimum_score = .70
    minimum_initial_score = .45
    minimum_margin = .025

    def __init__(self, image, rectangle):
        frame = grayscale(image)
        bounds = QRectF(rectangle).normalized()
        x = max(0, int(round(bounds.x())))
        y = max(0, int(round(bounds.y())))
        width = min(frame.shape[1] - x, int(round(bounds.width())))
        height = min(frame.shape[0] - y, int(round(bounds.height())))
        if width < 6 or height < 6:
            raise ValueError("Encadrez une zone d'au moins 6 × 6 pixels.")
        self.x, self.y, self.width, self.height = x, y, width, height
        self.reference_x, self.reference_y = width / 2, height / 2
        self.initial = frame[y:y + height, x:x + width].copy()
        self.template = self.initial.copy()
        if float(self.template.std()) < 4:
            raise ValueError("La zone sélectionnée manque de détails pour être suivie de façon fiable.")

    @property
    def point(self):
        return QPointF(self.x + self.reference_x, self.y + self.reference_y)

    @property
    def rectangle(self):
        return QRectF(self.x, self.y, self.width, self.height)

    def reanchor(self, image, point):
        """Keep the box dimensions, but place its physical reference on ``point``."""
        frame = grayscale(image)
        x = int(round(point.x() - self.width / 2))
        y = int(round(point.y() - self.height / 2))
        x = max(0, min(x, frame.shape[1] - self.width))
        y = max(0, min(y, frame.shape[0] - self.height))
        self.x, self.y = x, y
        self.reference_x = max(0, min(float(point.x() - x), self.width))
        self.reference_y = max(0, min(float(point.y() - y), self.height))
        self.template = frame[y:y + self.height, x:x + self.width].copy()
        self.initial = self.template.copy()

    def locate(self, image):
        frame = grayscale(image)
        radius = max(12, int(round(max(self.width, self.height) * 1.25)))
        min_x = max(0, self.x - radius)
        max_x = min(frame.shape[1] - self.width, self.x + radius)
        min_y = max(0, self.y - radius)
        max_y = min(frame.shape[0] - self.height, self.y + radius)
        if min_x > max_x or min_y > max_y:
            return None

        step = max(1, int(ceil(max(self.width, self.height) / 48)))
        xs = list(range(min_x, max_x + 1, step))
        ys = list(range(min_y, max_y + 1, step))
        if xs[-1] != max_x:
            xs.append(max_x)
        if ys[-1] != max_y:
            ys.append(max_y)
        sample = max(1, int(ceil(max(self.width, self.height) / 64)))
        sampled_template = self.template[::sample, ::sample]
        scores = np.empty((len(ys), len(xs)), dtype=np.float32)
        for row, y in enumerate(ys):
            for column, x in enumerate(xs):
                patch = frame[y:y + self.height:sample, x:x + self.width:sample]
                scores[row, column] = _correlation(sampled_template, patch)

        best_row, best_column = np.unravel_index(int(np.argmax(scores)), scores.shape)
        coarse_x, coarse_y = xs[best_column], ys[best_row]
        masked = scores.copy()
        neighborhood = max(2, min(self.width, self.height) // (4 * step))
        masked[max(0, best_row - neighborhood):best_row + neighborhood + 1,
               max(0, best_column - neighborhood):best_column + neighborhood + 1] = -1
        second = float(masked.max()) if masked.size > 9 else -1.0

        best_x, best_y, best_score = coarse_x, coarse_y, -1.0
        for y in range(max(min_y, coarse_y - step), min(max_y, coarse_y + step) + 1):
            for x in range(max(min_x, coarse_x - step), min(max_x, coarse_x + step) + 1):
                patch = frame[y:y + self.height:sample, x:x + self.width:sample]
                score = _correlation(sampled_template, patch)
                if score > best_score:
                    best_x, best_y, best_score = x, y, score

        patch = frame[best_y:best_y + self.height, best_x:best_x + self.width]
        initial_score = _correlation(self.initial[::sample, ::sample], patch[::sample, ::sample])
        unambiguous = best_score >= .92 or best_score - second >= self.minimum_margin
        if (best_score < self.minimum_score or initial_score < self.minimum_initial_score
                or not unambiguous):
            return None

        self.x, self.y = best_x, best_y
        if best_score >= .85:
            self.template = np.rint(.9 * self.template + .1 * patch).astype(np.uint8)
        return Match(self.point, best_score)
