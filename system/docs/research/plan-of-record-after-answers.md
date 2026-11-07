# Plan of record after the operator's answers (2026-11-07)

`system/docs/questions-for-the-operator.md` carries the answers (commit `9d87558f`). This is what each one changes here,
and the first measured result owed on each.

## 1. Dumps: mine to take, read-write ranges only

Cleared, with the constraint stated plainly: **no decrypted executable, ever** - so the dump covers `rw` pages (heap,
`.data`, `.bss`) and never the module's read-only or executable pages. The anchors do not need them.

Procedure, as answered: three dumps in one **proven-live** round - A with the clock counting, B three to five seconds later
for differential search, C just after a hit seen on a frame - stored under `~/gBox_alt/scratch/agent/re4sw-dumps/`, at
most three sets, never in git. `job_ram_dump session_id=<sid> budget_s=60` first; if it comes back partial on Switch (its
header says what is missing), loop `GET /api/sessions/{sid}/ram/hex` over the mapped `rw` rows that
`re4_switch._rows` lists.

**The probe defect is fixed** (`system/tools/probes/probe_re4_live_measure.py` unpacks `api()`'s `(status, payload)`); the
older `probe_re4_measure.py` still has it and is the next fix.

## 2. The collection is a tool, not a directory

`job_characters op=list kind=character`, `op=get character=<slug>` - `gbox/cast_roster.py` and `gbox/cast_swap.py`. That is
the answer to "where are the Sonic/Mario/DOA models": the roster, with each entry's rig readiness. Approved for runtime
mod builds on the operator's machines; nothing built from them is published, shared or committed, and extracted assets stay
out of git.

## 3. Switch titles: a clean character or nothing

The operator chose the harder option, and it is now the target: **a shape change is not the deliverable.** Keep pushing on
the part-table rules until a clean character draws. Every research pass must end with a measured **drawn / not drawn**, a
real frame, and a note in `docs/research/`. That rules out the "giant Ganado is progress" framing: on the Switch titles it
is a probe result, not a deliverable.

## 4. No live player needed

An idle Leon is hit within 15-20 s of the round starting. So: snapshot (or dump A) in the first seconds, let Leon stand,
**confirm the hit on a frame**, and only then sample `decreased`. That removes the main failure mode of the last three
health attempts - sampling a change that had not happened yet.

## 5. Mercenaries 3D stays on the i9-NUC; RE4 VR is parked

* Mercenaries 3D: RetroArch `citra_libretro`, RAM through `gbox.citra_memory`, catalog `0ed22ae742e1b56b`, EUR title
  `0004000000038B00`, driver `gbox.mercs.titles.merc3d_3ds`. **No Spark port.** The i9-NUC's own loop has played it.
* RE4 VR: research only from here. The extracted paks stay; no runtime work.

## 6. Disk

180 GB free is enough. I may delete only my own scratch under `~/gBox_alt/scratch/agent` (41 GB today), must stop and ask
below 100 GB, and never touch the operator's games, saves, keys, firmware or builds.

## The Sonic GameCube build: what was actually in it

While waiting on the answers I checked the build that claimed to be Sonic, and it was not:

```
re4gsonic1512/re4-d1.iso   md5 ca749757e3b9d119f3feb1f9f0f81bd7
re4-lab/gc/re4-d1.iso      md5 ca749757e3b9d119f3feb1f9f0f81bd7   <- byte-identical: no Sonic in it at all
```

The patched player archives do exist, separately (`re4-lab/re4gc-sonic/pl00,pl08,pl09,pl10.drs`), so the disc was never
patched. A real build was made (`re4gsonic_real`): the four archives written into a copy of the disc at their FST offsets
(`em/pl00.drs` 240678972, `em/pl08.drs` 253162716, `em/pl09.drs` 255386332, `em/pl10.drs` 269492540), each shorter than
its disc entry and therefore padded with zeros to the entry size - a DRS is read through its own entry table, so the
padding is never addressed.

**That build did not launch a session**, and the run script's failure left the host idle until the rotation was restored by
hand. So: the injection is done and verified at the byte level, the *launch* is not, and that is the open item - not the
model work.

## Order of work from here

1. Launch `re4gsonic_real` and get a frame: Sonic drawn or not drawn, recorded either way.
2. The three dumps, then offline search for the clock, the enemy array and the player - the accelerant the answers made
   possible.
3. The Switch part-table rules, with the clean-character bar.

## The Sonic GameCube build: it launches now, and Sonic is not drawn (2026-11-07)

**Why the first attempt never ran.** `filemods.launch_path` resolves a mod build to `meta["image"]` when that key is set,
and otherwise to `mod_dir / <the library's own file name>`. This game's library file is
`Resident Evil 4 (USA) (Disc 1).gcz`, so an ISO dropped into the build folder was never the file Dolphin opened:

```
FileNotFoundError: .../mods/78ab9efa2e310db4/re4gsonic_real/Resident Evil 4 (USA) (Disc 1).gcz
```

Setting `"image": "re4-d1.iso"` in `.gbox-mod.json` fixed it: the launch returned 200, a session appeared, and the
GameCube bot played a Mercenaries round from it.

**What is on screen.** Stock HUNK, `01'57"33`, the dock stage - a real round, no Sonic:

![stock HUNK in the patched build](evidence/re4gc-sonic-build-stock-hunk.jpg)

**What is verified about the patch.** The four archives in `re4-lab/re4gc-sonic/` are genuinely different from the disc's
originals - 185,027 to 189,909 bytes differ in the first 200 KB alone, and every one is shorter than its disc entry (which
is why they were zero-padded to the entry size). The writes landed at the FST offsets:

```
em/pl00.drs 240678972 | em/pl08.drs 253162716 | em/pl09.drs 255386332 | em/pl10.drs 269492540
```

**So the failure is one of two things, and they are distinguishable:**

1. the Mercenaries slot that draws HUNK is **not** one of `pl00/pl08/pl09/pl10`, so nothing patched was ever asked for; or
2. a rebuilt DRS is **not accepted**, and the game falls back to the model it already has in memory.

The next experiment separates them without a rebuild: patch **one** slot with a change that must be visible if it is read
(a same-size vertex scale on the player model), and if that does not draw either, the writer is the problem rather than the
slot map. A round-trip write of the *original* bytes is the control: if the game still plays after a byte-identical
rewrite, the padding-and-write path is sound.

**What this costs and what it doesn't.** The model work is not the blocker here - the archives exist and the injection is
byte-verified. The blocker is identifying which archive the drawn character comes from, which is a lookup in the game's
own loader, not a modelling problem.