# RE6 Switch live run runbook (Sonic on Leon / full roster)

Everything below is already built on the automation node (`i9-NUC`); this is the exact sequence to put a build on the
emulator host and have the bot play it. It exists because the node's command runner deadlocked during the first live
session (2026-11-09) and could not be recovered without restarting the gBox/DSH app.

## What is where

| item | path |
|---|---|
| geometry-only build (first live run) | `D:\gBox\cache\mods\115f9cdbba115432\re6sw_sonic_leon` (30 files, 33.5 MB) |
| textured build (**use this one**) | `D:\gBox\cache\mods\115f9cdbba115432\re6sw_sonic_leon_tex` (37 files, 46.3 MB) |
| per-costume roster, 51 slots | `D:\gBox\cache\mods\115f9cdbba115432\re6sw_smash_cast` (217 files) |
| textured roster, 7 characters | `D:\gBox\cache\mods\115f9cdbba115432\re6sw_textured_cast` (296 files, 440 MB) |
| reference-bone A/B probe recipe | `C:\_tools\gBox\.tmp\build_rev_variant.py` |
| install helper (upload + write + select + launch) | `C:\_tools\gBox\.tmp\install_switch_build.py` |

Emulator host: **lilspark** (`4e342e9ebf5948da`), Eden. Its load directory (gBox-managed):
`/home/ehm_eckx/gBox/system/gbox-data/runtime-linux-aarch64/eden-linux/data/eden/load/01002A000CD48000`.
The RE6 Switch title: gBox game `115f9cdbba115432`, title id `01002A000CD48000`.

## 1. Install and swap a build (one command, from the node)

```powershell
python C:\_tools\gBox\.tmp\install_switch_build.py re6sw_sonic_leon_tex --launch
```

It uploads every file as a control-plane artifact, calls `switch_mods op=write` on lilspark with the artifact changes,
`op=select` to enable that build (and disable the other RE6 builds), then
`POST /api/games/115f9cdbba115432/launch?node=lilspark&mod=<build>` which swaps the mod into the running session.

If the app/runner is healthy but the script is not available, the same steps by hand:

```powershell
$tok = Get-Content C:\_tools\gBox\system\gbox-data\api_token
$h = @{ Authorization = "Bearer $tok"; 'Content-Type' = 'application/json' }
# per file: POST /api/artifacts?name=<rel> (raw body) -> {"sha256": ...}; collect { "romfs/<rel>": {"artifact": sha} }
$body = @{ tool='switch_mods'; require_worker='4e342e9ebf5948da'; input=@{
            op='write'; game_id='115f9cdbba115432'; build='re6sw_sonic_leon_tex'; changes=$changes } } |
        ConvertTo-Json -Depth 8
Invoke-RestMethod -Uri 'http://10.89.1.246:8765/api/jobs' -Headers $h -Method Post -Body $body
```

## 2. Make the bot play (why it did not)

The first live session was launched with a plain launch call (no `autoplay=true`), so Eden booted the title with the mod
and **no bot**. `autoplay op=prepare` is not the hand-off: it drives a *paused warm* game's menus to a round start (it
timed out on a running session).

Start the bot on the live session either from the gBox viewer's **Autoplay** control, or:

```powershell
$body = @{ tool='autoplay'; require_worker='4e342e9ebf5948da'; input=@{
            op='start'; session_id='<session id>'; mode='auto' } } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri 'http://10.89.1.246:8765/api/jobs' -Headers $h -Method Post -Body $body
```

RE6's playbook is `mercs_bot`; with no mission it takes over wherever the player is (the round in progress).

## 3. Capture the evidence

- Frame: `GET /api/sessions/<sid>/frame.jpg` (Bearer token) → PNG/JPG of the live frame.
- Session record: `GET /api/sessions` (fields `mod`, `mod_build`, `detail.overlay`).
- Save the accepted frame under `system/docs/evidence/re6-scale/` and reference it from
  `system/docs/re6-model-replacement.md`.

## 4. If the model still looks wrong

- **Colour wrong, shape right**: the build is geometry-only or the two-half `0x2B` albedo is sampled differently by the
  shader. Try `re6sw_sonic_leon_tex`; if it is still wrong, dump a frame of the character select and the round and
  compare which texture the material picks (the binding is decoded in `re6_switch_tex.body_albedo_paths`).
- **Shape/scale wrong** (huge, stretched, wings): the four-weight joint-byte order is the first suspect. Build the
  A/B probe with `python C:\_tools\gBox\.tmp\build_rev_variant.py` (produces `re6sw_sonic_leon_rev`) and install it
  the same way. `mtf_author.build_one_mesh(..., reverse_bones=True)` stores the joint bytes b3,b2,b1,b0 instead of
  b0,b1,b2,b3; compare the two frames.
- **Nothing renders / game falls back to a box**: check `GET /api/sessions` overlay (`enabled`, `files`) and the Eden
  log path in the session detail; a failed mod shows as the native character rather than a crash.
