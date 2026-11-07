# MercMode sidebar panel: the four swap actions, measured

The PiP's MercMode panel (`clients/web/viz/mercmode.js`, `swapHTML` / `wireSwaps`) offers remove clothes, swap clothes,
character -> zombie and zombies -> cast. Each is backed by a route in `gbox/decrypt_lab.py`. This note records what each
one actually does after being run against the live RE5 Switch tree on 2026-11-06, and where the honest limit is.

## What the routes did (RE5 Switch, `re5_switch`, build `panel-verify`)

| action | route | result |
|---|---|---|
| remove clothes | `POST /api/decrypt-lab/strip-clothes` | `uPl00ChrisNormal.arc`: body group `evf0000_01`, **4** clothing maps repainted (`pl00Gear_BM`, `pl00Gear_MM`, `pl00Glove_BM`, `evf0000_03_MM`), **4** skipped on a tag mismatch, 43,356,552 B out |
| swap clothes | `POST /api/decrypt-lab/model-swap` | `chris|sheva` moves BM+MM+NM, `chris|jill` BM+MM+NM, `chris|wesker` MM+NM; josh / excella / barry / rebecca share **no** tag with Chris and are struck out in the panel before a click |
| character -> zombie | `POST /api/decrypt-lab/model-swap` (slot = player arc, donor = `uEm6c`) | 3/3 maps moved (`NM` retagged), 43,360,031 B out. Textures only: a player arc given an enemy **mesh** has never produced a session |
| zombies -> cast | `POST /api/decrypt-lab/zombie-cast` (new) | walks every enemy archive the title spawns, one cast member each |

## Why "zombies -> cast" needed a route of its own

The panel used to move a single archive (`uEm6c`) while a round fills its enemies from `uEm10` / `uEm11` Majini plus
`uEm21` / `uEm62` - the same trap `skin_swap.ZOMBIE_ARCS` already documents after a round with the swap on showed three
ordinary Majini. A one-arc click cannot show the operator anything.

`/api/decrypt-lab/zombie-cast` takes the title's whole `ZOMBIE_ARCS` set, gives each enemy a different cast member
(`decrypt_lab.zombie_donors`, round-robin, never the same character twice until the cast is exhausted) and reports every
arc by name:

* `swapped` - with the mesh names moved, the texture count and the size written;
* `absent` - the extracted tree does not hold that enemy archive (nothing to do, not a failure);
* `too_big` - the donor is more than `max_growth` (3x) the slot's file, refused before it reaches the overlay;
* `failed` - with the reason.

`geometry: false` is the default and that is deliberate: on this engine an MRL-only enemy swap boots and plays a round,
while a foreign `MOD` mesh is not drawn (docs/research/sonic-into-re5-first-attempt.md: the engine draws the game's own
triangles with the donor's vertex positions). The flag is exposed so the shape question is one call away, not a code
change - it is the experiment, not the default.

## Shared code

The per-arc work the `model-swap` route had inline is now `decrypt_lab._swap_arc_bytes`, used by both routes, so a fix
lands on all of them (remove clothes keeps its own group logic because it repaints clothing from the body, which is a
different operation).

## What is still out of reach, stated plainly

* **A player character wearing a zombie's mesh.** Measured broken twice (the build is made, no session appears). The
  panel therefore swaps the player's *skin* for the enemy's, which is what "character -> zombie" does today.
* **A Sonic (or any foreign) mesh as an RE5 character.** Needs the part-table rules; vertex writing cannot produce a
  clean shape. RE4 GameCube is the title where a foreign rigged model does work (`re4gc_zombies.py`, 58 of 60 enemy
  packs).
* **A save state in the incident report on Switch.** eden/citron provide no checkpoint primitive; the report carries a
  bounded RAM witness instead (`mercs/incident.py`, 48 KiB: player actor + nearest four enemies, hashed and
  zlib+base64), which is the designed substitute, not a missing step.

## Verified

* `system/tests/test_decrypt_lab_zombie_cast.py` - 5 tests on the planning logic (every arc covered, no donor repeated
  while the cast lasts, the rotation start moves, an absent arc is reported not failed, a title with no map plans
  nothing).
* `system/tests/test_mercmode.cjs` - 21/21 panel tests still pass with the new button wiring.
* 302 swap-related tests pass (`pytest -k "decrypt or skin_swap or mercmode or zombie_cast or mt_arc or model_swap"`).
