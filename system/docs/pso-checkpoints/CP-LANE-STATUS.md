# PSO lane status - consolidated hand-off (2026-11-11)

Branch `ds-pso-live-platform-20261110`, tip `a62d89bf`+ this commit. Written at the end of a long session; every claim below names where
its evidence lives, and nothing is marked done on the strength of a narration.

## The checkpoints

| CP | Subject | State | Evidence / blocker |
|---|---|---|---|
| CP0 | clean start | delivered earlier | per the session record; not re-run this session |
| CP1 | local coder model on the 3090 | **DONE this session** | `cp1-local-model.json`: deepseek-r1:14b answered while the 3090 went 2.4 -> 13.1 GB |
| CP2 | the gold-set model check | **VERDICT this session** | `cp2-deepseek-probe.json` + round-238 doc: plausible roles, **no exact names**, 23.9 s/function -> fallback clause applies |
| CP3 | bulk labelling, unattended | **RUNNING** | `labels-deepseek.jsonl` growing (12/82 at ~25 s each = 2.37/min); separate from the stale qwen file |
| CP4 | no cold boots (jump state) | delivered earlier | not re-verified this session |
| CP5 | Forest 1 for development (warp) | delivered earlier | not re-verified this session |
| CP6 | formats / decryption | delivered earlier | not re-verified this session |
| CP7 | executable targets | partial | `functions.jsonl` holds 82 exported functions; labelling is candidate-only |
| CP8 | room pieces for expansion | delivered earlier | `map_forest01d.dat` decodes 150/150 objects (round 215) |
| CP9 | save data (the card with BQF) | **PARTIAL this session** | directory + files cracked (`memcard/`), payload **not decryptable**: no repeating key, not the documented LCG, not PRS |
| CP10 | P6a in a field area | delivered earlier | not re-verified this session |
| CP11 | P6b editor page | delivered earlier (branch) | `ds-pso-editor-page-20261110` awaits the RE session's merge |
| CP12 | P7a rigged swap | delivered earlier | not re-verified this session |
| CP13 | P7b library donors | delivered earlier | not re-verified this session |
| CP14 | P6c one room added | delivered earlier | not re-verified this session |
| CP15 | P1 city -> Forest 1 | delivered earlier | not re-verified this session |
| CP16 | focus-free movement | delivered earlier | not re-verified this session |
| CP17 | Forest 1 -> Forest 2 **by walking** | **ROUTE CERTIFIED, NOT WALKED** | `cp17-route-certificate.txt`: 9 legs, **0 blocked**, 999 units, ends 3.7 units from the warp, 37 s at 27 u/s. Accept needs the floor id to change while walking - never yet observed |
| CP18 | Dragon defeated | **TOOL READY, NO EVIDENCE** | `boss_both.py` captures the exact accept series (boss HP to 0 with every player's HP); the one fight happened without it |
| CP19 | Episode I unattended | **NOT STARTED** | needs CP17 + CP18 plus `mastery_run.py --all` |

## What is built and proven, independent of the checkpoints

* **movement**: 27 units/s measured (8x the previous controller); the runner holds a direction and needs no per-step probing;
* **navigation**: 5,701 free cells on Forest 1, 6,145 on Forest 2, floor-aware planner collapsing 149 waypoints into 9-12 straight legs;
* **the operator's exits**: Forest 1's warps at **(133,-48)** and **(536,-566)** recovered from their own recorded play;
* **operator arbitration**: `pso_input` is the only key path, and it stands down whenever the operator has been active inside 3 s; proven
  live (the log shows it pausing mid-run) and in unit tests;
* **memory**: `write_memory` / `freeze_memory` / `poke` work **only** on a session the running worker owns, with rollback receipts;
* **observation**: `learn_live` records position/HP/entities/damage every second; `poi` accumulates warps, switches, doors and containers per
  floor - it is what found `TObjWarpBossMulti` at (155,-501) in Forest 2;
* **map control**: click / shift+click verified end-to-end into `goto.json`;
* **viewer**: answers instantly, including with no game (was hanging for hours).

## The operator's requests

| request | state |
|---|---|
| random weapon/frame/shield/mag every 2 min | running (`equip_roulette --loop`) |
| five copies in all five slots | `five_slots.py`, inventory-verified |
| mag with random stats and level each swap | applied live (def 35 / pow 48 / dex 36 / mind 81, level 200) |
| click-to-move and click-to-kill from the map | verified wired |
| all spells | **blocked**: technique table located at `+0x2E7`, write channel proven, needs a live session |
| Ultimate difficulty | `apply_master.py ultimate`, needs a live session |
| bot plays the game | needs a live session; the 37-second walk is ready |

## The single blocker

**Every remaining item needs one thing: a PSO session started from the gBox app.** Not an agent job - an agent-launched session is
`agent_owned`, and gBox deliberately routes no input to it, which is what made the controller dead in rounds 228-229. The correct sequence
is: app Play -> operator-owned session -> load the character -> `mastery_run.py --all` plus `apply_master.py`.

## Risks worth handing over

1. **The save may not have been written.** `PSO_CHARACTER.bin` on the live card contains no plaintext character name, so either the payload
   is encrypted as shown or the character was never committed to that card. Worth checking in-game before any long run.
2. **CP18's co-op half is easy to lose.** "Both players alive" needs two `TObjPlayer` entries in the entity table; against a single-player
   session the accept condition cannot be met no matter how clean the fight is.
3. **The local model is a lead generator, not an authority.** 23.9 s/function and no exact names on the gold set; nothing it proposes should
   enter `pso_ram.py` without a decompile or live proof.
