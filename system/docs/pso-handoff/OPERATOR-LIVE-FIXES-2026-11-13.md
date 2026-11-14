# PSO live operator fixes — status flag, units, doors, 3-second handover (2026-11-13)

This is the record of the fixes made while the operator played the running GameCube PSO Episode I & II Plus session
(session `6083c2c087524581-594b14c30d3a4c69`, floor 3). Every claim below was measured on the live session; the scripts
are in `system/docs/research/` and every write went through the audited `write_memory` job or the game's own native
routines through the already-installed gBox dispatcher (header `GBPSOGC4`, `VT_UPDATE -> 0x80004C00`).

## 1. The status-ailment flag: `TObjPlayer + 0x254` (u32, big-endian)

The operator's paralysis ("attack is disabled") lived in one word of the player actor:

| observed value | meaning | effect |
|---|---|---|
| `0x00000010` | Paralysis | attack/tech input ignored |
| `0x0000000F` | Poison | attack works, HP drains ~1/s |
| `0x00000000` | no ailment | normal |

Measured both ways: the word read `0x10` while the attack press left the action-state word (`+0x326`) and hit-record
count (`+0xA8`) flat; the same session later read `0x0F`, attacked normally, and drained HP (34 → 31 → 27 → 14 → 1).
Writing zero to `+0x254` stopped the drain dead (ten samples at 1 HP) and the HP was then restored to 67/68.

The likely PSO status ids match the gc-forever attack-effect ids: `0x02` Freeze, `0x03` Shock, `0x0F` Poison,
`0x10` Paralysis, `0x11` Slow, `0x12` Confusion. Only `0x0F` and `0x10` were observed here.

`pso-operator-guard.py` polls the word and clears it — that is the "flip the flag" remedy the operator asked for; it
also makes any future ailment clear within ~0.2 s whatever applied it.

## 2. Unit slots: the game's own `F_EQUIP` takes a slot row, and frames need their record patched

* `F_EQUIP(player, item_object, slot)` (`0x801B9F40`): when the item's category is not weapon-like the third argument
  is clamped to **9..12** — those are the four unit rows of the equipment array at `player + 0xD04`. Passing `0` for
  every unit is why the first four attempts each replaced the previous unit (row 9 only).
* A frame's unit-slot count lives in its **20-byte create record, byte 4**. The live records are in the `0x80Fxxxxx`
  heap, 28 bytes apart (20-byte record + 8-byte trailer) — *not* the Dreamcast 28-byte slot layout, which is why both
  the app's `pso_inventory` and a byte scan for the Dreamcast format answered "inventory not found".
* The Brightness Circle frame was patched `data1[4]=4` and then all four Cure units were equipped into rows 9-12:
  Cure/Paralysis `010343`, Cure/Shock `010347`, Cure/Freeze `010346`, Cure/Confuse `010345`.

`pso-native.py` does this through the native command queue: it writes `[fn, r3..r10, result]` 40-byte commands to
`0x80004400` and polls them through the audited write_memory job. The queue and dispatcher are the ones gBox installs,
so this does not add a second owner.

## 3. Doors: the native stage-flag array is the gate, and it is writable

`0x80515CC8`, 18 groups of 32 bytes, **group = current floor** (`0x805D5FC0`); flag `index` (0..255) is byte
`group*32 + index//8`, mask `0x80 >> index%8` (verified earlier by the co-op lane from the accessor at `0x80229220`).
Per-object native state is recomputed from these flags every frame, so setting the bit is what opens the gate.

`pso-operator-guard.py` watches the player's distance to any door/barrier/fence (classes containing `TODoor`,
`TObjLazerFenceNorm`, `TOBarrierEnergy01`, ...). When a door is within 42 units it sets the stage flags of every
switch/panel in the room and of the nearby energy barriers. First live receipt: in room 34 near `TODoorCave02@15` it
set flags `[60, 61, 62, 90, 91, 100, 101]` on floor 3.

## 4. Three-second operator handover, and demonstration capture

`pso-autoplay-loop.py` is the supervisor:

* watches the operator's physical pads (XInput slots 1-3; slot 0 is gBox's virtual pad = the bot), the Dolphin
  keyboard bindings, and the app's session-pad view (**only `player`/`ui` sources** — the view also carries the bot's
  own reported input, which caused one false handover before it was filtered);
* while operator input is fresh (last 3 s) it touches `D:\gBox\pso-ds\operator-playing.flag`, runs
  `pso-demo-recorder.py` so the operator's play is captured as a synchronized input+RAM trace, and keeps the bot off;
* after 3 s of silence it withdraws the flag, closes the recorder (which segments the demonstration and appends to
  `skills.json`), and runs `pso-bounded.py play` in 60-second bounded chunks (the bounded player's own OperatorGuard
  still preempts it mid-tick if the flag returns);
* both live guards (status clear, door unlock) run in its loop, during operator play and bot play alike.

`pso-operator-modes.py` keeps the operator's standing preferences: Randomized gear on a **120 s** interval
(weapon/shield/mag; the frame and its cure units are intentionally excluded so the immunity survives the rotation),
and re-applies the cure units if they ever come off.

Measured limitation: the bounded combat is still weak — in the first 60 s chunk it made 6 combo attempts on a
`TObjEneShark` at 14-18 units with **0 hits** (melee reach is shorter; the policy default attack range was reduced
from 20 to 11 in `pso_bounded.ProgressionPolicy` afterwards). Progress in room 34 was an orbit at `(-390,990)`.
Recorded operator demonstrations are the intended fix: the trace becomes a replayable route
(`demo-*-route.jsonl` -> `pso-bounded.py walk --route-file`) and the segmented skills carry the observed
preconditions/actions/results.

## 5. Tool inventory (all in `system/docs/research/`)

| tool | role |
|---|---|
| `pso-native.py` | native game-thread calls via the gBox dispatcher queue; frame slots + unit equip; generated-item removal |
| `pso-operator-guard.py` | status-word clear + door stage-flag unlock (functions also imported by the supervisor) |
| `pso-autoplay-loop.py` | 3 s operator/bot handover supervisor, demo recording, live guards |
| `pso-operator-modes.py` | Randomized 2-minute gear rotation keeper + cure-unit re-apply |
| `pso-demo-recorder.py` | operator input+RAM demonstration recorder and segmenter |
| `pso-ram-find.py` | full-RAM dump/locate (used to find the item-record arena) |
| `pso-status-probe.py`, `pso-status-fix.py`, `pso-status-brute.py` | status-field discovery and test tools |
| `pso-live-inventory.py` | session-RPC inventory scan (kept for the record; the GC arena is not the DC layout) |

Evidence: `D:\gBox\pso-ds\mandate\` (`status\ram-*.bin`, `native-equip-*.json`, `operator-guard.jsonl`,
`autoplay-loop.jsonl`, `autoplay-bot.log`), `D:\gBox\pso-ds\bounded\play-*.jsonl`.
