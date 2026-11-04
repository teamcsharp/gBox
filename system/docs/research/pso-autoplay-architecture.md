# PSO Episode I & II Plus — Full Autoplay Architecture (GC, 3OE2 / GPOE8P)

Synthesis of 12 parallel research+design agents into one buildable system.
game_id `436e0bb84d5337d1`, disc guard `GPOE8P\0\x02` @ `0x80000000`, Dolphin, big-endian MEM1.
Scope: RESEARCH + DESIGN. No emulator launched, no RAM written. Status date 2026-11-04.

---

## 0. The one-sentence answer to "how is this not autoplaying yet"

**The live-RAM 2D-map + pathfinder + goal engine the operator is asking for ALREADY EXISTS, is read-only, and is hot-reloadable — but it is deliberately disc-gated to THREE Forest collision layouts.** Everywhere past Forest (Caves, Mines, Ruins, all of Ep2, every boss arena) the `Provider` returns no grid, A* goes dark, and the bot limps forward on geometry-free door-sniffing + stage-flag force-writes + native floor warps. Those warps are why a run *looks* like it progresses without ever solving a room.

Lifting ONE gate in `pso_coop_geometry.py` (the `KNOWN`-dict membership tests) turns the existing engine loose on every randomized room of every zone with **no new RAM reversing required**. That is the fastest path to a visibly-moving autoplay bot and is build step #1.

This is verified in code, not assumed:
- `pso_coop_geometry.py:834` — `if (episode, floor) not in {(a,b) for a,b,_ in KNOWN}: raise "No verified geometry for this area"`
- `pso_coop_geometry.py:858-860` — `source = KNOWN.get((episode, floor, digest)); if not source: raise "Loaded collision layout has no exact disc proof"`
- `KNOWN` (`:20-25`) contains only town (`map_city00_00c`), Forest1 (`map_forest01c`), Forest2 (`map_forest02c` + `map_aforest02c`).

---

## 1. System model — what PSO autoplay is, and the two loops

PSO co-op here is **same-game offline split-screen**: ONE Dolphin, one disc, one isolated memory card, up to 4 local characters sharing one world. NOT networked instances. Do not redesign toward linked instances.

There are TWO autoplay entry points. Keep them straight:

| Loop | Entry | Nature | Use |
|---|---|---|---|
| **Solo campaign** | `pso_campaign.play()` | Vision-LLM planner (screenshots → Ollama → `{thought,screen,actions}`) over a native fighter | Title/menu/credits recognition; the path that "doesn't reliably leave the title" |
| **Co-op campaign** | `pso_coop.play()` (~4300 LOC) | During verified field play: **RAM-only, NO vision LLM**. P1 navigates/fights/unlocks purely from RAM | The real engine. All nav intelligence lives here. Build here. |

`pso_coop.play()` dispatches here when `players>=2`. The field loop per tick:
1. `Reader.snapshot()` → world state (players from `PLAYER 0x8050EA10`, entities from `ENTITY_TABLE 0x8050D460`), then `pso_coop_geometry.Provider.snapshot()` attaches the collision grid + `geometry_identity`, then `pso_coop_gates.observe()` attaches door/gate state.
2. Menu handling (`pso_menu_observer` / `pso_license_menu` template matchers; `menu_unstick` native warp).
3. Controller-mapping proof (two-pad town probe) + `AccessPolicy.step` (writes area/mission availability flags).
4. `apply_master_build_tick()` — crit / never-miss / random-weapon / mag / units / 3x speed, every tick.
5. `controller.tick(state)` — the per-room goal + movement, in a crash-resilient try/except so one bad frame never kills the loop.

**The operator's framing is already the intended architecture.** "Break the game into 2D maps solved by pathfinding + goal systems per room, analyze on a 2D level, autoplay in 3D" is literally what `Provider`→`Atlas.project`→`RoomMap` A*→`movement_keys` do — for Forest. The work is to make it universal and let a clean goal engine own P1.

---

## 2. The unified layer stack

```
                         pso_coop.play()  (top loop; crash-resilient tick)
                                   │
   ┌───────────────────────────────┼───────────────────────────────────────┐
   │ EPISODE/DIFFICULTY ledger      │  Progress.observe()  (DONE, keep as-is) │
   └───────────────────────────────┼───────────────────────────────────────┘
                                   │
     ZONE SEQUENCER  (NEW pso_sequencer.py / pso_zone_map.py)
        floor→objective table, Ep1+Ep2 routes, exit-vs-warp, Ruins gate
                                   │
     GOAL ENGINE  (NEW pso_goal.py + existing FieldObjectives)
        per-room goal arbiter: KILL_ALL / PRESS_SWITCH / WALK_THROUGH /
        REACH_WARP / FIND_BOSS_DOOR / FIGHT_BOSS / EXPLORE / CROSS_FENCE
        completion signals ranked: stage-flag flip > room-id change >
        FLOOR change > boss-HP→0 > enemy-scan-empty (heuristic)
                                   │
     PATHFINDER  (pso_coop_nav.RoomMap A*, extend)  +  STEER (NEW pure-pursuit)
        8-conn grid A*, learned blocked edges, toward()=always-progress,
        + turn penalty, LOS string-pull, PlanCache hysteresis, dynamic
        enemy soft-cost overlay
                                   │
     2D NAV-MESH  (pso_coop_geometry Provider/Atlas — LIFT THE GATE)
        live collision triangles → per-player connected 2D occupancy grid
        + per-cell height, keyed by live mesh fingerprint (randomized-safe)
                                   │
     THREAT LAYER (NEW pso_coop_threat.py)  — enemy/hazard danger grid
                                   │
     RAM READ  (semantic.Extractor + profiles/pso-gc-plus-us.json)
        actor table, player poses, stage flags, collision roots
                                   │
     INPUT  movement_keys()→8-octant stick (digital) | analog via ViGEm vpad
            recenter() L-snap camera invariant; Inputs.hold() timed pulses
```

Sidecars wired in, not in the vertical path:
- **COMBAT** — `pso_master_build` (crit/never-miss/3x/random weapon/mag/4-unit armor) + `pso_coop_combat` (attack envelope) + target selection from the live entity table.
- **BOSS** — `pso_boss_strategy` advisor (`boss_target`/`boss_alive`/`boss_telemetry`) on boss floors; the goal engine routes TO the arena and defers aim to it.
- **CO-OP** — P1 sole navigator; P2..P4 `swarm_follow` (geometry-free orbit+defend); the fence puzzle borrows one free follower.

**Contract between layers (keeps the 12-way split clean):** the `state` dict (producer: `Reader`+geometry) and the `(goal, target)` tuple (producer: goal engine, consumer: the executor methods `drive_forward`/`boss_combat`/`fence_role`). Everything new is a pure, read-only, function-locally-imported leaf so it hot-reloads with the loop.

---

## 3. The 2D nav-mesh is real — how it is built each frame

All CONFIRMED and already running read-only every frame (`pso_coop_geometry.py`, `psomap.py`):

1. **Collision in RAM is true triangle geometry.** A per-floor collision REL is relocated into an allocation whose root/base/size/manager pointers sit at fixed globals `ROOTS = (0x805D4E68, 0x805D6000, 0x805D6014, 0x805D5650)`. `manager+0x1C` is a null-terminated table (≤256) of 0x18-byte mesh entries → mesh header `{u32 nv, verts*, u32 nf, faces*}`; vertex = 3×f32; face = 36B `{u16 v0,v1,v2,flags; f32 normal@+8}`. Face flags: `TRIGGER_FLAG 0x8000` = event volume (skip), `PLAYER_FLOOR_MASK 0x41` = walkable, `normal.y>0.6` = floor else wall/slope. Verified 2026-10-05 on `map_forest01c.rel`: 69 meshes, 1455 triangles, raster matches Forest 1.
2. **Raster to 2D grid.** `Atlas` stamps upward faces into 5.0-unit cells as `{(cx,cz) → sorted floor heights}`, clips wall spans out of each cell's band (overpasses preserved, not flattened).
3. **Per-room isolation.** `Atlas.project(player)` = 8-neighbour connected-component flood fill seeded at the player's cell, trimmed to 1-cell clearance → the "current room" as `collision_grid = {size, floor, heights, walls, max_step .75, max_slope .75}`. This carves the room live out of whatever randomized layout loaded.
4. **Identity.** `identity = sha256(episode,floor,roots,table,blob)` is the cache/fingerprint key. `room_key()` (`pso_coop_nav.py:25`) composes `build+episode+floor+difficulty+room+height-layer+geometry_identity(+landmarks when no geometry)` so a learned wall NEVER leaks across a randomized variant or across episodes. **Verified in code.**
5. **Consumption.** `RoomMap` A*-routes on the grid (`route`/`toward`); `pso_map.extract_surface` serializes it to the operator's 2D viewer; `pso_map_feed` serves it.

Fallbacks already present (keep): `MarginViews` (single-height recovery grid at seams/doorways — note `_snapshot` already promotes a margin `safe` grid when `project()` returns empty, `:880-886`), `LocalConnectors` (half-unit exact-triangle raster for overlaps), observation-learned blocked edges (`RoomMap.observe`: an intended step that moved <2u twice becomes a persistent blocked edge, keyed by `room_key`), object-position nav from the entity table.

---

## 4. THE blocker and the exact change (build step #1)

### 4.1 What to change — `pso_coop_geometry.Provider._snapshot` (hot-reloadable)

Add a flag `ALLOW_UNPROVEN_LAYOUTS` (module const, default `True`, instantly revertable — operator revert-gate friendly). Then:

- **`:834`** — replace `if (episode, floor) not in KNOWN-keys: raise` with: accept any `floor` where `0 <= floor` for the current episode (town=0, zone>=1). Under the flag, do not require membership.
- **`:858-860`** — compute `digest` and `source = KNOWN.get((episode,floor,digest))` exactly as now, but when unknown DO NOT raise: set `source = {'path': None, 'layout': 'live_mesh', 'triangles_sha256': digest, 'triangle_count': n}`; keep `layout_identity = sha256(f'3OE2|{episode}|{floor}|{digest}')` (already the cache authority, `:866`). Known layouts stay `'verified_disc'`.
- **`_forest2_binding` + the `expected` tuple (`:836,838,852`)** — keep READING those words and FOLD them into the fingerprint, but make the Forest2-specific hard-equals OPTIONAL for non-Forest2 floors (they are area-specific and only defined for `(1,2)`; `_forest2_binding` already returns `None` elsewhere, so no change needed there — just do not invent an equivalent hard-equals for new zones until a per-zone variant selector is confirmed; see Open Q #3).

**KEEP every universal guard** (these make a garbage/mid-load mesh RAISE rather than mislead): `PHASE==14` + `FLOOR` match + both player ptrs == table (`:831,836,839`), `TRAVELLING==0` (the 4th `_binding` word), collision-manager getter code hash `0x8007A728==806db0504e800020` (`:841`), the player-floor code hashes (`0x800791BC/0x8007A448/0x801B7998`, `_player_floor_code`), structural guards (terminator, relocation-inside-allocation, finite bounds, vertex/face/cell budgets), and the post-raster double-read consistency re-check (`:851,898`) that already catches a mid-load garbage mesh.

**No other module changes needed for step #1.** `pso_coop_nav`, `pso_map`, `pso_map_feed`, `FieldObjectives` all consume whatever grid the `Provider` emits and key everything by the live fingerprint, so they light up for Caves/Mines/Ruins/Ep2/boss-arenas automatically.

### 4.2 The second, independent gate (do not confuse with 4.1)

`_snapshot:831` also hard-requires `set(players) == {1, 2}` (exactly two seated players). That gates the **geometry** reader, NOT zone coverage. Lifting 4.1 gives pathfinding in all zones with the current 2-player seating; the 4-player work (§8) is separate and not on the critical path to a visibly-moving bot.

---

## 5. Consolidated RAM map (deduped, confidence-marked)

Reconciliation note: the room-geometry agent flagged `0x805D49B8` as an unknown "gameplay substate (guess)". It is **`TRAVELLING`, confirmed** (`pso_campaign`, `pso_coop_native`, `pso_fence`, and the geometry `_binding` which expects it `==0`). Resolved to confirmed below.

### Globals / selectors
| Addr | Name | Meaning | Conf |
|---|---|---|---|
| `0x80000000` | DISC_GUARD | 8B `GPOE8P\0\x02`; gate all native ops | confirmed |
| `0x804FE120` | PHASE | 10=menu, 14=in-game, 15=online; gameplay=14 | confirmed |
| `0x805D5FC0` | FLOOR | 0=Pioneer2/town, ≥1=zone. Also the stage-flag GROUP index | confirmed |
| `0x805D6060` | EPISODE | 0=Ep1,1=Ep2 (play-ep = value+1) | confirmed |
| `0x805D49B8` | TRAVELLING | ≠0 while area loading (actors recreated; suspend nav). Geometry binding expects 0 | confirmed (reconciled) |
| `0x805D5550` | DIFFICULTY | 0..3 Normal..Ultimate | confirmed |
| `0x805D34B8` | MODE | ==2 offline MULTI (the 2-player campaign mode) | confirmed |
| `0x805D5B50` | VISITED | per-floor destination-available bitmask | confirmed |
| `0x805127F8` | QUEST/AREA_BITMAP | 0x200B availability bitmap (area+mission flags) | confirmed |
| `0x804C3BC8` | VT_UPDATE | player vtable update slot (player+0x18 == this-12) | confirmed |
| `0x801BB330` | ORIGINAL_UPDATE | stock player-update routine (re-run for 3x speed) | confirmed |

### Tables
| Addr | Name | Meaning | Conf |
|---|---|---|---|
| `0x8050EA10` | PLAYER | 4-slot player object ptr table P1..P4 (0=empty) | confirmed |
| `0x8050D460` | ENTITY_TABLE | ≤256 u32 ptrs, null-term: players+enemies+gates+warps+objects | confirmed |

### Stage flags / warp
| Addr | Name | Meaning | Conf |
|---|---|---|---|
| `0x80515CC8` | STAGE_FLAG_BASE | 18 groups×32B, group=floor, MSB-first. Authoritative door/fence/switch OPEN state | confirmed |
| `0x80229220` | stage_flag_accessor | native get/set/clear(group,index); build-sig guard | confirmed |
| `0x80515BA0` | TRAVEL_STATE | +0xC = target floor for native area-load | confirmed |
| `0x80228540 / 0x8000F998 / 0x801BAB1C` | SET_TARGET/BEGIN_TRAVEL/WARP | native floor-load path (reused by pso_fence) | confirmed |

### Collision (area-agnostic, one engine format)
| Addr | Name | Meaning | Conf |
|---|---|---|---|
| `0x805D4E68 / 0x805D6000 / 0x805D6014 / 0x805D5650` | COLLISION root/base/size/manager (`ROOTS`) | collision-REL allocation; blob=base..base+size; manager+0x1C=mesh ptr table | confirmed |
| `0x8007A728` | collision_getter_codeguard | `806db0504e800020`; version lock, area-agnostic | confirmed |
| `0x800791BC` (+`0x8007A448`,`0x801B7998`) | player_floor_query_code | yields PLAYER_FLOOR_MASK 0x41 / TRIGGER 0x8000; code-hash guarded | confirmed |
| `0x80513920` | FOREST2_floor_record | +12*floor = map-index/variant; **Ep1 Forest2-specific** (per-zone analogues unknown) | confirmed |
| `0x805D5FC4` | map_index_variant | Forest2 selected variant words; fold into fingerprint | confirmed |

### Actor struct (size 0x340, offsets from object ptr)
| Off | Name | Meaning | Conf |
|---|---|---|---|
| `+0x00` | class_name_ptr | u32→C++ class C-string (TObjPlayer/TObjEne*/TBoss*/TObjDoor/TObjAreaWarp*) | confirmed |
| `+0x18` | vtable | ==VT_UPDATE-12 validates a real TObjPlayer | confirmed |
| `+0x1C` | entity_id | u16: 0..11 player, 0x1001.. npc, 0x4000.. object | confirmed |
| `+0x28` | room | u16 room/section id | confirmed |
| `+0x2A` | wave | u16 spawn wave (per-wave room-clear) | confirmed-static; verify live |
| `+0x2C` | index | u16 per-descriptor index | confirmed-static; verify live |
| `+0x38/+0x3C/+0x40` | pos x/y/z | 3×f32 BE world position (read `>3f` at +0x38) | confirmed |
| `+0x60` | angle | i32 BAMS; heading_deg=angle*360/65536 | confirmed |
| `+0x80` | spawn_descriptor_ptr | →0x48B spawn record (candidate room census) | confirmed-static; unverified live |
| `+0xA4/+0xA8` | hitrecord_list/count | 44B records / u32 count>0 = attacking NOW (3x-speed gate) | confirmed |
| `+0xC8` (low16) | flag_index | barrier/switch stage-flag index; garbage for plain TObjDoor | confirmed |
| `+0xCC` | barrier_mode | 1=open uncond; 2/3=consult stage flag | confirmed |
| `+0xAC / +0xD0` | native_state / flags | recomputed each frame; NEITHER proves passability | confirmed |
| `+0x2B0` | stat_block_ptr | atp@0,mst@2,evp@4,hp@6,dfp@8,ata@10,lck@12 (LCK→100 crit backstop) | confirmed |
| `+0x2B8` | hp_max | u16 | confirmed |
| `+0x2D2` | crit_threshold | min(const,this) rolls the crit (pso_crit) | confirmed |
| `+0x324` | control_mode | ==2 ⇒ damage gated OFF this tick (invuln). `vulnerable = (!=2)` | confirmed-static (ELF); live-on-enemy in progress |
| `+0x326` | action_state | Dragon {21,22}=grounded-attack/breath/eruption; per-enemy sets unmapped | confirmed Dragon; else guess |
| `+0x30` | result_flags | Dragon sets bit 0x0800 during attack | confirmed |
| `+0x32C` | hp | u16 current; 0=dead | confirmed |
| `+0x32E` | tp | u16 current TP | confirmed |
| `+0x3C0` | dying_flags | bit 0x40 = dying/despawn | confirmed Dragon |
| `+0x3E0` | parent_ptr | sub-part→parent (De Rol Le joint→head) | confirmed |
| `+0xD00` | inventory_mgr_ptr | TItemManager | confirmed |
| `+0xD04` | equip_slots | 13 u32 active equipped-item ptrs | confirmed |
| `+0x198` (mag obj) | mag_stats | iq/synchro/def/pow/dex/mind + color@+0x1A6; vtable 0x8049F478 | confirmed |

### Fence passability (via deref)
| Addr | Name | Meaning | Conf |
|---|---|---|---|
| `fence+0xB4 / +0xB0` | fence_state/flag | TObjLazerFenceNorm state machine + gating flag | confirmed |
| `*(fence+0xA4)+0x18 bit0` | laser_collision_enable | CLEAR = fence dropped = passable (frame-stable) | confirmed |

### Combat code sites (read-only; caves already installed)
| Addr | Name | Meaning | Conf |
|---|---|---|---|
| `0x80014108` | FUN damage-apply | subtracts damage only when target +0x324!=2 (defines vulnerable) | confirmed |
| `0x8001468C / 0x80014678` | crit branch / threshold | melee ×1.5 crit; forced for local players (cave 0x80005000) | confirmed |
| `0x80015F00 / 0x80016384` | accuracy sites | never-miss (cave 0x80006800) | confirmed |
| `0x80004C00` | speed dispatcher cave | re-runs ORIGINAL_UPDATE ×2 extra when +0xA8>0 = 3x attack | confirmed |
| `0x801050E4` | EQUIP_PATCH | `38000005` = equip anything | confirmed |
| `0x801057A8 / 0x801B9F40 / 0x801B63AC` | F_CREATE/F_EQUIP/RECOMPUTE | native item create/equip/stat recompute | confirmed |
| `0x80112C90` | MAG_APPLY | mag recompute after stat write | confirmed |

### Known UNKNOWNS (guess / unfound — do not build hard logic on these)
| Target | Why it matters | Conf |
|---|---|---|
| Field warp classes `TObjAreaWarp*`/`TObjMapWarp*` + dest-floor param | positive exit/boss-door detection; only `TObjCityDoor_Warp` (town) confirmed | guess |
| Dark Falz form byte (scan +0x320..+0x360, +0x3C0..+0x400) | element pick (Zonde/Barta/Foie); today HP-fraction heuristic | guess |
| Vol Opt P1→P2 signal (P02 cube z=-5000→origin) + real P2 target | which of Core(3000)/P02(9500) takes lethal damage | guess |
| Ruins pillar flag indices (groups 2/4/7) + monument class | legitimate (non-warp) Ruins unlock | guess |
| RANGED_CRIT_ROUTINE (sibling of FUN_80014108) | crit-only for guns (boss floors FORCE guns) | guess/unfound |
| COMBO_CONFIG (customize 3-slot) | special-attack finisher | guess/unfound |
| Ep2 boss floors 12/13/14/15 + classes TBoss5-8 | Ep2 boss tuning | high-confidence derivation; NEEDS_LIVE |
| frame `data1[4]` unit-slot-count semantics | whether 4-unit armor needs equip-any or the byte carries it | partial |
| per-enemy aggro/target field | proactive avoidance (today inferred from +0x326/+0xA8) | unmapped |

---

## 6. Module build map (every touch point, with hot-reload status)

HOT-RELOADABLE (`hot_reload.BOT_MODULES`, verified `:49-65`): `pso_coop`, `pso_coop_geometry`, `pso_coop_nav`, `pso_coop_frontier`, `pso_coop_town`, `pso_coop_gates`, `pso_map`, `pso_knowledge`, `pso_master_build`, `pso_survival`, `pso_fence`. Also force-`reload`ed in `play()` startup: `pso_speed`, `pso_boss_strategy`. A NEW pure leaf module hot-reloads if it is a BOT_MODULE and imported function-locally (follow the `pso_coop_gates` pattern).

NOT hot-reloadable (need worker restart): `pso_campaign`, `pso_coop_setup`, `pso_coop_access`, `pso_menu_observer`, `pso_license_menu`, `pso_gc_live`, `pso_gc_extras`, `adapters.py`, and **profile field additions** (`profiles/pso-gc-plus-us.json` is read once at `Extractor` init).

| Module | Status | Change |
|---|---|---|
| `pso_coop_geometry.py` | hot | **STEP 1**: lift `KNOWN` gate behind `ALLOW_UNPROVEN_LAYOUTS`; keep all universal guards; set `layout:'live_mesh'` source |
| `pso_coop_nav.py` | hot | add `soft_cost` param + turn-penalty to `_astar`/`route`/`toward`; add `smooth(path)` LOS string-pull; keep `observe`/`save` untouched |
| NEW `pso_coop_steer.py` | hot (new BOT_MODULE) | pure `PlanCache` (per-slot cached path + invalidation) + `pure_pursuit(path,player,lookahead)` |
| NEW `pso_coop_threat.py` | hot (new BOT_MODULE) | pure read-only `enemy_threats`/`hazard_zones`/`danger_grid`; mines & attacking cones as lethal/soft cells |
| NEW `pso_goal.py` | hot (new BOT_MODULE) | pure `select_room_goal(state,ctx)`→(goal,target,why); `zone_objective(state)`; wire ADVISORY first (`stats["pso_goal"]`), then migrate tick() branches |
| NEW `pso_sequencer.py` + `pso_zone_map.py` | hot (new BOT_MODULE) | floor→objective tables (Ep1+Ep2), `ROUTE_EP2`, exit-vs-warp `transition()`, `RuinsGate` sub-objective |
| `pso_coop_frontier.py` | hot | `FieldObjectives.destination` consumes the typed goal; bias toward the floor's known exit-warp |
| `pso_coop_gates.py` | hot | `classify_warp` (confirmed roots, exclude town `TObjCityDoor_*` from field exits), read-only `door_state`/`fence_passable`, authoritative room-clear from exit-gate flag flip |
| `pso_coop.py` tick | hot (one non-trivial edit) | call threat grid + PlanCache + pure_pursuit; pass `(goal,target)`; extend enemy rows with `vulnerable`/`attacking`; guard `observe()` against enemy-caused stalls |
| `pso_boss_strategy.py` | force-reloaded | add Dark Falz / Olga element-cycle, confirm Ep2; the goal engine routes TO the arena, defers aim here |
| `profiles/pso-gc-plus-us.json` | RESTART | add enemy fields `control_mode@0x324`, `action_state@0x326`, `dying@0x3C0`, `wave@0x2A`, `index@0x2C` |
| `adapters.py` | RESTART | analog-axis output for the ViGEm vpad path; expose `has_analog_stick`; GCPad3/4 + SIDevice2/3 for 4-player |
| `pso_coop_setup.py` / `pso_coop_access.py` / `pso_coop_mapping.py` / `pso_coop_menu.py` | RESTART | widen the ~11 hardcoded `==2 / {0,1} / (1,2)` sites for 3-4 players (§8) |

---

## 7. ORDERED implementation plan (fastest visible result first)

Rationale: PSO nav currently does not leave rooms via real pathfinding anywhere past Forest. The ranking maximizes visible motion per unit of work and keeps each step shippable by a bot-reload (no restart) until the ones that require a restart.

1. **Lift the geometry disc-gate** (`pso_coop_geometry.py`, §4.1). Default-on, revertable flag. → the EXISTING A* + frontier immediately pathfind Caves/Mines/Ruins/Ep2/boss-arena floors. **This is the single change that produces a visibly-moving autoplay bot in zones that today only warp.** Bot-reload, no restart. Verify read-only per §9 before trusting (log `geometry_source.layout == 'live_mesh'` on the operator's 2D map).

2. **Raise the force-unlock / warp timers to true last-resort** (`pso_coop.py` `maybe_force_unlock`, `advance_on_stall`). Once real pathing covers the area, the stage-flag force-writes and native warps must stop masking the nav so you can SEE pathfinding working (and so the bot plays the game instead of teleport-skipping). Bot-reload.

3. **Pure-pursuit look-ahead + octant hysteresis/dither** (`pso_coop_nav.smooth` + `pso_coop_steer.py`). Kills the 8-way stair-step wobble and octant-boundary oscillation. Immediate motion-quality win, bot-reload, no adapter work.

4. **Dynamic enemy soft-cost overlay + `observe()` enemy guard** (`pso_coop_threat.py` + nav `soft_cost`). Stops A* routing straight through mobs and stops enemy-caused stalls being learned as false walls (operator hates both freezes and bots bumping walls). Bot-reload.

5. **Goal engine ADVISORY** (`pso_goal.select_room_goal`) published to `stats["pso_goal"]` + the 2D map plan strip, then migrate `tick()` branches one at a time onto it with the executors untouched. Makes the per-room goal named, testable, visible. Bot-reload.

6. **Zone sequencer + Ep2 route fix** (`pso_sequencer.py`/`pso_zone_map.py`): add `ROUTE_EP2`, `FLOOR_NAMES_EP2`, branch `advance_floor` on EPISODE (today Ep2 warps along the wrong floor ids), prefer the legitimate exit warp when a room is complete. Bot-reload (the `advance_floor` branch is in `pso_fence`, also hot).

7. **Warp/door/room-clear authoritative detection** (`pso_coop_gates`): `classify_warp`, exit-gate stage-flag flip as the CONFIRMED room-clear signal (replaces the enemy-scan heuristic), fence collision bit. Bot-reload. (Blocked on Open Q #1/#2 for field-warp class + the mode-2/3 open predicate — ship the heuristic fallback meanwhile.)

8. **PlanCache committed replanning** (hysteresis; recompute only on goal change / segment consumed / new learned wall / new dynamic obstacle). Bot-reload.

9. **Profile enemy fields + target selection gate** (RESTART): add `control_mode/action_state/dying/wave/index`; feed `+0x324 != 2` into target selection so the bot never empties its envelope into an invulnerable frame. First restart-requiring step.

10. **Analog pad output via ViGEm** (`adapters.py`, RESTART): biggest motion-quality jump (proportional magnitude, off-octant heading, decel onto switches). ViGEm vpads already proven on the i9 for 2 players. Acceptance = the existing `mapping_probe`.

11. **Ranged/technique crit cave + combo/special finisher** (`pso_crit`): find RANGED_CRIT_ROUTINE (xref 0x3FC00000 + the +0x2D2 load) so "critical attacks only" holds for guns; add a combo-window cadence + special finisher once COMBO_CONFIG is located. Needs static RE + one live write-verify on a clean rig.

12. **4-player seating** (§8, RESTART): N independent pads + widen the ~11 hardcoded 2-player sites. Off the critical path to "visibly moving"; the nav/combat/survival brain already generalizes.

13. **Boss polish**: Dark Falz form byte + element cast, Vol Opt P2 signal, Ep2 boss live capture, Olga P2 element-cycle.

---

## 8. Co-op 2→4 players

The RAM + brain are already 4-ready: `PLAYER` is a 4-slot table, `GC` accepts `player_index 0-3`, the speed dispatcher loops `range(4)`, `survival_tick` iterates slots 0-3, `swarm_follow` is generic over slot and explicitly P3/P4-ready. P1 is the SOLE navigator (A*+frontier+gates); P2..P4 are geometry-free swarm-followers (orbit + defend the host) — keep follow-the-host, do NOT give followers independent goal nav (that was the old `waiting_for_buddy` deadlock).

The real blocker is PHYSICAL per-player input: P1=GCPad1, P2=GCPad2 share ONE virtual keyboard distinguished only by key, and the Windows map is already scraping for non-colliding keys. Right path = **4 independent virtual pads** (ViGEm on the i9, already done+verified for 2; uinput on lilspark), one per Dolphin port, routed by player index. Then widen the ~11 hardcoded `==2 / {0,1} / (1,2)` sites (`Reader.snapshot` reads only 2 ptrs; `tick` gate `len!=2`; the two-pad probe; `AccessPolicy`; menu/town scene; `pso_coop_setup.prepare` hardcodes `coop_players=2`; `adapters._argv`/`send_input_player`; `pso_coop_mapping` attestation). The join mechanic is the offline lobby: each extra buddy presses Start and selects a saved buddy card — the roster must hold 3-4 saved characters. Native gear for a slot waits on `_pso_verified_player_slots`.

---

## 9. Verification plan (read-only; no launch, no writes)

All against an ALREADY-running PSO session (`mcp__gbox read_memory`/`job_read_memory`) or an offline MEM1 dump (`job_ram_dump` + `entity_probe`). Never launch, never write, never disrupt the live lilspark stream or in-flight RE4/PSO sessions.

- **Gate lift (step 1) on a new zone (e.g. Cave1):** dump `base..base+size` + the manager table; run `parse_loaded` offline; assert triangle count sane and the player's cell height within ~1u of `actor+0x3C`. Confirm `Atlas.project` returns a non-empty safe component at the player before trusting A* there. Log `geometry_source.layout`.
- **Same ROOTS/getter per zone:** confirm `0x8007A728` getter hash and the `ROOTS` globals hold in Cave/Mine/Ruins/VR/boss (strongly expected — one engine — but confirm against a dump; Open Q #2).
- **Per-zone variant selector:** check whether non-Forest zones have an analogue of Forest2's `0x80513920`/`0x805D5FC4`; if so read + fold into the fingerprint, do not hard-code (Open Q #3).
- **Flag semantics per zone:** verify `0x41` walkable / `0x8000` trigger mean the same in Cave/Mine/Ruins (Open Q #4).
- **Enemy combat fields:** read `+0x324` on a Forest wolf across idle→attack→stagger, correlate value 2 with HP-flat frames; sample `+0x326` attack ids per enemy.
- **Warp class + dest param:** grep entity class strings on a field floor for the exit teleporter; diff Forest1-exit vs Forest2-exit objects to locate the dest-floor word.
- **Room-clear:** sample the exit fence `*(fence+0xA4)+0x18 bit0` and the barrier stage flag before/after a room clears; confirm the 1→0 / 0→1 coincides with the drop.
- **Ruins unlock fork:** sample `STAGE_FLAG_BASE + {2,4,7}*32` in Forest2/Cave2/Mine2 while using a totem; check whether the Pioneer2 Ruins teleporter depends on those 3 flags (Account B) or only the Vol-Opt-cleared flag (Account A).
- **Boss phase transitions:** log `{+0x324,+0x326,+0x2B8,+0x32C,pos,+0x3E0,+0x3C0}` once/sec across a transition; pin Dark Falz form byte, Vol Opt P02 cube move, De Rol Le surfaced action-state, and the real Ep2 class strings/floors.

---

## 10. Biggest risks

1. **Trusting a live-parsed mesh instead of a disc proof.** Mitigated: all structural + double-read-consistency + phase/floor/ptr/native-code-hash guards stay; a bad mesh raises rather than misleads; `room_key` fingerprinting stops cross-variant contamination; revert flag pins back to known-only without a deploy.
2. **A zone's collision mesh misbehaving** (a per-zone variant selector like Forest2's, an unexpected trigger-face meaning, or a boss arena whose moving body is a dynamic actor not in the static mesh). Mitigated by per-zone read-only verification BEFORE trusting A* there, and the observation-learned-edge + object-nav fallbacks.
3. **Masking fallbacks hiding real nav bugs.** The force-unlock stage-flag writes and native warps make a run *look* fine while never solving a room. Raising their timers (step 2) is required to expose and fix the real pathing — but risks more visible stalls in a zone the mesh can't yet solve; keep them as a last-resort backstop, do not remove.
4. **Input quantization.** Until analog (ViGEm) lands, 8-way digital steering overshoots small targets (switches) and oscillates at octant boundaries; the pure-pursuit + hysteresis/dither step reduces but does not eliminate it.
5. **Boss under-damage from invuln/element gates.** Guns forced on boss floors are not yet crit-hooked (ranged crit cave unfound), and Olga P2 / Dark Falz need element cycling; firing into a `+0x324==2` frame wastes the engagement. Feeding `+0x324` into target selection is the single highest-value combat fix.
6. **Restart-gated steps end sessions.** Profile fields, analog pad, and 4-player seating need a worker restart (kills warm pool, shows loading screens). Batch them; the first 8 build steps are all bot-reload-only.
7. **Ep2 floor route correctness.** Ep2 play order is NOT floor-id order (warps jump non-sequentially) and `advance_floor` currently always uses the Ep1 route; a naive floor+1 sequencer is wrong for Ep2 — drive by the live FLOOR after each warp, not a script.

---

## 11. Open questions needing live-game verification

1. In-field WARP class strings + dest-floor param (only town `TObjCityDoor_Warp` confirmed; `TObjAreaWarp*`/`TObjMapWarp*` are newserv labels, unverified against 3OE2).
2. Do ALL zones use the same `ROOTS` globals + manager getter at `0x8007A728`? (Expected; confirm per-zone.)
3. Does any non-Forest zone have its own variant selector (like Forest2's `0x80513920`/`0x805D5FC4`)?
4. Do `PLAYER_FLOOR_MASK 0x41` / `TRIGGER_FLAG 0x8000` mean walkable/trigger in Cave/Mine/Ruins?
5. Ruins unlock: Account A (beat Vol Opt ⇒ Ruins lights) vs Account B (3 totems in Forest2/Cave2/Mine2 + re-beat Vol Opt + Principal talk)? And does Pioneer2 area-gating need a Principal dialogue beat at all?
6. Live confirmation of `+0x324==2` invulnerability on NON-boss enemies; per-enemy `+0x326` attack-id sets.
7. Which `TRIGGER_FLAG 0x8000` faces are DAMAGING (Vol Opt electric floor) vs benign event/warp volumes?
8. Dark Falz form byte; Vol Opt P1→P2 signal + real lethal P2 target; De Rol Le/Barba surfaced-vulnerable action-state value.
9. Ep2 boss floors (12/13/14/15) + class strings + add classes (Olga's Gael/Giel) — byte-confirm on a live Ep2 boss arena.
10. `wave@0x2A` / `index@0x2C` live confirmation; spawn-descriptor `+0x80` lifetime for a room census.
11. frame `data1[4]` unit-slot semantics (does the 4-unit armor rely on equip-any, or does the byte carry the slots?).
12. Do slots 2,3 player ptrs populate at `PLAYER+8/+12` with `+0x1C == 2,3` when a 3rd/4th buddy joins, and does the offline lobby seat 4 locals?

---

## 12. The "20 agents" orchestration note

The operator asked for 20 agents on PSO. This document is the convergence target for that fan-out. A productive division that matches the build order and the hot-reload boundaries:

- **Ship lane (1 agent, highest priority):** implement step 1 (gate lift) + step 2 (timer backstop) behind the revert flag; bot-reload; produce in-game evidence frames of the bot pathfinding a Cave/Mine room (operator rule: every nav PR embeds real frames).
- **Live-verify lane (3-4 agents, read-only):** run the §9 probes per zone (Cave/Mine/Ruins/Ep2/each boss) against an idle i9/Spark session — never the live stream. Each resolves a batch of §11 open questions and posts confirmed offsets.
- **Nav-quality lane (2-3 agents):** steps 3,4,8 (pure-pursuit, threat overlay, PlanCache) in `pso_coop_nav`/`pso_coop_steer`/`pso_coop_threat`.
- **Goal/zone lane (2-3 agents):** steps 5,6,7 (`pso_goal`, `pso_sequencer`/`pso_zone_map`, `pso_coop_gates` warp/room-clear) + Ruins gate.
- **Combat lane (2-3 agents):** step 9 target-vulnerability gate, step 11 ranged crit cave + combo/special, build/loadout catalog-backed randomization.
- **Boss lane (2 agents):** step 13 + the boss live captures.
- **Platform lane (2 agents, restart-gated):** step 10 analog ViGEm, step 12 four-player seating.

Keep the contract fixed: `state` dict in, `(goal,target)` out, pure read-only leaves, function-local imports, per-variant `room_key`. Do NOT launch emulators from the design/verify lanes; the ship lane deploys by bot-reload and only batches restart-gated steps.
