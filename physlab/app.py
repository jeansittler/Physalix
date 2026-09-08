"""Création de l'application et démarrage de la boucle Qt."""

import sys

from PySide6.QtWidgets import QApplication

from physlab.ui.main_window import MainWindow
from physlab.ui.theme import apply_theme


def main() -> int:
    """Lancer l'interface de Physalyx."""
    app = QApplication(sys.argv)
    app.setApplicationName("Physalyx")
    apply_theme(app)

    window = MainWindow()
    window.show()

    return app.exec()
