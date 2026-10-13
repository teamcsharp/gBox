# Rip and decomp tools: ninja_ripper, ida, n64recomp, decomp_me

Tickets #443 (NinjaRipper as LLM tools) and #90 (decomp.me / IDA Pro / N64Recomp). All four are registry tools, so they
show up for the in-app agent (`gbox/agent.py` tool specs + playbook lines), for Hermes and over MCP as `job_<name>`
like RenderDoc's `scene_capture`. gBox never downloads or installs NinjaRipper, IDA or N64Recomp: when one is missing,
the worker's check hook keeps the tool off that worker and the job is rejected with a message that says what to
install and which `gbox.toml` key to set.

RenderDoc (`characters op=extract`, `scene_capture`, `gbox/frame_rip.py`) and Ghidra (`analyze_binary`,
`ghidra_script`, `re_study`, REA) stay the main routes. These tools fill the gaps: NinjaRipper for PC games whose draws
RenderDoc can't replay, IDA where it is licensed, N64Recomp for N64 static recompilation, decomp.me for matching
decompilation of single functions.

## ninja_ripper (Windows PC worker)

`gbox/ninja_ripper.py`. Ops:

| op | input | what it does |
|---|---|---|
| status | | install found, output folders, processes it launched |
| launch | exe, args, cwd, mode | starts an agent-owned program with NinjaRipper inside; returns pid |
| attach | session_id | loads NinjaRipper into an agent-owned gBox session's process |
| rip | pid or session_id, hotkey, wait_s | presses the rip hotkey, waits for new files, returns the new rip set |
| list | limit | rip sets (folders with .rip / .nr), newest first |
| import | path (default newest), select, name | converts the .rip meshes to one GLB artifact (`ninja_rip.glb` + `ninja_rip.json`) |
| stop | pid | closes a program ninja_ripper launched |

The agent's `ninja_ripper op=import name=<name>` then runs `characters op=add artifact=<glb sha> kind=object` on the
Spark, so the rip lands in the collection like any other model.

Rules (shared with `gbox/background_testing.py` and the session observers):

- launch / attach / rip / stop run only as agent jobs (`agent_use`) on a PC ticked for background testing in the Tasks
  menu (`GET /api/testing/workers`). The agent sends launches to `require_worker=idle`, which the server resolves to an
  idle PC that is ticked.
- attach and session rips only touch agent-owned sessions (`background_testing.agent_owned`: tray label `owner=agent`
  or an `agent_use` launch job; `owner=you` always wins).
- pid rips and stop only touch processes in `<runtime>/ninja_ripper/launched.json` (what the tool launched itself);
  stop refuses attached sessions (end those with `session_op`).

Config (`gbox.toml` or the PC's local overlay):

```toml
[ninja_ripper]
path = "C:/_tools/NinjaRipper1.7.1"     # folder with NinjaRipper*.exe (default: searched, see below)
# dll = "C:/_tools/NinjaRipper1.7.1/x64/<intercept>.dll"   # when the install has more than one candidate
# launcher_args = ["{launcher}", "{exe}", "{args}"]       # mode=launcher: argv template ({launcher} {exe} {args} {cwd} {out})
# hotkey = "F10"                                          # rip hotkey; "ctrl+F11" style combos work
# output_dir = "C:/_tools/NinjaRipper1.7.1/_NinjaRipper"
```

Discovery when `path` is unset: env `NINJA_RIPPER_HOME`, then `NinjaRipper*.exe` in C:/_tools, Program Files (x86),
the user's Desktop / Downloads / Documents / tools and `<runtime>/tools` (one level, or three levels under any folder
with "ninja" in its name). The DLL to inject is the single DLL in the install whose name contains ninja / ripper /
intercept and that is not a d3d* / dxgi / opengl32 proxy; with zero or several candidates the tool asks for `dll`.

Launch modes: `inject` creates the process suspended, loads the DLL with a remote `LoadLibraryW` (the mechanism
`scene_capture` uses for RenderDoc) and resumes it. 64-bit targets only. `launcher` runs NinjaRipper's own launcher with
`launcher_args` (use it for 32-bit games or when your NinjaRipper version wants its own launcher). `auto` picks
`launcher` when `launcher_args` is set or the exe is not x64, else `inject`. The tool never copies proxy DLLs
(d3d9.dll, d3d11.dll) into a game folder.

### .rip parser

NinjaRipper 1.x writes one `.rip` per draw call (format version 4, little endian, as read by the community Blender and
Noesis importers):

```
u32 magic 0xDEADC0DE, u32 version 4, u32 faces, u32 vertices, u32 vertex_size, u32 textures, u32 shaders, u32 attrs
attrs x { cstr semantic, u32 semantic_index, u32 offset, u32 size, u32 n, u32 type[n] }   type: 0 float, 1 uint, 2 int
textures x cstr, shaders x cstr
faces x 3 u32 indices
vertices x vertex_size bytes; element k of an attribute is 4 bytes at offset + 4k
```

`parse_rip` checks every count and offset against the file and fixed bounds (16 M vertices / faces, 4 KB vertex,
64 attributes, 16 elements, 256 names, 1 KB strings), so a corrupt file is rejected with the reason, never read out of
range. `mesh_from_rip` takes POSITION (float x3), NORMAL, TEXCOORD0 and COLOR0 when they are float, drops triangles
with out-of-range indices (counted in the summary), and by default converts D3D's left-handed space to glTF (Z negated,
winding reversed; `d3d_to_gltf=false` keeps the raw values). Texture names are reduced to a file name inside the rip's
folder. PNG / JPEG textures embed as they are; DDS / TGA / BMP go through Pillow when it is installed (otherwise the
mesh is kept untextured and the texture is listed under `missing_textures`).

Known limits (medium confidence, not verified against a real rip on this PC because NinjaRipper isn't installed here):
NinjaRipper rips input vertex buffers, so meshes come out in their own model space (not placed in the scene); skinned
meshes come out in bind pose; NinjaRipper 2.x `.nr` files are listed but not converted; the default hotkey F10 is
NinjaRipper 1.x's "rip frame" key; injecting into an already-running process (`attach`) only works if NinjaRipper can
hook a device created before it loaded, otherwise relaunch with `op=launch`.

CLI for testing on a PC: `python -m gbox.ninja_ripper find`, `... list`, `... glb <folder> --out model.glb`.

## ida (Windows or Linux node with IDA Pro)

`gbox/decomp_tools.py`. `op=analyze binary_path=<file> processor=<IDA -p name>` runs
`idat64 -A -L<log> -o<db> -S<script> [-p<proc>] <copy>` with an IDAPython script that writes the same `analysis.json`
as `analyze_binary`'s Ghidra `ExportAnalysis.java`:

```json
{"program": {"name", "language", "image_base", "sha256"},
 "functions": [{"name", "entry": "80000400", "size", "source": "DEFAULT|ANALYSIS|IMPORTED"}],
 "strings": [{"addr", "value"}]}
```

so `re_lab.summarize_analysis`, re_study's dossier and `n64recomp` accept either. The binary is copied into
`<runtime>/ida/<name>-<job>` and the database goes there (`-o`), so IDA never writes beside a game file; extra_args
can't override -o / -S / -L. `op=status` reports the idat used. Discovery: `ida_home` (folder or exe), env `IDA_HOME` /
`IDADIR`, then folders named IDA* in C:/_tools, Program Files, ~/tools, /opt, ~ and `<runtime>/tools`; IDA 9's `idat.exe`
and IDA 7/8's `idat64.exe` both work. The script uses the IDA 7.4+ Python API (`ida_auto.auto_wait`, `idautils.Functions /
Chunks / Strings`, `ida_ida.inf_*`), not the removed IDC string functions the PR #154 draft used. For REA's own IDA
provider keep using `rea_env.REA_IDA_MCP_CONFIG` (docs/rea.md); this tool does not edit IDA's user settings.

## n64recomp (node with N64Recomp built)

`op=run rom_path=<owned ROM> analysis_sha256=<analysis.json> name=<work>` (or `analysis_path`):

1. reads the ROM (`.z64/.v64/.n64`, or one inside a `.zip/.7z`) through `n64_rom.read`, hashing the file before and
   after; the receipt has `rom_unchanged: true`,
2. writes `<runtime>/n64recomp/<name>/`: `rom.z64` (a normalized copy), `syms.toml` (the analysis' functions inside the
   boot segment ROM 0x1000 -> header entry point, the range re_study's N64 ELF covers: word aligned, non-overlapping,
   unique C names), `config.toml` (`[input] entrypoint, output_func_path = "RecompiledFuncs", symbols_file_path,
   rom_file_path`, plus `config_overrides` / `[patches]`, all paths kept inside the work folder),
3. runs `N64Recomp config.toml` there and records the generated files in `receipt.json` and the `n64recomp.json`
   artifact. `dry_run=true` stops after step 2.

`op=status` / `op=list` show the executable and the work folders. Overlays and compressed segments are not in the boot
segment; add them with `config_overrides` (e.g. `relocatable_sections_path`) and your own symbol work. The config and
symbol key names follow the N64Recomp README and the Zelda64Recomp configs (medium confidence; N64Recomp's TOML schema
has changed between versions, so check the first run's log). Discovery: `n64recomp_path` (exe or source folder with
`build/`), env `N64RECOMP`, PATH, then folders with "recomp" in their name in C:/_tools, ~/tools, /opt,
`<runtime>/tools`. N64Recomp is a CMake C++ project; gBox does not build it (the PR #154 draft's `cargo` provisioning
could not work).

## decomp_me (any node)

`op = status | compilers | platforms | presets | fetch (slug) | list (params) | submit | compile (slug)` against
`decomp_me_url` (default `https://decomp.me/api`; `api.decomp.dev` is decomp.dev, the progress site, and answers every
path with an empty 200, which the PR #154 draft mistook for token gating). `dry_run` defaults to true and returns the
exact request; real calls need `decomp_me_enabled = true` in gbox.toml (opt-in) and the `network` permission. `submit`
(platform + compiler or preset, target_asm, diff_label, context, source_code) creates a PUBLIC scratch; the result keeps
`claim_token` and the scratch URL so the operator can claim it while signed in. Field names follow decomp.me's
backend serializers (medium confidence). From this PC, decomp.me's API answers scripted clients with a Cloudflare
challenge (HTTP 403 HTML, checked 2026-10-12); the tool reports that as "Cloudflare challenge refused this client"
instead of returning the page, so expect dry runs to be the useful mode unless the deployment's IP is allowed through.

## Live checks (maintainer, on the agent test PC)

Nothing here can run on the Spark or on the operator's PC. On the test PC (ticked for background testing):

1. Worker registration: restart the worker after the deploy, `GET /api/workers`, and confirm `decomp_me` is in the
   test PC's `tools` and `ninja_ripper`, `ida`, `n64recomp` are either in `tools` (installed) or under `unavailable`
   with the install message.
2. NinjaRipper: unpack NinjaRipper 1.7.1 into `C:/_tools/NinjaRipper1.7.1`, restart the worker, then from MCP:
   `job_ninja_ripper {"op": "status"}` (install + DLL listed) ->
   `job_ninja_ripper {"op": "launch", "exe": "<a 64-bit D3D11 game or emulator exe>", "require_worker": "<test PC>"}` ->
   once in game `{"op": "rip", "pid": <pid>}` (expect `new_files > 0`) -> `{"op": "import"}` (expect a `ninja_rip.glb`
   artifact; open it in Blender) -> `{"op": "stop", "pid": <pid>}`. If launch says it can't pick the DLL, set
   `[ninja_ripper] dll`. If rip writes nothing, set `hotkey` / `output_dir` to what the NinjaRipper UI shows.
3. Converter only (no game needed): copy any NinjaRipper 1.x rip folder to the PC and run
   `python -m gbox.ninja_ripper glb <folder> --out C:/temp/rip.glb`; the printed summary lists skipped files and
   missing textures.
4. IDA (if licensed): set `ida_home`, restart, `job_ida {"op": "analyze", "binary_path": "<re_study ELF>",
   "processor": "mipsb"}` and compare the function count with `job_analyze_binary` on the same ELF.
5. N64Recomp (if built): `job_n64recomp {"op": "run", "rom_path": "<owned .z64>", "analysis_sha256": "<analysis.json
   of re_study's ELF>", "name": "test", "dry_run": true}`, inspect `syms.toml` / `config.toml`, then rerun without
   dry_run and check `RecompiledFuncs/` and `rom_unchanged: true`.
6. decomp.me: `job_decomp_me {"op": "fetch", "slug": "<any public scratch>"}` returns the request (dry run); only
   with the operator's opt-in, `decomp_me_enabled = true` and `"dry_run": false`.

Tests (fakes only): `python -m pytest tests/test_ninja_ripper.py tests/test_decomp_tools.py
tests/test_rip_decomp_registry.py -q -p no:cacheprovider`.
