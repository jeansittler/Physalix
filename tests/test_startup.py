"""Démarrage précoce, splash et protection d'instance."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from physalix import app as app_module
from physalix.startup import SingleInstance
from physalix.ui.startup_splash import StartupSplash


class FakeWindowsApi:
    def __init__(self):
        self.locked = False
        self.next_handle = 1
        self.closed = []
        self.tagged = []
        self.untagged = []
        self.windows = []
        self.activated = []

    def create_mutex(self, _name):
        handle = self.next_handle
        self.next_handle += 1
        already_exists = self.locked
        if not already_exists:
            self.locked = True
        return handle, already_exists

    def close_handle(self, handle):
        self.closed.append(handle)
        if handle == 1:
            self.locked = False

    def tag_window(self, hwnd):
        self.tagged.append(hwnd)

    def untag_window(self, hwnd):
        self.untagged.append(hwnd)

    def find_window(self):
        return self.windows.pop(0) if self.windows else None

    def activate_window(self, hwnd):
        self.activated.append(hwnd)
        return True


class SingleInstanceTests(unittest.TestCase):
    def test_concurrent_launch_is_rejected_and_existing_window_activated(self):
        api = FakeWindowsApi()
        first = SingleInstance(platform="win32", api=api)
        second = SingleInstance(platform="win32", api=api)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())

        api.windows = [456]
        self.assertTrue(second.activate_existing(timeout=0))
        self.assertEqual(api.activated, [456])
        first.close()

    def test_multiple_double_clicks_are_rejected_until_owner_closes(self):
        api = FakeWindowsApi()
        owner = SingleInstance(platform="win32", api=api)
        self.assertTrue(owner.acquire())
        for _ in range(4):
            self.assertFalse(SingleInstance(platform="win32", api=api).acquire())
        owner.close()

        relaunched = SingleInstance(platform="win32", api=api)
        self.assertTrue(relaunched.acquire())
        relaunched.close()

    def test_activation_waits_for_window_published_during_startup(self):
        api = FakeWindowsApi()
        api.windows = [None, None, 789]
        now = [0.0]

        def sleep(delay):
            now[0] += delay

        instance = SingleInstance(
            platform="win32", api=api, clock=lambda: now[0], sleeper=sleep
        )
        self.assertTrue(instance.activate_existing(timeout=1.0, interval=0.1))
        self.assertEqual(api.activated, [789])

    def test_non_windows_platform_does_not_create_system_lock(self):
        api = FakeWindowsApi()
        instance = SingleInstance(platform="linux", api=api)
        self.assertTrue(instance.acquire())
        self.assertFalse(instance.activate_existing(timeout=0))
        self.assertEqual(api.next_handle, 1)

    @unittest.skipUnless(sys.platform == "win32", "Mutex nommé propre à Windows")
    def test_real_named_mutex_is_atomic_and_released(self):
        name = rf"Local\Physalix.Physalix.StartupTest.{os.getpid()}"
        owner = SingleInstance(name=name)
        self.assertTrue(owner.acquire())
        command = (
            "from physalix.startup import SingleInstance; "
            f"lock=SingleInstance(name={name!r}); "
            "raise SystemExit(0 if not lock.acquire() else 1)"
        )
        blocked = subprocess.run([sys.executable, "-c", command], cwd=os.getcwd())
        self.assertEqual(blocked.returncode, 0)
        owner.close()

        command = (
            "from physalix.startup import SingleInstance; "
            f"lock=SingleInstance(name={name!r}); acquired=lock.acquire(); lock.close(); "
            "raise SystemExit(0 if acquired else 1)"
        )
        relaunched = subprocess.run([sys.executable, "-c", command], cwd=os.getcwd())
        self.assertEqual(relaunched.returncode, 0)


class StartupSplashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_splash_is_borderless_uses_real_stages_and_finishes(self):
        splash = StartupSplash()
        window = QWidget()
        try:
            self.assertTrue(splash.windowFlags() & Qt.WindowType.FramelessWindowHint)
            self.assertFalse(splash.logo_label.pixmap().isNull())
            self.assertEqual((splash.activity.minimum(), splash.activity.maximum()), (0, 0))
            for message in (
                "Initialisation de Physalix…",
                "Chargement des composants…",
                "Préparation de l'interface…",
                "Ouverture de Physalix…",
            ):
                splash.set_stage(message)
                self.assertEqual(splash.message_label.text(), message)
            splash.show()
            window.show()
            self.app.processEvents()
            splash.finish(window)
            self.app.processEvents()
            self.assertFalse(splash.isVisible())
            self.assertTrue(window.isVisible())
        finally:
            splash.close()
            window.close()

    def test_startup_failure_closes_splash_without_showing_main_window(self):
        application = MagicMock()
        splash = MagicMock()
        with patch.object(app_module, "QApplication", return_value=application), \
                patch.object(app_module, "StartupSplash", return_value=splash), \
                patch.object(app_module, "_load_main_window", side_effect=RuntimeError("boom")), \
                patch.object(app_module, "set_windows_app_id"), \
                patch.object(app_module, "application_icon"), \
                patch.object(app_module, "apply_theme"):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                app_module.main()
        splash.close.assert_called_once_with()
        application.exec.assert_not_called()


if __name__ == "__main__":
    unittest.main()
