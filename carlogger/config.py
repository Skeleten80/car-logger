"""Shared config resolution for the car-logger tools.

Prefers config.local.toml next to the chosen config file so local edits
(hardware channel, DBC path) survive project updates.
"""
from __future__ import annotations

import tomllib
from pathlib import Path


def resolve_config_path(cli_path: str | Path) -> Path:
    p = Path(cli_path)
    if not p.exists():
        # fall back to the shipped default next to the package
        p = Path(__file__).resolve().parent.parent / "config.toml"
    local = p.parent / "config.local.toml"
    return local if local.exists() else p


def load_config(cli_path: str | Path) -> tuple[dict, Path]:
    path = resolve_config_path(cli_path)
    with open(path, "rb") as f:
        return tomllib.load(f), path
