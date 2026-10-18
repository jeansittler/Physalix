"""Canevas interactif des coupes et etalonnages d'une image."""

from math import hypot

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from physalix.ui.theme import LIGHT, SERIES_COLORS


class ImageAnalysisCanvas(QWidget):
    segment_drawn = Signal(QPointF, QPointF)
    profile_selected = Signal(str)
    profile_changed = Signal(str)
    distance_reference_drawn = Signal(QPointF, QPointF)
    spectral_reference_chosen = Signal(int, QPointF)
    calibration_reference_changed = Signal(QPointF, QPointF)
    pointer_moved = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        self.profiles = []
        self.active_identifier = None
        self.calibration = None
        self.calibration_reference = None
        self.calibration_points_only = False
        self.calibration_visible = True
        self.hover_sample_marker = None
        self.selected_sample_marker = None
        self.new_profile_horizontal = False
        self.calibration_horizontal = False
        self.mode = "normal"
        self.zoom = 1.0
        self.pan = QPointF()
        self.pan_start = None
        self.pan_press_position = None
        self.pan_waits_for_drag = False
        self.space_pressed = False
        self.drag_start = None
        self.drag_target = None
        self.drag_original = None
        self.press_position = None
        self.drag_started = False
        self.preview_end = None
        self.spectral_target = 0
        self.setMinimumSize(480, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_image(self, image):
        self.image = QImage(image)
        self.fit_to_window()

    def set_profiles(self, profiles, active_identifier=None):
        self.profiles = profiles
        self.active_identifier = active_identifier
        self.update()

    def set_calibration(self, calibration):
        self.calibration = calibration
        self.update()

    def set_calibration_reference(self, reference, points_only=False):
        self.calibration_reference = reference
        self.calibration_points_only = bool(points_only)
        self.update()

    def set_calibration_visible(self, visible):
        self.calibration_visible = bool(visible)
        self.update()

    def set_hover_sample_marker(self, point=None, color=None):
        self.hover_sample_marker = None if point is None else (point, color)
        self.update()

    def set_selected_sample_marker(self, point=None, color=None):
        self.selected_sample_marker = None if point is None else (point, color)
        self.update()

    def set_horizontal_constraints(self, profile=False, calibration=False):
        self.new_profile_horizontal = bool(profile)
        self.calibration_horizontal = bool(calibration)

    def set_mode(self, mode, spectral_target=0):
        self.mode = mode
        self.spectral_target = spectral_target
        self.drag_start = self.preview_end = self.drag_target = self.drag_original = None
        self.press_position = None
        self.drag_started = False
        self.pan_start = self.pan_press_position = None
        self.pan_waits_for_drag = False
        self._update_cursor()
        self.update()

    def fit_to_window(self):
        self.zoom = 1.0
        self.pan = QPointF()
        self.update()

    def frame_segment(self, start, end, margin=36):
        """Cadrer un segment sans modifier le cadrage du graphique."""
        if self.image.isNull() or self.width() <= 2 * margin or self.height() <= 2 * margin:
            return
        x0, y0 = (start.x(), start.y()) if hasattr(start, "x") else start
        x1, y1 = (end.x(), end.y()) if hasattr(end, "x") else end
        length = hypot(x1 - x0, y1 - y0)
        image_margin = max(8.0, length * .06)
        target_width = max(abs(x1 - x0) + 2 * image_margin, 2 * image_margin)
        target_height = max(abs(y1 - y0) + 2 * image_margin, 2 * image_margin)
        desired_scale = min((self.width() - 2 * margin) / target_width,
                            (self.height() - 2 * margin) / target_height)
        self.zoom = min(30.0, max(1.0, desired_scale / self.fit_scale()))
        scale = self.fit_scale() * self.zoom
        target_center = QPointF((x0 + x1) / 2, (y0 + y1) / 2)
        image_center = QPointF(self.image.width() / 2, self.image.height() / 2)
        self.pan = QPointF(-(target_center.x() - image_center.x()) * scale,
                           -(target_center.y() - image_center.y()) * scale)
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
        if rectangle.isEmpty() or (not clamp and not rectangle.contains(position)):
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
        return QPointF(
            rectangle.left() + x * rectangle.width() / self.image.width(),
            rectangle.top() + y * rectangle.height() / self.image.height(),
        )

    def active_profile(self):
        return next((item for item in self.profiles if item.identifier == self.active_identifier), None)

    def _calibration_label_rects(self, segment):
        """Calculer les étiquettes d'un segment étalon, provisoire ou définitif."""
        if segment is None or self.image.isNull() or not any(point is not None for point in segment):
            return {}
        points = [self.screen_point(point) if point is not None else None for point in segment]
        if all(points):
            dx, dy = points[1].x() - points[0].x(), points[1].y() - points[0].y()
            length = hypot(dx, dy) or 1.0
            normal = QPointF(-dy / length, dx / length)
            tangent = QPointF(dx / length, dy / length)
        else:
            normal, tangent = QPointF(0, -1), QPointF(1, 0)
        size, offset, inset = 22.0, 19.0, 2.0

        def constrained_center(point, direction):
            center = point + direction * offset
            half = size / 2
            center.setX(min(max(center.x(), half + inset), self.width() - half - inset))
            center.setY(min(max(center.y(), half + inset), self.height() - half - inset))
            return center

        def label_rect(point, direction):
            directions = (direction, -direction, tangent, -tangent)
            centers = [constrained_center(point, candidate) for candidate in directions]
            center = next((candidate for candidate in centers if hypot(
                candidate.x() - point.x(), candidate.y() - point.y()) >= offset - .1), None)
            if center is None:
                center = max(centers, key=lambda candidate: hypot(
                    candidate.x() - point.x(), candidate.y() - point.y()))
            half = size / 2
            return QRectF(center.x() - half, center.y() - half, size, size)

        result = {}
        if points[0] is not None:
            result["A"] = label_rect(points[0], normal)
        if points[1] is not None:
            result["B"] = label_rect(points[1], -normal)
        return result

    def calibration_label_rects(self):
        """Rectangles écran des étiquettes A/B du segment étalon affiché."""
        if not self.calibration_visible:
            return {}
        segment = self.calibration_reference
        if segment is None and self.calibration is not None and self.calibration.mode != "none":
            segment = self.calibration.first, self.calibration.second
        return self._calibration_label_rects(segment)

    def preview_calibration_label_rects(self):
        if (self.mode not in ("distance", "calibration_draw")
                or self.drag_start is None or self.preview_end is None):
            return {}
        endpoint = (self.preview_end if hypot(
            self.preview_end.x() - self.drag_start.x(),
            self.preview_end.y() - self.drag_start.y()) >= 1 else None)
        return self._calibration_label_rects((self.drag_start, endpoint))

    def preview_segment_style(self):
        """Retourner le style définitif correspondant à l'outil de tracé actif."""
        if self.mode == "draw":
            return SERIES_COLORS[len(self.profiles) % len(SERIES_COLORS)], 2, True
        if self.mode in ("distance", "calibration_draw"):
            return LIGHT.warning, 2, True
        return None

    def _profile_target(self, position):
        """Retourner le profil et la partie cliquée les plus proches."""
        candidates = []
        for profile in self.profiles:
            if not profile.visible:
                continue
            start, end = self.screen_point(profile.start), self.screen_point(profile.end)
            start_distance = hypot(position.x() - start.x(), position.y() - start.y())
            end_distance = hypot(position.x() - end.x(), position.y() - end.y())
            if start_distance <= 12:
                candidates.append((start_distance, 0, profile, "start"))
            if end_distance <= 12:
                candidates.append((end_distance, 0, profile, "end"))
            segment_distance = self._segment_distance(position, start, end)
            if segment_distance <= 9:
                candidates.append((segment_distance, 1, profile, "segment"))
        if not candidates:
            return None
        _, _, profile, target = min(
            candidates,
            key=lambda item: (item[1], item[0], item[2].identifier != self.active_identifier),
        )
        return profile, target

    def _update_cursor(self, position=None):
        if self.pan_start is not None:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self.space_pressed:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif self.mode in ("draw", "distance", "calibration_draw", "spectral"):
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self.mode == "calibration_edit":
            target = (self._edit_target(position, self.calibration_reference,
                                        allow_segment=not self.calibration_points_only)
                      if position is not None else None)
            if target:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            elif position is not None and self.image_point(position) is not None:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self.mode == "normal":
            target = self._profile_target(position) if position is not None else None
            if target is None:
                cursor = (Qt.CursorShape.OpenHandCursor
                          if position is not None and self.image_point(position) is not None
                          else Qt.CursorShape.ArrowCursor)
                self.setCursor(cursor)
            elif target[1] in ("start", "end"):
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event):
        if self.image.isNull():
            return
        before = self.image_point(event.position())
        if before is None:
            return
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        new_zoom = min(30.0, max(1.0, self.zoom * factor))
        if new_zoom == self.zoom:
            return
        self.zoom = new_zoom
        self.pan += event.position() - self.screen_point(before)
        self.update()
        event.accept()

    @staticmethod
    def _segment_distance(point, start, end):
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length2 = dx * dx + dy * dy
        if not length2:
            return hypot(point.x() - start.x(), point.y() - start.y())
        t = max(0.0, min(1.0, ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / length2))
        projection = QPointF(start.x() + t * dx, start.y() + t * dy)
        return hypot(point.x() - projection.x(), point.y() - projection.y())

    def _edit_target(self, position, segment=None, allow_segment=True):
        if segment is None:
            profile = self.active_profile()
            segment = (profile.start, profile.end) if profile is not None else None
        if segment is None:
            return None
        start = self.screen_point(segment[0]) if segment[0] is not None else None
        end = self.screen_point(segment[1]) if segment[1] is not None else None
        if start is not None and hypot(position.x() - start.x(), position.y() - start.y()) <= 12:
            return "start"
        if end is not None and hypot(position.x() - end.x(), position.y() - end.y()) <= 12:
            return "end"
        return ("segment" if allow_segment and start is not None and end is not None
                and self._segment_distance(position, start, end) <= 9 else None)

    def _finish_draw_segment(self, end):
        """Finaliser au second clic le segment commencé au premier clic."""
        start, mode = self.drag_start, self.mode
        horizontal = ((mode == "draw" and self.new_profile_horizontal)
                      or (mode in ("distance", "calibration_draw")
                          and self.calibration_horizontal))
        if horizontal:
            end.setY(start.y())
        if hypot(end.x() - start.x(), end.y() - start.y()) < 1:
            return
        self.drag_start = self.preview_end = None
        if mode == "draw":
            self.segment_drawn.emit(start, end)
        elif mode == "calibration_draw":
            self.calibration_reference = ((start.x(), start.y()), (end.x(), end.y()))
            self.calibration_reference_changed.emit(start, end)
        else:
            self.distance_reference_drawn.emit(start, end)

    def mousePressEvent(self, event):
        if self.image.isNull():
            return
        self.setFocus()
        if (event.button() == Qt.MouseButton.MiddleButton
                or (event.button() == Qt.MouseButton.LeftButton and self.space_pressed)):
            self.pan_start = event.position()
            self.pan_press_position = event.position()
            self.pan_waits_for_drag = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.image_point(event.position())
        if point is None:
            return
        if self.mode in ("draw", "distance", "calibration_draw"):
            if self.drag_start is None:
                self.drag_start = point
                self.preview_end = point
            else:
                self._finish_draw_segment(point)
        elif self.mode == "spectral":
            self.spectral_reference_chosen.emit(self.spectral_target, point)
        elif self.mode == "normal":
            target = self._profile_target(event.position())
            if target is not None:
                profile, self.drag_target = target
                if profile.identifier != self.active_identifier:
                    self.active_identifier = profile.identifier
                    self.profile_selected.emit(profile.identifier)
                self.drag_start = point
                self.drag_original = profile.start, profile.end
                self.press_position = event.position()
                self.drag_started = False
            else:
                self.pan_start = event.position()
                self.pan_press_position = event.position()
                self.pan_waits_for_drag = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self.mode == "calibration_edit":
            self.drag_target = self._edit_target(
                event.position(), self.calibration_reference,
                allow_segment=not self.calibration_points_only)
            if self.drag_target and self.calibration_reference:
                self.drag_start = point
                self.drag_original = self.calibration_reference
                self.press_position = event.position()
                self.drag_started = False
            else:
                self.pan_start = event.position()
                self.pan_press_position = event.position()
                self.pan_waits_for_drag = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.update()

    def mouseMoveEvent(self, event):
        point = self.image_point(event.position())
        self.pointer_moved.emit(point)
        if self.pan_start is not None:
            if (self.pan_waits_for_drag and self.pan_press_position is not None
                    and hypot(event.position().x() - self.pan_press_position.x(),
                              event.position().y() - self.pan_press_position.y()) < 3):
                return
            self.pan_waits_for_drag = False
            self.pan += event.position() - self.pan_start
            self.pan_start = event.position()
        elif self.drag_start is not None and self.mode in ("draw", "distance", "calibration_draw"):
            self.preview_end = self.image_point(event.position(), clamp=True)
            horizontal = ((self.mode == "draw" and self.new_profile_horizontal)
                          or (self.mode in ("distance", "calibration_draw")
                              and self.calibration_horizontal))
            if horizontal and self.preview_end is not None:
                self.preview_end.setY(self.drag_start.y())
        elif self.drag_start is not None and self.mode == "normal" and self.drag_target:
            profile = self.active_profile()
            current = self.image_point(event.position(), clamp=True)
            if profile is not None and current is not None:
                if (not self.drag_started and self.press_position is not None
                        and hypot(event.position().x() - self.press_position.x(),
                                  event.position().y() - self.press_position.y()) < 3):
                    self._update_cursor(event.position())
                    return
                self.drag_started = True
                original_start, original_end = self.drag_original
                if self.drag_target == "start":
                    if profile.horizontal:
                        current.setY(profile.end[1])
                    if hypot(current.x() - profile.end[0], current.y() - profile.end[1]) >= 1:
                        profile.start = current.x(), current.y()
                elif self.drag_target == "end":
                    if profile.horizontal:
                        current.setY(profile.start[1])
                    if hypot(current.x() - profile.start[0], current.y() - profile.start[1]) >= 1:
                        profile.end = current.x(), current.y()
                else:
                    dx, dy = current.x() - self.drag_start.x(), current.y() - self.drag_start.y()
                    max_dx = min(self.image.width() - 1 - original_end[0],
                                 self.image.width() - 1 - original_start[0])
                    min_dx = max(-original_start[0], -original_end[0])
                    max_dy = min(self.image.height() - 1 - original_end[1],
                                 self.image.height() - 1 - original_start[1])
                    min_dy = max(-original_start[1], -original_end[1])
                    dx, dy = min(max(dx, min_dx), max_dx), min(max(dy, min_dy), max_dy)
                    profile.start = original_start[0] + dx, original_start[1] + dy
                    profile.end = original_end[0] + dx, original_end[1] + dy
                self.profile_changed.emit(profile.identifier)
        elif self.drag_start is not None and self.mode == "calibration_edit" and self.drag_target:
            current = self.image_point(event.position(), clamp=True)
            if current is not None and self.calibration_reference:
                if (not self.drag_started and self.press_position is not None
                        and hypot(event.position().x() - self.press_position.x(),
                                  event.position().y() - self.press_position.y()) < 3):
                    self._update_cursor(event.position())
                    return
                self.drag_started = True
                original_start, original_end = self.drag_original
                start, end = QPointF(*self.calibration_reference[0]), QPointF(*self.calibration_reference[1])
                if self.drag_target == "start":
                    if self.calibration_horizontal:
                        current.setY(end.y())
                    if hypot(current.x() - end.x(), current.y() - end.y()) >= 1:
                        start = current
                elif self.drag_target == "end":
                    if self.calibration_horizontal:
                        current.setY(start.y())
                    if hypot(current.x() - start.x(), current.y() - start.y()) >= 1:
                        end = current
                else:
                    dx, dy = current.x() - self.drag_start.x(), current.y() - self.drag_start.y()
                    min_dx = max(-original_start[0], -original_end[0])
                    max_dx = min(self.image.width() - 1 - original_start[0],
                                 self.image.width() - 1 - original_end[0])
                    min_dy = max(-original_start[1], -original_end[1])
                    max_dy = min(self.image.height() - 1 - original_start[1],
                                 self.image.height() - 1 - original_end[1])
                    dx, dy = min(max(dx, min_dx), max_dx), min(max(dy, min_dy), max_dy)
                    start = QPointF(original_start[0] + dx, original_start[1] + dy)
                    end = QPointF(original_end[0] + dx, original_end[1] + dy)
                self.calibration_reference = ((start.x(), start.y()), (end.x(), end.y()))
                self.calibration_reference_changed.emit(start, end)
        else:
            self._update_cursor(event.position())
        self.update()

    def mouseReleaseEvent(self, event):
        if self.pan_start is not None and event.button() in (
                Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self.pan_start = None
            self.pan_press_position = None
            self.pan_waits_for_drag = False
            self._update_cursor(event.position())
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.drag_start is not None and self.mode == "normal":
            profile = self.active_profile()
            changed = self.drag_started
            self.drag_start = self.drag_target = self.drag_original = None
            self.press_position = None
            self.drag_started = False
            if profile is not None and changed:
                self.profile_changed.emit(profile.identifier)
        elif self.drag_start is not None and self.mode == "calibration_edit":
            self.drag_start = self.drag_target = self.drag_original = None
            self.press_position = None
            self.drag_started = False
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_pressed = True
            self._update_cursor()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_pressed = False
            self._update_cursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def leaveEvent(self, event):
        self.pointer_moved.emit(None)
        super().leaveEvent(event)

    def _draw_segment(self, painter, start, end, color, width=2, band=1, active=False):
        start, end = self.screen_point(start), self.screen_point(end)
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = hypot(dx, dy)
        if band > 1 and length:
            half = band * self.fit_scale() * self.zoom / 2
            nx, ny = -dy / length * half, dx / length * half
            polygon = QPolygonF([
                start + QPointF(nx, ny), end + QPointF(nx, ny),
                end - QPointF(nx, ny), start - QPointF(nx, ny),
            ])
            shade = QColor(color)
            shade.setAlpha(55)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shade)
            painter.drawPolygon(polygon)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(color), width + (1 if active else 0)))
        painter.drawLine(start, end)
        if active:
            painter.setBrush(QColor(LIGHT.surface))
            for point in (start, end):
                painter.drawEllipse(point, 6, 6)

    def _draw_reference_point(self, painter, point):
        point = self.screen_point(point)
        painter.setBrush(QColor(LIGHT.surface))
        painter.setPen(QPen(QColor(LIGHT.warning), 3))
        painter.drawEllipse(point, 6, 6)

    @staticmethod
    def _draw_calibration_labels(painter, labels):
        if not labels:
            return
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setBrush(QColor(17, 24, 39, 230))
        painter.setPen(QPen(QColor(LIGHT.warning), 2))
        for label, rectangle in labels.items():
            painter.drawRoundedRect(rectangle, 5, 5)
            painter.setPen(QColor("white"))
            painter.drawText(rectangle, Qt.AlignmentFlag.AlignCenter, label)
            painter.setPen(QPen(QColor(LIGHT.warning), 2))

    def _draw_sample_marker(self, painter, marker, selected=False):
        if marker is None:
            return
        point, color = marker
        point = self.screen_point(point)
        color = QColor(color or LIGHT.primary)
        painter.setBrush(color if not selected else QColor(LIGHT.surface))
        painter.setPen(QPen(QColor("white"), 4 if selected else 3))
        painter.drawEllipse(point, 8 if selected else 5, 8 if selected else 5)
        painter.setPen(QPen(QColor("#111827"), 2))
        painter.drawEllipse(point, 8 if selected else 5, 8 if selected else 5)
        if selected:
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(point, 3, 3)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(LIGHT.video))
        if self.image.isNull():
            painter.setPen(QColor(LIGHT.video_text))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Ouvrez une image JPG, PNG ou BMP pour commencer")
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.image_rect(), self.image, QRectF(self.image.rect()))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for profile in self.profiles:
            if profile.visible:
                self._draw_segment(painter, profile.start, profile.end, profile.color,
                                   band=profile.width,
                                   active=profile.identifier == self.active_identifier)
        self._draw_sample_marker(painter, self.hover_sample_marker)
        self._draw_sample_marker(painter, self.selected_sample_marker, selected=True)
        preview_labels = {}
        if self.drag_start is not None and self.preview_end is not None:
            preview_style = self.preview_segment_style()
            if preview_style is not None:
                color, width, active = preview_style
                self._draw_segment(
                    painter, self.drag_start, self.preview_end,
                    color, width=width, active=active)
            if self.mode in ("distance", "calibration_draw"):
                preview_labels = self.preview_calibration_label_rects()
        if self.calibration_visible and self.calibration_reference is not None:
            points = [point for point in self.calibration_reference if point is not None]
            if len(points) == 2 and not self.calibration_points_only:
                self._draw_segment(painter, points[0], points[1], LIGHT.warning, width=2,
                                   active=self.mode == "calibration_edit")
            else:
                for point in points:
                    self._draw_reference_point(painter, point)
        calibration = self.calibration
        if (self.calibration_visible and calibration is not None and calibration.mode != "none"
                and self.calibration_reference is None):
            color = LIGHT.warning
            if calibration.mode == "spectral" and calibration.spectral_method == "two_points":
                self._draw_reference_point(painter, calibration.first)
                self._draw_reference_point(painter, calibration.second)
            else:
                self._draw_segment(painter, calibration.first, calibration.second, color, width=2)
        self._draw_calibration_labels(
            painter, preview_labels or self.calibration_label_rects())
