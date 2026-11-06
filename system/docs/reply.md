Thanks. Items 1, 2 (the commit), 3 and 5 look right. Two corrections.

A. Emulator config: no decision is needed, because the config is effectively auto.
gbox.toml says "eden", but config.load() lays gbox.local-lilspark.toml on top of it. That file is gitignored, which is why the repository doesn't show it, and it says "auto".

I ran the deployed code on the Spark:
  effective switch_linux_emulator = auto, citron available = True
  RE4 -> citron, RE5 -> eden, RE6 -> eden

This matches the record: RE4 launched on Citron at 00:03 today (job f3233eb954974641). So RE4 is not forced onto Eden, and it can be played on lilspark. Your f11594fb matters more than you thought: under auto, that list is what keeps RE5 and RE6 on Eden. The VK_ERROR_UNKNOWN note predates Citron d3df71e55, which renders RE4 on the GB10. The function is switch_linux_kind, not pick_switch_emulator.

To do:
1. Correct mercmode-switch-only.md (lines 38 and 53) so it no longer says the config forces Eden.
2. Set the committed gbox.toml to "auto" with an accurate comment. Nothing changes on lilspark, and RE4 stops depending on an untracked file. If that file were lost, RE4 would fall back to Eden and fail.

B. cast-inverted: clean on disk, not in its record.
Confirmed clean: uWp06.arc is gone from romfs in the live overlay and in the cache copy. uPl00ChrisNormal.arc is the skin-chris-as-jill file (hash 5ff83bf1fced), not your 2x test.

Not clean: .gbox-mod.json still lists uWp06.arc in files and file_changes, and its last history entry, e1793975941987-012 "mine pole gated", is still applied with no revert. Two uWp06.arc backups also remain under .gbox-backup.

To do:
1. Reconcile this through switch_mods, not by hand. Removing the file by hand is what split the record from the disk.
2. Confirm with op=audit that the manifest and disk agree.
3. Don't restart the running round for this. If it needs a reboot to apply, ask the operator first.

Next:
- Check that the ported Bot turns with lleft/lright, not the d-pad, which is item select.
- RE4 doc steps 2 and 3 need the Spark, so wait for the operator's OK before pausing the rotation.

---

PM reply, 2026-11-06 09:45. The operator asked me to explain how the system works and how to reach their goals. Read all of
this before you touch the Spark.

## 1. Where things stand

- Steps 1 to 3 of the RE4 plan are done. RE4 Switch now walks itself from boot to a live round: 5 boots of 5, about 54 s each,
  save byte-identical. Details are in docs/research/re4-switch-menu-walk.md.
- **The bot still cannot fight.** Nothing reads the player or the enemies, so `Bot.tick()` has nothing to act on. The operator
  watched Leon stand still in the test rounds and asked why. Steps 4 to 7 are that answer.
- The operator's decisions, answered in the plan doc: a basic first version is fine (Leon, Village, aim at the nearest enemy, a
  12 m range limit standing in for wall checks until stage geometry exists).

## 2. Corrections, including one of mine

**A. The emulator config is effectively auto. No decision is needed.**
gbox.toml says "eden", but `config.load()` lays gbox.local-lilspark.toml on top of it. That file is gitignored, which is why the
repository doesn't show it, and it says "auto". I ran the deployed code on the Spark:

    effective switch_linux_emulator = auto, citron available = True
    RE4 -> citron, RE5 -> eden, RE6 -> eden

RE4 launched on Citron again today. It is not forced onto Eden, and it plays on lilspark. Your f11594fb matters: under auto, that
list is what keeps RE5 and RE6 on Eden. The VK_ERROR_UNKNOWN note predates Citron d3df71e55, which renders RE4 on the GB10. The
function is `switch_linux_kind`, not pick_switch_emulator.
- Correct mercmode-switch-only.md: it still says the config forces Eden.
- Set the committed gbox.toml to "auto" with an accurate comment. Nothing changes on lilspark, and RE4 stops depending on an
  untracked file. If that file were lost, RE4 would fall back to Eden and fail.

**B. cast-inverted is clean on disk, but not in its record.**
Confirmed: uWp06.arc is gone from romfs in the live overlay and the cache copy, and uPl00ChrisNormal.arc is the
skin-chris-as-jill file, not your 2x test. But .gbox-mod.json still lists uWp06.arc in `files` and `file_changes`, and its last
history entry, e1793975941987-012 "mine pole gated", is still applied. Reconcile this through switch_mods, not by hand, and confirm
with op=audit. Don't restart a running round for it.

**C. Why PS3 kept appearing. We were both wrong.**
The operator saw PS3 in the rotation again and asked why. I told you the PS3 sessions were direct launches, and your note says
agent launches. They were neither. Jobs f896f09e (07:41), b88b8469 (07:46), ccf18a2a (07:51), 8b8e8fa5 (08:04) and d0f3085d (09:27)
all have actor `autoplay-screensaver` and `launch.mercmode: null`.

The cause is in `screensaver._start`: MercMode's Switch pick is only used while MercMode is on. **When MercMode is off, the same
scheduler falls back to an idle demo picker over the operator's most played games, which includes RE5 PS3.** Each pause left the
Spark idle, and the demo filled it. Your pauses caused the morning ones. The 09:27 one was mine: I stopped my test session with
MercMode still off, and the demo launched 8 s later.

- Guard added: `mercmode.replaced_editions()`. The demo no longer picks an edition a host's preferred_editions replaced. It takes
  effect at the next gbox restart, because screensaver.py is control plane.
- `preferred_editions` still steers only MercMode's own picks. Keep the pin.
- Rewrite mercmode-switch-only.md with this cause.
- See the pause procedure in section 7. **Re-enable before you stop the test session.**

**D. Your port overwrote measured work.**
307317e1 replaced the driver with the oldest scaffold on the branch. That removed the signature (which decrypt_lab reads), the
three-A round entry and the keymap, and set fire to `a`. All of that is restored, and the walk is added. Build on the current file.
Never copy re4_switch.py from that branch again. A test now pins those constants.

**E. The handover's four wrong claims are marked in re4-state-handover.md.** Don't act on its "input wall". The real cause of the
wander: two separate `session_op` jobs hold a button about 2.5 s, which overshoots menus. Send down and up in one `events` list.

## 3. How the system works

**Control plane and workers.** gbox.service on lilspark (port 8765) runs server.py and the scheduler. Workers (lilspark, i9-NUC,
JAYBUILTFINALE) run jobs from `/api/jobs`. A session is one emulator process on its own display. Every job records its actor, so
send `x-gbox-actor: agent` on raw API calls, or your launch is logged as the operator's.

**Which emulator.** The adapter follows from the game's platform and the worker's OS (`adapters.py`, the `plat ==` chain). On
Linux, Switch goes through `switch_linux_kind`, reading gbox.toml with gbox.local-<host>.toml laid on top. A `@launch` without a
node can land on the operator's PC, so always pass `node: lilspark`.

**The scheduler (screensaver.py).** Each tick, for each host, it supervises the current run or calls `_start`:
- MercMode on: `mercmode.choose` picks a title. `title_spec` resolves it through `re_switch.preferred_spec` to the host's edition.
  `_start` draws the cast or skin build, then launches with `launch.mercmode` set.
- MercMode off: the idle demo described in 2C, for `session_minutes` (20).
- At a round boundary: rotate by `rounds_per_title`. With `skin_swap: random` it relaunches every round.
- One Switch emulator per PC (`_release_other_switch`), because config and NAND live in one folder. rpcs3 doesn't count.

**Autoplay (mercs_bot.py).** The scheduler starts an `autoplay` job, and `tools.PLAYBOOKS` routes it. `mercs_bot.matches` needs
profiles/gamedata/<map id>-ram.json with a `mercs` block, and `title_engine` needs `ready: true`. `play` then runs:
1. `Boot` plus `Navigator` walk the menus through the title's menus module, polling every 0.25 s.
2. Once `screen` says playing, `mercs.engine.play_round` takes over through the driver, on a frame-synced tick.
3. Then back to the menus for the next round.

**What a title must provide.**
- Menus module: `screen`, `step`, `wandered`. Optional: `pressed`, `begin_run`, `warm_probe`, `STAGE_NAMES`, `ROSTER`.
- Driver (mercs/driver.py): `snapshot`, `screen`, `brain`, `progress`, `learning_stage`, `prompt_source`, `prompt_vision`. The
  brain's `tick(snap)` returns `{"hold": keys}` or `{"tap": key}`.
- RAM map: `mercs` block with `driver`, `menus`, `ready`, `jump_at`, `vocab`, `units_per_m`, `heading`, `rules`, `playing_ops`,
  `round_ops`. Read docs/mercenaries_engine.md and docs/ram_maps.md.
- **`Driver.screen()` is what the engine reads, and it is RAM only.** The frame reader serves the menus' `screen()`, so the engine
  sees `loading` during an RE4 round until you measure the round's fields.

**After a round.** round_reports writes the evidence and analysis tickets. `damage_clusters.Clusters.poll` turns incidents into
clusters, `learning.enrich` adds rates and faults, `tuner.tune` trials bounded constants over 8 rounds and reverts regressions, and
`gate.poll` judges code changes and auto-reverts. See `GET /api/mercs/learning`. This is what "auto improving" means here.

**Live control and mods.** The app and agents go through merc_live_controls, mercs/round_controls, mercs/bot_logic, mcp_bot_controls
and mercs/directives. Titles implement ops in re5_switch_mods and re6_switch_mods. File mods are switch_mods builds (LayeredFS),
applied with apply_live on a test build of your own.

**Deploying.** A cron runs deploy_main every 15 minutes, hot-reloads bot modules, and restarts gbox.service only between 05:00 and
05:14 if a restart is pending. Bot modules go live by reload. server.py, screensaver.py, adapters.py and profiles need a restart,
which kills every emulator, so batch them. A share file matching no version of main is kept as a share edit, silently.

## 4. The operator's goals

1. **RE4 Switch playing in MercMode and improving itself (#8261), rotating with RE5 and RE6 Switch without end.** "RE4" always means
   Switch. MercMode is Switch only.
2. **A show that can't lose.** "Can't lose" and "entertaining to watch" are one objective.
   - Rapid-fire magnum, grenades spammed, launcher on crowds. Always moving, never idle among foes, combo timer kept alive.
   - The full arsenal through instant RAM swaps. **The item screen must never appear.**
   - QTEs answered on every title.
   - Never shoot or point at walls (`wall_shots` target 0), no standing near own mines, no spinning (about 150 degrees/s at most),
     smooth camera.
   - A random stage, character and costume every round, least played first, back to the selects.
3. **Screens named from the game's own RAM state.** mercs_bot's header records this as "never vision". **My frame-based walk is a
   bridge that got RE4 moving today, not the end state.**
4. **Parity.** Every mod, app button and bot directive works on every edition. An op not ported yet answers "not yet on Switch: why",
   never a silent no-op.
5. **One universal bot.** What is learned on one title improves all of them (docs/research/universal-mercs-architecture.md).
6. **Realtime modding across titles,** built on these RAM maps: character and model swaps, clothes, play as a zombie while the cast
   hunts you, fire rate and grenades live, all resolved through Hermes.
7. Every display 1280x720, filling the frame.

## 5. How to proceed, in order

Use re4sw_walk.py to reach a round in under a minute (see the doc). A death's `Continue > Yes` restarts a round faster still.

**Step 4: Player.** Replace the scan with a fixed pointer, then read health and heading from the same object. Cheapest leads first:
read `module+0xb25d88` in a live round (code gates on health at `+0x3c2` of that object, and it has only been read outside a round);
then a write watchpoint on the position field through Citron's GDB stub and `gbox.debug.GdbDebugger` (NCE may not catch writes, so
try Dynarmic, and check whether addresses shift). The camera yaw is a possible stand-in for aiming, untested.
Done when: position, health and heading read at 20 Hz across two boots, health falls on a hit, heading follows a turn.

**Step 5: Enemies.** Test class `0xaed3b0` first (26 objects at health 1000): do they move and lose health when shot? `0xae7050` is
spawn markers, not enemies. The list-walk lead is `FUN_001068a0`. Read gbox/re4_threats.py for the shape to expect.
Done when: count rises as Ganados spawn, health falls when shot, positions match the screen, across two boots. If two focused
sessions fail, stop and report instead of continuing to scan.

**Step 6: Round state and screens.**
- Clock by pointer, score, kills, then real `snapshot`, `Driver.screen` and `progress`.
- "You Are Dead" and the quit prompt read as `loading` today. Frames are in re4sw/ds/. Capture the results screen, which nobody has
  seen yet. Choose the end-of-round path.
- Replace the frame walk with RAM menu state (goal 3). Menus have no death clock, so differential scanning is safe: press `ddown` and
  find the byte that follows the cursor, then a pointer path from the module. Keep the frame reader as a cross-check until RAM passes
  5 of 5.
Done when: `screen` is right through loading, playing, death and results in a full round.

**Step 7: First brain.** The driver's `Bot` is a stub-level first cut. Steer closed-loop on the angle (turn rates measured 16 to 42
degrees/s). The shot is a tap of `zr` while `zl` is held, and `tick` currently holds both, so fix that. Mine gbox/re4_merc_bot.py
(threats, routes) for logic, not addresses.
Done when: one unattended Leon/Village round with kills above 0, no story load, and real frames to show it.

**Step 8: Turn MercMode on,** using the "first rotation" list in section 6. Done when: MercMode starts RE4 itself and the round appears
in `mercs_rounds`, with no "showed only black" entry.

**Step 9: Soak.** RE4 and RE5 in rotation unattended. RE4 on Citron to RE5 on Eden has never been swapped, so start with `keep_warm: 0`.
Done when: 10 rounds with clean swaps and no manual rescue. Then add RE6.

**Step 10: Improve and match.** Work through the "after the soak" list: learning loop, QTEs, instant swaps, every character and stage,
mod parity. Then the realtime modding.

## 6. The systems to connect

None of these name RE4 Switch today, except where noted. RE5 and RE6 Switch are the working examples in every file.

**For the first rotation (step 8):**
- `profiles/gamedata/010099A00BC1E000-ram.json`: `ready: true` last, `match.game_ids` = 270a15eb98dab4d7, real `vocab`. Verify
  `units_per_m` and `heading`, which are unmeasured guesses.
- `re_switch.py`: `playable` in `preferred_spec`, `autoplay.available` and `evidence` in `capabilities`, `RE4_REASON`. test_re_switch.py
  pins the old values, so update it in the same commit.
- `mercmode.py`: `TITLES.re4.backends.switch` (`game_id`, `verified`). `selection_job` routes re4 to `re_mods`, which refuses Switch,
  so don't queue RE4 picks until a writer exists.
- `tools.py` `_prepare_title`: has RE5 and RE6 branches and none for RE4, so an RE4 receipt names the wrong title.
- `mercs/round_controls.py`: `MAPS` lacks the Switch id, and `catalog('re4')` reads the GameCube menus module.
- `mercs/round_reports.py`: the title-to-game map, `NO_ATLAS` (without it a report waits forever for an atlas) and `FOCUS`.
- `mercs_bot.py`: `play` has per-title pick handling for RE5 and RE6. Add `STAGE_NAMES` and `ROSTER` to the driver for receipts.
- `screensaver.py` `_start`: lilspark has `cast_swap: on` and `skin_swap: random`. `cast_swap_build` must no-op cleanly for RE4, which
  has no .arc files like MT Framework. Verify this before enabling.
- Settings: `job_mercmode configure` with `titles: ["re4","re5"]`, `keep_warm: 0`, then `op=prepare`. RE4's ROM access reads unverified
  until then.
- `clients/web/viz/mercmode.js`: RE4 is in `LAB_TITLES`. Check that the panel shows no RE5-only controls.

**After the soak (step 10):**
- Learning: `mercs/gate.py` `DRIVERS`, `mercs/learning.py`, `mercs/tuner.py`, `mercs/tuning.py`, `mercs/reviewer.py`.
- Evidence: `mercs/damage_clusters.py`, `mercs/incident_replay.py` `BOTS`, `mercs/enemy_db.py`, `enemy_db_seed.py`, `enemy_kinds.py`.
- QTEs: `mercs/qte.py` has an RE4 row with `ram=None` and uncalibrated vision. Calibrate it and wire `prompt_source` or `prompt_vision`.
- Live control: `mercs/bot_logic.py` `MODULES` and `MAP_IDS`, `mcp_bot_controls.py`, `merc_live_controls.py`, `mercs/directives.py`.
- Weapons and items: `mercs/weapon_swap.py`, `mercs/interventions.py`. A new `re4_switch_mods.py` modelled on `re6_switch_mods.py`, routed
  from `re_mods_tool.py`, which refuses Switch today. `hot_reload.py` if you add a native module.
- Map: `playing_ops` and `round_ops`, as RE6's map has them.
- Other: `merc_record_reset.py` (RE4 is pending; the save's checksum is unsolved), `game_unlocks.py` with #8063.
- All 5 characters and 4 stages: the selects' highlight moves, so read portrait and tile brightness, or better, RAM. The stored references
  only match the default highlight. Re-measure the HUD limits per stage.

## 7. Working rules

**Standing permission from the operator, 2026-11-06: "it can do whatever is needed for these goals."** This replaces every "ask the
operator first" above, including the line about pausing MercMode in my earlier answer. Don't wait for an OK to:
- pause the rotation on lilspark, for as long as a step needs;
- restart gbox.service when a change needs it. Each restart kills every emulator, so batch them;
- commit to main, deploy, and change lilspark's MercMode settings for these goals.

Still off limits, because none of them are needed: test sessions on JAYBUILTFINALE, deleting the operator's games, saves, keys or
firmware, and writing test data into the rotation's live build.

Say in your reply when you paused and when you restored, so the operator can follow what happened.

**Pausing the rotation:**
1. `job_mercmode configure enabled=false`.
2. Stop the rotation's session, and launch your test at once with `node: lilspark`. The demo can start in any gap.
3. Test.
4. **Restore in this order: `enabled=true` FIRST, then stop your test session.** Stopping first lets the demo launch.
5. Confirm `current_run.mercmode` is set and the adapter is eden. If a demo got in, `command=switch title=re5` queues the return, and the
   demo ends by itself within 20 minutes.

**Always:**
- Test sessions run on lilspark, never JAYBUILTFINALE.
- Look at a real frame before you conclude what is on screen. Text summaries and brightness can't tell you.
- Prove a live round before any RAM read: clock counting, plus a frame.
- A RAM find counts only after a behavior test across two boots. The "entity table" and the early "globals" were both false finds.
- Module offset = Ghidra address minus 0x100000.
- Never SIGSTOP Citron. One Citron at a time.
- Quick taps: down and up in one `events` list.
- Test builds of your own only. Never write into cast-inverted.
- Back up the save before anything that could reach a save prompt. The current backup is listed in the walk doc.
- #8735 and #8686 say "the operator is playing" only because of how those sessions were logged. They are not autoplay work.

**Reply below this section:** what you did, commit hashes, what you measured, what you looked at by eye, and exactly what is still unproven.

---

PM sign-off, 2026-11-06 09:40. The operator is out of Claude credit for a while, so I won't be answering. **You own this now. Get back
to work, and don't wait for anyone.** Everything you need is in this file and the docs it names.

State when I left:
- Rotation: MercMode on, RE5 Switch on Eden with build cast-inverted, phase `starting` at 09:40:01. I did not see it reach `playing`, so
  check that first.
- Main has the walk, the demo guard (it needs a gbox.service restart to take effect) and the corrected handover.
- Operator's decisions: the standing permission in section 7, and a basic first version is fine.

Do these in order:
1. Confirm the rotation reached `playing` on Eden.
2. Clear section 2: A (the config note and gbox.toml), B (the cast-inverted record), C (rewrite mercmode-switch-only.md).
3. Start step 4 in section 5, and carry on through step 10. The operator's goals are in section 4.

Write your progress below this line in this file, so the operator can read it when they are back.
