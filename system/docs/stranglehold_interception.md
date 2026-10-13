# Stranglehold bullet-time interception

This document describes the minimum set of game systems gBox uses to
intercept a Stranglehold precision-aim (bullet-time) shot, suspend its
resolution, and override whether it hits or misses, and the Tetris DS link
that lets a Tetris round decide the shot (#1401).

## Minimum set of systems

The canonical source is `profiles/stranglehold-ps3-us.json`. The six
systems are:

| Role | Symbol / entry point | Why it matters |
|---|---|---|
| Shot type | `StrangleholdProjectile_Bullet_PrecisionAim` | The only projectile that enters bullet-time. |
| Suspend point | RPCS3 process pause (`RPCS3Adapter.pause`) | Freezes every PPU/SPU thread so the bullet cannot impact. |
| Presentation verdict | `ResolvePrecisionAim` | Decides whether the cinema shows a hit or a miss. |
| Damage verdict | `StrangleholdPawn.ServerResolveDamage` | The precision-aim branch sets lethal damage scale. |
| Slow motion | `WorldInfo.TimeDilation` via `SetTequilaTimeActive` | Slows the world while the shot is suspended. |
| Aim state | `StrangleholdPlayerPawn.IsPrecisionAiming` = pawn byte `+0x13FC == 2` | The link trigger (below). |

## Chat / agent interface

The `stranglehold_shot` tool exposes these systems through the gBox chat
agent:

- `op=systems` — list the systems above, the link trigger and the known guests.
- `op=locate` — find the profile's script functions in RAM for a running
  Stranglehold session.
- `op=arm` — apply the `god` preset (infinite life) so you can test safely.
- `op=fire verdict=hit|miss` — immediately force the next shot to hit or
  miss.
- `op=link guest=tetris_ds` — hands-free: the precision-aim trigger comes from
  the Stranglehold profile, the win/lose flags from `profiles/tetris-ds-us.json`
  (`round=vs_cpu`, the default, or `round=sprint`), and the guest session is
  found (a running Tetris DS session) or launched (`@launch`, `guest_node`,
  default `linux`: one emulator per worker, so the guest runs beside the host,
  not on its PC). `style=pip` (default) freezes Stranglehold and shows Tetris
  picture-in-picture; `pause` and `overlay` are the other styles. A guest win
  applies `god_hit`, a loss `god_miss`, before Stranglehold resumes.
- `op=link guest_session_id=... trigger=... win=... lose=...` — the same with
  explicit watch specs (any guest, e.g. Puyo Puyo Tetris).

`game_link` underneath: when the trigger turns true it pauses the host,
resumes the guest and loads its parked save state, polls win/lose, pauses the
guest, applies the verdict preset while the host is still frozen, resumes the
host and waits for the moment to end. A guest on another worker is driven
through the control plane (`RemoteSession`: `/api/sessions/{sid}/rpc`
read_memory / pause / resume / info, `session_op load_state` jobs); in `pip`
style its MJPEG stream (`/api/sessions/{sid}/mjpeg`, reported as `pip` in the
link status) is the picture-in-picture, and a local guest window is placed
borderless over a corner of the host (`overlay.pip_on`). A failed round
(e.g. no save state parked) resumes the host and reports the error.

Watch specs: `{address, type u8|u16|u32|f32, eq|ne|lt|gt|ge|le}`, plus an
optional `path` of pointer steps from `address` (an offset = dereference a
32-bit pointer there; `{"walk": next, "until": {"offset", "mask"}}` = follow a
linked list; `{"add": n}`), or `{"any": [...]}` / `{"all": [...]}`. A null or
unmapped pointer on the path reads as false (loading screens).

## Host trigger: precision aim (static, unverified live)

Found in the decrypted `EBOOT.BIN` (retail SELF, APP key revision 1; PPC64,
32-bit pointers, 1:1 guest addresses in RPCS3):

- Native table entry `0x101CA2CC` "intAStrangleholdPlayerPawnexecIsPrecisionAiming"
  -> OPD `0x0177B5D0` -> exec thunk `0x002D9600` ->
  `AStrangleholdPlayerPawn::IsPrecisionAiming` `0x0039B3AC`:
  `lbz r0,0x13FC(this); return r0 == 2`. Its siblings read the same byte:
  `IsInBarrage` (`== 3`), `IsInSpinBomb` (`== 4`): the Tequila Bomb mode.
- The local pawn: `GWorld` = `0x1032D740` (TOC `0x017F4E80` + `0x1C18`);
  `0x00D273C4` returns World `+0x4C` (PersistentLevel) `+0x38` (Actors) `[0]`
  (WorldInfo) `+0x338` (ControllerList); the helper `0x002A5B14` walks
  NextController (`+0x1B8`) to the controller whose bitfield word `+0x1BC` has
  its top bit set (bIsPlayer); `0x00454640` reads its Pawn at `+0x1AC`.

Trigger spec (in the profile): address `0x1032D740`, path
`[0, 0x4C, 0x38, 0, 0x338, walk 0x1B8 until +0x1BC & 0x80000000, 0x1AC, add 0x13FC]`,
`u8 == 2`. Confidence: the field is high, the pointer path medium.

## Guest: Tetris DS (USA, ATRE)

`profiles/tetris-ds-us.json`, from the ARM9 overlays (overlay 0 = Standard
mode, disassembled with capstone) and the community Action Replay codes.
Player records at `0x0217DB88 + 0x300 * slot` (VS CPU: slot 0 = player,
slot 1 = CPU):

| Field | Slot 0 | Notes |
|---|---|---|
| state (u8) | `0x0217DD32` | 2 falling, 4 spawn, **7 topped out** (written only by `0x02113658`, called when a piece cannot spawn or fit) |
| score (u32) | `0x0217DD34` | AR "Max Score" |
| lines (u32) | `0x0217DD38` | Line Clear ends at 25, Marathon at 200 |
| level (u32) | `0x0217DD3C` | AR "Always Level N" |
| current piece (u8) | `0x0217DD24` | 0 Z, 1 S, 2 L, 3 J, 4 T, 5 O, 6 I |
| CPU state (u8) | `0x0217E032` | slot 1; VS CPU win branch when it is 7 |

Rounds: `vs_cpu` — win = CPU state 7, lose = player state 7 (one VS CPU
match); `sprint` — win = 2 lines, lose = player state 7 (a few seconds).
melonDS (RetroArch) exposes main RAM as SYSTEM_RAM: native `0x02xxxxxx`
addresses go through the new NDS window in `RetroArchAdapter.RAM_WINDOWS`.

## Live check (not run yet: no sessions were touched)

1. Launch Stranglehold on the operator's PC and Tetris DS on the Spark
   (`node=linux`). In Tetris DS start Standard > VS CPU and save a state at the
   first piece (the round's parked state).
2. Read the Tetris DS addresses through the session inspector
   (`POST /api/sessions/<tds>/rpc {"op":"read_memory","args":{"address":35118372,"length":32}}`, i.e. 0x0217DD24):
   the piece byte at +0 changes per piece, score/lines/level at +0x10/+0x14/+0x18
   follow the screen, state at +0x0E reads 2/4 while playing and 7 when you top
   out.
3. In Stranglehold (past the title screen, at least one Tequila bar), start the
   link: `stranglehold_shot op=link session_id=<stranglehold> guest=tetris_ds`.
4. Enter Precision Aim: Stranglehold freezes, the Tetris match reloads in
   picture-in-picture. Win (the CPU tops out) -> the shot hits and kills; lose ->
   it misses. `game_link op=status` shows rounds, history and errors.
5. If the trigger never fires, read the path by hand
   (`_watch_address`) or fall back to `memory_search` on the precision-aim byte.

## Session models (#1410): cooked-package inventory

`python -m gbox.stranglehold_inventory [CookedPS3] [--json out.json]` reads only
the table chunks of every package (a few MB in total). On the owned disc: 881
packages (828 chunked zlib, 48 fully compressed script packages, 5 raw),
168 hold 674 SkeletalMesh exports (224 unique names), 0 errors:

- player: Tequila (`tequila01`, `_jacket`, `_jack_swtr`, `_suit`, `_sweater`)
  in `char_tequila*.xxx` (5 single-player + 5 `_MP`), plus cinematics;
- enemies: 60 meshes (`assaultClass01..05`, `SMGClass`, `pistolClass`,
  `eliteClass`, `lieutenantClass`, `meleeClass`, `sniperClass`, `butcherClass`,
  `devilClass`, `dc_` / `Imperial9_` faction variants) in 50 level
  `*_mission` / `*_mso` packages for the campaign and 22 `char_<faction>_*_MP`
  packages for multiplayer;
- bosses: Damon / Vlad Zakarov, Jerry Ying, Wong, Dapang in 6 mission
  packages + cinematics + `char_*_MP`.

The native model reader and the writer for these meshes are `gbox.stranglehold_models` and
`gbox.stranglehold_swap`, documented in `docs/stranglehold.md`. That doc covers the SPU-segment SkeletalMesh layout,
the 39-character roster and the Tequila / multiplayer-skin writer.
