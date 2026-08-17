"""Small, explicit HOM modification primitives.

There is intentionally no command parser or arbitrary execution facility here.
Each function performs one validated operation and returns its HOM result.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from .validation import (
    input_connection,
    node_label,
    require_method,
    require_deletable_node,
    require_network_parent,
    require_parameter,
    require_subnet_node,
    require_valid_node,
    validate_expression,
    validate_flag_value,
    validate_hda_parameter_interface,
    validate_node_parameter_interface,
    validate_node_parameter_interface_target,
    validate_node_name,
    validate_node_type_name,
    validate_nonnegative_integer,
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


def delete_node(node: Any) -> None:
    """Destroy one validated leaf node through Houdini's normal undo system."""
    node = require_deletable_node(node)
    destroy = require_method(node, "destroy", "Node %s cannot be deleted." % node_label(node))
    try:
        destroy()
    except Exception as error:
        raise RuntimeError("Could not delete node %s." % node_label(node)) from error


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


def set_node_comment(node: Any, comment: str) -> Any:
    """Set one node comment and return the node."""
    node = require_valid_node(node)
    comment = validate_text(comment, "comment")
    method = require_method(node, "setComment", "Node %s does not support comments." % node_label(node))
    try:
        method(comment)
    except Exception as error:
        raise RuntimeError("Could not set comment on node %s." % node_label(node)) from error
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


def add_nodes_to_network_box(network_box: Any, nodes: list[Any], fit: bool = True) -> Any:
    """Add nodes from the box's network, optionally fitting around its contents."""
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("nodes must be a non-empty list of nodes.")
    if not isinstance(fit, bool):
        raise ValueError("fit must be a boolean.")
    box_parent = _network_item_parent(network_box, "Network box")
    add_item = require_method(network_box, "addItem", "Network box does not support adding items.")
    existing_items = _network_box_items(network_box)
    for node in nodes:
        node = require_valid_node(node, "network box node")
        node_parent = _network_item_parent(node, "Node")
        if node_label(node_parent) != node_label(box_parent):
            raise RuntimeError(
                "Node %s belongs to %s, not network box parent %s."
                % (node_label(node), node_label(node_parent), node_label(box_parent))
            )
        if any(item is node or node_label(item) == node_label(node) for item in existing_items):
            continue
        try:
            add_item(node)
        except Exception as error:
            raise RuntimeError("Could not add node %s to network box." % node_label(node)) from error
        existing_items.append(node)
    if fit:
        fit_around_contents = require_method(
            network_box, "fitAroundContents", "Network box does not support fitting around contents."
        )
        try:
            fit_around_contents()
        except Exception as error:
            raise RuntimeError("Could not fit network box around its contents.") from error
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


def create_hda(
    node: Any,
    type_name: str,
    label: str,
    file_path: str,
    min_inputs: int = 0,
    max_inputs: int = 0,
) -> Any:
    """Turn an existing subnet into an HDA and disable spare-parm saving."""
    node = require_subnet_node(node)
    type_name = validate_node_type_name(type_name)
    label = validate_text(label, "label")
    if not label.strip():
        raise ValueError("label must be a non-empty string.")
    file_path = validate_text(file_path, "file_path")
    if not file_path.strip():
        raise ValueError("file_path must be a non-empty string.")
    min_inputs = validate_nonnegative_integer(min_inputs, "min_inputs")
    max_inputs = validate_nonnegative_integer(max_inputs, "max_inputs")
    if min_inputs > max_inputs:
        raise ValueError("min_inputs cannot be greater than max_inputs.")
    hou = _get_hou()
    try:
        expanded_file_path = hou.expandString(file_path)
    except Exception as error:
        raise RuntimeError("Could not expand HDA file path %r." % file_path) from error
    if not isinstance(expanded_file_path, str) or not expanded_file_path:
        raise RuntimeError("Houdini did not produce a usable HDA file path from %r." % file_path)
    try:
        Path(expanded_file_path).parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RuntimeError("Could not create HDA directory for %r." % expanded_file_path) from error
    creator = require_method(node, "createDigitalAsset", "Node %s cannot create an HDA." % node_label(node))
    try:
        hda_node = creator(
            name=type_name,
            hda_file_name=expanded_file_path,
            description=label,
            min_num_inputs=min_inputs,
            max_num_inputs=max_inputs,
        )
    except Exception as error:
        raise RuntimeError("Could not create HDA %r from node %s." % (type_name, node_label(node))) from error
    _disable_save_spare_parameters(hda_node)
    return hda_node


def install_hda_parameter_interface(node: Any, templates: list[dict[str, Any]], mode: str = "replace") -> Any:
    """Install a declarative interface on an HDA definition, never its node."""
    node = require_valid_node(node, "HDA node")
    templates = validate_hda_parameter_interface(templates, mode)
    hou = _get_hou()
    definition = _hda_definition(node)
    try:
        group = hou.ParmTemplateGroup()
        for template in templates:
            group.append(_build_parm_template(hou, template))
        definition.setParmTemplateGroup(group)
    except Exception as error:
        raise RuntimeError("Could not install the parameter interface on HDA node %s." % node_label(node)) from error
    _disable_save_spare_parameters(node, definition=definition)
    return node


def install_node_parameter_interface(node: Any, templates: list[dict[str, Any]]) -> Any:
    """Upsert declared spare parameters without replacing the node interface.

    The node's current parameter-template group is retained intact.  Submitted
    templates replace same-named spare templates and folders merge their
    children by name, preserving unrelated standard and spare parameters.
    """
    templates = validate_node_parameter_interface(templates)
    node = validate_node_parameter_interface_target(node, templates)
    hou = _get_hou()
    try:
        group = node.parmTemplateGroup()
        for template in templates:
            existing = _group_template(group, template["name"])
            built = _build_node_parm_template(hou, template, existing)
            if existing is None:
                group.append(built)
            else:
                group.replace(template["name"], built)
        node.setParmTemplateGroup(group, rename_conflicting_parms=False)
        _verify_node_parameter_interface(node, templates)
    except (RuntimeError, ValueError):
        raise
    except Exception as error:
        raise RuntimeError(
            "install_node_parameter_interface failed on %s (%s: %s)."
            % (node_label(node), type(error).__name__, error)
        ) from error
    return node


def _is_same_connection(connection: Any, source: Any, output_index: int) -> bool:
    try:
        return (
            node_label(connection.outputNode()) == node_label(source)
            and connection.outputIndex() == output_index
        )
    except Exception as error:
        raise RuntimeError("Could not inspect the existing input connection.") from error


def _network_item_parent(item: Any, role: str) -> Any:
    method = require_method(item, "parent", "%s has no parent network." % role)
    try:
        parent = method()
    except Exception as error:
        raise RuntimeError("Could not determine %s parent network." % role.lower()) from error
    return require_network_parent(parent)


def _network_box_items(network_box: Any) -> list[Any]:
    try:
        items = network_box.items()
    except AttributeError:
        return []
    except Exception as error:
        raise RuntimeError("Could not inspect network box contents.") from error
    try:
        return list(items)
    except TypeError as error:
        raise RuntimeError("Could not inspect network box contents.") from error


def _hda_definition(node: Any) -> Any:
    try:
        node_type = node.type()
        definition = node_type.definition()
    except Exception as error:
        raise RuntimeError("Could not retrieve HDA definition from node %s." % node_label(node)) from error
    if definition is None:
        raise RuntimeError("Node %s is not an HDA with an editable definition." % node_label(node))
    return definition


def _disable_save_spare_parameters(node: Any, definition: Any | None = None) -> None:
    definition = definition or _hda_definition(node)
    try:
        options = definition.options()
        options.setSaveSpareParms(False)
        definition.setOptions(options)
    except Exception as error:
        raise RuntimeError("Could not disable spare-parameter saving for HDA node %s." % node_label(node)) from error


def _build_parm_template(hou: Any, spec: dict[str, Any]) -> Any:
    kind = spec["type"]
    kwargs = _template_common_kwargs(spec, include_help=kind != "folder")
    if kind == "folder":
        children = tuple(_build_parm_template(hou, child) for child in spec["children"])
        return hou.FolderParmTemplate(spec["name"], spec["label"], parm_templates=children, **kwargs)
    if kind in {"float", "int"}:
        default = _component_default(spec, spec["components"], float if kind == "float" else int)
        numeric_kwargs = {
            "default_value": default,
            "min": spec.get("min", 0.0 if kind == "float" else 0),
            "max": spec.get("max", 10.0 if kind == "float" else 10),
            "min_is_strict": spec.get("min_is_strict", False),
            "max_is_strict": spec.get("max_is_strict", False),
            **kwargs,
        }
        template_class = hou.FloatParmTemplate if kind == "float" else hou.IntParmTemplate
        return template_class(spec["name"], spec["label"], spec["components"], **numeric_kwargs)
    if kind == "toggle":
        return hou.ToggleParmTemplate(spec["name"], spec["label"], default_value=spec.get("default", False), **kwargs)
    if kind == "string":
        return hou.StringParmTemplate(
            spec["name"], spec["label"], spec["components"],
            default_value=_component_default(spec, spec["components"], str), **kwargs
        )
    if kind == "menu":
        return hou.MenuParmTemplate(
            spec["name"], spec["label"], tuple(spec["items"]),
            menu_labels=tuple(spec.get("labels", spec["items"])),
            default_value=spec.get("default", 0), **kwargs
        )
    raise RuntimeError("Unsupported HDA parameter template type %r." % kind)


def _build_node_parm_template(hou: Any, spec: dict[str, Any], existing: Any | None = None) -> Any:
    """Build one scalar spare-parameter template, merging folder children."""
    kind = spec["type"]
    if kind == "folder":
        children = _merge_folder_children(
            hou, _folder_templates(existing), spec["children"]
        )
        folder = hou.FolderParmTemplate(spec["name"], spec["label"])
        for child in children:
            folder.addParmTemplate(child)
        return folder
    if kind in {"float", "int"}:
        numeric_kwargs = {
            "default_value": (
                (float if kind == "float" else int)(spec.get("default", 0)),
            ),
            "min": spec.get("min", 0.0 if kind == "float" else 0),
            "max": spec.get("max", 10.0 if kind == "float" else 10),
            "min_is_strict": spec.get("min_strict", False),
            "max_is_strict": spec.get("max_strict", False),
        }
        template_class = hou.FloatParmTemplate if kind == "float" else hou.IntParmTemplate
        return template_class(spec["name"], spec["label"], 1, **numeric_kwargs)
    if kind == "toggle":
        return hou.ToggleParmTemplate(
            spec["name"], spec["label"], default_value=spec.get("default", False)
        )
    if kind == "string":
        return hou.StringParmTemplate(
            spec["name"], spec["label"], 1, default_value=(spec.get("default", ""),)
        )
    if kind == "menu":
        values = tuple(item["value"] for item in spec["items"])
        labels = tuple(item["label"] for item in spec["items"])
        default = spec.get("default", values[0])
        return hou.MenuParmTemplate(
            spec["name"], spec["label"], values,
            menu_labels=labels, default_value=values.index(default),
        )
    raise RuntimeError("Unsupported node parameter template type %r." % kind)


def _merge_folder_children(hou: Any, existing: list[Any], submitted: list[dict[str, Any]]) -> list[Any]:
    merged = list(existing)
    indices = {
        name: index for index, template in enumerate(merged)
        if (name := _template_name(template)) is not None
    }
    for spec in submitted:
        index = indices.get(spec["name"])
        previous = merged[index] if index is not None else None
        built = _build_node_parm_template(hou, spec, previous)
        if index is None:
            indices[spec["name"]] = len(merged)
            merged.append(built)
        else:
            merged[index] = built
    return merged


def _group_template(group: Any, name: str) -> Any | None:
    try:
        return group.find(name)
    except Exception as error:
        raise RuntimeError("Could not inspect parameter template %r." % name) from error


def _folder_templates(template: Any | None) -> list[Any]:
    if template is None:
        return []
    try:
        templates = template.parmTemplates()
    except AttributeError:
        return []
    except Exception as error:
        raise RuntimeError("Could not inspect existing parameter folder contents.") from error
    try:
        return list(templates)
    except TypeError as error:
        raise RuntimeError("Could not inspect existing parameter folder contents.") from error


def _template_name(template: Any) -> str | None:
    try:
        name = template.name()
    except Exception:
        return None
    return name if isinstance(name, str) and name else None


def _verify_node_parameter_interface(node: Any, templates: list[dict[str, Any]]) -> None:
    """Confirm Houdini installed every requested scalar spare parameter."""
    for template in templates:
        for name in _node_interface_leaf_names(template):
            try:
                parameter = node.parm(name)
            except Exception as error:
                raise RuntimeError(
                    "Could not verify spare parameter %r on node %s."
                    % (name, node_label(node))
                ) from error
            if parameter is None:
                raise RuntimeError(
                    "Spare parameter %r was not installed on node %s."
                    % (name, node_label(node))
                )


def _node_interface_leaf_names(template: dict[str, Any]) -> list[str]:
    if template["type"] != "folder":
        return [template["name"]]
    names: list[str] = []
    for child in template["children"]:
        names.extend(_node_interface_leaf_names(child))
    return names


def _template_common_kwargs(spec: dict[str, Any], *, include_help: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    fields = (("hidden", "is_hidden"), ("tags", "tags"))
    if include_help:
        fields = (("help", "help"),) + fields
    for key, target in fields:
        if key in spec:
            kwargs[target] = spec[key]
    return kwargs


def _component_default(spec: dict[str, Any], components: int, converter: Any) -> tuple[Any, ...]:
    value = spec.get("default", "" if converter is str else 0)
    values = value if isinstance(value, (list, tuple)) else [value]
    return tuple(converter(item) for item in values)


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


def _get_hou() -> Any:
    try:
        return importlib.import_module("hou")
    except ImportError as error:
        raise RuntimeError("Houdini's hou module is not available for this action.") from error
