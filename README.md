# Houdini Chat Bridge

Houdini Chat Bridge is a reusable Python framework for allowing an external
conversational AI to inspect and safely modify SideFX Houdini SOP networks.

## Current scope

This repository currently implements Milestone 2: structured, read-only
Houdini network inspection plus stable snapshots and pure-Python diffs. It
intentionally does **not** implement OpenAI APIs, MCP, LLM or chat integration,
network requests, modification operations, or a Houdini Python Panel.

`context.py` exposes inspection of individual nodes, selections, upstream
networks, and the current network-editor context. `snapshot.py` converts
inspection into stable network data, while `diff.py` compares snapshots without
Houdini and formats the resulting change report. `formatting.py` turns context
data into readable text without querying Houdini itself.

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

The planned Python Panel lives under `houdini/python_panels/`, but it must
remain a thin UI layer and is not implemented yet.

## Development workflow

1. Work on pure data models, snapshots, diffs, validation, and formatting in
   `src/houdini_chat_bridge/`.
2. Add unit tests for pure Python behavior in `tests/` and run them without
   Houdini installed.
3. Keep HOM-dependent code isolated, then manually smoke-test it in Houdini.
4. Use `scripts/install_dev.py` as the future entry point for local Houdini
   development installation; it is intentionally a placeholder in this
   scaffold.

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

Milestone 2 is complete. Scene modification remains out of scope.
