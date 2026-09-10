"""GitHub Release updates, independent of Qt; no GitHub API or credentials."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from physalix import __version__

# Public binary distribution only. The source repository remains private.
DISTRIBUTION_REPOSITORY_URL = "https://github.com/jeansittler/Physalix-releases"
MANIFEST_URL = DISTRIBUTION_REPOSITORY_URL + "/releases/latest/download/update.json"
TIMEOUT = 10
CHECK_INTERVAL = 24 * 60 * 60
MAX_MANIFEST = 1024 * 1024
MAX_INSTALLER = 2 * 1024**3
CHUNK_SIZE = 256 * 1024
log = logging.getLogger(__name__)


class UpdateError(Exception):
    """A failure safe to report without exposing technical details."""


class IntegrityError(UpdateError):
    pass


class Cancelled(UpdateError):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise UpdateError("Invalid version")
    parts = tuple(map(int, value.split(".")))
    if any(part > 65535 for part in parts):
        raise UpdateError("Version outside Windows metadata range")
    return parts


def is_newer(remote, local=__version__):
    return version_tuple(remote) > version_tuple(local)


def development_override():
    return not getattr(sys, "frozen", False) and bool(os.environ.get("PHYSALIX_UPDATE_MANIFEST_URL"))


def manifest_url():
    return os.environ["PHYSALIX_UPDATE_MANIFEST_URL"] if development_override() else MANIFEST_URL


def validate_url(url, allow_local=False):
    if not isinstance(url, str) or any(ord(c) < 33 for c in url):
        raise UpdateError("Invalid URL")
    parsed = urlsplit(url)
    local = allow_local and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (parsed.scheme != "https" and not local) or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise UpdateError("HTTPS URL required")
    return url


@dataclass(frozen=True)
class Manifest:
    version: str
    installer_url: str
    sha256: str
    notes: str
    mandatory: bool

    @classmethod
    def parse(cls, raw, allow_local=False):
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise UpdateError("Manifest must be an object")
            version_tuple(data["version"])
            validate_url(data["installer_url"], allow_local)
            if not isinstance(data["sha256"], str) or not re.fullmatch(r"[a-fA-F0-9]{64}", data["sha256"]):
                raise UpdateError("Invalid SHA-256")
            if not isinstance(data["notes"], str) or len(data["notes"]) > 20000 or type(data["mandatory"]) is not bool:
                raise UpdateError("Invalid notes or mandatory flag")
            # Additional fields are intentionally ignored for forward compatibility.
            return cls(data["version"], data["installer_url"], data["sha256"].lower(), data["notes"], data["mandatory"])
        except (ValueError, KeyError, TypeError) as error:
            raise UpdateError("Invalid update manifest") from error


class SafeRedirect(HTTPRedirectHandler):
    def __init__(self, allow_local):
        super().__init__()
        self.allow_local = allow_local

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, self.allow_local)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url, allow_local=False):
    validate_url(url, allow_local)
    request = Request(url, headers={"User-Agent": f"Physalix/{__version__}", "Accept-Encoding": "identity"})
    return build_opener(SafeRedirect(allow_local)).open(request, timeout=TIMEOUT)


def read_chunks(response, maximum, cancel, deadline):
    size = 0
    while True:
        if cancel.is_set():
            raise Cancelled()
        if time.monotonic() > deadline:
            raise TimeoutError("Update transfer deadline exceeded")
        chunk = response.read(CHUNK_SIZE)
        if not chunk:
            return
        size += len(chunk)
        if size > maximum:
            raise UpdateError("Transfer too large")
        yield chunk


def fetch_manifest(url=None, cancel=None):
    log.info("Checking for updates; local version %s", __version__)
    with open_url(url or manifest_url(), development_override()) as response:
        raw = b"".join(read_chunks(response, MAX_MANIFEST, cancel or threading.Event(), time.monotonic() + 30))
    manifest = Manifest.parse(raw, development_override())
    log.info("Remote version %s", manifest.version)
    return manifest


def data_directory():
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    return base / "Physalix" / "updates"


def configure_logging(directory):
    if log.handlers:
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "updater.log", maxBytes=256 * 1024, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    except OSError:
        pass  # A read-only profile must never prevent application startup.


def claim_check(directory, manual=False, now=None):
    """Persist attempts before networking, including failures. Serialize Windows launches."""
    now = time.time() if now is None else now
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "check.lock").open("a+b") as lock:
            if sys.platform == "win32":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            path = directory / "state.json"
            try:
                last = json.loads(path.read_text(encoding="utf-8"))["last_check"]
                valid = type(last) in (int, float) and math.isfinite(last)
            except (OSError, ValueError, KeyError, TypeError):
                last, valid = 0, False
            if not manual and valid and 0 <= now - last < CHECK_INTERVAL:
                return False
            temporary = directory / "state.json.tmp"
            temporary.write_text(json.dumps({"last_check": now}), encoding="utf-8")
            temporary.replace(path)
            return True
    except OSError as error:
        log.warning("Check state unavailable (%s)", type(error).__name__)
        # Without persistent throttling skip automatic requests; manual still works.
        return manual


def sha256_file(path, cancel=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def remove_download(path):
    """Only remove the single file and its now-empty private temporary directory."""
    try:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    except OSError:
        log.warning("Temporary update cleanup failed")


def download_installer(manifest, progress=lambda done, total: None, cancel=None):
    cancel = cancel or threading.Event()
    folder = Path(tempfile.mkdtemp(prefix=f"Physalix-update-{manifest.version}-"))
    path = folder / f"Physalix-Setup-{manifest.version}.exe"
    log.info("Downloading installer %s", manifest.version)
    try:
        with open_url(manifest.installer_url, development_override()) as response, path.open("xb") as stream:
            total = int(response.headers.get("Content-Length", 0))
            if total < 0 or total > MAX_INSTALLER:
                raise UpdateError("Invalid installer size")
            done = 0
            for chunk in read_chunks(response, MAX_INSTALLER, cancel, time.monotonic() + 30 * 60):
                stream.write(chunk)
                done += len(chunk)
                progress(done, total)
        if cancel.is_set():
            raise Cancelled()
        if total and done != total:
            raise UpdateError("Incomplete installer")
        if not done or not hmac.compare_digest(sha256_file(path, cancel), manifest.sha256):
            raise IntegrityError("SHA-256 mismatch")
        log.info("SHA-256 validated for %s", manifest.version)
        return path
    except Exception:
        remove_download(path)
        raise


def _launch_elevated(path):
    """Request Windows consent/administrator credentials before returning success."""
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    execute = shell.ShellExecuteExW
    execute.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    execute.restype = wintypes.BOOL
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    initialized = ole.CoInitializeEx(None, 0x2 | 0x4)
    # Qt may already have initialized this thread in a different apartment.
    if initialized < 0 and initialized != -2147417850:  # RPC_E_CHANGED_MODE
        raise UpdateError("Cannot initialize Windows Shell")
    try:
        info = ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        # Wait for launch before closing Physalix; suppress errors, never UAC UI.
        info.fMask = 0x00000100 | 0x00000400  # NOASYNC | FLAG_NO_UI
        info.lpVerb = "runas"
        info.lpFile = str(path)
        info.lpParameters = "/SP- /NORESTART"
        info.lpDirectory = str(path.parent)
        info.nShow = 1  # SW_SHOWNORMAL
        if not execute(ctypes.byref(info)):
            error = ctypes.get_last_error()
            if error == 1223:  # ERROR_CANCELLED (consent or credentials refused)
                raise Cancelled("La mise à jour a été annulée.")
            raise ctypes.WinError(error)
    finally:
        if initialized in (0, 1):
            ole.CoUninitialize()


def launch_installer(path):
    """Launch verified Setup elevated, leaving Physalix itself unelevated."""
    if sys.platform != "win32":
        raise UpdateError("Windows installer required")
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise UpdateError("Installer is not a file")
    restore_dll = None
    original_path = os.environ.get("PATH")
    if getattr(sys, "frozen", False):
        import ctypes
        set_dll = ctypes.windll.kernel32.SetDllDirectoryW
        set_dll.argtypes = [ctypes.c_wchar_p]
        set_dll.restype = ctypes.c_int
        if not set_dll(None):
            raise OSError("Cannot reset DLL search path")
        restore_dll = lambda: set_dll(sys._MEIPASS)
    try:
        if getattr(sys, "frozen", False):
            root = Path(sys._MEIPASS).resolve()
            os.environ["PATH"] = os.pathsep.join(p for p in (original_path or "").split(os.pathsep)
                                               if p and not Path(p).resolve().is_relative_to(root))
        _launch_elevated(path)
        log.info("Elevated installer launched; installation not yet confirmed")
    finally:
        if restore_dll:
            if original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = original_path
            restore_dll()
