# Project manager handover — RE5 modified characters, modified enemies, and the mines requirement

Prepared 2026-11-09 by the DeepSeek resume session, for the project manager who finishes this work.
Read this first, then [reply.md](reply.md), [DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md](DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md)
and [research/re5-sonic-mario-handoff.md](research/re5-sonic-mario-handoff.md). Where this document and an older one
disagree, this document wins; where a live reading disagrees with this document, the live reading wins.

---

## 1. The goal, in the operator's words

> "The user wants a live pick-whip workflow … choose a source character, choose a game and target character/enemy
> slot … apply a real replacement to the running stream."
> "RE5 only, modified characters only: Sonic-franchise characters as the Mercenaries cast and Mario-franchise
> characters replacing enemies."
> "It is imperative that any character has mines in their inventory and they are able to quickly select them and
> place them randomly every 30 seconds as they are traversing the level."

Translated into acceptance tests:

| # | Requirement | Done when |
|---|---|---|
| G1 | RE5 Switch only; every enabled rotation slot is a modified character, no stock roulette | MercMode runs RE5 Switch with `cast_swap`/`skin_swap` off and each cast slot carries an accepted overlay |
| G2 | The Sonic-family cast covers the whole Mercenaries roster, one donor per slot | each slot/costume has its own authored archive, visible in a live round |
| G3 | Mario-family characters replace the enemies | a live Public Assembly round draws a Mario donor where a Majini used to be, repeatedly, with combat |
| G4 | **Every character carries mines and places one roughly every 30 s while traversing** | real inventory `0x10A`; new native `uWp0a` actors ~30 s apart when clearance permits; safe retreat; the bot survives |
| G5 | Honest reporting | every claim carries session/job ids, hashes and frames; unsupported combinations say why |

G4 is *currently* the operator's most emphatic request. G1/G2 are half-done (one slot), G3 is at the
measurement stage. None of G1–G3 may be described as finished in the operator's hearing.

---

## 2. Status at a glance (2026-11-09, before the next acceptance run)

| Area | State | Evidence / where |
|---|---|---|
| Round-boundary acceptance for the repeating queue | **Accepted** | 7 real boundaries relaunched the exact build/character/stage (`d1257c16…`, `f8fc0664…`, `ce8c36cf…`, `43ab169e…`, `fc4ba1de…`, `ed700fe8…`), combat advanced each time; frames + stream health in the resume block of [reply.md](reply.md) |
| Sonic v15 as the Chris (BSAA) slot | **Live-verified, not final** | artifact `d96c9c9e…` renders and fights as Chris BSAA; head/quill occlusion, detailed grip, feet still unaccepted |
| Reproducing v15 from source | **Broken (recipe drift)** | committed `build_grip_candidate` no longer yields `d96c9c9e…`; see §4.1 — do not promote before this is resolved |
| Native Sheva→Chris counterpart | **Accepted for one pair** | output `ee04244c…`, visible gameplay 300/1 → 2400/8; reverse pairs refused 409 |
| Mario enemy replacement | **Measured, not built** | live census (2 boots) names `uEm10`/`uEm11`; `uEm10.arc` mapped; the existing writer cannot author it (no group 0) |
| Mines in every loadout | **Implemented, deployed; live acceptance incomplete** | 54/54 templates verified; `ecba20b1` fix deployed (share hash `0db520de…`); live placement receipts still owed |
| Comparison window | Working | local artifact preview + `POST /api/decrypt-lab/model-compare`; raw-FK caveat |
| Control plane | Recovered after a wedge | gbox.service restarted; API listening again (§4.5) |
| MercMode configuration | **Drifted — RE5 modified-only is NOT in force** | at the last check `titles:["re6"]`, `enabled:false`, empty queue; a PS3 RE5 Gold session was running (§4.4) |

---

## 3. The system map — what was built and how it fits the goal

Everything below is in `system/` of <https://github.com/teamcsharp/gBox>. The architecture predates this work;
the *replacement* and *bot* pieces are what this project added.

### 3.1 Control plane, workers, and the API

- The `gbox.service` unit on **lilspark** (`http://10.89.1.246:8765`) is the control plane (FastAPI, `gbox/server.py`)
  plus a worker. Workers register, poll `POST /api/jobs` and execute tools. Every job records an **actor**: raw API
  calls must send `x-gbox-actor: agent`, otherwise a launch is logged as the operator's.
- Auth: `Authorization: Bearer <token>` from `system/gbox-data/api_token`. Never print, paste or commit it.
- Node rule: **one Switch emulator per PC**. `lilspark` boots Switch titles on Eden (service runs `--worker`).
  Launch jobs must pass `node: "lilspark"` (or `require_worker`) or they can land elsewhere.
- Useful read-only routes: `GET /api/mercmode`, `GET /api/sessions?include_ended=false`, `GET /api/jobs[/{id}]`,
  `GET /api/sessions/{sid}/frame.jpg`, `GET /api/sessions/{sid}/stream/health`,
  `GET /api/autoplay/telemetry/{sid}`, `GET /api/artifacts/{sha256}`.
- Job shape: `{"tool": "...", "input": {...}, "require_worker": "<worker id>", "agent_use": true}`; poll
  `GET /api/jobs/{id}` until `succeeded|failed|...`.

### 3.2 MercMode — the scheduler that keeps a chosen build playing

`gbox/mercmode.py` + `gbox/screensaver.py` + `gbox/mercmode_tool.py`.

- Each round the scheduler launches the next queue entry; for Switch builds a **same-title launch forces a title
  restart** because LayeredFS is read at boot. The current round is lost — this is not hot reload.
- `repeat_queue: true` rotates the first queue entry to the end, so a one-entry queue is the same build forever.
  Capability name: `mercmode_repeat_queue` (an older host silently ignores an unknown field — always read back).
- Accepted boundary evidence: five+ terminal round boundaries each relaunched the same
  `recovery-sonic-native-grip-v15-20261109` / Chris (BSAA) / Public Assembly.
- The intended RE5 configuration (copy-paste) is in
  [DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md](DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md) ("MercMode: keep the exact modified
  build playing"). Key subtleties: queue `mode` must be `mercenaries`, while `preferred_editions.re5.mode` must be
  `no_mercy` (that selects the Switch No Mercy backend); `keep_warm: 0` during acceptance; `skin_swap`/`cast_swap`
  off so a stray random recipe cannot run.

### 3.3 Switch builds = tracked LayeredFS overlays

`gbox/switch_mods.py`. A build is a folder `<cache>/mods/<game id>/<build name>/romfs/...` with a `.gbox-mod.json`
manifest; only changed files are stored, the base NSP is never copied. Writes keep backups and history, and compose
against the latest pending edits. `op=status|write|revert|apply_pending|apply_live|audit|new_build`.

- Never hand-edit an overlay: use `switch_mods` (the `cast-inverted` incident in [reply.md](reply.md) is why).
- Duplicate entry names exist across MOD/MRL; replace by explicit index (`replace_at`) — name-only replacement once
  corrupted the wrong resource.
- For an existing running session, `POST /api/sessions/{sid}/swap {"mod": "<build>", "keep_state": true}` restarts
  the title in the same session. `keep_state` does **not** preserve a Switch round.

### 3.4 The character replacement pipeline (the core of G1/G2)

```
source GLB (character library)
      |  characters._load / mtf_materials.source_mesh  (vertices, triangles, atlas, skin weights)
      v
mtf_retarget.repose/transfer      anatomical role mapping (15 roles), bind-pose frames, root motion
      v
re5_mesh_import.build_archive     one-mesh MOD with the target's skeleton/materials; four-weight vertices;
                                  bounds, envelope records, MRL albedo binding, TEX atlas
      v
mtf_author / mt_model / mtf_mrl / mtf_tex   byte-level MOD/MRL/TEX authorship inside the .arc
      v
re5_sonic_writer.build_grip_candidate      the bounded v15 experiment (hands + grip)
      v
switch_mods.write_files           tracked overlay on lilspark -> restart -> live verification
```

Modules: `gbox/mt_arc.py`, `mt_model.py`, `mtf_author.py`, `mtf_materials.py`, `mtf_mrl.py`, `mtf_tex.py`,
`mtf_secondary.py`, `mtf_motion.py`, `mtf_motion_edit.py`, `mtf_retarget.py`, `re5_mesh_import.py`,
`re5_sonic_hands.py`, `re5_sonic_grip.py`, `re5_sonic_writer.py`.

Formats that bit everyone and must stay as measured (see "Preserve these fixes" in the continuation guide): zlib
framing, MOD packed mesh fields (group 12 bits / material 12 bits / LOD 8), 144-byte weight-bound trailer records
with the count at `0xA0`, inverse-transpose normals, UV-derived tangents, BC7 mip/padding, `+11` AO / `+15` tangent
sign bytes.

The **native counterpart** path is separate and stricter: `re5_player_archive.compose` swaps MOD/MRL payloads while
keeping the destination's lookup names, appends texture dependencies, and is gated to one accepted pair
(`re5ps3_sheva_normal -> chris`, output `ee04244c…`). `re5_char_swap`/`re5_ips.py` add the one measured ExeFS
class rebind (`uEm11 -> uEm10`) with an exact NSO build check.

### 3.5 The comparison window (evidence, not gameplay)

- `POST /api/decrypt-lab/model-compare` (read-only, `ModelCompareIn`) samples the native archive and one overlay
  under the same animation; `clients/desktop/decrypt-lab-compare-window.cjs` is a standalone Electron window.
- Hands can be isolated from occluding head/body via real skin weights; both sides share frame and scale.
- Normal preview refuses engine-IK clips; **raw FK is explicitly not gameplay**. Joint differences are not errors
  (different proportions); the window proves pose/contact geometry, not weapon contact in the engine.
- Use it for every new donor before a live trial. Launch example is in the continuation guide; on Windows the API
  URL must be the **last** argument.

### 3.6 The Mercenaries bot stack (G1/G4, and the enemy work)

`gbox/mercs/` — `driver.py`, `engine.py`, screensaver integration, and per-title modules under
`gbox/mercs/titles/`. For RE5 Switch:

- `re5_switch.py` — RAM map (player `S_PLAYER=0x1CF1C98`, `P_FIRST=0x30`, position `+0x60`, health `+0x1EB8`,
  inventory `+0x30F0` 24×0x38, enemies `S_ENEMY=0x1CF04B8` `+0x38` count / `+0x48` array, cGameSys
  `S_MAIN=0x26A1BA8 -> +0x584E0`, Mercenaries counters at `+0x948/+0x96C/+0x990`), menu walking, the fight, the
  mines integration, and the snapshot the telemetry publishes.
- `re5_switch_mods.py` — the live actuators (`op=status|mines|bot_logic|loadout|...`), including `mine_loadout`.
- `re5_switch_mines.py` — the mine controller (§3.7).
- `mercs_bot.py` — the playbook that drives menus -> round -> results, with `round_ops` preparing loadouts before
  the actor is constructed.
- Telemetry: the bot POSTs stats to `/api/autoplay/telemetry/{sid}`; read them back with the same GET. This is the
  fastest live view of `mines_placed`, `mine_attempts`, `mine_blocked_reason`, `mine_relocating`, `mine_overdue_s`.

### 3.7 Mines in depth (G4)

**Supply.** `re5_switch_mods.mine_loadout(on)` writes the proximity bomb (`0x10A`, WP0A) into **every Mercenaries
loadout template** (54 verified) on a quick-slot grid, never deleting a gun/knife/heal; it swaps grids when the
bomb would land off-grid, and `compose_templates` composes it with other template edits. Infinite ammo's no-ammo flag
keeps the stack at 5 (the HUD shows infinity). `mercs_bot.round_ops` applies it **before** the actor exists, so a
round that starts after the change has the bomb; the sidebar `mines` op can toggle on/off and change the cadence
(`MINE_EVERY_S`, default 30).

**The cycle** (`Mines.tick`, states `idle -> neutral -> equip -> place -> settle -> retreat -> rearm`):

1. *due()* — one placement per `every_s` (30 s) of the round, but only with no Majini within `FOE_CLEAR_CM` (5 m)
   and no bomb within `SPACING_CM` (6 m) of the last site or of a bomb still down. When blocked it runs to a clearer
   site for a bounded 3 s, then yields 1 s to combat.
2. *neutral* — the pad rests 0.5 s (the D-pad needs a neutral pad), then a tap of the mine's own quick-slot key.
3. *equip* — waits for the bomb's **hand flag** (not just the grid record — `ecba20b1` added `Mines.equipped()` for
   exactly the live failure below), re-checks clearance, records the pre-press ground scan.
4. *place* — taps `zl` 0.25 s; **a placement counts only when a new nearby native `uWp0a` actor appears** relative
   to that scan (`CONFIRM_CM` 2 m). A count drop or the placing motion alone is `mine_unconfirmed`: still retreat, no
   credit.
5. *settle* — the placing motion plays out (≤1.6 s).
6. *retreat* — runs out through the widest gap to ≥8 m, the new bomb counted as an obstacle, then re-arms the gun.
7. **Guard, all round** — a Majini near a bomb of his while he is inside its blast radius (8 m) sends him out; the
   mid-cycle variant aborts a place/settle/retreat. A close crowd (≤3 m) abandons the run and fights instead.

Counters (`mines_placed`, `mine_attempts`, `mine_unconfirmed`, `mine_equip_failures`, `mines_gone`, `mine_clear_runs`,
`mine_blasts`, `mine_kills`, `mine_blast_hp_loss`) plus starved-state fields (`mine_overdue_s`,
`mine_blocked_reason`, `mine_relocating`, `mine_last_confirmation`) are the honest reporting surface. `tools.py`'s
scalar telemetry omits nested objects; use the autoplay telemetry GET or RAM for detail.

**Verification tool (new):** `system/scripts/re5_mine_probe.py` — read-only API probe that prints the player's
inventory row for `0x10A` (count/cap/grid/hand), every `uWp0a` ground unit with its position, new mines with their
distance from the player, and score/kills. Usage:

```powershell
python system/scripts/re5_mine_probe.py <session_id> --samples 40 --pause 5
```

A good run shows the bomb in inventory (5/5, a quick grid), then `NEW_MINE` lines ~30 s apart while clearance
permits, with `grounds` growing and later shrinking as bombs detonate.

### 3.8 Enemy identification and the Mario groundwork (G3)

- `re5_char_swap.catalogue(romfs)` lists 41 character and **139 enemy** archives of the extracted RE5 Switch RomFS.
- Live census (read-only `read_memory`, class names via the DTI vtable path, two boots): Public Assembly draws
  **`uEm10` (27–28 of 40 slots, HP 800)** and **`uEm11` (7–8, HP 700)**, plus `uEm20`/`uEm21` (dynamite) and
  `uEm62` props. So the Majini body is `uEm10.arc` (SHA-256 `1fa271890891ff31ac1aeb8d6dfc9a6d8bdcdd1ec252954b9d22a61519634a0c`),
  models on MOD entries `234/235/236` = `em1000`/`_low`/`_mid` (MRL 196–198) and `237–239` = `em1001` variants.
- `em1000` is 92 bones, 70 materials (`gam01_*_BM` albedos), ~341 mesh records across option groups **1..225 and no
  group 0**. That last fact is the current blocker: `re5_mesh_import`'s `source_proportions`/`source_reposed` path
  refuses a non-group-0 template, and the `native_segments` path needs the full 15-role profile measured on the
  Majini skeleton.
- Donors measured and ready: `sm64ds_mario` (`ea509bdf…`, 17 joints, complete role metadata), `melee_mario`
  (61 joints, fingers), plus `sm64_mario`, `melee_luigi/peach/bowser/yoshi`. Provenance of `*_hd` Render96 models is
  a model pack, not an extracted game donor — keep that distinction.

---

## 4. Issues encountered and struggles (what actually went wrong)

### 4.1 The v15 recipe no longer reproduces its own artifact — **the biggest structural risk**

- Pristine inputs still verify on lilspark: original Chris ARC `8ab0dc18…`,
  `~/gBox_alt/switch/romfs/010018100CD46000/nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc`; source GLB `5dd7cc07…`.
  The live overlay still hashes `d96c9c9e…`.
- But committed `build_grip_candidate` fails its own guard chain: stage-1 `build()` now yields MOD97 `cec895d2…`
  instead of the reviewed v12 `b87ecc87…`; even stitching the stored v12 MOD through `re5_sonic_hands.author` yields
  `e9c2bf23…` instead of pinned v14 `426ac8ad…`.
- Verified identical under the deployed share code (service venv, numpy 2.5.3 + ispc_texcomp 1.0.1), the clean
  `gBox-src` deploy clone, and a BOM/LF-normalized copy of the committed closure — so it is **recipe drift in the
  repository, not an environment artifact**. Most likely an uncommitted writer state produced the original artifacts.
- Consequence: `plan()` cannot be registered with "exact-source/target guards" honestly. The live artifact and the
  content-addressed store (`GET /api/artifacts/d96c9c9e…`) remain the source of truth.
- Do **not** "fix" this by editing the guard hashes. Either reconstruct the builder that reproduces the accepted
  bytes, or adopt an artifact-based route that pins the exact SHA and refuses anything else.

### 4.2 Deployed-vs-repo confusion (line endings, BOM)

The Spark's share copy is CRLF and has a UTF-8 BOM on several `re5_sonic_*.py` files; the repo is LF without BOM.
Hash comparisons therefore "differ" by appearance only — the *content* matched. When comparing deployed code with
the repo, normalize CRLF/BOM first, or you will chase ghosts as this session did for about an hour.
`deployed-main.txt` records the deployed commit; the deploy backups live under `gbox-data/deploy-backups/`.

### 4.3 The mine equip failure (fixed in `ecba20b1`)

First round after the supply change: `mine_attempts=1`, `mine_equip_failures=1`, `mines_placed=0`, then
`blocked="enemy too close"`/relocating for the rest of the sampled window. Two real defects:

1. the bomb was found only through its quick-grid record, so a press that moved/re-handed the item was scored as
   "did not come to hand" — `Mines.equipped()` now uses the item's own `rounds>0` + `hand` flags;
2. the cycle's timeout clock was wall time even while the controller was not ticking (grabbed by a Majini, healing),
   so a 1.5 s grab failed an attempt whose press had landed — `GAP_S=0.75` now pauses the cycle clock across gaps.

Tests grew to **49** in the three mine suites (gap pause, in-hand-without-grid, empty in-hand stack; the two sparse-
tick tests now tick at the engine's 0.05 s cadence). Deployed share hash
`0db520de38b236b48c93970fbc11a3662a819066f9c39a99ddf86684c1c1f42d` matches the committed file.

### 4.4 Shared-worker contention and configuration drift (live, unresolved)

- The operator launched a **RE6 Switch** session on lilspark mid-acceptance (actor `operator`, no autobot, 0 stream
  viewers). One Switch emulator per PC: MercMode then reported "a game is already running there" and no RE5 round
  could run until it ended.
- Later the MercMode settings changed to `titles:["re6"]`, `enabled:false`, `repeat_queue:true`, empty queue,
  `preferred_editions.re6 = switch/no_mercy`, and a **PS3 RE5 Gold Edition** session
  (`1948975c…-055575359cc343fe`, game `e7ca89bbeb67360d`) was running — the opposite of the modified-only RE5
  requirement. A parallel RE6 stream of work (see [re6-switch-handover.md](re6-switch-handover.md)) is active in
  the same repository and the same host. Coordinate; do not fight it with restarts.
- The lesson: **read MercMode settings and the session list before every acceptance run**, and restore the intended
  queue rather than assuming it survived.

### 4.5 Control-plane wedge (recovered, watch for it)

gbox.service restarted at 08:36 after a stop timeout; it served jobs, then at ~08:57 stopped accepting connections
while the process stayed alive and its worker loop logged `worker registration retry: [Errno 111] Connection
refused` every 5 s. `ss -ltn` showed **no listener on 8765**, journal had no traceback (event-loop stall, load
average ~6–7 with a ComfyUI SIGSTOP/SIGCONT ping-pong). Restarting `gbox.service` restored 8765 immediately. No
emulator was running at the time, so nothing was lost. If the API hangs again: confirm no emulator, restart the
service, verify `ss -ltn | grep 8765`, then check `GET /api/mercmode`.

### 4.6 Test-suite noise that is not your bug

`system/tests/test_mercmode_repeat_queue.py` fails 10 tests **in this checkout even on a stashed tree** (collection
needs `system/tests` on `PYTHONPATH`; failures pre-date the mine work). Do not chase them; note them and move on.

### 4.7 Honesty failures this project has already paid for (do not repeat)

- A successful boot / structural validity was repeatedly mistaken for acceptance; black screens and title screens
  are not gameplay.
- Native cast/texture swaps were once labelled "Mario" without a Mario donor — never again.
- `cast-inverted`'s manifest drifted from disk because files were deleted by hand instead of through `switch_mods`.
- Some earlier handoffs claimed a fixed emulator config; read `config.load()` output instead of guessing.
- The v15 comparison window shows raw FK; it is **not** the engine's layered animation or IK. Say so every time.

---

## 5. Open issues, ranked

| # | Issue | Impact | Resolution path |
|---|---|---|---|
| 1 | **Mines live acceptance incomplete** | G4 unproven | restore RE5 modified run -> probe + telemetry (§6.C) |
| 2 | **v15 recipe drift** | G1/G2 cannot be promoted honestly | reconstruct builder or adopt artifact-pinned registration (§6.D) |
| 3 | **Mario enemy writer blocked on group-0 guard** | G3 not started | small group-aware enemy writer (§6.E) |
| 4 | **MercMode config drifted to RE6/PS3** | wrong content on air | restore the exact RE5 queue when the operator/RE6 stream is done (§6.B) |
| 5 | Sonic head/quill occlusion and feet contact | acceptance quality | use the comparison window isolated views, then decide; do not hide by camera angle |
| 6 | Remaining Sonic cast slots | G2 | per-donor role profiles (Tails/Amy/Shadow/Knuckles/Rouge/Eggman/Tikal in the research guide) |
| 7 | Composite overlay (player + enemy edits) | G1/G3 | `switch_mods.write_files` with collision refusal; scope to RE5 title only |
| 8 | Control-plane fragility | operations | watch journald + `ss`; restart service after confirming no emulator |

---

## 6. What the PM must do, in order

### A. Take stock before touching anything (read-only, 5 minutes)

1. `git -C C:\_tools\gBox status` and `git log --oneline -10`; never commit over another stream's files.
2. API: `GET /api/mercmode` (hosts, settings, current run), `GET /api/sessions?include_ended=false`,
   `GET /api/jobs?limit=20`. If the API hangs -> §4.5.
3. Confirm the worker id and whether an emulator/session is running. **Never kill an `actor: operator` session.**

### B. Restore the RE5 modified-only configuration (only when the host is free)

Post the exact body from [DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md](DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md) ("MercMode:
keep the exact modified build playing") — RE5 only, `repeat_queue:true`, single queue entry
`recovery-sonic-native-grip-v15-20261109` / Chris (BSAA) / stage 0, `skin_swap`/`cast_swap` off, `keep_warm:0`,
`preferred_editions.re5 = switch/no_mercy`. Then read it back (`GET /api/mercmode`) and follow the launch job to
completion; confirm a fresh RE5 Switch session with that build before declaring anything.

### C. Finish the mines acceptance (highest priority; the operator's explicit imperative)

1. Wait until the round is `playing` and the bot is driving (telemetry `running:true`, `age_s` small).
2. In one window: `python system/scripts/re5_mine_probe.py <sid> --samples 40 --pause 5`.
3. In another: poll `GET /api/autoplay/telemetry/<sid>` and record `mines_placed`, `mine_attempts`,
   `mine_equip_failures`, `mine_unconfirmed`, `mine_blocked_reason`, `mine_relocating`, `mine_status`.
4. **Accept only if**: the probe shows the inventory `0x10A` row with a positive count on a quick grid; at least two
   `NEW_MINE` receipts ~30 s apart (clearance permitting) that also appear as `mines_placed` increments; the bot
   leaves each bomb's blast (retreat completes, no self-damage); and the round continues (score/kills advance).
5. If placement is starved, read `mine_blocked_reason`: `enemy too close` is clearance (expected in No Mercy crowds —
   consider the relocate logic or a smaller `FOE_CLEAR_CM` only with evidence), `no usable mine in a quick slot` is a
   supply bug (check `mine_loadout` and the template audit), `the bomb did not come to hand` is an input/equip issue
   (the `ecba20b1` fix targets it — verify it is deployed).
6. Record the receipt in the continuation guide and commit it. Only then say G4 is operational.

### D. Decide the Sonic acceptance (v15) and how to promote it

1. Use the comparison window for aimed-fire, reload, melee and locomotion; use the isolated-hand view for grip.
2. If the hands/weapon intersect or point wrongly, fix the measured bind/attachment mapping — do not accept it by
   camera framing, and do not disable the head in the final recipe.
3. Promotion requires a builder that reproduces the accepted bytes. Two honest options:
   - reconstruct the writer so `build_grip_candidate` yields `d96c9c9e…` again (then register with the existing
     exact-source/target guards);
   - or register an artifact-pinned route: require the exact output SHA from the artifact store and refuse anything
     else, with `replacement_scope.complete=false` until cutscenes/costumes are accounted for.
4. Never default to Chris when a different character is running; the UI must show the one supported slot.

### E. Build the first Mario enemy (G3)

1. Write a **group-aware enemy writer** (new bounded module): replace the body-group meshes of `em1000` +
   `em1000_mid` + `em1000_low` (and the `em1001` set if in scope) inside `uEm10.arc`, retaining the native 92-bone
   skeleton, materials and motion. Reuse `mtf_author`, `mtf_mrl.bind_albedo`, `mtf_tex.replace_image`; extend the
   existing `re5_mesh_import` guard only with an explicit, reviewed group list — do not loosen it globally.
2. First donor: `sm64ds_mario` (`ea509bdf…`) for a quick proportion test, then `melee_mario` if fingers/materials
   matter. Measure the Majini role-to-bone map from bind positions before authoring (the census script patterns are
   in §3.8; the ENEMY_LINE walk is `sUnit + 0x18 + 0x30*10`).
3. Build into a **separate** `recovery-mario-*` overlay; never into the live v15 build. Compare in the window first.
4. Live-test one controlled Public Assembly round: the drawn enemy must visibly be Mario with combat; capture frames
   and the class census. Do not label a texture/cast swap as Mario.
5. Extend to `uEm11` only after `uEm10` passes; the measured class-rebind pair (`uEm10 -> uEm11` + IPS) stays separate.

### F. Expand the Sonic cast (G2)

One donor per slot, each with: pinned hashes/provenance, a reviewed 15-role profile (hands differ per donor), a
comparison-window pass, a bounded build, and a live round. The proposed mapping is in
[research/re5-sonic-mario-handoff.md](research/re5-sonic-mario-handoff.md). Do not copy Sonic's glove selectors or
node indices; measure each donor.

### G. Compose and report

One tracked overlay per accepted combination, with duplicate-path collisions refused, scoped to RE5 title
`010018100CD46000` / game `52d15709be0fda1a`. Keep `replacement_scope.complete=false` until gameplay, cutscenes,
costumes and cinematics are accounted for. Update `reply.md` and the continuation guide with real receipts.

---

## 7. Runbooks

### 7.1 API basics

```powershell
$t = (Get-Content C:\_tools\gBox\system\gbox-data\api_token -Raw).Trim()
$h = @{ Authorization = "Bearer $t"; 'x-gbox-actor' = 'agent' }
Invoke-RestMethod http://10.89.1.246:8765/api/mercmode -Headers $h | ConvertTo-Json -Depth 4
```

Submit and poll a job:

```powershell
$body = @{ tool='re5_mods'; require_worker='4e342e9ebf5948da'; agent_use=$true;
           input=@{ session_id='<sid>'; op='status' } } | ConvertTo-Json -Depth 5
$j = Invoke-RestMethod http://10.89.1.246:8765/api/jobs -Headers $h -Method Post -Body $body -ContentType 'application/json'
Invoke-RestMethod ("http://10.89.1.246:8765/api/jobs/" + $j.id) -Headers $h | ConvertTo-Json -Depth 5
```

Worker id is historical (`4e342e9ebf5948da`); confirm in `GET /api/mercmode` (`hosts[].worker_id`).

### 7.2 Deploy code to lilspark

`system/scripts/deploy_main.sh --deploy` on the Spark: syncs merged main to `~/gBox/system`, backs up overwritten
files, and **bot-only changes reload in place** (`POST /api/workers/<host>/bot-reload`) without restarting the
service or touching emulators. Restart the service only when control-plane code changed and no emulator is running —
it kills every emulator. Never schedule it.

### 7.3 Build and write a candidate

Follow the reproduction block in the continuation guide, but heed §4.1: the current writer does not reproduce v15.
For a new donor, pin its GLB hash, extend the recipe's role profile, build offline, then:

```json
{"tool":"switch_mods","require_worker":"<worker>","input":{
  "op":"write","game_id":"52d15709be0fda1a","build":"recovery-<name>",
  "changes":{"romfs/nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc":{"artifact":"<sha256>"}},
  "note":"experimental; runtime acceptance pending"}}
```

Then `POST /api/sessions/{sid}/swap {"mod":"recovery-<name>","keep_state":true}` (restarts the title) or let the
MercMode queue relaunch. Follow the nested jobs, not just the parent acknowledgement.

### 7.4 View and verify

- Frames: `GET /api/sessions/{sid}/frame.jpg`; stream health: `GET /api/sessions/{sid}/stream/health`.
- Continuous feed: `/api/broadcast/pc/lilspark.mjpg` (video only) or `.ts` / HLS; use the established broadcast token.
- A held frame during a boot is not proof of a fresh process — check `age_s` and the session id.
- Mercenaries progress: `mercmode_native_progress` (`score`, `kills`, `round_id`, `sample_at`) must advance.

### 7.5 Mercenaries telemetry

```powershell
Invoke-RestMethod ("http://10.89.1.246:8765/api/autoplay/telemetry/" + $sid) -Headers $h |
  Select-Object -ExpandProperty stats |
  Select-Object mines_placed, mine_attempts, mine_equip_failures, mine_unconfirmed, mine_blocked_reason,
                mine_relocating, mine_overdue_s, mine_status
```

### 7.6 Common failures

| Symptom | Likely cause | Action |
|---|---|---|
| `a game is already running there` | another session holds the Switch emulator | wait for it; never kill an operator session |
| API hangs, no listener on 8765 | control-plane stall | confirm no emulator -> `systemctl restart gbox.service` -> verify listener |
| Title boots to black / stalls in menus | GPU-init retry, faded frame | inspect log tail, one same-artifact retry; compare artifacts, not vibes |
| `mine_blocked_reason: enemy too close` | No Mercy crowd | relocate logic; only relax `FOE_CLEAR_CM` with evidence |
| `the bomb did not come to hand` | equip input lost or item grid moved | confirm `ecba20b1` deployed; check telemetry after fix |
| `no usable mine in a quick slot` | loadout not applied / round predates it | `re5_mods op=mines on` -> next round; re-audit templates |
| Old overlay tested instead of the new one | session launched before the write | read `current_run.build`/`mod` and the session's `mod` |

---

## 8. Rules of engagement (non-negotiable)

- RE5 only. Do not modify RE4/RE6 or resume stock roulette while the modified-only requirement stands.
- Never kill, restart or reconfigure the **operator's** sessions, and never restart `gbox.service` while an emulator
  runs (it kills them all).
- Never write test data into the live acceptance build or into `cast-inverted`; use `recovery-*` builds.
- Always send `x-gbox-actor: agent` on raw API calls.
- Keep secrets (token, keys), game assets, candidate binaries and screenshots out of Git.
- Say what is proven vs planned, with ids and hashes. A boot is not acceptance; a title screen is not gameplay; a
  structural round-trip is not a visible replacement.
- Standing permission from the operator (2026-11-06) covers pausing rotation, restarting gbox.service when a change
  needs it, commits/deploys and lilspark MercMode settings — not deleting games/saves/keys, not JAYBUILTFINALE test
  sessions, not writing into the live build.

---

## 9. Where everything lives

| Thing | Path / id |
|---|---|
| Continuation guide (live state, exact config, API bodies) | [DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md](DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md) |
| Operator-visible state and history | [reply.md](reply.md) |
| Sonic/Mario inventory + per-slot plan | [research/re5-sonic-mario-handoff.md](research/re5-sonic-mario-handoff.md) |
| Sonic format/pose/grip experiment record | [research/re5-same-table-sonic.md](research/re5-same-table-sonic.md) |
| Replacement scope definition | [character-replacement-scope.md](character-replacement-scope.md) |
| LayeredFS behavior | [switch-mods.md](switch-mods.md) |
| MercMode operations | [mercmode.md](mercmode.md), [mercmode-adding-titles.md](mercmode-adding-titles.md) |
| Broadcast/stream | [broadcast.md](broadcast.md), [stream-stability.md](stream-stability.md) |
| RE6 parallel stream | [re6-switch-handover.md](re6-switch-handover.md) |
| Mine probe tool | `system/scripts/re5_mine_probe.py` |
| Mine controller | `system/gbox/mercs/titles/re5_switch_mines.py` |
| RE5 RAM map / bot | `system/gbox/mercs/titles/re5_switch.py`, `re5_switch_mods.py` |
| Replacement pipeline | `system/gbox/{mt_arc,mt_model,mtf_*}.py`, `re5_mesh_import.py`, `re5_sonic_*.py` |
| Native counterpart | `re5_player_archive.py`, `re5_character_writer.py`, `re5_char_swap.py`, `re5_ips.py` |
| Comparison window | `system/clients/desktop/decrypt-lab-compare-window.cjs`, `gbox/decrypt_lab.py` |
| RE5 Switch title / game | `010018100CD46000` / `52d15709be0fda1a` |
| Accepted artifacts | v15 `d96c9c9e…`; native pair `ee04244c…`; v12 `ee21fc92…`; v14 `4025fe19…` |
| Source hashes | SA2 Sonic GLB `5dd7cc07…`; Chris ARC `8ab0dc18…`; `uEm10.arc` `1fa27189…`; SM64DS Mario `ea509bdf…` |

---

## 10. Suggested first day for the PM

1. Morning: read §1–§4 of this doc; verify the environment (§6.A); if the host is free, restore RE5 modified-only
   (§6.B) and run the mine acceptance (§6.C) — that is the operator's live imperative.
2. Midday: record the mine receipt and commit it; decide the v15 promotion question (§6.D) with the operator's
   acceptance criteria in hand.
3. Afternoon: stand up the group-aware enemy writer skeleton and one `uEm10` candidate build offline (§6.E) — no live
   round needed to author and compare.
4. Before any live test: confirm which agent/session owns the host, and that you are not stepping on the parallel
   RE6 stream.

A short honest status line that the operator will accept: *"Sonic v15 is live as Chris BSAA and the repeating queue
keeps it running across round boundaries; the other cast slots and the Mario enemies are not implemented; mines are
supplied to every template and the placement controller now survives grabs, but the live 30-second placement receipt
is still pending."*
