import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QDialog

from physalix import __version__, updates
from physalix.ui.updates import UpdateController, UpdateDialog


class UpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QMainWindow()
        self.window.confirm_save = Mock(return_value=True)
        self.controller = UpdateController(self.window)

    def tearDown(self):
        self.controller.stop()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def wait_done(self):
        deadline = time.monotonic() + 3
        while self.controller.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertFalse(self.controller.busy)

    def test_automatic_silent_manual_feedback(self):
        c = self.controller
        current = updates.Manifest(__version__, "https://example.com/i.exe", "a" * 64, "Notes", False)
        with patch("physalix.ui.updates.QMessageBox.information") as info:
            c.finish("check", current, None)
            c.finish("check", None, TimeoutError())
            info.assert_not_called()
            c.manual = True
            c.finish("check", current, None)
            self.assertEqual(info.call_args.args[2], "Physalix est à jour.")
            c.finish("check", None, TimeoutError())
            self.assertEqual(info.call_count, 2)

    def test_network_runs_off_gui_thread_and_manual_bypasses_cache(self):
        release = threading.Event()
        started = threading.Event()
        threads = []
        def fetch(**kwargs):
            threads.append(threading.get_ident())
            started.set()
            release.wait(2)
            return updates.Manifest(__version__, "https://example.com/i.exe", "a" * 64, "", False)
        with tempfile.TemporaryDirectory() as folder, patch.object(updates, "data_directory", return_value=Path(folder)), patch.object(updates, "configure_logging"), patch.object(updates, "fetch_manifest", side_effect=fetch) as request, patch("physalix.ui.updates.QMessageBox.information"):
            updates.claim_check(Path(folder))
            self.controller.check()
            self.wait_done()
            request.assert_not_called()
            self.controller.manual_check()
            self.assertTrue(started.wait(1))
            tick = Mock()
            QTimer.singleShot(0, tick)
            self.app.processEvents()
            tick.assert_called_once()
            self.assertNotEqual(threads[0], threading.get_ident())
            release.set()
            self.wait_done()
            request.assert_called_once()

    def test_shutdown_during_check(self):
        release = threading.Event()
        done = threading.Event()
        def operation(cancel):
            release.wait(2)
            done.set()
            return None
        self.controller.run_job("check", operation)
        self.controller.stop()
        release.set()
        self.assertTrue(done.wait(1))
        self.wait_done()

    def test_download_result_survives_progress_dialog_close(self):
        with patch.object(updates, "download_installer", return_value=Path("fake.exe")), patch.object(self.controller, "install") as install:
            self.controller.download(updates.Manifest("1.1.1", "https://example.com/i.exe", "a" * 64, "", False))
            self.wait_done()
            install.assert_called_once_with(Path("fake.exe"))

    def test_save_prompt_cannot_start_another_check(self):
        def install(path):
            self.assertTrue(self.controller.busy)
            self.controller.check()
        with patch.object(self.controller, "install", side_effect=install), patch.object(self.controller, "run_job") as job:
            self.controller.finish("download", Path("fake.exe"), None)
            job.assert_not_called()
            self.assertFalse(self.controller.busy)

    def test_cancel_download_allows_retry(self):
        started = threading.Event()
        def download(manifest, progress, cancel):
            started.set()
            cancel.wait(2)
            raise updates.Cancelled()
        with patch.object(updates, "download_installer", side_effect=download), patch.object(self.controller, "install") as install, patch("physalix.ui.updates.QMessageBox.information") as info:
            self.controller.download(None)
            self.assertTrue(started.wait(1))
            self.controller.cancel.set()
            self.wait_done()
            install.assert_not_called()
            info.assert_not_called()
            self.assertTrue(self.controller.check_action.isEnabled())

    def test_bad_hash_never_launches(self):
        with patch.object(updates, "launch_installer") as launch, patch("physalix.ui.updates.QMessageBox.information") as info:
            self.controller.finish("download", None, updates.IntegrityError())
            launch.assert_not_called()
            self.assertIn("vérifiée", info.call_args.args[2])

    def test_save_cancel_and_launch_failure_keep_project_open(self):
        self.window.confirm_save.return_value = False
        with patch.object(updates, "launch_installer") as launch, patch.object(updates, "remove_download") as cleanup, patch.object(self.window, "close") as close:
            self.controller.install(Path("fake.exe"))
            launch.assert_not_called()
            close.assert_not_called()
            cleanup.assert_called_once()
        self.window.confirm_save.return_value = True
        with patch.object(updates, "launch_installer", side_effect=OSError), patch.object(updates, "remove_download"), patch.object(self.window, "close") as close, patch("physalix.ui.updates.QMessageBox.information"):
            self.controller.install(Path("fake.exe"))
            close.assert_not_called()

    def test_successful_handoff_saves_then_closes(self):
        sequence = []
        self.window.confirm_save.side_effect = lambda: sequence.append("save") or True
        with patch.object(updates, "launch_installer", side_effect=lambda p: sequence.append("launch")), patch.object(self.window, "close", side_effect=lambda: sequence.append("close")):
            self.controller.install(Path("fake.exe"))
            self.assertEqual(sequence, ["save", "launch", "close"])
            self.assertTrue(self.window._discard_on_close)

    def test_notes_are_plain_text_and_mandatory_is_optional(self):
        notes = '<a href="https://example.com">Text</a>'
        dialog = UpdateDialog(updates.Manifest("1.1.1", "https://example.com/i.exe", "a" * 64, notes, True))
        self.assertEqual(dialog.notes.toPlainText(), notes)
        dialog.reject()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        dialog.deleteLater()
