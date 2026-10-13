# Whole-cast swap: one game's entire cast as another game's (`gbox/cast_swap.py`)

The operator's ask: "replace the entire cast of one game with the entire cast of another game", e.g. everyone in
Phantasy Star Online as wrestlers (Def Jam Vendetta, SmackDown! 2, No Mercy / WCW entries) or as the Jet Grind Radio
crew, each donor looking like its own game's character (no outline shell, correct textures).

## Use it

* **Chat / agent**: "replace everyone in PSO with wrestlers", "the entire cast of JGR as SA2 characters". The agent
  prompt and the `mashup` planner (`mashup.parse_cast_request`) route these to `characters op=cast_swap`, never to a
  loop of `op=use`.
* **Tool**: `characters op=cast_swap target_game=<id|title> source=<game id|title|abbreviation|group>
  [mapping=auto|random|by_role] [seed] [slots=all|main|enemies|pedestrians|<slot list>] [assignments=[{slot,
  character}]] [plan_only=true] [launch=true]`. `plan_only` returns the plan (nothing is built, nothing re-extracted).
  Launching happens only when `launch` is passed explicitly.
* **Desktop / web**: right-click a game in the library (the web client's game menu, also inside the desktop shell) or
  a conversation's game chip in the desktop shell -> **Replace entire cast with...** -> pick a source (groups first:
  Wrestlers, Fighters, Sega; then every source game of the collection with its usable count), a mapping, the slots
  (everyone / main cast / enemies) and an optional seed -> **Plan the cast** shows every target slot with the donor's
  thumbnail and a picker of all eligible donors ("leave as it is" drops a slot) -> **Build one mod** queues the job on
  the Spark and shows the per-slot report. The dialog is `clients/web/viz/cast-swap.js`; the API behind the plan is
  `GET /api/cast_swap/sources?game_id=` and `POST /api/cast_swap/plan`; the build is a `characters op=cast_swap` job.

## How it works

1. **Slots** come from the target's writer (`char_coverage.cast_slots` -> the writer module's `cast_slots()`, or
   `cast_slots_live(ctx, game)` when the list has to be read off the game: Vice City's peds). Aggregates
   (`enemy:boomas`, `enemies`, `drivers`, `pedestrians`, `passengers`, `peds:all`, Def Jam's / No Mercy's `player`)
   and aliases (JGR's and Crazy Taxi's `player` = Beat / Axel) are dropped so each model gets exactly one donor.
   Slots a writer marks `not_working` (the PSO player class: the game doesn't draw it yet) are listed as skipped.
2. **Donors**: every collection entry of the source (`resolve_source`: a group, a game id, a DEDICATED extractor name,
   or title words with abbreviations like PSO / JGR / SA2 / SD2 / DOA2; comma lists combine sources). Head-size
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
   slots, then deals donors by body size: the slot's `size` hint (PSO enemies: Gigobooma 1.4, Dark Belra 1.7, Rappy
   0.7 ...; DOA2: Bass 1.3, Tengu 1.25, Kasumi 0.9 ...) against the donor's height relative to its own game's cast
   (glTF accessor bounds, read on the control plane). `random` deals a seeded shuffle. Operator edits
   (`assignments`) override single rows.
5. **One build** (`build` -> `BUILDERS[writer]`), per slot `built` / `partial` / `failed` with the reason, plus the
   skipped slots; the mod's `.gbox-mod.json` gets a `cast` list and every built donor a target record. The same
   plan reuses its mod (`cast_<game>_<source>_<plan digest>`) unless `rebuild`.

| Writer | Multi-slot path | Status |
|---|---|---|
| PSO Ver.2 (`gbox.pso_player` / `pso_enemy`) | **pairs**: `pso_enemy.build_cast` -> `build_swap` with a donor per enemy body; each pack rebuilt once, one `patch_gdi` | every enemy slot (Booma family + the 16 other packs); a failing body (pack room, unmappable skeleton) fails alone; the player class is skipped (not drawn yet) |
| DOA2 (`gbox.doa2_swap`) | **pairs**: `use_roster` (every selectable fighter in one disc) | full cast (14 fighters); the roster needs every fighter, so `slots=` subsets fail with plan_roster's reason |
| Def Jam Vendetta PS2 (`gbox.defjam_writer`) | **pairs**: `match` (one data.bin) | full cast (44 names, every costume) |
| SmackDown! 2 (`gbox.yukes_sd`) | **pairs**: `match` | full cast (66 wrestlers) |
| No Mercy (`gbox.aki_wrestling`) | **pairs**: `match` (one ROM) | full cast (64 default wrestlers); WCW World Tour / Revenge rosters come off their ROMs, not listed yet |
| Vice City PC (`gbox.gta_vc_swap`) | **pairs**: `build_cast` (every ped its own donor, one gta3.img rebuild) | full cast on a classic RenderWare install; the owned install is the UE4 Definitive Edition, so every slot fails with that reason |
| JGR (`gbox.jgr_swap`) | **chain**: each cast member's `jgr.build_swap(..., data=)` on the previous step's PLAYER.AFS, one `patch_gdi` | full cast (16) |
| Crazy Taxi GC (`gbox.crazy_taxi_swap`) | **chain**: each slot's `swap_bank` on the previous step's polDC0.all, one disc image | full cast (4 drivers, 19 pedestrian and 31 passenger groups) |
| Single-slot writers (SM64, GTA III, LCS, PE, PE2, FF7, SA2, MGS, RE4 GC, RE6, Metal Arms, Clay Fighter) | one slot per mod (`characters op=use`) | the player only; other slots are listed as skipped with the reason (RE6 enemy families, Metal Arms bots picked on screen, Clay Fighter fighters, which also need sprites donors) |

**The chained path** (`cast_swap.chain`) is the common route for writers without a pairs API: the changed files are
staged once (`{path: bytes}`, never the original image), each slot's writer step reads the staged bytes (or a disc
through `StagedDisc`) and returns its new bytes, a failing step leaves the staged files untouched and is reported, and
the writer writes the image once at the end. A writer joins by getting an entry in `BUILDERS` that builds its steps.

## Tests

* `tests/test_cast_swap.py`: slot enumeration (PSO, JGR, Crazy Taxi, Def Jam, DOA2), sources (groups, titles, ids,
  extractors, comma lists), costume dedupe, the retarget check, the stale-reader re-extract trigger (gate +
  `_refresher` + `reader_status`), determinism and the by_role rules, edits, the chain with fake writers (each step
  sees the previous output; failures isolated), one-mod builds with per-slot reports and plan reuse, the JGR chain
  builder, the PSO pairs build on synthetic enemy packs and a synthetic GDI (`build_swap` donors per enemy,
  `build_cast` writes one image, never the original), the API endpoints, the tool / mashup / agent routing.
* `tests/test_cast_swap_menu.cjs`: the source picker, the editable plan rows, the edits sent, the controller's plan
  -> build -> report flow, failures, and the menu entries in both clients.
