"""Generate an auditable inventory for the bundled third-party runtimes."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
VERSION = runpy.run_path(str(ROOT / "physalix/_version.py"))["__version__"]
MANIFEST = ROOT / "third_party/components.json"

EXPECTED_PACKAGES = {
    "av": "17.1.0",
    "PySide6": "6.11.2",
    "shiboken6": "6.11.2",
}
EXPECTED_DLL_PATTERNS = (
    "avcodec-62-*.dll", "avdevice-62-*.dll", "avfilter-11-*.dll",
    "avformat-62-*.dll", "avutil-60-*.dll", "swresample-6-*.dll",
    "swscale-9-*.dll", "libdav1d-*.dll", "libmp3lame-0-*.dll",
    "libopencore-amrnb-0-*.dll", "libopencore-amrwb-0-*.dll", "libopus-0-*.dll",
    "libSvtAv1Enc-*.dll", "libvpx-1-*.dll", "libwebp-*.dll",
    "libwebpmux-*.dll", "libsharpyuv-*.dll", "libvpl-*.dll",
    "libx264-165-*.dll", "libx265-*.dll", "zlib1-*.dll", "libiconv-2-*.dll",
    "libgcc_s_seh-1-*.dll", "libstdc++-6-*.dll", "libwinpthread-1-*.dll",
    "Qt6Core.dll", "Qt6VirtualKeyboard.dll",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(bundle: Path, target: Path) -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["release"] == VERSION, "third-party manifest version is stale"
    installed = {name: importlib.metadata.version(name) for name in EXPECTED_PACKAGES}
    assert installed == EXPECTED_PACKAGES, f"unexpected runtime packages: {installed}"
    assert bundle.is_dir(), f"bundle not found: {bundle}"
    matches = {}
    for pattern in EXPECTED_DLL_PATTERNS:
        found = list(bundle.rglob(pattern))
        assert len(found) == 1, f"expected one {pattern}, found {len(found)}"
        matches[pattern] = found[0]
    binaries = []
    for pattern, path in matches.items():
        binaries.append({
            "expected_pattern": pattern,
            "name": path.name,
            "path": path.relative_to(bundle).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    output = {
        "schema": 1,
        "physalix": VERSION,
        "declared_components": data["components"],
        "python_packages": installed,
        "audited_binaries": binaries,
        "source_distribution_required": True,
        "source_instructions": "See third_party/README.md; publish exact corresponding sources with binaries.",
    }
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Third-party inventory OK: {len(binaries)} audited DLLs -> {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", nargs="?", type=Path, default=ROOT / "dist/Physalix")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/third-party-inventory.json")
    args = parser.parse_args()
    main(args.bundle.resolve(), args.output.resolve())
