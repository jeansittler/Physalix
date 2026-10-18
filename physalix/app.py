"""Création de l'application et démarrage de la boucle Qt."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from physalix.project import LEGACY_SUFFIX, PROJECT_SUFFIX
from physalix.ui.theme import apply_theme
from physalix.ui.branding import application_icon, set_windows_app_id
from physalix.ui.startup_splash import StartupSplash
from physalix import __version__


def project_path_from_arguments(arguments) -> Path | None:
    """Return the supported project path passed on the command line, if any."""
    for argument in arguments[1:]:
        path = Path(argument)
        if path.suffix.lower() in (PROJECT_SUFFIX, LEGACY_SUFFIX):
            return path
    return None


def _load_main_window():
    """Retarder le graphe d'imports principal jusqu'après l'affichage du splash."""

    from physalix.ui.main_window import MainWindow

    return MainWindow


def main(instance_guard=None) -> int:
    """Lancer l'interface de Physalyx."""
    set_windows_app_id()
    app = QApplication(sys.argv)
    # Keep the internal name: QStandardPaths uses it for existing local data.
    app.setApplicationName("Physalix")
    app.setApplicationDisplayName("Physalyx")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(application_icon())
    apply_theme(app)

    splash = StartupSplash()
    splash.show()
    if instance_guard is not None:
        instance_guard.tag_window(splash)
    app.processEvents()

    try:
        splash.set_stage("Chargement des composants…")
        app.processEvents()
        MainWindow = _load_main_window()
        splash.set_stage("Préparation de l'interface…")
        app.processEvents()
        window = MainWindow()
        project_path = project_path_from_arguments(app.arguments())
        if project_path is not None:
            splash.set_stage("Ouverture du projet…")
            app.processEvents()
            window.open_project_path(project_path)
        else:
            splash.set_stage("Ouverture de Physalyx…")
        window.show()
        if instance_guard is not None:
            instance_guard.tag_window(window)
            instance_guard.untag_window(splash)
        splash.finish(window)
    except Exception:
        splash.close()
        app.processEvents()
        raise

    window.updater.start()
    app.aboutToQuit.connect(window.updater.stop)

    return app.exec()
