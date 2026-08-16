"""Pure-Python tests for inspection-data formatting."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from houdini_chat_bridge.formatting import format_context_for_chatgpt


class FormattingTests(unittest.TestCase):
    def test_formats_structured_context_without_houdini(self):
        context = {
            "current_network": {"path": "/obj/build", "type_name": "geo", "type_category": "Object"},
            "selected_nodes": [
                {
                    "valid": True,
                    "path": "/obj/build/box",
                    "type_name": "box",
                    "type_category": "Sop",
                    "position": [0.0, 1.0],
                    "display_flag": True,
                    "parameters": [{"name": "size", "value": [1.0, 2.0, 3.0]}],
                }
            ],
        }

        result = format_context_for_chatgpt(context)

        self.assertIn("Current network: /obj/build [Object/geo]", result)
        self.assertIn("/obj/build/box [Sop/box]", result)
        self.assertIn("size = [1.0, 2.0, 3.0]", result)

    def test_rejects_unstructured_context(self):
        with self.assertRaises(ValueError):
            format_context_for_chatgpt([])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
