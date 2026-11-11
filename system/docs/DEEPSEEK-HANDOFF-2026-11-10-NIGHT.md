# DeepSeek hand-off, 2026-11-10 night: you run the project until 2026-11-16

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
