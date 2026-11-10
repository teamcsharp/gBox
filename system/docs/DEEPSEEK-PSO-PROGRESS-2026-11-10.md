# DeepSeek PSO lane: progress check, the menu stall, the GPU, and how to go on locally (2026-11-10)

> **Hard rule (2026-11-10 ~12:50): hands off lilspark.** Never `ssh` into the Spark (10.89.1.246), never run
> `sudo` / `systemctl` / `kill` there, never launch or stop a game on it. Something did that twice today, and each
> `systemctl restart gbox.service` killed the live MercMode games. Work on the i9 against its own gBox
> (`10.89.1.43:8765`). Send `x-gbox-actor: agent` on every API call. Anything that needs lilspark is a request in
> your lane log; the RE session does it. See DEEPSEEK-HANDOFF-2026-11-10.md section 0.


Written for the DeepSeek session on the i9-NUC by the PM's audit agent, at about 12:20 CST. Read this first. It does
not replace `DEEPSEEK-PSO-TASK-GUIDE-2026-11-09.md` §0d (the goals) or `DEEPSEEK-HANDOFF-2026-11-10.md` (credit,
branches only, scope). Where it differs from your own `PSO-HANDOFF-2026-11-10.md`, this one wins, and §2 says why.

The operator, 2026-11-10 ~12:10 CST: "I was watching it sit on menu screens stuck and wasnt sure it was progressing. Look
over what it has accomplished and make sure that the progress is useful for the goals indicated."

The operator, ~12:15 CST: "on the i9 computer, I hooked up an 3090 egpu. So I wanted deepseek using local means of
inspection and the power of my gpus to accelerate the task and the investigation using the full power of my gpu. I am
not sure if its using it or if it is even helping but I need deepseek using my gpu to the max in order to get the pso task
completed as fully as possible."

Everything below marked **measured** was read from the i9's control plane (`http://10.89.1.43:8765`, read-only GETs),
from git, or from a test run on main at `7182de5f`. **Inferred** means reasoned from those, not observed.

---

## 0. The short version

1. **The offline work is good and on the goals.** The disc is decoded (P2), the executable is partly mapped (P2b), the
   map writer builds a bootable disc (P6a), the editor's backend exists (P6b), the player model builds from this disc and a
   body swap is visible in game (P7a/P7b), and `pso_swapfit` predicts which swaps crash. That took roughly 2 of the
   lane's ~8 hours today.
2. **The live work mostly looped.** About 32 of the 44 rounds (about 5.5 hours) went to P1: menus, pads, and then 12+
   rounds walking Pioneer 2's rooms looking for a way to the surface. That search never found it. Your own hand-off says
   "no route to Forest 1 found".
3. **There is a route, and you may have recorded it.** In round 6 (session `dbc5ff9be4ca416c-c91e5802a9844b37`,
   05:29-06:06) the **operator took BQF from that same Pioneer 2 into Forest 1**. Your recorder wrote that session to
   `D:\gBox\pso-ds\demos\dbc5ff9be4ca416c-c91e5802a9844b37.jsonl`: four XInput slots plus phase, floor, room and
   position every 0.2 s. Rounds 28, 35 and 38 list "demo -> route fixture" as open, and no round read the file back.
   Read it first (§4.1).
4. **Why it "sat on menu screens" (measured):**
   - 22 cold boots today, all through the title menus. 12 of them lasted 5 minutes or less.
   - No savestate or checkpoint was ever kept, so each test re-walked the menus.
   - The five-minute admission gate ran before every launch. About 2 hours of the 04:52-12:09 window had no game
     running.
   - The last session ended with both players' in-game START menu open and the DeepSeek app window over Dolphin.
   - No autobot ran at any time.
5. **The 3090 is idle (measured):** 0-141 MB of 24,576 MB used, 0-25 % utilisation, and no Ollama answers on the i9's
   loopback. Nothing in the lane uses it. §1 is the plan to put it to work. The biggest win is a local coder model doing the
   bulk P2b labelling, so the $2.96 of DeepSeek credit only pays for review.
6. **Order from now:**
   - fix your 5 red `test_pso_steer.py` tests and the 4 steering-evidence tests (§6.3);
   - stand up the local model and the Ghidra labelling pipeline;
   - do the offline P2b targets that unblock the editor and the swap;
   - batch live work into short windows, from savestates, using the operator's recorded route.

   P1's cold-boot acceptance comes last.

---

## 1. The GPU: is the 3090 used, and how to use it to the max

### 1.1 What is measured

The i9's worker telemetry (`GET /api/workers`, row `i9-NUC`, `resources.gpus`), sampled every 10 s from 12:16:13 to
12:17:24 CST, while no game session was running:

| GPU | UUID | VRAM used | utilisation |
|---|---|---|---|
| RTX 3090 (eGPU, 24,576 MB) | `GPU-f3697ec1-9016-3424-7886-750a24ddc07a` | 141 MB, then **0 MB** from 12:16:44 | 25 %, then **0 %** |
| RTX 2070 (internal, 8,192 MB) | `GPU-7ba78a18-c298-f7f2-d4c1-d3de4d3a6c9b` | 1,562-1,667 MB | 16-41 % |

Also measured:
- `ollama.available = false`: "Ollama is not reachable on this worker at 127.0.0.1:11434".
- The central plane's last sample of the i9 (02:25 CST) shows the same picture: 3090 at 46 MB and 0 %, 2070 at
  1,298 MB and 17 %.
- CPU stood at 38-55 % with no game running. The process was not identified.
- Your lane logs never mention a local model, CUDA or the 3090 for PSO.
- The i9 client lane measured, at 02:25 CST, that Switch decrypting is I/O-bound at about 245 MB/s, so the GPU cannot
  speed it up (`ds-i9-client-lane-and-hot-swap-requests-20261109.md`, round 54).
- The frame of the last session shows the DeepSeek desktop app on the i9.

What that means:
- **No model is resident on either GPU.** A loaded model holds gigabytes of VRAM; the 3090 holds none, and the 2070
  holds only what it held at 02:25 with nothing running, which is the desktop.
- Your harness's reasoning runs on the paid DeepSeek API. Nothing local takes bulk work off it.
- **Not measured:** which GPU Dolphin rendered on during today's sessions. gBox forces the Vulkan backend
  (`adapters.py`, `Dolphin.Core.GFXBackend`) but not the adapter. Dolphin's `GFX.ini` `[Hardware] Adapter` picks it.
  Read that file and the `Using GPU` line of `D:\gBox\runtime\logs\dolphin-win-*.log`.

### 1.2 What the GPU can buy, judged by the goals

| idea | goal it serves | what it buys | verdict |
|---|---|---|---|
| **A local coder LLM on the 3090** as your bulk analyst: it reads Ghidra's decompiled C, proposes names for functions and structures, and summarises formats | 1 (decrypt / break down: P2b) and through it 2 (editor) and 3 (swap) | The open P2b targets in §5 are dozens to thousands of functions of reading. A local model does that at no credit cost, around the clock. DeepSeek only checks the shortlist. | **Do this first.** It is the one idea that turns the GPU into progress on the hard parts. |
| **Blender (Cycles OptiX) renders on the 3090** of the extracted and swapped player models | 3 (P7a rigging, P7b) | Each boot to check a swap costs about 10 minutes with the gate. A T-pose plus walk-cycle render catches the "giant polygons" deformation (round 34) offline in seconds. | **Do it with P7a's rigging.** |
| **An area survey from savestates**: load each field area once, dump the entity table and the RAM around it | 2 (P6a proof, P6b labels, P6c) and 4 (P3) | Two results that are otherwise decompiles: the class index -> `TObj*` name table (each live entity's class name against the placement set's class indices) and the room-local -> world offset per area. It is CPU-bound; the GPU barely matters. | **Do it, but it is not a GPU job.** One extra Dolphin at most. The i9-9980HK has 8 cores, and each Dolphin takes 2-3. |
| **Several Dolphins in parallel** to explore or to fuzz editor builds | 2 (P6c safety) | A batch boot test of generated layouts, catching crash dialogs. | **Later, after P6c exists.** Limited by CPU, not GPU. |
| **A local vision model** labelling recorded frames (menu screens, dialogue) | 4 (P1) | Could label which RAM signature goes with which screen. But P1 must decide from RAM, and the menu walk already works. | **Skip** unless the menu RAM map stalls. |
| **CUDA for RAM diffs, texture decode or hashing** | none in practice | RAM is 24 MB and numpy does a diff in milliseconds. Texture decode is trivial. Decrypting is I/O-bound. | **Skip.** |

Be honest in the lane log about this. Much of PSO's work is CPU, disk or reasoning, not GPU. "The GPU to the max" pays
off where it replaces paid tokens (the LLM) and boots (the renders).

### 1.3 Set up the local model on the 3090 (one round)

Everything on `D:`, nothing on `C:`, loopback only.

1. **Install** Ollama for Windows, or a CUDA build of llama.cpp if you prefer its server. Put the models on `D:`:
   ```powershell
   setx OLLAMA_MODELS "D:\gBox\llm\ollama-models"
   setx OLLAMA_HOST "127.0.0.1:11434"         # loopback only; gBox's worker probes exactly this address
   setx CUDA_DEVICE_ORDER "PCI_BUS_ID"
   setx CUDA_VISIBLE_DEVICES "GPU-f3697ec1-9016-3424-7886-750a24ddc07a"   # the 3090 only (UUID from §1.1)
   setx OLLAMA_FLASH_ATTENTION "1"
   setx OLLAMA_KV_CACHE_TYPE "q8_0"           # halves the KV cache
   setx OLLAMA_MAX_LOADED_MODELS "1"
   setx OLLAMA_NUM_PARALLEL "2"
   setx OLLAMA_KEEP_ALIVE "24h"                # the eGPU link makes a 20 GB reload slow; load once
   ```
   Quit Ollama (the tray app) and start it again after `setx`, so it reads the new variables.
2. **Pick the model by measurement, not by name.** Candidates that fit 24 GB:
   - a 32B coder at Q4 (about 20 GB of weights);
   - a 30B mixture-of-experts coder at Q4 (about 19 GB; much faster per token);
   - a 14B coder (about 9 GB) if Dolphin has to share the card.

   Pull two, run the gold-set test in step 4, and keep the better one.
3. **VRAM budget.** Keep the 3090 at 22 GB or less:
   - weights plus a 16k-context KV cache;
   - keep the context at 16k for labelling (one function per prompt), not 128k.

   Keep Dolphin on the 2070:
   - it renders PSO easily;
   - the eGPU's Thunderbolt link is the worse place for per-frame work.

   If §1.1's check shows Dolphin on the 3090, say so in the lane log and size the model down (the 14B) rather than
   change the shared Dolphin profile. The operator plays from that profile.
4. **Verify it is really on the 3090**:
   ```powershell
   nvidia-smi --query-gpu=index,name,uuid,memory.used,utilization.gpu --format=csv
   nvidia-smi --query-compute-apps=pid,process_name,used_memory,gpu_uuid --format=csv
   ollama ps                                   # PROCESSOR must read "100% GPU", not a CPU/GPU split
   ```
   Also check gBox's own view: `GET /api/workers`, `i9-NUC`, must show `.ollama.available = true` and the 3090's
   `memory_used_mb` near the model size.
5. **Gold set before trust.** `docs/research/pso-gc-executable.md` §3 names 34 code addresses proven by byte-exact
   guards. Give the model those 34 functions' decompiled C with the names stripped. Score its names against the known
   ones (exact, or the same role). Record:
   - the hit rate;
   - tokens/s (`ollama run <model> --verbose` prints the eval rate);
   - the time per function.

   If the hit rate is poor, use the model only for summaries and candidate lists, never for names that go into
   `pso_ram.py` unproven.

### 1.4 The labelling pipeline: Ghidra on the CPU, the model on the 3090, DeepSeek reviews

Your Ghidra project is `D:\gBox\ghidra-pso`: 25,981 functions, pyghidra in `D:\gBox\runtime\pyghidra-venv`.

1. **Export** with pyghidra, one JSONL row per function, to `D:\gBox\pso-ds\llm\functions.jsonl`:
   - address, size, current name;
   - callers and callees;
   - the strings it references;
   - the decompiled C, truncated to about 6 KB.

   Use all cores. Export the target neighbourhoods first (§5 A): the functions that reference the 315 `TObj*` strings and
   the `gsl_set_*` / `gsl_*` area strings; the callers and callees of `FUN_80207E88` / `FUN_802077CC`; the function
   containing `0x8028f508` and its callers; anything near the card SDK calls.
2. **Label** in batches against `127.0.0.1:11434`. Ask for a small JSON per function: `{"name", "role", "confidence",
   "evidence": [the strings, constants or calls it rests on]}`. Write the results to `labels.jsonl` beside the export.
   This runs unattended. Leave it going while you do anything else.
3. **Review** only the rows that matter for a §5 target and have evidence. That is where DeepSeek's credit goes. A name
   enters `pso_ram.py` or `docs/research/pso-gc-executable.md` only with its proof: the decompile, the xref chain, or a
   live RAM watch with the session id. That is the same rule as today.
4. **Measure that it helps**, and put the numbers in the lane log:
   - functions labelled per hour by the local model;
   - DeepSeek dollars per accepted label, against today's baseline of DeepSeek reading functions itself;
   - the 3090's VRAM and utilisation from `nvidia-smi` while the batch runs.

   "Helps" means the §5 targets close faster per dollar. If they do not, say so.

The pipeline script is tooling: keep it in `D:\gBox\pso-ds\llm\`. Only a reusable reader (for example a loader for
`labels.jsonl`) goes into git, on a branch, with a test.

### 1.5 Renders for the swap (with P7a's rigging)

`pso_player.build` already writes a manifest: meshes, skeleton and PNG textures.
- Export the build to glTF through the existing extract and export path (`job_export_asset`, `open_in_blender` are on
  the i9's tool list).
- Render it headless with Blender Cycles on the 3090, from the command line with the OptiX device. Do one T-pose and a
  few frames of a walk clip per candidate swap.
- Check with `nvidia-smi` that `blender.exe` is on the 3090.
- A swap that renders clean goes to a boot test.
- A swap that renders exploded is fixed offline. It costs no launch and no five-minute gate.

---

## 2. What the lane has accomplished, judged against the goals

The goals (guide §0d):
1. decrypted and broken down;
2. a level editor (P6a-c);
3. character hot swap (P7a-b);
4. autoplay mastery, all zones and bosses, four players (P1, then P3-P5).

| item | commits | goal | how far it moves the goal | verdict |
|---|---|---|---|---|
| Placement sets found in `gsl_set_*.gsl`; the 68-byte record; `kind = flags \| class index`; byte-identical rebuilds of 285 set files | `2b25e24d` | 1, 2 | The editor's data layer exists. | **Useful, core** |
| Container reference (GCZ -> GCM/FST -> GSL/AFS -> BML -> PRS), the two `PsoV3.dol` builds told apart | `1ee1d723`, `a7fac496` | 1 | P2's format half done, with round trips. | **Useful** |
| `pso_areas` catalogue (72 areas, 1,000 files, 784,070 triangles), `pso-gc-areas.md`, the formats docs | `2b25e24d` (+ Hermes `04441d69`) | 1, 2 | P2's accept test is largely met for geometry and collision. | **Useful** |
| `pso_ram.py`: 34/34 code addresses resolved in Ghidra, 17 by byte-exact guards; the class-name pointer fix | `2b25e24d`, `febac018` | 1, 4 | The base of P2b. Open targets are listed in `pso-gc-executable.md` §7. | **Useful, half done** |
| Edited disc boots (object moved in Forest 1 layout 0) | `2474bcec` | 2 | The writer is proven at the byte level; not yet seen in game. | **Useful** |
| `pso_editor` (574 editable sets, placements, edit, preview, build) | `f1d6ffaa` | 2 | P6b's backend; there is no page yet. | **Useful** |
| `pso_gc_paths`, NJCM big-endian payloads, GVR textures: `pso_player.build` runs on this disc | `ddd6274e`, `0ea9ee61`, `2b706cdc` | 3 | P7a's model read works end to end. | **Useful, core** |
| Pack and loose-file swap; launch `mod` is a query parameter; the game reads the loose `plAbdy00.nj` | `fc835b3f`, `2fcc7dc0` | 3 | P7b per boot is visible (deformed). | **Useful** |
| Swap bounds: HUcast deforms, HUnewearl crashes at `0x8028f508`; `pso_swapfit` predicts it | `9fb68bed`, `118a7c1d` | 3 | A pre-build safety gate, and a P2b target. | **Useful** |
| City-placement mod built and booted; placements are room-local; RAM scanner validated | `5bc850c4`, `6c0d8851` | 2 | Two methods ruled out; the offset is the open piece. | **Useful negatives** |
| Boot-mode byte, `pso_menu_walk`, offline menu path, character created, `pso_boot_walk` six presses | `1e69a0e9`, `9791d2b1`, `93f7844c`, `a489832d` | 4 | Boot to town by gBox's presses works. The "screen id" was retracted (round 3). | **Partly useful** |
| Pad plumbing: `pad_bind`, `_setup_vpad` retry, `padstate.operator_slot`, the relay throttle, the Select+L1+R1 chord, the demonstration recorder | `21bf3894`, `005efeb1`, `c9db33bc`, `04f28b28`, `27741971` | 4 (and the operator's own play) | Real defects fixed. The recorder's output was never used (§0.3). | **Useful** |
| MULTI MODE: the two-pad INI, `SIDevice1 = 6`, P2 keyboard pad, two players in the lobby with no intro | `b27acb3d`, `3ce225f8`, `e0e4ec27`, `ae3768aa`, `2d38ff6b` | 4 (P5 needs co-op) | The co-op route works. But it edits the shared Dolphin profile on every PSO launch, and P2 needs the window in front (§6.4). | **Useful, with a cost** |
| `pso_write` (the gated, audited write path) | `54d272d1` | 2, 3, 4 | The right shape for live writes. | **Useful** |
| Keyboard walkers (`pso_move`, `pso_kbwalk`, `greedy_walk`, door crossing), `pso_explore` | `e4e925af`, `e3339528`, `d0cc97d7`, `b9f99393`, `b024fc1a`, `8d2c92c6`, `7a6e7f8c`, `a8f6222c` | 4 (P3 later) | A closed-loop walker that works. It needs the window in front, so it is fragile on a shared PC. | **Partly useful** |
| The city survey: rooms 10/20/30/40/41, boundary bands, inert doors, no counter answering A | `d64c6f7e`, `3424fd7b`, `c3efa058`, `42e26dcb`, `7620d3fa`, `f66fd9cb`, `fe0210fb` | 4 | 12+ rounds, no exit found; and the operator had already shown the way. | **Mostly a loop** |
| Intro "cannot be exited" (rounds 13, 37) | `93f7844c`, `fe0210fb` | 4 | **Contradicted by your own rounds 5-6** (below). | **Wrong conclusion** |

### What your hand-off (`PSO-HANDOFF-2026-11-10.md`) gets wrong

- **"The single-player intro conversation cannot be exited."** Rounds 5 and 6 are in the same session
  (`dbc5ff9be4ca416c-c91e5802a9844b37`, room 41):
  - the keyboard moved BQF from `(-5.9, -1965.7)` to `(16.6, -1936.2)`;
  - the walker reached Irene, and A started "Well, let me brief you on your mission.";
  - then the operator played on into Forest 1 (`FLOOR 1`, rooms 11 and 16).

  Rounds 13 and 37 tested a later boot that landed in front of the Principal in a conversation, mode 5. The conclusion
  holds for that state and that input path only.

  `54dc451d` (12:29, also pushed to `main`) adds one more sweep of that scene: Y/X/Z/B/L/R, START+A, A+START, BBB and
  30 s idle. That is the loop this doc asks you to stop. MULTI MODE already avoids the scene, and the operator got past
  it. Spend no more rounds on it.
- **"No route to Forest 1 found."** The operator found one this morning, and your recorder may hold it.
- **"The last session is parked in the intro of a single-player boot."** Its last frame (session
  `83202f53e9cd4aa5-697967ea4f634dc8`, about 11:57) is the two-player split screen in town, with both players' START
  menus open (P2's cursor on Quit Game).
- **"The 4 steering tests came with the lane's push"** (the hand-off's wording, not yours). Measured:
  - they were green when written (`09ff0729`, 2026-11-02 13:22);
  - they were red by `6b95cb75` (2026-11-02 20:51), after the 11-02 co-op steering commits; the first red is
    `6d465b8a`, "geometry-free forward fallback";
  - they were red at `ac7e4ea5`, before your first commit today.

  They are still yours to fix (§6.3).
- **"100 PSO tests green at hand-off."** True for the files it names. But `test_pso_steer.py`, which you added in
  `b024fc1a`, fails **5 of 5** on main: it tests `pso_kbwalk.steer_calibrate` and `steer_walk`, which were never
  committed. Measured over every `test_pso*.py` / `test_pad_bind.py` file:
  - before your first commit (`ac7e4ea5`): 40 failed, 1,150 passed;
  - on `7182de5f`: 45 failed, 1,300 passed.

  So the lane added 150 passing tests and those 5 failures, and nothing else regressed.
- **`7182de5f` (12:08) and `54dc451d` (12:29) were pushed straight to `main`.** The branches-only rule landed at 12:02 (`b49c7e2f`). From now
  on, branches only.

---

## 3. Why it sits on menu screens

### Measured

- **The i9 runs its own control plane.** You started it from `C:\_tools\gBox\system` (`serve --worker`, round 2), so
  the worker registers at `127.0.0.1`. It is reachable at `10.89.1.43:8765`.
  - The central plane (`10.89.1.246:8765`) has shown `i9-NUC` **offline since 02:25 CST**.
  - So the app and the RE session cannot see your sessions, and nobody there can help unstick one.
- **22 PSO launches today, 04:52-11:38, all cold boots through the title menus.** In minutes:
  - 12, 10, 38, 13, 3, 13, 6, 1, 27, 2, 2, 1, 2, 3;
  - 107 (the MULTI MODE co-op session);
  - 2, 3, 3, 1, 5, 29, 30.

  Twelve lasted 5 minutes or less: boot-walk, INI and character-select checks.
- **No savestate or checkpoint was kept.** `previous_checkpoints = []` and `rewind: off` on every session. Each stop
  threw away the town or lobby moment, and the next test re-walked the menus.
- **The admission gate.** Every agent launch waits for five minutes without operator input, and gBox's own pad input
  also resets the idle clock (round 3).
  - About 124 of the 437 minutes between 04:52 and 12:09 had no session at all, in 21 gaps.
  - At 12:16 the gate read `allowed: false`, `Waiting for five minutes without operator input`, with
    `idle_seconds` 0-64: someone was using the i9.
- **No autobot ran.**
  - `GET /api/autoplay/telemetry/{sid}` returns `{}` for the recent sessions.
  - `pso_controls.state` is `waiting`.
  - MercMode on the i9 is disabled.

  What the operator watched was your hand-driven tests.
- **The last frame** (session `...697967ea4f634dc8`, about 11:57):
  - both players have the in-game START menu open;
  - the DeepSeek desktop app overlaps the Dolphin window.

  Round 5 says the START menu blocks movement. Round 43 says `win_send_keys` raises (`adapters.py:622`) when Dolphin is
  not in front.
- **A stale job.** `launch_game` `4b176dbab90240cb` (`debug=true`, so `require_os: linux`) has sat queued since 04:50. A
  Windows worker never claims it. Cancel your own job.

### The causes named in the brief, one by one

| suspected cause | status | evidence |
|---|---|---|
| No character on the memory card at SELECT CHARACTER | **Ruled out since round 4** | BQF (HUmar, ORAN) was created by pad in round 4 and loaded from `MemoryCardA.USA.raw` in rounds 9 and 13; P2's temp character `3P` exists since round 19. The operator's play also used BQF. No operator decision is needed here. |
| The analog stick not reaching PSO through the virtual pad | **Real (measured in round 19), cause unknown** | The pad's buttons work and its stick moves nobody, while the keyboard bindings move both players. Hypothesis to test once (inferred): `padstate.RELAY` mirrors the operator's resting stick into the same pad and cancels the bot's stick hold. See §4.4. |
| Pad slot 0 vs 1 | **Fixed** | `pad_bind.choose_slot` (`21bf3894`), `padstate.operator_slot` (`c9db33bc`), the vpad retry (`005efeb1`). Not a current cause. |
| A second worker stack | **Not seen** | One worker (`83202f53e9cd4aa5`) on the i9 plane. Processes were not inspected (read-only from this PC). |
| A walk loop that never advances | **Yes, at the town level** | Rounds 20-41 walked rooms 10/20/30/40 and found no exit. Every hypothesis about the room-40 teleporter was tested with **P1 alone**. "Both players present" (round 26) was tested on the lobby pedestal, which is decorative. |

**Inferred:** the "menu screens" the operator saw are:
- the repeated cold boots;
- the gaps the admission gate forced between them;
- the START menu left open;
- the character-select previews used for the swap tests.

None of it is a broken menu walk. The menu walk works (round 13).

---

## 4. The way past the menus, exactly

### 4.1 Read the operator's route (no session, about 5 minutes)

In `D:\gBox\pso-ds\demos\dbc5ff9be4ca416c-c91e5802a9844b37.jsonl` (and `pads.jsonl` from `pso_padwatch.py`):
1. Find the first row where `floor` goes from `0` to `1`.
2. Print the 90 s before it: `room`, `x/z`, `phase`, `travelling`, and which XInput slot changed with which buttons.

That is the route and the button that took the party down. Turn it into waypoints and a route fixture with a test, as
round 6's next step 2 already said.

If the file starts with `floor` already `1`, the recorder started too late. Then ask the operator the one question in
§4.6.

Two cheap leads for the next live window, if the file does not settle it:
- **Both players inside room 40's teleporter ring.** Your own `pso-gc-pioneer2-rooms.md` ("Open: the teleporter does not
  answer") says to test this next. Round 26 tested "both players" on the lobby pedestal instead.
- **The reception counter in the lobby.** The last frame of session `83202f53e9cd4aa5-313da77a485442c1` shows 3P at the
  lobby pedestal and, to its right, a counter with screens and an NPC standing behind it. Whether it is the guild is
  not known. Round 29 found that A only answers when you face the keeper, not from across the counter. Check that this
  counter was approached from the keeper's side before you rule it out.

### 4.2 Make one savestate and stop cold-booting for tests

- In the next live window, boot MULTI MODE to the lobby once (`pso_boot_walk.MULTI_STEPS` plus the P2 steps from round
  19).
- Save state slot 1 (`session_op` `save_state`; the Windows adapter's `save_state` confirms the file Dolphin writes).
- Copy the `.sav` to `D:\gBox\pso-ds\states\lobby-2p.sav`. Do the same once in Forest 1 when you get there.
- After that, every test is: launch, then load the state, and you are in the lobby in seconds.

A mod build still applies when the state is loaded: the RAM is from the old disc, so load the area you are testing
after the state (walk or warp into it). That reload reads the modded files.

### 4.3 For everything except P1's acceptance, use the native area load

- **Boss arenas.** `pso_mods` op `boss_warp` loads one now (`pso_live.gamecube` -> `Adventure.teleport_boss`, the
  native `SET_TARGET` / `BEGIN_TRAVEL` / `WARP` path).
- **Any floor.** `gbox.pso_fence.warp_to_floor(ad, floor)` is the same path for any floor (1 = Forest 1). The co-op
  bot's floor advance (`pso_coop` -> `advance_floor`) runs on it, live-verified on 11-03/04 (guide §2).
- Expose it as a `pso_mods` op `floor_warp`, on a branch with a test.
- Use it as a **development tool**:
  - P6a's in-game proof (`pso_objmove_forest01_l0_r60` is already built);
  - P7b's "does an area change reload the model?";
  - the area survey (§1.2).
- Label all such evidence "reached by warp (dev)". It never counts for P1, P3 or P5 acceptance.

### 4.4 The input path that works, and the one test that could free it

| input | works? | needs the window in front? |
|---|---|---|
| P1 virtual pad buttons (A, B, START, D-pad) | yes, every menu in the lane | **no** |
| P1 virtual pad stick | **no** (round 19) | - |
| P1 keyboard arrows (the INI's alternates) | yes, moves P1 | **yes** |
| P2 keyboard (`D`/`R`/`M`/`Y`, `SPACE`, `NUMPAD8/2/4/6`; uppercase names only; B needs a 0.4 s hold) | yes | **yes** |

Two consequences:
- **Movement today needs the Dolphin window in front.** On a PC the operator is using, that fights them (and the
  DeepSeek app). Only drive movement when `GET /api/workers` reports `idle_seconds >= 300`, which is the same rule the
  admission uses. Restore the window first. Leave it alone the moment the operator is active.
- **One cheap test** could make movement focus-free:
  1. Hold `up` through the virtual pad for 2 s, with the character free in the lobby and `padstate.RELAY` for that
     session off.
  2. Read the position back.

  If it moves, the relay was overwriting the stick, and the keyboard walker can retire in favour of the pad. If it does
  not move, write that down and stop testing the stick.

### 4.5 Use the existing buddy launch for co-op, not the shared profile

`docs/pso-buddy-launch.md` is the co-op launch from 11-01 to 11-04. The `launch_game` **job** with `pso_coop: true`
gives:
- an isolated, persistent buddy card under `gbox-data/pso-buddies/...`;
- a private Dolphin User directory;
- where the virtual pad is on, a second virtual pad for P2 (`_setup_vpad` with `coop_players = 2`), so P2's buttons
  are focus-free too.

You launched through `POST /api/games/{gid}/launch`:
- that route has no `pso_coop` parameter at all, which is why round 15's `{"pso_coop": true}` was dropped;
- so the lane wrote two-pad and `SIDevice` edits into the **shared** Dolphin profile, which the operator's own PSO
  launches also use.

Try the job route once:
- leave `debug` false (`debug=true` makes it Linux-only; see the stuck job in §3);
- note in the lane log whether MULTI MODE opens with it;
- note whether P2 gets a virtual pad.

If it works, prefer it, and propose on a branch that the shared-profile edits apply only to such isolated launches.

### 4.6 Does this need the operator?

Only if §4.1's file does not cover the 0 -> 1 floor change. Then ask exactly this, in the lane log:

> "This morning (about 05:50-06:05) you took BQF from Principal Tyrell's office into Forest 1. How did you leave the
> conversation, and what did you use to go down to the planet (which room, and which button)?"

Do not ask anything else about P1 until that answer is in.

---

## 5. The re-prioritised plan: never idle on a menu

The offline packages progress from the disc image and the executable alone. Order the work so a live session is never
what you are waiting on. Keep the local model's labelling batch (§1.4) running in the background throughout.

**A. Offline, in this order** (each one is a finished, pushed step):
1. **Fix the red tests** (§6.3): your 5 in `test_pso_steer.py`, then the 4 steering-evidence ones. Branch
   `ds-pso-steer-tests-20261110`.
2. **The local model and the gold set** (§1.3). Branch not needed: it is tooling on `D:`. Lane log entry with the
   numbers.
3. **The object-class registry** (index -> `TObj*` name). This is `pso-gc-executable.md` §7.3, "the single highest-value
   decompile left for the editor". It turns every placement into "door", "warp", "switch" or "Booma":
   - for P6b's page;
   - for the swap's actor handling;
   - for P3's navigation graph.
4. **The room-local -> world offset, statically.**
   - Hypothesis (inferred): the Scene `r.rel` section table (Forest 1: 17 sections of 40 bytes, root at `0x3114`) holds
     per-section origins and rotations.
   - A record's `group_id` / `set_id` may name its section, so that world = section origin + rotation x record.
   - Check it against round 42's city data: the four room-10 door entities, matched by the six pairwise distances as
     your hand-off proposes.
   - That closes P6a's proof method without a live session.
5. **The floor -> map resolver** (`FUN_80207E88`, `FUN_802077CC`). It binds every floor to its files and layout, and the
   editor and the survey need that.
6. **The function at `0x8028f508`** (the swap crash). It lets `pso_swapfit` validate the material table from the code
   instead of from two observations.
7. **The Ragol teleporter / quest gate in code.** Find what the city teleporter checks before it opens: a flag, a quest
   state, or all players inside. That answers P1 statically, and it explains why nine single-player approaches did
   nothing.
8. **P7a rigging** (`build_swap` for GC: big-endian body, GVR textures, flat names), gated by `pso_swapfit.compare` and
   checked by a render (§1.5).
9. **P6b's page** in `system/clients`, over `pso_editor`:
   - the top-down floor and walls from `psomap.collision`;
   - placements as markers, labelled by item 3;
   - save -> build.
10. **`n.rel` render geometry** (`fmt2`) and the **save-data layout**, last among the offline items.

**B. Live, in short batched windows** (only when `idle_seconds >= 300`, one session per window, never more than one
Dolphin of yours while the operator might play):
1. Read §4.1. Make the lobby savestate (§4.2). Cancel the stale job.
2. Reach Forest 1, using the first of these that works:
   - the operator's route;
   - both players inside room 40's teleporter;
   - the lobby counter, faced from the keeper's side (§4.1);
   - `floor_warp` as dev (§4.3).

   Save a Forest 1 state.
3. P6a's in-game proof in Forest 1 with `pso_objmove_forest01_l0_r60`: read the entity table and find the moved object.
4. P7b hot: does an area change reload the player model from disc? Test it with a swapped loose `plAbdy00.nj`.
5. The area survey from savestates (§1.2): the class table and the offsets, measured per area.

**C. Then** P1's acceptance (three cold launches to Forest 1 by real presses, both players, no warp), P3 (traversal by
the collision graph), P4 and P5.

---

## 6. How to work locally on the i9

### 6.1 Checkout and branches
- Fast-forward `C:\_tools\gBox` to `origin/main` (`git fetch`, `merge --ff-only`). Work in a worktree:
  `git -C C:\_tools\gBox worktree add C:\_tools\gBox-wt-<topic> -b ds-<topic>-20261110 origin/main`.
- **Push the branch, never `main`.** The RE session reviews and merges. Say in the lane log which commits are yours.
- Data, builds, caches, Ghidra, models and frames go on `D:`. Nothing extracted from the disc goes into git.

### 6.2 Your control plane
- You run `serve --worker` locally, so the central plane shows the i9 offline and the app cannot see your sessions.
- Say so in the lane log each time you start it.
- Ask the RE session whether the i9 should rejoin the central plane (`worker --server http://10.89.1.246:8765`). That is
  their call, not yours to change.
- Only one worker stack may run on the i9. Before you start one, check that no other gBox worker process is running.

### 6.3 Tests

Invocation, from the repo root:
`PYTHONPATH="system;system/tests" python -m pytest -q -p no:cacheprovider --disable-warnings <files>`.

**The PSO baseline (measured).** Over all 103 `test_pso*.py` / `test_pad_bind.py` files:

| commit | failed | passed | skipped |
|---|---|---|---|
| `ac7e4ea5` (before your first commit) | 40 | 1,150 | 132 |
| `7182de5f` (main now) | 45 | 1,300 | 133 |

**First, yours:** `test_pso_steer.py` (added in `b024fc1a`) fails 5 of 5. It calls `pso_kbwalk.steer_calibrate` and
`steer_walk`, the round-25 turn model that you abandoned and never committed. Delete the file, or commit the code with
the model clearly marked as not used live. One line in the lane log either way.

**The 40 that were red before you started:**

| file | failures |
|---|---|
| `test_pso_margin_controller.py` | 13 |
| `test_pso_combat_routing.py` | 4 |
| `test_pso_steering_evidence.py` | 4 |
| `test_pso_field_margin.py` | 3 |
| `test_pso_lifecycle.py` | 3 |
| `test_pso_reload_admission.py` | 3 |
| `test_pso_coop_setup.py` | 2 |
| `test_pso_equipment_hooks.py` | 2 |
| `test_pso_runtime_repair.py` | 2 |
| `test_pso_combat_range.py` | 1 |
| `test_pso_enemy.py` | 1 |
| `test_pso_planner_transport.py` | 1 |
| `test_pso_recorded_evidence.py` | 1 |

Fix the steering-evidence 4 (the hand-off asks for them). Leave the others, but never add to them.

`test_pso_steering_evidence.py` fails 4 of 7 on `7182de5f`:
- `test_actual_margin_tick_records_exact_command_and_next_existing_observation`: steering `source` is `swarm_spread`
  where the test pins `margin_recovery`.
- `test_deferred_delivery_preserves_exception_and_never_claims_motion`: `KeyError: 2` in `c.margin_attempts`.
- `test_telemetry_write_failure_never_changes_command_or_tick_result`: `_observe_boss` writes `st["boss_present"]`
  outside any guard (`pso_coop.py:2844`, called at 3205), so a telemetry failure aborts the tick. **That one is a real
  code bug:** fix it in the code, not in the test.
- `test_held_no_movement_records_no_fabricated_steering`: `tick()` returns `True` where nothing should move. The newer
  forward fallback acts in the rig.

They passed at `09ff0729` and fail after the 11-02 co-op steering commits (`6d465b8a` "geometry-free forward fallback"
first, all four by `6b95cb75`). For the three steering ones, read what the tests protect, which is margin-recovery
evidence. Then choose one of two fixes, and write down why:
- a precedence rule (margin recovery wins while its state is present);
- the rig switches the forward fallback and the swarm spread off.

Do not delete assertions. Run `test_pso_coop.py` and the margin and steering suites before pushing.

### 6.4 Dolphin, the pad and the operator
- Never stop a session whose launch actor is `operator`.
- Never re-bind the operator's pad slot mid-session. Round 6 did it briefly; do not repeat it.
- The shared Dolphin profile is the operator's too. Every PSO launch now writes the two-pad `GCPadNew.ini` and
  `SIDevice` into it (`b27acb3d`, `3ce225f8`). Prefer the isolated buddy launch (§4.5). Do not add more shared-profile
  edits.
- With `BackgroundInput` on, the keyboard bindings may read keys typed into other windows. This is inferred, not
  measured. Keep that in mind before adding more keyboard bindings.
- Before any step that brings Dolphin to the front, check `idle_seconds >= 300`. Afterwards, close the in-game START
  menu, and leave the window where you found it.
- Close crash dialogs after a crash test, for example round 35's HUnewearl `Invalid read`. A dialog left in front
  blocks every later keyboard step.

### 6.5 Credit

The DeepSeek balance was $2.96 at 11:51 CST.
- Bulk reading goes to the local model.
- DeepSeek does the review, the hard reasoning and the code.
- One finished, pushed step per round, so a top-up gap loses nothing.
- Below $0.50, write a five-line hand-off in the lane log and stop.

---

## 7. What to report back

Append each step to `system/docs/ds-pso-lane-2026-11-10.md` on your branch, and push the branch. Per step:
- **what:** the package and item from §5, and the goal it serves (1-4);
- **commits** and the branch;
- **measured vs inferred:** say which, line by line;
- **live evidence:** session ids, the savestate used, RAM reads with addresses, frames (kept on `D:`), and "reached by
  warp (dev)" wherever a warp was used;
- **GPU:** the `nvidia-smi` line for the 3090 during the step, and the local model's tokens/s and labels per hour;
- **credit:** DeepSeek dollars before and after;
- **tests:** what you ran, against the §6.3 baseline (45 failed on `7182de5f`; never more);
- **next:** one line;
- **for the operator:** only the §4.6 question, and only if §4.1 did not answer it.

---

## Appendix: the evidence behind §3 (all read-only)

- i9 plane `GET /api/sessions`: 46 PSO sessions in total, 22 today. Each listed with its start, end, mod and exit `via:
  stop`. The last is `83202f53e9cd4aa5-697967ea4f634dc8`, `pso_city_npc_moved`, 11:38-12:09. No session was running at
  12:17.
- i9 plane `GET /api/jobs`, today:
  - 22 `launch_game` succeeded, 1 queued since 04:50 (`4b176dbab90240cb`, `require_os: linux`);
  - 20 `session_op stop_game` succeeded, 1 failed;
  - `write_memory`: 2 succeeded, 4 failed (07:29-07:42, session `a189397c90264878-577d5984235144e7`: the tick-counter
    probe of round 15).
- i9 plane `GET /api/workers`, `i9-NUC` at 12:16-12:17:
  - `admission.allowed = false` ("Waiting for five minutes without operator input."), `background_testing = true`;
  - `ollama.available = false`;
  - the GPU samples in §1.1.
- Central plane `GET /api/workers`: `i9-NUC` (`cfc1f4ebaf534b05`) `online: false`, last seen 02:25 CST.
- Frames:
  - `GET /api/sessions/{sid}/frame.jpg` for the last three sessions;
  - the last one is described in §3; the two before it show both players in town with their HUDs and no menu open.
  - The frames are kept off git.
- Tests (run on JAYBUILTFINALE, Python 3.12):
  - `test_pso_steering_evidence.py`: 4 failed, 3 passed on `7182de5f`; the same at `ac7e4ea5`; 7 passed at
    `09ff0729`;
  - all 103 PSO test files: 45 failed / 1,300 passed on `7182de5f`, against 40 failed / 1,150 passed at `ac7e4ea5`. The 5
    new failures are all in `test_pso_steer.py`, and none failing at `ac7e4ea5` passes now.
