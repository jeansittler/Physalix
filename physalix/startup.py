"""Protection d'instance et activation Windows avant le chargement de Qt."""

from __future__ import annotations

import ctypes
import sys
import time


MUTEX_NAME = r"Local\Physalix.Physalix.SingleInstance"
WINDOW_PROPERTY = "Physalix.Physalix.ApplicationWindow"
ERROR_ALREADY_EXISTS = 183


class _WindowsApi:
    """Petit adaptateur Win32, chargé uniquement sur Windows."""

    def __init__(self):
        from ctypes import wintypes

        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._user32.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
        self._user32.SetPropW.restype = wintypes.BOOL
        self._user32.RemovePropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self._user32.RemovePropW.restype = wintypes.HANDLE
        self._user32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self._user32.GetPropW.restype = wintypes.HANDLE
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL
        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self._user32.EnumWindows.argtypes = [self._enum_callback, wintypes.LPARAM]
        self._user32.EnumWindows.restype = wintypes.BOOL

    def create_mutex(self, name):
        ctypes.set_last_error(0)
        handle = self._kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "Impossible de créer le mutex Physalyx.")
        return handle, ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def close_handle(self, handle):
        self._kernel32.CloseHandle(handle)

    def tag_window(self, hwnd):
        if not self._user32.SetPropW(hwnd, WINDOW_PROPERTY, 1):
            raise OSError(ctypes.get_last_error(), "Impossible d'identifier la fenêtre Physalyx.")

    def untag_window(self, hwnd):
        self._user32.RemovePropW(hwnd, WINDOW_PROPERTY)

    def find_window(self):
        found = []

        @self._enum_callback
        def visit(hwnd, _parameter):
            if self._user32.IsWindowVisible(hwnd) and self._user32.GetPropW(
                hwnd, WINDOW_PROPERTY
            ):
                found.append(hwnd)
                return False
            return True

        self._user32.EnumWindows(visit, 0)
        return found[0] if found else None

    def activate_window(self, hwnd):
        self._user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        return bool(self._user32.SetForegroundWindow(hwnd))


class SingleInstance:
    """Conserver un mutex de session et retrouver la fenêtre de l'instance active."""

    def __init__(
        self, *, name=MUTEX_NAME, platform=None, api=None, clock=None, sleeper=None
    ):
        self._name = name
        self._platform = sys.platform if platform is None else platform
        self._api = api
        self._handle = None
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep

    @property
    def enabled(self):
        return self._platform == "win32"

    def _windows(self):
        if self._api is None:
            self._api = _WindowsApi()
        return self._api

    def acquire(self):
        if not self.enabled:
            return True
        if self._handle is not None:
            return True
        handle, already_exists = self._windows().create_mutex(self._name)
        if already_exists:
            self._windows().close_handle(handle)
            return False
        self._handle = handle
        return True

    def activate_existing(self, timeout=1.5, interval=0.05):
        """Attendre brièvement que le premier lancement publie sa fenêtre."""

        if not self.enabled:
            return False
        deadline = self._clock() + max(0.0, timeout)
        while True:
            hwnd = self._windows().find_window()
            if hwnd is not None:
                return self._windows().activate_window(hwnd)
            if self._clock() >= deadline:
                return False
            self._sleep(min(interval, max(0.0, deadline - self._clock())))

    def tag_window(self, window):
        if self.enabled:
            self._windows().tag_window(int(window.winId()))

    def untag_window(self, window):
        if self.enabled:
            self._windows().untag_window(int(window.winId()))

    def close(self):
        if self._handle is not None:
            self._windows().close_handle(self._handle)
            self._handle = None

    def __del__(self):
        self.close()


def show_startup_error(error):
    """Afficher une erreur compréhensible même si Qt n'a pas pu démarrer."""

    message = f"Physalyx n'a pas pu démarrer.\n\n{error}"
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "Démarrage de Physalyx", 0x10)
    else:
        print(message, file=sys.stderr)
