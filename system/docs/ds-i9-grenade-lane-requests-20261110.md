# i9 grenade lane - requests for the PM, 2026-11-10 15:45 CST

From the DeepSeek session on the i9 (grenade-ring lane, guide
[`DEEPSEEK-GRENADE-RING-CHECKPOINTS-2026-11-10.md`](DEEPSEEK-GRENADE-RING-CHECKPOINTS-2026-11-10.md)). Per your
instruction this doc is the request for your service; the lane's work stays on its branch
([`ds-grenade-ring-lane-2026-11-10.md`](ds-grenade-ring-lane-2026-11-10.md)).

**Short:** checkpoint 0 of the guide is built, tested and pushed as one branch. Two things are outside my reach: (1)
the merge + `gbox.service` restart that makes it live on lilspark, and (2) the RE4 Switch base content, without which
checkpoints E/F cannot start. A third, optional item is a read-only capture for the RE6 launcher.

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

## 2. The RE4 Switch base content on the i9 (checkpoints E1 and F1)

- I have only the **update 1.0.2 NSP**: `D:\gBox\cache\270a15eb98dab4d7\Resident Evil 4 [UPDATE 1.0.2]
  [010099a00bc1e000].nsp`. It carries no ticket, so the extractor answers *"no ticket in the container: a title key
  cannot be derived"*. There is no base NSP on the i9's drives, and JAYBUILTFINALE's shares are not reachable from the
  i9.
- what I need: the **base** content for `010099A00BC1E000`, copied onto the i9 read-only - either the base NSP or the
  extracted `main` (a file `main` plus its `main-*.nso` name if possible). A path such as
  `D:\gBox\cache\re4-base\` is perfect; just say where it is.
- I will check it against the guide's constants: build `82C2A04A21D3E0B850F273D4149C9003`, NSO sha256
  `98ca897f07b2c864a0cabfb9dd8ca46a54b88c565ba629da3b7a4b6a57a57441`. Then E1 (find the never-executed zero cave and
  prove no branch/literal targets it), E2 (the player unit's vtable trigger) and F1
  (`re4_switch_blasts.verify`) can run offline on this box.
- no toolchain decision is needed: capstone 5.0.7 and unicorn 2.1.4 are installed, so the hand-encoded route (E0(c))
  works.

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
