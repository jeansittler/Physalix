"""Qt presentation and asynchronous update orchestration."""
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QMessageBox,
                               QProgressDialog, QPushButton, QTextBrowser, QVBoxLayout)

from physalix import __version__
from physalix import updates


class UpdateDialog(QDialog):
    def __init__(self, manifest, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mise à jour disponible")
        self.resize(520, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Physalix {manifest.version} est disponible.\nVersion installée : {__version__}"))
        layout.addWidget(QLabel("Nouveautés :"))
        self.notes = QTextBrowser()
        self.notes.setPlainText(manifest.notes)
        self.notes.setOpenExternalLinks(False)
        layout.addWidget(self.notes)
        buttons = QDialogButtonBox()
        buttons.addButton("Mettre à jour", QDialogButtonBox.ButtonRole.AcceptRole)
        later = buttons.addButton("Plus tard", QDialogButtonBox.ButtonRole.RejectRole)
        later.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class UpdateController(QObject):
    completed = Signal(str, object, object)
    progress = Signal(object, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.busy = False
        self.stopped = False
        self.manual = False
        self.cancel = threading.Event()
        self.download_dialog = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.check)
        self.completed.connect(self.finish, Qt.ConnectionType.QueuedConnection)
        self.progress.connect(self.show_progress, Qt.ConnectionType.QueuedConnection)
        help_menu = window.menuBar().addMenu("Aide")
        help_menu.addAction("À propos de Physalix…", self.about)
        self.check_action = help_menu.addAction("Rechercher les mises à jour", self.manual_check)

    def start(self):
        # Called only by the real entry point, never by staging/test MainWindows.
        if updates.updates_enabled():
            self.timer.start(2500)

    def stop(self):
        self.stopped = True
        self.timer.stop()
        self.cancel.set()

    def about(self):
        dialog = QDialog(self.window)
        dialog.setWindowTitle("À propos de Physalix")
        layout = QVBoxLayout(dialog)
        label = QLabel(f"Physalix\nVersion {__version__}")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        button = QPushButton("Rechercher les mises à jour")
        button.setEnabled(not self.busy)
        if not updates.updates_enabled():
            button.setText("Mises à jour désactivées (version de développement)")
        button.clicked.connect(dialog.accept)
        layout.addWidget(button)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.manual_check()

    def run_job(self, kind, operation):
        self.busy = True
        self.check_action.setEnabled(False)
        self.cancel = threading.Event()
        cancel = self.cancel

        def work():
            result, error = None, None
            try:
                result = operation(cancel)
            except Exception as caught:
                error = caught
                # Exception messages can contain user/proxy paths or signed URLs.
                updates.log.warning("Update %s failed (%s)", kind, type(caught).__name__)
            if cancel.is_set() and kind == "download" and result:
                updates.remove_download(result)
                result, error = None, updates.Cancelled()
            try:
                self.completed.emit(kind, result, error)
            except RuntimeError:
                if kind == "download" and result:
                    updates.remove_download(result)

        # No QThread destructor crash or network wait when the main window closes.
        threading.Thread(target=work, name=f"Physalix-update-{kind}", daemon=True).start()

    @Slot()
    def manual_check(self):
        if not updates.updates_enabled():
            QMessageBox.information(
                self.window,
                "Mise à jour",
                "La recherche de mises à jour est désactivée pour cette version de développement.",
            )
            return
        self.check(manual=True)

    def check(self, manual=False):
        if self.busy or self.stopped:
            return
        if not updates.updates_enabled():
            if manual:
                self.manual_check()
            return
        self.manual = manual
        if manual:
            self.window.statusBar().showMessage("Recherche des mises à jour…")

        def operation(cancel):
            directory = updates.data_directory()
            if updates.development_override():
                directory = directory / "development"
            updates.configure_logging(directory)
            if not updates.claim_check(directory, manual):
                return None
            return updates.fetch_manifest(cancel=cancel)

        self.run_job("check", operation)

    @Slot(object, object)
    def show_progress(self, done, total):
        if self.download_dialog is not None:
            self.download_dialog.setRange(0, 100 if total else 0)
            if total:
                self.download_dialog.setValue(min(99, int(done * 100 / total)))
            self.download_dialog.setLabelText(f"Téléchargement de Physalix… {done / 1024**2:.1f} Mo")

    @Slot(str, object, object)
    def finish(self, kind, result, error):
        self.busy = False
        self.check_action.setEnabled(True)
        if self.download_dialog is not None:
            self.download_dialog.canceled.disconnect()
            self.download_dialog.close()
            self.download_dialog.deleteLater()
            self.download_dialog = None
        if self.stopped or self.cancel.is_set():
            if kind == "download" and result:
                updates.remove_download(result)
            return
        self.window.statusBar().clearMessage()
        if error:
            if kind == "download" or self.manual:
                text = ("La mise à jour n’a pas pu être vérifiée. Le fichier a été supprimé. Réessayez plus tard."
                        if isinstance(error, updates.IntegrityError) else
                        "Impossible de récupérer la mise à jour pour le moment. Réessayez plus tard.")
                QMessageBox.information(self.window, "Mise à jour", text)
            return
        if kind == "check":
            if result is None:
                return
            if not updates.is_newer(result.version):
                if self.manual:
                    QMessageBox.information(self.window, "Mise à jour", "Physalix est à jour.")
                return
            # Keep checks disabled while the modal offer is open (nested Qt event loop).
            self.busy = True
            self.check_action.setEnabled(False)
            accepted = UpdateDialog(result, self.window).exec() == QDialog.DialogCode.Accepted
            self.busy = False
            self.check_action.setEnabled(True)
            if accepted and not self.stopped:
                self.download(result)
        else:
            self.busy = True
            self.check_action.setEnabled(False)
            try:
                self.install(result)
            finally:
                self.busy = False
                self.check_action.setEnabled(not self.stopped)

    def download(self, manifest):
        self.download_dialog = QProgressDialog("Téléchargement de Physalix…", "Annuler", 0, 0, self.window)
        self.download_dialog.setWindowTitle("Mise à jour de Physalix")
        self.download_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.download_dialog.setMinimumDuration(0)
        self.download_dialog.setAutoClose(False)
        self.download_dialog.setAutoReset(False)
        self.download_dialog.canceled.connect(lambda: self.cancel.set())
        self.run_job("download", lambda cancel: updates.download_installer(manifest, self.progress.emit, cancel))
        self.download_dialog.show()

    def install(self, path):
        # Confirm/save after download: edits made while checking are included.
        if not self.window.confirm_save():
            updates.remove_download(path)
            return
        try:
            updates.launch_installer(path)
        except updates.Cancelled:
            updates.log.info("Installer elevation cancelled")
            updates.remove_download(path)
            QMessageBox.information(self.window, "Mise à jour", "La mise à jour a été annulée.")
            return
        except Exception as error:
            updates.log.warning("Installer launch failed (%s)", type(error).__name__)
            updates.remove_download(path)
            QMessageBox.information(self.window, "Mise à jour", "L’installation n’a pas pu démarrer. Votre projet reste ouvert.")
            return
        # Save/discard was confirmed above; no second prompt after launching Setup.
        self.window._discard_on_close = True
        self.window.close()
