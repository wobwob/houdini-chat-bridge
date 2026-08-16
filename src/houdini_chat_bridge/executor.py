"""Validated batch execution for the explicit Houdini action set.

The executor plans symbolic references and scope before entering Houdini's undo
group. HOM actions remain small functions in :mod:`actions`; this module owns
batch-local object identities, structural validation, and dispatch only.
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
    require_subnet_node,
    require_valid_node,
    validate_expression,
    validate_flag_value,
    validate_hda_parameter_interface,
    validate_node_name,
    validate_node_type_name,
    validate_nonnegative_integer,
    validate_port_index,
    validate_position,
    validate_text,
)


DEFAULT_LABEL = "Houdini Chat Bridge batch"
_SUPPORTED_ACTIONS = {
    "create_node", "set_parameter", "set_expression", "connect_nodes",
    "disconnect_input", "set_display_flag", "set_render_flag", "set_node_comment",
    "create_network_box", "add_nodes_to_network_box", "create_sticky_note",
    "create_hda", "install_hda_parameter_interface",
}
_NODE_SYMBOL = "node"
_NETWORK_BOX_SYMBOL = "network_box"


def execute_operations(
    parent: Any, operations: list[Mapping[str, Any]], *, label: str = DEFAULT_LABEL,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run supported operations in one undo group and return a structured diff.

    Existing node paths must resolve to the supplied execution parent or one
    of its descendants. Batch-local references use ``{"ref": "id"}`` and may
    only refer to an object created by an earlier operation. ``create_node``
    declares node IDs; ``create_network_box`` declares network-box IDs. The
    IDs share one namespace and never reconstruct an object from a requested
    Houdini name.
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
        before = snapshot_network(parent, recursive=True)
    except Exception as error:
        result["errors"].append(_error_record(None, None, "Could not capture before snapshot: %s" % error))
        return result

    symbols: dict[str, dict[str, Any]] = {}
    try:
        with _undo_group(hou, label):
            for plan in plans:
                try:
                    _dispatch(plan, hou, parent, symbols)
                except Exception as error:
                    result["errors"].append(_error_record(plan["index"], plan["action"], str(error)))
                    break
                result["operations_completed"].append({"index": plan["index"], "action": plan["action"]})
    except Exception as error:
        if not result["errors"]:
            result["errors"].append(_error_record(None, None, "Could not execute undo group: %s" % error))
    try:
        after = snapshot_network(parent, recursive=True)
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
    return {"success": False, "label": label, "operations_requested": requested,
            "operations_completed": [], "diff": _empty_diff(), "errors": []}


def _empty_diff() -> dict[str, list[Any]]:
    return {"created_nodes": [], "deleted_nodes": [], "modified_nodes": [],
            "parameter_changes": [], "connection_changes": [], "flag_changes": [],
            "comment_changes": []}


def _preflight_batch(hou: Any, parent: Any, operations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate batch structure and all state already knowable before execution."""
    declared = _declared_symbols(operations)
    available: dict[str, str] = {}
    seen: set[str] = set()
    plans: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        action = operation.get("action")
        try:
            created_symbol = _preflight_operation(hou, parent, operation, declared, available, seen)
        except (RuntimeError, ValueError) as error:
            errors.append(_error_record(index, action if isinstance(action, str) else None, str(error)))
            continue
        if created_symbol is not None:
            symbol_id, kind = created_symbol
            available[symbol_id] = kind
            seen.add(symbol_id)
        plans.append({"index": index, "action": action, "operation": operation})
    return plans, errors


def _declared_symbols(operations: list[dict[str, Any]]) -> dict[str, str]:
    declared: dict[str, str] = {}
    for operation in operations:
        kind = _created_symbol_kind(operation.get("action"))
        value = operation.get("id")
        if kind is not None and isinstance(value, str) and value.strip() and value not in declared:
            declared[value] = kind
    return declared


def _created_symbol_kind(action: Any) -> str | None:
    if action == "create_node":
        return _NODE_SYMBOL
    if action == "create_network_box":
        return _NETWORK_BOX_SYMBOL
    return None


def _preflight_operation(hou: Any, parent: Any, operation: Mapping[str, Any], declared: Mapping[str, str], available: Mapping[str, str], seen: set[str]) -> tuple[str, str] | None:
    action = operation.get("action")
    if not isinstance(action, str) or action not in _SUPPORTED_ACTIONS:
        raise ValueError("Unsupported action %r." % action)
    if action == "create_node":
        _check_fields(operation, action, {"node_type_name"}, {"id", "name", "position", "parent"})
        validate_node_type_name(operation["node_type_name"])
        validate_node_name(operation.get("name"))
        validate_position(operation.get("position"))
        _preflight_parent(hou, parent, operation.get("parent"), declared, available)
        return _created_symbol(operation, _NODE_SYMBOL, seen)
    if action == "set_parameter":
        _check_fields(operation, action, {"node", "parameter", "value"}, set())
        node = _preflight_node_target(hou, parent, operation["node"], "node", declared, available)
        if node is not None:
            require_parameter(node, operation["parameter"])
        return None
    if action == "set_expression":
        _check_fields(operation, action, {"node", "parameter", "expression"}, {"language"})
        node = _preflight_node_target(hou, parent, operation["node"], "node", declared, available)
        if node is not None:
            require_parameter(node, operation["parameter"])
        validate_expression(operation["expression"])
        _expression_language(hou, operation.get("language"))
        return None
    if action == "connect_nodes":
        _check_fields(operation, action, {"source", "target"}, {"input_index", "output_index", "replace_existing"})
        source = _preflight_node_target(hou, parent, operation["source"], "source", declared, available)
        target = _preflight_node_target(hou, parent, operation["target"], "target", declared, available)
        _validate_connection_fields(operation, source, target)
        return None
    if action == "disconnect_input":
        _check_fields(operation, action, {"target"}, {"input_index"})
        target = _preflight_node_target(hou, parent, operation["target"], "target", declared, available)
        _validate_input_index(operation.get("input_index", 0), target)
        if target is not None and input_connection(target, operation.get("input_index", 0)) is None:
            raise RuntimeError("Target node %s input %d is not connected." % (node_label(target), operation.get("input_index", 0)))
        return None
    if action in {"set_display_flag", "set_render_flag"}:
        _check_fields(operation, action, {"node", "enabled"}, set())
        _preflight_node_target(hou, parent, operation["node"], "node", declared, available)
        validate_flag_value(operation["enabled"], "enabled")
        return None
    if action == "set_node_comment":
        _check_fields(operation, action, {"node", "comment"}, set())
        _preflight_node_target(hou, parent, operation["node"], "node", declared, available)
        validate_text(operation["comment"], "comment")
        return None
    if action == "create_network_box":
        _check_fields(operation, action, set(), {"id", "name", "comment", "parent"})
        validate_node_name(operation.get("name"))
        if "comment" in operation:
            validate_text(operation["comment"], "comment")
        _preflight_parent(hou, parent, operation.get("parent"), declared, available)
        return _created_symbol(operation, _NETWORK_BOX_SYMBOL, seen)
    if action == "add_nodes_to_network_box":
        _check_fields(operation, action, {"box", "nodes"}, {"fit"})
        _preflight_network_box_target(hou, parent, operation["box"], "box", declared, available)
        nodes = operation["nodes"]
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("nodes must be a non-empty list of node references.")
        for index, node_reference in enumerate(nodes):
            _preflight_node_target(hou, parent, node_reference, "nodes[%d]" % index, declared, available)
        if "fit" in operation and not isinstance(operation["fit"], bool):
            raise ValueError("fit must be a boolean.")
        return None
    if action == "create_sticky_note":
        _check_fields(operation, action, {"text"}, {"name", "parent"})
        validate_text(operation["text"], "text")
        validate_node_name(operation.get("name"))
        _preflight_parent(hou, parent, operation.get("parent"), declared, available)
        return None
    if action == "create_hda":
        _check_fields(operation, action, {"node", "type_name", "label", "file_path"}, {"min_inputs", "max_inputs"})
        node = _preflight_node_target(hou, parent, operation["node"], "node", declared, available, require_network=True)
        if node is not None:
            require_subnet_node(node)
        validate_node_type_name(operation["type_name"])
        _validate_nonempty_text_field(operation["label"], "label")
        _validate_nonempty_text_field(operation["file_path"], "file_path")
        _validate_hda_input_counts(operation.get("min_inputs", 0), operation.get("max_inputs", 0))
        return None
    if action == "install_hda_parameter_interface":
        _check_fields(operation, action, {"node", "templates"}, {"mode"})
        _preflight_node_target(hou, parent, operation["node"], "node", declared, available)
        validate_hda_parameter_interface(operation["templates"], operation.get("mode", "replace"))
        return None
    raise RuntimeError("Unsupported action %r." % action)


def _created_symbol(operation: Mapping[str, Any], kind: str, seen: set[str]) -> tuple[str, str] | None:
    if "id" not in operation:
        return None
    symbol_id = _operation_id(operation, kind)
    if symbol_id in seen:
        raise ValueError("Duplicate batch object id %r." % symbol_id)
    return symbol_id, kind


def _preflight_parent(hou: Any, root: Any, reference: Any, declared: Mapping[str, str], available: Mapping[str, str]) -> Any | None:
    if reference is None:
        return root
    return _preflight_node_target(hou, root, reference, "parent", declared, available, require_network=True)


def _preflight_node_target(hou: Any, root: Any, reference: Any, field_name: str, declared: Mapping[str, str], available: Mapping[str, str], *, require_network: bool = False) -> Any | None:
    reference_id = _reference_id(reference)
    if reference_id is not None:
        _preflight_symbol(reference_id, _NODE_SYMBOL, field_name, declared, available)
        return None
    node = _scoped_node_from_path(hou, root, reference, field_name)
    if require_network:
        require_network_parent(node)
    return node


def _preflight_network_box_target(hou: Any, root: Any, reference: Any, field_name: str, declared: Mapping[str, str], available: Mapping[str, str]) -> Any | None:
    reference_id = _reference_id(reference)
    if reference_id is not None:
        _preflight_symbol(reference_id, _NETWORK_BOX_SYMBOL, field_name, declared, available)
        return None
    return _scoped_network_box_by_name(root, reference, field_name)


def _preflight_symbol(reference_id: str, expected_kind: str, field_name: str, declared: Mapping[str, str], available: Mapping[str, str]) -> None:
    declared_kind = declared.get(reference_id)
    if declared_kind is None:
        raise ValueError("Unknown symbolic reference %r in field %r." % (reference_id, field_name))
    if declared_kind != expected_kind:
        raise ValueError("Symbolic reference %r in field %r is a %s, not a %s." % (reference_id, field_name, declared_kind, expected_kind))
    if reference_id not in available:
        raise ValueError("Forward symbolic reference %r in field %r; create it earlier in the batch." % (reference_id, field_name))


def _dispatch(plan: Mapping[str, Any], hou: Any, root: Any, symbols: dict[str, dict[str, Any]]) -> Any:
    operation = plan["operation"]
    action = plan["action"]
    if action == "create_node":
        node = actions.create_node(_runtime_parent(hou, root, symbols, operation.get("parent")), operation["node_type_name"], name=operation.get("name"), position=operation.get("position"))
        _store_symbol(symbols, operation, _NODE_SYMBOL, node)
        return node
    if action == "set_parameter":
        return actions.set_parameter(_runtime_node(hou, root, symbols, operation["node"], "node"), operation["parameter"], operation["value"])
    if action == "set_expression":
        return actions.set_expression(_runtime_node(hou, root, symbols, operation["node"], "node"), operation["parameter"], operation["expression"], language=_expression_language(hou, operation.get("language")))
    if action == "connect_nodes":
        return actions.connect_nodes(_runtime_node(hou, root, symbols, operation["source"], "source"), _runtime_node(hou, root, symbols, operation["target"], "target"), input_index=operation.get("input_index", 0), output_index=operation.get("output_index", 0), replace_existing=operation.get("replace_existing", False))
    if action == "disconnect_input":
        return actions.disconnect_input(_runtime_node(hou, root, symbols, operation["target"], "target"), operation.get("input_index", 0))
    if action == "set_display_flag":
        return actions.set_display_flag(_runtime_node(hou, root, symbols, operation["node"], "node"), operation["enabled"])
    if action == "set_render_flag":
        return actions.set_render_flag(_runtime_node(hou, root, symbols, operation["node"], "node"), operation["enabled"])
    if action == "set_node_comment":
        return actions.set_node_comment(_runtime_node(hou, root, symbols, operation["node"], "node"), operation["comment"])
    if action == "create_network_box":
        box = actions.create_network_box(_runtime_parent(hou, root, symbols, operation.get("parent")), name=operation.get("name"), comment=operation.get("comment"))
        _store_symbol(symbols, operation, _NETWORK_BOX_SYMBOL, box)
        return box
    if action == "add_nodes_to_network_box":
        return actions.add_nodes_to_network_box(_runtime_network_box(hou, root, symbols, operation["box"], "box"), [_runtime_node(hou, root, symbols, reference, "nodes[%d]" % index) for index, reference in enumerate(operation["nodes"])], fit=operation.get("fit", True))
    if action == "create_sticky_note":
        return actions.create_sticky_note(_runtime_parent(hou, root, symbols, operation.get("parent")), operation["text"], name=operation.get("name"))
    if action == "create_hda":
        source = _runtime_node(hou, root, symbols, operation["node"], "node")
        hda_node = actions.create_hda(source, operation["type_name"], operation["label"], operation["file_path"], min_inputs=operation.get("min_inputs", 0), max_inputs=operation.get("max_inputs", 0))
        _replace_node_symbol(symbols, operation["node"], hda_node)
        return hda_node
    if action == "install_hda_parameter_interface":
        return actions.install_hda_parameter_interface(_runtime_node(hou, root, symbols, operation["node"], "node"), operation["templates"], mode=operation.get("mode", "replace"))
    raise RuntimeError("Unsupported action %r." % action)


def _store_symbol(symbols: dict[str, dict[str, Any]], operation: Mapping[str, Any], kind: str, value: Any) -> None:
    if "id" in operation:
        symbols[_operation_id(operation, kind)] = {"kind": kind, "value": value}


def _replace_node_symbol(symbols: dict[str, dict[str, Any]], reference: Any, hda_node: Any) -> None:
    reference_id = _reference_id(reference)
    if reference_id is not None:
        symbols[reference_id]["value"] = hda_node


def _runtime_parent(hou: Any, root: Any, symbols: Mapping[str, Mapping[str, Any]], reference: Any) -> Any:
    if reference is None:
        return root
    return require_network_parent(_runtime_node(hou, root, symbols, reference, "parent"))


def _runtime_node(hou: Any, root: Any, symbols: Mapping[str, Mapping[str, Any]], reference: Any, field_name: str) -> Any:
    reference_id = _reference_id(reference)
    if reference_id is not None:
        return _runtime_symbol(symbols, reference_id, _NODE_SYMBOL, field_name)
    return _scoped_node_from_path(hou, root, reference, field_name)


def _runtime_network_box(hou: Any, root: Any, symbols: Mapping[str, Mapping[str, Any]], reference: Any, field_name: str) -> Any:
    reference_id = _reference_id(reference)
    if reference_id is not None:
        return _runtime_symbol(symbols, reference_id, _NETWORK_BOX_SYMBOL, field_name)
    return _scoped_network_box_by_name(root, reference, field_name)


def _runtime_symbol(symbols: Mapping[str, Mapping[str, Any]], reference_id: str, expected_kind: str, field_name: str) -> Any:
    entry = symbols.get(reference_id)
    if entry is None or entry.get("kind") != expected_kind:
        raise RuntimeError("Symbolic reference %r is unavailable as a %s at execution time." % (reference_id, expected_kind))
    value = entry.get("value")
    if expected_kind == _NODE_SYMBOL:
        return require_valid_node(value, "%s node" % field_name)
    if value is None:
        raise RuntimeError("Symbolic network box reference %r is invalid." % reference_id)
    return value


def _validate_connection_fields(operation: Mapping[str, Any], source: Any | None, target: Any | None) -> None:
    input_index, output_index = operation.get("input_index", 0), operation.get("output_index", 0)
    _validate_input_index(input_index, target)
    _validate_output_index(output_index, source)
    if not isinstance(operation.get("replace_existing", False), bool):
        raise ValueError("replace_existing must be a boolean.")
    if source is None or target is None:
        return
    existing = input_connection(target, input_index)
    if existing is not None and not operation.get("replace_existing", False) and not _matches_connection(existing, source, output_index):
        raise RuntimeError("Target node %s input %d is already connected; pass replace_existing=True to replace it." % (node_label(target), input_index))


def _validate_hda_input_counts(min_inputs: Any, max_inputs: Any) -> None:
    min_inputs = validate_nonnegative_integer(min_inputs, "min_inputs")
    max_inputs = validate_nonnegative_integer(max_inputs, "max_inputs")
    if min_inputs > max_inputs:
        raise ValueError("min_inputs cannot be greater than max_inputs.")


def _validate_nonempty_text_field(value: Any, field_name: str) -> str:
    value = validate_text(value, field_name)
    if not value.strip():
        raise ValueError("%s must be a non-empty string." % field_name)
    return value


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


def _scoped_node_from_path(hou: Any, root: Any, path: Any, field_name: str) -> Any:
    if not isinstance(path, str) or not path:
        raise ValueError("Action field %r must be an existing scoped node path string or {'ref': 'id'}." % field_name)
    try:
        node = hou.node(path)
    except Exception as error:
        raise RuntimeError("Could not resolve %s node path %r." % (field_name, path)) from error
    if node is None:
        raise RuntimeError("%s node does not exist: %s." % (field_name.capitalize(), path))
    require_valid_node(node, "%s node" % field_name)
    _require_scope(node, root, field_name)
    return node


def _scoped_network_box_by_name(root: Any, name: Any, field_name: str) -> Any:
    if not isinstance(name, str) or not name:
        raise ValueError("Action field %r must be a network box name string or {'ref': 'id'}." % field_name)
    try:
        boxes = root.networkBoxes()
    except Exception as error:
        raise RuntimeError("Could not inspect network boxes in execution scope %s." % node_label(root)) from error
    matches = [box for box in boxes if _network_box_name(box) == name]
    if not matches:
        raise RuntimeError("Network box %r does not exist in execution scope %s." % (name, node_label(root)))
    if len(matches) > 1:
        raise RuntimeError("Network box name %r is ambiguous in execution scope %s." % (name, node_label(root)))
    return matches[0]


def _network_box_name(network_box: Any) -> str | None:
    try:
        value = network_box.name()
    except TypeError:
        value = getattr(network_box, "name", None)
    except Exception:
        value = None
    return value if isinstance(value, str) else None


def _require_scope(node: Any, root: Any, field_name: str) -> None:
    """Require a node to be the root or a descendant, without path prefixes."""
    seen: set[int] = set()
    current = node
    while current is not None:
        if current is root or node_label(current) == node_label(root):
            return
        marker = id(current)
        if marker in seen:
            break
        seen.add(marker)
        try:
            current = current.parent()
        except Exception as error:
            raise RuntimeError("Could not determine parent of %s node %s." % (field_name, node_label(node))) from error
    raise RuntimeError("%s node %s is outside execution scope %s." % (field_name.capitalize(), node_label(node), node_label(root)))


def _operation_id(operation: Mapping[str, Any], kind: str) -> str:
    value = operation.get("id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s id must be a non-empty string." % kind.replace("_", " "))
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


def _check_fields(operation: Mapping[str, Any], action: str, required: set[str], optional: set[str]) -> None:
    missing = sorted(required - set(operation))
    if missing:
        raise ValueError("Action %r is missing required field(s): %s." % (action, ", ".join(missing)))
    unknown = sorted(set(operation) - {"action"} - required - optional)
    if unknown:
        raise ValueError("Action %r contains unsupported field(s): %s." % (action, ", ".join(unknown)))


def _expression_language(hou: Any, language: Any) -> Any:
    if language is None:
        return None
    if not isinstance(language, str) or not language.strip():
        raise ValueError("language must be a non-empty Houdini expression-language name.")
    name = {"hscript": "Hscript", "python": "Python"}.get(language.lower())
    if name is None:
        raise ValueError("Unsupported Houdini expression language %r." % language)
    try:
        return getattr(hou.exprLanguage, name)
    except Exception as error:
        raise ValueError("Unsupported Houdini expression language %r." % language) from error


def _matches_connection(connection: Any, source: Any, output_index: int) -> bool:
    try:
        return node_label(connection.outputNode()) == node_label(source) and connection.outputIndex() == output_index
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
