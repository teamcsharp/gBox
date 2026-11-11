# PSO lane status - consolidated hand-off (2026-11-11, refreshed)

Branch `ds-pso-live-platform-20261110`, tip `107a8027` plus this commit. Every claim names where its evidence lives.

## Headline

The **offline half of the PM document advanced substantially** while no game was running: CP1 is verified, CP2 has a measured verdict, CP3
runs unattended, CP9's card layout is cracked, and the **level editor the operator asked for is now end-to-end** (map -> rooms -> doorways ->
placements -> inspect -> edit). The **live half (CP17-CP19) is unchanged and blocked on one thing: a PSO session started from the gBox app.**

## The checkpoints

| CP | Subject | State | Evidence |
|---|---|---|---|
| CP0 | clean start | delivered earlier | session record; not re-run |
| CP1 | local coder model on the 3090 | **DONE** | `cp1-local-model.json`: deepseek-r1:14b answered while the 3090 went 2.4 -> 13.1 GB |
| CP2 | gold-set model check | **VERDICT** | `cp2-deepseek-probe.json` + round-238: plausible roles, no exact names, 23.9 s/function -> fallback applies |
| CP3 | bulk labelling | **RUNNING** | `labels-deepseek.jsonl`, 38/82 at ~25 s each (2.37/min), own file, resumable |
| CP4-CP6 | jump state, Forest 1 dev warp, formats | delivered earlier | not re-verified this session |
| CP7 | executable targets | partial | `functions.jsonl` 82 functions; labels are candidate-only |
| CP8 | room pieces for expansion | **ADVANCED** | mesh segmentation: Forest 1 11 rooms, **Forest 2 14 rooms** (`routes/*-rooms-mesh.json`) |
| CP9 | save data | **PARTIAL** | card directory + files cracked (0x20C0, name at +0x08, BE blocks); payload encrypted, two cipher hypotheses eliminated |
| CP10-CP16 | editor page, swaps, donors, room add, P1, focus-free | delivered earlier | CP11 branch unmerged |
| CP17 | Forest 1 -> 2 **by walking** | **ROUTE CERTIFIED, NOT WALKED** | 9 legs, 0 blocked, 999 units, ends 3.7 units from the warp, 37 s |
| CP18 | Dragon defeated | **TOOL READY, NO EVIDENCE** | `boss_both.py` captures boss HP + every player's HP |
| CP19 | Episode I unattended | **NOT STARTED** | `mastery_run.py --all`, refuses to run without an operator-owned session |

## The level editor, end to end (this session's biggest deliverable)

| layer | built from | verified |
|---|---|---|
| **rooms** | erode + grow + flood over the collision mesh | 11 rooms Forest 1 (7 known centres recovered), **14 rooms Forest 2 (first ever)** |
| **doorways** | cells whose neighbour belongs to another room | 61 / 76 edges |
| **placements** | 68-byte set records: class id + 3 floats | 150 / 196 objects decoded per floor |
| **inspect** | click a room in the viewer | room id, cells, centre, object counts |
| **edit** | place mode: pick a record, click a room | validated append, **refuses void points** (`(1082,1030)` -> "673.3 units from room 6") |
| **byte safety** | move one record | exactly **12 bytes**, exactly **1 object**, other 149 records identical |
| **growth** | add one record | 150 -> 151, +68 bytes, **remainder 0** |

All offline, all from shipped data, nothing written to the game's originals (edited copies in `rel/edited/` until the PM's CP11 build path
installs one).

## The operator's requests

| request | state |
|---|---|
| random weapon/frame/shield/mag every 2 min | running (`equip_roulette --loop`) |
| five copies in all five slots | `five_slots.py`, inventory-verified |
| mag with random stats/level each swap | applied live (level-200 roll) |
| click-to-move and click-to-kill from the map | verified into `goto.json` |
| top-down map + build/edit levels | **delivered**: rooms, doors, placements, inspect, place, validate |
| all spells | blocked: technique table at `+0x2E7`, write channel proven, needs a session |
| Ultimate difficulty | `apply_master.py ultimate`, needs a session |
| bot plays the game | needs a session; the 37-second walk is ready |

## The single blocker, unchanged

Every live item needs **a PSO session started from the gBox app**. An agent-launched session is `agent_owned`, and gBox routes no input to it
(that is what made the controller dead in rounds 228-229). Sequence: app Play -> operator-owned session -> load character ->
`mastery_run.py --all` + `apply_master.py`.

## Risks for hand-off

1. **The save may never have been written** - `PSO_CHARACTER.bin` has no plaintext character name.
2. **CP18's "both players alive" cannot be met on a single-player session** - it needs two `TObjPlayer` entries.
3. **The local model is a lead generator** - nothing it names enters `pso_ram.py` without a decompile or live proof.
4. **No edited set file has ever been booted by the game** - the byte-level proofs are sound, but that is the natural first acceptance test
   when a session returns.
