"""Chargement et validation des notes de version locales."""
import json
import re

from physalix import __version__
from physalix.ui.resources import resource_path


RELEASE_NOTES_PATH = resource_path("release-notes.json")
_VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


class ReleaseNotesError(ValueError):
    """Notes locales absentes ou invalides."""


def _version_key(value):
    if not isinstance(value, str) or not _VERSION_PATTERN.fullmatch(value):
        raise ReleaseNotesError("Version de notes invalide")
    parts = tuple(map(int, value.split(".")))
    if any(part > 65535 for part in parts):
        raise ReleaseNotesError("Version de notes invalide")
    return parts


def validate_release_notes(data, *, require_current=False, current_version=None):
    """Valide et renvoie les versions de la plus récente à la plus ancienne."""
    if not isinstance(data, list) or not data:
        raise ReleaseNotesError("Les notes de version doivent former une liste non vide")
    entries = []
    seen = set()
    for entry in data:
        if not isinstance(entry, dict):
            raise ReleaseNotesError("Entrée de notes invalide")
        version = entry.get("version")
        key = _version_key(version)
        notes = entry.get("notes")
        if (key in seen or not isinstance(notes, list) or not notes
                or not all(isinstance(note, str) and note.strip() for note in notes)):
            raise ReleaseNotesError("Entrée de notes invalide")
        seen.add(key)
        entries.append({"version": version, "notes": [note.strip() for note in notes]})
    entries.sort(key=lambda entry: _version_key(entry["version"]), reverse=True)
    if require_current:
        expected = __version__ if current_version is None else current_version
        if entries[0]["version"] != expected:
            raise ReleaseNotesError("La dernière version documentée ne correspond pas à la version préparée")
    return entries


def load_release_notes(path=None, *, require_current=False, current_version=None):
    """Charge la ressource embarquée, ou un chemin explicite pour les outils/tests."""
    source = RELEASE_NOTES_PATH if path is None else path
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseNotesError("Impossible de lire les notes de version locales") from error
    return validate_release_notes(
        data, require_current=require_current, current_version=current_version
    )


def current_release(entries, current_version=None):
    """Renvoie l'entrée correspondant à la version installée, si elle existe."""
    expected = __version__ if current_version is None else current_version
    return next((entry for entry in entries if entry["version"] == expected), None)
