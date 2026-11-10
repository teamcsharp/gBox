# DeepSeek hand-off, 2026-11-10 (from the RE session)

Written for the DeepSeek session on the i9-NUC. The operator, 2026-11-10 ~12:00 CST: "prepare a document for handing off
the tasks to deepseek so i can have it continue on the tasks from the i9". This doc is the start point. Where it differs
from older DeepSeek docs, this one wins:
- `DEEPSEEK-PSO-TASK-GUIDE-2026-11-09.md`
- `DEEPSEEK-GRENADE-RING-TASK-2026-11-10.md`

Check every live fact against the system before you rely on it.

## 0. Read first

- **Credit.** The DeepSeek balance was **$2.96 at 11:51 CST**. The operator turned DeepSeek off for Hermes so what is left
  goes to you ("relax the lanes on Deepseek so credit can be saved for it's harness"). Work in small, finished steps, and
  write each one to your lane log, so a top-up gap loses nothing.
- **Branches only.** Work on a branch and push the branch, never `main` (operator 2026-11-10). The RE session reviews,
  merges and deploys. Name branches `ds-<topic>-20261110`.
- **Scope.** RE Mercenaries work is the **Switch editions only**:
  - RE4 `010099A00BC1E000`;
  - RE5 `010018100CD46000`;
  - RE6 `01002A000CD48000`.

  PSO is your other lane. PS3, GameCube and Wii editions get no new work.
- **Live sessions.** Only MercMode's own sessions: `agent_owned` true and the launch actor not `operator`.
  - Never stop, relaunch or reconfigure a session, and never change MercMode settings, the queue, `default_mods` or
    `re4-mods.json`.
  - Need a restart or a setting changed? Ask in your lane log; the RE session does it at a gap.
- **API token.** `system/gbox-data/api_token`, never printed. Send the header `x-gbox-actor: agent`.
- **Tests.** No new failures. Known red on main:
  - 11 RE5 Switch files (bonus / giveup / rampage / smooth / threat);
  - 3 RE6 (2 `test_re6_magnum_quick4`, 1 sniper in `test_re56_weapon_controls`);
  - the 4 in `test_pso_steering_evidence.py`. They broke with the 11-02 co-op steering commits (`6d465b8a` ..
    `6b95cb75`), not with your lane. One is a real bug: `_observe_boss` writes telemetry outside any guard
    (`pso_coop.py` around line 2844), so a telemetry failure aborts the tick. Fix that one. See
    `DEEPSEEK-PSO-PROGRESS-2026-11-10.md`.

## 1. What changed today (live on lilspark unless marked)

- **Rotation:** MercMode plays 5-round blocks per title, character-swapped builds only.
  - **RE4:** `recovery-re4-fit-v4-20261110`, all five cast slots plus 14 Ganados, a new proportional fit, measured sizes.
  - **RE5:** `recovery-series-01-20261110`.
  - **RE6:** `recovery-re6-enemy-cast-01-20261110`, the gallery players plus 13 enemy classes as library characters.
- **Shared bot core:** `gbox/mercs/core/`:
  - `combat.py`, the universal core;
  - `respond.py`, the doctrine: flash, mine or fire under threat;
  - `fire_pattern.py`, the PS3 magnum's scatter;
  - `room_map.py`.
- **Room maps:** RE4 and RE5 have room maps from the stages' own collision data.
- **RE6 (branch re6-bomb-mind, merged):**
  - the remote bomb is dropped already armed and set off through the detonator flag (player +0x5A19 bit 0x20);
  - grenades come in by hook, 5 per equip;
  - QTEs are solved in RAM;
  - the scatter barrage (`grenade_scatter`) is flash only.
- **Your grenade lane** (`ds-grenade-ring-20261110`) is merged:
  - the honest per-kind status, live on all titles;
  - the RE5 flash ring, verified live;
  - the RE6 ring, built on the verified pair;
  - the RE6 status bug is gone on the current session: RE6 interventions answer available, flash available.
- **Lesson 1: no rewriting executed code on the Spark.** Citron NCE runs RE4 natively, and the Spark's cores have no
  instruction-cache coherency (`CTR_EL0 = 0x9444C004`, DIC = 0). RE4's loadout code patch rewrote already-executed
  instructions, and every stage load hung, ending in `Unhandled NCE prefetch abort: pc=0x0`. That patch is off for good
  (`LOADOUT_CODE_PATCH = False`). Random weapons are now given by data writes in round.

  The RE5 / RE6 native controllers work because they never rewrite executed code:
  - they install only into **zero padding the game has never run**, through the code segment's backing file
    (`re6_switch_native.Controller.install`);
  - they are reached through **data**, not a patched branch.

  Keep to that rule.
- **Lesson 2: offline jobs used to block launches.** Any job on a worker blocked MercMode's next launch. Offline analysis
  jobs (Ghidra, decompile, `rea_*`) no longer do, but run heavy analysis on the i9, not on lilspark.
- **Lesson 3: Hermes tickets and the game gate.** A ticket that names a game in its context does not dispatch while
  MercMode plays that game. Leave `game_id` out of static or research tickets.

## 2. Your lanes, in order

### A. PSO (continue)

`DEEPSEEK-PSO-TASK-GUIDE-2026-11-09.md` section 0d is still current:
- decrypt;
- the level editor P6a-c;
- character hot swap P7a-b;
- working on the i9, at full speed.

Add one item: fix the 4 failing tests in `system/tests/test_pso_steering_evidence.py` first. They fail on plain main.

### B. Grenades on the Switch titles (all three kinds, then the barrage)

The RE6 grenade work was the RE session's lane until this morning. That lane is merged, so **RE6 grenade kinds are now
yours too**. The bomb, detonator and QTE hooks stay as they are.

1. **RE6 hand and incendiary.**
   - The classes are known: uWp1091 hand (item 0x113, DTI main+0x2951490, vtable main+0x284B788) and uWp1093
     incendiary (0x114).
   - The compiled spawn image pins the flash's class. Make the class a parameter of the spawn, rebuild, and get a live
     receipt per kind: frames, detonated / requested, `self_damage` 0.
   - Then let `grenade_status` advertise each kind.
   - Read `system/docs/research/re6-weapon-dti-tree.md` (Hermes #9437, merged).
2. **RE6 launcher rounds in the scatter barrage.**
   - #9437 lists uWp1080 (the grenade launcher, item 0x112), uWp1120 (the rocket launcher, 0x11B) and their shells
     uWp1302-1304 (items 0x133-0x135).
   - Find the shell spawn path, and put real launcher rounds into `grenade_scatter`'s random kinds. The operator asked for
     "a rapid barrage of random grenades from the grenade launcher without equipping it".
3. **RE5 hand and incendiary.**
   - Find RE5 Switch's grenade item classes the way #9437 found RE6's: walk the MtDTI static initialiser. The tool is
     `system/gbox/mercs/re6_dti_emu.py`; point it at RE5's main NSO.
   - Then the same parameterised spawn and live receipts as for RE6.
4. **The scatter barrage on RE5** (package 6 of `DEEPSEEK-GRENADE-RING-TASK-2026-11-10.md`):
   - op `grenade_scatter`;
   - the shared "going gets tough" rule in `core/combat.py`;
   - stats `scatters_fired` / `scatter_rounds` / `scatter_kills`.
5. **RE4 Switch: a native call harness, then its flash.**
   - RE4 has none, and the doctrine leaves about half of RE4's threat ticks unanswered for want of a flash.
   - Build the harness on the RE5 / RE6 controller's design: code only into never-executed zero padding through the
     backing file, a data trigger, a mailbox, read-back, the "Uncertain" recovery.
   - Prove first, on the live title, that the trigger never needs an executed instruction rewritten.
   - Then call the blast routines Hermes found: `system/gbox/mercs/titles/re4_switch_blasts.py` and
     `system/docs/research/re4-switch-grenade-flash.md` (#9436). They give the flash at main+0x2E4E50, the grenade at
     main+0x2E48B0, the area attack at 0x33B770 and the radii.
   - Deliver, in this order:
     1. the flash at his position (a controller op the doctrine can call, like RE5's `flash_now`);
     2. the RE4 ring;
     3. the RE4 barrage.
   - Tell the RE session when the flash op exists. Wiring it into `respond.py` for RE4 is a one-line Kit change.

## 3. How to work

- **Setup.** Worktree on the i9: `git -C C:\_tools\gBox worktree add <dir> -b ds-<topic>-20261110 origin/main`.
  Commit, push the branch, append each step to your lane log `system/docs/ds-grenade-ring-lane-2026-11-10.md` (or a new
  `ds-<topic>-lane-2026-11-10.md`), and push that too.
- **Live sessions.** Find the live one with `GET /api/mercmode` (host lilspark, `current_run`). Read and write its memory
  only through the gBox API's session memory jobs. Frames: `GET /api/sessions/{sid}/frame.jpg`. Bot telemetry:
  `GET /api/autoplay/telemetry/{sid}`.
- **Your titles' turns.** The queue plays RE4, RE5 and RE6 in 5-round blocks. Your live test needs the matching title.
  Use its block; don't ask for the queue to change unless a block never comes.
- **Restarts.** Title modules hot-reload on deploy, but a running RE4 bot keeps its boot code until the next session.
  `interventions.py`, `merc_live_controls.py`, `tools.py`, `screensaver.py` and new modules need a `gbox.service` restart.
  Ask for it in the lane log.
- **Evidence for every claim.** Session id, frames before and after, the counters, and which parts are static only.

## 4. What the RE session needs back

Per item: branch and commit, tests run against the baseline, live receipts (or "static only"), and what is still
missing and why. Put it in the lane log. The RE session reviews and merges from there.
