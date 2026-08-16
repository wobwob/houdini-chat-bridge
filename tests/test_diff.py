"""Hand-written, Houdini-free fixtures for snapshot diff behavior."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from houdini_chat_bridge.diff import compare_snapshots, format_diff


def node(path, name, **changes):
    result = {
        "path": path,
        "name": name,
        "type_name": "null",
        "type_category": "Sop",
        "display_flag": False,
        "render_flag": False,
        "input_connections": [],
        "parameters": [],
    }
    result.update(changes)
    return result


def fixtures():
    before = {
        "schema_version": 1,
        "nodes": [
            node("/obj/build/body", "BODY"),
            node(
                "/obj/build/pole",
                "POLE",
                type_name="tube",
                parameters=[
                    {"name": "height", "value": 4.0},
                    {"name": "profile", "expression": "ch('../profile/scale')", "expression_language": "Hscript"},
                ],
            ),
            node(
                "/obj/build/profile",
                "PROFILE",
                input_connections=[{"input_index": 0, "upstream_node_path": "/obj/build/body", "upstream_output_index": 0}],
            ),
            node("/obj/build/obsolete", "OBSOLETE"),
        ],
    }
    after = {
        "schema_version": 1,
        "nodes": [
            node("/obj/build/body", "BODY"),
            node(
                "/obj/build/pole",
                "POLE",
                type_name="tube",
                display_flag=True,
                parameters=[
                    {"name": "height", "value": 5.0},
                    {"name": "profile", "expression": "ch('../profile/width')", "expression_language": "Hscript"},
                ],
            ),
            node(
                "/obj/build/profile",
                "PROFILE",
                render_flag=True,
                input_connections=[{"input_index": 0, "upstream_node_path": "/obj/build/taper", "upstream_output_index": 0}],
            ),
            node("/obj/build/taper", "ROOF_TAPER", type_name="polyextrude"),
        ],
    }
    return before, after


class SnapshotDiffTests(unittest.TestCase):
    def test_detects_created_and_deleted_nodes(self):
        before, after = fixtures()

        result = compare_snapshots(before, after)

        self.assertEqual(result["created_nodes"], [{"path": "/obj/build/taper", "name": "ROOF_TAPER", "type_name": "polyextrude", "type_category": "Sop"}])
        self.assertEqual(result["deleted_nodes"], [{"path": "/obj/build/obsolete", "name": "OBSOLETE", "type_name": "null", "type_category": "Sop"}])

    def test_detects_value_and_expression_parameter_changes(self):
        before, after = fixtures()

        result = compare_snapshots(before, after)

        changes = result["parameter_changes"]
        self.assertEqual([change["parameter"] for change in changes], ["height", "profile"])
        self.assertEqual(changes[0]["before"], {"name": "height", "value": 4.0})
        self.assertEqual(changes[0]["after"], {"name": "height", "value": 5.0})
        self.assertEqual(changes[1]["before"]["expression"], "ch('../profile/scale')")
        self.assertEqual(changes[1]["after"]["expression"], "ch('../profile/width')")

    def test_detects_input_connection_and_flag_changes(self):
        before, after = fixtures()

        result = compare_snapshots(before, after)

        self.assertEqual(result["connection_changes"][0]["node"], "/obj/build/profile")
        self.assertEqual(result["connection_changes"][0]["node_name"], "PROFILE")
        self.assertEqual(result["connection_changes"][0]["before_node_name"], "BODY")
        self.assertEqual(result["connection_changes"][0]["after_node_name"], "ROOF_TAPER")
        self.assertEqual(result["connection_changes"][0]["before"], {
            "input_index": 0, "upstream_node_path": "/obj/build/body", "upstream_output_index": 0,
        })
        self.assertEqual(
            [(item["node_name"], item["flag"], item["before"], item["after"]) for item in result["flag_changes"]],
            [("POLE", "display_flag", False, True), ("PROFILE", "render_flag", False, True)],
        )

    def test_modified_nodes_groups_each_kind_of_change(self):
        before, after = fixtures()

        result = compare_snapshots(before, after)
        modified = {entry["node"]: entry for entry in result["modified_nodes"]}

        self.assertEqual(set(modified), {"/obj/build/pole", "/obj/build/profile"})
        self.assertEqual(len(modified["/obj/build/pole"]["parameter_changes"]), 2)
        self.assertEqual(len(modified["/obj/build/pole"]["flag_changes"]), 1)
        self.assertEqual(len(modified["/obj/build/profile"]["connection_changes"]), 1)

    def test_identical_snapshots_are_empty_and_unknown_flags_are_ignored(self):
        before, after = fixtures()
        after = copy.deepcopy(before)
        before["nodes"][0]["display_flag"] = None
        after["nodes"][0]["display_flag"] = False

        result = compare_snapshots(before, after)

        self.assertEqual(result["created_nodes"], [])
        self.assertEqual(result["deleted_nodes"], [])
        self.assertEqual(result["modified_nodes"], [])
        self.assertEqual(result["connection_changes"], [])
        self.assertEqual(result["flag_changes"], [])

    def test_rejects_duplicate_node_paths(self):
        before, after = fixtures()
        before["nodes"].append(copy.deepcopy(before["nodes"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate node path"):
            compare_snapshots(before, after)

    def test_formats_readable_diff(self):
        before, after = fixtures()

        result = format_diff(compare_snapshots(before, after))

        self.assertIn("Created:\n- ROOF_TAPER", result)
        self.assertIn("- POLE\n  height: 4.0 -> 5.0", result)
        self.assertIn("PROFILE input 0: BODY[0] -> ROOF_TAPER[0]", result)
        self.assertIn("Deleted:\n- OBSOLETE", result)

    def test_detects_and_formats_comment_changes(self):
        before, after = fixtures()
        before["nodes"][0]["comment"] = "Old note"
        after["nodes"][0]["comment"] = "New note"

        result = compare_snapshots(before, after)

        self.assertEqual(result["comment_changes"], [{
            "node": "/obj/build/body", "before": "Old note", "after": "New note", "node_name": "BODY",
        }])
        self.assertIn("Comments:\n- BODY: 'Old note' -> 'New note'", format_diff(result))


if __name__ == "__main__":
    unittest.main()
