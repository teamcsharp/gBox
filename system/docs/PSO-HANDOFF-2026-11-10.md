# PSO lane — hand-off brief (2026-11-10, i9-NUC)

**Updated at round 57.** Everything below was measured on the live `GPOE8P` disc and the i9-NUC, and every claim names its
evidence. The lane doc (`docs/ds-pso-lane-2026-11-10.md`) has the round-by-round record; this file is the state, the
blockers and the next steps.

## Where the objective stands, package by package

| package | state | evidence |
|---|---|---|
| **P2** decode every disc format + per-area catalogue | **done, one format first-pass** | `docs/research/pso-gc-{areas,formats-containers,formats-models,formats-textures,formats-tables}.md`; placement sets, GSL/AFS/BML/PRS/NJCM/GVR all round-trip; **`.evt` event scripts** decoded to framing (rounds 52-53) but not to opcode semantics |
| **P2b** executable mapped | **good**, one address open | `docs/research/pso-gc-executable.md`, `gbox/pso_ram.py`, and now `gbox/pso_dol.py` (address map, base `0x8000c000` matching the Ghidra export) and `gbox/pso_classes.py` (the object-class registry). Open: `0x8028f508` (the model-walk crash) |
| **P1** boot to the field by real presses | **boot to town done; field blocked by design, not by route** | six frame-verified presses to Pioneer 2, two-player co-op, movement, the city mapped room by room. **There is no city event script on the disc**, so nothing editable decides the city→floor transition -- see "P1's gate" below |
| **P6a** map writer | **done and proven in game** | `gbox/pso_map_write.py`, `pso_editor` (+CLI, +ASCII map), and the proof: `pso_guilddoor_moved` moves `TObjCityDoor_Guild` from world (185,173) to (235,173), and the running game reports **(235.0, 173.0)** |
| **P6b** editor page | **backend + CLI done, no page** | `python -m gbox.pso_editor <disc> sets|list --world|map|move|delete|build`; 16 tests |
| **P7a** player-model writer | **builds models; rigging not done** | `pso_player.build` end to end on this disc (7 meshes, skeleton, 7 GVR textures) |
| **P7b** hot swap | **visible, not correct, now predictable** | HUcast body renders deformed; HUnewearl body **crashes** at `PC 0x8028f508`; `pso_swapfit.compare` predicts which, from the texture-bucket count |
| **P3-P5** traversal, bosses, campaign | **not started** | blocked on P1 |

**121 PSO tests green** at this revision (verified round 57).

## P1's gate — the finding that matters

Rounds 42-53 spent a great deal of effort trying to find a *route* from Pioneer 2 to a floor. Round 53 closed that line:

* **the single-player intro conversation cannot be exited** — no button, no combination, no idle (rounds 37, 45);
* **no city event script exists** — the 143 `.evt` scripts cover 28 field and boss areas and **not the city** (round 53), so
  no placement or script on the disc decides whether a city door transitions;
* the city's four doors are placed identically and behave differently (`Warp` works, the others do not), which is consistent
  with the decision being **code**, not data.

**So P1 needs the executable's quest logic, or quest-state manipulation in RAM — not a better route.** Anything that claims
a route exists should be treated as unproven until it is walked.

## What round 44's brief said that has since changed

| then | now |
|---|---|
| "P6a: proof incomplete, the moved object has never been seen" | **proven**: `TObjCityDoor_Guild` read at (235,173) in RAM after the writer moved it |
| "P6b: no page" | backend **and CLI and ASCII map**; only the page remains |
| "the `x=0` corridor is the most promising unexplored line" | **retired** — those `TObject`s are `TObjCityAirCar_Car` (traffic), round 55 |
| "seven `0x40` records are the shop counters with keepers behind them" | **retired** — they are `TObjCamera`, round 55 |
| "P7b: visible, not correct" | same, plus a **predictive rule** (`pso_swapfit`) |
| (P2b) "one open address" | plus a **DOL address map** and the **class registry**, calibrated two ways |

## The live environment

* gBox server + worker on **i9-NUC** (`10.89.1.43:8765`), `python -m gbox --config gbox.toml serve --worker` from
  `C:\_tools\gBox\system`; token `system/gbox-data/api_token`; **`x-gbox-actor: agent` on every call**.
* **Never touch lilspark** (10.89.1.246): no ssh, no sudo/systemctl/kill, no launches or stops there. This lane's launches
  have all gone to the i9's own worker, which is the only one its gBox knows.
* the `mod` is a **query parameter**: `POST /api/games/{gid}/launch?node=<worker>&mod=<build>`; a JSON body field is ignored.
* every launch needs **five minutes without operator input**; a pad press resets that clock, so a verify-a-launch round costs
  ~10 minutes of wall clock.
* **`win_send_keys` raises** (`adapters.py:656`) when the emulator window is not foreground, and a session driven in that
  state looks exactly like a game ignoring input. Restore the window before driving; an open in-game menu also blocks
  movement and looks the same.
* helper scripts (not in git) in `D:\gBox\pso-ds\`: `walklib.py` (two-player movement), `pad.py`/`api.py`/`live.py`/
  `shot.py`/`win.py`, `qi0_scan.py` (RAM scanner), `qm0_offset_validate.py`, `re0_names.py`, `rg0_region.py`.
* mods on disk under `D:\gBox\cache\mods\436e0bb84d5337d1\`: `pso_objmove_forest01_l0_r60`, `pso_hotswap_humar_to_hucast`,
  `pso_hotswap2_both`, `pso_hotswap_humar_to_hunewearl`, `pso_city_npc_moved`, `pso_guilddoor_moved`.

## Next steps, in the order I would take them

1. **P1 via the executable.** The tools now exist: `pso_dol` (address map), `pso_classes` (named class ids), and the Ghidra
   export with 25,981 functions. Search for code that touches a `TObjCityDoor_Guild` instance or the quest-state block,
   rather than searching for "the guild".
2. **Finish the `.evt` decode.** The framing is solid (143/143); the opcodes are not. The field scripts are where room
   transitions live once a floor is reachable.
3. **P6b's page** — pure UI over a finished CLI.
4. **P7a rigging** — `build_swap` adapted for GC (big-endian body, GVR textures, flat names), gated by `pso_swapfit.compare`
   so a donor that would crash is refused before a build exists.
5. Then P3-P5, which need P1.

## Addendum: rounds 58-60 (the last three)

Two findings that change what the next session should do first, and one lead retired.

**The city has a GUILD room and fifteen unread sets.** The executable's string table names the city's music tracks --
`SHOP.adx`, `GUILD.adx`, `MEDICAL.adx`, `city.adx` at `0x80443654` -- and its labels -- "ITEM STORE", "HUNTER GUILD",
"CHECK ROOM", "JUDGMENT" at `0x8044c10f`. Its areas are named `map_lobby_01..10` (at `0x8044adfc`). On the disc that is
fifteen placement sets, `SET/map_lobby_01o.dat` .. `_10o.dat` plus colour and soccer variants, **none of which this lane had
opened** -- every map it built used `map_city00_00o.dat` alone. They hold a door class the city's own set never uses,
`TObjDoorKey` (12-13 per set), beside `TObjEvtCollision` and `TObjEnvSound*`.

**Those sets are per-room local spaces, so do not map them with the city00 offset.** `map_city00_00o.dat` spans local
x -562..132, z -2021..42; `SET/map_lobby_01o.dat` spans x -277..273, z -317..240, and the two share no record. The offset
`(+228,+291)` is a property of city00 only. **Solve a lobby set's offset per room**: enter the room, read its entities, and
solve it from a record that must be one of them -- the same method the co-op spawn points used for city00.

**Retired:** the "east of the lobby" reading (round 58) came from applying city00's offset to a lobby set. It means nothing.

**Where that leaves P1.** The gate is still code -- no city event script exists -- but the room inventory is data that has
only just been found. The order I would try: solve one lobby set's offset, name its `TObjDoorKey` doors in world coordinates,
then walk to whichever of them is not a place already known.

**Tests at close: 138 green** across eighteen PSO modules (`test_pso_*`, `test_pad_bind`), verified at round 60.
