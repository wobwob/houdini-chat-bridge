"""Houdini-free tests for explicit HOM action primitives."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from houdini_chat_bridge.actions import (
    connect_nodes,
    create_network_box,
    create_node,
    create_sticky_note,
    disconnect_input,
    set_display_flag,
    set_expression,
    set_parameter,
    set_render_flag,
)
from houdini_chat_bridge.validation import validate_position


class FakeParameter:
    def __init__(self):
        self.value = None
        self.expression = None
        self.language = None

    def set(self, value):
        self.value = value

    def setExpression(self, expression, language=None):
        self.expression = expression
        self.language = language


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


class FakeNetworkBox:
    def __init__(self, name):
        self.name = name
        self.comment = None
        self.color = None

    def setComment(self, comment):
        self.comment = comment

    def setColor(self, color):
        self.color = color


class FakeStickyNote:
    def __init__(self):
        self.text = None
        self.name = None

    def setText(self, text):
        self.text = text

    def setName(self, name):
        self.name = name


class FakeNode:
    def __init__(self, path, parameters=None):
        self.path_value = path
        self.parameters = parameters or {}
        self.inputs = []
        self.children = []
        self.created = []
        self.position = None
        self.display = False
        self.render = False
        self.boxes = []
        self.notes = []

    def isValid(self):
        return True

    def path(self):
        return self.path_value

    def name(self):
        return self.path_value.rsplit("/", 1)[-1]

    def parm(self, name):
        return self.parameters.get(name)

    def createNode(self, node_type_name, name):
        child = FakeNode("%s/%s" % (self.path_value, name or node_type_name))
        child.node_type_name = node_type_name
        self.created.append(child)
        return child

    def setPosition(self, position):
        self.position = position

    def inputConnections(self):
        return list(self.inputs)

    def inputCount(self):
        return 3

    def outputCount(self):
        return 2

    def setInput(self, input_index, source, output_index=0):
        self.inputs = [item for item in self.inputs if item.inputIndex() != input_index]
        if source is not None:
            self.inputs.append(FakeConnection(source, output_index, input_index))

    def setDisplayFlag(self, enabled):
        self.display = enabled

    def setRenderFlag(self, enabled):
        self.render = enabled

    def createNetworkBox(self, name):
        box = FakeNetworkBox(name)
        self.boxes.append(box)
        return box

    def createStickyNote(self):
        note = FakeStickyNote()
        self.notes.append(note)
        return note


class ActionTests(unittest.TestCase):
    def test_create_node_uses_requested_name_and_only_positions_when_requested(self):
        parent = FakeNode("/obj/custom")

        first = create_node(parent, "box", name="foundation")
        second = create_node(parent, "transform", name="raise_roof", position=(4, -2))

        self.assertEqual(first.path(), "/obj/custom/foundation")
        self.assertIsNone(first.position)
        self.assertEqual(second.position, (4.0, -2.0))

    def test_parameter_actions_validate_parameter_names_and_set_values(self):
        height = FakeParameter()
        node = FakeNode("/obj/custom/pole", {"height": height})

        self.assertIs(set_parameter(node, "height", 5.0), node)
        self.assertEqual(height.value, 5.0)
        set_expression(node, "height", "$F / 10", language="Hscript")
        self.assertEqual(height.expression, "$F / 10")
        self.assertEqual(height.language, "Hscript")
        with self.assertRaisesRegex(RuntimeError, "Parameter 'missing'.*/obj/custom/pole"):
            set_parameter(node, "missing", 1)

    def test_connections_preserve_existing_inputs_unless_replacement_is_explicit(self):
        old_source = FakeNode("/obj/custom/old")
        new_source = FakeNode("/obj/custom/new")
        target = FakeNode("/obj/custom/target")
        target.setInput(0, old_source, 0)

        with self.assertRaisesRegex(RuntimeError, "already connected"):
            connect_nodes(new_source, target, input_index=0)
        connect_nodes(new_source, target, input_index=0, output_index=1, replace_existing=True)

        connection = target.inputConnections()[0]
        self.assertIs(connection.outputNode(), new_source)
        self.assertEqual(connection.outputIndex(), 1)
        self.assertIs(disconnect_input(target, 0), target)
        self.assertEqual(target.inputConnections(), [])
        with self.assertRaisesRegex(RuntimeError, "is not connected"):
            disconnect_input(target, 0)

    def test_connection_port_validation_contains_node_context(self):
        source = FakeNode("/obj/custom/source")
        target = FakeNode("/obj/custom/target")

        with self.assertRaisesRegex(RuntimeError, "/obj/custom/target.*input index 3"):
            connect_nodes(source, target, input_index=3)
        with self.assertRaisesRegex(RuntimeError, "/obj/custom/source.*output index 2"):
            connect_nodes(source, target, output_index=2)

    def test_flag_actions_require_boolean_values(self):
        node = FakeNode("/obj/custom/output")

        set_display_flag(node, True)
        set_render_flag(node, True)
        self.assertTrue(node.display)
        self.assertTrue(node.render)
        with self.assertRaisesRegex(ValueError, "enabled must be a boolean"):
            set_display_flag(node, 1)  # type: ignore[arg-type]

    def test_network_annotations_are_created_without_moving_nodes(self):
        parent = FakeNode("/obj/custom")

        box = create_network_box(parent, name="roof_group", comment="Roof assembly")
        note = create_sticky_note(parent, "Keep this branch intact.", name="preserve_branch")

        self.assertEqual(box.name, "roof_group")
        self.assertEqual(box.comment, "Roof assembly")
        self.assertEqual(box.color, (0.0, 0.0, 0.0))
        self.assertEqual(note.text, "Keep this branch intact.")
        self.assertEqual(note.name, "preserve_branch")
        self.assertEqual(parent.children, [])

    def test_validation_rejects_invalid_position_and_path_as_a_name(self):
        parent = FakeNode("/obj/custom")

        with self.assertRaisesRegex(ValueError, "two-item"):
            validate_position((1,))
        with self.assertRaisesRegex(ValueError, "not a path"):
            create_node(parent, "box", name="/obj/geo1")


if __name__ == "__main__":
    unittest.main()
