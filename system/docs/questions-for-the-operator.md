# Questions for the operator

Written 2026-11-07. Each question says **why it blocks** and **what it unblocks**, so it can be answered without reading
the rest of the research. Nothing here is a request to do the work for me - it is the handful of facts only the operator
has.

## What I need most, in order

### 1. A full guest-memory dump of one live RE4 Switch round

**The ask.** With the rotation paused and RE4 Switch in a live Mercenaries round, capture the whole guest memory region to
a file on the Spark (it looked like a few hundred MB; the adapter can already read it, so this is a loop over the mapped
ranges, not a new tool).

**Why.** Every anchor attempt costs a boot (~6 min) and 3 of the last 5 boots ended somewhere other than a round. A dump
turns that into offline analysis: I can search for the clock, the enemy array and the player object as often as I like,
against a round I know was live, and only boot again to *verify* a candidate.

**What it unblocks.** `S_PLAYER`, `S_EMMGR` and `S_MERC` - the three things the MercMode document says are missing, which
is what stops RE4 Switch aiming and reporting a rank.

### 2. The collection: where the Sonic/Mario/DOA models live, and which are approved

**The ask.** A path (or a library id) for the extracted models/rigs/animations that may be used at runtime, and which
characters are approved for a runtime replacement versus research only.

**Why.** The objective asks for zombies replaced by Mario/Sonic/DOA characters from the collection, and "any models that
have had their rigs/animation extracted". I have not found the collection's manifest, so I cannot tell which titles are
present, what format the rigs are in, or which are safe to publish in a mod.

**What it unblocks.** Wiring a donor into a title: for RE4 GameCube a real rigged model works today (`re4gc_zombies`
plays), so the collection is what decides whether that becomes Sonic or stays the dog.

### 3. A decision on what "Sonic in the Switch titles" means, given the engine's limit

**What I measured.** On RE4 Switch the engine draws a slot's **own topology**: a rebuilt mesh with a different vertex
count is accepted by every offline check I can make and simply not drawn, while a same-topology vertex edit is drawn
(giants, and the bone-morphed enemies in `docs/research/evidence/`). RE5/RE6 Switch have the same class of limit at the
part table.

**The question.** For the Switch titles, is the acceptable deliverable (a) a **shape change** toward a donor - recognisable
as "not a villager", not as a clean Sonic - with the clean version delivered on a title that can take it (RE4 GameCube
today), or (b) do you want me to keep pushing on the Switch part-table rules until a clean character is possible, which is
open-ended research?

**Why it matters.** (a) can be demonstrated in a round this week. (b) is the honest path to the literal request but has no
measured way forward yet.

### 4. Live input for two minutes, once

**The ask.** Someone plays RE4 Switch for ~2 minutes while I read memory: take damage, then pick up an item.

**Why.** Health and item state are the easiest anchors to confirm by behaviour ("it fell when I was hit"), and the two
failure modes I keep hitting are (i) nothing actually damaged the player and (ii) a `decreased` sample with no change
empties the search.

**What it unblocks.** The health anchor without a dump, and a cross-check on the dump approach above.

### 5. Mercenaries 3D and RE4 VR: which runtime is the target

**The ask.** For **Mercenaries 3D**: which emulator and which ROM (region, path). For **RE4 VR**: is there a Windows
worker that can run the Quest build (the research note calls it the RefractAdapter path), or is the target streaming from
a headset, or an Android-x86 image on the Spark?

**Why.** "Fully deconstructed and playable in merc mode on the Spark" has three different answers depending on the runtime,
and each is weeks of work. I have the VR paks readable (`docs/research/re4-vr-extraction.md`) but nothing to run them on.

### 6. Disk space

**The ask.** Approval to free space, or confirmation that 181 GB free is enough. The filesystem is at **95%**.

**Why.** The VR package is 8.4 GB, RE4 Switch 20 GB, and model-swap experiments write multi-GB mod builds. A dump (item 1)
adds more.

## Things I do not need help with

* reading the formats - the RE4 Switch containers, BIN meshes, textures and the FEN archives are decoded and byte-identical
  on round-trip;
* the MercMode wiring for RE4 - the nine gates from `docs/mercmode-adding-titles.md` are applied;
* the decrypt tooling - hactool, Ghidra (arm64 decompiler built here), REA and the integrations box all work and are
  callable by routes and by agents.

## What I would do with the answers, in order

1. **Dump + offline search** (item 1) -> `S_PLAYER`/`S_EMMGR`/`S_MERC` -> RE4 Switch aims and reports its rank; the bot
   stops playing blind.
2. **Collection manifest** (item 2) + the decision (item 3) -> a Sonic donor aimed at RE4 GameCube (where a rigged model is
   drawn) while the Switch titles get the shape change they can take.
3. **Runtime decision** (item 5) -> pick one of Mercenaries 3D / RE4 VR and commit to it rather than both.

## One technical note for the record

The probe written this round (`system/tools/probes/probe_re4_measure.py`) reached a **proven-live round** (the clock's
corner of the frame changed between two samples) and restored the rotation in a `finally`. Its two measurements returned
no candidates, which is a defect in how it reads the search API's reply, not a result - it is the first thing to fix next
round, and it is why I am asking for a dump rather than more boots.

---

## Answers (operator, 2026-11-07)

Items 2, 3, 5 (RE4 VR) and 6 are the operator's decisions. Items 1, 4 and 5 (Mercenaries 3D) needed no operator input, and
are answered from the code and the live MercMode status. The operator's standing permission of 2026-11-06 still applies:
pause the rotation, restart, commit and deploy as the goals need.

### 1. Memory dump: do it yourself

No operator action is needed. You are cleared to take the dumps.

- **Writable ranges only** (`rw` pages: heap, `.data`, `.bss`). Leave out the module's read-only and executable pages. Agents
  must never produce the decrypted game executable in any form, and the anchors don't need it.
- Try `job_ram_dump session_id=<sid> budget_s=60` first. It is built around a main-RAM layout and may come back partial on
  Switch: its header says what is missing. If it does, loop `GET /api/sessions/{sid}/ram/hex` (or the adapter's reads) over the
  mapped `rw` rows, as `re4_switch._rows` lists them.
- Take three dumps in one proven-live round, each with a real frame saved beside it:
  - A: the clock is counting;
  - B: 3 to 5 s later, for differential search;
  - C: just after a hit you have seen on a frame (see item 4).
- Store them under `~/gBox_alt/scratch/agent/re4sw-dumps/`, never in git. Keep at most three sets.
- Pause and restore in the documented order: `enabled=false` first; when restoring, `enabled=true` **before** stopping the
  test session.

### 2. The collection: it is the `characters` tool

The collection already exists: `job_characters op=list kind=character` lists it, and `op=get character=<slug>` gives one entry
with its rig readiness (code: `gbox/cast_roster.py`, `gbox/cast_swap.py`).

**Approved: any collection character with an extracted rig may be used in runtime mod builds on the operator's machines.**
Nothing built from them is published, shared or committed. Extracted models and game assets stay out of git.

### 3. Sonic in the Switch titles: keep pushing for a clean character

The operator chose (b): **a shape change is not the deliverable for the Switch titles.** Keep working on the Switch part-table
rules until a clean character draws.

Every research pass must end with a measured result: drawn or not drawn, with a real frame, recorded in
`docs/research/`. The order in "What I would do with the answers" stands. Only the Switch target changes.

### 4. Live input: not needed

You don't need anyone to play. An idle Leon is hit within 15 to 20 s of the round starting: the first Ganados arrive then
(`re4-switch-integration-plan.md`, measurement trap).

1. Take the search snapshot (or dump A) in the first seconds of the round.
2. Let Leon stand still.
3. Confirm the hit on a frame: the red flash, or the health display dropping.
4. Only then sample `decreased`.

Item pickups need kills, so leave them until the shot works.

### 5. Runtimes

**Mercenaries 3D: already set up, and the target stays the i9-NUC.** No Spark port was requested.

- Emulator: RetroArch `citra_libretro`, with RAM through `gbox.citra_memory`.
- Catalog id: `0ed22ae742e1b56b`. The "(USA)" 7z holds the EUR image, title `0004000000038B00`.
- ROM: `/mnt/gbox/hyperspin/Arcade/collections/Nintendo 3DS/roms/Resident Evil - The Mercenaries 3D (USA).7z`.
- Driver: `gbox.mercs.titles.merc3d_3ds`.
- The i9-NUC's own MercMode loop has played it.

**RE4 VR: parked.** Keep the extracted VR paks as research only, and do no runtime work on it.

### 6. Disk: 180 GB free is enough

- Delete only files you created yourself under `~/gBox_alt/scratch/agent`, which is 41 GB today.
- Stop and ask before free space falls below 100 GB.
- Never delete the operator's games, saves, keys, firmware or builds, `cast-inverted` included.
- The old 360 GB cache the operator approved for deletion on 2026-10-13 is already gone.

### The probe defect

Agreed: fix how `probe_re4_measure.py` reads the search API's reply before trusting any "no candidates" result.
