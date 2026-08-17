"""Stable, serializable network snapshots built from read-only inspection."""

from __future__ import annotations

from typing import Any

from .context import inspect_node


SNAPSHOT_SCHEMA_VERSION = 2


def snapshot_network(parent_or_nodes: Any, *, recursive: bool = False) -> dict[str, Any]:
    """Create a stable snapshot of a network parent's children or supplied nodes.

    Pass a Houdini network node to snapshot its direct children, or pass an
    iterable of nodes to snapshot precisely those nodes. The result excludes
    Set ``recursive=True`` to include all descendants of a supplied network
    parent. The result excludes UI-oriented and time-dependent inspection
    fields such as output connections. Positions, comments, and root network
    box membership are retained because PATCH actions can change them
    deliberately.
    """
    nodes, root_path = _resolve_nodes(parent_or_nodes)
    if recursive:
        nodes = _collect_descendants(nodes)
    snapshots: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for node in nodes:
        inspected = inspect_node(node)
        if inspected.get("valid") is not True:
            continue
        snapshot = _snapshot_node(inspected)
        path = snapshot["path"]
        if path in seen_paths:
            raise ValueError("snapshot input contains multiple nodes with path %r." % path)
        seen_paths.add(path)
        snapshots.append(snapshot)

    result = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "root_path": root_path,
        "nodes": sorted(snapshots, key=lambda item: item["path"]),
    }
    if root_path is not None:
        result["network_boxes"] = _snapshot_network_boxes(parent_or_nodes)
    return result


def _resolve_nodes(parent_or_nodes: Any) -> tuple[list[Any], str | None]:
    if parent_or_nodes is None:
        raise ValueError("parent_or_nodes must be a Houdini network node or an iterable of nodes.")

    children = _call(parent_or_nodes, "children")
    if children is not _MISSING:
        return _as_list(children), _text(_call(parent_or_nodes, "path"))

    if isinstance(parent_or_nodes, (str, bytes, dict)):
        raise ValueError("parent_or_nodes must be a Houdini network node or an iterable of nodes.")
    try:
        return list(parent_or_nodes), None
    except TypeError as error:
        raise ValueError(
            "parent_or_nodes must be a Houdini network node or an iterable of nodes."
        ) from error


def _snapshot_node(inspected: dict[str, Any]) -> dict[str, Any]:
    path = inspected.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("Cannot snapshot a node without a stable path.")
    return {
        "path": path,
        "name": _text(inspected.get("name")),
        "type_name": _text(inspected.get("type_name")),
        "type_category": _text(inspected.get("type_category")),
        "position": _position(inspected.get("position")),
        "display_flag": _bool_or_none(inspected.get("display_flag")),
        "render_flag": _bool_or_none(inspected.get("render_flag")),
        "comment": _text(inspected.get("comment")),
        "input_connections": _snapshot_inputs(inspected.get("input_connections")),
        "parameters": _snapshot_parameters(inspected.get("parameters")),
    }


def _snapshot_network_boxes(parent: Any) -> list[dict[str, Any]]:
    """Capture named boxes in the execution network and their node members."""
    boxes: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for network_box in _as_list(_call(parent, "networkBoxes")):
        name = _text(_call(network_box, "name"))
        if name is None:
            continue
        if name in seen_names:
            raise ValueError("network snapshot contains duplicate network box name %r." % name)
        seen_names.add(name)
        node_paths = sorted({
            path for item in _as_list(_call(network_box, "items"))
            if (path := _text(_call(item, "path"))) is not None
        })
        boxes.append({"name": name, "node_paths": node_paths})
    return sorted(boxes, key=lambda item: item["name"])


def _collect_descendants(nodes: list[Any]) -> list[Any]:
    """Return supplied nodes and their descendants once, in stable path order."""
    collected: list[Any] = []
    seen: set[str] = set()

    def visit(node: Any) -> None:
        path = _text(_call(node, "path"))
        key = path if path is not None else "<object:%d>" % id(node)
        if key in seen:
            return
        seen.add(key)
        collected.append(node)
        children = _as_list(_call(node, "children"))
        for child in sorted(children, key=_node_sort_key):
            visit(child)

    for node in sorted(nodes, key=_node_sort_key):
        visit(node)
    return collected


def _node_sort_key(node: Any) -> str:
    return _text(_call(node, "path")) or "<object:%d>" % id(node)


def _snapshot_inputs(value: Any) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for connection in _as_list(value):
        if not isinstance(connection, dict):
            continue
        input_index = connection.get("input_index")
        upstream_path = connection.get("upstream_node_path")
        output_index = connection.get("upstream_output_index")
        if not isinstance(input_index, int) or not isinstance(upstream_path, str):
            continue
        inputs.append(
            {
                "input_index": input_index,
                "upstream_node_path": upstream_path,
                "upstream_output_index": output_index if isinstance(output_index, int) else None,
            }
        )
    return sorted(
        inputs,
        key=lambda item: (item["input_index"], item["upstream_node_path"], _sort_index(item["upstream_output_index"])),
    )


def _snapshot_parameters(value: Any) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    for parameter in _as_list(value):
        if not isinstance(parameter, dict) or not isinstance(parameter.get("name"), str):
            continue
        item: dict[str, Any] = {"name": parameter["name"]}
        expression = parameter.get("expression")
        if isinstance(expression, str):
            item["expression"] = expression
            if isinstance(parameter.get("expression_language"), str):
                item["expression_language"] = parameter["expression_language"]
        elif "value" in parameter:
            item["value"] = parameter["value"]
        else:
            item["value_available"] = False
        parameters.append(item)
    return sorted(parameters, key=lambda item: item["name"])


_MISSING = object()


def _call(target: Any, name: str) -> Any:
    try:
        value = getattr(target, name)
        return value() if callable(value) else value
    except Exception:
        return _MISSING


def _as_list(value: Any) -> list[Any]:
    if value is _MISSING or value is None or isinstance(value, (str, bytes, dict)):
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _position(value: Any) -> list[float] | None:
    if value is None or isinstance(value, (str, bytes, dict)):
        return None
    try:
        coordinates = list(value)
    except TypeError:
        return None
    if len(coordinates) != 2:
        return None
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in coordinates):
        return None
    return [float(coordinates[0]), float(coordinates[1])]


def _sort_index(value: int | None) -> int:
    return value if isinstance(value, int) else -1
