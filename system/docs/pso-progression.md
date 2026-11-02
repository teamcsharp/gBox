# PSO Episode I & II — door / room progression mechanics

Game knowledge that drives the co-op bot's room-to-room progression logic
(`pso_coop_gates.py` gate model, `pso_coop_frontier.py` routing,
`pso_coop.py` controller). Written like a player's guide so the logic matches
how the game actually gates forward movement. **Operator's #1 demand: the
buddies open and pass through EVERY door and advance room-to-room through the
whole game "with gusto" — decisive forward motion, never dithering.**

## How a room gates the exit (the four gate types)

PSO areas are a chain of rooms joined by doors. A room's forward door is held
shut by one of these mechanisms. The bot must recognize which and act:

1. **Room-clear laser fence** (`TObjLazerFenceNorm`, energy barrier
   `TOBarrierEnergy01`). A blue/red laser wall across the exit. It drops
   automatically **once every enemy in the room is defeated** — "when they're
   all dead, the laser fence will unlock." Combat is the key; no switch.
2. **Switch / floor-panel door.** The exit is held by a laser fence or locked
   door that only opens while/after a **floor switch is pressed**. The switch
   is a separate object: `TLazerFenceSw` (a floor switch you stand on) or
   `TObjDoorKey` (a "door panel" you walk into / activate). "A player on a
   switch in the same room as the warp can lower the lasers guarding the exit."
   Some rooms need **two or more panels** pressed (co-op: one buddy can hold a
   switch so the other passes; a lone bot presses them in sequence). Switches
   can be **hidden behind breakable rocks** beside a fence — attack the rocks to
   reveal the switch.
3. **Open door / plain door** (`TObjDoor`). Many doors are not locked at all —
   they open automatically as a player walks up to them once the room is clear.
   The only "mechanic" is to **commit and walk through** into the next room.
4. **Area warp / teleporter** (`TObjAreaWarp*`, telepipe/transport). A glowing
   pad that moves the party to the **next area** (e.g. Forest 1 → Forest 2) or
   to a **boss arena** (Forest 2 ends with a transport to the Dragon's lair
   beneath the Central Dome; defeating the Dragon opens the Caves). You reach it
   by walking onto it. Note: warp classes are **not** gate objects in the
   profile, so the planner treats them as explore/walk-through targets, not as
   barriers to clear.

Boss doors: the arena-entry warp becomes available only after the area's
critical path is cleared; defeating a boss opens the next area.

## Episode I areas and critical path

Forest → Cave → Mine → Ruins, each ending in a boss:
- **Forest** (Forest 1, Forest 2): mostly room-clear laser fences plus a few
  switch-panel doors; the standing rule is **kill everything in a room before
  moving on**, then the fence drops and you proceed. Forest 2 ends with a warp
  to the **Dragon**. Beating the Dragon opens the Caves.
- **Cave** (1–3): more switch puzzles and room-clear fences; ends at **De Rol
  Le**.
- **Mine** (1–2): room-clear + switches; ends at **Vol Opt**.
- **Ruins** (1–3): room-clear + switches; ends at **Dark Falz**.

## Episode II areas

VR **Temple** (Alpha/Beta) and VR **Spaceship** (Alpha/Beta) are the opening
virtual-reality training areas; bosses are re-skins (Barba Ray for the Temple,
Gol Dragon for the Spaceship). Then **CCA** (Central Control Area), **Seabed**,
etc. Episode II adds **lab / principal** gating: some areas open only after
earlier VR areas are completed. Same per-room door mechanics apply
(room-clear fences, floor switches, plain doors, area warps).

## Navigation tips the bot encodes

- Move room-to-room along the critical path; a room's exit is the door/fence/
  warp farthest along that path.
- In a **cleared room** (no live enemies) the forward door is either already
  open (walk through decisively) or waiting on a **switch** — go press it.
- Switches first, then the door they gate, then through — **P1 leads, P2
  follows**, decisive forward motion (no re-centering dither).
- Area warps are walk-onto targets to the next area / boss arena.

## This build's native object classes (3OE2, profile `pso-gc-plus-us`)

Entity `class` string at object+0x00, `room` (u16) at +0x28, `x/y/z` (f32) at
+0x38/3C/40. Gate-kind prefixes in the profile: `TObjDoor*`, `TObjLazerFence*`,
`TLazerFenceSw`, `TOBarrier*`.

- `TObjDoor` / `TObjDoorKey` — door and door-panel (`TObjDoorKey` is treated as
  a **switch/panel** to activate, not a wall to route around).
- `TObjLazerFenceNorm` — room-clear laser fence (the wall).
- `TLazerFenceSw` — floor switch that controls a fence.
- `TOBarrierEnergy01` — energy barrier; in 3OE2 `mode 1` enables
  unconditionally, `mode 2/3` consult a **stage flag** via accessor `0x80229220`
  (flag index at object+0xC8 low16, per-object native state at +0xAC). The
  stage-flag *array base* is not yet reverse-engineered, so the open predicate
  is observed, not forced (see the live case below and the forced-unlock note).

## Live case 2026-11-02: Forest 1, room 10 → 11 (why they were stuck)

Session `cfd61ef3fae244fc-2b339a70d4284694`, i9-NUC, Episode 1 Forest 1, 2P.
Mission `pso-gc-forest1-first-wave`: "open two door panels, reach room 11."

Both buddies spawn at the room-10 entrance (~x7,z-30) with **no enemies** in
the room. Room 10 holds **two `TObjDoorKey` panels** (16490 at ≈(-127,71),
16491 at ≈(-95,214)) and doors 16492/16494 leading onward; room 11 holds the
flag-10 `TOBarrierEnergy01`. So this is a **switch-panel door** room (type 2):
the two panels must be pressed to open the door to room 11.

The `FieldObjectives` planner only routes to `TObjDoor`/fence/barrier **gate**
classes and never to **switch** classes (`TObjDoorKey`/`TLazerFenceSw`), and it
only advances on the slowly-expanding verified collision grid. Near spawn that
grid is a tiny patch, so the planner fell to **frontier exploration** and
oscillated with ~5-unit hops near spawn (waypoints like (12.5,-27.5),
(7.5,-32.5)) — never committing across the room to the panels at x≈-130. It
never pressed a panel, so the door never opened and the pair camped in room 10.

**Fix:** a decisive forward-progression push (see `pso_coop_gates.classify` +
the controller) that, in an enemy-free room, drives **P1 onto each switch/panel
in turn (press), then through the forward door with gusto**, P2 following —
overriding timid frontier wandering. Room-clear rooms still clear first (combat
keeps priority); open doors/warps are walked through.

## Sources

Fan guides and wikis (Episode I & II, GameCube/Dreamcast); treat room-specific
details as patterns, confirmed against live RAM where possible:
- Phantasy Star Wiki — Forest / Forest 2 / VR Spaceship pages
  (phantasystar.fandom.com).
- Ragol.co.uk forums walkthrough threads (forums.ragol.co.uk tid=1796, 2112):
  switch-lowers-lasers, kill-everything-before-moving-on, Forest 2 → Dragon
  warp, hidden switch behind breakable rocks.
- GiantBomb wiki (Episode I & II overview: VR Temple/Spaceship, Alpha/Beta
  tiers, boss re-skins).
- CheatBook / CheatCC (blocked/laser-door corner-attack trick — unverified).
- Live RAM observation of the running session (object classes, rooms, barrier
  mode/flag offsets) — 2026-11-02.
