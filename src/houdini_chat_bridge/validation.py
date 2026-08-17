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
    try:
        is_network = getattr(parent, "isNetwork", None)
        if callable(is_network) and is_network() is False:
            raise RuntimeError("Parent node %s is not a network." % node_label(parent))
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError("Could not validate whether parent node %s is a network." % node_label(parent)) from error
    require_method(parent, "createNode", "Parent node %s cannot create nodes." % node_label(parent))
    return parent


def require_subnet_node(node: Any) -> Any:
    """Validate the deliberately narrow source type accepted for HDA creation."""
    node = require_network_parent(node)
    try:
        node_type = node.type()
        type_name = node_type.name()
    except Exception as error:
        raise RuntimeError("Could not determine node type for HDA source %s." % node_label(node)) from error
    if type_name != "subnet":
        raise RuntimeError("HDA source node %s must be a subnet, not %r." % (node_label(node), type_name))
    return node


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


def validate_nonnegative_integer(value: Any, field_name: str) -> int:
    """Validate a non-negative integer without accepting booleans."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("%s must be a non-negative integer." % field_name)
    return value


def validate_hda_parameter_interface(templates: Any, mode: Any) -> list[dict[str, Any]]:
    """Validate the intentionally small, serializable HDA interface schema.

    The returned dictionaries are copies so execution never mutates the
    operation data supplied by a caller. Template construction itself remains
    in ``actions.py`` because it requires HOM classes.
    """
    if mode != "replace":
        raise ValueError("HDA parameter interface mode must be 'replace'.")
    if not isinstance(templates, list):
        raise ValueError("HDA parameter interface templates must be a list.")
    names: set[str] = set()
    return [_validate_hda_template(template, names) for template in templates]


def validate_node_parameter_interface(templates: Any) -> list[dict[str, Any]]:
    """Validate a spare-parameter interface for an ordinary Houdini node.

    This schema deliberately differs from the HDA-definition schema: it is a
    small scalar-control format suited to temporary controller nodes.
    """
    prefix = "install_node_parameter_interface"
    if not isinstance(templates, list):
        raise ValueError("%s: templates must be an array." % prefix)
    names: set[str] = set()
    return [_validate_node_template(template, names) for template in templates]


def require_node_parameter_interface(node: Any) -> Any:
    """Validate that an ordinary node can safely carry spare parameters."""
    node = require_valid_node(node, "parameter-interface node")
    require_method(
        node,
        "parmTemplateGroup",
        "Node %s does not support parameter-template groups." % node_label(node),
    )
    require_method(
        node,
        "setParmTemplateGroup",
        "Node %s cannot install parameter-template groups." % node_label(node),
    )
    return node


def validate_node_parameter_interface_target(
    node: Any, templates: list[dict[str, Any]]
) -> Any:
    """Ensure submitted spare names do not replace built-in parameters."""
    node = require_node_parameter_interface(node)
    for template in templates:
        for name in _node_template_names(template):
            try:
                parameter = node.parm(name)
                is_spare = getattr(parameter, "isSpare", None) if parameter is not None else None
                if callable(is_spare) and is_spare() is False:
                    raise RuntimeError(
                        "Parameter %r on node %s is built in and cannot be replaced."
                        % (name, node_label(node))
                    )
            except RuntimeError:
                raise
            except Exception as error:
                raise RuntimeError(
                    "Could not inspect parameter %r on node %s." % (name, node_label(node))
                ) from error
    return node


def _validate_node_template(template: Any, names: set[str]) -> dict[str, Any]:
    prefix = "install_node_parameter_interface"
    if not isinstance(template, dict):
        raise ValueError("%s: each template must be an object." % prefix)
    kind = template.get("type")
    if kind not in {"folder", "float", "int", "toggle", "string", "menu"}:
        raise ValueError("%s: unsupported template type %r." % (prefix, kind))
    name = _node_template_text(template.get("name"), "parameter name")
    label = _node_template_text(template.get("label"), "parameter label")
    if name in names:
        raise ValueError('%s: duplicate parameter name "%s".' % (prefix, name))
    names.add(name)

    allowed = {"type", "name", "label"}
    if kind == "folder":
        allowed.add("children")
    elif kind in {"float", "int"}:
        allowed.update({"default", "min", "max", "min_strict", "max_strict"})
    elif kind in {"toggle", "string"}:
        allowed.add("default")
    elif kind == "menu":
        allowed.update({"items", "default"})
    unknown = sorted(set(template) - allowed)
    if unknown:
        raise ValueError("%s: template %r has unsupported field(s): %s." % (
            prefix, name, ", ".join(unknown),
        ))

    result = dict(template)
    if kind == "folder":
        children = result.get("children")
        if not isinstance(children, list):
            raise ValueError("%s: folder %r children must be an array." % (prefix, name))
        result["children"] = [_validate_node_template(child, names) for child in children]
        return result
    if kind == "float":
        _validate_node_numeric_template(result, name, integer=False)
    elif kind == "int":
        _validate_node_numeric_template(result, name, integer=True)
    elif kind == "toggle" and "default" in result and not isinstance(result["default"], bool):
        raise ValueError("%s: toggle %r default must be a boolean." % (prefix, name))
    elif kind == "string" and "default" in result and not isinstance(result["default"], str):
        raise ValueError("%s: string %r default must be a string." % (prefix, name))
    elif kind == "menu":
        _validate_node_menu_template(result, name)
    return result


def _node_template_names(template: dict[str, Any]) -> list[str]:
    names = [template["name"]]
    if template["type"] == "folder":
        for child in template["children"]:
            names.extend(_node_template_names(child))
    return names


def _validate_node_numeric_template(template: dict[str, Any], name: str, *, integer: bool) -> None:
    prefix = "install_node_parameter_interface"
    type_name = "integer" if integer else "numeric"
    for field in ("default", "min", "max"):
        if field not in template:
            continue
        value = template[field]
        valid = (
            isinstance(value, int) and not isinstance(value, bool)
            if integer else isinstance(value, (int, float)) and not isinstance(value, bool)
        )
        if not valid:
            raise ValueError("%s: %s %r %s must be %s." % (
                prefix, template["type"], name, field, type_name,
            ))
    for field in ("min_strict", "max_strict"):
        if field in template and not isinstance(template[field], bool):
            raise ValueError("%s: %s %r %s must be a boolean." % (
                prefix, template["type"], name, field,
            ))
    if "min" in template and "max" in template and template["min"] > template["max"]:
        raise ValueError("%s: %s %r min cannot be greater than max." % (
            prefix, template["type"], name,
        ))


def _validate_node_menu_template(template: dict[str, Any], name: str) -> None:
    prefix = "install_node_parameter_interface"
    items = template.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("%s: menu %r items must be a non-empty array." % (prefix, name))
    values: set[str] = set()
    validated_items: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("%s: menu %r items must be objects." % (prefix, name))
        if set(item) != {"value", "label"}:
            raise ValueError("%s: menu %r items require only value and label." % (prefix, name))
        value = _node_template_text(item.get("value"), "menu value")
        label = _node_template_text(item.get("label"), "menu item label")
        if value in values:
            raise ValueError('%s: menu %r has duplicate value "%s".' % (prefix, name, value))
        values.add(value)
        validated_items.append({"value": value, "label": label})
    template["items"] = validated_items
    if "default" in template:
        default = template["default"]
        if not isinstance(default, str) or default not in values:
            raise ValueError('%s: menu "%s" default "%s" is not one of its items.' % (
                prefix, name, default,
            ))


def _node_template_text(value: Any, field_name: str) -> str:
    prefix = "install_node_parameter_interface"
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s: %s must be a non-empty string." % (prefix, field_name))
    return value


def _validate_hda_template(template: Any, names: set[str]) -> dict[str, Any]:
    if not isinstance(template, dict):
        raise ValueError("Each HDA parameter template must be a mapping.")
    kind = template.get("type")
    if kind not in {"folder", "float", "int", "toggle", "string", "menu"}:
        raise ValueError("Unsupported HDA parameter template type %r." % kind)
    name = _require_nonempty_text(template.get("name"), "HDA parameter template name")
    label = _require_nonempty_text(template.get("label"), "HDA parameter template label")
    if name in names:
        raise ValueError("Duplicate HDA parameter template name %r." % name)
    names.add(name)

    allowed = {"type", "name", "label", "help", "hidden", "tags"}
    if kind == "folder":
        allowed.add("children")
    elif kind in {"float", "int"}:
        allowed.update({"components", "default", "min", "max", "min_is_strict", "max_is_strict"})
    elif kind == "toggle":
        allowed.add("default")
    elif kind == "string":
        allowed.update({"components", "default"})
    elif kind == "menu":
        allowed.update({"items", "labels", "default"})
    unknown = sorted(set(template) - allowed)
    if unknown:
        raise ValueError("HDA parameter template %r has unsupported field(s): %s." % (name, ", ".join(unknown)))

    result = dict(template)
    if "help" in result:
        validate_text(result["help"], "HDA parameter template help")
        if kind == "folder":
            raise ValueError("Folder template %r does not support help text." % name)
    if "hidden" in result and not isinstance(result["hidden"], bool):
        raise ValueError("HDA parameter template hidden must be a boolean.")
    if "tags" in result:
        tags = result["tags"]
        if not isinstance(tags, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in tags.items()):
            raise ValueError("HDA parameter template tags must map strings to strings.")

    if kind == "folder":
        children = result.get("children", [])
        if not isinstance(children, list):
            raise ValueError("Folder template %r children must be a list." % name)
        result["children"] = [_validate_hda_template(child, names) for child in children]
        return result

    if kind in {"float", "int", "string"}:
        components = result.get("components", 1)
        if not isinstance(components, int) or isinstance(components, bool) or components < 1:
            raise ValueError("HDA parameter template components must be a positive integer.")
        result["components"] = components
        if "default" in result:
            _validate_default_components(result["default"], components, name)

    if kind in {"float", "int"}:
        default_values = result.get("default", 0)
        default_values = default_values if isinstance(default_values, (list, tuple)) else [default_values]
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in default_values):
            raise ValueError("HDA parameter template %r default must be numeric." % name)
        for bound in ("min", "max"):
            if bound in result and (not isinstance(result[bound], (int, float)) or isinstance(result[bound], bool)):
                raise ValueError("HDA parameter template %s must be numeric." % bound)
        for strict in ("min_is_strict", "max_is_strict"):
            if strict in result and not isinstance(result[strict], bool):
                raise ValueError("HDA parameter template %s must be a boolean." % strict)
        if "min" in result and "max" in result and result["min"] > result["max"]:
            raise ValueError("HDA parameter template min cannot be greater than max.")
    elif kind == "toggle" and "default" in result and not isinstance(result["default"], bool):
        raise ValueError("Toggle template %r default must be a boolean." % name)
    elif kind == "menu":
        items = result.get("items")
        if not isinstance(items, list) or not items or not all(isinstance(item, str) and item for item in items):
            raise ValueError("Menu template %r items must be a non-empty list of strings." % name)
        labels = result.get("labels")
        if labels is not None and (not isinstance(labels, list) or not all(isinstance(item, str) for item in labels)):
            raise ValueError("Menu template %r labels must be a list of strings." % name)
        if "default" in result and (not isinstance(result["default"], int) or isinstance(result["default"], bool)):
            raise ValueError("Menu template %r default must be an integer index." % name)
        if "default" in result and not 0 <= result["default"] < len(items):
            raise ValueError("Menu template %r default is outside its items." % name)
    elif kind == "string" and "default" in result:
        values = result["default"] if isinstance(result["default"], (list, tuple)) else [result["default"]]
        if not all(isinstance(value, str) for value in values):
            raise ValueError("String template %r default must be string value(s)." % name)
    return result


def _validate_default_components(value: Any, components: int, name: str) -> None:
    values = value if isinstance(value, (list, tuple)) else [value]
    if len(values) != components:
        raise ValueError("HDA parameter template %r default must contain %d value(s)." % (name, components))


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
