"""Generate update.json from the final (optionally signed) installer."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physalix import __version__
from physalix.updates import Manifest, DISTRIBUTION_REPOSITORY_URL, sha256_file, version_tuple


def prepare(directory, notes):
    version_tuple(__version__)
    installer = directory / f"Physalix-Setup-{__version__}.exe"
    if not installer.is_file() or not installer.stat().st_size:
        raise ValueError(f"Installer missing or empty: {installer.name}")
    # Reject an incorrectly renamed older installer, using the existing build dependency.
    import pefile
    with pefile.PE(str(installer), fast_load=False) as pe:
        major, minor, patch = version_tuple(__version__)
        fixed = pe.VS_FIXEDFILEINFO[0]
        if (fixed.FileVersionMS, fixed.FileVersionLS) != ((major << 16) | minor, patch << 16):
            raise ValueError("Installer PE version does not match project version")
    data = dict(version=__version__,
                installer_url=f"{DISTRIBUTION_REPOSITORY_URL}/releases/download/v{__version__}/{installer.name}",
                sha256=sha256_file(installer), notes=notes, mandatory=False)
    raw = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    Manifest.parse(raw)
    target = directory / "update.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(raw, encoding="utf-8")
    temporary.replace(target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=ROOT / "artifacts")
    parser.add_argument("--notes-file", type=Path, default=ROOT / "packaging/update-notes.txt")
    args = parser.parse_args()
    print(prepare(args.artifacts.resolve(), args.notes_file.read_text(encoding="utf-8").strip()))
