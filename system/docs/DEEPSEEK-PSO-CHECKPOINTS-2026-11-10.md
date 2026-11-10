# DeepSeek PSO checkpoints: how to proceed from here (2026-11-10, ~14:00 CST)

Written for the DeepSeek session(s) on the i9-NUC by the PM's audit agent. The operator, ~13:40 CST: "check into the pso
task and make an updated task guide for the deepseek session as to how to proceed and get to the checkpoints".

This is the task guide from now on. It is an ordered list of checkpoints (CP), starting from where the lane really is at
14:00. `DEEPSEEK-PSO-TASK-GUIDE-2026-11-09.md` §0d still defines the goals. `DEEPSEEK-PSO-PROGRESS-2026-11-10.md`
explains the audit behind this. Where they differ from this file, this file wins.

---

## Hard rules (read before every session)

> **1. Hands off lilspark.** Never `ssh` into the Spark (10.89.1.246). Never run `sudo`, `systemctl`, `kill` or `curl`
> there. Never launch, stop or relaunch a game on it.
>
> Today something did all of that:
> - two `sudo systemctl restart gbox.service`, at 12:22:57 and 12:41:09, each of which killed the live MercMode games;
> - curl stops and operator-token launches.
>
> Work only against the i9's own gBox (`http://10.89.1.43:8765`) and its own Dolphin. Anything that needs lilspark is a
> request in your evidence file; the RE session does it.

> **2. Branches only. Never push `main`.**
> - Branch names: `ds-pso-cp<NN>-<topic>-20261110`. Push the branch. The RE session reviews and merges.
> - Since noon, 19 commits by `gBox DeepSeek lane <deepseek@gbox.local>` went straight to `main` (the last at 13:35).
>   That stops now.

> **3. `x-gbox-actor: agent` on every API call,** with the token from `system/gbox-data/api_token`. Never print the
> token.

> **4. One checkpoint, one owner.** Two DeepSeek identities are working PSO in parallel:
> - `gBox DeepSeek lane` pushes to `main`;
> - `DeepSeek` pushes `ds-pso-*` branches.
>
> They have already built the same thing twice: `gbox/pso_classes.py` on main and `gbox/pso_class_registry.py` on a
> branch read the same table, with the same 0x46-0x49 doors. The branch pins it at `0x805D3138`; main finds it from the
> `TObjCityDoor_Shop` anchor. They also collide on round numbers (two "Round 53", two "Round 58").
>
> Claim a checkpoint by pushing its branch first, with an empty evidence file (rule 5). Never work a checkpoint whose
> branch already exists. If you are the session that has been pushing to `main`, either stop PSO work or carry on only
> on branches under this claim rule. Say which, in one line, in an evidence file on a branch.

> **5. Evidence goes in its own file, not in the shared lane log.** 11 of your 16 open PSO branches conflict with `main`.
> Every one of those conflicts is in `ds-pso-lane-2026-11-10.md`, and one branch also conflicts on `test_pso_editor.py`.
> - From now on, each checkpoint writes `system/docs/pso-checkpoints/CP<NN>-<topic>.md`, created on its own branch.
> - Do not edit `ds-pso-lane-2026-11-10.md` again. It stays as the history of rounds 1-61.

> **6. Leave the i9 the way the operator should find it.** When a step ends:
> - close the in-game menu;
> - restore the Dolphin window if you moved it;
> - stop your own session if nothing needs it.
>
> At 13:46, session `83202f53e9cd4aa5-54da9e9d8a764de8` (yours, `pso_guilddoor_moved`, up since 12:55) was sitting with
> both players' START menus open and the DeepSeek app window over Dolphin. That is the "stuck on menu screens" the
> operator keeps seeing.
>
> Never stop a session whose launch actor is `operator`.

> **7. Live steps only when the operator is away.**
> - Run a live step only when `GET /api/workers`, row `i9-NUC`, reports `idle_seconds >= 300` and `admission.allowed`.
>   That is the same five-minute rule the launch gate uses.
> - Otherwise do an offline checkpoint. Every phase below has one, so there is never a reason to wait on a menu.

> **8. Credit.** DeepSeek was at $2.96 at 11:51. Two identities have committed since; the balance now is not known
> here.
> - Read the balance before each checkpoint. Below $0.50, write a five-line hand-off in your evidence file and stop.
> - Once CP1 is done, bulk reading goes to the local model; DeepSeek reviews and writes code.

---

## Where the lane is at 14:00 (measured)

**Done and on `main`:**
- P2 formats:
  - placement sets, GSL / AFS / BML / PRS / NJCM / GVR round trips (`2b25e24d`, `1ee1d723`, `a7fac496`);
  - the `.evt` framing, 143/143 (`09af0b4d`, `02dfda2a`).
- P2b:
  - `pso_ram` (`2b25e24d`, `febac018`);
  - `pso_dol`, the DOL address map at base `0x8000c000` (`94367dfd`);
  - `pso_classes` (`ef21e790`, `8f56873c`).
- **P6a proven in game:**
  - the offset `(+228,+291)` (`082975fc`);
  - `pso_guilddoor_moved` read back at `(235.0, 173.0)` (`639fc1d5`);
  - `pso_offset.solve` (`8032491f`).
- P6b: backend, CLI and ASCII map (`f1d6ffaa`, `bf777c74`, `14987a73`).
- P7a model build and P7b visible swap: `ddd6274e`, `0ea9ee61`, `2b706cdc`, `fc835b3f`, `2fcc7dc0`, `9fb68bed`,
  `118a7c1d`.
- P1 boot to town and MULTI MODE co-op: `93f7844c`, `e0e4ec27`, `2d38ff6b`.

**On branches, waiting for the RE session's merge (16, by `DeepSeek`):**

| branch | tip | checkpoint | merges clean? |
|---|---|---|---|
| `ds-pso-steering-tests-20261110` | `5773d4be` | the 4 steering-evidence tests green, plus the unguarded-telemetry bug | lane-log conflict |
| `ds-pso-steer-tests2-20261110` | `275c0bdf` | `steer_calibrate` / `steer_walk` for the 5 red `test_pso_steer.py` | lane-log conflict |
| `ds-pso-floor-map-20261110` | `6cb1c828` | the floor -> map/layout resolver (36 floors) | lane-log conflict |
| `ds-pso-floor-editor-20261110` | `2be3617f` | the floor record's meaning, floor -> sets join | lane log and `test_pso_editor.py` |
| `ds-pso-class-registry-20261110` | `a18da08e` | A3: registry at `0x805D3138`, 148 names, 84.4 % labelled (duplicates `pso_classes`) | lane-log conflict |
| `ds-pso-editor-page-20261110` | `262b117c` | P6b page + `POST /api/pso/editor/build` | lane-log conflict |
| `ds-pso-travel-gate-20261110` | `4b872480` | A7 first pass | lane-log conflict |
| `ds-pso-vtables-20261110` | `e2d5191e` | A7: class vtable convention | lane-log conflict |
| `ds-pso-vtable-census-20261110` | `9bf56a16` | vtable census in code | lane-log conflict |
| `ds-pso-sda-20261110` | `28def085` | r13 / r2 small-data bases | lane-log conflict |
| `ds-pso-memcard-20261110` | `1438cf10` | A10: card reader (see CP9: it may have read the wrong card) | lane-log conflict |
| `ds-pso-floor-warp-20261110` | `712f4a7f` | `pso_mods` op `floor_warp` (dev) | clean |
| `ds-pso-actor-dump-20261110` | `92ee3e4d` | A7: no city event set; `pso_actor_dump` | clean |
| `ds-pso-gvr-write-20261110` | `e84af16c` | A8: GVR writer incl. CMPR | clean |
| `ds-pso-tree-endian-20261110` | `8090217d` | A8: big-endian node tree | clean |
| `ds-pso-body-platform-20261110` | `e1abfc4b` | A8: platform-aware body read/write | clean |

**Not done (measured at 13:46):**
- **No local model.** `ollama.available = false`. The 3090 shows 141 MB and 37-39 % while Dolphin runs, and dropped to
  0 MB when a session stopped at 12:16. So Dolphin renders on the 3090 (inferred from that on/off match), and nothing
  else uses it.
- **No savestate or jump state.** Every session since 12:10 has `previous_checkpoints: []` and `jump: false`. There have
  been 4 more cold boots, and one launch was cancelled by the operator at 12:51.
- **A stale job.** `launch_game` `4b176dbab90240cb` (Linux-only) is still queued from 04:50.
- **The operator question is not delivered.** The `DeepSeek` session read the recording back: 404 rows, 881 s, and it
  starts with `floor` already 1, so it does not contain the route. That session drafted the §4.6 question, but only in an
  unmerged branch's lane log.

**Tests:** the PSO baseline is in CP0.

---

## CP0. Clean start (15 minutes, mostly offline)

- **Goal:** all four, because it unblocks everything else.
- **Steps:**
  1. Stop your parked session if nothing needs it. Confirm it is yours first (`agent_owned: true`, not `operator`).
     Close its menus first if you will keep it.
  2. Cancel your stale queued `launch_game` `4b176dbab90240cb` on the i9's plane.
  3. Make every open `ds-pso-*` branch merge clean. First check
     `git branch -r --merged origin/main`, and never rewrite a branch the RE session has already merged. For each
     unmerged one:
     - rebase it on `origin/main`;
     - move its lane-log text into `system/docs/pso-checkpoints/<branch-topic>.md`;
     - drop its edit to `ds-pso-lane-2026-11-10.md`;
     - push it again (the same branch name, `--force-with-lease`, on your own unmerged branch only).

     Say in the evidence file which branches you rewrote, so the reviewer does not review a stale tip.
  4. Reconcile the duplicate registry on one branch, `ds-pso-cp00-classes-20261110`:
     - keep `gbox/pso_classes.py` as the module;
     - fold in the branch's table address (`0x805D3138`) and its 148-name list as a cross-check test;
     - make `pso_class_registry` a thin alias, or delete it;
     - keep both sets of tests.
  5. Put the operator question in `system/docs/pso-checkpoints/CP00-operator-question.md` and tell the RE session in
     one line that it is waiting:
     > "This morning (about 05:50-06:05) you took BQF from Principal Tyrell's office into Forest 1. How did you leave
     > the conversation, and what did you use to go down to the planet (which room, and which button)?"
- **Accept:**
  - `git merge-tree --write-tree origin/main <branch>` exits 0 for every `ds-pso-*` branch;
  - one registry module, with its tests green;
  - the i9 plane shows no queued Linux job and no parked agent session;
  - the question file exists.
- **Evidence:** `CP00-clean-start.md`, listing the branches and tips after the rebase, the merge-tree results, and the
  baseline test numbers below.
- **Test baseline.**
  - Run every `system/tests/test_pso*.py` and `test_pad_bind.py`:
    `PYTHONPATH="system;system/tests" python -m pytest -q -p no:cacheprovider --disable-warnings <files>`.
  - Measured on `8032491f` (main at 13:35): see "The CP0 test baseline" at the end of this file.
  - "Done" for any checkpoint means no new failures against that number.
- **If blocked:** if a rebase conflicts in code (not the log), leave that branch as it is and name the conflict in the
  evidence file. The RE session resolves it.

---

## CP1. The local coder model on the 3090 (GPU)

- **Goal:** 1 (decrypt / P2b), and through it the editor and the swap.
- **State:** open. Measured at 13:46: Ollama unreachable, and nothing on the 3090 but Dolphin (141 MB).
- **Steps** (everything on `D:`, loopback only):
  1. Install Ollama for Windows. If installing is not possible, use a portable CUDA build of llama.cpp's
     `llama-server` unzipped to `D:\gBox\llm\llama.cpp\` (no installer).
  2. Set the environment, then quit and restart Ollama so it reads it:
     ```powershell
     setx OLLAMA_MODELS "D:\gBox\llm\ollama-models"
     setx OLLAMA_HOST "127.0.0.1:11434"
     setx CUDA_VISIBLE_DEVICES "GPU-f3697ec1-9016-3424-7886-750a24ddc07a"   # the 3090's UUID (worker telemetry)
     setx OLLAMA_FLASH_ATTENTION "1"
     setx OLLAMA_KV_CACHE_TYPE "q8_0"
     setx OLLAMA_MAX_LOADED_MODELS "1"
     setx OLLAMA_NUM_PARALLEL "2"
     setx OLLAMA_KEEP_ALIVE "24h"
     ```
  3. Pull two coder models that fit 24 GB with Dolphin beside them. Dolphin uses about 0.2 GB of the 3090 today; keep
     the 3090 at 22 GB or less in total. Candidates:
     - a 30B mixture-of-experts coder at Q4 (about 19 GB, fast);
     - a 32B dense coder at Q4 (about 20 GB);
     - a 14B coder as the fallback (about 9 GB).

     Use a 16k context, not more.
- **Accept:**
  - `ollama ps` shows the model at `100% GPU`;
  - `nvidia-smi --query-compute-apps=pid,process_name,used_memory,gpu_uuid --format=csv` lists the runtime on
    `GPU-f3697ec1-...` with the model's size;
  - `GET /api/workers`, row `i9-NUC`: `.ollama.available = true`, and the 3090's `memory_used_mb` near the model
    size;
  - `ollama run <model> --verbose` prints an eval rate (tokens/s).
- **Evidence:** `CP01-local-model.md`, holding:
  - the three outputs above, verbatim;
  - the model names and sizes;
  - tokens/s for each candidate.
- **If blocked:** if the install needs the operator's permission, or CUDA will not start on the eGPU, write the exact
  error in the evidence file, put the question to the operator through the RE session, and go on to CP4 and CP6. They
  need no model.

## CP2. The gold set: the 34 known functions

- **Goal:** 1. This checks the model before anyone trusts it.
- **Steps:**
  1. Take the 34 code addresses already proven in `docs/research/pso-gc-executable.md` §3 (named in `gbox/pso_ram.py`).
  2. Export each function's decompiled C from the Ghidra project `D:\gBox\ghidra-pso` with pyghidra
     (`D:\gBox\runtime\pyghidra-venv\Scripts\python.exe`). Strip the names.
  3. Ask both candidate models for `{"name", "role", "confidence", "evidence"}` per function.
  4. Score each answer: exact name, same role, or wrong.
- **Accept:** `D:\gBox\pso-ds\llm\gold34-<model>.json` exists for each candidate, with a hit rate and seconds per
  function. Pick the model with the best role hit rate.
- **Evidence:** `CP02-gold-set.md`, holding the two scores, the chosen model, and five example answers (right and
  wrong).
- **If blocked:** below about 50 % on roles, keep the model only for summaries and candidate lists. No name it proposes
  enters `pso_ram.py` without a decompile or live proof, which was always the rule.

## CP3. The bulk labelling pipeline, running unattended

- **Goal:** 1, feeding CP7, CP8, CP12 and CP15.
- **Steps:**
  1. Export JSONL rows to `D:\gBox\pso-ds\llm\functions.jsonl`. Each row holds: address, size, callers, callees,
     referenced strings, and the decompiled C truncated to about 6 KB.
  2. Export these neighbourhoods first:
     - the `0x8028f508` function and its callers (CP12);
     - the code that reads `TObjCityDoor_*` instances and the door classes' vtables (CP15);
     - the card / `CARD*` SDK callers (CP9);
     - the `.evt` interpreter's callers (CP7);
     - the scene / `n.rel` loader (CP8).
  3. A script in `D:\gBox\pso-ds\llm\` labels them in batches against `127.0.0.1:11434` and writes `labels.jsonl`.
  4. Leave it running while you do anything else.
  5. DeepSeek reviews only rows tied to an open checkpoint.
- **Accept:**
  - `labels.jsonl` grows on its own;
  - functions labelled per hour, measured;
  - `nvidia-smi` shows the 3090 busy during the batch;
  - the first reviewed labels are accepted into `pso-gc-executable.md`, each with its proof.
- **Evidence:** `CP03-labelling.md`, holding throughput, rows labelled, labels accepted, and DeepSeek dollars per
  accepted label.
- **If blocked:** the export alone is still useful. Review it with DeepSeek in small batches.

---

## CP4. No cold boots: a lobby jump state

- **Goal:** 2, 3 and 4. Every live test after this starts in the lobby in seconds instead of re-walking the menus.
- **What already exists** (`gbox/jumpstate.py`): a `launch_game` **job** with `jump: true` boots Windows Dolphin
  straight into `<runtime>\jumpstates\<game_id>-<build>.state` with `--save_state`. Here `<build>` is the mod name, or
  `stock`. On the i9 the runtime folder is `D:\gBox\runtime`, inferred from the Dolphin log path
  `D:\gBox\runtime\logs\dolphin-win-*.log`. The session's `detail.jump` reports `{booted: true, file: ...}`.
- **Steps** (one live window):
  1. Launch the stock game. Boot MULTI MODE to the lobby (`pso_boot_walk.MULTI_STEPS` plus the P2 steps of round 19).
  2. Close every menu.
  3. Submit `session_op` `save_state`. The Windows adapter saves Dolphin slot 1, confirms the file it wrote, and returns
     its path.
  4. Copy that file to `D:\gBox\runtime\jumpstates\436e0bb84d5337d1-stock.state`. Copy it again for each mod build you
     will test, as `436e0bb84d5337d1-<mod>.state`.
  5. Launch through the job route with `jump: true` and the mod you want (`mod` in the job input).
- **Accept:**
  - the new session's `detail.jump.booted = true`;
  - within 30 s, `pso_ram` reads two players, `FLOOR 0`, room 10;
  - no menu was pressed.
- **Evidence:** `CP04-jump-state.md`, holding the session ids, the state file's sha256, and the RAM read.
- **Mod caveat.** A state holds the old disc's loaded area in RAM. For a mod test, change area after the boot (walk out
  and back, or CP5's warp) so the area reloads from the modded disc. P6a's proof did this implicitly by booting cold.
- **If blocked:**
  - If `jump` does not boot (the detail says why), launch normally and `session_op` `load_state` slot 1 right after.
  - If `save_state` fails, record the error and do CP6-CP9 offline. They need no session.

## CP5. Forest 1 for development (warp, not P1)

- **Goal:** 2, 3 and 4 (development only).
- **State:** the code is ready on `ds-pso-floor-warp-20261110` (`712f4a7f`, `pso_mods` op `floor_warp`) and is not
  merged.
- **Steps:**
  1. After the merge (or with the i9 plane run from a worktree that has it, one stack only, and never while an operator
     session runs), boot the lobby jump state.
  2. Call `pso_mods` `op=floor_warp target=1`.
  3. Wait until `travelling` is 0 and `FLOOR` is 1.
  4. Save a state and copy it to `jumpstates\436e0bb84d5337d1-stock-forest1.state`. To boot it, copy it over the
     build's name.
- **Accept:** `FLOOR 1` with both players, the entity table showing Forest classes, and a Forest 1 state file.
- **Evidence:** `CP05-forest1-dev.md`, labelled "**reached by warp (dev)**". It never counts for P1, P3 or P5.
- **If blocked:** `pso_mods` `boss_warp` (on main) loads a boss arena by the same native path. Use it to test that the
  warp works at all.

---

## CP6. Decrypt / formats: what is left of P2

- **Goal:** 1.
- **Done** (on main): every container, PRS, NJCM, GVR, the placement sets, the `.evt` framing, the areas catalogue.
- **Done on branches:** the GVR writer with CMPR (`e84af16c`), the big-endian node tree (`8090217d`), the
  platform-aware body (`e1abfc4b`).
- **Open, in order:**
  1. **`.evt` opcode semantics.**
     - Name the opcodes by their interpreter (CP3 exports its neighbourhood) and by correlation in a field area: CP5's
       state, then watch an event fire.
     - **Accept:** `gbox/pso_evt.py` decodes each opcode group to a named op; a test rebuilds one real script
       byte-identically from the named ops.
  2. **`n.rel` render geometry** (the `fmt2` root).
     - **Accept:** a decoder with a round trip on one real Forest 1 file, and the triangle count compared against
       `c.rel`'s footprint.
  3. **Other encrypted or checksummed data:** only the save data remains (CP9).
- **Evidence:** `CP06-<format>.md` per format: the files used, round-trip byte counts, tests.
- **If blocked:** each item is offline. Move to the next.

## CP7. The executable: open P2b targets (with the local model)

- **Goal:** 1, and through it 2 and 3.
- **Done:** `pso_ram`, `pso_dol`, the class registry, the floor resolver (branch `6cb1c828`), the small-data bases
  (branch `28def085`), the vtable census (branch `9bf56a16`).
- **Open, in order:**
  1. **The model-walk crash at `0x8028f508`** (CP12 needs it).
     - **Accept:** the function named, with its decompile and the field it reads at `+0x8`, in `pso-gc-executable.md`;
       `pso_swapfit` checks that field from the file.
  2. **The object loader.** What turns a placement's `kind` into a constructor call (it confirms the 148 labels and
     names the other 16 %).
     - **Accept:** labelled coverage above 84.4 %, with a test.
  3. **The scene loader** (what reads `n.rel` / `r.rel` and with which transform). CP8 and CP14 need it.
- **Evidence:** `CP07-<target>.md`, holding the address, the decompile excerpt and the proof.
- **If blocked:** go back to the local model's candidate list (CP3) for the next target.

## CP8. The room pieces (for level expansion)

- **Goal:** 2 (P6c).
- **Steps:**
  1. Decode the `r.rel` section table: Forest 1 has 17 sections of 40 bytes, root at `0x3114`.
  2. Find each section's transform and which geometry and collision pieces it places.
  3. Cross-check against `pso_offset.solve`'s per-room offsets.
- **Accept:** a reader that lists Forest 1's rooms with their origins, and a test that a known door entity lands on a
  section boundary.
- **Evidence:** `CP08-room-pieces.md`.
- **If blocked:** offline. Work CP7's scene loader first.

## CP9. Save data: the card that really holds BQF

- **Goal:** 1 (the last "encrypted or checksummed" item) and 4 (the save the boots use).
- **State:** `ds-pso-memcard-20261110` reads `MemoryCardA.USA.raw` and finds every PSO entry at first block `0xFFFF`,
  count 0. But BQF has loaded from a card in rounds 9, 13, 19 and since. So either that reader read a file Dolphin was
  not using, or it misreads the directory. (Inferred; unresolved.)
- **Steps:**
  1. Find the card the running Dolphin really has open: `Dolphin.Core.MemcardAPath` on its command line (the `-C`
     arguments) or in that session's Dolphin user directory. Launches with `memory_cards: "operator"` copy the
     operator's selected card into the session work dir instead.
  2. Compare the file's mtime with a "Wrote to Memory Card A" moment.
  3. Run the reader on that file. Read it only: never write the operator's cards.
  4. Then decode `PSO_CHARACTER`'s payload layout and name any checksum or cipher, with its key source.
- **Accept:**
  - the real card's path;
  - the reader lists BQF's entry with real blocks;
  - a test parses a copy of it;
  - the doc names the save's checksum or cipher, or proves there is none.
- **Evidence:** `CP09-save-data.md`.
- **If blocked:** offline. The CP3 export of the `CARD*` callers gives the save code's layout.

---

## CP10. P6a in a field area

- **Goal:** 2. The city proof is done (`639fc1d5`); the guide's acceptance names Forest 1.
- **Steps:**
  1. Boot `pso_objmove_forest01_l0_r60` (already built under `D:\gBox\cache\mods\436e0bb84d5337d1\`) with CP4's
     state and CP5's warp.
  2. Solve Forest 1's offset with `pso_offset.solve(<the set's records>, <entities>)`.
  3. Read the moved record's entity.
- **Accept:** the entity is at the written world position (the "MOVED" verdict as in round 49), and the unchanged records
  are where they were.
- **Evidence:** `CP10-p6a-forest1.md`, holding the session id, the offset, and the before and after positions. Mark it
  "reached by warp (dev)".
- **If blocked:** without CP5, prove it in another loaded room of the city.

## CP11. P6b: the editor page, end to end

- **Goal:** 2.
- **State:** the page and its build API are on `ds-pso-editor-page-20261110` (`262b117c`), not merged. A merge changes
  `server.py`, so the i9 plane needs a restart. Never restart it while an operator session runs.
- **Steps:**
  1. After the merge, open the page.
  2. Pick Forest 1's set and drag a marker.
  3. Build.
  4. Boot it (CP4) and read the entity (CP10's method).
- **Accept:** a moved marker in the page becomes a moved entity in RAM. A frame of the page and the entity read go in
  the evidence.
- **Evidence:** `CP11-editor-page.md`.
- **If blocked:** do the page's remaining UI offline (labels from the merged registry, the collision floor view), and
  test it with the build API's own tests.

## CP12. P7a: a correct (rigged) swap

- **Goal:** 3.
- **State:** the three A8 pieces are on branches (`e84af16c`, `8090217d`, `e1abfc4b`).
- **Steps:**
  1. Wire them into `pso_player.build_swap` behind `platform='gc'`:
     - `gvr_chunk` in place of `pvr_like`;
     - the big-endian tree and body writers;
     - the flat GC file names (`pso_gc_paths`).
  2. Gate every build with `pso_swapfit.compare`.
  3. Render each candidate headless in Blender (Cycles, OptiX on the 3090) before booting it.
  4. Boot only the clean ones, to character select.
- **Accept:**
  - a swapped body that `pso_swapfit` marks safe;
  - it renders without exploded polygons (image on `D:`);
  - it shows at character select with no Dolphin crash dialog (a frame).
- **Evidence:** `CP12-rigged-swap.md`, holding the donor, the swapfit report, the render path, the session id and the
  frame description.
- **If blocked:** if the rig still deforms, stay offline and compare bone weights and roles against the host. CP7's
  `0x8028f508` tells you what the renderer reads.

## CP13. P7b: library donors, per boot and then hot

- **Goal:** 3.
- **Steps:**
  1. **Per boot.** A donor from gBox's character library (the same donor seam as `re5_donor_pool` / `re5_cast_writer`),
     retargeted to PSO's 64-bone skeleton by CP12's path, built, and shown at character select.
  2. **Hot.**
     - With CP5's Forest 1 state, find where the loaded player model lives in RAM, using the actor's model pointer and
       CP7's loader.
     - Then test whether an area change reloads it from disc.
     - Then either rewrite it in RAM through the audited `pso_write` path, or point the next load at another file that
       is on the disc.
- **Accept:** two different library donors in one session, swapped without restarting Dolphin, each with a frame (the
  guide's §0d test).
- **Evidence:** `CP13-hot-swap.md`.
- **If blocked:** deliver per boot first. It is useful on its own.

---

## CP14. P6c: one room added

- **Goal:** 2.
- **Steps:**
  1. Using CP8's room pieces, duplicate one Forest 1 room piece, joined to an existing door.
  2. Collision included.
  3. Build, and load it with CP5's warp.
- **Accept:**
  - the area loads without a crash;
  - the player stands on the new piece (a stable `y` in RAM);
  - the bot's or walker's position can reach it.
- **Evidence:** `CP14-room-added.md`.
- **If blocked:** first expand by adding records (objects and enemies), which the writer already does, and record it as
  "expansion by placements only".

## CP15. P1: the real way from the city to Forest 1

- **Goal:** 4.
- **Steps, cheapest first:**
  1. The operator's answer to CP0's question.
  2. **Both players inside room 40's teleporter ring.** Never tested: round 26 tested "both players" on the lobby
     pedestal, and your own `pso-gc-pioneer2-rooms.md` says to test this next.
  3. **A live actor dump** (`pso_actor_dump`, on `92ee3e4d`) of `TObjCityDoor_Warp` against `_Guild`. Find the handler
     slots that differ, then CP3 and CP7 decompile that handler for the condition it checks.
  4. Before you walk to any door in the `map_lobby_01..10` sets, check that those sets are loaded in the offline city
     at all.
     - The entity table matched `map_city00_00o.dat` (10 of 28 records at distance 0).
     - Fifteen `map_lobby_*` sets with "colour and soccer variants" look like the **online lobbies**, not city rooms.
       This is inferred, not measured.
     - So confirm residency before you walk.
- **Accept:** `FLOOR` goes 0 -> 1 with `travelling` 1 -> 0 and no warp used, with the RAM trace and the session id.
  Then the guide's P1 test: three cold launches reaching Forest 1 with both players.
- **Evidence:** `CP15-p1-route.md`.
- **If blocked:** do not walk the city again. Go back to step 3 offline (the handler's condition is a decompile).

## CP16. Focus-free movement

- **Goal:** 4 (P3-P5 cannot fight the operator for the window).
- **Steps:** with the character free in the lobby (CP4) and `padstate.RELAY` off for that session, hold `up` through
  the virtual pad for 2 s, then read the position.
- **Accept:** the position moves.
  - If it does, the stick path works and the keyboard walker retires.
  - If it does not, write down the negative and stop testing the stick.
- **Evidence:** `CP16-stick.md`.
- **If blocked:** keep the keyboard walker, live only under rule 7.

## CP17-CP19. Mastery

- **CP17 (P3): Forest 1 -> Forest 2 by walking the collision graph.**
  - Use `psomap.collision`, the floor resolver and `pso_floor_map`, then `re5_nav`'s pattern.
  - Do it with both players, and develop it from CP5's state.
  - **Accept:** the floor id changes by walking, with no warp.
- **CP18 (P4): the Dragon defeated.**
  - Develop it with `boss_warp` (dev) and `pso_boss_strategy`.
  - **Accept:** the boss's HP reaches 0 from RAM, with both players alive.
- **CP19 (P5): Episode I unattended**, with the mastery build (`pso_master_build`).

---

## Per-checkpoint evidence file (the format)

`system/docs/pso-checkpoints/CP<NN>-<topic>.md`, on that checkpoint's branch:

```
# CP<NN> <title> — <done | blocked | partial>
Session identity: <DeepSeek | gBox DeepSeek lane>    Branch: ds-pso-cp<NN>-...    Commits: <sha> ...
Goal: <decrypt | editor | hot swap | mastery>
Measured: <each line with its source: file, session id, RAM address, test>
Inferred: <each line>
Live: <session ids, jump state used, "reached by warp (dev)" where it applies, frames kept on D:>
GPU: <nvidia-smi line for the 3090; local model tokens/s and labels/hour>
Credit: <DeepSeek $ before / after>
Tests: <files run; failed/passed against the CP0 baseline>
Needs: <a merge, an i9 plane restart, an operator answer, anything for the RE session>
Next: <one line>
```

## The CP0 test baseline (measured on `8032491f`)

Every `system/tests/test_pso*.py` file plus `test_pad_bind.py`, run on JAYBUILTFINALE (Python 3.12) at 14:08 CST.

| commit | failed | passed | skipped |
|---|---|---|---|
| `ac7e4ea5` (before the lane's first commit) | 40 | 1,150 | 132 |
| `7182de5f` (12:08) | 45 | 1,300 | 133 |
| `8032491f` (main at 13:35) | **45** | **1,333** | 133 |

The 45 are the same set at `7182de5f` and `8032491f`.

| file | failures | note |
|---|---|---|
| `test_pso_margin_controller.py` | 13 | red before the lane |
| `test_pso_steer.py` | 5 | the lane's (`b024fc1a`); `ds-pso-steer-tests2-20261110` says it fixes them (not re-run here) |
| `test_pso_combat_routing.py` | 4 | red before the lane |
| `test_pso_steering_evidence.py` | 4 | red since 11-02; `ds-pso-steering-tests-20261110` says it fixes them (not re-run here) |
| `test_pso_field_margin.py` | 3 | red before the lane |
| `test_pso_lifecycle.py` | 3 | red before the lane |
| `test_pso_reload_admission.py` | 3 | red before the lane |
| `test_pso_coop_setup.py` | 2 | red before the lane |
| `test_pso_equipment_hooks.py` | 2 | red before the lane |
| `test_pso_runtime_repair.py` | 2 | red before the lane |
| `test_pso_combat_range.py` | 1 | red before the lane |
| `test_pso_enemy.py` | 1 | red before the lane |
| `test_pso_planner_transport.py` | 1 | red before the lane |
| `test_pso_recorded_evidence.py` | 1 | red before the lane |

If the two test branches do what their commits say, the count drops to 36 once they are merged. Never more than the
number at the last merge.
