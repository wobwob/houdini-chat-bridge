"""Pure-Python checks for the external Houdini development package installer."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[1]
INSTALLER_PATH = REPOSITORY_ROOT / "scripts" / "install_dev.py"
PANEL_PATH = REPOSITORY_ROOT / "houdini" / "python_panels" / "houdini_chat_bridge.pypanel"


def load_installer():
    specification = importlib.util.spec_from_file_location("install_dev", INSTALLER_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError("Could not load development installer.")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class DevelopmentInstallTests(unittest.TestCase):
    def test_installer_writes_package_outside_the_repository(self):
        installer = load_installer()
        with tempfile.TemporaryDirectory() as temporary_directory:
            preferences = Path(temporary_directory) / "houdini20.5"
            package_path = installer.install_development_package(preferences, REPOSITORY_ROOT)
            package = json.loads(package_path.read_text(encoding="utf-8"))

        self.assertEqual(package_path.name, "houdini_chat_bridge_dev.json")
        self.assertEqual(package["hpath"], "$HOUDINI_CHAT_BRIDGE_ROOT/houdini")
        self.assertIn("PYTHONPATH", package["env"][1])
        self.assertEqual(package["env"][0]["HOUDINI_CHAT_BRIDGE_ROOT"], REPOSITORY_ROOT.as_posix())

    def test_python_panel_definition_is_well_formed_and_uses_create_hook(self):
        root = ElementTree.parse(PANEL_PATH).getroot()
        interface = root.find("interface")
        script = interface.findtext("script") if interface is not None else ""

        self.assertEqual(root.tag, "pythonPanelDocument")
        self.assertEqual(interface.get("name"), "houdini_chat_bridge")
        self.assertIn("onCreateInterface", script)
        self.assertIn("panel.create_panel", script)


if __name__ == "__main__":
    unittest.main()
