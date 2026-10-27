# RE4 GameCube: the title and the menus from RAM

Operator 2026-10-20, about a bot demo stuck at the title: "why cant Ghidra see the game is on the title screen?" It can
now. `gbox/re4_menus.py` reads where Resident Evil 4 (G4BE08) is between boot and a Mercenaries round, and the RE4
playbook (`gbox/re4_merc_bot.py`) presses only what that screen needs to reach the next round.

## What RAM says

`pG+0x20` (the game's main routine) is 0 everywhere outside a room, so it can't tell the title from Select Player.
The title and every menu before a round belong to one task, title.cpp's. Its state is in a 0x60-byte work area (TW)
on the heap.

**Finding TW (`re4_menus.tw`):**
- The scheduler (scheduler.cpp) keeps its tasks at `0x80289F50`, `0x348` bytes each:
  - `+0x4` state;
  - `+0x18` an OSThread, with its saved sp at `+0x18+0x4` and its stack base at `+0x18+0x304`;
  - `+0x33C` the task's entry.
- While the title and its menus run, task 0's entry is `0x80161738` (title.cpp's task, created by `0x801224B8`, which
  also sets room 0x120: that is why the room reads 0x120 at the title). In a room it is the game loop `0x80116640`.
- The title task loops `table[TW[0]](TW)`, with the routine table `0x8020CC10` in r30 and TW in r31. When it waits
  for the next frame, both registers sit next to each other on its stack. TW is the word after `0x8020CC10`, searched
  in the top 1 KiB of task 0's stack.
- In the MEM1 of a Select Player save state, TW was 0x80A55860, at stack top - 0x34.

**The fields:**

| field | what | values |
|---|---|---|
| TW+0x00 u8 | title routine | 0 init, 1-4 boot (memory card, logos, the warning, PRESS START: START skips them), 5 main menu, 6 extra games, 7 a game starting |
| TW+0x01 u8 | the routine's step | main menu (5): 0 setup, 1 the menu, 2 New Game, 3 a story game starting, 4 Options, 7 Load. Extras (6): 0-3 loading and setup, 4 GAME START / EXIT, 6-7 setup, 8 Select Player, 9 leaving, 10-11 setup, 12 Select Stage, 13 starting |
| TW+0x24 u32 | main menu: how many items | 5 with the extra games unlocked, 3 without |
| TW+0x28 u32 | main menu cursor | with the extras: START (a new game), ASSIGNMENT ADA, THE MERCENARIES, LOAD, OPTIONS (codes 6, 2, 3, 4, 5); without: START, LOAD, OPTIONS (1, 4, 5) |
| TW+0x54 u8 | The Mercenaries' menu | 0 GAME START, 1 EXIT |
| TW+0x55 u8 | Select Player | 0 Leon, 1 Ada, 2 Krauser, 3 HUNK, 4 Wesker: the portraits left to right (left / right, wraps) |
| TW+0x56 u8 | Select Stage | 2 x 2 grid, 0 the Village (reset to 0 when Select Player is confirmed) |
| pG+0x54 u32 | the extra game picked | 0x40000000 The Mercenaries, 0x80000000 Assignment Ada |

**Where each field comes from in main.dol** (read with capstone from the disc's own main.dol):
- the routine table `0x8020CC10`;
- the main menu handler `0x801621F0`: up / down on the pad's pressed word, A / START pick a code by `pSys+4 & 0x40000000`;
- the main menu's dispatch `0x801627C4`;
- the extra games' routine `0x801633BC`, and in it:
  - the GAME START / EXIT handler `0x80163768`;
  - Select Player `0x80163CE4`, with the cursor at `0x80163F84`;
  - Select Stage `0x801644C0`.

The menus read the game's logical pad (`0x80288830`: pressed `+0x18/+0x1C`, repeat `+0x28/+0x2C`). Up is
0x01000000, down 0x02000000, right 0x04000000, left 0x08000000, A 0x80000000, B 0x40000000 and START 0x1000. gBox
presses the D-pad (`dup` / `ddown` / `dleft` / `dright`) for them.

The same fields are in the RAM map (`profiles/gamedata/G4BE08-ram.json`, group `menu`), so the RAM inspector shows
them. The map's pointer chain reads TW at stack top - 0x34, which holds while the task waits in its main loop. Check
`menu.task0_entry` first: in a room the chain points at garbage.

**Signatures, before any of it is trusted (`re4_menus.SIGNATURES`, `signed(m)`):** the first 16 code bytes of the
title task (`0x80161738`), the main menu handler (`0x801621F0`), the extra games' routine (`0x801633BC`) and Select
Stage (`0x801644C0`), and the routine table's first entries (`0x8020CC10`), as main.dol puts them in RAM. All of them
must match, else `screen()` says `unknown` (with an `error`) and `step()` presses nothing: another build, another
region or another game at these addresses is never read as RE4's menus. A match is remembered on the memory view
(`_re4_signed`), so the check costs one compare per run.

**In a room** (task 0 is the game loop) the screen comes from pG and the Mercenaries snapshot
(`re4_merc_bot.snapshot`):

| where | when |
|---|---|
| playing | a Mercenaries room (0x4xx) running (pG+0x20 = 3, or 4 changing rooms), with a player and time on the clock |
| results | the same, with the clock at 0 |
| dead | the player's health at 0 ("You Are Dead") |
| loading | the stage still loading (pG+0x20 0-2: the clock then shows the last round's time), or no player yet |
| story | a room outside the Mercenaries' (and not the title's 0x120): the run is off the path for good |

There is no `paused` yet: the pause menu is not read.

## The way to a round (`re4_menus.step`)

| screen | press |
|---|---|
| title (routines 0-4) | START |
| main menu | D-pad to THE MERCENARIES, then A; a menu built before the unlock bits went in: nothing (it idles back to the title and is built again) |
| New Game, Options, Load, Assignment Ada | B (never a pick there) |
| The Mercenaries' menu | up to GAME START, then A (never EXIT) |
| Select Player | left / right to Leon (the shorter way round), then A |
| Select Stage | to the Village, then A |
| a room: results (clock at 0), "You Are Dead" | A (next; Continue Yes) |
| setup, loading, starting, an attract movie as it ends | nothing: wait (START skips a movie only while it plays) |
| unknown (RAM can't name it, or the code doesn't match) | nothing |

**How presses are made** (`gbox.mercs_bot.Navigator`, shared by every title's menus):
- One press at a time, held 0.3 s (0.18 s for the D-pad). The menus move on the repeat word, and a longer hold can
  step twice.
- A screen is pressed on only once RAM has shown it for 0.5 s. A round's first frames run the room with the clock
  not yet set, which reads as the results for a moment; one A went in there before this rule (live 2026-10-20).
- The next press waits until RAM shows the last one took, or 1.2 s passed.
- `stats["ram_progress"]` counts every screen or cursor change. The black watch trusts it.
- Before a playbook starts, every pad key is released: a driver killed with a key down left the stick held, which
  read as "left" on every menu, and Select Stage never moved (2026-10-20).

**Off the path:** a story game starting from the main menu, or a story room, ends the run with `stats["hung"]`
(a bot demo is then relaunched). So do 30 s on a screen RAM can't name, or 120 s with nothing moving in RAM.

## The hooks and the menu moment

- `setup()` out of a round puts in only the unlock bits (`mercenaries_unlock`, RAM only), so the main menu lists THE
  MERCENARIES.
- At Select Player, before any code hook, the playbook saves the menu moment: this game and build's jump state
  (gbox.jumpstate, Dolphin's demo slot 10; the operator's slots are never written).
- Then it applies the rest of the hack package (`merc_loadout` and the code hooks), once per boot. On 2026-10-20 a
  Dolphin state saved after the hooks restored into a hang, and the same Dolphin taking the package a second time, plus
  the operator's kept mods from the desktop app, ended in a stage load that never finished. The package's ops now check
  the bytes they patch and write the same code again (idempotent); instant rounds (below) load states taken after the
  hooks and verify every load in RAM.
- A bot-demo launch, and the relaunch of a frozen one, boots straight into the menu moment.

## Instant rounds (no menus between rounds)

Operator 2026-10-26: "consistently playing without breaks in between rounds ... Even if we have to use save states".
`re4_merc_bot.InstantRounds` over `gbox.mercs.round_states` (Linux Dolphin only):

- **Capture.** At the first in-round frame of a round the menus started, the bot holds still and Dolphin's demo slot
  (`jump_save`, slot 10) takes a state. That happens only when the selects named the character and stage, the package's
  hooks are in RAM, and the library holds fewer than two states for that combination. The state goes to
  `<runtime>/round_states/<game id>-<build>-<disc id>r<rev>/` with a JSON receipt: room, stage, character, the clock,
  sha256, loads and failures. The library keeps at most 2 per combination, 40 per folder and 768 MB.
- **Load.** At a round's end (results, or Leon dead), MercMode gets the boundary first. After a 0.6 s beat, a state is
  copied over this game's slot-8 file and Dolphin's slot-8 load key is pressed (`checkpoint_load`, already bound in
  every gBox Dolphin). The file that was there is put back afterwards. The state is the DJ's pick, or a random stage and
  character that are neither the round just played nor its character. While combinations are missing, a share of the
  rounds walks the menus to one so that it gets captured.
- **Verify.** Within 6 s, RAM must show the state's room with the room routine on, Leon alive, the clock at the state's
  start and the VI count (`0x802B2D2C`) moving. The round then starts as a new round with its own boundary id, route
  map, `rounds` count and `round_gap_s`. The package found in the state counts as applied, so `arm_round` never stacks
  it on itself; a state without the package gets it now. The state's pending equip (`0x80002F24`) is cleared, so the
  round's own random gun stays in hand.
- **Fallback.** If RAM never shows the loaded round, the menus walk on from the results screen, and the walk heads for
  that combination so a fresh state replaces it. After 2 failures a state is dropped; after 3 failed loads in a row,
  instant rounds go off for 6 h. If a load freezes the game (the VI count stops), the run ends as hung (relaunch), the
  state is dropped and instant rounds go off for 6 h.
- **Off.** Set `INSTANT_ROUNDS = False` (a bot hot reload) or launch with `mercmode.instant_rounds: false`.

## Between rounds: the menus' watch and phantom rounds (2026-10-26)

- The menus' "nothing moved in RAM" and loading clocks (`mercs_bot.Boot`, `Navigator`) start again whenever a round
  starts (`Boot.round_played`). Before, they ran on through the round. A stage's first frames run the room with the
  clock still at 0 and read as results, so a round that began on that frame and ended on the results screen showed no
  change at all. The round's whole length counted as "nothing moved in RAM for 154 s on results", and every RE4
  MercMode turn on the Spark that day ended there as hung (ten runs).
- A results screen ends a round only after the clock was last seen at 5 s or less (it ran down to 0). A retry without a
  load the bot saw counts only once the clock is back up. Continue restores Leon's health on the death screen first,
  and then the reload's first frames read as results: together that made an 11 s phantom round that MercMode counted.
- re_mods calls that run game code (`equip`, give items: `RE4.call` through the dispatcher at `0x80122610`, which runs
  every frame, loads included) wait for a running room (pG+0x20 = 3 and a player); during a load or a menu they
  refuse with "the game is loading a room or showing a menu".
- The Sessions view no longer switches the operator's kept mods on by itself in a bot demo or an agent's session.

## Checked

- **Static:** the routines and fields above, from main.dol.
- **Two MEM1 dumps from Dolphin 2609 save states** (LZ4: StateExtendedBaseHeader, compression 1; MEM1 found by the
  disc id):
  - Select Player: task 0 = `0x80161738`, TW `0x80A55860`, routine 6 step 8, main menu 5 items with the cursor on
    THE MERCENARIES, GAME START, Leon, Village, pG+0x54 = 0x50000000.
  - The Village start: task 0 = `0x80116640` (the game loop), room 0x400.
- **Unit tests** (`tests/test_re4_menus.py`): a simulated title task walked from the title to a round. The only picks
  are THE MERCENARIES, GAME START, Leon and the Village. `tests/test_mercs_bot.py` walks the same simulated RE4 to two
  rounds through the deployment playbook.
- **Live, 2026-10-20 on the Spark** (an agent test session, the branch's playbook driven standalone with RAM read from
  the session's own Dolphin and the pad through the session input API; real frames in
  `docs/evidence/bot-demos-anywhere/`, each taken when RAM named a new screen; the stream's picture trails RAM by up to
  a second):
  - From the attract movie to a Village round in 26 s, by RAM alone: START skipped the movie; the main menu's cursor on
    LOAD (3), up to THE MERCENARIES (2), A; GAME START; Leon; the Village; the round on (room 0x400, pG+0x20 3, the
    clock at 120.0).
  - After the round it went back through the title task (the Mercenaries menu, Select Player, Select Stage) to the
    Village again.
  - Select Player's order comes from a real frame: RAM cursor 2 is Jack Krauser.
  - A re-run with this code (22:52 CST): the main menu to a Village round in 20 s, with no press during the stage
    load. Leon died twice (the hooks, sent as re_mods jobs, waited in CPU admission and never went in). Each time the
    stage reloaded and the round restarted at 120.0: three rounds entered in 2 min 06 s, no story, no wrong pick.
  - Still to see live: a round that runs out its clock, the Results, and the menus to the next round; and the menu
    moment. Both need the in-worker playbook after deployment, where the package goes in inside the autoplay job.
