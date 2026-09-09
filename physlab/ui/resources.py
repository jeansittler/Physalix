"""Chemins des ressources, identiques en source et dans le bundle PyInstaller."""

from pathlib import Path


def resource_path(*parts: str) -> Path:
    return Path(__file__).resolve().parent.joinpath("resources", *parts)
