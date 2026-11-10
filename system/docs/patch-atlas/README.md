# gBox patch atlas

The operator, 2026-11-10: "make sure we have the information and understanding to do live hooks and patches on the
games we modded so we can insert / replace / live replace / in game pickwhip them in the future. The purpose of gbox
is to make a platform database of game patching and how to identify and replace files seamlessly in gameplay to make
modifications in action."

This is that database. For every game gBox has modded, it records:

- how to identify the game and each replaceable file or asset;
- how gBox replaced it, with which writer, and whether that was seen in game;
- how it can be swapped or hooked live during gameplay;
- what is still missing before a live swap or a pick whip works.

| | |
|---|---|
| Data | `system/gbox/patch_atlas.json` (format `gbox-patch-atlas/1`) |
| Pages | `docs/patch-atlas/<platform>/<game>.md`, rendered from the JSON. Never edit them by hand. |
| Generator | `system/scripts/patch_atlas.py` (stdlib only, so it also runs on the Spark), tests in `tests/test_patch_atlas.py` |
| First edition | 2026-11-10. 39 games on 11 platforms. 390 builds were scanned: 133 from the Spark's patch library and 257 live Switch overlays. |

## The four verbs

| verb | meaning | gBox's mechanisms |
|---|---|---|
| **insert** | Add something the game does not have: a new file or entry, new code, a new arena. | LayeredFS overlays (any RomFS path); code caves hooked through a vtable slot (PSO GC, GTA PS2 EE dispatcher); native controllers placed in never-run code padding (RE5 / RE6 Switch); per-frame stubs that call the game's own code (RE6 X360); `live_inject` free arenas, which must be declared, never guessed. |
| **replace** | Rebuild the container with a new asset, then boot it. | One writer per game (the asset tables on each page) plus a container writer per platform: LayeredFS overlay, GameCube FST, ISO9660, PS1 raw sectors, GDI, N64 ROM + CRC, Xbox folder. |
| **live replace** | Change the running game without losing the session. | Five forms, from weakest to strongest: (1) same-session title restart (Switch Eden / Citron, the round is lost); (2) session swap that keeps the moment (save state -> modded image -> load state; the new model shows at the next load); (3) in-place file hot reload at a load boundary (RE6 Switch on Yuzu); (4) RAM data writes (weapons, health, unlocks, costume cursors, textures); (5) in-RAM model injection (`live_inject`, `oot_hot_swap`, `live_link` SM64). |
| **pick whip** | Point at a thing on screen, identify it, swap it. | `pick_identify` (screen point -> entity -> RAM -> writer slot) and `pick_replace` (live, else build + session swap). See `docs/live-picker.md` and `docs/live-inject.md`. Backends exist for gamecube, wii, dreamcast, naomi, ps2 and psx (`pick_tool.LIVE_PLATFORMS`), plus the OoT, SM64 and DOA2 special cases. |

Status words used on every page:

| field | values |
|---|---|
| `replace` | `proven` (an asset was seen working in game), `partial`, `untested`, `none` |
| `live file swap` | `proven` (a file swapped into a running session took effect), `static_only` (rebuild + reboot or a session swap only), `none` |
| `RAM writes proven` | the number of curated RAM hooks with a live write receipt |
| `pick whip` | `works`, `partial` (identify works, or an identify/replace exists that has not been run live), `none` |

## Strongest live-patch paths today

1. **Switch RE5 / RE6: RAM data writes and native controllers, proven live.**
   - RAM data: fire rate (the player's time scale during the shot motion), infinite ammo (the weapon records' "needs no ammo" flag), loadout templates, RE6's unlock mask and costume cursor, and RE4's health, firepower and facing.
   - Native code: the RE5 flash and weapon change and the RE6 equip run inside the game's own code. The controllers sit in never-run padding and are reached through data.
   - Code: `merc_live_controls.py`, `mercs/titles/re*_switch_mods.py`, `re*_switch_native.py`.
2. **RE6 Switch hot reload, proven once (Yuzu on the i9, 2026-11-09).**
   - The body arc was overwritten in place at the RESULTS screen. The next round in the same session drew the new body with no restart, and a third round drew the old one again.
   - This is the closest thing to a seamless in-gameplay character swap that gBox has done.
   - Not yet repeated on Eden / Citron on lilspark. The `switch_mods op=hotswap` tool still pads shorter files, which broke RE6's load on the i9.
3. **Switch same-session title restart, proven on Eden.**
   - `switch_mods op=apply_live` and `session_swap` keep the session, the display and the stream, but they reboot the title, so the round is lost.
4. **RE6 Xbox 360: the game's own code called from a per-frame stub.**
   - `sResource` loads a weapon arc into a running round in about 0.05 s.
   - Inventory, loadout and save-mask writes are all proven.
   - Not yet tried on a body arc.
5. **GameCube: PSO and Agent Under Fire.**
   - PSO GC: a code cave runs PSO's own item and equip routines, and a face texture was painted in RAM, seen in game and restored.
   - AUF: live controls work, and the pick whip names the actor under the cursor (verified live).
6. **N64: OoT live statues.** A room's display-list pointer is hooked and re-hooked after every room load (seen in game).
7. **Dreamcast DOA2: session swap that keeps the moment.** Two costume builds were checked in game after the state reload.
8. **PS2 GTA III: EE code cave.** A native GiveWeapon call through a dispatcher booted via one vtable slot.

## Biggest gaps

- **No character mesh has been replaced in RAM mid-gameplay on any game.**
  - `live_inject` / `pick_replace mode=live` have been tested on synthetic RAM only.
  - The OoT NPC hot swap stalled on a black frame.
  - The SM64 RDRAM hot swap has only fake-adapter tests.
- **Switch has no pick whip backend.**
  - `pick_tool.LIVE_PLATFORMS` has no `switch`.
  - No pointer is mapped from a player / enemy object to its loaded model (MT `MOD` / RE4 `udas`) on any Switch title, so a pick cannot become an in-RAM swap.
  - Identification pieces exist (an MT object's class name is its archive stem; RE4's unit table and projection matrix) but are not wired into `pick_identify`.
- **Switch hot reload is only proven on Yuzu / i9.**
  - Eden and Citron have no save states and layer the RomFS once per boot, so the hot reload must be proven there first.
  - On RE4, the NCE rule forbids hooking the pack loader with a code patch.
- **Textures in VRAM cannot be reached.** That covers PS1 VRAM, Dreamcast PVR / PVM and PS2 GS memory, so a live model swap there keeps the old textures until the game reloads them.
- **Writers whose output was never booted.** MGS2, Def Jam Vendetta, GoldenEye, SoulCalibur II GC, the RE5 PS3 ARC writers, the Twin Snakes live path, and the PSO GC class swaps. Their swaps are static facts, not proven patches.
- **The patch library has no `index.json`.**
  - `patch_archive.py` writes it last, and its index comprehension reads `image` / `writer` from every row. The lone-file rows (hash sidecars) do not have those keys, so the run ended in a KeyError after every `archive.json` was written.
  - The scan in this atlas (`scan.builds`, `scan.folders`) is the index until that script is fixed.

The per-game gap list is generated below.

## How to use it

- **A person:** start from the games table below, then open a game's page. Each page has these sections:
  - identification
  - file layout
  - the replaceable asset table (where it lives, how gBox found it, the writer, the method, whether it was seen in game)
  - live replacement: file swap, pick whip, live controls, curated RAM hooks, and the repo's RAM map fields
  - the builds the library holds
  - gaps and sources
- **An agent or a tool:** read `system/gbox/patch_atlas.json`.
  - `games[slug].curated.live.ram_hooks` and `generated.repo.ram_maps[*].fields` give the addresses.
  - `curated.assets[*].writer` names the module and the MCP op that replaces an asset.
  - `generated.library.rows` lists every build with its recipe (tool + op + args), which rebuilds it.
  - To read the live fields of a mapped game, use `gbox.ram_map.load(<map id or game id>).read(reader)` (docs/ram_maps.md).

### Regenerate

```sh
# 1. On the Spark (read-only), summarise the patch library and the live Switch builds (about 250 KB of JSON):
scp system/scripts/patch_atlas.py system/gbox/patch_atlas.json spark:/tmp/
ssh spark 'python3 -I /tmp/patch_atlas.py scan --library ~/gBox/system/gbox-data/patch-library \
    --switch ~/gBox_alt/gbox-cache/mods --db ~/gBox/system/gbox-data/gbox.sqlite3 \
    --atlas /tmp/patch_atlas.json --out /tmp/patch_atlas_scan.json'
scp spark:/tmp/patch_atlas_scan.json .
# 2. In system/: merge the scan, refresh the repo facts (RAM maps, codes, items, picker profiles,
#    missing sources), render every page and the generated blocks of this README.
python scripts/patch_atlas.py build --scan patch_atlas_scan.json
# Research a game (or correct one): write {"games": {slug: GAME}} and merge it.
python scripts/patch_atlas.py curate --from my-research.json
# Is anything stale? Exit 1 if `build` would change the JSON or a page.
python scripts/patch_atlas.py check
```

A scan never copies build bytes. It reads each build's `archive.json` and `.gbox-mod.json` only, plus the catalog DB in
`mode=ro`.

A library folder is matched to a game in three ways:

1. by catalog id (`curated.game_ids`);
2. by Switch title id (`curated.identification.title_id`);
3. otherwise a **stub** page is created. That marks a newly modded game nobody has researched yet.

## Schema

`patch_atlas.json`:

| key | contents |
|---|---|
| `format` | `gbox-patch-atlas/1` |
| `scan` | The last scan: date, host, roots, notes, folder and build counts. |
| `platforms.<platform>` | Curated. `name`, `emulators`, `files` (how replaced files get in), `ram` (how gBox reads / writes guest RAM), `mechanisms[]` (`verb`, `name`, `status`, `how`, `code`), `rules[]`. |
| `games.<slug>.curated` | The research (below). Only `curate` changes it. |
| `games.<slug>.status` | Derived each build: `replace`, `live_file_swap`, `ram_writes_proven`, `ram_reads_proven`, `pickwhip`, `assets(_verified)`, `builds(_verified)`. |
| `games.<slug>.page` | The page's path under `docs/patch-atlas/`. |
| `games.<slug>.generated.catalog` | `{game_id: {title, platform, region, serial, file, format, size, library, hashes}}` from the catalog DB. |
| `games.<slug>.generated.library` | The scanned builds: `folders`, `builds`, counts `by_source` / `by_writer` / `by_kind` / `by_tool`, `verified` (from the manifests), `files_touched`, `donors`, `sidecar_only` (builds known only by their hash sidecar), and `rows[]` (one per build: `name`, `source`, `tier`, `writer`, `kind`, `recipe`, `built`, `image`, `files_count`, `files`, `slots_count`, `donors`, `replaces`, `verified`, `note`, Switch `title_id` / `edits` / `hot_swaps`, library `payload_files` / `not_kept` / `size`). |
| `games.<slug>.generated.repo` | `ram_maps[]` (file, id, endian, groups, `fields[]` name / at / type / what / source, notes), `codes[]`, `items[]`, `unlock[]`, `pick_profiles[]`, `capabilities`, and `missing_sources` (cited paths not in the checkout). |
| `unpaged_writers` | Writer modules (`*_swap.py`, `*_writer.py`, `*_cast.py`, `*_mods.py`, `*_mod.py`) that no page cites. |

A curated `GAME` entry (the input to `curate`):

```json
{
  "title": "...", "platform": "switch|gamecube|wii|ps2|psx|ps3|dreamcast|n64|xbox|xbox360|nes|3ds",
  "game_ids": ["<16-hex catalog ids, plus library folder aliases such as a Switch title id>"],
  "emulator": "the emulator and the PCs it runs on",
  "identification": {"title_id": null, "disc_id": null, "serial": null, "hashes": {"<what>": "<value>"}, "notes": ""},
  "layout": [{"container": "", "format": "", "reader": "gbox/...py", "notes": ""}],
  "assets": [{"class": "character|costume|face|texture|enemy|weapon|item|stage|audio|ui|banner|text|motion|other",
              "where": "", "how_found": "", "writer": "gbox/...py (tool op=...)", "method": "",
              "verified_in_game": "yes|no|partial|unknown", "evidence": "", "notes": ""}],
  "live": {"file_swap": {"status": "proven|static_only|none", "how": ""},
           "ram_hooks": [{"name": "", "address": "0x...", "what": "", "source": "",
                          "status": "proven_write|proven_read|unverified"}],
           "live_controls": "", "pickwhip": {"status": "works|partial|none", "how": ""}},
  "gaps": ["concrete, most important first"],
  "sources": ["system/gbox/...py", "system/docs/...md"]
}
```

## How gBox identifies a game and its files

- **Catalog id.**
  - `game_id` is the first 16 hex characters of the file's sha1 when the library is hashed.
  - Otherwise it is the first 16 hex characters of `sha1("<library>:<rel_path>")` (`gbox/catalog.py`).
  - Regional versions, extra discs and update NSPs each get their own id. A page lists all of them.
- **Platform ids.**
  - Switch: the title id from the catalog `serial` or the NSP ticket (`switch_mods.title_id_for`); builds load from `load/<title id>/`.
  - GameCube / Wii: the disc id at `0x80000000` in RAM (`G4BE08`, `GRSEAF`, `GW7E69`, `GPOE8P`), which the RAM maps and picker profiles match.
  - PS3: the disc serial (`BLUS30491`).
  - Some writers pin the executable's sha256: the PSO GC `PsoV3.dol`, the DOA2 `1ST_READ.BIN`, the SM64 PAL ROM, the DOA3 XBE.
  - ASLR Switch titles are matched by a 64-byte signature of `main`.
- **Inside a build.**
  - Every build folder carries `.gbox-mod.json`: the replaced `files` / `file_changes`, `slots` (slot -> donor), the `writer`, a `kind`, a `recipe` / `build_call` (tool + input that rebuilds it), and verification flags.
  - Switch overlays add `layeredfs` (title id, load path) and an edit `history` with backups.
- **In the patch library** (`~/gBox/system/gbox-data/patch-library/<game_id>/<build>/` on the Spark), each non-Switch build that was deleted on 2026-11-10 left:
  - its manifest;
  - `archive.json` (where it was, its size, what was kept);
  - `payload/` (the replaced files' bytes: Xbox 360 tree builds and GameCube discs; base game + payload = the build);
  - `meta/` (previews).

  Changes inside an archive or a non-GameCube image were not kept as bytes (`not_kept`): rebuild those with the recipe.

  Folders named `.<build>.sha256.json` are hash sidecars of builds deleted earlier. The atlas lists them as `sidecar_only`.

## Platform mechanisms

<!-- atlas:platforms:begin -->
<a id="switch"></a>
### Nintendo Switch (Eden / Citron on lilspark, Yuzu on Windows)

**Emulators:** Eden v0.2.1 on lilspark (RE5, RE6; NCE: the game's ARM64 code runs natively); Citron NEO on lilspark for RE4 only (adapters.SWITCH_CITRON_TITLES); portable Yuzu on Windows PCs (i9-NUC: the RE6 hot-reload test).

**How files get in:** LayeredFS overlay builds (gbox/switch_mods.py, docs/switch-mods.md): a build folder holds only the changed RomFS / ExeFS files plus .gbox-mod.json (history, .gbox-backup copies, .gbox-pending edits). It is linked into the emulator's load/<title id>/<build>; every other build of the title goes in [DisabledAddOns]. The base NSP is never copied. Write with switch_mods op=write or file_mod op=build, undo with op=revert. Eden and Citron layer the RomFS once, when the title boots.

**RAM access:** Linux (Eden / Citron): /proc/<pid>/mem inside the emulator's HostMemory memfd arena (gbox/eden_memory.py, SwitchLinuxAdapter.read_memory / write_memory). Under NCE a guest address is the host address; read-only guest pages are written through a writable alias of the same memfd. The titles are ASLR: every hook is the main module's base (found by a 64-byte signature) plus an offset, so the RAM maps hold no absolute fields. Windows Yuzu: only through the GDB stub of a private debug=true launch (YuzuAdapter.debugger).

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| replace | overlay build, title boots with it | proven live | only the changed files (MT Framework .arc, RE4 .udas / imagepackhd) go in the overlay; launch_game mod=<build> | switch_mods op=write; characters op=use (RE5 / RE6 writers); re4_switch_models / re4_switch_enemies CLIs; receipts: RE5 Sonic v15 / Ryo / Mario uEm10, RE6 Sonic geometry on Leon, RE4 donor bodies |
| insert | native controller in never-run code padding | proven live | code goes only into zero padding of main's code segment that never ran (through the segment's backing file) and is reached through data (a private vtable copy); boot-time ExeFS IPS patches are also allowed | mercs/titles/re5_switch_native.py, re6_switch_native.Controller.install; RE5 native flash (20 explosions in 2.3 s), native weapon change; RE6 native equip |
| live replace | same-session title restart | proven live (round lost) | switch_mods op=apply_live, or POST /api/sessions/{sid}/swap on an Eden / Citron session: the edit lands in the build, then SwitchLinuxAdapter.restart_title reboots the title in the same session, display and stream (new PID). Eden has no save states, so the moment is not kept | gbox/switch_mods.py apply_live; gbox/server.py session_swap; docs/DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md |
| live replace | hot reload: overwrite a build file in place at a round boundary | proven once (RE6, Yuzu, i9); untested on Eden / Citron | the running title re-reads the archive at its next load: RE6 body arc uPl00LeonUsa.arc overwritten at the RESULTS screen, the next round in the same session drew it, and back again (both lengths differed: any valid arc works). switch_mods op=hotswap refuses longer data and zero-pads shorter data; padding broke RE6's load on the i9 | switch_mods op=hotswap; docs/ds-i9-client-lane-and-hot-swap-requests-20261109.md round 32 |
| live replace | RAM data writes | proven live | named offsets from the module base: weapon records, fire-rate time scale, loadout templates, unlock masks, costume cursor, health, firepower, facing | gbox/merc_live_controls.py, mercs/titles/re5_switch_mods.py / re6_switch_mods.py / re4_switch_mods.py; POST /api/sessions/{sid}/live-controls |
| pickwhip | point at something on screen | none (identify-only pieces) | pick_tool.LIVE_PLATFORMS has no switch and pick_identify has no Switch backend (the picker falls back to a colour region). Pieces: an MT Framework object's class (getDTI) is its archive stem (enemy_identity), tactical-map clicks on enemies, RE4 unit positions + projection matrix | gbox/pick_tool.py LIVE_PLATFORMS; gbox/mercs/enemy_identity.py |

> **Rule:** NCE: never rewrite guest code that has already run. Eden / Citron run the game natively and the Spark's cores report CTR_EL0.DIC = 0 (no instruction-cache coherency), so code written from outside the emulator is not seen reliably: RE4's loadout code patch hung every stage load and is off (mercs/titles/re4_switch_mods.py LOADOUT_CODE_PATCH = False, 'refused under NCE'). Data writes are fine; new code only in never-run padding reached through data; ExeFS patches only at boot. (docs/DEEPSEEK-HANDOFF-2026-11-10.md, Lesson 1.)

> **Rule:** No save states on Eden / Citron: any swap that reboots the title loses the round; a hot reload needs a round boundary.

Games: [Resident Evil 4 (Nintendo Switch, update 1.0.2) - The Mercenaries](switch/re4-switch.md), [Resident Evil 5 (Switch, The Mercenaries United / No Mercy)](switch/re5-switch.md), [Resident Evil 6 (Switch, The Mercenaries No Mercy)](switch/re6-switch.md)

<a id="gamecube"></a>
### GameCube (Dolphin)

**Emulators:** Dolphin: lilspark (Linux flatpak, DolphinAdapter), i9-NUC and other Windows PCs (DolphinWinAdapter); pinned 2609a builds for agent work.

**How files get in:** Disc FST rebuild: gcdisc.py / gcz.py read the file table in place; filemods.build_image copies the image (GCZ -> ISO) and romexport.gc_put_file writes each file into its slot, or moves it to free space and rewrites its FST entry. Some games index files by their old size: RE4 packs must stay no bigger than the original and be padded to it.

**RAM access:** Windows: DolphinProcMem reads and writes MEM1 (0x80000000-0x81800000) in the process without halting. Linux: ShmRam reads Dolphin's shared memory without halting; writes go through the GDB stub, which halts the CPU. Code patches can lag behind Dolphin's JIT (blocks already compiled).

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| replace | rebuilt disc, cold boot | proven live | characters op=use -> the game's writer -> filemods.build_image | RE4 GC (Sonic, Mario, Aya, Sonic Ganados), Metal Arms, 007 AUF casts, Crazy Taxi drivers |
| insert | code cave hooked through a vtable slot | proven live | PSO GC: a cave at 0x80004C00 runs the game's own item / equip routines on the game thread from the player-update vtable slot 0x804C3BC8 | gbox/pso_rehook.py, pso_write.py; PSO validation receipts (revive, MAG, always-hit) |
| live replace | session swap that keeps the moment | implemented; model change only at the next load | save state -> load the modded disc -> load state (server.session_swap keep_state). A GameCube state keeps the old FST and every model already in RAM, so the new model shows when the game next loads it (docs/model-replacement-state.md) | gbox/server.py session_swap; live_link (RE4 GC player path) |
| live replace | RAM data / texture writes | proven live | RE4 GC re_mods codes (unlocks, time bonus, infinite ammo, loadouts); AUF live controls; PSO face texture painted in RAM at 0x80c1ed20, read back, seen in game, restored | gbox/re_mods_tool.py, auf_live.py, pso_face*.py |
| live replace | model injection into RAM (live_inject) | synthetic tests only | pick_replace mode=live: locate the rebuilt images in a paused snapshot (GX display lists, vertex arrays), write only changed words, read back, roll back, frame check | gbox/live_inject.py, docs/live-inject.md |
| pickwhip | pick_identify gamecube backend | partial (identify verified on AUF) | profile camera projection (profiles/auf-gcn-us.json via entity_probe: names verified live), generic GX pointer walk otherwise; Metal Arms bot_at(x, y) | gbox/pick_tool.py, entity_probe.py, pick_ram.py |

> **Rule:** A GameCube save state carries the FST it booted with: replaying it on a disc whose files moved reads the old locations. Keep replaced files at their offset / size, or install the new disc's FST first.

Games: [007: Agent Under Fire (USA)](gamecube/agent-under-fire-gamecube.md), [Crazy Taxi (USA)](gamecube/crazy-taxi-gamecube.md), [Luigi's Mansion (USA)](gamecube/luigis-mansion-gamecube.md), [Metal Arms: Glitch in the System (USA)](gamecube/metal-arms-gamecube.md), [007: Nightfire (USA)](gamecube/nightfire-gamecube.md), [Phantasy Star Online Episode I & II (+ Plus, + Return To Ragol V1.0.3 patched disc)](gamecube/pso-gamecube.md), [Resident Evil 4 (GameCube, USA, Discs 1-2)](gamecube/re4-gamecube.md), [Soul Calibur II (USA)](gamecube/soulcalibur2-gamecube.md), [Metal Gear Solid: The Twin Snakes (USA, 2 discs)](gamecube/twin-snakes-gamecube.md)

<a id="wii"></a>
### Wii (Dolphin)

**Emulators:** Dolphin (the Spark), extracted disc booted as a DirectoryBlob (DATA/sys/main.dol).

**How files get in:** Extracted-disc tree: re4wii.build_mod hard-links the base tree and replaces only the changed files; no image rebuild.

**RAM access:** As GameCube (Dolphin): MEM1 0x80000000+, plus MEM2 for Wii.

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| replace | hard-link tree build | proven live | RE4 Wii: Aya as a playable Mercenaries character | gbox/re4wii.py |
| live replace | RAM data writes | proven live | RE4 Wii unlocks, time bonus x3, weapon tables, clock freeze, unlimited health | gbox/re_games.py (WII_PAL), re_mods |
| pickwhip | generic | none | only pick_tool's generic wii RAM walk; RE4 Wii's player pointer is not ported | gbox/pick_tool.py |

Games: [Resident Evil 4: Wii Edition](wii/re4-wii.md)

<a id="ps2"></a>
### PlayStation 2 (PCSX2 core in RetroArch)

**Emulators:** RetroArch pcsx2_libretro (LRPS2). On the Spark (arm64) only the EE interpreter runs, about a third of full speed for GTA LCS.

**How files get in:** ISO9660 image copies: archive entries (MGS2 STAGE.DAT, GTA IMG, Def Jam DATA.BIN) rewritten in place within each entry's sector budget, the file table unchanged.

**RAM access:** RetroArch network commands READ_CORE_MEMORY / WRITE_CORE_MEMORY (fallback READ / WRITE_CORE_RAM), 512-byte chunks, read back (gbox/adapters.py RetroArchAdapter). EE RAM sits at offset 0, so the native address is the offset. Writing into recompiled code pages from outside crashes the core.

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| insert | EE code cave booted through one vtable slot | proven live | gta_mods puts a dispatcher at 0xFA000 / 0xF9000 and points one vtable slot at it; the EE then patches its own code and runs native calls (GiveWeapon) | gbox/gta_mods_tool.py, gta3_items.py; GTA III weapon grant on i9-NUC, 2026-10-15 |
| replace | patched ISO, cold boot | proven live (GTA III faces, GTA LCS outfits) | characters op=use -> the game's writer | gbox/gta3_face_takeover.py, gta_lcs_cast.py; MGS2 and Def Jam builds never booted |
| live replace | session swap that keeps the moment | implemented, never run on PS2 | characters op=live_use (MGS2) -> session_swap keep_state; new models at the next stage load | gbox/mgs2_swap.py, server.py session_swap |
| pickwhip | slot guess / name -> slot | partial | GTA III centre pick -> player model; GTA LCS reads the player's outfit live (FindPlayerPed -> model index); MGS2 maps a spoken target to a slot | gbox/gta3_chars.py, gta_lcs_cast.py, mgs2_swap.py |

> **Rule:** GS textures are not injected by live_inject; a live model swap keeps old textures until the game reloads them.

Games: [Def Jam: Vendetta](ps2/defjam-vendetta-ps2.md), [Grand Theft Auto: Liberty City Stories](ps2/gta-lcs-ps2.md), [Grand Theft Auto III](ps2/gta3-ps2.md), [Metal Gear Solid 2: Substance](ps2/mgs2-ps2.md)

<a id="psx"></a>
### PlayStation (pcsx_rearmed in RetroArch)

**Emulators:** RetroArch pcsx_rearmed; DuckStation (flatpak, GDB server) only for Linux debug launches.

**How files get in:** Raw disc (BIN / CUE) copies: files patched in place within their sectors (MGS STAGE.DIR KMDs, FF7 LZS / BCX / BSX, Parasite Eve PE.IMG blobs, SmackDown PAC entries).

**RAM access:** READ / WRITE_CORE_MEMORY with address & 0x1FFFFF (main RAM). VRAM (textures, CLUTs) cannot be reached. cheats.py decodes and freezes GameShark 30 / 80 / D0 / E0 codes.

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| replace | patched disc, cold boot | proven live | FF7 Mario as Cloud (field + battle), Parasite Eve Mario as Aya, SmackDown 2 Sonic as The Rock | gbox/ff7_swap.py, pe_swap.py, yukes_sd.py |
| live replace | session swap that keeps the moment | implemented, never seen live | MGS VR Missions characters op=live_use -> session_swap; KMDs reload only on a stage (re)start | gbox/mgs_vr_swap.py |
| live replace | RAM writes | no live write receipt | MGS VR complete / unlock_all are allowlisted; nothing written live is recorded | gbox/mgs_vr_tool.py, cheats.py |
| pickwhip | actor projection | partial (MGS VR on save states) | mgs_vr op=pick projects Snake and the soldiers through the view matrix at 0x800B280C; other games: generic slot guess | gbox/mgs_vr_tool.py |

> **Rule:** Textures live in VRAM, which RetroArch cannot write: any live model swap keeps the old textures.

Games: [Final Fantasy VII](ps1/ff7-psx.md), [Metal Gear Solid: VR Missions](ps1/mgs-vr-missions-psx.md), [Metal Gear Solid](ps1/mgs1-psx.md), [Parasite Eve](ps1/parasite-eve-psx.md), [WWF SmackDown! 2: Know Your Role](ps1/smackdown2-psx.md)

<a id="ps3"></a>
### PlayStation 3 (RPCS3)

**Emulators:** RPCS3: RPCS3Adapter on Windows, RPCS3LinuxAdapter (arm64 AppImage) on lilspark.

**How files get in:** Folder games: a mod is a folder applied at launch (launch_game mod=). RE5 PS3 ARC writers are offline only (no install / launch path).

**RAM access:** Process memory at the guest base (a 4 GiB window, found by the ELF header at +0x10000: adapters.rpcs3_guest_base on Linux, a probe on Windows); read-only pages lifted for the write.

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| live replace | RAM data writes | proven live (RE5 PS3) | fire rate, infinite ammo, loadout templates, timer, turn speed, the system save image | gbox/re5_mods_tool.py, mercs/titles/re5_ps3.py |
| live replace | save state | partial | save_state = F2 save-and-continue; load_state = relaunch | gbox/adapters.py RPCS3Adapter |
| pickwhip | none | none | pick_ram has no PS3 layout | gbox/pick_ram.py |

> **Rule:** RE5 / RE6 PS3 are parked (operator 2026-11-10: Switch focus); the universal Mercs core must still drive them.

Games: [Puyo Puyo Tetris](ps3/puyo-puyo-tetris-ps3.md), [Resident Evil 5 Gold Edition](ps3/re5-ps3.md), [Resident Evil 6](ps3/re6-ps3.md)

<a id="dreamcast"></a>
### Dreamcast (Flycast in RetroArch)

**Emulators:** RetroArch flycast_libretro (lilspark, i9-NUC, JAYBUILTFINALE).

**How files get in:** GDI rebuild (gbox/gdrom.py): AFS members, PRS, BML and Ninja files repacked; some games need each file to fit its old sectors (SA2 SONICMDL.PRS / SONICTEX.PRS).

**RAM access:** READ / WRITE_CORE_MEMORY first, then the RAM view (READ / WRITE_CORE_RAM), 512-byte chunks, read back. Main RAM 0x8C000000 (aliases 0x0C / 0x8C / 0xAC).

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| replace | rebuilt GDI, cold boot | proven live | DOA2 costumes (Amy -> Ein, Gen Fu -> Leifang), JGR Amy as Beat, SA2 Leon through City Escape, SoulCalibur v2 / v3 | gbox/doa2_swap.py, jgr_swap.py, sa2_chars.py, soulcalibur_swap.py |
| live replace | session swap that keeps the moment | proven live (DOA2) | save state -> launch the mod -> load state; DOA2 costume builds were checked with damage dealt after the state reload | gbox/server.py session_swap |
| live replace | RAM writes | proven live (flags only) | unlock / cheat flags read back (DOA2 0x8C239D6A.., JGR 0x8C10F3E1.., SoulCalibur 0x8C336DFA..) | profiles/gamedata/*-codes.json, gbox/cheats.py |
| live replace | model injection into RAM (live_inject) | synthetic tests only | splits AFS / PRS / BML into members and Ninja files into NJCM + POF0 (exact relocation); refuses runtime-deformed geometry (DOA2) and pointer-layout changes without POF0 (SA2); PVR / PVM textures live in VRAM and are skipped | gbox/live_inject.py |
| pickwhip | profile camera / actor context | partial | PSO Ver.2: RAM camera + entity table project enemies and the picked model is extracted; DOA2: doa2_context actor -> CHR / model / texture tables (live replace refused) | profiles/pso-v2-dc-us.json, gbox/doa2_context.py, pick_tool.py |

Games: [Dead or Alive 2 - Limited Edition (Japan)](dreamcast/doa2-dreamcast.md), [Jet Grind Radio (USA)](dreamcast/jet-grind-radio-dreamcast.md), [Phantasy Star Online Ver. 2 (USA)](dreamcast/pso-v2-dreamcast.md), [Sonic Adventure 2 (USA)](dreamcast/sa2-dreamcast.md), [SoulCalibur (USA)](dreamcast/soulcalibur-dreamcast.md)

<a id="n64"></a>
### Nintendo 64 (parallel_n64 in RetroArch)

**Emulators:** RetroArch parallel_n64 (mupen64plus_next has no linux / aarch64 build); Expansion Pak on for the AKI wrestling titles.

**How files get in:** ROM rebuild (z64, big-endian): file / dma tables repointed, Yaz0 re-encoded, the header CRC fixed (gbox/n64_rom.py, n64_mod_finalize.py, docs/n64-crc-normalization.md).

**RAM access:** READ / WRITE_CORE_MEMORY (512-byte chunks). RDRAM comes back as little-endian 32-bit words, so every reader word-swaps (oot._rd / _wr, pick_ram.fix_n64).

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| live replace | display-list pointer hook | proven live (OoT statues) | oot_live.hook_once rewrites a room's display-list pointer and a watcher re-hooks it after each room load | gbox/oot_live.py |
| live replace | bounded object rewrite (oot_hot_swap) | built; the in-game test stalled on a black frame | paused, re-encode a model into one loaded NPC object's reclaimable bytes, same size, only changed bytes, bounds + read-back + rollback | gbox/oot_hot_swap.py, docs/model_swaps.md #706 |
| live replace | RDRAM segment hot swap (SM64) | fake-adapter tests only | live_link finds Mario's segment 04 byte-exact in RDRAM, writes the new one at the same size, repoints display lists, frame check, revert | gbox/live_link.py, tests/test_live_link_identity.py |
| replace | ROM rebuild | proven live | OoT casts, SM64 Mario, No Mercy (file table moved to Expansion Pak RAM + a MIPS part-list hook), WCW Revenge | gbox/oot_swap.py, sm64_swap.py, aki_wrestling.py, aki_wcw.py |
| pickwhip | OoT / SM64 backends | partial | OoT: actor nearest the point via viewProjectionMtxF + its object + SkelAnime; SM64: always Mario; No Mercy slots_on_screen boxes each wrestler (extract only, not wired to the whip) | gbox/oot_live.py, pick_tool.py, aki_wrestling.py |

> **Rule:** N64 is not in pick_tool.LIVE_PLATFORMS: only the game-specific routes (OoT NPCs, SM64 Mario) go live.

Games: [007 - GoldenEye (Europe)](n64/goldeneye-n64.md), [WWF No Mercy (USA) (Rev A)](n64/no-mercy-n64.md), [The Legend of Zelda: Ocarina of Time (USA NTSC 1.0 / Rev B 1.2; Master Quest Europe GameCube Edition)](n64/oot-n64.md), [Super Mario 64 (catalog USA and Europe entries; both hold the PAL NSMP ROM)](n64/sm64-n64.md), [WCW/nWo Revenge (USA)](n64/wcw-revenge-n64.md), [WCW vs. nWo: World Tour (USA)](n64/wcw-world-tour-n64.md)

<a id="xbox"></a>
### Xbox (Cxbx / xemu, native recompiled runner)

**Emulators:** Cxbx-Reloaded and xemu adapters support launch, stop, query and frame only (gbox/xbox.py). DOA3 runs on the pinned doa3-re v0.2 native recompiled runner on a Windows worker.

**How files get in:** Disc folder copies; DOA3's loadfile.afs costume entries rewritten in place at the same size.

**RAM access:** Only the DOA3 runner: its 64 MiB guest allocation read and written directly after checking the XBE header and code hashes (gbox/doa3_memory.py).

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| live replace | virtual pad / RAM reads | proven live (pad writes) | port-4 pad block writes drive the menus; mode, phase, health, select cursor and picked character are read | gbox/doa3_memory.py, doa3_pad.py |
| pickwhip | none | none | xbox is not a pick platform; the runner has no save state | gbox/pick_tool.py |

Games: [Dead or Alive 3 (USA)](xbox/doa3-xbox.md)

<a id="xbox360"></a>
### Xbox 360 (Xenia)

**Emulators:** Xenia Canary on Windows (i9-NUC), window docked into gBox.

**How files get in:** Mod folders (tree builds): only the replaced files (nativeXenon/arc/X360/*.arc) beside the base; launch_game mod= relaunches.

**RAM access:** Windows ReadProcessMemory / WriteProcessMemory at the guest base, found by probing 2^n + 0x82000000 for 'MZ' (+0x1000 for addresses >= 0xE0000000); read-only pages lifted with VirtualProtectEx (gbox/xenia.py XeniaAdapter).

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| insert | per-frame stub calling the game's own code | proven live | a private vtable copy routes a call to a stub: uPlayer::setItem, sResource getResource (loads a uWp arc into a running round in ~0.05 s) | gbox/re6.py, re6_items.py; docs/research/re6-native-flash.md |
| live replace | RAM data writes | proven live | health, inventory, Mercenaries loadout table, save masks | gbox/re6.py (job_re6) |
| live replace | session swap | none | XeniaAdapter has no save state: a new build means a relaunch and picking the character again | gbox/xenia.py |

> **Rule:** Xenia compiles guest code once: code patches go in right after boot, and stub bytes never change after.

Games: [Resident Evil 6](xbox360/re6-xbox360.md)

<a id="nes"></a>
### NES (Mesen in RetroArch)

**Emulators:** RetroArch mesen core.

**How files get in:** ROM rebuild, same size (CHR tiles + PRG tables).

**RAM access:** READ_CORE_MEMORY reads (player state, animation frame, camera) for the ghost overlay; no live writes.

| verb | mechanism | status | how | code / evidence |
|---|---|---|---|---|
| replace | same-size ROM | booted (1600 frames) | smb1_sprite_build swaps tiles and tables | gbox/smb1_sprite_build.py |
| live replace | Mesen HD tile packs | TAS replays only | tas_sprites skins the player without changing the ROM | gbox/tas_sprites.py |

Games: [Super Mario Bros. (World)](nes/smb1-nes.md)
<!-- atlas:platforms:end -->

## Games

<!-- atlas:games:begin -->
| game | platform | catalog ids | replace | live file swap | RAM writes proven | pick whip | builds (manifest-verified) |
|---|---|---|---|---|---|---|---|
| [Resident Evil 4 (Nintendo Switch, update 1.0.2) - The Mercenaries](switch/re4-switch.md) | Nintendo Switch | `270a15eb98dab4d7`, `010099A00BC1E000` | proven | static only | 5 | none | 98 (0) |
| [Resident Evil 5 (Switch, The Mercenaries United / No Mercy)](switch/re5-switch.md) | Nintendo Switch | `52d15709be0fda1a` | proven | proven live | 6 | partial | 136 (0) |
| [Resident Evil 6 (Switch, The Mercenaries No Mercy)](switch/re6-switch.md) | Nintendo Switch | `115f9cdbba115432`, `5d50031f5c8057b1` | proven | proven live | 8 | partial | 23 (0) |
| [007: Agent Under Fire (USA)](gamecube/agent-under-fire-gamecube.md) | GameCube | `65b7187589166b26`, `a8a1484cf7ac7ce1` | proven | none | 2 | partial | 0 (0) |
| [Crazy Taxi (USA)](gamecube/crazy-taxi-gamecube.md) | GameCube | `bc02bb68790ce2e7` | proven | none | 0 | partial | 0 (0) |
| [Luigi's Mansion (USA)](gamecube/luigis-mansion-gamecube.md) | GameCube | `3916cab91041a203`, `lm` | untested | none | 0 | none | 2 (0) |
| [Metal Arms: Glitch in the System (USA)](gamecube/metal-arms-gamecube.md) | GameCube | `7e103ec3aab47fa2` | proven | none | 0 | partial | 1 (0) |
| [007: Nightfire (USA)](gamecube/nightfire-gamecube.md) | GameCube | `744ba3bc797403bf` | untested | none | 0 | none | 0 (0) |
| [Phantasy Star Online Episode I & II (+ Plus, + Return To Ragol V1.0.3 patched disc)](gamecube/pso-gamecube.md) | GameCube | `436e0bb84d5337d1`, `6b55435e3c565370`, `7a3692dc0cbc9b82`, `5b5792e27be59f59` | proven | static only | 3 | partial | 10 (0) |
| [Resident Evil 4 (GameCube, USA, Discs 1-2)](gamecube/re4-gamecube.md) | GameCube | `78ab9efa2e310db4`, `e42c9b780c07c437` | proven | static only | 4 | partial | 41 (0) |
| [Soul Calibur II (USA)](gamecube/soulcalibur2-gamecube.md) | GameCube | `201629ad498aba7b`, `e08e8a0c1b3c9060` | untested | none | 0 | none | 0 (0) |
| [Metal Gear Solid: The Twin Snakes (USA, 2 discs)](gamecube/twin-snakes-gamecube.md) | GameCube | `79965f951e479d2b`, `bf3675da8955e248`, `ba32927ecc104b9a`, `b87996662aa2a8f7` | partial | static only | 0 | partial | 8 (0) |
| [Resident Evil 4: Wii Edition](wii/re4-wii.md) | Wii | `79c3a3eccb34fe62` | proven | static only | 4 | none | 1 (0) |
| [Def Jam: Vendetta](ps2/defjam-vendetta-ps2.md) | PlayStation 2 | `deabd11481aa5a0c` | untested | static only | 0 | none | 1 (0) |
| [Grand Theft Auto: Liberty City Stories](ps2/gta-lcs-ps2.md) | PlayStation 2 | `002b9dca58a18ea1` | proven | static only | 1 | partial | 1 (0) |
| [Grand Theft Auto III](ps2/gta3-ps2.md) | PlayStation 2 | `265819390074bb4e`, `82173dff3bf1ad6d` | proven | static only | 3 | partial | 1 (0) |
| [Metal Gear Solid 2: Substance](ps2/mgs2-ps2.md) | PlayStation 2 | `cb7aae71edb10cd3`, `3fc2fad561187055` | untested | static only | 1 | partial | 3 (0) |
| [Final Fantasy VII](ps1/ff7-psx.md) | PlayStation | `6703ee6f461a2ea5`, `52d73a58e6b29209`, `18581bf582f81eb2` | partial | static only | 0 | none | 10 (0) |
| [Metal Gear Solid: VR Missions](ps1/mgs-vr-missions-psx.md) | PlayStation | `afd2fc507bb69843`, `f55555ee6513391b` | untested | static only | 0 | partial | 17 (0) |
| [Metal Gear Solid](ps1/mgs1-psx.md) | PlayStation | `f27552db74dffdeb`, `b13795ef235edee3` | untested | none | 0 | none | 2 (0) |
| [Parasite Eve](ps1/parasite-eve-psx.md) | PlayStation | `c0b85e0b89f6de74`, `2ad5e8b6a18702cb` | proven | static only | 0 | none | 1 (0) |
| [WWF SmackDown! 2: Know Your Role](ps1/smackdown2-psx.md) | PlayStation | `276334ad218ffb46` | proven | static only | 0 | none | 6 (0) |
| [Puyo Puyo Tetris](ps3/puyo-puyo-tetris-ps3.md) | PlayStation 3 | `e322d2213961ff3c` | untested | none | 0 | none | 1 (0) |
| [Resident Evil 5 Gold Edition](ps3/re5-ps3.md) | PlayStation 3 | `e7ca89bbeb67360d` | proven | none | 8 | none | 0 (0) |
| [Resident Evil 6](ps3/re6-ps3.md) | PlayStation 3 | `6fc93ff62e4eb868` | untested | none | 0 | none | 0 (0) |
| [Dead or Alive 2 - Limited Edition (Japan)](dreamcast/doa2-dreamcast.md) | Dreamcast | `1de2e7634f3161ff`, `5f08ad9a86ebcc9a` | partial | static only | 1 | partial | 1 (0) |
| [Jet Grind Radio (USA)](dreamcast/jet-grind-radio-dreamcast.md) | Dreamcast | `4187aeab4d67638c` | partial | static only | 2 | partial | 1 (0) |
| [Phantasy Star Online Ver. 2 (USA)](dreamcast/pso-v2-dreamcast.md) | Dreamcast | `daba7a3b195dcf6b` | untested | none | 0 | partial | 3 (0) |
| [Sonic Adventure 2 (USA)](dreamcast/sa2-dreamcast.md) | Dreamcast | `d95ed7ed1e40552a` | proven | static only | 0 | partial | 1 (0) |
| [SoulCalibur (USA)](dreamcast/soulcalibur-dreamcast.md) | Dreamcast | `c747331797369f74`, `e4ad4831b09591b6`, `32bdc48bc550f79b` | partial | static only | 1 | none | 0 (0) |
| [007 - GoldenEye (Europe)](n64/goldeneye-n64.md) | Nintendo 64 | `eecd1708cb2b8d14` | untested | none | 0 | none | 0 (0) |
| [WWF No Mercy (USA) (Rev A)](n64/no-mercy-n64.md) | Nintendo 64 | `23a346e48b6368a6` | proven | none | 1 | partial | 1 (0) |
| [The Legend of Zelda: Ocarina of Time (USA NTSC 1.0 / Rev B 1.2; Master Quest Europe GameCube Edition)](n64/oot-n64.md) | Nintendo 64 | `1aa2e4bb5797493f`, `446e8e442d726e31`, `ff72441b33ff806b` | proven | static only | 3 | partial | 3 (0) |
| [Super Mario 64 (catalog USA and Europe entries; both hold the PAL NSMP ROM)](n64/sm64-n64.md) | Nintendo 64 | `b7aecee966090bfa`, `66062703301f4969` | proven | static only | 1 | partial | 2 (0) |
| [WCW/nWo Revenge (USA)](n64/wcw-revenge-n64.md) | Nintendo 64 | `bca7ec4ecf71d164` | proven | none | 1 | none | 1 (0) |
| [WCW vs. nWo: World Tour (USA)](n64/wcw-world-tour-n64.md) | Nintendo 64 | `59bf059d2eadd372` | untested | none | 1 | none | 1 (0) |
| [Dead or Alive 3 (USA)](xbox/doa3-xbox.md) | Xbox | `b8edf7040116f3aa`, `f03a801797a90506` | partial | none | 1 | none | 1 (0) |
| [Resident Evil 6](xbox360/re6-xbox360.md) | Xbox 360 | `0871eee3b68cdea3` | proven | static only | 10 | none | 11 (0) |
| [Super Mario Bros. (World)](nes/smb1-nes.md) | NES | `49b6a2f65aca26a2` | partial | none | 0 | none | 1 (0) |
<!-- atlas:games:end -->

## Gap list: what each game needs before a live in-game swap / pick whip

<!-- atlas:gaps:begin -->
- **[Resident Evil 4 (Nintendo Switch, update 1.0.2) - The Mercenaries](switch/re4-switch.md)** (Nintendo Switch):
  - No RAM link from a unit to its drawn pack, BIN or texture, and no hook into the loader that streams em/pl packs: a mesh cannot change mid-round.
  - NCE rule: Citron runs RE4 natively (NCE) and the Spark's cores have no I-cache coherency (CTR_EL0 DIC=0), so gBox must not rewrite executed guest code (LOADOUT_CODE_PATCH=False after every stage load hung).
  - Allowed code routes under NCE: data writes, boot-time ExeFS overlays, or code in never-run zero padding via the code segment's backing file reached by data (RE5/RE6 controllers). RE4 has no such native call harness yet.
  - ... 9 more on the page
- **[Resident Evil 5 (Switch, The Mercenaries United / No Mercy)](switch/re5-switch.md)** (Nintendo Switch):
  - No zero-restart archive swap on Eden: switch_mods op=hotswap (same-length, in place) exists but recovery-hotswap-probe-20261109 has no recorded result; Eden packs the layered RomFS once per boot.
  - No save states on Eden/Citron: every file swap reboots the title and loses the round (the incident report carries a 48 KiB RAM witness instead).
  - No RAM path to the resource manager / loaded MOD pointers on Switch, so a mesh cannot change mid-round (RE6 X360 has sResource calls; Switch none).
  - ... 4 more on the page
- **[Resident Evil 6 (Switch, The Mercenaries No Mercy)](switch/re6-switch.md)** (Nintendo Switch):
  - Hot reload is proven only on Yuzu/i9; on lilspark Eden it is untested, and switch_mods.hotswap pads shorter payloads, which broke the RE6 load on the i9 (round 20) - it must allow a different valid length or exact sizes.
  - Textured enemy reskins: the i9 found enemy materials bind to the unit's asset list; re6_enemy_cast's class-material route is offline-verified only - needs a gameplay frame.
  - No resource-manager hook or mapped MOD/texture-unit pointers on Switch: nothing can change a mesh mid-round.
  - ... 4 more on the page
- **[007: Agent Under Fire (USA)](gamecube/agent-under-fire-gamecube.md)** (GameCube):
  - No live model injection into a loaded level (live-inject: 'generic, attempted')
  - Campaign enemies, other missions and hit registration on donors unchecked
  - No AUF build in the Spark library (survey builds 0)
- **[Crazy Taxi (USA)](gamecube/crazy-taxi-gamecube.md)** (GameCube):
  - No RAM map or entity reader
  - Driver skeleton not decoded (#1369)
  - No build in the Spark library (survey builds 0)
- **[Luigi's Mansion (USA)](gamecube/luigis-mansion-gamecube.md)** (GameCube):
  - No reader, writer, RAM map or disc id pinned; only the banner pipeline test exists
  - The 'lm' library folder is not a catalog id
- **[Metal Arms: Glitch in the System (USA)](gamecube/metal-arms-gamecube.md)** (GameCube):
  - No in-RAM model replacement; picks always end in a rebuild + reboot
  - Heap scan is slow over the GDB stub
  - Player and NPC mods are separate images; NPC atlas can scramble shared textures
- **[007: Nightfire (USA)](gamecube/nightfire-gamecube.md)** (GameCube):
  - No character mesh writer and no characters op=use route
  - No RAM map; nothing read from a running game
  - No builds
- **[Phantasy Star Online Episode I & II (+ Plus, + Return To Ragol V1.0.3 patched disc)](gamecube/pso-gamecube.md)** (GameCube):
  - No pso_gc_swap build has been booted in Dolphin; P7a rigging for GC (gvr_chunk, BE tree, flat names) sits on unmerged branches e84af16c/8090217d/e1abfc4b
  - Hot swap (CP13): the loaded player model's RAM location / actor model pointer is not found; area-change reload from disc untested
  - No camera mapping in profiles/pso-gc-plus-us.json, so pickwhip cannot project entities to the screen
  - ... 2 more on the page
- **[Resident Evil 4 (GameCube, USA, Discs 1-2)](gamecube/re4-gamecube.md)** (GameCube):
  - No model pointer is mapped: the player em and EmMgr slots carry no known pack/BIN field; cEm.Character (+0x3D0, decomp) is not read live.
  - Live swap is a new disc image + relaunch; a restored save state keeps the old model in RAM; no verified RE4-specific RAM refresh.
  - Pickwhip: no RE4 GC camera/entity profile for the picker; live_inject has never written a model into a running game.
  - ... 4 more on the page
- **[Soul Calibur II (USA)](gamecube/soulcalibur2-gamecube.md)** (GameCube):
  - No SC2 build has been booted in Dolphin; none is in the Spark library
  - No live model/costume pointer write (costume +0x64 is only read at the body load)
  - CPUThread=False FIFO workaround still needs a select-to-match check
- **[Metal Gear Solid: The Twin Snakes (USA, 2 discs)](gamecube/twin-snakes-gamecube.md)** (GameCube):
  - Neither the disc swap nor the live RAM apply has been seen in Dolphin; loaded-copy layout comes from the decompile, not a RAM dump
  - Dolphin may keep the old texture cached until texel hashes are re-checked
  - REL runtime load address not recorded; every live step needs a paused 24 MiB MEM1 scan over the GDB stub
  - ... 1 more on the page
- **[Resident Evil 4: Wii Edition](wii/re4-wii.md)** (Wii):
  - Wii main.dol sha256 not pinned; re4_editions offsets are GC copies until relocated (locate() needs the Wii r13 for pG / player).
  - Player pointer, ItemMgr and the per-frame hook are not ported (re_games.WII_PAL P_PLAYER / ITEM_MGR / HOOK_SITE None): no bot, no live give/equip/blasts.
  - No RAM map file for RB4P08 in profiles/gamedata.
  - ... 4 more on the page
- **[Def Jam: Vendetta](ps2/defjam-vendetta-ps2.md)** (PlayStation 2):
  - boot a build in an emulator once (pick Briggs)
  - map the loaded wrestler buffers and the active fighters in EE RAM (needs a gameplay state, not an FMV)
  - FACE/hands are hidden, so expressions and finger poses are lost
  - ... 1 more on the page
- **[Grand Theft Auto: Liberty City Stories](ps2/gta-lcs-ps2.md)** (PlayStation 2):
  - cutscene Toni (csplr*/csplayer*, extra face bones) not retargeted
  - live reload of the player model via RequestSpecialModel 0x18FF80 through the gta_mods call queue is not built
  - gta_mods car_jump/ped_rain never run in a real pcsx2 session
  - ... 2 more on the page
- **[Grand Theft Auto III](ps2/gta3-ps2.md)** (PlayStation 2):
  - no live model replacement: a native RequestModel reload through the existing call queue is not built
  - full-body writer covers the player skins only (peds get faces only)
  - gta3_swap player body has no cited in-game frame
  - ... 3 more on the page
- **[Metal Gear Solid 2: Substance](ps2/mgs2-ps2.md)** (PlayStation 2):
  - first PCSX2 run of a cast build: drawing, strip parity, atlas TEX0/CLUT, second-texture flags (parts written as 0x48/0x49), stencil shadows, memory
  - read 0x1B9300 on a running session to confirm current_stage
  - in-RAM kms hot-patch so a swap shows without a stage load
  - ... 3 more on the page
- **[Final Fantasy VII](ps1/ff7-psx.md)** (PlayStation):
  - no RAM map of field/battle actors or the loaded model buffers
  - textures live in VRAM, which RetroArch cannot write, so a live swap would keep old textures
  - whole-cast builds and later/special scenes not checked in game
  - ... 1 more on the page
- **[Metal Gear Solid: VR Missions](ps1/mgs-vr-missions-psx.md)** (PlayStation):
  - no build seen in a live mission yet (VRAM placement and CLUT upload inferred)
  - no in-RAM KMD write: KMDs change only after a stage restart; textures in VRAM cannot be written through RetroArch
  - actor names of the ninja and stage-specific figures, GCL bytecode, stage geometry/collision undecoded
  - ... 1 more on the page
- **[Metal Gear Solid](ps1/mgs1-psx.md)** (PlayStation):
  - find which KMD the dock (s00a) actually draws for Snake: the init 39213 change was invisible
  - move MGS1 onto the native StageDir writer (no MetalMintSolid) and any donor, not HUcast only
  - no DEDICATED reader (replacement-readiness) and no RAM map of the MGS1 executable
- **[Parasite Eve](ps1/parasite-eve-psx.md)** (PlayStation):
  - enemy/NPC models in room packages (section C) have no writer
  - no RAM pointer to the loaded Aya model, so no in-RAM swap
  - textures are VRAM uploads, not writable through RetroArch
- **[WWF SmackDown! 2: Know Your Role](ps1/smackdown2-psx.md)** (PlayStation):
  - map which roster ids occupy the player slots in RAM (as the WCW N64 profiles do) for a pick whip
  - live reload of a part (re-run the part loader) is not built
  - portraits and names unchanged; SmackDown! 1 has no writer
- **[Puyo Puyo Tetris](ps3/puyo-puyo-tetris-ps3.md)** (PlayStation 3):
  - no asset reader or writer beyond the banner test
  - result/win flag address not mapped
- **[Resident Evil 5 Gold Edition](ps3/re5-ps3.md)** (PlayStation 3):
  - No modified PS3 ARC has ever been installed or booted in RPCS3: writers are offline-only and there is no folder-game mod/overlay launch path.
  - Writers cover two packs (Chris and Sheva normal); other costumes, Jill/Wesker/Excella (non-finite UVs), Irving (vertex type 4), NPCs and enemies have none.
  - No live model/costume/character RAM swap; the character only changes through the native menu (mercs_select, native_start_verified=false).
  - ... 4 more on the page
- **[Resident Evil 6](ps3/re6-ps3.md)** (PlayStation 3):
  - No live RPCS3 read has confirmed the sPlayer / sEnemy instances or any offset; menu cursor, timer and round readers missing (MercMode reason string).
  - No save map or native unlock routine (re6_ps3_unlock evidence chain unmet).
  - No uPl/uEm archive census, model reader or writer for PS3 RE6; Switch and X360 writers are explicitly not reused.
  - ... 1 more on the page
- **[Dead or Alive 2 - Limited Edition (Japan)](dreamcast/doa2-dreamcast.md)** (Dreamcast):
  - profiles/gamedata/1de2e7634f3161ff-ram.json, named in doa2_dc.py, is not in this checkout
  - the mixed random build and its confirm hook were never run in an emulator
  - no live costume pick: the select cursor record (base r12 + player<<7) has no fixed RAM address, so a RAM write at confirm in place of the exe hook is unmapped
  - ... 3 more on the page
- **[Jet Grind Radio (USA)](dreamcast/jet-grind-radio-dreamcast.md)** (Dreamcast):
  - the active player's native ID is not read from RAM: slot=player assumes Beat unless active_id is passed
  - no writer for ENEMY.AFS police and rival gangs, Professor K, select/title models or DEMO*.AFS scenes
  - live injection never run; PTEX/PVR textures live in VRAM and are not injected; the PLAY loader rewrites pointers in place
  - ... 1 more on the page
- **[Phantasy Star Online Ver. 2 (USA)](dreamcast/pso-v2-dreamcast.md)** (Dreamcast):
  - No enemy cast build has been checked in Flycast (Forest 1 Booma); docs/pso_enemy_swap.md, named as the live check, is not in this tree
  - Booma slot writes BM_ENE_BM1_SHARK_A.BML while the pick profile maps TObjEneBeast to BM_ENE_RE8_B_BEAST_A.BML - which pack Forest 1 loads is unconfirmed
  - Player class writer not working (weighted vertex chunks vs 11-sector file limit)
  - ... 1 more on the page
- **[Sonic Adventure 2 (USA)](dreamcast/sa2-dreamcast.md)** (Dreamcast):
  - only Sonic's slot is written: other playables, 2P/alt costumes (HSONIC/XSONIC/PSOSONIC), spin ball/board parts and event models are not
  - sa2_mods addresses never live-checked; CurrentCharacter untested as a character switch
  - no live model write (no POF0, VRAM textures); no RAM map json
- **[SoulCalibur (USA)](dreamcast/soulcalibur-dreamcast.md)** (Dreamcast):
  - no build after v3 seen in game; random hook randomness on Flycast TMU unverified
  - player struct costume field (+0x5C30) untested as a live costume switch
- **[007 - GoldenEye (Europe)](n64/goldeneye-n64.md)** (Nintendo 64):
  - No body swap has been built or booted; the library has no build
  - Budget heuristic uses only the first render node's triangles
  - No RAM map for the Europe cartridge in a running session
  - ... 1 more on the page
- **[WWF No Mercy (USA) (Rev A)](n64/no-mercy-n64.md)** (Nintendo 64):
  - No live model write: new parts need new file ids in a rebuilt file table, so no RAM-only swap path exists
  - pick_identify has no No Mercy backend; slots_on_screen is not wired into the whip
  - Writer is NW4E rev 1 only; Europe 2e8850a2a6c53375 refused
  - ... 2 more on the page
- **[The Legend of Zelda: Ocarina of Time (USA NTSC 1.0 / Rev B 1.2; Master Quest Europe GameCube Edition)](n64/oot-n64.md)** (Nintendo 64):
  - oot_hot_swap never shown working in game: a private cloned-save test stalled on a black frame with object DMA pending (docs/model_swaps.md #706)
  - No live writer for Link (player slot always goes to build + relaunch)
  - Live swap is NTSC 1.2 only (1aa2e4bb5797493f); 446e8e442d726e31 (1.0, the cast ROM in oot_cast.md) and the GC MQ ROM get build mode; gc-eu-mq has no entry in oot.LAYOUTS so no live RAM tools at all
  - ... 4 more on the page
- **[Super Mario 64 (catalog USA and Europe entries; both hold the PAL NSMP ROM)](n64/sm64-n64.md)** (Nintendo 64):
  - RDRAM hot swap has only fake-adapter tests (tests/test_live_link_identity.py); no in-game proof
  - Only Mario is a slot; pick does not project other objects, so the whip cannot target anything else
  - Hot swap needs the session's current seg04 to match the previous build or vanilla exactly; another build or save state means relaunch
  - ... 2 more on the page
- **[WCW/nWo Revenge (USA)](n64/wcw-revenge-n64.md)** (Nintendo 64):
  - No live write path or point picking
  - aki_wrestling.needs() and PROFILES still describe Revenge as reader-only although aki_wcw has the writer (stale text)
- **[WCW vs. nWo: World Tour (USA)](n64/wcw-world-tour-n64.md)** (Nintendo 64):
  - No in-game frame of a World Tour replacement is cited
  - No live write path or on-screen slot boxes (No Mercy's slots_on_screen not ported)
  - Body/costume tables are boot-segment data; a live swap would also need the new files loaded
- **[Dead or Alive 3 (USA)](xbox/doa3-xbox.md)** (Xbox):
  - no costume index in the RAM map (only character), so there is no live costume select
  - general GuestMemory.write has no live receipt; only the pad block is exercised; xbox-launch.md still says no writes
  - no save state, so a build swap loses the moment; no live model inject for Xbox
  - ... 1 more on the page
- **[Resident Evil 6](xbox360/re6-xbox360.md)** (Xbox 360):
  - No live body swap: a new build needs a relaunch and re-picking the native character; Xenia adapter has no save state, so no keep-the-moment session_swap.
  - Untested whether the proven live sResource load (uWp arcs) can load a modified uPl body arc into a round; doc claims the engine does not support it.
  - No active-character detection: which native slot/costume is playing is not read (loadout record char/costume bytes exist but are not wired).
  - ... 4 more on the page
- **[Super Mario Bros. (World)](nes/smb1-nes.md)** (NES):
  - No live sprite write: tiles are in CHR-ROM and the table/palettes in PRG; ghost_runs says injection needs a ROM patch (OAM rewritten every frame)
  - The Sonic build changes PRG tables, so tas.rebind_graphics (CHR-only variants) cannot carry native tapes onto it
  - Writer covers only Sonic 2 -> SMB1 player
<!-- atlas:gaps:end -->

## Writers without a page yet

<!-- atlas:unpaged:begin -->
14 writer modules (`*_swap.py`, `*_writer.py`, `*_cast.py`, `*_mods.py`, `*_mod.py`) are not cited by any atlas page yet - games gBox can mod whose builds were never archived to the library, or helpers. Research them next:

`gbox/built_mods.py`, `gbox/clayfighter_swap.py`, `gbox/crazy_taxi2_swap.py`, `gbox/dmc3_mod.py`, `gbox/doapp_swap.py`, `gbox/etm_swap.py`, `gbox/gta_vc_swap.py`, `gbox/merc3d_mod.py`, `gbox/mvc2_writer.py`, `gbox/overlay_swap.py`, `gbox/pe2_swap.py`, `gbox/sa1_writer.py`, `gbox/sonic1_swap.py`, `gbox/stranglehold_swap.py`
<!-- atlas:unpaged:end -->
