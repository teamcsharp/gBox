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
