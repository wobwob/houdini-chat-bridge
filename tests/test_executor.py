"""Houdini-free tests for batch planning, symbolic references, and undo."""

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
        self.expression = None

    def set(self, value):
        if value == "fail":
            raise RuntimeError("simulated parameter failure")
        self.value = value

    def setExpression(self, expression, language=None):
        self.expression = expression


class FakeConnection:
    def __init__(self, source, output_index, input_index):
        self.source = source
        self.output_index = output_index
        self.input_index = input_index

    def outputNode(self):
        return self.source

    def outputIndex(self):
        return self.output_index

    def inputIndex(self):
        return self.input_index


class FakeNode:
    def __init__(self, path, parent=None, parameters=None, node_type_name="null"):
        self.path_value = path
        self.parent_value = parent
        self.parameters = parameters or {}
        self.node_type_name = node_type_name
        self.inputs = []
        self.children = []
        self.display = False
        self.render = False
        self.position = None

    def isValid(self):
        return True

    def path(self):
        return self.path_value

    def name(self):
        return self.path_value.rsplit("/", 1)[-1]

    def parent(self):
        return self.parent_value

    def parm(self, name):
        return self.parameters.get(name)

    def createNode(self, node_type_name, name):
        node_name = name or node_type_name
        node = FakeNode(
            "%s/%s" % (self.path_value, node_name),
            parent=self,
            parameters={"height": FakeParameter(1.0), "width": FakeParameter(1.0)},
            node_type_name=node_type_name,
        )
        self.children.append(node)
        return node

    def setPosition(self, position):
        self.position = position

    def inputConnections(self):
        return list(self.inputs)

    def inputCount(self):
        return 4

    def outputCount(self):
        return 1

    def setInput(self, input_index, source, output_index=0):
        self.inputs = [connection for connection in self.inputs if connection.inputIndex() != input_index]
        if source is not None:
            self.inputs.append(FakeConnection(source, output_index, input_index))

    def setDisplayFlag(self, enabled):
        self.display = enabled

    def setRenderFlag(self, enabled):
        self.render = enabled


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


def snapshot_for(parent):
    nodes = []
    for node in parent.children:
        parameters = [
            {"name": name, "value": parameter.value}
            for name, parameter in sorted(node.parameters.items())
        ]
        inputs = [
            {
                "input_index": connection.inputIndex(),
                "upstream_node_path": connection.outputNode().path(),
                "upstream_output_index": connection.outputIndex(),
            }
            for connection in sorted(node.inputConnections(), key=lambda item: item.inputIndex())
        ]
        nodes.append(
            {
                "path": node.path(),
                "name": node.name(),
                "type_name": node.node_type_name,
                "type_category": "Sop",
                "display_flag": node.display,
                "render_flag": node.render,
                "input_connections": inputs,
                "parameters": parameters,
            }
        )
    return {"schema_version": 1, "nodes": nodes}


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.parent = FakeNode("/obj/custom")
        self.pole = FakeNode(
            "/obj/custom/POLE",
            parent=self.parent,
            parameters={"height": FakeParameter(4.0), "width": FakeParameter(1.0)},
            node_type_name="tube",
        )
        self.parent.children.append(self.pole)
        self.events = []
        self.hou = FakeHou({self.parent.path(): self.parent, self.pole.path(): self.pole}, self.events)

    def execute(self, operations, **kwargs):
        with patch.dict(sys.modules, {"hou": self.hou}), patch(
            "houdini_chat_bridge.executor.snapshot_network", side_effect=snapshot_for
        ):
            return execute_operations(self.parent, operations, **kwargs)

    def test_executes_scoped_existing_node_batch_in_one_undo_group_and_returns_diff(self):
        result = self.execute(
            [{"action": "set_parameter", "node": "/obj/custom/POLE", "parameter": "height", "value": 5.0}],
            label="Raise pole",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["operations_completed"], [{"index": 0, "action": "set_parameter"}])
        self.assertEqual(result["diff"]["parameter_changes"][0]["before"]["value"], 4.0)
        self.assertEqual(result["diff"]["parameter_changes"][0]["after"]["value"], 5.0)
        self.assertEqual(self.events, [("group", "Raise pole"), ("enter", "Raise pole"), ("exit", "Raise pole")])

    def test_create_then_set_parameter_by_symbolic_reference(self):
        result = self.execute([
            {"action": "create_node", "id": "a", "node_type_name": "tube", "name": "A"},
            {"action": "set_parameter", "node": {"ref": "a"}, "parameter": "height", "value": 5.0},
        ])

        created = self.parent.children[-1]
        self.assertTrue(result["success"])
        self.assertEqual(created.name(), "A")
        self.assertEqual(created.parm("height").value, 5.0)
        self.assertEqual(result["diff"]["created_nodes"][0]["name"], "A")
        self.assertEqual(len(result["operations_completed"]), 2)

    def test_create_then_connect_symbolic_references(self):
        result = self.execute([
            {"action": "create_node", "id": "a", "node_type_name": "tube", "name": "A"},
            {"action": "create_node", "id": "b", "node_type_name": "null", "name": "B"},
            {"action": "connect_nodes", "source": {"ref": "a"}, "target": {"ref": "b"}},
        ])

        source, target = self.parent.children[-2:]
        self.assertTrue(result["success"])
        self.assertIs(target.inputConnections()[0].outputNode(), source)
        self.assertEqual(len(result["operations_completed"]), 3)

    def test_create_then_set_display_flag_by_symbolic_reference(self):
        result = self.execute([
            {"action": "create_node", "id": "a", "node_type_name": "tube", "name": "A"},
            {"action": "set_display_flag", "node": {"ref": "a"}, "enabled": True},
        ])

        self.assertTrue(result["success"])
        self.assertTrue(self.parent.children[-1].display)

    def test_duplicate_ids_are_rejected_before_execution(self):
        result = self.execute([
            {"action": "create_node", "id": "a", "node_type_name": "tube", "name": "A"},
            {"action": "create_node", "id": "a", "node_type_name": "null", "name": "B"},
        ])

        self.assertFalse(result["success"])
        self.assertIn("Duplicate", result["errors"][0]["message"])
        self.assertEqual(len(self.parent.children), 1)
        self.assertEqual(self.events, [])

    def test_unknown_reference_is_rejected_before_execution(self):
        result = self.execute([
            {"action": "set_parameter", "node": {"ref": "missing"}, "parameter": "height", "value": 5.0}
        ])

        self.assertFalse(result["success"])
        self.assertIn("Unknown symbolic reference", result["errors"][0]["message"])
        self.assertEqual(self.events, [])

    def test_forward_reference_is_rejected_before_execution(self):
        result = self.execute([
            {"action": "set_parameter", "node": {"ref": "a"}, "parameter": "height", "value": 5.0},
            {"action": "create_node", "id": "a", "node_type_name": "tube", "name": "A"},
        ])

        self.assertFalse(result["success"])
        self.assertIn("Forward symbolic reference", result["errors"][0]["message"])
        self.assertEqual(self.events, [])

    def test_existing_path_outside_execution_scope_is_rejected(self):
        other_parent = FakeNode("/obj/other")
        other_node = FakeNode(
            "/obj/other/OUTSIDE", parent=other_parent, parameters={"height": FakeParameter(1.0)}
        )
        self.hou.nodes[other_node.path()] = other_node

        result = self.execute([
            {"action": "set_parameter", "node": other_node.path(), "parameter": "height", "value": 5.0}
        ])

        self.assertFalse(result["success"])
        self.assertIn("outside execution scope", result["errors"][0]["message"])
        self.assertEqual(other_node.parm("height").value, 1.0)

    def test_runtime_failure_after_creation_is_one_undo_group_with_partial_diff(self):
        result = self.execute([
            {"action": "create_node", "id": "a", "node_type_name": "tube", "name": "A"},
            {"action": "set_parameter", "node": {"ref": "a"}, "parameter": "width", "value": "fail"},
        ])

        self.assertFalse(result["success"])
        self.assertEqual(result["operations_completed"], [{"index": 0, "action": "create_node"}])
        self.assertEqual(result["errors"][0]["operation_index"], 1)
        self.assertEqual(result["diff"]["created_nodes"][0]["name"], "A")
        self.assertEqual(self.events, [
            ("group", "Houdini Chat Bridge batch"),
            ("enter", "Houdini Chat Bridge batch"),
            ("exit", "Houdini Chat Bridge batch"),
        ])

    def test_dry_run_validates_references_without_mutation_or_undo_group(self):
        result = self.execute([
            {"action": "create_node", "id": "a", "node_type_name": "tube", "name": "A"},
            {"action": "set_parameter", "node": {"ref": "a"}, "parameter": "height", "value": 5.0},
        ], dry_run=True)

        self.assertTrue(result["success"])
        self.assertEqual(len(self.parent.children), 1)
        self.assertEqual(self.events, [])

    def test_prevalidation_reports_invalid_existing_parameters_and_actions(self):
        result = self.execute([
            {"action": "set_parameter", "node": "/obj/custom/POLE", "parameter": "missing", "value": 5.0},
            {"action": "delete_everything"},
        ])

        self.assertFalse(result["success"])
        self.assertEqual(len(result["errors"]), 2)
        self.assertIn("Parameter 'missing'", result["errors"][0]["message"])
        self.assertIn("Unsupported action", result["errors"][1]["message"])
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
