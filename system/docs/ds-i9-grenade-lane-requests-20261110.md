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

