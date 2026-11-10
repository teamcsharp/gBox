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
