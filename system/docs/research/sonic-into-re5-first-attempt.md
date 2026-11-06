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

## Second attempt: the bisect, and what it ruled out

The first attempt's suspects were the 341 -> 1 restructure. This attempt removed that variable entirely: a Majini with
**every part kept** (records, groups, materials and the index buffer untouched) and only vertex positions scaled 1.2x, with
the bounding box transformed from the model's own box so nothing clamps (1008 parts changed across the three body LODs).

It booted as its own build (`bisect-scaled`), drew its menus, and then the frame **froze**: the same 4560-byte frame, mean
1.5, std 3.3, for six minutes, with autoplay running and making no difference.

So the engine does not merely dislike a restructured part table - it hangs on a model whose structure is untouched and only
vertex positions were rewritten. **The fault is in the rewrite, not the restructure.** The next bisect is inside the writer:

1. write the model back with **no edits at all** (same vertex bytes, same bounds) and boot it. If that hangs, the container
   assembly is at fault (offsets, trailer, compression) and vertex data is not yet in question;
2. if (1) boots, write decoded-then-repacked positions with the original bytes preserved and the bounds untouched, which
   isolates the quantisation round trip from the container.

### Two bugs found and fixed while doing this

* New mesh records must start from the existing bytes. Zeroing them erased a record field the vertex decoder needs, and part
  0 came back with no positions (the existing test caught it immediately).
* Bounds computed from only the decodable parts **shrank** the box (y 125.2 instead of 185.6), which would clamp every part
  that did not decode - the same clamp trap as before, in a new place. The box is now the original box transformed by the
  same scale.

### Launching a test build

`switch_mods create_build` alone does **not** register a build: a launch refuses it with "no built mod ... for this game".
`op: new_build` registers it, and that is the one that launches.
## The freeze is the header box, not the vertex data

Two builds differ in exactly one thing: whether the header's bounding sphere/box was rewritten.

* **scale 0.8, box untouched** (positions stay inside the model's own box): the title boots and runs - menus, intro cutscene,
  frames changing throughout a 36-frame window. No freeze.
* **scale 1.2, box rewritten** (positions need a bigger box): menus, then a frozen frame - identical 4560-byte frames,
  mean 1.5, std 3.3, for six minutes.

So written vertex data is accepted by the engine; **the bounding box I write is not**. That narrows it to the 48 bytes the
box lives in (sphere x/y/z/r + min + max). The likely offenders, cheapest first:

1. the sphere radius: I wrote `max(extent) * scale / 2`, which is not necessarily a radius the engine accepts (it may expect
   the radius to enclose the box from its centre, or to be in another unit);
2. the min/max extent itself: doubling it is fine in principle, but if the engine compares the box against per-part data it
   may reject a disagreement;
3. whether the box must be rewritten at all when geometry only shrinks - the 0.8 run shows it need not.

Until that is settled, **scaling down with the untouched box is the known-good way to write geometry**: it needs no box
rewrite and it runs.