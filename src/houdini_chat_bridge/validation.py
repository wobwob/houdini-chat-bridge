"""Validation helpers for the small, controlled HOM action set."""

from __future__ import annotations

from typing import Any


def require_valid_node(node: Any, role: str = "node") -> Any:
    """Return a valid HOM node or raise a useful error."""
    if node is None:
        raise RuntimeError("%s is missing." % role)
    try:
        checker = getattr(node, "isValid", None)
        if callable(checker) and checker() is False:
            raise RuntimeError("%s %s is no longer valid." % (role, node_label(node)))
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError("Could not validate %s." % role) from error
    return node


def require_network_parent(parent: Any) -> Any:
    """Validate that ``parent`` can create network items."""
    require_valid_node(parent, "parent node")
    require_method(parent, "createNode", "Parent node %s cannot create nodes." % node_label(parent))
    return parent


def require_parameter(node: Any, parameter_name: str) -> Any:
    """Validate and return a parameter on ``node``."""
    require_valid_node(node)
    validate_parameter_name(parameter_name)
    try:
        parameter = node.parm(parameter_name)
    except Exception as error:
        raise RuntimeError(
            "Could not look up parameter %r on node %s." % (parameter_name, node_label(node))
        ) from error
    if parameter is None:
        raise RuntimeError("Parameter %r does not exist on node %s." % (parameter_name, node_label(node)))
    return parameter


def require_method(target: Any, method_name: str, message: str) -> Any:
    """Return a callable method or raise ``RuntimeError`` with ``message``."""
    try:
        method = getattr(target, method_name)
    except Exception as error:
        raise RuntimeError(message) from error
    if not callable(method):
        raise RuntimeError(message)
    return method


def validate_node_type_name(node_type_name: str) -> str:
    return _require_nonempty_text(node_type_name, "node_type_name")


def validate_node_name(name: str | None) -> str | None:
    if name is None:
        return None
    name = _require_nonempty_text(name, "name")
    if "/" in name:
        raise ValueError("name must be a node instance name, not a path: %r." % name)
    return name


def validate_parameter_name(parameter_name: str) -> str:
    return _require_nonempty_text(parameter_name, "parameter_name")


def validate_expression(expression: str) -> str:
    return _require_nonempty_text(expression, "expression")


def validate_text(text: str, field_name: str) -> str:
    if not isinstance(text, str):
        raise ValueError("%s must be a string." % field_name)
    return text


def validate_port_index(index: int, label: str, node: Any, count_method_name: str) -> int:
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError("%s must be a non-negative integer." % label)
    count = _optional_integer_call(node, count_method_name)
    if count is not None and index >= count:
        raise RuntimeError("Node %s has no %s %d." % (node_label(node), label, index))
    return index


def validate_position(position: tuple[float, float] | list[float] | None) -> tuple[float, float] | None:
    if position is None:
        return None
    if not isinstance(position, (tuple, list)) or len(position) != 2:
        raise ValueError("position must be a two-item tuple or list.")
    try:
        return (float(position[0]), float(position[1]))
    except (TypeError, ValueError) as error:
        raise ValueError("position must contain numeric x and y values.") from error


def validate_flag_value(enabled: bool, flag_name: str) -> bool:
    if not isinstance(enabled, bool):
        raise ValueError("%s must be a boolean." % flag_name)
    return enabled


def input_connection(node: Any, input_index: int) -> Any | None:
    """Return the connection at an input index, if one exists."""
    try:
        connections = node.inputConnections()
    except Exception as error:
        raise RuntimeError("Could not inspect inputs on node %s." % node_label(node)) from error
    try:
        for connection in connections:
            if connection.inputIndex() == input_index:
                return connection
    except Exception as error:
        raise RuntimeError("Could not inspect an input connection on node %s." % node_label(node)) from error
    return None


def node_label(node: Any) -> str:
    """Return a useful node path without allowing validation to fail on it."""
    try:
        path = node.path()
        if isinstance(path, str) and path:
            return path
    except Exception:
        pass
    try:
        name = node.name()
        if isinstance(name, str) and name:
            return name
    except Exception:
        pass
    return "<unknown node>"


def _require_nonempty_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string." % field_name)
    return value


def _optional_integer_call(node: Any, method_name: str) -> int | None:
    try:
        method = getattr(node, method_name)
    except Exception:
        return None
    if not callable(method):
        return None
    try:
        value = method()
    except Exception:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None
