# Houdini Chat Bridge

Houdini Chat Bridge is a reusable Python framework for allowing an external
conversational AI to inspect and safely modify SideFX Houdini SOP networks.

## Current scope

This repository currently implements Milestone 5: structured inspection,
stable snapshots, pure-Python diffs, validated Houdini actions, operation
batches with automatic diffs and one Houdini undo group, plus an initial
PySide6 Python Panel. It intentionally does **not** implement OpenAI APIs,
MCP, LLM or chat integration, network requests, arbitrary execution, or a chat
client.

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
5. In **PATCH EXECUTION**, enter a JSON list using real paths from the current
   network, for example:

   ```json
   [
     {
       "action": "set_parameter",
       "node": "/your/network/POLE",
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

Milestone 5 is complete. UI remains deliberately limited to inspection and
explicit operation-batch execution.
