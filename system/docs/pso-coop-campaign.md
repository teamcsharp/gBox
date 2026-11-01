# PSO Plus two-controller campaign

The `pso-coop-episodes-1-2` campaign controls two offline players using separate
Dolphin controller ports. It is an experimental campaign controller, not a
recorded or verified full-game completion. The supported executable is GameCube
Plus US `GPOE8P`, disc 0 revision 2 (3OE2), with the existing native code guards.

Launch an isolated co-op session with a dedicated new memory card. The adapter
provides `send_input_player(events, player=1|2)` and exposes the requested speed as
`autoplay_speed`. `pso_campaign.play(..., players=2)` selects this controller;
the original single-player campaign remains available.

The adapter's `_pso_coop_new_card` metadata must identify the current session,
the isolated card path, and `isolated=True`. Only that authorization lets the
planner initialize a new card and create new characters. Character names, classes,
and appearance preferences are randomized once per isolated campaign card,
persisted across worker/autoplay restarts, and entered through the real character creator. They are not
written into a save file. Each menu input is followed by a new observation; a
confirmation never automatically continues into an unseen dialog. Existing
character deletion or replacement remains outside the controller's instructions.

## Native control and controller verification

The reader matches both entries of `TObjPlayer_objs` at `0x8050EA10` against the
semantic entity table. It checks the class, native slot ID, expected vtable,
pointer bounds, positions, HP, and table stability. A second object is not enough
to claim that a second controller works: in Pioneer 2, the controller sends each
pad an isolated, bounded movement and confirms that only its intended actor moved.
An absent, swapped, or unmoving pad stops verification before combat. The
session-local `_pso_verified_player_slots={0,1}` marker is set only after both
probes pass, and is cleared at menus and on stop.

Both players receive combat inputs together. The native loop recenters their
cameras independently, reads current heading/position/HP, approaches enemies in
the same room, faces them before attacking, and retreats at low HP. It records
observed enemy HP reductions and positive-to-zero transitions separately from
attack-button inputs. The visual planner runs in a background thread, so model
latency does not suspend ongoing native combat. Stale plans are discarded after
an area, room, player, or life-state change. Healing, action-palette interpretation,
doors, switches, character menus and story decisions still require visual planning.

Input durations scale with requested emulator speed, with a minimum host pulse.
This does not establish that the host can sustain 2x, 4x, 8x, or 10x or that the
controller completes the game at those speeds. High-speed acceptance requires
measured game progress and damage outcomes on the actual worker.

During a speed change, both pads release and decisions wait. An interrupted
change requires relaunching to restore a known rate. Above 1x, the controller
samples the native CPU timebase at most once per second. The sampler verifies
the isolated card/session, offline phase, both mapped player identities, area,
difficulty, and clock-function bytes before and after the call. It uses the same
session lock as equipment commands and a shared per-adapter native queue lock;
busy locks cause the sample to be skipped, without waiting on an equipment edit.

Each sample brackets the native call with host monotonic timestamps. Two samples
provide an achieved rate and lower/upper bounds reflecting enqueue/acknowledgement
uncertainty. Calls over 150 ms, wide uncertainty, stale samples, implausible clock
deltas, loading, player changes, resets/restores, and speed changes invalidate
the evidence. An unknown native-call outcome is latched without automatic retry.
The controller reports a measured slow rate even when a higher rate was requested.
Only fresh evidence whose entire interval matches the requested rate within 5%
allows accelerated movement failures to teach walls. Default 1x behavior remains
unchanged. These checks have simulated-memory regression coverage; no achieved
rate or campaign completion on the i9 is established by those tests.

## Remembering obstacles

`pso_coop_nav.py` persists observed walkable segments and blocked movement edges.
Two stable, unsuccessful approaches teach a blocked edge. Loading, damage,
combat, and room changes cannot teach a wall. A later successful passage removes
the block, allowing doors to open normally. A path search routes around known
blocks, cannot cut a known diagonal corner, and stops after a bounded search.
Six seconds without approach progress discards the current approach and defers an
unreachable enemy while planning a route.

Memory is scoped by executable build, episode, floor, difficulty when verified,
room, floor layer, and the actual static-object/gate layout. Without a verified
native layer, memory is bounded to four-unit height bands, so a bridge and the
passage beneath it do not inherit each other's blocks. It is not keyed by room number
alone, because PSO randomizes layouts. Rooms without identifying geometry or
landmarks retain only session-local observations. These observations are not
presented as the game's collision mesh.

Difficulty is read from the guarded 3OE2 native global `0x805D5550`.
An adapter may additionally provide `pso_campaign_context()` with verified
geometry metadata:

```python
{
    "geometry_verified": True,
    "geometry_identity": "sha256-of-the-actual-loaded-collision-resource",
    "geometry_layer": "verified-current-floor-layer",
    "collision_grid": {"size": 12.0, "floor": [...], "walls": [...]},
}
```

Only positively verified geometry with an identified floor layer is accepted.
A flattened whole-level grid is not used to infer stacked floors. With a collision grid, path
search is restricted to known floor cells and rejects off-floor goals. Without
one, local exploration uses observations and explicitly remains incomplete.
The existing `psomap.py` parser supports GameCube collision REL files, but this
controller does not guess which randomized collision resource is currently
loaded.

## Completion evidence

The goal order is Episode I then II, through Normal, Hard, Very Hard and Ultimate,
then repeat. A locked difficulty tells the planner to continue leveling the same
characters at an available difficulty; no level or unlock flags are fabricated.
Completion requires both native player objects, a verified matching difficulty,
all required episode floors, an observed final-boss positive-to-zero HP transition
with no surviving boss parts, and two distinct ending images separated by at
least two seconds. Partial routes and despawns do not complete an episode.

Multi Mode does not rely on a single-player ending screen for loop control.
An independently labeled `episode_route_complete` receipt requires all required
floors, a final-boss positive-to-zero transition remaining at zero for two seconds,
and both living buddies returning to Pioneer 2 for two observations a second
apart. It advances the requested episode/difficulty and asks the planner to save
normally and change Game Mode. This route receipt explicitly sets
`all_rooms_verified=False` and `full_campaign_verified=False`; it does not prove
every room or the complete single-player story. Boss despawn or an ordinary town
trip cannot create it. Native route counters remain separate from ending receipts.

The Sega manual (pages 34-36) specifies that Multi Mode difficulty eligibility
depends on the participating characters' levels, transporters need all players
aboard, and Quit Game saves the characters before returning to the game options.
The controller follows these actual multiplayer menus and does not assume the
single-player quest or difficulty-unlock sequence applies to co-op.

The co-op reader adds a real difficulty field to the earlier single-player
controller. Complete native collision-resource selection, full-room objective
verification, all boss-specific
readers, and end-to-end co-op acceptance are still required before claiming an
autonomous completion loop across every difficulty.

Validation: focused tests cover independent controller release, swapped-pad
rejection, native slot identity, both players attacking in one control step,
bounded menu inputs, persistent obstacle avoidance, geometry boundaries, and
completion evidence. Live character creation, pad mapping and campaign completion
must be reported separately from these tests.

Source for offline multiplayer support: the [Sega GameCube manual](https://www.gamesdatabase.org/Media/SYSTEM/Nintendo_GameCube/Manual/formated/Phantasy_Star_Online_Episode_I_-_II_Plus_-_2004_-_Sega.pdf).

## Native difficulty evidence

The owned `PsoV3.dol` SHA-256 is
`1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a`.
Static PowerPC disassembly shows:

- `0x801330C0`: calls the existing selected-index getter `0x801334DC`;
  `0x801330C4`: `stw r3,-0x50B0(r13)` stores that result.
- `0x801F44D4`: reads `r13-0x50B0`, then bounds the value to `0..3`
  before indexing per-difficulty quest flags.
- `0x800ACA34`: reads the same global and compares it to `3` to choose the
  Ultimate enemy branch. This is a gameplay field, not merely a menu selection.
- The established episode getter at `0x8001E5C8` reads `r13-0x45A0`, matching
  episode global `0x805D6060`, hence `r13=0x805DA600` and difficulty
  `r13-0x50B0=0x805D5550`.

`pso_coop_native.context()` checks all four instruction fingerprints, exact disc
revision, active offline phase, `0..3` bounds and stable before/after reads. It
never writes the difficulty. Live comparison against each selected difficulty
remains an acceptance check separate from this static derivation.

## Native clock evidence

In the same owned executable, `0x80375F20` contains
`7c6c42e64e800020`: `mftb r3,0x10c; blr`. This returns the lower 32 bits of the
emulated PowerPC timebase without changing game state. The existing guarded
game-thread dispatcher returns `r3`; clock sampling uses that queue and its
verified hook, rather than a guessed timer field. The call's own instruction
bytes must match before it is issued.

Dolphin's [system timer implementation](https://raw.githubusercontent.com/dolphin-emu/dolphin/master/Source/Core/Core/HW/SystemTimers.cpp)
advances the timebase from emulated core ticks. Its
[clock ratio](https://raw.githubusercontent.com/dolphin-emu/dolphin/master/Source/Core/Core/HW/SystemTimers.h)
gives 486 MHz / 12 = 40.5 million timebase ticks per emulated second for GameCube.
The sampler handles unsigned wrap, bounds the sample gap to two host seconds,
and includes the adapter's reset/restore epoch in both the sample identity and
published receipt. It does not infer achieved speed from the requested setting,
hotkey delivery, captured-video frame rate, or render frame count.

## Enemy spawning audit

Enemy instance spawning remains unsupported. The existing floor-item and
enemy-loot hooks create items, not enemies. A read-only audit of the owned 3OE2
executable above found a genuine enemy creation path:

- Area-specific constructor tables start at `0x80498E98`. The type `0x44`
  entry at `0x80498048` points to factory `0x800922E4`. It allocates native
  objects and calls `0x800927DC`, which installs the `TObjEneBeast` class name
  and vtable and reads already-loaded enemy resource globals.
- `0x8020CC48` selects a constructor by current area and descriptor type;
  `0x8020CCF4` calls it with the descriptor's `+4` address.
- Native caller `0x8020CD44` walks `0x48`-byte descriptors. After construction,
  it stores the actor at descriptor `+0x44`, sets descriptor flags, copies
  room/wave/index fields to actor `+0x28/+0x2A/+0x2C`, retains the descriptor
  at actor `+0x80`, and calls vtable `+0x13C` with a separate indexed record.
  Calling the factory alone would omit this native bookkeeping.

This establishes static candidates, not a safe callable spawn operation. Still
unverified are descriptor allocation and lifetime, unique entity/index capacity,
the separate indexed record's ownership, loaded-resource compatibility, wave
completion accounting, and death/area-unload cleanup for newly injected actors.
Those contracts and an isolated offline create/fight/kill/unload trial are needed
before a bounded room-spawn control can be enabled. No enemy creation call or
game-memory mutation was performed by this audit.

The [upstream constructor tables](https://raw.githubusercontent.com/fuzziqersoftware/newserv/9b075e4d125edac2a8740dc90b013e6e41322e1f/notes/dat-constructor-tables.txt)
cover 3OE1 rather than this 3OE2 build. The locally archived 3OE1 `CreateObject.s`
target `0x8020C158` and event `construct_enemies` address `0x80207714` resolve to
different code here; they must not be reused as 3OE2 entry points.
