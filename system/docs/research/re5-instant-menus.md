# RE5 Switch: instant menus (2026-11-09)

Title 010018100CD46000 (Resident Evil 5, Switch, The Mercenaries United, No Mercy) on Eden, host lilspark.

Operator, 2026-11-09: "I need the bot to learn, train and master navigating these menu screens to get through them
faster and faster until it is instantaneous. It is agonizing to watch the bot struggle option by option in the menu
system. I need the bot able to flip RAM switches and byte states in the game to get wherever it needs to go as fast as
possible ... It is important that the bot learns and navigates menus stronger and faster each time."

Code: `gbox/mercs/titles/re5_switch.py` (`menu_assist`, `JUMP_SCREENS`, `_menu_seen`, `_menu_clock`,
`same_round_next`, `StageCycle.observe_cursor` / `note_press` / `stalled`), `gbox/mercs/menu_speed.py` (the per-screen
learner and the transition clock), `gbox/mercs_bot.py` (`Navigator` hints, `Boot` calls `menu_assist`),
`gbox/mercs/bot_logic.py` (the two knobs and the sidebar's menus line), `clients/web/viz/bot-logic-sidebar.js`.
Tests: `tests/test_re5_switch_instant_menus.py`, `tests/test_menu_speed.py`, `tests/test_re5_switch_cycle.py`,
`tests/test_bot_logic_sidebar.cjs`.

Every number below says whether it was **measured** (round data, telemetry), **run** (tests, the synthetic model) or
**inferred** (arithmetic on the measured numbers). Nothing here was written to the live game.

## 1. Measurements

### Between rounds (measured: round maps + the round database, read-only on the Spark)

Source: `gbox-data/mercs/round_maps/010018100CD46000/*/*.json` (each round's `started` = its first sample with the clock
running, `ended` = its death or results) and `gbox-data/mercs/curriculum/010018100CD46000/rounds.sqlite` (each round's
cumulative `menu_presses`). A gap is the next round's start minus the last round's end, both in the same autoplay run;
rounds a bot reload interrupted (1.3-2 s "gaps") are left out. 2026-11-01 .. 11-09, 315 gaps.

| what | n | gap median | p10 | p90 | menu presses (median) |
|---|---|---|---|---|---|
| after a death (Continue? No, save, results, selects, load, intro) | 281 | 40.6 s | 35.2 s | 90.7 s | 9 |
| after a completed round (tally, results, selects, load, intro) | 34 | 36.7 s | 30.9 s | 91.5 s | 12 |
| 11-01 .. 11-05 (the walk as it was) | 247 | 39.8-42.9 s by day | | | 9-10.5 |
| 11-06 .. 11-08 (the roster calibration walk, see below) | 42 | 91.0-98.0 s by day | | | 44-46 |
| 11-09 (DJ picks; no calibration walk) | 26 | 34.9 s (min 29.1) | | | 6.5 |

A least-squares fit over the 315 gaps: **gap = 26.3 s + 1.48 s per menu press** (residual sd 4.3 s). So about 26 s of
every gap is the game's own (the death animation and dialog, the save, the stage load, the round's intro) and every
press the walk makes costs 1.5 s on average.

Why a press cost that much (from the code, not measured): RE5 Switch had no `NAV_CURSOR` (RE5 PS3 and RE6 Switch
have one), so every press paid the Navigator's fixed waits: 0.5 s of "stable" after any RAM change (every cursor step
included), 0.3 s (A) / 0.18 s (D-pad) held, menus read every 0.25 s, and a press RAM did not show sent again only after
1.2 s.

**The calibration walk (measured, the biggest single loss).** On 11-06 .. 11-08 the character select took about 40
presses every round and the gaps were 91-98 s. The walk that was meant to learn the roster size (`CHARACTER_SLOTS`,
still 0 in `gbox-data/mercs/re5-switch-cycle.json`) pressed right `CALIBRATE_PRESSES` (40) times every visit and never
learned anything: on 11-07, 51 of 53 rounds were "Jill (Battle Suit)" (index 7), on 11-08 30 rounds "Chris (BSAA)" and
17 "Jill (Battle Suit)". In 1,289 recorded rounds the select's own cursor (the index A confirmed, counted in the cycle
file) never went past 9. Inferred: a 10-entry select that wraps (40 presses are 4 laps, back to the entry it opened
on - the same costume coming round 51 times says it opens on the last one). Its wrap rule needed more entries than the
14 names in `CHARACTERS` (`max_cursor + 1 > 14`), so a 10-entry select could never teach its count. Fixed (3.3).

### One live transition (measured: telemetry, sampled every 5 s, so each time is +-5 s)

Recorded read-only from `GET /api/autoplay/telemetry/<sid>` (session ae02be4bd9974915-ae3a00850f6843b5, 2026-11-09 CST):

| time | screen | menu presses (cumulative) | note |
|---|---|---|---|
| 17:58:38 | results | 0 | the round over |
| 17:58:52 | select_stage | 6 | last press "select_stage: dright" |
| 17:58:57 | loading | 10 | last press "select_player: a" |
| 17:59:03 | loading | 10 | rounds 1 -> 2 (the menus saw the intro) |
| 17:59:18 | playing | 10 | Missile Area, Jill (Battle Suit); clock 115.47 s, so it started about 17:59:13 |

About 35 s from the results to the clock running, 10 presses; about 14 s of it before the stage select (the tally,
the dialogs, the load into the selects), about 5 s on the two selects, about 16 s stage load and intro.

### Cold launch (measured by the operator's agent from telemetry, 5 s granularity)

22:58:23 alert_ok -> 22:58:31 play_game -> 22:58:40 select_stage -> 22:58:48 loading -> 22:59:04 playing (UTC):
about 41 s from "Load successful" to the round. The walk there is alert_ok (A), main menu (A), PLAY GAME (down, A),
EXTRA CONTENT (A), The Mercenaries United (A), the mode list (down x3, A), the stage (k steps, A), the character
(j steps, A): 11 + k + j presses at about 1.5 s each, then the load and the intro.

### The screens a death walks through (code + docs/research/re5-switch-ram.md, not timed per screen yet)

death -> "You Are Dead - Continue?" (uIdGameover00; the bot waited a fixed `DEAD_WAIT_S` 2.5 s, then answered No)
-> "Save successful" (uIdAlert00 id 0x09, A) -> results (uIdMerceEd00, +) -> loading -> STAGE SELECT (uIdStartUp21)
-> CHARACTER SELECT (uIdStartUp22) -> NOW LOADING -> the intro (player in the stage, phase 0, about 10 s by the
warm-pool measurement) -> the clock runs (phase 1). The new stats (section 4) time each of these screens on every
transition from now on.

## 2. What changed, in one paragraph

Every menu screen now learns its own waits (how soon after it appears a press is taken, how soon after a cursor move,
how long a D-pad press may go unseen, how long a press is held), getting faster x0.92 on every press RAM shows taken
and slower x1.45 on a press RAM never showed (that value then becomes the screen's floor); the menus are read every
30 ms on those screens so a press goes on the first frames the screen takes input. On the menus whose cursor the bot
already reads, the cursor integer is written in RAM instead of stepped to, read back, held, proven by the game's own
step, and then confirmed with one press. A death is answered the moment the dialog takes input, the walk stops pressing
into the end of a select, the 10-entry roster is learned from its wrap, and "Continue? Yes" (no save, no selects, no
load) is taken whenever the next round is this one anyway. Each transition's menu seconds, seconds to gameplay, per
screen times and presses go to the stats and the sidebar ("menus: X s (best Y s)").

## 3. The jumps and the skips

### 3.1 Where the cursors are (the fields the bot already reads; docs/research/re5-switch-ram.md, live 2026-10-26)

Every unit is found on every read: `sUnit` = [main + 0x26A3270]; move line L's first unit at sUnit + 0x18 + 0x30 * L
(32 lines); a unit's next at +0x18; a unit's class from its vtable's slot 5 (getDTI: `adrp x0 / add x0 / ret`) ->
MtDTI + 8 -> the name. main's base is found by its 64-byte read-only signature at main + 0x1191000 (ASLR moves it every
boot). Every cursor is a little-endian s32.

| screen | unit class | cursor field | entries known to exist | target | jump |
|---|---|---|---|---|---|
| main menu | uIdStartUp00 | +0x74 | 2 (PLAY GAME 0, more: the walk has read 2) | 0 PLAY GAME | approach from 1 when 2+ away |
| PLAY GAME | uIdStartUp01 (+0x1C4 == 0) | +0x74 | 2 (EPISODES 0, EXTRA CONTENT 1) | 1 | never (one step either way) |
| EXTRA CONTENT | uIdStartUp01 (+0x1C4 != 0) | +0x1D8 | 1 (THE MERCENARIES UNITED 0) | 0 | never (opens on 0; entry 1 not known) |
| mode list | uIdStartUp29 (+0x1C4 == 1) | +0x1C8 | 4 (SINGLE / CO-OP / SPLIT-SCREEN / NO MERCY) | 3 (2 for split screen) | approach: write 2, one down |
| STAGE SELECT | uIdStartUp21 | +0x74 | 8 (the stages) | the cycle / DJ / operator's stage | approach, then direct |
| CHARACTER SELECT | uIdStartUp22 | +0x1D0 | learned: the largest index the game's own cursor showed (0-9 so far: the cycle file's confirmed characters), or `CHARACTER_SLOTS` | the pick | approach, then direct, only to known entries |
| Continue? | uIdGameover00 | +0x1CC (0 Yes, 1 No) | 2 | No / Yes | not jumped: the bot answers in-round, one tap; +0x1EC == 2 (takes input) is used instead (3.3) |

### 3.2 How a jump is done and verified (`re5_switch.menu_assist`, called by `mercs_bot.Boot` before each press)

1. **Two equal reads.** The screen's unit and cursor must read the same twice, at least 34 ms (two frames) and at most
   1 s apart (a menu still being built may change). A unit seen on another screen first is a new visit.
2. **Known entries only.** The target and the written value must be below the screen's known entry count (table).
3. **The class again.** The unit's class is read again right before the write (a unit freed and reused is never
   written).
4. **The write.** `adapter.write_memory(unit + offset, s32)` (the Switch adapter reads every write back and raises when
   it differs), then a read through the walk's own memory view must show the value. Refused writes (no
   `memory_write` permission, `mercs_no_modifications`) stop the jumps for that session; the walk steps as before.
5. **Held.** A later read, at least 34 ms after the write, must still show the value (the game did not put its own
   index back). Until then the screen carries `jump_wait` and `step()` presses nothing.
6. **Approach first.** A screen's first `JUMP_PROVE_N` (3) jumps write the entry next to the target (target - 1 when
   the cursor is below it, target + 1 above) and let one native D-pad step land on the target. The cursor moving off
   the written value onto the target proves the game steps from that integer (a field it ignored would step from its
   real index, and land elsewhere). After 3 proofs the screen writes the target itself and the walk presses A.
7. **Fallback.** A write that did not hold, or a step that landed elsewhere, is a failure: that visit steps option by
   option from the cursor RAM shows. A screen with `JUMP_FAIL_N` (2) failures more than its proofs stops jumping
   (`jump_off`, kept in the profile); the sidebar's "RAM cursor jumps" off and on again clears it.
8. **The roster learning never reads a written cursor** (`observe_cursor` is skipped on a unit the bot wrote, and the
   stage cycle's pending press is dropped at the write).

Stats: `menu_jumps`, `menu_jumps_proven`, `menu_jump_fails`, `menu_last_jump` ("select_stage: cursor 0 -> 5 (approach,
target 6)"), `menu_jump_error`; per screen in `menu_latency` ("select_stage ... jump 3/4": proofs / held writes).

Run (tests on the synthetic guest, `tests/test_re5_switch_instant_menus.py`): the approach write and its proof; the
direct write after 3 proofs; a game that puts its own index back every frame (the write never holds: failure, stepping
from the real cursor, no second write that visit); a game that steps its own hidden index (the write holds but the
step lands on 1, not 6: failure; two of them switch the screen off; off and on again clears it); targets past the
known entries are never written; the mode list writes 2 for NO MERCY; no write in an unmodified session, with a
refusing adapter, or on a unit whose class changed.

### 3.3 Skips

- **Continue? Yes when the next round is this one** (`REPLAY_SAME_ROUND`, `same_round_next`). The RAM doc's live
  observation: Yes restarts the same stage and character at once - no save, no results, no selects, no stage load (the
  whole walk). `REPLAY_ON_DEATH` stays off (the operator wants a new stage and character every round), so Yes is taken
  only when the operator's `mercs_select` fixed both the stage and the character and the round that just ended was on
  them (the stage cycle's record of what the selects confirmed); never under the random cycle, never while the icon
  panel's rotation or a DJ pick owns the next round. Verification: the existing replay accounting (the first tick alive
  with the clock within 3 s of full: `rounds` +1, `deaths_continued`, `round_start_via` "dead/retry") and the transition
  is recorded as kind "retry".
- **The dialog's own input state instead of a fixed wait.** uIdGameover00 +0x1EC reads 2 once "Continue?" takes input
  (live 2026-10-26). The snapshot now carries `continue_ready`; the bot answers the first tick it reads True instead of
  waiting `DEAD_WAIT_S` (2.5 s) after the death. It only ever shortens the wait (an unreadable field keeps the old one).
- **No pressing into the end of a select** (`STALL_PRESSES` 3, `STALL_S` 2 s). A forward walk whose cursor RAM shows
  standing still through 3 re-presses over 2 s confirms the entry it rests on now, which is what `CALIBRATE_PRESSES`
  (40) or `CYCLE_MAX_PRESSES` (14) would have confirmed 10-30 presses later. A moving walk is never cut short (that once
  confirmed a mid-roster character and halved the score). Those wall presses no longer teach the screen's waits.
- **The roster count from its wrap** (`WRAP_MIN_ENTRY` 3). A forward press made on this visit from entry 3 or later that
  lands on 0 has wrapped: the count is that entry + 1 (10). The forward press RAM has not shown yet is kept until the
  cursor moves, and is dropped off the selects, so a reopened select at 0 never teaches a count. Once learned (kept in
  `re5-switch-cycle.json`), the cycle picks among the 10 and the 40-press walk is gone.

Candidates not built (not shown by recorded RAM; each needs a live probe first):
- the round's intro (about 10 s of phase 0 before the clock runs): whether a press, or cGameSys +0x944 = 1, starts the
  clock early without breaking the round's set-up;
- The Mercenaries United's START: whether uIdStartUp29 +0x1C4 = 1 opens the mode list without the press and the fade;
- PRESS ANY BUTTON: built 2026-11-10 (branch mercs-menu-pace). `screen()` names the title "title" once uIdTitle00 +0x18
  is set (as `warm_probe` does) and the Navigator confirms it on its first read (`menu_pace.title_hints`: no settle),
  instead of the Boot's `BOOT_KEY` every 3 s on an unnamed screen. The boot's own screens (`mercs_bot.BOOT_SCREENS`)
  no longer end the boot's grace, so the unnamed save load after the title keeps the 600 s limit, not 30 s;
- the results tally: MercMode needs it to count a completed round (`result_ready`), so it is not skipped.

## 4. The learning, the stats and the panel

Per screen (`menu_speed.Speed.screen(where)`, kept in `<data dir>/mercs/learned/010018100CD46000/menu_speed.json`):

| knob | start | floor | ceiling | used for |
|---|---|---|---|---|
| settle_s | 0.45 s | 0.03 s | 0.50 s | a new screen (or a confirm's result) before its first press |
| step_s | 0.30 s | 0.03 s | 0.50 s | a cursor move on the same screen before the next press |
| retry_s | 0.60 s | 0.15 s | 1.20 s | a D-pad press RAM did not show, sent again (a confirm keeps 1.2 s: never confirmed twice) |
| hold_s | 0.30 s | 0.10 s | 0.30 s | A / B / + held |
| dir_hold_s | 0.18 s | 0.05 s | 0.18 s | a D-pad press held |

The rule: a press RAM shows taken (the screen, its unit or its cursor changed) lowers the knobs that press used x0.92
and records the screen's confirm latency; a press RAM never showed (another press on the same unchanged screen, or 0.9 s
for a D-pad / 2.5 s for a confirm) raises them x1.45 and makes the value that failed the knob's floor; later taken
presses do not go below 1.1 x the floor until enough of them (0.5 % each) wear it away. Every hint is capped at the
Navigator's own fixed wait, so a screen that never confirms anything walks exactly as before. Learned screens are read
every 30 ms (`FAST_POLL_S`).

Transitions: from a round's end (the Driver's first death or results tick after its clock ran) or a run's first menu
screen, to the menus done (the first loading / intro after the character select) and to the next round's clock
running. Kinds: next (round to round), boot (a run's first walk), retry (Continue? Yes: no menus), prepare (a MercMode
background preparation: never in the best or the trend). Kept: the last 50 with each screen's seconds and presses.

Stats (scalars, so telemetry and the round notebook keep them): `menu_seconds` (the last round-to-round walk),
`menu_seconds_best`, `menu_seconds_trend` (the last 10, oldest first), `menu_play_seconds` / `menu_play_best` /
`menu_play_trend` (to the clock running), `menu_boot_seconds` / `menu_boot_best`, `menu_screens` (the last walk: "alert_ok
0.6s/1p, results 1.1s/1p, loading 2.0s/0p, select_stage 0.9s/2p, ..."), `menu_latency` (each screen's learned settle,
confirm latency and jump record), `menu_presses_last`, `menu_jumps_last`, `menu_open_s`.

Panel: the sidebar shows "menus: X s (best Y s) · to play Z s" under the PC line (hover: the screens), from
`bot_logic.status("re5")["menus"]`; the "Menus" group has two switches: "RAM cursor jumps" (`MENU_JUMPS`) and
"Learned menu timing" (`MENU_LEARN`).

## 5. Before / after

Run (the synthetic model in `tests/test_re5_switch_instant_menus.py`: a press is taken 0.10 s after its screen appears,
A moves on after 0.30 s, two 1.0 s loads; results -> intro with the stage cursor 0 -> 6 and the character 0 -> 7):
the fixed walk 17.79 s / 17 presses; learned, run 1 6.02 s / 6 presses (approach jumps), run 12 3.98 s / 4 presses
(direct jumps, learned waits); per run 6.02, 5.60, 5.42, 4.56, 4.36, 4.35, 4.23, 4.23, 4.12, 4.13, 4.02, 3.98. These are
the model's latencies, not the game's: the live numbers come from the stats above.

Inferred for the live game, from the fit (26.3 s + 1.48 s per press):
- a death to the next round, as on 11-09 (35 s, 6-7 presses): the D-pad steps go (jumps), the remaining 4 presses
  (Save successful, +, stage A, character A) drop from ~1.5 s to a few tenths each once learned, and the death is
  answered when the dialog takes input: about 26-29 s, of which ~26 s is the game's own (dialog, save, loads, intro);
- a calibration-walk round (91-98 s, 44-46 presses): the same 26-29 s once the wrap teaches the 10 entries (the first
  visit), and never again 40 presses;
- a cold launch's walk (41 s from Load successful, ~13 presses): the mode list's three downs become one, then none;
  each press's fixed 0.8-1.0 s of waits becomes learned; roughly 25-30 s, the rest being the stage load and intro.

## 6. What the operator must check live

1. The stage select jump: with the bot at STAGE SELECT, `menu_last_jump` reads "select_stage: cursor a -> b (approach,
   target t)" and the screen's highlight moves to b, then the one native step lands on t, and the round that loads is
   stage t (the round's `stage` stat and the picture agree). After three of those, "direct" writes: the highlight jumps
   straight to t and A confirms t (the stage preview may lag a frame; the loaded stage is the check).
2. The character select jump, both pages: a pick on a later entry ("approach" then "direct"); the round's character (the
   picture) is the one picked. If the highlight and the loaded character disagree, turn "RAM cursor jumps" off.
3. The mode list on a cold launch: NO MERCY reached with one down (approach) and the round is No Mercy.
4. A death: the answer goes in the moment "Continue?" takes input (well before 2.5 s), and No still leads to the selects.
5. The roster: `CHARACTER_SLOTS` in `gbox-data/mercs/re5-switch-cycle.json` becomes 10 after the first calibration
   visit wraps (or the walk confirms at its end after 3 re-presses). Is there a second page dright never reaches (a
   shoulder button)? If so, the cursor integer and the pages need a live map before page 2 can be picked.
6. The learned waits: `menu_latency` per screen (settle going down, misses rare); `menu_seconds` and its trend falling
   run after run; the sidebar's line.
7. Writes refused or not holding show as `menu_jump_error` / `menu_jump_fails`; a screen that went `OFF` in
   `menu_latency` steps option by option.

## 7. The same recipe for RE6 Switch and RE4 Switch

1. Measure: the round maps and the round notebook give each gap and the presses between two rounds; fit gap = a + b x
   presses to split the game's own time from the walk's.
2. List the menus whose cursor the bot already reads, with the unit class, the offset and the entries known to exist.
   - **RE6 Switch** (`gbox/mercs/titles/re6_switch.py`): uIdStartUp00 / 01 / 30 / 31 cursor +0x50, uIdStartUp32 (the
     character) +0x1CC with its costume cursor +0x1F8 (count +0x21C), uIdStartUp02 (EXTRA CONTENT) +0x50 with its mode
     list (count +0x54, ids +0x1C4), Continue? uIdGameover00 +0x50 (ready when +0x248 is a pointer). RE6 already bursts
     its key batches (`fast_start`) and learns the old cadence; it blind-presses PLAY GAME and EXTRA CONTENT because a
     cursor read there once named the wrong entry (11-09), so its jumps start with the selects (stage, character,
     costume), each with the approach proof.
   - **RE4 Switch** (`gbox/mercs/titles/re4_switch.py`): not MT Framework (the 2007 RE4 engine) and its menus are read
     from the capture frame (`re4_switch_screens`), not RAM, with targets only on the main menu and the extras list.
     First find the title task's work area in RAM, as the GameCube build's (`gbox.re4_menus`: the title.cpp task, its
     routine / step and cursor), at main's base + an offset pinned by a signature; then the per-screen hints, then jumps
     on the select player / select stage cursors with the same approach proof.
3. Give the title a `menu_assist(m, scr, stats)` (the `Boot` already calls it), `scr["unit"]` per cursor screen, the
   per-screen hints from `menu_speed` (`speed.seen` in `screen()`, `speed.press` in `pressed()`), and `_menu_clock` in
   its Driver's `screen()`; the Navigator and the learner are shared.
4. Skips: the title's own "same round again" (RE6: Continue? Yes), its dialogs' input-ready fields, a stall give-up on
   its selects.
