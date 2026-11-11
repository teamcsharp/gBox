# CP07.3 the scene loader — done (the loader is named; the transform data needs the DC image, which is packed)

Session identity: DeepSeek    Branch: ds-pso-cp07-scene-loader-20261110    Commits: this branch
Goal: 1, and CP8/CP14 through it

## The loader, named

**`FUN_801fb798`** (220 bytes, no callers in the image — it is reached from the area-transition tables) is the scene
load:

```c
uVar1 = FUN_802034a8();                     // the current floor/episode selector
iVar2 = FUN_801fba20();                     // the area's sub-index
iVar3 = FUN_80207e88(uVar1);                // the floor -> map/layout resolver (already decoded in pso_floor_map)
iVar3 = iVar3 + iVar2 * 8;                  // an 8-byte entry: {u32, char *name}
FUN_801317e4(buf, *(u32 *)(iVar3 + 4), s_r_rel_8044a7b0);   // "<name>r.rel"
iVar2 = FUN_800f9ae8(buf);                  // load it; the handle lands in the global at r13-0x46d8
FUN_801317e4(buf, *(u32 *)(iVar3 + 4), "n.rel");            // "<name>n.rel"
FUN_8023e638(buf, *(u32 *)(*(u32 *)(r13-0x46d8) + 4));      // load that too
...
```

So the loader's inputs are exactly the two tables `pso_floor_map` already reproduces (the 36-entry area/layout lists at
`0x804C8FC0` / `0x804C9270`) and the per-area 8-byte entry it takes the **name** from, with `FUN_800f9ae8` /
`FUN_8023e638` doing the file IO.

**`FUN_802066bc`** (192 bytes) is the `n.rel` **magic dispatcher**: it names the file, opens it (`FUN_800f9d80`),
reads it (`FUN_800f94bc`), then walks the table at **`0x804c8b08`** two pointers at a time, comparing the loaded
file's first **4 bytes** (`FUN_8039dabc(data, entry, 4)`) and stores `entry[1]` - the handler/data pointer for that
magic - into the global at `r13-0x4618` (initialised to `0xffffffff` = "no match"). Its caller is `FUN_8020681c`
(360 bytes), the `n.rel` load path, itself called from `0x801a40d8`.

**Decompile excerpts** are in the round log for this branch; the addresses are `801fb798`, `802066bc`, `80206db8`,
`8020681c`, the table `0x804c8b08`, and the floor resolver `80207e88` (already in `pso_floor_map`).

## The transform: where CP8's data really is (measured)

* The owned **GameCube** disc has **649 `.rel` files**, and the scene ones live in `Scene/` as
  `map_<area>_<room>{c,n,r}.rel` (e.g. `Scene/map_aancient01_00r.rel`, 48,864 bytes).
* **Forest 1 has no `r.rel` on the GC disc.** Its area data is `map_forest01d.dat` (the placement set) plus
  `map_forest_e/f/g/j.bin` and `gsl_forest01.gsl`. CP8's premise ("Forest 1, 17 sections of 40 bytes, root at
  `0x3114`") is **Dreamcast data** and does not apply to this build as written.
* The GC `r.rel` files that do exist **begin with floats**: `Scene/map_aancient01_00r.rel` starts
  `c2 c8 00 01 00 00 00 00 c3 16 00 00 c2 c7 ff fe` = `-100.00001, 0.0, -150.0, -99.99998` - a root transform at offset
  0 is the obvious reading and the right place for CP8 to start on this build.
* CP8's Dreamcast input exists on this machine only as a compressed image:
  `D:\gBox\cache\daba7a3b195dcf6b\Phantasy Star Online Ver. 2 (USA).chd` (785,313,172 bytes). There is **no `chdman`** and
  no Dreamcast disc reader in the tree, so `map_forest01_00r.rel` cannot be read today.

## Needs (RE session)

- a decision on CP8's data: either extract the CHD (`chdman extractcd`) somewhere on the i9, or accept that CP8 is
  **GameCube-shaped** (the `Scene/*.rel` files above) and restate its accept against `map_aancient01_00r.rel`-style data.
- nothing else: the loader itself is documented and needs no live session.

Tests: none changed (documentation and analysis); CP0 baseline unchanged (45 failed / 1,329 passed / 132 skipped).

Next: CP7.2, the object loader (the `kind` -> constructor dispatch), which is offline and has a measurable accept
(labelled coverage above 84.4 %).
