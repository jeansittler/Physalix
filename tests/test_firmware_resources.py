"""Tests ciblés des artefacts firmware Uno, sans Arduino CLI."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from physalix.acquisition import PROTOCOL_VERSION, REQUIRED_FIRMWARE_CAPABILITIES
from physalix.firmware_resources import (
    AVRDUDE_CONFIG,
    AVRDUDE_EXECUTABLE,
    AVRDUDE_NAME,
    AVRDUDE_VERSION,
    FIRMWARE_MANIFEST_SCHEMA,
    UNO_BOARD,
    UNO_HEX_FILE,
    FirmwareManifest,
    FirmwareResourceError,
    create_manifest,
    load_uno_resources,
    manifest_bytes,
    read_source_metadata,
    validate_manifest_metadata,
)


ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = ROOT / "firmware" / "physalix_acquisition_uno" / "firmware_metadata.h"
SKETCH_PATH = ROOT / "firmware" / "physalix_acquisition_uno" / "physalix_acquisition_uno.ino"


class FirmwareResourceTests(unittest.TestCase):
    def setUp(self):
        self.metadata = read_source_metadata(METADATA_PATH)
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.hex_path = self.directory / UNO_HEX_FILE
        self.hex_path.write_bytes(b":0400000001020304F2\n:00000001FF\n")
        self.executable = self.directory / AVRDUDE_EXECUTABLE
        self.config = self.directory / AVRDUDE_CONFIG
        self.executable.parent.mkdir()
        self.executable.write_bytes(b"fake avrdude executable")
        self.config.write_bytes(b"fake avrdude configuration")

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(self, manifest):
        path = self.directory / "manifest.json"
        path.write_bytes(manifest_bytes(manifest))
        return path

    def test_canonical_source_matches_pc_protocol_and_capabilities(self):
        self.assertEqual(self.metadata.firmware_version, "1.0.0")
        self.assertEqual(self.metadata.protocol_version, PROTOCOL_VERSION)
        self.assertEqual(self.metadata.required_capabilities,
                         REQUIRED_FIRMWARE_CAPABILITIES)
        sketch = SKETCH_PATH.read_text(encoding="utf-8")
        self.assertIn('#include "firmware_metadata.h"', sketch)
        self.assertIn("FIRMWARE_MAJOR = PHYSALIX_FIRMWARE_VERSION_MAJOR", sketch)
        self.assertIn("PROTOCOL_VERSION = PHYSALIX_PROTOCOL_VERSION", sketch)
        self.assertIn("CAPABILITIES = PHYSALIX_REQUIRED_CAPABILITIES", sketch)

    def test_manifest_round_trip_schema_target_version_and_hash(self):
        manifest = create_manifest(self.hex_path, self.metadata, self.directory)
        loaded = FirmwareManifest.load(self.write_manifest(manifest))

        self.assertEqual(loaded.schema, FIRMWARE_MANIFEST_SCHEMA)
        self.assertEqual(loaded.board, UNO_BOARD)
        self.assertEqual(loaded.firmware_version, "1.0.0")
        self.assertEqual(loaded.protocol_version, PROTOCOL_VERSION)
        self.assertEqual(loaded.required_capabilities,
                         REQUIRED_FIRMWARE_CAPABILITIES)
        self.assertEqual(loaded.hex_file, UNO_HEX_FILE)
        self.assertEqual(loaded.verify_hex(self.directory), self.hex_path)
        self.assertEqual(loaded.uploader.name, AVRDUDE_NAME)
        self.assertEqual(loaded.uploader.version, AVRDUDE_VERSION)
        self.assertEqual(loaded.verify_uploader(self.directory),
                         (self.executable, self.config))

    def test_corrupted_or_missing_hex_is_rejected(self):
        manifest = create_manifest(self.hex_path, self.metadata, self.directory)
        self.hex_path.write_bytes(self.hex_path.read_bytes() + b"corruption")
        with self.assertRaisesRegex(FirmwareResourceError, "SHA-256"):
            manifest.verify_hex(self.directory)
        self.hex_path.unlink()
        with self.assertRaisesRegex(FirmwareResourceError, "introuvable"):
            manifest.verify_hex(self.directory)

    def test_version_protocol_and_capability_divergences_are_rejected(self):
        manifest = create_manifest(self.hex_path, self.metadata, self.directory)
        for changed, wording in (
            (replace(manifest, firmware_version="1.0.1"), "version"),
            (replace(manifest, protocol_version=PROTOCOL_VERSION + 1), "protocole"),
            (replace(manifest, required_capabilities=0), "capacités"),
        ):
            with self.subTest(field=wording):
                with self.assertRaisesRegex(FirmwareResourceError, wording):
                    validate_manifest_metadata(changed, self.metadata)

    def test_manifest_is_deterministic_for_unchanged_hex(self):
        first = manifest_bytes(create_manifest(self.hex_path, self.metadata, self.directory))
        second = manifest_bytes(create_manifest(self.hex_path, self.metadata, self.directory))
        self.assertEqual(first, second)
        self.assertNotIn(b"timestamp", first)

    def test_invalid_schema_board_and_hex_name_are_rejected(self):
        data = json.loads(manifest_bytes(
            create_manifest(self.hex_path, self.metadata, self.directory)))
        for key, value in (("schema", FIRMWARE_MANIFEST_SCHEMA + 1), ("board", "nano"),
                           ("hex_file", "../firmware.hex")):
            with self.subTest(key=key):
                changed = dict(data)
                changed[key] = value
                with self.assertRaises(FirmwareResourceError):
                    FirmwareManifest.from_dict(changed)

    def test_corrupted_or_missing_uploader_resource_is_rejected(self):
        manifest = create_manifest(self.hex_path, self.metadata, self.directory)
        self.executable.write_bytes(b"corrupted")
        with self.assertRaisesRegex(FirmwareResourceError, "SHA-256"):
            manifest.verify_uploader(self.directory)
        self.executable.unlink()
        with self.assertRaisesRegex(FirmwareResourceError, "introuvable"):
            manifest.verify_uploader(self.directory)

    def test_manifest_rejects_invalid_uploader_and_unsafe_paths(self):
        data = json.loads(manifest_bytes(
            create_manifest(self.hex_path, self.metadata, self.directory)))
        for mutate in (
            lambda uploader: uploader.update(version="8.2"),
            lambda uploader: uploader.update(executable="../avrdude.exe"),
            lambda uploader: uploader["files"][0].update(sha256="bad"),
        ):
            with self.subTest(mutate=mutate):
                changed = json.loads(json.dumps(data))
                mutate(changed["uploader"])
                with self.assertRaises(FirmwareResourceError):
                    FirmwareManifest.from_dict(changed)

    def test_resources_load_from_development_directory_with_spaces(self):
        spaced = self.directory / "resources with spaces" / "uno"
        (spaced / "tools").mkdir(parents=True)
        target_hex = spaced / UNO_HEX_FILE
        target_hex.write_bytes(self.hex_path.read_bytes())
        target_executable = spaced / AVRDUDE_EXECUTABLE
        target_config = spaced / AVRDUDE_CONFIG
        target_executable.write_bytes(self.executable.read_bytes())
        target_config.write_bytes(self.config.read_bytes())
        manifest = create_manifest(target_hex, self.metadata, spaced)
        (spaced / "manifest.json").write_bytes(manifest_bytes(manifest))

        resources = load_uno_resources(spaced)

        self.assertEqual(resources.firmware, target_hex)
        self.assertEqual(resources.uploader_executable, target_executable)
        self.assertEqual(resources.uploader_config, target_config)


if __name__ == "__main__":
    unittest.main()
