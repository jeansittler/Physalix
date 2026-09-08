"""Titres horizontaux et flèches ancrés aux extrémités visibles du repère."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QGraphicsPathItem
import pyqtgraph as pg
from physlab.ui.theme import LIGHT


class EndAxis(pg.AxisItem):
    def __init__(self, orientation):
        self.arrow = None
        super().__init__(orientation=orientation)
        self.arrow = QGraphicsPathItem(self)
        self.arrow.setPen(pg.mkPen(LIGHT.muted, width=1.8))
        self.arrow.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.arrow.setZValue(5)
        self.resizeEvent()

    def resizeEvent(self, event=None):
        super().resizeEvent(event)
        if self.label is None:
            return
        self.label.setRotation(0)
        bounds = self.label.boundingRect()
        width = self.size().width()
        if self.orientation == 'bottom':
            self.label.setPos(max(0, width-bounds.width()), self.size().height()-bounds.height()+5)
        elif self.orientation == 'right':
            self.label.setPos(-bounds.width()-6, -bounds.height()-8)
        else:
            self.label.setPos(width+6, -bounds.height()-8)
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
