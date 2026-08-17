"""Read-only, serializable inspection of Houdini networks through HOM.

This module deliberately does not import :mod:`hou` at import time.  That keeps
``inspect_node`` testable with lightweight fakes and allows the package's pure
Python modules to load outside Houdini.
"""

from __future__ import annotations

import importlib
import math
from typing import Any


_MISSING = object()


def inspect_node(node: Any) -> dict[str, Any]:
    """Return a serializable, read-only description of ``node``.

    Invalid or unavailable nodes produce ``{"valid": False, ...}`` rather
    than raising. Parameter capture is intentionally limited to non-default
    parameters and parameters with expressions.
    """
    if not _is_valid_node(node):
        return {
            "valid": False,
            "path": _text(_call(node, "path")),
            "name": _text(_call(node, "name")),
            "error": "Node is missing or no longer valid.",
        }

    node_type = _call(node, "type")
    category = _call(node_type, "category")
    input_records = _input_connection_records(node)
    output_records = _output_connection_records(node)
    return {
        "valid": True,
        "path": _text(_call(node, "path")),
        "name": _text(_call(node, "name")),
        "type_name": _text(_call(node_type, "name")),
        "type_category": _text(_call(category, "name")),
        "position": _position(_call(node, "position")),
        "comment": _text(_call(node, "comment")),
        "display_flag": _boolean_or_none(_call(node, "isDisplayFlagSet")),
        "render_flag": _boolean_or_none(_call(node, "isRenderFlagSet")),
        "input_connections": [record for record, _ in input_records],
        "output_connections": [record for record, _ in output_records],
        "parameters": _inspect_parameters(node),
    }


def inspect_selected_nodes() -> dict[str, Any]:
    """Inspect all currently selected Houdini nodes in stable path order."""
    hou = _get_hou()
    if hou is None:
        return _hou_unavailable("selected_nodes")
    selected = _call(hou, "selectedNodes")
    nodes = sorted(_sequence(selected), key=_node_sort_key)
    return {"selected_nodes": [inspect_node(node) for node in nodes]}


def inspect_upstream_network(node: Any) -> dict[str, Any]:
    """Inspect ``node`` and every wired upstream node exactly once.

    Traversal follows only input connections, tracks visited node paths, and
    sorts connections and results to provide stable snapshot input.
    """
    if not _is_valid_node(node):
        return {
            "root_path": _text(_call(node, "path")),
            "nodes": [inspect_node(node)],
            "connections": [],
        }

    visited: set[str] = set()
    inspected: dict[str, dict[str, Any]] = {}
    connections: list[dict[str, Any]] = []

    def visit(current: Any) -> None:
        key = _node_key(current)
        if key in visited:
            return
        visited.add(key)
        inspected[key] = inspect_node(current)
        for record, upstream_node in _input_connection_records(current):
            connections.append(
                {
                    "source_path": record["upstream_node_path"],
                    "source_output_index": record["upstream_output_index"],
                    "target_path": _text(_call(current, "path")),
                    "target_input_index": record["input_index"],
                }
            )
            if _is_valid_node(upstream_node):
                visit(upstream_node)

    visit(node)
    return {
        "root_path": _text(_call(node, "path")),
        "nodes": sorted(inspected.values(), key=lambda item: _sort_text(item.get("path"))),
        "connections": sorted(
            connections,
            key=lambda item: (
                _sort_text(item["source_path"]),
                _sort_index(item["source_output_index"]),
                _sort_text(item["target_path"]),
                _sort_index(item["target_input_index"]),
            ),
        ),
    }


def inspect_current_context() -> dict[str, Any]:
    """Return useful network-editor context without assuming a node path."""
    hou = _get_hou()
    if hou is None:
        return _hou_unavailable("current_context")

    editor = _find_network_editor(hou)
    network = _call(editor, "pwd") if editor is not None else _call(hou, "pwd")
    display_node = _call(network, "displayNode")
    render_node = _call(network, "renderNode")
    selected = _call(hou, "selectedNodes")
    return {
        "network_editor": _editor_reference(editor),
        "current_network": _node_reference(network),
        "selected_nodes": [
            inspect_node(item) for item in sorted(_sequence(selected), key=_node_sort_key)
        ],
        "display_node": inspect_node(display_node) if _is_valid_node(display_node) else None,
        "render_node": inspect_node(render_node) if _is_valid_node(render_node) else None,
    }


def inspect_current_network() -> dict[str, Any]:
    """Inspect every immediate child in the active Network Editor's network.

    This describes the network currently visible in Houdini rather than
    recursively walking into nested subnetworks.  It deliberately reuses the
    same read-only node inspection as the other context exports.
    """
    hou = _get_hou()
    if hou is None:
        return _hou_unavailable("current_network")

    editor = _find_network_editor(hou)
    network = _call(editor, "pwd") if editor is not None else _call(hou, "pwd")
    display_node = _call(network, "displayNode")
    render_node = _call(network, "renderNode")
    children = sorted(_sequence(_call(network, "children")), key=_node_sort_key)
    return {
        "network_editor": _editor_reference(editor),
        "current_network": _node_reference(network),
        "display_node": inspect_node(display_node) if _is_valid_node(display_node) else None,
        "render_node": inspect_node(render_node) if _is_valid_node(render_node) else None,
        "nodes": [inspect_node(node) for node in children],
    }


def _inspect_parameters(node: Any) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    for parm in _sequence(_call(node, "parms")):
        is_default = _boolean_or_none(_call(parm, "isAtDefault"))
        expression = _parameter_expression(parm)
        if is_default is True and expression is None:
            continue
        if is_default is None and expression is None:
            # Do not risk serializing every parameter when its default state
            # cannot be determined by this Houdini version or a custom parm.
            continue
        template = _call(parm, "parmTemplate")
        result: dict[str, Any] = {
            "name": _text(_call(parm, "name")),
            "label": _text(_call(template, "label")),
            "template_type": _enum_text(_call(template, "type")),
            "data_type": _enum_text(_call(template, "dataType")),
            "num_components": _integer_or_none(_call(template, "numComponents")),
            "is_default": is_default,
            "is_time_dependent": _boolean_or_none(_call(parm, "isTimeDependent")),
            "tags": _json_mapping(_call(template, "tags")),
        }
        if expression is not None:
            result["expression"] = expression
            language = _enum_text(_call(parm, "expressionLanguage"))
            if language is not None:
                result["expression_language"] = language
        value = _json_value(_call(parm, "eval"))
        if value is not _MISSING:
            result["value"] = value
        parameters.append(result)
    return sorted(parameters, key=lambda item: _sort_text(item.get("name")))


def _parameter_expression(parm: Any) -> str | None:
    if _boolean_or_none(_call(parm, "hasExpression")) is False:
        return None
    return _text(_call(parm, "expression"))


def _input_connection_records(node: Any) -> list[tuple[dict[str, Any], Any]]:
    records: list[tuple[dict[str, Any], Any]] = []
    for connection in _sequence(_call(node, "inputConnections")):
        upstream = _call(connection, "outputNode")
        records.append(({
            "input_index": _integer_or_none(_call(connection, "inputIndex")),
            "upstream_node_path": _text(_call(upstream, "path")),
            "upstream_output_index": _integer_or_none(_call(connection, "outputIndex")),
        }, upstream))
    return sorted(records, key=lambda item: (
        _sort_index(item[0]["input_index"]),
        _sort_text(item[0]["upstream_node_path"]),
        _sort_index(item[0]["upstream_output_index"]),
    ))


def _output_connection_records(node: Any) -> list[tuple[dict[str, Any], Any]]:
    records: list[tuple[dict[str, Any], Any]] = []
    for connection in _sequence(_call(node, "outputConnections")):
        downstream = _call(connection, "inputNode")
        records.append(({
            "output_index": _integer_or_none(_call(connection, "outputIndex")),
            "downstream_node_path": _text(_call(downstream, "path")),
            "downstream_input_index": _integer_or_none(_call(connection, "inputIndex")),
        }, downstream))
    return sorted(records, key=lambda item: (
        _sort_index(item[0]["output_index"]),
        _sort_text(item[0]["downstream_node_path"]),
        _sort_index(item[0]["downstream_input_index"]),
    ))


def _find_network_editor(hou: Any) -> Any:
    ui = _call(hou, "ui")
    tabs = [tab for tab in _sequence(_call(ui, "paneTabs")) if _is_network_editor(tab)]
    if not tabs:
        return None
    active = [tab for tab in tabs if _boolean_or_none(_call(tab, "isCurrentTab")) is True]
    return sorted(active or tabs, key=lambda tab: (
        _sort_text(_call(tab, "name")), _node_sort_key(_call(tab, "pwd")),
    ))[0]


def _is_network_editor(tab: Any) -> bool:
    tab_type = _enum_text(_call(tab, "type")) or tab.__class__.__name__
    return "networkeditor" in tab_type.replace(" ", "").lower()


def _editor_reference(editor: Any) -> dict[str, Any] | None:
    if editor is None:
        return None
    return {"name": _text(_call(editor, "name")), "type": _enum_text(_call(editor, "type"))}


def _node_reference(node: Any) -> dict[str, Any] | None:
    if not _is_valid_node(node):
        return None
    node_type = _call(node, "type")
    return {
        "path": _text(_call(node, "path")),
        "name": _text(_call(node, "name")),
        "type_name": _text(_call(node_type, "name")),
        "type_category": _text(_call(_call(node_type, "category"), "name")),
    }


def _get_hou() -> Any:
    try:
        return importlib.import_module("hou")
    except ImportError:
        return None


def _hou_unavailable(scope: str) -> dict[str, Any]:
    return {
        "error": "Houdini's hou module is not available; %s cannot be inspected." % scope,
        "selected_nodes": [],
    }


def _is_valid_node(node: Any) -> bool:
    if node is None or node is _MISSING:
        return False
    try:
        checker = getattr(node, "isValid", _MISSING)
        if checker is _MISSING:
            return True
        result = checker() if callable(checker) else checker
        return result is not False
    except Exception:
        return False


def _call(target: Any, name: str) -> Any:
    if target is None or target is _MISSING:
        return _MISSING
    try:
        value = getattr(target, name)
        return value() if callable(value) else value
    except Exception:
        return _MISSING


def _sequence(value: Any) -> list[Any]:
    if value is _MISSING or value is None or isinstance(value, (str, bytes, dict)):
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _position(value: Any) -> list[float] | None:
    if value is _MISSING or value is None:
        return None
    x, y = _call(value, "x"), _call(value, "y")
    if x is _MISSING or y is _MISSING:
        try:
            x, y = value[0], value[1]
        except (IndexError, KeyError, TypeError):
            return None
    try:
        return [float(x), float(y)]
    except (TypeError, ValueError):
        return None


def _json_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    converted: dict[str, Any] = {}
    for key in sorted(value, key=str):
        item = _json_value(value[key])
        if item is not _MISSING:
            converted[str(key)] = item
    return converted


def _json_value(value: Any) -> Any:
    """Convert known safe value types without leaking HOM objects."""
    if value is _MISSING:
        return _MISSING
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (list, tuple)):
        converted = [_json_value(item) for item in value]
        return converted if all(item is not _MISSING for item in converted) else _MISSING
    if isinstance(value, dict):
        return _json_mapping(value)
    return _MISSING


def _text(value: Any) -> str | None:
    if value is _MISSING or value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return str(value)
    return _enum_text(value)


def _enum_text(value: Any) -> str | None:
    if value is _MISSING or value is None:
        return None
    if isinstance(value, str):
        return value
    name = _call(value, "name")
    if isinstance(name, str):
        return name
    text = str(value)
    return text if text and " object at 0x" not in text else None


def _boolean_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _integer_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _node_key(node: Any) -> str:
    path = _text(_call(node, "path"))
    if path:
        return path
    name = _text(_call(node, "name"))
    return name or "unidentified:%d" % id(node)


def _node_sort_key(node: Any) -> tuple[str, str]:
    return (_sort_text(_call(node, "path")), _sort_text(_call(node, "name")))


def _sort_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _sort_index(value: Any) -> int:
    return value if isinstance(value, int) else -1
