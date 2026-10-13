# Whole-cast swap: one game's entire cast as another game's (`gbox/cast_swap.py`)

The operator's ask: "replace the entire cast of one game with the entire cast of another game", e.g. everyone in
Phantasy Star Online as wrestlers (Def Jam Vendetta, SmackDown! 2, No Mercy / WCW entries) or as the Jet Grind Radio
crew, each donor looking like its own game's character (no outline shell, correct textures).

## Use it

* **Chat / agent**: "replace everyone in PSO with wrestlers", "the entire cast of JGR as SA2 characters". The agent
  prompt and the `mashup` planner (`mashup.parse_cast_request`) route these to `characters op=cast_swap`, never to a
  loop of `op=use`.
* **Tool**: `characters op=cast_swap target_game=<id|title> source=<game id|title|abbreviation|group>
  [mapping=auto|random|by_role] [assign=random] [seed] [prefer=<source>] [slots=all|main|enemies|bosses|npcs|bots|
  campaign|pedestrians|<comma list of groups / slots>] [assignments=[{slot, character}]] [plan_only=true]
  [launch=true]`. `plan_only` returns the plan (nothing is built, nothing re-extracted). Launching happens only when
  `launch` is passed explicitly.
* **Random from a source, any game** (#1385: "replace ... with randomly selected characters from SA2"):
  `assign=random seed=<x>` deals the source's donors at random over the chosen slots, the same way as the cast plan's
  "Deal ticked donors" (PR #291). The deal is seeded, so the same seed gives the same cast. No donor repeats before
  every donor has been used, and every character name is dealt once before any name repeats (The Rock of No Mercy and
  The Rock of SmackDown! 2 count as one name, `name_key`). `assign` wins over `mapping`; the mashup planner sets it
  when a request says "random". `prefer=<source spec>` puts that part of the source first, for example
  `source=wrestlers prefer=smackdown2,nomercy` for "wrestlers, WWE first".
* **Desktop / web**: right-click a game in the library (the web client's game menu, also inside the desktop shell) or
  a conversation's game chip in the desktop shell -> **Replace entire cast with...** -> pick a source (groups first:
  Wrestlers, Fighters, Sega, Sonic; then every source game of the collection with its usable count), a mapping, the slots
  (everyone / main cast / enemies) and an optional seed -> **Plan the cast** shows every target slot with the donor's
  thumbnail and a picker of all eligible donors ("leave as it is" drops a slot) -> **Build one mod** queues the job on
  the Spark and shows the per-slot report. The dialog is `clients/web/viz/cast-swap.js`; the API behind the plan is
  `GET /api/cast_swap/sources?game_id=` and `POST /api/cast_swap/plan`; the build is a `characters op=cast_swap` job.

## How it works

1. **Slots** come from the target's writer (`char_coverage.cast_slots` -> the writer module's `cast_slots()`, or
   `cast_slots_live(ctx, game)` when the list has to be read off the game: Vice City's peds, AUF's level cast). A row
   may list `groups` it belongs to; `slots=` matches groups, kinds and slot names, and a comma list is their union
   (`slots=campaign,bots`, `slots=player,bosses,npcs,bots`). Aggregates
   (`enemy:boomas`, `enemies`, `drivers`, `pedestrians`, `passengers`, `peds:all`, Def Jam's / No Mercy's `player`)
   and aliases (JGR's and Crazy Taxi's `player` = Beat / Axel) are dropped so each model gets exactly one donor.
   Slots a writer marks `not_working` (the PSO player class: the game doesn't draw it yet) are listed as skipped.
2. **Donors**: every collection entry of the source (`resolve_source`: a group, a game id, a DEDICATED extractor name,
   or title words with abbreviations like PSO / JGR / SA1 / SA2 / SD2 / DOA2; comma lists combine sources; a title
   match leaves out sequels the request doesn't number: "Sonic Adventure" is SA1 only, the `sonic` group is SA1 + SA2,
   see docs/sa1_reader.md). Head-size
   variants are left out and costumes of one character collapse onto one donor (`dedupe`: Briggs costumes 1-3 -> one).
3. **Quality gate** (`gate`):
   * an entry made by an older DEDICATED reader than the current one is **re-extracted before the build**
     (`characters.reader_status` / `READER_VERSIONS`; today JGR: entries without `jgr_reader: 2` carry the v1
     cel-shading outline shell and wrong per-group textures). `characters.extract_dedicated` uses the same check.
     A plan only flags them ("will be re-extracted"); a failed re-extraction refuses the donor with the reason.
   * an entry that fails the collection's retarget check is **refused with the reason**: no body roles, no hip, or
     (on the control plane) the model / preview check (`characters.verify_entry`) fails.
4. **Mapping** (`assign`, deterministic for the same slots, donors, mapping and seed; no donor repeats before every
   donor has been used): `by_role` (and `auto`) puts lead characters (`native_player`, a player/hero alias) on player
   slots (or, when the target has no player slot of its own, on the slot its `player` alias names: Crazy Taxi's Axel),
   then deals donors by body size: the slot's `size` hint (PSO enemies: Gigobooma 1.4, Dark Belra 1.7, Rappy
   0.7 ...; DOA2: Bass 1.3, Tengu 1.25, Kasumi 0.9 ...; Crazy Taxi drivers: Gus 1.15, Axel / Gena 1.0, B.D. Joe 0.97,
   measured from their parts in polDC0.all) against the donor's height relative to its own game's cast
   (glTF accessor bounds, read on the control plane). `random` deals a seeded shuffle. Operator edits
   (`assignments`) override single rows.
5. **One build** (`build` -> `BUILDERS[writer]`), per slot `built` / `partial` / `failed` with the reason, plus the
   skipped slots; the mod's `.gbox-mod.json` gets a `cast` list and every built donor a target record. The same
   plan reuses its mod (`cast_<game>_<source>_<plan digest>`) unless `rebuild`.

| Writer | Multi-slot path | Status |
|---|---|---|
| PSO Ver.2 (`gbox.pso_player` / `pso_enemy`) | **pairs**: `pso_enemy.build_cast` -> `build_swap` with a donor per enemy body; each pack rebuilt once, one `patch_gdi` | every enemy slot (Booma family + the 16 other packs); a failing body (pack room, unmappable skeleton) fails alone; the player class is skipped (not drawn yet) |
| DOA2 (`gbox.doa2_swap`) | **pairs**: `use_roster` (every selectable fighter in one disc) | full cast (14 fighters); the roster needs every fighter, so `slots=` subsets fail with plan_roster's reason |
| SoulCalibur DC (`gbox.soulcalibur_swap`) | **pairs**: `build_cast` (every slot's costumes rebuilt in their own HUMAN.DAT slots, one GD-ROM) | full cast (19 fighters, 45 costumes); `characters op=use slot=roster` adds the random costume hook (docs/soulcalibur_dc.md); unverified in game |
| Def Jam Vendetta PS2 (`gbox.defjam_writer`) | **pairs**: `match` (one data.bin) | full cast (44 names, every costume) |
| SmackDown! 2 (`gbox.yukes_sd`) | **pairs**: `match` | full cast (66 wrestlers) |
| No Mercy (`gbox.aki_wrestling`) | **pairs**: `match` (one ROM) | full cast (64 default wrestlers); WCW World Tour / Revenge rosters come off their ROMs, not listed yet |
| Vice City PC (`gbox.gta_vc_swap`) | **pairs**: `build_cast` (every ped its own donor, one gta3.img rebuild) | full cast on a classic RenderWare install; the owned install is the UE4 Definitive Edition, so every slot fails with that reason |
| Enter the Matrix PS2 (`gbox.etm_swap`) | **pairs**: `build_cast` (every slot's costume / variant .dcn files rewritten in one WAD1.DFU, in place) | 37 slots (Niobe, Ghost, Agents, Trinity, Morpheus, Neo, Seraph, SWAT, police ...); the catalog's windows_native entry is the PS2 disc; unverified in PCSX2 (docs/matrix_pipeline.md) |
| Metal Gear Solid 2 Substance PS2 (`gbox.mgs2_swap`) | **pairs**: `build_cast` (every slot's kms models in every stage that carries them, one STAGE.DAT / STAGE2.DAT image, in place) | 18 slots (Snake, Pliskin, Raiden x3, the soldier variants, Marines, Olga, Ninja, Ocelot, Solidus, Otacon); the catalog's windows_native entry is the PS2 DVD; unverified in PCSX2 (docs/mgs2.md) |
| Ocarina of Time N64 (`gbox.oot_swap`) | **pairs**: `oot_swap.build_cast` (every slot's object rebuilt on the previous slots' output, one ROM: DMA + gObjectTable + CRC; object growth shared out per room) | 85 slots (Link, NPCs, sages, enemies, bosses: `docs/oot_cast.md`); Epona, Navi, Like Like, En_Hy townsfolk skipped with the reason |
| Twin Snakes GC (`gbox.twin_snakes_swap`) | **pairs**: `build_cast` (every slot's model in every gameplay stage of one stage.dat, rebuilt in place) | Snake, every Genome soldier model (+ low-detail twins), bosses, Meryl / Otacon / Johnny (`docs/twin_snakes.md`); cut-scene stages stay stock; unverified in Dolphin |
| Soul Calibur II GC (`gbox.soulcalibur2_swap`) | **pairs**: `build_cast` (every slot's costume packages, Extra-mode copies included, rewritten in place in human.olk; one disc image) | all 24 fighters (Link included), 73 costumes; `slot=random` alternates two donor pools over each fighter's costumes and patches the body load to draw a costume at random (`docs/soulcalibur2_gc.md`); unverified in Dolphin |
| JGR (`gbox.jgr_swap`) | **chain**: each cast member's `jgr.build_swap(..., data=)` on the previous step's PLAYER.AFS, one `patch_gdi` | full cast (16) |
| Crazy Taxi GC (`gbox.crazy_taxi_swap`) | **chain**: each slot's `swap_bank` on the previous step's polDC0.all, one disc image | full cast (4 drivers, 19 pedestrian and 31 passenger groups) |
| 007 Agent Under Fire GC (`gbox.auf_swap`) | **pairs**: `auf_swap.build_cast` (every level's restable rebuilt once with all its donors, one disc image; the level cast read off the disc) | 57 slots: `campaign:<body>` x 40 (Bond, henchmen, bosses, allies, hostages) and `mp:<body>` x 17 (16 bots + the escort VIP); groups campaign, multiplayer, bots, bosses, npcs, enemies, player, model:<body> (docs/auf_writer.md) |
| Metal Gear Solid VR Missions PS1 (`gbox.mgs_vr_swap`) | **pairs**: `mgs_vr_swap.build_cast` (every slot fitted into one staged STAGE.DIR: each mission stage's copy of a model and its texture archive, native rewrite, one BIN) | 7 slots: player (Snake), enemy:soldier (38582 + 55267 in 88 stages), enemy:ninja and four stage-specific figures; a node without the disc image hands the build to a Windows worker (`characters op=use slot=cast`); unverified in game (docs/mgs_vr_decomp.md) |
| Single-slot writers (SM64, GTA III, LCS, PE, PE2, FF7, SA2, MGS disc 1, RE4 GC, RE6, Metal Arms, Clay Fighter) | one slot per mod (`characters op=use`) | the player only; other slots are listed as skipped with the reason (RE6 enemy families, Metal Arms bots picked on screen, Clay Fighter fighters, which also need sprites donors) |

**The chained path** (`cast_swap.chain`) is the common route for writers without a pairs API: the changed files are
staged once (`{path: bytes}`, never the original image), each slot's writer step reads the staged bytes (or a disc
through `StagedDisc`) and returns its new bytes, a failing step leaves the staged files untouched and is reported, and
the writer writes the image once at the end. A writer joins by getting an entry in `BUILDERS` that builds its steps.

**Fixed names (`mod_name=`, the Sonic showcase).** `mod_name=showcase_sonic_<title>` builds into that folder instead of
`cast_<game>_<source>_<digest>`; the marker's `cast_plan` (`plan_digest`: which donor on which slot) then decides a
rebuild, so an unchanged plan is reused and a changed one rebuilt. `showcase=true` adds the `showcase` record to the
marker and skips the Play-as character targets. A writer that names its own build (DOA2 roster, one-slot writers) gets
a hard-linked copy under the fixed name (`link_tree`). See docs/sonic_showcase.md.

## Tests

* `tests/test_cast_swap.py`: slot enumeration (PSO, JGR, Crazy Taxi, Def Jam, DOA2), sources (groups, titles, ids,
  extractors, comma lists), costume dedupe, the retarget check, the stale-reader re-extract trigger (gate +
  `_refresher` + `reader_status`), determinism and the by_role rules, edits, the chain with fake writers (each step
  sees the previous output; failures isolated), one-mod builds with per-slot reports and plan reuse, the JGR chain
  builder, the PSO pairs build on synthetic enemy packs and a synthetic GDI (`build_swap` donors per enemy,
  `build_cast` writes one image, never the original), the API endpoints, the tool / mashup / agent routing.
* `tests/test_cast_swap_menu.cjs`: the source picker, the editable plan rows, the edits sent, the controller's plan
  -> build -> report flow, failures, the menu entries in both clients, and a target's own slot sets (AUF's
  Campaign + multiplayer bots).
* `tests/test_cast_swap.py` (AUF): the 57 context slots cover the 372 (level, body) pairs once; the group filters
  (`campaign`, `bots`, `player,bosses,npcs,bots` -> 48); `assign=random` over SA2 (every character once per round,
  seeded) and on PSO; `prefer=` with cross-game name dedupe (`spread`, `name_key`); the mashup's "randomly" ->
  `assign=random`. The AUF build path itself is tested in `tests/test_auf_swap.py`.

## 007 Agent Under Fire builds (#1529, #1385)

`auf_cast_wrestlers` (57/57 slots, distinct WWF wrestlers) and `auf_cast_sonic_random` (56/56 slots, SA2 at random
over the campaign and the bots) were built with the calls in docs/auf_writer.md section 5. They were read back level
by level and booted in an agent-owned Dolphin: the first mission's cut scene and bot matches showed the donors. The
frames are in `D:\gBox\research\auf\evidence\`.

## Live check (2026-10-13, test PC, read-only)

Run from the Windows test PC against the live control plane with GET requests only (no job, no build, no launch: the
branch is not deployed, and builds run on the Spark). The live `/api/characters` answered 500, so the collection was
read per source game (`/api/games/<gid>/roster` + `/api/characters/<slug>`: 248 entries) and `cast_swap.plan` ran
locally on it for PSO Ver.2 (USA, `daba7a3b195dcf6b`), `mapping=by_role seed=live-1`:

* **PSO <- Def Jam wrestlers: nothing to build yet.** The only Def Jam entries in the live collection are the 57
  GameCube ones (`gbox.defjam_vendetta`: static meshes, rig not decoded): the gate refuses every one with "no body
  roles (rig.roles): the model is not mapped onto a skeleton". The PS2 reader (`defjam_vendetta_ps2`, rigged, with
  roles) has not run on the live server (its roster endpoint reports no extractor for `deabd11481aa5a0c`, collection
  state "unsupported"), so `characters op=collect game_id=deabd11481aa5a0c` on a deployed build is the next step; with
  those 58 entries the same call plans Def Jam donors (44 names after the costume merge).
* **PSO <- wrestlers: planned.** 19 enemy slots (Booma, Gobooma, Gigobooma + 16 packs) get 19 different donors from
  175 usable No Mercy / World Tour / SmackDown! 2 entries (57 Def Jam GC entries refused, reason above); the PSO
  player class is listed as skipped (not drawn by the game yet). Mod `cast_phantasy_star_onli_wrestlers_no_mercy_55851431`.
* **PSO <- JGR: planned, all 16 donors stale.** Every live JGR entry is still reader v1 (no `jgr_reader`), so the plan
  lists all 16 as "will be re-extracted (reader v1 -> v2)": the build re-extracts them (outline shell gone, per-group
  textures) before fitting; 19 slots over 16 donors, so three repeat after the first full round.

Heights were unknown in this run (the library isn't on this PC), so by_role fell back to the seeded order; on the
Spark the menu's plan reads them. The building half was checked on synthetic data only (tests above); the in-game
check of a built cast mod (Forest 1 Boomas, docs/pso_enemy_swap.md) is still to do.
