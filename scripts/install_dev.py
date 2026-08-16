"""Register this checkout as a Houdini development package without copying it."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence


PACKAGE_FILENAME = "houdini_chat_bridge_dev.json"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def package_definition(repository_root: Path) -> dict[str, object]:
    """Return the package data that exposes source code and Python Panels."""
    root = repository_root.resolve().as_posix()
    return {
        "load_package_once": True,
        "env": [
            {"HOUDINI_CHAT_BRIDGE_ROOT": root},
            {
                "PYTHONPATH": {
                    "value": "$HOUDINI_CHAT_BRIDGE_ROOT/src",
                    "method": "prepend",
                }
            },
        ],
        "hpath": "$HOUDINI_CHAT_BRIDGE_ROOT/houdini",
    }


def install_development_package(preferences_directory: Path, repository_root: Path = REPOSITORY_ROOT) -> Path:
    """Write a package file under Houdini preferences and return its path."""
    destination = preferences_directory.expanduser().resolve() / "packages" / PACKAGE_FILENAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(package_definition(repository_root), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefs-dir",
        type=Path,
        default=os.environ.get("HOUDINI_USER_PREF_DIR"),
        help="Houdini user preference directory (defaults to $HOUDINI_USER_PREF_DIR).",
    )
    arguments = parser.parse_args(argv)
    if arguments.prefs_dir is None:
        parser.error("--prefs-dir is required when HOUDINI_USER_PREF_DIR is not set.")
    package_path = install_development_package(arguments.prefs_dir)
    print("Registered Houdini Chat Bridge development package: %s" % package_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
