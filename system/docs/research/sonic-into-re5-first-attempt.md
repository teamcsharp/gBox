# Sonic into an RE5 enemy slot: built, loaded, and not drawn

2026-11-06. First genuine attempt at the operator's "zombies as Sonic" ask. The mesh is written into the game's Majini model
and the game loads it — but it **renders nothing**, and this records exactly how far it got and what that implies.

## What was built (and works structurally)

`gbox/mtf_import.py` writes an arbitrary mesh into an MTF model: one part, its own vertex buffer in format `0x18b0faa8`
(position, bone id, normal, tangent, uv) and its own strip index buffer (one triangle per strip, `0xFFFF` between them). The
target's bones, groups, materials and header tail are kept, and the bounds are rewritten to cover the new mesh — the box
matters because the short positions are quantised against it.

`rebuild_mod` gained `mesh_count` / `face_count`, so a model can be restructured to a different number of parts. That change
also caught a real regression in my own code: new records must start from the existing bytes, because the record fields the
writer does not name (one of which the vertex decoder needs) were being zeroed.

Measured, SA2 Sonic -> RE5 `uEm10` (the Majini a No Mercy round spawns):

```
source     4107 vertices, 1369 triangles, POSITION/NORMAL/TEXCOORD_0/JOINTS_0/WEIGHTS_0, 62 joints
mapping    62 joints -> 18 of the target's 92 bones; Sonic's head joint -> bone 90 (the target's head)
target     pawn\em\em10\model\em1000 and its _low/_mid LODs (the arc holds 341 parts per entry)
result     each LOD rebuilt as 1 part, valid, bounds y -1.7 .. 185.6 cm, 80,840,652-byte arc
```

Loaded into the game as its own LayeredFS build (`sonic-test`), RE5 launched on Eden with `mod: sonic-test`,
`boot_failures: []`, `boot_attempts: 1`.

## What happened on screen

**Six minutes of pure black frames** (mean 0.0, std 0.0) while the session reported running. The process is alive and the
archive is accepted, but the engine never draws. That is the same shape as the earlier white-screen failures: no crash, no
error, no picture.

## What that implies

The model went from **341 parts to 1**. Everything the engine knows about that mesh is per part — part records point at
material indices, the groups block describes how parts group, and the index buffer addresses the whole model. A single part
with a fresh index buffer is internally consistent (it re-parses, `split_valid()` passes, every index is in range) but the
engine's assumptions about the enemy model are not met. So the next attempts, in the order I would try them:

1. **Keep the part count.** Write Sonic's vertices into the existing 341 records (each part gets a share of the 4107
   vertices) and keep the part table, groups and material indices exactly as they are. Only positions, normals, uvs and bone
   ids change. This is the least the engine can object to.
2. **Replace only the body parts** that carry the visible skin, leaving effect/animation parts alone.
3. Then textures, which are a separate problem: an RE5 body arc carries its own TEX entries (Chris 84), and none of Sonic's
   are in the archive yet, so even a drawn Sonic would wear the Majini's material.

## The state left behind

The rotation is back on RE5 with `cast_swap: on` and `skin_swap: random` — a modded round every match — and the Sonic build
is kept as `sonic-test` for the next attempt.
