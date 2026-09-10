"""Build preflight and isolated frozen smoke test; standard library + build tools."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = runpy.run_path(str(ROOT / "physalix/_version.py"))["__version__"]


def environment():
    assert sys.platform == "win32" and platform.machine().lower() in ("amd64", "x86_64")
    assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32, "Use CPython 3.12 x64"
    assert re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", VERSION)
    assert all(int(x) <= 65535 for x in VERSION.split("."))
    for line in (ROOT / "packaging/requirements-build.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            name, expected = line.split("==")
            actual = importlib.metadata.version(name)
            assert actual == expected, f"{name}: {actual} != {expected}; install packaging/requirements-build.txt"
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    print(f"Environment OK: Python {platform.python_version()}, Physalix {VERSION}")


def bundle(directory):
    from PyInstaller.archive.readers import CArchiveReader
    import pefile
    directory = directory.resolve()
    exe = directory / "Physalix.exe"
    pe = pefile.PE(str(exe))
    assert pe.FILE_HEADER.Machine == 0x8664
    assert pe.OPTIONAL_HEADER.Subsystem == 2, "GUI executable expected"
    fixed = pe.VS_FIXEDFILEINFO[0]
    major, minor, patch = map(int, VERSION.split("."))
    assert (fixed.FileVersionMS, fixed.FileVersionLS) == ((major << 16) | minor, patch << 16)
    pe.close()
    modules = CArchiveReader(str(exe)).open_embedded_archive("PYZ.pyz").toc
    assert "physalix.app" in modules and "numpy" in modules and "scipy" in modules
    assert all(name in modules for name in ("physalix.updates", "physalix.ui.updates", "urllib.request", "ssl"))
    assert not any(n.startswith(("physlab", "physalyx", "tests.")) for n in modules)
    forbidden = {".venv", ".git", ".github", ".pytest_cache", "__pycache__", "tests", "build", "dist"}
    for path in directory.rglob("*"):
        assert not forbidden.intersection(path.relative_to(directory).parts), path
    for source in (ROOT / "physalix/ui/resources").rglob("*"):
        if source.is_file():
            target = directory / "_internal" / source.relative_to(ROOT)
            assert target.read_bytes() == source.read_bytes(), target
    for name in ("python312.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "MSVCP140.dll"):
        assert list(directory.rglob(name)), f"Missing runtime: {name}"
    assert list(directory.rglob("qwindows.dll")), "Windows Qt plugin missing"
    for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md", "LISEZ-MOI.txt"):
        assert (directory / "_internal" / notice).is_file(), f"Missing distribution notice: {notice}"
    for notice in ("README.md", "components.json"):
        target = directory / "_internal" / "third_party" / notice
        assert target.is_file(), f"Missing third-party compliance file: {target}"
    assert list((directory / "_internal" / "third_party" / "licenses").glob("*.txt")), \
        "Missing third-party license texts"
    env = os.environ.copy()
    for key in list(env):
        if key.upper().startswith(("PYTHON", "QT_", "PYSIDE", "VIRTUAL_ENV", "CONDA")):
            del env[key]
    windows = os.environ["SystemRoot"]
    env["PATH"] = os.pathsep.join([str(Path(windows) / "System32"), windows])
    with tempfile.TemporaryDirectory(prefix="Physalix external cwd ") as temporary:
        report = Path(temporary) / "report.json"
        result = subprocess.run([str(exe), "--distribution-check", str(report)], cwd=temporary,
                                env=env, timeout=90, capture_output=True)
        data = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
        data["exit_code"] = result.returncode
        data["stderr"] = result.stderr.decode(errors="replace")
        (ROOT / "artifacts/distribution-check.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        assert result.returncode == 0 and data.get("ok") and data.get("frozen"), data
        assert data["version"] == VERSION and data["platform"] == "windows", data
    files = [{"path": str(p.relative_to(directory)), "size": p.stat().st_size,
              "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(directory.rglob("*")) if p.is_file()]
    manifest = {"version": VERSION, "python": platform.python_version(), "files": files,
                "bytes": sum(f["size"] for f in files)}
    (ROOT / "artifacts/bundle-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Frozen check OK: {len(files)} files, {manifest['bytes'] / 1024**2:.1f} MiB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["environment", "bundle"])
    parser.add_argument("directory", nargs="?", type=Path, default=ROOT / "dist/Physalix")
    args = parser.parse_args()
    environment() if args.action == "environment" else bundle(args.directory)
