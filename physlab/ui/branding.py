"""Identité visuelle de Physalix et rendu du logo en coordonnées Qt HiDPI."""

import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from physlab.ui.resources import resource_path


def application_icon() -> QIcon:
    return QIcon(str(resource_path("branding", "icon_physalix.ico")))


def set_windows_app_id() -> None:
    """Donner au processus son identité avant la création des fenêtres."""
    if sys.platform == "win32":
        import ctypes

        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        result = set_app_id("Physalix.Physalix")
        if result < 0:
            raise OSError(f"Impossible de définir l'identité Windows : {result:#x}")


class BrandLogo(QWidget):
    """Conserver le PNG original pour un rendu lissé à chaque échelle écran."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap(str(resource_path("branding", "logo_physalix.png")))
        self.setFixedSize(180, 60)
        self.setAccessibleName("Physalix")
        self.setToolTip("Physalix — Observer • Mesurer • Comprendre")

    def paintEvent(self, event):
        if self._pixmap.isNull():
            return
        size = self._pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF((self.width() - size.width()) / 2,
                        (self.height() - size.height()) / 2, size.width(), size.height())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
