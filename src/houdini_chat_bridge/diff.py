"""Pure-Python comparison and presentation of Houdini network snapshots."""

from __future__ import annotations

from typing import Any, Mapping


def compare_snapshots(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Compare two stable snapshots and return structured network changes.

    Snapshots are treated as data only. This module deliberately has no HOM or
    ``hou`` dependency, making comparison suitable for ordinary unit tests.
    """
    before_nodes = _node_index(before, "before")
    after_nodes = _node_index(after, "after")
    before_paths = set(before_nodes)
    after_paths = set(after_nodes)

    created_nodes = [_node_reference(after_nodes[path]) for path in sorted(after_paths - before_paths)]
    deleted_nodes = [_node_reference(before_nodes[path]) for path in sorted(before_paths - after_paths)]
    parameter_changes: list[dict[str, Any]] = []
    connection_changes: list[dict[str, Any]] = []
    flag_changes: list[dict[str, Any]] = []
    modified: dict[str, dict[str, Any]] = {}

    for path in sorted(before_paths & after_paths):
        before_node = before_nodes[path]
        after_node = after_nodes[path]
        node_changes = _node_changes(before_node, after_node)
        parameters = _parameter_changes(path, before_node, after_node)
        connections = _connection_changes(path, before_node, after_node)
        flags = _flag_changes(path, before_node, after_node)
        _add_display_names(parameters, connections, flags, before_nodes, after_nodes)

        parameter_changes.extend(parameters)
        connection_changes.extend(connections)
        flag_changes.extend(flags)
        if node_changes or parameters or connections or flags:
            modified[path] = {
                "node": path,
                "node_name": after_node.get("name") or before_node.get("name"),
                "node_changes": node_changes,
                "parameter_changes": parameters,
                "connection_changes": connections,
                "flag_changes": flags,
            }

    return {
        "created_nodes": created_nodes,
        "deleted_nodes": deleted_nodes,
        "modified_nodes": [modified[path] for path in sorted(modified)],
        "parameter_changes": parameter_changes,
        "connection_changes": connection_changes,
        "flag_changes": flag_changes,
    }


def format_diff(diff: Mapping[str, Any]) -> str:
    """Return a readable summary of a structured result from ``compare_snapshots``."""
    if not isinstance(diff, Mapping):
        raise ValueError("diff must be a structured mapping returned by compare_snapshots.")

    lines = ["Created:"]
    _append_node_list(lines, diff.get("created_nodes"))
    lines.extend(["", "Modified:"])
    _append_modified_nodes(lines, diff.get("modified_nodes"))
    lines.extend(["", "Connections:"])
    _append_connection_changes(lines, diff.get("connection_changes"))
    lines.extend(["", "Flags:"])
    _append_flag_changes(lines, diff.get("flag_changes"))
    lines.extend(["", "Deleted:"])
    _append_node_list(lines, diff.get("deleted_nodes"))
    return "\n".join(lines)


def _node_index(snapshot: Mapping[str, Any], label: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("%s snapshot must be a mapping." % label)
    nodes = snapshot.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("%s snapshot must contain a 'nodes' list." % label)
    index: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, Mapping):
            raise ValueError("%s snapshot contains a non-mapping node." % label)
        path = node.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("%s snapshot contains a node without a path." % label)
        if path in index:
            raise ValueError("%s snapshot contains duplicate node path %r." % (label, path))
        index[path] = node
    return index


def _node_reference(node: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": node["path"],
        "name": node.get("name"),
        "type_name": node.get("type_name"),
        "type_category": node.get("type_category"),
    }


def _node_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
    changes = []
    for field in ("type_name", "type_category"):
        if before.get(field) != after.get(field):
            changes.append({"field": field, "before": before.get(field), "after": after.get(field)})
    return changes


def _parameter_changes(
    path: str, before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[dict[str, Any]]:
    before_parameters = _named_index(before.get("parameters"), "parameter", path)
    after_parameters = _named_index(after.get("parameters"), "parameter", path)
    changes = []
    for name in sorted(set(before_parameters) | set(after_parameters)):
        previous = before_parameters.get(name)
        current = after_parameters.get(name)
        if previous != current:
            changes.append({"node": path, "parameter": name, "before": previous, "after": current})
    return changes


def _connection_changes(
    path: str, before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[dict[str, Any]]:
    before_inputs = _input_index(before.get("input_connections"), path)
    after_inputs = _input_index(after.get("input_connections"), path)
    changes = []
    for input_index in sorted(set(before_inputs) | set(after_inputs)):
        previous = before_inputs.get(input_index)
        current = after_inputs.get(input_index)
        if previous != current:
            changes.append(
                {"node": path, "input_index": input_index, "before": previous, "after": current}
            )
    return changes


def _flag_changes(
    path: str, before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[dict[str, Any]]:
    changes = []
    for flag in ("display_flag", "render_flag"):
        previous = before.get(flag)
        current = after.get(flag)
        if previous is not None and current is not None and previous != current:
            changes.append({"node": path, "flag": flag, "before": previous, "after": current})
    return changes


def _named_index(value: Any, label: str, path: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        return {}
    index: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise ValueError("Node %r contains an invalid %s entry." % (path, label))
        name = item["name"]
        if name in index:
            raise ValueError("Node %r contains duplicate %s %r." % (path, label, name))
        index[name] = item
    return index


def _input_index(value: Any, path: str) -> dict[int, Mapping[str, Any]]:
    if not isinstance(value, list):
        return {}
    index: dict[int, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("input_index"), int):
            raise ValueError("Node %r contains an invalid input connection." % path)
        input_index = item["input_index"]
        if input_index in index:
            raise ValueError("Node %r contains multiple connections for input %d." % (path, input_index))
        index[input_index] = item
    return index


def _add_display_names(
    parameters: list[dict[str, Any]],
    connections: list[dict[str, Any]],
    flags: list[dict[str, Any]],
    before_nodes: Mapping[str, Mapping[str, Any]],
    after_nodes: Mapping[str, Mapping[str, Any]],
) -> None:
    for change in parameters + flags:
        node = after_nodes.get(change["node"]) or before_nodes.get(change["node"])
        if node is not None:
            change["node_name"] = node.get("name")
    for change in connections:
        target = after_nodes.get(change["node"]) or before_nodes.get(change["node"])
        if target is not None:
            change["node_name"] = target.get("name")
        before_connection = change.get("before")
        after_connection = change.get("after")
        if isinstance(before_connection, Mapping):
            source = before_nodes.get(before_connection.get("upstream_node_path"))
            if source is not None:
                change["before_node_name"] = source.get("name")
        if isinstance(after_connection, Mapping):
            source = after_nodes.get(after_connection.get("upstream_node_path"))
            if source is not None:
                change["after_node_name"] = source.get("name")


def _append_node_list(lines: list[str], nodes: Any) -> None:
    valid_nodes = nodes if isinstance(nodes, list) else []
    if not valid_nodes:
        lines.append("- none")
        return
    for node in valid_nodes:
        if isinstance(node, Mapping):
            lines.append("- %s" % _node_label(node))


def _append_modified_nodes(lines: list[str], nodes: Any) -> None:
    valid_nodes = nodes if isinstance(nodes, list) else []
    if not valid_nodes:
        lines.append("- none")
        return
    for node in valid_nodes:
        if not isinstance(node, Mapping):
            continue
        lines.append("- %s" % _node_label(node))
        for change in node.get("node_changes", []):
            if isinstance(change, Mapping):
                lines.append("  %s: %s -> %s" % (
                    change.get("field"), change.get("before"), change.get("after"),
                ))
        for change in node.get("parameter_changes", []):
            if isinstance(change, Mapping):
                lines.append("  %s: %s -> %s" % (
                    change.get("parameter"), _parameter_value(change.get("before")),
                    _parameter_value(change.get("after")),
                ))


def _append_connection_changes(lines: list[str], changes: Any) -> None:
    valid_changes = changes if isinstance(changes, list) else []
    if not valid_changes:
        lines.append("- none")
        return
    for change in valid_changes:
        if isinstance(change, Mapping):
            lines.append("- %s input %s: %s -> %s" % (
                _node_label(change), change.get("input_index"),
                _connection_label(change.get("before"), change.get("before_node_name")),
                _connection_label(change.get("after"), change.get("after_node_name")),
            ))


def _append_flag_changes(lines: list[str], changes: Any) -> None:
    valid_changes = changes if isinstance(changes, list) else []
    if not valid_changes:
        lines.append("- none")
        return
    for change in valid_changes:
        if isinstance(change, Mapping):
            flag = str(change.get("flag", "flag")).replace("_flag", "")
            lines.append("- %s %s: %s -> %s" % (
                _node_label(change), flag, change.get("before"), change.get("after"),
            ))


def _parameter_value(value: Any) -> str:
    if value is None:
        return "<default>"
    if not isinstance(value, Mapping):
        return repr(value)
    if "expression" in value:
        return "expression: %s" % value["expression"]
    if "value" in value:
        return repr(value["value"])
    return "<not safely evaluated>"


def _connection_label(value: Any, node_name: Any = None) -> str:
    if not isinstance(value, Mapping):
        return "none"
    source = str(node_name) if isinstance(node_name, str) and node_name else _path_label(value.get("upstream_node_path"))
    output = value.get("upstream_output_index")
    return "%s%s" % (source, "[%s]" % output if output is not None else "")


def _node_label(node: Mapping[str, Any]) -> str:
    return str(node.get("name") or node.get("node_name") or _path_label(node.get("path") or node.get("node")))


def _path_label(path: Any) -> str:
    if not isinstance(path, str) or not path:
        return "unknown"
    return path.rstrip("/").rsplit("/", 1)[-1] or path
