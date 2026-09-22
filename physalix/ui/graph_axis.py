"""Titres horizontaux et flèches ancrés aux extrémités visibles du repère."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QGraphicsPathItem
import pyqtgraph as pg
from physalix.ui.theme import LIGHT


class EndAxis(pg.AxisItem):
    def __init__(self, orientation):
        self.arrow = None
        super().__init__(orientation=orientation)
        self.arrow = QGraphicsPathItem(self)
        self.arrow.setPen(pg.mkPen(LIGHT.muted, width=1.8))
        self.arrow.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.arrow.setZValue(5)
        self.resizeEvent()

    def setLabel(self, *args, **kwargs):
        """Replacer immédiatement le titre lorsque son texte change."""
        super().setLabel(*args, **kwargs)
        self.resizeEvent()

    def tickValues(self, min_value, max_value, size):
        """Conserver zéro parmi les graduations majeures lorsqu'il est visible."""
        levels = [(spacing, list(values))
                  for spacing, values in super().tickValues(min_value, max_value, size)]
        if levels and min(min_value, max_value) <= 0 <= max(min_value, max_value):
            tolerance = max(abs(max_value-min_value), 1) * 1e-12
            if not any(abs(value) <= tolerance
                       for _, values in levels for value in values):
                levels[0][1].append(0.0)
                levels[0][1].sort()
        return levels

    def generateDrawSpecs(self, painter):
        """Rabattre le libellé zéro dans l'axe si le bord l'aurait rogné."""
        specs = super().generateDrawSpecs(painter)
        if specs is None or not (min(self.range) <= 0 <= max(self.range)):
            return specs
        axis_spec, tick_specs, text_specs = specs
        zero_text = self.tickStrings([0], self.autoSIPrefixScale*self.scale, 1)[0]
        if any(text == zero_text for _, _, text in text_specs):
            return specs

        if self.style['tickFont'] is not None:
            painter.setFont(self.style['tickFont'])
        bounds = self.mapRectFromParent(self.geometry())
        span = self.range[1] - self.range[0]
        if span == 0:
            return specs
        text_rect = painter.boundingRect(
            QRectF(0, 0, 100, 100), Qt.AlignmentFlag.AlignCenter, zero_text)
        text_rect.setHeight(text_rect.height() * .8)
        width, height = text_rect.width(), text_rect.height()
        vertical = self.orientation in ('left', 'right')
        offset = max(0, self.style['tickLength']) + self.style['tickTextOffset'][0 if vertical else 1]
        if vertical:
            position = bounds.bottom() - (0-self.range[0]) * bounds.height() / span
            if self.orientation == 'left':
                rect = QRectF(bounds.right()-offset-width, position-height/2, width, height)
                alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            else:
                rect = QRectF(bounds.left()+offset, position-height/2, width, height)
                alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        else:
            position = bounds.left() + (0-self.range[0]) * bounds.width() / span
            rect = QRectF(position-width/2, bounds.top()+offset, width, height)
            alignment = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop

        limits = self.boundingRect()
        rect.moveLeft(min(max(rect.left(), limits.left()), limits.right()-rect.width()))
        rect.moveTop(min(max(rect.top(), limits.top()), limits.bottom()-rect.height()))
        text_specs.append((rect, alignment | Qt.TextFlag.TextDontClip, zero_text))
        return axis_spec, tick_specs, text_specs

    def resizeEvent(self, event=None):
        super().resizeEvent(event)
        if self.label is None:
            return
        self.label.setRotation(0)
        bounds = self.label.boundingRect()
        width = self.size().width()
        if self.orientation == 'bottom':
            self.label.setPos(max(0, width-bounds.width()-16),
                              max(0, self.size().height()-bounds.height()))
        elif self.orientation == 'right':
            self.label.setPos(-bounds.width()-8, 2)
        else:
            self.label.setPos(width+8, 2)
        self.label.setZValue(6)
        if self.arrow is not None:
            path = QPainterPath()
            if self.orientation == 'bottom':
                path.moveTo(width-10, -5)
                path.lineTo(width-1, 0)
                path.lineTo(width-10, 5)
            elif self.orientation == 'right':
                path.moveTo(-5, 9)
                path.lineTo(0, 0)
                path.lineTo(5, 9)
            else:
                path.moveTo(width-6, 9)
                path.lineTo(width-1, 0)
                path.lineTo(width+4, 9)
            self.arrow.setPath(path)
