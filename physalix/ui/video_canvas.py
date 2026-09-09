"""Affichage et pointage dans les coordonnées de l'image, hors bandes noires."""

from math import atan2, cos, sin

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget


def arrow(painter, start, end, color):
    painter.setPen(QPen(QColor(color), 2))
    painter.drawLine(start, end)
    angle = atan2(end.y() - start.y(), end.x() - start.x())
    for offset in (-.5, .5):
        painter.drawLine(end, end - QPointF(10 * cos(angle + offset), 10 * sin(angle + offset)))


class VideoCanvas(QWidget):
    clicked = Signal(QPointF)
    point_selected = Signal(int)
    hovered = Signal(object)

    def __init__(self):
        super().__init__()
        self.pixmap = QPixmap()
        self.origin = None
        self.x_direction = 1
        self.y_direction = 1
        self.ruler = None
        self.anchor = None
        self.calibration_direction = "horizontal"
        self.pointer = None
        self.point = None
        self.points = {}
        self.highlight_index = None
        self.selecting = False
        self.active = False
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMouseTracking(True)

    def image_rect(self):
        if self.pixmap.isNull():
            return QRectF()
        scale = min(self.width() / self.pixmap.width(), self.height() / self.pixmap.height())
        width, height = self.pixmap.width() * scale, self.pixmap.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def image_point(self, position):
        rect = self.image_rect()
        if rect.isEmpty() or not rect.contains(position):
            return None
        return QPointF((position.x() - rect.x()) * self.pixmap.width() / rect.width(),
                       (position.y() - rect.y()) * self.pixmap.height() / rect.height())

    def screen_point(self, point):
        rect = self.image_rect()
        return QPointF(rect.x() + point.x() * rect.width() / self.pixmap.width(),
                       rect.y() + point.y() * rect.height() / self.pixmap.height())

    def setPixmap(self, pixmap):
        self.pixmap = pixmap
        self.pointer = None
        self.hovered.emit(None)
        self.update()

    def mouseMoveEvent(self, event):
        self.pointer = self.image_point(event.position())
        self.hovered.emit(self.calibration_point(self.pointer))
        self.update()

    def calibration_point(self, point):
        """Même extrémité contrainte pour l'aperçu, la loupe et la mesure."""
        if point is None or self.anchor is None:
            return point
        if self.calibration_direction == "horizontal":
            return QPointF(point.x(), self.anchor.y())
        if self.calibration_direction == "vertical":
            return QPointF(self.anchor.x(), point.y())
        return point

    def leaveEvent(self, event):
        self.pointer = None
        self.hovered.emit(None)
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.active:
            point = self.image_point(event.position())
            if point is not None:
                if self.selecting:
                    index = self.point_at(event.position())
                    if index is not None:
                        self.point_selected.emit(index)
                else:
                    self.clicked.emit(point)

    def point_at(self, position):
        """Sélection à distance constante à l'écran, quel que soit le zoom."""
        if self.pixmap.isNull() or self.image_point(position) is None:
            return None
        candidates = []
        for index, point in self.points.items():
            delta = self.screen_point(point) - position
            distance = delta.x() ** 2 + delta.y() ** 2
            if distance <= 10 ** 2:
                candidates.append((distance, index))
        return min(candidates)[1] if candidates else None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#151922"))
        if self.pixmap.isNull():
            painter.setPen(QColor("#d7dce5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Aucune vidéo ouverte")
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.image_rect(), self.pixmap, QRectF(self.pixmap.rect()))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, point in self.points.items():
            if index == self.highlight_index:
                continue
            center = self.screen_point(point)
            painter.setPen(QPen(QColor(0, 0, 0, 100), 3))
            painter.drawEllipse(center, 3, 3)
            painter.setPen(QPen(QColor(255, 170, 190, 155), 1.2))
            painter.drawEllipse(center, 3, 3)
        if self.ruler:
            arrow(painter, *(self.screen_point(p) for p in self.ruler), "#ffc857")
        if self.anchor is not None and self.pointer is not None:
            arrow(painter, self.screen_point(self.anchor), self.screen_point(self.calibration_point(self.pointer)), "#ffc857")
        if self.origin is not None:
            start = self.screen_point(self.origin)
            arrow(painter, start, start + QPointF(45 * self.x_direction, 0), "#54e1ba")
            arrow(painter, start, start + QPointF(0, -45 * self.y_direction), "#54e1ba")
            painter.drawText(start + QPointF(47 if self.x_direction == 1 else -56, 5), "x")
            painter.drawText(start + QPointF(5, -47 if self.y_direction == 1 else 57), "y")
            painter.drawText(start + QPointF(-13 * self.x_direction, 17 * self.y_direction), "O")
        if self.point is not None:
            center = self.screen_point(self.point)
            painter.setPen(QPen(QColor(0, 0, 0, 180), 4))
            painter.drawEllipse(center, 5, 5)
            painter.setPen(QPen(QColor("#ff6584"), 2))
            painter.drawEllipse(center, 5, 5)
        if self.active and not self.selecting and self.pointer is not None:
            center = self.screen_point(self.calibration_point(self.pointer))
            for color, width in (("#000000", 3), ("#ffffff", 1)):
                painter.setPen(QPen(QColor(color), width))
                painter.drawEllipse(center, 7, 7)
                painter.drawLine(center - QPointF(13, 0), center + QPointF(13, 0))
                painter.drawLine(center - QPointF(0, 13), center + QPointF(0, 13))


class Magnifier(QWidget):
    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.point = None
        self.setFixedSize(140, 140)
        canvas.hovered.connect(self.set_point)

    def set_point(self, point):
        self.point = point
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#151922"))
        if self.point is None or self.canvas.pixmap.isNull():
            painter.setPen(QColor("#d7dce5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Loupe ×6\nSurvolez l'image")
            return
        painter.save()
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(6, 6)
        painter.translate(-self.point.x(), -self.point.y())
        painter.drawPixmap(0, 0, self.canvas.pixmap)
        painter.restore()
        center = QPointF(self.width() / 2, self.height() / 2)
        for color, width in (("#000000", 3), ("#ffffff", 1)):
            painter.setPen(QPen(QColor(color), width))
            painter.drawLine(center - QPointF(18, 0), center + QPointF(18, 0))
            painter.drawLine(center - QPointF(0, 18), center + QPointF(0, 18))
