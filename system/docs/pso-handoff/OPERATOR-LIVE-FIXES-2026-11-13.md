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

## 6. Round 2 - the autonomous player stops orbiting and changes room (same night)

The bounded player had three measurable reasons to stand still, each fixed in `gbox/pso_bounded.py` and verified live:

1. **It chased unreachable enemies forever.** In Cavern 1 room 34 a `TObjEneShark` sat at 15-23 units for minutes (37
   consecutive ticks on that one objective) with **0 combo attempts**, because the loop never got inside attack range -
   the enemy was unreachable by walking. `Automaton._account` now tracks the best distance to the current wave: no
   closing for 8 s, or 20 s on the same enemy in total, hands it to the policy's `avoid` list so a door or another
   target becomes choosable.
2. **Its melee range was too long.** `ProgressionPolicy.attack_range` was 20 units, then 11, against a starting Saber;
   it is now **8.0**, so a combo starts only inside real melee reach (the operator's earlier handoff measured the real
   PMT ranges at 13-30 for the weapon classes, but the starting Saber is the short end and whiffs outside ~10).
3. **Doors were not objectives at all.** `DOOR_CLASSES` holds only the generic names `TObjDoor`, `TObjLazerFenceNorm`
   and `TOBarrierEnergy01`; every Cave-1 door instance is `TODoorCave02`/`TODoorCave03`, so the policy never saw them
   and the character wandered in place. The policy now matches the **door family** ("Door"/"Fence"/"Barrier" in the
   class) as a rank-3 exploration objective (below waves/switches, above optional loot), aims past it through the
   existing door plan, and a door that produced a settled room change is added to `avoid` so the old 280-tick
   ping-pong cannot return.

Live result, verified in the session and the hash-chained ledger: the bot crossed from **room 34 to room 40** in Cave 1
(positions `(-165,792)` -> `(26,704)` -> `(73,713)`; `progress room` in `play-20261113-223942.jsonl`), and then picked
the room's **`TLazerFenceSw`** switch as its next objective. The door-unlock guard logged the stage-flag sets that let
that doorway open, and the status word stayed `0` throughout.

Remaining known weakness: the character has been sitting at 1 HP (the game did not raise it after the earlier damage
dump), and combat still reports 0 hits - the approach/range model needs the operator's recorded demonstrations to
calibrate facing and reach per weapon, which is the next use of `pso-demo-recorder.py`.

## 7. Round 4 - the RAM half of the map bridge: live collision grid -> 2D route map -> routed bot

The co-op geometry provider (`gbox.pso_coop_geometry`) already knew how to read the game's loaded collision REL out
of memory, but its `Provider` refuses any floor outside town/Forest and requires two players, so the single-player
live session had no map at all. The same internals work fine for one player - and for any area - when called
directly:

* **`pso-live-map.py`** - reads the collision roots (`0x805D4E68/0x805D6000/0x805D6014/0x805D5650`), the manager
  mesh table and the 380 KiB allocation (Cave 1's allocation is larger than the 256 KiB co-op budget, so it reads it
  in 64 KiB pieces), re-parses the triangles with `psomap`, projects the player with `Atlas`, and writes the floor's
  walkable cells as a `forest_route.MapRouter` grid. Live Cave 1 receipt: **8,487 triangles, digest
  `90afe75e8627`, 210,116 walkable 2.5-unit cells** - and the character's own cell is guaranteed present because it
  was projected by the same atlas.
* **`pso-route-plan.py`** - A* over that live grid to the nearest door/switch/enemy/warp or a coordinate; prints
  waypoints the existing `pso-bounded.py walk --route-file` can replay. First plan: nearest `TODoorCave02` 217 units
  straight, 233 units of walkable route, 76 cells.
* **`pso-autoplay-loop.py`** - now dumps the live map before every bot chunk and passes `--map/--map-name` to
  `pso-bounded.py play`, so the bounded player's objectives are pursued along real collision instead of a hill-climb
  straight line. Receipt in `autoplay-bot.log`: `routing over live-floor3-90afe75e8627: 210116 safe cells`.

One bug surfaced and is fixed: the route CLI's coverage test compared **world coordinates to cell numbers**, so it
declared the live map "101 units away" and dropped the router. It now converts the player through `router.cell()`
first; the same chunk then logs the routing line with no coverage warning. In the same window the routed bot produced
its **first verified combat hit** (`combos: attempts 5, hits 1, progress enemy-hp`) and kept moving across the room
instead of orbiting.

The operator also asked for proximity door unlocking; `pso-doors-always.py` now saturates the current floor's whole
stage-flag group as soon as any door/barrier/fence is within **30 units** (permanent - nothing clears it), after the
measured fact that setting only the room's switch bits left the Cave door at (-600,805) shut while the full-group
write opened it and the character crossed room 34 -> 8 within two seconds.

## 8. Round 4 - max-grind weapon guarantee, and recovering the game from a Dolphin panic dialog

The operator: "This weapon is so weak. Make sure that any weapon you give the character is grinded to the maximum
level." Two measured facts made this a one-byte problem and a process problem:

* A weapon's grind is **byte 3 of its 20-byte item record**, and the disc's ItemPMT exposes each weapon's own
  maximum through `GET /api/pso/items?version=gc` (`max_grind`). The old randomized rotation created its rares
  through the game's give path with that byte at 0, which is why every rotated weapon was +0.
* The live record the game reads is stored in the **TItem object**; heap copies of the record (save image etc.) are
  stale, and poking them changes what a scan shows but not what F_INVENTORY reports. Trying to resolve the object
  with F_FIND_ITEM/F_ITEM_OBJECT by hand **crashed the emulator** (Dolphin modal: "Invalid read from 0xdb037816,
  PC = 0x801d56e0") - the game sat frozen behind that dialog for ~25 minutes while every clock in RAM stayed
  constant. The dialog was dismissed by clicking "Ignore for this session" (screen capture of the dialog kept as
  `mandate/dolphin-warning.png`); the game resumed and the queue drained immediately.

`pso-grind-max.py` now avoids the item-object route entirely: it creates the weapon through the game's own 6x2B
create path (prepare record in BUF -> create TItem -> attach -> equip -> F_STATS) with the grind byte already at the
PMT maximum, then verifies the equipped row's `data[3]`. `--equip-best` picks the strongest class-compatible
grindeable weapon by `atp_max + 2*max_grind`. The randomized rotation was stopped (it was the +0 weapon source);
`--watch` keeps any grindeable equipped weapon at its PMT maximum.

Live receipt: **TSUMIKIRI J-SWORD (003200), grind 50 (= its PMT maximum), equipped and verified**, inventory
returned to 22 rows by removing unequipped generated gear.

## 9. Round 5 - the local server died, and the session was rescued from the operator's own snapshot

While restarting the autoplay supervisor I killed its process group and the Windows local authority
(`gbox.desktop_local`, which hosts the worker **in-process** and is the parent of Dolphin) stopped serving: the
TCP listener on 127.0.0.1:18765 disappeared while the process stayed alive, the control plane reaped the session
(`{"reason": "worker offline", "via": "reap"}`), and the game could no longer be controlled even though Dolphin
itself was still running.

The rescue worked because the operator had taken a `state_transfer op=snapshot` at 23:28:34 (artifact
`4ccd99fe106a684d5ef51a1c00adf922f745717cb48d2690222b6d4200f9fc1f`, 21.7 MB). A snapshot artifact is a **Dolphin
savestate** (`GPOE8P` header), not a cloud blob, and the tool's `import` operation copies it to
`User/StateSaves/GPOE8P.s01` and presses the adapter's load-state hotkey. Sequence, all scripted in
`pso-rescue-session.py`:

1. kill the orphan Dolphin and the dead `desktop_local` pair; the Electron app **respawned its own local server**
   on 18765 within seconds (it supervises that child);
2. `launch_game` with the cached catalog entry (`mandate/pso-catalog-entry.json`, worker `ee68c2f40f10443b`) -
   new session `ee68c2f40f10443b-a5dc25262b4f4765`, running in ~20 s;
3. `state_transfer op=import artifact=4ccd99...` - the import reports `slot_verified: true` and
   `bytes: 22,777,915`;
4. verify through the new session's own RPC: player back at `(525.2, -53.7)` room 1, HP 1, status word `0`,
   and the equipped **TSUMIKIRI J-SWORD at grind 50** - the exact moment from 23:28;
5. a fresh safety snapshot of the restored moment was taken immediately (artifact
   `87041c7be1439e9ea25955ac87cdd2deaf3eca93eeb3b9db6c1e992ab6e4ef83`).

The autoplay supervisor, the proximity door unlock and the max-grind watchdog were then restarted against the new
session: live map `live-floor3-90afe75e8627` (8,487 triangles / 210,116 cells), weapon family `Weapons:tsumikirijsword`
mapped to attack range 16, and the bot resumed room traversal (room 1 -> 30).

Lessons recorded for future rounds: the button that ends a session is the worker's death, not Dolphin's; a killed
`desktop_local` is respawned by the Electron app but its sessions are reaped; and any long play session should be
periodically snapshotted with `state_transfer op=snapshot` so a worker loss costs minutes, not hours.

## 10. Round 6 - combat starts hitting, and the snapshot safety net becomes automatic

With the restored session running, two things were measured/added:

* **Weapon-family attack reach.** The bot's combo decision used one fixed range, which was wrong for every weapon but
  the starting Saber (it whiffed at 14-18 units against a Saber's short reach). The supervisor now reads the equipped
  weapon's `family_key` from the disc catalog and passes `--attack-range` to the bounded player
  (`system/docs/research/pso-autoplay-loop.py: REACH_BY_FAMILY`). Live verification with the TSUMIKIRI J-SWORD
  (`Weapons:tsumikirijsword`) at range 16: `combos: {"attempts": 6, "hits": 2, ...}` and the target
  `TObjEneShark` vanished (combat kill) - the first real hits in the live session.
* **Automatic moment snapshots.** `pso-snapshot.py` submits `state_transfer op=snapshot` for the live session every
  5 minutes and records each artifact in `mandate/snapshots.jsonl`. First live artifact:
  `ae54b7d976313456d540c9f495657ece7b5184e20228a13da56bc319c877108b` (22.9 MB Dolphin savestate). This is the
  safety net that made the earlier rescue possible, now running without a human remembering to press it.

## 11. Round 6b - learning the hit rules from the operator's own demonstrations

`pso-combat-learn.py` streams the recorded demonstrations (the operator plays on the keyboard, so every attack is a
`{'src':'keyboard','keys':['A']}` rising edge in the trace), joins each press with the sample taken beside it (player
position + heading, every entity with its HP) and resolves it against the following 2.5 s of samples. Across 18
traces / 13 presses with a target / 10 resolved: **10 hits, hit rate 1.0**, with every hit at **9-22 units** and
inside a tight facing cone. Output: `mandate/combat-model.json` and `system/docs/research/pso-combat-learn.py`.

That changed two things in the bot:

* **Face the enemy before swinging.** `Automaton._plan` for a wave objective now measures the angle between the
  player's heading and the enemy's bearing when inside attack range; past `aim_tolerance_deg = 40` it spends one
  movement step to re-aim instead of burning the combo. (The operator's hits were all within ~10 degrees.)
* **Weapon reach from the demonstrated data.** The supervisor's family table now gives the sword class 18 units and
  the partisan 20 (was 16/18), still conservative against the demonstrated 22-unit hits.

Also verified live this round: the restored bot walked Caves 1 from the entrance (room 1, z ~ -50) to room 50
(z ~ 985) across successive 60-second chunks with zero failures, status word kept at 0 the whole time.

## 12. Round 8 - deliberate floor coverage: learn the door graph, then walk through every new doorway

The bot spent chunks wandering the same two bordering Cave rooms because nothing knew which doorway had been
crossed. Three small pieces turn that into coverage:

* **`pso-door-crossings.py`** samples the session ~1 Hz, confirms a room change on a second read (the room value
  flickers at boundaries) and records `{floor, layout, from_room, to_room, x, z}` in `mandate/door-crossings.jsonl`.
  The layout name is the collision digest from the live map dump, so a randomized map never inherits another
  layout's door knowledge.
* **`pso-frontier.py`** joins that log with the live entity list: it picks the nearest door **in the current room
  that has never been crossed** (falling back to a door leading to an unvisited room), and prints its coordinate.
  Switch panels (`TLazerFenceSw`, `TObjDoorKey`) are excluded - they are pressed, not walked through.
* **`pso-autoplay-loop.py`** asks for a frontier door before each chunk and, when one exists, runs
  `pso-bounded.py walk --to <door> --through` instead of open-ended play. A doorway that fails twice in four minutes
  is skipped for a while so a blocked gate cannot consume the session.

Live receipt in the restored session: the first frontier chunk drove the character 156 units to a never-crossed
`TODoorCave02`; the crossing tracker recorded **room 50 -> 111 at (322.2, 817.9)** (then 111 -> 40), the door is now
learned, and the next frontier target switched to a different never-crossed door in room 40 (200, 805).

## 13. Round 9 - frontier navigation that checks reachability, and routes through learned doors

The first frontier pass could pick a door that the collision mesh cannot reach (Cave 1's (-200,805) door sits behind a
closed gate in the static mesh), so a whole 60 s chunk drove at nothing. The planner now:

* builds the same `forest_route.MapRouter` grid from the newest `live-map-floorN-<digest>.json` and rejects a door
  whose collision route is `None` (recorded in `door-blocked.json`; the veto expires in 15 minutes because a gate can
  open later);
* when the current room has no unexplored door, runs BFS over the learned room graph (crossings joined to door
  positions) to the nearest reachable room that still has one, and returns the **first hop's door**;
* logs every decision to `mandate/frontier.jsonl`.

Live this round: the planner vetoed (-200,805) and (0,605) as unreachable, redirected to (0,1005), and the bot then
crossed **40 -> 111 at (213.9, 818.0)** and **111 -> 50 at (339.1, 818.1)**, adding both doorways to the learned
graph (7 crossings logged); the next frontier target is a never-crossed door in room 50 at (520,1105), 311 units
away with a verified route.

## 14. Round 9 - a native-call panic killed the guest; recovery to a clean boot

Shortly after 00:03 the live game froze for good: all of MEM1 was static (1 changed word of 6.29M in a second), the
Dolphin window kept a stale frame, and its GDB debug port (52764) no longer accepted connections. A Dolphin
"Warning: Invalid read from 0x00000048, PC = 0x80101d4c" **panic** had appeared (PC inside the item/create code); it
was dismissed with "Ignore for this session", but the guest CPU never advanced again - the emulator process stayed
alive and busy, so no hotkey, pause/resume cycle (`win_suspend_emulation`, 77 threads) or in-emulator savestate load
could restart it.

The only working actuator left was the memory-write path, and re-importing savestates into the half-dead emulator
kept landing on the same halted CPU. Recovery therefore relaunched: `launch_game` closes the stuck session, starts a
fresh emulator, and `state_transfer op=import` restores a snapshot. `pso-relaunch-restore.py` scripts that flow
(stop/relaunch -> import -> re-arm the Virtual Scape Doll -> report the player), and `pso-boot-restore.py` adds the
"drive the boot menus until the player entity exists before importing" step. In the end the old snapshot states
themselves re-froze shortly after import, so the session was taken to a **clean boot** with `pso-session.py restart
--force`: player 68/68 HP in Pioneer 2, permanent Scape Doll re-armed, TSUMIKIRI J-SWORD +50 re-created through the
max-grind give path, and the autoplay supervisor restarted.

Suspected trigger and mitigation: the **grind watchdog polled `pso_controls op=list` every 2 s**, which makes the
worker run native F_INVENTORY on the game thread; during an area/loading transition that call can hit a stale
inventory pointer. The watchdog has been stopped - every weapon gBox gives is already created at its PMT maximum, so
the guard is only needed if the randomized rotation is re-enabled. The lesson: no high-frequency native polling
against a live game; read-only RAM passes (status word, doors, position) are safe, native calls are not.

## 15. Round 10 - T0 gate driver: town -> Forest, controller-only, counted

The clean session after the round-9 recovery is in Pioneer 2, which is exactly where the mandate's first gate lives, so
`pso-t0-trial.py` was written to prove it: the character must reach Forest 1 through the **Pioneer 2 warp pad** using
only controller input (no dev warps, no memory writes), ten times.

What the live session taught the driver:

* The real pad is the `TObject` at world (360, 26); `TObjCityDoor_Warp` at (254, 25) is only the door marker.
* The pad's destination menu needs **two A presses about a second apart** (first opens FOREST 1 / CAVE 1 with FOREST 1
  highlighted, second confirms). One press only opens the menu; the earlier "pressing A did nothing" reading was that.
* The Forest 1 return pad is a `TObject` at (12.1, -16.6); a single A returns to Pioneer 2 and plays the warp-out
  effect. Forest arrival is near (-9.7, 22.8), town return near (285-360, 16-25) - close enough that the plaza railing
  needs a detour only when starting far away: the town leg uses `(255,-5) -> (340,50) -> pad` when far and walks
  straight to the pad when the return already put us in the pad plaza.

Each verified leg records the floor register before/after, the player entity position and room, and the input count in
`mandate/t0-trial.jsonl`; the run ends with `mandate/t0-receipt.json` (`controller_only: true`, `memory_writes: 0`,
`dev_warps: 0`). First cycle verified live: town->forest floor 0->1 and forest->town floor 1->0.

## 16. Round 11 - the door latch: what Ghidra proves, and what the live session proved

Operator's standing request (2026-11-14, live): *"The game should have a Ghidra hook and latch on it that anytime I
play this game, it automatically unlocks any door I walk up to."*

**Working behaviour right now:** `pso-doors-always.py` polls the door-family entities around the player and, within 30
units of any of them, saturates the current floor's stage-flag group (0x80515CC8 + floor*32, 32 bytes of 0xFF) through
the audited write path. Measured live at 01:35: the operator stood 16 units from a `TObjDoor` in Forest 1; the pass
saturated group 0x80515CE8 and the operator walked through into Forest 2 seconds later. It is automatic and permanent,
but it is a **RAM latch polled by the agent**, not yet an in-engine hook.

**What Ghidra established for the native hook** (decompiled from D:\gBox\ghidra-pso\PSO, program pso_v3.elf, image base
0x8000C000):

* The player actor's vtable pointer is set by the constructor `FUN_801bd424` - it writes `player+0x18 = 0x804C3BBC`.
* The player-update function pointer is vtable slot `0x804C3BBC + 0x0C = 0x804C3BC8` ("VT_UPDATE"), and it holds
  `ORIGINAL_UPDATE = 0x801BB330`. `FUN_801BB330` is a normal function: it calls ~10 subsystem updaters then branches
  through its own action dispatch.
* Four functions reference the vtable base: `FUN_801bd424`, `FUN_801bd570`, `FUN_801bd70c`, `FUN_801bd928` (the first
  two are constructors; the other two are state/vtable selectors).
* Only the vtable data refers to `0x801BB330` - no direct branch exists - so the update must be invoked through the
  vtable slot or a cached copy of it.

**Negative result (important):** replacing `0x804C3BC8` with a small MIPS wrapper that writes a RAM marker and then
tail-jumps to gBox's cave at 0x80004C00 does **not** execute while the game is already running: the pointer stays
patched for seconds and the marker never changes, while a normal gBox command still runs in 0.17 s with the cave
pointer restored. Conclusion: the snapshot of the slot is not re-read on every update by the running actor - the game
appears to have resolved the update entry already (likely copied at actor construction or into the JIT-warmed vtable
path). A live latch therefore needs a **code patch at a real entry point** - `ORIGINAL_UPDATE` 0x801BB330's first 16
bytes replaced by an absolute jump into a trampoline that runs the saturation routine, executes the displaced
prologue, then continues at 0x801BB340, with a guest icbi flush (gBox's FLUSH_CODE at CAVE+0x300 shows the pattern)
so Dolphin recompiles the patched block. That is the next step; the decompilation facts above are its map.

The mis-install that froze the guest for a few minutes is also instructive: a wrapper that reloads VT_UPDATE after
hooking it tail-calls itself forever, and the recovery that worked without losing the operator's run was to break the
loop **in memory** (write `blr` over the routine's loop branch) and restore the original pointer - the CPU was
executing our code from RAM, so the patch took effect on the next iteration.
