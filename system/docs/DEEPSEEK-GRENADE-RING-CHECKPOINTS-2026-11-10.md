# DeepSeek grenade-ring lane: checkpoints, 2026-11-10 (for the i9 session)

Written by the RE session on JAYBUILTFINALE, 2026-11-10 ~14:05 CST. The operator (~13:40) asked for "a checked,
updated task guide with checkpoints" for the PSO lane, then said "same with grenade ring". This is that guide for the
grenade lane.

It was checked against origin/main `8032491f` (13:35), every `ds-*` grenade branch, the lane log on each branch, and
the i9's own control plane. Where it differs from `DEEPSEEK-HANDOFF-2026-11-10.md` section 2B or
`DEEPSEEK-GRENADE-RING-TASK-2026-11-10.md`, this doc wins. It replaces their order with the checkpoints below.

## 0. Rules (read before anything else)

- **Hands off lilspark (the Spark, 10.89.1.246).** This is a hard rule.
  - Never `ssh` into it, and never run `sudo`, `systemctl`, `kill` or `curl` there.
  - Never launch, stop or relaunch a game there.
  - Never change MercMode settings, the queue, `default_mods` or `re4-mods.json`.
  - Two `systemctl restart gbox.service` today (12:22:57 and 12:41:09) killed the live games. The Spark's journal
    shows they came from ssh sessions opened from JAYBUILTFINALE (10.89.1.13). The i9 (10.89.1.43) opened none since
    12:00. Keep it that way.
- **Work on the i9,** against its own gBox (`10.89.1.43:8765`), with its local disc images, Eden / Citron, Ghidra
  and Python.
- **Branches only.** Name each one `ds-<topic>-20261110`. Push the branch, never `main`.
  - The RE session reviews, merges and deploys.
  - The grenade lane kept to this rule. The PSO lane ("gBox DeepSeek lane") pushed 17 commits straight to main after
    12:02; don't do that here.
- **Stack your branches.** Cut each new branch from your previous tip, or from the integration branch of
  checkpoint 0, never from main in parallel. Today's seven branches all append to the lane log at the same line, so
  merging both chains conflicts three times. A straight line of branches never conflicts.
- **Every API call** carries `x-gbox-actor: agent`. The token is `system/gbox-data/api_token`; never print it.
- **Live tests on the Switch titles run only in MercMode's own blocks.** MercMode plays 5-round blocks per title,
  only on sessions with `agent_owned: true` whose launch actor is not `operator`.
  - You may read a live session from the i9 with GET only: `GET /api/mercmode` (host lilspark, `current_run`),
    `GET /api/sessions/{sid}/interventions`, `GET /api/sessions/{sid}/frame.jpg` and
    `GET /api/autoplay/telemetry/{sid}`.
  - Anything else on lilspark is a request in the lane log, in the request format in section 3: a merge and deploy,
    a `gbox.service` restart, a turn on a title, or a probe fired.
  - The RE session fires the probe. Or it answers with a session id and a window, and then you may POST that one
    named intervention from the i9.
- **The NCE code rule.** Citron and Eden run the guest natively on the Spark, and the Spark's cores have no
  instruction-cache coherency (`CTR_EL0 = 0x9444C004`: DIC = 0, IminLine = 64 bytes).
  - Never rewrite an instruction the game has executed.
  - Install code only into **never-executed zero padding**, through the code segment's backing file (the HostMemory
    memfd; `re6_switch_native.Controller.install`).
  - Start every image on a fresh 64-byte line that holds no executed instruction. All of today's images do:
    RE6 `0x18F2640`, RE5 `0x118E600`.
  - Reach the code through **data**: one aligned vtable-pointer store, as `attach()` does. Never through a patched
    branch.
  - RE4's loadout code patch broke this rule, and every stage load hung (`Unhandled NCE prefetch abort: pc=0x0`).
- **Credit.** Work in small, finished steps. Write each one to the lane log
  (`system/docs/ds-grenade-ring-lane-2026-11-10.md` on your branch) before starting the next.
- **Tests.** No new failures. Run from `<worktree>/system`, with `PYTHONPATH="<worktree>/system;<worktree>/system/tests"`
  (the RE5 scatter tests import `test_re5_class_pair`). Known red on main, not yours:
  - 11 in `test_re5_switch_(bonus, bonus_giveup, rampage, smooth, threat)`;
  - 3 RE6 (2 in `test_re6_magnum_quick4`, 1 sniper in `test_re56_weapon_controls`);
  - the 4 in `test_pso_steering_evidence.py`.

## 1. Where the lane stands (checked 2026-11-10 ~13:55 CST)

**Since 12:00 the lane worked offline on the i9 only.** Today the i9's control plane shows PSO sessions and jobs
only; its last Switch job is from 11-09, and none of its jobs is a grenade one. No grenade code reached main since the
merge of `ds-grenade-ring-20261110`. Every later step is on an unmerged branch, and none has a live receipt.

| Item | State | Branch / commit | Evidence |
|---|---|---|---|
| Honest per-kind status (pkg 1) | **done, live** | main (`ds-grenade-ring-20261110` merged) | lane log, 07:34 read on RE6 session `3353e106…-ae42844f…`: three per-kind rows |
| RE5 flash ring | **done, live** | main | session `cbbcdba7…-fb4707a2…`, request `f077980c…`: 10/10 detonated, 1.05 s, hp 916 -> 916 |
| RE6 flash ring | built, **no live receipt yet** | main | unit tests only; the lane log's "still missing 1" is still open |
| RE6 status bug (stale base) | fixed per the hand-off (`re6-bomb-mind`) | main | hand-off section 1; no live RE6 session at 13:55 to re-read |
| Bot's own ring rule (pkg 5) | live on main | `grenade_ring.py` | RE5/RE6 `RING=True`, every 20 s, kind flash |
| RE6 scatter barrage, flash only | live on main (RE session's lane) | `re6-bomb-mind` | `SCATTER=True`, every 12 s, 8 rounds |
| **A** RE6 hand + incendiary | **static done**, live open | `ds-re6-bomb-classes-20261110` `1ec0bfe9` | class pair derived from the pinned images (two words each); caves `0x18F2BC0`/`0x18F2CC0` PASS `scripts/verify_re6_classes.py` |
| A' RE6 explosive ring floor | static done | `ds-re6-ring-explosive-floor-20261110` `2a0ff081` (stacked on B) | `RING_EXPLOSIVE_CLEAR_CM = 600` in `grenade_ring` only (see checkpoint 0.2) |
| **B** RE6 launcher rounds | **tables pinned, blocked** | `ds-re6-launcher-shells-20261110` `226c985b` | uWp1302-1304 / items 0x133-0x135 pinned; the detonate wrapper refuses a shell (action object vs `0x288C9A0`) |
| **C** RE5 hand + incendiary | **static done**, live open | `ds-re5-classes-20261110` `ac5b396f`, `ds-re5-classes-pair-20261110` `7dc50b31` | uWp06 hand `+0x1D714C8`, uWp07 incendiary `+0x1D71500`, uWp08 flash `+0x1D71538` (matches the live flash); pair **installed in place** (see checkpoint 0.1) |
| C' RE5 explosive ring floor | static done | `ds-re5-ring-explosive-floor-20261110` `11cb05a2` | same 600 cm, ring only |
| **D** RE5 scatter barrage (pkg 6) | **static done, needs a revision** | `ds-re5-scatter-20261110` `a03fa8f5` | op, rule, knobs, 7 tests; conflicts with the RE5 flash cap (see D) |
| **E** RE4 native call harness | not started | - | blocked on an ARM64 toolchain decision (lane handover) |
| **F** RE4 flash op | not started | - | needs E |
| **G** RE4 ring and barrage | not started | - | needs E and F |
| Handover note | doc only | `ds-grenade-handover-20261110` `ceec7da8` | the merge order and the probe requests |

**Checked by the RE session at this point:**
- Every branch merges into `8032491f` without a code conflict. Merged together (the RE6 tip, then RE5 scatter, RE5
  floor and the handover), only the lane log conflicts: three append-against-append hunks.
- On that combined tree, these 12 files gave **163 passed**: `test_re6_class_images`, `test_re5_class_pair`,
  `test_re5_class_table`, `test_re5_scatter`, `test_re6_grenade_ring`, `test_re5_grenade_ring`,
  `test_mercs_grenade_status`, `test_mercs_grenade_ring`, `test_re6_native_build`, `test_merc_interventions`,
  `test_intervention_worker` and `test_re5_switch_native`.
- `test_bot_logic`, `test_re5_switch_ss_campaign` and `test_mercs_engine` gave **37 passed**.

**Three defects found in the check.** They must be fixed before any live probe (checkpoint 0):
1. **The probe route places explosive rounds at 300 cm.** The intervention worker calls
   `ctl.grenade_scatter(kind)` with no `safe_cm` (`interventions.py` around line 529). Both titles'
   `grenade_scatter` then put an explicit hand / incendiary round at `near = max(250, SCATTER_MIN_CM) = 300 cm`. The
   600 cm floor went into `grenade_ring` only. The hand / incendiary probes that the handover asks the RE session to
   fire would therefore land inside his own blast, and the first receipt would be a self-damage one. That is the
   failure round 51 was written to prevent.
2. **The RE5 in-place pair takes RE5's native controller down on a running emulator.** `attach()` installs every
   `CODE` image, and `install()` refuses non-zero bytes ("native code padding is occupied"). It has to: those bytes
   are executed code.
   - After the merge, the 15-minute auto-deploy hot-reloads `re5_switch_native` before any restart. From then on,
     any RE5 emulator that already ran the old `spawn` / `explode` refuses the flash, the ring and the `weapons`
     image until it restarts.
   - On RE5 that is the doctrine's flash, the mine flashes and the critical flash.
3. **The RE5 scatter undoes the operator's flash cap.** Main's 13:05 / 13:08 commits hold RE5 to one flash a minute
   (`re5_switch.FLASH_MIN_GAP_S`, a sidebar slider). `ds-re5-scatter` puts RE5 into `SCATTER_TITLES` with
   `SCATTER=True`, and its random kinds are the verified ones, which is the flash only. So every automatic barrage is
   a cone of 8 flashes, every `SCATTER_EVERY_S`, and the rule never looks at the flash clock.

## 2. The checkpoints, in order

Each checkpoint gives its goal, the steps, the acceptance (what counts as done), the evidence for the lane log, and the
fallback if it is blocked. "Receipt" means the intervention row read back from `GET /api/sessions/{sid}/interventions`:
`state`, `detonated` / `requested`, `rounds[]` (each with `class_vtable`, `pos`, `dist_cm`), hp before and after,
`self_damage`, `effect`, `probe`. Collect frames with `GET /api/sessions/{sid}/frame.jpg` before and after, and the
round's kills and score from `GET /api/autoplay/telemetry/{sid}` before and after.

### Checkpoint 0: make the pushed work safe to merge, then get it live

**Goal.** One branch the RE session can merge and deploy in a single gap, without breaking anything that works live
now.

**Steps (yours).**
- **0.1 RE5: tolerate the old pair.** In `re5_switch_native.py`, before `attach()` installs anything, read the bytes
  at `0x118E820` and `0x118E9D0`:
  - If they are the old shipped `spawn` / `explode` (`IMAGES["spawn"]` / `IMAGES["explode"]` in
    `native/re5_ebffdb22/code.py`, the digests the class pair replaced), attach with the old `CODE` table and run the
    flash with the old call shape: DTI and vtable are compiled in, no item or update arguments.
  - On such an emulator, answer `hand` / `incendiary` `Unavailable`: "this emulator runs the pre-class pair; the next
    emulator gets it".
  - Zero caves get the class pair, as now. Never write over the old bytes.
  - Tests: a fake emulator holding the old pair confirms the flash through the old shape and refuses hand with that
    reason; a zero cave installs the class pair; an emulator holding any other bytes still refuses everything.
- **0.2 The explosive floor in the scatter, both titles.** In `re6_switch_native.grenade_scatter` and
  `re5_switch_native.grenade_scatter`, set
  `near = lo if this == "flash" else max(lo, RING_EXPLOSIVE_CLEAR_CM, float(safe_cm or 0.0) + SCATTER_SAFE_CM)`.
  If `hi` is below that, raise `hi` to it as well. Report the floor in the receipt (`floor_cm`). Tests: an explicit
  `kind="hand"` scatter with no `safe_cm` places every round at 600 cm or more, on both titles.
- **0.3 The flash floor in the scatter, both titles** (the operator: "never let the bot get stunned by their own
  flash grenades"). Flash rounds start at `FLASH_PLACE_MIN_CM` from him: the title module's value when it has one
  (`mercs-aim-book` adds 400 cm on RE5), else 400 cm, instead of 300. Test: a random (flash) barrage has no round
  under 400 cm.
- **0.4 RE5's automatic barrage off by default.** On `ds-re5-scatter`, set `re5_switch.SCATTER = False`.
  - The intervention op stays: the capability is advertised whenever the controller has `grenade_scatter`. So the
    probe route works, and the operator's button works.
  - Checkpoint D turns the automatic barrage back on, under the flash cap.
- **0.5 The integration branch.** `git worktree add <dir> -b ds-grenade-merge-20261110 origin/main`, then merge in
  this order:
  1. `ds-re6-ring-explosive-floor-20261110` (it contains the RE6 classes and the launcher shells);
  2. `ds-re5-scatter-20261110` (it contains the RE5 classes and the class pair);
  3. `ds-re5-ring-explosive-floor-20261110`;
  4. `ds-grenade-handover-20261110`.

  Resolve the lane log once, keeping every section in time order. Commit 0.1-0.4 on top. Run the 12 files listed in
  section 1 plus `test_bot_logic`, `test_re5_switch_ss_campaign` and `test_mercs_engine`. Push the branch.
- **0.6 Ask in the lane log:** merge `ds-grenade-merge-20261110 @ <commit>`, then restart `gbox.service` in the same
  gap. The new `classes.py` modules load only at start, and a restart gives every RE5 emulator the class pair. Add:
  "after the restart, read RE5 and RE6 interventions status once; fire one RE5 flash".

**Acceptance.**
- The RE session's merge commit is on main.
- After the restart, `GET .../interventions` on an RE5 and on an RE6 MercMode session shows `flash` available and
  `hand` / `incendiary` unavailable with the "no live receipt yet" reasons.
- One RE5 flash confirms after the deploy (doctrine stat `crit_flashes` / `mine_flashes`, or a PiP flash receipt).

**Evidence.** Branch and commit; the test files with passed / failed counts against the known-red list; the RE
session's merge hash; the two status reads after the restart; the RE5 flash receipt.

**Fallback.** If the RE session wants the titles apart: RE6 first (`ds-re6-ring-explosive-floor` plus 0.2 and 0.3
for RE6; it installs into new caves, so it is no risk to a running emulator), then RE5 once 0.1 is in. Without 0.1,
RE5 is merged only together with a restart, never on the cron.

### Checkpoint A: RE6 hand and incendiary, live

**Goal.** A confirmed receipt per kind, then both kinds advertised in the PiP and drawn by the barrage. The bomb,
detonator and QTE hooks stay as they are.

**Steps.**
- **A0 (for the record).** One RE6 flash `grenade_ring` receipt. The lane log still owes it, and its geometry is
  what the hand / incendiary rings reuse.
- **A1 Pick a round whose character carries the kind.** RE6 refuses a class whose resources are not loaded ("hand
  resources are not loaded for this character").
  - From `re6_switch_mods.LOADOUTS`: hand `0x113` is in loadouts `0x0002` and `0x1006`; incendiary `0x114` is in
    `0x1001` and `0x0006`.
  - Read the live inventory without writing, either through the RE6 mods status / live-controls read the lane used
    at 07:34, or by asking the RE session which character is up.
  - A refusal for resources is a real result. Record it and wait for a matching character; don't retry blind.
- **A2 The probe (after checkpoint 0 is live).** Ask in the lane log:
  `POST /api/sessions/{sid}/interventions` with `{"op": "grenade_scatter", "request_id": "<new uuid>", "args":
  {"kind": "hand"}}`, then the same with `"incendiary"`, on the RE6 block, with the header `x-gbox-actor: agent`.
- **A3 Advertise each kind that passes.**
  - Add the kind to `re6_switch_native.RING_VERIFIED_KINDS` and update the "advertised kinds" tests.
    `grenade_status` and `SCATTER_KINDS` follow from that constant.
  - **In the same commit,** make the random barrage draw only the verified kinds **whose resources are loaded for
    this character**. Today the random path checks every kind in `SCATTER_KINDS`, so adding `hand` would make every
    random barrage refuse for any character without hand grenades, flash carriers included.
  - Report per-character availability in `grenade_kinds()` the same way.
  - Tests: a character with flash only still barrages; one with flash and hand draws both.

**Acceptance, per kind.**
- `state: confirmed` and `probe: true`;
- `detonated == requested`;
- every `rounds[].class_vtable` equals the module base plus the kind's vtable: hand `0x284B788`, incendiary
  `0x284B328`;
- every `dist_cm >= 600`;
- `self_damage: 0` (hp before equals hp after);
- frames that show the effect: a blast for the hand grenade, a fire pool for the incendiary;
- the kill delta (at least one receipt with enemies in the cone).

**Evidence.** Session id, title, character and build; request ids; the receipt JSON; frames; kills before and after;
the A3 commit with its tests.

**Fallback.**
- `failed` or `uncertain` from the detonate wrapper: the class pair passed the allocation's own vtable, so check that
  the wrapper's action check (words 30-36, bomb action class `0x288C9A0`) holds for uWp1091 / uWp1093. They are
  uWpBomb children, so it should. Record the reason and fix that before trying again.
- No matching character for a whole block: ask the RE session in the lane log which RE6 cast slot carries the item.
  Don't ask for the queue to change.

### Checkpoint B: RE6 launcher rounds in the barrage

**Goal.** The operator's "a rapid barrage of random grenades from the grenade launcher without equipping it": real
launcher shells among `grenade_scatter`'s random kinds.

**State.** The tables are pinned (`SHELLS`, `LAUNCHERS`, `LAUNCHER_ROUNDS` in `native/re6_061d2a06/classes.py`). The
bomb wrapper cannot explode a shell, because a shell carries the launcher's action object.

**Steps (offline, on the i9).**
- **B1 The launcher's fire function.**
  - In the update's `main` (build `061D2A06…`), scan for `adrp x1` + `add x1` resolving to a shell DTI (`0x2952098`,
    `0x29520D0`, `0x2952108`), followed by `bl 0x3BCF90`. That is `CREATE_ITEM`, the constructor `spawn.c` already
    calls.
  - The function that holds it is the shell spawn. Its caller in uWp1080's vtable (DTI `0x2951260`) is the fire.
  - Record the arguments: owner, start position, the direction / velocity vector, and the launch or init call that
    follows.
  - Tools: capstone (already a research dependency), `gbox/mercs/re6_dti_emu.py`, and Ghidra on the i9.
- **B2 How a shell explodes.**
  - From uWpShellLauncher's vtable (DTI `0x2950B98`), find the hit / update path and the action class it switches to
    on impact.
  - Then choose one design:
    - (a) `spawn_shell`: create the shell with a velocity toward the threat and let its own impact explode it; or
    - (b) `spawn_shell` at the point plus `detonate_shell`: request its explosion like `detonate.c` does, checking the
      shell's action class in place of `0x288C9A0`.
- **B3 The images.**
  - Put them in new zero padding **after `0x18F2DA8`**, the end of the class caves, on a 64-byte line.
  - Vet them with the checks in `scripts/verify_re6_classes.py`, pin their digests, and write tests on a fake emulator,
    as in `test_re6_class_images.py`.
  - Caution: `build.sh` links `spawn_bomb`'s `.rodata` at `0x18F2BC0`. It is empty today: the image is 232 bytes and
    ends at `0x18F2BA8`. Never rebuild `spawn_bomb` with constants while the class caves sit there.
- **B4 Explicit probe kinds first.** Add the shells to `grenade_scatter` as explicit probe kinds, with the same
  600 cm floor. Each joins the random kinds only after its receipt.

**Acceptance, per shell.** A confirmed probe receipt; `detonated == requested`; every `dist_cm >= 600`;
`self_damage: 0`; frames that show the shell's own effect; the kill delta. Then the random barrage, with a shell
among its rounds, confirms on a live round.

**Evidence.** The B1 / B2 addresses with their disassembly in `docs/research/re6-weapon-dti-tree.md`; the images'
digests; the tests; the receipts.

**Fallback.**
- If the fire's arguments cannot be settled statically, ask the RE session in the lane log for a read-only capture
  during an RE6 round whose character carries the grenade launcher. `0x112` is in loadouts `0x1004` and `0x0206`, and
  the arsenal swap (`re6_switch.py`, "weapon_swap hook") can put it in his hands. The capture: the shell object's
  fields right after one real shot.
- If the launcher path stays out of reach, the barrage's random kinds are hand / incendiary / flash. The task doc
  allows that: "else the hand / incendiary / flash grenades". Say so in the lane log, and say why.

### Checkpoint C: RE5 hand and incendiary, live

**Goal.** A confirmed receipt per kind on RE5, then both advertised.

**State.** The classes are derived from the game's own MtDTI initialiser and cross-checked: uWp08 equals the live
flash DTI. The class pair takes DTI x2, vtable x4, item w5 and update x6. **The one unconfirmed choice** is the update
function for hand / incendiary: `0x806B80`, the bomb base update.

**Steps.**
- **C1 Precondition.** Checkpoint 0 is live, and the RE5 emulator was started after the restart. With 0.1 in, an older
  emulator answers "pre-class pair" instead of failing.
- **C2 The probe.** Ask in the lane log, for the RE5 block: `grenade_scatter` with `kind=hand`, then
  `kind=incendiary`. The body is as in A2.
- **C3 Advertise.** Add each kind that passes to `re5_switch_native.RING_VERIFIED_KINDS`, with its tests.

**Acceptance, per kind.**
- `confirmed` and `probe: true`;
- `detonated == requested`;
- `rounds[].class_vtable` is the same value on every round, and is not the flash vtable `+0x1C5EF58`;
- every `dist_cm >= 600`;
- `self_damage: 0`;
- frames that show a blast (hand) or fire (incendiary);
- the kill delta.

**Evidence.** As for A, plus the class vtable each kind carried. Write those into
`native/re5_ebffdb22/classes.py` as measured values.

**Fallback.**
- `uncertain` or `failed` with `0x806B80`: the update is the likely cause. Read the update slot of the allocation's
  own vtable (the flash's `0x820E50` sits in a known slot of uWp08's vtable; take the same slot in uWp06's and
  uWp07's). Pass that, and probe again.
- Two failed probes on one kind: stop and write it up. Don't spend credit on blind retries.

### Checkpoint D: the RE5 scatter barrage under the flash cap (package 6)

**Goal.** The barrage on RE5 "whenever the going gets tough", without breaking "one flash a minute"
(`FLASH_MIN_GAP_S`, the sidebar slider).

**State.** The op, the cone, the receipt and the knobs are built (`a03fa8f5`). Checkpoint 0 turned the automatic
barrage off.

**Steps.**
- **D1 One flash clock.** The `mercs-aim-book` agent (section 4) makes `stats["native_flash_confirmed_at"]` the clock
  every RE5 flash rule reads, and puts the ring under `FLASH_MIN_GAP_S`. Put the scatter on that same clock:
  - `scatter_policy` reads the title's `FLASH_MIN_GAP_S`;
  - `decide_scatter` refuses a barrage whose kinds would all be flash while the gap is closed. Once hand or
    incendiary is verified, the random draw leaves the flash out inside the gap instead;
  - `fire_scatter` stamps `native_flash_confirmed_at` when any flash round confirms. So does an operator click on the
    op, so his own rules wait a minute after it.

  Build D on main **after** `mercs-aim-book` merges. Both lanes edit `grenade_ring.policy()`, so if it has not merged
  by the time you get here, keep your gate in its own function and leave `policy()` alone.
- **D2 On again.** Set `re5_switch.SCATTER = True` once D1 is in.
- **D3 A live barrage,** clicked or automatic, on an RE5 round.

**Acceptance.**
- The receipt is `confirmed` with `detonated == requested`, every flash round at 400 cm or more and every explosive
  round at 600 cm or more, `self_damage: 0`, frames, and the kill delta.
- Over a full RE5 block, the stats show `scatters_fired`, `scatter_rounds` and `scatter_kills`, and **no two flashes
  of any source closer together than `FLASH_MIN_GAP_S`**. Compare the confirmed-flash times in the telemetry.
- Tests: a flash-only barrage inside the gap is refused with its reason; a stamped clock holds the title's own
  `_native_flash`.

**Evidence.** The block's telemetry extract (flash times and the scatter counters), one receipt with frames, the
commit, the tests.

**Fallback.** Until a non-flash kind is verified on RE5 (checkpoint C), the automatic barrage is a flash cone and the
cap allows one a minute. If the RE session judges that not worth having, leave `SCATTER = False` and keep the op for
clicks. Say so in the lane log.

### Checkpoint E: an RE4 Switch native call harness

**Goal.** A `re4_switch_native.Controller`: install, attach, call, mailbox, read-back, and the "Uncertain" recovery.
It is a subclass of `re6_switch_native.Controller`'s primitives, as `re5_switch_native` is, and it never rewrites an
executed instruction.

RE4 is build `82C2A04A21D3E0B850F273D4149C9003` (`re4_switch.BUILD_ID`). It runs on Citron, NCE, single-core, guest
address equal to host address. Its positions are in **millimetres**.

**Steps.**
- **E0 Tooling (the blocker the lane named).** Ask in the lane log for one of these:
  - (a) WSL2 Ubuntu on the i9, with `gcc-aarch64-linux-gnu`, `binutils-aarch64-linux-gnu`, `clang` and `qemu-user`.
    The existing `build.sh` scripts run unchanged, and the ABI tests run under `qemu-aarch64 -L /usr/aarch64-linux-gnu`.
  - (b) LLVM for Windows (clang, ld.lld, llvm-objcopy) for building, plus the Python `unicorn` package to run the
    `test_*.c` contracts against a fake memory map.
  - (c) No toolchain: hand-encode words as the RE5 / RE6 class work did, check each by capstone round trip, and run
    them under `unicorn`. It needs only pip and is slower.

  Installing (a) or (b) on the i9 is the operator's call, through the RE session. (c) needs no decision, so start E1
  while you wait.
- **E1 Static proof, offline.**
  - Extract RE4's `main` the way the lane did for RE6: `python -m gbox.switch_extract exefs` plus
    `hactool -t nso --uncompressed`. Check `MAIN_NSO_SHA256`.
  - Find the `.text` tail's zero run. Choose the cave on a fresh 64-byte line (better, a 4 KiB page start) that holds
    no executed instruction.
  - Prove that no B / BL / ADR / ADRP+ADD target and no 64-bit literal points into it. Port the scanner to
    `scripts/verify_re4_caves.py` and write a test.
- **E2 The trigger, by data.** RE5 already works this way: `re5_switch_native.Controller.attach` installs a clone of
  the player object's vtable (at `TEMP`) whose `+0x60` slot is the dispatcher, then stores the clone's address into
  the player object. That one store is the whole trigger.
  - On RE4, the player unit (class `0xB0C0A0` or `0xB09A60`, through `S_PLAYER` / `S_PLAYER_2`) carries its vtable
    pointer at `+0`.
  - Find the slot the unit manager calls every frame, and build a clone vtable with that slot pointing at the
    dispatcher. The clone is only ever read, so it can live in the cave.
  - The trigger is one aligned 8-byte store of the object's vtable pointer. The restore puts the original back.
- **E3 Private storage.** RE4 is not MT Framework, so the RE5 / RE6 bootstrap's allocator (`ALLOC_FLAGS` /
  `ALLOC_TABLE`) does not port. Either find RE4's own allocator, or prove a `.bss` range unused: no references to it
  in `.text`, and zero across three stage loads (ask for a read-only watch). The cave itself is not writable by the
  guest.
- **E4 The code rule in code.** The controller's write helper refuses any target inside `main`'s `.text` / `.rodata`
  except `install()` into the verified zero cave. Write a test for that.
- **E5 Offline tests** on a fake emulator, as in `test_re6_class_images.py`:
  - install refuses non-zero bytes and a cave with a reference into it;
  - attach writes only the vtable pointer;
  - a mailbox publish is consumed once, under the generation guard;
  - a timeout is `Uncertain` and never replayed.
- **E6 Live proof** (the RE session runs it, on the RE4 block, after your branch is merged). A no-op call: the
  dispatcher returns a magic word through the mailbox. Ask for a read-only check that the cave lies in the HostMemory
  backing mapping (`/proc/<pid>/maps`). If it does not, `install()` refuses "ambiguous guest backing file", and that
  answer is the result.

**Acceptance.**
- The no-op call's magic word reads back;
- the round goes on;
- three stage loads (round restarts) with the harness attached, with no hang and no `Unhandled NCE prefetch abort`
  in the Citron log;
- frames before and after.

**Evidence.** The cave and trigger addresses with their scans; the tests; the RE session's live note with the Citron
log excerpt.

**Fallback.** If Citron's code segment has no HostMemory backing file, or the trigger needs an executed instruction
changed, **stop**. No other code-write route is acceptable: the `/proc/<pid>/mem` alias is the one that hung. Report
it, and RE4 keeps fire and mines in the doctrine.

### Checkpoint F: the RE4 flash, offered to the doctrine

**Goal.** A controller op the doctrine can call, like RE5's flash. About half of RE4's threat ticks go unanswered for
want of a flash (`threat_lacks_flash`).

**Steps.**
- **F1 Check the anchors.** Run `re4_switch_blasts.verify(main_bin)` against the extracted image
  (`tests/test_re4_switch_blasts.py`) and confirm the anchors from `docs/research/re4-switch-grenade-flash.md` (#9436).
- **F2 The op** `Controller.flash_at(x, y, z)`, on the game thread through the harness, by one of two routes:
  - (i) the flash blast `0x2E4E50` with a zeroed fake object: position at `+0xA4`, and `+0x3CC` not `0xD6` so the
    ground / type check does not skip the effects; or
  - (ii) the parts directly:
    - `EFFECT 0x1F7DC0` with ids `0x3F` and `0x0C`;
    - `SOUND 0x261C20` with id `0x13`;
    - `AREA_ATTACK 0x33B770` with class `0x17` and radius `15000.0` from `0x6E8A74`, at pos.y + 500.

  Put the module function `flash_now(ad)` beside it, and add the capability in `interventions.py`.
- **F3 Where it goes off: on the crowd, never at his feet** (the operator, and `mercs-aim-book`'s design).
  - The point comes from `core.flash_window.place()` once that merges, converted to mm: min 4000, max 9000, from 12000.
  - Until then, use the nearest crowd's centre pushed out to 4000 mm.
- **F4 Status.** The RE4 flash row in `grenade_status` goes to built; to verified after the receipt.
- **F5 Tell the RE session in the lane log** that the op exists. The doctrine change is theirs and one line:
  `re4_switch.py` around line 1890, `respond.Kit(fire=fire, flash=None, …)` gets the RE4 flash ask.

**Acceptance.**
- A live receipt, `state: confirmed`;
- one or more Ganados within 15 m change to their flash-stun state: record their motion / state ids before and after;
- Leon's hp is unchanged and Leon is not stunned;
- frames show the bloom;
- three flashes across a stage load with no hang.
- After the Kit change, RE4's `threat_lacks_flash` stops climbing (the RE session reads it).

**Fallback.** If (i) runs but nothing reels, try (ii). If (ii)'s area attack hits nothing, the blast also needs the
game flags (`game+0x5090 |= 0x800000`, `game+0x5094 |= 0x20000000`, pos at `+0x4FA4`): find the game object pointer
first.

### Checkpoint G: the RE4 ring and barrage

**Goal.** `grenade_ring` and `grenade_scatter` on RE4, with the same contracts and receipts as RE5 and RE6.

**Steps.**
- **G1 The flash ring:** N `flash_at` points round him, the inner ring at 4000 mm or more.
- **G2 The hand-grenade ring:** the blast `0x2E48B0`, class `0x13`, radius 6000 mm. Its floor is 7000 mm or more,
  and past the learned reach.
- **G3 The incendiary** (item `0x02`) has no blast entry yet. Find it the way #9436 found the other two, then add it.
- **G4 The barrage.** Add `010099A00BC1E000` to `SCATTER_TITLES`, and add `SCATTER`, `SCATTER_EVERY_S` and
  `SCATTER_N` to `re4_switch.py` with their PiP rows. The shared rule works in cm; convert at the controller
  boundary with `re4_switch`'s `MM_PER_CM`.

**Acceptance, per kind, live.** `detonated == requested`; the smallest distance at or above the floor;
`self_damage: 0`; frames; the kill delta.

**Fallback.** Ship the kinds that pass. Each kind that does not stays refused in `grenade_status` with its reason.

### Checkpoint H (only after `mercs-aim-book` merges, and only if the RE session hands it over): RE6 flash on the crowd

The aim-book work places RE5's flashes on the crowd. RE6 has no such placement yet: its flash ring's inner ring is
150 cm and its scatter's flash floor is 300 cm (400 after checkpoint 0.3).

The RE6 counterpart:
- `re6_switch_native.Controller.flash_at(x, y, z)`, the same `_ring_one` step as one grenade;
- `FLASH_PLACE` / `FLASH_PLACE_MIN_CM` in `re6_switch.py`;
- the ring policy's inner floor, which reads `FLASH_PLACE_MIN_CM` once aim-book is in.

Acceptance: a live RE6 `flash_at` receipt at 400 cm or more, the player's hp unchanged and no stun on him, and
frames.

## 3. How to ask, and how to report

**A request** (append it to the lane log on your branch, push, and wait):

    ## REQUEST <hh:mm CST> - <one line>
    - needs: merge <branch> @ <commit> | gbox.service restart | <title> block | probe fired
    - exact call: POST /api/sessions/{sid}/interventions  {"op": ..., "request_id": "<uuid>", "args": {...}}
    - precondition: <character / inventory / emulator started after the restart>
    - record: receipt fields, frames before/after, kills before/after

**A checkpoint result** (one section each):

    ## CP <x> - <kind> - confirmed | refused | uncertain | static only (<hh:mm CST>)
    - session <sid> (title, character, build), request <id>
    - receipt: state, detonated/requested, class_vtable, min dist_cm, hp before/after, self_damage
    - frames: <paths>; kills <before> -> <after>
    - branch / commit; tests: <files> <passed>/<failed> vs the known-red list
    - still missing, and why

A refused or uncertain receipt is a result. Write it down with its reason before you change anything.

## 4. The `mercs-aim-book` agent's flash work, and what it changes here

The RE session's `mercs-aim-book` agent works on JAYBUILTFINALE (worktree `gBox-wt-aimbook`). At 13:55 nothing of it
was pushed; it is uncommitted on a base of `2ce14d78`. It answers the operator's 2026-11-10 asks: "never let the bot
get stunned by their own flash grenades", "use that time to plan mines and throw grenades and clear the crowd", and
"only be able to flashbang once a minute or on a slider".

**What it adds:**
- `core/flash_window.py`:
  - `place()` puts a flash on the crowd, pushed out to `min_cm` from him;
  - `Window.plan()` names the step for each tick of the reel, in order: mine, then throw, then move, then fire.
- `core/aim_book.py`.
- `re5_switch_native.Controller.flash_at(x, y, z)`: one verified flash moved onto a point through
  `_ring_one(x, y, z, 0)`, refused nearer than 250 cm.
- In `re5_switch.py`:
  - `FLASH_PLACE = True`;
  - `FLASH_PLACE_MIN_CM` / `MAX` / `FROM` = 400 / 900 / 1200;
  - `FLASH_WINDOW = True` and `FLASH_WINDOW_S = 3.5`;
  - one flash clock, `stats["native_flash_confirmed_at"]`, which the title's own rules read through
    `_flashed_lately`.
- In `grenade_ring.py`, for the flash ring:
  - `policy()` reads `FLASH_MIN_GAP_S` and lifts `inner_cm` to `FLASH_PLACE_MIN_CM`;
  - `decide()` refuses a flash ring inside the gap;
  - `fire()` stamps the clock after a flash ring.
- It does not touch the scatter rule, RE6's flash placement or RE4.

**What that means for this lane:**
- **Keep `_ring_one`'s signature.** Aim-book calls `_ring_one(x, y, z, 0)`. The class branch's
  `_ring_one(x, y, z, index, kind="flash")` is compatible; keep `kind` last and defaulted.
- **Every flash you spawn goes off at least 4 m from him,** in rings and barrages, on RE5 and RE6 (checkpoint 0.3,
  checkpoint H), and on RE4 (`flash_at` on the crowd, 4000 mm; checkpoint F).
- **Every RE5 flash you fire is on the one clock.** Read `FLASH_MIN_GAP_S`, stamp `native_flash_confirmed_at`
  (checkpoint D).
- **Coordinate edits to `grenade_ring.policy()`.** Both lanes change it. Base D and H on main after aim-book merges.
- **Later.** Once hand grenades are verified on RE5 (checkpoint C), the flash window's "throw a grenade at the stunned
  pack" step could use a native hand-grenade cone at the reeling crowd (`grenade_scatter(kind="hand",
  toward=<stunned>)`) instead of the thrown one. Offer it in the lane log; the RE session decides.

## 5. Order, and what to do while you wait

0 -> A and C (the probes need only checkpoint 0 live) -> D -> B -> E -> F -> G, with H when it is handed over.

Whenever you are waiting on a block or a merge, do the next offline step:
- B1 / B2 (RE6 launcher statics);
- E0 (c), E1, E2 and E5 (the RE4 harness statics and tests);
- F1 (the RE4 anchors).

None of these needs lilspark.
