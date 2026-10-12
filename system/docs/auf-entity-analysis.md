# 007: Agent Under Fire (GameCube, USA) - entity identification (pick whip stage 1)

Ticket #1438, stage 1: name the game entity under a screen point without a hand-written profile.
Everything below comes from static analysis of the owned disc's main executable; nothing has been
read from a running game yet. The live check at the end is what turns "high confidence" into "verified".

Deliverables: `gbox/entity_probe.py` (generic probe), `profiles/auf-gcn-us.json` (the semantic profile
the `pick` tool and `semantic.Extractor` now load), `tests/test_entity_probe.py`,
`gbox/au_inventory.py --extract` (disc file extractor), `gbox/re_seeds.py` title facts.

## 1. The executable

| file | sha256 | notes |
| --- | --- | --- |
| disc `collections/Nintendo GameCube/roms/007 - Agent Under Fire (USA).gcz` | `00a0ebbd99cf3934b626dbc0d5bfa0de53e91a1f717fbb1814cb6c93d393faac` | GW7E69, Dolphin GCZ |
| `/base.elf/Bond.elf` | `1a9c0d19fb7bab09c2fd6ef56bd8158e88e507f72ba982d0ca292bc8145e716f` | 4,729,888 bytes, the game |
| `/base.elf/boot.elf` | `29b2a3b48badbfef7b62542d14a0ca41f4bfc72a728bb4644c012bc69061446d` | 252,080 bytes, loader |
| `/base.elf/base.elf` | `22cc9ec3ec53652cf7c3a05bc050a88a9a2c0ed2c5e2bea9ab7f5ef073f961be` | 252,128 bytes |
| `/base.elf/driving.elf` | `fcb6f28c96d2e503524e4657c05c82c86006a74e3a7c795a4b79a850d9a305e8` | driving missions (separate ELF) |
| `/base.elf/Movie.elf` | `408014af8990ed7d7e449d7614f6dc4e46c8981c2dc7e551932b0d3b22da8ac7` | |
| `main.dol` (disc header 0x420) | `2f082f5b7b3f060746ed28d3ee8970eec2e8613f97136733b2e374173e23d26b` | 152,256 bytes |

Extract them again with `python -m gbox.au_inventory SRC.gcz --extract Bond.elf boot.elf --out-dir DIR`.

Bond.elf is an `ET_EXEC` PowerPC ELF that **keeps its symbol table and relocations**: `.symtab` with
17,636 CodeWarrior-mangled symbols (file markers, functions with sizes, globals), `.rela.text/.data/...`
naming the target symbol of every address load (including `R_PPC_EMB_SDA21` for r13/r2 small data).
No Ghidra run was needed: pyelftools + capstone (scratchpad `xref.py`, `classtree.py`) gave xrefs and
annotated disassembly directly.

Layout: `.init 0x80007100`, `.text 0x800094A0..0x80228CF0`, `.rodata 0x80228F20`, `.data 0x8023D980`,
`.bss 0x802916C0 (0x251978)`, `.sdata 0x804E3040`, `.sbss 0x804E3480`, `.sdata2 0x804E42A0`;
`_SDA_BASE_` (r13) = `0x804EB040`, `_SDA2_BASE_` (r2) = `0x804EC2A0`; entry `0x80007140`.

Engine: Quake III Arena + Ritual UberTools lineage (the same class names as FAKK2's public source:
`Class > Listener > Entity > Animate > Sentient > Player/Actor`, `gentity_t`, `gclient_t`, `str`,
`tiki` models, `Event`/`ClassDef` reflection). EA's build moved fields around, so every offset here was
read from this executable, not copied from FAKK2.

## 2. Structures found (addresses are RAM addresses as linked)

### 2.1 Entity table (server side)

| what | where | evidence |
| --- | --- | --- |
| `g_entities` (gentity_t* array base) | `0x804E38B0` (.sbss, r13-0x7790) | `G_NextEntity` 0x800990D0 walks it; `gGameEntities` 0x804E3520 is the renderer's copy (SIM_SetGameData) |
| entity count `globals.num_entities` | `0x803F0210` (globals+0x80) | `G_Spawn` 0x80092CD0 bumps it and calls `gi.LocateGameData(g_entities, n, 0x2B0, game.clients, 0x860)`; `gNumGameEntities` 0x804E3528 mirrors it |
| record stride `sizeof(gentity_t)` | `0x2B0` | the `mulli 0x2B0` in G_NextEntity / Entity::Entity; `active_edicts`/`free_edicts` are 688-byte objects |
| `NUM_GENTITIES`, `ENTITYNUM_NONE/WORLD`, `maxclients`, `maxentities` | `0x804E38DC`, `0x804E38D0`/`0x804E38D4`, `0x804E3904`, `0x804E3908` | symbol table (cvars hold a `cvar_t*`, integer at +0x20) |

`gentity_t` (record) fields used:

| offset | field | evidence |
| --- | --- | --- |
| +0x00 | `s.number` | `G_InitEdict` 0x80098D10 stores `(edict - g_entities) / 0x2B0` |
| +0x04 | `s.eType` (bit 0 = brush model in R_MarkVisibleEntities) | cleared in Entity::Entity |
| +0x10 / +0x1C | `s.origin` / net origin | `Entity::setOrigin` 0x80074C64 |
| +0x34 / +0x40 / +0x238 | angles copies | `Entity::setAngles` 0x800743F8 |
| +0x54 | `s.parent` (bind parent entnum, `ENTITYNUM_NONE` when unbound) | setOrigin, Entity::Entity |
| +0x5C | `s.modelindex` | `setModel` 0x80075D00 reads it after `gi.setmodel`; R_MarkVisibleEntities skips `< 0` |
| +0x124 | svflags: `0x80` hidden from the renderer, `0x40000000` marked visible this frame, `0x20` set at init | `R_MarkVisibleEntities` 0x80015EBC, G_InitEdict |
| +0x1E0 | `gclient_t*` | Entity::Entity copies it to Entity+0x18 |
| +0x1E4 | `inuse` | G_InitEdict writes 1; G_NextEntity / R_MarkVisibleEntities test it |
| +0x214 / +0x220 | `absmin` / `absmax` (world AABB after `gi.linkentity`) | `Entity::link` 0x80074FB8 copies them to Entity+0x44/+0x50 |
| +0x22C | `currentOrigin` | setOrigin |
| +0x24C | `Entity*` (the C++ object) | Entity::Entity stores `this`; G_NextEntity returns it |
| +0x268 | centroid | Entity::link |
| +0x2A4 / +0x2A8 | `next` / `prev` (active_edicts list at `0x803F0230`) | G_Spawn, Entity::Entity |

### 2.2 Entity object (C++)

| offset | field | evidence |
| --- | --- | --- |
| +0x04 | vtable pointer (Class keeps it at +4) | Entity::Entity stores `__vt__6Entity`; every virtual call is `lwz r12,4(r3); lwz r12,slot(r12)` |
| +0x10 | `entnum` | copied from edict+0 |
| +0x14 | `edict` (gentity_t*) | Entity::Entity |
| +0x18 | `client` (gclient_t*) | Entity::Entity |
| +0x1C | `classname` (const char*, from `classinfo()->classname`) | Entity::Entity (vtable slot +8) |
| +0x20 | `spawnflags` | `G_GetIntArg("spawnflags")` |
| +0x28 | `model` (`str`) | setModel; `str` = `{strdata*}`, `strdata` = `{char *data; int refcount; int alloced; int len}` (`str::EnsureAlloced` 0x8012B8F0) |
| +0x2C / +0x38 | `mins` / `maxs` | setModel writes them from the model bounds |
| +0x44 / +0x50 | `absmin` / `absmax` | Entity::link |
| +0x68 | centroid | Entity::link |
| +0x8C | `origin` (world) | setOrigin |
| +0x98 | `angles` | setAngles |
| +0xB0 | orientation 3x3 | setOrigin (bind path), `AnglesToMat` in setAngles |
| +0x120 / +0x124.. | `numchildren` / `children[8]` entnums | setOrigin child loop |
| +0x144 | model handle (`gi+0xF0(edict)`) | setModel |
| +0x158 / +0x15C / +0x168 | `bindmaster` / `localorigin` / `localangles` | setOrigin, setAngles |
| +0x424 (Player only) | `fov` degrees, clamped 1..160, 90 when below 90 with a cvar bit | `Player::SetFov` 0x800DB038 |

### 2.3 Classes

The 246 `ClassDef` registrations were recovered from the `__sinit_*` static initialisers
(`ClassDef::ClassDef(this, classname, classID, superclass, responses, newInstance, size)` at
0x8005B108): name, map classID, superclass, instance size and vtable (`__vt__` symbols). 205 derive
from `Entity`; all of them are in the profile's `entities.classes` keyed by vtable address. The ones
the pick whip cares about:

| class | vtable | size | chain | kind |
| --- | --- | --- | --- | --- |
| Player | `0x80254E70` | 2112 | Sentient > Animate > Entity | player |
| DeathmatchPlayer | `0x802482C0` | 2352 | Player | player |
| Bot | `0x80287BB4` | 3216 | DeathmatchPlayer | bot (multiplayer AI) |
| ClonePlayer | `0x80247958` | 1168 | Sentient | player |
| Actor (`monster_generic`) | `0x802612C0` | 2592 | Sentient | npc (single-player AI) |
| Deadbody | `0x80247EFC` | 944 | Sentient | corpse |
| Sentient | `0x80259E4C` | 944 | Animate | npc |
| Vehicle / DrivableVehicle / Helicopter | `0x8025CFF8` / `0x8025CEAC` / `0x8024C8C8` | | VehicleBase > ScriptModel | vehicle |
| World (`worldspawn`) | `0x80260354` | 496 | Entity | world |

Kind = first `kind_roots` entry found in the superclass chain (profile `entities.kind_roots`).

### 2.4 Camera (what the renderer actually uses)

`R_RenderPlayerView` 0x80014B1C -> `R_RenderPlayerView_Sub` 0x800149F8 -> `R_BuildCameraMatrix`
0x800138A0 (camera) and `R_Draw` 0x800142B0 -> `R_SetupProjection` 0x80014270 ->
`RenderViewBuildProjectionMat` 0x801AD22C -> `veMatPerspective` 0x8019B4D0 (projection).

`R_BuildCameraMatrix(player, mtx, fov*, angles*)` reads `gclient_t` number `player % gNumClients`
at `gClientArr + player * gClientSize`:

| what | where | notes |
| --- | --- | --- |
| `gClientArr` / `gClientSize` / `gNumClients` / `currentPlayer` | `0x804E3530` / `0x804E3534` / `0x804E3068` / `0x804E34CC` | all .sbss; stride expected `0x860` (the LocateGameData call) |
| eye position | client+0x74 (f32 x3) | `PLAYER_ClientAdjustView` 0x8000D7E4 adds `PLAYER_GetViewposAdjustment` to it first: it is the final eye |
| view angles | client+0x68 (f32 x3, Quake pitch/yaw/roll degrees) | shake/roll added by PLAYER_ClientAdjustView |
| fov | client+0x2D0 (degrees), magnification divisor +0x2D4 | `R_fGetFovFromPlayerNumber` multiplies by 0.0174533 |
| scripted camera | pm_flags client+0xC bit `0x100` -> eye +0x2DC, angles +0x2E8, fov +0x2F4; transition flag +0x2D8, duration +0x2F8, remaining +0x2FC (slerped by `R_SlerpCamera`) | |
| render state `re` | `0x803CA2C0`: fov radians +0x2BC, far +0x2B8, near +0xB58, viewport x/y/w/h +0xB6C, player +0x2B6 | |

Angles: `AnglesToMat` = Quake `AngleVectors` (forward, -right, up), so forward =
(cos p cos y, cos p sin y, -sin p), z up, degrees. Projection: `veMatPerspective(mtx, fov, aspect, near,
far, sx, sy)` builds `m00 = cot(fov/2) / (aspect * sx)` and `m11 = cot(fov/2) / sy` (sx = sy = 1 in
single player), i.e. **fov spans the vertical axis**; aspect = view aspect * (w/h) / pixel aspect = 4:3.

## 3. The probe

`gbox/entity_probe.Probe(profile, read).scan(w, h)` walks `g_entities[0..num_entities)`, skips free
slots and wild pointers, reads each object's class (vtable -> class table), classname, model string,
position, box and flags, projects the world AABB through the client camera, and
`Probe.under_point(x, y, scan)` picks the entity whose projected box contains the point (creatures
first, nearest first; within 6% of the width otherwise). `semantic.Extractor` delegates to it for
`entities.layout: struct_array`, and the `pick` tool returns `_pick_from_probe` for
`camera.layout: pos_angles_fov`, so `pick` now works on this game as soon as the profile matches
(`GW7E69` at 0x80000000). Offline: `python -m gbox.entity_probe profiles/auf-gcn-us.json ram.raw --point 320,240`.

## 4. What remains to verify live (nothing has been read from Dolphin yet)

1. Every address above against a running session (the ELF is `ET_EXEC`, so no relocation is expected,
   but the loader `boot.elf` could in principle place things differently).
2. The angle convention's pitch sign and yaw origin, and the fov axis (vertical assumed).
3. That `absmin/absmax` (edict+0x214/+0x220) are kept current for bots and NPCs (they are written by
   `gi.linkentity`; an unlinked entity has a degenerate box and the probe falls back to its point).
4. The svflags bits `0x80` (hidden) and `0x40000000` (rendered this frame).
5. Split-screen: `currentPlayer` as the viewed client index.

## 5. Exact live check (maintainer, agent-owned Dolphin session only)

Dump or read these ranges with `rpc op=read_memory` (or Dolphin's Dump MEM1 to `ram.raw` and the CLI above):

| read | expect |
| --- | --- |
| `0x80000000` 6 bytes | `GW7E69` |
| `0x804E38B0` u32, `0x804E3520` u32 | the same pointer, `0x80xxxxxx`, 16-byte aligned |
| `0x803F0210` u32, `0x804E3528` u32 | the same count, roughly 100-700 in a level, `<= 1024` |
| `0x804E3530` u32, `0x804E3534` u32, `0x804E3068` u32, `0x804E34CC` u32 | client array pointer, `0x860`, `1` in single player, `0` |
| `g_entities[0]` (0x2B0 bytes) | +0x1E4 = 1, +0x24C -> object; object+4 = `0x80254E70` (Player), object+0x1C -> "Player", object+0x28 -> strdata -> "models/..." (Bond), object+0x8C = player position, object+0x18 = the client pointer from `0x804E3530` |
| client 0 | +0x74 ~= player position + viewheight (eye above origin by tens of units), +0x68 angles (yaw changes when turning, pitch when looking up/down), +0x2D0 fov in 1..160 (90 normally), +0xC bit 0x100 only in cutscenes |
| first record whose object+4 is `0x802612C0` (Actor) or `0x80287BB4` (Bot) | its +0x8C position in front of the player; `python -m gbox.entity_probe ... --point X,Y` with the drop point of the attached frame names it, and the printed `screen_box` matches the character's outline in the frame |

Acceptance for this stage (ticket): the entity under the drop point named correctly in three different
moments, with the frames and boxes attached. Record each confirmed address with `re_dossier op=record`.
