# DeepSeek task guide: Phantasy Star Online, decrypted, broken down and played (2026-11-09)

Written for the DeepSeek session on the i9-NUC. The operator, 2026-11-09 ~22:40 UTC: "the deepseek task is failing so
you [the RE5 session] will take over for the RE6 task as well. Instead let's have deepseek resume and finish the tasks
for decrypting and breaking down pso for autoplay."

So: **stop RE6** (the RE5 session on JAYBUILTFINALE owns RE4/RE5/RE6 from now), **resume PSO**. Read §1 to §3 once,
then take the packages in order; each has an acceptance test.

---

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
