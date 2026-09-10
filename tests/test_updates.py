import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from urllib.error import URLError

from physalix import updates as u


def manifest_data(**changes):
    data = dict(version="1.1.1", installer_url="https://github.com/jeansittler/Physalix-releases/releases/download/v1.1.1/Physalix-Setup-1.1.1.exe",
                sha256=hashlib.sha256(b"installer").hexdigest(), notes="Corrections", mandatory=False)
    data.update(changes)
    return data


def manifest(**changes):
    return u.Manifest.parse(json.dumps(manifest_data(**changes)))


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}


class UpdateTests(unittest.TestCase):
    def test_public_distribution_endpoint(self):
        self.assertEqual(u.MANIFEST_URL,
                         "https://github.com/jeansittler/Physalix-releases/releases/latest/download/update.json")

    def test_versions(self):
        for local, remote, expected in [("1.1.0", "1.1.0", False), ("1.1.0", "1.1.1", True),
                ("1.1.9", "1.2.0", True), ("1.9.9", "2.0.0", True), ("1.2.0", "1.1.9", False),
                ("1.9.0", "1.10.0", True)]:
            with self.subTest(local=local, remote=remote):
                self.assertEqual(u.is_newer(remote, local), expected)

    def test_invalid_versions(self):
        for value in ("1.1", "v1.1.0", "1.1.0-beta", "01.1.0", None, "1.1.999999", "1.1.0/../../x"):
            with self.subTest(value=value), self.assertRaises(u.UpdateError):
                u.version_tuple(value)

    def test_invalid_json_and_required_fields(self):
        for raw in ("{", "[]", "null", b"\xff"):
            with self.subTest(raw=raw), self.assertRaises(u.UpdateError):
                u.Manifest.parse(raw)
        for field in manifest_data():
            data = manifest_data()
            del data[field]
            with self.subTest(field=field), self.assertRaises(u.UpdateError):
                u.Manifest.parse(json.dumps(data))

    def test_types_and_forward_compatibility(self):
        for changes in (dict(mandatory="false"), dict(sha256="x" * 64), dict(notes=[]), dict(installer_url="file:///x")):
            with self.subTest(changes=changes), self.assertRaises(u.UpdateError):
                manifest(**changes)
        self.assertTrue(manifest(mandatory=True, future_field={}).mandatory)
        self.assertEqual(manifest(sha256="A" * 64).sha256, "a" * 64)

    def test_network_and_timeout_failures(self):
        for error in (URLError("offline"), TimeoutError("timeout")):
            with self.subTest(error=error), patch.object(u, "updates_enabled", return_value=True), patch.object(u, "open_url", side_effect=error), self.assertRaises(type(error)):
                u.fetch_manifest()
        with patch.object(u, "updates_enabled", return_value=True), patch.object(u, "open_url", return_value=Response(b"invalid")), self.assertRaises(u.UpdateError):
            u.fetch_manifest()

    def test_fetch(self):
        with patch.object(u, "updates_enabled", return_value=True), patch.object(u, "open_url", return_value=Response(json.dumps(manifest_data()).encode())) as request:
            self.assertEqual(u.fetch_manifest().version, "1.1.1")
            self.assertEqual(request.call_args.args[0], u.MANIFEST_URL)

    def test_development_build_disables_release_checks(self):
        self.assertFalse(u.updates_enabled())
        self.assertFalse(u.is_newer("1.1.3"))
        self.assertFalse(u.is_newer("1.2.0"))
        self.assertTrue(u.is_newer("1.2.1"))
        with patch.object(u, "open_url") as request, self.assertRaises(u.UpdateError):
            u.fetch_manifest()
        request.assert_not_called()

    def test_transport_timeout_and_redirect_security(self):
        with patch.object(u, "build_opener") as opener:
            u.open_url(u.MANIFEST_URL)
            self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 10)
        with self.assertRaises(u.UpdateError):
            u.SafeRedirect(False).redirect_request(None, None, 302, "", {}, "http://example.com/x")
        for url in ("http://example.com/x", "file:///tmp/x", "https://user:secret@github.com/x", "https://github.com/x\n"):
            with self.subTest(url=url), self.assertRaises(u.UpdateError):
                u.validate_url(url)
        u.validate_url("http://127.0.0.1:8765/update.json", True)

    def test_override_only_in_source(self):
        with patch.dict("os.environ", PHYSALIX_UPDATE_MANIFEST_URL="http://127.0.0.1:8765/update.json"):
            with patch.object(u.sys, "frozen", False, create=True):
                self.assertIn("127.0.0.1", u.manifest_url())
            with patch.object(u.sys, "frozen", True, create=True):
                self.assertEqual(u.manifest_url(), u.MANIFEST_URL)
                self.assertFalse(u.development_override())

    def test_throttle_attempts_manual_and_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            self.assertTrue(u.claim_check(path, now=100000))
            self.assertFalse(u.claim_check(path, now=100001))
            self.assertTrue(u.claim_check(path, manual=True, now=100002))
            self.assertFalse(u.claim_check(path, now=100003))
            self.assertTrue(u.claim_check(path, now=100002 + u.CHECK_INTERVAL))
            self.assertTrue(u.claim_check(path, now=1))  # Clock moved backwards.
            (path / "state.json").write_text("corrupt")
            self.assertTrue(u.claim_check(path, now=10))

    def test_unwritable_state(self):
        with patch.object(Path, "mkdir", side_effect=PermissionError):
            self.assertFalse(u.claim_check(Path("unused")))
            self.assertTrue(u.claim_check(Path("unused"), manual=True))

    def test_download_valid_hash_and_progress(self):
        content = b"installer" * (u.CHUNK_SIZE // 9 + 3)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "private"
            target.mkdir()
            with patch.object(u.tempfile, "mkdtemp", return_value=str(target)), patch.object(u, "open_url", return_value=Response(content, {"Content-Length": str(len(content))})):
                progress = Mock()
                result = u.download_installer(manifest(sha256=hashlib.sha256(content).hexdigest()), progress)
                self.assertEqual(result.name, "Physalix-Setup-1.1.1.exe")
                self.assertEqual(u.sha256_file(result), hashlib.sha256(content).hexdigest())
                self.assertGreater(progress.call_count, 1)
                progress.assert_called_with(len(content), len(content))

    def test_bad_hash_incomplete_cancel_and_cleanup(self):
        for content, headers, cancel, error in [(b"wrong", {}, False, u.IntegrityError),
                (b"installer", {"Content-Length": "100"}, False, u.UpdateError),
                (b"installer", {}, True, u.Cancelled)]:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "private"
                target.mkdir()
                event = threading.Event()
                if cancel:
                    event.set()
                with patch.object(u.tempfile, "mkdtemp", return_value=str(target)), patch.object(u, "open_url", return_value=Response(content, headers)), self.assertRaises(error):
                    u.download_installer(manifest(), cancel=event)
                self.assertFalse(target.exists())

    def test_limits_and_deadline(self):
        with self.assertRaises(u.UpdateError):
            list(u.read_chunks(Response(b"abc"), 2, threading.Event(), float("inf")))
        with self.assertRaises(TimeoutError):
            list(u.read_chunks(Response(b"abc"), 10, threading.Event(), 0))

    def test_hash_verification_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "installer.exe"
            path.write_bytes(b"installer")
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(u.Cancelled):
                u.sha256_file(path, cancel)

    def test_launch_requests_windows_elevation(self):
        import ctypes
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "Physalix été Setup.exe"
            path.write_bytes(b"fake")
            shell, ole = Mock(), Mock()
            ole.CoInitializeEx.return_value = 0
            def execute(pointer):
                info = pointer._obj
                self.assertEqual(info.cbSize, ctypes.sizeof(info))
                self.assertEqual(info.lpVerb, "runas")
                self.assertEqual(info.lpFile, str(path.resolve()))
                self.assertEqual(info.lpParameters, "/SP- /NORESTART")
                self.assertEqual(info.lpDirectory, str(path.parent.resolve()))
                self.assertEqual(info.fMask, 0x500)
                self.assertEqual(info.nShow, 1)
                return True
            shell.ShellExecuteExW.side_effect = execute
            with patch.object(ctypes, "WinDLL", side_effect=[shell, ole], create=True), patch.object(u.sys, "platform", "win32"), patch.object(u.sys, "frozen", False, create=True):
                u.launch_installer(path)
            shell.ShellExecuteExW.assert_called_once()
            ole.CoUninitialize.assert_called_once()

    def test_windows_cancel_and_launch_errors(self):
        import ctypes
        for code, expected in [(1223, u.Cancelled), (5, OSError), (2, OSError)]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "Setup.exe"
                path.write_bytes(b"fake")
                shell, ole = Mock(), Mock()
                shell.ShellExecuteExW.return_value = False
                ole.CoInitializeEx.return_value = 1
                with patch.object(ctypes, "WinDLL", side_effect=[shell, ole], create=True), patch.object(ctypes, "get_last_error", return_value=code, create=True), patch.object(u.sys, "platform", "win32"), self.assertRaises(expected):
                    u.launch_installer(path)
                ole.CoUninitialize.assert_called_once()

    def test_missing_installer_and_directory_never_call_windows(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(u, "_launch_elevated") as launch, patch.object(u.sys, "platform", "win32"):
            with self.assertRaises(FileNotFoundError):
                u.launch_installer(Path(folder) / "missing.exe")
            with self.assertRaises(u.UpdateError):
                u.launch_installer(Path(folder))
            launch.assert_not_called()

    def test_frozen_environment_restored_after_success_cancel_or_error(self):
        import ctypes
        for error in (None, u.Cancelled(), OSError()):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                path = root / "Setup.exe"
                path.write_bytes(b"fake")
                bundled = root / "_internal"
                original = str(bundled) + u.os.pathsep + str(root)
                set_dll = Mock(return_value=1)
                def execute(path):
                    self.assertEqual(u.os.environ["PATH"], str(root))
                    if error:
                        raise error
                with patch.object(u.sys, "platform", "win32"), patch.object(u.sys, "frozen", True, create=True), patch.object(u.sys, "_MEIPASS", str(bundled), create=True), patch.dict(u.os.environ, PATH=original), patch.object(ctypes.windll.kernel32, "SetDllDirectoryW", set_dll), patch.object(u, "_launch_elevated", side_effect=execute):
                    if error:
                        with self.assertRaises(type(error)):
                            u.launch_installer(path)
                    else:
                        u.launch_installer(path)
                    self.assertEqual(u.os.environ["PATH"], original)
                    self.assertEqual([c.args for c in set_dll.call_args_list], [(None,), (str(bundled),)])


class ReleaseTests(unittest.TestCase):
    def test_installer_identity_and_settings(self):
        root = Path(__file__).resolve().parents[1]
        iss = (root / "packaging/installer/Physalix.iss").read_text(encoding="utf-8")
        for line in ("AppId={{807A4F23-674E-4CD3-9B57-D66B7B819B72}", "UsePreviousAppDir=yes",
                     "PrivilegesRequired=admin", "ArchitecturesInstallIn64BitMode=x64compatible",
                     "DefaultDirName={autopf}\\Physalix", "AppVersion={#AppVersion}"):
            self.assertIn(line, iss)

    def test_manifest_generation(self):
        from scripts import prepare_release
        from physalix import __base_version__
        from physalix import __version_info__
        major, minor, patch_version = __version_info__
        with tempfile.TemporaryDirectory() as folder, patch.object(
            prepare_release, "__version__", __base_version__
        ):
            path = Path(folder)
            with self.assertRaises(ValueError):
                prepare_release.prepare(path, "Notes")
            content = b"fake PE handled by mock"
            (path / f"Physalix-Setup-{__base_version__}.exe").write_bytes(content)
            with patch("pefile.PE") as pe:
                fixed = pe.return_value.__enter__.return_value.VS_FIXEDFILEINFO[0]
                fixed.FileVersionMS = (major << 16) | minor
                fixed.FileVersionLS = patch_version << 16
                result = json.loads(prepare_release.prepare(path, "Notes é").read_text(encoding="utf-8"))
                self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())
                self.assertEqual(result["installer_url"], f"https://github.com/jeansittler/Physalix-releases/releases/download/v{__base_version__}/Physalix-Setup-{__base_version__}.exe")
                fixed.FileVersionMS = 0
                with self.assertRaises(ValueError):
                    prepare_release.prepare(path, "Notes")
