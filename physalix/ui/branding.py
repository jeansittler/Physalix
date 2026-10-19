"""Identité visuelle de Physalyx et rendu du logo en coordonnées Qt HiDPI."""

import sys

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPixmap, qAlpha
from PySide6.QtWidgets import QWidget

from physalix.ui.resources import resource_path
from physalix import __development__


def application_icon() -> QIcon:
    return QIcon(str(resource_path("branding", "icon_physalix.ico")))


def set_windows_app_id() -> None:
    """Donner au processus son identité avant la création des fenêtres."""
    if sys.platform == "win32":
        import ctypes

        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        app_id = "Physalix.Physalix.Development" if __development__ else "Physalix.Physalix"
        result = set_app_id(app_id)
        if result < 0:
            raise OSError(f"Impossible de définir l'identité Windows : {result:#x}")


class BrandLogo(QWidget):
    """Associer le symbole historique intact au nouveau nom public."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap(str(resource_path("branding", "icon_physalix.png")))
        self._source_rect = self._visible_rect(self._pixmap)
        self._symbol_only = False
        self.setDisplaySize(124, 38)
        self.setAccessibleName("Physalyx")
        self.setToolTip("Physalyx — Observer • Mesurer • Comprendre")

    def setDisplaySize(self, width, height):
        """Adapter l'affichage sans rééchantillonner la ressource HiDPI."""
        self.setFixedSize(width, height)

    def setSymbolOnly(self, symbol_only):
        """Masquer le wordmark lorsque la navigation manque de largeur."""
        symbol_only = bool(symbol_only)
        if symbol_only != self._symbol_only:
            self._symbol_only = symbol_only
            self.update()

    def symbolOnly(self):
        return self._symbol_only

    def _font(self):
        font = QFont("Segoe UI")
        font.setPixelSize(max(12, round(self.height() * .52)))
        font.setWeight(QFont.Weight.Bold)
        return font

    def _target_rect(self):
        margin = max(1.0, self.height() * .08)
        side = max(1.0, self.height() - 2 * margin)
        left = (self.width() - side) / 2 if self._symbol_only else margin
        return QRectF(left, margin, side, side)

    @staticmethod
    def _visible_rect(pixmap, alpha_threshold=5):
        """Calculer une fois les limites des pixels réellement visibles."""
        if pixmap.isNull():
            return QRect()
        image = pixmap.toImage()
        left, top = image.width(), image.height()
        right = bottom = -1
        for y in range(image.height()):
            for x in range(image.width()):
                if qAlpha(image.pixel(x, y)) > alpha_threshold:
                    left = min(left, x)
                    right = max(right, x)
                    top = min(top, y)
                    bottom = max(bottom, y)
        return (QRect(left, top, right - left + 1, bottom - top + 1)
                if right >= left and bottom >= top else QRect(pixmap.rect()))

    def paintEvent(self, event):
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing |
                               QPainter.RenderHint.TextAntialiasing |
                               QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self._target_rect(), self._pixmap, QRectF(self._source_rect))
        if self._symbol_only:
            return
        font = self._font()
        painter.setFont(font)
        painter.setPen(QColor("#0B2744"))
        metrics = QFontMetricsF(font)
        text_rect = QRectF(self._target_rect().right() + max(2.0, self.width() * .02), 0,
                           self.width() - self._target_rect().right(), self.height())
        if metrics.horizontalAdvance("Physalyx") > text_rect.width():
            font.setPixelSize(max(8, round(font.pixelSize() * text_rect.width() /
                                           metrics.horizontalAdvance("Physalyx"))))
            painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter |
                         Qt.AlignmentFlag.AlignLeft, "Physalyx")
