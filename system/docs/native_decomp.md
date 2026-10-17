# Local decompilation and recompilation tools (#2396)

`decomp_pipeline`, `xenonrecomp`, and `rexglue` are typed worker tools, exposed through MCP as
`job_<name>` and through the in-app agent by the same names. Hermes and Spark2 can discover
their schemas and submit normal `start_job` work. Preserve the job ID while queued/running;
pin subsequent operations to the worker that owns `work_id`. Operations have bounded timeouts,
project locks, logs, source hashes and receipt artifacts. They never launch paid model workers.

Hermes terminal tasks can use the identical typed adapter directly:
`python -m gbox.native_decomp decomp_pipeline --config gbox.toml --input-file task.json`.
Omit `--input-file` for status; choose `xenonrecomp` or `rexglue` for those tools. This starts
no web server or persistent worker and does not require interrupting a running gBox service.

## Install once on an analysis node

From `system/`, using its Python environment:

```text
python scripts/setup_native_decomp.py --engine all
```

Choose `--engine decomp_pipeline`, `xenonrecomp`, or `rexglue` for one installation. This is an
explicit network/install action, not a side effect of discovering or calling the tools. It
pins DecompPipeline to `84dcbc44bfa5ba451ac1da35e924bc534e02bcd9`, XenonRecomp to
`ddd128bcca99fe8bfbb99bea583c972351fa6ace` (including submodules), and RexGlue to v0.10.0.
Upstream licenses remain with each installation; no upstream source or game executable is
vendored in gBox. XenonRecomp needs CMake, Ninja and Clang 18+; the installer builds with two
jobs. RexGlue uses the official host-specific SDK archive and checks its release digest when supplied.

Installation goes under `<runtime>/decomp-tools`. `gbox-local.json` there contains per-host
paths; it does not change the shared `gbox.toml`. Explicit `[native_decomp.<engine>]` settings
override those paths; `GBOX_DECOMP_PIPELINE_HOME`, `GBOX_XENONRECOMP_HOME`, and
`GBOX_REXGLUE_HOME` can also select installations. Tools always expose `op=status`, including
when binaries are absent. Discovery alone is not an execution/readiness claim.

DecompPipeline uses the existing Ghidra and JDK21. Its additive SH-4 language installer leaves
stock SLEIGH files unchanged. gBox accepts the exact already-correct `bsr` block in Ghidra
12.1.4 instead of applying that upstream correction twice. Unknown language variants fail
for inspection. Windows setup detects an existing MSVC `vcvars64.bat`; Linux can run Ghidra
analysis and prepare/task, but the upstream C checker requires Windows/MSVC. Run the full
workflow on a configured Windows analysis worker when behavioral verdicts are needed.

## Dreamcast function tasking

1. `decomp_pipeline {"op":"status"}`: inspect installation and checker dependencies.
2. `init` with a unique `work_id`, extracted `binary_path`, `expected_sha256`, optional catalog
   `game_id`, and `game_end` (verified exclusive game-code boundary in SH-4 RAM). The extracted
   executable must load at the upstream target's 0x8c010000; other CPUs/relocations need their
   own verified upstream target, not a label change. The original is copied and hashed.
3. `setup` imports/analyzes that copy in a private Ghidra project.
4. `prepare` with `address` builds the assembly/pseudocode packet and independent oracle.
5. `task` returns assembly, pseudocode, the function signature and `tc_rt.h` to Hermes/Spark2.
   It excludes hidden vectors/expected results. The local model writes just the candidate C.
6. `check` with `address` and `candidate_source` invokes the official dev **and hidden** checker.
   A legitimate `FAIL` is a result for another local attempt; compiler/runtime/infrastructure
   failures remain visible. `verified=true` requires PASS at compare stage with zero failures,
   no runtime error, and at least 16 vectors in each set. A model's success statement never counts.
7. `audit` reports upstream project blockers. Manual check receipts do not automatically promote
   the upstream matching ledger; keep the receipt and candidate together for reviewed adoption.

This is sampled behavioral equivalence, not original-compiler byte matching or proof for
every possible input. Keep independent controls, call/branch coverage and known oracle limits
with the evidence. The integration does not enable upstream `serve`, `investigate`, watcher,
or paid Claude workers; local systems own task dispatch and use the independent checker.

## Xbox 360

Both tools accept extracted XEX2 executables, not full ISOs. `init` takes `binary_path`,
`expected_sha256`, a unique `work_id`, and optional `game_id`, staging a source copy.

For `xenonrecomp`, follow `init -> analyze -> codegen`. Optional `xenon_options` at init may
specify independently established `functions=[{address,size}]` and documented register
save/restore or setjmp/longjmp addresses. Paths and speculative optimizations cannot be
overridden. `analyze` writes jump tables and `codegen` writes C++. The receipt counts generated
sources and unsupported-instruction messages. Generation with warnings remains incomplete
game engineering; XenonRecomp supplies no runtime.

For `rexglue`, follow `init -> codegen`. Its own initializer creates the project and SDK build
files, and codegen performs its analysis/validation. Unresolved calls are reported as failures
with the native log; do not suppress them to claim a port works. The generated project remains
available for reviewed game-specific function/configuration corrections. Runtime integration,
compilation and actual gameplay are separate per-game work.

All projects are under `<runtime>/native-decomp/<engine>/<work_id>`. Existing projects are
never replaced by init. A kernel lock prevents concurrent operations on the same project;
timeouts/cancellation stop only the launched process tree. Failed outputs/logs remain for
diagnosis. Input hashes are checked before/after execution. Receipts enumerate source files
and hashes; they contain no claim that a model reader, writer, or playable game is complete.

## Verification

```text
python -m pytest tests/test_native_decomp.py tests/test_rip_decomp_registry.py tests/test_decomp_tools.py tests/test_native_engineering.py tests/test_tool_registration_resilience.py -q
```

Actual execution on 2026-10-17: Ghidra 12.1.4 imported a synthetic `mov #7,r0; rts; nop`
SH-4 function and prepared 48 dev/48 hidden vectors. The existing Windows/MSVC checker
accepted the C translation returning 7 (96/96), and rejected a translation returning 8
(96/96 mismatches). XenonRecomp generated C++ from the owned Burnout Revenge XEX
SHA-256 `5258c75d9ae649ed4fb71d4e2fe8808545db16092cfe764ea1a2504f5aae2e2d`, with unsupported
instruction diagnostics. RexGlue initialized that same project and correctly rejected two
unresolved calls at 0x8256C6F0 and 0x8256DB78. Neither result establishes a playable Burnout port.

The actual Spark2 route (`sparkDeux`, `nvidia/Qwen3.8-27B-NVFP4`) consumed the prepared task
packet, produced its own C candidate, and passed all 96 independent checker cases. The call
used 1,948 prompt tokens and 38 completion tokens through the local-only node endpoint.
RexGlue also generated C++ for independently encoded `addi r3,r4,1; blr`, and the generated
function compiled with its SDK headers and executed on ARM64, returning 7 for input 6.

Sources: [DecompPipeline](https://github.com/GeneralAtrox/DecompPipeline),
[XenonRecomp](https://github.com/hedge-dev/XenonRecomp), [RexGlue SDK](https://github.com/rexglue/rexglue-sdk).
