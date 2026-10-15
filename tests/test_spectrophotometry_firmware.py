"""Ressources et programmation du Nano Spectro, sans accès matériel."""

import json
from pathlib import Path
import tempfile
import unittest

from physalix.firmware_flash import (
    NanoBootloader,
    build_nano_avrdude_command,
)
from physalix.firmware_resources import (
    NANO_BOARD,
    NANO_HEX_FILE,
    NANO_RESOURCE_DIRECTORY,
    UNO_RESOURCE_DIRECTORY,
    FirmwareManifest,
    FirmwareResourceError,
    load_nano_resources,
    read_spectro_source_metadata,
    sha256_file,
    validate_manifest_metadata,
)


ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "firmware/physalix_spectrophotometer_nano/firmware_metadata.h"


class SpectroFirmwareResourceTests(unittest.TestCase):
    def test_official_resource_matches_source_and_reuses_uno_uploader(self):
        resources = load_nano_resources()
        metadata = read_spectro_source_metadata(METADATA)
        self.assertEqual(resources.manifest.board, NANO_BOARD)
        self.assertEqual(resources.firmware.name, NANO_HEX_FILE)
        self.assertEqual(resources.manifest.firmware_version, "1.0.0")
        self.assertEqual(resources.manifest.protocol_version, 1)
        self.assertEqual(resources.manifest.required_capabilities, 0x1F)
        self.assertEqual(resources.manifest.hex_sha256, sha256_file(resources.firmware))
        validate_manifest_metadata(resources.manifest, metadata)
        self.assertEqual(resources.firmware.parent, NANO_RESOURCE_DIRECTORY)
        self.assertEqual(resources.uploader_executable.parent.parent, UNO_RESOURCE_DIRECTORY)
        self.assertFalse((NANO_RESOURCE_DIRECTORY / "tools").exists())

    def test_manifest_rejects_wrong_board_hex_and_corruption(self):
        source = json.loads((NANO_RESOURCE_DIRECTORY / "manifest.json").read_text())
        with self.assertRaises(FirmwareResourceError):
            FirmwareManifest.from_dict(
                {**source, "board": "uno-r3-atmega328p"},
                expected_board=NANO_BOARD,
                expected_hex_file=NANO_HEX_FILE,
            )
        with self.assertRaises(FirmwareResourceError):
            FirmwareManifest.from_dict(
                {**source, "hex_file": "wrong.hex"},
                expected_board=NANO_BOARD,
                expected_hex_file=NANO_HEX_FILE,
            )
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            (directory / "manifest.json").write_text(json.dumps(source), encoding="utf-8")
            (directory / NANO_HEX_FILE).write_bytes(b"corrupted")
            with self.assertRaises(FirmwareResourceError):
                load_nano_resources(directory)

    def test_commands_are_explicit_for_both_bootloaders(self):
        resources = load_nano_resources()
        recent = build_nano_avrdude_command(
            resources, "COM4", NanoBootloader.RECENT
        )
        old = build_nano_avrdude_command(resources, "COM4", NanoBootloader.OLD)
        for command in (recent, old):
            self.assertEqual(command.arguments[2:6], ("-p", "atmega328p", "-c", "arduino"))
            self.assertEqual(command.arguments[6:8], ("-P", "COM4"))
            self.assertIn("-D", command.arguments)
            self.assertNotIn("-V", command.arguments)
            self.assertEqual(command.arguments[-1], f"flash:w:{resources.firmware}:i")
        self.assertEqual(recent.arguments[9], "115200")
        self.assertEqual(old.arguments[9], "57600")
        with self.assertRaises(ValueError):
            build_nano_avrdude_command(resources, "COM4", "recent")


if __name__ == "__main__":
    unittest.main()
