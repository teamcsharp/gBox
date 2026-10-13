# PR evidence: pictures of a mod working

Operator rule: *a PR that changes what a game shows includes screenshots and images of the mod working, so it can
be analysed.* This page is the pipeline that produces those pictures and attaches them to the PR.

| Piece | What it makes | Kind label |
|---|---|---|
| `evidence_capture` tool (`gbox/evidence_capture.py`) | frames of the build in a running emulator, optional stock-vs-mod pairs | **in-game frame** |
| `scripts/evidence_offline.py` | stock slot model next to the fitted donor, fit-event snapshots | **offline render** |
| `scripts/ui_evidence.py` | headless-browser screenshots of a branch's UI against fixture data | **UI screenshot** |
| `scripts/pr_evidence.py` | pushes the pictures to the `pr-evidence` branch, adds the gallery to the PR body | - |

Every picture carries its kind in the image itself (a coloured tag) and in the PR caption. An offline render is never
described as in-game.

## 1. In-game frames: `evidence_capture`

```
POST /api/jobs {"tool": "evidence_capture", "input": {
  "game_id": "afd2fc507bb69843",        # required
  "mod": "mgs_vr_sonic_cast",           # "" = the stock game
  "node": "auto",                       # auto | worker name/id | windows | linux
  "inputs": null,                       # null = the recipe's steps; [] = none; [{press, hold_s, wait_s, repeat, tool, input, shot, label}]
  "load_moment": null,                  # null = the recipe's moment; "none" = boot; {"artifact": sha} | {"slot": n, "worker": name}
                                        # | {"mod_card": id} | "recorded"
  "shots": [],                          # [] = the recipe's; [{label, at_s | after_inputs, kind: frame | scene}]
  "compare_stock": true,                # also the unmodded game + a before/after picture per shot label
  "recipe": "",                         # a named variant (e.g. "mission_failed", "ninja")
  "boot_s": null}}
```

Output (`job.output`): `{game_id, mod, recipe, worker, runs: [{variant: mod|stock, session_id, reached, frames,
stopped, notes, error?}], frames: [{run, label, sha256, url, kind: "in-game frame", width, height, mean_luma, dark?}],
pairs: [{label, stock, mod, composite, url}], artifacts: [sha256...], notes}`. Frames and pair pictures are artifacts
(`GET /api/artifacts/<sha256>`); finished captures are listed at `GET /api/evidence?game_id=&mod=`.

How it keeps the operator's play safe (stream stability):

* **Never on a node with a running game.** `launch_game` keeps one game per node and would close it, so a node
  with any running session (the operator's, or another agent's) is refused, named or not.
* **Idle nodes only, low priority.** `node=auto` takes a Windows worker ticked for background testing (Tasks menu),
  with no jobs running and no input for 5 minutes (longest-idle first), else the Spark when nothing runs there. A
  named node gets the same refusals (a Windows PC with unknown idle time is allowed only when named).
* **Agent-owned test session.** Launched as an agent job (2% volume on Windows), labelled `owner: agent`
  ("Evidence capture: <game> (<mod>)", shown dimmed in the tray).
* **It stops only its own session**, whatever happened (`finally`), and never swaps, pauses or stops anything else.
* **It yields.** Between steps it checks the node: fresh input on that PC or a game started there stops its session
  at once and the job fails with "yielded: ...". Frames taken before are kept in the error-free runs.
* **One capture at a time** (a second POST is refused with 409). A server restart retires a running capture like the
  other in-server jobs.

Reaching gameplay: a saved state holds the models that were in RAM when it was saved, so a moment alone shows the old
models. A recipe therefore loads the moment and then plays `after_moment` steps that make the game load its models
again from the modded disc (restart the stage, Continue after Game Over, change scene), or boots and plays `steps`.

Recording a moment for a game (operator-initiated; the game keeps running, nothing is paused):

```
POST /api/evidence/moments {"session_id": "<running session>", "game_id": "", "variant": "",
                            "label": "dock, GAME OVER > CONTINUE",
                            "after_moment": [{"press": ["a"], "wait_s": 15, "shot": "dock (continue)"}]}
```

It exports the session's state (`state_transfer op=export`) and stores it as the game's recorded moment (setting
`evidence_moments`); captures use it in place of the seed moment. `GET /api/evidence/recipes` lists the recipes with
what was recorded.

## 2. Recipes: `gbox/evidence_recipes.json`

One entry per `game_id`: `status`, `prefer_os`, `boot_s`, `shows` (which camera / screen shows the replaced
characters), `moment`, `after_moment`, `steps` (boot path), `shots`, `todo`, `variants`. Step tools allowed in a
recipe are session-scoped only: `zelda_oot` (goto, state, skip_deku_tree), `mgs_vr` (status, complete, unlock_all,
stages), `stage_warp`, `session_op` (load_state, pause, resume, step_frames, reset). Pad names: `a b x y start select
up down left right l r z`.

| Game | game_id | Status | Seed |
|---|---|---|---|
| Dead or Alive 2 LE (DC) | 1de2e7634f3161ff | unverified | title-screen state `b1fb3646...` (flycast aarch64, lilspark) -> Start, mode, character select (shot), pick, versus (shot), fight (shot) |
| Crazy Taxi (GC) | bc02bb68790ce2e7 | unverified | no state: boot path to the driver select (shots: driver select x2, in the city) |
| MGS VR Missions | afd2fc507bb69843 | unverified | Sneaking stage state `bfe300e2...` (i9-NUC) -> pause > Restart (shots: pause menu, stage restarted, gameplay); variant `mission_failed`: mod card f72f4f155abd (slot 21 on JAYBUILTFINALE, MISSION FAILED) -> TRY AGAIN; variant `ninja`: **needs_state** |
| MGS The Twin Snakes (GC) | ba32927ecc104b9a | **needs_state** | record the dock GAME OVER > CONTINUE moment (instructions in the recipe's `todo`) |
| Ocarina of Time (USA) | 446e8e442d726e31 | unverified | temple-room state `ecfea6b8...` (oot_sa2shadow session) -> `zelda_oot goto kakariko` (scene reload) |
| Ocarina of Time (2nd dump) | 1aa2e4bb5797493f | **needs_state** | only local slot-0 saves exist |
| Super Mario 64 (USA) | b7aecee966090bfa | unverified | boot path (Mario loads once at boot, a state keeps the old model); variant `moment` with export `0bafe1dd...` |
| Super Mario 64 (EU) | 66062703301f4969 | unverified | boot path |

"unverified" means written from the game's menus and the saved frames, never replayed: run each once and look at
the diagnostic shots (pause menu, character select) before trusting it; then set `status: ready`.

## 3. Offline renders: `scripts/evidence_offline.py`

When no idle node exists, or as a companion to the frames. Headless (`characters.render_preview`, no GPU, no
emulator); every picture lands in `--out` with a `manifest.json` ({file, caption, kind}) for `pr_evidence.py`.

```
# a stock model next to a fitted one (glTF / GLB / KMD) or two existing pictures
python system/scripts/evidence_offline.py pair --before stock.glb --after fitted.gltf --caption "..." --name x --out DIR

# MGS VR Missions: fit donors from the owned disc, stock disc KMD vs fitted KMD (textured through MetalMintSolid
# when installed), plus the writer's fit-event snapshots (scale / retarget / proportion geometry)
python system/scripts/evidence_offline.py mgs-vr --disc "D:/gBox/cache/modbase/mgs_vr_us/Metal Gear Solid - VR Missions (USA).bin" \
    --collection <characters dir> --pair player=sonic --pair enemy:soldier=sa2_knuckles --pair enemy:ninja=sa2_shadow --out DIR
```

It runs at low CPU priority and reads the disc only; nothing but the PNGs and the manifest is written to `--out`.

## 4. UI screenshots: `scripts/ui_evidence.py`

Serves a branch's `system/clients` with a fixture-backed fake `/api` (GET answered from a fixture JSON, everything
else a no-op, nothing forwarded to a real control plane) and drives headless Chromium (Playwright) through the shots
of a spec. Fixtures and specs per PR live in `system/tests/fixtures/ui_evidence/`.

## 5. Attaching: `scripts/pr_evidence.py`

```
python system/scripts/pr_evidence.py --pr 296 --manifest out/pr-296/manifest.json \
    --gh "ssh ehm_eckx@10.89.1.246 gh"
python system/scripts/pr_evidence.py --pr 302 --images a.png b.png --captions "Builds tab" "Build details" \
    --kinds ui ui --gh "ssh ehm_eckx@10.89.1.246 gh"
python system/scripts/pr_evidence.py --pr 296 --job <evidence_capture job id> --token-file <api_token> --gh "..."
```

* Only pictures (PNG / JPEG / GIF / WebP, checked by their bytes) are ever committed; each is kept under `--max-kb`
  (default 1000): optimised PNG, else JPEG, else scaled down.
* They go to the orphan branch `pr-evidence` under `pr-<N>/` through git plumbing (no checkout; the working tree and
  index are untouched; other PRs' folders are kept; a rerun replaces the PR's folder), then
  `git push origin <commit>:refs/heads/pr-evidence`.
* The PR body gets an `## Evidence` section between `<!-- pr-evidence:start -->` / `<!-- pr-evidence:end -->` (a
  rerun replaces it; it goes above a trailing "Generated with" line), one captioned image per picture marked
  *(in-game frame)*, *(offline render)* or *(UI screenshot)*, linked as
  `https://github.com/teamcsharp/gBox/blob/pr-evidence/pr-<N>/<file>?raw=true`.
* The new body is always printed. With `--gh` the current body is read (`gh pr view N --json body`) and the new one
  written (`gh pr edit N --body-file -`). `--dry-run` commits and edits nothing; `--no-push` commits locally only.

Tests: `tests/test_evidence_capture.py` (fake sessions: node choice, stop-own-session, yield, recipes, server
route, pictures), `tests/test_pr_evidence.py` (picture checks, shrinking, body generation, orphan-branch commit).
