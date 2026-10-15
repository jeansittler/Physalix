"""Generate a deterministic manifest for a compiled Physalix firmware."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from physalix.firmware_resources import (
    FirmwareResourceError, NANO_BOARD, NANO_HEX_FILE, UNO_RESOURCE_DIRECTORY,
    create_manifest, manifest_bytes, read_source_metadata,
    read_spectro_source_metadata, validate_manifest_metadata,
)


def main(metadata_path: Path, hex_path: Path, output_path: Path,
         uploader_directory: Path, target: str = "uno") -> None:
    if target == "spectro":
        from physalix.spectrophotometry_protocol import PROTOCOL_VERSION
        from physalix.spectrophotometry_serial import SPECTRO_REQUIRED_CAPABILITIES
        metadata = read_spectro_source_metadata(metadata_path)
        required_capabilities = SPECTRO_REQUIRED_CAPABILITIES
        manifest_options = {"board": NANO_BOARD, "hex_file": NANO_HEX_FILE}
    else:
        from physalix.acquisition import PROTOCOL_VERSION, REQUIRED_FIRMWARE_CAPABILITIES
        metadata = read_source_metadata(metadata_path)
        required_capabilities = REQUIRED_FIRMWARE_CAPABILITIES
        manifest_options = {}
    if metadata.protocol_version != PROTOCOL_VERSION:
        raise FirmwareResourceError(
            f"Protocole firmware {metadata.protocol_version} != protocole PC {PROTOCOL_VERSION}.")
    if (metadata.required_capabilities & required_capabilities
            != required_capabilities):
        raise FirmwareResourceError(
            "Le firmware ne fournit pas toutes les capacités requises par Physalix.")
    manifest = create_manifest(
        hex_path, metadata, uploader_directory, **manifest_options
    )
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
    parser.add_argument("--target", choices=("uno", "spectro"), default="uno")
    args = parser.parse_args()
    main(args.metadata.resolve(), args.hex.resolve(), args.output.resolve(),
         args.uploader_directory.resolve(), args.target)
