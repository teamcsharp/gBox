# DeepSeek task guide: Phantasy Star Online, decrypted, broken down and played (2026-11-09)

Written for the DeepSeek session on the i9-NUC. The operator, 2026-11-09 ~22:40 UTC: "the deepseek task is failing so
you [the RE5 session] will take over for the RE6 task as well. Instead let's have deepseek resume and finish the tasks
for decrypting and breaking down pso for autoplay."

So: **stop RE6** (the RE5 session on JAYBUILTFINALE owns RE4/RE5/RE6 from now), **resume PSO**. Read §1 to §3 once,
then take the packages in order; each has an acceptance test.

---

## 0d. PM note, 2026-11-10 ~10:20 UTC: the operator's three goals, how to work on the i9, full speed (read this first)

The operator, 2026-11-10: "I want that game fully decrypted and able to be given this same treatment and have it
decrypted enough that levels can be expanded and layouts changed in a custom editor and the character can be hot
swapped with any of the models from the collection. I need it going full blast on that."

"This same treatment" means what the Resident Evil titles have in MercMode: an autobot that plays, live mods, and
the cast swapped with characters from gBox's character library.

The three goals, each with a test the operator can see:

1. **Decrypted and broken down.** This is §4 P2 (every disc format decoded, with byte-identical round trips) and P2b
   (the executable mapped). "Decrypted" here mostly means decoded: PRS compression, the GSL / AFS / BML containers,
   the NJ / XJ models, the XVM / GVM textures, the map files. Name anything that is genuinely encrypted or checksummed
   (the save data, a network blob) and how it is keyed.
2. **A custom level editor: layouts changed and levels expanded.**
   - **P6a.** The map writer: the area's geometry and collision (`map_*_n.rel` / `c.rel`), the object and enemy sets
     (`*.dat`), the events (`*.evt`), written back from an edited model with round-trip tests.
   - **P6b.** The editor itself, as a page of the gBox desktop client following the live map's look (`system/clients`).
     It shows a top-down view of an area's floor and walls from its collision. Objects, enemies, doors, switches and
     teleporters are draggable markers that can be added and deleted. Its save writes the map files, builds the disc
     and launches it in Dolphin on the i9.
   - **P6c.** Expansion: rooms added by reusing the area's own room pieces (geometry and collision placed and joined),
     with the bot's navigation graph (P3) rebuilt from the edited map.
   - Accept on: an edited Forest 1 (objects moved, a room added) that boots, and that the bot walks through to the next
     area.
3. **Characters hot-swapped with any model from the collection.**
   - **P7a.** A PSO player-model writer that retargets a library donor onto the PSO player skeleton: the same donors
     and donor seam the RE5 cast writer uses (`gbox/re5_donor_pool.py`, `re5_cast_writer.py`, the character library
     the extract jobs feed). Start with one class's body and a T-posed donor.
   - **P7b.** The swap, in two steps:
     - first per boot: a build with the donor in the class's model file;
     - then hot: find where PSO keeps the loaded player model in RAM (P2b) and whether an area change reloads it from
       disc. Then make "pick a donor in the gBox app; it appears at the next area load without restarting Dolphin"
       work, by rewriting the loaded model or by switching the file the next load reads.
   - Accept on: two different library donors played in one session, swapped without a Dolphin restart, with frames.

**Working locally on the i9 (your machine).**
- **Your checkout.** gBox's worker on the i9-NUC runs its own checkout, `C:\_tools\gBox`. Fast-forward it to
  `origin/main` yourself (`git -C C:\_tools\gBox fetch` / `merge --ff-only`); nobody else can reach that disk. Work
  in your own git worktree on a branch.
- **Data.** PSO Episode I & II (GameCube) is in the gBox library. Its extracted files, your Ghidra project and all
  builds and caches go on `D:`, never `C:`, never in git.
- **Builds.** gBox already writes modified PSO builds that Dolphin boots (`pso_face_build`, the `extract_pso_*` jobs).
  Reuse that build path for the editor's maps and the swapped models rather than inventing a new disc rebuilder.
- **Play and test** in Dolphin through the i9 worker. The co-op bot and the ViGEm virtual pads are already there: one
  pad per player, and presses land without window focus (`adapters.DolphinWinAdapter._setup_vpad`).
- **Deploy-gated routes:** `x-gbox-actor: deploy` with `system/gbox-data/api_token`.
  - Bot reload: `POST /api/workers/i9-NUC/bot-reload`.
  - Fast-forward the worker's checkout: `POST /api/workers/i9-NUC/update-repo`, when it is registered.
- **Known traps** (§2 and the memory of 11-03/04):
  - only one gBox worker stack may run on the i9; two gamepad watchers fight the pad;
  - `pso_survival` / `pso_master_build` / `pso_boss_strategy` / `pso_speed` reload only when `pso_coop` reloads;
  - a dead autobot looks like a standing character: check telemetry `age_s` and `bot.running`.
- Never stop a session whose launch actor is `operator`.

**Full speed.**
- Use the i9's cores, fast disk and GPUs for decoding, building and Ghidra.
- Hermes is fully available: 28 lanes (lilspark2 plus the paid DeepSeek / Claude / Z.AI nodes, which work the
  operator's priority list). For bulk, independent pieces (one format's decoder and round-trip tests, one area's file
  catalogue, one boss's RAM fields), file Hermes tickets with an acceptance test and ask for them on the priority list.
  Review what comes back before it goes on main.
- Keep your own lane on the hard, serial parts: the executable map, the map writer, the editor, the model writer.

**Order.** P2 + P2b together, then P1 (boot to the field by itself), then P6a / P7a as soon as their formats are
decoded, then P6b / P7b, then P3-P5. A round doc entry per step in `docs/ds-pso-lane-2026-11-10.md`: what, the
commits, the evidence, what is next.

## 0c. PM note, 2026-11-10 ~09:00 UTC: PSO only, decryption and breakdown first (superseded by 0d where they differ)

**RE6 is no longer yours, in any part.** Thank you for the handover (`HANDOVER-i9-re6-2026-11-10.md`). The RE session
has taken it over on lilspark and it plays again:

- The cause of the crashes was the version. Since 11-05, lilspark ran RE6 from a local cache folder that held only
  the base NSP. The 1.0.2 update (`[01002A000CD48800][v131072]`) is now copied beside it, so Eden applies it.
- RE6 is back in the MercMode rotation. A round played Mining the Depths: 195 kills, 1 death, `recovery-re6-update-exefs-20261110`.
- The bot fixes are on main (`46dc0750`): the stuck native equip, standing through grenade throws, and remote bombs
  (placed every 10 s, 20x throw speed, detonated with one enemy on them).

Do not start, stop or build anything RE (RE4/RE5/RE6) from now on. If you find a bug in your Switch decryption
modules (`switch_nca`, `switch_bktr`, `switch_patch`, `switch_extract`, `switch_decrypt`, `switch_arc`), write it in
your lane doc; do not fix RE code paths.

**Your task, in the operator's words of 2026-11-10: "analyzing, breaking down, and fully decrypting PSO".** That
means, for Phantasy Star Online Episode I & II (GameCube), these two things, in this order:

1. **The disc, fully decoded:** §4 P2.
2. **The executable, fully mapped:** P2b below.

Then P1 (boot to the field by itself), which P2b makes much easier, and P3-P6 as written.

**What is already there and what is not (checked on main 2026-11-10):**
- Not on main: no `docs/research/pso-gc-*.md`. The spark2 tickets #9182-#9184 (the disc's formats, the containers
  and compression, the map geometry and enemy sets) produced nothing on main. Check their state in the inbox; if
  they are not done, P2 is wholly yours. Do not wait for them.
- Not on main: no PSO lane doc of yours and no PSO code commit since 11-09.
- Present: the code base §2 lists (`gbox/pso_*.py`, `psomap.py`, `psoitems.py`, `psotext.py`, `pso_rom_export.py`)
  and the extract jobs (`extract_pso_model`, `extract_pso_area`).
- Present: the player RAM in §2 (slot table `0x8050EA10`).
- Hermes now has 64 lanes: lilspark2 (local) 32, plus three paid nodes (Claude 16, DeepSeek 24, Z.AI 16). You may
  file Hermes tickets for bulk, independent pieces, such as one format's round-trip tests or one area's catalogue.
  Give each ticket an acceptance test, and review what comes back before it goes on main.

### P2b. Map the executable (new; do it beside P2)
The GameCube executable (`main.dol` on the disc) in Ghidra:

- the DOL loaded at its section addresses;
- the SDK / runtime libraries identified;
- then the game's own functions named, for every system the bot and the mods touch:
  - the game phase and its state machine: title, PRESS START, menus, Pioneer 2, field, boss, death;
  - the menu cursor and selection bytes (P1 needs these);
  - the floor/area load and the warp;
  - the player and enemy objects (layouts, HP, position, AI state, the attack wind-ups);
  - items and the inventory, the mag;
  - the map loader (what reads `*.rel` / `*.dat` / `*.evt`, and with which layouts);
  - the boss part counters;
  - anything encrypted or checksummed on disc or in save data (name the cipher and its key source).

Output:
- `docs/research/pso-gc-executable.md`: every address with what it is and how it was proven (a decompiled function,
  a live RAM watch with the session id);
- a Ghidra project or exported symbol file on the i9's `D:` (never in git);
- `gbox/pso_ram.py`: the addresses as named constants with readers, with tests on synthetic memory.

Accept on: P1's menu walk using only RAM-read state from this map, and the map loader's file layouts matching P2's
decoders.

**Order and pace:** P2 and P2b in parallel, then P1, P3-P6. Append each round to `docs/ds-pso-lane-2026-11-10.md`
on main: what you decoded, the commits, the evidence, what is next. The first round doc is due after your first
package step, not at the end.

## 0b. PM note, 2026-11-10 01:30 UTC: stop RE6 now, hand it over, start PSO (superseded by 0c)

Rounds 16-21 are good findings and are on main (`5812b22b` .. `259b45eb`): an RE6 round runs on the update-only
ExeFS build, a single arc swap plays, the 45-arc roster does not, and the heads-only build deadlocks after the save.
But they are RE6, and the operator's words were: "the deepseek task is failing so you will take over for the RE6
task as well. Instead lets have deepseek resume and finish the tasks for decrypting and breaking down pso for
autoplay." So, in this order and nothing else:

1. **Amended 02:40 UTC: finish the roster bisect, then stop RE6.** Rounds 22-25 found the Helena head donor and
   then the AcHead group: you are one bisect from the answer. Name the bad AcHead donor(s) (the RAM-driven nav, as
   your round 25 says), publish the working roster build without them, and stop RE6 there.
2. **Hand it over in five lines** at the end of your i9 lane doc: the build ids that exist now
   (`recovery-re6-update-only-20261109b`, `recovery-re6-update-roster-v1` and any other), the 45 donor arc names with
   their sha256 or artifact ids (or the path of the list), which donor files are missing from the cache, the Yuzu
   config you used on the i9, and the exact launch you ran per bisect row.
3. **Then PSO, §4 P1 first** (boot to the field by itself). spark2's PSO breakdown is your input:
   `docs/research/pso-gc-*.md` from Hermes tickets #9182-#9184; read them before P2.

Your Switch decryption modules stay yours and in use (`switch_nca`, `switch_bktr`, `switch_patch`, `switch_extract`,
`switch_decrypt`, `switch_arc`); a bug report on them from the RE session will come through this file.

## 0a. PM note, 2026-11-09 23:55 UTC (superseded by 0b where they differ)

Your rounds 6-15 since this guide was pushed are good work and are on main: `switch_nca`, `switch_bktr`,
`switch_patch`, `switch_extract` and the dispatchable `switch_decrypt` job give gBox its own Switch decryption on any
client. Keep them; the RE lanes will use them. But the operator's direction stands: RE6 is the RE session's, PSO is
yours. To close RE6 properly rather than leave it half-way:

1. **One more round on the BKTR payload, then stop.** Your round 13 left region 8 not decrypting as CTR/plaintext/
   XTS. Before trying more variants by hand, get a known-good reference: decode the same update NCA with a mature
   implementation of the NCA patch (BKTR / AesCtrEx + indirect storage) format, e.g. LibHac's `hactoolnet` (its
   `--basenca` option applies an update to a base) or `nstool`, with the share's `prod.keys`, on the i9 (data on `D:`).
   Compare its output for `Game_eng.arc` (it must start with `ARC\0`) and the subsection table it reports with
   yours; that tells you which of your conventions is wrong in minutes. Check also whether region 8 is a relocation
   back into the base RomFS (indirect storage) rather than patch data that needs decrypting.
2. **Whatever the outcome, write it down and hand it over** in your i9 lane doc: the reference tool's result, what
   `switch_patch` produces, and the exact remaining gap. If the reference tool gives a valid patched RomFS, publish
   the Mercenaries files it yields (the `s12xx` stage archives and anything the update replaces under
   `nativeNXx64/arc/NX/`) as artifacts and list their sha256; the RE session builds the RE6 update overlay from them.
3. **Then PSO, from §4 P1.** spark2 is already breaking PSO down for you: Hermes tickets #9182 (every file on the
   Episode I & II disc by format), #9183 (PRS / GSL / AFS / BML with round-trips) and #9184 (map geometry, collision
   and enemy/object sets per area) write `docs/research/pso-gc-*.md` as they finish. Read them before P2; do not
   duplicate them.

Commit hygiene is good (tests with every module, a round doc per round). Two asks: never edit files on the Spark's
share directly (deploys keep such edits and they silently diverge from main - four were found tonight), and say in
each round doc which commits are yours.

## 0. Hand RE6 over first (half an hour)

Leave everything you built where it is and write down where it is, in one commit to `main`:

- append a "Handed over 2026-11-09" section to
  [your i9 lane doc](ds-i9-client-lane-and-hot-swap-requests-20261109.md): the i9 builds and staging dirs
  (`recovery-re6-update-v131072-20261109`, `re6sw_*`, `D:\gBox\cache\re6sw_cast_cache\`), the Yuzu setup, the save(s)
  you tried and with which version, the unlock state, and the exact next step you saw (the update's BKTR RomFS);
- publish the update's ExeFS files as artifacts (`POST /api/artifacts?name=...`, raw body) and list their sha256 there,
  so the Spark lane can build `recovery-re6-update-v131072` itself;
- do not delete anything on the i9; stop any RE6 session you started (yours only - never one whose launch actor is
  `operator`).

`gbox/switch_nca.py` (your NCA reader) and `switch_mods op=hotswap` stay on main and are used by the RE lanes. Thank you
for them.

---

## 1. What the operator wants from PSO (their words)

- 2026-11-02 (/goal): "the PSO bot plays MASTERFULLY": traverse and complete all zones, reach and defeat every boss,
  combat spec (critical-only, random weapons, never-miss, custom armor with 4 units, maxed mag, 3x attack speed), fully
  automated, up to 3 players (co-op on the GameCube version, Episodes I & II).
- 2026-11-03: "map and deconstruct the game fully so maps can be modded, generated, expanded, randomized (new /
  alternative maps), and PSO models exported for cross-use" (PSO characters inserted into the Mercenaries titles).
- 2026-11-09: "resume and finish the tasks for decrypting and breaking down pso for autoplay."

## 2. State, as last recorded (2026-11-03/04; check every line against the live system before relying on it)

**Working, live-verified then**
- Perpetual floor-to-floor play 1 -> 14 by the native floor-load warp (`pso_fence.advance_floor`), reaching Dark Falz
  (floor 14). This is a warp, not traversal: the operator's goal is real traversal.
- Never-die: `pso_survival.apply_survival` every tick for both players (max HP `+0x2B8` and HP `+0x32C` held at 9999;
  10 Scape Dolls; death log `gbox-data/pso/deaths.jsonl`). Called from `pso_coop.survival_tick`.
- Mastery build: `pso_master_build.py` implements the whole spec (never-miss `pso_accuracy`, crit-only `pso_crit` +
  LCK 100, weapon reroll every 10 s, frame + 4 units + shield, maxed mag, `pso_speed`, up to 3 players).
- Input: ViGEm virtual pads for Dolphin, one per player (branch `pso-i9-vpad-input` 245f8006; check it is on main),
  presses land regardless of window focus.
- Boss knowledge: `pso_boss_strategy` (Dragon: hold the arena centre and fire outward; De Rol Le; Vol Opt by
  `boss_parts_remaining`; Dark Falz three forms) and the walkthrough research (Ep1 zone order, Ruins opened by the
  three pillars on Forest 2 / Cave 2 / Mine 2).

**The blockers recorded then**
1. The campaign never leaves the title on its own: it does not press Start at PRESS START / attract and does not walk
   the menus (offline -> character -> Pioneer 2 -> zone) with real presses; it waits for a "verified town" and tries
   native warps that do not work from the title (PHASE `0x804FE120` cycles 10 -> 3 -> 9, FLOOR `0x805D5FC0` = 0).
2. A non-vpad `win_send_keys` path in `adapters.py` raises "the game window isn't open" on window churn and kills
   `play()`.
3. Two complete gBox worker stacks ran on the i9 at once (venv + uv); the two gamepad watchers fight the pad. Kill the
   one not bound to port 18765 (an i9-local action: you run on the i9, so you can).
4. Reload traps: `pso_survival`, `pso_master_build`, `pso_boss_strategy`, `pso_speed` are not bot modules; they
   re-import only when `pso_coop` reloads. The autobot can die silently within a minute: check telemetry `age_s`
   (fresh < 15 s) and `bot.running` before calling anything a navigation bug.

**Player RAM** (GameCube, big-endian): slot table `0x8050EA10` (4 x u32) -> P1 `0x80DA62A0`, P2 `0x80DA8830`;
per player HP u16 `+0x32C`, max HP `+0x2B8`, position f32 `+0x38/+0x3C/+0x40`, control mode `+0x324` (do not force it
on a player).

**Code and docs to start from**: `gbox/pso_*.py` (54 modules: `pso_coop*` the co-op bot, `pso_gc*` the GameCube
adapter and live hooks, `pso_map.py` / `psomap.py` / `pso_map_feed.py` the map, `pso_rom_export.py`, `pso_enemy.py`,
`psoitems.py`, `psotext.py`), `docs/pso_gc.md`, `docs/pso-*.md` (campaign loop, co-op campaign, controls, map
directives, progression, enemy drops / traversal, run reviewer, runtime acceptance 2026-11-01),
`docs/research/pso-autoplay-architecture.md`, and the extract jobs (`extract_pso_model`, `extract_pso_area`,
`pso_face_build`).

## 3. Rules

- Work on the i9 in a git worktree on a branch; merge to `main` with a merge commit after the named tests pass; push;
  say what you pushed. Commit messages say what changed, why, and what is proven.
- Evidence: a session id, the build, the frame artifacts, RAM readings with addresses. A title screen is not gameplay; a
  warp is not traversal; an offline decode is not a live result.
- Never stop a session whose launch actor is `operator`. Never delete operator-placed games, saves, firmware or keys.
  Data, builds and caches on `D:`, never `C:`. No secrets, ISOs or extracted game assets in git.
- `[builds] auto_send = true` since tonight: agents may send builds to client PCs. You may use all cores, the fastest
  disk and the GPUs for decoding and building.
- The API token is `system/gbox-data/api_token`; send `x-gbox-actor: agent` (or `deploy` for the deploy-gated worker
  routes) and never print it.

---

## 4. The packages

### P1. Boot to the field by itself (the blocker of record)
Title -> PRESS START -> the offline menus -> character select (or create) -> Pioneer 2 -> the Hunter's Guild / the
telepipe -> Forest 1, by real presses on the virtual pads, with the screen read from RAM (the menu state bytes), not
from frames. Then the same after a death, a disconnect of P2 and a worker restart.
Accept on: three cold launches in a row reaching Forest 1 with both players, no warp used, session ids and RAM phase
traces recorded.

### P2. Decrypt and break down the disc (what "breaking down PSO" means here)
Every file format on the PSO Episode I & II disc the bot or a mod needs, decoded and documented, with round-trip
(decode -> encode -> byte-identical) where the game reads it: the archives (GSL / AFS / BML containers), the
compression (PRS), the map files per area (`map_*_n.rel` / `c.rel` geometry and collision, `d.dat` / `e.dat` object
and enemy sets, `*.evt` events), the models (NJ / XJ / BML), the textures (XVM / XVR / GVM), the item and text tables
already started (`psoitems.py`, `psotext.py`), and any encrypted container you meet (say which and how it is keyed).
Output: a module per format with tests on synthetic fixtures, a catalogue of every area's files with sizes and hashes
under `docs/research/`, and the extracted data on the i9's `D:` (never in git).
Accept on: every Ep1 and Ep2 field area's geometry, collision and enemy set decoded, and one map file rewritten (one
object moved) that the game loads and shows.

### P3. The bot walks the areas by their map (traversal, not warps)
From P2's collision: a navigation graph per area (walkable floor, doors, gates, switches, teleporters), the bot
routing room to room to the next area's gate the way RE5's bot routes on its stage nav mesh (`gbox/mercs/titles/
re5_nav.py` is a good pattern), opening doors by their switches, using the telepipe and the boss teleporter.
Accept on: Forest 1 -> Dragon reached by walking, both players, no warp; then each Ep1 area in turn.

### P4. Every boss defeated
Dragon, De Rol Le, Vol Opt, Dark Falz (Ep1); Barba Ray, Gol Dragon, Gal Gryphon, Olga Flow (Ep2), with the weak points
of `pso_boss_strategy` and the walkthrough research; the boss's own HP / part counters from RAM as the measure.
Accept on: a boss kill per boss with the session id, the time, and both players alive at the end.

### P5. The full campaign and three players
Ep1 Forest -> Ruins (with the three pillars) -> Dark Falz, then Ep2, unattended, with the mastery build; a third
player once two are solid (`apply_master_build_all`).
Accept on: an unattended Episode I clear; then Episode II.

### P6. Maps that can be modded and generated
On P2's formats: moved / added objects and enemies, a room reordered, then a generated variation of an area that loads
and that the bot can still walk (P3's graph rebuilt from the new map). And the PSO character models exported for the
Mercenaries titles (the RE5 cast writer takes any rigged donor: `gbox/re5_donor_pool.py`, `re5_cast_writer.py`).
Accept on: one generated area variant played through by the bot.

---

## 5. What to send back

Per package: the branch and commits, what was pushed to `main`, session ids and evidence, the acceptance test answered
yes or no, what you could not do and why. Append each round to a doc of your own on main
(`docs/ds-pso-lane-<date>.md`) as you did for the i9 lane; the RE session reads it.
