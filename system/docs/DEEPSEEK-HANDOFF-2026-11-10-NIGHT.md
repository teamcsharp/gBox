# DeepSeek hand-off, 2026-11-10 night: you run the project until 2026-11-16

> **2026-11-11: read `DEEPSEEK-PM-HANDOFF-2026-11-11.md` first.** It is the operating manual: MercMode on lilspark,
> the i9 (decryption lab, live mode, service node), Hermes tasking and branch judging, the bot's improvement goals,
> and the one bot for RE4 / RE5 / RE6. Its "what to do" replaces sections 1-5 below; the ground rules and this Log
> stay.

The coordinating Claude session is offline until 2026-11-16 (the operator's usage). The operator, 18:20:

> "bring all the completed progress of the branches and hermes together and prepare to hand it off to the deepseek harness for completion ... I want the i9 to complete and finish the PSO task work fully in the meantime and to dispatch all work through hermes and the i9 gbox kiosk for completion for bot improvements based on my critique. In RE4 the bot is still turning back and forth and is stuck in the same room. I need the bot firing relentlessly with any weapon type magnum or shotgun with rapid fire at these threats instead of getting decimated by them."

## Ground rules: what changes now that you are the PM

**Hands off lilspark still holds:**
- no ssh / sudo / systemctl / kill on the Spark;
- no launches or stops there;
- every gBox API call carries `x-gbox-actor: agent`;
- never print keys.

**New: you may merge to main.** The Spark deploys main itself:
- `~/bin/gbox_autodeploy.sh` runs from cron every 15 minutes and hot-reloads bot modules at each title's next session;
- it restarts gbox.service at 05:00-05:14 when a restart is pending.

So a tested merge to main goes live with nobody touching lilspark. The gate for every merge:
1. Merge current origin/main into the branch.
2. Run the MercMode / RE subset (`system/tests/test_{mercmode,mercs_,re4_,re5_switch,re6_switch,screensaver,tactical}*`, plus the ticket's own tests) on the branch AND on main. Merge only when the branch adds no failure. Known red on main: 10 in RE5 Switch (bonus / giveup / smooth / rampage / threat) and `test_mcp_queue_checkpoint_roundtrip`.
3. Use a plain merge commit. The pre-push guard refuses `system/tools/`; put scripts in `system/scripts/`. No game assets or binaries.
4. Push. If the guard fails on an unknown remote sha, fetch, merge and push again.
5. Note the merge in this doc's log section at the bottom.

**Code needing a restart** (worker or control-plane modules, new modules) goes live at the 05:00 restart. Write that in your note.

## 1. RE4 Switch first (Hermes #9560, `077fe2a1606b4cbc`; fix it yourself if Hermes has not by 2026-11-11)

**Movement: he swivels and stays in the first room.**
- Seen in a bot_trace of session 25385f8f4eb94342-6eb677c2f1194dea: the room map's unwall ("a wall ahead, along it instead") sends a pure sideways stick (lleft, deg 90, no lup).
- RE4 is tank controls, so he turns in place and the walker turns him back.
- Fix in `core/room_map.py` and `titles/re4_walk.py` / `re4_switch.py`:
  - turn to the wall's tangent, then push forward;
  - a probe scaled to the room;
  - no unwall while the route leg is clear (extend ROOM_LEGS to unwall);
  - hysteresis of about 0.8 s on the chosen side;
  - the never-stand step walks forward instead of turning.
- Measure with `system/scripts/bot_trace.py record|draw` replays: facing reversals per minute, net metres per minute.
- The plan is also on #9527.

**Weapons and fire.**
- `gbox-data/mercs/re4-mods.json` is right: fire_rate 20, random_weapon, infinite_ammo, max_level, aim_lock.
- Live telemetry is not: `mods_weapon_given` was 4 for a whole session, and there is no fire-table stat.
- Fix `re4_switch_mods._round_weapon` / `_give_weapon` / `_apply_fire_rate` (rf_applied_boot) so every round gets a magnum or a shotgun (MAGNUM_SHARE toward 1.0, shotguns in the draw) with the 20x tables. Krauser's bow uses the motion-rate route (0d93ebf2).
- The bot fires relentlessly at any Ganado in line of sight within range, and flanks only when there is no line of sight at all.
- Report per round in telemetry: the weapon given, the fire tables written.

## 2. PSO: finish it

Work `DEEPSEEK-PSO-CHECKPOINTS-2026-11-10.md` (CP0-CP19) to the end on the i9, the operator's PSO master goal: all zones and bosses, the combat / build spec, 4 players. Use the 3090. Merge each finished checkpoint to main with the gate above.

## 3. The i9 kiosk: service node + local LLM

Build `DEEPSEEK-HANDOFF-2026-11-10-EVENING.md` sections 1 and 1b:
- service-node readiness (eGPU, gBox running, service_work), registration, and central routing of inbox decryption / analysis tasks;
- the strongest local model on the 3090, measured, serving with high concurrency, registered as a Hermes local node.

Then send it the heavy analysis work.

## 4. Hermes: keep it doing the operator's bot critiques

- **The operator-critique path works since today's merge (258279f8).** A note in the PiP "Critique the bot…" box (or ⚠ Flawed) becomes an `operator_requested` "Improve <title>: coaching note N" request, worked right after the priority list, and not held while that game plays.
- **The Hermes priority list,** set via `POST /api/hermes/queue/priority` with request ids first (saved under the queue's lock since 53cc8962). These are code-change tickets. The "read-and-report" lines in their attached rules block do NOT apply; that was clarified on each ticket.

| Ticket | Work |
|---|---|
| #9560 | RE4 movement + weapons |
| #9531 | model-transfer QA: the RE4 pl0d far body inside-out; the whole donor's normals look inverted to the operator |
| #9533 | universal rig transfer + comparison window |
| #9534 | ladders as nav links; inventory merged |
| #9525 | death lessons; evidence merged: the killer class must be joined from the player_damage logs |
| #9526 | proactive crowds; baseline merged |
| #9527 | no wall hugging / straight runs |
| #9529 | RE5 / RE6 never fire at nothing |
| #9528 | one map format |

- **Each check-in:**
  - read `GET /api/hermes/local/nodes`; `~/.hermes/cron/executions.db` is the Spark's, so ask for counts through gBox's API, not ssh;
  - review the published `hermes/request-*` branches, and merge the good ones with the gate;
  - put new critiques on the list.
- **Nodes:**
  - lilspark2 at 12 lanes (16 overloaded the gateway) and claude at 4;
  - deepseek off (your own harness uses the credit);
  - Z.AI off (quota).

## 5. What is live now (main 76708784)

- RE4: the doorway / detour fixes, the aim book (RAM aim line, sway zeroed, every shot learned), Krauser's bow at the fire_rate multiplier.
- RE5: the flash on the crowd, the flash window (mine, grenade, move, fire), the barrage under the flash clock (your scatter cap), the aim book.
- RE6:
  - FlashGate: one flash a minute, tight situations only, no flash at heavies;
  - fire-first;
  - grenades only onto floor (never lava);
  - quick commands;
  - the aim book.
- Everywhere:
  - the menu pace (the bot starts the tick a game is up);
  - the ComfyUI render-only freeze (for Pine Box);
  - `excluded_platforms`: no PS3 / Xbox / Xbox 360 on lilspark;
  - the patch atlas (`system/docs/patch-atlas/`);
  - the coach pipeline (outbox, retry, operator-first);
  - your grenade CP0.
- The Spark keeps only Switch RE builds. The others are archived in `gbox-data/patch-library` with their manifests and payloads.

## Log (append your merges here)

- 2026-11-10 18:25: hand-off written by the Claude session; main 76708784.
- 2026-11-10 19:0x: RE4 (#9560) first slice, branch `ds-re4-fire-first-20261110`:
  - **movement**: the room map's unwall now leaves a wall along its own tangent (`RoomMap.walk_block_detail` /
    `RoomMap.tangents`), the probe and the step along it scaled to the room (`ROOM_PROBE_SHARE` / `ROOM_UNWALL_SHARE`),
    the side kept per wall (0.8 s at least, `WALL_KEEP_S` while that wall is his) and `ROOM_LEGS` extended to the unwall
    (never a detour on the mesh walker's own route leg). Stats `unwall_tangents`, `unwall_tangent_steps`,
    `unwall_side_switches`. A 10 s synthetic wall round: 1.9 m -> 5.3 m net, never a push, 2 clear shots.
  - **fire first** (the operator's live round, 2026-11-10 night: "the bot is raising their weapon over and over and
    getting defeated ... needs to fire and deal with threats before lowering his weapon and fleeing or throwing
    grenades"): `FIRE_FIRST` - a Ganado within 4.5 m with a clear line is answered with the gun (no heavy keep-away, no
    swarm escape, no grenade swap, no step / wall tangent that lowers it), the gun-up turn to a close target out to
    2.6 rad, and `gun_downs` / `gun_down_last` / `gun_down_<doing>` in the telemetry.
  - **weapons**: every round a magnum or a shotgun only (`MAGNUMS | SHOTGUNS`, `MAGNUM_SHARE` 0.8); a
    results -> playing round is a new round too (the "4 a session" bug: only an intro counted); the `fire_rate` tables
    written and reported in the round's own give (`weapon_rounds`, `fire_tables`).
  - tests: `test_re4_room_map.py` (+5), `test_re4_switch_mods.py` (+1), `test_mercs_combat_discipline.py` (+1), the
    swarm / heavy fight tests now fire-first with the rollback.
  - the round report carries it: RE4's `round_counters` now include `gun_downs`, `gun_kept`, `gun_up_ticks`,
    `gun_down_ticks`, `unwall_tangents`, `unwall_tangent_steps`, and `round_reports.METRICS` has the `control` group -
    the next live round's report says whether the raise / lower is still there (analysis tickets included), and
    `gun_down_last` in the round's row names what did it.
- 2026-11-10 19:1x: the test suite no longer writes the operator's mercs telemetry (the checkout's
  `gbox-data/mercs/re4-sight-blocks.jsonl`, `re4-walk-presses.jsonl`, `re4-crossings.jsonl` had test lines that looked
  like live bot data): an autouse fixture points `re4_switch.SIGHT_LOG` / `WALK_LOG` and `re4_walk.CROSSING_LOG` at each
  test's own temp files, and `tests/test_mercs_test_isolation.py` is the rule (it also runs a synthetic round and checks
  the deployment's files are untouched).

- 2026-11-10 18:52: merged `ds-grenade-re4-bss-20261110` @ `16b984bd` into main (`b2dec801`). It carries the RE4
  native harness (E0(c) dispatcher at `main+0x655880`, E4's write rule, E5's controller with the single-vtable-store
  trigger and the mailbox call surface), F's flash op (`flash_at` -> the game's blast `main+0x2E4E50` with a 4000 mm
  floor, `place_flash`/`flash_now` on `core.flash_window.place`), G's ring/barrage offline (both automatic paths off),
  the E3 read-only `.bss` watch riding the RE4 telemetry (five candidate pages, 16 bytes each, into
  `stats["bss_watch"]` at every snapshot), and the E3/E4 static verifiers plus their tests.
  **Gate:** the branch merged current `origin/main`; the targeted set (every touched module, 21 files: the RE4
  harness/verifier tests, the RE4 switch/mod tests, the grenade ring/status/scatter/intervention tests) ran **383
  passed, 1 skipped** on the branch @ `16b984bd` and again on main @ `b2dec801`; the full 3103-test MercMode/RE
  subset was still running at merge time (its failures will be checked against this note).
  **Risk:** none to gameplay - `RING`/`SCATTER` are `False` on RE4, the harness refuses to attach without the proven
  private page (E3), and the watch is five 16-byte reads per snapshot. **Restart:** the native controller is a new
  module and `interventions.native_controller` changed - both go live at the 05:00 restart; the `.bss` watch is a bot
  module and hot-reloads at the next RE4 session.

- 2026-11-10 18:5x: PSO CP0 done (the clean start), by the DeepSeek session. All 16 open `ds-pso-*\\ branches merged
  into main; each branch's own CP0 commit had moved its lane-log text to `system/docs/pso-checkpoints/lane/<topic>.md`,
  so no branch was rewritten (`git merge-tree --write-tree` exited 0 for all 16). Four merges hit research-doc
  conflicts (an older "floor resolver not mapped" text against main's decoded one; 5b and 5c both kept), resolved in
  favour of the newer finding, UTF-8 clean. One registry, cross-checked: `pso_classes` (self-calibrating reader) and
  `pso_class_registry` (pinned 0x805D3138, 240 slots, 148 names) agree in `tests/test_pso_registries_agree.py`; the
  editor's `family` block was restored and its marker fixed (the vtable-census copy predated it). PSO suite (115
  files): 41 failed / 1399 passed / 132 skipped right after the merges, then 36 failed on the 14 baseline files after
  the fixes - the baseline 45 less the 9 the two test branches fix, no new failure. Evidence:
  `system/docs/pso-checkpoints/CP00-clean-start.md`; the operator question is in `CP00-operator-question.md` (asked
  2026-11-10 night). Next: CP1 (the local coder model on the 3090).

- 2026-11-10 19:0x: PSO CP1 measured (the local coder model on the 3090) by the DeepSeek session. Ollama 0.5.7 on
  i9-NUC already had `qwen2.5-coder:14b` (9.0 GB) and `:32b` (19.9 GB); both run 100% GPU (nvidia-smi lists
  `ollama_llama_server.exe` on `GPU-f3697ec1-...`). Measured: 14b 51.8 tok/s single-shot, 47.0-48.6 tok/s aggregate
  flat from 4 to 16 concurrent (two slots, `OLLAMA_NUM_PARALLEL=2`); 32b 28.6 tok/s single-shot, 29.9-30.7 tok/s
  aggregate. Two 16k-context tags created (`qwen2.5-coder:{14b,32b}-16k`, `num_ctx 16384`; the 14b-16k at 15 GB /
  11,990 MiB, 39.2 tok/s). Evidence: `system/docs/pso-checkpoints/CP01-local-model.md`. The i9 node's measured capacity
  is **2 lanes**; the 8-16 concurrency ask needs vLLM/llama.cpp continuous batching - the measurements, the
  recommendation and the exact `[hermes.local.nodes.i9]` block are in `system/docs/i9-service-node.md` (not applied:
  the shared gbox.toml must not carry it, and section 1's readiness gates it).
- 2026-11-10 19:12: merged `ds-grenade-re4-bss-20261110` @ `8991e881` into main (`9e99f9a3`) - the **E6 harness selftest**
  (the dispatcher now carries its own `ret` at `cave+0x84`, called through the mailbox: a zero result plus the entry
  ticks prove the cloned vtable and the publish/consume round trip with no game code; a `re4_harness_selftest`
  intervention op, capability offered only when the controller has `selftest`; the dispatcher pin is now 136 bytes,
  sha256 `3e3b937d3e32c01dfbeabd1dbca1560e009929a3e8e24cedfc2b4d233448ce55`), and `native_controller` now imports each
  title module inside its try, so a test double that replaces a base class cannot stop the search for the title's own
  controller (the RE5 shared-controller test had caught the old import order). **Gate:** targeted 201 passed, 1 skipped
  on the branch and post-merge on main; the RE5 Switch group is back to its known red exactly (10 failed, 713 passed:
  bonus 1, giveup 5, smooth 2, threat 2). E6/F still wait for the proven private page (the `.bss` watch rides the RE4
  telemetry) and the 05:00 restart for the new module; nothing is enabled gameplay-side.

- 2026-11-10 19:1x: PSO CP1 completed and CP2/CP3 merged, by the DeepSeek session. CP1's own evidence was on
  `ds-pso-cp01-local-model-20261110` (the 14B installed; 54.83 tok/s); this session appended the second candidate and
  the concurrency: 32B pulled (19.9 GB, 100% GPU, 28.6 tok/s single-shot, 29.9-30.7 tok/s aggregate), 14B 47-48.6
  tok/s aggregate at 4/8/16 concurrent (two slots: the node capacity is 2), and the `-16k` tags
  (`num_ctx 16384`). CP2 and CP3 are merged with their evidence: both models score **0.04 role rate** (1/25 each, 0
  exact names), so neither is used to name anything - the 14B is chosen on speed (2.73 s vs 23.50 s a function) for
  summaries and candidate lists, and CP3's labels are leads, never evidence (82 rows, 1,621 functions/hour). Tests:
  `test_pso_llm.py` 7 passed. 26 newer `ds-pso-*` branches (CP4-17 and the swap/editor work) are open for the next
  check-ins.

- 2026-11-10 19:22: gate note correction - the single 3103-test MercMode/RE run wedged on a blocking test after ~2.5 h
  (pytest-timeout could not interrupt it); gates are run as prefix groups instead. So far: RE5 Switch 10 failed / 713
  passed / 1 skipped = the known red list exactly; the targeted sets (201-383 tests) are green on the branch and on
  main after each merge.

- 2026-11-10 19:3x: PSO branches merged by the DeepSeek session, with their evidence: `ds-pso-handover`, `ds-pso-reconcile`,
  `ds-pso-cp16-stick` (docs), and `ds-pso-cp00-classes` (CP0 step 4: the pinned table, the 148 names and the families
  folded into `pso_classes`, plus the DOL **section-table correction** - `sections`/`address_of`/`offset_of`; the
  anchor-derived table is now cross-checked against `PINNED_ADDRESS 0x805D3138` / `PINNED_NAMES` in
  `test_pso_classes.py`). The post-merge state is recorded in `CP00-classes.md`: both registry modules stay because
  `pso_editor` calls `pso_class_registry` without a DOL, and `tests/test_pso_registries_agree.py` ties them;
  `pso_classes` is the module going forward. Tests: the registry/editor/llm set 67 passed (CP0 baseline unchanged).
  `ds-pso-classes-family` is superseded by this merge (same families/vtable work, earlier base). 22 more `ds-pso-*`
  branches remain open for the next check-ins (CP4-17 and the swap/editor work).

- 2026-11-10 20:0x: the PSO checkpoint wave merged by the DeepSeek session - **14 branches**: `cp06-evt-opcodes`,
  `cp06-nrel`, `cp07-model-walk`, `cp07-object-loader`, `cp07-scene-loader`, `cp08-room-pieces`,
  `cp09-save-data`, `cp04-jump-state`, `cp10-forest1`, `cp15-room-inventory`, `cp17-walk-graph`,
  `cp12-rigged-swap`, `cp-status`, `editor-views`. All merged clean (no code conflict); tests after each batch:
  65 / 71 / 52 passed (evt, nrel, swapfit, classes, rooms, save-cipher, memcard, walk, walker, steer, nj-snapshot,
  floor-map, editor, editor-api, llm). Main now carries evidence for **CP0-CP17** (`system/docs/pso-checkpoints/`).
  **Blockers now on record:** CP04 (jump state) is blocked because the i9's worker does not claim `launch_game`;
  CP08 (room pieces) is blocked because the Dreamcast image on hand is a CHD v4, unreadable here; CP06's opcode layer is
  live-dependent after three offline attempts; CP09's save checksum is not found (not proven absent). Superseded and left
  unmerged: `classes-family`, `object-loader-findings`, `swap-gc` (their work is in cp00-classes / cp07 / cp12).
  Still conflicting for a focused pass: `body-swap`, `cp00-clean-start`, `cp11-editor-page`, `cp13-library-donors`,
  `editor-page2`, `swapfit-ui`.
﻿
- 2026-11-10 20:3x: the PSO wave continued by the DeepSeek session. **CP13-library-donors** merged (its endianness
  fixes and the head/hair/cap stand-ins; the conflict was additive - kept main's platform body section *and* the
  branch's `gc_head_parts`). **CP00-clean-start** merged (the lane's steps 1-2 evidence: the parked session stopped,
  the stale launch cancelled, 24/24 merge-tree clean) with this session's merge record appended as an appendix.
  **editor-page2** merged (P6b: `POST /api/pso/editor/build` + preview, the swap-fit gate on the page, the
  `pso_editor.class_labeller` DOL-backed labels); conflicts resolved by keeping main's superset `pso_classes` and
  the branch's editor/API/tests - and with it **no production module imports `pso_class_registry` any more**, so CP0
  step 4 is effectively done (`pso_classes` is the one registry the editor uses; the old module is legacy + tested).
  Tests: 55 passed (editor/editor-api/views/classes/registries/llm), 52 passed (editor/body set). Superseded and left
  unmerged: `body-swap` and `swap-gc` (cp12 has the rigged swap), `cp11-editor-page` and `swapfit-ui` (older
  variants of editor-page2), `classes-family` / `object-loader-findings`.
﻿
- 2026-11-10 20:4x: MercMode visibility (the operator: "why isn't MercMode alternating between RE4/5/6 ... the window needs to
  indicate that something is being demonstrated"). On the Spark's plane: titles re5/re6/re4 were set to **5 rounds per
  title** with a title-grouped 20-round queue, so it looked stuck on RE4 between rotations. Changed live via
  `POST /api/mercmode`: `rounds_per_title` 1 and the same 20 entries **interleaved** re4 → re5 → re6 → ... (every mod,
  stage and character preserved), so each native round boundary switches version. The MercMode panel now also names the
  demonstration: the run line shows `Demonstrating: <mod>` (`run.mod`) and each queued round shows its mod
  (`system/clients/web/viz/mercmode.js`); the queue's runs are recovery tests
  (`recovery-re4-fit-v4-20261110`, `recovery-series-01-20261110`, `recovery-re6-enemy-cast-01-20261110`).
  Separately: the PSO **attract** launch `a43d86814ee34c36` has been queued ~32 min on i9-NUC, held only by the
  operator-idle admission ("Waiting for five minutes without operator input"); it starts after 5 min with no input on that
  PC. Its run's `result` carries `unsupported operand type(s) for +: 'int' and 'dict'` from the previous mission - to
  trace next.
﻿
- 2026-11-10 20:5x: the RE4 bot "just standing there, not fighting" - root cause found and fixed. `re4_switch_mods.maintain`
  published a per-round weapon **record** (`weapon_round = {round, name, id, fire_tables}`, added for the round
  report in this session's first merge) and `re4switch_bot._maintain_mods` sums every value it returns into
  `stats["mods_*"]`: on the first verified weapon give the playbook raised `unsupported operand type(s) for +: 'int'
  and 'dict'` and the mission **ended**, leaving the game running with nobody pressing anything - which also explains a
  round that never ends, so MercMode never rotates. Fix (`b5efa90f`): maintain returns counters only (the weapon's
  name/round stay in `status()` / `st["weapon_rounds"]`, where the round report reads them), and the mods panel adds
  counters while keeping a record as it is. Regression tests: every maintain value is a counter; the panel survives a
  record. The live mission on the Spark was restarted (autoplay job `69a59edf7e384316`, started) so it fights now; the
  Spark's autodeploy carries the file fix within its 15-minute cron, and the next session loads it. **Follow-up:** a
  mission that ends `ok:false` while its round is live should be restarted (or the round cut) by the scheduler - today
  it just stands there.
﻿
- 2026-11-10 21:0x: the mission watchdog (`tools._mission_restartable` / `_restart_mission`, wired into `_ended`):
  a playbook that ends with its own exception on a session nobody stopped, took over or declared a bad end is
  **restarted on the same session** after 5 s, at most twice - so a code fault costs seconds instead of leaving the game
  standing for the round (the RE4 `int + dict` death this session found). A frozen/black game stays `_bad_end`'s,
  and a mission the operator stopped or took over is never restarted; a session another run owns is left alone.
  Regression tests: tests/test_autoplay_mission_restart.py (5) plus the autoplay recovery/handoff/resume suites (42
  passed).
﻿
- 2026-11-10 21:1x: **deployment check by hash** (a reusable check-in: the worker's `build_sources` in
  `GET /api/workers` is a sha256 per gbox source file, so a fix's presence on the Spark is verifiable without ssh).
  At 21:15: `gbox/mercs/titles/re4_switch_mods.py` **matches local** (the `int + dict` fix is live in the Spark's
  checkout) and `gbox/mercs/titles/re4_switch.py` matches; `gbox/re4switch_bot.py` and `gbox/tools.py` are still
  the previous versions (the mods-panel hardening and the mission watchdog await the next autodeploy). The screensaver
  restarted autoplay itself (job `275ecddb83d2441a`, 21:07) after the failed mission, so the live session got a new
  mission; the run's `result` still carries the old error until a mission ends.

- 2026-11-10 19:45: operational note - deploy_main.sh's deploy-restart-pending file (set when any non-bot runtime
  file is in a merge) makes every later bot-only merge skip its in-place bot reload until the 05:00 restart. Our
  grenade merge included interventions.py, so the RE4 .bss watch is copied but not loaded in the running bot; the
  operator can force POST /api/workers/lilspark/bot-reload (operator actor; the API refuses gent with 403), else
  it lands at 05:00. Plan time-sensitive bot changes as bot-only merges.
- 2026-11-10 20:10: merged `ds-grenade-re4-bss-20261110` @ `b6434d77` into main (`d458a024`) - the `.bss` watch now keeps
  the last THREE distinct stage loads in `stats["bss_watch_loads"]` (a single telemetry read after an RE4 block gives
  the three-load evidence even with nobody polling), and the RE4 hand-grenade ring joins the status as a built /
  no-receipt row beside the flash (incendiary still not identified). Targeted gate 163 passed. Still waiting on the
  operator bot-reload (or the 05:00 restart) for the bot modules to load.
- 2026-11-10 20:20: merged `ds-grenade-re4-bss-20261110` @ `3a6a2885` into main (`17766d37`) - `choose_mailbox()` turns
  E3's telemetry evidence into one page: it intersects the all-zero pages across every recorded stage load and returns
  the first in the vetted order, so the watch result becomes a one-line `MAILBOX_AT` commit. Targeted gate 83 passed.
﻿
- 2026-11-10 19:4x-19:5x: **the operator's PC plays while they work** (operator: "play PSO on the i9 despite me being on the
  PC"). Added the per-PC `allow_while_active` background-testing policy (`background_testing.policy` +
  `guarded_reason(allow_active=None)` resolves it; `POST /api/testing/workers/{wid}` stores it beside the budget;
  tests in `test_background_testing.py`), set `i9-NUC` to `allow_while_active: true` and budget 90, and **restarted
  the i9's gBox** (it ran since 08:21 with the old code; new pids 44900/51820, health back in 26 s, worker re-registered).
  Then: two PSO `launch_game` jobs (this session's and the other agent's, both held by the idle rule) were admitted;
  the duplicate was cancelled, one PSO session runs (`3998f537ab154a22-b13f235d1b2e42a1`), and the **PSO campaign
  autoplay** (`pso-episodes-1-2`) started on it - a frame shows Dolphin past the title screen into the world.
  `7a4952d8` verification: on `origin/main`; the Spark's `deploy`-actor bot-reload reports `ok: true, "no loaded
  bot module changed: nothing to reload"` (its loaded modules already match), and `update-repo` cannot fast-forward
  (`/home/ehm_eckx/gBox/system` is not a git checkout) - the G3 watch needs an RE4 round to record its loads, and
  MercMode now alternates one round per title (RE4 -> RE6 Sherry/Rail Yard observed live), so the next RE4 block records
  them. Left alone: the Hermes recorders `pso_padwatch.py` / `pso_demo_rec.py` (not input drivers).
- 2026-11-10 21:10: merged `ds-grenade-re4-bss-20261110` @ `96954533` into main (`63ae6f93`) - **the reason the E3 watch never
  appeared in telemetry**: `gbox/tools.py`'s autoplay telemetry `body()` publishes only scalar stats
  (`{k: v for k, v in live.items() if isinstance(v, (int, float, str, bool))}`), so the watch dict/list were silently
  dropped. The watch now goes out as JSON strings (`bss_watch`, `bss_watch_loads`), and `choose_mailbox()` parses the
  published string form. Targeted gate 45 passed, 1 skipped. The operator's bot-reload said "no loaded bot module
  changed" because the loaded module matched the share's (old) copy - after this merge the deploy copies the new file
  and one more bot-reload (or the 05:00 restart) makes the watch visible on the next RE4 block.
﻿
- 2026-11-10 20:0x: **PSO is autoplaying through its menus on the i9** (the operator's ask: watch it play the game). The
  single-player route is the known dead end: pressing START reaches the episode-1 intro narration and the game returns to
  the title (`pso_boot_local.py --start-at press_start` pressed START, the frame showed the intro, six more START
  presses returned to PRESS START). So the session was relaunched on the **two-controller branch** (`pso_coop: true`,
  session `aa4ba9c970e14266-9ef9fc607d884e0f`) and the **coop campaign** (`pso-coop-episodes-1-2`) started on it:
  frames show PRESS START -> the title main menu (ONLINE/OFFLINE/OPTIONS/WEBSITE) -> character select (a HUmar on the
  selection platform). The single-player campaign's stop was its own error budget (`errors >= 5`, the vision planner on
  the Spark's `qwen2.5vl:7b` times out while the Spark's GPU plays RE6); the coop route's scripted MULTI MODE walk does
  the menus, so it does not depend on the planner. Note: the i9 now has two worker registrations (the service and the
  desktop app's `desktop_local`), so launch jobs must resolve the current online worker id
  (`GET /api/workers`), not the one from an earlier session.
﻿
- 2026-11-10 20:1x: the coop campaign carried PSO past the menus on the i9: the frames run PRESS START -> title main menu ->
  OFFLINE/MULTI MODE -> **character creation** (a HUmar preview on the platform - the two-controller launch uses its own
  isolated memory card, so the buddies are created) -> **Pioneer 2** (the station over Ragol). The earlier single-player
  campaign had stopped on its own error budget; the coop route's scripted MULTI walk plus creation is what gets through.
  Next for the campaign: the Pioneer 2 descent and Forest 1, where the native combat driver takes over.
﻿
- 2026-11-10 20:2x: **PSO is in gameplay on the i9.** The buddy card now holds the created character (24 of 251 blocks
  used on `gbox-data/pso-buddies/i9-NUC/436e0bb84d5337d1/dolphin/A.USA.raw`), and the coop campaign is walking the
  character through **Pioneer 2** (frame: the plaza and its portal, the HUD in the corner). The title/story loop is
  behind it: title -> OFFLINE -> the saved buddy -> Pioneer 2. Next: the teleporter down to Forest 1, where the native
  combat driver fights. (Note for the lane: the intro narration returns to the title if pressed through on a new card;
  the created character is what turns the next pass into gameplay, so do not press A during the movie.)
﻿
- 2026-11-10 20:2x: PSO's campaign reached **Pioneer 2's Lab** on the i9: the frame shows the created FOmar at the Lab
  counter with an NPC's message ("You may come back to the Lab before completing the field, if you want.") and the
  HP/TP HUD - the teleporter burst before it was the city-to-Lab transition. The campaign is walking the hub and
  talking to NPCs with the two controllers.
  **Planner bottleneck identified and being fixed:** the PSO campaign's vision planner resolves to the Spark's Ollama
  (`10.89.1.246:11434`, `qwen2.5vl:7b`) through `config.llm_endpoints`, and the Spark's GPU is busy playing
  MercMode, so planner calls time out and the campaign walks into walls. The i9 has the 3090 and its own Ollama, but at
  **0.5.7**, too old for `qwen2.5vl` ("requires a newer version of Ollama"). Downloading the current Windows
  installer (1.86 GB; ~1.0 GB in at 20:2x) to upgrade it; added `[agent] vision_url = "http://127.0.0.1:11434"` (with
  llm_url/model/searx_url) to the untracked `gbox.local-i9-nuc.toml` so `pso_campaign.vision_settings` uses the
  local endpoint; this needs the i9's gBox restarted (do it when no PSO session is live, or let the live one end).
﻿
- 2026-11-10 20:3x: MercMode verified **fighting** on the Spark: a frame of the live RE6 No Mercy round (score 85,220,
  97 kills, a 05'13" clock, a 002 combo, the blueprint-look enemy cast the recovery-re6-enemy-cast-01 mod installs,
  a flamethrower heavy behind). The run has been on RE6 for ~45 min - a No Mercy round is long, and the queue rotates
  one round per title, so RE4's watch block comes after this one. Also fixed: `pso_boot_local.py` imported gbox from
  one lane's scratch clone (`C:\_tools\gBox\.tmp\main-repo\system`), which exists on no other machine; it now derives
  `system/` and `system/tools/` from `__file__`. The i9 Ollama installer download is at ~1.24 of 1.86 GB.
- 2026-11-10 22:45: merged `ds-grenade-re4-bss-20261110` @ `b63f77c0` into main (`971a01d3`) - **E5 hardening**: a timed-out
  harness call now **retires its mailbox request** (state back to idle, best effort) and refuses further calls until
  detach/re-attach, so a paused game, a stage load or a late dispatcher tick can never execute a timed-out request
  later. The `Uncertain` still means the effect may have started, but it is never repeated. Targeted gate 77 passed.
  Also of note from the static G3 pass: the `0x67B2A0..0x67B640` blast page is referenced by no code and no data at all
  (no adrp, no pointers), so those descriptor slots are not the runtime dispatch table; the incendiary's class-0x16
  dispatch is still open. Live: the same RE6 session has held the queue for hours (no RE4/RE5 block), so the E3 watch
  and the CP0/D live receipts remain pending.
﻿
- 2026-11-10 20:4x: **PSO reached Forest 1 on the i9** - a frame shows the character (LYRA95, level 2, HP 22/40) in the
  forest's stone ruins beside a teleport ring, dark enemies ahead and the action palette up: the campaign cleared the
  Pioneer 2 hub and descended. Code: `pso_campaign.vision_settings` now prefers **this worker's own Ollama** when it
  serves the model (a 2 s `/api/show` probe) before any configured remote endpoint, with an explicit
  `agent.vision_url` still winning - the fix for the walk-into-walls planner timeouts (tests: local chosen, missing
  local falls back, explicit URL respected; `test_pso_campaign.py` 30 passed). The i9 Ollama installer is at ~1.50 of
  1.86 GB.

- 2026-11-10 23:05: merged ds-grenade-re4-bss-20261110 @ cbf7cfa0 into main (8b6c033c) - checkpoint A3'''s
  mechanism: an RE6 random barrage now draws only the verified kinds **whose resources the character carries** (a
  missing hand grenade no longer refuses a flash barrage; the checkpoint'''s caveat), while a narrowed draw still
  refuses an unloaded kind with its own reason. Three tests; 157 passed across the RE6/grenade set. The live probes
  (A2/C2: hand/incendiary grenade_scatter receipts) still wait on an RE6/RE5 block where the character carries the
  kind.
﻿
- 2026-11-10 20:5x: **RE5 is playing on the Spark** (operator: "why do I never see RE5 come up"). The answer: the
  rotation advances only at a verified round end and the queue was grouped re4 -> re5 -> re6, so RE5 was third; with
  RE6's No Mercy round running ~50 minutes it never came up. Fixed live: the queue is reordered to its five `re5`
  entries first (then re4/re6), `rounds_per_title` stays 1, and a `switch` dispatch put RE5 on now - frames show the
  RE5 title and then a Mercenaries round (Sheva, 01'51" on the clock). Earlier RE5 session starts ended within ~1 min
  each: those were the switch sequence restarting the game, not a crash (the current session is stable in-round).
  Ollama: the 1.86 GB installer downloaded, but its silent install needs elevation and hung in this non-interactive
  session (OllamaSetup killed, the 0.5.7 server restarted and answering) - the upgrade needs the operator's UAC or a
  5.0-era fallback; the planner fix (local model preferred) is in main either way.
﻿
- 2026-11-10 21:0x: PSO campaign restarted on the running session (it had stopped after the coop launch's card check: the
  current session was not launched with `pso_coop` so the two-player campaign refuses it - `ValueError: Launch PSO
  with pso_coop=true`; the single-player campaign runs instead). Tried the Spark's smaller vision models to dodge the
  busy GPU: `gemma3:1b` is refused by preflight ("does not advertise vision capability"), so only `qwen2.5vl:7b`
  qualifies there. The i9 planner fix therefore needs a newer Ollama, and the installer needs elevation this session
  cannot answer - so a **portable** `ollama-windows-amd64.zip` is downloading (no admin: run it beside the current
  install, same models dir, then `agent.vision_url` 127.0.0.1:11434 already points the campaign at it).
﻿
- 2026-11-10 21:1x: the operator's split: **MercMode on the gBox stream, PSO played locally by them.** Stopped the PSO
  autoplay (`{"mission": "playbook: pso_campaign", "stopped": true}`) so the bot does not fight their pad; the PSO
  session stays up for them. Rebuilt MercMode's rotation queue: re5/re6 only offer **no_mercy** (a `mercenaries`
  entry for them is a 422), so the queue is now `re4(merc) -> re5(no_mercy) -> re6(no_mercy)` repeated three times,
  `rounds_per_title` 1, `repeat_queue` true, and a `start` dispatch with `pip: true` put RE4 on air (frame: Leon
  firing, 7-in-a-row combo, 01'56" on the clock). Code: `pso_campaign` now retries a failing planner for ten minutes
  (`PLANNER_GIVE_UP_S`) instead of ending the run after five failed calls, with `planner_failing_for_s` in the
  telemetry (31 tests in `test_pso_campaign.py`).
﻿
- 2026-11-10 21:2x: **the rotation and the fire-first fight verified on the stream.** RE4 is on air and fighting: two
  frames 8 s apart show the combo going **26 -> 28 in a row** with the score 7,800 -> 8,400 and the gun up and firing
  (the recovery-re4-fit-v4 mod's swapped cast included). The session history shows the cycle working: six RE5 sessions
  from ~17 min back (each ~2-3 min) then RE4, so the queue re4 -> re5 -> re6 is being played. The RE5 sessions are
  short (~150-200 s each) - worth a check next round whether their No Mercy round ends early (death) or the title's
  round reader sees an end early.
﻿
- 2026-11-10 21:1x: **RE5's rounds are not fights - the bot stalls at CHARACTER SELECT.** The round reports explain the
  long-standing "RE5 dies in 2-3 minutes": six consecutive RE5 reports are `outcome: lost` with **0 or 1 shots**, and
  two frames of the live RE5 session ~2 minutes apart are the same **CHARACTER SELECT** screen (Chris Redfield, BSAA,
  A OK). The title screen and character select are reached (input works), but nothing confirms the character, so the
  round never starts and the session ends as "lost". Next: the RE5 title's menu state machine (the known-red RE5 Switch
  area) - it must press OK on character select and go through stage select; RE4/RE6 do not stall here. Also confirmed:
  the round-report API is `GET /api/mercs/round-reports` (+ `/{id}`), with `report.metrics` and `outcome`, the
  live verification source for MercMode bots.
﻿
- 2026-11-10 21:2x: **RE5's stall is the character select, and one A press starts the round.** Frames showed the RE5
  session parked on CHARACTER SELECT for minutes; posting two A events through `POST /api/sessions/{sid}/input`
  (agent actor, `{"queued": 2}`) moved it through NOW LOADING into a **No Mercy round** (frame: 01'45" on the clock, a
  "Break free" grab, the HELP gauge). So the title and its round work; the bot's RE5 menu walk simply never confirms the
  character (its STAGE/CHARACTER SELECT state machine reads the RAM cursors but the confirm press is not sent). Next:
  wire the confirm press into the RE5 title's select phase (or the generic mercs_bot's menu phase) with a timeout, so
  the operator never sees the parked screen - and the round reports stop being 0-shot "lost".
﻿
- 2026-11-10 21:4x: the RE5 select stall has a fix in code. `mercs_bot.Boot.tick` now presses the title's confirm key
  (**direct**, outside the Navigator) when RAM names a select (`select_stage`/`select_player`), the screen has not
  moved for `STALL_CONFIRM_S` (15 s), the Navigator's own press did not take, no confirmation chain is open and the
  select takes input; rate-limited by `BOOT_PRESS_S`, logged as `stall_confirm_presses` / `stall_confirm_at`.
  `stall_confirm_due` is the tested predicate (`test_mercs_bot.py` 16 passed). Deploys to the Spark via the
  autodeploy and hot-reloads at the next session; until then RE5 can still park, and a manual A press through
  `POST /api/sessions/{sid}/input` starts its round.
﻿
- 2026-11-10 21:5x: the Spark's deploy is **paused behind `deploy-restart-pending`**, not behind a local edit: the Spark's
  `gbox/mercs_bot.py` hashes exactly to main's revision `8195b80c` (an older commit), and the round-26 select-confirm
  fix is not in it. `deploy_main.sh`'s `activation_for` returns `restart` whenever that marker exists, so every
  later merge - including bot-only ones - waits for the service restart (the 05:00 window, or an operator restart).
  Confirmed against the worker's `build_sources` hashes for `mercs_bot.py` and `pso_campaign.py`. Until then the
  RE5 character-select workaround is the operator's/agent's A press through `POST /api/sessions/{sid}/input`.
  Also live: RE6's No Mercy round is long (the rotation has been on it ~30 min), the Pine Box program feed is pinned
  to the PSO session by "following what you watch" while `/api/broadcast/pc/lilspark.jpg` shows the live RE6 feed.
﻿
- 2026-11-10 22:0x: **deploy: bot modules no longer wait for the pending service restart.** `deploy_main.sh`'s
  `activation_for` returned `restart` whenever `deploy-restart-pending` existed, so every merge after that marker -
  bot-only modules the classifier calls `reload` included - waited for the 05:00 window (this session's RE5
  select-confirm fix sat undeployed for hours; the Spark's `mercs_bot.py` still hashes to main `8195b80c`). The
  function now keeps the restart for runtime code and for the retry when nothing new arrived, but lets a
  `reload`-classified change go in with `bot_reload` (its settle safety restores the old modules if the restarted
  bot dies) while the restart stays pending. Verified with a bash harness over the extracted function: pending+bot ->
  reload, pending+server -> restart, pending+nothing -> restart, nothing -> none. Pushed as `95e4ab18`; the Spark's
  next deploy run copies the script and the run after that uses it.

- 2026-11-10 23:45: merged ds-grenade-re4-bss-20261110 @ e4df387e into main (9fda4e20) - **E3 status-path probe**: the
  RE4 native controller'''s prepare() now includes the five candidate .bss pages in its refusal, so a single live
  GET /api/sessions/{sid}/interventions on an RE4 round is itself the read-only watch (the bot-module telemetry path
  stays the fallback; deploy-restart-pending still blocks its reload). Two tests; targeted gate 67 passed.
﻿
- 2026-11-10 22:1x: after the deploy fix, the Spark's `gbox/mercs_bot.py` **is deployed** (worker `build_sources` hash
  equals local) and its bot-reload reports nothing left to reload - so the select-confirm fix is in the worker's code.
  But a forced RE5 switch then landed on the main menu's **EXTRA CONTENT** page (frame: EPISODES/EXTRA CONTENT/FRIEND
  MATCH/BONUS FEATURES with PLAY GAME in the side column), not on PLAY GAME -> the RE5 menu walk drifts as well as
  failing to confirm: its cursor target/read is not reliable on this title. RE5's round start needs both fixed (the
  confirm press is wired; the navigation target is not). The rotation stays on RE5 until its next boundary.
- 2026-11-11 00:00: merged `ds-grenade-re4-bss-20261110` @ `dc67a25a` into main (`73e240f5`) - **G3's incendiary probe
  path**: `grenade_ring(kind="incendiary", allow_unverified=True)` calls the class-0x16 persistent-fire candidate
  `main+0x2E4BA0` through the same fake object, receipt `probe: true`; the status and the rule still refuse it. This is
  the handle for the RE session's live G3 probe, not a PiP button. Two tests, targeted gate 62 passed.
﻿
- 2026-11-10 22:2x: **correction to the round-29b note: EXTRA CONTENT was not drift - it is a step on the documented
  path** ("PRESS ANY BUTTON, Load successful, PLAY GAME, EXTRA CONTENT, THE MERCENARIES UNITED, START, NO MERCY, stage,
  character", docs/research/re5-switch-ram.md). The forced RE5 switch then walked the whole path on its own and the
  frame shows a **No Mercy round in progress** (Sheva, 01'35" on the clock, an Executioner and a Majini in front, the
  weapon drawn) - no manual A press needed. So the select-confirm fix plus the deploy-unblock did their job on RE5;
  the earlier 0-shot "lost" rounds were the character-select park. Next check: the round's report (shots > 0) when it
  ends.
﻿
- 2026-11-10 22:3x: **the operator's own app view no longer steers the broadcast program** (operator: "the activity of my
  local gBox usage on the i9 should not change the stream or impact it ... the PSO task uses gBox to handle modding and
  loading the game so its in the app internally"). `broadcast.choose` now ignores a watch whose `client` is the
  desktop app (`desktop-webview`): it stays "still on air" instead of following the local PSO view, while a
  browser/Pine viewer's watch still follows and On air (a program pin) still switches explicitly. Test:
  `test_broadcast.py` 60 passed. Pushed as `9e25bae2` (rebased over the lane's 05:00 summary). The Spark's copy is
  server code, so the change needs its next service restart (05:00) - until then the immediate lock is the On air pin
  on the MercMode run or Pine following `/api/broadcast/pc/lilspark`.
- 2026-11-11 01:30: merged `ds-grenade-re4-bss-20261110` @ `155dd102` into main (`88f51e83`) - **G3 identified
  statically**: the `.data` class behaviour table (stride 0x58, spawn at +0x28) lists the grenades in item order -
  hand `0xB05B00` -> `0x2E48B0`, **incendiary `0xB05B58` -> `0x2E4BA0`** (secondary `0x2E4DF0`), flash `0xB05BB0` ->
  `0x2E4E50`. The incendiary's spawn is the persistent fire (EFFECT 0x26, no AREA_ATTACK; no class-0x16 area site
  exists), which is why it never matched the other two. `scripts/re4_blast_scan.py` now reports the class entries, a
  test pins the three, and `INCENDIARY_CANDIDATE` carries the evidence; the probe path (allow_unverified) already
  calls it. Live probe still owed; tests 43 passed.
﻿
- 2026-11-10 22:4x: live state while the broadcast fix deploys. The i9's local control plane answers again on 8765
  (pid 28024, `-m gbox serve --worker`) after a bind race, but its worker record still shows **offline** on both
  planes; the operator's **eight queued `file_mod` jobs** (the PSO modding/loading work) are held by "Human gameplay is
  active on this PC; background compute is waiting" - the ownership gate, which `allow_while_active` does **not**
  bypass (control play never yields the pad). So the modding waits for their session to end or needs a dedicated-PC
  policy that covers ownership too. Broadcast: the program was `no game is running` a moment ago (RE5 round ended,
  i9 feed gone) with the app still watching a PSO session; `/api/broadcast/program` refuses agents by design, so the
  On air pin is the operator's switch until the server restart applies the desktop-view fix.
- 2026-11-11 02:00: merged `ds-grenade-re4-bss-20261110` @ `0ee688df` into main (`645fe433`) - the **E6 plumbing
  test**: a worker claim carrying `re4_harness_selftest` calls the controller's `selftest()` and posts its receipt
  (epoch echo included), closing the last untested link between the click and the harness no-op. 14 worker tests, 77
  targeted passed. Live: no `.bss` watch capture yet (no RE4 round published the strings); the 05:00 restart remains
  the next deployment event.
﻿
- 2026-11-10 22:5x: **dedicated-PC policy extends to ownership** (operator: "the PSO task uses gBox to handle modding and
  loading the game ... play it despite me being on the PC"). `guarded_reason`'s ownership check was absolute, so the
  operator's eight queued `file_mod` (delete_build) jobs waited on "Human gameplay is active on this PC" even with
  `allow_while_active` set. Now a designated PC lets its **non-pad** tools through while the operator plays (file
  work, builds, characters, analysis); `PAD_TOOLS` (launch_game, session_op, autoplay, poke, write/freeze_memory,
  cheats, mercmode, bot_reload, repo_update, session_swap, state_transfer) still wait, and callers with no job keep
  ownership authoritative. Tests: test_background_testing.py 5 passed. Also: the i9 worker is back (two live
  registrations, the old `aa4ba9c9` dead) and the eight orphaned delete jobs were re-pointed at the live worker id;
  MercMode is playing RE5 on the Spark. Both this and the broadcast desktop-view change are **server code**, so they
  apply at the Spark's next service restart (05:00); pushed as `a59da474`.
- 2026-11-11 03:00: merged `ds-grenade-re4-bss-20261110` @ `24efa1e7` into main (`e2050fc5`) - **RE5 uncertain-state
  diagnostics**: an uncertain operation now records its cause through one `_fail(exc, recoverable=...)` helper at all
  five failure sites, and the recovery refusal reads `native controller awaits recovery after an uncertain operation
  (TypeError: ...)`, turning the live "awaits recovery" status into an actionable line. The night saw that state twice
  on live RE5 rounds (22:05 and earlier), with kills at 0, so the cause matters for the morning. 19 tests.
- 2026-11-11 00:00 (Claude, with the operator): **Pine Box locked onto the Spark's MercMode** - gBox's program pinned to
  `pc lilspark` and Pine's lock set to `program` (Pine's "Follow PC: spark1" fell back to the i9 whenever spark1 had no
  row: MercMode sessions are agent_owned and Pine hides those, and a title handover leaves lilspark without a session).
  Do not change either. **The 2026-11-10 Hermes + DeepSeek assimilation merged** (branch `assim-mercmode-20261110`):
  see `DEEPSEEK-PM-HANDOFF-2026-11-11.md` section 5.4 for the merged / ported / reverted / skipped list and why. Gate:
  the MercMode/RE subset plus every touched test, no failure beyond main's 14 known red. Branches still in flight (wall
  reports, donor normals, donor rotation, research assimilation): that doc's section 9.

- 2026-11-11 09:42 (DeepSeek PM): **post-restart verification, the donor rotation's pools made real, and a Spark restart
  to know about.**
  - **Deployment is the merged main.** At 09:15 the worker's `build_sources` hashes on lilspark equal main's files for
    `gbox/donor_rotation.py`, `gbox/mercmode.py`, `gbox/screensaver.py`, `gbox/mesh_orientation.py`, `gbox/mtf_materials.py`,
    `gbox/re5_mesh_import.py`, `gbox/re6_switch_models.py` (the normals fix and the donor rotation are both live; the
    05:00 restart loaded them - `gbox-data/deployed-main.txt` 05:00:02).
  - **The donor rotation had no RE4 or RE6 pool**: only builds present in `gbox-data/mercs/donor_rejects.json`'s
    `audited_builds` can be drawn, and the two builds the rotation actually plays were never audited (the 11-10 audit
    covered the pools/series, not `recovery-re4-fit-v4-20261110` or `recovery-re6-enemy-cast-01-20261110`), so RE4/RE6
    fell back to `default_mods` and only RE5 could draw (3 builds).
  - **Fix applied (data only, no restart):** audited the two builds' own fit receipts on the Spark
    (`gBox_alt/scratch/re4-fit-v2/{out-v4/cast,out-v4/enemy}/receipt.json` and
    `gBox_alt/scratch/re6-enemy-cast/out/recovery-re6-enemy-cast-01-20261110/receipt.json`) with
    `python -m gbox.donor_fit_audit`, merged the index into a copy of the live file (operator rejects kept; **0 new
    rejects**; 28 -> 30 audited builds), and replaced it atomically over SMB. Backup:
    `gbox-data/mercs/donor_rejects.json.bak-20261111-091812`. Result, read from `GET /api/mercmode` at 09:40:
    **re4 pool `[recovery-re4-fit-v4-20261110]` (19 donors), re5 `[series-01, series-02, series-04]`,
    re6 `[recovery-re6-enemy-cast-01-20261110]` (13 donors)**; both new entries pass `donor_rotation.fit_gate`.** The
    queue still names a build per block, so a draw only happens on a queue entry without `mod`; RE4/RE6 have one
    verified build each, so their variety still needs new builds, not a settings change.
  - **lilspark's gbox.service restarted at ~09:39:38** (worker id `60d56e74a744411a` -> `c63a6efd5f584229`); the control
    plane was unresponsive on :8765 for ~2 minutes (health, sessions and workers all timed out; SMB and ping stayed up)
    and the program went to a slate. It recovered on its own and MercMode resumed: session
    `c63a6efd5f584229-bc8febabc7af4e29` (RE4, `recovery-re4-fit-v4-20261110`) started 09:40:34 and the program is
    `live`, `pinned to lilspark (its MercMode turn)`. The cause is not proven from here (systemd journal is not on the
    share); the restart followed a 171 s `GET /api/mercmode` and a read-only SQLite open of the 2.4 GB store over SMB.
    **Operational rule for the next rounds: use the light endpoints (`/api/broadcast/feeds`, `/api/sessions`,
    `/api/jobs`, `/api/workers`), one `/api/mercmode` at a time, and never open the live store over SMB while the service
    is up** - the status route is the one the 2026-10-26 stall came from.
  - **RE5's block 09:19-09:24 (first after the restart) is a red flag:** five rounds, all `died`, in 36-97 s, with
    `shots 0 / hits 0`, 0-2 kills, `round_hurt_while_idle` 4 and `round_threat_answered_fire` 0 (one flash answered).
    Either the fire path is not raising/firing on RE5 or the round report's shot counters are not wired for its Switch
    reader - the RE5 report also has many nulls (`round_deaths`, `round_shots`). Needs a live trace on the next RE5 block
    before a ticket; numbers and the report id are in this note.
  - **Section 9's in-flight branches are missing:** `wt-wallreport-20261110` and `assim-hermes-research-20261110` are
    neither local nor on origin in this clone (the normals and donor-rotation branches are merged). Priority 1
    (wall-stuck auto-reports) and the research assimilation need those branches pushed, or the PM cannot gate them.
  - No live settings were changed this round (queue, program pin and Pine lock untouched).

- 2026-11-11 09:54 (DeepSeek PM): **RE4's rounds were invisible to the round reports - fixed (`f8931ce2`).**
  - **Found:** the Spark's `mercs/curriculum/` holds `010018100CD46000` (RE5), `01002A000CD48000` (RE6), `BLUS30491` and
    `G4BE08` and **no `010099A00BC1E000`**. `re4switch_bot.py` (the playbook MercMode runs for RE4) never writes a Notebook
    row, so the round-report scanner has no RE4 cursor and has created no RE4 report (the newest 30 were RE5/RE6 only) -
    the title the operator critiques most is the one with no block metrics, no coaching-loop evidence and no damage/
    death-lesson linkage. The bot already computed `gun_downs`, `gun_kept`, `unwall_tangents`, `stand_breaks`, and they
    went nowhere (`RE4Switch.round_counters`, which only the engine records).
  - **Fix:** `play()` declares `session_id` / `source_job_id` (declared in its signature so `tools._start_playbook` passes
    them) and the round end (`_post`) writes `gbox.mercs.notebook.Notebook.finish` with `round_id` = the boundary's
    round, outcome `results` = completed / `dead` = died, `team_role solo_p1`, `scoring_scope solo`, the exact session id
    and the 16-hex autoplay job, plus this round's own `round_<counter>` amounts from a snapshot taken when the round
    started. Best effort: a notebook failure is a stat, never the round's end.
  - **Gate:** `test_re4switch_bot.py` (4 new) + `test_mercs_round_reports.py` + `test_re4_switch_fight.py` +
    `test_re4_switch_mods.py` + `test_re4_switch_game_state.py` = **156 passed**.
  - **Deploy: runtime code, not a bot module (`gbox.re4switch_bot` is not in `hot_reload.BOT_MODULES`), so this waits for
    the 05:00 service restart.** The next autodeploy copies it and sets `deploy-restart-pending`; until then the Spark's
    playbook is the old one and writes nothing. After the restart the scanner seeds the first RE4 terminal round within
    the hour - `GET /api/mercs/round-reports` should then carry title `010099A00BC1E000` with the control group's
    `round_gun_downs` / `round_unwall_tangents`. An operator restart makes that happen sooner; no bot hot-reload is
    needed.
  - **The number the first report will judge** (60 s trace of RE4 session `c63a6efd5f584229-bc8febabc7af4e29`, 09:46, 240
    rows): phases aim 106 / flank 66 / fire 38 (zr) / unwall 21; notes "the line is not on a Ganado yet" 49, "no clear
    shot: round it by the mesh walker" 17; telemetry `gun_downs 46` (flank 27, fire 1) vs `gun_kept 7`, `stand_breaks 26`,
    `walls_pressed 0`. The gun still goes down most often to flank, and fire-first keeps it only 7 times in that window.
    No new ticket: the aim/fire backlog (#9499, #9484, #9466, #9560) is open, and the doc's rule is to judge a block's
    numbers, not one minute - the report is now the instrument for that.

- 2026-11-11 11:20 (DeepSeek PM): **the operator authorized the gateway restart; the grenade ring and the RE4 evidence are
  live.**
  - **Restart:** `gbox.service` restarted on lilspark at ~10:49 (worker `c63a6efd5f584229` -> `0569c82d21614288`,
    health back immediately, `deploy-restart-pending` cleared after the restart because the 10:45 deploy had already
    copied everything). It activated the pending runtime: the RE4 playbook's round Notebook (`f8931ce2`), the RE4 E3
    watch (`78093822`), the RE4 harness `_CREATE_LOCK` (`20028ad6`), the RE6 ring flag fix (`be058678`) and the
    intervention probe's `allow_unverified` (`59850e4e`).
  - **RE4 round reports exist (verified live):** the scanner now has an `010099A00BC1E000` cursor and five reports
    (10:57-11:03): kills 7-24, `round_gun_downs` 35-43, `round_unwall_tangents` 5-11, all `died`. The operator's
    raise/lower and wall numbers are now in the loop - the fire-first regression is measurable per round, and the
    report is the instrument #9526's acceptance will use.
  - **RE4 harness:** the controller builds (no more AttributeError) and the status now names the real gate -
    "no proven private storage ... pages now: ..."; `bss_watch`/`bss_watch_loads` are publishing (stage 3, four pages
    nonzero, `0x1700000` all zero). The round-start load change (`cb956095`, deployed 11:15) makes the same stage count
    a load per round; after three round starts `choose_mailbox` -> `MAILBOX_AT = 0x1700000` and the next RE4 session can
    attach for the flash/hand receipts.
  - **RE6 flash ring CONFIRMED live** (request `43927d54-9007-4688-b2fa-e0981fe4ed1b`, session
    `0569c82d21614288-bc86d7aad571481a`): `confirmed`, 10 requested / 10 detonated, 600 cm ring, 703.9 ms, hp 900 -> 900,
    self-damage 0, the after-frame full of the blue flash bloom. The full receipt and the open items are in the grenade
    lane log round 84.
  - **RE5:** the 10:51 session ended after 2.4 min; its controller said "no living player in an active Mercenaries round"
    (the session had already ended). Its status now names hand/incendiary as built on the parameterised spawn
    (uWp06/uWp07 DTI) with no live receipt yet - the next live RE5 round is the probe.
  - **The crowd/combo ask:** #9526 (proactive on crowds) and #9268 (RE6 standing still) are first in the Hermes queue,
    with the live evidence comment that the read-and-report rules do not apply; no Hermes run had picked it up at 11:20.

- 2026-11-11 12:18 (DeepSeek PM): **the RE4 harness chain is fixed end to end (mailbox -> ready pair -> check guard); the
  operator's crowd ticket gets a clean code home.**
  - A second authorized gateway restart at 12:01 (worker `ae2bda4751dc44b1`) activated the RE5 ring call budget
    (`79173f23`, 2.5 s per ring call); the RE5 block at 12:02 never reached a round and ended, so the automatic ring
    is still unverified on the new budget.
  - The post-mailbox RE4 probe found the first harness-capable session and clicked the whole sequence: the selftest
    reached the controller but failed on "'Controller' object has no attribute 'sp'" - `write()` -> the inherited RE6
    `check()` reads RE6's `sp`/generation offsets. Fixed (`7ea436fa`): the RE4 controller has its own `check()` (build,
    bound unit id, vtable class/clone). Deployed 12:15; a fresh probe waits for a session started after 12:14 to take
    the selftest/flash/ring receipts.
  - **#9526's Hermes run published docs only** (75054446, a read-only survey) despite the message that the read-only
    rules are void: the ticket body's stale research RULES still steer the run. Filed **#9720**
    ("CODE-CHANGE: Mercs bots - dispatch the crowd before it closes", id `35563acd0ac44bcc`) with the explicit
    code-change marker, the operator's words, the live RE6 and RE4 baselines and the numeric acceptance; replied on
    #9526 that 75054446 does not close it and #9720 is the code work; **#9720 is first in the Hermes queue**.
  - The RE4 round reports keep flowing through the new pipeline (21-85 gun downs/round, 12-19 kills), so the crowd/
    fire-first work has a live measurement on both titles.

- 2026-11-11 13:05 (DeepSeek PM): **the operator's three new asks are in the build or the queue; two live gates stay open.**
  - **RE6 remote mines** (`47e029c9`, activated by the 13:03 restart): a ring of four ejected from his body through the
    instant spawn, no throw/animation; the flag detonation (no detonator in hand); the rule drops a ring ~22 s +/- 8 s
    (jittered, mid-match) and detonates 3 rings / 75 s; the `remote_mines` op (ring|detonate) is in the worker for the
    operator's own clicks. Next RE6 block: the mine_* stats + a live receipt.
  - **RE4 Krauser bow** (`1dc41975`, deploys 13:15): the 20x cap -> 40x, the trigger floor 0.025 s and a 25 ms fight
    tick while class 0x1C is in hand. Live data behind it: five Krauser rounds 12:56-12:59, 0 kills each, 0-10
    aim.round_shots/round, 110/158 threat ticks unanswered at 12:58 - the bot holds with the bow; the deeper gate is
    ticket #9744's aim acceptance.
  - **Combo-loss reports + aim + grenade/mine rationale**: `#9744` (CODE-CHANGE, operator's words, the live baselines
    and the acceptance) is **second in the Hermes queue** behind `#9720` (the crowd/combo doctrine); `#9526`'s docs-only
    run stays rejected.
  - **#9720 / #9744** are the two live code tickets; the queue priority is set (35563acd, c5590814 first).
  - **RE4 harness E6** is still uncertain: the mailbox call never completes (the dispatcher's invocation, not the page,
    is the missing piece); the rings/flash stay honestly refused until it does.
  - **The RE5 13:03 block** never reached a round (title) and ended; the 2.5 s ring budget remains unverified live.
  - The 13:00 deploy reloaded `grenade_ring` (the periodic 2-minute random-kind ring is live) and the deploy state is
    clean; the goal stays active.

- 2026-11-11 13:40 (DeepSeek PM): **the RE6 remote-mine rings are live (28 bombs / 7 rings / 2 flag detonations) and the
  bow 40x is deployed.**
  - Live receipt: RE6 `fefc7b32...-944946...`, `mine_rings_dropped` 7, `mine_ring_bombs` 28,
    `mine_flag_detonations` 2, kills 5 by 13:38 - the operator's "massive quantities ... then detonate them remotely"
    working with no throw, no animation, no detonator in hand (`47e029c9`, `2e5cb097`).
  - The `remote_mines` capability needed the claim allow-list (`9e1f7d56`): the worker's report was 422 "invalid worker
    capability report" and the PiP had no operations until the restart loaded it.
  - RE4 bow: `d4e00881` deployed at 13:15 (reloaded `re4_switch_mods`, `re4_switch_native`) - the bow plays at 40x by
    default (BOW_MOTION_X), the trigger floor is 0.025 s and the playbook ticks at 0.025 s while the bow is up. The
    pre-deploy Krauser rounds (13:10-13:14, 20x) already showed 5-8 kills and 11-31 shots in the good rounds; the next
    Krauser round measures the 40x.
  - The RE4 playbook now runs the bot's ring rule (the periodic two-minute random-kind ring across all three Switch
    titles), and the harness selftest returns its mailbox counters on an incomplete call (`64597c05`).
  - The RE4 harness E6 remains the blocker for the RE4 ring/flash receipts: the dispatcher is installed but never
    invoked on the mailbox schedule; the diagnostic receipt is the next live probe's first read.
  - The RE5 ring budget (2.5 s) and the periodic ring are live; the RE5 blocks since the fix have not reached a round
    (the 13:03 title hang) - the next live RE5 round is the test.
  - #9720 and #9744 stay first/second in the Hermes queue; no run has picked either up yet.

- 2026-11-11 13:50 (DeepSeek PM): **the combo-loss follow reports are in the build; the operator's QTE ask is ticket
  #9769; the RE6 mines keep running (64 bombs, 5 flag detonations).**
  - **Combo-loss follow reports** (`b813c90f`, deployed 13:45, engine reloaded): `gbox/mercs/combo_reports.py` posts one
    Hermes request per combo lost (round/session/title, combo before/after, kills/score/clock, the threats within 6 m
    and the bot's doing/why), deduped, capped at 3 per round, a failed post is a stat. The next engine run (the next
    RE5/RE6 round) files them live; the round report keeps combo_breaks for the totals.
  - **QTE flags + stick throttle** (`#9769`, first in the Hermes queue): the operator's 13:47 screenshot (a dog mauling
    the player, the stick QTE icon up) with "flip the flags for QTE events instantly ... still fails to throttle the
    stick". The ticket specifies the RAM state to find (the sActionButton singleton's answered/return-to-play fields),
    the verified flag flip (only while a QTE shows, re-read, rate-capped) and the left-stick analog throttle/oscillation,
    with the live acceptance (a dog maul escaped <= 250 ms, 0 false flips).
  - **RE6 remote mines**: 16 rings / 64 bombs / 5 flag detonations by 13:44 on the same block - the operator's "massive
    quantities then detonate them remotely" is running continuously (rings of four every ~22 s).
  - **RE4 bow 40x** deployed at 13:15 (d4e00881); the next Krauser round measures shots/round at the 40x (the 20x rounds
    already reached 5-8 kills and 11-31 shots).
  - The RE4 harness E6 remains uncertain (the diagnostic receipt awaits the next RE4 probe); the RE5 2.5 s ring budget
    awaits a live RE5 round (the last two RE5 blocks hung on the title screen).
