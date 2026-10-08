"""Generate the deterministic manifest for a compiled Physalix Uno firmware."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from physalix.acquisition import PROTOCOL_VERSION, REQUIRED_FIRMWARE_CAPABILITIES
from physalix.firmware_resources import (
    FirmwareResourceError, UNO_RESOURCE_DIRECTORY, create_manifest, manifest_bytes,
    read_source_metadata, validate_manifest_metadata,
)


def main(metadata_path: Path, hex_path: Path, output_path: Path,
         uploader_directory: Path) -> None:
    metadata = read_source_metadata(metadata_path)
    if metadata.protocol_version != PROTOCOL_VERSION:
        raise FirmwareResourceError(
            f"Protocole firmware {metadata.protocol_version} != protocole PC {PROTOCOL_VERSION}.")
    if (metadata.required_capabilities & REQUIRED_FIRMWARE_CAPABILITIES
            != REQUIRED_FIRMWARE_CAPABILITIES):
        raise FirmwareResourceError(
            "Le firmware ne fournit pas toutes les capacités requises par Physalix.")
    manifest = create_manifest(hex_path, metadata, uploader_directory)
    validate_manifest_metadata(manifest, metadata)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(manifest_bytes(manifest))
    manifest.verify_hex(output_path.parent)
    manifest.verify_uploader(uploader_directory)
    print(f"Firmware {manifest.firmware_version}: {manifest.hex_sha256}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--hex", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--uploader-directory", type=Path, default=UNO_RESOURCE_DIRECTORY)
    args = parser.parse_args()
    main(args.metadata.resolve(), args.hex.resolve(), args.output.resolve(),
         args.uploader_directory.resolve())
