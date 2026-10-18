"""Accueil visuel donnant un accès direct aux outils scientifiques."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from physalix.ui.components import role
from physalix.ui.icons import icon
from physalix.ui.theme import LIGHT
from physalix import __version__


TOOLS = (
    ("Données", "Saisir, organiser et vérifier des mesures expérimentales.", "data", 0),
    ("Graphique", "Tracer les grandeurs et comparer plusieurs séries.", "graph", 1),
    ("Modélisation", "Ajuster un modèle et interpréter ses paramètres.", "model", 2),
    ("Pointage", "Relever la position d’un mobile image par image.", "video", 3),
    ("Calculs", "Créer de nouvelles grandeurs à partir de formules.", "calculations", 4),
    ("Statistiques", "Décrire une série et visualiser sa dispersion.", "statistics", 5),
    ("Numérisation", "Extraire les points d'une courbe depuis une image.", "digitizer", 6),
    ("Analyse d’images", "Mesurer une distance ou un profil d’intensité.", "image_analysis", 9),
    ("Acquisition Arduino", "Observer un signal et transférer les mesures.", "acquisition", 7),
    ("Spectrophotométrie", "Mesurer un spectre d’absorbance expérimental.", "spectrophotometry", 8),
)


class ScientificPreview(QWidget):
    """Petite scène vectorielle fidèle au vocabulaire de chaque module."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedHeight(126)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _line(self, painter, points, color=LIGHT.primary, width=2.2):
        painter.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        painter.drawPath(path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(LIGHT.border), 1))
        painter.setBrush(QColor(LIGHT.secondary))
        painter.drawRoundedRect(area, 6, 6)
        r = area.adjusted(13, 10, -13, -10)
        getattr(self, f"_paint_{self.kind}")(painter, r)

    def _axes(self, painter, r, x=26, y=13):
        painter.setPen(QPen(QColor(LIGHT.border_strong), 1))
        painter.drawLine(QPointF(r.left() + x, r.bottom() - y),
                         QPointF(r.right(), r.bottom() - y))
        painter.drawLine(QPointF(r.left() + x, r.bottom() - y),
                         QPointF(r.left() + x, r.top()))
        return r.left() + x, r.bottom() - y, r.width() - x, r.height() - y

    def _paint_data(self, p, r):
        rows, cols = 4, 4
        cell_w, cell_h = r.width() / cols, r.height() / rows
        p.setPen(QPen(QColor(LIGHT.table_grid), 1))
        p.setBrush(QColor(LIGHT.surface))
        p.drawRect(r)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), cell_h), QColor(LIGHT.table_header))
        for i in range(1, cols):
            p.drawLine(QPointF(r.left() + i * cell_w, r.top()), QPointF(r.left() + i * cell_w, r.bottom()))
        for i in range(1, rows):
            p.drawLine(QPointF(r.left(), r.top() + i * cell_h), QPointF(r.right(), r.top() + i * cell_h))
        p.setPen(QColor(LIGHT.navy))
        p.setFont(QFont(LIGHT.font, 8, QFont.Weight.DemiBold))
        for i, text in enumerate(("t (s)", "x (m)", "v (m·s⁻¹)", "Δx (m)")):
            p.drawText(QRectF(r.left() + i * cell_w, r.top(), cell_w, cell_h), Qt.AlignmentFlag.AlignCenter, text)
        p.setFont(QFont(LIGHT.font, 8))
        values = (("0,00", "0,12", "0,48"), ("0,10", "0,19", "0,71"),
                  ("0,20", "0,29", "0,96"), ("—", "0,10", "0,01"))
        for c, column in enumerate(values):
            for row, text in enumerate(column, 1):
                p.drawText(QRectF(r.left() + c * cell_w, r.top() + row * cell_h,
                                  cell_w, cell_h), Qt.AlignmentFlag.AlignCenter, text)

    def _paint_graph(self, p, r):
        x0, y0, w, h = self._axes(p, r)
        pts = [QPointF(x0 + w * i / 8, y0 - h * (0.13 + 0.68 * (i / 8) ** 1.45)) for i in range(9)]
        self._line(p, pts)
        p.setBrush(QColor(LIGHT.primary)); p.setPen(Qt.PenStyle.NoPen)
        for point in pts: p.drawEllipse(point, 3.2, 3.2)
        p.setPen(QColor(LIGHT.muted)); p.setFont(QFont(LIGHT.font, 7))
        p.drawText(QRectF(x0 + 6, r.top(), 70, 14), "x = f(t)")

    def _paint_model(self, p, r):
        x0, y0, w, h = self._axes(p, r)
        curve = [QPointF(x0 + w * i / 60, y0 - h * (0.1 + .78 * (1 - math.exp(-i / 15)))) for i in range(61)]
        self._line(p, curve, LIGHT.primary_pressed, 2.4)
        p.setBrush(QColor("#D84315")); p.setPen(Qt.PenStyle.NoPen)
        for i in range(0, 61, 7):
            point = curve[i] + QPointF(0, 2 * math.sin(i))
            p.drawEllipse(point, 2.8, 2.8)
        p.setPen(QColor(LIGHT.muted)); p.setFont(QFont(LIGHT.font, 7))
        p.drawText(QRectF(x0 + 7, r.top(), 130, 14), "u(t) = E·(1 − e⁻ᵗ/τ)")

    def _paint_video(self, p, r):
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#E2E8EF")); p.drawRoundedRect(r, 4, 4)
        p.setBrush(QColor("#D4DEE7")); p.drawRect(QRectF(r.left(), r.bottom() - 25, r.width(), 25))
        points = []
        for i in range(8):
            x = r.left() + 20 + i * (r.width() - 40) / 7
            y = r.bottom() - 28 - 54 * math.sin(math.pi * i / 9)
            points.append(QPointF(x, y))
        self._line(p, points, LIGHT.border_strong, 1.2)
        for i, point in enumerate(points):
            p.setBrush(QColor(LIGHT.primary if i == 5 else "#FFFFFF"))
            p.setPen(QPen(QColor(LIGHT.primary), 1.6)); p.drawEllipse(point, 4, 4)
        p.setPen(QColor(LIGHT.muted)); p.setFont(QFont(LIGHT.font, 7)); p.drawText(r.adjusted(7, 5, 0, 0), "Image 18 / 42")

    def _paint_calculations(self, p, r):
        p.setPen(QPen(QColor(LIGHT.border), 1)); p.setBrush(QColor(LIGHT.surface))
        boxes = (("v", "Δx / Δt"), ("Ec", "½ · m · v²"), ("a", "Δv / Δt"))
        h = 25
        for i, (name, formula) in enumerate(boxes):
            box = QRectF(r.left(), r.top() + 4 + i * 31, r.width(), h)
            p.drawRoundedRect(box, 4, 4); p.fillRect(QRectF(box.left(), box.top(), 38, box.height()), QColor(LIGHT.primary_soft))
            p.setPen(QColor(LIGHT.primary_pressed)); p.setFont(QFont(LIGHT.font, 9, QFont.Weight.Bold))
            p.drawText(QRectF(box.left(), box.top(), 38, box.height()), Qt.AlignmentFlag.AlignCenter, name)
            p.setPen(QColor(LIGHT.text)); p.setFont(QFont(LIGHT.font, 9))
            p.drawText(box.adjusted(50, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, formula)
            p.setPen(QPen(QColor(LIGHT.border), 1))

    def _paint_statistics(self, p, r):
        x0, y0, w, h = self._axes(p, r)
        heights = (.25, .48, .72, .92, .8, .52, .28)
        bw = w / (len(heights) + 1)
        p.setPen(QPen(QColor(LIGHT.primary_pressed), 1)); p.setBrush(QColor(LIGHT.primary_soft))
        for i, value in enumerate(heights):
            p.drawRect(QRectF(x0 + bw * (i + .55), y0 - h * value, bw * .9, h * value))
        p.setPen(QPen(QColor("#D84315"), 1.5, Qt.PenStyle.DashLine)); mid = x0 + w * .55
        p.drawLine(QPointF(mid, r.top()), QPointF(mid, y0))

    def _paint_digitizer(self, p, r):
        x0, y0, w, h = self._axes(p, r)
        curve = [QPointF(x0 + w * i / 45, y0 - h * (.1 + .72 * math.sin(i / 30) ** 1.3)) for i in range(46)]
        self._line(p, curve, LIGHT.muted, 1.6)
        p.setBrush(QColor(LIGHT.surface)); p.setPen(QPen(QColor(LIGHT.primary), 1.6))
        for i in range(3, 46, 6): p.drawEllipse(curve[i], 3, 3)
        p.setPen(QPen(QColor(LIGHT.primary), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x0 + 15, y0), QPointF(x0 + 15, r.top() + 5))

    def _paint_image_analysis(self, p, r):
        image = QRectF(r.left(), r.top(), r.width() * .56, r.height() * .66)
        p.setPen(QPen(QColor(LIGHT.border_strong), 1)); p.setBrush(QColor("#DCE4EA"))
        p.drawRoundedRect(image, 3, 3)
        p.save(); p.setClipRect(image.adjusted(1, 1, -1, -1))
        for radius, color in ((34, "#C3D0D9"), (24, "#EFF3F5"), (14, "#AEBFCB")):
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(color))
            p.drawEllipse(QPointF(image.left() + image.width() * .43,
                                  image.top() + image.height() * .53), radius, radius * .72)
        p.setBrush(QColor("#73899A")); p.drawEllipse(
            QPointF(image.right() - 17, image.top() + 17), 8, 6)
        p.restore()

        start = QPointF(image.left() + 16, image.bottom() - 15)
        end = QPointF(image.right() - 15, image.top() + 15)
        p.setPen(QPen(QColor(LIGHT.primary_pressed), 2)); p.drawLine(start, end)
        p.setBrush(QColor(LIGHT.surface)); p.setPen(QPen(QColor(LIGHT.primary_pressed), 2))
        p.drawEllipse(start, 3.5, 3.5); p.drawEllipse(end, 3.5, 3.5)
        direction = end - start; length = max(1.0, math.hypot(direction.x(), direction.y()))
        normal = QPointF(-direction.y() / length * 4, direction.x() / length * 4)
        unit = QPointF(direction.x() / length * 7, direction.y() / length * 7)
        p.drawLine(start, start + unit + normal); p.drawLine(start, start + unit - normal)
        p.drawLine(end, end - unit + normal); p.drawLine(end, end - unit - normal)
        p.setPen(QColor(LIGHT.primary_pressed)); p.setFont(QFont(LIGHT.font, 7, QFont.Weight.DemiBold))
        p.drawText(QRectF(image.left() + 5, image.top() + 3, 42, 13), "d = 4,2 mm")

        graph = QRectF(image.right() + 11, r.top() + 5, r.right() - image.right() - 11,
                       image.height() - 5)
        gx, gy, gw, gh = self._axes(p, graph, 12, 7)
        profile = [QPointF(gx + gw*i/32,
                           gy - gh*(.16 + .63*math.exp(-((i-17)/6)**2)
                                    + .08*math.sin(i*.75))) for i in range(33)]
        self._line(p, profile, LIGHT.primary, 1.7)
        p.setPen(QColor(LIGHT.muted)); p.setFont(QFont(LIGHT.font, 7))
        p.drawText(QRectF(graph.left() + 14, graph.top() - 2, graph.width(), 12), "Profil I(x)")

        caption_y = image.bottom() + 9
        p.setPen(QColor(LIGHT.muted)); p.setFont(QFont(LIGHT.font, 7))
        p.drawText(QRectF(r.left(), caption_y, r.width(), r.bottom() - caption_y),
                   Qt.AlignmentFlag.AlignCenter, "segment de mesure  →  profil d’intensité")

    def _paint_acquisition(self, p, r):
        x0, y0, w, h = self._axes(p, r)
        charge = [QPointF(x0+w*i/70, y0-h*(.08+.75*(1-math.exp(-i/13)))) for i in range(36)]
        discharge = [QPointF(x0+w*(35+i)/70, y0-h*(.08+.75*math.exp(-i/13))) for i in range(36)]
        self._line(p, charge + discharge, LIGHT.primary, 2.2)
        p.setPen(QPen(QColor("#D84315"), 1.4, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x0, y0-h*.87), QPointF(x0+w*.5, y0-h*.87)); p.drawLine(QPointF(x0+w*.5, y0-h*.08), QPointF(x0+w, y0-h*.08))
        p.setPen(QColor(LIGHT.success)); p.setFont(QFont(LIGHT.font, 7, QFont.Weight.DemiBold)); p.drawText(QRectF(x0+7, r.top(), 90, 14), "A0 · 200 Hz")

    def _paint_spectrophotometry(self, p, r):
        x0, y0, w, h = self._axes(p, r)
        values = (.10, .18, .42, .83, .68, .36, .17, .11)
        colors = ("#6B51A3", "#315DB5", "#1590C4", "#33A96A", "#A4B52D", "#E09A2B", "#D75832", "#B33B52")
        pts = []
        for i, (value, color) in enumerate(zip(values, colors)):
            point = QPointF(x0 + w*(i+.3)/8, y0-h*value); pts.append(point)
            p.setPen(QPen(QColor(color), 2)); p.drawLine(QPointF(point.x(), y0), point)
        self._line(p, pts, LIGHT.navy, 1.4)
        for point, color in zip(pts, colors): p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(color)); p.drawEllipse(point, 3.5, 3.5)
        p.setPen(QColor(LIGHT.muted)); p.setFont(QFont(LIGHT.font, 7)); p.drawText(QRectF(x0+8, r.top(), 100, 14), "Absorbance A(λ)")


class ToolCard(QFrame):
    activated = Signal(int)

    def __init__(self, title, description, kind, tab_index, parent=None):
        super().__init__(parent)
        role(self, "homeToolCard")
        self.tab_index = tab_index
        self.setProperty("hovered", False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)
        self.setToolTip(f"Ouvrir {title}")
        self.setMinimumWidth(220)
        self.setFixedHeight(224)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 11)
        layout.setSpacing(7)
        layout.addWidget(ScientificPreview(kind))
        heading = QHBoxLayout(); heading.setSpacing(7)
        badge = QLabel(); badge.setPixmap(icon(kind).pixmap(20, 20)); badge.setFixedSize(22, 22)
        heading.addWidget(badge)
        heading.addWidget(role(QLabel(title), "homeToolTitle"), 1)
        layout.addLayout(heading)
        description_label = role(QLabel(description), "homeToolDescription")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

    def _refresh(self):
        self.style().unpolish(self); self.style().polish(self); self.update()

    def enterEvent(self, event):
        self.setProperty("hovered", True); self._refresh(); super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hovered", False); self._refresh(); super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self.tab_index)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.tab_index); event.accept(); return
        super().keyPressEvent(event)


class HomeHeader(QFrame):
    """Bandeau compact, puis empilé lorsque la fenêtre devient étroite."""

    def __init__(self, parent=None):
        super().__init__(parent)
        role(self, "homeHeader")
        self.layout_box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.layout_box.setContentsMargins(18, 13, 18, 13)
        self.layout_box.setSpacing(16)

        identity = QWidget(); identity_layout = QHBoxLayout(identity)
        identity_layout.setContentsMargins(0, 0, 0, 0); identity_layout.setSpacing(13)
        accent = role(QFrame(), "homeHeaderAccent"); accent.setFixedSize(4, 52)
        identity_layout.addWidget(accent)
        message = QVBoxLayout(); message.setSpacing(1)
        message.addWidget(role(QLabel("PHYSIQUE EXPÉRIMENTALE"), "homeEyebrow"))
        headline = role(QLabel("Observer, mesurer et comprendre les phénomènes physiques"), "homeHeadline")
        headline.setWordWrap(True)
        subtitle = role(QLabel("Choisissez un outil pour commencer ou poursuivre votre expérience."), "muted")
        subtitle.setWordWrap(True)
        message.addWidget(headline); message.addWidget(subtitle)
        identity_layout.addLayout(message, 1)
        self.layout_box.addWidget(identity, 1)

        self.actions = QWidget(); actions = QHBoxLayout(self.actions)
        actions.setContentsMargins(0, 0, 0, 0); actions.setSpacing(8)
        self.new_button = role(QPushButton("Nouveau projet"), "primary")
        self.open_button = QPushButton("Ouvrir un projet…")
        actions.addWidget(self.new_button); actions.addWidget(self.open_button); actions.addStretch()
        self.layout_box.addWidget(self.actions, 0, Qt.AlignmentFlag.AlignVCenter)

    def resizeEvent(self, event):
        direction = (QBoxLayout.Direction.TopToBottom if event.size().width() < 900
                     else QBoxLayout.Direction.LeftToRight)
        self.layout_box.setDirection(direction)
        super().resizeEvent(event)


class HomePage(QWidget):
    module_requested = Signal(int)
    new_project_requested = Signal()
    open_project_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homePage")
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content = QWidget(); self.content.setObjectName("homeContent")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(24, 18, 24, 22); content_layout.setSpacing(16)

        header = HomeHeader()
        header.new_button.clicked.connect(lambda: self.new_project_requested.emit())
        header.open_button.clicked.connect(lambda: self.open_project_requested.emit())
        content_layout.addWidget(header)

        title_row = QHBoxLayout(); title_row.setContentsMargins(2, 2, 2, 0)
        title_row.addWidget(role(QLabel("Outils scientifiques"), "sectionTitle")); title_row.addStretch()
        title_row.addWidget(role(QLabel(f"Physalyx {__version__}"), "muted"))
        content_layout.addLayout(title_row)

        self.gallery = QWidget(); self.gallery.setMaximumWidth(1540)
        self.grid = QGridLayout(self.gallery)
        self.grid.setContentsMargins(0, 0, 0, 0); self.grid.setHorizontalSpacing(14); self.grid.setVerticalSpacing(14)
        self.cards = []
        for spec in TOOLS:
            card = ToolCard(*spec); card.activated.connect(self.module_requested)
            self.cards.append(card)
        content_layout.addWidget(self.gallery, 0, Qt.AlignmentFlag.AlignHCenter)
        content_layout.addStretch()
        scroll.setWidget(self.content); outer.addWidget(scroll)
        self._columns = 0
        self.gallery.setFixedWidth(max(440, min(1540, self.width() - 62)))
        self._arrange(self._column_count(self.width()))

    def _column_count(self, width):
        """Choisir le maximum confortable sans créer une rangée orpheline."""
        usable = max(0, min(width - 62, 1540))
        columns = max(2, min(5, (usable + 14) // (220 + 14)))
        if columns == 3 and len(self.cards) % columns == 1:
            columns = 2
        return columns

    def _arrange(self, columns):
        if columns == self._columns: return
        while self.grid.count(): self.grid.takeAt(0)
        for column in range(5):
            self.grid.setColumnStretch(column, 0)
        complete = len(self.cards) // columns
        remainder = len(self.cards) % columns
        for index, card in enumerate(self.cards):
            row, column = divmod(index, columns)
            if remainder and row == complete:
                column += (columns - remainder) // 2
            self.grid.addWidget(card, row, column)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        self._columns = columns

    def resizeEvent(self, event):
        self.gallery.setFixedWidth(max(440, min(1540, event.size().width() - 62)))
        self._arrange(self._column_count(event.size().width()))
        super().resizeEvent(event)
