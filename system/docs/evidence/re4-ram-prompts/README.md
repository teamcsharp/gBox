# RE4 GameCube: the action prompts, QTEs and doors read from RAM

Operator, 2026-10-20: "Surely when it comes to the dialogue of A needing to be pressed, that there are hex keys or
codes in the RAM that come up that basically tell us this information" ... "Vision analysis to me should be the last
level that we have to fall back to".

`gbox/re4_ram_prompts.py` reads the game's own action-button state (Resident Evil 4, GameCube NTSC-U `G4BE08`). The
Mercenaries playbook (`gbox/re4_merc_bot.py play()`) asks it first; the screen detector (`gbox/screen_prompt.py`) is
only asked when RAM can't tell (another game, a failed read, a button kind the tables don't know).

## What RAM says

| what | where | values |
|---|---|---|
| a prompt is up, and its button | `0x80279320` u8 (the kind the action manager drew this frame) | 0 none, 1 / 2 / 0xE A, 3 L+R, 4 A+B, 5 B, 6 X, 7 Y, 0xB SHAKE OFF (waggle the stick, or mash A / B) |
| which prompt | message slot 1 `0x80213E64`: +4 bit 0 on screen, +0x98 the slot's read cursor in the label's message | message bank 0 id = label + 0x16: TAKE 0x28, JUMP OVER 5 / 0x12, KICK 7, OPEN 0x10, CLIMB UP 8, CLIMB DOWN 9, JUMP DOWN 4, JUMP IN 3, JUMP OUT 2, PUSH 6, DODGE 0x25, SHAKE OFF 0x2B ... (`LABELS`) |
| what it belongs to | the action manager's node pool `0x80278B28` (8 x 0x18) | label, priority, dispatch (0 call, 2 area event), kind, data (the AEV entry, door, Ganado), callback, owner |
| an action passed its check this frame | `0x80278B26` u8 | 1 / 0 |
| the area events Leon stands in | AevMgr (`*0x802B3178` = `0x80289B3C`) +0x10, 32-byte bitset by entry index (+0x36) | the room's AEV / ITA entries, walked through the manager's 16 lists |
| a door opening | Leon (`*0x802B3044`) +0xFC = 4 (an object action), +0x3B8 the door em (em id +0x100 = 0x41), `0x801F4C14` = 0x800DDA0C / 0x800DDDC8 (the door routines); an area-event door instead sets pG+0x20 = 4 (room change) with the room in pG+0x28 | `door_from_ram()` |
| what Leon is doing | Leon +0xFC..0xFF: `00 ..` under the player's control, `01 00 01 00` held by a Ganado (SHAKE OFF), `04 ..` an object action: a door (above) or a kick (the Ganado's em at +0x3B8, a routine in its code module at `0x801F4C14`) | `leon_from_ram()` |

How they were found: capstone over the disc's `main.dol` (the routines are listed in the module's docstring). The
action manager's register routine `0x800B207C` is called by every source of a prompt; its per-frame `0x800B1950`
draws the first node that passes its check (`0x800B1AFC` stores the kind at `0x80279320` and draws the label in
message slot 1) and runs its callback on the button (`0x800B1D24`, which also names the buttons through the game's pad
bits; the pad map `0x80207380` ties those bits to A / B / X / Y / L / R). The labels' text came from the disc's
`etc/core.das` message file and was then read out of the live RAM.

## How each value was checked in the game

1. **Real RAM before the live run** (Dolphin's `lastState.sav` of the earlier session, 16:08 CST, decoded out of its
   LZ4 block): the message bank 0 language block at `0x806C929C` reads TALK, JUMP OVER, KICK, OPEN, TAKE, SHAKE OFF at
   ids 0x16, 0x1B, 0x1D, 0x26, 0x3E, 0x41 (label + 0x16); the node pool still held the last frame's two TAKE nodes
   (label 0x28, kind 1, priority 8, dispatch 2, data = ITA item entries, callback = the item handler `0x8014E308`,
   owner = Leon); slot 1's message pointer sat 0xC bytes into TAKE (so the module looks the label up by the message
   that contains the pointer, not by its start).
2. **Live, read only** (session `e2771e1c892e46e9-d7dbf0129c4f4b1b` on lilspark, display :90, the agent's Mercenaries
   bot playing the Village, 2026-10-20 16:59-17:12 CST): `action_from_ram()` and `screen_prompt.detect()` at 12 Hz
   on the same moments (Dolphin's shared RAM view through `/proc/<pid>/mem`; the X display read with `XGetImage`),
   8,374 samples in rounds, frames saved at every change:

   | RAM \ screen detector | none | A icon | B icon |
   |---|---|---|---|
   | no prompt | 8,097 | 19 (the screen one sample behind) | 1 (fire behind Leon: a false B) |
   | A (TAKE, OPEN, JUMP DOWN, KICK) | 27 (RAM one sample ahead) | 175 | - |
   | SHAKE OFF (`wiggle`) | 53 | - | 2 (the stick icon's red arrows) |

   32 prompts came up: TAKE 19, OPEN 6, SHAKE OFF 4, KICK 2, JUMP DOWN 1, every one with the text the screen showed.
   The screen detector saw 27 of them (it never sees SHAKE OFF's stick icon as a button). RAM leads the picture by
   one sample at both ends (median 84 ms, at most 96 ms).
3. **The node behind each prompt** (same run): TAKE = dispatch 2 (area event), priority 8, the item handler
   `0x8014E308`, data = the ITA entry (`aev.kind` item); OPEN = a door object (callback `0x800DD8C4`, data = the door
   em, em id 0x41); KICK = priority 0xB, data = the stunned Ganado's em, callback in the Ganado's code module loaded at
   `0x8172AB80`; JUMP DOWN = Leon's context check, callback `0x8013CF7C`; SHAKE OFF = no callback (the grab code counts
   the presses itself, Leon +0x518).
4. **A door opening** (same run): right after each OPEN press, Leon +0xFC..0xFF went to `04 00 01 00` with the door em
   (em id 0x41, EmMgr slot 23) at +0x3B8 and `0x800DDA0C` at `0x801F4C14`, while the picture showed him pushing the door
   (`door-opening.png`). A kick gives the same routine 4 with a Ganado (em id 0x16) and a routine in its code module.

## Frames

Each is a real frame of the run with the RAM values read at the same moment written under it.

| file | prompt |
|---|---|
| `take.png` | A TAKE (an item; RAM: kind 1, label 0x28, area event item) |
| `open.png` | A OPEN (a door object) |
| `jump-down.png` | A JUMP DOWN (off the start roof) |
| `kick.png` | A KICK (a stunned Ganado) |
| `shake-off.png` | SHAKE OFF (a grab: the stick icon; the screen detector read it as a B) |
| `door-opening.png` | no prompt: Leon opening the door (RAM: door object, routine `0x800DDA0C`) |
| `no-prompt-false-b.png` | no prompt in RAM while the screen detector saw a B in the fire |

## Not seen in the game yet

Static analysis only, no live moment yet: the QTEs (DODGE / JUMP with A+B or L+R, kinds 4 / 3: the Village has
none), JUMP OVER (fences), JUMP IN / JUMP OUT (windows), CLIMB UP / CLIMB DOWN (the ladder AEV and the ladders the
Ganados raise), KNOCK DOWN, X / Y prompts (kinds 6 / 7), and an area-event door (pG+0x20 = 4: the Village has no AEV
doors). Kinds 9 / 0xA (story QTEs in the stage modules) are pressed by their own code: RAM reports them as unknown and
the playbook asks the screen.

## Files

- `gbox/re4_ram_prompts.py`: `prompt_from_ram`, `action_from_ram`, `leon_from_ram`, `door_from_ram`,
  `aev_entries`, `zones`, `items_from_ram`, `source` (the playbook's RAM prompt source); `python -m
  gbox.re4_ram_prompts 60` prints every change live (Dolphin on Linux).
- `tests/test_re4_ram_prompts.py` with `tests/fixtures/re4_ram_prompts.json`: the RAM read at moments of this run
  decodes to the prompt the frame shows.
- `profiles/gamedata/G4BE08-ram.json`: the same fields in the RAM map format (`docs/ram_maps.md`).
