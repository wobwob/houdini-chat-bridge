"""Pure-Python validation tests for normal-node spare parameter interfaces."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from houdini_chat_bridge.validation import validate_node_parameter_interface


class NodeParameterInterfaceValidationTests(unittest.TestCase):
    def test_accepts_recursive_common_parameter_templates(self):
        templates = [{"type": "folder", "name": "controls", "label": "Controls", "children": [
            {"type": "float", "name": "width", "label": "Width", "default": 5.0, "min": 1.0, "max": 10.0, "min_strict": True},
            {"type": "int", "name": "rows", "label": "Rows", "default": 3, "min": 1, "max": 8},
            {"type": "toggle", "name": "enabled", "label": "Enabled", "default": True},
            {"type": "string", "name": "label", "label": "Label", "default": "House"},
            {"type": "folder", "name": "roof", "label": "Roof", "children": [
                {"type": "menu", "name": "style", "label": "Style", "items": [
                    {"value": "pitched", "label": "Pitched"},
                    {"value": "flat", "label": "Flat"},
                ], "default": "pitched"},
            ]},
        ]}]

        validated = validate_node_parameter_interface(templates)

        self.assertEqual(validated, templates)
        self.assertIsNot(validated[0], templates[0])

    def test_rejects_invalid_template_shapes_with_action_specific_errors(self):
        cases = [
            ([{"type": "color", "name": "tint", "label": "Tint"}], "unsupported template type"),
            ([
                {"type": "float", "name": "width", "label": "Width"},
                {"type": "int", "name": "width", "label": "Rows"},
            ], 'duplicate parameter name "width"'),
            ([{"type": "float", "name": "width", "label": "Width", "min": 10.0, "max": 2.0}], "min cannot be greater"),
            ([{"type": "int", "name": "rows", "label": "Rows", "default": 2.5}], "must be integer"),
            ([{"type": "folder", "name": "main", "label": "Main", "children": {}}], "children must be an array"),
            ([{"type": "menu", "name": "style", "label": "Style", "items": [{"value": "a", "label": "A"}], "default": "missing"}], "is not one of its items"),
            ([{"type": "menu", "name": "style", "label": "Style", "items": [{"value": "a", "label": "A"}, {"value": "a", "label": "Again"}]}], "duplicate value"),
        ]

        for templates, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                ValueError, "install_node_parameter_interface:.*%s" % message
            ):
                validate_node_parameter_interface(templates)


if __name__ == "__main__":
    unittest.main()
