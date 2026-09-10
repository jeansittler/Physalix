"""Petits composants de présentation sans logique scientifique."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QWidget, QBoxLayout, QScrollArea, QSizePolicy

from physalix.ui.theme import LIGHT


def role(widget, name):
    widget.setProperty("role", name)
    return widget


def refresh_style(widget):
    """Réappliquer les sélecteurs QSS après changement d’une propriété dynamique."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def label(text, kind="sectionTitle"):
    widget = role(QLabel(text), kind)
    widget.setWordWrap(True)
    return widget


def page_layout(layout):
    layout.setContentsMargins(LIGHT.page, LIGHT.section, LIGHT.page, LIGHT.section)
    layout.setSpacing(LIGHT.group)
    return layout


def page_header(title, description):
    widget = role(QWidget(), "pageHeader")
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, LIGHT.small)
    row.setSpacing(LIGHT.group)
    accent = role(QFrame(), "pageAccent")
    accent.setFixedSize(5, 42)
    row.addWidget(accent)
    text = QVBoxLayout()
    text.setSpacing(1)
    text.addWidget(label(title, "pageTitle"))
    text.addWidget(label(description, "pageSubtitle"))
    row.addLayout(text, 1)
    return widget


def panel(title=None, kind="card"):
    widget = role(QFrame(), kind)
    if kind in ("help", "toolbar"):
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    outer = QVBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    if title:
        header = role(QWidget(), "cardHeader")
        heading = QHBoxLayout(header)
        heading.setContentsMargins(LIGHT.section, 10, LIGHT.section, 10)
        heading.setSpacing(LIGHT.related)
        accent = role(QFrame(), "cardAccent")
        accent.setFixedSize(4, 20)
        heading.addWidget(accent)
        heading.addWidget(label(title, "cardTitle"), 1)
        outer.addWidget(header)
        divider = role(QFrame(), "cardDivider")
        divider.setFixedHeight(1)
        outer.addWidget(divider)
    content = QWidget()
    layout = QVBoxLayout(content)
    vertical = LIGHT.related if kind in ("help", "toolbar") else LIGHT.group
    layout.setContentsMargins(LIGHT.section, vertical, LIGHT.section, vertical)
    layout.setSpacing(vertical)
    outer.addWidget(content, 1)
    return widget, layout


def workspace_layout(owner, minimum_width, minimum_height):
    """Préserver l'accès aux outils par défilement sous la taille confortable."""
    outer = QVBoxLayout(owner)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    content.setMinimumSize(minimum_width, minimum_height)
    scroll.setWidget(content)
    outer.addWidget(scroll)
    return page_layout(QVBoxLayout(content))


def help_toggle(title, text, description=None):
    """Aide au clavier comme à la souris, repliée au lancement."""
    box, layout = panel(kind="help")
    heading = QHBoxLayout()
    if description:
        heading.addWidget(label(title, "pageTitle"))
        heading.addWidget(label(description, "pageSubtitle"), 1)
    else:
        heading.addWidget(label(title, "caption"), 1)
    toggle = QPushButton("Afficher l’aide")
    toggle.setCheckable(True)
    heading.addWidget(toggle)
    layout.addLayout(heading)
    details = label(text, "muted")
    details.hide()
    layout.addWidget(details)
    def expand(checked):
        details.setVisible(checked)
        toggle.setText("Masquer l’aide" if checked else "Afficher l’aide")
    toggle.toggled.connect(expand)
    return box


class ResponsiveCards(QWidget):
    """Deux cartes côte à côte, empilées lorsque la fenêtre est étroite."""

    def __init__(self, first, second, first_stretch=1, second_stretch=1):
        super().__init__()
        self.horizontal_stretch = first_stretch, second_stretch
        self.cards = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(LIGHT.section)
        self.cards.addWidget(first, 1)
        self.cards.addWidget(second, 1)
        self._set_direction(self.width())

    def _set_direction(self, width):
        direction = (QBoxLayout.Direction.LeftToRight if width >= LIGHT.wide_layout
                     else QBoxLayout.Direction.TopToBottom)
        if self.cards.direction() != direction:
            self.cards.setDirection(direction)
        for index, stretch in enumerate(self.horizontal_stretch):
            self.cards.setStretch(index, stretch if direction == QBoxLayout.Direction.LeftToRight else 0)

    def resizeEvent(self, event):
        self._set_direction(event.size().width())
        super().resizeEvent(event)


class ResponsiveActions(QWidget):
    """Aligner les actions sur une ligne, puis les empiler sans débordement."""

    def __init__(self, primary, secondary, tertiary):
        super().__init__()
        self.widgets = primary, secondary, tertiary
        self.actions = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(LIGHT.related)
        self._horizontal = None
        self._arrange(self.width() >= 1000)

    def _arrange(self, horizontal):
        if self._horizontal == horizontal:
            return
        while self.actions.count():
            self.actions.takeAt(0)
        self.actions.setDirection(QBoxLayout.Direction.LeftToRight if horizontal
                                  else QBoxLayout.Direction.TopToBottom)
        self.actions.addWidget(self.widgets[0], 0, Qt.AlignmentFlag.AlignLeft)
        self.actions.addWidget(self.widgets[1], 0, Qt.AlignmentFlag.AlignLeft)
        if horizontal:
            self.actions.addStretch()
        self.actions.addWidget(self.widgets[2], 0, Qt.AlignmentFlag.AlignLeft)
        self._horizontal = horizontal

    def resizeEvent(self, event):
        self._arrange(event.size().width() >= 1000)
        super().resizeEvent(event)
