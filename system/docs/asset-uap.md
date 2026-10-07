# Universal Asset Package (UAP) v0.1

Defined in `gbox/uap.py` (`Manifest`), with its JSON Schema in `schemas/Manifest.schema.json` and an example in `fixtures/cube_uap/`.

A package is a directory containing `manifest.json` plus `textures/`. The manifest holds meshes (positions, normals, UVs, indices, 4-joint skin), materials (with the original `source` params kept verbatim), skeleton (rest TRS, parent index), animation clips (per-bone TRS channels, events), collision meshes, a scene node hierarchy, the coordinate system, `unit_scale_m`, `confidence` per plan §12 dimension, provenance and dependencies.

The validator (`uap.validate`) checks:

- index ranges and triangle counts
- attribute counts
- finite positions
- material and texture references
- acyclic skeleton and unit quaternions
- skin weights summing to 1
- strictly increasing keyframes
- node references
- presence of provenance

Exports:

- **glTF 2.0:** embedded buffer, skin with computed inverse bind matrices, animations, and gBox metadata in `extras.gbox`.
- **OBJ:** static geometry only.
- **Not yet:** FBX, Alembic, Godot and Unreal recipes.
- ponytail: geometry is stored as inline JSON. Switch to binary buffers once packages grow past a few MB.
