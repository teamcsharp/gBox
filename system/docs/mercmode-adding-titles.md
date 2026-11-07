# MercMode: adding RE4 Switch, custom games and custom rotations

How to plug the autobot into RE4 Switch, add RE4 to the rotation, add a new game, and steer what plays. State as of
2026-11-07. In gBox, "RE4" means the Switch edition (title id `010099A00BC1E000`, catalog id `270a15eb98dab4d7`), never
the GameCube disc.

## The short version

- **RE4 Switch cannot autoplay yet.** It boots, takes input and walks itself to a live round (5 boots of 5), but the bot
  cannot see the player or the enemies. Finding those RAM addresses is the real work. The wiring below is small next to it.
- **Rotating titles that already work needs only settings.** See [Custom rotations and overrides](#custom-rotations-and-overrides).
- **A new game needs code.** The title list is closed: nothing reads it from a config file, and a rotation holds at most 3
  titles. See [Adding a custom game](#adding-a-custom-game).

## How the pieces connect

```
Scheduler (screensaver.py)      picks a title with mercmode.choose, launches it, starts autoplay
  -> tools.autoplay             tries tools.PLAYBOOKS in order; mercs_bot.matches must say yes
    -> mercs_bot.play           walks the menus through the title's menus module
      -> engine.play_round      plays the round: driver.snapshot -> driver.screen -> brain.tick -> pad input
        -> publish_boundary     reports the round's end to the scheduler
  <- mercmode.accept_boundary   checks that report; only an accepted round counts toward rotating
```

A title is four things: a **RAM map** (`profiles/gamedata/<map id>-ram.json`), a **menus module**, a **driver** and a
**brain**. RE4 Switch keeps the last three in [re4_switch.py](../gbox/mercs/titles/re4_switch.py). RE5 and RE6 Switch are the
working examples to copy. For the shared vocabulary, see [mercenaries_engine.md](mercenaries_engine.md).

## Where RE4 Switch stands

| Piece | State |
|---|---|
| Boot and picture | Works, on Citron d3df71e55 only. Eden cannot run it |
| Input and keymap | Work: `zl` aim, `zr` fire, `lleft`/`lright` turn, left stick moves. The d-pad is item select |
| Module base | Works: a signature finds it each boot, confirmed live |
| Menu walk to a round | Works from capture frames, Leon and Village only. Not yet run inside a worker autoplay job |
| Player pointer (`S_PLAYER`) | **Missing.** `snapshot()` returns `player: None` |
| Enemy list (`S_EMMGR`) | **Missing.** Best lead: class `0xaed3b0`, 26 objects at health 1000. `0xae7050` is spawn markers, not enemies |
| Clock, score, kills (`S_MERC`) | **Missing.** The clock was found by scan but has no fixed pointer |
| Brain | First cut, and its shot is broken (step 4 below) |

## Plugging the autobot into RE4

Do these in order. Nothing past step 1 can be tested until the anchors exist.

### 1. Measure the anchors

Fill the `None` constants at the top of `re4_switch.py`: `S_PLAYER`, `P_POS`, `P_ROT`, health, `S_EMMGR`, `E_POS`, `E_HP` and
`S_MERC` with its fields. The procedure is in [re4-switch-anchors.md](research/re4-switch-anchors.md) and
[re4-mercmode-blocker.md](research/re4-mercmode-blocker.md).

- **Module offset = Ghidra address - 0x100000.**
- A find counts only after a behavior test across two boots: it moves, or it loses health. Two earlier "finds" were false.
- Prove the round is live first: the clock counts and a real frame shows it. Ganados reach Leon in 15-20 s, and a dead
  Leon reads as flat data.
- **Don't assume full health is 100.** The anchors note searches for 100, but an earlier pass measured an `int16` falling
  from 1336 to 1054. Confirm with a visible hit, since one `decreased` sample with no hit empties the search.
- The pointer leads disagree between notes (`module+0xb25d78`, `module+0xb25d88`). Test both.
- The enemy-table layout in `snapshot()` (base, count, stride) is a GameCube hypothesis, not a measurement.

### 2. Make the driver report the round

The engine reads `Driver.screen()`, not the menus' `screen()`, and the two disagree today. The frame reader says `playing`
and hands over, then `Driver.screen()` says `loading` because `player` is `None`. After 20 s the engine returns `lost` and the
run ends with `wandered: "the round was lost"`.

| Method | Needed for |
|---|---|
| `snapshot(m)` | `player` `{ptr, pos, rot, hp, hp_max}`, `enemies` `[{slot, ptr, pos, hp, hp_max}]`, `timer`, `score`, `kills`, `combo`. Keep the same shape as RE5 and RE6 |
| `screen(m, snap)` | `playing`, `dead`, `results`, `loading` or `story`, correct through a full round. "You Are Dead" and the quit prompt currently read as `loading`, and nobody has captured the results screen |
| `result_ready(snap, now)` | **Missing, and required.** Without it the results witness has `tally_ready: false` and the boundary is refused |
| `menu_handoff(m, snap, where)` | Missing, recommended. It stops a known menu with no player from counting as a lost round |
| `learning_stage(snap)` | Missing, recommended. It keys the round evidence by stage |

### 3. Open the door to autoplay

`mercs_bot.matches` must find the profile and an engine. Two values in
[010099A00BC1E000-ram.json](../profiles/gamedata/010099A00BC1E000-ram.json) block that today:

- `match.game_ids` is empty, so the session's game finds no map. Set it to `["270a15eb98dab4d7"]`.
- `mercs.ready` is `false`. Set it to `true` **last**, because `engine.READY` is `False` and `ready` is what lets a title in.

Also verify `units_per_m` and `heading`, which are unmeasured guesses. The map's note "Renders on Eden only" is out of date.

### 4. Fix the shot

`Bot.tick` returns `{"hold": {AIM_BTN}, "tap": FIRE_BTN}`, but the engine's tap path ignores `hold`: it calls `hold(set())`,
which **releases aim**, presses the tap, then rests about 0.8 s ([engine.py](../gbox/mercs/engine.py), `if "tap" in act`). So the
trigger fires with aim down and rapid fire is impossible. `test_re4_switch_brain.py` checks only the returned dict, so it
passes anyway. Pulse the trigger through `hold` across ticks instead: `{zl}`, `{zl, zr}`, `{zl}`. Found by reading the code,
not yet seen live.

Then steer closed-loop on the angle, because measured turn rates ran from 16 to 42 degrees/s. Mine
`gbox/re4_merc_bot.py` for logic, not addresses. The first version may use a 12 m range limit in place of wall checks,
which the operator accepted until stage geometry exists.

### 5. Run it by hand

Pause the rotation first, using the order in [mercmode-switch-only.md](research/mercmode-switch-only.md). Use gBox's tools
(on raw API calls, send `x-gbox-actor: agent` or the launch is logged as the operator's):

```
job_mercmode    op=configure host=lilspark enabled=false
launch_game     game_id=270a15eb98dab4d7 node=lilspark      # always pass node, or it can land on the operator's PC
job_autoplay    op=start session_id=<sid> mode=playbook
job_autoplay    op=status session_id=<sid>
bot_sessions                                                # live screen, rounds and kills
job_autoplay    op=stop session_id=<sid>
```

**Use `mode=playbook` when testing.** It refuses with an error if the bot does not match. `mode=auto` falls back silently to
learned or vision play, which looks like the bot running.

**To restore: set `enabled=true` first, then stop the test session.** Stopping first leaves a gap, and the idle demo fills it.

Done when one unattended Leon/Village round has kills above 0, no story load, and real frames to show it.

| Symptom | Cause |
|---|---|
| `no playbook plays ...` | `match.game_ids` or `mercs.ready` (step 3) |
| Run ends with "the round was lost" | `Driver.screen()` never says `playing` (step 2) |
| Leon stands still in a round | `snapshot()` has no player or enemies, so `tick` returns nothing |
| Leon aims, then lowers the gun | The tap path (step 4) |
| Rounds end but the title never rotates | Read `mercmode_boundary_error` in the bot's stats |

## Adding RE4 to the rotation

Do this after one clean unattended round. Each item is a gate that RE5 and RE6 already pass.

| # | Where | Change |
|---|---|---|
| 1 | [re_switch.py](../gbox/re_switch.py) `preferred_spec` | RE4's `playable: False` to `True` |
| 2 | `re_switch.py` `capabilities` | `autoplay.available`, `evidence`, and update `RE4_REASON` |
| 3 | [test_re_switch.py](../tests/test_re_switch.py) | Two tests pin "not playable". Update them in the same commit |
| 4 | [mercmode.py](../gbox/mercmode.py) `TITLES.re4.backends.switch` | Set `game_id` (`None` today) and `verified`. This also adds RE4 to `known_game_ids`, which refuses a prepare receipt naming it |
| 5 | [mercmode_tool.py](../gbox/mercmode_tool.py) prepare loop | Add `RS.RE4_GAME_ID`. `op=prepare` does not probe RE4 Switch today, so only a prior launch on that PC can prove ROM access |
| 6 | `mercmode.py` `accept_boundary` | **Key the RE4 check on `expected_map`, not `spec['map_id']`.** `TITLES['re4']` says `G4BE08`, so every RE4 Switch boundary is refused: "RE4 must be in its native Mercenaries room routine" |
| 7 | `tools.py` `_prepare_title` | Add an RE4 branch beside RE5 and RE6, or its receipt names the wrong title |
| 8 | `mercs/round_reports.py` | Add to `TITLES`, `NO_ATLAS` and `FOCUS`. Without `NO_ATLAS`, reports wait forever for an atlas |
| 9 | `mercs/round_controls.py` `MAPS` | Add the Switch id. `mercmode.catalog()['re4']` also reads the GameCube menus module, though the rosters match |

Gate 6 is the trap: without it, RE4 plays and reports correctly, yet its rounds never count. The title rotates only when the
10-minute stall guard (`NO_PROGRESS_S`) ends the turn.

Already fine, no change needed: `SWITCH_CITRON_TITLES` routes RE4 to Citron, `LAB_TITLES` in the web panel names it, and
`cast_swap` and `skin_swap` return nothing for RE4, so it plays stock.

**Not for the first rotation: queued character and stage picks.** `selection_job` routes RE4 to `re_mods`, which refuses
Switch. The pick branch in `mercs_bot.play` is GameCube-only, and the walk reads only Leon and Village. A pick would be
ignored or fail.

**Turn it on:**

```
job_mercmode op=configure host=lilspark enabled=true titles=["re4","re5"] rounds_per_title=1 keep_warm=0
  preferred_editions={"re4": {"platform":"switch","mode":"mercenaries","title_id":"010099A00BC1E000"},
                      "re5": {"platform":"switch","mode":"no_mercy","title_id":"010018100CD46000"}}
```

**Without the `re4` pin you get the GameCube disc.** Use `keep_warm=0` because only one Switch emulator can run per PC, and
RE4 on Citron to RE5 on Eden has never been swapped. Soak for 10 rounds with no rescue, then add RE6 (`"mode":"no_mercy"`,
`"title_id":"01002A000CD48000"`).

**After the soak**, for parity and self-improvement, these tables also name RE5 and RE6 but not RE4:

- Learning: `mercs/gate.py` `DRIVERS`, `mercs/learning.py` `MODULES`, `mercs/tuner.py`, `mercs/tuning.py`
- Evidence: `mercs/damage_clusters.py` `GAMES`, `mercs/incident_replay.py` `BOTS`, `mercs/enemy_db.py`, `mercs/enemy_kinds.py`
- Live control: `mercs/bot_logic.py` `MODULES` and `MAP_IDS`, `mcp_bot_controls.py`, `mercs/interventions.py`, `mercs/weapon_swap.py`
- QTEs: `mercs/qte.py`, whose RE4 row has `ram=None` and uncalibrated vision
- Mods: `re_mods_tool.py` refuses Switch until a writer like `re6_switch_mods.py` exists

## Adding a custom game

There is no config-only path. `normalize` refuses any title not in `TITLES`, and the tool's schema is a fixed list.

**Is it a Mercenaries-style game?** MercMode rotates on a native round end: a results or death screen the bot can prove from
RAM. For anything else, such as a fighter or a story game, use the idle demo instead (below).

### A game with rounds

1. **Library and emulator.** It needs a catalog entry, and an adapter on that platform that gives RAM reads and input.
2. **RAM map.** Create `profiles/gamedata/<map id>-ram.json` with `match.game_ids` and a `mercs` block naming `driver` and
   `menus`. Leave `ready: false` until it plays. See [ram_maps.md](ram_maps.md).
3. **Driver and menus.** Add `gbox/mercs/titles/<name>.py`:

   ```python
   class MyGame(Driver):
       map_id = "<map id>"
       solo_p1 = True                                     # required for rounds to count as solo
       def snapshot(self, m): ...                         # player, enemies, timer, kills, score
       def screen(self, m, snap): ...                     # playing | dead | results | loading ...
       def brain(self, m, stats, clock, learn_dir=None, nav=None): ...   # object with tick(snap) -> {"hold": keys}
       def result_ready(self, snap, now): ...             # the score tally has finished
       def menu_handoff(self, m, snap, where): ...
       def progress(self, snap): ...
   DRIVER = MyGame

   def screen(m, merc=None): ...                          # menus: {"where", "cursor", "target"}
   def step(scr): ...                                     # one pad key toward the next round, or None
   def wandered(scr): ...                                 # why the run left the mode for good, or None
   ```

4. **Register it** in every closed list:

   | Where | Change |
   |---|---|
   | `mercmode.py` `TITLES` | A new row (below) |
   | `mercmode_tool.py` | The `titles` and `title` `Literal` lists, and the prepare loop |
   | `mercmode.py` `catalog()` | Its roster and stages. Without this, the queue refuses a mode, character or stage for it |
   | `mercmode.py` `selection_job`, `mercs_bot.play` | Only if a pick should reach a running game |
   | `clients/web/viz/mercmode.js` `TITLE_NAMES` | Its name in the panel |
   | `mercs/round_reports.py` | `TITLES`, `NO_ATLAS`, `FOCUS` |

   ```python
   'mygame': {'name': 'My Game', 'map_id': '<map id>', 'platform': '<catalog platform>',
              'game_ids': ('<catalog id>',), 'playable': True, 'modes': ['mercenaries'],
              'characters': 4, 'stages': 6, 'driver': 'gbox.mercs.titles.mygame'},
   ```

   `merc3d` is the closest example. To list a game before it works, copy `re3`: `'playable': False` with a `reason`, which the
   panel shows.

5. **End-of-round proof.** `accept_boundary` needs one of:
   - `dead`: real player health at or below 0.
   - `results`: the tally is done, and either the clock is 0 or kills are at least 150.
   - A title whose missions end early can set `native_complete: True` and give its driver `mission_complete(m, snap)`.

6. **Test.** Run `test_mercmode*.py` and add a test for the new title. For a Switch title, also check
   `SWITCH_CITRON_TITLES` and that the emulator actually runs it.

**More than 3 titles in one rotation** also needs changes to the limit in `normalize` and `(titles + [title])[-3:]` in
`plan_dispatch`.

**A game with no round end** can technically join: the stall guard ends its turn after 10 minutes if another title is
playable. That is a recovery path, not a design, and it counts no rounds.

### Any other game: the idle demo

With MercMode off, the same scheduler rotates games by time and starts autoplay on each. It uses a playbook if one matches,
otherwise the operator's learned style or vision.

```
POST /api/autoplay-screensaver  {"games": ["<catalog id>", ...], "session_minutes": 20}
```

A pinned game must still pass the recorded-play filter (`min_pads`, default 300 pad inputs), so a game nobody has played won't
be picked until you lower it. The demo also skips any edition that a host's `preferred_editions` replaced.

## Custom rotations and overrides

Settings are per PC. Use `job_mercmode op=configure host=<pc> ...` or `POST /api/mercmode` with `{"host": "<pc>", ...}`.

**How the next title is picked:** a pick already promised, then the head of the queue, then the playable selected title picked
longest ago, skipping the one just played. Ties are random. There is no setting for a fixed order. For an exact order, use the
queue.

| You want | Do this | Watch out for |
|---|---|---|
| A rotation | `titles=[...]`, `rounds_per_title=N` | 1-3 titles, 1-20 rounds. Only playable titles are used |
| One title only | `command=start title=re5` | **Overwrites `titles`** with that one title |
| Another title now | `command=switch title=re6` | Ends the current turn now. Keeps only the last 3 titles, so it can drop one |
| An exact next round | `queue=[{"title":"re5","mode":"mercenaries","character":"Jill (BSAA)","stage":2}]` | Replaces the whole queue (20 at most). Applies at the next round end, even for an unselected title. Blank fields are random |
| A build for one round | Add `"mod":"<build folder>"` to a queue entry | The PC must already have that build |
| Which edition | `preferred_editions={...}` | RE4, RE5 and RE6 Switch only, written exactly as in `re_switch.EDITIONS`. `{}` means the native GameCube, PS3 or Xbox 360 editions |
| Stay in this game | `enabled=false` while it plays | The game and bot carry on. **If that session ends, the idle demo takes over** and can launch a native edition |
| Stop | `command=stop` | Closes MercMode's own game, never one the operator took over |
| Keep a bot already running | `POST /api/mercmode/adopt {"host","session_id"}` | Solo bot with fresh telemetry only |
| Which emulator | `switch_linux_emulator` in `gbox.local-<host>.toml`, or `SWITCH_CITRON_TITLES` | The local file overrides `gbox.toml`. Needs a restart |
| Faster swaps | `keep_warm=0..2` | Never warm between two Switch titles. They switch cold |
| Random models | `skin_swap=random`, `cast_swap=on` | No effect on RE4 |

**Who may do what:** only the operator can start or command MercMode on JAYBUILTFINALE. Automation can start it only on PCs
ticked for background testing.

**Check the result** with `job_mercmode op=status`. For each PC, read `settings`, `current_run` and `titles[].reason`, which says
why a title won't play.

**Live example, 2026-11-07 14:27.** An operator `command=start title=re4` on lilspark left `titles: ["re4"]` and
`preferred_editions: {}`. The session that came up was the GameCube disc on Dolphin under `re4_merc_bot`. If you ask for RE4 and
see `dolphin` or `G4BE08`, the pin is missing.

## Deploying changes

- **Reload live:** `gbox/mercs/**` and `mercs_bot.py`, except the modules listed in `hot_reload.NOT_BOT`, such as
  `round_controls` and `round_reports`.
- **Need a `gbox.service` restart:** `mercmode.py`, `screensaver.py`, `re_switch.py`, `tools.py`, `adapters.py`, `profiles/`.
  A restart kills every emulator, so batch them.
- Commits to `main` deploy through the 15-minute cron, which restarts only between 05:00 and 05:14 if one is pending.

## Rules that came from mistakes

- Test sessions run on lilspark, never JAYBUILTFINALE.
- Look at a real frame before concluding what is on screen. Brightness and text summaries cannot tell you.
- Never SIGSTOP Citron, which wedges the round intro. Run one Citron at a time.
- Send a quick tap as down and up in one `events` list. Two separate jobs hold the button about 2.5 s and overshoot menus.
- Back up `savegame00.sav` before anything that could reach a save prompt. The main-menu cursor opens on LOAD.
- Use test builds of your own. Never write test data into the rotation's live build, `cast-inverted`.

## How this was checked

**Run against the code on 2026-11-07:** RE4 with no pin resolves to GameCube and with the pin to Switch, `playable: False`;
4 titles and unknown titles are refused; no map resolves for `270a15eb98dab4d7`; RE4 is absent from `known_game_ids`; an RE4
Switch death boundary is refused while the same RE5 one is accepted; a results witness without `tally_ready` is refused; both
swaps return nothing for RE4. The lilspark example comes from live `job_mercmode op=status`.

**Read from the code, not run live:** everything about how a full RE4 round behaves through the engine, including the tap path
in step 4, since no RE4 round has been played by the bot.

**See also:** [mercmode.md](mercmode.md), [mercenaries_engine.md](mercenaries_engine.md), and in `research/`:
[re4-switch-menu-walk.md](research/re4-switch-menu-walk.md), [re4-switch-anchors.md](research/re4-switch-anchors.md),
[re4-mercmode-blocker.md](research/re4-mercmode-blocker.md), [mercmode-switch-only.md](research/mercmode-switch-only.md).
