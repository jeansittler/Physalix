"""Tests ciblés des artefacts firmware Uno, sans Arduino CLI."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from physalix.acquisition import PROTOCOL_VERSION, REQUIRED_FIRMWARE_CAPABILITIES
from physalix.firmware_resources import (
    FIRMWARE_MANIFEST_SCHEMA,
    UNO_BOARD,
    UNO_HEX_FILE,
    FirmwareManifest,
    FirmwareResourceError,
    create_manifest,
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
        manifest = create_manifest(self.hex_path, self.metadata)
        loaded = FirmwareManifest.load(self.write_manifest(manifest))

        self.assertEqual(loaded.schema, FIRMWARE_MANIFEST_SCHEMA)
        self.assertEqual(loaded.board, UNO_BOARD)
        self.assertEqual(loaded.firmware_version, "1.0.0")
        self.assertEqual(loaded.protocol_version, PROTOCOL_VERSION)
        self.assertEqual(loaded.required_capabilities,
                         REQUIRED_FIRMWARE_CAPABILITIES)
        self.assertEqual(loaded.hex_file, UNO_HEX_FILE)
        self.assertEqual(loaded.verify_hex(self.directory), self.hex_path)

    def test_corrupted_or_missing_hex_is_rejected(self):
        manifest = create_manifest(self.hex_path, self.metadata)
        self.hex_path.write_bytes(self.hex_path.read_bytes() + b"corruption")
        with self.assertRaisesRegex(FirmwareResourceError, "SHA-256"):
            manifest.verify_hex(self.directory)
        self.hex_path.unlink()
        with self.assertRaisesRegex(FirmwareResourceError, "introuvable"):
            manifest.verify_hex(self.directory)

    def test_version_protocol_and_capability_divergences_are_rejected(self):
        manifest = create_manifest(self.hex_path, self.metadata)
        for changed, wording in (
            (replace(manifest, firmware_version="1.0.1"), "version"),
            (replace(manifest, protocol_version=PROTOCOL_VERSION + 1), "protocole"),
            (replace(manifest, required_capabilities=0), "capacités"),
        ):
            with self.subTest(field=wording):
                with self.assertRaisesRegex(FirmwareResourceError, wording):
                    validate_manifest_metadata(changed, self.metadata)

    def test_manifest_is_deterministic_for_unchanged_hex(self):
        first = manifest_bytes(create_manifest(self.hex_path, self.metadata))
        second = manifest_bytes(create_manifest(self.hex_path, self.metadata))
        self.assertEqual(first, second)
        self.assertNotIn(b"timestamp", first)

    def test_invalid_schema_board_and_hex_name_are_rejected(self):
        data = json.loads(manifest_bytes(create_manifest(self.hex_path, self.metadata)))
        for key, value in (("schema", 2), ("board", "nano"),
                           ("hex_file", "../firmware.hex")):
            with self.subTest(key=key):
                changed = dict(data)
                changed[key] = value
                with self.assertRaises(FirmwareResourceError):
                    FirmwareManifest.from_dict(changed)


if __name__ == "__main__":
    unittest.main()
