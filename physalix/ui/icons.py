"""Pictogrammes vectoriels simples, rendus par Qt aux résolutions HiDPI."""

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

from physalix.ui.theme import LIGHT


PATHS = {
    "data": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16M15 10v10M3 15h18"/>',
    "graph": '<path d="M4 3v17h17M7 15l4-5 4 2 5-7"/>',
    "model": '<path d="M7 20c4 0 2-16 7-16h2M7 9h9M16 14l5 6m0-6-5 6"/>',
    "video": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3Z"/>',
    "calculations": '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M8 6h8M8 11h2m4 0h2M8 15h2m4 0h2M8 19h2m4 0h2"/>',
    "statistics": '<path d="M3 3v18h18M7 17v-5h3v5M12 17V6h3v11M17 17V9h3v8"/>',
    "add": '<path d="M12 5v14M5 12h14"/><circle cx="12" cy="12" r="9"/>',
}


def icon(name, active=False, navigation=False):
    result = QIcon()
    normal = LIGHT.surface if active else (LIGHT.nav_text if navigation else LIGHT.text)
    for mode, color in ((QIcon.Normal, normal),
                        (QIcon.Selected, LIGHT.surface), (QIcon.Disabled, LIGHT.disabled)):
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>'
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        for size in (20, 40, 60):
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            result.addPixmap(pixmap, mode)
    return result
