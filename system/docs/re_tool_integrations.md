# ReAgent, Ghidra Bridge and Ariane as gBox functions (#847)

Inbox #847 asked for three repositories by Dryxio to become functions the LLM can call:
[ReAgent](https://github.com/Dryxio/reagent), [Ghidra Bridge](https://github.com/Dryxio/ghidra-bridge) and
[Ariane](https://github.com/Dryxio/ariane). Branch `re-tool-integrations`, 2026-10-12. Each repository was cloned
read-only into a scratch directory, read, and never installed or run. No upstream code is vendored. The work is ported
or reimplemented in gBox, with credit in each module's docstring.

| project | what it is | licence | in gBox |
|---|---|---|---|
| Ghidra Bridge (`ghidra-ai-bridge` 0.2.0) | Python CLI/API that gives AI agents Ghidra data: decompile by address or name, callers and callees, strings with references, structs/enums/vtables, and function search. It works from a headless PyGhidra export (JSON files), then answers queries offline from that export. | MIT | `ghidra_bridge` worker tool (`gbox/ghidra_bridge.py`, `ghidra_bridge_server.py`, `ghidra_bridge_tool.py`) |
| ReAgent (`auto-re-agent` 0.4.0) | An autonomous agent that reconstructs C/C++ functions from Ghidra evidence. It runs a reverser → checker → fix loop with evidence requests and a structural verifier, then build/test/parity gates, and picks functions by strategy. It brings its own LLM providers and CLI. | MIT | `re_agent` tool + the `reconstruct-function` playbook (`gbox/re_agent.py`, `gbox/re_seeds.py`) |
| Ariane | A GTA III / Vice City / San Andreas map viewer and editor (aap's euryopa on librw). It edits IPL/IDE/IMG data. `ariane.asi` adds Test in Game (teleport, time, weather) and San Andreas hot reload. Agent Alpha is a separate bundle (arianectl / MCP) that drives the editor. | GPL (README: "dual-licensed as GPL" because of LZO). The repository has no LICENSE file. | `gta_live` worker tool (`gbox/gta_live.py`) + the `gta-live-state` playbook. No code was taken from the repository. |

All three are registered in the tool registry, so they also appear in gBox's MCP server. They are also in the chat
agent's `tool_specs` (`gta_live`, `ghidra_bridge`, `re_agent`), with routing lines in its system prompt.
`gta_live` is in `WORKER_TOOLS`, so chat controls can run it. It is also in `MODIFIES`, but only for its writes:
teleport, spawn, and weather/time/wanted when a value is given.

## Ghidra Bridge → `ghidra_bridge`

Upstream's design has two halves: a PyGhidra export, and offline queries over that export. gBox keeps both and adds a
live mode in the same process, following `gbox/rea.py`'s conventions: a worker-owned persistent subprocess, requests
serialized under a lock and matched by id, stderr kept apart from protocol stdout, and an `unavailable()` that names
the fix.

- **Live.** `Session` starts `gbox/ghidra_bridge_server.py` under a Python that has PyGhidra. Its environment gets
  `GHIDRA_INSTALL_DIR` = the operator's Ghidra (`rea_env`, then the environment, then `ghidra_home`) and `JAVA_HOME` =
  the pinned JDK 21. `op=open` imports `binary_path` into a gBox-owned project under `gbox-data/analysis/ghidra_bridge`
  (the game file is only read), or opens an existing project (`project_dir` + `project_name` + `program_name`). The
  program stays open on that worker, so later queries are fast. `op=stop` closes it and ends the process.
- **Ops**: `status`, `start`, `open`, `info`, `functions`, `decompile` (0x address or name; returns C plus callers and
  callees), `xrefs_to`, `xrefs_from` (callees + data refs), `containing`, `strings` (regex; returns each string with
  the functions that reference it), `run_script` (any GhidraScript; gBox's `adapters/ghidra` scripts by name), `export`,
  `close`, `stop`. Results are JSON. The full result is also kept as the `ghidra_bridge.json` artifact.
- **Export.** `op=export` writes upstream's layout: `_index.json`, one `<address>.json` per function and
  `_strings.json`. The upstream CLI and ReAgent can read it. Any query op given `export_dir` and no open program
  answers from such a directory, with no Ghidra running (`ExportBackend`).
- **PyGhidra** comes from the operator's own Ghidra: Ghidra 11.3+ ships offline wheels in
  `Ghidra/Features/PyGhidra/pypkg/dist`. `gbox ghidra-bridge-install` builds `<runtime>/pyghidra-venv` from those
  wheels with `--no-index`. It downloads nothing and does not modify Ghidra. `GBOX_PYGHIDRA_PYTHON` overrides the
  interpreter.
- If one request fails, the program stays open. If the process dies, the caller is told to reopen; it is never
  silently restarted.

## ReAgent → `re_agent` + playbook `reconstruct-function`

gBox ports ReAgent's loop and stop rules rather than adding a second agent with its own providers and CLI:

- `op=reverse target=<addr|name>`: the reverser gets the decompilation, callers and callees. It may answer
  `{"actions":[{"tool":"decompile","target":"0x..."}]}`. The `ghidra_bridge` on the same worker serves those requests,
  up to `max_investigations`. An independent checker then gives a JSON verdict (or labelled `VERDICT:` lines) and the
  structural verifier runs. The verifier vetoes a PASS when calls or branches are missing, or when a constant return
  differs. The fix rounds feed back the issues, the verifier findings and the fix instructions. The loop stops on PASS,
  on the LLM call budget, or when a round repeats the same candidate and diagnostics.
- `op=pick` ranks functions by `high-impact` (most callers first), `easiest-first` or `dependency-order`
  (callees before callers).
- `op=check` and `op=verify` judge a candidate written by someone else, such as the chat model.
- Models come from `llm_endpoints`, the same routing as `llm_complete`. `checker_endpoint` selects an independent
  checker. Without an endpoint the tool returns ToolUnavailable; it never substitutes a model.
- Upstream's build/test/parity gates (clang index, candidate overlays) were not ported, because gBox has no source
  tree to build against. Every result is `status: hypothesis`, and the playbook ends with `re_dossier op=record`.

## Ariane → `gta_live`

Ariane is an editor for the PC games' map files. The operator plays PS2 discs and the Vice City Definitive Edition,
neither of which Ariane edits. Running its GPL editor or ASI inside gBox would not fit either. So gBox gives the LLM
Ariane's in-game controls (teleport, time, weather) plus the game state around them, using `read_memory` /
`write_memory`:

`games | resolve | pools | player | vehicles | weather | time | wanted | teleport | spawn`

- **Writes** go through `gta_mods_tool.Mem`: data memory only, never code. Each write is confirmed by read-back and
  returns its `before`/`after` bytes for undo. No game file is touched.
- **Provenance.** Every field reports its `source` and `live_checked`. All of them are `live_checked: false`.
  - GTA III and LCS players, pools, strides and offsets come from `gbox/gta_games.py`, which `gta_mods` uses live.
  - The CWanted layout (chaos at +0x0, level at +0x18) and the chaos-per-star values (0/70/200/570/1220/2420/4820)
    come from re3.
  - The clock, weather, pool pointers and `CPlayerPed::m_pWanted` come from **op=resolve** on the game's own ELF
    symbol table: GCC 2.x `_6CClock.ms_nGameClockHours`-style names and Itanium names. The wanted-pointer offset is
    the first `lw rX, imm(a0)` in `CPlayerPed::SetWantedLevel`. GTA III's PS2 ELF keeps its `.symtab`. Get it with
    `re_study`, then run `gta_live op=resolve elf_path=...`. Results are cached per game in
    `gbox-data/gta_live/<game>.json`; the curated table wins on conflicts.
  - A field with no source is missing, and the op says how to map it (memory_search / resolve / re_dossier) rather
    than guessing.
- **Spawn** uses `gta_mods spawn_vehicle` (GTA III), which creates the vehicle on the EE through gta_mods' hook.

| owned version (catalog) | table |
|---|---|
| GTA III PS2 SLUS-20062: `265819390074bb4e`, `82173dff3bf1ad6d` (the second is filed under windows_native, but it is a PS2 .chd) | player, pools (ped/vehicle), vehicles, teleport, spawn, densities. After `resolve`: time, weather, wanted, plus the object/building/dummy pools if the symbols exist |
| Liberty City Stories PS2 SLUS-21423: `002b9dca58a18ea1` | player, pools (ped/vehicle), teleport. No vehicle stride, so no vehicle listing yet. No spawn |
| Vice City PS2 SLUS-20552: `5eacc9f11d9a5956` (filed under windows_native, but it is a PS2 .chd) | detection only; whatever `resolve` finds in its ELF |
| Vice City Stories PS2 SLUS-21590: `6f5a05916536492b` (PSP `18d96224e254c7c4`) | detection only (no symbols expected) |
| Vice City windows_native `1fd42f50b10252e6` | **refused**: it is the Definitive Edition (Unreal Engine 4), with no RenderWare structures (docs/gta_vc_pc_swap.md) |

Ariane's map editing itself (moving IPL instances, IMG rebuilds) would mean writing the operator's game files.
#847 does not get that: nothing here modifies a game file in place. If it is wanted later, the route is a mod copy,
the way `file_mod` / modloader already work.

## Tests

`tests/test_re_tool_integrations.py`: 19 tests, all fakes, no Ghidra/LLM/emulator.
- A fake bridge server speaks the real protocol: lifecycle, errors that keep the program open, process loss, input
  validation and run_script dirs.
- The real server's `serve()` loop is run with a fake Bridge.
- The export backend is tested on upstream's file layout, along with the registered tool over an export and the
  `unavailable()` messages.
- ReAgent: parsing, the verifier, the three strategies, and the loop (evidence request → FAIL → fix → PASS; stops on
  a repeat or the budget; the verifier vetoes a checker PASS), plus the tool ops.
- gta_live: detection and refusals, player/vehicles/pools/teleport on a fake EE RAM, unmapped guidance, and a
  synthetic symbol-table ELF through `resolve`, then weather/time/wanted.
- Agent wiring: specs, `MODIFIES` rules, and worker pinning.

## Live checks (2026-10-12, operator's Windows PC)

| check | result |
|---|---|
| Ghidra Bridge, live, against the operator's Ghidra 12.1.4 (`D:/gBox/runtime/ghidra_12.1.4_PUBLIC`, JDK 21.0.12). PyGhidra 3.1.0 was installed offline from that Ghidra's own wheels into a scratch venv. Target: a copy of `hostname.exe` (36 KB). | **passed.** `open` (import + auto-analysis, 242 s first time; 94 s to reopen the saved project) → x86:LE:64, 85 functions. `functions`, `decompile` of `__security_check_cookie` (C + callers + callees), `xrefs_to`, `xrefs_from`, `strings` with references, `containing`, `export` (20 functions, 110 strings in upstream layout), and an offline `decompile` from that export all worked. `run_script ExportAnalysis.java` produced 37 functions and 102 strings. `stop` worked. |
| `run_script` before the bundle fix | failed with "Failed to find source bundle containing script". Fixed: the script's folder is now registered with Ghidra's BundleHost. Re-run passed (row above). |
| ReAgent `op=reverse` against a real model | **not run here.** This PC has no `llm_endpoints`, and the Spark is out of scope for this run. The loop is covered by the fake-model tests. |
| `gta_live` on a running PS2 GTA III | **not run.** No game session may be launched in this run. Every address stays `live_checked: false`. First live check to do: GTA III → `gta_live op=player`, then `vehicles`, then `resolve` with the SLUS_200.62 ELF, then `time hours=0` on screen. |
