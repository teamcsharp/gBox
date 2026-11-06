# Fitting a collection model onto a game skeleton: what already exists

2026-11-06. Recorded because it changes the shape of the remaining work on "zombies as Sonic/Mario/DOA": the hard part is
largely done for one title, and the pieces that did it are in the repository.

## The evidence

`~/agent-work/re4chars/sonic_sn_leon.glb` — actually `sonic_on_leon.glb` — inspected directly:

```
121 nodes, 1 mesh, 1 skin, 119 joints
joint names: b000, b001, b002, b003, b004, b026, b027, b028, b032, b033 ...
```

Those `b<id>` names are **the game's own bone numbering**, which is exactly the contract
`gbox/re4gc_models.gltf_to_bin` states for its input: "a glTF rigged to its bones (`b<id>` joint names)". So a Sonic mesh is
already fitted onto Leon's skeleton and ready for the RE4 GC writer. `sonic_src.glb` (62 joints, `node000...`) is the
unfitted source.

Also present: `gbox-pr-audit-.../re5-donor-fitting-v1/donor-poses/sa2_super_sonic-baseline.glb` — the RE5 donor-fitting
work's baseline poses, i.e. the same fitting exercise for the PS3 edition.

## The machinery that exists

| piece | where |
|---|---|
| fit a source rig onto a target's bones | `re4gc_enemies.retarget(rig, tmpl, roles=GANADO_ROLES)` |
| role table for the target | `GANADO_ROLES` (hand-written) — and now `mt_model.bone_roles()` (derived) |
| merge joints by name | `char_swap.glb_merge_joints(src, dst, merge)` |
| write a fitted GLB into the game's format | `re4gc_models.gltf_to_bin`, `swap_body` |
| write into an MTF model (Switch) | `mt_model.pack_vertices` + `replace_part` |

## What this means for the Switch titles

The correspondence problem is solved twice over: hand-written role tables exist for RE4 GC, and `mt_model.bone_roles()`
now derives them from the model's own geometry (validated: Chris height 180.7 cm, head at y 185.1, hands at x ±88.1;
Sheva 162.6 / 165.8 / ±74.7). What does not exist yet is a **fitted GLB for an RE5/RE6 Switch skeleton** — the existing
fitted artefacts are for RE4 GC (Leon's bones) and the RE5 PS3 donor-fitting baseline.

So the remaining path is concrete rather than exploratory:

1. take a collection GLB (Sonic, Mario, DOA) and derive its role bones by the same geometric rule;
2. map roles onto an RE5 Switch skeleton from `mt_model.bone_roles()` and merge the joints by name;
3. pack the fitted vertices with `mt_model.pack_vertices` (bone ids remapped to the target) and install with
   `replace_part`;
4. boot test.

Steps 1-3 use code that exists. Step 4 is the only unknown, and it has failed before for a good reason: an
approximately-correct mesh hangs the load, so the layout must be exact - which is now decoded end to end.
