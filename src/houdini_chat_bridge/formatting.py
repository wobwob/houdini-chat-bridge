"""Pure-Python formatting for structured Houdini inspection data."""

from __future__ import annotations

from typing import Any, Mapping


def format_context_for_chatgpt(context: Mapping[str, Any]) -> str:
    """Format inspection data as concise, readable context for a chat model.

    The function consumes only supplied structured data; it never queries
    Houdini or imports ``hou``.
    """
    if not isinstance(context, Mapping):
        raise ValueError("context must be a structured mapping returned by an inspection function.")

    lines = ["Houdini network context"]
    if context.get("error"):
        lines.extend(["", "Inspection note: %s" % context["error"]])
    network = context.get("current_network")
    if isinstance(network, Mapping):
        lines.extend(["", "Current network: %s" % _node_summary(network)])
    editor = context.get("network_editor")
    if isinstance(editor, Mapping):
        lines.append("Editor: %s (%s)" % (
            editor.get("name") or "unnamed", editor.get("type") or "Network Editor",
        ))
    for label, key in (("Display node", "display_node"), ("Render node", "render_node")):
        node = context.get(key)
        if isinstance(node, Mapping):
            lines.append("%s: %s" % (label, _node_summary(node)))

    selected = context.get("selected_nodes")
    nodes = selected if isinstance(selected, list) else context.get("nodes")
    if isinstance(nodes, list):
        heading = "Selected nodes" if isinstance(selected, list) else "Inspected nodes"
        lines.extend(["", "%s (%d):" % (heading, len(nodes))])
        for node in sorted((item for item in nodes if isinstance(item, Mapping)), key=_node_sort_key):
            lines.extend(_format_node(node))

    connections = context.get("connections")
    if isinstance(connections, list):
        lines.extend(["", "Upstream connections (%d):" % len(connections)])
        for connection in connections:
            if isinstance(connection, Mapping):
                lines.append("- %s[%s] -> %s[%s]" % (
                    connection.get("source_path", "unknown"),
                    connection.get("source_output_index", "?"),
                    connection.get("target_path", "unknown"),
                    connection.get("target_input_index", "?"),
                ))
    return "\n".join(lines)


def format_execution_summary(result: Mapping[str, Any]) -> str:
    """Format a concise, user-facing execution success summary.

    The complete structured executor result remains available separately for
    debugging; this deliberately reports only the high-value scene changes.
    """
    diff = result.get("diff")
    diff_data = diff if isinstance(diff, Mapping) else {}
    completed = result.get("operations_completed")
    completed_actions = [
        item.get("action") for item in completed
        if isinstance(item, Mapping) and isinstance(item.get("action"), str)
    ] if isinstance(completed, list) else []
    lines = ["SUCCESS"]
    created_nodes = _item_count(diff_data.get("created_nodes"))
    network_boxes = completed_actions.count("create_network_box")
    if created_nodes or network_boxes:
        lines.extend(["", "Created:"])
        if created_nodes:
            lines.append("  %d node%s" % (created_nodes, _plural_suffix(created_nodes)))
        if network_boxes:
            lines.append("  %d network box%s" % (network_boxes, _plural_suffix(network_boxes)))
    parameter_changes = _item_count(diff_data.get("parameter_changes"))
    if parameter_changes:
        lines.extend(["", "Modified:", "  %d parameter%s" % (
            parameter_changes, _plural_suffix(parameter_changes),
        )])
    hda_labels = _completed_hda_labels(result, completed_actions)
    if hda_labels:
        lines.extend(["", "HDA:"])
        lines.extend("  %s" % label for label in hda_labels)
    if len(lines) == 1:
        lines.extend(["", "Patch executed successfully."])
    return "\n".join(lines)


def _completed_hda_labels(result: Mapping[str, Any], completed_actions: list[str]) -> list[str]:
    if "create_hda" not in completed_actions:
        return []
    requested = result.get("operations_requested")
    if not isinstance(requested, list):
        return []
    return [
        str(operation.get("label") or operation.get("type_name"))
        for operation in requested
        if isinstance(operation, Mapping) and operation.get("action") == "create_hda"
    ]


def _item_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _plural_suffix(count: int) -> str:
    return "" if count == 1 else "s"


def _format_node(node: Mapping[str, Any]) -> list[str]:
    if node.get("valid") is False:
        return ["- Invalid node: %s" % (node.get("path") or node.get("error") or "unknown")]
    lines = ["- %s" % _node_summary(node)]
    position = node.get("position")
    if isinstance(position, list) and len(position) == 2:
        lines.append("  Position: %s, %s" % (position[0], position[1]))
    if node.get("comment"):
        lines.append("  Comment: %s" % node["comment"])
    flags = []
    if node.get("display_flag") is True:
        flags.append("display")
    if node.get("render_flag") is True:
        flags.append("render")
    if flags:
        lines.append("  Flags: %s" % ", ".join(flags))
    inputs = node.get("input_connections")
    if isinstance(inputs, list) and inputs:
        lines.append("  Inputs: " + ", ".join(
            "%s[%s] -> input %s" % (
                item.get("upstream_node_path", "unknown"),
                item.get("upstream_output_index", "?"), item.get("input_index", "?"),
            ) for item in inputs if isinstance(item, Mapping)
        ))
    parameters = node.get("parameters")
    if isinstance(parameters, list) and parameters:
        lines.append("  Non-default parameters:")
        for parameter in sorted((item for item in parameters if isinstance(item, Mapping)), key=lambda item: str(item.get("name", ""))):
            lines.append("    - %s" % _parameter_summary(parameter))
    return lines


def _node_summary(node: Mapping[str, Any]) -> str:
    path = node.get("path") or node.get("name") or "unknown node"
    type_name = node.get("type_name")
    category = node.get("type_category")
    type_text = "/".join(str(item) for item in (category, type_name) if item)
    return "%s%s" % (path, " [%s]" % type_text if type_text else "")


def _parameter_summary(parameter: Mapping[str, Any]) -> str:
    name = parameter.get("name") or "unnamed"
    label = parameter.get("label")
    details = " (%s)" % label if label and label != name else ""
    if parameter.get("expression") is not None:
        return "%s%s = expression: %s" % (name, details, parameter["expression"])
    if "value" in parameter:
        return "%s%s = %r" % (name, details, parameter["value"])
    return "%s%s = <not safely evaluated>" % (name, details)


def _node_sort_key(node: Mapping[str, Any]) -> str:
    return str(node.get("path") or node.get("name") or "")
