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
- Then it applies the rest of the hack package (`merc_loadout` and the code hooks), once per boot. A Dolphin state
  saved after the hooks restores into a hang. The same Dolphin taking the package a second time, plus the operator's
  kept mods from the desktop app, ended in a stage load that never finished (2026-10-20).
- A bot-demo launch, and the relaunch of a frozen one, boots straight into the menu moment.
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
  - Not yet seen live: two full rounds in a row, and the menu moment (a jump state needs the worker-side playbook).
