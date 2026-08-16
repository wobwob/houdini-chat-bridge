# Houdini Chat Bridge project rules

These rules are permanent guidance for work in this repository.

## Houdini conventions

- This project targets SideFX Houdini SOP workflows.
- Use HOM through the `hou` module for Houdini interaction.
- Never assume `/obj/geo1`.
- Avoid brittle absolute node paths.
- Validate nodes and parameters before modifying them.
- Prefer non-destructive changes.
- All modification batches must eventually support Houdini undo.
- Do not call `layoutChildren()` on existing user networks.
- New nodes should use meaningful role-based names.
- Preserve existing branches unless replacement is explicitly requested.
- Network boxes created by the system should be black when practical.
- Do not redundantly repeat SOP/operator types in node instance names where Houdini can display the node type separately.
- A finished HDA should store user controls on the HDA definition/interface, not an internal controller Null.
- High-level dimensions should drive downstream calculated implementation values, not vice versa.

## Architecture rules

- Keep Houdini inspection separate from modification.
- Keep pure data transformation/diff code independent from `hou` wherever practical.
- `context.py` reads Houdini network state.
- `geometry.py` summarizes geometry without dumping unnecessary point-level data.
- `snapshot.py` creates stable serializable snapshots.
- `diff.py` compares snapshots and must remain pure Python.
- `validation.py` validates requested operations before HOM modification.
- `actions.py` contains small controlled HOM operations.
- `executor.py` coordinates validation, undo and execution.
- `formatting.py` converts structured data into human-readable ChatGPT context.
- UI code must never contain core Houdini business logic.
- No arbitrary `exec()` implementation in the core architecture.

## Engineering rules

- Python code should be readable and typed where practical.
- Prefer dataclasses or simple structured dictionaries over opaque abstractions.
- Keep functions small.
- Fail with useful `RuntimeError`/`ValueError` messages.
- Avoid huge framework abstractions.
- Do not add dependencies unless genuinely necessary.
- Write unit tests for pure Python functionality.
- Houdini-dependent behavior should be isolated enough to smoke-test manually in Houdini.
