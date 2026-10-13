# universal-modder in gBox (#825)

[universal-modder](https://github.com/rehan-remade/universal-modder) is a kit of agent skills, a Python CLI (`um`) and a
knowledge base for modding PC games with AI agents. gBox takes its tools apart and turns them into typed worker tools
(`gbox/universal_modder.py`). The chat agent, Hermes and MCP clients can call them on any worker, and on a live session.

- **Licence:** MIT (Copyright (c) 2026 Rehan and universal-modder contributors). The licence text is in
  `gbox/vendor/universal_modder/LICENSE`.
- **Pinned commit:** `5ba8150e27b4f1bf17ae19dcecdb2341e467885a` (package version 0.2.0, read 2026-10-12).
- **Dependencies:** upstream needs Pillow, NumPy and PyYAML. gBox already depends on all three, so nothing new is
  installed. ComfyUI and Blender are optional and run as separate programs.
- **Approach:** vendored, not bridged. The modules are plain Python with no installer, so a pinned copy is simpler and
  safer than shelling out to a `um` install. `gbox/vendor/universal_modder/__init__.py` lists every file taken and every
  change made. Each change is also marked with a `gBox:` comment in the code.

## Tools

Every result has `changed` (what the op wrote) and `undo` (how to reverse it). Read-only ops return `changed: []`.
Nothing writes into a game install. Mods go to gBox's mod folders, and snapshots and renders go to
`<cache>/universal_modder/`.

| Tool | Ops | Changes / undo |
|---|---|---|
| `um_scan` | `scan` (session_id, game_id, path or name) and `list`. Reports engine and version, .NET or native, anti-cheat, mod loaders, mod and save folders, ranked routes and the engine playbook. | Read-only. |
| `um_kb` | `search` (from the offline index of about 200 field notes), `show` (fetches the note from the pinned commit and caches it), `playbook`, `safety`, `engines`. | `show` caches the note under `<cache>/universal_modder/kb/<commit>/`. The copy is harmless to keep or delete. |
| `um_backup` | `create`, `list`, `diff`, `restore`, `delete`. Snapshots are zip files with a sha1 manifest. | `create` adds a zip (undo: `delete`). `restore` is a dry run unless `confirm=true`. Before writing it takes a `<name>-pre-restore` snapshot (undo: restore that one), and it refuses Steam, Epic, Xbox and session install folders. `delete` cannot be undone. |
| `um_publish_check` | Lints a mod folder or a gBox mod: game files copied verbatim, leaked keys, decompiled code, user paths, missing README. | Read-only. |
| `um_mod` | `stage` (files from worker paths or artifacts go to `cache/mods/<game_id>/<name>/` with `.gbox-mod.json` and a README), `list`, `remove`. | `stage` writes only into that folder and never replaces another tool's mod. `remove` moves the folder to `<cache>/universal_modder/trash/` (undo: move it back). |
| `um_sprite` | `info`, `cutout`, `fit`, `pixelate`, `palette`, `sheet`, `slice`, `frames`, `team_mask`, `seamless`, `tile_preview`, `preview`. Input is a worker file, an artifact, or the live session's frame (with `crop`). | Outputs are new artifacts. With `mod` and `game_id` they are also staged into that mod (undo: `um_mod op=remove`). |
| `um_comfy` | `status`, `image` (ComfyUI's default text-to-image graph; `sprite=true` cuts the result out), `run` (any API-format workflow, with `set` overrides). | Writes PNGs and `comfy_manifest.jsonl` under `<cache>/universal_modder/comfy/` (undo: delete them). |
| `um_render3d` | Renders a collection character, a glb artifact or a worker path with headless Blender. Presets: `aoe2`, `iso8`, `trueiso`, `topdown`, `side`, `turntable`. Produces one sheet per animation. | Frames go under `<cache>/universal_modder/render3d/<name>/` (undo: delete that folder). Sheets can be staged into a mod. |

Live-session hooks:

- `um_scan session_id=` resolves the session's game folder: the Steam `common/<game>` or Unreal project folder for a PC
  exe, or the disc root for a PS3 disc folder. If the session runs a ROM or disc image, it explains why there is no
  folder to scan instead of scanning the ROM library.
- `um_sprite session_id=` works on the frame on screen.
- `um_backup restore session_id=` also protects that game's folder.
- `um_publish_check session_id=` compares the mod against the running game's files.

The chat agent has every tool in `tool_specs`, plus an `Agent` method that sends the job to the session's worker, the
`worker` given, or else a Windows node. A SYSTEM-prompt rule routes "what engine / how do I mod / has anyone modded X"
to them. MCP clients get them automatically from the registry as `job_um_scan`, `job_um_kb` and so on.

`filemods.launch_path` refuses to launch a mod whose `.gbox-mod.json` says `"launchable": false`. Staged universal-modder
mods are overlays, not game copies.

## Left out, and why

| Upstream | Why it is not in gBox |
|---|---|
| `um fal` (fal.ai sprites, 3D, rigging, audio, video) | A paid cloud API. It needs `FAL_KEY` and uploads local files to a third party. `um_comfy` covers local image generation. |
| `um win` and `um/ps1` (WinDrive input, process-loopback audio, `kill`, `launch`, `reg set`, `setup`) | Input injection, killing processes, writing to the registry and downloading an ffmpeg build are unsafe as agent tools. gBox's session tools (look_at_screen, get_frame, session_op send_input, recording, launch and stop) already cover them. |
| `um video` (showcase video editor) | A large ffmpeg EDL renderer. gBox has its own recording and clip pipeline. It can be added later as `um_video` if wanted. |
| `um kb new`, `check`, `index`, `sync`, `pr` | They write notes, push branches and open GitHub PRs. gBox keeps what it learns in its own knowledge base (`recall`, `save_recipe`, `re_playbook`). Search and show stay, pinned to the vendored commit instead of following `main`. |
| `knowledge/` notes (3.3 MB) | Only `index.json` is vendored, for offline search. Notes are fetched one at a time on `show`, from the pinned commit only. |
| Agent skills, plugins, MCP configs, `examples/`, `cli.py` | Instructions for other agent hosts and demo mods. The engine playbooks and safety rules from `skills/mod-any-game/references` are vendored and served by `um_kb`. |

## Tests

`tests/test_universal_modder.py` tests every op against fakes: temp game folders (a fake Unity install with BepInEx
and, in one test, EasyAntiCheat), a fake live session and frame, fake GitHub raw fetches, a fake ComfyUI server and a
fake Blender subprocess. It also checks registration (worker, MCP `info()`, agent specs and worker routing).
`tests/test_tool_registration_resilience.py` still passes.

```
python -m pytest tests/test_universal_modder.py tests/test_tool_registration_resilience.py -q -p no:cacheprovider
```

## Live check (agent test PC, after deploy)

1. In the gBox chat on the Windows PC, type: `what engine is <an installed Steam game> and has anyone modded it?`
   The agent should call `um_scan` (name or session_id) and then `um_kb op=search`. The reply should name the engine,
   loaders and anti-cheat, and list the field-note titles.
2. `back up my <game> saves`: `um_backup op=create path=<a saves folder um_scan listed>`. The result's `undo` names the
   delete call. `um_backup op=restore name=<set>` without confirm returns `dry_run: true` and changes nothing.
3. During any session: `cut out the sprite at 40% across, 60% down`. The agent should call `um_sprite op=cutout
   session_id=<sid> crop=[...]`, and a PNG artifact should appear in the chat.
4. From Claude Code with the gBox MCP server: `job_um_kb {"op": "search", "query": "unreal pak"}` returns hits, which
   confirms the MCP registration.
5. Optional: with ComfyUI running on that PC, `job_um_comfy {"op": "status"}`. With Blender installed,
   `job_um_render3d {"character": "<collection slug>", "preset": "side", "anims": "idle:4:bob"}`.
