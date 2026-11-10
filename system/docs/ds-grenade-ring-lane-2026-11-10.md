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
same never-executed padding tail as the four shipped images. `tools/verify_re6_classes.py` checks them against the
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
