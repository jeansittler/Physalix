"""Generate update.json from the final (optionally signed) installer."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physalix import __version__
from physalix.updates import (
    Manifest, DISTRIBUTION_REPOSITORY_URL, UpdateError, sha256_file, version_tuple,
)

HISTORY_FILE = ROOT / "packaging/update-history.json"


def current_notes(text):
    lines = text.splitlines()
    if not lines or not lines[0].startswith("Physalix "):
        raise ValueError("Update notes must start with 'Physalix <version>'")
    notes_version = lines[0].removeprefix("Physalix ").strip()
    try:
        version_tuple(notes_version)
    except UpdateError as error:
        raise ValueError("Invalid update notes version") from error
    if notes_version != __version__:
        raise ValueError("Update notes version does not match project version")
    notes = [line[2:].strip() for line in lines if line.startswith("- ") and line[2:].strip()]
    if not notes:
        raise ValueError("Update notes contain no usable entry")
    return {"version": notes_version, "notes": notes}


def release_changelog(history, current):
    if not isinstance(history, list):
        raise ValueError("Update history must be a list")
    current_version = version_tuple(current["version"])
    result = []
    previous = None
    seen = set()
    for entry in history:
        if not isinstance(entry, dict):
            raise ValueError("Invalid update history entry")
        try:
            entry_version = version_tuple(entry["version"])
            notes = entry["notes"]
        except (KeyError, TypeError, UpdateError):
            raise ValueError("Invalid update history entry") from None
        if (not isinstance(notes, list) or not notes
                or not all(isinstance(note, str) and note.strip() for note in notes)):
            raise ValueError("Invalid update history notes")
        if entry_version in seen:
            raise ValueError("Duplicate update history version")
        if previous is not None and entry_version <= previous:
            raise ValueError("Update history versions must be strictly increasing")
        if entry_version >= current_version:
            raise ValueError("Update history version must precede current version")
        seen.add(entry_version)
        previous = entry_version
        result.append({"version": entry["version"], "notes": [note.strip() for note in notes]})
    result.append(current)
    return result


def cumulative_notes(changelog):
    return "\n\n".join(
        f"Version {entry['version']}\n\n"
        + "\n".join(f"• {note}" for note in entry["notes"])
        for entry in changelog
    )


def prepare(directory, notes, history=None):
    version_tuple(__version__)
    current = current_notes(notes)
    if history is None:
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Invalid update history file") from error
    changelog = release_changelog(history, current)
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
                sha256=sha256_file(installer),
                notes=cumulative_notes(changelog),
                changelog=changelog,
                mandatory=False)
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
    print(prepare(args.artifacts.resolve(), args.notes_file.read_text(encoding="utf-8")))
