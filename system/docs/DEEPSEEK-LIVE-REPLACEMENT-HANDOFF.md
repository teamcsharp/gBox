# DeepSeek handoff: live character replacement and modified-only MercMode

Prepared 2026-11-09 from the recovery session. This is a continuation guide, not a claim that the full requested system is finished. Read `reply.md` and the most recent job/session receipts alongside this file: live state may have advanced after this checkpoint.

## User's intended result

The user wants a live pick-whip workflow: choose a source character, choose a game and target character/enemy slot, see the models and animation differences side by side, retarget the model/rig/materials, and apply a real replacement to the running stream. The eventual workflow spans titles; it must report supported combinations honestly instead of implying an arbitrary GLB can be dropped into any game.

The immediate direction is **RE5 only, modified characters only**: Sonic-franchise characters as the Mercenaries cast and Mario-franchise characters replacing enemies. One Sonic repeated across every slot is not the completed cast. Do not resume stock RE4/RE5/RE6 roulette while that work is incomplete. The latest instruction is stronger than the earlier random native-skin/cast rotation. The entire RE5 Mercenaries roster has NOT been replaced, and Mario enemies have NOT been accepted in gameplay. The detailed owned-source inventory and proposed per-slot retargeting plan are in [the Sonic/Mario implementation handoff](research/re5-sonic-mario-handoff.md).

The user specifically rejected the earlier Sonic arms/hands pointing backwards. They asked for an actual comparison window with both models and synchronized animations. That window exists and has been opened; preserve it rather than launching duplicates.

## Checkpoint and current truth

| Area | Established result | Remaining boundary |
| --- | --- | --- |
| MercMode recovery | RE5 Switch preparation, session-owned round selection, scheduler/watchdog, overlay restart and repeating-queue fixes are implemented and tested. `554a3e20` is activated and the exact repeating Sonic v15 queue is configured. **Accepted 2026-11-09 ~08:35 UTC:** real terminal boundaries relaunched the same build/character/stage (sessions `d1257c16…`, `f8fc0664…`, `ce8c36cf…`, `43ab169e…`), each with advancing score/kills and fresh frames. | Round-boundary acceptance is done; detailed hand/feet contact views remain open. |
| Live overlay | Eden title restarts repeatedly kept the same gBox session/display/stream while the process PID changed. | This is a title reboot, **not zero-restart RAM asset hot reload**. The current round is lost. Audio continuity was not verified. |
| Native player replacement | Exact native Sheva normal -> Chris BSAA composition rendered Sheva and advanced score/kills from 300/1 to 2400/8 in Public Assembly. | Only that bounded recipe/output was accepted. Reverse pairs, other slots/costumes, cinematics and complete appearance coverage remain unverified. |
| Sonic | Full v15 visibly rendered and fought in Public Assembly as Chris BSAA: score/kills advanced from 13220/43 to 26210/57 between 07:14:47 and 07:15:06 UTC. The arm/hand and pistol point forward in the actual screenshot. | Head/quill occlusion, detailed weapon contact and feet acceptance remain incomplete. It is **unregistered**, experimental, and not the default `plan()` recipe. |
| Mario enemies | Native enemy archive/class-rebind groundwork exists. | No accepted Mario enemy recipe or visible Mario-zombie gameplay proof exists. Do not label native cast/texture swaps as Mario. |
| Cross-title pick-whip | Readers, previews, bounded writers, tracked overlays and restart orchestration provide useful components. | A general source/target capability and retargeting workflow is unfinished. Each title/slot needs its own validated writer and acceptance. |

Important commits, newest first:

- `554a3e20` (`554a3e20f3039d0c4dc5de6fe7ad7d9b89c41111`) — repeat configured MercMode build playlists without stock fallback.
- `4e0ecc31` — Fit Sonic palms and finger anchors to native weapon grip (v15).
- `7583005f` (`7583005f03d14d71a129b0bce0b3dde92bf5ffbf`) — measured Hand grip comparison and live Sonic arm evidence.
- `70b0e65a` — compose verified native RE5 player replacement in the target resource namespace.
- `dc854f53` — measured Sonic finger rig and isolated-limb comparison.
- `c0c1e154` — native player gate following failed early visibility acceptance.
- `d8a54660` — one owned GPU-init retry for mapped black Eden restarts.

At the earlier handoff checkpoint, local/pushed core work reached `4e0ecc31`; the Spark disk checkout was reported at `7583005f`, while its long-running service still had older imported code. **That pending activation was resolved at 2026-11-09 07:10:42 UTC:** `554a3e20` is active, service PID `1307414`, worker `4e342e9ebf5948da`. Eight source hashes were verified and the new comparison route is active. Nine external process identities were retained, one execution completed normally, and four DB jobs plus the Hermes gateway were preserved. These are the activation receipt's observations; recheck current identities before later operations.

The newly active native character API was checked with a read-only plan: original Sheva -> Chris returned the accepted `ee04244c4d3012904b4858cef1ce10352f20361963fcc52787543f4ecf9a9800` output; the reverse pair returned 409; no writes occurred. `repeat_queue:true` and the exact Sonic v15 entry below are configured and were retained across two observations. A real subsequent terminal-round relaunch still needs acceptance.

The previous stock run was deliberately stopped from autoplay and paused to honor modified-only playback. It has been superseded by the modified run: **SID `4e342e9ebf5948da-d1257c164cc0405e`, emulator PID `1316339`, autoplay job `1f343320be524907`**, observed playing Public Assembly as Chris BSAA with full Sonic v15. Combat advanced from score 13220/43 kills at 07:14:47 UTC to 26210/57 at 07:15:06 UTC. These are observed identities, not permission to stop a later process reusing a PID. The actual frame shows forward arm/hand and pistol; full-character head/quill occlusion prevents complete hand-contact acceptance, and feet checks remain incomplete.

The stable `/api/broadcast/pc/lilspark.mjpg` feed delivered three fresh JPEGs in 0.23 seconds. Stream health reported running, frame age 0.0 seconds, p50 16.65 ms, p95 23.48 ms, maximum 90.89 ms and zero intervals above 100 ms. This establishes fresh video delivery during the observation, not uninterrupted future delivery or audio acceptance. A post-restart audit at 07:12:49 UTC also found all eight agents making fresh progress within 59 seconds, nine cron PIDs plus the gateway alive, and eight inference requests serving with zero waiting.

## Exact RE5 identities and artifacts

- Game ID: `52d15709be0fda1a`; Switch title ID: `010018100CD46000`; Decrypt Lab title: `re5_switch`.
- Target: Chris **BSAA/normal**, not every Chris costume. Archive: `nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc`; internal model `pl0000`, MOD entry index `97`.
- Original Chris archive SHA-256: `8ab0dc181d1f6ec155e193c5820d1756d877acf711424863b16f7850b592f6c8`.
- Original SA2 Sonic GLB SHA-256: `5dd7cc07f3116a8f1f59ccc9bde8da5ccae65338cbf83d8c7151608c2ae74df4`.
- Original library identity: slug `sonic`, file `sa2_sonic_0.glb`, game `d95ed7ed1e40552a`, Dreamcast source `SONIC2/SONICMDL.PRS` and `SONIC2/SONICTEX.PRS`, extraction `gbox.sa2_chars + gbox.ninja`. Variants/props are not interchangeable with this measured input.

| Candidate | Exact archive SHA-256 | Purpose |
| --- | --- | --- |
| v12 | `ee21fc928c8ad8f90904fc2763b8cf15bcb50765c554dd61ac567336074683ff` | Arm reposing/root-motion scaling baseline; remote build `recovery-sonic-player-rooted-20261108`. |
| v14 | `4025fe19aab2d431d14dd8b7a2ed86a3f2a5fd1733ee092087a08be7562a33ce` | Finger/cuff correction before native grip fitting. |
| **v15 full character** | `d96c9c9e8efaee4cf3a0eda9f10ff12ef1515e1efd604f9c34d081cd3a80cb8a` | Latest candidate. Remote build **`recovery-sonic-native-grip-v15-20261109`**. |
| v15 headless/lift visibility diagnostic | `99238b72667ddedb667b0e947d3e064f91464c8e52522f5ad409cbb937e499d0` | Diagnostic camera/hand visibility only. Never substitute this for acceptance of the full character. |

The full v15 write job `e017b01a58644903` succeeded on lilspark through the existing API. The artifact was uploaded to the content-addressed API store and the overlay was staged. Subsequent full-character gameplay and combat were verified as recorded above; detailed contact/feet checks and complete appearance coverage remain open.

Local owned inputs/candidates currently exist under `.scratch-merc-recovery/assets/`: `uPl00ChrisNormal.arc`, `sonic.glb`, and the `sonic-player-root-scaled-v12`, `sonic-player-cuff-v14`, `sonic-player-grip-v15` folders, each candidate containing `romfs/<archive path above>`. These ignored files are conveniences, not prerequisites supplied by Git.

### Reproduce v15 without ignored helper scripts

**Correction 2026-11-09: the recipe did not drift; the lilspark failure was BLAS-kernel rounding.** The resume
session saw stage-1 `build()` yield MOD97 `cec895d2…` instead of the reviewed v12 `b87ecc87…`, and the stored v12
MOD through `re5_sonic_hands.author` yield `e9c2bf23…` instead of the pinned v14 `426ac8ad…`. All three of its runs
were on lilspark (aarch64); it varied the code, never the machine. On the authoring PC (JAYBUILTFINALE, NumPy 2.5.4,
OpenBLAS SkylakeX kernels) the code as committed in `4e0ecc31` and in main `6a041c30` both rebuild `d96c9c9e…`, and
the only later changes to the recipe's modules are optional parameters that default to the old behaviour. Forcing
another kernel on that PC (`OPENBLAS_CORETYPE=Haswell` or `Nehalem`) stops the same commit at the same guard, with
stage-1 MOD `44296edc…` or `26c7a135…`. The differing bytes are float32 slots of the skeleton tables within 1e-12
of the reviewed values; no vertex, weight, envelope or bound byte differs.

`gbox.re5_sonic_residue` now settles those slots to the reviewed bytes and refuses any other difference, so
`build_grip_candidate` returns `d96c9c9e…` under all three kernel families on the PC. **It has not been run on
lilspark.** Run the block below there: the receipt carries `reproduces_reviewed`, and when it is false
`re5_sonic_writer.grip_reproduction(archive)` names the payload that differs. The model is expected to match now.
The BC7 atlas comes from the native `ispc_texcomp` encoder and Pillow mips, and the entry framing from the linked
zlib; the recipe cannot make those portable and they are unmeasured on aarch64. If they differ on the host, build
on the PC and promote through the artifact-pinned route (handover §6.D option 2). `GET /api/artifacts/d96c9c9e…`
still serves the accepted bytes.

Opt-in check on a PC that owns the inputs:
`GBOX_RE5_SONIC_ASSETS=<folder with uPl00ChrisNormal.arc and sonic.glb> pytest tests/test_re5_sonic_reproduction.py`
rebuilds all stages under the automatic, Haswell and Nehalem kernels, about a minute each.

Use committed `gbox.re5_sonic_writer.build_grip_candidate`, **not** `build()` or `plan()`; those intentionally still use the earlier unregistered recipe. Run with `system` on `PYTHONPATH`, the audit environment's dependencies, an owned original archive and the exact library GLB:

```python
from pathlib import Path
import hashlib, json
from gbox.re5_sonic_writer import build_grip_candidate

native = Path("PATH_TO_OWNED_ORIGINAL/uPl00ChrisNormal.arc")
source = Path("PATH_TO_CHARACTER_LIBRARY/sonic/sa2_sonic_0.glb")
out = Path("PATH_TO_NEW_CANDIDATE")
archive, receipt = build_grip_candidate(native.read_bytes(), source)
assert hashlib.sha256(archive).hexdigest() == (
    "d96c9c9e8efaee4cf3a0eda9f10ff12ef1515e1efd604f9c34d081cd3a80cb8a")
target = out / "romfs/nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(archive)
(out / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
```

Both input hashes are checked by the recipe. The source library directory is resolved by `characters.library_root(config)`; original extracted Switch assets are resolved by the existing RE5 writer/RomFS helpers. Inspect those configured locations instead of assuming another machine has the same scratch tree.

The already uploaded candidate can be fetched with authenticated `GET /api/artifacts/d96c9c9e8efaee4cf3a0eda9f10ff12ef1515e1efd604f9c34d081cd3a80cb8a`; verify the downloaded SHA before writing or using it. Artifact metadata is at the same path plus `/meta`. The named overlay lives under the configured `<cache>/mods/52d15709be0fda1a/recovery-sonic-native-grip-v15-20261109/`; obtain the real cache root from configuration/status. It contains an overlay and `.gbox-mod.json`, not a full copied game.

## Usable comparison window

Latest verified local window receipt: `.scratch-merc-recovery/comparison-smoke-20261109T070333Z.receipt.json`; owner receipt: `local-comparison-20261109T070328Z.receipt.json`. At that observation the window PID was `57988`, owner PID `79772`, actual sidecar PID `14940`, API `http://127.0.0.1:56714`, state `ready`. Treat PIDs as observations and verify creation time/command line before any owned cleanup. Do not launch a second window just because a previous task listed a different PID.

This is clearly labeled **local artifact preview**, reading exact original Chris and saved candidate bytes. It does not pretend to be the deployed API or the running game's pose. Native Chris remains the left reference; the right dropdown includes v12, v14 and v15 with readable names. "Source" in the current comparison means native Chris; there is no extra original-GLB pane.

Use the controls as follows:

1. Choose `Sonic: native grip fit (v15)`.
2. Choose Front (+Z), Side or the other shared camera presets. Both sides share orientation and scale.
3. Select Left hand or Right hand, then **Focus joint** and **Isolate limb**. This removes the head/body occluding the glove. Focus centers the corresponding joint separately in each panel, while the numeric Difference retains absolute centimeter coordinates.
4. Use **Hand grip (2 frames)** for the measured native `wp00` entry `115`, clip `110`. It is strictly gated by the original archive and clip identity; it is not a guessed animation name for other games.
5. Clip `25` in entry `115` is a useful 80-frame, non-IK upper-body/finger animation. Earlier/Later loads bounded frame windows, Play/step uses the same exact frame on both sides.

Game IK, physics and layered motion are not evaluated. Normal preview refuses engine-IK clips; **Raw FK diagnostic** is explicitly incomplete and must not be called a gameplay-equivalent animation. Joint differences are not automatically errors: Sonic intentionally has different proportions. CPU v15 measurements establish native wrist-local digit anchors within `1.732e-6 cm` across 14 sampled frames and unchanged non-finger body/arm/wrist geometry; they do not establish weapon contact in the game engine.

Committed comparison implementation: `clients/desktop/decrypt-lab-compare-window.cjs`, its HTML/JS, `decrypt-lab-compare.js`, `decrypt-lab.cjs`, `gbox/decrypt_lab.py`, and `gbox/mtf_motion.py`. The production read-only route is `POST /api/decrypt-lab/model-compare`; it validates title/archive/build and lazily catalogs only the selected LMT entry. See `ModelCompareIn` and endpoint tests for the exact body rather than inventing a parallel API.

For example, an authenticated read-only sample body is `{"title":"re5_switch","op":"sample","build":"recovery-sonic-native-grip-v15-20261109","animation_entry":115,"animation_index":110,"start_frame":0,"frame_count":2,"frame_step":1,"raw_fk":false}`. Check the returned source/candidate hashes, evaluation mode and limitations. A 404 from the old running server does not invalidate the local artifacts; it means the route has not been activated there.

The local supervisor/sidecar/smoke helpers are ignored, not deployable project dependencies. They import the production sampler/validation, allow only exact-hash registered local artifacts, bind an ephemeral loopback port, keep a temporary secret in Electron main only, expose no worker/DB mutations, and clean up the sidecar/token when the owned window exits. If they are absent, use the committed standalone entry against a **verified active** production comparison API:

```text
gBox.exe <repo>/system/clients/desktop/decrypt-lab-compare-window.cjs --token-file <existing-token-file> --build recovery-sonic-native-grip-v15-20261109 --title re5_switch --animation-entry 115 --animation-index 25 --api http://10.89.1.246:8765
```

Pass arguments as a subprocess list; clear `ELECTRON_RUN_AS_NODE` for the child. On Windows the API URL must be the **last** argument: this Electron runtime exits before loading the entry if external URL arguments are followed by switches. The tested runtime is `C:\Users\Ehm Ecks\AppData\Local\gbox\app\gBox.exe`. This entry never imports desktop `main.js`, starts a worker or restarts the user's desktop. Do not turn off the Electron sandbox. Keep the token out of logs and the renderer. The current local window remains usable independently of the now-active remote API; no replacement launch is needed merely because activation completed.

## MercMode: keep the exact modified build playing

An existing DJ queue entry already accepts `mod`, a single overlay folder name. `screensaver._start` carries this into `launch_game` with `local_build_ok=true`; the queued build takes precedence over random skin/cast generation. A same-title queued build forces a title restart at its round boundary because LayeredFS loads at boot. A queue entry without a build instead supplies a one-round native menu selection.

Previously the queue consumed each entry once. **The new minimal `repeat_queue` setting rotates the first entry to the end**; a single entry therefore remains the selected build/character/stage indefinitely. Its default is false. It does not add a universal persistent `fixed_build` field. Implementation is in `mercmode.py`, `mercmode_tool.py`, `screensaver.py`, worker capability `mercmode_repeat_queue`, and `tests/test_mercmode_repeat_queue.py`. The implementation has 10 new tests and 174 existing scheduler/recovery tests passing and is activated in `554a3e20`. The exact repeating Sonic queue is already configured; avoid duplicating root's launch. An older server elsewhere may silently ignore an unknown settings field, so read back effective settings when configuring another host.

After confirming the named build exists on the selected host, the intended exact configuration is:

```http
POST /api/mercmode
Authorization: Bearer <existing token>
Content-Type: application/json

{
  "host": "lilspark",
  "command": "start",
  "title": "re5",
  "pip": true,
  "enabled": true,
  "titles": ["re5"],
  "rounds_per_title": 1,
  "repeat_queue": true,
  "queue": [{
    "title": "re5",
    "mode": "mercenaries",
    "character": "Chris (BSAA)",
    "stage": 0,
    "mod": "recovery-sonic-native-grip-v15-20261109"
  }],
  "preferred_editions": {
    "re5": {"platform": "switch", "mode": "no_mercy", "title_id": "010018100CD46000"}
  },
  "skin_swap": "off",
  "cast_swap": "off",
  "coop_ratio": "off",
  "keep_warm": 0
}
```

Stage `0` is Public Assembly. The queue's `mode` must be `mercenaries` (or omitted) to satisfy the current shared RE5 roster validator; **`preferred_editions.re5.mode: "no_mercy"` selects the actual Switch No Mercy backend**. Putting `no_mercy` directly in the queue fails validation. Chris BSAA is intentional: this archive does not replace a randomly selected alternate costume or Sheva. No Mercy is solo; do not enable co-op for this pinned acceptance run. Disable random skin/cast generation to avoid an unrelated recipe being used if a queue/config mistake occurs. Keep warm off during acceptance so a parked stock game cannot be mistaken for the newly loaded artifact. This is one Sonic slot, not Sonic throughout the entire Mercenaries roster.

`GET /api/mercmode` returns effective host settings, current run, queue and dispatch state. Follow the actual dispatch/launch job to completion, then check `GET /api/sessions?include_ended=false` for the **current** RE5 SID and selected build. Do not infer success from `enabled=true` or a queued job. Observe score/kills, fresh telemetry and actual frames; a healthy long round must not be killed merely for being long. Once repeat support is active, verify a real boundary leaves the queue intact and the next launch still uses the exact build/character/stage.

On hosts without repeat support, a one-entry queue is **one-shot**. Keep a manually verified modified session under explicit control there; do not allow it to drain into random stock rounds and call that a fixed-build mode. The Spark's repeat support is now active and its full Sonic run is playing. Preserve that owned run; do not submit another `start`/`swap` merely to reproduce the already verified launch.

### Direct tracked write/apply and stream viewing

Use existing routes, not manual emulator directories. If reconstruction is needed, submit a `switch_mods` write job to the exact current worker:

```json
{
  "tool": "switch_mods",
  "require_worker": "CURRENT_LILSPARK_WORKER_ID",
  "input": {
    "op": "write",
    "game_id": "52d15709be0fda1a",
    "build": "recovery-sonic-native-grip-v15-20261109",
    "changes": {
      "romfs/nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc": {
        "artifact": "d96c9c9e8efaee4cf3a0eda9f10ff12ef1515e1efd604f9c34d081cd3a80cb8a"
      }
    },
    "note": "Experimental Sonic v15; runtime acceptance pending"
  }
}
```

Submit through `POST /api/jobs`, poll `GET /api/jobs/{job_id}` and inspect errors/result. This v15 write was already completed; don't needlessly duplicate it. `switch_mods op=status` can inspect the overlay/manifest/pending files on its owning worker. Overlay writes are tracked with backups/history; edits to an in-use build may be pending until restart.

For an existing exact, running, matching-game SID, `POST /api/sessions/{sid}/swap` with `{"mod":"recovery-sonic-native-grip-v15-20261109","keep_state":true}` enters the existing swap orchestration. On Eden this restarts the title within the same session. `keep_state` does not promise preservation of a Switch round/save-state. For a cold start, existing `@launch` accepts `game_id`, explicit `node` and `mod`; scope to the desired host so it cannot choose an unrelated Windows session. Follow nested swap/launch jobs, not only the parent acknowledgement; other emulator paths can return a different SID.

For viewing, use the gBox Sessions/MercMode panel and open the **actual current SID** in PiP. `pip:true` on dispatch asks that host's app to show its own run. The existing app reports `POST /api/broadcast/watching {"session_id":"..."}`; the broadcast program follows the operator's watched session in auto mode. Inspect `GET /api/sessions/{sid}/stream/health` for delivery evidence. A running emulator alone does not prove streaming. Do not start a second encoder, desktop or worker to fix a stale UI without first checking the session stream path.

For continuous viewing across round restarts, use the existing stable host-follow feed: `/api/broadcast/pc/lilspark.mjpg` (video only), `/api/broadcast/pc/lilspark.ts`, or `/api/broadcast/pc/lilspark/hls/index.m3u8`, with the existing broadcast authorization flow. Program and session feeds also exist. These routes keep their reader attached through source changes and use a held frame/slate while a new title boots. A displayed held frame is not proof that the new process is delivering fresh frames. Do not paste the operator API token into a publicly shared stream URL; use the established broadcast token setup.

Health/recovery sequence for a stalled modified run:

1. Read effective MercMode settings and host run/phase; ensure only RE5 and the intended repeating build are selected. Inspect readiness/dispatch errors before resubmitting.
2. Identify the exact running SID, worker, build and emulator PID. An ended session, parked warm game or title screen is not an active Mercenaries round.
3. Inspect the accepted autoplay job and fresh telemetry. Confirm stage/character, actual round clock and score/kills; verify that a genuine terminal boundary reached the scheduler. Do not manufacture a boundary to force a change.
4. Inspect that session's stream health and a fresh frame. If gameplay is healthy but video is stale, diagnose existing capture/stream delivery; if video is healthy but the bot is stopped, diagnose that bot/job. Avoid treating all failures as emulator hangs.
5. For a completed restart, follow returned job/SID lineage and the host's active feed. Re-read settings after a worker/service epoch change. Restore the same named overlay, not a stock fallback, and preserve any operator takeover.

Detailed references: [MercMode operation and ownership](mercmode.md), [adding title adapters and acceptance gates](mercmode-adding-titles.md), [stream reconnection behavior](stream-stability.md), and [broadcast formats, authorization, host-follow and sound](broadcast.md). Some historical inventory statements in those guides predate the Switch recovery; current source, worker capabilities and measured receipts decide readiness.

## Immediate next work, in order

1. **Preserve the verified full v15 combat run and accept the next real round transition.** Use the current SID/job above and keep only the named modified RE5 build playing. The repeating queue was retained across two observations; verify a real terminal boundary still launches that exact build, Chris BSAA and Public Assembly. Continue front/side and isolated hand checks against aiming, pistol grip, reload, melee and locomotion. A headless lifted diagnostic can explain occlusion but cannot substitute for full-character acceptance.
2. **Decide v15 acceptance from visible gameplay.** Save source/output hashes, selected slot/costume, build, session, changed process PID, actual camera frames and score/kills. If the hands/weapon still intersect or point wrongly, fix the measured bind/attachment mapping; do not hide it by only showing the back or disabling the head in the final recipe.
3. **Promote only an accepted exact recipe.** Keep Sonic unregistered until acceptance. `build_grip_candidate` is currently separate from `plan`; registration alone would still invoke the old path. Explicitly select the accepted builder/version, add exact-source/target guards and tests, expose truthful receipt coverage, then make the UI offer only that supported slot. Never silently default to Chris when a different random character is running.
4. **Implement Mario enemy replacement as its own bounded recipe.** First inspect owned Mario library/source assets and record hashes/provenance. Identify the exact enemy archive/class used in the selected stage. Retarget geometry/materials/skin/animation to that enemy, preserve resource namespace and dependencies, build a separate candidate, compare it, then test visible combat. Only combine accepted Sonic and Mario edits into one named overlay when both pass. Do not reuse an old native cast-swap label as proof.
5. **Expand roster and cross-title support deliberately.** Model the source-target capabilities in the UI, including unsupported reasons. Per-title adapters should resolve the target slot, native skeleton/animation IDs, material pipeline, bundle references, outfit/LOD variants and restart semantics. Plan/preview first, tracked build second, explicit apply/restart last. Emit coverage receipts; don't advertise arbitrary cross-title transplantation from one successful pair.

## Native composition and enemy groundwork

The public native player route is bounded to original library `re5ps3_sheva_normal` -> explicit `chris` target. It selects the corresponding owned **Switch** native assets; it does not import the PS3 GLB. `re5_player_archive.py` replaces MOD/MRL while retaining Chris's internal lookup names and other resources, then appends 34 required TEX dependencies. Exact accepted output SHA: `ee04244c4d3012904b4858cef1ce10352f20361963fcc52787543f4ecf9a9800`. Native Sheva source SHA: `77e9ede6a6bf84d74fa487acaca77624e503377c2910d1af62dda0b7f914957e`.

`re5_character_writer.py`, `switch_mods.py` and the native UI now reject unsupported/reverse player pairs actionably. `replacement_scope.gameplay_verified=true` for the bounded acceptance does not imply `complete=true`. The live isolated writer test did not itself prove that the newly deployed API code had been activated.

The measured enemy pair `uEm10.arc` -> `uEm11.arc` requires its paired ExeFS `main.ips` class rebind. `re5_ips.py` verifies the exact existing NSO0 main build ID, original instruction and supported uncompressed text layout before planning it. `re5_char_swap.plan_changes(..., main=...)` refuses this pair without verified main bytes. Keep archive and IPS together. This is evidence for one native class substitution, not a Mario import or an arbitrary class patch.

The fresh read-only Spark audit found **120 RE5 build directories and zero Mario mentions in build names, root JSON markers or overlay paths**. Library entries `mario`, `mario_hd`, `sm64_mario` and `melee_mario` had no RE5 target mapping. Owned SM64 Mario has 20 joints; Melee Mario has 61. Choose a provenance-verified source and measure it before authoring; Render96/model-pack variants are a different provenance. The separate [cast handoff](research/re5-sonic-mario-handoff.md) inventories SA2/SA1 Sonic-family and SM64/SM64 DS/Melee Mario-family donors. Existing enemy harness names and sustained combat with stock-looking enemies are not evidence of a replaced Mario cast.

## Preserve these fixes; don't rediscover the old failures

- ARC entries can share a name across MOD and MRL. Use exact entry index/type (`replace_at`, explicit API indices); ambiguous names return 409. Name-only replacement previously overwrote the wrong resource.
- Preserve shipped zlib framing (legacy raw-deflate is read-compatible), compressed payload semantics and the uncompressed-size tag. Changing the wrapper caused load freezes.
- MOD packed mesh fields are group 12 bits / material 12 bits / LOD mask 8 bits. Old "LOD0" selection was effectively head-material selection, not the whole highest-detail model.
- MOD vertex offsets/indices and root/inverse-bind quantization are measured. Weight-bound trailer records are 144 bytes; update header count at `0xA0` to the new records, preserve mesh ID at `+0x26`, and author bone-local envelopes. A stale count such as 3799 with one record froze loading.
- The atlas preserves source per-triangle materials/alpha; normals use the correct inverse-transpose skin/node transform and normalization. Final UV gradients determine tangents; mirrored seams need separate handedness. Byte `+11` is AO, `+15` tangent sign. Do not overwrite them with guessed normal data.
- Actual Switch TEX BC7 mip/padding layouts are implemented and roundtripped. Preserve container headers, all mips and compression. Neutral native secondary maps were a measured appearance control, not a universal material rule.
- A source A-pose cannot simply be placed around native T-pose bone axes. Sonic now reposes source geometry/normals with proper hand frames while preserving source proportions; root motion is retargeted separately. Fingers need native grip anchors as well as a plausible rest shape.
- Overlay edits compose the latest applied/pending target; donor data stays pristine. Otherwise a later clothes operation can overwrite a native/model replacement from base RomFS.
- `live_use` requires an explicit current, running same-game SID. Session listing includes ended sessions by default. UI waits for nested restart jobs and reports actual same/new-session behavior.
- Round selections are per-session and one-shot, keyed by request identity; prepare -> play -> hot reload must not replay a consumed pick. Operator persistent selections retain their older semantics. Rebecca/Josh indices must not index a hardcoded 10-character family tuple.

## Files, checks and acceptance scope

Core implementation: `gbox/mt_model.py`, `mtf_author.py`, `mtf_materials.py`, `mtf_mrl.py`, `mtf_tex.py`, `mtf_secondary.py`, `mtf_motion.py`, `mtf_motion_edit.py`, `re5_mesh_import.py`, `re5_sonic_hands.py`, `re5_sonic_grip.py`, `re5_sonic_writer.py`. Wiring: `gbox/decrypt_lab.py`, `switch_mods.py`, `re5_character_writer.py`, `re5_player_archive.py`, `model_swap.py`, `mercmode.py`, `mercmode_tool.py`, `screensaver.py`, `mercs/round_controls.py`, and desktop/web comparison/MercMode modules.

Core reported **57 focused v15 tests passing** plus exact output reproduction and the 14-frame grip audit. Existing comparison browser tests exercise real rendering, focus/isolation and labels; native LMT tests explicitly check codec/IK boundaries. The repeat-queue delta has 10 new tests and 174 existing scheduler/recovery tests passing; keep these counts separate from unrelated earlier suites.

From repo root on this Windows workstation, use the audit environment, not the default Python 2.7 installation:

```powershell
$env:PYTHONPATH = 'system'
& .\.venv-session-audit\Scripts\python.exe -m pytest -q -p no:cacheprovider --disable-warnings --basetemp=.scratch-merc-recovery/handoff-tests system/tests/test_re5_sonic_grip.py system/tests/test_re5_sonic_hands.py system/tests/test_re5_sonic_writer.py system/tests/test_mtf_motion.py system/tests/test_mtf_motion_edit.py system/tests/test_decrypt_lab_compare.py system/tests/test_mercmode_repeat_queue.py
node --test system/tests/test_decrypt_lab_compare.cjs system/tests/test_decrypt_lab_compare_window.cjs
```

Use a new ignored basetemp if one is already in use. Browser tests use the existing `system/scripts/browser_lifecycle.cjs` infrastructure and isolated profile/state; do not create another framework or manipulate the user's open window. Dependencies for real BC7 encoding and geometry are installed in the audit venv. Inspect project dependency declarations before assuming a fresh machine has them.

Read [character-replacement-scope.md](character-replacement-scope.md): requested default coverage includes gameplay, in-engine cutscenes, costumes/detail variants and prerecorded cinematics. A native mesh writer cannot rewrite movies by implication. Keep `replacement_scope.complete=false` until the requested appearances are accounted for. See [switch-mods.md](switch-mods.md) for tracked overlay behavior and live restart evidence.

## RE5 mine-policy follow-up

The user subsequently required mines in every character/stage loadout, placed roughly every 30 seconds while fleeing. A live audit found the immediate blockers: saved `mines off` preference revision 4 was being reapplied on launch, the actual inventory contained grenade `0x106` rather than proximity mine `0x10A`, and the sidebar interval was 5 seconds. Root removed only that obsolete mines preference through the agent-context API. Job `4481276a2a794b84` saved `MINES=true` / `MINE_EVERY_S=30`; job `a56842da26ca470f` verified mines enabled at 30 seconds. Those configuration receipts do **not** prove a live mine was placed.

The follow-up code prepares all 54 native loadout templates before actor construction through `mercs_bot.round_ops`, maintains supply through the driver, preserves usable quick-slot grids, identifies the mine rather than casting a grenade into one, and refills positive inventory counts. Root's bot integration lets a due mine interrupt ordinary fleeing after held/dying/healing priorities; the mine action clears the previous escape so two movement policies do not compete. The controller keeps enemy/blast margins, runs toward a clearer site for bounded three-second attempts with one-second combat yields, retries failed equips after three seconds, and rechecks safety before pressing ZL. A mid-cycle blast escape now retains the actual hazard position and current controller clock instead of immediately timing out from a missing player timestamp.

`mines_placed` now increments only after a **new nearby native `uWp0a` actor** appears relative to the pre-press ground scan. Inventory disappearance, count reduction and placing motion are insufficient proof; those observations can still require a precautionary retreat. `mine_last_confirmation` records actor pointer, position, observation time and source, and clears on a new round. `mine_overdue_s`, `mine_blocked_reason` and `mine_relocating` expose starvation rather than hiding it behind attempt counts. Before calling the requested behavior operational, verify real inventory `0x10A`, consecutive native actor receipts about 30 seconds apart when clearance permits, a safe departure, and survival in the actual round. No live placement acceptance is claimed by this addendum; read root's newest receipt for deployment and observed results.

Mine implementation commit `1a56e529` was pushed with concurrent RE6 work preserved in merge `63f241db`. The four bot modules (`re5_switch`, `re5_switch_mines`, `re5_switch_mods`, `mercs_bot`) were reloaded through the installed deployment's bot-only function; one bot resumed in 0.9 seconds, with the service and emulator unchanged. The final targeted suite passed **140 tests**. A read-only native RAM audit verified **54/54 actual Mercenaries templates** carry positive-count quick-slot mines, with zero missing blocks. The old live player still had grenades because its inventory predates this change; the next native round must construct the new inventory. Check the newest acceptance below before claiming live placements.

### Mine acceptance attempt, 2026-11-09 ~10:45-11:30 UTC (DeepSeek resume)

First round after a bot-reload round started with the new inventory: `re5_mods op=status` reported `mine_loadout=true`,
`mine_settings={enabled:true, interval_s:30.0}`, and the live autoplay telemetry
(`GET /api/autoplay/telemetry/<sid>`) showed `mines_placed=0, mine_attempts=1, mine_equip_failures=1` with
`mine_blocked_reason="enemy too close"` and `mine_relocating=true`. Two defects were fixed in `re5_switch_mines.py`:

1. **The bomb was looked up only through its quick-grid record** (`stack()` requires `grid in QUICK`). When the equip
   press moves or re-hands the item, that lookup fails and a successful press was scored as "the bomb did not come to
   hand". The new `Mines.equipped()` finds the bomb by its own `rounds>0` + `hand` flags, and the equip state plants
   from that.
2. **The cycle's state clock ran on wall time even while the controller was not ticking** (held by a Majini, healing,
   a reload stall). A grab longer than `EQUIP_S` therefore failed an attempt whose press had landed. `GAP_S = 0.75`
   now pauses `self.t` across tick gaps, so `EQUIP_S`/`PLACE_S`/`SETTLE_S` measure only active control. The engine's
   real cadence is 0.05 s, so a real gap of that size is always an interruption.

Tests: `test_re5_switch_mines.py` gained the gap-pause, in-hand-without-grid and empty-stack cases; the two tests that
depended on sparse tick spacing now tick at the engine cadence. Mine/policy/supply suites: **49 passed**; the
`mods`/`parity`/`directives` suites also pass. (The 10 `test_mercmode_repeat_queue.py` failures pre-date this change:
they fail identically on the stashed tree in this checkout.)

Commit `ecba20b1` is pushed. **Live acceptance is still not claimed** — two blockers, in order:

- The Spark's only Switch emulator was taken by the operator's RE6 Switch session (`4e342e9e…-4d2815d5…`, launched
  by actor `operator`, no autobot, 0 stream viewers), so MercMode reported "a game is already running there" and no
  RE5 round could run. This session must not be killed by an agent.
- After that, the workstation's `pwsh` startup wedged machine-wide (even `git log -1` and `whoami` hang; a fresh
  subagent sees the same), so no further git/HTTP/test/deploy work was possible from this session.

Next session, in order: (a) wait for the RE6 session to end (or have the operator stop it) so MercMode restores the
modified RE5 run; (b) deploy `ecba20b1` to the Spark with `deploy_main.sh --deploy` (bot-only reload; never restart the
service for this) — the share currently runs the pre-fix mine module; (c) run
`.scratch-deepseek/mine_probe.py <sid> 40 5` while sampling `GET /api/autoplay/telemetry/<sid>` to confirm real
inventory `0x10A`, `mines_placed` rising with new `uWp0a` actors ~30 s apart when clearance permits, a safe departure
and survival; (d) only then call the requested behavior operational and record the receipt here.

The live telemetry endpoint publishes scalar stats only (`tools.py`); nested `mine_supply` and `mine_last_confirmation` objects are not in that endpoint. Use its strict `mines_placed` counter with fresh session/gameplay evidence, and read native inventory/ground actors or full job results for detailed receipts. Do not interpret an omitted dictionary as supply being disabled. Deployment also synced concurrent main work to disk; only the four mine-related bot modules were activated here. Do not restart the service solely because a broader deploy-pending marker exists.

## Runtime/service continuity and safe resumption

API origin is `http://10.89.1.246:8765`; Spark host is lilspark (SSH alias `spark`). Historical worker ID `e93128c2856b4eab` can change. Existing local token file is `system/gbox-data/api_token`; read it into an Authorization header and never print, paste or commit it. Start with read-only current workers/jobs/sessions/MercMode and git status/log. Do not blindly replay ignored helpers containing old process/session/commit identities.

The service-restart delay was real: external Hermes gateway/cron processes are in separate user service/scope cgroups, but the old gBox process itself serves active inference proxy streams. Restarting gBox can cut those requests even though it does not kill the external Hermes processes. The audited service stop timeout was 10 seconds. There is no atomic request-admission/drain barrier; a momentary quiet sample is not a guarantee.

Root and the Merc agent completed the narrowly scoped activation at 07:10:42 UTC using exact identity guards and retry evidence for the callback-free inference work; its successful preservation checks are recorded above. No further activation is pending for `554a3e20`. This is not blanket authorization to bypass global guards or restart all workers. Check the newest activation receipt and service PID before any later operation. In-flight write-capable MCP requests may have unknown outcomes and must not be blindly replayed. Committed SQLite jobs survive a restart, but in-process session-swap/reset orchestration can be interrupted; inspect those jobs before retrying.

At an earlier old-service checkpoint, turning MercMode off could allow a generic idle PS3 demo to start. Root accounted for this explicitly during activation. Preserve the latest user-directed modified-only state; do not toggle settings casually to obtain a quiet server.

Keep ignored source assets, candidate binaries, temporary tokens, screenshots and process-owner receipts out of Git. Commit source/tests/docs only after targeted checks. Keep this handoff and `reply.md` synchronized with actual final build/session/acceptance evidence, rather than treating an experiment's successful build as completion.
