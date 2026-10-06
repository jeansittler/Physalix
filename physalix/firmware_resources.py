"""Read and validate firmware artifacts bundled with Physalix."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


FIRMWARE_MANIFEST_SCHEMA = 2
UNO_BOARD = "uno-r3-atmega328p"
UNO_HEX_FILE = "physalix_acquisition_uno.hex"
AVRDUDE_NAME = "avrdude"
AVRDUDE_VERSION = "8.1"
AVRDUDE_EXECUTABLE = "tools/avrdude.exe"
AVRDUDE_CONFIG = "tools/avrdude.conf"
UNO_RESOURCE_DIRECTORY = Path(__file__).resolve().parent / "resources" / "firmware" / "uno"

_MANIFEST_FIELDS = {
    "schema", "board", "firmware_version", "protocol_version",
    "required_capabilities", "hex_file", "hex_sha256", "uploader",
}
_UPLOADER_FIELDS = {"name", "version", "executable", "config", "files"}
_UPLOADER_FILE_FIELDS = {"path", "sha256"}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_VERSION_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
_DEFINE_RE = re.compile(r"^\s*#define\s+(PHYSALIX_[A-Z0-9_]+)\s+([^\s/]+)", re.MULTILINE)


class FirmwareResourceError(ValueError):
    """A firmware manifest, metadata header or HEX artifact is invalid."""


@dataclass(frozen=True)
class FirmwareSourceMetadata:
    firmware_version: str
    protocol_version: int
    required_capabilities: int


def _resource_name(value: object, expected: str) -> str:
    if not isinstance(value, str) or value != expected:
        raise FirmwareResourceError("Chemin de ressource uploader invalide.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise FirmwareResourceError("Chemin de ressource uploader invalide.")
    return value


@dataclass(frozen=True)
class UploaderFile:
    path: str
    sha256: str

    @classmethod
    def from_dict(cls, data: object, expected_path: str) -> "UploaderFile":
        if not isinstance(data, dict) or set(data) != _UPLOADER_FILE_FIELDS:
            raise FirmwareResourceError("Fichier uploader invalide dans le manifeste.")
        path = _resource_name(data["path"], expected_path)
        digest = data["sha256"]
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise FirmwareResourceError("SHA-256 uploader invalide dans le manifeste.")
        return cls(path, digest)


@dataclass(frozen=True)
class UploaderManifest:
    name: str
    version: str
    executable: str
    config: str
    files: tuple[UploaderFile, ...]

    @classmethod
    def from_dict(cls, data: object) -> "UploaderManifest":
        if not isinstance(data, dict) or set(data) != _UPLOADER_FIELDS:
            raise FirmwareResourceError("Description uploader invalide dans le manifeste.")
        if data["name"] != AVRDUDE_NAME or data["version"] != AVRDUDE_VERSION:
            raise FirmwareResourceError("Uploader ou version uploader non pris en charge.")
        executable = _resource_name(data["executable"], AVRDUDE_EXECUTABLE)
        config = _resource_name(data["config"], AVRDUDE_CONFIG)
        entries = data["files"]
        expected = (AVRDUDE_EXECUTABLE, AVRDUDE_CONFIG)
        if not isinstance(entries, list) or len(entries) != len(expected):
            raise FirmwareResourceError("Liste des ressources uploader invalide.")
        files = tuple(UploaderFile.from_dict(item, path)
                      for item, path in zip(entries, expected))
        return cls(data["name"], data["version"], executable, config, files)

    def verify(self, directory: Path) -> tuple[Path, Path]:
        verified = {}
        for item in self.files:
            path = directory.joinpath(*PurePosixPath(item.path).parts)
            try:
                size = path.stat().st_size
            except OSError as error:
                raise FirmwareResourceError(f"Ressource uploader introuvable : {path}") from error
            if size == 0:
                raise FirmwareResourceError(f"Ressource uploader vide : {path}")
            if sha256_file(path) != item.sha256:
                raise FirmwareResourceError(
                    f"Le SHA-256 de la ressource uploader {item.path} ne correspond pas au manifeste.")
            verified[item.path] = path
        return verified[self.executable], verified[self.config]


@dataclass(frozen=True)
class FirmwareManifest:
    schema: int
    board: str
    firmware_version: str
    protocol_version: int
    required_capabilities: int
    hex_file: str
    hex_sha256: str
    uploader: UploaderManifest

    @classmethod
    def from_dict(cls, data: object) -> "FirmwareManifest":
        if not isinstance(data, dict) or set(data) != _MANIFEST_FIELDS:
            raise FirmwareResourceError("Champs du manifeste firmware invalides.")
        if type(data["schema"]) is not int or data["schema"] != FIRMWARE_MANIFEST_SCHEMA:
            raise FirmwareResourceError("Schéma du manifeste firmware non pris en charge.")
        if data["board"] != UNO_BOARD:
            raise FirmwareResourceError("Le manifeste ne cible pas l'Arduino Uno R3.")
        if not isinstance(data["firmware_version"], str) or not _VERSION_RE.fullmatch(data["firmware_version"]):
            raise FirmwareResourceError("Version firmware invalide dans le manifeste.")
        if type(data["protocol_version"]) is not int or not 0 <= data["protocol_version"] <= 255:
            raise FirmwareResourceError("Version de protocole invalide dans le manifeste.")
        capabilities = data["required_capabilities"]
        if type(capabilities) is not int or not 0 <= capabilities <= 0xFFFFFFFF:
            raise FirmwareResourceError("Capacités firmware invalides dans le manifeste.")
        hex_file = data["hex_file"]
        if not isinstance(hex_file, str) or PurePosixPath(hex_file).name != hex_file or hex_file != UNO_HEX_FILE:
            raise FirmwareResourceError("Nom du fichier HEX invalide dans le manifeste.")
        digest = data["hex_sha256"]
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise FirmwareResourceError("SHA-256 invalide dans le manifeste.")
        values = dict(data)
        values["uploader"] = UploaderManifest.from_dict(data["uploader"])
        return cls(**values)

    @classmethod
    def load(cls, path: Path) -> "FirmwareManifest":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise FirmwareResourceError(f"Impossible de lire le manifeste firmware : {error}") from error
        return cls.from_dict(data)

    def verify_hex(self, directory: Path) -> Path:
        path = directory / self.hex_file
        try:
            size = path.stat().st_size
        except OSError as error:
            raise FirmwareResourceError(f"Fichier HEX firmware introuvable : {path}") from error
        if size == 0:
            raise FirmwareResourceError("Le fichier HEX firmware est vide.")
        if sha256_file(path) != self.hex_sha256:
            raise FirmwareResourceError("Le SHA-256 du firmware ne correspond pas au manifeste.")
        return path

    def verify_uploader(self, directory: Path) -> tuple[Path, Path]:
        return self.uploader.verify(directory)


@dataclass(frozen=True)
class FirmwareResources:
    manifest: FirmwareManifest
    firmware: Path
    uploader_executable: Path
    uploader_config: Path


def load_uno_resources(directory: Path | None = None) -> FirmwareResources:
    directory = Path(directory) if directory is not None else UNO_RESOURCE_DIRECTORY
    manifest = FirmwareManifest.load(directory / "manifest.json")
    firmware = manifest.verify_hex(directory)
    executable, config = manifest.verify_uploader(directory)
    return FirmwareResources(manifest, firmware, executable, config)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_source_metadata(path: Path) -> FirmwareSourceMetadata:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise FirmwareResourceError(f"Impossible de lire les métadonnées firmware : {error}") from error
    defines = dict(_DEFINE_RE.findall(text))
    required = (
        "PHYSALIX_FIRMWARE_VERSION_MAJOR", "PHYSALIX_FIRMWARE_VERSION_MINOR",
        "PHYSALIX_FIRMWARE_VERSION_PATCH", "PHYSALIX_PROTOCOL_VERSION",
        "PHYSALIX_REQUIRED_CAPABILITIES",
    )
    missing = [name for name in required if name not in defines]
    if missing:
        raise FirmwareResourceError(f"Métadonnées firmware absentes : {', '.join(missing)}")

    def number(name: str) -> int:
        value = defines[name].rstrip("uUlL")
        try:
            return int(value, 0)
        except ValueError as error:
            raise FirmwareResourceError(f"Valeur non entière pour {name} : {defines[name]}") from error

    version = tuple(number(name) for name in required[:3])
    if any(not 0 <= part <= 255 for part in version):
        raise FirmwareResourceError("Composante de version firmware hors limites.")
    return FirmwareSourceMetadata(
        ".".join(map(str, version)), number("PHYSALIX_PROTOCOL_VERSION"),
        number("PHYSALIX_REQUIRED_CAPABILITIES"),
    )


def create_manifest(hex_path: Path, metadata: FirmwareSourceMetadata,
                    uploader_directory: Path) -> FirmwareManifest:
    if not hex_path.is_file() or hex_path.stat().st_size == 0:
        raise FirmwareResourceError(f"Fichier HEX absent ou vide : {hex_path}")
    uploader_files = tuple(
        UploaderFile(path, sha256_file(uploader_directory.joinpath(*PurePosixPath(path).parts)))
        for path in (AVRDUDE_EXECUTABLE, AVRDUDE_CONFIG)
    )
    uploader = UploaderManifest(
        AVRDUDE_NAME, AVRDUDE_VERSION, AVRDUDE_EXECUTABLE, AVRDUDE_CONFIG,
        uploader_files,
    )
    uploader.verify(uploader_directory)
    return FirmwareManifest(
        schema=FIRMWARE_MANIFEST_SCHEMA,
        board=UNO_BOARD,
        firmware_version=metadata.firmware_version,
        protocol_version=metadata.protocol_version,
        required_capabilities=metadata.required_capabilities,
        hex_file=UNO_HEX_FILE,
        hex_sha256=sha256_file(hex_path),
        uploader=uploader,
    )


def manifest_bytes(manifest: FirmwareManifest) -> bytes:
    return (json.dumps(asdict(manifest), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n").encode("utf-8")


def validate_manifest_metadata(manifest: FirmwareManifest,
                               metadata: FirmwareSourceMetadata) -> None:
    if manifest.firmware_version != metadata.firmware_version:
        raise FirmwareResourceError("Divergence de version entre le firmware et le manifeste.")
    if manifest.protocol_version != metadata.protocol_version:
        raise FirmwareResourceError("Divergence de protocole entre le firmware et le manifeste.")
    if manifest.required_capabilities != metadata.required_capabilities:
        raise FirmwareResourceError("Divergence de capacités entre le firmware et le manifeste.")
