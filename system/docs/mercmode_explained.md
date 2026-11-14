# MercMode combat, explained

**The whole system, its priorities, its commands, its RAM/aim machinery, and the operator guidance that built it.**

| | |
|---|---|
| Document | `system/docs/mercmode_explained.md` |
| Audience | the operator (you), future maintainers, review agents |
| Source of truth | this repository at `c3893b42f` + the live worker on `lilspark` |
| Generated | 2026-11-14, rounds 23-38 of the DeepSeek PM handoff |
| Status | The bot plays, fights, keeps combo stretches and explores the systems described here. **S-rank / five stars on every RE4, RE5 and RE6 run is NOT achieved and this document does not claim it.** |

This document is expansive on purpose. It is the map of the combat machine: every layer, every class and method family,
every operator-facing command, the exact order in which the bot decides, how it reads the game through RAM instead of
pixels, how the aimbot acquires and fires, why it has been reported raising the gun without firing, and a
request-by-request table of what you asked for, what changed, and what the subsequent rounds showed and what you
complained about next.

How to read it:

- **Part I (sections 1-4)** explains the architecture, the game-by-game differences, the tick model and the priority
  ladders. If you only read one part, read section 4.
- **Part II (sections 5-6)** is the "no vision model" half: RAM/hex reads, snapshots, RAM truth, the laser raycast and
  the aimbot, and the full anatomy of "the gun is up but it is not firing".
- **Part III (sections 7-12)** is the control surface and the history: action catalogue, bot-logic knobs, directives,
  intervention operations, guidance-to-implementation-to-evidence tables, live round performance, game differences in
  detail, known limits, and complete class/method appendices.

---

**Contents**

| Part | Sections |
|---|---|
| I - Architecture and priority | [1. The contract](#1-the-contract-the-system-is-built-around) · [2. Architecture](#2-architecture-the-six-layers) · [3. Execution model](#3-the-execution-model-ticks-snapshots-and-actions) · [4. Priority ladders](#4-priority-ladders-what-wins-in-what-order) |
| II - Senses and aim | [5. Vision via RAM](#5-how-the-bot-sees-without-a-vision-model) · [6. The aimbot](#6-the-aimbot-laser-raycast-body-profiles-camera-lock-trigger-authorization) |
| III - Commands and history | [7. Command catalogue](#7-command-catalogue-everything-the-system-can-be-told-to-do) · [8. Guidance ledger](#8-guidance---implementation---evidence---next-complaint) · [9. Performance](#9-live-performance-table-round-reports-snapshot) · [10. Game differences](#10-game-by-game-how-combat-differs-in-re4-and-re5) · [11. Limits](#11-known-limitations-open-verifications-and-honesty-notes) · [12. Appendices](#12-appendices-class--method--function-inventory) |

---

## 1. The contract the system is built around

The bot is not a scripted route. It is a socket-runtime agent: a real console game runs in the emulator, a worker reads
its RAM every tick, decides an action through a stack of named rules, and writes controller state back into the game.
Everything below is the machinery that turns your guidance into that loop.

Your guidance, as the system treats it (quotes are verbatim):

> "The combo of the match is dependant upon always adding kills consistently. I do not want the bot failing the combo."
> "losing / resetting the combo is a waste of a match and is a serious fail condition"
> "the combo must always grow and always be maintained"
> "the combo should never be lost"

> "An enemy must be dispatched every 4 seconds ... If the bot is always running and always dropping mines, the combo is
> easy to maintain. If the bot fights while placing mines, the goal becomes easier."

> "the bot must not only fight enemies but locate and pursue them ... the bot should interpret the map / ram / hex
> information of the game to know where each and every enemy is on the map."

> "Every enemy is meant to be dispatched. I want the bot aiming to dispatch each and every enemy no matter the distance."

Those five statements become five structural commitments:

| # | Contract | Structural implementation |
|---|---|---|
| K1 | The combo is the true meta | combo keeper + urgency clock + kill-gap pursuit; break attribution; combo-aware deferral of heals/bonuses |
| K2 | Every 4 s an enemy dies | continuous fire/scatter/quick-shot/grenade ladder, remote-mine rings, flash rings, pursue-anywhere hunt |
| K3 | Never stand still | side-step strafing inside aim, forced relocate after 2.5 s in one spot, blast escapes, boss step-out |
| K4 | Know where every enemy is | RAM enemy scan from the game's own enemy manager (no vision model), nav mesh for line/walkability |
| K5 | Dispatch everything at any distance | laser-ray long geometry, RAM camera-aim lock, unlimited-range look/aim rules, WANT_WEAPON/magnum/shotgun rules |

The rest of this document is the detail behind that table.

---

## 2. Architecture: the six layers

The runtime has six layers. Each lower layer is replaceable per game; the top layers are shared.


| Layer | What it owns | Code (representative) |
|---|---|---|
| 6. Operator surface | PiP buttons, tool calls, directives, MercMode session control, bot-logic knobs, round reports | `gbox/interventions`, `gbox/mercs/interventions.py`, `gbox/mercs/directives.py`, `gbox/mercs/bot_logic.py`, `/api/mercmode`, `/api/mercs/round-reports` |
| 5. Worker runtime | session lifecycle, screen detection, round evidence, tick clock (20 Hz), action dispatch to the emulator, flash/ring threads, review handshake | `gbox/mercs/driver.py`, `gbox/mercs/engine.py`, `gbox/mercs/session_runtime.py`, `gbox/mercs/round_reports.py`, `gbox/mercs/reviewer.py` |
| 4. Title bot | per-game brain: snapshot -> priority ladder -> action dictionary | `titles/re6_switch.Bot` (183 methods), `titles/re5_switch.Bot` (208), `titles/re4_switch.Bot` (97) |
| 3. Title engine helpers | native memory controller, bomb/ring lanes, QTE recovery, movement safety, shell probe, equipment | `titles/re6_switch_native.Controller`, `re6_remote_control.py`, `re6_bomb_deadlines.py`, `qte_escape.py`, `titles/*_movement_safety.py`, `titles/re6_switch_shell_probe.py` |
| 2. Shared brain/core | doctrine, aim book, fire pattern, ballistics, crowd/flash windows, lessons, threat memory, score/combo math | `gbox/mercs/core/*`, `gbox/mercs/aim.py`, `gbox/mercs/ballistics.py`, `gbox/mercs/behavior_metrics.py`, `gbox/mercs/learning.py` |
| 1. Hardware/OS adapters | process discovery, module bases, byte reads/writes, input bytes, screenshot/UI, emulator control | `gbox/adapters.py`, per-context adapters; game memory through `m.rd/m.wr`, controller bytes through native controllers |

### 2.1 The combat loop in one line per tick

'
```text
snapshot   ->  choose target    ->  prove/aim the line  ->  authorize the trigger  ->  action dictionary
20 Hz      RAM enemy scan        laser ray / nav mesh      envelope + rules         hold/tap/camera/right-stick
```

The action is a plain dict (for example `{"hold": ("zl", "zr")}` or `{"tap": "zr"}`). The title's
`RE6Switch`/`RE5Switch`/`RE4Switch` class sends that dict to the native controller; the controller writes controller
bytes into the game (or directly to RAM for the aim lock and native flash/ring helpers).

### 2.2 How a game is differentiated

All games share the *shape* of the loop, not the bytes. The differentiation points are:


| Concern | RE4 (GameCube/Wii + switch harness) | RE5 (PS3 RPCS3 + switch harness) | RE6 (Switch) |
|---|---|---|---|
| Bot module | `titles/re4_switch.py` (Bot, 97 methods) | `titles/re5_switch.py` (Bot, 208 methods) | `titles/re6_switch.py` (Bot, 183 methods) |
| Native controller | `titles/re4_switch_native.Controller` (40 methods) | `titles/re5_switch_native.Controller` (30 methods) | `titles/re6_switch_native.Controller` (34 methods) |
| Snapshot model | 17 keys: player, enemies, laser, camera, game, timer, kills, weapon_class, census | 42 keys: player, enemies, nav, prompt, laser, ground_mines, bonus_scan, rank points, timer_start | 46 keys: player, enemies, navmesh, prompts, laser, camera, throwables, bonuses, mercenaries_phase, complete |
| Aim lock (RAM camera write) | aim/camera read; room geometry; laser gate witnesses | aim_camera + aim_pitch; aim geometry module (`titles/re5_aim_geometry.py`) | full camera write (`re6_switch_mods` aim lock), `aim_cam` read-back, lock failures counted |
| Hit combo time source | chests | chests | blue time crystals shot/destroyed C6 |
| Mines | bot-served hand throw (GameCube physical hand); `titles/re4_switch_mines.py` | bot-served proximity mine drop + ring (`titles/re5_switch_mines.py`, `re5_native_mine_tactic.py`) | native remote-mine lane (`re6_remote_control.py`, `re6_bomb_deadlines.py`): placement, 5 s deadline, escape, detonate |
| Nade rings | `re4_reactive_ring.py`, wheel throw machinery | `re5_reactive_ring.py`, `re5_mines.py` | flash ring (15 mined on flash), QTE ring, launcher shell research (`re6_switch_shell_probe.py`) |
| QTE model | native prompt keys + pace + specials | native prompt keys + `titles/re5_qte.py` (ProgressHook) | native prompt keys + `qte_escape.Recovery` + auto-QTE RAM flag + QTE mine ring |
| Mods surface | `re4_switch_mods`; weapon rate/native weapon classes | `re5_switch_mods`; infinite ammo, fire rate, weapon override, loadout, add/set time | `re6_switch_mods`; bot_options nades/flash/aim_lock/bomb_drop, live weapon, bot_logic |
| Static challenge | rooms, ladders, loading transitions (`re4_walk.py`, `re4_traversal.py`) | stage hazards, coop, eggs (`re5_stages.py`, `re5_coop.py`) | floor levels (`re6_floor.py`), boss step-outs, ledge ranged |

### 2.3 The files that make the RE6 bot (the reference game)

| File | Lines | Role |
|---|---|---|

| `titles/re6_switch.py` | 9183 | the Bot class: snapshot, priority ladders, combat, aim, combo keeper, QTE, bombs, bonus run |
| `titles/re5_switch.py` | 9223 | the RE5 Bot class: same shape, RE5 bytes and stage/special logic |
| `titles/re4_switch.py` | 4732 | the RE4 Bot class: same shape, room/ladder/witness logic |
| `titles/re6_switch_native.py` | 1139 | native RE6 memory controller: pointer reads, bomb ring/detonate, flash, input |
| `titles/re6_switch_mods.py` | 1692 | RE6 live mods: bot_options, aim lock camera write, weapon swap, bomb armed flag |
| `titles/re6_switch_equip.py` | 372 | equipment wheel: nades/guns mapping and wheel steps |
| `titles/re6_switch_shell_probe.py` | 421 | launcher shell (shell1304 etc.) research: probe and ring barrage |
| `titles/re6_switch_wall.py` | 184 | wall/safety hook for movement actions |
| `titles/re6_movement_safety.py` | 233 | generic movement safety (bombs, walls, crowd) |
| `re6_remote_control.py` | 549 | remote-mine engine lane: travel drops, emergency rings, QTE rings, deadline-first detonation, nitrogen ring hook |
| `re6_bomb_deadlines.py` | 127 | native placement -> 5 s deadline book; blast observation; misses |
| `qte_escape.py` | 115 | QTE recovery: flash cover while held, RAM solve grants, QTE ring, recovery burst |
| `interventions.py` | 866 | operator intervention queue for the title bots (grenade_ring etc.) |
| `grenade_status.py` | 316 | per-title grenade kind/ring support matrix (sources, availabilities) |
| `remote_mines.py` | 77 | RE6 remote-mine policy: ring cadence, flash combo ring, surround ring, detonate rules |
| `bot_logic.py` | 354 | live operator knobs per title (saved, re-applied at every round start) |
| `tuning.py` | 227 | the per-round title tuning pipeline (applies bot_logic and mods) |
| `directives.py` | 151 | instant operator commands (fight/hunt/score/mine/flashbang/...) |

---

## 3. The execution model: ticks, snapshots and actions

### 3.1 The clock

- Base tick: `TICK_S = 0.05` (20 Hz) in the title bot. Every tick: read snapshot, run priority ladder, emit zero or one
  action dictionary.
- The aim book / fire pattern add the game's own cadence on top: a hold can be emitted every tick, but the trigger model
  (`fire_pattern`, `MAGNUM_FIRE_X`, `handgun` / `magnum` families) spaces the actual `zr` requests.
- Native threads run off-tick for things that must not stall a tick: flash deployment, bomb ring allocation, bomb
  detonation, shell barrage. They report receipts back through `stats` (`native_flash_confirmed_at`,
  `mine_ring_last`, `mine_detonate_last`, `nitrogen_ring_last`).
- A round's evidence is separate from the action loop: `round_reports.py` builds the report (score, rank, kills, max
  combo, accuracy, deaths) and `reviewer.py` feeds the Hermes gate.

### 3.2 The action vocabulary

An action dictionary can carry:


| Field | Meaning | Examples |
|---|---|---|
| `hold` | buttons pressed while the action runs | `("zl", "zr")` aim+fire; `("ldown", "lright")` move |
| `tap` | single-frame button presses | `"zr"`, `"b"`, `"a"`, `"r"`, `"up"` |
| `camera` | absolute camera yaw/pitch write (aim lock) when RAM write is available | `{"yaw": ..., "pitch": ...}` |
| `stick` | right-stick camera direction (when no RAM camera path) | `("rleft",)` / `("rup",)` |
| `move` | left-stick movement direction | `"lleft"`, `"lup"`, `"ldown"` |
| `doing` | the *intent* name used for logs/attribution/priority | `aim`, `fire`, `quick_shot`, `bomb_escape`, `hunt` |
| `act` | the precise sub-action name used in stats | `raise_fire`, `blast_retreat`, `prompt_key`, `hit_flash` |
| `why` | one-line human explanation included in telemetry | "the gun is up with one in front: firing" |

The pair (`doing`, `act`) is the audit trail. Every round report and every death file names the exact pair that was
running. That is how "the bot was just standing there" becomes a measurable `doing=bonus` vs `doing=aim` question.

### 3.3 The per-tick housekeeping order (`_tick`, RE6)

Beyond the decision itself, the tick performs these housekeeping passes in this order (extracted from the current
source): round detection/start, kill/score witnesses, core decision (`_core_tick`), aim sampling, LOS sampling, tablet
check, bomb kill accounting, bomb tracking, blast bookkeeping, bonus book, **combo tick**, quick-attack tick, census,
taunt watch, windup watch, down watch, hazard watch, periodic quick-attack interrupt, **aim-lock tick**, dying
transition bookkeeping, hold-ended detection, grab swap, prompt presses, grab detonation. Several of these can return
an action and end the tick; the most important are annotated in section 4.

### 3.4 One big safety invariant

No rule may write a game state the game itself would not write. The bot never issues a raw "kill" or "teleport"; it
writes controller bytes (the same ones a human writes) and, for aim, camera yaw/pitch. The only direct state writes are
the documented mods (infinite ammo, fire-rate tuning, aim lock camera write) surfaced as operator options. That is the
line between "mastering the hacked game" and "cheating with hacks": the operator asked for the former.

---

## 4. Priority ladders: what wins, in what order

This is the heart of the document. The bot is a chain of early-return ladders; the order *is* the policy.

### 4.1 Survival ladder (highest priority, in order)


| # | Rule | Condition | Action emitted | Why it preempts everything |
|---|---|---|---|---|
| 1 | Held / grabbed escape | player held by an enemy | held escape + QTE recovery flash | the player cannot act until freed |
| 2 | Blast retreat | inside the native remote-mine blast margin (`mine_escape_required`, clearance < 1200 cm) | pure walk out (`bomb_escape`), evaluated before any shot | a detonation is pending; standing in it = death |
| 3 | Relocate | has moved < RELOCATE_R (120 cm) in RELOCATE_S (2.5 s) with an enemy within 900 cm | walk to open space (`relocate`) | operator: "if they stand in the same place they will be crowded and decimated" |
| 4 | QTE recovery / prompt | a prompt key is on screen or a QTE was solved | tap the shown key on that tick (`prompt_key`); flash cover while held | operator: combat QTEs are absolute |
| 5 | Hit / QTE answer | damage landed this tick or a QTE escape was observed | native flash (odd hits) or nitrogen ring request (even hits) + random 1-5 quick shots | operator: flash on every hit; reactively stun |
| 6 | Downed / dying | player state is down or hp <= DYING_HP | critical flash first, then down fight / tablet | one-chance states; flash is the only out |
| 7 | Boss step-out | enemy with hp_max >= BIG_HP within BOSS_STEP_R (650 cm) has a wind-up | walk out of its reach (`boss_step_out`) | a stomp/major attack one-shots; operator: never stand still |
| 8 | Lethal dodge | learned attack wind-up from an enemy on the aim line | dodge/step before the shot | the attack was already learned as lethal |
| 9 | Tablet heal / crowd heal | hp below threshold and combo window >= 3 s | tablet tap (`tablet`) | survival is expected; delayed only while a chain is live |
| 10 | Emergency flashbang | operator flash button / critical crowd | native flash, no item screen | a flash is instantaneous crowd control |

### 4.2 Combo-keeper ladder (runs immediately after survival; the operator's #1 meta)

The keeper is active when **either** the mandate flag (`_combo_hot_now`) is on **or** the explicit urgency clock
(`_combo_urgent_now`) is on: a running combo with `combo_left_s <= COMBO_URGENT_S (3.0 s)`, or no kill for
`COMBO_KEEP_S (2.5 s)`, or (round start) no kill for 2.5 s.


| # | Keeper step | Trigger inside the ladder | Action | Counters |
|---|---|---|---|---|
| K1 | Combat grenade | urgent tick, item wheel free, frag/fire grenade loaded, a live enemy in 500-1500 cm | wheel throw into the mob (pacing gates relaxed for this call) | `combo_grenades`, `combat_grenade_throws` |
| K2 | Quick shot | a ray-target is available inside COMBO_QUICK_R (280 cm) and the quick-shot gap (0.22 s) passed | `zl`+`zr` quick shot at it | `combo_quick_shots` |
| K3 | Face for quick shot | target is close but the camera is not yet on it (75 deg cap, melee kick at MELEE_R) | right-stick turn / melee at arm range | `combo_turns` |
| K4 | Chase | no quick-shot target: walk/turn toward the nearest viable enemy (any distance) | pursuit walk or turn | `combo_guard_walks` |
| K5 | Stall spray | a raise has been failing to prove (gun up, no fire) and an enemy is within CLOSE_FIRE_R | forced quick shot | `stall_sprays` |
| K6 | Walk-elsewhere / hunt | nothing in the current area | hunt_elsewhere / hunt_offlevel | `hunt_elsewhere` |

If the keeper cannot act (e.g. no enemy anywhere, no grenade, nothing on line) the tick falls through to normal combat;
a break is attributed to the doing that was running (`combo_break_<doing>`, `combo_break_last_why`) so every loss has a
named cause.

### 4.3 Combat/engagement ladder (inside `_decide`)


| # | Block | What it does | Notable stats |
|---|---|---|---|
| 1 | Operator directive | `fight` / `hunt` / `score` / `mine` / `escape` ... applied from `doctrine_directive*` | `directive` |
| 2 | Held item | a grenade in hand: finish the throw; another item: put it away | `nade_wheel`, `held_prompt_presses` |
| 3 | Hit flash / QTE answer | see survival ladder #5 | `hit_flashes`, `hit_flash_requests`, `hit_nitrogen_requests` |
| 4 | Combat grenade | the 8 s grenade-into-mob rule (`GRENADE_EVERY_S`) | `combat_grenade_throws` |
| 5 | Grenade cycle | optional wheel throw / flash / fire / frag / cluster burst | `nade_throws`, `frags`, `flashes`, `re6_grenade_bursts` |
| 6 | Downed fight | on the floor: flash, then fight from the ground | `down_fights` |
| 7 | Critical heals | downed flash, critical tablet, crowd tablet (hp-gated) | `critical_flashes`, `tablets` |
| 8 | Lethal-out dodge | pre-shot dodge from learned lethal wind-ups | `lethal_dodges`, `lethal_combo_shots` |
| 9 | Miss answer | 3 misses in a row -> 3 quick attacks (MISS_QA_*) | `miss_quick_attacks` |
| 10 | Periodic quick attack | every PERIODIC_QA_INTERVAL_S a 4-shot quick-attack volley while not starving the combo | `periodic_qa`, `periodic_wait_combo_yields` |
| 11 | Taunt | a taunt window when safe and no target | `taunts` |
| 12 | Bomb / mine | place or fight the bomb state (BOMB_MIND, bomb_drop) | `bomb_drop`, `bomb_offers` |
| 13 | Nade | start/finish a wheel throw cycle (normal pacing) | `nade_throws` |
| 14 | Target pick | nearest / threat / laser-source / boss priority; `aim_at` selection | `target_pick` |
| 15 | Quick turn | turn camera toward the pick when far off line | `quick_turns` |
| 16 | Crowd control | in a surround: gun down, back out along open heading (`crowd_hold`) | `cc_backouts`, `crowd_holds` |
| 17 | Close/front fight | the aim/fire ladder (section 6.3): point blank, close fire, geometry, envelope, spray | `close_fires`, `scatter_forced`, `raise_trigger_requests` |
| 18 | Range shot | laser/geometry long shot up to SNIPER_LONG_R (6000 cm); quick shot inside QSHOT_R (200) | `sniper_shots`, `long_geometry_fires` |
| 19 | Detour | bonus run below the bank, hunt, off-level aim, wander | `bonus`, `hunt`, `walk_detour` |
| 20 | Idle fallback | keep moving / face threat / nothing | `no_foes`, `walk` |

### 4.4 Trigger authorization ladder (the last gate before a bullet)

Even when the aim ladder wants to fire, the trigger is released only when one of these proofs is true (RE6):

1. **Point blank** (`POINT_BLANK_R <= 260 cm`) with the body-envelope error inside `FIRE_ENVELOPE` (30 cm half-body,
   pitch 35 cm): fire without the laser.
2. **Close fire** (`CLOSE_FIRE_R <= 600 cm`) on a line the nav mesh says is clear, with the camera-envelope error inside,
   without the laser/probe refinements (operator: close enemies must be dispatched).
3. **Proven line**: laser ray intersects the target's body volume, or nav mesh proves the straight line and the distance
   is inside `GEOM_CLOSE_R`/`GEOM_FIRE_ERR`; then fire.
4. **Proven line in the correcting path**: ray source is the camera (not the laser) and the line proves + mesh clear +
   not short; fire.
5. **Forced raise scatter**: an aim episode has not yet put `RAISE_MIN_BULLETS` (20) trigger requests out; the current
   aim target is within `RAISE_SPRAY_R` (1000 cm), same floor, mesh line clear -> force the trigger (scatter).
6. **Quick shot / melee / burst** rules bypass the envelope with their own gates (`QSHOT_R`, `MELEE_R`).

Anything else returns a raise, a reposition, or a walk - never a bare trigger. Section 6.4 explains why this list is
also the answer to "the gun is up but it is not firing".

---

## 5. How the bot sees without a vision model

There is no image model in the combat loop. "Seeing" is three independent truth sources, all numeric:

### 5.1 RAM truth (the primary sense)

The title snapshot reads the game's own structures every tick:

- **Module base**: a known signature address (RE6: `S_GAMEMAN/S_PLAYER/S_ENEMY/S_UNIT` offsets into the module) read
  through the adapter's `rd`. Every read is bounds/validity checked (`ptr_ok`), and unreadable pointers yield `None`
  rather than a guess.
- **Player**: pointer chain -> position (`P_POS` 0x60), rotation (0x70), HP (0x1368), state/action, motion, tablets,
  inventory (equipped, weapon id, guns, ammo, nades), generation.
- **Enemies**: the game's own enemy manager: `S_ENEMY` -> count `E_COUNT (0x40)` -> array `E_ARRAY (0x50)`; each unit's
  class, position (`E_POS` 0x60), HP (`E_HP` 0x1368), action/wind-up, generation. The scan is the complete enemy list of
  the current level: that is how the bot "knows where each and every enemy is on the map" without pixels.
- **Counters**: timer, score, kills, combo, combo timer, max combo, mercenaries phase/mode/complete.
- **Prompts**: the game's prompt units (key glyph + type) -> the QTE input.
- **Throwables/units**: remote mines, shells, flash resources (census for the ring lanes).
- **Camera**: yaw/pitch and camera target (used for aim).
- **Laser**: the laser-sight unit (section 6.1) - the game's own "where is the gun pointing" truth.
- **Bonuses**: time crystals (RE6), chests (RE4/RE5) units with position and state.
- **Nav mesh**: the game's collision triangles decoded once (`navmesh`, `_decode_nav`), used for walkability and
  line-of-sight rays; no pixels involved.

### 5.1.1 From hex to meaning: a worked example

Every snapshot field is a typed decode from a raw byte range. The pattern is always: module base -> pointer -> struct
unpack -> semantic field.

| Hex offset | Read | Decoding | Meaning |
|---|---|---|---|
| module + `0x28EAC10` (`S_PLAYER`) | `u64` | pointer | the player manager |
| manager + `0x30` (`P_FIRST`) | `u64` | pointer | player 0 |
| player + `0x60` (`P_POS`) | 12 bytes | `struct.unpack("<3f", ...)` | x, y, z world position |
| player + `0x1368` (`P_HP`) | 4 bytes | `struct.unpack("<hh", ...)` | hp, hp_max (two int16) |
| player + `0x6E2` (`P_STATE`) | 1 byte | `rd(...,1)[0]` | player state (0 standing, 2 downed...) |
| player + `0x598` (`P_MOTION`) | 2 bytes | `struct.unpack("<H", ...)` | motion/animation id |
| player + `0x5196` (`P_TABLETS`) | 2 bytes | `struct.unpack("<h", ...)` | first-aid/tablet count |
| module + `0x28E9AA8` (`S_ENEMY`) | `u64` | pointer | enemy manager |
| manager + `0x40` (`E_COUNT`) | int32 | `_i32` | live enemy count |
| manager + `0x50` (`E_ARRAY`) | `u64` | pointer array | enemy unit pointers |
| enemy + `0x60` (`E_POS`) | 12 bytes | `<3f` | enemy position |
| enemy + `0x1368` (`E_HP`) | 4 bytes | `<hh` | enemy hp, hp_max |
| player camera `CAM_OWNED` -> uCameraQFPS + `0x2C0` (`QFPS_PITCH`) | 8 bytes | `<2f` | camera pitch, yaw (floats; verified owner + vtable) |

Caches: unit scans (laser, camera, throwables, prompts) are cached per module base with `_FOUND`; a unit read that fails
or is out of place drops the cache and rescans. No value crosses into the decision layer without a finite/range check.

### 5.2 Nav-mesh sight (the "is the line clear" sense)

`NavMesh` (class in `re6_switch.py`, 6 methods) answers `clear(a, b)` / locate / path queries over the level's
triangles. It is the geometry witness: an enemy behind a wall is *visible to RAM but blocked to the mesh*, and the bot
treats mesh-blocked lines as not shootable (except the explicit point-blank/close-fire allowances). This is also how
pathing around the geometry works: `_escape_route` A* over the mesh produces the bomb-escape heading, the relocate
heading, and pursuit paths.

### 5.3 Laser truth (the "where is the muzzle" sense)

The enemy/self laser sight units are the game's own raycast display. The bot reads the laser's muzzle and dot
(section 6.1) to know exactly where the gun is pointing, then intersects that ray with enemy body volumes. That is a
three-dimensional, unlimited-distance sight cone as long as the laser exists.

### 5.4 What "no vision model" means in practice

- No screen capture is required for combat; the loop is purely numeric. (Screenshots are for the operator and for
  research/debug, not for aiming.)
- Enemies cannot be "unseen" by the system if RAM lists them; they can be *occluded* by mesh geometry, and that is
  intentional.
- If a pointer is unreadable, the system degrades to `None` and conservative rules (wait/reposition), not to guesses.
- The bot cannot learn a novel visual appearance; it discriminates enemies through RAM class ids, `enemy_identity`,
  body profiles (learned by class), and hp_max/behavior patterns.

---

## 6. The aimbot: laser raycast, body profiles, camera lock, trigger authorization

### 6.1 The laser sight is the aim truth

The game draws a laser from the muzzle to the first hit. The bot reads both ends of that ray from the laser unit:

| Read | Expression | Meaning |
|---|---|---|
| Unit find | `_find_unit(m, base, "laser", ("uLaserSight",), LASER_LINES)`; fallback `own_laser(m, p, index)` via `P_LASER (0x54E8)` and owner check at `LASER_OWNER (0x590)` | is this laser *his*? |
| Dot | `LASER_DOT = 0x60` (value 96) | where the ray lands in world space |
| Muzzle | `LASER_FROM = 0x440` (1088) | where the ray starts |
| Gun-up amount | `LASER_UP = 0x12C` (300), up when `>= LASER_UP_MIN 0.6`, `alpha` logged | has the gun actually been raised |
| Sanity | muzzle within `MUZZLE_NEAR = 400 cm` of the player when up; otherwise the cached unit is someone else's laser and the cache is dropped | stale-cache protection |

Two proof paths use the laser:

- **Ray-proven line**: `ray_error(origin, dot, point)` returns the yaw/pitch radians that would put the ray on the
  point; `near_line(...)`/`line_hits(...)`/`segment_hits(...)` intersect the ray segment with a body volume before its
  endpoint. A wall hit is never extended.
- **Camera line** (no laser read or laser short): the camera yaw/pitch and the enemy position produce the same
  yaw/pitch error; the ray is then believed only when the nav mesh says the straight line is clear (or the distance is
  inside point blank / close fire).

`aim_point(e)` aims at the enemy's chest on or near his floor using the class's learned `body(e)` profile; the body
volume (radius, height, head offset) is what `line_hits` uses, so a shot "on the head" or "on the chest" is the same
mathematical segment test.

### 6.2 The aim pipeline, step by step


| # | Step | Implementation | Failure fallback |
|---|---|---|---|
| 1 | Target pick | `_decide` picks `aim_at` from live enemies: nearest / most dangerous / laser source / boss / off-floor rules | no target -> hunt/walk/turn |
| 2 | Aim point | `aim_point(e)` -> chest point on the body profile (`body_classes`, `body`, UNIVERSAL_CORE) | body profile unknown -> chest approximation |
| 3 | Source selection | `_aim` reads the own laser (`laser`/`own_laser`); with the laser up it is the origin/dot source; otherwise the camera (`aim_cam`) line is the source | no laser and no camera -> stick steering only |
| 4 | Error solve | `ray_error(origin, dot, aim_point)` -> `(yaw_err, pitch_err)`; from the camera path the same solve uses `camera yaw/pitch` | angles outside sanity -> turn, never fire |
| 5 | Lock or steer | `AIM_LOCK` (True) and distance inside `AIM_LOCK_R (1500 cm)`: RAM camera write to `aim_cam.addr` (`re6_switch_mods` aim_writer) then read-back; otherwise `_yaw`/`_pitch` right-stick steering (`rleft/rright/rup/rdown`) | lock unconfirmed -> sticks; `aim_locks`/`lock_failures` counted |
| 6 | Envelope check | `_fire_envelope(dist, yaw_err, pitch_err)`: body half-width `FIRE_BODY_HALF_CM 30 cm` at range, pitch height tolerance, `SPRAY_YAW/SPRAY_PITCH` for spray shots | outside envelope -> raise/re-aim, not fire |
| 7 | Authorization | the ladder of section 4.4: point blank / close fire / proven / correcting / forced raise scatter / quick shot | unauthorized -> raise (caps 0.6 s), reposition for a line |
| 8 | Trigger | `_trigger(on, now, auto)` with the weapon family cadence (`fire_pattern`, `MAGNUM_FIRE_X`, `handgun`/`magnum`) and `fire_cooldown_s`; strafe added to aim actions (section 9.2) | cooldown -> hold aim, keep strafing |
| 9 | Bookkeeping | `_k_shot`: confirmed shots only are recorded to the aim book; accuracy from round reports | unattributed trigger requests are not trained |

### 6.3 Fire envelopes and the numbers that govern them

All distances in centimetres, all angles in radians unless noted. These are the shipped/verified values at the time of
this document (source constants; the bot-logic knobs can override some at runtime):


| Constant | Value | Role |
|---|---|---|
| `TICK_S` | 0.05 | decision tick (20 Hz) |
| `ENGAGE_R` | 1800 | normal engagement radius (a target beyond needs a proof/long-shot rule) |
| `MAX_DY` | 300 | same-floor vertical tolerance for shooting at all |
| `FIRE_LEVEL_DY` | 120 | tight level tolerance for fire decisions |
| `FIRE_ZONE_R` | 600 | close enemy preempts the bonus phase |
| `FIRE_FIRST_R` | 400 | one in clear sight near: gun before wheel/nade fire-first |
| `GEOM_CLOSE_R` / `GEOM_FIRE_ERR` / `GEOM_FIRE_PITCH` | 500 / 8 deg / 10 deg | nav-mesh geometry fire proof |
| `SPRAY_YAW` / `SPRAY_PITCH` | 30 deg / 20 deg | spray scatter cone |
| `POINT_BLANK_R` | 260 | no-laser point blank fire |
| `CLOSE_FIRE_R` | 600 | close fire on mesh-clear line (operator 2026-11-14) |
| `RAISE_SPRAY_R` / `RAISE_MIN_BULLETS` | 1000 / 20 | forced scatter burst when a gun is raised |
| `QSHOT_R` / `QSHOT_CONE` / `QSHOT_GAP_S` | 200 / 35 deg / 1.5 s | the game's own quick shot |
| `HIT_QS_N` / `HIT_QS_GAP_S` | 3 / 0.35 s | hit response quick-shot burst |
| `MELEE_R` | 140 | melee kick at arm range |
| `CC_R` / `CROWD_R` / `CROWD_N` | 200 / 260 / 2 | crowd/close-combat classification |
| `CROWD_GUN_N` / `CROWD_GUN_R` | 1 / 600 (operator 2026-11-14) | any close enemy -> shotgun/magnum |
| `LASER_WAIT_S` / `READY_S` | 0.7 / 0.12 | laser wait / raise ready window |
| `AIM_LOCK_R` | 1500 | camera RAM lock range |
| `SNIPER_LONG_R` / `LEDGE_RANGED_R` | 6000 / 8000 | long-range geometry / ledge ranged handling |
| `COMBO_KEEP_S` / `COMBO_HOT_R` / `COMBO_QUICK_R` / `COMBO_QUICK_GAP_S` | 2.5 / 3000 / 280 / 0.22 | combo keeper |
| `COMBO_URGENT_S` | 3.0 | the keeper's explicit urgency clock |
| `NADE_MIN_R` / `NADE_MAX_R` / `GRENADE_EVERY_S` | 500 / 1500 / 8 | combat grenade rule |
| `BOMB_SELF_R` / `BOMB_RADIUS_MAX` / `BOMB_MARGIN_CM` | 700 / 900 / 200 | native bomb safety (engine detonate safe = max(1200, ...)) |
| `STRAFE_S` / `RELOCATE_R` / `RELOCATE_S` | 0.8 / 120 / 2.5 | always-moving rules |
| `BOSS_STEP_R` | 650 | big wind-up step-out radius |

### 6.4 The full anatomy of "the gun is up but the bot is not firing"

This is the single most-repeated complaint in the rounds ("*I just watched him raise his gun up and not shoot in front
of a mob of people*"). The honest answer has two halves: why the old rules held fire, and what now guarantees fire.
The ladder that authorizes a trigger is section 4.4; every entry was added to close one of the causes below.


| Cause | What happened on screen | Rounds / evidence | Resolution now |
|---|---|---|---|
| Laser wait | the bot waited `LASER_WAIT_S 0.7 s` for a laser read before firing; with a flaky laser this repeated as a raise loop | early rounds: `reraise` counts high, e.g. 74% of t_raise was this wait | the close/point-blank/geometry proofs fire inside READY_S; the forced raise scatter fires on the raise tick |
| Mesh/probe proof only | the camera raise gate needed `proven and envelope and not is_blocked`; a target whose line never proved raised the gun for up to 50 s | live 2026-11-14: "raising the gun ~50 s while the combo lapsed" | raise gates fire when the nav-mesh line is clear at close range; mesh-blocked lines still reposition after 0.6 s |
| Body envelope too tight at range | stick error alone exceeded the 30 cm body envelope; the bot held aim instead of firing | reports of waving the gun at mid distance | geometry proof at `GEOM_CLOSE_R` with 8/10 deg tolerance; close fire body envelope; forced scatter inside 1000 cm |
| `is_blocked` false positives | a wall/cover hit from a probe vetoed the shot even when the enemy was visible | live fires at ceilings/floors and "never shooting" reports | `is_blocked` is now the authoritative mesh line only; probe refinements no longer veto close fire; level veto (`FIRE_LEVEL_DY`) remains |
| Raise cap | the raise was capped at 0.6 s and then repositioned, so in a mosh pit the bot looked like it raised and did not fire | round 33: raise repositions | a raise episode now fires its 20-bullet scatter at the aim target before any reposition |
| Held item / wheel cycle | a grenade or item in hand meant the trigger was not pulled for that cycle | nade/tablet complaints | hit/QTE/grenade rules run before the wheel; the wheel only opens on its own turn |
| Ammo 0 / reload | the gun was up but the magazine was empty; kill-with-gun-ammo rules exist | `ammo 0` shots in samples | `p.get("ammo") != 0` gates; the gun is reloaded/switched before a raise if empty |
| Preemptions | blast retreat/relocate/prompt/QTE/hold/down can preempt the aim before the trigger | these are intentional survival rules | documented in section 4.1; a normal aim tick cannot be preempted by a non-survival rule |
| Camera-not-on-target | the enemy was behind/left of the camera; the bot raised but steering had not solved the angle yet | live screenshots: enemy at the screen centre but off the ray | quick turn + face-for-quick-shot + strafe while aiming; the body envelope allows 30 cm at range |

**What is guaranteed now** (all tested): whenever the aim ladder is reached with a live same-floor target on a clear
nav-mesh line and ammo, the bot fires - immediately at point blank/close range, and through the raise-scatter burst
otherwise. A raise at a target whose line is blocked by the mesh, who is off-floor, or while an ammo-out hold is in
force is the only intentional non-fire. If you see a raise without fire again, the telemetry tables to look at are:
`raise_trigger_requests` vs `raise_repositions`, `scatter_forced`, `raise_bullets`, `offlevel_fire_veto`, `close_fires`,
`point_blank_fires`, `fire_contact_verified`, `aim` (the last aim string: distance, yaw/pitch error, source, keys).

### 6.5 Aim accuracy bookkeeping and learning

Every confirmed shot is attributed (`_k_shot`) only when the shot's effect is witnessed (damage or enemy hit) - raw
trigger requests are never trained. The aim book stores per-weapon/per-distance outcomes; the round report exposes
accuracy; `aim_book`, `hit_reports`, `impact_lessons` feed corrections into the next rounds, while `aim_locks` and
`lock_failures` count the RAM camera lock behaviour.

---

## 7. Command catalogue: everything the system can be told to do

### 7.1 Instant operator directives (`directives.py`)

These are the words the PiP accepts and the bot applies on the next tick. The hold time is how long the directive
keeps priority after it is issued.


| Command | Meaning | Hold (s) |
|---|---|---|
| fight | Fight them! (stop standing there, fight the foes) | 15 |
| next_area | Go to the next area | 0 |
| explore | Navigate more of the level | 15 |
| hunt | Go after the enemies (seek, find and dispatch them) | 20 |
| score | Go for score increases (build the combo) | 20 |
| repetitive | You are doing a repetitive action (stop it, go forward) | 8 |
| mine | Drop a mine and flee | 0 |
| mine_trail | Drop mines while leaving the area (plant, move on, repeat) | 45 |
| missing | You are missing (adjust the aim for this weapon) | 0 |
| rush | Flash and rush (in among them: every prompt, the magnum, a mine) | 10 |
| flashbang | Emergency flashbang (detonate a flash at my position NOW) | 0 |

### 7.2 Interventions (`interventions.py` OPERATIONS) - the operator buttons


| Operation | What it does |
|---|---|
| `first_aid_now` | press the first-aid/tablet immediately (survival override) |
| `flash_now` | native flash at the player, no item screen |
| `equip_primary` | put the primary gun in hand |
| `set_infinite_ammo` | toggle the game's infinite-ammo mod for this session |
| `detonate_mines` | flag-detonate the outstanding remote bombs |
| `remote_mines` | ask the remote-mine lane for a ring/status |
| `grenade_ring` | ring of grenades by the title's implementation (shell1304 launcher ring on RE6; hand/proximity rings on RE4/RE5) |
| `grenade_scatter` | scattering grenade throws |
| `proximity_mine_drop` / `proximity_mine_ring` | RE5 proximity mine drop/ring |
| `magnum_quick4` | the magnum 4-quick-shot pattern |
| `re6_shell_probe` / `re6_shell_barrage` | launcher shell research: probe one shell, then barrage a ring |
| `re4_harness_selftest` | RE4 switch harness self-test |

### 7.3 The action catalogue (`doing` / `act`) emitted by the RE6 bot

These are *all* distinct (doing, act) pairs in the current RE6 bot - 91 pairs. Each is a command the priority ladder can
emit; the `why` string attached to it in telemetry says which rule fired.


```text
aim             raise_fire
bomb            bomb_det_block
bomb            bomb_det_hold
bomb            bomb_face
bomb            bomb_gun_back
bomb            bomb_wait
bomb            gun_back
bomb_escape     blast_retreat
bonus           bonus_face
bonus           bonus_melee
bonus           bonus_raise
bonus           bonus_run
bonus           bonus_turn
bonus           bonus_wait
crowd           cc_kick
crowd           cc_quick_shot
crowd           cc_space
crowd           cc_turn
crowd           crowd_hold
crowd           fever_close
crowd           fever_kick
crowd           fever_quick_shot
crowd           push_kick
crowd           push_shot
crowd           push_walk
dead            continue
dead            dead_wait
down            down_dying_stay
down            down_kick
down            down_rise
down            down_windup_hold
flash           critical_flash
flash           hit_flash
held            break_free
held            grab_panic
held            held_auto_qte
held            held_prompt
hunt            combo_guard_walk
hunt            hunt_offlevel
melee           face_melee
melee           melee
melee           miss_quick_attack
melee           taunt
nade            gun_back
nade            nade_back
nade            nade_flash
no_foes         idle
no_foes         ranged_break
none            no_player
prompt          frozen_page
prompt          prompt_key
prompt          prompt_stick
quick_shot      combo_quick_shot
quick_shot      hit_quick_shot
quick_shot      lethal_combo_shot
quick_shot      periodic_quick_release
quick_shot      periodic_quick_shot
quick_shot      periodic_quick_wait
quick_shot      qte_recovery_shot
quick_shot      quick_shot
quick_shot      quick_shot_release
quick_shot      stall_spray
quick_turn      grab_panic
quick_turn      quick_turn
quick_turn      quick_turn_settle
raise           offlevel_raise
raise           raise
reload          reload
reload          reload_wait
reload          weapon_cycle_wait
reload          weapon_settle
reload          weapon_switch
tablet          tablet
tablet          tablet_dying
tablet          tablet_lower
turn            face_for_quick_shot
turn            ranged_break
turn            turn
unaim           unaim
walk            boss_step_out
walk            hazard_out
walk            lethal_backoff
walk            map_goal_walk
walk            pursue
walk            raise_reposition
walk            ranged_break
walk            relocate
walk            walk_blocked
walk            walk_detour
walk            walk_no_route
walk            wall_escape
```

RE5 and RE4 bots do not use this `_go` helper: their bots return the same kind of action dictionaries through their own
engagement helpers, with the same conceptual actions (aim, fire, quick shot, melee, bomb, mine, prompt, tablet, walk,
turn, crowd, special). Their class/method inventories are in the appendices.

### 7.4 Bot-logic knobs (live operator settings, re-applied every round)

Saved in `gbox-data/mercs/bot-logic.json`; any reload resets module constants and `tuning.apply` re-applies the saved
values at the next round start. The tables list every knob: name, operator label, group and shipped default.


(knob table unavailable: ValueError: too many values to unpack (expected 7))
---

## 8. Guidance -> implementation -> evidence -> next complaint

This is the honest ledger the operator asked for: what you said, what was built, what the following rounds showed, and
what you said next. Rounds refer to the DeepSeek PM handoff rounds (the append-only log is
`system/docs/DEEPSEEK-PM-HANDOFF-2026-11-13.md`). "Evidence" is live round telemetry/report data, not a claim.


| Round / when | Your guidance (abridged) | What was implemented | Evidence after the change | What you said next |
|---|---|---|---|---|
| R1-R8 | "start on time bonuses"; "once the time is at 5 minutes ... fighting, traps and combo maintenance" | bonus phase planner (RE4/RE5 chests, RE6 blue crystals), bank rule at 300 s, crystal shooting, phase switch | phase timers confirmed running: bonus phase then fight phase in reports | "the bot is meandering"; "not finding enemies" |
| R8-R12 | "the combo must always grow ... the combo should never be lost" | combo-aware priority: quick shot/face/chase keeper, break attribution (`combo_break_<doing>`), kill-gap pursuit, combo-aware deferral of heals/bonuses | 157-kill round (4 deaths) R10; 154 kills / max combo 53 / 193,200 score (build 69600bacd); a 2-minute stretch with combo == kills and 0 breaks | "the bot is just raising their gun and not firing"; "still losing the combo" |
| R13-R17 | "Enemy must be dispatched every 4 seconds ... dropping mines ... spamming rapid fire" | remote-mine ring cadence (drop_every_s ~10 s), flash-combo ring, surround ring, kill witnesses; more frequent held-fire resolution | kill cadence, mine ring counters; deaths from 1 hp with tablet failures found | "bot fells QTEs" (QTE failures); "bot not detonating bombs" |
| R18-R22 | "bot is shooting the ceiling / through the floor"; "nitrogen ring can't be clicked" | floor/level fire vetoes (`FIRE_LEVEL_DY`, off-level aim rules), laser/LOS truth, wall safety; shell-probe admission and receipt labeling fixes; row sources preserved | ceiling shots reduced; shell ring click receipts traceable | "can't click the nitrogen ring" (census refusal) |
| R23-R27 | "bot gets hit and fails QTEs"; "bot not reacting"; "the bot should drop mines then leave" | QTE recovery (flash while held, RAM auto-QTE, QTE ring), grab/flash responses, escape-then-detonate rules | qte_auto true, qte_seen 8, qte_failed 0 in a sample; 741,304-score completed round R24; 415,080 interrupted R25 | "combo still breaks"; "bombs explode after enemies leave" |
| R28-R31 | "If the bot fights while placing mines, the goal becomes easier"; "never let the combo stop" | blast combo fights (fight if shortfall <=1000 cm and deadline >1 s), lethal-out pre-shot dodge, downed flash first, standing-1hp flash, heal windows | 154-kill round from the earlier build remained best; live deaths from 1 hp in crowds reduced by critical flash ordering | "the bot stands and gets stomped"; "still raising the gun without firing" |
| R32-R34 | "combo is the true meta"; "flash must be automated"; "make the ring controls work" | `_combo_mandate_on` hot even before the first kill, hunt_elsewhere/offlevel, ring admission tolerates 4 remotes (04bc64a9d), operator shell-path row labeling, aim lock monitoring | combo breaks attributed by doing: held/tablet/down/nade/bomb_escape; round timing: 154 kills best | "you need to fire when the gun is up" (screenshot: gun up, mutant in front) |
| R35-R36 | "the bot has their gun up, but they don't take the shot ... at least twenty bullets in a scatter" | close fire (<=600 cm mesh-clear envelope), stall spray, raise repositions 0.6 s, then (26ee0e1cb) raise gates fire, forced 20-bullet scatter, strafe while aiming, relocate walk, boss step-out, heavy weapon within 600 cm, combo-urgency grenade spam, hit/QTE flash + alternation with nitrogen ring requests | live build 26ee0e1cb: 65 kills / combo 43 / one break in a sample; **raise_trigger_requests 108 / scatter_forced 108** in ~2 min; earlier window 223 raise fires; relocations firing | "Why is the bot never throwing grenades?" (next section) |
| R37-R38 | "why is the bot never throwing grenades? they are so effective" | NADES default on; periodic combat grenade every GRENADE_EVERY_S 8 s into a mob in 500-1500 cm, pacing gates relaxed for that call (c3893b42f); shell-caller max_remotes (aaf6e3219) so the alternating nitrogen ring can fire while a flash ring is out | unit-tested (351 pass); live verification of `combat_grenade_throws` was cut short by this document request - the live counter check for the grenade rule is still pending | (pending live round sample next round) |

### 8.1 The complaints that shaped the architecture (verbatim, with the structure they created)


| Your words | The structural response |
|---|---|
| "I see the bot standing around not shooting" | raise caps, forbidden idle, stall spray, periodic quick attack, kill-gap chase, relocate rule |
| "the bot is meandering" / "didn't find enemies" | RAM enemy scan + hunt_elsewhere/offlevel + pursue-any-distance combo mandate |
| "the bot is shooting the ceiling / through the floor" | `FIRE_LEVEL_DY`, off-level veto, mesh line checks, floor rules; level veto kept after the close-fire change |
| "can't click the nitrogen ring" | shell probe admission, receipt rows labeled with source, census checked under the native lock, caller-scoped remote tolerance |
| "QTE failures" | native prompt key press on the tick it appears, auto-QTE RAM flag, QTE recovery ring/flash, failure reports to `gbox-data/mercs/qte-failures/` |
| "not detonating enough remote bombs" | engine deadline-first lane: placement -> 5 s deadline -> escape -> detonate when clear; detonation receipts and misses counted |
| "bot gets stuck on ladders / repetitive QTEs" | prompt skip classes (repetitive climb/pickup) while combat prompts are absolute |
| "the bot stood still and got smashed by a giant foot" | strafe inside aim, forced relocate after 2.5 s/120 cm, boss step-out before anything |
| "losing the combo is a serious fail" | keeper ladder (grenade -> quick shot -> face -> chase -> spray -> hunt), urgency clock, break attribution per doing |
| "flash on every hit / QTE; alternate flash ring or nitrogen ring" | hit/QTE flash request, random 1-5 quick shots, alternating nitrogen ring request served by the remote lane |
| "always be dropping mines every 10 s" | remote-mine ring cadence in policy, travel drops and emergency rings; detonation on clearance |
| "grenades are so effective" | NADES on by default + 8 s combat grenade rule + cluster burst preserved |

---

## 9. Live performance table (round reports snapshot)

The latest stored round reports at document time (generated from `/api/mercs/round-reports`). "score" is the MercMode
score; max combo the highest chain in the round. Accuracy is only comparable within the same weapon regime.


| Time | Outcome | Score | Kills | Max combo | Accuracy | Deaths |
|---|---|---|---|---|---|---|
| 2026-11-14T11:17:18 | died | 31620 | 32 | 15 | 0.26 | 1 |
| 2026-11-14T11:08:57 | interrupted | 24950 | 30 | 17 |  | 0 |
| 2026-11-14T11:08:56 | interrupted | 13060 | 30 | 5 | 0.204 | 0 |
| 2026-11-14T11:00:08 | interrupted | 46440 | 74 | 22 | 0.2 | 0 |
| 2026-11-14T10:53:50 | died | 46280 | 55 | 29 | 0.155 | 1 |
| 2026-11-14T10:47:07 | died | 75880 | 87 | 30 |  | 1 |
| 2026-11-14T10:34:49 | died | 251760 | 163 | 51 |  | 1 |
| 2026-11-14T11:16:31 | died | 4200 | 14 | 0 |  | 0 |
| 2026-11-14T11:14:28 | died | 135380 | 155 | 30 |  | 1 |
| 2026-11-14T10:59:38 | died | 35440 | 49 | 17 | 0.214 | 1 |
| 2026-11-14T10:52:11 | died | 27440 | 38 | 18 |  | 1 |
| 2026-11-14T09:53:41 | interrupted | 119180 | 69 | 61 |  | 0 |
| 2026-11-14T09:53:40 | interrupted | 119180 | 69 | 61 |  | 0 |
| 2026-11-14T10:39:36 | died | 32480 | 34 | 23 |  | 0 |
| 2026-11-14T10:30:15 | died | 193200 | 154 | 53 | 0.5 | 0 |
| 2026-11-14T11:03:21 | died | 3480 | 9 | 3 |  | 1 |
| 2026-11-14T09:17:08 | interrupted | 6900 | 23 | 0 |  | 0 |
| 2026-11-14T09:17:07 | interrupted | 6600 | 22 | 0 | 0.2 | 0 |
| 2026-11-14T10:53:51 | died | 124960 | 84 | 59 | 0.5 | 1 |
| 2026-11-14T10:45:08 | died | 53320 | 52 | 22 | 0.0 | 1 |
| 2026-11-14T08:56:29 | interrupted | 23920 | 39 | 15 |  | 0 |
| 2026-11-14T08:56:23 | interrupted | 23920 | 39 | 15 |  | 0 |
| 2026-11-14T10:33:45 | died | 64280 | 53 | 40 |  | 0 |
| 2026-11-14T08:48:46 | interrupted | 1680 | 5 | 3 |  | 0 |
| 2026-11-14T11:16:01 | died | 90260 | 84 | 31 | 0.0 | 1 |
| 2026-11-14T08:35:52 | interrupted | 0 | 0 | 0 |  | 0 |
| 2026-11-14T11:04:41 | completed | 7120 | 17 | 6 | 0.421 | 0 |
| 2026-11-14T08:26:33 | interrupted | 59060 | 56 | 35 |  | 0 |
| 2026-11-14T08:26:33 | interrupted | 59060 | 56 | 35 | 1.0 | 0 |
| 2026-11-14T10:53:51 | died | 4500 | 15 | 0 | 1.0 | 1 |
| 2026-11-14T10:52:27 | died | 26540 | 24 | 24 | 1.0 | 0 |
| 2026-11-14T10:50:37 | died | 29940 | 28 | 26 |  | 1 |
| 2026-11-14T08:09:21 | interrupted | 17270 | 15 |  |  |  |
| 2026-11-14T07:48:29 | interrupted | 81880 | 61 | 46 |  | 0 |
| 2026-11-14T07:48:29 | interrupted | 81880 | 61 | 46 | 1.0 | 0 |
| 2026-11-14T11:06:32 | completed | 10820 | 19 | 9 |  | 0 |
| 2026-11-14T07:38:02 | interrupted | 50380 | 65 | 28 |  | 0 |
| 2026-11-14T07:37:53 | interrupted | 50380 | 65 | 28 | 0.163 | 0 |
| 2026-11-14T07:27:02 | interrupted | 21710 | 25 |  |  |  |
| 2026-11-14T07:20:32 | interrupted | 2500 | 5 | 2 |  | 0 |

Notable rounds quoted across the rounds (from telemetry and handoff evidence):

| Evidence | What it showed |
|---|---|
| 741,304 score, completed | the best full round in the recorded set; high combo stretch |
| 154 kills / max combo 53 / 193,200 score / ~18 min (build `69600bacd`) | best kill+combo run; 11 attributed breaks |
| 157 kills / 4 deaths (round 10) | early high-kill run |
| 40 kills, combo == kills, 0 breaks over a 2-minute stretch | proof the keeper works when kills keep coming |
| 65 kills / combo 43 / one break (build `aaf6e3219`) | after the operator-contract build; raise-fire counters 108+ |
| 223 raise-fire triggers in ~3 min (build `26ee0e1cb`) | the raised gun fires instead of waving |
| 99-kill, zero-death long round | earlier streak round |

**S-rank / five stars is still not achieved.** No table here claims otherwise; the goal remains active.

### 9.1 Deaths (the last stored death files)


| At | Session | Kills | Combo | Cause | Heals | Acts |
|---|---|---|---|---|---|---|
| 1794655108 | 56e2f01e50324149-cce1705de12a426d | 32 | 0 | doing=down why=down at 1 health: staying down, no fight held=0 lost=0 hp3s=[1] near2m=18 near4m=27 bomb=wait@2321cm | {'tablets': 2, 'presses': 11, 'misses': 14} | down_dying_stay |
| 1794655091 | 56e2f01e50324149-cce1705de12a426d | 32 | 0 | doing=down why=down at 1 health: staying down, no fight held=0 lost=0 hp3s=[1] near2m=18 near4m=27 bomb=wait@2321cm | {'tablets': 2, 'presses': 11, 'misses': 14} | down_dying_stay |
| 1794655074 | 56e2f01e50324149-cce1705de12a426d | 32 | 0 | doing=down why=down at 1 health: staying down, no fight held=0 lost=0 hp3s=[1] near2m=18 near4m=27 bomb=wait@2321cm | {'tablets': 2, 'presses': 11, 'misses': 14} | down_dying_stay |
| 1794655057 | 56e2f01e50324149-cce1705de12a426d | 32 | 0 | doing=down why=down at 1 health: staying down, no fight held=0 lost=0 hp3s=[1] near2m=18 near4m=27 bomb=wait@2321cm | {'tablets': 2, 'presses': 11, 'misses': 14} | down_dying_stay |
| 1794655040 | 56e2f01e50324149-cce1705de12a426d | 32 | 0 | doing=down why=down at 1 health: staying down, no fight held=0 lost=0 hp3s=[1] near2m=18 near4m=27 bomb=wait@2321cm | {'tablets': 2, 'presses': 11, 'misses': 14} | down_dying_stay |
| 1794653690 | c81883a4f2964e03-76ceecf721944917 | 55 | 17 | doing=down why=down at 1 health: staying down, no fight held=0 lost=0 hp3s=[1, 1] near2m=1 near4m=2 bomb=wait@3695cm | {'tablets': 0, 'presses': 3, 'misses': 2} | down_dying_stay |
| 1794653673 | c81883a4f2964e03-76ceecf721944917 | 55 | 17 | doing=down why=down at 1 health: staying down, no fight held=0 lost=0 hp3s=[1, 1] near2m=1 near4m=2 bomb=wait@3695cm | {'tablets': 0, 'presses': 3, 'misses': 2} | down_dying_stay |
| 1794653656 | c81883a4f2964e03-76ceecf721944917 | 55 | 17 | doing=down why=down at 1 health: staying down, no fight held=0 lost=0 hp3s=[1, 1] near2m=1 near4m=2 bomb=wait@3695cm | {'tablets': 0, 'presses': 3, 'misses': 2} | down_dying_stay |

---

## 10. Game-by-game: how combat differs in RE4 and RE5

The shared shape (section 4) is realised differently per game. The full differences:

### 10.1 RE4 (GameCube/Wii eras + switch harness)

- Bot: `titles/re4_switch.py` (Bot, 97 methods); snapshot has 17 keys (`player`, `enemies`, `laser`, `camera`, `game`,
  `timer`, `kills`, `weapon_class`, `census_classes`, `laser_gate`, `fire_witness` ...).
- Aiming: room geometry (`re4_room_map.py`), camera/laser gate, `re4_garrador_aim.py` for the Garrador, weapon rate
  (`re4_weapon_rate.py`), native weapon classes (`re4_switch_weapon_native.py`).
- Movement: room-based navigation (`re4_nav.py`, `re4_walk.py`, `re4_traversal.py`, ladders), movement safety module.
- Mines: bot-served hand throw with the physical hand (`re4_switch_mines.py`), because the GameCube hands the item model.
- Rings: `re4_reactive_ring.py` reactive ring machinery.
- QTE: `re4_switch_screens.py`, prompts and pace (`Pace` class) - the GameCube's QTEs are native screens.
- The RE4 GameCube path required a verified unlimited-life hand for the ring; this is why some RE4 ring classes only run
  on verified builds.

### 10.2 RE5 (PS3 RPCS3 + switch harness)

- Bot: `titles/re5_switch.py` (Bot, 208 methods); snapshot has 42 keys including `nav`, `prompt`, `ground_mines`,
  `bonus_scan`, `rank_points`, `timer_start`, `scoring_players`, `no_mercy`.
- Aiming: `re5_aim_geometry.py`, `re5_switch_aim.py`, aim camera/pitch, fire animation (`re5_fire_animation.py`),
  weapon catalogue (`re5_weapon_catalogue.py`, `re5_weapons.py`).
- Mines: proximity mines and mine escape (`re5_mines.py`, `re5_mine_escape.py`, `re5_native_mine_tactic.py`,
  `re5_native_mine_escape.py`, `re5_proximity_native.py`), with a bot-served ring.
- QTE: `re5_qte.py` ProgressHook, `re5_switch_prompt.py`, recovery (`re5_qte_recovery.py`, `re5_recovery.py`).
- Stage specials: `re5_specials.py`, `re5_stages.py`, stage hazards, coop, eggs, health/inventory modules.
- Rings: `re5_reactive_ring.py`.

### 10.3 RE6 (Switch)

- Bot: `titles/re6_switch.py` (Bot, 183 methods); snapshot 46 keys.
- Native controller `re6_switch_native.Controller` (34 methods); engine lanes for remote mines, deadlines, shell probe,
  QTE recovery; `re6_switch_mods` for aim lock and bot options; `re6_switch_equip` wheel; `re6_switch_wall` and
  `re6_movement_safety` movement hooks.
- This is the reference game for the modern combat contract (raise-fire, scatter, combo keeper, relocate, hit flash
  rings, nitrogen alternation).

---

## 11. Known limitations, open verifications and honesty notes

- **Combo is not yet invariant.** Break counts still appear in live samples (typically held/down/tablet/blast/QTE
  windows). The keeper reduces them; it does not yet make them zero.
- **Raised gun without firing** is reduced by the raise-fire + forced scatter rules, but a wall-blocked line, an
  off-floor target, QTE/hold, or a blast escape will still not fire - intentionally. Any future report should be
  checked against the telemetry list in section 6.4 before changing the policy again.
- **Hit-flash / nitrogen alternation**: wired and tested; live counters (`hit_flashes`, `hit_nitrogen_requests`,
  `nitrogen_rings`) have not yet been observed firing in a sampled window (the hits did not line up with the flash
  gate). Nitrogen rings can still be refused by the shell census; the bot-side request now tolerates the flash ring's
  15 remotes, the operator click keeps the 4-mine tolerance.
- **Combat grenade rule** (`combat_grenade_throws`, every 8 s into a mob) is unit-tested; the live verification sample
  was interrupted by this document request and is pending.
- **Mine rings and enemies**: mines are placed on the travel/flash/surround triggers; a scheduled ring is not currently
  gated on a nearby enemy (a gate was tried and reverted because it broke the travel-placement contract). Detonation
  happens as soon as the player is clear, which is the "explode while enemies are near" behaviour the operator wants
  only when enemies were near at placement time.
- **Red tests**: 3 tests in `tests/test_mercs_remote_mines.py` (flash/surround ring expectations) remain red from
  another lane's engine drift; everything in the switch/bonus/periodic and shell suites is green (351 + 69 at last run).
- **Host contention**: the MercMode rotation includes PSO/RE4/RE6 lanes; a forced `stop`+`start title=re6` is the
  reliable way to secure a RE6 verification window.
- **S-rank / five stars: not achieved.** The live best full round is 741,304 score with a high combo, which is not a
  five-star score on all runs. The goal stays open until the operator's round evidence says otherwise.

---

## 12. Appendices: class / method / function inventory

Auto-generated from the source at this revision; descriptions are the first docstring line where present. The full
method index is included for the core RE6 modules and the RE4/RE5 bot classes so the document is a complete map, not a
summary.


### `titles/re6_switch.py`


**class _Pick** (2 methods) - This menu visit's draws, kept until the round is up (screen() says playing), then drawn afresh at the next

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `reset` |  |


**class NavMesh** (6 methods) - A stage's walkable triangles: V vertices, T (a, b, c) indices, N neighbour lists; locate() / path().

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `links` | The tactical map's links: per triangle [(neighbour, its shared edge 0-2, cost)], from N (worked out once). |
| `_inside` |  |
| `locate` | The triangle under pt (within NAV_DY of its height), else the nearest centre within two cells. |
| `clear` | Whether the straight line a -> b stays on the walkable floor (on a's level): walked triangle to triangle |
| `path` | A* from a's triangle to b's: the shared edges' midpoints, then b. None: off the mesh or no way there. |

- class `_Title` - When the title came up without its main-menu byte (the unlock-on-load is off: the run must say so).

**class BlastBook** (4 methods) - The remote bomb's reach in this title, learned from its blasts: each booked blast {me_cm, hp_lost, hit_cm,

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `radius` |  |
| `safe` |  |
| `add` |  |


**class Bot** (183 methods) - One decision per tick from the snapshot.

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `_round_start` | The first tick alive of a round: its marker for the engine; after a death answered YES, the replay counts as |
| `_stage_book` | Each stage's lessons (operator 18:03: "learning and studying and cycling through all of the levels"): once a |
| `_stage_write` |  |
| `_cost` |  |
| `_choose` |  |
| `held` | The left stick pressed for STUCK_S while he neither turns nor moves: something holds him. |
| `grabbed` |  |
| `_tablet_check` | An R press counts as a tablet once the count falls (stats tablets); none within TABLET_CONFIRM_S is a press |
| `_note_dying_transition` | What took him from above 1 health to the dying crawl (the S-rank killer): the flat telemetry the death |
| `_qte_recovery_shot` | Three quick shots right after a survived QTE, before the flee (operator 2026-11-13). |
| `_quick_shot_target` | The enemy the camera/laser ray is actually on within `radius` (None: the ray is on the ceiling/air). |
| `_face_for_quick_shot` | Turn the camera to the nearest close enemy (no fire): the quick shot follows once the ray is on him. |
| `_heal_window_ok` | A heal may start only with a fresh combo window (or none running), unless near-critical health. |
| `_inside_blast_margin` | True when a placed mine's clearance rule says he is still inside the blast and must move out. |
| `_qte_report` | A failed QTE/prompt writes its own JSON investigation file (kept to QTE_REPORT_KEEP). |
| `_relocate_step` | Never hold the same spot among enemies: after RELOCATE_S with less than RELOCATE_R walked while one is |
| `_combat_grenade` | A grenade into a mob in throw range at most every GRENADE_EVERY_S (operator: "why is the bot never throwing |
| `_blast_retreat` | Out of a live remote-bomb blast BEFORE any other action: the engine's detonation waits for 1200 cm and live |
| `_combo_mandate_on` | The combo mandate is in force: a kill must land now, so a non-kill detour (a bomb sprint included) waits. |
| `_laser_sources` | Enemies whose laser sight / ranged wind-up is on him, nearest first ("backtrace the laser to the enemy"). |
| `_combat_pressure` | An alive enemy is in sight within COMBAT_PRESSURE_R on his floor: fight, do not go sightseeing. |
| `_combo_guard` | Never idle while the combo is about to lapse (operator 2026-11-13, the absolute mandate: "never let the bot |
| `_critical_no_tablet_flash` | Critical health in a melee crowd: the native flash and a gun-down moment instead of raising the gun. |
| `_dying` | At 1 health (RE6's dying crawl): R for a tablet every DYING_GAP_S while the case holds one. None: no press |
| `_score_hits` | A zombie's health falling within HIT_S of a shot is that shot's hit (accuracy = hits / shots). |
| `_turn` | The camera (gun down): the right stick, pulsed inside TURN_FINE so it does not swing past him. |
| `_yaw` |  |
| `_pitch` |  |
| `_trigger` | The trigger while a zombie is on the line: held for an automatic gun, tapped (a tick down, a tick up: the |
| `_burst` |  |
| `_fp_driver` |  |
| `_fp_offset` | The scatter's offset (cm) from e's aim point for this press, or None (no pattern gun, or a pattern error: |
| `_fp_fired` |  |
| `_gun_down` |  |
| `_act` | What this tick decided, for the watch panel and the round's audit: stats act and acts (counts). |
| `_go` | One decision: its doing (the look's time budget), its act (stats act / acts) and why. |
| `tick` |  |
| `_respond` | core.respond on this tick's decision: the native flash, the remote bomb due, or the fight on the threats. |
| `_flash_gate` |  |
| `_flash_immune` | A flash does not stop him: FLASH_IMMUNE_HP of maximum health or more, or a boss tier. |
| `_escape_clear` | A clear way out: the push heading's line PUSH_CHECK_R long on the nav mesh, nobody within 150 cm of its end |
| `_flash_reason` | core.flash_window.tight on this tick: grabbed / windup / surrounded / low_falling, or None. |
| `_flash_ok` | (allowed, reason) of an automatic flash by path: the gate's minute and, FLASH_TIGHT, a tight reason. |
| `_fire_first` | FIRE_FIRST: the nearest flashable one in clear sight within FIRE_FIRST_R on his level, or None. |
| `_respond_flash` | The native flash at his position (re6_switch_native, the operator's flash_now: no item screen, no input), |
| `_detonator_away` | The remote in his hand outside a throw or a press of his own (the game's item bounce, a hold, a blast): the gun |
| `_no_wheel` | The D-pad never leaves the bot in a round (operator 2026-11-10: "I dont even want to see the item screen or |
| `_remote_unsafe` | The remote in his hand with its bomb out and him inside the learned reach + margin (ZR would set it off). |
| `_gun_index` |  |
| `_equip_keys` | Every equip through the RAM hook (re6_switch_equip's native request) - never the item wheel or the weapon |
| `_govern` | The turn governor: his heading turning faster than SPIN_DEG_S, or a sped-up action running, releases the |
| `observe_round` | Record a native death before the engine finalizes this round's evidence. |
| `_record_death` |  |
| `_tick` |  |
| `_held_prompt` | In a hold, whatever button the game's prompt shows, pressed and let go tick by tick (a mash, and a timing |
| `_emergency_flashbang` | Legacy directives cannot substitute inventory/throw input for a native effect. |
| `_wall_command` | The operator's wall (the PiP's wall button sends the explore / next_area command; operator 2026-10-28: "it |
| `_operator_command` | The operator's instant commands (gbox.mercs.directives), else the doctrine's (core.doctrine.Reader), read |
| `_mine_now` | The mine command: the remote bomb due for MINE_DUE_S (the bomb rule's own gates for room and health stay). |
| `_mine_due` |  |
| `_goals` |  |
| `receive_map_goal` | The tactical publisher's hand-over, on the engine's thread: the operator's click. |
| `map_goal_plan` | For the tactical map (tactical._take_map_goals): the round's map-goal token, what a click may ask for (an |
| `_goal_log` | MAP_GOAL_LOG: one JSON line (at most one a second unless forced); never raises. |
| `_floor_y` | The floor's height under a spot on the map: the mesh's triangle there nearest his own height, else his. |
| `_operator_goal` | MAP_GOALS: this tick's action for the operator's mark on the map, None when there is none (or it waits). |
| `_walk_goal` | The walk to a mark by the stage's mesh (straight with no mesh); no route for GOAL_NO_ROUTE_S closes the mark |
| `_never_stand` | The step along open floor when he has not moved STAND_MOVE_CM for STAND_MAX_S. |
| `_grab_swap` | A grab: a random loaded shotgun or magnum other than the gun in hand, switched to once he is free. |
| `_grab_detonate` | A grab never bypasses the native all-bomb clearance gate with ZR. |
| `_weapon_switch` | The wanted weapon into his hands - the app's (WANT_WEAPON), else a shotgun for a crowd on him, else a grab's |
| `_hold_ended` | A RAM hold's end: stats holds_freed_no_press (it ended before he pressed anything: the game's auto QTE) or |
| `_decide` |  |
| `_on_line` | The first body intersected by the measured laser segment. Camera alignment only guides acquisition; |
| `_aim` |  |
| `_quick_tick` | Quick attacks from his action (snapshot action): stats quick_attacks (each one begun), quick_attack_interval |
| `_periodic_qa_interrupt` | A prompt owns its resulting action; it cannot acknowledge an earlier burst. |
| `_periodic_qa_observe` | Observe the game's action after a requested burst press; an input is not a landed attack. |
| `_periodic_quick_attack` | Bounded periodic quick shots, below native prompts, healing and equipment recovery. |
| `_lock_ready` |  |
| `_off_floor` | The living ones off his floor within AIM_LOCK_R (3D) and in sight: a ceiling's, a hanging one, a boss. |
| `_vertical_threat` | One off his level worth aiming at: above him within CEILING_R, or a big one. |
| `_lock_fail` |  |
| `_lock` | The player camera's yaw onto the camera's line through tgt's aim point (or point), its pitch from that line's |
| `_sweep` | The lock's sweep: the current target until SWEEP_SHOTS aimed shots (or his health is gone), then the nearest |
| `_aim_core` |  |
| `_aim_learning_clear` |  |
| `_aim_tick` |  |
| `_aim_book_offset` | The book's correction as an offset (cm) from aim_point - the body point, the lead, the angular correction - |
| `_aim_book_shot` |  |
| `_aimed_shot` |  |
| `_lock_tick` | aimed_hits: an aimed shot's target's health fell within LOCK_HIT_S; boss_damage: the big ones' health lost |
| `_down_tick` | Down (DOWN_ACTIONS, kept through DOWN_KEEP's) or up; down_s, down_kills, down_recoveries, since_dying. |
| `_down_fight` | Down: the nearest within DOWN_FIGHT_R locked and fired at (a kick for one within MELEE_R), no tablet, no |
| `_hazard_tick` | His health falling with nobody within HAZARD_CONTACT_R, not held and not his blast: a hazard marked at his |
| `_hazard_break_due` |  |
| `_windup_tick` | Wind-ups begun (windup_seen), stopped by a hit (windup_interrupts), and his health falling with one winding up |
| `_taunt_watch` | The triggers: TAUNT_KILLS kills within TAUNT_KILLS_S, a blast's TAUNT_BLAST kills (bomb_kills / grenade_kills |
| `_taunt` | A trigger waiting, nobody within TAUNT_CLEAR_R, TAUNT_GAP_S since the last: the right stick's click (a tap, |
| `_census_tick` | The stage's living zombies (census_alive) and those on his floor (census_floor); a pursuit's end: the kill |
| `_prompt_book` | The shown prompts against the last tick's: new ones counted seen (prompt_types), gone ones after a press |
| `_prompt_spot` | A B prompt's spot, logged per stage (the nav's climb links to be). |
| `_prompt_pressed` | Every shown prompt asking for key counts as pressed now (its latency the first time). |
| `_prompt` | A shown prompt's button, pressed at once and again every PROMPT_REPEAT_S while it stays. None: no prompt to |
| `_nav_heading` | The next nav-mesh waypoint heading; None means no usable mesh or no path, distinguished by the caller. |
| `_walk_keys` | Turn with the governed stick; forward and side steps wait for observed facing. No navigation RAM writes. |
| `_pursue` | After the best zombie of the whole stage (his floor first, then the nearest): along the camera turned to him, |
| `_open_heading` | The clearest way out: of KITE_DIRS headings, the one the zombies within KITE_SCAN_R stand least in the way of |
| `_way_costs` | [(cost, heading)] of the KITE_DIRS headings: how much the zombies within KITE_SCAN_R stand in each one's way. |
| `_overwhelmed` | OVER_N within OVER_R, or his health fallen within HP_FALL_S with OVER_HURT_N that near. |
| `_push_heading` | The way out of a crowd: the KITE_DIRS headings from the clearest (_open_heading's cost) on, the first whose |
| `_stick` | The left stick toward heading h with the camera at yaw: up along it, left at +90 deg, the diagonals between. |
| `combo_left` | Seconds left in the running combo's window (sGameMan +0x409C; None: no combo, or not read) - |
| `_bonus_wait` | Combo pacing may defer time collection only after the five-minute bank. |
| `_bonus_clock_ready` | Only a finite current clock proves the bank; zero is a valid low clock. |
| `_time_bonus_priority` |  |
| `_combo_tick` | The combo's count and window (sGameMan): stats combo_best, combo_breaks (it lapsed with a zombie in reach), |
| `_nade` | _nade_core, thrown on the move: while one is within NADE_FLEE_R the stick keeps him going away from them |
| `_nade_core` | A flash at FLASH_N within FLASH_R (none within NADE_CLEAR_R), or a hand / incendiary grenade into a cluster |
| `_held_item` | An item in his hand outside a throw or a bomb's steps: a hand / incendiary / flash grenade thrown at once (the |
| `_nade_ground` | The camera onto the ground among them for the throw (NADE_GROUND_MIN above): a point toward n["to"], at least |
| `_throw_plan` |  |
| `_throw_aligned` |  |
| `_wheel_key` | The D-pad press that steps the item wheel toward wheel index `index` (live 2026-10-27 14:17: from a gun the |
| `_clusters` | Clusters of NADE_N within NADE_CLUSTER_R of one another NADE_MIN_R..NADE_MAX_R off (each zombie once). |
| `_nade_ground_ok` | A grenade target on the ground: on his floor (NADE_FLOOR_DY), standing on the nav mesh near its height, and |
| `_floor_at` | True: pt stands on a walkable triangle of the nav mesh (inside it, within dy of the floor's height there); |
| `_nade_landing` | Where this grenade may go (NADE_LAND_SLACK above): the group's centre at their feet when it, the points |
| `_nade_aim_keys` | The right stick while the grenade is readied: the camera's line (mCameraPos -> mTargetPos) onto the ground |
| `_nade_again` | The next target of the in-hand burst (NADE_BURST_N throws of the grenade he holds), or None: the burst is |
| `_nade_moved` | Has he moved on since the last throw cycle - NADE_MOVE_CM from where it stood, or NADE_MOVE_WAIT_S since? |
| `_nade_done` |  |
| `_burst_begin` | Start a grenade cluster-bomb burst (operator 2026-11-03) when BURST_SURROUND_N or more enemies encircle him |
| `_burst_end` | End the cluster-bomb burst: record the lobbed count and let _mods restore the normal throw speed. |
| `_fire_envelope` | The current aim error would still land inside the body at this distance (FIRE_BODY_HALF_CM/ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬ |
| `_measured_contact` | Current body contact, excluding a pre-redirect ray and a frozen ray after camera movement. |
| `is_blocked` | Out of sight: blocked within BLOCK_S, or behind a wall by the nav mesh (_sight), and not within BLOCK_MIN_R of |
| `_sight` | The nav mesh's line from him to e (cached SIGHT_S): False only when it crosses a wall; off his level or off |
| `_mesh_clear` | The nav mesh PROVES the straight line from him to e is clear (no wall before the enemy). True only when a mesh |
| `_block` | A zombie out of sight for BLOCK_S (stats <why>): never fired at, never the target while another is open. |
| `_ray_short` | The laser's ray pointed at him (within LOS_YAW / LOS_PITCH of his chest) ends short of him: a wall between. |
| `_probe_short` | The lock on him LOS_PROBE_S and the laser's ray, within LOS_PROBE_ERR of his line, ends short of him. |
| `_los_tick` | Out of sight by what the shots did: the trigger on one zombie NOHIT_S without his health falling, or |
| `_push_through` | The fever after a flash with a way out: the stick along it (he faces where he walks), the camera turned onto |
| `_crowd_control` | A zombie up close (CC_R, in front or flanking): the gun down, the game's quick shot every CC_QSHOT_GAP_S and a |
| `_bonus_book` | This round's bonuses: one waiting at the last tick and gone now was broken (taken: stats bonuses_taken, |
| `_bonus_close` | The round's end (or a replay): the bonuses still waiting count as missed; bonus_log keeps the last rounds. |
| `_bonus_run` |  |
| `_bonus_sight` | The nav mesh's line from him to the bonus's middle (~1.3 m up): False when a wall is between them. |
| `_bonus_shoot` | A bonus shot through the lock: its centre locked onto, the gun up, the trigger down while the laser's ray runs |
| `_time_bonus_shot` | Below the five-minute bank: shoot a blue time bonus in range through the lock instead of only walking to it. |
| `_green_save` | The match: the combo window under COMBO_LOW_S, a green (combo) bonus in sight within BONUS_SHOOT_R and nobody |
| `_bonus` | A combo bonus in reach with nobody near (BONUS_SAFE_R): turned to, the gun up, the aim's ray closed |
| `_bomb` | Remote bombs (BOMBS): healthy (BOMB_MIN_HP), nobody within BOMB_ROOM_R and BOMB_STAND_N coming 6-12 m off, at |
| `_drop_ok` | The bomb may go down by the instant drop (BOMB_INSTANT_DROP): the hook bound, its native drop offered on |
| `_held_bomb_ok` | The remote bomb in hand may be placed at once: the hook bound (BOMB_MIND), one in his pack, none out, him |
| `_bomb_out` | A bomb of his out: the remote's slot at mode 1 and, where the snapshot read it, the detonator's flag still |
| `_mind_ok` | The hook may set the bomb off now: BOMB_MIND, a hook bound to this session and ready, no failure within |
| `_bomb_went_off` | The bomb out is gone after a set-off (the game put the gun back): counted, its toll read for BOMB_LEARN_S |
| `_bomb_track` | Where the bomb out lies: read from its unit (snapshot bomb_pos, within BOMB_REAL_R of him), else where he stood |
| `_bomb_escape` | Inside the bomb's learned reach while it is out: he walks out before anything else (only a hold comes first); |
| `_blast_tick` | A blast's toll, BOMB_LEARN_S after it showed: the zombies it hurt and spared by their distance from it, his |
| `_death` | stats death_log: what he was doing over his last HP_HIST_S (the decisions while his health fell), whether a |
| `_escape_route` | The heading along a mesh A* route to the nearest floor point already clear of every armed bomb. |
| `_bomb_walk` | Off the bomb: the camera turned to it and the stick back (he runs away from it); not 30 cm further in |
| `_escape_fire_inputs` | Merge retreat movement into firearm aim before the final wall checks. |
| `_bomb_kills_tick` | A blast's kills (stats bomb_kills): the kill count BOMB_KILLS_S after it less the count when it was set off; |
| `_bomb_press` | One step of a bomb's keys: the wheel stepped (D-pad down) until the remote bomb is in hand, the crowd brought |
| `_front_foe` | A living zombie in front of him within reach (inside FRONT_CONE of his facing). |
| `_pulls_tick` | Trigger pulls: one starts when the trigger starts working on a zombie (its look entry, the raise's first pull |
| `_k_shot` | Every resolved pull, the misses above all, into the enemy knowledge database (operator 2026-10-28: "I want a |
| `_look_tick` | After each decision: the time since the last tick in the budget of the decision that ran (t_<doing>, |
| `_uc` | The core's pieces, made on first use (a bot the hot reload rebinds to this class never ran this version's |
| `_profile` | This tick's profile (made at the tick's start by _core_tick), else a fresh one. |
| `_core_error` |  |
| `_core_tick` | Every playing tick: the profile (the live constants), and who hurt him (the living, his health's falls). |
| `_threat_pick` | The scorer's bands over these (combat.Threats.priority): a learned wind-up within its class's reach, a boss / |
| `_lethal_out` | A learned attack that lands through his shots under way within its reach (combat.Threats.step_out): the gun |
| `_frozen` | combat.NotInControl (FROZEN above): A every FROZEN_TAP_S while his shots do nothing and nothing moves him. |
| `_idle_core` | combat.IdleGuard on this tick's output: the gun up IDLE_AIM_S at his target without a shot -> IDLE_WALK_S |
| `prompt_ok` |  |
| `save` |  |


**class RE6Switch** (11 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `snapshot` |  |
| `screen` | playing / dead / results / loading for the engine. The HUD unit and the player name the round; the clock |
| `_where` |  |
| `death_witness` |  |
| `_mods` | The session's live mods (re6_switch_mods: infinite_ammo's magazines topped up) on every snapshot, when the |
| `result_ready` | The terminal tally is final (the engine closes the round's evidence then): the RESULTS unit is up, or the |
| `menu_handoff` | The engine hands a finished round back to the menus only when RAM names a native screen: the results, a |
| `brain` |  |
| `prompt_keys` |  |
| `progress` |  |


**class BombMind** (7 methods) - The bot's remote-bomb hook (BOMB_MIND): re6_switch_mods.detonate on the session's own adapter - the

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `adapter` |  |
| `ready` |  |
| `__call__` |  |
| `drop_ready` | The instant drop is offered: Linux NCE (the native mailbox, re6_switch_native) on this session. |
| `drop` | A remote bomb down at `at` (default his feet) already placed and armed (re6_switch_native.bomb_drop_now). |
| `settle` |  |

### `titles/re6_switch_native.py`

- class `Unavailable` - 
- class `Uncertain` - 
- class `AllocationLost` - The game reclaimed a spawned projectile before we could detonate it.

**class Controller** (34 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `adapter` |  |
| `rd` |  |
| `q` |  |
| `w` |  |
| `check_build` |  |
| `check` |  |
| `write` |  |
| `publish_call` |  |
| `install` | Install only into zero padding, through its exact verified backing FD. |
| `stopped` |  |
| `wait` |  |
| `attach` |  |
| `validate_heap` |  |
| `call` |  |
| `recover_completed_call` | Permit a new click only after the old native call is fully quiescent. |
| `detach_completed` |  |
| `ready` | Current intervention epoch without changing the bound call owner. |
| `_ammo_backend` |  |
| `ammo_status` | Read this title's supported ammo mechanism without installing a hook. |
| `set_infinite_ammo` | Use the existing mod, with the same life/input guard before every write. |
| `weapon_choices` |  |
| `equip_primary` |  |
| `current_weapon` |  |
| `flash` |  |
| `grenade_kinds` | The ring's kinds as this build can honestly fire them (gbox.mercs.grenade_status reads this). |
| `launcher_kinds` | The rounds this title's grenade launcher fires: the shell classes (uWp1302/1303/1304). Cross-title the |
| `_ring_one` | One grenade of `kind` spawned, relocated to (x, y, z) and detonated. |
| `shell_barrage_ring` | One research barrage of launcher shells on a ring around the player (the 360 nitrogen ring). |
| `grenade_ring` | Spawn `count` grenades in a ring around the player and detonate them in a quick ripple. |
| `grenade_scatter` | A scatter barrage (operator 2026-11-10 ~07:00: "spray a scatter shot of grenades from his postion at threats |
| `_ensure_image` | One more pinned image into the zero padding (install() refuses anything else), the process stopped for it |
| `drop_bomb` | A remote bomb dropped at `at` (x, y, z; default his feet) already lying placed and armed - no throw, no |
| `drop_bomb_ring` | `count` remote bombs ejected from his body in a ring around him, each already lying placed and armed - |

### `titles/re6_switch_mods.py`


**class Mem** (2 methods) - The session's guest memory for re6_switch's readers: rd() and the adapter (its guest rows find main).

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `rd` |  |


**class RE6Switch** (5 methods) - RE6 Switch in one session: main's base this boot, checked against this build's title gate.

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `slots` | The gun slots [(slot, rounds, capacity)]: the weapon slots' cItem records with a magazine (0 < capacity <= |
| `tablet_slot` | The tablet case's live slot (slot, count, capacity): an item slot (7-11) with the cItem vtable, in use, the |
| `thrown_slots` | The live grenade and remote bomb slots: (stacks, wheel), each [(slot, type, count, capacity)] - a cItem slot in |
| `status` |  |

### `titles/re6_switch_equip.py`

- class `_Stop` - 

**class _Reads** (4 methods) - Bounded native reads; the caller's memory adapter owns process identity.

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `rd` |  |
| `u32` |  |
| `u64` |  |


**class Controller** (5 methods) - Session-bound driver bridge. Refusal never falls back to wheel inputs.

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `record` |  |
| `cycle_ready` | Read-only proof that ordinary pad cycling will not overlap a request. |
| `tick` |  |
| `select` |  |

### `re6_remote_control.py`


**class Travel** (4 methods) - Credit observed locomotion, never stick input, wall pushing or warps.

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `observe` |  |
| `due` |  |
| `claimed` |  |


**class RingFlight** (5 methods) - One allocation batch per player life; no replay after an uncertain call.

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `busy` |  |
| `submit` |  |
| `poll` |  |
| `close` |  |

### `re6_bomb_deadlines.py`


**class Deadlines** (4 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `observe` |  |
| `triggered` |  |
| `_result` |  |

### `qte_escape.py`


**class Recovery** (4 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `_fire` |  |
| `observe` |  |
| `_dispatch` |  |

### `interventions.py`


**class Queue** (8 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `_remember` |  |
| `_change` |  |
| `status` |  |
| `post` |  |
| `claim` |  |
| `finish` |  |
| `finish_many` |  |

### `titles/re5_switch.py`


**class StageCycle** (9 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `observe_cursor` | Learn the character select's entry count from the game's own cursor. |
| `note_press` | Remember the cursor and key of a press, so observe_cursor can tell a stall from a move; a forward press on |
| `stalled` | The forward walk has stood still (STALL_PRESSES presses over STALL_S at one cursor): the select's end. |
| `visit` | A new walk on a select (or its A): the stall count starts again. |
| `save` |  |
| `pick` | (stage, character) for the coming round, held until a round starts on it. |
| `started` |  |
| `coverage_text` |  |


**class _SteadyGoals** (1 methods) - map_goals.Goals with the enemy rule of 2026-11-09 20:50 (no health reading is alive; a slot empty for

| Method | Purpose (first doc line) |
|---|---|
| `resolve` |  |


**class Bot** (208 methods) - One decision per tick from the snapshot.

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `_cost` |  |
| `raise_tol` | How far off his bearing the gun comes up: BODY_AIM_TOL, or close up his body's angle (RAISE_WIDTH half-widths: |
| `_low_h` | A low body's aim height (LOW_BODIES), else None (the guards keep their own rule). |
| `_aim_h` | The height on him to aim at: downed/kneeling motions the real body height (the operator 2026-10-28 |
| `_kcost` | _cost, K_RANGE_PREF less for a Majini standing where K says his class's shots do the most (learned, sure). |
| `_example` | The first EXAMPLES of a fault in the round, readable: round time, his position and heading, the detail, the |
| `_fault_tick` | Every tick: crowd_max, the seconds a Majini stands close behind him while he aims at another, the far |
| `_rear_backoff` | A Majini closing from behind while he aims ahead (the damage batch's 'grabbed from behind'): back up to |
| `_pursue` | The combo running down with nobody on his level in reach: run to the census's best (stuck: a detour). |
| `_escape_keys` | The left stick away from the crowd (each Majini pushing by 1/d^2), in his frame: back, sideways or between. |
| `_bonus_tick` | The round's statues: each new one seen, one gone taken; the clock's jumps (time_gained); bonuses_left. |
| `_bonus_stuck` | A stuck wiggle while running for a statue: the second one gives that statue up for BONUS_STUCK_BLOCK_S. |
| `_go_bonus` | Phase 1 (operator 16:52: "running from Checkpoint to Checkpoint, grabbing the time bonuses ... the only way to |
| `_watch_whips` | A turn of WHIP_DEG or more one way, then WHIP_BACK_DEG back within WHIP_S of its end: a whip. |
| `_rampage_gun` | Prefer the gun already in hand within each family; avoid swapping equivalent shotguns. |
| `_crowd_hit` | A live shot reaches a body; only a shotgun gets its full 3-D spread cone. |
| `_unload` | The trigger down off a confirmed body (UNLOAD above): ok (the gun up, no wall short of him) and the ray's error |
| `_rampage` | Anyone on his level within RAMPAGE_R: the gun up, the trigger down, the nearest inside held (above). |
| `_winding` | Current native wind-up evidence. Old damage correlations are not an attack flag. |
| `_wind_r` | How near a wind-up counts: WINDUP_R, or the reach his class has hurt him from (learned) when farther. |
| `_windup_tick` | The wind-ups within reach (_wind_r) on his level: counted as they start, resolved WINDUP_HIT_S later (an attack |
| `_dynamite_lit` | A Majini with a lit stick of dynamite: one of the carrier classes (DYNAMITE_CLASSES) in a lit-fuse motion |
| `_dynamite_tick` | The dynamite Majini (DYNAMITE): every lit carrier within DYNAMITE_R on his level is counted as it appears |
| `_lethal_tick` | A learned lethal attack under way that his shots do not stop (threat_memory.unstoppable: it has landed |
| `_quick_behind` | A Majini close behind him (the quick turn above): the turn's first step, or the trigger let go first. |
| `_sweep` | The turret sweep (SWEEP above): this tick's keys while it runs, None when the circle is not crowded. |
| `_keep_moving` | His dwell at one spot (DWELL_R): avg_dwell_s / max_dwell_s, and a relocation due past DWELL_MAX_S with |
| `_trail_tick` | His own trail: a point every TRAIL_EVERY_S (where he has been is open and reachable), the last TRAIL_KEPT. |
| `_reloc_goal` | Where to relocate: a point he knows is open - his own trail (TRAIL_AGE_S old or more, RELOC_GOAL_MIN away) |
| `_relocate` | A relocation (RELOCATE above): the run's keys while it lasts, None otherwise. |
| `_frozen_dot` | The live dot unchanged FROZEN_TICKS aimed ticks while the right stick was held or his heading changed. |
| `_aim_away` | The aim over AWAY_ERR off the nearest threat within THREAT_NEAR_R for AWAY_S: that one, at once. |
| `_track_approach` | Each Majini's closing speed on him (cm/s, + = coming), smoothed (APPROACH_EMA), from tick to tick. |
| `_threat_d` | How soon this Majini is on him: the distance less APPROACH_LEAD_S of his closing speed, x the turn to him. |
| `_threat_near` | A Majini on his level within THREAT_NEAR_R (THREAT_FIRST). |
| `_threat_pick` | Threat first: within THREAT_CAP_R, his level first, the lowest threat distance; the current one kept within |
| `_held_near` | One on his level within HOLD_R (a hold he would not break in time): hold first - the current target kept |
| `_core_error` |  |
| `_tier_pick` | The universal scorer's boss / dangerous band over these (combat.priority with combat_profile().tier): a boss |
| `_throw_core` | THROWS above: this tick's step of a grenade throw (combat.ThrowPolicy decides; the title's own path does it): |
| `_throw_abort` |  |
| `_frozen_core` | combat.NotInControl (FROZEN above): A every FROZEN_TAP_S while his shots do nothing and nothing moves him. |
| `_choose` | The Majini to fight. A target this close is not flipped to one behind him (the rear target's flip): one this |
| `_giveup_state` | Its state, made when missing: a bot the hot reload rebinds to this class never ran this version's __init__. |
| `_given_up` | Whether this Majini is given up now (TARGET_GIVEUP) - never during the fight for the operator's mark. |
| `_reach` | (reachable, how far): on his floor (LEVEL_DY) (True, the flat distance); on another floor the stage's mesh |
| `_noshot_note` | His shot at this Majini ended on geometry (the wall block): the give-up's evidence, an episode while the |
| `_giveup_tick` | TARGET_GIVEUP: each Majini in the pool with an open episode of wall evidence - closing on him renews the |
| `_giveup_pool` | The fight's pool: the Majini given up left out (TARGET_GIVEUP; back early once near on his floor, or on his |
| `_off_floor_go` | OFF_FLOOR_GO: whether this tick is the run to the target's floor by the mesh instead of a shot - everyone in |
| `_pitch_to` | The aim's pitch (absolute, radians) from his muzzle to this Majini's chest. |
| `_calm_sticks` | The right stick shaped (CALM): no reversal within CALM_REVERSE_S, the gun-down turn held to CALM_TURN_DEG_S |
| `_prompt_type` |  |
| `_door_kind` | What a prompt opens when it is a door's or a window's (DOOR_PROMPTS above): "door" / "window" (the owner's |
| `_majini_near` | The nearest living Majini (never a crow) on his level within r cm (and need(e), when given), else None. |
| `_door_threat` | The Majini a door's prompt waits for: one within DOOR_GRAB_R, or winding up within DOOR_HOLD_R, on his level |
| `_prompt_wanted` |  |
| `_prompt` | The game's shown prompt (snap prompt) answered by its type and mode (PROMPTS above); None when there is none |
| `_writer` |  |
| `_lock_aim` | AIM_LOCK: the aim moved by RAM - the heading by yaw_err, the camera pitch by pitch_err (radians: + = a larger |
| `_lock_errors` | (yaw, pitch) errors for the lock: from the laser's ray when it is long enough to steer by, else his heading |
| `wall_memory` | A blocked spot and the heading into it (the routing's own, or the governor's): no push there again. |
| `_wall_start` |  |
| `_door_spots` |  |
| `_door_labels` | The labels learned as doors (DOOR_FILE DOOR_LABELS_KEY: str(label) -> {through, taken, what, classes, |
| `_door_save` | The stage's spots and the learned labels written back to DOOR_FILE (other stages' rows kept); never raises. |
| `_door_find` | The remembered spot this one is (within 1 m, 1.5 m up or down; another label there is another spot). |
| `_door_get` |  |
| `_remember_door` | A door / ledge prompt's spot kept for the stage (DOOR_FILE), with its intel when given (seen once more); |
| `_door_note` | The remembered spot's intel: counters raised by inc, fields set; written back. -> its intel ({} if none). |
| `_door_learn` | A door label that took him through (past the object, or to another level): a door's wherever it shows. |
| `_door_log` | DOOR_LOG: one JSON line - a door / window / ledge seen, held, taken, through, an exploration step; the newest |
| `_prompt_at` | The prompt's object position (snap prompt target_pos: re5_switch.prompt_owner), when read near him. |
| `_door_seen` | A door / window / ledge prompt shows: remembered (the spot, its button) and logged - a flicker of the same |
| `_other_seen` | A prompt typed "other" (none of the known kinds): one log line per label, kind and owner class every 30 s, so |
| `_door_taken` | A door / ledge prompt pressed and gone: remembered taken, the way through watched (DOOR_WATCH_S) and, for a |
| `_door_watch_tick` | The door / ledge just taken (or walked through, an open one): through - past the object's own position along |
| `_door_safe` | fn(*args), or None on any error (stats door_error): the doors' memory and walks never cost a tick. |
| `_goal_in_force` | The operator's mark on the map is in force (MAP_GOALS): the door walks and the exploration wait for it. |
| `_door_through` | A door just opened: on through it, at a run the way he faced it, for DOOR_THROUGH_S (the fight first with a |
| `_pick_door` |  |
| `_door_walk` |  |
| `_explore` | DOOR_EXPLORE above: with nobody to fight, the doors / windows / ledges seen on this stage, one after another. |
| `_explore_pick` | The nearest remembered spot not tried within DOOR_RETRY_S (one tried within DOOR_FRESH_S costs DOOR_FRESH_CM |
| `_explore_miss` |  |
| `_explore_step` | The exploration's door, a phase at a time: there by the mesh at a run (go), onto its spot (near), the way he |
| `_wall_gov` |  |
| `_governor` | HEADING_GOV: his heading turned faster than HEADING_GOV_DEG_S since the last tick: no turn stick this tick |
| `_shot_tail` | No stick at all while the shot motion plays and SHOT_TAIL_S after it (operator 2026-10-28 04:0x: "they seem |
| `_count_sticks` | The right stick's motion this tick: a key newly down (stick_onsets: the pulses), and the yaw turned the other |
| `_plan` | K's dispatch plan for this Majini (class, distance, weapon), or None (no class, K off, or no learned field). |
| `_sure` |  |
| `_track_combo` | A combo that falls to 0 is a break; one whose window had run out at the last read is a lapse. |
| `_lapse_cause` |  |
| `_combo_left` | Seconds left in the running combo's window (None: no combo, or not read). |
| `_combo_urgent` |  |
| `_set_target` | The target from here on: a change is counted (target_switches), and a change back to the one he left within |
| `held` | The sticks pressed for STUCK_S while he neither turns nor moves: something holds him. |
| `grabbed` |  |
| `_score_hits` | Associate observed target HP losses with one recent pull, not every pull. |
| `_mesh_guard` | Steer before the wall (operator 2026-10-29: "the bot is just running at this wall"): he walks along his facing |
| `_room_map` | This round's stage map (ROOM_MAP), else None; stats room_map names its collision archive. |
| `_room_guard` | ROOM_MAP above: the way ahead of the left stick on the stage's collision; refused, the route's way or the |
| `_room_learn` | A step he just made (ROOM_LEARN_S / ROOM_LEARN_CM, one level) across a wall of the map: a door, a gate, a |
| `_room_sight_blocked` | ROOM_MAP: a wall of the stage's collision on the shot's line (his gun MUZZLE_H up, the Majini's chest). |
| `_stick_toward` | The left stick toward a bearing in his own frame (radians, + = his left): the nearest of eight. |
| `_never_stand` | NEVER_STAND above: the step along open floor when he has not moved for STAND_MAX_S. |
| `_turn` | The body (gun down): the right stick, pulsed inside TURN_FINE so it does not swing past him. |
| `_yaw` |  |
| `_pitch_settled` | The pitch stick, after the raise's own pitch settles (RAISE_SETTLE_S) and coasting once the measured rate |
| `_pitch` |  |
| `_pulse_n` | Inside FINE: a pulse every n ticks - 2 (a tick on, a tick off) without a window (close up), else from how the |
| `_laser_misses_all` | True only when a measured laser ray exists and no body lies under it (endpoint or segment): a new pull |
| `_trigger` | ZR held while on him: the game repeats a held trigger at the gun's pace (live: 2.7 shots/s held or tapped |
| `_fp_steer` | FIRE_PATTERN: the laser on him with a pattern gun - the stick toward the scatter's next point on his body |
| `_round_start` | The first tick alive of a round: the engine's marker, once (a marker changed again on a replay made the |
| `_new_round` | A round's own state and gauges, at the first round's start and at each replay's (dead/retry: the engine's |
| `_stage_now` | The stage this round is played on: the driver's identity (stats ss_stage: the navigation signature, else the |
| `_stage_learning` | What the bot learned for this stage, in force: the tuning (its constants and avoid spots), the learned |
| `_stage_sync` | The round's stage learned after its first tick (the navigation signature reads a moment later, or corrects a |
| `_start_face_open` | Once per round: face the most open compass direction before moving. |
| `_gun_down` |  |
| `_aim_core` |  |
| `_aim_tick` | The census to the aim book every tick: the open shots resolved, learned and saved. |
| `_aim_family` |  |
| `_aim_book_point` | The point re5_switch_aim.apply steers the laser onto: his chest (as the bot chose it) moved by the book's |
| `_aim_book_contact` | AIM_BOOK_GATE: whether the laser's line crosses him inside the book's tolerance ellipse round its point (None: |
| `_aim_book_shot` | The pull's record for the aim book: the target as the census has him now, the plan the aim went for, the |
| `_flashed_lately` | A flash from anywhere - the ring, the operator's button, his own - went off within FLASH_MIN_GAP_S: its |
| `_flash_point` | Where a bot flash goes off: flash_window.place round him (None: nobody near - no flash wanted). |
| `_flash_go` | The native flash: on the crowd at point (Controller.flash_at - also on a controller made before the method |
| `_flash_self_tick` | His own motion in the FLASH_STUN_S after a confirmed flash (any source), by where it went off: a motion |
| `_flash_self_close` |  |
| `_heading_keys` | The left stick toward heading h in his frame (_escape_keys' table). |
| `_flash_window` | FLASH_WINDOW: the seconds after a confirmed flash, used (flash_window.Window.plan): the mine, the grenade, the |
| `_specials` | The special-move layer, made on first use. A bot built before the layer existed, or one holding a layer of a |
| `_special` | re5_specials.Specials.<what>(self, *args); None on any error (the specials never stop the bot). |
| `_heal` | The heal (HEAL_* above): its next press, or None (no heal now). |
| `_retreat_heading` | The critical retreat's heading (operator 2026-11-10, coaching note 11, 'Flawed handling': 26% health, no heal, |
| `_loaded_gun` |  |
| `_gun_back` | A grenade or the bomb in hand (THROWN) with nothing else using it: the gun's D-pad slot, a tap every |
| `_rearm` | The gun back in his hands after a heal: the one he held (its D-pad slot), else the first gun on one. |
| `_escape` | A ring (RING_*): run out through the widest gap between their bearings; None when not ringed. |
| `tick` |  |
| `_respond` | core.respond on this tick's decision: the native flash, the mine asked for, or the fight on the threats. |
| `_respond_settle` |  |
| `_critical_flash` | CRIT_FLASH above: one native flash when he is held in a crowd, low in a crowd, or in his own bomb's blast with |
| `_native_flash` | Ask the native controller for a flash at his position now (asynchronous, like the crowd flash; one at a |
| `_mine_flash` | MINE_FLASH above: the flash the moment a bomb is down, and the one that opens the way for an overdue bomb. |
| `_grenade_crowd` | A crowded, verified attack threat can justify one flash during fire. |
| `_native_equipment` | Translate a quick-slot weapon intent into a native attachment request. |
| `_tick` |  |
| `_mine_action` | Only a physical mine hazard can interrupt the combat/navigation plan. |
| `observe_reactions` | Also called before prompt-only ticks, so QTE handling never hides a request. |
| `_mine_route` | The mine controller's run out (its retreat, its guard) picks a heading by the widest gap among the Majini; |
| `_goals` |  |
| `receive_map_goal` | The tactical publisher's hand-over, on the engine's thread: the operator's click. |
| `_goal_log` | MAP_GOAL_LOG: one JSON line (at most one a second unless forced); never raises. |
| `map_goal_plan` | For the tactical map (tactical._take_map_goals, beside what it already takes from this bot): the round's |
| `_floor_y` | The floor's height under a spot on the map (the mesh's floor there nearest his own height), else his. |
| `_operator_goal` | MAP_GOALS: this tick's action for the operator's mark on the map, None when there is none (or it waits). |
| `_mesh_no_exit` | The mesh's last plan failed only because of the crossings refused on this stage (_mesh_waypoint's |
| `_goal_no_exit` | The operator's mark closes as unavailable with the mesh's reason (the loop the operator watched in the bus |
| `_gait` | The left stick for a walk to a Majini `dist` away: a run beyond RUN_R. |
| `_walled_off` | CLOSE_IN: whether the mesh says there is no open floor on the line between him and this Majini. |
| `_mesh_avoid` | The crossings he could not take on this stage's mesh (their portals, as (x, y, z)) for route(avoid=): |
| `_mesh_refuse` | This crossing is left out of the stage's routes for MESH_AVOID_S; the route is planned again next tick. |
| `_mesh_open` | Whether the straight way from `pos` to (x, z) is open floor on the mesh, the far end taken at the floor's own |
| `_route_wall` | The wall governor met a wall while the route steered (WALL_ROUTE_YIELD): the push at the route's waypoint |
| `_mesh_waypoint` | The next point (x, z) of the nav mesh's route from him to `goal` (x, y, z), or None when the mesh is not |
| `_approach` | The turn keys toward `goal` (a position): along the learned map's route when it has one (NAV_APPROACH |
| `_locate` | The run to the census's best enemy when none is on his floor (LOCATE above). stats locates (targets taken), |
| `_operator_command` | The operator's instant commands (gbox.mercs.directives, the PS3 bot's set): one-shots act on the tick they |
| `_mine_now` |  |
| `_emergency_flashbang_arm` | Legacy directives must not equip or throw a grenade as an instant flash. |
| `_flashbang_throw` | The emergency flashbang's actual throw, ticked every frame once armed: equip the flash grenade via its |
| `_repositioning` | re5_switch_aim.keep_active's bounded step is under way (the gun is down for it until its end) - unless this |
| `_chosen_item` | The operator's weapon: the native three-minute primary while usable, else select_weapon's preference. |
| `_corridor` | A floor corridor to this Majini on the stage's mesh (cached 0.5 s each): True / False, None when unknown or |
| `_wm_count` |  |
| `_wm_press` | A tap pattern's press tick: a trigger edge (a shot: the pull's hit window opens). |
| `_wm_release` | A tap pattern's release tick (not a slip: the next press is the next shot). |
| `_mastery` | WEAPON_MASTERY: the weapon in hand's own controller when it has no laser fight (re5_weapons.MASTERY: the |
| `_wm_tick` | Per family, while its weapon is in hand: shots (trigger edges), hits (target health lost near a pull, the |
| `_goal_decide` | The fight for the operator's mark (_operator_goal): _decide on its pool as it is - the marked one never given |
| `_decide` | _decide_inner, and the gate that held the trigger is published on the way out. |
| `_decide_inner` |  |
| `_cam_down` | The aim's own pitch (P_AIM_PITCH, + = down) more than CAM_DOWN_MAX below his chest's elevation while aimed at a |
| `_cam_up` | The aim's own pitch (P_AIM_PITCH) more than CAM_UP_MAX up while aimed at a Majini on his level within |
| `_sky_guard` | The laser more than SKY_MARGIN above the target's elevation: the pitch-up stick out, the pitch-down in. |
| `_track_pitch_rate` | The aim's pitch rate from this ray and the last (None across a dot that jumped, or a short ray). |
| `_note_ray_pitch` | The aim's pitch from each live ray; the first after a raise compared with the last before it. |
| `_pitch_up` | An aimed tick with the laser over PITCH_UP_LOG above level (a ray PITCH_UP_RAY or longer): counted, with |
| `_near_aim` | The Majini nearest the aim line (by the ray's yaw to his chest), within SWITCH_ERR and in reach; None. |
| `_pull_start` | Record a trigger edge and measured aim evidence, not an emitted bullet. |
| `_behind` | What the dot met behind him on a ray-through pull: "wall", "floor" or "none" (nothing in range). |
| `_pull_end` |  |
| `_aim_report` |  |
| `_resolve_pulls` | Report target HP observations and distinguish body contact from a ray miss. |
| `_k_shot` | The pull for the enemy knowledge database: his class, the distance, the weapon, the dot's point on him (a world |
| `_k_tick` | Each tick: a health fall -> record_damage (the Majini holding him, else the nearest, and how); the live |
| `_hazard_hit` | Health lost with no Majini within HAZARD_FREE_R: the place hurt him (fire, a furnace, a fall - operator |
| `_front_foe` | Another living Majini in front of him (inside BODY_AIM_TOL) within reach: one he could shoot without turning. |
| `_look_tick` | After each decision: its time in the budget (t_<doing>), the turning with a foe in front, the pulls' outcomes, |
| `_fight` | The PS3 combat core's decision on the Switch pad (re5_switch_brain.Fighter), with the Switch's trigger time |
| `prompt_ok` |  |
| `save` |  |


**class RE5Switch** (12 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `snapshot` |  |
| `doctrine_view` | The universal doctrine's view of the round (gbox.mercs.core.doctrine.view, this title's units and wind-ups) |
| `screen` |  |
| `_identity` | The round's stage and character in its stats when this visit's selects did not name them: a fragment that |
| `_cycle_started` | A round is up on what the selects confirmed: the stage cycle counts it; the round's stats name it. |
| `_mods` | The session's live mods (re5_switch_mods: fire_rate's time scale during shots, the no-ammo flags' |
| `result_ready` | The round's results tally is over: its score and kills unchanged for a second after at least two on the |
| `menu_handoff` | The engine hands a finished round back to the menus only when RAM names a native screen. That means the |
| `brain` |  |
| `prompt_keys` |  |
| `progress` |  |

### `titles/re4_switch.py`


**class ClockFinder** (3 methods) - The round clock, found and then followed (one per boot, kept on m.re4_clock). observe() reads the bss every call

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `observe` |  |
| `_rows` |  |


**class UnitCensus** (4 methods) - The units of the configured classes (PLAYER_CLASS, ENEMY_CLASSES), found by their vtable word in the heap and

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `classes` |  |
| `refresh` |  |
| `read` | (player unit or None, [enemy units]), one read each, deduplicated by id + health + type (the arena shows |


**class Pace** (4 methods) - When the walk's next press may go in (see MOVE_GAP_S): observe() every read, ready() before step(), pressed()

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `observe` |  |
| `ready` |  |
| `pressed` |  |


**class RE4Switch** (6 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `snapshot` |  |
| `screen` |  |
| `brain` |  |
| `prompt_keys` |  |
| `progress` |  |


**class Bot** (97 methods) - One decision per tick from the snapshot (re5_switch.Bot's shape: tick(snap) -> {"hold": keys, "tap": key}).

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `_flat` |  |
| `_live` | [(distance, bearing error, enemy)] of the living Ganados with a position. |
| `_close_threats` | [(distance, bearing error, enemy)] of the living Ganados within FIRE_FIRST_MM: the ones on him now. |
| `_shootable` | A Ganado on him now (within FIRE_FIRST_MM) with a clear shot line from where he stands: the fight can answer |
| `_fire_first` | FIRE_FIRST: a Ganado on him now with a clear line the fight can answer from where he stands - the gun, not a |
| `_nearest` | The nearest living Ganado (kept for the first cut's callers). |
| `_count_kills` | Kills: the game's own counter when it is read (MercSysWk + MW_KILL), else a census unit whose health fell to |
| `combo_owed` | Seconds since the last kill when the next one is owed (KILL_PACE_S), None while the combo is fresh. |
| `_line_of_sight_ok` | No wall shots: a clear ray from Leon to the target. Uses the stage's obstacle / navmesh data when it is |
| `_near_own_hazard` | Keep clear of mine darts using their native power-dependent blast reach. |
| `_may_fire` | The operator's fire-gates, all of which must pass before a shot: controls confirmed, in range, clear line |
| `_mine_ring_done` | Successful sweeps are paced start-to-start; failed sweeps get a short combat/retry interval. |
| `_mine_ring_step` | The mine-thrower ring (operator 2026-11-12): ten darts at 36 deg round him, every 1.5 min or to stop a boss. |
| `_boss_pick` | (distance, error, enemy) of the boss to neutralize, or None (operator 2026-11-12: "neutralize the boss until |
| `_boss_scene` | Publish the boss picture the ring's own defensive rule reads (grenade_ring.decide, the nitrous question). |
| `_boss_release` | The lock ends: killed (its health reached zero), lost (out of the census BOSS_LOST_S), or the round reset. |
| `_choose` | (distance, error, enemy) to fight, or None: the quickest kill once the combo is owed, the one nearest the |
| `_keep_pack` | PACK_KEEP: the pick of the scorer (a grudge) or of the doctrine (the combo's quickest kill) replaces the |
| `_fp` |  |
| `_fp_aim` | (dist, err, enemy, the yaw offset) for this tick's shot: the hop to a neighbour on the gun's line after |
| `_fp_fired` | A tap went out: the shot's point in the stats (scattered / centred / unearned), the scatter's next point. |
| `_tap` | The shot: ZR tapped with the aim held (the engine sends a tap as down + up before the hold, so the shot fires |
| `_aim_core` |  |
| `_aim_tick` |  |
| `_gun_origin` | The line's origin: the laser's own (RAM) while it is up, else his position GUN_H_MM up (mm). |
| `_aim_plan` |  |
| `_aim_shot` | The tap's record (aim_book.Ledger): the plan meant, the laser's line when it is up, else `actual` angles. |
| `_lock_live` | Whether the aim lock writes the requests (re4_switch_mods' count, stats mods_aim_writes, rose lately). |
| `_ram_aim` | AIM_RAM: the steady aim (see AIM_PITCH_GAIN). None: the old path aims and fires this tick (no aim read, the |
| `_bow_in_hand` | The gun in hand is the bow (the fast-fire class family): arrows discharge on the bow's own fast path. |
| `_turn` |  |
| `_aim_turn` |  |
| `_aim_stick` |  |
| `_learn_turn` | The turn sign's live check (TURN_LEARN): does the error on the same Ganado shrink between turn ticks? |
| `_command` |  |
| `_operator_command` | (command, action now or None): the command in force (the operator's, else the doctrine's), and for the |
| `_roaming` | The operator's new way (an escape run of kind "cmd") as this tick's action, said; None when there is none. |
| `tick` |  |
| `_respond` | core.respond (RESPOND above) on this tick's decision: the fight on the threats when it answered nothing. |
| `_fight` |  |
| `_escape_goal` | A point ESCAPE_MM away from the Ganados near him along open floor (see ESCAPE_*), or None when every line |
| `_ladder_escape_goal` | The landing of the nearest ladder DOWN he can reach before the Ganados near him, or None (no mesh, no |
| `_run_to` | The run to an escape goal: the quick turn when it lies behind him, else _approach (the mesh walker) with B. |
| `_escape` | An escape of this kind under way (its goal, until when), or a new one; None when walled in or arrived. |
| `_escaping` | The run of this kind still under way (before its until, not arrived), else None. |
| `_hit_backoff` | Hit: break contact for HIT_BACKOFF_S instead of trading another blow (the operator's choice, 2026-11-12). |
| `_publish_doing` | Publish this tick's doing/why, and count it (stats "t_<doing>"). |
| `_heal` | Hurt: the first aid spray into his hand, used, and the gun back - all through HAND_REQUEST, a flag write the |
| `_heavy_keep` | HEAVY_*: a heavy within HEAVY_KEEP_MM - away along open floor (_escape), HEAVY_RUN_S at a time. |
| `_low_life` | LOW_LIFE: away from the Ganados along open floor (_escape), LOW_LIFE_RUN_S at a time. |
| `_melee` | The melee follow-up (MELEE_*): in to a Ganado just hit, then Y at the prompt; None when there is none. |
| `_not_in_control` | The round's screen when the game says he is not in control (game_state): the intro card and a hold are paged |
| `_frozen` | A tap of FROZEN_KEY while he is not in control (FROZEN_*), else None: through the shared detector |
| `_frozen_legacy` | _frozen before the universal core (UNIVERSAL_CORE off, or the game's own state read). |
| `_sight_blocked` | The sight gate held this shot: logged (SIGHT_LOG), and past SIGHT_HOLD_S a FLANK_S flank begins. |
| `_sight_given_up` | FLANK_GIVE_UP_S: this target has had a flank budget's worth of walking - the sight gate no longer blocks it. |
| `_flank_step` | One tick of a flank (no clear shot at e). FLANK_LOS: over as soon as the shot is open from where he stands |
| `_flank_goal` | The nearest point along the mesh's route from him to e (FLANK_SAMPLE_MM apart, FLANK_LOOK_MM at most, to |
| `_log_block` | One sight block: the stats' last one and a line in SIGHT_LOG (the wall, where the shot met it). |
| `_approach` | (stick keys, how) toward goal: the mesh walker when one is attached (Bot.walker.approach(goal) -> keys, the |
| `_remember` | Keep where the Ganados were seen (the freshest SIGHT_MEMORY_N, for SIGHT_MEMORY_S), so a round is not lost to |
| `_locate` | Nobody in range: the nearest Ganado by the map, walked to (run past RUN_CM); nobody known: the sweep. |
| `_gun_down_telemetry` | The raise / lower count the operator sees (2026-11-10: the bot "raising their weapon over and over", jarring |
| `_pose_tick` | His position or facing changed since the last tick (FROZEN_MM / FROZEN_RAD): he is in control. |
| `_camera_collapsed` | CAMERA_COLLAPSE above: this tick's camera-to-player distance through combat.CameraCollapse; True on the tick |
| `_room_map` | This snapshot's room map (ROOM_MAP), else None; stats room_map names the room in use. |
| `_walk_test` | The test for a walk line the bot picks itself, (a, b) mm -> bool, or None with no geometry at all: the |
| `_route_leg` | ROOM_LEGS: this tick's action is the mesh walker's own route leg (re4_walk.Walker.leg: the route's steer, |
| `_room_ahead` | ROOM_MAP's probe on a walking tick: None (the way ahead is open, or a crossing the walker is taking), the |
| `_room_reach` | The probe's length (mm): ROOM_PROBE_MM of the room's own scale (ROOM_PROBE_SHARE of its smaller side, within |
| `_unwall_reach` | The step along a wall (mm), scaled to the room like the probe (ROOM_UNWALL_SHARE of its smaller side, within |
| `_same_heading` |  |
| `_unwall_tries` | The headings off his facing (degrees) `combat.WallPress.away` tries, this wall's tangents first (ROOM_TANGENTS: |
| `_room_wall_beside` | The wall within his body's height beside him (pressed against it), or None: the room map's own walls. |
| `_on_tangent` | The goal `walls.away` chose lies along heading h from where he stands (2 deg): the tangent's own step. |
| `_shot_open` | A living Ganado in fire range with a clear shot line from where he stands: the fight's own hunt works again, |
| `_tangent_still` | One more step of the same tangent (the room's own scaled step), when it is walkable: un["goal"] moved on. |
| `_wall_core` | WALL_* above: the action's walk checked against the walls he has pressed, and pressing a new one; with |
| `_unwall_keys` | Toward an open-floor goal: the quick turn when it lies behind him, a turn on the spot while it is more than |
| `_never_stand` | The doctrine's floor: a tick that neither fires nor moves him for STAND_MAX_S becomes a STAND_STEP_S step. |
| `_never_stand_core` | The never-stand rule by the shared discipline (combat.stand_engaged / combat.open_step): not standing while |
| `_step_keys` | The step's keys this tick: toward its open-floor goal (a turn on the spot while it lies more than |
| `new_round` | Reset observations at a confirmed round start; keep the persisted lessons and adjustments. |
| `record_death` | A native/visual terminal witness also records deaths whose final HP sample was missed. |
| `_uc` | The core's pieces, made on first use (a bot the hot reload rebinds to this class never ran this version's |
| `_profile` | This tick's profile (made at the tick's start by _core_tick), else a fresh one. |
| `_core_error` |  |
| `_core_tick` | Every tick: the profile (the live constants), and who hurt him (the living Ganados, his life's falls). |
| `_threat_pick` | (distance, error, enemy) of the scorer's first tiers among `near` (combat.Threats.priority: a wind-up within |
| `_lethal_out` | A learned attack that lands through his shots, under way within its reach (combat.Threats.step_out): away |
| `_hand_ask` | A new HAND_REQUEST (an item id to hold, or None: the gun back) for re4_switch_mods.maintain; its seq. |
| `_fleeing` | An escape run under way (low life, a heavy, a swarm, a learned attack). |
| `_throw_core` | THROWS above: this tick's step of a throw (combat.ThrowPolicy decides): hand (the swap asked, HAND_STATE's |
| `_idle_core` | combat.IdleGuard on this tick's action: the gun up IDLE_AIM_S at the Ganado in range without a shot -> |
| `prompt_ok` |  |
| `save` |  |

### `titles/re5_switch_native.py`

- class `ControllerBusy` - The mailbox lock was refused before any native call was submitted.

**class Controller** (30 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `proximity_mines` |  |
| `proximity_mine_status` |  |
| `_ammo_backend` |  |
| `__init__` |  |
| `_fail` | Mark the controller uncertain, remembering what failed so the status refusal names it. |
| `check_build` |  |
| `check` |  |
| `pair` | The spawn/explode pair this emulator holds, detected once; raises when it is unrecognised. |
| `_require_kind` | Refuse a non-flash kind on an emulator whose pair is still the old flash-only one, before any native call. |
| `_spawn` | Spawn one native grenade unit of `kind` through the pair this emulator holds -> (unit, born). |
| `_detonate` | The explosion transition: the old four arguments, or the class pair's vtable/item/update. |
| `ready` |  |
| `validate_heap` |  |
| `attach` |  |
| `call` |  |
| `recover_completed_call` |  |
| `detach_completed` |  |
| `projectile` |  |
| `prepare` | Install/allocate dispatch before advertising the viewer capability. |
| `flash` |  |
| `flash_at` | One flash ON THE CROWD (re5_switch.FLASH_PLACE): the verified flash with the unit's live transform and home |
| `ring_capable` |  |
| `grenade_kinds` | The ring's kinds as this build can honestly fire them (gbox.mercs.grenade_status reads this). |
| `launcher_kinds` |  |
| `_ring_one` | One grenade of `kind` spawned, relocated to (x, y, z), and detonated. |
| `grenade_ring` | Spawn `count` grenades in a ring around the player and detonate them in a quick ripple. |
| `grenade_scatter` | A scatter barrage: `count` grenades set off at points of a cone from him toward the threats. |
| `current_weapon` |  |
| `weapon_choices` |  |
| `equip_primary` |  |

### `titles/re4_switch_native.py`


**class Controller** (40 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `weapon_choices` |  |
| `current_weapon` |  |
| `equipment_quiescent` |  |
| `equip_primary` |  |
| `ammo_status` |  |
| `set_infinite_ammo` |  |
| `__init__` |  |
| `check_build` |  |
| `check` | The identity guard every write passes (the base class's check reads RE6's `sp`/generation offsets, which |
| `write` | A guest write. Refuses `main`'s `.text`/`.rodata`: only `install()` may touch the cave (and only there). |
| `install` | Install bytes only inside the vetted zero cave (the base class's memfd path still refuses nonzero bytes). |
| `bss_watch_probe` | The five E3 candidate pages as `off=hex16` (read-only): the status reason carries them to the PiP/API. |
| `prepare` | The status path: no capability is advertised before the private page is proven (E3). |
| `ready` | (player, generation) - the pair `interventions`'s worker and status epoch unpack. |
| `clone_address` |  |
| `attached` |  |
| `ensure_attached` | Attach the harness on demand (RE5/RE6 attach inside every native op; RE4's ring/flash refused instead). |
| `attach` | Build the clone, install dispatcher + clone into the cave, and publish the clone - one vtable store. |
| `detach` | Put the original vtable pointer back (the clone in the cave is only ever read). |
| `call` | One native call on the game thread: publish the request, wait for done, return x0. Never replays. |
| `ticks` | The dispatcher's entry counter (E6's live proof that the cloned slot fires every frame). |
| `spray_item` | Find a real player-owned first-aid slot; never synthesize an inventory record. |
| `keep_spray` |  |
| `first_aid_now` | One acknowledged call to the game's item-use function; the wrapper validates again on the game thread. |
| `scratch` | The fake blast object, in the same proven page as the mailbox (the mailbox uses only its first 0x80). |
| `player_position` |  |
| `_retire` | Put the mailbox back to idle so a request nobody is waiting for cannot run later (best effort). |
| `player_life` | The player's own life field (module+`PLAYER_LIFE`, u16), or None when it reads outside `LIFE_SANE`. |
| `_blast_at` | One blast through the mailbox: a zeroed object at the point, the game's own function, one call. |
| `flash_at` | Start the game's flash blast on the point (x, y, z - RE4's millimetres) through the harness. |
| `grenade_kinds` | The ring's kinds as THIS build can honestly fire them (gbox.mercs.grenade_status reads this). |
| `launcher_kinds` |  |
| `_mine_rows` |  |
| `_detonate_mine_rows` |  |
| `detonate_mines` |  |
| `maintain_mines` |  |
| `grenade_ring` | N blasts in a ring round him (checkpoint G1/G2): flash 4000 mm or more, hand grenade 7000 mm or more. |
| `grenade_scatter` | A barrage of native blasts in a cone toward the threats (checkpoint G4), same contract as RE5/RE6. |
| `flash` | The intervention's `flash_now` op: the crowd point through this controller's own adapter. |
| `selftest` | E6's no-op: attach, then one mailbox call to the dispatcher's own `ret` - no game code runs. |


**class _Reader** (3 methods) - The adapter as `re4_switch.snapshot` wants it (`m.rd` and attribute caching), for a worker that has no driver.

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `rd` |  |
| `__getattr__` |  |

### `titles/re5_qte.py`

- class `Reject` - 

**class ProgressHook** (4 methods) - One bounded write per observed selection, scoped to one process/controller.

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `_result` |  |
| `_observe` |  |
| `step` |  |

### `titles/re5_mines.py`

- class `GroundMines` - 

**class Controller** (10 methods) - 

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `bind_learning` |  |
| `learn` |  |
| `observe_blasts` |  |
| `reset_round` | Discard pad/inventory/actor ownership from a completed player scope. |
| `event` |  |
| `return_gun` |  |
| `clear_escape` | Completion requires measured separation, never a movement button alone. |
| `deferred_gun` | A spacing/route refusal must not leave an optional mine equipped. |
| `tick` |  |

### `titles/re4_switch_mines.py`


**class Fuses** (3 methods) - Three seconds from first observed spawn; expose polling lateness honestly.

| Method | Purpose (first doc line) |
|---|---|
| `__init__` |  |
| `observe` |  |
| `claim` |  |

### `grenade_status.py`

- class `Kind` - 

**class Title** (1 methods) - One Mercenaries title's ring support: the kinds it is built and verified for, or why it has none.

| Method | Purpose (first doc line) |
|---|---|
| `ring` |  |


### Module-level functions (core RE6 modules)


**titles/re6_switch.py** (81 module-level functions)

| Function | Purpose (first doc line) |
|---|---|
| `scatter_kinds` | The kinds a random barrage can draw: the native controller's verified set (the flash today; A/C extend it). |
| `request` | The next selects' character and stage (MercMode's DJ queue): a character by name or select id, a stage index |
| `_coverage_path` |  |
| `coverage` | {"stages": {name: rounds}, "characters": {name: rounds}} (read once, then kept). |
| `_count_round` |  |
| `stage_target` | The stage select's target: the queued stage when it can start, else this visit's random draw among the stages |
| `wanted_character` | The queued character, else this visit's random draw among the select's listed ids (PLAYER_ID without them). |
| `costume_target` | (the costume the select shows for select id cid, this visit's random target among the ones it lists). |
| `costume_code` | (character, costume index) of a costume code (the unlock mask's bit): 4 a character for the first seven, then |
| `player_target` | The character select's cursor index for the wanted character (a queued one, else PLAYER_ID): its place in the |
| `continue_target` | The "Continue?" answer the pace wants: YES (the replay) unless REPLAY_ON_DEATH is off. |
| `_rows` | The guest's readable rows [(start, end, perms)] in guest addresses (the Citron / Eden adapter's HostMemory arena; |
| `module_base` | main's load address this boot: cached on m and checked again (one 64-byte read) on every call. |
| `u64` |  |
| `_i32` |  |
| `ptr_ok` |  |
| `enemy_class` | His RAM class (uEm5200 / uEm5210 zombies, uEm1000 J'avo ...: the live map's legend, gbox/mercs/enemy_kinds.py), |
| `class_name` | An MtObject's class from its vtable's getDTI (slot 5: adrp x0 / add x0 / ret). |
| `wrap` |  |
| `heading_of` |  |
| `heading` |  |
| `ui_units` | The interface units up now: class name -> the first unit of that class (the interface lines only, by vtable). |
| `inventory_state` | (the equipped slot's index, the item id in hand, the remote bomb): +0x5064 names the equipped slot by its +0x9 |
| `inventory_items` | The grenades on his item wheel: {type: (wheel index +0x9, count +0xE)} for the live slots holding one. |
| `inventory_guns` | His weapons now: {type: wheel index} for the live weapon slots (+0x9 index below WEAPON_INDEXES). |
| `inventory_ammo` | Rounds in the live item whose wheel index matches the equipped weapon, never another gun's count. |
| `inventory_gun_ammo` | Verified loaded/empty counts by weapon wheel index; ambiguous identities are omitted. |
| `unit_action` | A unit's current action's class (+0x13F0: the player's cPlAction_pl_act_..., a set piece's cSm...Act_...). |
| `equipped_id` | The item id of the gun in hand (inventory_state). |
| `mercs_target` | uIdStartUp30's entry the menus walk takes: SPLIT for a split-screen session, SOLO otherwise. |
| `player_index` | The player a snapshot of m is for (0 = Player 1, the solo default); None for a value that names no slot. |
| `player_pointer` | Player `index` from sPlayer's slots, only when its own index byte agrees (never a neighbouring slot's). |
| `own_camera` | Player p's own camera (its +0x3A28, owned when the camera's +0xB0 points back at p): the reading camera() makes. |
| `own_laser` | Player p's own laser sight (its +0x54E8, owned when the laser's +0x590 holds p's index): the reading laser() |
| `navmesh` | The stage's NavMesh (cached while its resource stays; None when none is loaded or it does not decode). |
| `_decode_nav` |  |
| `prompts` | The game's shown button prompts for this player: [{type, button, pad, key, ab}] (key: the Switch button to press, |
| `game_man` |  |
| `snapshot` | The round from RAM: the player, the live enemies and the Mercenaries counters (None where a pointer is not). |
| `_speed_for` | The title's learned menu cadence, bound to this adapter's data dir on first use; NAV_CURSOR stays one dict so |
| `screen` | The menus interface with the learned cadence folded in (gbox.mercs.menu_speed): the Navigator's NAV_CURSOR is |
| `menu_pace_line` | Each screen's learned waits on one line (gbox.mercs_bot.menu_clock: the run's menu_pace stat). |
| `menu_status` | The sidebar's menus line (gbox.mercs.bot_logic.status): the walks gbox.mercs_bot timed for this title, round to |
| `begin_run` | gbox.mercs_bot.play's start of a menus walk: the learner (one per process, kept across sessions) times this |
| `_screen` | The RAM screen, with a read that loses its page reported as "unknown" instead of ending the run. |
| `_screen_impl` | The deployment's menus interface (gbox/mercs_bot.py): where RE6 is, from RAM. A dialog first (its id names the |
| `native_game_over` | Fresh active-list UI evidence tied to this snapshot's player lifecycle. |
| `continue_prompt` | YOU ARE DEAD - CONTINUE?: where "dead", its cursor once the YES / NO menu takes input (None before: no key), |
| `step` | One key toward the next round: a cursor walks to its target first (the D-pad), then A confirms. The title takes |
| `fast_batch` | The whole key batch for the current menu screen: every cursor move at once, then the confirm. |
| `_cursor_batch` |  |
| `fast_start` | Drive the native menus in bursts until the round starts, confirming only segment boundaries. |
| `wandered` | The title held without its main-menu byte: A would start the Prologue, so the run stops and says why. |
| `pressed` |  |
| `warm_probe` | gbox.mercs.warm_boot's boot observer for RE6 Switch (title_probe): a stable native menu where the warm pool may |
| `_find_unit` | A unit by class on sUnit's lines: found once (each vtable named only once), checked by its vtable afterwards, |
| `owned_throwables` | Read owned grenade/bomb identities across every native update line. |
| `placed_bomb` | Where the placed remote bomb lies (x, y, z), or None: its unit found on sUnit's lines (looked for again at most |
| `forget` | Drop a cached unit ("camera", "laser") for every main base: the next read looks for it again. |
| `camera` | The game camera: {pos, target, yaw, pitch} from uCamera's own properties (mCameraPos +0x60, mTargetPos +0x80, |
| `laser` | The laser sight's dot (uLaserSight +0x60: where the aim's ray lands), the muzzle (+0x440) and how far up the |
| `aim_cam` | P1's player camera state: {addr (the uCameraQFPS inside his own uCameraCtrl), pitch (-1..1), yaw}; None when the |
| `aim_writer` | The aim lock's writer for this session: write(addr, pitch, yaw) -> True once both floats are written and read |
| `aim_point` | Where to aim at e: his chest on (or near) his floor - his class's own (body(e)) with UNIVERSAL_CORE; one off it |
| `near_line` | Whether the line origin -> toward passes within r of pt, ahead of origin and within reach. |
| `ray_error` | (yaw, pitch) radians that turn the ray origin -> toward onto target (+ yaw = a larger heading, + pitch = up). |
| `body_classes` | The classes with a body of their own: BODY_CLASSES, and MEASURED with MEASURED_BODIES. |
| `body` | His class's body for the aim and the hit test (body_classes() through combat.BodyTable), else a standing |
| `dot_on` | Where the laser dot sits on a zombie standing at foot: "head", "body", else None; prof: his class's body |
| `through` | Whether the ray origin -> dot runs to him: it reaches his chest's distance (less FIRE_SLACK) and passes inside |
| `line_hits` | Whether the line from origin through toward, out to reach, passes inside a zombie standing at foot (his head or |
| `segment_hits` | The measured laser ends on a body or intersects it before its endpoint; never extend a wall hit (prof: his |
| `bonuses` | The bonuses still waiting to be broken: [{ptr, pos, kind ("time" / "combo")}]; None when a read failed. |
| `near_ray` | Whether the ray origin -> dot reaches point (it does not end more than slack short of it) and passes within |
| `windup` | 'melee' / 'ranged' for one winding up an attack on him (by its action), else None. |
| `aim_family` | The aim book's family of the gun in his hand: every gun has one (the automatics too). |
| `fire_family` | The fire pattern's family of the gun in his hand (the player row's weapon_id), None for the automatics. |
| `attack_named` | His action names an attack under way, melee or ranged (not a hit reaction): the attack flag threat memory |
| `windup_named` | His action names a melee wind-up (WINDUP_KEYS, any distance: the core puts the reach on it). |
| `combat_profile` | RE6 Switch's calibration of the universal fight, from the live constants (a knob turned is in the next one). |
| `prompt_skipped` | A prompt the bot must not answer. |


**titles/re6_switch_native.py** (11 module-level functions)

| Function | Purpose (first doc line) |
|---|---|
| `flash_place_min_cm` | The nearest a flash round may be placed from him: the title's own floor (aim-book) or 400 cm (checkpoint 0.3). |
| `ring_defaults` |  |
| `verify_build` | Check a decompressed `main` image (hactool `--uncompressed`, its 0x100 header still in front) against the |
| `process_identity` |  |
| `backing_region` |  |
| `grenade_scatter_now` | The scatter barrage on the session's one native controller (the bot's rule, the PiP's grenade_scatter). Never |
| `bomb_drop_now` | The bot's / the PiP's instant remote-bomb drop on the session's one native controller. Never raises: a refusal |
| `bomb_ring_now` | The bot's / the PiP's ring of instant remote bombs on the session's one native controller (drop_bomb_ring). |
| `bomb_detonate_now` | Every remote bomb of his lying placed set off through the detonator's own flag (re6_switch_mods.detonate): |
| `flash_now` | One call = one native effect. Callers own durable request deduplication. |
| `grenade_ring_now` |  |


**re6_remote_control.py** (5 module-level functions)

| Function | Purpose (first doc line) |
|---|---|
| `position` |  |
| `single_drop_now` | One body-position drop with an atomic all-bomb and held-gun preflight. |
| `landing_drop_now` | Recheck native feet/action and the same floor under the allocation lock. |
| `emergency_ring_now` | Serialize the live all-bomb preflight with the existing ring operation. |
| `control` |  |


**re6_bomb_deadlines.py** (2 module-level functions)

| Function | Purpose (first doc line) |
|---|---|
| `finite` |  |
| `record_placement` | Share exact native confirmations with manual, bot and ring observers. |


**titles/re6_switch_shell_probe.py** (9 module-level functions)

| Function | Purpose (first doc line) |
|---|---|
| `_is_ice` |  |
| `nearby_targets` | Bounded, read-only baseline for susceptible enemies near the proposed effect. |
| `ice_changes` | New nearby ice reactions, never claimed as exclusive hit attribution. |
| `inspect_shell` | Read the native shell's identity, action and enemy attack queue; write nothing. |
| `_safe_point` |  |
| `_install_images` |  |
| `_no_owned_remotes` | Called under the shared native lock; stale/partial telemetry is no census. |
| `probe_one` | Explicit research only: one shell per player generation, never replayed. |
| `barrage` | Research barrage: `count` launcher shells spawned on a ring radius_cm around the player and armed at their |


**interventions.py** (10 module-level functions)

| Function | Purpose (first doc line) |
|---|---|
| `shell_probe_args` | Research-only, one named shell at one point; no pointers/counts/code input. |
| `shell_barrage_args` | Research-only launcher ring: one shell kind, a bounded count and ring radius; no pointers/code input. |
| `kind_rows` | Validate a worker's grenade-kind rows for the viewer, keeping the honest source label. |
| `wake_on_post` | Local serve/worker dispatch wakes on commit; remote workers retain polling. |
| `wake` |  |
| `install` |  |
| `native_controller` | One serialized native controller per adapter, shared by UI and MCP. |
| `completion_receipt` | A returned native call is not proof that its in-game effect happened. |
| `worker_loop` | Independent of video/input/UI requests; serialized native mailbox owner. |
| `_worker_loop` |  |


**remote_mines.py** (3 module-level functions)

| Function | Purpose (first doc line) |
|---|---|
| `status` | The remote-mine lane per title for the mod sidebar: the RE6 native ring/detonate is verified; the other |
| `policy` | The defaults with a ``stats['remote_mines']`` override (tests/tools), bounds enforced. |
| `control` | Native placement evidence starts a five-second deadline; escape begins immediately. |


### Module-level functions (RE6 safety/overlay modules)

| Module | Module-level functions |
|---|---|
| `titles/re6_switch_wall.py` | wall/probe helpers invoked by the movement hook (line tests, push-out, steer) - see source; no classes |
| `titles/re6_movement_safety.py` | movement-action safety wrapper (bomb/heading steering hooks) - see source; no classes |
| `titles/re6_switch_shell_probe.py` | `probe_one`, `barrage`, `inspect_shell`, `nearby_targets`, `ice_changes`, `_no_owned_remotes` (admission), `_safe_point`, `_install_images` |
| `titles/re6_switch_weapon_native.py` | native weapon-flag helpers for the RE6 equipment path |

### Shared combat-core modules (selected, not exhaustive)

| Module | Role in combat |
|---|---|
| `gbox/mercs/aim.py` | generic aim solver helpers shared by titles |
| `gbox/mercs/ballistics.py` | bullet drop/spread/travel math |
| `gbox/mercs/fire_pattern.py`, `core/fire_pattern.py` | weapon-family trigger cadence/scatter pattern |
| `gbox/mercs/behavior_metrics.py` | per-round behaviour counters (kill gaps, combos, movement) |
| `gbox/mercs/aim_book.py` | learned per-weapon/per-distance aim corrections |
| `gbox/mercs/flash_window.py` | when a flash is worth it (crowd, tight, immune) |
| `gbox/mercs/threat.py`, `threat_memory.py` | threat scoring and memorised dangerous enemies |
| `gbox/mercs/core/*` | doctrine, fire burst, respond, control axes, death lessons, menu pace, throw aim |
| `gbox/mercs/driver.py`, `engine.py` | session/tick runtime and screen state machine |
| `gbox/mercs/round_reports.py` | report assembly (score/rank/kills/combo/accuracy/deaths) |
| `gbox/mercs/reviewer.py` | Hermes review gate handshake |
| `gbox/mercs/combo_reports.py` | combo accounting/attribution reporting |
| `gbox/mercs/round_audit.py` | round evidence audit |
| `gbox/mercs/deployables.py`, `grenade_ring.py`, `re6_dti_emu.py` | deployables/ring helpers |
| `gbox/mercs/qte.py` | shared QTE machinery |
| `gbox/mercs/lessons.py`, `learning.py` | cross-round learning/lessons |
| `gbox/mercs/enemy_db.py`, `enemy_kinds.py`, `enemy_identity.py` | enemy class data, kinds and identity tiers |

---

## Appendix A: the operator's Mercenaries rules as written (2026-11-14)


```text
- initially go after the time bonuses throughout the level while building initial combo
- always keep the combo running and activate combo time via chests (RE4), chests (RE5), shooting / destroying blue time bonus crystals (RE6)
- throughout the match, the bot needs to relocate and capture / destroy combo time activators after acquiring time bonuses initially
- once the time is at 5 minutes, the strategy can go into fighting, traps and combo maintenance.
- the combo of the match is dependant upon always adding kills consistently. I do not want the bot failing the combo.
- They need to do any and all actions to keep the combo growing and maintain it while surviving.
- losing / resetting the combo is a waste of a match and is a serious fail condition
- the combo must always grow and always be maintained
- the combo should never be lost
- surviving is expected but the combo is the true meta of the game.
- the goal is to have a steady match where the combo matches the kill count due to being intrinsic and consistent
- the bot must not only fight enemies but locate and pursue them.
- the bot should interpret the map / ram / hex information of the game to know where each and every enemy is on the map.
- the bot should be capable of long shots of unlimited distance if needed.
- the bot should be able to throw grenades across the entire map at enemies and be able to throw and plant remote mines at unlimited distances able to detonate them at will remotely to deal with threats.
- An enemy must be dispatched every 4 seconds, this is why you must be dropping mines, throwing grenades and spamming rapid fire shots.
- If the bot is always running and always dropping mines, the combo is easy to maintain.
- If the bot fights while placing mines, the goal becomes easier.
- If the bot is always moving and placing a mine every 10 seconds and dispatching a foe every 4 seconds, the combo will be easier to maintain.
- The true goal is to make the bot a master at the game without mods and hacks. But for now the bot must master the hacked modified game to be able to fire without reload and reactively stun opponents who hurt them.
- The true measure of success is the combo being maintained. This can only be done by pursuing enemies while keeping a distance from them while dispatching them.
- Every enemy is meant to be dispatched. I want the bot aiming to dispatch each and every enemy no matter the distance.
```

---

## Appendix C: operational commands used to verify the bot

These are the harness commands used to test, deploy and sample the bot (the runtime details, not game actions):

```text
# tests (from C:\_tools\gBox\system with PYTHONPATH=tests;.)
python -m pytest tests/test_re6_switch.py tests/test_re6_bonus_priority.py tests/test_re6_periodic_quick_attack.py -q
python -m pytest tests/test_re6_shell_probe_receipts.py tests/test_re6_shell_barrage.py -q

# deploy the current main to lilspark and activate it
timeout 150 bash scripts/deploy_main.sh --deploy
sudo -n systemctl restart gbox.service

# Hermes review gate
POST /api/hermes/task-mode {"enabled": true}

# MercMode window control
POST /api/mercmode {"host":"lilspark","command":"stop"}
POST /api/mercmode {"host":"lilspark","command":"start","title":"re6"}
POST /api/mercmode {"host":"lilspark","queue":[{"title":"re6"}]}     / {"queue":[]}

# observation
GET /api/sessions?include_ended=false
GET /api/autoplay/telemetry/<sid>            (stats incl. combo/kills/raise_trigger_requests/...)
GET /api/mercs/round-reports?limit=N         (score/rank/kills/max_combo/accuracy/deaths)
GET /api/sessions/<sid>/interventions
POST /api/sessions/<sid>/interventions       (operator buttons: flash_now, grenade_ring, ...)
GET /api/workers/<wid>/bot-logic             (saved knobs; re-applied each round start)

# QTE failure investigation files
gbox-data/mercs/qte-failures/*.json
```

---

## Appendix B: where to look when something is wrong

| Symptom | Telemetry / file to read first |
|---|---|
| combo lost | `stats.combo_breaks`, `combo_break_last`, `combo_break_last_why`, `combo_break_<doing>`, round report combo/kills |
| gun up, no shot | `stats.aim` string, `raise_trigger_requests` vs `raise_repositions`, `scatter_forced`, `raise_bullets`, `offlevel_fire_veto`, `close_fires`, `point_blank_fires`, `fire_contact_verified` |
| not fighting / standing | `stats.act/doing`, `relocations`, `strafe_ticks`, `no_foes`, `idle_s`, `kill_gap_max_s` |
| QTE failed | `gbox-data/mercs/qte-failures/*.json`, `qte_seen`, `qte_failed`, `qte_solved_ram`, `qte_auto` |
| mines not exploding | `mine_ring_requests`, `mine_deadline_pending`, `mine_clearance_cm`, `mine_required_clearance_cm`, `mine_flag_detonations`, `mine_detonate_reason`, death cause `bomb` |
| grenades absent | `combat_grenade_throws`, `nade_throw`, `nades` inventory in snapshot, `nade_wheel` |
| flash/nitrogen rings | `hit_flashes`, `hit_flash_requests`, `hit_nitrogen_requests`, `nitrogen_rings`, `nitrogen_ring_error`, `ring_flash_at` |
| raises blocked by geometry | `los_blocks`, `offlevel_fire_veto`, `raise_repositions`, `aim` string source, navmesh |
| host/queued verification | `/api/sessions`, `/api/autoplay/telemetry/<sid>`, `/api/mercs/round-reports`; force a window with MercMode `stop` then `start title=re6` |
