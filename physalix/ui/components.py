"""Petits composants de présentation sans logique scientifique."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QWidget, QBoxLayout, QScrollArea

from physalix.ui.theme import LIGHT


def role(widget, name):
    widget.setProperty("role", name)
    return widget


def label(text, kind="sectionTitle"):
    widget = role(QLabel(text), kind)
    widget.setWordWrap(True)
    return widget


def page_layout(layout):
    layout.setContentsMargins(LIGHT.page, LIGHT.section, LIGHT.page, LIGHT.section)
    layout.setSpacing(LIGHT.group)
    return layout


def panel(title=None):
    widget = role(QFrame(), "card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(LIGHT.section, LIGHT.group, LIGHT.section, LIGHT.group)
    layout.setSpacing(LIGHT.group)
    if title:
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(label(title, "cardTitle"))
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


def help_toggle(title, text):
    """Aide au clavier comme à la souris, repliée au lancement."""
    box, layout = panel()
    heading = QHBoxLayout()
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

    def __init__(self, first, second):
        super().__init__()
        self.cards = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(LIGHT.section)
        self.cards.addWidget(first, 1)
        self.cards.addWidget(second, 1)

    def resizeEvent(self, event):
        direction = (QBoxLayout.Direction.LeftToRight if event.size().width() >= LIGHT.wide_layout
                     else QBoxLayout.Direction.TopToBottom)
        if self.cards.direction() != direction:
            self.cards.setDirection(direction)
        super().resizeEvent(event)
