# DeepSeek grenade-ring lane — 2026-11-10

Lane log for `system/docs/DEEPSEEK-GRENADE-RING-TASK-2026-11-10.md` (the operator: "i need the grenade deployment
feature completed across all titles in full ... and all these titles"). Every claim below is either a test in the
repo or a receipt quoted with its session id.

## Status for the PM (2026-11-10, 07:1x)

**Read with the operator's 07:07 update to `DEEPSEEK-GRENADE-RING-TASK-2026-11-10.md`:** RE6 grenades now belong to
the RE session's `re6-bomb-mind` lane (this lane stops touching them; main's RE6 ring stays as it is until that
branch merges), the "when to ring" rule moves into the now-available `gbox/mercs/core/combat.py`, a **package 6**
(the scatter barrage on RE4/RE5 Switch) was added, and work is to be pushed to a branch, not main - this commit is
the one PM note and then the lane returns to its branch (`ds-grenade-ring-20261110`).

**Landed on main already (via this lane and the PM's universal-core merge):** the honest per-kind status, the RE6
Switch ring (frozen from here), the bot's when-to-ring rule with `rings_deployed`/`ring_kills` and its PiP knobs, the
PiP chooser, and the offline check that the RE6 native pair matches the operator's installed build. Nothing changes
a title bot's decisions outside the ring hook, and the ring is Switch-only.

- **Works and is proven:** RE5 Switch flash ring (live: 10/10 detonated, 1.05 s, no self-damage - receipt below);
  per-kind status on every title (19 tests + live before/after observations); RE6 ring geometry/partial handling and
  the native caves against the real 061D2A06 image (10 + 4 tests); the bot rule (13 tests); the PiP chooser (21 JS
  tests).
- **Open, and why:** package 6 (scatter barrage) not started; the rule still lives in `gbox/mercs/grenade_ring.py`
  and wants moving onto `core/combat.py` per the doc; RE5 hand+incendiary (item DTIs unconfirmed + an ARM64 rebuild);
  the RE4 Switch ring (no native call harness on that title); the 4 failing
  `tests/test_pso_steering_evidence.py` (on this lane's list now); and the RE6 status bug's root cause (RE6 is now
  the other lane's, so handed over with the ready() evidence request noted below).
- **Needs one action:** a `gbox.service` restart at a gap on lilspark (and locally if that node should show the new
  status). Title modules hot-reload; `interventions.py`, `engine.py` and the new modules only load on restart.
- **Conflicts:** the only file two lanes both added is `gbox/mercs/enemy_identity.py`; this lane uses the other
  lane's module (`tier(title, class, hp_max)`) and keeps no table of its own.

## What works now, per title and kind

The ring is ten grenades spawned in a ring around the player that bloom outward and detonate. "Built" means a
native path exists in `gbox/mercs/titles/*`; "verified" means a live ring was observed on lilspark; "refused" means
the PiP says why and the queue refuses the click (nothing is substituted).

| Title | flash | hand | incendiary | Where |
|---|---|---|---|---|
| RE5 Switch (`010018100CD46000`) | **verified live** (this lane, 2026-11-10 05:34) | refused: the native item class/DTI is not known on this build and the compiled spawn image pins the flash DTI at link time | same | `re5_switch_native.Controller.grenade_ring` |
| RE6 Switch (`01002A000CD48000`) | **built this lane** on the live-verified RE6 spawn/detonate pair; live acceptance is the one item still open (below) | refused, same reason | refused, same reason | `re6_switch_native.Controller.grenade_ring` (new) |
| RE4 GameCube (`G4BE08`) | out of scope since the operator's 2026-11-10 "Switch only" update; its existing ring is untouched and the bot's auto-ring does not run on it | - | - | - |
| RE4 Switch (`010099A00BC1E000`) | not built | not built | not built | — |
| RE5 PS3, RE6 PS3, RE4 Wii | out of scope (2026-11-10 "Switch only"); no ring built | - | - | - |
| Mercenaries 3D, RE3 PSX | not built | not built | not built | — |

### RE5 Switch flash ring — live receipt

Session `cbbcdba729dd4c66-fb4707a29b574df9` (lilspark, RE5 No Mercy, Sheva, agent-owned, launch not from the
operator), request `f077980c-edfc-431e-a7cf-c9d931b59614`:

- `confirmed`, `verified: true`, `effect: native_flash_ring`, **detonated 10 / requested 10** in **1.05 s**;
- grenade generations 4164-4173, ring radius 600 cm (inner 150 cm), every position recorded in the receipt;
- **hp 916 -> 916, self_damage 0**;
- frames: `.tmp/evidence/ring-20261110-053408-before.jpg` and `...-after.jpg` (the after frame is the flash bloom
  filling the screen); the round's kill/score counters were 0/0 before and after - a flash stuns, it does not kill,
  and this round had no enemy inside the ring at that moment.
- Evidence JSON: `.tmp/evidence/ring-20261110-053408-flash.json` (local to the Windows box).

This is the same burst the RE5 research doc calls unfinished ("the broader request for 20 grenades in two seconds
remains unfinished"): the 10-grenade ring is now a single op, not twenty clicks.

## 1. An honest status (package 1)

`gbox/mercs/grenade_status.py` is the one authority. It answers with **all three kinds, always**: built and verified
here, refused for this build (with the reason), not built for this title, or verified but not firing right now (no
living player, operator on the pad, a changed build). Three levels of truth, resolved in order:

1. the title table (`TITLES`): which kinds are built and verified where;
2. the live native controller's own `grenade_kinds()` - it may gate a kind on live state (RE4 GameCube's hand
   grenades need its verified unlimited life), and its verdict wins. A kind the table calls verified is **not**
   advertised when no controller exists for the session or its status read fails: a row never becomes a click that
   could not execute;
3. this moment: with no living player, the kinds that would otherwise work carry that reason; a kind refused for
   its own reason keeps it.

Wiring:

- `gbox/mercs/interventions.py`: the worker publishes `options.grenade_kinds` with **every** claim, including when
  no native controller exists; the capability list still gates what can be queued. `GET .../interventions` fills the
  rows from the session record before a worker has ever claimed, so a title with no ring says "the grenade ring is
  not built for RE4 Switch yet" instead of only "worker not connected".
- `system/clients/web/viz/stream-interventions.js`: the chooser shows each kind's own verdict. A kind that says
  available without the `grenade_ring` capability stays disabled ("not ready"), because nothing could execute it.
- `gbox/mcp_server.py`: the `game_intervention` description now points at `status.options.grenade_kinds`.

Two live defects found and fixed on the way:

- **A worker that dies leaves the PiP blind.** Live, 05:09, the RE4 Switch session answered
  `available:false, reason:"worker not connected"` while the round played; a minute later the same session reported
  the joined module refusals. The loop caught only `(httpx.HTTPError, ValueError, OSError)`; anything else (a
  module's own exception type during a claim) ended the thread for the rest of the round. It now survives a fault,
  reports the reason, and still surfaces a fault that never clears (100 in a row) instead of spinning.
- **The RE6 status bug is not yet reproduced with a cause.** See "Still missing" - the status now at least says
  the truth per kind instead of greying everything out with one string.

## 2-4. The rings

- **RE6 Switch (package 4): built.** `re6_switch_native.Controller.grenade_ring` runs the verified spawn
  (`+0x18F2880`) and detonation (`+0x18F29C0`) pair ten times, relocating each projectile's live transform
  (`+0x60`) onto the ring before its explosion - the only step the single live flash never exercised. Partial rings
  are `uncertain` and never replayed, a lost allocation aborts with the evidence, and the receipt carries every
  grenade's generation and position, hp before/after and self-damage. Hand/incendiary are refused with their reason.
- **RE5 hand and incendiary (package 2): not done, and why.** The RE5 spawn image is compiled: `spawn.c` calls
  `CREATE_ITEM(*(void**)S_ITEM, FLASH_DTI, 10, 1, 0)` with `FLASH_DTI` a link-time symbol (`main+0x1D71538`). A
  different grenade needs (a) its own item/DTI address on this build - not identified yet - and (b) a rebuilt
  spawn image with the new symbol, which needs an ARM64 toolchain (this Windows box has none: no clang, no lld, no
  aarch64 binutils) and a new pinned asset checksum. Both are prerequisites, and neither is a Python change.
- **RE4 Switch (package 3): not built, and why.** `re4_switch*` has no native call harness at all (no mailbox, no
  checked-in ARM64 payload), unlike RE5/RE6. A ring there needs the executable's own blast routine identified
  (docs/research/re4-weapons-ram.md and re4-parity.md describe the tables, not a detonate-at-position call) and a
  compiled payload built and verified - the same toolchain gap as above.

## 5. The bot deploys it by itself (package 5)

`gbox/mercs/enemy_identity.py` (new): boss/heavy/normal/unknown tiers from a measured class table and the enemy's
maximum health - never inferred from a class name. `gbox/mercs/grenade_ring.py` (new) is the rule, once for every
title:

- **when to fire**: `>= RING_N` enemies within 4 m (surrounded), any boss/heavy within that range, or a crowd of at
  least `RING_N-2` that has not thinned for 8 s;
- **never inside the learned blast reach**: the ring's radius is `max(radius_cm, bomb_safe_cm + 250 cm)`, and a
  learned reach wider than the native ring's ceiling refuses the ring instead of gambling;
- **at most every `RING_EVERY_S`** (20 s default, 1-600 s bounds), never while the operator has the pad, never
  while the round is not being played (the bot's keys are released first);
- **stats**: `rings_deployed`, `ring_kills` (kills inside the 12 s window after a confirmed ring - an attribution
  window, not proof each kill was the ring's), plus `ring_last_at`, `ring_decision`, `ring_attempted`,
  `ring_error` for the reviewer.

`gbox/mercs/engine.play_round` calls it once per playing tick (`ring_step`), and `re5_switch` / `re6_switch` expose
`RING`, `RING_N`, `RING_EVERY_S`, `RING_KIND` as three new rows in the PiP's bot-logic sidebar ("Grenade ring
(auto)", "Crowd size for the ring", "Seconds between rings"). `gbox/mercs/core/combat.py` is not on main (branch
`mercs-universal-core` has not landed), so the rule lives in its own module with no title-specific logic; when that
core lands, `decide()` is the function to move onto it.

## Commits

- `be21ba0` (branch `ds-grenade-ring-20261110`): the whole lane (status, RE6 ring, bot rule, JS, tests).
- `38740baa`: the merge with the then-current main. Its one conflict was
  `system/gbox/mercs/enemy_identity.py`, added by the enemy-identity lane at the same time; resolved **in favour of
  that lane's module** - the ring's rule calls `enemy_identity.tier(title, class, hp_max)` for boss/dangerous instead
  of keeping its own table, so one enemy identity feeds the tactical map, the bots and this rule.
- `369495c0`: Switch-only gating (the operator's 2026-11-10 update), this lane log, and a clicked ring counted in
  `rings_deployed`/`ring_kills` like the bot's own.
- `76d098fc` (on the branch `ds-grenade-ring-20261110`): the RE6 native-cave verifier and the local-installation
  check (below). It is on main as the cherry-pick `690f1d28` - the branch commit's hash differs because it was
  cherry-picked onto main rather than merged.
- the two PM-note commits (`09cfc9a7`, `f2c7004f`): the status block above, cherry-picked onto main together with
  the verifier.

The branch stays the place for the next round of work; main carries everything shipped so far.

## What the PiP showed before this lane (the observed problem)

Captured live from the deployed server on 2026-11-10, one interventions `GET` per title while a MercMode round
played (receipts under `.tmp/evidence/` on the Windows box, sessions named):

- **RE6 Switch** `5a68e96bfd1447a2-261245764a5f48be`, 04:54: `available: false`, `capabilities: []`, reason
  `no living player in an active Mercenaries round` - every button greyed out with one string, while the run's own
  stats said `mercenaries_phase: 1` with 101 kills. This is the doc's known bug; see "Still missing".
- **RE5 Switch** `cbbcdba729dd4c66-fb4707a29b574df9`, 05:06: `available: true`, caps
  `flash_now/equip_primary/grenade_ring/set_infinite_ammo`, **no `options.grenade_kinds` at all** - the chooser fell
  back to its built-in text ("Hand-grenade ring not yet verified on this build.") rather than the worker's own truth.
- **RE4 Switch** `0254df67bf934b6d-451c1ac27e79452c`, 05:09: `available: false`, reason `worker not connected`, then
  a minute later the joined module refusals - the status was either blind (dead worker) or a paragraph of internals,
  never "the ring is not built for this title".

## The RE6 native pair checked against the operator's own installation (2026-11-10, offline)

The operator pointed this lane at the local RE6 Switch copy: `D:\gBox\cache\115f9cdbba115432\Resident Evil 6
[01002A000CD48000].nsp` (base 1.0.0) plus `Resident Evil 6 [01002A000CD48800][v131072].nsp` (the update). No game
was launched for this; it is file analysis only.

1. `python -m gbox.switch_extract exefs <nsp> <program.nca> <out> --keys \\10.89.1.125\QuickSwap2\Emulation\_switch\prod.keys`
   pulled `main` out of each program NCA; `hactool -t nso --uncompressed=main.bin main` (the repo's
   `system/tools/bin/hactool.exe`) expanded the LZ4 sections.
2. **The installed build is the pinned one.** The base NSP's `main` is build `2A797A895C35383B0C8052BC6E2B281B`;
   the *update's* `main` is **`061D2A06CD700785E987C42CE2D72231`** - exactly `re6_switch.BUILD_ID`.
3. **The ring's caves are still padding on it.** `re6_switch_native.verify_build(main.bin)` (new; a pure function
   with tests in `tests/test_re6_native_build.py`) reports the pinned signature at virtual `0x2151000` and all three
   install targets **pristine zero padding**: `0x18F2640` (call, 536 bytes), `0x18F2880` (spawn, 256), `0x18F29C0`
   (detonate, 232), every one `installable: true`. The same check refuses the base 1.0.0 image by its signature.
   Receipt: `.tmp/evidence/re6-build-verify.json` (local).

So the RE6 ring's native pair is right for this installation; what it needs to *run* is an ARM64 Linux NCE host
(the Spark), because the controller installs into the guest's HostMemory through `/proc` and memfd. This PC
(Windows, yuzu/Dynarmic) cannot execute it by design - hence the local run was not used for the ring itself.

How to repeat: extract the update's `main` as above and run
`python -c "from gbox.mercs.titles import re6_switch_native as N; print(N.verify_build(open('main.bin','rb').read()))"`.

## Tests

New: `tests/test_mercs_grenade_status.py` (19), `tests/test_re6_grenade_ring.py` (10), `tests/test_re6_native_build.py` (4),
`tests/test_mercs_grenade_ring.py` (13), worker/status cases in `tests/test_intervention_worker.py` and
`tests/test_merc_interventions.py`, and the chooser case in `tests/stream-interventions.test.cjs` (21 JS tests pass).

On the merged tree, the engine/interventions/native/RE5-RE6-mod/enemy-identity group is **174 passed, 1 skipped**;
the RE4-RE6 title group is **146 passed, 3 failed** - the same three `test_re6_magnum_quick4.py` failures the
pristine `origin/main` commit shows in the same files (an `mcp` client import problem and a `primary_weapon`
snapshot case), so no new failures come from this lane.

## Still missing, and why

1. **Live acceptance of the RE6 ring.** The code is in and unit-tested; the round windows on lilspark are being
   watched (RE6 No Mercy comes up in the MercMode queue). Nothing is claimed confirmed without the receipt.
2. **The RE6 status bug's cause.** Live on 2026-11-10 the RE6 session's status answered
   `available:false, "no living player in an active Mercenaries round"`; the round's own stats said
   `mercenaries_phase: 1` with a living player. The diagnosis needs the live module base (ASLR: `0x3ca8449000` for
   the RE5 round, not the research doc's `0x3ca7c04000`) - the read-only `re5_mods` `live_controls` job reports it,
   and a watcher is queued to capture the ready() inputs from the next RE6 round. Until then the honest status
   change stands (the reason is shown per kind), but the detection fix is not claimed.
3. **RE5 hand/incendiary** and **RE4 Switch's ring**: native image build + the two item/DTI addresses (RE5) and the
   RE4 Switch blast routine (RE4). Both are RE + ARM64 toolchain work, not reachable from this box.
4. **Tuning from live rounds**: `RING_N`, `RING_EVERY_S` and the blast margin are defaults; they want a few RE6
   and RE5 rounds with the stat counters reviewed.
5. **Deployment**: the title modules hot-reload on the Spark (`gbox_autodeploy.sh`, 15 min); `interventions.py` and
   the new modules need a `gbox.service` restart - **RE session: please restart it at a gap** so the honest status
   and the RE6 ring reach the live sessions.

## Live verification of the honest status (2026-11-10 07:34, after the Spark restart)

The Spark's gBox restarted (worker `3353e106cb7c47bd`) with this lane's main code, and an RE6 No Mercy round was
live. `GET /api/sessions/3353e106cb7c47bd-ae42844f9e324aae/interventions` returned **all three kinds, each with its
own verdict**:

    flash        unavailable  "no living player in an active Mercenaries round"
    hand         unavailable  "a hand-grenade ring is not yet verified on this build (its item class/DTI is unconfirmed)"
    incendiary   unavailable  "an incendiary-grenade ring is not yet verified on this build (its item class/DTI is unconfirmed)"

That is package 1's acceptance on a live title: before this lane the same session answered `capabilities: []` with
one generic string and no per-kind rows at all (the old answer is quoted above).

### The RE6 detection bug, measured

The same round's controller cannot act, but the RAM says it should. Read through the session RPC at the module base
the title's own mods status reported (`0x3ca83da000`, signature verified at `+0x2151000`):

    S_PLAYER  -> 0x5d32ba20f0   player -> 0x5d63f1a0f0   generation 6
    S_GAMEMAN -> 0x5d34af20f0   phase 1 (playing), mode 2 (No Mercy), kills 90
    player hp 900 / 900          position (-3035.5, 500.1, 4822.4)

Every condition `re6_switch_native.Controller.ready()` tests is satisfied, so those exact checks verdict **"ready"** -
yet the worker's own `ready()` raises "no living player in an active Mercenaries round" at the same time (the status
kept that reason while the player read above was taken). Same adapter, same addresses: the worker's controller is
not looking at this session's `main`, and the likeliest cause is a **stale cached base/controller**
(`ad._re6_native_flash` left from an earlier boot) whose `self.base` points at an older image whose `S_GAMEMAN` slot
is zero - exactly the branch that produces this message. Instrumenting it needs a worker code change plus a Spark
deploy, so:

- RE6 grenades are the `re6-bomb-mind` lane's from the operator's 07:07 update; this evidence goes with them;
- the *status* half is fixed and live (above);
- the detection fix is **not** claimed, and the honest per-kind reasons hide nothing until it lands.

## Step: RE5's grenade classes, derived from the game's own initialiser (2026-11-10, branch `ds-re5-classes-20261110`)

Hand-off lane B item 3: "Find RE5 Switch's grenade item classes the way #9437 found RE6's: walk the MtDTI static
initialiser. The tool is `system/gbox/mercs/re6_dti_emu.py`; point it at RE5's main NSO."

**The image.** `python -m gbox.switch_extract exefs` on the share's `Resident Evil 5.nsp` (program NCA
`15af72f2…`) + `hactool -t nso --uncompressed` gives `main.bin`, build **`EBFFDB223149A725A93CD9B60979F6AA`** - the
pinned build `re5_switch.SIGNATURE`/`docs/research/re5-native-flash.md` describe. `.text` 0..0x118F000,
`.rodata` ..0x1A92000, `.rwdata` ..0x1CE5000, `.bss` ..0x26A6000.

**The initialiser.** One long straight-line MtDTI registration block at `main+0x84800..0x84Fxx`: per class it builds
the object in `x0` (`adrp`/`add` into `.bss`), the name string in `x1`, the parent DTI in `x2`, the size in `w3` and
the id in `w4` (`0x07010000 + 0x100 * class`), then calls `main+0xBD28D0`. The grenade family shares the parent
**`uWpBomb` at `main+0x1D71180`**, and its members come out in order:

| kind | class | DTI (main+) | item (id >> 8) | size |
|---|---|---|---|---|
| hand | uWp06 | **0x1D714C8** | 0x106 | 0x28D0 |
| incendiary | uWp07 | **0x1D71500** | 0x107 | 0x28D0 |
| flash | uWp08 | **0x1D71538** | 0x108 | 0x28E0 |

**The cross-check that makes it trustworthy:** uWp08's DTI is `0x1D71538` - exactly the DTI the *live-verified*
native flash already spawns with (`native/re5_ebffdb22/build.sh --defsym=FLASH_DTI=0x1d71538`,
`docs/research/re5-native-flash.md`). The class number is the item, one-based, matching RE6's pattern (uWp1091/93/95/97
= items 0x113/114/115/116) and the item table's hand 0x106 / incendiary 0x107 / flash 0x108. The same run also
derives the rest of the table (uWp00..uWp63, uWpShell, uWpShellCommon) with sizes - useful for the launcher rounds
asked for later.

**What is checked in.** `gbox/mercs/native/re5_ebffdb22/classes.py`: the pinned table, and `derive(image)` - a small
ARM64 emulator for the registration block (w/x register aliasing, adrp/add/mov/movk/bl) - and `verify(image)`, which
compares the pinned table with what the image's own initialiser builds, including the uWp08 cross-check.
`tools/verify_re5_classes.py <main.bin>` runs it. Against the operator's image: **PASS**, no mismatches, the whole
uWp table printed for the record.

**Tests** (`tests/test_re5_class_table.py`, 4): the pinned table; a *synthetic* registration block built in the
game's shape derives the same rows; a moved DTI is reported rather than trusted; the uWp08 cross-check is enforced.
(3 of the 4 need no image at all; capstone is the research dependency, imported only inside `derive`.)

**Ready for the next step, measured now:** RE5's `spawn` image builds the DTI in **x1** at words 12-13
(`adrp x1` + `add x1, #0x538`) - the same two instructions as RE6's, so two NOPs make it a parameter. Its `explode`
image builds `FLASH_VT` in **x4** at words 4-5, so there the *caller's x4* is already the class vtable: NOP the pair
and the wrapper checks the class it was handed. That is the parameterised pair for RE5, in new zero padding vetted
the same way as RE6's; then the controller kinds and the live receipts (RE5's `grenade_scatter` does not exist yet -
package 6 on RE5 is hand-off item 4 - so a small explicit probe op or the scatter op is the receipt route).

## Step: RE5's spawn/explode become class parameters (2026-11-10, branch `ds-re5-classes-pair-20261110`)

Hand-off lane B item 3, second half: the RE5 wrappers now take the class, so hand (uWp06) and incendiary (uWp07)
grenades can use the same live-verified spawn/explode pair as the flash (uWp08). No compiler: every change is the
replacement of a pinned instruction in the verified blob, with the source words asserted first.

| image | word(s) | was | now | argument |
|---|---|---|---|---|
| `spawn` (432 B @ `0x118E820`) | 12-13 | `adrp x1` + `add x1, #0x538` (FLASH_DTI) | `orr x1, xzr, x2` + `nop` | class DTI in **x2** (3rd call arg; x1 already carries the generation) |
| `explode` (248 B @ `0x118E9D0`) | 4-5 | `adrp x4` + `add x4, #0xf58` (FLASH_VT) | `nop` + `nop` | class vtable in **x4** (the allocation's own, read after initialisation) |
| | 47 | `movz w3, #0x108` (the flash item) | `orr w3, wzr, w5` | item id in **w5** |
| | 55 | `bl 0x820E50` (the flash update) | `blr x6` | update in **x6**: `0x820E50` for the flash (verified), **`0x806B80`** for the other uWpBomb classes (the bomb base update the flash's own update calls - the one choice here that the live receipt has to confirm) |

**Where they install - in place, because there is nowhere else.** RE5's `.text` tail is one zero run
`0x118E5B0..0x118F000`, and the four shipped images already fill it (`call`, `spawn`, `explode`, `weapons` end at
`0x118EFFC`); there is no second padding cave as there was on RE6. So the pair replaces the two shipped images at the
same addresses and sizes with their own new pinned digests (`spawn_class` `c288f03f…`, `explode_class`
`c6137b3d…`); the originals keep their pins in `code.py` as the record. `install()` refuses a cave that holds other
bytes, so **an emulator already running the old pair refuses rather than being corrupted**; every new session gets
the parameterised pair. The RE session should re-verify the flash live after this deploys.

**Controller** (`re5_switch_native.py`): the flash passes its verified DTI `0x1D71538`, its vtable is read from the
allocation and checked against `main+0x1C5EF58`, item `0x108`, update `0x820E50`. Hand/incendiary pass their DTI
(`0x1D714C8` / `0x1D71500`), the vtable the allocation carries, their item (`0x106` / `0x107`) and `0x806B80`.
`grenade_ring` takes `allow_unverified` and `grenade_kinds()` still advertises **flash only** -
`RING_IMPLEMENTED_KINDS` names all three.

**Tests** (`tests/test_re5_class_pair.py`, 11): the four replaced words and nothing else changed; a tampered source
image refused instead of patched; the update-offset table; hand vs flash argument pass-through on a fake emulator
(including a vtable the table does not carry, so the wrapper is proven to take the allocation's own); the flash's
verified values and its class check; unverified/unknown refusals; the advertised kinds. The RE5 ring and native
suites' fakes were updated for the pair, and the affected set (RE5 native/ring/class pair/class table, interventions,
worker, grenade status/rule, re5 mods, engine) is **149 passed**.

**Still open on this item:** the live receipts for hand and incendiary. The route is the same explicit-kind probe
RE6 got, and RE5 has no `grenade_scatter` yet (next item 4), so the clean order is: land the RE5 barrage with the
explicit-kind probe (one more step), then fire `kind=hand` and `kind=incendiary` on an RE5 Mercenaries round and
record receipt + frames + self_damage. Until then `grenade_status` keeps advertising flash only, which is honest.

## Step: RE5's scatter barrage - hand-off item 4 (2026-11-10, branch `ds-re5-scatter-20261110`)

Operator 2026-11-10 ~07:00: "i want the bot able to spray a scatter shot of grenades from his postion at threats at
will ... a rapid barrage of random grenades from the grenade launcher without equipping it on his character ... sprayed
like a scatterhsot whenever the going gets tough". RE6 got it this morning (the other lane); this is RE5's.

**`re5_switch_native.Controller.grenade_scatter(kind="random", count, toward, spread_deg, min_cm, max_cm, gap_ms,
safe_cm, rng)`** - the same contract and receipt shape as RE6's: `count` rounds, each the ring's verified native step
(spawn, moved onto its point, the explosion transition), so nothing is equipped and the gun stays in his hand. The cone
follows `toward` ([(x, z)] of the threats, averaged) or his facing when there is none; rounds run near to far within
`SCATTER_SPREAD_DEG` (±30°), about chest height (+120 cm), 100-200 ms apart. `kind="random"` draws from
`SCATTER_KINDS` - the verified kinds only, the flash today; an explicit implemented class (hand/incendiary) is the
**receipt probe** (`probe: true` in the receipt). An explosive kind keeps every point past `safe_cm` (his learned
blast reach) plus a 1 cm epsilon so the sin/cos placement cannot land a hair inside it. A partial barrage is
uncertain and never replayed; the receipt carries every round's position, class vtable, distance, and hp/self-damage.

**The automated rule already existed** (`gbox/mercs/grenade_ring.py`, the other lane's): when the ring's own decision
says no, it runs `decide_scatter` (surrounded, hurt within 3 s with a threat close, a boss/dangerous class within
reach, or a pack not thinning; never within 6 s of a ring) and fires through `fire_scatter`, keeping
`scatters_fired`, `scatter_rounds`, `scatter_kills` (a kill window), `scatter_failures` and `scatter_decision`. This
step only adds RE5 to `SCATTER_TITLES` and gives the title its knobs: `SCATTER`, `SCATTER_EVERY_S`, `SCATTER_N` in
`re5_switch.py`, plus the three rows in the PiP's bot-logic sidebar ("Grenade scatter barrage (auto)", "Seconds
between barrages", "Rounds in a barrage"). The intervention op `grenade_scatter` is advertised for RE5 automatically
because `interventions.context()` adds the capability when the controller has the method.

**Tests** (`tests/test_re5_scatter.py`, 7): a random barrage is a flash cone from near to far at chest height, every
round through the verified wrappers; the probe carries the hand class's DTI/vtable/item and marks `probe`; an
explosive probe never lands inside the learned reach; a partial barrage is uncertain and recoverable; an unknown kind
is refused before any native call; the rule lists RE5 and reads its knobs; the shared hook returns a step for RE5 and
none for a PS3 session. Affected suites (RE5 scatter/class pair/class table/ring/native/mods, interventions, worker,
grenade rule/status, engine, bot logic): **169 passed**.

**Receipts this unblocks:** with the explicit-class probe, an RE5 Mercenaries round can now fire
`grenade_scatter {"kind": "hand"}` and `{"kind": "incendiary"}` - the same request shape as RE6's - which is the live
receipt item 3 still owes. Both this branch and `ds-re5-classes-pair-20261110` must be deployed for it (the title
module hot-reloads; `interventions.py` already carries the op from the RE6 lane).
