"""Placer la légende dans la zone la moins occupée du repère visible."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt
from physalix.ui.theme import LIGHT


class SmartLegend(pg.LegendItem):
    def __init__(self, view, series):
        super().__init__(offset=(12, 12), labelTextColor=LIGHT.text,
                         brush=pg.mkBrush(255, 255, 255, 235))
        self.setParentItem(view)
        self.view = view
        self.series = series
        self.manual = False
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.place)
        view.sigRangeChanged.connect(self.schedule)
        view.sigResized.connect(self.schedule)

    def mouseDragEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.manual = True
            self.timer.stop()
        super().mouseDragEvent(event)

    def schedule(self, *args):
        if not self.manual:
            self.timer.start(0)

    def reset_placement(self):
        self.manual = False
        self.schedule()

    def place(self):
        if self.manual or not self.items or not self.isVisible():
            return
        self.layout.activate()
        width, height = self.boundingRect().width(), self.boundingRect().height()
        vw, vh = self.view.width(), self.view.height()
        xmax, ymax = max(12, vw-width-12), max(12, vh-height-12)
        (x0, x1), (y0, y1) = self.view.viewRange()
        if x0 == x1 or y0 == y1:
            return

        def mapped(item):
            x, y = item.getData()
            if x is None or y is None:
                return np.empty((0, 2))
            source = item.getViewBox()
            (x0, x1), (y0, y1) = source.viewRange() if source is not None else self.view.viewRange()
            return np.column_stack(((np.asarray(x)-x0)*vw/(x1-x0),
                                    (y1-np.asarray(y))*vh/(y1-y0)))

        points, segments = [], []
        for series in self.series():
            if not series.visible.isChecked():
                continue
            points.append(mapped(series.points))
            curves = [series.line] if series.line.isVisible() else []
            for fit in series.fits:
                curves.extend(c for c in (fit.curve, fit.extension) if c.isVisible())
            for curve in curves:
                data = mapped(curve)
                if len(data) > 1:
                    segments.append(np.stack((data[:-1], data[1:]), axis=1))
        points = np.concatenate(points) if points else np.empty((0, 2))
        segments = np.concatenate(segments) if segments else np.empty((0, 2, 2))
        # Les NaN séparent notamment les deux prolongements d’une droite.
        segments = segments[np.isfinite(segments).all(axis=(1, 2))]

        def score(x, y):
            low, high = np.array([x-8, y-8]), np.array([x+width+8, y+height+8])
            occupied = np.count_nonzero(((points >= low) & (points <= high)).all(axis=1))
            # Intersection segment/rectangle par découpage paramétrique, sans échantillonnage.
            if len(segments):
                start, delta = segments[:, 0], segments[:, 1]-segments[:, 0]
                parallel = delta == 0
                safe_delta = np.where(parallel, 1, delta)
                a, b = (low-start)/safe_delta, (high-start)/safe_delta
                enter = np.where(parallel, -np.inf, np.minimum(a, b)).max(axis=1)
                leave = np.where(parallel, np.inf, np.maximum(a, b)).min(axis=1)
                outside = (parallel & ((start < low) | (start > high))).any(axis=1)
                occupied += np.count_nonzero(~outside & (np.maximum(enter, 0) <= np.minimum(leave, 1)))
            return occupied

        # Les coins sont privilégiés ; une grille permet aussi de trouver un vide intérieur.
        candidates = [(12, 12), (xmax, 12), (12, ymax), (xmax, ymax)]
        candidates += [(x, y) for y in np.linspace(12, ymax, 15)
                       for x in np.linspace(12, xmax, 15)]
        best, best_score = candidates[0], float('inf')
        for candidate in candidates:
            count = score(*candidate)
            if count < best_score:
                best, best_score = candidate, count
            if count == 0:
                break
        self.anchor(itemPos=(0, 0), parentPos=(0, 0), offset=best)
