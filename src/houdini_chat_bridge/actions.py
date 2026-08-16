"""Small, explicit HOM modification primitives.

There is intentionally no command parser or arbitrary execution facility here.
Each function performs one validated operation and returns its HOM result.
"""

from __future__ import annotations

import importlib
from typing import Any

from .validation import (
    input_connection,
    node_label,
    require_method,
    require_network_parent,
    require_parameter,
    require_valid_node,
    validate_expression,
    validate_flag_value,
    validate_node_name,
    validate_node_type_name,
    validate_port_index,
    validate_position,
    validate_text,
)


def create_node(
    parent: Any,
    node_type_name: str,
    name: str | None = None,
    position: tuple[float, float] | list[float] | None = None,
) -> Any:
    """Create and optionally position one new node under ``parent``."""
    parent = require_network_parent(parent)
    node_type_name = validate_node_type_name(node_type_name)
    name = validate_node_name(name)
    position = validate_position(position)
    try:
        node = parent.createNode(node_type_name, name)
    except Exception as error:
        raise RuntimeError(
            "Could not create node type %r under parent %s." % (node_type_name, node_label(parent))
        ) from error
    if position is not None:
        set_position = require_method(
            node, "setPosition", "New node %s does not support positioning." % node_label(node)
        )
        try:
            set_position(position)
        except Exception as error:
            raise RuntimeError("Could not position new node %s." % node_label(node)) from error
    return node


def set_parameter(node: Any, parameter_name: str, value: Any) -> Any:
    """Set one existing parameter value and return ``node``."""
    parameter = require_parameter(node, parameter_name)
    try:
        parameter.set(value)
    except Exception as error:
        raise RuntimeError(
            "Could not set parameter %r on node %s." % (parameter_name, node_label(node))
        ) from error
    return node


def set_expression(node: Any, parameter_name: str, expression: str, language: Any = None) -> Any:
    """Set one parameter expression, optionally with a HOM expression language."""
    parameter = require_parameter(node, parameter_name)
    expression = validate_expression(expression)
    try:
        if language is None:
            parameter.setExpression(expression)
        else:
            parameter.setExpression(expression, language=language)
    except Exception as error:
        raise RuntimeError(
            "Could not set expression on parameter %r of node %s." % (parameter_name, node_label(node))
        ) from error
    return node


def connect_nodes(
    source: Any,
    target: Any,
    input_index: int = 0,
    output_index: int = 0,
    replace_existing: bool = False,
) -> Any:
    """Connect ``source`` to an available target input without replacing by default."""
    source = require_valid_node(source, "source node")
    target = require_valid_node(target, "target node")
    input_index = validate_port_index(input_index, "input index", target, "inputCount")
    output_index = validate_port_index(output_index, "output index", source, "outputCount")
    if not isinstance(replace_existing, bool):
        raise ValueError("replace_existing must be a boolean.")

    existing = input_connection(target, input_index)
    if existing is not None:
        if _is_same_connection(existing, source, output_index):
            return target
        if not replace_existing:
            raise RuntimeError(
                "Target node %s input %d is already connected; pass replace_existing=True to replace it."
                % (node_label(target), input_index)
            )
    set_input = require_method(target, "setInput", "Node %s does not support input connections." % node_label(target))
    try:
        set_input(input_index, source, output_index)
    except Exception as error:
        raise RuntimeError(
            "Could not connect %s output %d to %s input %d."
            % (node_label(source), output_index, node_label(target), input_index)
        ) from error
    return target


def disconnect_input(target: Any, input_index: int = 0) -> Any:
    """Explicitly disconnect an occupied target input and return ``target``."""
    target = require_valid_node(target, "target node")
    input_index = validate_port_index(input_index, "input index", target, "inputCount")
    if input_connection(target, input_index) is None:
        raise RuntimeError("Target node %s input %d is not connected." % (node_label(target), input_index))
    set_input = require_method(target, "setInput", "Node %s does not support input connections." % node_label(target))
    try:
        set_input(input_index, None)
    except Exception as error:
        raise RuntimeError("Could not disconnect node %s input %d." % (node_label(target), input_index)) from error
    return target


def set_display_flag(node: Any, enabled: bool) -> Any:
    """Set one node's display flag and return the node."""
    node = require_valid_node(node)
    enabled = validate_flag_value(enabled, "enabled")
    method = require_method(node, "setDisplayFlag", "Node %s does not support display flags." % node_label(node))
    try:
        method(enabled)
    except Exception as error:
        raise RuntimeError("Could not set display flag on node %s." % node_label(node)) from error
    return node


def set_render_flag(node: Any, enabled: bool) -> Any:
    """Set one node's render flag and return the node."""
    node = require_valid_node(node)
    enabled = validate_flag_value(enabled, "enabled")
    method = require_method(node, "setRenderFlag", "Node %s does not support render flags." % node_label(node))
    try:
        method(enabled)
    except Exception as error:
        raise RuntimeError("Could not set render flag on node %s." % node_label(node)) from error
    return node


def create_network_box(parent: Any, name: str | None = None, comment: str | None = None) -> Any:
    """Create a black network box by default, without moving existing nodes."""
    parent = require_network_parent(parent)
    name = validate_node_name(name)
    if comment is not None:
        comment = validate_text(comment, "comment")
    creator = require_method(
        parent, "createNetworkBox", "Parent node %s cannot create network boxes." % node_label(parent)
    )
    try:
        network_box = creator(name)
    except Exception as error:
        raise RuntimeError("Could not create a network box under parent %s." % node_label(parent)) from error
    if comment is not None:
        set_comment = require_method(network_box, "setComment", "New network box does not support comments.")
        try:
            set_comment(comment)
        except Exception as error:
            raise RuntimeError("Could not set comment on the new network box.") from error
    _set_black_if_supported(network_box)
    return network_box


def create_sticky_note(parent: Any, text: str, name: str | None = None) -> Any:
    """Create one sticky note under ``parent`` and return it."""
    parent = require_network_parent(parent)
    text = validate_text(text, "text")
    name = validate_node_name(name)
    creator = require_method(
        parent, "createStickyNote", "Parent node %s cannot create sticky notes." % node_label(parent)
    )
    try:
        note = creator()
    except Exception as error:
        raise RuntimeError("Could not create a sticky note under parent %s." % node_label(parent)) from error
    set_text = require_method(note, "setText", "New sticky note does not support text.")
    try:
        set_text(text)
    except Exception as error:
        raise RuntimeError("Could not set text on the new sticky note.") from error
    if name is not None:
        set_name = require_method(note, "setName", "New sticky note does not support names.")
        try:
            set_name(name)
        except Exception as error:
            raise RuntimeError("Could not name the new sticky note %r." % name) from error
    return note


def _is_same_connection(connection: Any, source: Any, output_index: int) -> bool:
    try:
        return (
            node_label(connection.outputNode()) == node_label(source)
            and connection.outputIndex() == output_index
        )
    except Exception as error:
        raise RuntimeError("Could not inspect the existing input connection.") from error


def _set_black_if_supported(network_box: Any) -> None:
    try:
        set_color = getattr(network_box, "setColor")
    except Exception:
        return
    if not callable(set_color):
        return
    try:
        set_color(_black_color())
    except Exception as error:
        raise RuntimeError("Could not set the new network box color to black.") from error


def _black_color() -> Any:
    try:
        hou = importlib.import_module("hou")
        return hou.Color((0.0, 0.0, 0.0))
    except ImportError:
        # Useful for HOM-shaped test doubles; real Houdini supplies hou.Color.
        return (0.0, 0.0, 0.0)
