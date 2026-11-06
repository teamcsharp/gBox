rig_roles: joint roles from geometry, with the structural case that still needs handling

The ganado swap needs a roles map (hip, chest, neck, head, each upper arm / forearm / hand, each thigh / shin / foot) and Sonic's
glTF has no anatomical names, so the roles have to come from the rest pose. New module `gbox/rig_roles.py`, four tests passing:

* head = highest joint, its parent chain gives neck and chest
* hip = the ROOT of that chain, not the joint above it (rigs differ in spine count; the test skeleton has an extra one)
* limb roots = the pair of children that are not on the spine chain - arms by widest X span, legs by deepest drop
* `named()` maps indices to joint names for `characters.rig_from_gltf`

Measured on Sonic's own rig (66 nodes, all unnamed): it derives head/neck/chest/hip correctly and then **stops**, because his
shoulders do not hang off the head-to-root chain:

```
node000 (0.00, 0.00, 0.00)  root / hips
node001 (0.00, 5.00, 0.00)  spine        <- parent chain of the highest joint
node002 (0.00, 5.24, 0.00)  highest joint (read as head)
node003 (0.00, 5.09, 0.00)  the chain then DESCENDS ...
node005 (0.00, 4.62, 0.00)  ... to here, where the arms split
node006 (-0.28, 4.69)  node016 (0.32, 4.68)   the two shoulders
```

So the lateral pair is a child of a joint off the spine chain. The fix is a fallback: when the spine chain has no branching
joint, scan every joint for the best lateral pair (children of opposite X, arms) and the best downward pair (legs) and use
those as the limb roots. That is a small, testable addition to the same module, and it makes the derivation work on rigs whose
spine runs head-first, which this one does.
## Rewritten derivation: limb pairs first, then the spine

The first version started from the highest joint and walked down the spine. Sonic's rig defeats that: the highest joints are
his **ears** (two joints at y 8.20), the chain descends through the head to a chest at 6.63, and the arms hang from the chest
while the legs hang from the hip at 4.62 - so a "highest joint" rule calls an ear the head and the origin the hip.

Now the **mirrored sibling pairs are found first** (the least ambiguous thing a humanoid rig has), then the spine is inferred:

```
chest = parent of the arm pair        hip = parent of the leg pair
head  = one highest joint, or the deepest common ancestor of several (ears, horns, antennae)
neck  = parent of the head
```

Five tests pass, including a synthetic rig shaped exactly like Sonic's (ears at the top, chest below the head, arms off the
chest, legs off the hip) which asserts all sixteen roles.

Measured on Sonic: **all sixteen roles derive**, e.g. `l_upper node037`, `l_thigh node016`, `r_thigh node006`.

## Where the enemy swap now stands

```
rig_roles.named(Sonic)               16 roles                    ok
characters.rig_from_gltf(Sonic)      62 joints, 4 prims, 16 roles ok
re4gc_enemies.retarget(rig, ganado)  fits onto the ganado skeleton ok   <- the hard part
write_rigged_gltf(...)               writes a JSON .gltf           ok
swap_body -> gltf_to_bin             FAILS: gltf_to_bin reads binary GLB, the writer emits JSON
```

`swap_body` needs a `.glb`; `re4gc_enemies.write_rigged_gltf` deliberately writes a self-contained `.gltf`. The repo has many
`to_glb` helpers (per title); the missing piece is a JSON-glTF -> GLB step, either reused from one of them or written once as
a shared utility. That is the whole remaining gap for zombies-as-Sonic - the retarget, the roles and the pack surgery all work.
## A real bug: a mod built from enemy packs contained no files

`char_swap.build_mod` globbed only `pl*.drs`, so an enemy swap produced a mod whose `files` list was **empty** - it launched,
said `mod: re4gsonic1512`, and changed nothing. Fixed to carry `em*.drs` as well:

```python
packed = sorted(list(Path(drs_dir).glob("pl*.drs")) + list(Path(drs_dir).glob("em*.drs")))
```

Verified: the rebuilt mod reports `files: ["em/em10.drs"]`.

## The ganado pack fits only with its spare bodies collapsed

Sonic retargeted onto the ganado skeleton is bigger than the slot it replaces:

```
em/em10.drs   swapped 10,654,208  vs 10,628,000 on disc   grows at every texture size (max_tex 8 still grows)
              with the pack's other 13 body slots collapsed: 10,340,608   FITS
em/em11.drs   6,271,136 vs 6,260,192 even collapsed        still grows by 10,944
```

So em10 (the base ganado) can carry Sonic today; em11 needs decimation or a smaller texture set. The texture size is not what
grows the pack - geometry is - which is worth knowing for every enemy swap after this.

## Open

`autoplay op=prepare` returned **500 Internal Server Error** on this mod (it succeeded on the player mod earlier), so the menus
were never walked and the capture only reached RE4's main menu. That is the next thing to look at, and it may be the new RE4
selection branch - it is my code, and it is the one path that differs between the run that worked and this one.