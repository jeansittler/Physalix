"""Canevas interactif dédié à la numérisation d'un graphique statique."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class GraphImageCanvas(QWidget):
    rectangle_selected = Signal(QRectF)
    image_clicked = Signal(QPointF)
    point_selected = Signal(int)
    point_moved = Signal(int, QPointF)
    color_selected = Signal(QColor, QPointF)
    pointer_moved = Signal(object)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.image = QImage()
        self.mode = "pan"
        self.zoom = 1.0
        self.pan = QPointF()
        self.pointer = None
        self.drag_start = None
        self.pan_start = None
        self.selection_rect = None
        self.dragged_point = None
        self.selected_point = None
        self.setMinimumSize(420, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_image(self, image):
        self.image = QImage(image)
        self.fit_to_window()

    def set_mode(self, mode):
        self.mode = mode
        self.drag_start = None
        self.selection_rect = None
        self.setCursor(Qt.CursorShape.OpenHandCursor if mode == "pan" else Qt.CursorShape.CrossCursor)
        self.update()

    def fit_to_window(self):
        self.zoom = 1.0
        self.pan = QPointF()
        self.update()

    def fit_scale(self):
        if self.image.isNull():
            return 1.0
        return min(self.width() / self.image.width(), self.height() / self.image.height())

    def image_rect(self):
        if self.image.isNull():
            return QRectF()
        scale = self.fit_scale() * self.zoom
        width, height = self.image.width() * scale, self.image.height() * scale
        center = QPointF(self.width() / 2, self.height() / 2) + self.pan
        return QRectF(center.x() - width / 2, center.y() - height / 2, width, height)

    def image_point(self, position, clamp=False):
        rectangle = self.image_rect()
        if rectangle.isEmpty():
            return None
        if not clamp and not rectangle.contains(position):
            return None
        x = (position.x() - rectangle.left()) * self.image.width() / rectangle.width()
        y = (position.y() - rectangle.top()) * self.image.height() / rectangle.height()
        if clamp:
            x = min(max(x, 0.0), self.image.width() - 1.0)
            y = min(max(y, 0.0), self.image.height() - 1.0)
        return QPointF(x, y)

    def screen_point(self, point):
        x, y = (point.x(), point.y()) if hasattr(point, "x") else point
        rectangle = self.image_rect()
        return QPointF(rectangle.left() + x * rectangle.width() / self.image.width(),
                       rectangle.top() + y * rectangle.height() / self.image.height())

    def wheelEvent(self, event):
        if self.image.isNull():
            return
        before = self.image_point(event.position())
        if before is None:
            return
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        new_zoom = min(20.0, max(1.0, self.zoom * factor))
        if new_zoom == self.zoom:
            return
        self.zoom = new_zoom
        after_screen = self.screen_point(before)
        self.pan += event.position() - after_screen
        self.update()

    def point_at(self, position):
        candidates = []
        for point in self.session.points:
            delta = self.screen_point(point.pixel) - position
            distance = delta.x() ** 2 + delta.y() ** 2
            if distance <= 11 ** 2:
                candidates.append((distance, point.identifier))
        return min(candidates)[1] if candidates else None

    def constrain_to_roi(self, point):
        if point is None or self.session.roi is None:
            return point
        x, y, width, height = self.session.roi
        return QPointF(min(max(point.x(), x), x + width),
                       min(max(point.y(), y), y + height))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.image.isNull():
            return
        self.setFocus()
        if self.mode == "pan":
            self.pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        point = self.image_point(event.position())
        if point is None:
            return
        if self.mode == "roi":
            self.drag_start = point
            self.selection_rect = QRectF(point, point)
        elif self.mode == "edit":
            identifier = self.point_at(event.position())
            self.selected_point = identifier
            self.dragged_point = identifier
            if identifier is not None:
                self.point_selected.emit(identifier)
        elif self.mode == "color":
            color = self.image.pixelColor(int(point.x()), int(point.y()))
            self.color_selected.emit(color, point)
        else:
            self.image_clicked.emit(point)
        self.update()

    def mouseMoveEvent(self, event):
        self.pointer = self.image_point(event.position())
        self.pointer_moved.emit(self.pointer)
        if self.pan_start is not None:
            self.pan += event.position() - self.pan_start
            self.pan_start = event.position()
        elif self.drag_start is not None and self.mode == "roi":
            point = self.image_point(event.position(), clamp=True)
            self.selection_rect = QRectF(self.drag_start, point).normalized()
        elif self.dragged_point is not None and self.mode == "edit":
            point = self.constrain_to_roi(self.image_point(event.position(), clamp=True))
            stored = self.session.point(self.dragged_point)
            if stored is not None and point is not None:
                stored.pixel = (point.x(), point.y())
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.pan_start is not None:
            self.pan_start = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif self.drag_start is not None:
            point = self.image_point(event.position(), clamp=True)
            rectangle = QRectF(self.drag_start, point).normalized() if point is not None else QRectF()
            self.drag_start = None
            self.selection_rect = None
            if rectangle.width() >= 2 and rectangle.height() >= 2:
                self.rectangle_selected.emit(rectangle)
        elif self.dragged_point is not None:
            identifier = self.dragged_point
            self.dragged_point = None
            stored = self.session.point(identifier)
            if stored is not None:
                self.point_moved.emit(identifier, QPointF(*stored.pixel))
        self.update()

    def leaveEvent(self, event):
        self.pointer = None
        self.pointer_moved.emit(None)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#151922"))
        if self.image.isNull():
            painter.setPen(QColor("#d7dce5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Ouvrez une image JPEG ou PNG pour commencer")
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.image_rect(), self.image, QRectF(self.image.rect()))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.session.roi is not None:
            x, y, width, height = self.session.roi
            rectangle = QRectF(self.screen_point((x, y)), self.screen_point((x + width, y + height)))
            painter.setPen(QPen(QColor("#54e1ba"), 2))
            painter.drawRect(rectangle)
        if self.selection_rect is not None:
            rectangle = QRectF(self.screen_point(self.selection_rect.topLeft()),
                               self.screen_point(self.selection_rect.bottomRight())).normalized()
            painter.setPen(QPen(QColor("#54e1ba"), 2, Qt.PenStyle.DashLine))
            painter.drawRect(rectangle)
        for color, marks in (("#ffc857", self.session.x_marks), ("#5cc8ff", self.session.y_marks)):
            painter.setPen(QPen(QColor(color), 2))
            for mark in marks:
                center = self.screen_point(mark.pixel)
                painter.drawLine(center - QPointF(8, 0), center + QPointF(8, 0))
                painter.drawLine(center - QPointF(0, 8), center + QPointF(0, 8))
        for point in self.session.points:
            center = self.screen_point(point.pixel)
            color = QColor("#54e1ba" if point.validated else "#ffc857")
            if point.identifier == self.selected_point:
                painter.setPen(QPen(QColor("#ffffff"), 5))
                painter.drawEllipse(center, 6, 6)
            painter.setPen(QPen(QColor(0, 0, 0, 170), 4))
            painter.drawEllipse(center, 5, 5)
            painter.setPen(QPen(color, 2))
            painter.drawEllipse(center, 5, 5)
        if self.pointer is not None and self.mode != "pan":
            center = self.screen_point(self.pointer)
            for color, width in (("#000000", 3), ("#ffffff", 1)):
                painter.setPen(QPen(QColor(color), width))
                painter.drawLine(center - QPointF(10, 0), center + QPointF(10, 0))
                painter.drawLine(center - QPointF(0, 10), center + QPointF(0, 10))
