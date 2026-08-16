"""Validated batch execution for the explicit Houdini action set."""

from __future__ import annotations

import importlib
from typing import Any, Mapping

from . import actions
from .diff import compare_snapshots
from .snapshot import snapshot_network
from .validation import (
    input_connection,
    node_label,
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


DEFAULT_LABEL = "Houdini Chat Bridge batch"
_SUPPORTED_ACTIONS = {
    "create_node",
    "set_parameter",
    "set_expression",
    "connect_nodes",
    "disconnect_input",
    "set_display_flag",
    "set_render_flag",
    "create_network_box",
    "create_sticky_note",
}


def execute_operations(
    parent: Any,
    operations: list[Mapping[str, Any]],
    *,
    label: str = DEFAULT_LABEL,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate and execute supported operations as one Houdini undo group.

    ``parent`` defines the direct-network snapshot scope. On a runtime failure,
    completed actions are not hidden or automatically reverted; they remain in
    the one undo group and the returned diff describes the partial result.
    """
    requested, input_error = _normalise_operations(operations)
    result = _result(label, requested)
    if input_error is not None:
        result["errors"].append(_error_record(None, None, input_error))
        return result
    if not isinstance(label, str) or not label.strip():
        result["errors"].append(_error_record(None, None, "label must be a non-empty string."))
        return result
    if not isinstance(dry_run, bool):
        result["errors"].append(_error_record(None, None, "dry_run must be a boolean."))
        return result

    try:
        require_valid_node(parent, "snapshot parent")
        hou = _get_hou()
    except (RuntimeError, ValueError) as error:
        result["errors"].append(_error_record(None, None, str(error)))
        return result

    plans, validation_errors = _validate_batch(hou, requested)
    if validation_errors:
        result["errors"].extend(validation_errors)
        return result
    if dry_run:
        result["success"] = True
        return result

    try:
        before = snapshot_network(parent)
    except Exception as error:
        result["errors"].append(_error_record(None, None, "Could not capture before snapshot: %s" % error))
        return result

    try:
        with _undo_group(hou, label):
            for plan in plans:
                try:
                    _dispatch(plan, hou)
                except Exception as error:
                    result["errors"].append(_error_record(plan["index"], plan["action"], str(error)))
                    break
                result["operations_completed"].append(
                    {"index": plan["index"], "action": plan["action"]}
                )
    except Exception as error:
        if not result["errors"]:
            result["errors"].append(_error_record(None, None, "Could not execute undo group: %s" % error))

    try:
        after = snapshot_network(parent)
        result["diff"] = compare_snapshots(before, after)
    except Exception as error:
        result["errors"].append(_error_record(None, None, "Could not capture result diff: %s" % error))
        return result

    result["success"] = not result["errors"] and len(result["operations_completed"]) == len(plans)
    return result


def _normalise_operations(operations: Any) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(operations, list):
        return [], "operations must be a list of structured operation mappings."
    normalised: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping):
            return [], "Operation %d must be a mapping." % index
        normalised.append(dict(operation))
    return normalised, None


def _result(label: Any, requested: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "success": False,
        "label": label,
        "operations_requested": requested,
        "operations_completed": [],
        "diff": _empty_diff(),
        "errors": [],
    }


def _empty_diff() -> dict[str, list[Any]]:
    return {
        "created_nodes": [],
        "deleted_nodes": [],
        "modified_nodes": [],
        "parameter_changes": [],
        "connection_changes": [],
        "flag_changes": [],
    }


def _validate_batch(hou: Any, operations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plans: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        action = operation.get("action")
        try:
            _validate_operation(hou, operation)
        except (RuntimeError, ValueError) as error:
            errors.append(_error_record(index, action if isinstance(action, str) else None, str(error)))
        else:
            plans.append({"index": index, "action": action, "operation": operation})
    return plans, errors


def _validate_operation(hou: Any, operation: Mapping[str, Any]) -> None:
    action = operation.get("action")
    if not isinstance(action, str) or action not in _SUPPORTED_ACTIONS:
        raise ValueError("Unsupported action %r." % action)

    if action == "create_node":
        _check_fields(operation, action, {"parent", "node_type_name"}, {"name", "position"})
        require_network_parent(_node_from_operation(hou, operation, "parent"))
        validate_node_type_name(operation["node_type_name"])
        validate_node_name(operation.get("name"))
        validate_position(operation.get("position"))
    elif action == "set_parameter":
        _check_fields(operation, action, {"node", "parameter", "value"}, set())
        require_parameter(_node_from_operation(hou, operation, "node"), operation["parameter"])
    elif action == "set_expression":
        _check_fields(operation, action, {"node", "parameter", "expression"}, {"language"})
        require_parameter(_node_from_operation(hou, operation, "node"), operation["parameter"])
        validate_expression(operation["expression"])
        _expression_language(hou, operation.get("language"))
    elif action == "connect_nodes":
        _check_fields(operation, action, {"source", "target"}, {"input_index", "output_index", "replace_existing"})
        source = require_valid_node(_node_from_operation(hou, operation, "source"), "source node")
        target = require_valid_node(_node_from_operation(hou, operation, "target"), "target node")
        validate_port_index(operation.get("input_index", 0), "input index", target, "inputCount")
        validate_port_index(operation.get("output_index", 0), "output index", source, "outputCount")
        if not isinstance(operation.get("replace_existing", False), bool):
            raise ValueError("replace_existing must be a boolean.")
        existing = input_connection(target, operation.get("input_index", 0))
        if existing is not None and not operation.get("replace_existing", False):
            if not _matches_connection(existing, source, operation.get("output_index", 0)):
                raise RuntimeError(
                    "Target node %s input %d is already connected; pass replace_existing=True to replace it."
                    % (node_label(target), operation.get("input_index", 0))
                )
    elif action == "disconnect_input":
        _check_fields(operation, action, {"target"}, {"input_index"})
        target = require_valid_node(_node_from_operation(hou, operation, "target"), "target node")
        validate_port_index(operation.get("input_index", 0), "input index", target, "inputCount")
        if input_connection(target, operation.get("input_index", 0)) is None:
            raise RuntimeError(
                "Target node %s input %d is not connected."
                % (node_label(target), operation.get("input_index", 0))
            )
    elif action in {"set_display_flag", "set_render_flag"}:
        _check_fields(operation, action, {"node", "enabled"}, set())
        require_valid_node(_node_from_operation(hou, operation, "node"))
        validate_flag_value(operation["enabled"], "enabled")
    elif action == "create_network_box":
        _check_fields(operation, action, {"parent"}, {"name", "comment"})
        require_network_parent(_node_from_operation(hou, operation, "parent"))
        validate_node_name(operation.get("name"))
        if "comment" in operation:
            validate_text(operation["comment"], "comment")
    elif action == "create_sticky_note":
        _check_fields(operation, action, {"parent", "text"}, {"name"})
        require_network_parent(_node_from_operation(hou, operation, "parent"))
        validate_text(operation["text"], "text")
        validate_node_name(operation.get("name"))


def _dispatch(plan: Mapping[str, Any], hou: Any) -> Any:
    operation = plan["operation"]
    action = plan["action"]
    if action == "create_node":
        return actions.create_node(
            _node_from_operation(hou, operation, "parent"),
            operation["node_type_name"],
            name=operation.get("name"),
            position=operation.get("position"),
        )
    if action == "set_parameter":
        return actions.set_parameter(
            _node_from_operation(hou, operation, "node"), operation["parameter"], operation["value"]
        )
    if action == "set_expression":
        return actions.set_expression(
            _node_from_operation(hou, operation, "node"),
            operation["parameter"],
            operation["expression"],
            language=_expression_language(hou, operation.get("language")),
        )
    if action == "connect_nodes":
        return actions.connect_nodes(
            _node_from_operation(hou, operation, "source"),
            _node_from_operation(hou, operation, "target"),
            input_index=operation.get("input_index", 0),
            output_index=operation.get("output_index", 0),
            replace_existing=operation.get("replace_existing", False),
        )
    if action == "disconnect_input":
        return actions.disconnect_input(
            _node_from_operation(hou, operation, "target"), operation.get("input_index", 0)
        )
    if action == "set_display_flag":
        return actions.set_display_flag(_node_from_operation(hou, operation, "node"), operation["enabled"])
    if action == "set_render_flag":
        return actions.set_render_flag(_node_from_operation(hou, operation, "node"), operation["enabled"])
    if action == "create_network_box":
        return actions.create_network_box(
            _node_from_operation(hou, operation, "parent"),
            name=operation.get("name"),
            comment=operation.get("comment"),
        )
    if action == "create_sticky_note":
        return actions.create_sticky_note(
            _node_from_operation(hou, operation, "parent"),
            operation["text"],
            name=operation.get("name"),
        )
    raise RuntimeError("Unsupported action %r." % action)


def _check_fields(
    operation: Mapping[str, Any], action: str, required: set[str], optional: set[str]
) -> None:
    missing = sorted(required - set(operation))
    if missing:
        raise ValueError("Action %r is missing required field(s): %s." % (action, ", ".join(missing)))
    unknown = sorted(set(operation) - {"action"} - required - optional)
    if unknown:
        raise ValueError("Action %r contains unsupported field(s): %s." % (action, ", ".join(unknown)))


def _node_from_operation(hou: Any, operation: Mapping[str, Any], field_name: str) -> Any:
    path = operation.get(field_name)
    if not isinstance(path, str) or not path:
        raise ValueError("Action field %r must be a non-empty node path string." % field_name)
    try:
        node = hou.node(path)
    except Exception as error:
        raise RuntimeError("Could not resolve %s node path %r." % (field_name, path)) from error
    if node is None:
        raise RuntimeError("%s node does not exist: %s." % (field_name.capitalize(), path))
    return node


def _expression_language(hou: Any, language: Any) -> Any:
    if language is None:
        return None
    if not isinstance(language, str) or not language:
        raise ValueError("language must be a non-empty Houdini expression-language name.")
    try:
        return getattr(hou.exprLanguage, language)
    except Exception as error:
        raise ValueError("Unsupported Houdini expression language %r." % language) from error


def _matches_connection(connection: Any, source: Any, output_index: int) -> bool:
    try:
        return (
            node_label(connection.outputNode()) == node_label(source)
            and connection.outputIndex() == output_index
        )
    except Exception as error:
        raise RuntimeError("Could not inspect the existing input connection.") from error


def _undo_group(hou: Any, label: str) -> Any:
    try:
        return hou.undos.group(label)
    except Exception as error:
        raise RuntimeError("Could not start Houdini undo group %r." % label) from error


def _get_hou() -> Any:
    try:
        return importlib.import_module("hou")
    except ImportError as error:
        raise RuntimeError("Houdini's hou module is not available; operations cannot be executed.") from error


def _error_record(index: int | None, action: str | None, message: str) -> dict[str, Any]:
    return {"operation_index": index, "action": action, "message": message}
