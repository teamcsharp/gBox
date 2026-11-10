# i9 grenade lane - requests for the PM, 2026-11-10 15:45 CST

From the DeepSeek session on the i9 (grenade-ring lane, guide
[`DEEPSEEK-GRENADE-RING-CHECKPOINTS-2026-11-10.md`](DEEPSEEK-GRENADE-RING-CHECKPOINTS-2026-11-10.md)). Per your
instruction this doc is the request for your service; the lane's work stays on its branch
([`ds-grenade-ring-lane-2026-11-10.md`](ds-grenade-ring-lane-2026-11-10.md)).

**Short:** checkpoint 0 of the guide is built, tested and pushed as one branch. Two things were outside my reach: (1)
the merge + `gbox.service` restart that makes it live on lilspark, and (2) the RE4 Switch base content. **Item 2 is
already resolved** (see its section - the Spark's own extracted `main.bin` was on its home share and is now copied
read-only onto the i9; F1 passes and E1's cave is vetted). What remains for your service is item 1 (the merge +
restart) and the optional item 3 (a read-only RE6 launcher capture).

## 1. Merge and restart one branch (checkpoint 0's acceptance)

- branch: **`ds-grenade-merge-20261110`** (pushed; tip `24319c66`; the code is `5068b945`, then this round's merge of
  main + docs). It is based on today's main `2564c0a1`; the merge was checked clean and the full checkpoint-0 test
  list gives **219 passed, 0 failed** on the merged tree.
- what it fixes, from the guide's three checked defects:
  1. the probe route's explosive rounds now start at 600 cm (they were at 300, inside their own blast);
  2. RE5 tolerates an emulator still running the old spawn/explode pair (flash keeps working; hand/incendiary answer
     "pre-class pair" until that emulator restarts) - no executed instruction is ever rewritten;
  3. RE5's automatic barrage is off until its flash-cap work lands (the op still advertises, so probes/buttons work).
- the ask, in one gap at a round boundary (no live game):
  1. merge the branch to main (the RE session's merge is the protocol; if it is busy, please route this to it, or do
     it yourself - it is a plain merge, no deploy scripts beyond the restart);
  2. `gbox.service` restart on lilspark in the same gap (the restart loads `interventions.py` and the new
     `classes.py` modules; a fresh RE5 emulator then gets the class pair).
- after that I will ask the RE session (or you) for the two status reads and one RE5 flash; the guide's checkpoint-0
  acceptance is exactly that. Until it is deployed nothing I do can produce a live receipt.

## 2. The RE4 Switch base content on the i9 (checkpoints E1 and F1) - RESOLVED 15:58 CST

**Resolved, no action needed.** The Spark's decrypt-lab had already extracted the same update NSP
(`GET /api/decrypt-lab/state`: `main-82C2A04A21D3E0B850F273D4149C9003.nso`), and its extracted `main.bin` was on its
home share, so I copied it read-only to `D:\gBox\cache\re4-base\main.bin` (11,716,664 bytes; the raw NSO as
`main.nso`). It is the right build: the 64-byte signature at `main+0x100000` matches, and
`re4_switch_blasts.verify` passes on it. F1 is done, and E1's cave is found and vetted at `main+0x655880` (1920 bytes,
64-byte aligned, all zero, no branch/literal references) with the new `scripts/verify_re4_caves.py` and its 10 tests.
One honest note: the documented `MAIN_NSO_SHA256` (`98ca897f...`) is Citron's 30,146,816-byte `dump_nso` form; this
expanded image hashes differently because its header was rewritten and .bss padding is absent, so the signature and
the blast anchors are the identification. The old request text follows for the record: the i9 had only the ticketless
update NSP; the base content is now here.


## 3. Optional: one read-only capture for the RE6 launcher (checkpoint B)

The guide's B1 static scan does not hold on the pinned image (I checked it: no shell class DTI is ever materialised,
and `0x3BCF90` is only our own compiled spawn image's link-time veneer to `0x359270`). The guide's own fallback is a
read-only capture in an RE6 round whose character carries the grenade launcher (item `0x112`, loadouts `0x1004` /
`0x0206`): right after one real shot, the shell object's class vtable, owner, action class, position and the
`+0x3880..+0x3960` range. Nothing is written and no probe is fired. If the RE session can take that capture in a
normal RE6 block, B1/B2 can continue; details are in the lane log's 15:40 request.

## What is done and where the evidence is

- checkpoint 0: code `5068b945` on the branch above; 219 passed on main `2564c0a1`; the result section and the two
  requests are in the lane log on the branch (14:25, 14:32, 15:30, 15:40).
- the lane log also holds round 52's B1 negative evidence (the scans and the class-info records with their DTI
  getters) and the RE4 request above in its own voice.
- nothing from this lane touched main except this one doc, as you asked; no write of any kind has gone to lilspark.

## PM response, 2026-11-10 ~16:45 CST

- **Item 1 is merged to main** as `ds-grenade-merge-20261110` (tip e621f849), via the merge commit before 4fab1f3e.
  - Today's main already carried the RE6 / RE5 flash-cap work (ef438820: `core/flash_window.py` FlashGate, `FLASH_MIN_GAP_S` = 60 s, the RE6 tight-situation reasons).
  - Your branch merged on top of it with no conflict.
  - The targeted tests passed: 629, 0 failed (grenade ring / scatter / class tables / pair fallback / RE5 / RE6 Switch / respond / live controls).
- **One change to your branch.** The pre-push guard publishes nothing under `system/tools/`, so `verify_re4_caves.py`, `verify_re5_classes.py` and `verify_re6_classes.py` now live in `system/scripts/`. The tests, `classes.py` and these docs point there (4fab1f3e).
- **Deployed to lilspark's share.** A `gbox.service` restart is armed for the end of the current RE6 MercMode block. It loads `interventions.py` / `classes.py`; the next RE5 emulator is a fresh one, so it gets the class pair.
- **RE5's automatic barrage stays off**, as your branch set it. The flash cap it was waiting for is now live, so turning it back on (on the gate) is your next RE5 step, on a branch.
- **Acceptance reads.** The coordinating Claude session may be offline when the restart lands. Ask the operator for the two status reads and the one RE5 flash, or leave the exact read-only calls here for the next session.
- **Item 3** (the RE6 launcher capture) is not done yet.

## i9 follow-up, 2026-11-10 16:40 CST - checkpoint D is on a branch, and the restart window

**Checkpoint D is ready: branch `ds-grenade-re5-scatter-cap-20261110` @ `1bd0daed`** (cut from main `53cc8962`).
RE5's automatic barrage is back on **under the one flash clock** the flash-cap work brought:

- an all-flash barrage is refused while `FLASH_MIN_GAP_S` is closed (the ring's own reason, `flash_gap_skips` counted);
- a mixed draw (once checkpoint C verifies hand/incendiary) leaves the flash out of the barrage inside the gap instead
  of refusing - `scatter_kinds()` on both titles is the one place that list comes from, and a test pins
  `SCATTER_FLASH_ONLY == (scatter_kinds() == ("flash",))` so C cannot forget it;
- a confirmed flash round stamps `native_flash_confirmed_at` - the bot's own rules then wait the minute; a confirmed
  **operator click** on the scatter op stamps it too (the ring already did);
- `re5_switch.SCATTER = True` (D2). `kinds=` narrowing is validated in both native controllers before any native work.
- tests: focused **80 passed**; broad (the CP0 list plus flash-window / aim-book / re6-bomb-mind / re5 autogrenade /
  RE4 cave verifier) **247 passed, 0 failed**. No known-red file is touched.

**The ask.** Merge D **before the armed restart fires, if it has not yet** - then the single restart loads checkpoint 0
*and* D (`interventions.py` carries the operator-click stamp, so D cannot skip it). If the restart has already run,
merge D and schedule one more restart in a gap. The live acceptance for D is one RE5 barrage receipt after that merge
(detonated == requested, flash rounds >= 400 cm, self-damage 0, frames, kill delta) and a block whose confirmed
flashes are all >= `FLASH_MIN_GAP_S` apart.

**Checkpoint 0's acceptance is still open on my side**: the two status reads (RE5 and RE6) and one RE5 flash after the
restart. I can take the two read-only status reads from the i9 myself the moment the new service is up
(`GET /api/sessions/{sid}/interventions` via 10.89.1.246, the pre-restart baseline is captured); the **one RE5 flash
still needs the operator/RE session** (or a named session + window, then I may POST that one intervention). No write
of any kind has gone to lilspark.

**Status note, 16:47 CST.** The armed restart has not landed yet: GET /api/mercmode still shows the same RE6 No
Mercy session (78012a3fd3b146ba-f28ad0a196164cfb, started 15:56) in playing with mercmode_rounds_played = 1 for
about 45 minutes, so the block has not reached its end. If it is stuck, one restart in a gap would clear it and load
checkpoint 0 (+ D, if merged first) in one go; the read-only check above is all I can see from the i9.

## i9 follow-up 2, 2026-11-10 16:50 CST - E3's read-only .bss watch (and the state of the two pending items)

**E3 static half is done, on branch `ds-grenade-re4-bss-20261110` @ `2ac050db`** (from main `f1363f65`; no merge or
restart is needed for it). New `scripts/verify_re4_bss.py` + `tests/test_re4_bss.py` (10): it collects every static
reference into RE4's `.bss`, finds the unreferenced 4 KiB pages and vets a chosen one. On the operator's image:
**10,285 static references**, **4,381 free pages**, and a **3.4 MB unreferenced stretch at `0x1681000..0x19C0300`**.
Statically vetted candidates: `0x1700000`, `0x1681000` (large stretch), `0x1CB2000`, `0x1CB9000`, `0x1CBA000`,
`0x1CBB000`, `0x1CBC000` (tail).

**The ask (read-only, no game change):** during one RE4 Mercenaries round on lilspark, read these pages at **three
stage loads** - round start, mid-round after a restart, and the next stage:

    addresses: 0x1CB9000, 0x1CBA000, 0x1CBB000, 0x1CBC000, 0x1700000   (16 bytes each; a full 4 KiB page is better)

All zero on all three reads = that page becomes the harness's private storage (E3 done); any nonzero byte rules it
out. A register-indexed or run-time pointer into a page is invisible to the static scan, which is why the watch is the
second half. If no page passes, the fallback is RE4's own allocator (not identified yet) - I will say so in the lane
log.

**State of the two pending items (unchanged as of 16:50):**
- **D branch `ds-grenade-re5-scatter-cap-20261110` @ `1bd0daed` is still unmerged**, and the armed restart has still
  not fired: `GET /api/mercmode` shows the same RE6 No Mercy session from 15:56 in `playing` with one round played.
  If both are merged before one gap restart, a single restart loads checkpoint 0 and D together.
- **CP0 acceptance** (two status reads + one RE5 flash) waits on that restart; I can take the reads read-only from
  the i9, the flash needs the operator/RE session (or a named session + window).

## i9 follow-up 3, 2026-11-10 17:02 CST - checkpoint 0's RE6 read is in; two asks for the coming RE4 / RE5 blocks

**The restart landed with D merged** (`e317ff6d` / `eae1bb86`; new worker id `8cf47f44...` at ~16:54). The stale RE6
session is gone. **Checkpoint 0's RE6 acceptance read is done** - session `8cf47f441c5041fa-20b2f78a64564e4d`
(RE6 No Mercy, Jake):

    available=True, capabilities = flash_now, equip_primary, grenade_ring, grenade_scatter, magnum_quick4,
                                     set_infinite_ammo
    flash       available=True       (the RE6 stale-base "no living player" bug is gone on the fresh controller)
    hand        available=False      "... not yet verified on this build (uWp1091 is known; the compiled spawn image
                                      pins the flash's class)"
    incendiary  available=False      same, for uWp1093

**Two asks, both read-only and both fitting the next blocks.** The MercMode queue after the current RE6 block is
`re4 x5, re5 x5, re4 x5, re6 x5`:

1. **E3's zero watch, during the next RE4 block** (the first `re4 x5`). Read `0x1CB9000`, `0x1CBA000`, `0x1CBB000`,
   `0x1CBC000`, `0x1700000` at **three stage loads** of one round (round start, mid-round after a restart, next
   stage); all zero on all three = that page becomes the harness's private storage. 16 bytes each is enough, a full
   4 KiB page is ideal.
2. **The one RE5 flash, during the `re5 x5` block after it.** Either the operator's PiP click or a named session +
   window so I may POST that one intervention from the i9. In the same block I will take the **RE5 interventions read**
   (the second checkpoint-0 acceptance read) and, for checkpoint D's live acceptance, the telemetry's
   `scatters_fired` / `scatter_rounds` / `scatter_kills` and the confirmed-flash times (they must be at least
   `FLASH_MIN_GAP_S` apart).

No restart is needed for either ask; both are reads (plus, for the flash, whatever the operator normally clicks).

## i9 follow-up 4, 2026-11-10 17:52 CST - E4/E5 are done; the only thing the RE4 harness now waits on is the three-load watch

**The harness is complete offline** (branch `ds-grenade-re4-bss` @ `ffea2d0c`): E0(c) dispatcher (132 B at
`main+0x655880`, tail-calls the game's transform), E4's rule (`write()` refuses `main`'s `.text`/`.rodata`; only
`install()` into the vetted `0x655880..0x656000` cave), E5's controller (clone-vtable trigger by one 8-byte store,
mailbox publish/consume, generation guard, `Uncertain`-and-never-replayed timeouts) - **42 passed** across the four
RE4 harness test files. Its mailbox is deliberately unset until E3's watch passes.

**The one blocker is a read-only watch, and it needs an RE4 round.** The MercMode queue has `re4 x5` waiting behind
the current RE6 No Mercy block, and that block is a long survival round (296 kills / 1.35 M at 17:50, no round
boundary yet). Could you either:

- put a **short RE4 block (or a single RE4 round)** in front for the watch, then the RE5 block for checkpoint 0's
  remaining read + the one flash; or
- tell me a named RE4 session + window and I will ask the RE session to run the read-only watch (it is just five
  16-byte reads at three stage loads: `0x1CB9000`, `0x1CBA000`, `0x1CBB000`, `0x1CBC000`, `0x1700000`).

Everything else on my side is ready: with a passing page, the harness's mailbox can be set and E6's no-op magic-word
call / three-stage-load proof can be requested on the same RE4 round. No restart and no code change is needed for the
watch itself.

## i9 follow-up 5, 2026-11-10 18:12 CST - F2/F3/F4 are built on the branch; the queue is idle, so an RE4 round can start now

**The RE4 flash op is built** (branch `ds-grenade-re4-bss` @ `b930948e`): `Controller.flash_at(x, y, z)` runs the
game's own blast (`main+0x2E4E50`) through the harness with a zeroed fake object at the point (F2 route (i)),
refusing a point inside 4000 mm; `place_flash` / `flash_now(ad)` use `core.flash_window.place` in millimetres (4000 /
9000 / 12000, `LEVEL_MM`), and `grenade_status` now shows the RE4 Switch flash row as built with "no live receipt
yet" (ring kinds not offered). The controller is wired into `interventions.native_controller`; its `prepare()` still
refuses with the E3 reason, so nothing is advertised live before the private page is proven. Tests: 20 in
`test_re4_native` and the status/interventions expectations updated; broad run **242 passed**.

**Live state:** `GET /api/mercmode` shows **no current run** on lilspark (the RE6 block ended; the queue's `re4 x5`
has not started). If you start an RE4 block now, the same round can carry:

1. the read-only **three-load zero watch** of `0x1CB9000`, `0x1CBA000`, `0x1CBB000`, `0x1CBC000`, `0x1700000`
   (16 bytes each is enough) - the last piece of E3; and then
2. E6's no-op harness proof and F's live receipt, which need the mailbox set from a passing page.

No restart and no merge is needed for the watch itself; the branch is ready and its tests are green. Nothing has
been written to lilspark.

## URGENT WINDOW, 2026-11-10 18:20 CST - the RE4 block is live: the three-load watch can run now

`GET /api/mercmode` shows a live RE4 Switch Mercenaries block:

    session: 25385f8f4eb94342-6eb677c2f1194dea
    character Krauser, stage 2, round 1/5, mod recovery-re4-fit-v4-20261110
    telemetry: screen=playing, kills=0, threat_lacks_flash=369        <- the exact F metric, baseline 369

The rounds rotate stages, so **three stage loads fit in this block**. Please ask the RE session (or run yourself)
this read-only watch while the block lasts:

    read 0x1CB9000, 0x1CBA000, 0x1CBB000, 0x1CBC000, 0x1700000
    now (stage 2), at the next round's load (stage 3), and at the round after (stage 0/1)
    16 bytes each is enough; a full 4 KiB page each is better

All zero on all three reads = that page becomes the harness's private mailbox (E3 done), and the next RE4 block can
run E6's no-op proof and F's live flash receipt. Any nonzero byte rules that page out.

**After the watch:** merge `ds-grenade-re4-bss` @ `b930948e` (it has E0(c)/E4/E5/F2-F4 and its tests are green:
242 passed) and restart `gbox.service` in a gap, so the next RE4 block can exercise the harness. The doctrine line
(`respond.Kit(fire=fire, flash=None, ...)`) is the RE session's to write after F's receipt flips the status row to
verified.


**Block progress (18:36):** the RE4 session is at round 2/5, **stage 3** - that is the second stage load, so a read
taken now plus one at the next stage completes the three-load watch within this block. Still read-only, five pages,
16 bytes each.
