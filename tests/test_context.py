"""Houdini-free tests using small HOM-shaped fakes."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from houdini_chat_bridge.context import (
    inspect_current_context,
    inspect_current_network,
    inspect_node,
    inspect_upstream_network,
)


class FakeCategory:
    def name(self):
        return "Sop"


class FakeType:
    def name(self):
        return "box"

    def category(self):
        return FakeCategory()


class FakeTemplate:
    def __init__(self, label="Size"):
        self.label_value = label

    def label(self):
        return self.label_value

    def type(self):
        return "Float"

    def dataType(self):
        return "Float"

    def numComponents(self):
        return 3

    def tags(self):
        return {"role": "dimension"}


class FakeParm:
    def __init__(self, name, value, at_default, expression=None):
        self.name_value = name
        self.value = value
        self.at_default = at_default
        self.expression_value = expression

    def name(self):
        return self.name_value

    def isAtDefault(self):
        return self.at_default

    def hasExpression(self):
        return self.expression_value is not None

    def expression(self):
        return self.expression_value

    def expressionLanguage(self):
        return "Hscript"

    def eval(self):
        return self.value

    def parmTemplate(self):
        return FakeTemplate(self.name_value)

    def isTimeDependent(self):
        return self.expression_value is not None


class FakeConnection:
    def __init__(self, upstream, downstream, output_index, input_index):
        self.upstream = upstream
        self.downstream = downstream
        self.output_index = output_index
        self.input_index = input_index

    def outputNode(self):
        return self.upstream

    def inputNode(self):
        return self.downstream

    def outputIndex(self):
        return self.output_index

    def inputIndex(self):
        return self.input_index


class FakeNode:
    def __init__(self, path, parameters=()):
        self.path_value = path
        self.parameters = list(parameters)
        self.inputs = []
        self.outputs = []

    def isValid(self):
        return True

    def path(self):
        return self.path_value

    def name(self):
        return self.path_value.rsplit("/", 1)[-1]

    def type(self):
        return FakeType()

    def position(self):
        return (1.5, -2.0)

    def comment(self):
        return "A test node"

    def isDisplayFlagSet(self):
        return True

    def isRenderFlagSet(self):
        return False

    def inputConnections(self):
        return self.inputs

    def outputConnections(self):
        return self.outputs

    def parms(self):
        return self.parameters


class FakeNetwork(FakeNode):
    def __init__(self, path, display_node, render_node):
        super().__init__(path)
        self.display_node = display_node
        self.render_node = render_node
        self.child_nodes = []

    def displayNode(self):
        return self.display_node

    def renderNode(self):
        return self.render_node

    def children(self):
        return self.child_nodes


class FakeEditor:
    def __init__(self, network):
        self.network = network

    def type(self):
        return "NetworkEditor"

    def name(self):
        return "scene"

    def isCurrentTab(self):
        return True

    def pwd(self):
        return self.network


class FakeUi:
    def __init__(self, editor):
        self.editor = editor

    def paneTabs(self):
        return [self.editor]


class FakeHou:
    def __init__(self, network, selected):
        self.ui = FakeUi(FakeEditor(network))
        self.network = network
        self.selected = selected

    def selectedNodes(self):
        return self.selected

    def pwd(self):
        return self.network


class ContextInspectionTests(unittest.TestCase):
    def test_node_omits_default_parameters_and_serializes_connections(self):
        upstream = FakeNode("/obj/net/upstream")
        node = FakeNode(
            "/obj/net/target",
            parameters=(
                FakeParm("size", (1.0, 2.0, 3.0), False),
                FakeParm("group", "*", True),
                FakeParm("scale", 2.0, True, "$F / 10"),
            ),
        )
        connection = FakeConnection(upstream, node, 0, 1)
        node.inputs = [connection]
        upstream.outputs = [connection]

        result = inspect_node(node)

        self.assertEqual(result["position"], [1.5, -2.0])
        self.assertEqual([item["name"] for item in result["parameters"]], ["scale", "size"])
        self.assertEqual(result["parameters"][0]["expression"], "$F / 10")
        self.assertEqual(result["input_connections"][0]["upstream_node_path"], "/obj/net/upstream")
        self.assertEqual(result["output_connections"], [])
        json.dumps(result, sort_keys=True)

    def test_upstream_traversal_is_unique_and_sorted(self):
        source_a = FakeNode("/obj/net/a")
        source_b = FakeNode("/obj/net/b")
        target = FakeNode("/obj/net/target")
        target.inputs = [
            FakeConnection(source_b, target, 0, 1),
            FakeConnection(source_a, target, 0, 0),
        ]

        result = inspect_upstream_network(target)

        self.assertEqual(
            [node["path"] for node in result["nodes"]],
            ["/obj/net/a", "/obj/net/b", "/obj/net/target"],
        )
        self.assertEqual([edge["source_path"] for edge in result["connections"]], ["/obj/net/a", "/obj/net/b"])

    def test_current_context_uses_network_editor_without_path_assumptions(self):
        display = FakeNode("/obj/custom/display")
        render = FakeNode("/obj/custom/render")
        network = FakeNetwork("/obj/custom", display, render)
        hou = FakeHou(network, [render, display])

        with patch.dict(sys.modules, {"hou": hou}):
            result = inspect_current_context()

        self.assertEqual(result["current_network"]["path"], "/obj/custom")
        self.assertEqual(result["display_node"]["path"], "/obj/custom/display")
        self.assertEqual(
            [node["path"] for node in result["selected_nodes"]],
            ["/obj/custom/display", "/obj/custom/render"],
        )

    def test_current_network_inspects_immediate_children_in_stable_order(self):
        display = FakeNode("/obj/custom/display")
        render = FakeNode("/obj/custom/render")
        network = FakeNetwork("/obj/custom", display, render)
        network.child_nodes = [FakeNode("/obj/custom/z_last"), FakeNode("/obj/custom/a_first")]

        with patch.dict(sys.modules, {"hou": FakeHou(network, [])}):
            result = inspect_current_network()

        self.assertEqual(result["current_network"]["path"], "/obj/custom")
        self.assertEqual(
            [node["path"] for node in result["nodes"]],
            ["/obj/custom/a_first", "/obj/custom/z_last"],
        )


if __name__ == "__main__":
    unittest.main()
