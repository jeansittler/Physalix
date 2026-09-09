"""Création de l'application et démarrage de la boucle Qt."""

import sys

from PySide6.QtWidgets import QApplication

from physalix.ui.main_window import MainWindow
from physalix.ui.theme import apply_theme
from physalix.ui.branding import application_icon, set_windows_app_id


def main() -> int:
    """Lancer l'interface de Physalix."""
    set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("Physalix")
    app.setWindowIcon(application_icon())
    apply_theme(app)

    window = MainWindow()
    window.show()

    return app.exec()
