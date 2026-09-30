"""Identité visuelle de Physalix et rendu du logo en coordonnées Qt HiDPI."""

import sys

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap, qAlpha
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
    """Centrer le contenu visible du PNG et le rendre proprement en HiDPI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap(str(resource_path("branding", "logo_physalix.png")))
        self._source_rect = self._visible_rect(self._pixmap)
        self.setDisplaySize(124, 38)
        self.setAccessibleName("Physalix")
        self.setToolTip("Physalix — Observer • Mesurer • Comprendre")

    def setDisplaySize(self, width, height):
        """Adapter l'affichage sans rééchantillonner la ressource HiDPI."""
        self.setFixedSize(width, height)

    def _target_rect(self):
        size = self._source_rect.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - size.width()) / 2,
                      (self.height() - size.height()) / 2, size.width(), size.height())

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
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self._target_rect(), self._pixmap, QRectF(self._source_rect))
