"""Validated batch execution for the explicit Houdini action set.

The executor accepts existing-node paths scoped to one network and symbolic
references to nodes created earlier in the same batch. It never interprets
arbitrary Python or dispatches arbitrary function names.
"""

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
    """Run supported operations in one undo group and return their scene diff.

    ``parent`` is the only execution scope. Existing-node references must be
    direct children of it. A batch-local node reference has the form
    ``{"ref": "id"}``, where ``id`` was declared by an earlier
    ``create_node`` operation. A runtime failure leaves completed work in the
    one undoable Houdini group and reports the partial diff.
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
        parent = require_network_parent(parent)
        hou = _get_hou()
    except (RuntimeError, ValueError) as error:
        result["errors"].append(_error_record(None, None, str(error)))
        return result

    plans, validation_errors = _preflight_batch(hou, parent, requested)
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

    created: dict[str, Any] = {}
    try:
        with _undo_group(hou, label):
            for plan in plans:
                try:
                    _dispatch(plan, hou, parent, created)
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


def _preflight_batch(
    hou: Any, parent: Any, operations: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate structure, IDs, scoped existing nodes, and known current state."""
    declared_ids = _declared_ids(operations)
    available_ids: set[str] = set()
    seen_ids: set[str] = set()
    plans: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, operation in enumerate(operations):
        action = operation.get("action")
        try:
            created_id = _preflight_operation(
                hou, parent, operation, declared_ids, available_ids, seen_ids
            )
        except (RuntimeError, ValueError) as error:
            errors.append(_error_record(index, action if isinstance(action, str) else None, str(error)))
            continue
        if created_id is not None:
            available_ids.add(created_id)
            seen_ids.add(created_id)
        plans.append({"index": index, "action": action, "operation": operation})
    return plans, errors


def _declared_ids(operations: list[dict[str, Any]]) -> set[str]:
    return {
        operation["id"]
        for operation in operations
        if operation.get("action") == "create_node" and isinstance(operation.get("id"), str)
    }


def _preflight_operation(
    hou: Any,
    parent: Any,
    operation: Mapping[str, Any],
    declared_ids: set[str],
    available_ids: set[str],
    seen_ids: set[str],
) -> str | None:
    action = operation.get("action")
    if not isinstance(action, str) or action not in _SUPPORTED_ACTIONS:
        raise ValueError("Unsupported action %r." % action)

    if action == "create_node":
        _check_fields(operation, action, {"node_type_name"}, {"id", "name", "position"})
        validate_node_type_name(operation["node_type_name"])
        validate_node_name(operation.get("name"))
        validate_position(operation.get("position"))
        created_id = _operation_id(operation)
        if created_id is not None and created_id in seen_ids:
            raise ValueError("Duplicate create_node id %r." % created_id)
        return created_id

    if action == "set_parameter":
        _check_fields(operation, action, {"node", "parameter", "value"}, set())
        node = _preflight_target(hou, parent, operation["node"], "node", declared_ids, available_ids)
        if node is not None:
            require_parameter(node, operation["parameter"])
        return None

    if action == "set_expression":
        _check_fields(operation, action, {"node", "parameter", "expression"}, {"language"})
        node = _preflight_target(hou, parent, operation["node"], "node", declared_ids, available_ids)
        if node is not None:
            require_parameter(node, operation["parameter"])
        validate_expression(operation["expression"])
        _expression_language(hou, operation.get("language"))
        return None

    if action == "connect_nodes":
        _check_fields(operation, action, {"source", "target"}, {"input_index", "output_index", "replace_existing"})
        source = _preflight_target(hou, parent, operation["source"], "source", declared_ids, available_ids)
        target = _preflight_target(hou, parent, operation["target"], "target", declared_ids, available_ids)
        _validate_connection_fields(operation, source, target)
        return None

    if action == "disconnect_input":
        _check_fields(operation, action, {"target"}, {"input_index"})
        target = _preflight_target(hou, parent, operation["target"], "target", declared_ids, available_ids)
        _validate_input_index(operation.get("input_index", 0), target)
        if target is not None and input_connection(target, operation.get("input_index", 0)) is None:
            raise RuntimeError(
                "Target node %s input %d is not connected."
                % (node_label(target), operation.get("input_index", 0))
            )
        return None

    if action in {"set_display_flag", "set_render_flag"}:
        _check_fields(operation, action, {"node", "enabled"}, set())
        _preflight_target(hou, parent, operation["node"], "node", declared_ids, available_ids)
        validate_flag_value(operation["enabled"], "enabled")
        return None

    if action == "create_network_box":
        _check_fields(operation, action, set(), {"name", "comment"})
        validate_node_name(operation.get("name"))
        if "comment" in operation:
            validate_text(operation["comment"], "comment")
        return None

    if action == "create_sticky_note":
        _check_fields(operation, action, {"text"}, {"name"})
        validate_text(operation["text"], "text")
        validate_node_name(operation.get("name"))
        return None

    raise RuntimeError("Unsupported action %r." % action)


def _preflight_target(
    hou: Any,
    parent: Any,
    reference: Any,
    field_name: str,
    declared_ids: set[str],
    available_ids: set[str],
) -> Any | None:
    reference_id = _reference_id(reference)
    if reference_id is not None:
        if reference_id not in declared_ids:
            raise ValueError("Unknown symbolic reference %r in field %r." % (reference_id, field_name))
        if reference_id not in available_ids:
            raise ValueError(
                "Forward symbolic reference %r in field %r; create it earlier in the batch."
                % (reference_id, field_name)
            )
        return None
    return _scoped_node_from_path(hou, parent, reference, field_name)


def _dispatch(plan: Mapping[str, Any], hou: Any, parent: Any, created: dict[str, Any]) -> Any:
    operation = plan["operation"]
    action = plan["action"]
    if action == "create_node":
        node = actions.create_node(
            parent,
            operation["node_type_name"],
            name=operation.get("name"),
            position=operation.get("position"),
        )
        created_id = _operation_id(operation)
        if created_id is not None:
            created[created_id] = node
        return node
    if action == "set_parameter":
        return actions.set_parameter(
            _runtime_target(hou, parent, created, operation["node"], "node"),
            operation["parameter"],
            operation["value"],
        )
    if action == "set_expression":
        return actions.set_expression(
            _runtime_target(hou, parent, created, operation["node"], "node"),
            operation["parameter"],
            operation["expression"],
            language=_expression_language(hou, operation.get("language")),
        )
    if action == "connect_nodes":
        return actions.connect_nodes(
            _runtime_target(hou, parent, created, operation["source"], "source"),
            _runtime_target(hou, parent, created, operation["target"], "target"),
            input_index=operation.get("input_index", 0),
            output_index=operation.get("output_index", 0),
            replace_existing=operation.get("replace_existing", False),
        )
    if action == "disconnect_input":
        return actions.disconnect_input(
            _runtime_target(hou, parent, created, operation["target"], "target"),
            operation.get("input_index", 0),
        )
    if action == "set_display_flag":
        return actions.set_display_flag(
            _runtime_target(hou, parent, created, operation["node"], "node"), operation["enabled"]
        )
    if action == "set_render_flag":
        return actions.set_render_flag(
            _runtime_target(hou, parent, created, operation["node"], "node"), operation["enabled"]
        )
    if action == "create_network_box":
        return actions.create_network_box(parent, name=operation.get("name"), comment=operation.get("comment"))
    if action == "create_sticky_note":
        return actions.create_sticky_note(parent, operation["text"], name=operation.get("name"))
    raise RuntimeError("Unsupported action %r." % action)


def _runtime_target(hou: Any, parent: Any, created: Mapping[str, Any], reference: Any, field_name: str) -> Any:
    reference_id = _reference_id(reference)
    if reference_id is not None:
        try:
            node = created[reference_id]
        except KeyError as error:
            raise RuntimeError("Symbolic reference %r is unavailable at execution time." % reference_id) from error
        return require_valid_node(node, "%s node" % field_name)
    return _scoped_node_from_path(hou, parent, reference, field_name)


def _validate_connection_fields(operation: Mapping[str, Any], source: Any | None, target: Any | None) -> None:
    input_index = operation.get("input_index", 0)
    output_index = operation.get("output_index", 0)
    _validate_input_index(input_index, target)
    _validate_output_index(output_index, source)
    if not isinstance(operation.get("replace_existing", False), bool):
        raise ValueError("replace_existing must be a boolean.")
    if source is None or target is None:
        return
    existing = input_connection(target, input_index)
    if existing is not None and not operation.get("replace_existing", False):
        if not _matches_connection(existing, source, output_index):
            raise RuntimeError(
                "Target node %s input %d is already connected; pass replace_existing=True to replace it."
                % (node_label(target), input_index)
            )


def _validate_input_index(index: Any, target: Any | None) -> None:
    if target is None:
        _validate_nonnegative_index(index, "input index")
    else:
        validate_port_index(index, "input index", target, "inputCount")


def _validate_output_index(index: Any, source: Any | None) -> None:
    if source is None:
        _validate_nonnegative_index(index, "output index")
    else:
        validate_port_index(index, "output index", source, "outputCount")


def _validate_nonnegative_index(index: Any, label: str) -> None:
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError("%s must be a non-negative integer." % label)


def _scoped_node_from_path(hou: Any, parent: Any, path: Any, field_name: str) -> Any:
    if not isinstance(path, str) or not path:
        raise ValueError(
            "Action field %r must be an existing scoped node path string or {'ref': 'id'}." % field_name
        )
    try:
        node = hou.node(path)
    except Exception as error:
        raise RuntimeError("Could not resolve %s node path %r." % (field_name, path)) from error
    if node is None:
        raise RuntimeError("%s node does not exist: %s." % (field_name.capitalize(), path))
    require_valid_node(node, "%s node" % field_name)
    _require_scope(node, parent, field_name)
    return node


def _require_scope(node: Any, parent: Any, field_name: str) -> None:
    try:
        node_parent = node.parent()
    except Exception as error:
        raise RuntimeError("Could not determine parent of %s node %s." % (field_name, node_label(node))) from error
    if node_label(node_parent) != node_label(parent):
        raise RuntimeError(
            "%s node %s is outside execution scope %s."
            % (field_name.capitalize(), node_label(node), node_label(parent))
        )


def _operation_id(operation: Mapping[str, Any]) -> str | None:
    if "id" not in operation:
        return None
    value = operation["id"]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("create_node id must be a non-empty string.")
    return value


def _reference_id(reference: Any) -> str | None:
    if not isinstance(reference, Mapping):
        return None
    if set(reference) != {"ref"}:
        raise ValueError("Symbolic references must contain only {'ref': 'id'}.")
    value = reference.get("ref")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Symbolic reference id must be a non-empty string.")
    return value


def _check_fields(
    operation: Mapping[str, Any], action: str, required: set[str], optional: set[str]
) -> None:
    missing = sorted(required - set(operation))
    if missing:
        raise ValueError("Action %r is missing required field(s): %s." % (action, ", ".join(missing)))
    unknown = sorted(set(operation) - {"action"} - required - optional)
    if unknown:
        raise ValueError("Action %r contains unsupported field(s): %s." % (action, ", ".join(unknown)))


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
