# What this is: gBox engineering overview

**Purpose of this file.** A bird's-eye engineering briefing for an LLM (or an engineer) to get up to speed on gBox
without reading the repository. It covers structure, paths, runtime topology, data model, security, LLM/agent
integration, tools, emulators, optimisation, the DGX Spark setup, footprint and external dependencies. It is updated
at intervals; the "Last updated" line and §19 changelog say what changed. Statements are marked **verified** only
where they were exercised on the real machines.

Last updated: 2026-10-08.

---

## 1. One-paragraph summary

gBox is a self-hosted "universal game laboratory". It catalogs a large retro/console game library on a NAS
(over 63,000 entries), launches supported titles in emulators on a Linux GPU box (NVIDIA DGX Spark, arm64) or natively on a
Windows PC, streams and controls sessions, and exposes the running game to tooling: live memory read/write/freeze,
a CPU debugger (registers, disassembly, breakpoints, watchpoints), per-game *semantic state* profiles (player HP,
position, enemies…), autonomous play (navigation, combat, missions with recorded metrics), Ghidra static analysis
correlated with runtime observations, asset extraction to a canonical package format (UAP) with glTF export and a
Blender bridge, and an LLM chat/voice agent that drives all of it through typed, audited tools. A FastAPI control plane
on the Spark coordinates workers (the Spark itself and a Windows node) through a job queue; an Electron desktop app is
the main UI.

## 2. Goals (from `gBox Plan.md`, the master plan)

1. Universal library: scan, search, launch any title the operator owns (HyperSpin/Attract-Mode library + extra ISOs).
2. Universal runtime adapter: one capability interface over many emulators (memory, input, frames, state, debug).
3. Instrumentation → semantic state → autonomous play (first target: *Phantasy Star Online Ver.2*, Dreamcast).
4. Ghidra as an analysis service; static ↔ runtime correlation recorded as evidence-backed knowledge.
5. Asset lab: extract models/textures/skeletons/environments → UAP → glTF/OBJ → Blender / game engines.
6. Live picker (click an on-screen object → extract it), environments, mod builder, cross-title reuse.
7. Accountability: every action is a typed job with receipts, artifacts, audit log; LLM claims are never trusted
   without validation; evaluation must come from a different actor than the proposer.

Phase status (plan §26): 0 ✅, 1 ✅, 2 ✅ GC + DC state verified, 3 ✅ GC mission (repeatable, evaluated), DC route
autonomous, 4 ✅, 5 ✅, 6–9 in progress. See `ROADMAP.md` for evidence per phase.

## 3. Physical / network map

```
                         LAN 10.89.1.0/24
 ┌──────────────────────────────┐            ┌──────────────────────────────────┐
 │ NAS 10.89.1.125 (SMB)        │            │ DGX Spark "lilspark" 10.89.1.246 │  NVIDIA GB10, arm64, 121 GB RAM, 20 cores
 │  \HyperSpin Attraction\Arcade│◄──cifs ro──┤  /mnt/gbox/hyperspin              │
 │  \QuickSwap2\...\GC ISO      │◄──cifs ro──┤  /mnt/gbox/quickswap2             │
 └──────────────────────────────┘            │  :8765 gBox API + linux worker   │ (systemd gbox.service, user ehm_eckx)
                                             │  :11434 Ollama (LLMs)             │
                                             │  :8081 SearXNG (docker)           │
                                             │  :10300 Wyoming faster-whisper STT│ (docker)
                                             │  :10200 Wyoming Piper TTS         │ (docker)
                                             │  :8090 Pine Box Voice Director    │ (XTTS v2 voice cloning; Kokoro :8776)
                                             │  :4416 bgutil yt-dlp PO provider  │ (docker, localhost)
                                             │  SMB share \\10.89.1.246\ehm_eckx  │ ← canonical repo lives here
                                             │  per-session Xvfb :90+ , GDB stubs│ (localhost ports, ephemeral)
                                             └───────────────▲──────────────────┘
                                                             │ HTTP (bearer token), MJPEG, long-poll input
 ┌───────────────────────────────────────────────────────────┴───────────────────┐
 │ Windows PC "i9-NUC": Electron desktop app (gBox), Windows worker (python),    │
 │ native RetroArch ("gBox Game.exe"), Blender 5.3, Ghidra 12.1.4 + JDK 21,      │
 │ D:\gBox\cache (staging) D:\gBox\runtime (cores, ghidra, jdk) D:\gBox\recordings│
 │ git repo C:\_tools\gBox (origin github.com/teamcsharp/gBox), mirrored from share│
 └────────────────────────────────────────────────────────────────────────────────┘
```

Other containers on the Spark that gBox does not own: home-assistant, open-webui (:12000), voice-lab, spark-agent,
openwakeword (:10400), docker-socket-proxy (localhost:2375).

## 4. Repository layout

The repository root holds only `gBox.exe` (PyInstaller launcher for Windows) and `system/`.

```
gBox.exe                     Windows launcher: first run installs Electron + worker venv, then starts the app
system/
  gbox.toml                  site config (libraries, data/cache dirs, LLM endpoints, permissions, ghidra_home…)
  gBox Plan.md               master plan (requirements, phases, definition of done)
  README.md ARCHITECTURE.md ROADMAP.md SECURITY.md LICENSES-THIRD-PARTY.md
  docs/                      per-subsystem docs (this file, tool-contracts, emulator-adapters, ghidra-service, …)
  gbox/                      the Python package (control plane, worker, tools, adapters, analysis)
    __main__.py              CLI: serve [--worker], worker, init, setup, scan, schemas
    config.py                Config model (pydantic); per-OS paths (libraries, cache_dirs, runtime_dirs)
    models.py                Job, Receipt, WorkerInfo, CatalogEntry, KnowledgeEdge, RunRecord, Permission…
    registry.py              @tool registry: typed input/output, permissions, timeouts, validate/on_accept/on_fail
    store.py                 SQLite (WAL): docs table (jobs, sessions, chats, runs, edges, profiles…), catalog + FTS5,
                             hash-chained append-only audit, content-addressed artifact store
    server.py                FastAPI control plane (§7), static UIs, session streaming hub, chat hub, voice proxy
    worker.py                job worker loop (claims jobs matching its capabilities/OS, posts results)
    tools.py                 the typed tools (§8) + live session plumbing (_pump: frames/input/status/RPC)
    adapters.py              emulator adapters (§9): RetroArch, Dolphin, mGBA, DuckStation, MAME, RocketLauncher, Steam
    provision.py             dependency auto-install: apt, flatpak, libretro cores/BIOS, RetroArch, VirtualGL,
                             Ghidra, JDK 21, Blender add-on, rcedit/branding, NAS mounts
    catalog.py systems.py    library scanner (Attract-Mode/HyperSpin configs + romlists, header sniffing), platform rules
    debug.py                 CPU debugger: GDB remote-protocol client, register layouts, Capstone disassembly, VRAM map
    semantic.py              profile-driven semantic state extractor with invariants (profiles/*.json)
    autoplay.py              input driver, navigation (camera learning, A* on geometry grids), combat, mission runner
    bridge.py                Ghidra ↔ runtime correlation workflow → knowledge edges
    agent.py                 chat agent: tool specs, loop, ChatHub (conversations, game association, metrics)
    speech.py                STT/TTS (Wyoming, Voice Director XTTS/Kokoro)
    uap.py                   Universal Asset Package: schema, validator, glTF 2.0 / OBJ exporters
    ninja.py                 Sega Ninja formats: PRS, BML archives, NJCM chunk models, PVM/PVR textures → UAP
    psomap.py                PSO map data: collision REL (GC/DC) → walkable grid
    gcdisc.py gdrom.py       read-only GameCube ISO and Dreamcast GD-ROM (.gdi) filesystems; DOL/RAM → ELF
  profiles/                  semantic state profiles: pso-gc-plus-us.json, pso-v2-dc-us.json, auf-gcn-us.json (with evidence)
    entity_probe.py          generic entity/camera probe for table-of-records games (007 AUF; docs/auf-entity-analysis.md)
  adapters/ghidra/           Ghidra scripts: ExportAnalysis.java, ExplainAddresses.java
  clients/
    web/index.html           browser UI (library, sessions, inspect: memory/tiles/CPU/game state, controllers, ops)
    desktop/                 Electron app: main.js (windows, worker supervision, capture/record, embedding),
                             index.html (chat bar, Talk sidebar, inbox, tools), preload.js, winembed.py, launcher.py,
                             install.ps1
    blender/                 gbox_addon.py (clipboard paste), gbox_bridge.py (headless glTF import + report)
  scripts/                   bootstrap-linux.sh, bootstrap-windows.ps1, compat_sweep.py, agent_ledger.py
  schemas/                   JSON Schemas exported from the models
  tests/                     pytest suite (control plane, adapters, catalog, attract, UAP)
  assets/brand/              logo/icons used everywhere (app, exe, taskbar, emulator windows)
  gbox-data/                 RUNTIME DATA (gitignored): api_token, gbox.sqlite3, artifacts/, thumbs/, uap/, analysis/,
                             runtime-<os>-<arch>/ (cores, states, saves, logs, dolphin-user, recordings…)
```

Where things actually run: the Spark runs from `/home/ehm_eckx/gBox/system` (= the SMB share); the Windows worker and
desktop app run from `C:\_tools\gBox\system` (the git repo, mirrored from the share with `.git` excluded).

## 5. Architecture and data flow

* **Control plane** (`server.py`, FastAPI/uvicorn, :8765). Owns the SQLite store, job queue, catalog search, artifact
  store, audit chain, chat hub and the live-session hub (frame buffer, input queue, RPC rendezvous).
* **Workers** (`worker.py`): the Spark worker runs inside the same service process (`serve --worker`); the Windows
  worker is spawned and supervised by the Electron app. Workers register their capabilities/OS, long-poll for jobs,
  run tools, upload artifacts, post receipts. Jobs can be pinned by OS or worker id.
* **Sessions**: `launch_game` creates an adapter instance on a worker; the worker then runs three loops per session —
  frames (one long-lived streaming upload of length-prefixed JPEGs), input (long-poll; pad events + inspector/debug
  RPCs) and status. Session ids are `<worker_id>-<job_id>`. Browser/desktop clients view `GET /api/sessions/{sid}/mjpeg`
  and post input to `/input`; RPCs (`read_memory`, `debug_*`, `state`, `read_rom`, `info`) go through `/rpc` and are
  answered by the worker within 10 s.
* **Everything else** is a typed tool executed as a job (`POST /api/jobs {tool, input, require_os?}`) producing a
  receipt with validated artifacts.

## 6. Data model (design schema)

* `catalog` (game_id, library, title, platform, system, year, body JSON) + `catalog_fts` (FTS5, rowid-linked).
  CatalogEntry: rel_path, system, collections[], core, launch{kind,…}, media{boxart,snap,logo…}, size, playable,
  favourite/recent flags, cached_on.
* `docs(kind, id, body)` generic documents: job, receipt, worker, session, chat, run, edge (knowledge), profile,
  artifact (metadata), request (inbox).
* Audit: append-only table with SHA-256 hash chain (trigger blocks edits; `/api/audit/verify` checks the chain).
* Artifacts: content-addressed files under `gbox-data/artifacts/<sha256>` with media type + provenance JSON.
* KnowledgeEdge: {game_id, src, rel, dst, confidence, status hypothesis|validated|deprecated, evidence[artifact sha],
  source}. "validated" requires existing evidence artifacts.
* RunRecord (§21): objective, initial_state, policy_version, proposer, outcome, metrics, artifacts (trace, MP4),
  evaluation (only by a different actor).
* UAP manifest: meshes (positions, normals, uvs, indices, joints/weights), materials (+texture paths), skeleton (bones
  with TRS), animations, nodes, collision, confidence per dimension, provenance, source identity.
* Semantic profile (`profiles/*.json`): match {platform, title_contains, memory signature}, endian, entity table
  address, struct size, common fields, kinds (by class-name prefix or entity-id range) with kind fields, globals,
  per-field evidence strings.

## 7. HTTP API (control plane)

Catalog: `GET /api/catalog` (q, platform, system, sort, favorites, recent, local, letter, offset, limit),
`/api/catalog/best?q=` (ranked title match), `/facets`, `/platforms`, `/letter_offset`, `/{gid}`, `POST /{gid}/favorite`,
`/{gid}/status`, `POST /api/games/{gid}/launch?node=&debug=`.
Jobs: `GET/POST /api/jobs`, `/api/jobs/{id}`, `/cancel`, `/progress`; workers: `/api/workers`, `/register`, `/claim`,
`/result`; receipts; artifacts (`GET`, `/meta`, `POST /api/artifacts?name=&media_type=&provenance=` raw body).
Sessions: `/api/sessions`, `/{sid}/mjpeg`, `/frame.jpg`, `/input` (GET long-poll for workers, POST events),
`/rpc` (+`/rpc/{rid}` worker answers), `/stream` (worker upload), `/ended`.
Knowledge & runs: `POST /api/knowledge`, `POST /api/runs`, `/api/runs/{id}/evaluation`. Audit: `/api/audit`, `/verify`.
LLM/chat/voice: `/api/llm/models`, `/api/chat*` (conversations, messages, suggest), `/api/intent` (instant
"load/search" commands), `/api/stt`, `/api/tts`, `/api/voice/voices`. Misc: `/api/media`, `/api/systemart`, `/api/thumbs`,
`/api/clipboard` (Blender bridge), `/api/requests*` (operator inbox), `/api/registry` (tools, agents, Ghidra scripts),
`/api/metrics`, `/api/health`. Auth: `Authorization: Bearer <gbox-data/api_token>`; actor name via `x-gbox-actor`.

## 8. Tool system

`registry.py` defines `@tool(name, version, In, Out, capabilities, permissions, timeout_s, side_effects, artifacts,
validate, on_accept, on_fail, check)`. A worker only advertises tools whose `check()` passes on that host. After a run
the control plane re-validates outputs (independent validation; e.g. glTF round-trip vertex count, Blender vertex/bone
counts, artifact hashes) before accepting a receipt. Mutating tools need granted permissions (`gbox.toml`).

Current tools: `echo_artifact, scan_library, hash_game, launch_game, session_op (pause/resume/stop/save_state/
load_state/record_start/record_stop…), read_memory, write_memory (audited, keeps previous bytes for rollback),
freeze_memory, get_frame, export_asset, extract_pso_model, open_in_blender, analyze_binary, ghidra_script,
provision_node, llm_complete`.

## 9. Emulator structure

| Adapter | Used for | Control | Debug level |
|---|---|---|---|
| `RetroArchAdapter` + libretro cores | default for ~60 platforms (Linux: per-session Xvfb + VirtualGL on GPU; Windows: native window embedded in the app) | UDP network commands (status, pause, state, frame advance, rewind, READ/WRITE_CORE_MEMORY / CORE_RAM) | memory + Capstone disassembly |
| `DolphinAdapter` (flatpak) | GameCube/Wii by default on Linux | xdotool keys (GCPadNew.ini), GDB stub | full: registers, step, breakpoints, watchpoints |
| `MgbaAdapter` (apt) | GBA debug launches | xdotool, GDB stub (port 2345, one at a time) | full |
| `DuckStationAdapter` (flatpak) | PS1 debug launches | xdotool, GDB server | full |
| `MameAdapter` (apt 0.264) | arcade debug launches | xdotool, gdbstub (target.xml) | full for gdbstub-supported CPUs |
| `RPCS3Adapter` (official build + Sony firmware, auto-installed) | PS3 extracted disc folders (library `ps3`), Windows nodes | process; Xbox pad = player 1 (XInput profile written on first launch); pause/resume = NtSuspend/ResumeProcess | guest memory read/write via the process (PS3 address + host base 0x300000000), committed-region map |
| `RocketLauncherAdapter` | Windows: systems without a libretro core, via the drive's own emulators | process | none |
| `SteamAdapter` | Steam titles | URL launch | none |

Selection: `adapters.for_game(game, config, debug)`. Cores, BIOS and assets are downloaded on first use. Disassembly
covers PPC, SH4/SH2, MIPS LE/BE, ARM/Thumb, 68k, 6502/65C02/65816, x86. Not available: N64/SNES/Genesis/NES full
debug (no prebuilt emulator with a working stub on arm64; ares' stub drops connections), Dreamcast breakpoints (Flycast
needs a source build with `ENABLE_GDB_SERVER`, which needs operator approval).

## 10. LLM and agent integration

* Models: Spark-local Ollama via the OpenAI-compatible API (`/v1/chat/completions` with tools). Default
  `qwen3.6:35b`; picker lists every installed model with tool/vision/audio/thinking capabilities (refreshed live).
* Agent (`agent.py`): system prompt + live-game context (title, platform, ROM, runtime) injected per turn; web search
  is pinned to the live game title. Tools: `web_search` (SearXNG), `web_fetch`, `search_games`, `launch_game` (incl.
  debug), `list_sessions`, `session_info`, `read_memory`, `write_memory`, `freeze_memory`, `memory_snapshot`,
  `memory_filter`, `extract_tiles`, `look_at_screen` (vision model), `debugger`, `find_code_that_writes`
  (Ghidra bridge), `ask_user` (clickable multiple choice), `ghidra_scripts`, `run_tool` (any typed tool).
* Voice: Talk mode (VAD → Wyoming faster-whisper → agent → XTTS v2 cloned voices or Kokoro), dictation mic on every
  text box. Instant commands ("gBox, load …", "search for …") bypass the LLM.
* Accountability: each chat request is metered (time, tokens, tools) into the operator inbox; Claude Code sessions on
  the repo are logged by hooks (`scripts/agent_ledger.py`).

## 11. MCP offerings

gBox does **not** expose an MCP server yet. Everything an MCP server would offer already exists as typed HTTP
tools (§7–8), so a thin MCP adapter mapping `/api/registry` tools → MCP tools is the intended path. External MCP servers
are not used by gBox at runtime.

## 12. Security overview

* Single bearer token (`gbox-data/api_token`, never in git); all endpoints require it except static assets. Actor
  names are recorded but not authenticated separately (trusted LAN). See `SECURITY.md`.
* Permissions per tool (read, execute, memory_write, install, …) granted in `gbox.toml`; mutating tools are audited;
  memory writes keep the previous bytes for rollback; audit log is hash-chained and append-only.
* NAS mounts are read-only; source ROM/disc files are never modified (staging copies go to local cache; disc readers
  are read-only).
* Electron: `unsafely-treat-insecure-origin-as-secure` for the Spark origin (mic access over HTTP on the LAN).
* No cloud services are required; LLMs, STT, TTS, search run on the Spark.

## 13. System optimisation

* Rendering on the GB10 GPU via VirtualGL EGL for RetroArch; Dolphin uses Vulkan in its flatpak (NVIDIA GL extension).
* Streaming: persistent ffmpeg x11grab → MJPEG (≈55 fps), one upload stream per session, long-poll input, X key
  auto-repeat disabled on session displays, minimum 60 ms key hold for batched presses.
* Debugger I/O: TCP_NODELAY + TCP_QUICKACK on the GDB socket (1 MB read: 21 s → 0.1 s); whole-state reads under one
  CPU halt; RetroArch RAM reads in 16 KB UDP requests (16 MB Dreamcast RAM in ~17 s); `player_only` state reads for
  movement loops.
* Catalog: SQLite FTS5 with chunked upserts; thumbnail cache; library staging cache (Spark 150 GB, Windows D: 250 GB,
  LRU) for large discs.
* Windows native play for zero input lag; Spark streaming for anything else.

## 14. DGX Spark integration guide (condensed)

1. Share `\\10.89.1.246\ehm_eckx\gBox` is the canonical tree; `scripts/bootstrap-linux.sh` creates
   `system/.venv-linux-aarch64`, runs `gbox setup` (apt, NAS fstab mounts with backup, VirtualGL check, RetroArch
   build, cores, BIOS, Ghidra/JDK) and installs `gbox.service` (TimeoutStopSec=10).
2. Restarting `gbox.service` reloads code but ends running sessions (they are children of the service).
3. Flatpaks (Dolphin, DuckStation, PPSSPP, ares) need `flatpak run --filesystem=…`; DuckStation also needs
   `dbus-run-session` and its settings.ini patched in place.
4. Spark-only services gBox depends on: Ollama, SearXNG, Wyoming whisper/piper, Voice Director.
5. arm64 caveats: Ghidra's native decompiler is x86_64-only → decompilation jobs run on the Windows worker; some
   libretro cores have no aarch64 build (fallbacks in `provision.CORE_FALLBACKS`).

## 15. File footprint

* Repo (code + docs + brand assets): a few MB; `gBox.exe` ≈ 8 MB.
* Spark `gbox-data/` ≈ 3.1 GB (SQLite catalog/state, artifacts incl. MP4 recordings and UAP packages, thumbnails,
  runtime: RetroArch build, ~45 libretro cores, BIOS copies, save states, Dolphin user dir).
* Spark `~/gbox-cache` ≈ 7.3 GB (staged discs, extracted Dreamcast GD-ROM ≈ 1.3 GB, debug scratch).
* Windows `D:\gBox` (cache up to 250 GB, runtime: RetroArch-win + cores, Ghidra ≈ 1 GB, JDK 21, recordings),
  `%LOCALAPPDATA%\gbox` (Electron runtime + branded exe, worker venv).

## 16. External requirements and how they are used

| Dependency | Where | Used for |
|---|---|---|
| Python 3.11+: fastapi, uvicorn, pydantic, httpx, capstone (pip) | both | API, models, HTTP client, disassembly |
| SQLite (stdlib) | Spark | catalog, docs, audit, FTS5 |
| Pillow (dev scripts only) | Windows | previews in scripts (not a runtime dependency) |
| ffmpeg | both | frame capture, MJPEG streaming, MP4 recording |
| Xvfb, xdotool, x11-utils, xset | Spark | per-session displays and input |
| VirtualGL | Spark | GPU rendering for RetroArch on Xvfb |
| RetroArch (built from libretro buildbot) + libretro cores, BIOS | both | default emulation |
| flatpak: org.DolphinEmu.dolphin-emu, org.duckstation.DuckStation, org.ppsspp.PPSSPP, dev.ares.ares | Spark | debug-capable emulators |
| apt: mame, mgba-qt, mame-tools (chdman), openjdk-21, p7zip, cifs-utils | Spark | debug emulators, CHD extraction, Ghidra JVM |
| Ghidra 12.1.4 (+ JDK 21) | Spark (analysis), Windows (decompiler) | headless analysis, ExplainAddresses |
| Blender 5.3 | Windows | glTF import, .blend output, clipboard add-on |
| Electron 38 | Windows | desktop app |
| 7-Zip, rcedit, PyInstaller | Windows | RetroArch extraction, branding executables, gBox.exe |
| Ollama models, SearXNG, Wyoming whisper/piper, Voice Director (XTTS v2, Kokoro) | Spark | agent, search, voice |
| newserv (reference only, not linked) | — | documented PSO addresses/structures (`notes/ar-codes.txt`, Map.hh, BML/PRS formats) |

Imported external Python modules in `gbox/`: fastapi, starlette (via fastapi), pydantic, httpx, uvicorn, capstone.
Everything else is the standard library (sqlite3, struct, zlib, socket, subprocess, xml.etree, configparser, …).

## 17. Containers

gBox itself runs as a systemd service, not a container (a `Dockerfile` exists but is unused). It *consumes* these
Spark containers: `searxng` (:8081), `wyoming-whisper` (:10300), `wyoming-piper` (:10200), `bgutil-pot`
(yt-dlp PO tokens, localhost:4416). Voice Director and Kokoro run as Python processes from the Pine Box stack.

## 18. Key verified facts worth knowing

* PSO GC Plus (GPOE8P): entity table 0x8050D460, TObjPlayer HP +0x32C / max +0x2B8, pos +0x38, angle +0x60, class
  name pointer +0x00; `add_hp` = 0x8001140C (Ghidra + breakpoint validated).
* PSO V2 DC (2OEF): entity table 0x8C477D40, entity id +0x20, room +0x2C, pos +0x3C, angle +0x64, HP +0x330; serial
  check bypass = write 0xE001 (`mov #1,r0`, bytes 01 E0) at 0x8C1E743E and 0x8C2670B6; movement needs the analog stick;
  L trigger re-centres the camera.
* Forest 1 collision is identical on GC and DC (1,455 triangles); A* on the rasterised grid drives navigation.
* Unreal Engine 3 (`gbox/ue3.py`, tools `unreal_script` + `script_patch`): cooked PS3 packages are fully compressed
  (64 KiB zlib blocks); v375/licensee 25 function script size at +0x28. Disassembler covers ~92% of Stranglehold's
  functions. On 32-bit targets the in-RAM bytecode equals the disc bytecode except object pointers / name indices, so
  `ram_pattern` finds a function live.
* Stranglehold (BLUS30081) precision-aim shot: `StrangleholdProjectile_Bullet_PrecisionAim.ResolvePrecisionAim`
  (hit vs miss cinema) + `StrangleholdPawn.ServerResolveDamage` (@01e1 precision-aim branch, @02a6 DamageScale=1000).
  Profile `profiles/stranglehold-ps3-us.json` presets `hit` / `miss` / `off`; verified to locate (0x61C19780 /
  0x65C42000), apply and revert through the API. In-game effect still to be observed at a precision-aim moment.

## 19. Changelog

* 2026-10-05: first version (debugger, semantic profiles, autoplay, Ghidra bridge, Ninja asset pipeline, recordings).
* 2026-10-05 (late): PS3 platform + RPCS3 adapter, UE3 script explorer/disassembler, live script patches (Stranglehold
  precision-aim verdict), `docs/prompt_history.md` generated by `scripts/prompt_history.py` from the Stop hook.
  `memory_search` tool (cheat-search over a live session's RAM; 401 MB PS3 heap: snapshot 0.8 s, first filter ~10 s).
  Native-window sessions (RPCS3, RocketLauncher) no longer run a 60 fps desktop capture (caused stutter).
  Phase 7: `extract_pso_area` (PSO DC area render geometry d.rel + PVM textures + collision -> static UAP/glTF; Forest 1 =
  426 objects, 18,589 tris, 48 textures, rendered in Blender). RPCS3: F2 save state / F4 load newest, docked inside the
  app (re-docks after the in-process restart), Stranglehold `god` preset (infinite life) kept across reloads by a
  byte-check guard. Desktop: the gBox logo toggles voice; "save state / load state / pause / resume" run instantly.
  Phase 8: `mod` tool (named changesets of memory writes / script presets / cheats; apply with rollback data, rollback,
  verify, list). Graphics: `gbox/graphics.py` + `graphics` tool + Sessions -> Graphics panel (resolution scale, MSAA, AF,
  FSR/CAS, post-AA shader, vsync; "Best for my GPU"); RPCS3 per-game custom_configs/config_<SERIAL>.yml, RetroArch shader.
- 2026-10-06 (later): Knowledge base (`gbox/kb.py`, /api/kb*, agent `recall`/`remember`, auto-recall before each request,
  pages/wiki/answers learned automatically; nomic-embed-text + numpy). Agent: `wiki` (MediaWiki API, Fandom/Wikipedia),
  `image_search`, `show_gif`, link cards with page thumbnails (/api/preview), `show_asset` (3D asset cards: textured GLB
  viewer, Copy to Blender, GLB/OBJ/FBX/ABC via /api/uap/*; FBX/ABC through the `asset_convert` tool on a node with Blender),
  `offer_controls` (sliders/toggles in chat that run worker tools), `pso_drops` (finds PSO ItemRT rare tables in RAM by
  content; scale / all_rare / restore; verified live: Normal/Oran table at 0x8CB19440), `autoplay` tool (missions chain with
  "then"; Pioneer 2 office -> Forest 1 battle), repeat-call guard. memory_search defaults to each platform's main RAM.
  Desktop: one chat per game; Carbon monochrome icons everywhere (scripts/carbon_icons.py); gBox branding; audit rows group
  repeats (xN + spinner); drag/resize grip; game window stays visible with panels cut out of it (SetWindowRgn holes);
  right-click / Ctrl+click on the game (winembed mouse hook): game menu (autoplay F3/A, talk, conversation orb, save/load/
  slots, save-state film strip, settings, mapping, 3D troubleshooting flowchart), Ctrl+click = "I want this to be ..."; game
  eyedropper (Ctrl+I / status bar) with pre-selection and inspector; Extract tab (area geometry + live RAM entities, outliner,
  gizmo, inspector, exports). Web: 10-mode visualizer (/viz) on the loading screen, random per title, right-click to choose;
  session view fits the window (collapsible Graphics).


## 20. Current desktop and inbox behavior (2026-10-08)

* `gbox/inbox.py` identifies operator requests and automated descendants. Jobs propagate `parent_request_id` into tool context. The main inbox lists operator roots; automated work is nested under its originating request. Older automation with no provable origin is preserved separately. Ending an agent turn does not complete unfinished work.
* `clients/desktop/inbox-view.js` updates changed request data without replacing an active editor. Draft replies, image attachments and expanded details survive updates; unchanged responses skip rebuilding the DOM. The native-game focus handler rechecks editor focus after asynchronous guest-frame inspection.
* `clients/desktop/task-activity.js` displays a background task's title, last console/status line and real progress when provided. Unknown progress is indeterminate. `/api/jobs?state=queued,running` filters active jobs before applying the result limit.
* `clients/desktop/issue-report.js` opens a draft with subject, issue details and pasted/dropped/file-picked attachments. Windows Explorer file clipboard support resides in the desktop main process. Submission retains original attachment bytes and available game diagnostics; failures preserve the draft. See [issue reports](issue-reports.md).
* Recordings capture PC playback audio and support an application crop or gameplay-only crop from the recorder's right-click menu. Both HandBrake and ffmpeg compression paths preserve AAC. Actual Windows Electron recordings and ffmpeg compression have been verified; the HandBrake flags were checked against its CLI documentation. See [recording behavior and limits](recording.md).
* Right-click boot setup persists a character slug separately from its boot image, including shared roster mods. Game-specific swap/extraction writers and some replay states still require work; the visible selector does not establish support for every game or asset.

Changelog addition: 2026-10-08 ? inbox hierarchy and draft preservation, issue-report popup with arbitrary files, playback audio and gameplay-only recording, background-task progress and keyboard focus checks. These changes were tested on Windows; live service and desktop rollout is recorded in the inbox review.

* Popup lifecycle update: `clients/desktop/floating.js` provides shared persisted geometry, viewport clamping, drag/resize handling with pointer-capture-loss fallback, and listener cleanup on removal. Issue reports keep their heading/actions visible while the fields scroll. Native input validation and the full 724-entry inbox typing benchmark are recorded in [the inbox review](inbox-review-2026-10-08.md).
