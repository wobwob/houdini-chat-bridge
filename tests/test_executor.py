"""Houdini-free tests for batch planning, symbolic references, and undo."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from houdini_chat_bridge.executor import execute_operations


class FakeParameter:
    def __init__(self, value, spare=False):
        self.value = value
        self.expression = None
        self.spare = spare

    def set(self, value):
        if value == "fail":
            raise RuntimeError("simulated parameter failure")
        self.value = value

    def setExpression(self, expression, language=None):
        self.expression = expression

    def isSpare(self):
        return self.spare


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
        self.comment = ""
        self.boxes = []
        self.hda_definition = FakeHDADefinition()
        self.parameter_group = FakeParmTemplateGroup()
        self.valid = True

    def isValid(self):
        return self.valid

    def path(self):
        return self.path_value

    def name(self):
        return self.path_value.rsplit("/", 1)[-1]

    def parent(self):
        return self.parent_value

    def parm(self, name):
        return self.parameters.get(name)

    def parmTemplateGroup(self):
        return self.parameter_group

    def setParmTemplateGroup(self, group, rename_conflicting_parms=False):
        self.parameter_group = group
        self.rename_conflicting_parms = rename_conflicting_parms
        for template in _fake_leaf_templates(group.templates):
            if template.name() not in self.parameters:
                self.parameters[template.name()] = FakeParameter(0, spare=True)

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

    def destroy(self):
        if self.children:
            raise RuntimeError("cannot destroy a node with children")
        if self.parent_value is not None:
            self.parent_value.children.remove(self)
        self.valid = False

    def createNetworkBox(self, name):
        box = FakeNetworkBox(self, name or "network_box")
        self.boxes.append(box)
        return box

    def networkBoxes(self):
        return list(self.boxes)

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

    def setComment(self, comment):
        self.comment = comment

    def createDigitalAsset(self, **kwargs):
        self.hda_kwargs = kwargs
        return self

    def type(self):
        return FakeNodeType(self.hda_definition, self.node_type_name)


class FakeNetworkBox:
    def __init__(self, parent, name):
        self.parent_value = parent
        self.name_value = name
        self.contents = []
        self.fit_count = 0
        self.comment = ""
        self.color = None

    def parent(self):
        return self.parent_value

    def name(self):
        return self.name_value

    def items(self):
        return list(self.contents)

    def addItem(self, item):
        self.contents.append(item)

    def removeItem(self, item):
        self.contents.remove(item)

    def destroy(self):
        self.parent_value.boxes.remove(self)

    def fitAroundContents(self):
        self.fit_count += 1

    def setComment(self, comment):
        self.comment = comment

    def setColor(self, color):
        self.color = color


class FakeOptions:
    def __init__(self):
        self.save_spare_parms = True

    def setSaveSpareParms(self, value):
        self.save_spare_parms = value


class FakeHDADefinition:
    def __init__(self):
        self.options_value = FakeOptions()
        self.parameter_group = None

    def options(self):
        return self.options_value

    def setOptions(self, options):
        self.options_value = options

    def setParmTemplateGroup(self, group):
        self.parameter_group = group


class FakeNodeType:
    def __init__(self, definition, name):
        self.definition_value = definition
        self.name_value = name

    def definition(self):
        return self.definition_value

    def name(self):
        return self.name_value


class FakeParmTemplateGroup:
    def __init__(self, templates=None):
        self.templates = list(templates or [])

    def append(self, template):
        self.templates.append(template)

    def find(self, name):
        for template in self.templates:
            if template.name() == name:
                return template
        return None

    def replace(self, name, template):
        for index, current in enumerate(self.templates):
            if current.name() == name:
                self.templates[index] = template
                return
        raise ValueError("Template %s does not exist." % name)


class FakeParmTemplate:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def name(self):
        return self.args[0]


class FakeFolderParmTemplate(FakeParmTemplate):
    def parmTemplates(self):
        return self.kwargs.get("parm_templates", ())

    def addParmTemplate(self, template):
        self.kwargs["parm_templates"] = self.parmTemplates() + (template,)


class FakeFloatParmTemplate(FakeParmTemplate):
    def __init__(self, *args, **kwargs):
        _require_tuple_default("FloatParmTemplate", kwargs)
        super().__init__(*args, **kwargs)


class FakeIntParmTemplate(FakeParmTemplate):
    def __init__(self, *args, **kwargs):
        _require_tuple_default("IntParmTemplate", kwargs)
        super().__init__(*args, **kwargs)


class FakeStringParmTemplate(FakeParmTemplate):
    def __init__(self, *args, **kwargs):
        _require_tuple_default("StringParmTemplate", kwargs)
        super().__init__(*args, **kwargs)


class FakeMenuParmTemplate(FakeParmTemplate):
    def __init__(self, *args, **kwargs):
        if not isinstance(kwargs.get("default_value"), int):
            raise TypeError("MenuParmTemplate default_value must be an integer index.")
        super().__init__(*args, **kwargs)


def _require_tuple_default(template_type, kwargs):
    if not isinstance(kwargs.get("default_value"), tuple):
        raise TypeError("%s default_value must be a tuple." % template_type)


def _fake_leaf_templates(templates):
    for template in templates:
        if isinstance(template, FakeFolderParmTemplate):
            yield from _fake_leaf_templates(template.parmTemplates())
        else:
            yield template


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
        self.exprLanguage = type("ExprLanguage", (), {"Hscript": "Hscript", "Python": "Python"})
        self.ParmTemplateGroup = FakeParmTemplateGroup
        self.FolderParmTemplate = FakeFolderParmTemplate
        self.FloatParmTemplate = FakeFloatParmTemplate
        self.IntParmTemplate = FakeIntParmTemplate
        self.ToggleParmTemplate = FakeParmTemplate
        self.StringParmTemplate = FakeStringParmTemplate
        self.MenuParmTemplate = FakeMenuParmTemplate

    def node(self, path):
        return self.nodes.get(path)

    def expandString(self, path):
        return path

    def Color(self, value):
        return tuple(value)

    def Vector2(self, x, y):
        return (float(x), float(y))


def snapshot_for(parent, recursive=False):
    nodes = []
    pending = list(parent.children)
    while pending:
        node = pending.pop(0)
        if recursive:
            pending.extend(node.children)
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
                "position": list(node.position) if node.position is not None else None,
                "display_flag": node.display,
                "render_flag": node.render,
                "comment": node.comment,
                "input_connections": inputs,
                "parameters": parameters,
            }
        )
    boxes = [
        {
            "name": box.name(),
            "node_paths": sorted(item.path() for item in box.items() if hasattr(item, "path")),
        }
        for box in parent.networkBoxes()
    ]
    return {"schema_version": 2, "nodes": nodes, "network_boxes": boxes}


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

    def add_existing_node(self, name, *, parameters=None, node_type_name="null"):
        node = FakeNode(
            "%s/%s" % (self.parent.path(), name),
            parent=self.parent,
            parameters=parameters or {},
            node_type_name=node_type_name,
        )
        self.parent.children.append(node)
        self.hou.nodes[node.path()] = node
        return node

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

    def test_node_reference_path_resolves_relative_and_absolute_existing_nodes(self):
        existing = self.add_existing_node("HOUSE_CONTROLS")
        relative = self.execute([
            {"action": "set_node_comment", "node": {"path": "./HOUSE_CONTROLS"}, "comment": "Relative"},
        ])
        absolute = self.execute([
            {"action": "set_node_comment", "node": {"path": existing.path()}, "comment": "Absolute"},
        ])

        self.assertTrue(relative["success"])
        self.assertTrue(absolute["success"])
        self.assertEqual(existing.comment, "Absolute")

    def test_node_reference_path_check_is_non_mutating_and_execute_modifies_existing_node(self):
        existing = self.add_existing_node(
            "HOUSE_CONTROLS", parameters={"height": FakeParameter(4.0)}
        )
        operation = {
            "action": "set_parameter", "node": {"path": "HOUSE_CONTROLS"},
            "parameter": "height", "value": 6.0,
        }

        checked = self.execute([operation], dry_run=True)
        executed = self.execute([operation])

        self.assertTrue(checked["success"])
        self.assertTrue(executed["success"])
        self.assertEqual(existing.parm("height").value, 6.0)

    def test_node_reference_errors_distinguish_path_ref_and_malformed_objects(self):
        missing_path = self.execute([
            {"action": "set_node_comment", "node": {"path": "MISSING"}, "comment": "Nope"},
        ], dry_run=True)
        missing_ref = self.execute([
            {"action": "set_node_comment", "node": {"ref": "missing"}, "comment": "Nope"},
        ], dry_run=True)
        malformed = self.execute([
            {"action": "set_node_comment", "node": {}, "comment": "Nope"},
        ], dry_run=True)
        both = self.execute([
            {"action": "set_node_comment", "node": {"ref": "a", "path": "A"}, "comment": "Nope"},
        ], dry_run=True)

        self.assertIn("Existing node does not exist: MISSING", missing_path["errors"][0]["message"])
        self.assertIn("PATCH node reference does not exist: missing", missing_ref["errors"][0]["message"])
        self.assertIn("exactly one", malformed["errors"][0]["message"])
        self.assertIn("exactly one", both["errors"][0]["message"])
        self.assertEqual(self.events, [])

    def test_connect_nodes_supports_existing_and_same_batch_node_references(self):
        roof_input = self.add_existing_node("ROOF_IN")
        assembly = self.add_existing_node("HOUSE_ASSEMBLY")
        result = self.execute([
            {"action": "create_node", "id": "reverse", "node_type_name": "reverse", "name": "FIX_ROOF_NORMALS"},
            {"action": "connect_nodes", "source": {"path": "ROOF_IN"}, "target": {"ref": "reverse"}},
            {"action": "connect_nodes", "source": {"ref": "reverse"}, "target": {"path": "HOUSE_ASSEMBLY"}, "input_index": 2},
        ])

        reverse = self.parent.children[-1]
        self.assertTrue(result["success"])
        self.assertIs(reverse.inputConnections()[0].outputNode(), roof_input)
        self.assertIs(assembly.inputConnections()[0].outputNode(), reverse)
        self.assertEqual(assembly.inputConnections()[0].inputIndex(), 2)

    def test_node_parameter_interface_accepts_existing_path_reference(self):
        controls = self.add_existing_node("HOUSE_CONTROLS")
        result = self.execute([
            {"action": "install_node_parameter_interface", "node": {"path": "HOUSE_CONTROLS"}, "templates": [
                {"type": "folder", "name": "dimensions", "label": "Dimensions", "children": [
                    {"type": "float", "name": "house_width", "label": "House Width", "default": 5.0},
                ]},
            ]},
        ])

        self.assertTrue(result["success"])
        self.assertIsNotNone(controls.parm("house_width"))

    def test_delete_node_removes_existing_path_target_inside_undo_and_diff(self):
        unused = self.add_existing_node("UNUSED_NODE")
        result = self.execute([
            {"action": "delete_node", "node": {"path": "UNUSED_NODE"}},
        ])

        self.assertTrue(result["success"])
        self.assertFalse(unused.isValid())
        self.assertNotIn(unused, self.parent.children)
        self.assertEqual(result["diff"]["deleted_nodes"][0]["path"], unused.path())
        self.assertEqual(self.events, [
            ("group", "Houdini Chat Bridge batch"),
            ("enter", "Houdini Chat Bridge batch"),
            ("exit", "Houdini Chat Bridge batch"),
        ])

    def test_delete_node_dry_run_and_invalid_targets_do_not_mutate(self):
        unused = self.add_existing_node("UNUSED_NODE")
        checked = self.execute([
            {"action": "delete_node", "node": {"path": "UNUSED_NODE"}},
        ], dry_run=True)
        missing = self.execute([
            {"action": "delete_node", "node": {"path": "MISSING"}},
        ], dry_run=True)
        malformed = self.execute([
            {"action": "delete_node", "node": {"path": "UNUSED_NODE"}, "force": True},
        ], dry_run=True)

        self.assertTrue(checked["success"])
        self.assertTrue(unused.isValid())
        self.assertIn("Existing node does not exist: MISSING", missing["errors"][0]["message"])
        self.assertIn("unsupported field", malformed["errors"][0]["message"])
        self.assertEqual(self.events, [])

    def test_delete_node_rejects_execution_root_and_out_of_scope_nodes(self):
        other_parent = FakeNode("/obj/other")
        outside = FakeNode("/obj/other/UNUSED", parent=other_parent)
        self.hou.nodes[outside.path()] = outside
        root = self.execute([
            {"action": "delete_node", "node": {"path": self.parent.path()}},
        ], dry_run=True)
        out_of_scope = self.execute([
            {"action": "delete_node", "node": {"path": outside.path()}},
        ], dry_run=True)

        self.assertIn("Cannot delete the execution root", root["errors"][0]["message"])
        self.assertIn("outside execution scope", out_of_scope["errors"][0]["message"])
        self.assertTrue(outside.isValid())

    def test_delete_node_invalidates_same_batch_symbolic_reference(self):
        result = self.execute([
            {"action": "create_node", "id": "temp", "node_type_name": "null", "name": "TEMP"},
            {"action": "delete_node", "node": {"ref": "temp"}},
            {"action": "set_node_comment", "node": {"ref": "temp"}, "comment": "Should fail"},
        ])

        self.assertFalse(result["success"])
        self.assertEqual(result["operations_completed"], [
            {"index": 0, "action": "create_node"},
            {"index": 1, "action": "delete_node"},
        ])
        self.assertIn("unavailable as a node", result["errors"][0]["message"])
        self.assertFalse(any(node.name() == "TEMP" for node in self.parent.children))

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

    def test_set_comment_is_diffed(self):
        result = self.execute([
            {"action": "set_node_comment", "node": "/obj/custom/POLE", "comment": "Primary support"},
        ])

        self.assertTrue(result["success"])
        self.assertEqual(self.pole.comment, "Primary support")
        self.assertEqual(result["diff"]["comment_changes"], [{
            "node": "/obj/custom/POLE", "before": "", "after": "Primary support", "node_name": "POLE",
        }])

    def test_set_node_position_uses_existing_path_and_reports_before_after(self):
        self.pole.position = (1.0, 2.0)
        operation = {
            "action": "set_node_position", "node": {"path": "POLE"},
            "position": [-9.0, 14.0],
        }

        checked = self.execute([operation], dry_run=True)
        self.assertEqual(self.pole.position, (1.0, 2.0))
        executed = self.execute([operation])

        self.assertTrue(checked["success"])
        self.assertEqual(self.pole.position, (-9.0, 14.0))
        self.assertTrue(executed["success"])
        self.assertEqual(executed["diff"]["position_changes"], [{
            "node": "/obj/custom/POLE", "before": [1.0, 2.0], "after": [-9.0, 14.0],
            "node_name": "POLE",
        }])

    def test_set_node_position_rejects_invalid_reference_and_position_without_mutation(self):
        self.pole.position = (1.0, 2.0)
        missing = self.execute([
            {"action": "set_node_position", "node": {"path": "MISSING"}, "position": [1, 2]},
        ], dry_run=True)
        malformed = self.execute([
            {"action": "set_node_position", "node": {"path": "POLE"}, "position": [1]},
        ], dry_run=True)

        self.assertIn("Existing node does not exist: MISSING", missing["errors"][0]["message"])
        self.assertIn("position must", malformed["errors"][0]["message"])
        self.assertEqual(self.pole.position, (1.0, 2.0))
        self.assertEqual(self.events, [])

    def test_delete_network_box_by_name_preserves_nodes_and_reports_deleted_box(self):
        box = self.parent.createNetworkBox("FACADE")
        box.addItem(self.pole)
        operation = {"action": "delete_network_box", "box": {"name": "FACADE"}}

        checked = self.execute([operation], dry_run=True)
        self.assertTrue(checked["success"])
        self.assertIn(box, self.parent.boxes)
        executed = self.execute([operation])

        self.assertTrue(executed["success"])
        self.assertNotIn(box, self.parent.boxes)
        self.assertIn(self.pole, self.parent.children)
        self.assertEqual(executed["diff"]["deleted_network_boxes"], [{
            "name": "FACADE", "node_paths": [self.pole.path()],
        }])

    def test_remove_nodes_from_named_network_box_reports_membership_and_optional_fit(self):
        second = self.add_existing_node("WINDOWS_OUT")
        box = self.parent.createNetworkBox("FACADE")
        box.addItem(self.pole)
        box.addItem(second)
        result = self.execute([
            {
                "action": "remove_nodes_from_network_box", "box": {"name": "FACADE"},
                "nodes": [{"path": "POLE"}, {"path": "WINDOWS_OUT"}], "fit": True,
            },
        ])

        self.assertTrue(result["success"])
        self.assertEqual(box.items(), [])
        self.assertEqual(box.fit_count, 1)
        self.assertIn(self.pole, self.parent.children)
        self.assertIn(second, self.parent.children)
        self.assertEqual(result["diff"]["network_box_membership_changes"], [{
            "box": "FACADE",
            "before": [self.pole.path(), second.path()],
            "after": [],
        }])

    def test_existing_network_box_errors_are_preflighted_without_mutation(self):
        self.parent.createNetworkBox("DUPLICATE")
        self.parent.createNetworkBox("DUPLICATE")
        missing = self.execute([
            {"action": "delete_network_box", "box": {"name": "MISSING"}},
        ], dry_run=True)
        ambiguous = self.execute([
            {
                "action": "remove_nodes_from_network_box", "box": {"name": "DUPLICATE"},
                "nodes": [{"path": "POLE"}],
            },
        ], dry_run=True)

        self.assertIn("does not exist", missing["errors"][0]["message"])
        self.assertIn("ambiguous", ambiguous["errors"][0]["message"])
        self.assertEqual(self.events, [])

    def test_nested_nodes_and_network_box_references(self):
        result = self.execute([
            {"action": "create_node", "id": "subnet", "node_type_name": "subnet", "name": "ASSEMBLY"},
            {"action": "create_node", "id": "a", "node_type_name": "tube", "name": "POLE", "parent": {"ref": "subnet"}},
            {"action": "create_node", "id": "b", "node_type_name": "null", "name": "OUT", "parent": {"ref": "subnet"}},
            {"action": "set_node_comment", "node": {"ref": "a"}, "comment": "Drives the output"},
            {"action": "create_network_box", "id": "group", "name": "build", "parent": {"ref": "subnet"}},
            {"action": "add_nodes_to_network_box", "box": {"ref": "group"}, "nodes": [{"ref": "a"}, {"ref": "b"}]},
        ])

        subnet = self.parent.children[-1]
        pole, output = subnet.children
        box = subnet.boxes[0]
        self.assertTrue(result["success"])
        self.assertEqual(pole.comment, "Drives the output")
        self.assertEqual(box.contents, [pole, output])
        self.assertEqual(box.fit_count, 1)
        self.assertEqual(box.color, (0.0, 0.0, 0.0))
        self.assertIn("/obj/custom/ASSEMBLY/POLE", [item["path"] for item in result["diff"]["created_nodes"]])

    def test_network_box_membership_is_idempotent_and_wrong_parent_fails_in_group(self):
        result = self.execute([
            {"action": "create_node", "id": "subnet", "node_type_name": "subnet", "name": "ASSEMBLY"},
            {"action": "create_node", "id": "child", "node_type_name": "tube", "name": "CHILD", "parent": {"ref": "subnet"}},
            {"action": "create_network_box", "id": "root_box", "name": "root_box"},
            {"action": "add_nodes_to_network_box", "box": {"ref": "root_box"}, "nodes": [{"ref": "child"}]},
        ])

        self.assertFalse(result["success"])
        self.assertEqual(len(result["operations_completed"]), 3)
        self.assertIn("not network box parent", result["errors"][0]["message"])
        self.assertEqual(self.events.count(("group", "Houdini Chat Bridge batch")), 1)

    def test_duplicate_ids_are_shared_across_nodes_and_network_boxes(self):
        result = self.execute([
            {"action": "create_node", "id": "thing", "node_type_name": "tube", "name": "A"},
            {"action": "create_network_box", "id": "thing", "name": "B"},
        ])

        self.assertFalse(result["success"])
        self.assertIn("Duplicate batch object id", result["errors"][0]["message"])

    def test_unknown_network_box_and_forward_node_parent_are_rejected(self):
        unknown_box = self.execute([
            {"action": "add_nodes_to_network_box", "box": {"ref": "missing"}, "nodes": ["/obj/custom/POLE"]},
        ])
        forward_parent = self.execute([
            {"action": "create_node", "id": "child", "node_type_name": "tube", "parent": {"ref": "subnet"}},
            {"action": "create_node", "id": "subnet", "node_type_name": "subnet"},
        ])

        self.assertIn("Unknown symbolic reference", unknown_box["errors"][0]["message"])
        self.assertIn("Forward symbolic reference", forward_parent["errors"][0]["message"])

    def test_multiple_network_boxes_and_unknown_member_reference(self):
        result = self.execute([
            {"action": "create_node", "id": "a", "node_type_name": "tube", "name": "A"},
            {"action": "create_node", "id": "b", "node_type_name": "null", "name": "B"},
            {"action": "create_network_box", "id": "first", "name": "first"},
            {"action": "create_network_box", "id": "second", "name": "second"},
            {"action": "add_nodes_to_network_box", "box": {"ref": "first"}, "nodes": [{"ref": "a"}]},
            {"action": "add_nodes_to_network_box", "box": {"ref": "second"}, "nodes": [{"ref": "b"}], "fit": False},
        ])
        invalid = self.execute([
            {"action": "create_network_box", "id": "box", "name": "box"},
            {"action": "add_nodes_to_network_box", "box": {"ref": "box"}, "nodes": [{"ref": "missing"}]},
        ])

        first, second = self.parent.boxes[:2]
        self.assertTrue(result["success"])
        self.assertEqual([item.name() for item in first.contents], ["A"])
        self.assertEqual([item.name() for item in second.contents], ["B"])
        self.assertEqual(first.fit_count, 1)
        self.assertEqual(second.fit_count, 0)
        self.assertFalse(invalid["success"])
        self.assertIn("Unknown symbolic reference", invalid["errors"][0]["message"])

    def test_create_hda_and_install_definition_parameter_interface(self):
        result = self.execute([
            {"action": "create_node", "id": "asset", "node_type_name": "subnet", "name": "ROOF_ASSET"},
            {
                "action": "create_hda", "node": {"ref": "asset"}, "type_name": "hcb::roof::1.0",
                "label": "Roof Builder", "file_path": "/tmp/houdini-chat-bridge-tests/roof_builder.hda",
                "min_inputs": 0, "max_inputs": 1,
            },
            {
                "action": "install_hda_parameter_interface", "node": {"ref": "asset"}, "mode": "replace",
                "templates": [
                    {"type": "folder", "name": "main", "label": "Main", "children": [
                        {"type": "float", "name": "height", "label": "Height", "default": 4.0, "help": "Overall roof height."},
                        {"type": "int", "name": "segments", "label": "Segments", "default": 4, "min": 1},
                        {"type": "toggle", "name": "cap", "label": "Create cap", "default": True},
                        {"type": "string", "name": "material", "label": "Material", "default": "wood"},
                        {"type": "menu", "name": "style", "label": "Style", "items": ["gable", "flat"], "labels": ["Gable", "Flat"], "default": 0},
                    ]},
                ],
            },
        ])

        asset = self.parent.children[-1]
        self.assertTrue(result["success"])
        self.assertEqual(asset.hda_kwargs["name"], "hcb::roof::1.0")
        self.assertFalse(asset.hda_definition.options_value.save_spare_parms)
        self.assertIsNotNone(asset.hda_definition.parameter_group)
        self.assertEqual(len(asset.hda_definition.parameter_group.templates), 1)
        folder = asset.hda_definition.parameter_group.templates[0]
        self.assertEqual(len(folder.kwargs["parm_templates"]), 5)

    def test_node_parameter_interface_dry_run_is_non_mutating_and_id_reference_executes(self):
        templates = [
            {"type": "folder", "name": "dimensions", "label": "Dimensions", "children": [
                {"type": "float", "name": "house_width", "label": "House Width", "default": 5.0, "min": 2.0, "max": 12.0, "min_strict": True},
                {"type": "int", "name": "window_rows", "label": "Rows", "default": 3, "min": 1, "max": 8},
                {"type": "toggle", "name": "chimney", "label": "Enable Chimney", "default": True},
                {"type": "string", "name": "asset_label", "label": "Asset Label", "default": "Dutch House"},
                {"type": "folder", "name": "roof", "label": "Roof", "children": [
                    {"type": "menu", "name": "gable_style", "label": "Gable Style", "items": [
                        {"value": "pitched", "label": "Pitched"},
                        {"value": "stepped", "label": "Stepped"},
                    ], "default": "pitched"},
                ]},
            ]},
        ]
        operations = [
            {"action": "create_node", "id": "controls", "node_type_name": "null", "name": "HOUSE_CONTROLS"},
            {"action": "install_node_parameter_interface", "node": "controls", "templates": templates},
        ]

        checked = self.execute(operations, dry_run=True)
        executed = self.execute(operations)

        controls = self.parent.children[-1]
        self.assertTrue(checked["success"])
        self.assertEqual(len(self.parent.children), 2)
        self.assertEqual(self.events, [("group", "Houdini Chat Bridge batch"), ("enter", "Houdini Chat Bridge batch"), ("exit", "Houdini Chat Bridge batch")])
        self.assertTrue(executed["success"])
        dimensions = controls.parameter_group.find("dimensions")
        self.assertIsNotNone(dimensions)
        child_names = [child.name() for child in dimensions.parmTemplates()]
        self.assertEqual(child_names, ["house_width", "window_rows", "chimney", "asset_label", "roof"])
        children = {child.name(): child for child in dimensions.parmTemplates()}
        self.assertEqual(children["house_width"].kwargs["default_value"], (5.0,))
        self.assertEqual(children["window_rows"].kwargs["default_value"], (3,))
        self.assertEqual(children["asset_label"].kwargs["default_value"], ("Dutch House",))
        roof = dimensions.parmTemplates()[-1]
        menu = roof.parmTemplates()[0]
        self.assertEqual(menu.name(), "gable_style")
        self.assertEqual(menu.kwargs["default_value"], 0)
        self.assertEqual(controls.parm("house_width").isSpare(), True)
        self.assertFalse(controls.rename_conflicting_parms)

    def test_node_parameter_interface_upserts_and_preserves_existing_templates(self):
        controls = self.parent.createNode("null", "HOUSE_CONTROLS")
        self.hou.nodes[controls.path()] = controls
        standard = FakeParmTemplate("tx", "Translate X")
        unrelated = FakeParmTemplate("artist_note", "Artist Note")
        controls.parameter_group = FakeParmTemplateGroup([standard, unrelated])
        first = [{"type": "folder", "name": "dimensions", "label": "Dimensions", "children": [
            {"type": "float", "name": "house_width", "label": "House Width", "default": 5.0},
            {"type": "float", "name": "house_depth", "label": "House Depth", "default": 8.0},
        ]}]
        updated = [{"type": "folder", "name": "dimensions", "label": "Dimensions", "children": [
            {"type": "float", "name": "house_width", "label": "House Width", "default": 8.0},
            {"type": "int", "name": "window_rows", "label": "Rows", "default": 3},
        ]}]

        first_result = self.execute([
            {"action": "install_node_parameter_interface", "node": controls.path(), "templates": first},
        ])
        updated_result = self.execute([
            {"action": "install_node_parameter_interface", "node": controls.path(), "templates": updated},
        ])

        self.assertTrue(first_result["success"])
        self.assertTrue(updated_result["success"])
        self.assertEqual([template.name() for template in controls.parameter_group.templates], [
            "tx", "artist_note", "dimensions",
        ])
        dimensions = controls.parameter_group.find("dimensions")
        self.assertEqual([template.name() for template in dimensions.parmTemplates()], [
            "house_width", "house_depth", "window_rows",
        ])
        self.assertEqual(dimensions.parmTemplates()[0].kwargs["default_value"], (8.0,))

    def test_node_parameter_interface_check_rejects_builtin_parameter_name(self):
        result = self.execute([
            {"action": "install_node_parameter_interface", "node": self.pole.path(), "templates": [
                {"type": "float", "name": "height", "label": "Height", "default": 5.0},
            ]},
        ], dry_run=True)

        self.assertFalse(result["success"])
        self.assertIn("built in and cannot be replaced", result["errors"][0]["message"])
        self.assertEqual(self.events, [])

    def test_node_parameter_interface_reports_hom_error_details(self):
        controls = self.parent.createNode("null", "BROKEN_CONTROLS")
        self.hou.nodes[controls.path()] = controls

        def fail_to_install(group, rename_conflicting_parms=False):
            raise TypeError("expected a sequence for default_value")

        controls.setParmTemplateGroup = fail_to_install
        result = self.execute([
            {"action": "install_node_parameter_interface", "node": controls.path(), "templates": [
                {"type": "float", "name": "house_width", "label": "House Width", "default": 5.0},
            ]},
        ])

        self.assertFalse(result["success"])
        error = result["errors"][0]
        self.assertEqual(error["operation_index"], 0)
        self.assertEqual(error["action"], "install_node_parameter_interface")
        self.assertIn(controls.path(), error["message"])
        self.assertIn("TypeError: expected a sequence for default_value", error["message"])

    def test_descendant_existing_path_is_in_scope_and_expression_language_aliases_work(self):
        subnet = self.parent.createNode("subnet", "ASSEMBLY")
        child = subnet.createNode("tube", "POLE")
        self.hou.nodes[child.path()] = child
        result = self.execute([
            {"action": "set_expression", "node": child.path(), "parameter": "height", "expression": "$F", "language": "hscript"},
        ])

        self.assertTrue(result["success"])
        self.assertEqual(child.parm("height").expression, "$F")

    def test_hda_creation_requires_a_subnet_source(self):
        result = self.execute([
            {
                "action": "create_hda", "node": "/obj/custom/POLE", "type_name": "hcb::invalid::1.0",
                "label": "Invalid", "file_path": "/tmp/houdini-chat-bridge-tests/invalid.hda",
            },
        ])

        self.assertFalse(result["success"])
        self.assertIn("must be a subnet", result["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
