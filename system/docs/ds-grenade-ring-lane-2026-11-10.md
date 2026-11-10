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

## Step: RE6 hand and incendiary as a spawn/detonate parameter (2026-11-10, branch `ds-re6-bomb-classes-20261110`)

Hand-off lane B item 1: "Make the class a parameter of the spawn, rebuild, and get a live receipt per kind ... Then
let `grenade_status` advertise each kind."

**No compiler needed, and no rebuild of the verified images.** `spawn.c` builds the class DTI in its *second*
argument with exactly two instructions (`adrp x1, 0x2951000` / `add x1, x1, #0x500`), and `detonate.c` builds the
unit's class vtable in `x0` with two (`adrp x0, 0x284a000` / `add x0, x0, #0xeb8`). `native/re6_061d2a06/classes.py`
derives a parameterised pair from those pinned, verified blobs by replacing exactly those two instructions:

    spawn_class(player, dti)                                      # two NOPs: x1 arrives from the caller
    detonate_class(unit, player, generation, player_generation, class_vtable)   # mov x0, x4 + NOP

The dispatcher already maps call argument *n* to `x<n>` (`call.S`: `ldp x0,x1,[x19,#0xc8]`, `ldp x4,x5,[x19,#0xe8]`),
so `Controller.call` can hand both values. The derived images are pinned with their own digests
(`spawn_class` 256 B @ `543749d9…`, `detonate_class` 232 B @ `9ba12497…`) and the originals keep theirs.

**Where they install.** Two caves the repository has not used: `main+0x18F2BC0` and `main+0x18F2CC0`, inside the
same never-executed padding tail as the four shipped images. `scripts/verify_re6_classes.py` checks them against the
operator's own `main.bin`: `.text` is one zero run from `0x18F2630` to its end, both ranges are all zero, and no
B/BL/ADR/ADRP+ADD target and no 64-bit literal in `.text`/`.rodata` points into them. Run against the extracted
update image (build `061D2A06…`): **PASS** for both new caves, and the same check passes for the four shipped ones.
The originals are untouched and still what the flash and the bomb use; the class pair is installed on demand
(`_ensure_image`, the `spawn_bomb` pattern) only when a hand or incendiary grenade is fired.

**Controller.** `_ring_one(kind)` keeps the flash on the shipped pair and, for another class, spawns with its DTI and
detonates with the vtable **the allocated unit actually carries** (`q(unit)`) - so the wrapper's check is "still the
class we allocated", not "is a flash", and no per-class vtable table is trusted at run time. `grenade_ring` takes
`allow_unverified`, and `grenade_kinds()` still advertises **flash only**: the classes exist, their receipts do not.

**The receipt probe.** `grenade_scatter` already accepts an explicit kind and the queue does not gate that kind per
session, so an explicit implemented class there is the deliberate probe: its receipt gains `kinds` and
`probe: true`, and the default `random` barrage still draws from the verified kinds only. This is the request for
the first receipt, once this branch is deployed and an RE6 No Mercy round is live:

    POST /api/sessions/{sid}/interventions
    {"op": "grenade_scatter", "request_id": "<new uuid>", "args": {"kind": "hand"}}

and the same with `"incendiary"`. Record: the receipt (`state`, `detonated`, `rounds[].class_vtable`,
`self_damage`), a frame before and after, and the round's counters. If the wrapper's action-class expectations do
not hold for these classes, the receipt comes back `failed`/`uncertain` with its reason - that is the next thing to
fix, not something to paper over.

**Tests** (`tests/test_re6_class_images.py`, 19): the two patched instructions word for word and everything else
unchanged; a tampered source image refused instead of patched; the pinned digests; the class table against the DTI
tree; `image_bytes` routing; hand spawn/detonate arguments and the carried vtable on a fake emulator; the flash
ring and the single flash op still on the shipped pair with their own resource guard; unverified kinds refused
without the probe flag and unknown kinds refused before any native call; a class without loaded resources refused;
and the cave scanner finding a hole, a branch into it and a non-zero byte. The affected suites (class images, ring,
native build, RE6 mods/inventory, interventions/worker, grenade status/rule, RE5 ring/native, engine) are **166
passed**.

**Deploy needs**: the title module hot-reloads, but the new `classes.py` and `tools/` are new files and the worker
imports them - a `gbox.service` restart at a gap (already asked above) covers it.

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
`scripts/verify_re5_classes.py <main.bin>` runs it. Against the operator's image: **PASS**, no mismatches, the whole
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
## Round 50 (2026-11-10, later session) — RE6 launcher rounds: the tables pinned, and why they cannot ride the bomb wrapper

Hand-off lane B item 2 ("find the shell spawn path, put real launcher rounds into `grenade_scatter`'s random kinds").

**Pinned in code** (`native/re6_061d2a06/classes.py`, branch `ds-re6-launcher-shells-20261110`):
`SHELLS` uWp1302/1303/1304 (items 0x133-0x135, DTIs `0x2952098`/`0x29520d0`/`0x2952108`, size 0xE5C, parent
`uWpShellLauncher`), the `SHELL_FAMILY` chain (uWpShell `0x2950b60`, uWpShellLauncher `0x2950b98`, Bowgun, Homing,
Rifle 0x138), the `LAUNCHERS` (uWp1080 Grenade Launcher item 0x112 `0x2951260`; uWp1120 Rocket Launcher 0x11B
`0x2951458`) and `LAUNCHER_ROUNDS` (uWp1080 -> the three rounds). The test cross-checks every row against
`docs/research/re6-weapon-dti-tree.json`, so the code and the research tree cannot drift.

**The blocker, from our own wrapper's disassembly:** the detonate image checks the unit's **action object** against the
bomb action class `0x288C9A0` (words 30-36) before it fires, and the final comparison is against `0x288C868`. A round
carries the launcher's action, so the wrapper returns 0 - a clean refusal (no crash, no explosion). Parameterising the
class cannot fix that: a shell is a **projectile the weapon spawns with a velocity**, so the barrage needs the
launcher's own fire/explode path. That is the next step, and it is a live-iterated one (the fire function's arguments
have to be observed on a running RE6 round).

**No false advertising:** `grenade_scatter` still refuses shell kinds - a test asserts the shell names are in neither
`RING_IMPLEMENTED_KINDS` nor the ring's `CLASSES`, so nothing can fire a round that cannot explode. `re6_dti_emu`'s
table and this module now agree; the barrage's random kinds stay flash-only until a kind has a live receipt.

Tests: `test_re6_class_images.py` (21) incl. the tree cross-check and the "not a ring kind" guard; the RE6/intervention
set **126 passed**.

## Round 51 (2026-11-10, later session) — an explosive ring keeps its distance (RE6, and the RE5 equivalent)

Found while preparing the hand/incendiary receipts: the ring's distance guards were sized for the **verified flash** -
`RING_SELF_CLEAR_CM = 250` and a default inner radius of `150` - and the new explosive kinds inherited them. A default
hand ring would therefore have placed its first grenades 150 cm from the player, i.e. inside his own blast: the first
receipt would have been a self-damage one, and the kind would have looked broken when the placement was the fault.

**Fixed in `re6_switch_native` (branch `ds-re6-ring-explosive-floor-20261110`):**
- `RING_EXPLOSIVE_CLEAR_CM = 600.0` - the smallest radius an explosive kind (hand, incendiary) may be ringed at.
- `grenade_ring` uses it as the floor for both the outer radius and the inner ring when the kind is not the flash, so
  no default (or short requested) explosive ring can place a grenade inside the blast; the clamp is reported in the
  receipt (`radius_cm`, `inner_cm`), so nobody has to guess what the ring actually did.
- The flash path is untouched: 150 cm inner and 250 cm floor still apply (it is harmless up close, and that is the
  live-verified behaviour).

**Tests** (`test_re6_class_images.py`, 25 in the file): a default hand ring places all four grenades at >= 600 cm and
still expands outward; an incendiary ring asked for 300/100 cm is raised to 600 and the receipt says so; the flash ring
keeps its 150/250 near field. The rest of the RE6/intervention set stays green.

**The RE5 ring has the same shape and gets the same fix on `ds-re5-ring-explosive-floor-20261110`**, so the two titles
cannot diverge on the safety margin.

**Still blocked on the live side:** the receipts for hand/incendiary (RE6 and RE5) need the branches deployed on
lilspark and one round fired per kind; the probes and the exact request are in the sections above. Until then
`grenade_status` advertises the flash only, which is what "no silent substitution" means here.

## Round 51b (2026-11-10, later session) — the RE5 ring gets the same explosive floor

The RE5 ring carried the identical flash-sized near field (RING_SELF_CLEAR_CM = 250, default inner 150) that the new
explosive kinds inherit; a default hand ring would have detonated its first grenades 150 cm from the player.

**Fixed on this branch (ds-re5-ring-explosive-floor-20261110):** RING_EXPLOSIVE_CLEAR_CM = 600.0 is the floor for
both the outer radius and the inner ring when the kind is not the flash; the clamp is in the receipt (
adius_cm,
inner_cm), the flash path is untouched. Tests: default hand ring >= 600 cm; an incendiary ring asked for 300/100 is
raised to 600 and says so; flash keeps 150/250. RE5 class-pair/ring/native suites: **44 passed**.

Same rule as RE6 (ds-re6-ring-explosive-floor-20261110), so the two titles cannot diverge on the safety margin.

## What is ready, by branch

Merge in the order shown: `->` means "stacked on" (the later branch contains the earlier one, because its tests use the
earlier code).

| # | branch | commit | what it does | tests measured |
|---|---|---|---|---|
| 1 | `ds-re6-bomb-classes-20261110` | `1ec0bfe9` | RE6 hand + incendiary: the class becomes a spawn/detonate parameter (two instructions replaced in the pinned images; new caves vetted by `scripts/verify_re6_classes.py`, PASS on the operator's image); ring kinds, explicit-kind barrage probe | 166 passed (RE6 ring/native/classes/interventions/engine) |
| 2a | `ds-re6-launcher-shells-20261110` -> 1 | `226c985b` | launcher/round tables pinned (uWp1302-1304, items 0x133-0x135, DTIs 0x2952098/d0/0x2952108; launchers uWp1080 0x112, uWp1120 0x11B) cross-checked against the research JSON; **and the measured reason a round cannot ride the bomb wrapper** (action-object check 0x288C9A0) | 126 passed |
| 2b | `ds-re6-ring-explosive-floor-20261110` -> 2a | `2a0ff081` | explosive kinds get a 600 cm ring floor (the flash's 150/250 near field was inside a grenade's blast); clamp reported in the receipt | 25 passed (RE6 class images) |
| 3 | `ds-re5-classes-20261110` | `ac5b396f` | RE5 class table derived from the game's own MtDTI initialiser and verified: uWp06 hand `+0x1D714C8`, uWp07 incendiary `+0x1D71500`, uWp08 flash `+0x1D71538` (the last matches the live-verified flash DTI) | 53 passed |
| 4a | `ds-re5-classes-pair-20261110` -> 3 | `7dc50b31` | RE5 parameterised spawn/explode: class DTI in x2, class vtable in x4, item in w5, update in x6 (flash keeps 0x820E50; the others take the bomb base 0x806B80). **Installed in place** (RE5's .text tail has no free cave left); old sessions refuse, new ones get it | 149 passed |
| 4b | `ds-re5-scatter-20261110` -> 4a | `a03fa8f5` | RE5 barrage: `grenade_scatter` (cone toward the threats, near to far, chest height, explicit-kind probe), RE5 in `SCATTER_TITLES`, `SCATTER`/`SCATTER_EVERY_S`/`SCATTER_N`, three PiP rows | 169 passed |
| 4c | `ds-re5-ring-explosive-floor-20261110` -> 4a | `11cb05a2` | the same 600 cm floor on RE5 | 44 passed |

Every branch is pushed. None has been merged, and **none has a live receipt yet** - that is the only thing missing.

## What I need from you (lilspark)

1. **Deploy**: merge 1 + 2b (RE6) and 3 + 4a + 4b (+ 4c) (RE5), then restart `gbox.service` at a gap - the RE6/RE5
   controller modules are title modules and hot-reload, but a restart makes it deterministic. RE5's pair replaces two
   shipped images at the same addresses: **an emulator already running the old pair refuses cleanly** (`install()`
   refuses occupied bytes); every new session gets the parameterised pair. Re-verify the RE5 flash ring once after
   deploy (it now goes through the parameterised pair with the same values).
2. **Fire one probe per kind on the matching round** (5-round blocks per title):
   - `GET /api/mercmode` -> `current_run.title` is RE6 `01002A000CD48000` or RE5 `010018100CD46000`;
   - `POST /api/sessions/{sid}/interventions`, header `x-gbox-actor: agent`, body
     `{"op": "grenade_scatter", "request_id": "<new uuid>", "args": {"kind": "hand"}}` - then `{"kind": "incendiary"}`;
   - read the row back from `GET /api/sessions/{sid}/interventions` and record: `state`, `detonated`/`requested`,
     `rounds[].class_vtable`, `self_damage`, `effect`, and a frame before/after (`GET /api/sessions/{sid}/frame.jpg`).
   - A refused row (`state: failed`, reason) is a real result: send it back with the reason, do not retry blindly.
3. **Send me the receipts** (or paste them here). On a confirmed receipt for a kind I will flip it to advertised:
   `RING_VERIFIED_KINDS` in `re6_switch_native.py` / `re5_switch_native.py` plus the two "advertised kinds" tests, so
   the PiP and the queue offer it - `grenade_status` reads that constant, nothing else changes. I will take that as a
   small follow-up branch per title.

## Not done, and why

- **RE6 launcher rounds in the barrage**: blocked by design, not by effort - a uWpShellLauncher round carries the
  launcher's action object, and our detonation wrapper requires the bomb's (`0x288C9A0`), so the wrapper refuses it.
  The round is a projectile the weapon spawns with a velocity; the barrage needs the launcher's own fire path, which
  must be measured on a running round. The tables are pinned so that path has its addresses.
- **RE4 harness/flash/ring**: not started. It needs ARM64 code generation and this PC has no toolchain (Ghidra's
  assembler or an installed gcc/clang is a prerequisite), so it is the one item I cannot start without a decision on
  tooling.

## Baseline honesty

The grenade suites' pre-existing reds are unchanged by these branches (the hand-off's 11 RE5 / 3 RE6 known-red files
are untouched: no branch edits a file in that list). The counts above are the suites the branches themselves affect.

## Checkpoint 0 - the pushed work made safe to merge, on one branch (2026-11-10 14:25 CST, `ds-grenade-merge-20261110`)

The integration branch the RE session can merge and deploy in one gap. It is cut from `54b2a78e` and merges the four
branches in the doc's order; the only conflict was this lane log (append-against-append), resolved keeping every
section in time order, and there was **no code conflict**:

1. `ds-re6-ring-explosive-floor-20261110` (`2a0ff081` - the RE6 classes, the launcher shells, the 600 cm explosive ring floor);
2. `ds-re5-scatter-20261110` (`a03fa8f5` - the RE5 classes, the class pair, the scatter barrage);
3. `ds-re5-ring-explosive-floor-20261110` (`11cb05a2` - the RE5 explosive ring floor);
4. `ds-grenade-handover-20261110` (`ceec7da8` - the branch map and the probe requests).

**0.1 - RE5 tolerates the old pair.** `re5_switch_native` reads `main+0x118E820` / `main+0x118E9D0` *before* `attach()`
installs anything: the old shipped `spawn` / `explode` => the old `PRE_CLASS_CODE` table and the old call shapes
(two-argument spawn, four-argument explosion; the DTI and vtable are compiled in), so flash/ring/scatter keep working
and `hand` / `incendiary` answer `Unavailable` "this emulator runs the pre-class pair; the next emulator gets it";
zero caves => the class pair, as now; any other (or half-installed) bytes => everything refuses with no install. The
old bytes are never written. Tests: `test_re5_pair_fallback.py` (6) - the old pair fires the flash through the old
shape and writes nothing to the pair, hand/incendiary are refused before any native call, a zero cave installs the
class pair and fires the class shape, a pair the class images already wrote is reused, other and half-installed bytes
refuse everything.

**0.2 - the explosive floor in both scatters.** `re6_switch_native.grenade_scatter` and
`re5_switch_native.grenade_scatter` place every non-flash round at `max(lo, RING_EXPLOSIVE_CLEAR_CM, safe_cm +
SCATTER_SAFE_CM)` (600 cm with no learned reach), raise `hi` to that floor when the threat or the learned reach pulls
it lower, and report `floor_cm` / `floors_cm` in the receipt. The placement adds the 1 cm rounding margin so the
*measured* distance stays at or above the floor. Tests: an explicit `kind="hand"` barrage with no `safe_cm` places
every round at 600 cm or more, on both titles.

**0.3 - the flash floor in both scatters.** Flash rounds start at `FLASH_PLACE_MIN_CM` when the title has it
(`mercs-aim-book` will set 400 on RE5) and never below 400 cm (`flash_place_min_cm()`), instead of 300. Tests: a
random (flash) barrage has no round under 400 cm on either title, even with the threat at 120 cm.

**0.4 - RE5's automatic barrage off.** `re5_switch.SCATTER = False`; the `grenade_scatter` op stays advertised
whenever the controller has it, so the probe route and the operator's button work. Test:
`test_the_re5_automatic_barrage_is_off_until_checkpoint_d_but_the_op_stays`. Checkpoint D turns it back on under
`FLASH_MIN_GAP_S`.

**Tests on the merged tree** (from `<worktree>/system`, `PYTHONPATH="<worktree>/system;<worktree>/system/tests"`):
`test_re6_class_images`, `test_re5_class_pair`, `test_re5_class_table`, `test_re5_scatter`, `test_re6_grenade_ring`,
`test_re5_grenade_ring`, `test_mercs_grenade_status`, `test_mercs_grenade_ring`, `test_re6_native_build`,
`test_merc_interventions`, `test_intervention_worker`, `test_re5_switch_native`, `test_bot_logic`,
`test_re5_switch_ss_campaign`, `test_mercs_engine`, plus `test_re6_grenade_scatter` and `test_re5_pair_fallback`:
**219 passed, 0 failed**. None of the known-red files is in this set. One main test was updated knowingly:
`test_re6_grenade_scatter.test_the_barrage_is_rapid_and_refuses_unverified_kinds` now expects the resource refusal
("hand resources are not loaded ...") because the class branch makes `hand` an implemented probe kind and the
resource gate answers first; the old "not yet verified" case is still covered by `test_re6_class_images`.

Branch: `ds-grenade-merge-20261110`. The code commit is `5068b945` (the four merges, 0.1-0.4, the two new test files
and the two updated tests); this log and the request below are the commits on top of it.

## REQUEST 14:32 CST - merge `ds-grenade-merge-20261110`, then restart `gbox.service` in the same gap

- needs: merge `ds-grenade-merge-20261110` @ `5068b945` (the branch tip also carries this request), then a
  `gbox.service` restart **in the same gap** on lilspark
- why together: the restart is what loads `interventions.py` and the new `classes.py` modules, and what gives every
  RE5 emulator the class pair. An RE5 emulator that keeps running the old pair keeps its flash (0.1) and answers
  "pre-class pair" for hand/incendiary - nothing hangs and no executed instruction is rewritten.
- then, after the restart: read `GET /api/sessions/{sid}/interventions` once on an **RE5** and once on an **RE6**
  MercMode session (expect `flash` available; `hand` / `incendiary` unavailable with the "no live receipt yet"
  reasons), and **fire one RE5 flash**
- record: the two status reads (a screenshot of the PiP rows or the JSON), the RE5 flash receipt (`state`,
  `detonated`, `hp_before` / `hp_after`), and the doctrine `crit_flashes` / `mine_flashes` (or the PiP flash receipt)
  showing the flash confirmed after the deploy
- headers: `x-gbox-actor: agent`; the token is `system/gbox-data/api_token` - never print it

## Round 52 (2026-11-10 15:30 CST) - checkpoint B1's first pass: the guide's scan does not exist on the pinned image, and the class records it does have are named

Working offline on the i9 against the operator's own update image (`.tmp/re6exefs-update/main.bin`, extracted from
`Resident Evil 6 [01002A000CD48800][v131072].nsp`; `re6_switch_native.verify_build` on it: **ok**, build
`061D2A06CD700785E987C42CE2D72231`, all five code caves pristine). Every number below is a capstone scan over that
file (`mem = file offset - 0x100`, the whole `main` down to its `.text` tail at `0x18F2630`, `skipdata` on so no
region is skipped).

**What checkpoint B1 says to look for:** "scan for `adrp x1` + `add x1` resolving to a shell DTI (`0x2952098`,
`0x29520D0`, `0x2952108`), followed by `bl 0x3BCF90`".

**What the image actually has:**

1. **No shell DTI is ever built into `x1`.** Zero sites in 6,539,660 instructions. The only code that materialises
   the three shell DTIs is the MtDTI static initialiser itself - `0x140A34` uWp1302, `0x140AAC` uWp1303, `0x140B2C`
   uWp1304 - and it builds them in `x8` (the whole grenade/launcher family is built there; the same is true of
   FLASH_DTI, so `x1` there is our own compiled `spawn.c`'s link-time symbol, not the game's call shape).
2. **`bl 0x3BCF90` has zero call sites.** `0x3BCF90` is a two-instruction veneer:
   `0x3bcf90  and w4, w4, #1` / `0x3bcf94  b #0x359270`. The constructor body is **`0x359270`**.
3. **No address in `0x3BC000..0x3BE000` is materialised as a constant either** (zero `adrp`/`add` pairs), so the game
   does not reach it through a function-pointer table built from the constructor's own range.

So the launcher's fire is not a `CREATE_ITEM(allocator, shell_dti, ...)` site that scan can see. The class records do
give a new, checked lead, though:

**Each grenade/launcher class has a class-info record whose entry `+0x68` is a getter returning its DTI.** Found by
searching for a pointer to each getter and reading the 0x98 bytes before it (entries are `(0x403, fn, runtime_ptr)`,
0x18 apart):

| class | record | DTI getter | class-specific fns at +0x08 / +0x20 / +0x38 / +0x50 / +0x68 / +0x80 |
|---|---|---|---|
| uWp1302 | `0x1FD3BB0` | `0xF5A620` | 0xF5A580 / 0xF44750 / 0x2FD6E0 / 0xF44760 / **0xF5A620** / 0xF5A630 |
| uWp1303 | `0x1FD2E30` | `0xF5A360` | 0xF5A2C0 / 0xF44750 / 0x2FD6E0 / 0xF44760 / **0xF5A360** / 0xF59EE0 |
| uWp1304 | `0x1FD20B0` | `0xF59ED0` | 0xF59E30 / 0xF44750 / 0x2FD6E0 / 0xF44760 / **0xF59ED0** / 0xF59EE0 |
| uWpBomb | `0x2001FD8` | `0xF6EEA0` | 0xF6EDD0 / 0xF84C30 / 0x2FD6E0 / 0xF84C40 / **0xF6EEA0** / 0xF6EEB0 |
| flash | `0x2002CB0` | `0xF6F110` | 0xF6F040 / 0xF84C30 / 0x2FD6E0 / 0xF84C40 / **0xF6F110** / 0xF84F80 |
| incendiary | `0x20039B8` | `0xF6F2A0` | 0xF6F1D0 / 0xF84C30 / 0x2FD6E0 / 0xF84C40 / **0xF6F2A0** / 0xF84F80 |
| hand | `0x2004690` | `0xF6F430` | 0xF6F360 / 0xF84C30 / 0x2FD6E0 / 0xF84C40 / **0xF6F430** / 0xF84F80 |
| uWp1080 | `0x200CC28` | `0xF71980` | 0xF71930 / 0xF3D1B0 / 0x2FD6E0 / 0xF64230 / **0xF71980** / 0xF3D1E0 |

The uWp1080-specific bodies read: `0xF71930` calls `0xF3D090`, then re-dispatches through the class registry at
`0x296C48` slot `0x68` with the new object in `x1` (the uWp1080 constructor path); `0xF64230` walks the owner at
`+0x3884`/`+0x3888` allocating nodes of `0x60` bytes with `0x115CBB0` and storing the strings `"mMode"` / `"mType"` -
a property-bag/descriptor builder, not a shot; `0xF3D1E0` is a per-frame update over the owner's weapon state at
`+0x1300`. `0x2FD6E0` (shared by every record) is a two-word predicate (`[...+0x14] & 7`, true for 1..2).

**Nothing here is the fire yet.** The next step for B1 is the weapon's action object: the uWp1080 class does not hold
the shell spawn itself, so the shot must be an action class's transition (the same place the live flash's
`cWpAction_wp_act_throw` transition was found), and the record above gives its class registry slot. That is where the
next scan goes. Nothing in the repo changed for B, and nothing is claimed about the launcher.

## REQUEST 15:30 CST - a read-only copy of the RE4 Switch base content on the i9 (checkpoint E1 / F1 are blocked on it)

**RESOLVED 15:58, no action needed** (round 54: the Spark's decrypt-lab had already extracted the image and its
`main.bin` was on the home share; copied read-only to `D:\gBox\cache\re4-base\main.bin`, F1 passes, E1's cave vetted).

- needs: the RE4 Switch **base** content for title `010099A00BC1E000` copied onto the i9 (read-only), either the base
  NSP or the extracted `main` (+ its `main-*.nso` name/build id). A path under `D:\gBox\cache\` is enough; say where.
- why: only the **update 1.0.2 NSP** is on this box
  (`D:\gBox\cache\270a15eb98dab4d7\Resident Evil 4 [UPDATE 1.0.2] [010099a00bc1e000].nsp`). It has no `.tik` member,
  so `python -m gbox.switch_extract exefs` answers "no ticket in the container: a title key cannot be derived";
  there is no base NSP on the i9's drives, and JAYBUILTFINALE's shares are not reachable from the i9.
- what it unblocks: E1 (the `.text` tail's zero run and the no-reference proof), E2 (the player unit's vtable slot),
  and F1 (`re4_switch_blasts.verify(main_bin)` against the real image, `docs/research/re4-switch-grenade-flash.md`).
  The build to compare is `82C2A04A21D3E0B850F273D4149C9003`, NSO sha256
  `98ca897f07b2c864a0cabfb9dd8ca46a54b88c565ba629da3b7a4b6a57a57441`.
- meanwhile: E0(c) needs no decision - capstone 5.0.7 and unicorn 2.1.4 are both installed on this box - so the
  hand-encoded harness can start as soon as the image gives the cave and the trigger addresses.

## Round 53 (2026-11-10 15:40 CST) - the integration branch re-checked on today's main

`origin/main` moved from `54b2a78e` to `2564c0a1` (menu pace, all three Switch titles' at-once PRESS ANY BUTTON, RE4
Switch doorway navigation, the ComfyUI render freeze, `scripts/bot_trace.py`). The integration branch is merged with it
(`374c4aed`, no conflicts - this lane's only edit in a touched file is RE5's `SCATTER` line, and main's work is in
other regions) and the full checkpoint-0 list re-run on the merged tree:

    test_re6_class_images, test_re5_class_pair, test_re5_class_table, test_re5_scatter, test_re6_grenade_ring,
    test_re5_grenade_ring, test_mercs_grenade_status, test_mercs_grenade_ring, test_re6_native_build,
    test_merc_interventions, test_intervention_worker, test_re5_switch_native, test_bot_logic,
    test_re5_switch_ss_campaign, test_mercs_engine, test_re6_grenade_scatter, test_re5_pair_fallback

**219 passed, 0 failed** (90 s). Nothing in the merge changes the grenade behavior; the branch is still the single
merge-and-deploy unit requested at 14:32, now on top of today's main, so the RE session's merge in one gap stays
conflict-free. The request stands: merge `ds-grenade-merge-20261110` (code `5068b945`; the merges and docs sit on top),
restart `gbox.service` in the same gap, read the two statuses, fire one RE5 flash.

Branch tip after this round: this commit; the code commit is unchanged at `5068b945`.

## REQUEST 15:40 CST - checkpoint B's fallback: one read-only capture during an RE6 round that carries the grenade launcher

Static analysis is stuck at the same place the guide's fallback anticipates. The launcher's shell spawn is not the
`CREATE_ITEM(allocator, shell_dti, ...)` site the B1 scan describes (`docs` entry of round 52): on the pinned image
(update `061D2A06...`, verified) no shell DTI is ever built in `x1`, `0x3BCF90` is only our own compiled spawn's
link-time veneer (`and w4,w4,#1; b 0x359270`), and the class-info records give the classes and their DTI getters but
not the shot. What is needed is the shell object created by a real shot.

- needs: **one read-only capture during an RE6 round whose character carries the grenade launcher** (item `0x112`,
  in loadouts `0x1004` / `0x0206`; the arsenal swap can put it in his hands, or the RE session picks the character).
  The RE6 block is fine; no probe is fired, nothing is written.
- when: right after **one real shot** from the launcher (or its first impact), capture:
  1. the new unit pointer the shot created (walk the player's `+0x1300` manager / the projectile list, or the class
     registry entry for `uWp1302`/`uWp1303`/`uWp1304` - the head of the new unit's object);
  2. that unit's `+0x00` class vtable, `+0x1300` owner, `+0x1308` generation, `+0x13F0` action object and its
     class (`re6_switch.unit_action` gives the name), and `+0x60` transform (position);
  3. the velocity / direction fields around `+0x3920` (uWp1080 stores `0x4116CBE4` there for the bomb, so the shell's
     own fields are likely nearby) - 0x60-0x80 bytes from `+0x3880` to `+0x3940`;
  4. the action class the unit switches to at impact (a second read after the hit), which is what B2 needs.
- record: the unit pointer, class vtable, action class names before/after impact, and the raw hex of the two ranges
  above. A `read_memory` dump of `unit+0x0..0x140` and `unit+0x3880..0x3960` is enough.
- if no character in the RE6 block carries the launcher for a whole block, a read-only capture on the player object of
  any round that does is equally useful; the goal is the shell object's shape, not the kill.

## Round 54 (2026-11-10 15:58 CST) - the RE4 image is here, F1 passes, and E1's cave is found and vetted

**The image.** The Spark's decrypt-lab state (`GET /api/decrypt-lab/state`) showed RE4 Switch already extracted from
the same update NSP this box has: `main-82C2A04A21D3E0B850F273D4149C9003.nso`, with a disassembly and five fields
confirmed. The extracted files are on its home share, so no request to the PM/RE session is needed for them:

    \\10.89.1.246\ehm_eckx\gBox_alt\gbox-cache\exefs\010099A00BC1E000\main.bin   (11,716,664 bytes)
    \\10.89.1.246\ehm_eckx\gBox_alt\gbox-cache\exefs\010099A00BC1E000\main       (5,260,117 bytes, the raw NSO)

copied read-only to `D:\gBox\cache\re4-base\` (data drive, as the storage rule says). Nothing on the Spark was
started, stopped or written.

**The build check.** The 64-byte signature at virtual `0x100000` matches `re4_switch.SIGNATURE` exactly, and the
decrypt-lab's identify stage names build `82C2A04A21D3E0B850F273D4149C9003`. One honest note on
`MAIN_NSO_SHA256`: the documented `98ca897f...` is Citron `dump_nso`'s **30,146,816-byte** form (0x100 header + the
image at vaddr 0 including .bss, with the compressed-offset header values). This expanded image hashes to
`d006951b...`; padding it to the full 30,146,816 bytes hashes to `85de53b1...`, so the difference is the header
(and/or the dump's padding), not the code. The signature and the blast anchors below are what identify the build;
the raw Citron dump is not on the share any more. The header layout, measured here: `.text 0..0x655850`,
`.rodata 0x656000..0xAE1BCC`, `.rwdata 0xAE2000..0xB2C738`, `.bss 0xB2C738..0x1CC0000`.

**F1 passes.** `re4_switch_blasts.verify(open('main.bin','rb').read())` returns **no problems** on the operator's own
image: all three blast anchors (`0x2E48B0` hand, `0x2E4AA0` simple, `0x2E4E50` flash), their vtable slots, the
`AREA_ATTACK` call targets and the 6000/15000 radii all check out. Evidence: the empty problem list above; the
research doc is `docs/research/re4-switch-grenade-flash.md` (request #9436).

**E1's cave.** New tool `scripts/verify_re4_caves.py` (see its docstring for the exact contract) reads the layout from
the image's own NSO header, takes the first 64-byte line after the declared `.text`, and proves:

- cave **`main+0x655880`**, size **0x780 (1920 bytes)**, ends at the RX page boundary `0x656000`;
- the whole range is zero and 64-byte aligned (`0x655880 % 64 == 0`), inside the executable mapping (`text_size`
  rounds up to `0x656000`), and `.rodata` starts exactly at the page end - no overlap;
- **no** B/BL, ADR, ADRP+ADD target and **no** 64-bit literal in `.text`/`.rodata`/`.rwdata` points into it
  (the scanner also looks up to 3 instructions after an ADRP, not just the next one);
- verdict **PASS** on `D:\gBox\cache\re4-base\main.bin`; the same run prints the section table above.

Tests: `tests/test_re4_caves.py` (10) - a clean synthetic NSO yields the aligned tail cave; a B, an ADRP+ADD pair
and a 64-bit literal into the cave are each caught; a nonzero byte fails the hole test; a page-aligned `.text`
leaves no cave; truncated/foreign images are refused; the measured RE4 layout is pinned as a regression case
(`0x655880`, `0x780`); the CLI's PASS/FAIL exit codes and the `--at/--size` override are covered. Run together with
`test_re4_switch_blasts.py`: **11 passed, 1 skipped** (the skip is the test that wants the real image present).

**Next.** E2: the player unit's per-frame vtable slot (the `0xB09A60` / `0xB0C0A0` class tables are static, so the
clone-vtable trigger can be designed against the image), then E3/E4/E5. The pinned cave is the one to install into.

## Round 57 (2026-11-10 16:35 CST) - checkpoint D: RE5's barrage back on, under the one flash clock (branch `ds-grenade-re5-scatter-cap-20261110`)

Base: `origin/main` `53cc8962`, which already carries checkpoint 0 and the flash-cap work (`core/flash_window.py`,
`FLASH_MIN_GAP_S = 60`, `SCATTER_FLASH_ONLY`/`FLASH_TIGHT` for RE6). This lane's checks 0.2/0.3 are in that base too.

**D1 - one clock.** The rule side already had the pieces for a `SCATTER_FLASH_ONLY` title (`flash_rules()` reads
`FLASH_MIN_GAP_S`, `decide_scatter`'s `flash_only` branch calls `flash_held`, `fire_scatter` stamps). What was missing
for RE5, and what this branch adds:

- `re5_switch.SCATTER_FLASH_ONLY = True` (its only verified barrage kind is the flash) and
  `re5_switch.scatter_kinds()` - the title exposes the native verified set, so the rule no longer has to assume it;
  `re6_switch.scatter_kinds()` does the same for RE6.
- `scatter_policy()` now carries `kinds` (the title's set, default `("flash",)`), so `decide_scatter` can tell an
  all-flash barrage from a mixed one; the tests pin `SCATTER_FLASH_ONLY == (scatter_kinds() == ("flash",))` so
  checkpoint C cannot extend the kinds without revisiting the flag.
- `decide_scatter()` gate: while the flash clock (`stats["native_flash_confirmed_at"]` / `flash_stamp_at`) is inside
  `FLASH_MIN_GAP_S`, an all-flash barrage is refused with the same "one every 60 s (FLASH_MIN_GAP_S)" reason the ring
  uses (and `flash_gap_skips` counts it); a **mixed** barrage instead leaves the flash out (`narrowed`, `kinds` =
  the non-flash kinds) and may still fire - so a verified hand grenade can answer the moment without breaking the cap.
- `fire_scatter()` passes the narrowed `kinds` to the controller and stamps `native_flash_confirmed_at` (the shared
  clock, `stamp_flash`) when the confirmed receipt carried a flash round - not only on the flash-tight early path, so
  an all-flash barrage on any trigger holds the next automatic flash for the minute.
- **An operator click is on the same clock.** `interventions.py` already stamped the clock for a clicked ring; a
  confirmed clicked `grenade_scatter` whose receipt `kinds` include flash now stamps it too, so the bot's own rules
  wait a minute after the operator's barrage.
- Both native controllers take `kinds=` for a `random` barrage: each kind must be in `SCATTER_KINDS` (the verified
  set) or the call refuses before any native work; an explicit kind plus `kinds` is refused. The pre-class-pair
  fallback still applies (`_require_kind`).
- **D2:** `re5_switch.SCATTER = True`. The op stays advertised either way; nothing else about it changes.

**Tests.** Focused run (rule, both scatters, both controllers, interventions/worker): **80 passed**. Broad run (the
CP0 list plus flash-window/aim-book/re6-bomb-mind/re5 autogrenade and the RE4 cave verifier): **247 passed, 0
failed**. New `tests/test_mercs_scatter_cap.py` (9): RE5 is on and flash-only under its own clock; a closed clock
refuses the all-flash barrage with the reason and counts the skip; an open clock fires and stamps the clock, and the
title's own `_flashed_lately` then holds; a mixed barrage inside the gap fires with only the non-flash kind and does
not stamp; an open clock keeps the full mixed draw; both controllers draw only the narrowed kinds; invalid or empty
narrowing and narrowing an explicit kind are refused before any native call. `test_re5_scatter.py`'s 0.4 assertion is
updated to the on-under-clock contract.

**Request: merge `ds-grenade-re5-scatter-cap-20261110`.** The title constant and the rule hot-reload, but
`interventions.py` (the operator-click stamp) needs a `gbox.service` restart, so merge + restart in one gap as before.
**Live acceptance (checkpoint D3), on an RE5 MercMode round after that:**
- one confirmed `grenade_scatter` receipt: `detonated == requested`, every round `>= 400` cm (flash) / `>= 600` cm
  (explosive), `self_damage 0`, frames and the kill delta;
- over a block, the telemetry's confirmed flash times are all at least `FLASH_MIN_GAP_S` apart, with
  `scatters_fired` / `scatter_rounds` / `scatter_kills` moving;
- if the RE session judges the flash-only barrage not worth having before checkpoint C verifies another kind, say so
  in the lane log and revert D2 (the fallback the guide allows) rather than living with a cap-breaking barrage.

## Round 58 (2026-11-10 16:45 CST) - E3's static half: a 3.4 MB unreferenced stretch of RE4's .bss, and the watch request

E3 asks for private writable storage (mailbox, generation guard, call arguments, result word). The cave is executable
code in the RX segment - an install target, never guest-writable - so the storage must be either RE4's own allocator
(not identified) or a `.bss` range the game never touches. This round builds and runs the static half of that proof.

**Tool.** `system/scripts/verify_re4_bss.py` (same shape as the cave verifier; no gbox runtime dependency beyond
`gbox.nso_elf`). From the image's own NSO header it:

1. collects every static reference into `.bss`: an `adrp` followed within four instructions by an `add`,
   `ldr`/`str`/`ldp`/`stp` or other immediate use on the same register, every `adr`, and every 64-bit literal in
   `.text`/`.rodata`/`.rwdata`;
2. finds the 4 KiB-aligned windows of at least `--size` bytes with no reference in them (all of them, plus the
   largest unreferenced stretch);
3. vets one chosen range with `--at` (inside `.bss`, page-aligned, no reference) and exits 0/1.

Tests: `tests/test_re4_bss.py` (10) - a clean image offers every aligned page; a planted `adrp`+`add`, `adrp`+`ldr`,
an `adr` and a 64-bit literal each remove their page; a reference just past a window does not count; a range outside
`.bss`, an unaligned one, a size over a page and truncated/foreign images are refused; the CLI's PASS/FAIL.

**The operator's image** (`D:\gBox\cache\re4-base\main.bin`, layout `.text 0..0x655850`, `.rodata 0x656000..0xAE1BCC`,
`.rwdata 0xAE2000..0xB2C738`, `.bss 0xB2C738..0x1CC0000` = 18.4 MB):

- **10,285 static references into `.bss`** (mostly literals pointing at the bss base, plus the adrp-based data
  accesses);
- **4,381 free 4 KiB pages**;
- the **largest unreferenced stretch is `0x1681000..0x19C0300`** (0x33F300 = 3.4 MB, bracketed by references at
  `0x1680000` and `0x19C0300` - so it may be one large buffer, exactly the case the live watch exists for);
- free tail pages near `0x1CB2000..0x1CBC000`, with references at `0x1CB6000` and `0x1CBF090`.

**Statically vetted candidates** (each PASS: inside `.bss`, page-aligned, no static reference):
`0x1700000` and `0x1681000` (inside the large stretch), `0x1CB2000` and `0x1CB9000` (the tail).

**The caveat the request carries.** A register-indexed access (`base + xN`) or a pointer stored at run time is
invisible to a static scan. The chosen page must also read **all zero across three stage loads** on a live RE4 round;
only then may the controller use it. That watch is now the blocking piece of E3, and it is a read-only request:

- read: `0x1CB9000`, `0x1CBA000`, `0x1CBB000`, `0x1CBC000`, `0x1700000` (a 16-byte read of each is enough; a full
  4 KiB page is better);
- when: three stage loads of one RE4 Mercenaries round - the round start, mid-round after a restart, and the next
  stage;
- pass: all zero on all three reads. Any nonzero byte rules that page out for good.

Once one page passes, E4/E5 (the code rule and the offline tests) can build the controller's private storage on it
without touching game state.

## Round 59 (2026-11-10 17:00 CST) - the deploy landed: checkpoint 0's first live acceptance read (RE6)

**The restart happened and it carried D.** The PM merged `ds-grenade-re5-scatter-cap-20261110` (`e317ff6d`, then
`eae1bb86`), and the Spark's service restarted at ~16:54 under a new worker id (`8cf47f44...`, previously
`78012a3f...`). So the one restart loaded checkpoint 0 **and** D; the old stuck RE6 session is gone.

**Live read, RE6 No Mercy, session `8cf47f441c5041fa-20b2f78a64564e4d` (Jake, `up` 1794350098), 17:00:**

    GET /api/sessions/8cf47f441c5041fa-20b2f78a64564e4d/interventions
    available=True, reason=""
    capabilities = flash_now, equip_primary, grenade_ring, grenade_scatter, magnum_quick4, set_infinite_ammo
    flash       available=True   (the RE6 "no living player" stale-base bug is gone on the fresh controller)
    hand        available=False  "a hand-grenade ring is not yet verified on this build (uWp1091 is known; the
                                  compiled spawn image pins the flash's class)"
    incendiary  available=False  "an incendiary-grenade ring is not yet verified on this build (uWp1093 is known; ...)"

That is checkpoint 0's RE6 half: flash advertised, the two explosive kinds refused with their own no-receipt
reasons (the wording is the merged RE6 class branch's; RE5's is the explicit "no live receipt yet"). The pre-restart
baseline for comparison is in round 56 of the lane log (flash refused, capabilities empty).

**Still open for checkpoint 0:** the RE5 status read and the one RE5 flash. The MercMode queue after the current RE6
block is `re4 x5, re5 x5, ...`, so the RE5 window comes after the RE4 block - a read-only read from the i9 when it is
up, and the flash needs the operator/RE session. **E3's zero watch** fits the same RE4 block (its five pages, three
stage loads); both asks are in the PM doc on main.

**D's live acceptance** is also the RE5 block: one barrage receipt (if fired as an intervention) or the telemetry's
`scatters_fired`/`scatter_rounds`/`scatter_kills` plus the confirmed-flash times at least `FLASH_MIN_GAP_S` apart.

## Round 60 (2026-11-10 17:20 CST) - E0(c) done: the RE4 dispatcher is assembled, pinned and runs under unicorn

The only guest-side code the RE4 harness needs is the dispatcher behind the player object's cloned vtable slot.
It is now a real, tested image. Keystone 0.9.2 turned out to be installed on the i9, so instead of hand-encoding
words the source is a normal ARM64 assembly file, assembled at the cave address, checked by capstone and executed by
unicorn; the runtime never imports keystone - the bytes are pinned in `code.py`.

**New: `gbox/mercs/native/re4_82c2a04a/`**

- `dispatch.S` - the dispatcher (132 bytes, sha256 `2a6e9911...`), assembled at `main+0x655880`. It saves the
  callee-saved registers, reads the mailbox pointer from the clone (`ldr x20, [x19]; ldr x20, [x20, #0x100]`),
  bumps the mailbox `ticks` every entry (E6's live proof the slot fires per frame), performs one request when
  `state == 1` (`blank target = done`, 7 args from `+0x10`, result to `+0x48`, `state = 3`), and **tail-calls
  `main+0x2B6420`** (the unit transform virtual) with the unit in `x0` every time - so the game is unaffected while
  the harness is attached, and a missing mailbox is safe.
- `code.py` - the pinned image plus the one contract for the rest of the harness: `CAVE_AT 0x655880`,
  `CAVE_END 0x656000`, `ORIGINAL_TRANSFORM 0x2B6420`, `SLOT_TRANSFORM 0x20`, clone at `CLONE_AT = 0x655A00`
  (32 copied vtable entries = 0x100 bytes + the mailbox pointer at +0x100 = `CLONE_SIZE 0x108`), mailbox layout
  (`state +0x00`, `target +0x08`, `args +0x10..+0x40`, `result +0x48`, `generation +0x50`, `ticks +0x58`,
  `MAILBOX_SIZE 0x80`), and the state codes.
- `build_dispatch.py` - reproduces the image from `dispatch.S` with keystone, checks size/sha256/pinned bytes,
  disassembles with capstone and asserts the tail call resolves to `main+0x2B6420`; exit 0/1. Run:
  `python -m gbox.mercs.native.re4_82c2a04a.build_dispatch` -> **PASS** (132 bytes, tail 0x2b6420).
- `tests/test_re4_dispatcher.py` (10) - the pinned image reproduces from source (keystone, skipped if absent); every
  word decodes and the tail call lands on the original; the cave, clone alignment and fit are checked; and under
  **unicorn** on a synthetic map: an idle entry ticks and runs the original with the unit, a request calls the target
  with its seven arguments and stores the result (`7+8+9 = 24`), `state` goes requested -> done, a blank target
  completes without a call, a NULL mailbox still runs the original, the callee-saved registers survive (x19-x22,
  x28), and two requests run in sequence. All pass.

**Next**, and the only thing E3 still blocks: the controller (E4's write rule: refuse any write into `.text`/
`.rodata` except `install()` into the cave; E5's fake-emulator tests: install refuses nonzero bytes and a cave with a
reference into it, attach writes only the vtable pointer, a publish is consumed once under the generation guard, a
timeout is `Uncertain` and never replayed). It can be written now with a configurable mailbox; the default page must
wait for E3's three-load zero watch (requested) so no live build ever points at storage the game may use.

## Round 61 (2026-11-10 17:45 CST) - E4/E5 done: the RE4 harness controller, its write rule and offline tests

`gbox/mercs/titles/re4_switch_native.py` now holds the controller on top of the E0(c) dispatcher:

- **The trigger by data (E2):** `attach()` reads the player unit through `S_PLAYER`/`S_PLAYER_2`
  (`re4_switch.player_unit`), refuses any class outside `PLAYER_VTABLE_RANGE`, checks the vtable's slot `+0x20` is
  `main+0x2B6420`, copies 32 entries into a clone, points the clone's slot at the cave dispatcher, installs dispatcher
  + clone into the vetted cave, and performs **one aligned 8-byte store** into `player+0`. `detach()` puts the
  original pointer back. A re-attach is a no-op; a player change while attached is detected by its id.
- **E4, the code rule in code:** `write()` refuses any guest write into `main`'s `.text`/`.rodata`
  (`base .. base+0xAE1BCC`, the header's rodata end) - so the vtable store, the mailbox and every other write can
  only touch heap/`.bss`; `install()` is the only route into code and refuses any target outside the vetted cave
  (`0x655880..0x656000`). The base class's memfd install still refuses nonzero bytes.
- **The mailbox:** `call(off, *args)` publishes target + seven arguments + a generation, then the state word last
  (one 4-byte write), and waits for the dispatcher's `done`; the result is `x0`, a generation mismatch is `Uncertain`,
  and a timeout is `Uncertain` **without a replay** (the next call refuses while the mailbox is not idle/done).
  `ticks()` reads the dispatcher's entry counter - E6's proof that the cloned slot fires every frame.
- **The private storage stays unproven until E3's watch:** `mailbox` is a constructor argument (default `None`), and
  `attach()` refuses with "no proven private storage ... (E3's three-load watch is pending)". No live build can point
  the harness at a page the game might use.

**Tests** (`tests/test_re4_native.py`, 12) on a fake guest with the real layout (player of class `0xB0C0A0`, vtable
slot `+0x20` = `main+0x2B6420`, zero cave, mailbox): the write rule refuses code/rodata; install refuses outside the
cave; attach installs exactly the dispatcher and the clone and writes **only** the vtable pointer; re-attach no-op;
attach refuses without a mailbox, over a nonzero cave, with a changed transform slot, and for a non-unit player
class; a call publishes once and reads the result; a timeout is `Uncertain` and the request is never re-published;
a changed generation is not trusted; an unattached call is refused. With the earlier files: **42 passed** across
`test_re4_caves`, `test_re4_bss`, `test_re4_dispatcher`, `test_re4_native`.

**What is left of checkpoint E:** E3's read-only three-load zero watch (the five candidate pages) to pick the mailbox
page, then **E6**: the RE session runs a no-op call on a live RE4 round (magic word through the mailbox), three stage
loads with the harness attached, frames, and the Citron log - and the cave's presence in the HostMemory mapping (the
controller's `install` already refuses "ambiguous guest backing file", and that answer would be the result).

## Round 62 (2026-11-10 18:10 CST) - checkpoint F's op and placement are built: `flash_at`, `flash_now`, and the status row

**F2, the op.** `Controller.flash_at(x, y, z)` (RE4 millimetres) now runs the game's own flash blast on the game
thread through the harness, route (i) of the guide: a zeroed fake object at `mailbox+0x100` with the point at `+0xA4`
and `+0x3CC` left zero (not 0xD6, so the ground/type check does not skip the effects), then `main+0x2E4E50` through
the mailbox. It refuses a point closer than 4000 mm to him ("never at his feet"). The receipt is
`{state: "confirmed", verified: false, op: "flash_at", effect: "native_flash_blast", pos, from_player_cm}` -
confirmed means the native call returned, `verified` stays false until F4's live receipt (Ganados in range stunned,
his hp unchanged, the bloom on frames).

**F3, where it goes off.** `place_flash(player, enemies)` is `core.flash_window.place` (merged on main) in RE4's
millimetres: min 4000, max 9000, from 12000, level `re4_switch.LEVEL_MM`; `None` when nobody is near. The module op
`flash_now(ad, point=None)` computes that point from a memory shim over the adapter's snapshot and refuses
(`state: unavailable`) when nobody is within 12 m; `Controller.flash()` is the intervention worker's entry.

**F4, the status row.** `grenade_status`'s RE4 Switch entry is no longer "not built": the **flash row is built** -
`Kind(False, "a flash is built on the RE4 Switch native harness (main+0x2E4E50 via one vtable store) but has no live
receipt yet")` - with `controller="re4_switch_native"` (added to `_CONTROLLERS`); the ring kinds stay "does not
offer". `interventions.native_controller` now includes the RE4 Switch module (attribute `_re4_switch_harness`); the
controller's `prepare()` refuses with the E3 reason until the private page is proven, so nothing is advertised before
that. The status/interventions tests are updated to the new contract (the flash row built, hand/incendiary not
offered).

**Tests.** 8 new flash/placement tests in `tests/test_re4_native.py` (20 there): the fake object is written with the
point and a zero type byte, the published target is the flash blast and the first argument the object, the receipt
carries the point and the distance; the at-his-feet refusal writes nothing; `place_flash` pushes to the 4000 mm floor,
keeps within 4000..9000, returns None past 12 m; `flash_now` with a point, on the crowd, and refusing when nobody is
near. A unicorn engine-disposal fixture was added after a Windows atexit crash in the dispatcher tests (the tests
passed; the interpreter exit did not). Broad run of the RE4 harness, the grenade rule/scatter, interventions/worker,
bot logic and the mercs engine: **242 passed**.

**F5 to the RE session:** the RE4 flash op exists on `ds-grenade-re4-bss` (`Controller.flash_at` / `flash_now`), but
**do not wire the doctrine yet** - the harness has no proven mailbox page (E3's watch) and no live receipt. The one
doctrine line is `re4_switch.py` around line 1890, `respond.Kit(fire=fire, flash=None, ...)`, and it is the RE
session's to write after F4 flips the row to verified.

## Round 63 (2026-11-10 18:35 CST) - G1/G2 offline: the flash ring and the hand-grenade ring on the RE4 harness

Starting checkpoint G while the live RE4 block is up (it is still running: session `25385f8f4eb94342-6eb677c2f1194dea`,
round 2/5 at stage 3 - the second stage load; the three-load watch ask is on main).

**`Controller.grenade_ring(kind, count, radius_cm, inner_cm, ripple_ms, expand)`** on the RE4 harness, same contract
shape as RE5/RE6 (the shared rule calls it with cm, the controller converts with `MM_PER_CM`):

- **G1, the flash ring:** N `_blast_at` points on a circle round him, the inner ring at **4000 mm** or more (the
  flash's own floor, enforced by `_blast_at` as well), radius default 9000 mm, count default 10 (max 16), a 40 ms
  ripple; each point is one flash blast (`main+0x2E4E50`) through the mailbox, so the ring is N real effects.
- **G2, the hand-grenade ring:** the same geometry with the hand grenade's blast (`main+0x2E48B0`, class 0x13, radius
  6000 mm from the guide) and a **7000 mm** floor. The learned-blast-reach clamp stays the caller's (the rule's
  radius/inner already carry it; the floor is enforced here too).
- **G3, incendiary:** refused before any call - "the incendiary blast is not identified on this build yet".
- The receipt: `detonated == requested`, `radius_cm/mm`, `inner_cm/mm`, per-point `from_player_cm`/`radius_mm`,
  `hp_before/after` from the player's own life field (`module+PLAYER_LIFE`; `self_damage` 0 when unchanged),
  `elapsed_ms`, `verified: false` until a live receipt. A failed blast aborts with a partial `uncertain` receipt and
  is never replayed.

**Tests:** 4 new in `tests/test_re4_native.py` (24 there): a 4-point flash ring places every blast at 4000-10000 mm
and calls the flash blast four times, hp unchanged; a 2-point hand ring uses the hand blast at 7000 mm or more; the
incendiary ring is refused before any write; a blast that times out leaves `uncertain` with the two that completed.
With the other RE4 harness files and the status module: **73 passed**.

**Still to do for G:** G4 (add the title to `SCATTER_TITLES` and the scatter knobs to `re4_switch.py`, cm/mm at the
controller boundary, the barrage op) and the live receipts per kind - both need F's live receipt first, which needs
E3's watch and the branch deploy.

## Round 64 (2026-11-10 18:55 CST) - G4 offline: the RE4 barrage, its knobs, its PiP rows and the shared rule's step

**The controller's barrage.** `Controller.grenade_scatter(kind="random", count, toward, ..., safe_cm, rng, kinds)` on
the RE4 harness, same contract shape as RE5/RE6:

- kinds **flash** (`main+0x2E4E50`) and **hand** (`main+0x2E48B0`); `"random"` draws both; `kinds=` narrows one
  barrage (the shared flash cap); incendiary refused ("not identified yet", G3).
- units at the boundary: `toward` are the title's own raw (x, z) **millimetres** (straight from its snapshot), while
  `safe_cm` (the rule's learned reach) is converted with `MM_PER_CM`; each round keeps its own floor - flash
  **4000 mm**, hand **7000 mm** - and the learned reach plus one cm. The cone's axis comes from the threats' centre
  (else his facing), the far bound is the threats' reach + 2 m, points run near to far 100-200 ms apart.
- receipt: `detonated == requested`, `kinds`, `rounds[].kind/dist_cm/from_player_cm`, `near_cm/far_cm/floor_cm/
  floors_cm`, `hp_before/after` from his own life field, `self_damage`, `elapsed_ms`, `verified: false`; a partial
  barrage is `uncertain` and never replayed.

**The title and the rule (G4).** `re4_switch.py` carries `RING`/`RING_N`/`RING_EVERY_S`/`RING_KIND` and
`SCATTER`/`SCATTER_EVERY_S`/`SCATTER_N`, both automatic paths **off** until a live receipt per kind (the ops stay
available for clicks/probes), `SCATTER_FLASH_ONLY = False` (flash and hand are both built, so the cap narrows the draw
rather than refusing it) and `scatter_kinds()` -> `("flash", "hand")`; `bot_logic.KNOBS["re4"]` gained the three
SCATTER rows; `grenade_ring.SCATTER_TITLES` now includes `010099A00BC1E000`, so the shared rule offers RE4 its step
and the policy reads the title's kinds.

**Tests.** 6 new barrage tests in `test_re4_native.py` (30 there): a random barrage uses both blasts and both floors,
an explicit hand barrage uses only the hand blast at 7000 mm or more, `safe_cm` becomes the 1000 cm floor, a narrowed
draw uses one kind, the incendiary and an unknown draw are refused before any write, a failed round leaves the barrage
`uncertain`; and `tests/test_re4_scatter_wiring.py` (4): the title is built-but-off with both kinds, the rule offers
RE4 its step and not a PS3 title, the policy reads the knobs/kinds, and the PiP rows exist. With the earlier RE4
harness and shared-rule files: the focused set is **53 passed**; the broad run is in the same round's log below.
