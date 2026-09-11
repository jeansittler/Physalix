"""Création de l'application et démarrage de la boucle Qt."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from physalix.project import LEGACY_SUFFIX, PROJECT_SUFFIX
from physalix.ui.main_window import MainWindow
from physalix.ui.theme import apply_theme
from physalix.ui.branding import application_icon, set_windows_app_id
from physalix import __version__


def project_path_from_arguments(arguments) -> Path | None:
    """Return the supported project path passed on the command line, if any."""
    for argument in arguments[1:]:
        path = Path(argument)
        if path.suffix.lower() in (PROJECT_SUFFIX, LEGACY_SUFFIX):
            return path
    return None


def main() -> int:
    """Lancer l'interface de Physalix."""
    set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("Physalix")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(application_icon())
    apply_theme(app)

    window = MainWindow()
    window.show()
    project_path = project_path_from_arguments(app.arguments())
    if project_path is not None:
        window.open_project_path(project_path)
    window.updater.start()
    app.aboutToQuit.connect(window.updater.stop)

    return app.exec()
