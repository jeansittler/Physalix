"""Contrôles visuels communs aux outils qui superposent des tracés."""

from PySide6.QtWidgets import QPushButton

from physalix.ui.components import role
from physalix.ui.icons import icon


def hide_traces_button(callback):
    button = role(QPushButton("Masquer les tracés"), "primary")
    button.setIcon(icon("eye_off", active=True))
    button.setToolTip("Masquer l’outil et retirer ses tracés temporaires")
    button.clicked.connect(callback)
    return button
