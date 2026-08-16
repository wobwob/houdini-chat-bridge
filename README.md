# Houdini Chat Bridge

Houdini Chat Bridge is a reusable Python framework for allowing an external
conversational AI to inspect and safely modify SideFX Houdini SOP networks.

## Current scope

This repository currently implements structured inspection, recursive stable
snapshots, pure-Python diffs, validated Houdini actions, operation batches with
automatic diffs and one Houdini undo group, procedural-network construction,
and initial HDA creation/interface support. It includes an initial PySide6
Python Panel. It intentionally does **not** implement OpenAI APIs, MCP, LLM or
chat integration, network requests, arbitrary execution, or a chat client.

`context.py` exposes inspection of individual nodes, selections, upstream
networks, and the current network-editor context. `snapshot.py` converts
inspection into stable network data, while `diff.py` compares snapshots without
Houdini and formats the resulting change report. `validation.py` checks HOM
targets before `actions.py` performs a small, explicit action set.
`executor.py` validates and runs supported batches inside a single undo group.
`formatting.py` turns context data into readable text without querying Houdini
itself.

`panel.py` is only a PySide6 presentation layer. It renders inspection data,
copies already-structured context, decodes manually entered operation JSON, and
delegates validation/execution to `executor.py`. It contains no bridge business
logic and never executes clipboard contents automatically.

## Operation batches, symbolic objects, and scope

The executor accepts only explicit, documented action schemas. It supports an
existing node path string and a batch-local reference object:

- An existing node path string, such as `"/your/network/EXISTING"`.
- A batch-local reference object, such as `{"ref": "pole"}`.

`create_node` declares a node ID and `create_network_box` declares a
network-box ID. All IDs share one namespace. The executor stores the HOM object
returned by the creation action, so later operations never reconstruct a path
from a requested instance name. A reference is type-checked: a network-box ID
cannot be used where a node is required.

`create_node`, `create_network_box`, and `create_sticky_note` take an optional
`parent`. Omit it to use the `parent` passed to `execute_operations()`, pass an
existing in-scope network path, or pass a node reference created earlier in the
batch. Existing paths are restricted to that root network or its descendants;
the bridge cannot reach unrelated networks through arbitrary paths.

References must name a unique object ID declared earlier in the same batch.
Duplicate, unknown, and forward references are rejected before scene
modification. Preflight checks validate batch structure, IDs, scope, and
currently knowable scene state. Validation that depends on newly created nodes
occurs when its operation executes inside the batch's one undo group.

Supported actions are:

- `create_node`, `set_parameter`, `set_expression`, `connect_nodes`,
  `disconnect_input`, `set_display_flag`, `set_render_flag`, and
  `set_node_comment`.
- `create_network_box`, `add_nodes_to_network_box`, and `create_sticky_note`.
- `create_hda` and `install_hda_parameter_interface`.

The HDA parameter interface accepts `mode: "replace"` and a declarative
`templates` list. Supported template types are `folder`, `float`, `int`,
`toggle`, `string`, and `menu`; templates support human-facing `label` and
`help` text as well as their appropriate defaults and numeric/menu metadata.
The interface is installed on the HDA definition, never as spare parameters on
the HDA node or an internal controller Null. The HDA actions disable saving
spare parameters on the definition.

Here is a complete procedural/HDA batch. It creates a subnet, builds its
contents using symbolic parents, comments a node, groups the internal nodes in
a black network box, then converts the subnet into an HDA with two public
controls:

```json
[
  {
    "action": "create_node",
    "id": "asset",
    "node_type_name": "subnet",
    "name": "ROOF_BUILDER"
  },
  {
    "action": "create_node",
    "id": "body",
    "parent": {"ref": "asset"},
    "node_type_name": "box",
    "name": "BODY"
  },
  {
    "action": "create_node",
    "id": "taper",
    "parent": {"ref": "asset"},
    "node_type_name": "polyextrude",
    "name": "TAPER"
  },
  {
    "action": "connect_nodes",
    "source": {"ref": "body"},
    "target": {"ref": "taper"}
  },
  {
    "action": "set_node_comment",
    "node": {"ref": "taper"},
    "comment": "Tapers the roof body."
  },
  {
    "action": "create_network_box",
    "id": "roof_nodes",
    "parent": {"ref": "asset"},
    "name": "roof_nodes",
    "comment": "Roof construction"
  },
  {
    "action": "add_nodes_to_network_box",
    "box": {"ref": "roof_nodes"},
    "nodes": [{"ref": "body"}, {"ref": "taper"}],
    "fit": true
  },
  {
    "action": "create_hda",
    "node": {"ref": "asset"},
    "type_name": "hcb::roof_builder::1.0",
    "label": "Roof Builder",
    "file_path": "$HIP/otls/roof_builder.hda",
    "min_inputs": 0,
    "max_inputs": 1
  },
  {
    "action": "install_hda_parameter_interface",
    "node": {"ref": "asset"},
    "mode": "replace",
    "templates": [
      {
        "type": "folder",
        "name": "main",
        "label": "Main",
        "children": [
          {"type": "float", "name": "roof_height", "label": "Roof Height", "default": 4.0, "min": 0.0, "help": "Overall roof height."},
          {"type": "toggle", "name": "add_cap", "label": "Add Cap", "default": true, "help": "Add a cap to the roof."}
        ]
      }
    ]
  }
]
```

`set_parameter`, `set_expression`, `connect_nodes`, `disconnect_input`,
`set_display_flag`, `set_render_flag`, and `set_node_comment` all accept node
references. `add_nodes_to_network_box` accepts a network-box reference and a
list of node references. Network boxes are black by default where Houdini
supports colors; membership is idempotent and `fit` defaults to `true`.

Snapshots now recursively include descendants for executor before/after diffs,
and retain node comments as deliberate scene state. `diff.py` remains pure
Python and reports comment changes alongside parameter, connection, and flag
changes.

## Intended architecture

| Module | Responsibility |
| --- | --- |
| `context.py` | Read Houdini network state through HOM. |
| `geometry.py` | Summarize geometry without unnecessary point-level dumps. |
| `snapshot.py` | Create stable, serializable snapshots. |
| `diff.py` | Compare snapshots as pure Python. |
| `validation.py` | Validate requested operations before HOM changes. |
| `actions.py` | Provide small, controlled HOM operations. |
| `executor.py` | Coordinate validation, Houdini undo, and execution. |
| `formatting.py` | Turn structured data into human-readable AI context. |

The Python Panel definition lives under `houdini/python_panels/` and remains a
thin UI layer.

## Houdini development installation

Houdini packages let a checkout register its `houdini/` assets through
`HOUDINI_PATH`. The development installer writes one package file into the
chosen Houdini preference directory; it does not copy source files or panel
assets.

From this repository, with Houdini closed, run:

```bash
python scripts/install_dev.py --prefs-dir "$HOME/houdini20.5"
```

Replace the preference path with the directory for the Houdini version you use.
Alternatively, if `HOUDINI_USER_PREF_DIR` is already set, run:

```bash
python scripts/install_dev.py
```

The generated `packages/houdini_chat_bridge_dev.json` sets
`HOUDINI_CHAT_BRIDGE_ROOT`, prepends `src/` to `PYTHONPATH`, and adds
`houdini/` to Houdini's path. Restart Houdini after installation so it can load
the package and discover the `.pypanel` definition.

## Python Panel smoke test

1. Start Houdini and create or open any SOP network; no default node path is
   required.
2. Add a Python Panel pane and select **Houdini Chat Bridge** from its
   interface menu.
3. Select one or more SOP nodes and click **Refresh**. Confirm the current
   network, selection, and display node are shown.
4. Click **Copy Selected Context** and **Copy Upstream Context** with a node
   selected; paste the results into a text editor to confirm they are readable.
5. In **PATCH EXECUTION**, enter a JSON list. Use symbolic references for
   nodes or network boxes created earlier in the same batch, for example:

   ```json
   [
     {
       "action": "create_node",
       "id": "pole",
       "node_type_name": "tube",
       "name": "POLE"
     },
     {
       "action": "set_parameter",
       "node": {"ref": "pole"},
       "parameter": "height",
       "value": 5.0
     }
   ]
   ```

6. Click **Validate** or **Dry Run** first and confirm the scene is unchanged.
   Then click **Execute**, inspect **LAST RESULT**, and use Houdini Undo once to
   revert the entire batch.
7. Trigger an invalid parameter or malformed JSON and confirm the status plus
   collapsible **Technical Details** show the error.

All Houdini inspection and mutation calls occur from normal PySide6 button
handlers on Houdini's main Qt thread. Long-running HOM operations are not moved
to worker threads because Houdini UI/HOM access must stay on that thread.

## Development workflow

1. Work on pure data models, snapshots, diffs, validation, and formatting in
   `src/houdini_chat_bridge/`.
2. Add unit tests for pure Python behavior in `tests/` and run them without
   Houdini installed.
3. Keep HOM-dependent code isolated, then manually smoke-test it in Houdini.
4. Register the checkout with Houdini using `scripts/install_dev.py`, then
   restart Houdini to discover panel definitions.

Houdini provides the `hou` module. It is not a normal PyPI dependency, so this
project must not require Houdini to be available when running pure Python unit
tests. Modules that use `hou` should import it only within Houdini-facing code
or otherwise make its dependency explicit and isolatable.

## Repository layout

```text
src/houdini_chat_bridge/  Core framework package
houdini/python_panels/    Future Houdini Python Panel assets
scripts/                  Development utilities
tests/                    Pure Python unit tests
```

The UI remains deliberately limited to inspection and explicit operation-batch
execution; procedural/HDA functionality belongs in the bridge modules, not the
panel.
