"""Houdini-free tests for validated batch execution and undo behavior."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from houdini_chat_bridge.executor import execute_operations


class FakeParameter:
    def __init__(self, value):
        self.value = value

    def set(self, value):
        if value == "fail":
            raise RuntimeError("simulated parameter failure")
        self.value = value


class FakeNode:
    def __init__(self, path, parameters=None):
        self.path_value = path
        self.parameters = parameters or {}
        self.inputs = []

    def isValid(self):
        return True

    def path(self):
        return self.path_value

    def name(self):
        return self.path_value.rsplit("/", 1)[-1]

    def parm(self, name):
        return self.parameters.get(name)

    def inputConnections(self):
        return list(self.inputs)


class FakeUndoGroup:
    def __init__(self, label, recorder):
        self.label = label
        self.recorder = recorder

    def __enter__(self):
        self.recorder.append(("enter", self.label))
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.recorder.append(("exit", self.label))
        return False


class FakeUndos:
    def __init__(self, recorder):
        self.recorder = recorder

    def group(self, label):
        self.recorder.append(("group", label))
        return FakeUndoGroup(label, self.recorder)


class FakeHou:
    def __init__(self, nodes, recorder):
        self.nodes = nodes
        self.undos = FakeUndos(recorder)
        self.exprLanguage = type("ExprLanguage", (), {"Hscript": "Hscript"})

    def node(self, path):
        return self.nodes.get(path)


def snapshot_for(node):
    parameter = node.parm("height")
    return {
        "schema_version": 1,
        "nodes": [
            {
                "path": node.path(),
                "name": node.name(),
                "type_name": "tube",
                "type_category": "Sop",
                "display_flag": False,
                "render_flag": False,
                "input_connections": [],
                "parameters": [{"name": "height", "value": parameter.value}],
            }
        ],
    }


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.parent = FakeNode("/obj/custom")
        self.pole = FakeNode("/obj/custom/POLE", {"height": FakeParameter(4.0), "width": FakeParameter(1.0)})
        self.events = []
        self.hou = FakeHou({self.parent.path(): self.parent, self.pole.path(): self.pole}, self.events)

    def execute(self, operations, **kwargs):
        with patch.dict(sys.modules, {"hou": self.hou}), patch(
            "houdini_chat_bridge.executor.snapshot_network", side_effect=lambda parent: snapshot_for(self.pole)
        ):
            return execute_operations(self.parent, operations, **kwargs)

    def test_executes_supported_batch_in_one_undo_group_and_returns_diff(self):
        result = self.execute(
            [{"action": "set_parameter", "node": "/obj/custom/POLE", "parameter": "height", "value": 5.0}],
            label="Raise pole",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["operations_completed"], [{"index": 0, "action": "set_parameter"}])
        self.assertEqual(result["diff"]["parameter_changes"][0]["before"]["value"], 4.0)
        self.assertEqual(result["diff"]["parameter_changes"][0]["after"]["value"], 5.0)
        self.assertEqual(self.events, [("group", "Raise pole"), ("enter", "Raise pole"), ("exit", "Raise pole")])

    def test_dry_run_validates_without_mutation_snapshot_or_undo_group(self):
        with patch.dict(sys.modules, {"hou": self.hou}), patch(
            "houdini_chat_bridge.executor.snapshot_network"
        ) as snapshot:
            result = execute_operations(
                self.parent,
                [{"action": "set_parameter", "node": "/obj/custom/POLE", "parameter": "height", "value": 5.0}],
                dry_run=True,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["operations_completed"], [])
        self.assertEqual(self.pole.parm("height").value, 4.0)
        self.assertEqual(self.events, [])
        snapshot.assert_not_called()

    def test_prevalidation_reports_all_invalid_operations_without_mutation(self):
        result = self.execute([
            {"action": "set_parameter", "node": "/obj/custom/POLE", "parameter": "missing", "value": 5.0},
            {"action": "delete_everything"},
        ])

        self.assertFalse(result["success"])
        self.assertEqual(result["operations_completed"], [])
        self.assertEqual(len(result["errors"]), 2)
        self.assertIn("Parameter 'missing'", result["errors"][0]["message"])
        self.assertIn("Unsupported action", result["errors"][1]["message"])
        self.assertEqual(self.pole.parm("height").value, 4.0)
        self.assertEqual(self.events, [])

    def test_runtime_failure_preserves_completed_work_and_reports_partial_diff(self):
        result = self.execute([
            {"action": "set_parameter", "node": "/obj/custom/POLE", "parameter": "height", "value": 5.0},
            {"action": "set_parameter", "node": "/obj/custom/POLE", "parameter": "width", "value": "fail"},
        ])

        self.assertFalse(result["success"])
        self.assertEqual(result["operations_completed"], [{"index": 0, "action": "set_parameter"}])
        self.assertEqual(result["errors"][0]["operation_index"], 1)
        self.assertIn("Could not set parameter 'width'", result["errors"][0]["message"])
        self.assertEqual(self.pole.parm("height").value, 5.0)
        self.assertEqual(len(result["diff"]["parameter_changes"]), 1)
        self.assertEqual(self.events[0], ("group", "Houdini Chat Bridge batch"))

    def test_rejects_unexpected_operation_fields(self):
        result = self.execute([
            {
                "action": "set_parameter",
                "node": "/obj/custom/POLE",
                "parameter": "height",
                "value": 5.0,
                "arbitrary_code": "not allowed",
            }
        ])

        self.assertFalse(result["success"])
        self.assertIn("unsupported field", result["errors"][0]["message"])
        self.assertEqual(self.events, [])

    def test_dry_run_detects_an_occupied_input_that_would_be_replaced(self):
        old_source = FakeNode("/obj/custom/old_source")
        source = FakeNode("/obj/custom/source")
        target = FakeNode("/obj/custom/target")
        target.inputs = [type("Connection", (), {
            "inputIndex": lambda self: 0,
            "outputIndex": lambda self: 0,
            "outputNode": lambda self: old_source,
        })()]
        self.hou.nodes[source.path()] = source
        self.hou.nodes[old_source.path()] = old_source
        self.hou.nodes[target.path()] = target

        result = self.execute([
            {"action": "connect_nodes", "source": source.path(), "target": target.path(), "input_index": 0}
        ], dry_run=True)

        self.assertFalse(result["success"])
        self.assertIn("already connected", result["errors"][0]["message"])
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
