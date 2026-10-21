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
| TW+0x28 u32 | main menu cursor | with the extras: NEW GAME, ASSIGNMENT ADA, THE MERCENARIES, LOAD, OPTIONS (codes 6, 2, 3, 4, 5); without: NEW GAME, LOAD, OPTIONS (1, 4, 5) |
| TW+0x54 u8 | The Mercenaries' menu | 0 GAME START, 1 EXIT |
| TW+0x55 u8 | Select Player | 0 Leon, 1 Ada, 2 HUNK, 3 Krauser, 4 Wesker (left / right, wraps) |
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
| setup, loading, starting | nothing: wait |

**How presses are made:**
- One press at a time, held 0.3 s (0.18 s for the D-pad). The menus move on the repeat word, and a longer hold can
  step twice.
- The next press waits until RAM shows the last one took, or 1.2 s passed.
- `stats["ram_progress"]` counts every screen or cursor change. The black watch trusts it.

**Off the path:** a story game starting from the main menu, or a story room, ends the run with `stats["hung"]`
(a bot demo is then relaunched). So do 30 s on a screen RAM can't name, or 120 s with nothing moving in RAM.

## The hooks and the menu moment

- `setup()` out of a round puts in only the unlock bits (`mercenaries_unlock`, RAM only), so the main menu lists THE
  MERCENARIES.
- At Select Player, before any code hook, the playbook saves the menu moment: this game and build's jump state
  (gbox.jumpstate, Dolphin's demo slot 10; the operator's slots are never written).
- Then it applies the rest of the hack package (`merc_loadout` and the code hooks). A Dolphin state saved after the
  hooks restores into a hang (2026-10-20).
- A bot-demo launch, and the relaunch of a frozen one, boots straight into the menu moment.

## Checked

- **Static:** the routines and fields above, from main.dol.
- **Two MEM1 dumps from Dolphin 2609 save states** (LZ4: StateExtendedBaseHeader, compression 1; MEM1 found by the
  disc id):
  - Select Player: task 0 = `0x80161738`, TW `0x80A55860`, routine 6 step 8, main menu 5 items with the cursor on
    THE MERCENARIES, GAME START, Leon, Village, pG+0x54 = 0x50000000.
  - The Village start: task 0 = `0x80116640` (the game loop), room 0x400.
- **Unit tests** (`tests/test_re4_menus.py`): a simulated title task walked from the title to a round. The only picks
  are THE MERCENARIES, GAME START, Leon and the Village.
- **Live:** see the bot-demos-anywhere PR.
