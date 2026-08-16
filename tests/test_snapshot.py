"""Houdini-free tests for stable snapshot normalization."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from houdini_chat_bridge.snapshot import snapshot_network


class SnapshotTests(unittest.TestCase):
    def test_snapshot_sorts_nodes_and_excludes_volatile_inspection_data(self):
        first, second = object(), object()
        records = {
            id(first): {
                "valid": True,
                "path": "/obj/build/z_last",
                "name": "z_last",
                "type_name": "transform",
                "type_category": "Sop",
                "position": [99.0, 22.0],
                "comment": "Not part of a stable snapshot",
                "display_flag": False,
                "render_flag": False,
                "output_connections": [{"output_index": 0}],
                "input_connections": [{"input_index": 0, "upstream_node_path": "/obj/build/source", "upstream_output_index": 0}],
                "parameters": [
                    {"name": "scale", "value": 2.0},
                    {"name": "animated", "expression": "$F", "expression_language": "Hscript", "value": 17.0},
                ],
            },
            id(second): {
                "valid": True,
                "path": "/obj/build/a_first",
                "name": "a_first",
                "type_name": "box",
                "type_category": "Sop",
                "display_flag": True,
                "render_flag": False,
                "input_connections": [],
                "parameters": [],
            },
        }

        with patch("houdini_chat_bridge.snapshot.inspect_node", side_effect=lambda node: records[id(node)]):
            result = snapshot_network([first, second])

        self.assertEqual([node["path"] for node in result["nodes"]], ["/obj/build/a_first", "/obj/build/z_last"])
        last = result["nodes"][1]
        self.assertNotIn("position", last)
        self.assertNotIn("comment", last)
        self.assertNotIn("output_connections", last)
        self.assertEqual(last["parameters"][0], {"name": "animated", "expression": "$F", "expression_language": "Hscript"})
        json.dumps(result, sort_keys=True)


if __name__ == "__main__":
    unittest.main()
