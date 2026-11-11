# Lane-log text of `ds-pso-floor-editor-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `2be3617f`.

----

## Round 46 (2026-11-10, later session) — P2b item 2: the floor -> map/layout resolver, decoded from the executable

Working locally on the i9 (hard rule now in `DEEPSEEK-HANDOFF-2026-11-10.md` §0: no ssh/sudo/systemctl/kill/curl on
lilspark, no launches or stops there; every API call carries `x-gbox-actor: agent`). Nothing in this round touched
lilspark or any live session.

**The open item** (`docs/research/pso-gc-executable.md` §7.2): `FUN_80207E88` (104 bytes) and `FUN_802077CC` (64 bytes)
turn a floor id into a map name and layout - decompiling them would let the editor and the area survey bind a floor
to its files with no live load.

**Decompiled** from the existing project (`D:\gBox\ghidra-pso\PSO`, program `pso_v3.elf`):

- `FUN_80207E88(floor)`: for `floor < 0x24` it returns a `{char **names, u32 count}` entry from `0x804C8FC0`
  (Episode 1) or `0x804C9270` (Episode 2), chosen by `FUN_8030A6A8` (it tests `+current_episode == 3` and two
  helpers). Each entry names `count` area/layout pairs: `names[2i]` = the area's map name, `names[2i+1]` = the
  layout's.
- `FUN_802077CC(0..0x11, out)`: three words per row from an 18 x 12-byte **.bss** table at `0x80513920`, built by
  `FUN_80207C60` from a static 18 x 8-byte source at `0x8044B894` and defaulting each row's first word to `-1`.
  That is a different per-floor record (three words), not the map names; its meaning is the remaining question.

**Both 36-entry map-name tables are now read out and pinned** in `gbox/pso_floor_map.py`:
`floor_names(0)` = (`map_city00`, (`map_city00_00`,)); floor 1 = (`map_forest01`, (`map_forest01`,)); floor 3 = Cave 1
with six layouts; floor 15 = the lobby's fifteen rooms; floor 16 = `map_vs01` with three; floors 30-33 =
`map_boss05` .. `08`; Episode 2 is the same with `a`-prefixed areas for floors 0-14 and identical floors 15+. Floors
0-11 match `pso_areas.EPISODE1` in order, and floor 1 = Forest 1 matches the operator's recorded Forest 1 session
(floor 1, rooms 11-16). `derive(dol)` re-reads the table from a `PsoV3.dol` and `tools/verify_pso_floors.py <dol>`
reports PASS on the owned disc. Tests `test_pso_floor_map.py` (7): the area-table order, the layout names, Episode 2,
range handling, a synthetic DOL built in the executable's own layout, a changed table reported instead of trusted, and
an unmapped address raising instead of crashing.

**What the editor gets:** a floor id now resolves to its area and every layout name offline - the map name the
Scene files use (`map_<area>_<NN>{c,n,r}.rel`), so `pso_editor`/the survey can bind a floor to its files without
booting the game.

**P1 side note (§4.1 of the progress doc):** the operator's recording
(`D:\gBox\pso-ds\demos\dbc5ff9be4ca416c-c91e5802a9844b37.jsonl`, 404 rows, 881 s) **starts with `floor` already 1**
(Forest 1, rooms 11-16, no pad input recorded), so it does not contain the 0 -> 1 transition. Per §4.6, the one
question for the operator:

> "This morning (about 05:50-06:05) you took BQF from Principal Tyrell's office into Forest 1. How did you leave the
> conversation, and what did you use to go down to the planet (which room, and which button)?"

**Also noted on main while this ran:** P6a's offset is settled by another lane (`082975fc`: lobby (+228,+291),
distance 0.0 on all four doors and both spawns) and P6b has its command line (`bf777c74`) - this step does not
duplicate either.

**Next in the offline order:** §7.3, the object-class registry. Started: the 335 `TObj*` name pointers all sit in
the .data section at `0x805D2600` (335 hits, one section, irregular strides - the section starts with a `TAd*`
descriptor table), so the index order is not a flat pointer array; the loader that turns a placement's `kind` low
byte into a class needs decompiling next (the set-object reader), and the `.bss` floor record at `0x80513920` is the
other open reading.

## Round 52 (2026-11-10, later session) — the floor resolver's last unknown, and a floor -> sets join for the editor

Working locally; no lilspark, no live session.

**The `.bss` floor record resolved (P2b item 5's leftover).** `docs/research/pso-gc-executable.md` §7.2 left "that
second table is a per-floor three-word record, not the map names; its meaning is the remaining question". Decompiled:

* `FUN_80207798(floor, a, b, c)` **writes** one 12-byte row at `0x80513920` for `floor < 0x12`;
* `FUN_802078A4` walks the 18 rows and, for each live row (`word0 >= 0`), recomputes words 1 and 2 as
  `table[word0].param * k * (rng() - bias)` with the RNG at `FUN_8039C880` - i.e. it is a per-floor **randomised
  environment parameter** block (seeded once by `FUN_80207C60` from the 18 x 8-byte source at `0x8044B894`, which
  holds index/param pairs, `word0` defaulting to `-1`), **not** the floor -> map binding.

So the floor -> map/layout resolver really is only `FUN_80207E88`'s two tables (`0x804C8FC0` / `0x804C9270`), already
pinned in `gbox/pso_floor_map.py` (round 46); the second record belongs to the environment/effects side and does not
affect the editor. The research doc's bullet is corrected to say so.

**New for the editor (branch `ds-pso-floor-editor-20261110`):** `pso_editor.sets_for_floor(found, floor, episode2=...)`
- the join from a floor id to the set files of its area (`pso_floor_map.area_for_floor`), so a page or a CLI user can
  say "edit Forest 1" instead of remembering file names. It is a pure filter over `sets()`, matches only the area's
  own prefix (a longer name such as `map_forest010x.dat` is not floor 1's), and handles the Episode 2 `a`-prefixed
  areas. Tests: floor 0 -> the city's two sets, floor 1 -> forest01's, floor 3 -> cave01's, floor 99 -> none, the
  Episode 2 case, and the longer-name guard. `test_pso_editor` + `test_pso_floor_map`: **22 passed**.
