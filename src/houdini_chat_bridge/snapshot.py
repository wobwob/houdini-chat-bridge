"""Stable, serializable network snapshots built from read-only inspection."""

from __future__ import annotations

from typing import Any

from .context import inspect_node


SNAPSHOT_SCHEMA_VERSION = 1


def snapshot_network(parent_or_nodes: Any) -> dict[str, Any]:
    """Create a stable snapshot of a network parent's direct children or nodes.

    Pass a Houdini network node to snapshot its direct children, or pass an
    iterable of nodes to snapshot precisely those nodes. The result excludes
    UI-oriented and time-dependent inspection fields such as position, comment,
    output connections, and evaluated values for expression-driven parameters.
    """
    nodes, root_path = _resolve_nodes(parent_or_nodes)
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

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "root_path": root_path,
        "nodes": sorted(snapshots, key=lambda item: item["path"]),
    }


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
        "display_flag": _bool_or_none(inspected.get("display_flag")),
        "render_flag": _bool_or_none(inspected.get("render_flag")),
        "input_connections": _snapshot_inputs(inspected.get("input_connections")),
        "parameters": _snapshot_parameters(inspected.get("parameters")),
    }


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


def _sort_index(value: int | None) -> int:
    return value if isinstance(value, int) else -1
