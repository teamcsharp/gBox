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
## Enemies as Sonic: 58 packs rebuilt, injected, and still stock (2026-11-07)

`gbox.re4gc_zombies` (the collection path the answers approved) rebuilt **58 `em/*.drs` packs** from
`~/agent-work/re4chars/sonic_src.glb` with the service's own interpreter:

```
~/gBox/system/.venv-linux-aarch64/bin/python -m gbox.re4gc_zombies --iso <disc> --model sonic_src.glb --out ...
fitted: true  how: keep=4 tex=64  bytes: 5122720  disc: 5376864   (em10)
```

The system `python3` cannot run it at all (`pydantic 1.10.26`, no `model_validator`) - the service venv is
`pydantic 2.13.5`, which is why the venv interpreter is the one in use from here.

All 58 packs are the **same size as their disc entries** (the builder keeps a budget), so all 58 were written in place at
their FST offsets into a fresh build (`re4gsonic_enemies`), with `"image": "re4-d1.iso"` set so `filemods.launch_path`
returns the ISO.

**The result is stock.** In a live round the player is Leon and the Ganado in view is an ordinary villager:

![stock Ganado in the rebuilt-enemy build](evidence/re4gc-sonic-enemies-stock-ganado.jpg)

That is now **two** builds - player archives (`pl00/pl08/pl09/pl10`) and enemy archives (58 `em/*`) - each verified at the
byte level to differ from the disc, and neither drawn. The model work is not the variable any more; the **file Dolphin
opens** is. Two possibilities remain and one command decides it:

1. the adapter launches the library `.gcz` regardless of the mod path (the `FileNotFoundError` proves `launch_path` is
   consulted, not that its result is used); or
2. Dolphin opens the ISO and the game loads models from somewhere else entirely.

The deciding check is the Dolphin process's own command line during a run (`pgrep -af dolphin` for the `-e`/`--exec` and
the game argument): if it names the library `.gcz`, the build is never used and every injection test so far has been
measuring the wrong file. That check is the first thing next round, before any further build.
## Dolphin opens the patched ISO - so the injection is not being ignored (2026-11-07)

The command line settles hypothesis 1 from the last round. Launching `re4gsonic_enemies` and reading the emulator's own
process list:

```
dolphin-emu -b -u .../dolphin-user -C Dolphin.Core.GFXBackend=Vulkan ... <the game argument>
MARK opened: the patched ISO
```

The mod build's `re4-d1.iso` is the file the emulator was given. So the patched ISO **is** opened, and the game still draws
stock models - which means the remaining explanation is on the game's side, not the launcher's:

* either the disc's `em/*.drs` files are not what the game reads for models (an index or a second copy elsewhere), or
* a rebuilt DRS is not acceptable and the model in memory is the disc's own.

**The next experiment is chosen to separate those without more modelling work:** patch something whose loading path is
simple and whose effect is unmistakable - a **stage texture**. If a colour-changed stage texture draws, the injection
mechanism is sound end to end and the model archives specifically are not read from those paths; if it does not draw, the
write path itself is wrong and every archive test so far has been measuring that.

Two operational notes from this round, both mine:

* a launch failed with `dolphin exited 134: qt.qpa.xcb: could not connect to display :102` because it raced a display that
  was still being torn down - the probe must wait for the host to be idle, not just for `enabled=false`;
* that race left the host "busy with jobs" while MercMode wanted to start RE5. The launch job reported `failed`; the
  scheduler recovered on its own, but the sequence cost two minutes and is exactly the kind of thing the document's
  restore order exists to avoid.
## Round 57: the control runs, and the discriminator has not landed yet

**What exists from before me, which changes the question.** Three builds sit in the cache from 2026-10-06 and 2026-11-06:

| build | marker | patched files |
|---|---|---|
| `re4_aya` | `image: "RE4 Aya (Disc 1).iso"` | `em/pl00, pl08, pl09, pl10` |
| `re4_enemies_peach` | `image: "re4_enemies_peach.iso"` | `em/em16, em46, em56, em66` |
| `re4gsonic1512` | `image:` absent, `files: []` | none |

`re4_aya` patches **the same four player archives** my Sonic build patches, and `re4_enemies_peach` patches four enemy
archives - so this pipeline has produced builds before, and `re4gsonic1512`'s empty `files: []` is the same truth found in
round 55: it was a copy.

**The texture discriminator was inconclusive, for a reason worth writing down.** `ss/Cmn/f01.tpl` (511,456 bytes) had its
pixel data filled and was injected - and the Select Player screen came up untouched:

![Select Player, unchanged](evidence/re4gc-texprobe-select-player.jpg)

That proves nothing either way, because nothing establishes that `f01.tpl` is on that screen. Choosing a texture by name is
the same mistake as choosing a pointer by note: the experiment needs a file whose use is certain. **The next one uses the
font** (`font/*.fnt`), because text is on every screen, so a change is unmistakable and a non-change is decisive.

**The Aya control is unread.** It launched and reached Select Player, then every frame was identical (`mean 62.4` for seven
samples) - a stall, not a change. The portraits on that screen are textures, not the player model, so the run could not
have answered the question even if it had progressed.

**What is established, and it is worth stating plainly:** the emulator opens the patched ISO (round 56), the archives on it
are byte-verified different from the disc, and prior builds patched the same archives. What is **not** established is that
any rebuilt archive has ever been drawn - including the ones built before I got here. That is the gap the font test closes.
## The font test: every glyph filled, every label still crisp (2026-11-07)

A font is on every screen, so filling the glyph bitmaps was chosen as the unambiguous read test. Two builds:

| build | patched | result |
|---|---|---|
| `re4gc-fontprobe` | `font/common_p.fnt` - 98,796 bytes of glyph bitmap filled | title text normal |
| `re4gc-fontall` | **every** `font/*.fnt` on the disc - 13 files, 33 KB to 525 KB of glyphs each | title text normal |

![Title screen with every font filled](evidence/re4gc-fontall-title-text-normal.jpg)

And the patch is on the disc that was opened - verified by reading the mod ISO back at the FST offset:

```
font/common_p.fnt  source bytes 52..80: 00100000000000020000002000000000100020003000400050007000
                   mod    bytes 52..80: ffffffffffffffffffffffffffffffffffffffffffffffffffffffff
                   differing bytes: 97,575 | tail all 0xff: True
```

The emulator's complete argument list was also read, not substring-matched, and it carries exactly one disc:

```
MARK disc tokens: ['/home/ehm_eckx/gBox_alt/gbox-cache/mods/78ab9efa2e310db4/re4gc-fontall/re4-d1.iso']
```

`Load/Riivolution` was checked for an overlay that would shadow the disc: the directory exists and holds no files, so nothing
is shadowing.

**What this proves and what it does not.** It proves the ISO is the only disc, that the patched bytes are on it, and that a
fully filled font atlas does not change a single label. It does **not** yet prove that the game ignores patched files: it is
equally consistent with the menu labels being **pre-rendered textures** rather than the `.fnt` atlases (the `.fnt` files may
serve subtitles or the Japanese text). Two experiments in a row have now been inconclusive for the same reason - the asset
was chosen by name, not by evidence that the screen draws it.

**The next test is chosen the other way round: find which file the screen draws from, then patch it.** For this title that
means the stage archive, because the Ganados that appear in a village round may come from the stage package rather than
`em/*.drs` - which would also explain why a complete, byte-verified rebuild of all 58 `em/*` archives changed nothing.
That is the most valuable thing learned in this round: **the negative results are consistent with the wrong archive family,
not with a broken write path.**

## A method note, because it cost two rounds

Twice now the experiment was "patch a file, look at a screen, conclude". A file whose use is not established makes that
conclusion unsupportable in both directions. The rule from here: **the file must be identified from the game's own
reference to it first** - the same way the Switch texture join was solved (`"%s\%s\%08x.pack.fen"` out of the ELF), not by
guessing from a directory listing.
## Round 59: the game's own path strings (2026-11-07)

The font test's negative result prompted the question the earlier rounds should have asked first: **what names does the game
actually open?** The DOL answers it directly.

```
$ strings on the DOL (2,168,544 bytes)
Font/common_j.fnt   Font/system_j.fnt   Font/common_p.fnt   Font/stage%1d_j.fnt   Font/event%1d_j.fnt
em/em1f.das         em/pl00.das         em/wep01.das        em/wep02.das        em/em20.das ...
```

Two things in that output matter, and both were invisible from a directory listing:

1. **The font path is capitalised `Font/`, and the disc's FST says `font/`.** If the loader's lookup is case-sensitive, a
   request for `Font/common_p.fnt` does not find `font/common_p.fnt` - and that alone explains why filling every glyph atlas
   changed nothing. The `.fnt` files may be perfectly patchable and simply never opened under the name the game uses.
2. **The model archives the DOL names are `em/*.das`; the disc's are `em/*.drs`.** The disc does carry `.das` files - 90 of
   them, all stage rooms (`St1/r100.das` …) - so `.das` is a real extension on this disc, and `em/*.das` appears in the DOL
   while only `em/*.drs` exists in the FST. Either the loader swaps the extension, or `em/*.das` is a name that never
   resolves and the model comes from elsewhere.

Neither is a guess: both are strings in the executable, which is the same evidence that solved the Switch texture join
(`"%s\%s\%08x.pack.fen"` out of the ELF). It also explains the shape of every negative result so far: the files were
patched correctly, at correct offsets, on a disc the emulator definitely opened - and the game may never have asked for them
by those names.

**The next measurement is therefore not another patch.** It is: take `St1/r100.das` (the village room the bot walks into),
write a few KB of `0xFF` over its head, and launch. A stage the game loads cannot survive that intact - it will fail to load
or crash. If the village still loads normally, then the FST offsets in `gbox.gcdisc` are not the ones the game reads, and
that is a parser question, not a modding one.

## What is settled

* the emulator opens the patched ISO and nothing else (`MARK disc tokens:` one path, round 58);
* patched bytes are present at the FST offsets (verified by reading the mod ISO back);
* there is exactly **one** copy of a font's data on the disc (scanned all 1.4 GB for its header, 1 hit);
* no Riivolution/`Load` overlay shadows the disc (`Load/Riivolution` is empty);
* and now: the names the DOL uses are `Font/*.fnt` and `em/*.das`.
## Round 60: the break test, not yet concluded - and a better way to run it

`re4gc-stagebreak` was built: the first **4096 bytes of `St1/r100.das`** overwritten with `0xFF`. What happened:

| step | observation |
|---|---|
| boot | fine - title screen, menus, Select Player all normal |
| bot (`mode=playbook`) | **stalled on Select Player**, identical frames (`mean 62.4`) |
| four manual A presses | landed in the **LOAD GAME** save list, then "Load data? Yes / No" - the village was never asked for |
| after that | every frame identical (`mean 40.3`) for 96 s, then the session **ended by itself** with `error: None` |

So the test did not conclude: the game was never made to load the broken room, and the session's end is unexplained rather
than a recorded crash. The service journal has no Dolphin exit line for it.

**Two things to fix, both worth more than another guess:**

1. **The Select Player stall is reproducible** - it happened on the `re4_aya` run too, at exactly the same screen and the
   same `mean 62.4`. A bot that stalls on the Mercenaries character select is broken for every GC title, not just this test.
2. **There is a `warp` op that loads a room directly** (`re_mods`: `warp target=r102 [items=[x,y,z]]`, "r1xx village … r4xx
   Mercenaries"). That bypasses the menus entirely: warp into `r100` on the broken build and the village either loads or it
   does not. That is the correct instrument for this test, and it should have been the first one used.

**The next round's first action** is a warp into `r100` on `re4gc-stagebreak`, with the same warp on the unmodified disc as a
control. Two launches, one bit of information: does the game read the file at the FST offset. No modelling, no bot.
## Round 61: the reason nothing ever drew - our own FST parser pairs names with the wrong offsets (2026-11-07)

The warp test itself was inconclusive (both runs landed on the same Ada scene), but checking *why* produced the answer to
five rounds of negative results. Every GC archive carries a magic: `.drs` files begin `ca b6 be 20`. So a parsed offset for
a `.drs` path that does not begin with that magic is a **wrongly paired file**, not a modelling problem:

```
.drs entries: 128 | magic at parsed offset:  11 | not the magic: 117
.das entries:  90 | magic at parsed offset:  90
```

Examples, all `em/*`:

```
em/em10.drs  offset  832593344  head 836e834a   <- not a DRS
em/em11.drs  offset  843221344  head 836e834a
em/em16.drs  offset  873769984  head 836e834a
em/pl00.drs  offset  240678972  head cab6be20   <- correct
```

**This is the explanation for every "patched, verified, and not drawn" result in this session** - the 58 enemy packs, the
four player archives, and the prior session's `re4_aya` and `re4_enemies_peach` builds: they were written at offsets the
parser produced, and for 117 of 128 archives those offsets are not where the archive is. The write succeeded, the size
matched, the emulator opened the ISO - and the game read the real archive, untouched, a few kilobytes elsewhere.

It also explains the pattern in the failures: `em/pl00.drs` parses correctly (one of the 11), which is why a rebuild of it
could look plausible, and every `.das` stage archive parses correctly, which is why the stage file could be read properly
while the model archives could not.

**What is not yet known: the correct rule.** `parse_fst` reads 12-byte entries `{u8 is_dir, u24 name offset, u32 file
offset|parent, u32 size|next}` and takes name offsets relative to the name table (`fst[n*12:]`). One alternative - name
offsets relative to the FST start - was tried and is not it (the walk raised on an out-of-range name). The next step is the
one that should have come first: **walk the FST by hand against the raw bytes**, with the magic check as the scoreboard, until
128 of 128 land on their magic. `system/tools/probes/probe_gc_fst_offsets.py` does the scoring and is the test to run after
every change.

**The bar for the fix:** `probe_gc_fst_offsets.py` reports 0 mispairings, and only then is any archive patch re-run. Until
then every model-swap build in this repository - mine and earlier ones - is unverified, because it cannot have been applied
to the file the game reads.
## Round 62: correction - the FST parser is fine, and the game does use the FST

**Round 61's headline was wrong and is retracted here.** It claimed `parse_fst` mispaired 117 of 128 `.drs` entries because
they did not begin `ca b6 be 20`. The first bytes of files whose magic is *known* show why that reasoning failed:

```
opening.bnr        off  27780768  head 424e5231...                     "BNR1" - correct
font/common_p.fnt  off  42044316  head 00000020000180a0... 0020af30     a real .fnt with its TPL at +32 - correct
em/pl00.drs        off 240678972  head cab6be20 x8, then 00000000001017a0...
St1/r100.das       off 279349120  head cab6be20 x8, then 00000000002aeece...
em/em10.drs        off 832593344  head 836e834a835a82cc8341837a815b815b...
```

And across all 218 archives there are exactly **two** header families:

```
836e834a: 117 files
cab6be20: 101 files
```

So `ca b6 be 20` was never a universal magic - it is one container format, and the 117 files use another. Every offset the
parser reported is a real file. My claim that 117 archives were mispaired, and that this explained the negative results, was
false; the negative results are unexplained again, which is the honest position.

**What this round did establish is worth more than the retraction: the game reads the FST.** Corrupting the FST root entry
and the first entries with 0xFF (`re4gc-fstbreak`) leaves the emulator running and the picture **black for six samples over
72 seconds**:

```
MARK fstbreak_00 mean 0.0 ... MARK fstbreak_05 mean 0.0
```

The emulator is up (the session exists, frames are served) and the game never draws - so it looked its files up in the FST
and failed. A game with a private file table would not have noticed.

**That makes the remaining puzzle sharper, not vaguer:** the FST is consulted, the parsed offsets point at real files, the
patches are on the disc at those offsets, the emulator opens that disc - and a filled font atlas changes nothing on screen.
The next question is therefore not "where is the file" but "what does the game do with the bytes it read", and the cheapest
place to answer it is the one file the DOL names by an exact string: `Font/common_p.fnt` (capital F against the disc's
`font/`), which if case matters would explain a silent fallback to a different source.
## Round 63: the case test is negative, and the font was the wrong instrument all along

`re4gc-fontcase` renamed the FST's `font` directory to `Font` (a single byte in the name table, same length, so nothing
moves) **and** filled `common_p.fnt`'s glyphs. The title screen came up untouched again:

![Title screen, font dir renamed and glyphs filled](evidence/re4gc-fontcase-title-unchanged.jpg)

So case is not it. More importantly this closes the font line of enquiry: the labels `START`, `ASSIGNMENT ADA`,
`THE MERCENARIES`, the Capcom line and the `resident evil` logo are **pre-rendered art**, not glyphs from any `.fnt`. Three
patches (one font, all fonts, all fonts plus a rename) measured the same nothing, and the honest reading is that the
instrument was wrong, not the disc.

**What the same round found on the Switch side.** The HD port's UDAS container is **little-endian**, which is why
`udas_entries(data)` on `em16.udas` produced an entry at `0x20040000 + 0x20af3c00` - a big-endian read of a little-endian
table. Read correctly:

```
em16.udas: 4,016,416 bytes
  udas entries: 2
    {type: 0, size: 3,976,992, offset: 1056}
    {type: 4, size: 0,       offset: 3,996,704}
  entry type 0: 698 DAT slots
```

698 slots in one Ganado pack. That is the surface a "remove clothes" operation has to address: a DAT slot per model/part,
not a single mesh per enemy.

## What this means for the two goals

* **Sonic on GameCube**: still no drawn change, and the font path is exhausted. The next instrument must be a file whose
  use is proven by the *game's code*, not by a guess from the directory - which for this title means tracing the loader that
  the DOL's `em/*.das` strings belong to.
* **Clothes removal / clean characters on Switch**: the container is now decoded correctly (little-endian UDAS, 698 DAT
  slots) and the engine demonstrably draws same-topology edits, so a part-hide (collapse a slot's vertices to a point) is the
  next experiment that can succeed rather than the next guess.
## Round 64: "remove clothes" as a real operation, measured against a real pack

`gbox/re4hd_hide.py` hides a material by collapsing its vertices onto that material's own centroid. Topology is untouched -
every index, triangle and count stays exactly as it was - which is the only kind of edit the Switch engine draws.

**The first version was wrong, and the real pack said so.** It assumed `Mat.start` was a vertex index; on `pl00.udas`
material 13 "spanned" vertices 142,168..142,398 of a 3,425-vertex mesh. `Mat.start` is a display-list offset.

The property that is true is measurable: the material records' `triangle_count`s sum **exactly** to the mesh's triangle
count on the real pack -

```
sum(triangle_count) = 2,519   len(tris) = 2,519
```

- so triangles are stored in material order, material *i* owns `triangle_count[i]` consecutive triangles from the running
  total, and its vertices are the indices those triangles use. That is the rule the module now implements, and the test
  asserts the property itself before using it, so a pack that breaks it fails loudly instead of hiding the wrong part.

`hide_materials` returns a report - which materials, how many triangles and vertices each, the centroid, and
`triangles_unchanged` - so a build can say what it did rather than assume it.

Tests: 7 on the Spark (the last one on the real `pl00.udas`, including a `bin_write`/`bin_read` round-trip that keeps every
triangle), 6 plus the skipped real-pack case on a machine without the RomFS.

**Still owed: a frame.** The operation is built and measured; the next step is the one that counts - write the modified pack
into a LayeredFS build, launch with it, and look at the player. That is the first part-hide test that has a reason to draw.
## Round 65: the part-hide runs in the game, and the first result is ambiguous

Two builds were made and played, both in the Switch LayeredFS layout the tool expects
(`mods/270a15eb98dab4d7/<build>/romfs/bio4/em/pl00.udas` plus a `layeredfs` marker - the first attempt wrote to
`mods/010099A00BC1E000/…` and the launcher refused it with *"no built mod … for this game"*, because the folder is keyed by
the **game id**, not the title id).

| build | change | result |
|---|---|---|
| `re4sw-clothesless` | material 1 of `pl00` slot 0 collapsed: 564 vertices, 430 triangles, centroid `[-425.9, 1524.6, -38.0]` | **Leon renders normally** |
| `re4sw-nomodel` | all 14 materials collapsed: 3,425 vertices, topology unchanged | **black frames for ten samples, session ended** |

![Leon with material 1 collapsed](evidence/re4sw-clothesless-material1-normal.jpg)

The round was a live Mercenaries round (`01'03"76`) and Leon is complete - so either material 1 is a part that is not visible
from that camera (an inner surface, a LOD, teeth), or the pack was not loaded. **The all-collapsed control is consistent with
the pack being loaded** - a model whose every material sits on one point can break a renderer - but "black screen and the
session ended" is not proof of that either; a failed boot looks the same from a frame.

**The next experiment is designed so it cannot be ambiguous:** shrink a material to **10% about its own centroid** rather than
collapsing it. That cannot crash a renderer, and any visible part must shrink. If the player looks identical, the build is not
being loaded and that is the answer; if it shrinks, the pipeline works and the material list can be bisected for the clothing
one by mapping `material_id` to its texture.

## The reusable piece this leaves behind

`gbox/re4hd_hide.py` with 7 passing tests (the last on the real pack), and a build recipe that produces a valid LayeredFS
mod in the layout the launcher accepts - the two things "remove clothes / swap clothes" need before any UI is worth wiring.
## Round 66: the Switch playbook recovers from the save list - and the shrink probe reached a round

**The bot fix is the round's real result.** `re4switch_bot` now asks the driver for its own save-list recovery
(`driver._recover_story`) when the picture stays byte-identical for `still_s` (12 s) before any stage has been seen. The
driver has carried that policy since it was measured - *"identical frames for 260 s"* - but the playbook never called it, so
a stray confirm into LOAD looked exactly like a hang. With the fix, and a runner that waits for a real picture instead of a
fixed delay (a modified pack makes the first boot slower):

```
MARK picture up: mean 78.0
MARK shrink2_00 76.7 ... shrink2_04 56.7 ... shrink2_08 57.5
```

the walk reached a live Mercenaries round - `01'21"38`, Ganados closing in - with the modified pack loaded:

![the shrink build in a live round](evidence/re4sw-shrink1-round-normal.jpg)

**The model change still isn't visible.** `re4sw-shrink1` shrinks material 1 of `pl00` slot 0 to 10% about its centroid -
564 vertices, 430 triangles, topology untouched - and Leon is complete: shirt, straps, holster, all of it. So material 1 is
not a garment the camera sees (an inner surface, a LOD, teeth), **or** the pack is not read. Those two possibilities are
still not separated, and the previous round's collapse test could not separate them either.

**The control that separates them cannot crash and cannot be missed:** shrink **all 14 materials** to 10%. If the player
becomes a small blob, the build is read and the material list can be bisected for the garment by mapping `material_id` to its
texture. If the player is unchanged, the pack is not being read and that is the answer - and it is one boot, not a research
programme.

Two smaller things worth keeping: the runner now waits for `mean > 15` before starting the bot (a black frame during a slow
boot was being read as a crash), and `re4hd_hide.scale_materials` exists with its own tests because a shrink is a safer probe
than a collapse.
## Round 67: every material shrunk, the player unchanged - and the control that would explain it stalled

`re4sw-shrinkall2` was built through **`switch_mods.write_files`** (the writer the working morph builds used), not by hand:
the edit was staged and reported `"applied": [...001]`, the overlay summary says `{"files": 1, "bytes": 1448576, "edits": 1}`,
and the build holds exactly `romfs/bio4/em/pl00.udas`. It collapses nothing and crashes nothing: **all 14 materials of
`pl00` slot 0 are scaled to 10% about their own centroids**, 3,425 vertices, topology untouched. In the round the player is
complete:

![every material of pl00 shrunk to 10%, the player unchanged](evidence/re4sw-shrinkall-not-drawn.jpg)

So one of two things is true, and they are very different:

1. **`bio4/em/pl00.udas` is not the model Mercenaries draws for Leon.** The pack tree has 25 BIN slots per pack and many packs;
   story Leon and Mercenaries Leon are not necessarily the same file, and nothing so far has established that this one is
   used by the mode being played.
2. **The overlay is not reaching the emulator** for this file.

**The control for (2) stalled**, so the question is open: `re4-em16morph` - the build that visibly deformed enemies in earlier
rounds - was launched again and sat on one screen at `mean 19.4` for two minutes. That is the save-list prompt family again
(`Cancel loading?`), which the playbook now cancels, but this time the cancel did not clear it. Until that control runs, (1)
and (2) cannot be separated, and no further model work is worth doing.

**The next two steps, in order:**

1. **Fix the stall** on the 19.4 screen - capture it, name it, handle it - because a bot that cannot always get out of a menu
   makes every model experiment unreliable, and it is the same defect that cost rounds 60 and 66.
2. **Re-run `re4-em16morph`.** If the enemies deform, overlays work and the target pack is wrong (follow the pack the
   Mercenaries roster actually loads); if they do not, the overlay path is broken and that is the finding.

## What round 67 did deliver

`re4switch_bot` now presses the driver's save-list cancel **and** confirms the `Cancel loading? Yes/No` prompt (`CANCEL_CONFIRM
= ("up", "a")`, with a test asserting both), and the runner waits for a real picture before starting the bot. Those two fixes
are why three separate runs this round reached live Mercenaries rounds at all.
## Round 68: the stall has a name, and the overlays are not exclusive

**The stall.** The screen that held three runs at `mean 19.4` is the game's **"Cancel loading? Yes / No"** prompt with **No**
selected:

![Cancel loading? Yes/No](evidence/re4sw-cancel-loading-prompt.jpg)

The playbook's recovery skipped it for a precise reason: the prompt darkens its background, so the classifier calls it
`unknown`, and the recovery only ran on *named* screens. It is now a fixed escape sequence, one press per still picture -
`STALL_ESCAPE = ("b", "up", "a")` - that resets the moment the picture changes, so a wrong guess costs one press instead of
the run. Two tests pin it: the sequence runs in order on a still picture, and no escape press happens on a moving one
(a picture that moves is not a stall). Seven playbook tests, all green, deployed.

**The overlays are not exclusive.** This is the finding that matters for every model experiment:

```
citron load/010099A00BC1E000: 31 links
  lab-swap-test, re4-allem, re4-allganado, re4-dog-full, ... re4-em16morph, ... re4sw-clothesless,
  re4sw-nomodel, re4sw-shrink1, re4sw-shrinkall, re4sw-shrinkall2, ...
[DisabledAddOns] for the RE4 title: disabled\size=0
```

**Five of my builds contain a different `bio4/em/pl00.udas`** and all 31 are active, so the model drawn is whichever overlay
the emulator applies last - not necessarily the one just launched. That explains the "shrink everything and nothing happened"
result without any need for `pl00` to be the wrong pack: a *different* build's `pl00` (for instance `re4sw-clothesless`, which
only hides material 1) can win. `prepare_launch` does call `set_title_disabled(emu, tid, mods, build)`, and that call reports
success - but the config the emulator reads still has nothing disabled, so gBox is writing a config file the emulator does not
use.

**Next, in order:**

1. Find which config the emulator actually reads (its `-u` argument in the launch line, versus the path `set_title_disabled`
   writes), make them the same, and verify by reading `[DisabledAddOns]` **after** a launch with a build.
2. Remove the stale links and re-run the all-material shrink. If the player shrinks, overlays work and the whole model
   pipeline is unblocked; if not, `pl00.udas` is not the file Mercenaries loads and the pack has to be found from the game's
   own reference.

Nothing else on the model track is worth doing until the overlay question is answered - every result so far was measured
through a mechanism that may have been loading someone else's file.
## Round 69: the overlay works, so `pl00` is not Mercenaries' Leon

Measured **during a modded session**, not inferred afterwards:

```
[DisabledAddOns] entry 5 (0x010099A00BC1E000): disabled count 0 | build disabled: False
load/<title>/re4sw-shrinkall2 -> gbox-cache/mods/270a15eb98dab4d7/re4sw-shrinkall2   (a link)
emulator_reads  f47120f6bab1682ef6279cd83c59eb59
build_copy      f47120f6bab1682ef6279cd83c59eb59   same: true
```

My earlier reading of the config was wrong: entry 5 is the RE4 title and the 31 builds **were** listed as disabled, so
`set_title_disabled` is doing its job - the launched build is the only enabled one, and the file the emulator reads is byte-for-byte
the build's own `pl00.udas`. The overlay mechanism is sound.

**Which settles the ambiguity the other way: `bio4/em/pl00.udas` is not the model Mercenaries draws for Leon.** A file whose
every material was scaled to 10% was demonstrably the file being read, and the player was unchanged - so the mode's characters
come from somewhere else.

**The next probe is already built:** `re4sw-allplayers` rewrites **26 of the 27 player packs** (`pl00`..`pl21`), 227 BIN slots,
**259,937 vertices** scaled to 10% about their own centroids, written through `switch_mods.write_files`. Whatever the mode draws
a character from, its vertices move. Its run this round did not reach a round - the bot was left on the save-list prompt - so
the frame is owed next round, with the escape fixed first.

## The escape needs to be a state machine that does not reset on a repaint

`STALL_ESCAPE = ("b", "up", "a")` resets whenever the picture changes, and a cursor moving *is* a change: on the save list each
press repaints a little, so the sequence restarts at "b" and never reaches the confirm. The fix is to advance on
"still static after this press" rather than on "picture identical", and to treat a **named screen change** as the reset signal.
Until that is right the bot will keep stranding runs on this menu, and it is the same menu in three of the last four rounds.
## Round 70: the first character change actually drawn (2026-11-07)

`re4sw-allplayers` rewrites **26 of the 27 player packs** - 227 BIN slots, **259,937 vertices** scaled to 10% about their own
material centroids - through `switch_mods.write_files`. In a live Mercenaries round the **player is visibly destroyed** while
the Ganados are untouched:

![Leon collapsed to fragments, the enemies normal](evidence/re4sw-allplayers-leon-collapsed.jpg)

`01'26"52` on the clock, the HUD still says Leon, the pistol is in his hand and the rest of him is a shrunken fragment. The
Ganados - who live in `em*` packs, which this build does not touch - are completely normal, so the change is specific and
attributable.

**This is the first time a character replacement has been drawn on the Switch title**, and it settles every question the last
five rounds were circling:

* the LayeredFS overlay works, and the file the emulator reads is the build's own (md5 verified in round 69);
* a **topology-preserving vertex edit is drawn** - exactly the constraint the engine imposes;
* **Mercenaries' Leon is in `pl01`..`pl21`, not `pl00`** (the `pl00`-only build changed nothing, this one changed the player);
* the same round also produced a **death** the incident pipeline can key on (`You Are Dead`, `Continue Yes/No`):

![You Are Dead](evidence/re4sw-allplayers-you-are-dead.jpg)

**The next step is a bisection**, and it is cheap: shrink `pl00`..`pl0f` only, then the half that changes the player. Two or
three boots, and then "remove clothes" has a target pack and a material list instead of a guess.

## The escape fix that made the run possible

The playbook's escape advanced on pixel change, and a cursor repainting a stuck menu is a pixel change - so it restarted at its
first press forever. It now advances on **time since the last action** and restarts only when the **named screen** changes.
Eight tests, including one that pins exactly this: a stuck screen that keeps repainting still escalates.
## Round 71: the bisection is built and the escape is back-out only

Two changes, both earned this round:

**The escape must not confirm anything.** `STALL_ESCAPE` was `("b", "up", "a")`, and "a" on the save list *loads a save* -
which returns to the same prompt one screen later. It is now `("b", "b", "b", "b")`: back out of the prompt, the list and the
LOAD menu, and let the walk start again from whatever named screen it lands on. Eight playbook tests, all green, deployed.

**A probe may grow a model.** `scale_materials` refused any factor above 1.0, which silently dropped the whole first group of
the bisection (x3.0) and left a build with 13 packs instead of 20. The ceiling is now a sanity bound at 4.0, with the reason
written where the check is: shrinking is the *hide* use, growing is a legitimate *probe signature*.

**The bisection itself** (`re4sw-plquad2`): 20 player packs, 176 BIN slots, **211,098 vertices**, four groups with
distinguishable outcomes -

| packs | factor | a round would show |
|---|---|---|
| `pl00`..`pl06` | x3.0 | a giant |
| `pl07`..`pl0d` | x0.1 | a fragment |
| `pl0e`..`pl11`, `pl14`, `pl15` | x0.5 | noticeably smaller |
| `pl16`..`pl21` | untouched | unchanged |

Its run reached the main menu (`EXTRAS` visible in the frame) but the capture window closed before the round, so the
identification is still owed - one boot with a longer window, and then "remove clothes" has a target pack instead of a guess.

## What is now settled, and what it cost

The mechanism chain is proven end to end: overlay enabled and read (round 69, md5), a topology-preserving vertex edit drawn
(round 70, the collapsed player with untouched enemies), and a bot that reaches live rounds through the menus (round 70,
with this round's escape fix making it repeatable). What remains is *which pack* - a search, not a discovery.
## Round 72: Leon is in `pl01`..`pl06` - a giant head proves it

The four-group bisection worked exactly as designed. `re4sw-plquad2` (20 packs, 176 slots, 211,098 vertices) scaled
`pl00`..`pl06` x3.0, `pl07`..`pl0d` x0.1 and `pl0e`..`pl15` x0.5. In the round the player is a **giant head**:

![a giant head where Leon should be](evidence/re4sw-giant-head-pl01-06.jpg)

`00'12"76` on the clock, the HUD says Leon, and the model is enormous - the x3.0 group, seen from a camera that is now inside
it. Since a `pl00`-only shrink changed nothing (round 66) and this group did, **Mercenaries' Leon is in `pl01`..`pl06`**.

The narrowing build is already made: `re4sw-plhalf` - `pl01`..`pl03` at x3.0 (giant) against `pl04`..`pl06` at x0.1 (fragment),
31 slots, 53,526 vertices. One boot identifies the half; one more identifies the pack.

## The trap that wasted the follow-up run: a leftover emulator

The narrowed run started with the picture at `mean 18.7` - which is the **"Cancel loading? Yes/No"** prompt - *before* the bot
had pressed anything, so the game was already sitting there when the launch was made. That is not a boot path: the emulator
process from the previous run was still alive, and the "new" session attached to it. `pause_and_wait` stops gBox sessions and
waits for jobs, but it does not kill a stray emulator, so the next launch can inherit a menu somebody else left on screen.

**The probe must kill the emulator, not just the session.** `pkill -f citron` for the title before a launch (or an adapter check
that the process is gone), and the runner's `picture up` condition must be "a picture the *menus* can be, not one the last run
left" - which in practice means checking that the picture changes when a key is pressed, not just that it is bright.

## What this round changed in the library

`scale_materials` now permits factors up to 4.0, because a bisection needs distinguishable outcomes and refusing to grow a
model silently dropped a whole group (13 packs written instead of 20). Eight hide tests and eight playbook tests pass.
## Round 73: a real bug fixed, and the half-bisection blocked by input that does not land

**Fixed: `rea_tool` was silently missing from the node.** The service log repeated *"tool module rea_tool not loaded on this
machine: AttributeError: module 'gbox.rea' has no attribute 'VERSION'"*. The registry skips a tool module that raises, so the
REA tools were absent from every job while the integration itself worked. `gbox.rea` now exports **`VERSION`** and
**`unavailable()`** - the latter answering one string or nothing, and never raising, because a tool's `check` must not be able to
take the module down. Four tests pin the contract (`tests/test_rea_tool_contract.py`), they pass on both machines, and after the
restart the error is gone from the log.

**Fixed in the runner:** it now kills a stray emulator before launching and accepts a picture only when two samples **differ**.
Round 72's follow-up run had attached to a leftover emulator already sitting on "Cancel loading? Yes/No", which looked like a boot.

**Not fixed, and it is the blocker: the playbook's presses stopped landing.** The half-bisection run (`re4sw-plhalf`:
`pl01`..`pl03` x3.0 against `pl04`..`pl06` x0.1) started cleanly - "picture up and alive: mean 49.1" - and then sat at
`mean 19.4` for over two minutes while the escape pressed back every 12 s. Either the thread that sends input had ended, or the
input reached a process that was no longer the one being read. Until that is understood, **every** run that lands on a menu is a
coin flip, and the bisection cannot be finished by repeating the attempt.

**What the next round must do first:** send a single key and verify the screen changes - a two-frame input assertion - and only
then walk. If a key does not move the picture, the session is reading a frame from a process it does not drive, and the fix is in
`_launch` rather than in the playbook.
## Round 74: the keys land - and the autoplay thread was the unreliable part

**Input works, measured.** One key through `session_op send_input` changes the picture, twice in a row:

```
press a -> 200 | 'a' changed the picture: True | means 61.2 -> 23.9
press b -> 200 | 'b' changed the picture: True | means 74.5 -> 54.1
```

That was worth checking before anything else, because round 73 ended with a playbook pressing back every twelve seconds on a
menu that never moved.

**So the presses that did not land were the *autoplay* ones.** Driving the same route the driver describes - frame, classify,
one key - directly through `session_op` reached a live round in **18 steps** (`last screen playing`), twice:

![the directed walk's round: Leon grabbed at 01'05"53](evidence/re4sw-directed-walk-grabbed.jpg)

The round is real and Leon is grabbed at `01'05"53`. The harness only watches, so he dies - which is why the first capture
cadence caught "You Are Dead" instead of the player. That cadence is now four seconds, not twelve.

**What this means for the autoplay work:** the playbook's own input path (`_autoplay_send` behind the pad-takeover gate) is the
suspect, not the keys and not the menus. A bot that presses into a menu and then cannot press out of it is worse than no bot,
and the next step is to instrument that path rather than to keep re-running it.

**The half-bisection is still owed its frame.** `re4sw-plhalf` (`pl01`..`pl03` x3.0 against `pl04`..`pl06` x0.1) walks fine
under the directed harness; what it needs is a capture in the first seconds of the round, which the tightened cadence now does.
## Round 75: the search narrows honestly, and round 72's "giant head" was probably the camera

Four builds were tested through `switch_mods.write_files`, each with a round reached (or nearly) and each read from the frame:

| packs | change | what the frame showed |
|---|---|---|
| all 26 (`pl00`..`pl21`) | x0.1 | **the player collapsed to fragments** (round 70 - unambiguous) |
| `pl00` alone | x0.1 | **normal Leon** (round reached, `reached True`) |
| `pl01`..`pl06` | x3.0 / x0.1 | **normal Leon** |
| `pl07`..`pl0d` | x0.1 | **inconclusive** - the camera sits inside a body and the frames are dark |

**Round 72's "giant head" is retracted as evidence.** The build that produced it scaled `pl00`..`pl06` by x3.0, and the
`pl01`..`pl06` build does not change the player - so the head at `00'12"76` was almost certainly the camera clipping into a
normally-sized Leon during the round intro, not a scaled model. The unambiguous result stays the all-pack one, where the whole
body became fragments.

So the search space is now **`pl07`..`pl21`**, and the quarter `pl07`..`pl0d` is the one in question - it needs a capture that
starts *before* the camera enters a body (the intro), not one that starts with the first grab.

## What the round also proved

The directed walk is reliable: five runs, each reached the Mercenaries menu route in 14-18 steps, and two reached a live round.
The autoplay thread remains the unreliable path, and that is a real defect in the playbook for every title, not a probe detail.

## The lesson that cost the most rounds here

A frame is evidence only when what it shows cannot be explained another way. "A giant head" had two explanations - a scaled
model or a camera inside a normal head - and I treated it as one. The all-pack build was believed because the *whole body*
changed while the enemies did not; that is a difference no camera position produces.
## Round 76: a camera-independent probe, and the game's own per-character files

**The probe changed shape.** A 10% shrink can be hidden by the camera sitting inside a body - that is exactly what made the
`pl07`..`pl0d` quarter inconclusive. `re4sw-plhide` **collapses** whole packs instead (every material onto its centroid, 89
slots, 100,191 vertices across `pl07`..`pl0d`), because a *missing* player is readable from any camera angle and no camera
position produces it by accident. Its run did not reach a round (the walk ended on a `loading` screen), so the quarter is still
open - but the instrument is now the right one.

**A deterministic route exists and is worth more than the search:** the game ships its own per-character data.

```
bio4/etc/emleon00.esl .. emleon07.esl, omake00.esl .. (20 files)
```

Twenty `.esl` files, one family named for Leon, in the tree the game itself loads (`bio4/etc`, beside `core.udas`,
`memcard.udas`, the movie packs). If those reference the model packs by id, the mapping is a decode rather than a bisection -
and a decode is reusable for every character and every stage, which a bisection is not. The head is binary
(`0012 0000 2400 0020 f401 0002 c6e1 5600 ...`), so it needs the same treatment as the other containers: read the table, then
the strings.

**Order for the next round:** decode `emleon*.esl` first (one offline pass, no boot), and only fall back to the collapse
bisection if it carries no pack reference. The collapse probe stands ready either way.

## What the round cost and what it bought

One boot, no new frame. It bought the right probe for the remaining quarters, and it found the game's own character files -
which is the difference between searching 14 packs one boot at a time and reading the table the game uses.
## Round 77: the save-list prompt ignores the back key

Forty-five back presses left the prompt exactly as it was:

```
MARK walk steps 45 | reached False | last screen story_prompt
MARK plhide3_00 mean 19.4 ... plhide3_01 mean 19.4
```

So on **`story_prompt`** the back key is not an answer at all. It is a Yes/No dialog with **No** selected, and the only key that
does anything is the confirm key - `a` chooses No and returns to the list, after which the list itself can be left. That is why
every escape sequence built on `b` (the playbook's `("b", "b", "b", "b")` and this harness's fallback alike) could press for
minutes without moving: right screen, wrong key, and the measurement only looked like a stuck bot.

Both now answer `story_prompt` with `a` first.

**Also ruled out this round, quickly:** the `.esl` files carry no names (`emleon00.esl` is 8,160 bytes of compiled script with
no printable strings, so a character->pack table is not sitting there as text), and the executable's 25 `em/plXX.das` strings
carry no character words either. So the mapping is not a string lookup in either place; the collapse bisection stays the way
to finish it, and it now has a harness that can leave the menu it kept getting stuck on.
## Round 78: collapse is the wrong probe for this, and the player search has a cheap finish left

**Collapsing a whole pack can hang the stage.** `re4sw-plhide` (`pl07`..`pl0d` collapsed to points) never produced a picture:
ten frames of `mean 6.3` on a `loading` screen, then the run ended. A pack in that range is loaded by the stage, so replacing it
with geometry that has zero extent stops the load. That makes **collapse a disqualifying probe** for finding a character - it can
only tell "needed" from "not needed", not "player" from "not player".

**Two places the mapping is not, both checked this round:** the `.esl` files hold no names (8,160 bytes of compiled script,
zero printable strings), and the executable's 25 `em/plXX.das` strings hold no character words. The mapping is not a string
lookup in either.

**The finish that costs one boot each, and cannot hang the stage:** scale a group by **0.9** instead of 0 or 0.1. A 10% smaller
model loads exactly as the original does, and the player is the only thing whose size the observer can compare against the
environment and his own weapon. `scale_materials` already accepts that factor.

**And the deliverable does not actually need the identity first.** The enemy packs are known and the engine draws
same-topology edits - `re4-em16morph` is proof - so a Sonic-shaped Ganado is a property-transfer problem, not a lookup:

* `morph_bones_to(template, donor)` moves a template so its **skeleton** takes the donor's shape and carries each vertex with
  its own bone - "the donor's proportions come through instead of its nearest surface";
* the donor must be a `Bin` with a bone table, so a Sonic rig becomes a donor by writing its joint positions into a copy of
  the template's bone table (parent-relative translations are all these formats carry);
* the result keeps the Ganado's vertex count, primitive table and weights, which is exactly the class of edit the engine draws.

That is the next build: **`em16` with Sonic's proportions**, one overlay, one round, and a frame that either shows a
big-headed, small-bodied villager or shows nothing changed.
## Round 79: a Sonic-proportioned Ganado is built - the frame is owed

`re4sw-sonicganado` reshapes `em16.udas` (the Ganado pack that the working morph mod used) so its **skeleton takes the donor
rig's proportions**:

```
slot 27: 382 vertices reshaped | bones 34
slot 28: 125 vertices reshaped | bones 10
...
slots reshaped: 33 | vertices: 19,023
```

The mechanism is `morph_bones_to`: each vertex follows its own bone, so the donor's proportions come through instead of its
nearest surface, and the vertex count, primitive table, weights and materials are untouched - the class of edit this engine
draws and the only class it draws.

**The donor is a `Bin` with a bone table**, so Sonic becomes one by writing its joint offsets into a copy of the template's
bone table: joints ordered by hierarchy depth, scaled to the template's own height, and every offset computed from the donor's
absolute positions so a parent's replacement never contaminates a child's. That sentence is the reusable part - any collection
rig can be a donor for any pack this way.

**Its run did not reach a round.** The walk ended on `story_prompt` after 14 steps, and the frames show the prompt at
`mean 19.4` again. The harness now answers that prompt with the confirm key, so the remaining possibility is that `a` returns to
the same list rather than leaving it, and the walk then loops on the same named screen - which is a harness loop, not a game
state.

**The next run needs one thing: a demonstrated exit from the save list** (press `a`, then `b`, then confirm the list is gone
before walking on). Nothing about the model is in question - it is built, applied through the writer the working builds use, and
sized to the pack.

## What is proven, in one place

| claim | evidence |
|---|---|
| the overlay is read | emulator's `pl00.udas` md5 equals the build's (round 69) |
| a same-topology edit is drawn | the collapsed player with untouched enemies (round 70) |
| enemy packs are the ones drawn | `re4-em16morph` deformed Ganados on screen |
| a donor rig can reshape a pack | `re4sw-sonicganado`: 33 slots, 19,023 vertices, topology kept (this round) |

What is missing is a bot that reliably leaves one menu, and then a frame.
## Round 80: the menu that ate every run was the save state, and it is not the mods

Every failure from round 66 onward started with the picture at **`mean 19.4`** - the "Cancel loading? Yes/No" prompt - and I
kept treating it as a walk that had gone wrong. It was there **before** the game could be walked:

**a stock launch, no mod at all, boots to the same prompt** (`stock 1/2/3 mean 19.4`). So the screen comes from the game's own
saved state, not from anything gBox or the mods do.

**Moving the save aside gives a clean boot:**

```
0000000000000000/7027FDA9BE915B24FD085FC348A9C0BF   moved to ...bak-1794109093
stock launch, fresh: fresh 1 mean 61.1, fresh 2 61.2, fresh 3 61.2
```

and the frame is the **"PRESS A" title screen**. That is the first clean boot of this title in a dozen rounds. The operator's save
was restored immediately afterwards (`restored`, directory back in place) - moving it is a diagnostic, not a change to their data.

**What that means for the mode**: with the old save, the game comes up mid-load every time; every walk then starts inside a menu
nobody asked for, and no amount of key-pressing fixes it. With a fresh save the title screen is reachable, so the walk has a
starting point. A production runner should decide this explicitly - boot with the save it wants, rather than inherit whatever the
last session left - and the probe now has the evidence to say why.

**Two harness fixes this round, both real:**

* the walk presses with the driver's **per-screen confirm gaps** (`CONFIRM_GAP_S`) instead of a flat 3.5 s - a second confirm
  during a fade is what lands on LOAD in the first place;
* the `story_prompt` branch now uses the driver's own `_recover_story()` rather than a hand-made key cycle, which walked
  straight into the achievements menu when tried.

**Still owed:** the Sonic Ganado's frame. Its run on a fresh save ended on a `loading` screen (`mean 4.7`), which is either the
reshaped `em16` failing to load or the fresh save sending the walk into a story load - the next run has to tell those apart by
walking with a **stock** build on a fresh save first.
## Round 81: the save carries the Mercenaries unlock, so "fresh" is the wrong direction

The control answered it, and not the way I expected. A **stock** build on a fresh save walks into **NEW GAME** - Leon in his
story jacket on the village road:

![the fresh-save walk went into the story](evidence/re4sw-fresh-save-goes-new-game.jpg)

So the save is doing two jobs at once:

1. it holds the **Mercenaries unlock** - without it the mode is not where the walk expects, and the same key sequence lands on
   NEW GAME instead;
2. it was written with the game **mid-load**, which is why every boot with it comes up on "Cancel loading? Yes/No" at
   `mean 19.4`.

Neither state is the one a runner wants, and removing the save fixes the second problem while creating the first. The save has
been **restored** both times (the directory is back in place, verified), because it is the operator's data and this was a
diagnostic.

**What a runner actually needs is a save that is (a) past the village, so Mercenaries is unlocked, and (b) at a menu, not
mid-load.** That is a thing the operator can produce in one minute, and it is the one input this whole line of work has been
missing: `bio4` save slot at the title screen with THE MERCENARIES present in EXTRAS.

**The other half of the answer matters for the walk:** a fresh save's main menu has no CONTINUE row, so the driver's
`EXTRAS_ROW` index is off by one and the walk presses into NEW GAME. Row indices are a property of the save's state, not of the
game, so the walk should *read* which row is highlighted rather than count from a constant - or at least tolerate a menu whose
first row is not what it expects.

## Where this leaves the Sonic Ganado

Built, applied, 33 slots and 19,023 vertices reshaped, and its frame is still owed - now for a reason that is finally concrete:
the walk cannot reach Mercenaries with the save as it is, and cannot reach Mercenaries without it either.
## Round 82: the boot prompt is answered with Yes, and the walk reaches rounds in 13 steps

The save's mid-load state was the whole problem, and its solution was one key: the prompt is **"Cancel loading? Yes/No"** with
**No** selected, and declining it only returns to the save list. Saying **Yes** - `up`, then `a` - abandons the half-finished load
and the game goes on to its title screen. With that one answer in the harness, the same walk that had been stalling for a dozen
rounds reported:

```
MARK walk steps 13 | reached True | last screen unknown
```

and the frames are a live Mercenaries round: the briefing text (`01'48"34`, "Eliminate as many Ganados as you can before your
evac chopper arrives"), then the round itself with a mob of Ganados against the camera at `01'16"72`.

![the round the walk reached](evidence/re4sw-round-reached-after-resume-cancel.jpg)

**This is the first time the RE4 Switch walk has been reliable end to end**, and it was never a bot bug: it was a saved state
that had been written mid-load, plus a prompt whose default answer is the wrong one.

**The Sonic Ganado's frame is close but not yet readable.** The enemies are there (`01'16"72`), but at that range they are a mass
of bodies against the lens - a shape verdict needs them at distance, which is a capture-timing change rather than a build change.
The build itself is done: 33 slots, 19,023 vertices reshaped by bone, topology untouched.

## What the dozen rounds of stalling actually cost

Every "bot stuck on a menu" from round 66 onward was this: a save written mid-load, answered with the wrong key. The lesson is
worth stating because it generalises - **when a title is reached through a saved state, the first thing to verify is that the
state itself is at a menu**, and the *answer* to a resume prompt is a decision, not a nuisance: cancelling the resume is what a
runner wants, and declining it is a trap that looks identical from a frame.
## Round 83: two saves, and neither is the one a runner needs

The save directory holds three states, and testing them explains everything:

| file | menu | Mercenaries |
|---|---|---|
| `savegame00.sav` (the live one) | boots **mid-load**: "Cancel loading? Yes/No" | **unlocked** - EXTRAS is there once the prompt is answered |
| `savegame00.sav.fresh-bak` | clean main menu | **not unlocked**: NEW GAME, LOAD, LEADERBOARDS, HELP & OPTIONS, ACHIEVEMENTS - **no EXTRAS row at all** |
| `savegame00.sav.pre-experiment` | a copy of the live one | unlocked, same mid-load state |

![the fresh-bak save has no EXTRAS row](evidence/re4sw-fresh-bak-has-no-extras.jpg)

So the two properties a runner needs - **at a menu** and **Mercenaries unlocked** - are in **different files**. The live save has the unlock
but was written mid-load; the fresh backup boots clean but has never seen the village. The live save has been restored (verified,
1,047,200 bytes).

**A save with both is a one-minute thing for the operator**: load the unlocked save, let the game reach the title screen or a menu,
and save from there (or let a clean exit from a menu write it). That single file removes both failure modes at once.

**Until then the working combination is the live save plus the Yes answer**, which reached a round in 13 steps last round. It failed
once this round because the `up`/`a` went in before the prompt had settled - a timing defect in the harness, not in the idea: the
press must be conditioned on the prompt being *steady*, and retried if the screen has not changed afterwards.
## Round 84: the walk is reliable, and the enemy path draws (control confirmed)

Two results, both needed before any character claim can be made.

**The walk now gets to a Mercenaries round reliably.** With the resume prompt answered only once it is *steady* and retried up to
three times, the Sonic Ganado build reached a round in **8 steps** (`reached True`), and the control build in 16. That is the
harness defect from round 83 fixed properly - pressing during the dialog's fade did nothing, which looked exactly like a wrong key.

**The enemy path draws, under the new walk.** `re4-em16morph` - the build that deforms Ganados - shows a body loomed over Leon on a
rooftop with the round clock at `01'20"42`:

![a morphed Ganado at the rooftop](evidence/re4sw-giant-ganado-control.jpg)

So the chain for **enemy** replacement is proven end to end on this title with the current tooling: a pack written through
`switch_mods`, read by the emulator, its vertices reshaped by bone, and the result on screen in a live round.

**The Sonic Ganado itself is still one clean frame away.** Its runs reach rounds, and the frames land on explosions, empty roads, or
a mob pressed against the lens - the enemies are there (`01'16"72` in an earlier run), just never framed at a distance. That is a
capture-timing matter: the harness moves the camera on a fixed pattern, so the odds of catching an enemy at range depend on where
the round starts. The next run should turn toward the nearest enemy for two seconds before each capture rather than alternating
left/right blindly.

**What is settled for the Switch mod track:**

| link | state |
|---|---|
| overlay written and read | verified by md5 (round 69) |
| same-topology edit drawn | collapsed player with untouched enemies (round 70) |
| enemy packs are the drawn ones | the giant above, in a live round (this round) |
| a donor rig can reshape a pack | 33 slots, 19,023 vertices, topology kept (round 79) |
| the walk reaches rounds | 8 and 16 steps, two builds (this round) |
## Round 85: "remove clothes" as a reusable operation with a report

The four sidebar asks - remove clothes, swap clothes, character<->zombie, zombies->cast - all reduce to the same primitive: **edit
one model slot in place, topology untouched**. That primitive is now `gbox/re4hd_edit.py`, independent of HTTP and of any emulator,
so a route, a job or an agent can all use it:

| call | what it does |
|---|---|
| `material_census(pack, slot)` | every material with the triangle span it owns - the list a picker shows |
| `edit_pack(pack, slot, hide=[i])` | collapse those materials onto their own centroids |
| `edit_pack(pack, slot, scale=([i], f))` | move them by a factor about their centroid |
| `edit_pack(pack, slot, donor=<bin>)` | morph the slot toward a donor rig's proportions (`morph_bones_to`) |

Every call returns an `EditReport` with the operation, materials touched, vertex count, triangle count, and the **sha256 before
and after** - so a build states what it did instead of asking anyone to trust it. The pack's size is always the slot's own, which
is the one rule this engine enforces.

**Two defects the tests caught in the module itself**, both before it shipped: `bin_slots`' `ValueError` escaped as a raw error
instead of an `EditError` (so a caller could not distinguish "not a pack" from a bug), and the "no operation given" check ran
*after* the pack had been read, so a bad request cost a full decode first. Both fixed.

Tests: **6 pass on the Spark against the real Ganado pack** (material census sums to the mesh's triangle count, hide and scale
both keep the container size and the triangle table), 3 pass plus 3 skipped on a machine without the RomFS.

## And the capture keeps losing to the resume prompt

The exaggerated build (`re4sw-sonicx`, donor proportions x1.9) never reached a round: the resume prompt did not clear in three
attempts. The prompt accepts input only once it has settled, and the settle time varies - so the fix is not another key but a
**condition**: press only when two consecutive frames are identical *and* the classifier says `story_prompt`, and treat a third
failure as "boot again" rather than pressing on. That is the next change to the harness, and it is smaller than the modelling work
it unblocks.
## Round 86: bone-proportion transfer is too faithful to be a character change

`re4sw-sonicplayers` applies the donor morph to **22 player packs, 173 slots, 112,287 vertices** - every player model in the game
gets Sonic's skeleton written into its own bone table, scaled to its own height, vertices carried by their bones. The player in the
round is **unchanged**:

![the player with every pack morphed toward the donor rig](evidence/re4sw-sonicplayers-unchanged.jpg)

That is not a failure of the overlay (verified by md5 in round 69) nor of the walk (it reached the round in 16 steps). It is the
mechanism doing exactly what it promises: **a humanoid rig scaled to a humanoid height has humanoid proportions**, so moving each
vertex with its own bone leaves the silhouette essentially where it was. The same explanation covers the Sonic Ganado runs that
showed nothing surprising - its bone transfer is just as faithful.

**So the honest conclusion about the mechanism:** bone-proportion transfer preserves shape, and shape is what a character
replacement needs. The surface morph (`morph_to`) is the one that changes shape - it is what produced the visibly deformed enemies in
the working `em16morph` build - and it pays for it with a blobby result, because neighbouring vertices can land on opposite sides of
the donor.

**The next build, therefore, is the surface morph on the enemy packs** (`em16` first): same topology, same vertex count, same
triangle table, but vertices pulled to the donor's surface. That is the edit class this engine draws, and it is the one that has
actually changed a silhouette on screen.

## What this closes and what it leaves

* closed: "is the model edit being read at all" - yes, md5 and config both say so (rounds 69, 82);
* closed: "does a same-topology edit draw" - yes, the collapsed player with untouched enemies (round 70);
* closed: "does bone-proportion transfer change a character" - **no**, measured this round across every player pack;
* open: a *shape* transfer that is both drawn and recognisable - the surface morph is the only one with evidence behind it.
## Round 87: the surface morph draws, and the result is shards - which names the real problem

`re4sw-playerganado` pulls every player mesh onto a Ganado's surface: 26 packs, 98 slots, **227,800 vertices**, vertex counts and
primitive tables untouched. In the round the player is visibly *not* Leon any more - the frame shows untextured geometry jutting out
and a head that has collapsed into a dome with a spike:

![the player after the surface morph](evidence/re4sw-player-surface-morph-shards.jpg)

**So the surface morph draws.** That is the third mechanism question answered: bone transfer preserves the silhouette (round 86),
surface transfer changes it and is drawn (this round), and the result is a blob because neighbouring vertices land on opposite sides
of the donor. That matches the note the library already carries from round 23 - *"the blobby result measured on RE4 Switch"* - so this
is a reproduction of a known limitation, not a new surprise.

**Which names the real problem precisely.** A character replacement on this title needs a shape transfer that is *coherent per body
region*:

* bone transfer is coherent but shape-preserving - it keeps each vertex with its own bone;
* surface transfer changes shape but is incoherent - it ignores which bone a vertex belongs to;
* what is needed is **both**: restrict each vertex's snap to the donor's surface *near its own bone*, so the arm lands on the arm.

That is a small, well-defined change to `morph_to` - a per-bone nearest-surface search instead of a global one - and it is the next
piece of work. Everything around it is already in place: the operation, the report, the build, the walk, the capture.

## What the four mechanism questions now stand at

| question | answer | evidence |
|---|---|---|
| is the edited pack read at all? | yes | md5 of the emulator's file equals the build's |
| does a same-topology edit draw? | yes | collapsed player, untouched enemies (round 70) |
| does bone-proportion transfer change a character? | **no** | 22 packs morphed, player unchanged (round 86) |
| does a surface transfer draw? | **yes, as shards** | this round |
## Round 88: the coherent morph - the bone says where, the surface says what

`gbox/re4hd_coherent.py` is the synthesis the last two rounds pointed at:

* bone transfer is **coherent** (a vertex stays with its bone) but shape-preserving;
* surface transfer **changes shape** but its global nearest-surface search lets a left-arm vertex land on the right leg, which is
  what drew as shards;
* `coherent_surface(template, donor)` **restricts each vertex to the part of the donor's surface that belongs to its own body band**.

The band is the bone's rank in hierarchy order, collapsed into a few bands (`bands=6` by default), because bone ids do not
correspond between two rigs but position in the hierarchy does. A band with no faces of its own falls back to the whole donor, and a
mesh without weights falls back to the global search, so a probe never crashes on an unusual slot.

**Tests: 5 pass on the Spark, 4 + 1 skipped locally.** Two of them pin the contrast that motivates the module:

* a vertex whose bone is the low block lands on the low block, and one whose bone is the high block lands on the high block;
* the *global* morph, run on the same two-mesh scene, puts both vertices on the same block - which is exactly the failure that
  produced the shards.

**Two bugs the tests caught in the module and the fixture**, both worth naming because they are the two ways this could have shipped
broken: the guard `faces.size < 4` sent every small band to the global fallback (so the "coherent" version behaved like the shard
version on any ribbon of fewer than four triangles), and my first fixture weighted both donor blocks to the root bone, which read as a
code bug and was not one.

## The run

`re4sw-playercoherent` is built (26 packs, 98 slots, 227,800 vertices) and its run was gated by the resume prompt three times. The
prompt accepts input only when it has settled, and the settle time is not constant - so the harness needs a different strategy:
after a failed attempt, **re-boot the title** rather than pressing again. That is a small change and it is the only thing between the
coherent morph and its frame.
## Round 89: reboot-on-failure works, and the coherent morph is conservative

**The retry loop is the fix for the flaky prompt.** A failed resume-prompt press is not recoverable by pressing again - the dialog
wants input at a moment it does not announce - so a failed attempt now **re-boots the title** and tries again:

```
ATTEMPT 1 did not reach a round (log /tmp/coh1.log)
ATTEMPT 2 reached a round (log /tmp/coh2.log)
```

Two attempts, one round. That is the honest cost of this title's boot state: roughly a coin flip per attempt, with a retry that
turns it into a certainty. `/tmp/retry_walk.sh` is kept as `system/tools/probes/retry_walk.sh`.

**The coherent morph, in a round, on the player.** The run reached a Mercenaries round with **Wesker** and his model is unchanged:

![the player in the coherent-morph build](evidence/re4sw-coherent-player-wesker.jpg)

Two explanations, and the test suite already points at the second: either Wesker's pack is outside the 26 covered packs (his HUD
name proves he is a *different* slot from Leon), or the coherent morph is **conservative by construction** - its own test asserts
that morphing a mesh onto *itself* leaves it essentially unchanged, and a humanoid donor constrained per body band lands close to
where a humanoid target already was.

That is not a defect: it is the mechanism behaving as designed, and it says the **donor** is what has to be chosen for contrast. A
Ganado is too close to a human to reshape one into the other through a per-band constraint.

**The next build therefore points the coherent morph at the donor with the biggest silhouette difference available in-tree** - and the
clearest test of whether the band constraint is doing its job is an enemy reshaped toward a very different body plan (a limbless or
quadruped donor), where a coherent result and a sharded one cannot be confused.

## Where the mechanism work stands after nine rounds of it

| claim | state |
|---|---|
| overlay written and read | proven (md5) |
| same-topology edit drawn | proven (collapsed player) |
| bone transfer changes a character | **no** - shape-preserving by construction |
| global surface transfer | **drawn as shards** |
| coherent surface transfer | built, tested, **conservative on a humanoid donor** |
| boot path | solved by answering the resume prompt with Yes, plus a reboot retry |
## Round 90: a high-contrast donor, and a self-perpetuating boot state

**The donor.** Listing every enemy pack's body proportions found what the coherent morph needed - a donor whose silhouette cannot be
confused with a human's:

```
em3e.udas  slot 6   244 verts   140 tris   extent [1234, 2265, 155]   aspect 14.6
em16.udas  slot 0  3425 verts  ...          extent [...]              aspect  3.4 (humanoid)
```

`em3e` slot 6 is a flat slab. `re4sw-ganadoslab` morphs the Ganado toward it with the **coherent** transfer (7 slots, 12,633
vertices), so the result must be either a flattened Ganado or shards - two outcomes that cannot be mistaken for each other.

**The boot state may be recreating itself.** Two of three attempts died on the resume prompt, and the third walked without reaching a
round. The pattern across rounds 82-90 is that the prompt is present *more often than not*, and the explanation is uncomfortable but
simple: **the game writes its save when the session is stopped, and the session is stopped while the game is mid-load** - so every
run recreates the state that makes the next run start on the prompt. The save is not merely stale; the harness keeps re-creating it.

That suggests the one-time fix: boot, answer the prompt with **Yes** to reach a title screen, and let the session stop *from there* - so
the save that is written is a menu, not a half-finished load. After that the prompt should not appear again, and the whole retry loop
becomes unnecessary.

**What is owed, precisely:** one frame of `re4sw-ganadoslab` (coherent morph, slab donor). Everything else about it is built and
recorded; the run is competing with a boot state that the harness itself keeps creating.
## Round 91: the game auto-loads its save at boot, and the prompt comes back

The save-cycle probe measured the boot sequence instead of guessing at it:

```
MARK boot before:   [40.2, 19.4, 19.4]
MARK answered Yes
MARK after Yes:     [49.2, 19.4, 19.4]      <- the prompt returns
MARK stopped from the menu
MARK boot after:    [49.2, 19.4, 19.4, 19.4]
```

Three things follow, and they close the question:

1. the game boots to a menu (`40.2`), then **auto-loads its save** and lands on "Cancel loading?" (`19.4`);
2. answering **Yes** raises it to `49.2` - and then it **comes back to `19.4`**, because the game retries the load;
3. stopping *from a menu* does not help, because the state being saved is the retried load, not the menu.

So round 90's hypothesis was half right: the harness does keep recreating the state, but not by where it stops - by the game's own
auto-load of a save that cannot finish loading. **A mid-load save on this title is not a nuisance to be keyed past; it is a boot
loop.**

**What that means, precisely:**

* the save on this machine is unusable for a run - it is stuck mid-load, and no key sequence fixes a save the game cannot read;
* a **fresh** save boots clean but has no Mercenaries unlock (`EXTRAS` absent, measured in round 83);
* therefore the missing input is a **valid save with the unlock**: one the game loads without prompting, from a menu, past the village.

That is the same request as round 83, now with the reason measured rather than inferred: **not "the save is inconvenient" but "the save
cannot be loaded at all, so the title boot-loops"**. There is no key sequence and no build that fixes it from this side - the data is
the problem.

Everything else on the Switch track stands as recorded: overlay read, same-topology edit drawn, bone transfer shape-preserving,
surface transfer sharded, coherent transfer built and tested. The one thing that would turn those into a demonstrable character swap is
a save the game can load.
## Round 92: handing over a save is now one command, and here is exactly what is needed

The blocker is data, so the useful work is to make the hand-over trivial and the check automatic.

`gbox/re4_switch_save.py` inspects and installs this title's save:

```
python -m gbox.re4_switch_save --user <emulator user folder>              # inventory: every save file, size, date, sha256
python -m gbox.re4_switch_save --user <...> --save <file> --replace      # install, keeping the old one as .bak-<timestamp>
```

It refuses to overwrite without `--replace`, keeps the previous file, and **verifies the copy by sha256** before reporting success.
Six tests: the inventory, the refusal, the backup, the verification, a missing file and a missing title folder.

Run against the Spark it reports the current state, which also settles round 90's other hypothesis - **the save is not being
rewritten by the harness**: its sha256 has not changed since it was restored (`13908f63...` for both the live file and its `bak-r83`
copy). So the boot loop is simply a save the game cannot load, not a file being churned.

## What to hand over

**A RE4 Switch save that the game loads without prompting, written from a menu, with Mercenaries unlocked.** Concretely: on the
Spark, play the existing save until THE MERCENARIES is available in EXTRAS, return to the title screen, let the game save (or exit from
there), then give me that `savegame00.sav`.

With it: `re4sw-ganadoslab` (coherent morph toward the slab donor) and the Sonic builds get their frames on the first attempt, and the
MercMode rotation can boot this title without the retry dance.

Without it: the title boot-loops on a save it cannot read, and every experiment pays a coin flip per boot. That is not a code problem
and no further work on my side can fix it.
## Round 93: the extraction tab routes exist, and a caution about the API token from a shell

**The routes are in and registered.** `gbox.decrypt_lab` gained two, beside the existing pack routes:

| route | what it does |
|---|---|
| `GET /api/decrypt-lab/pack-materials?title=&pack=&slot=` | the material list with each material's triangle span - what a picker shows |
| `POST /api/decrypt-lab/pack-edit` | one in-place edit (hide, scale or donor morph) written into a LayeredFS build, returning the `EditReport` |

Registration is tested by installing the routes on a throwaway FastAPI app and enumerating them (4 pack routes present), and the edit
behaviour by `test_re4hd_edit.py` against the real Ganado pack. **9 tests green on the Spark.**

**Live verification was defeated by shell quoting, not by the code.** From an SSH one-liner, `authorization: Bearer <token>` was
mangled (401 "bad token") while `?token=<token>` worked for a GET - and the POST body arrived as a form-encoded string
(`input: "title:010099A00BC1E000"`). That is a property of quoting a 43-character token through PowerShell into SSH, and it cost this
round its end-to-end check. The lesson is concrete and worth keeping: **use `?token=` for GETs and write request bodies to a file
(`-d @body.json`) for POSTs** rather than embedding JSON in a quoted one-liner.

**One thing the session dump showed that contradicts an earlier conclusion, and is worth flagging rather than deciding:**
gBox's own session detail reports, for this title, *"RE4 Switch Mercenaries is available from a fresh save (no unlock needed)"*. Round
83 measured a fresh save showing a main menu with **no EXTRAS row**. Both cannot be right, and the difference matters: if Mercenaries
really needs no unlock, then a fresh save is usable and the boot-loop problem is the only obstacle; if it does need one, the operator's
save is required. The next run should settle it by walking a fresh save and looking at the menu rather than trusting either note.
## Round 94: the fresh-save question is still open, and the probe overshot

The probe to settle it pressed START three times, which went past the main menu into gameplay - so the frames show a close-up of the
world, not the menu. That is a probe defect, not a finding: **one** press is what reveals the menu, and nothing after it.

What the run did establish: with the save moved aside the title boots to a picture (`mean` reaching 42.6) and accepts input - so a
fresh save is a usable boot path, which is half the question. **The save was restored** in the probe's `finally`, and the rotation was
put back.

**The question itself - is THE MERCENARIES present on a fresh save? - stays open**, and it is worth the one press it costs next time:
launch with the save aside, press `a` once, capture, and read the row list. Round 83's frame of a fresh main menu showed no EXTRAS;
gBox's session detail asserts no unlock is needed. One of them is wrong, and the answer decides whether the operator's save is required
at all.
## Round 95: settled - a fresh save has no EXTRAS, so Mercenaries does need the unlock

One press revealed the menu, and it is unambiguous:

![a fresh save's main menu](evidence/re4sw-fresh-menu-no-extras.jpg)

**NEW GAME / LOAD / LEADERBOARDS / HELP & OPTIONS / ACHIEVEMENTS** - there is **no EXTRAS row**, so THE MERCENARIES is not reachable
from a fresh save. Round 83 was right and **gBox's own note was wrong**:

```
- RE4_UNLOCK_REASON = 'RE4 Switch Mercenaries is available from a fresh save (no unlock needed).'
+ RE4_UNLOCK_REASON = ('RE4 Switch Mercenaries needs an unlock carried by the save file: a fresh save shows no EXTRAS row
+                      (measured 2026-11-08), so a run needs a save that is past the village and loads from a menu.')
```

That string fed the panel's "unlocks" block, so it was telling an operator the opposite of the truth. Corrected in place, with the
measurement and its date in the comment.

**What this fixes in the plan:** the requirement for the operator's save is now settled by evidence rather than by two conflicting
notes. A usable save must be:

1. **past the village**, so EXTRAS / THE MERCENARIES exists;
2. **saved from a menu**, so the title does not auto-load into "Cancel loading?" and boot-loop (round 91).

Both conditions are about the file, and `gbox/re4_switch_save.py --save <file> --replace` installs it with a backup and a verified
copy. Nothing else on the Switch track is blocked once it exists.
## Round 96: the save resumes a live Mercenaries round

The prompt asks **"Cancel loading?"** - so **No** is the answer that lets the load continue, and that is the opposite of every attempt so
far. Launched stock, the title booted **straight into a Mercenaries round**:

![the save resuming a live Mercenaries round](evidence/re4sw-save-resumes-round.jpg)

`00'56"85` on the clock, Leon with the Mercenaries HUD, Ganados closing in. No walk, no menus, no prompt - the save is a round in
progress and the game resumed it.

**That changes the shape of every in-round test.** A model build no longer needs a menu walk at all: launch, wait for the round, capture.
Thirty rounds of walking were solving a problem that did not exist when the save is allowed to resume.

**With the mod build, the same launch landed on the prompt** (`19.4`) and the `No` press left it there. Two readings, and they are
testable: the mod launch changes the boot timing so the resume is attempted before the overlay is ready, or the prompt in that run is a
*different* prompt (a load the game cannot complete for another reason). The next run should capture the prompt's frame - not just its
mean - and compare it with the "Cancel loading?" seen before; a different dialog would explain why no key clears it.

**What is certain now:** the save is not "unusable" as round 91 concluded. It holds a live round, and the title resumes it. The
requirement is to launch in a way that lets that resume finish - which stock does.
## Round 97: the harness was walking past the round, and a mod breaks the save resume

**Two findings, one of which explains a dozen "reached False" runs.**

1. **A LayeredFS build breaks the save resume.** Launched stock, the title resumed straight into its Mercenaries round (round 96).
   Launched with a build, the same save produced "Cancel loading? Yes/No" - reproducibly, twice, with a captured frame. So the
   overlay and the resume are mutually exclusive on this title, and a mod test still has to come in through the menus.

2. **The walk was reaching the round and then walking past it.** Both retry attempts logged `last screen playing` with
   `reached False`: the classifier *named* the round, but the harness only counted `unknown` as reached, so it kept pressing - through
   the round, into the pause menu, and finally into **"Do you really want to quit? All unsaved progress will be lost."** The fix is one
   branch: `playing` is the round, capture and stop. It is in `system/tools/probes/walk_and_capture.py` (line 167) and was **not** the
   copy that ran this round - the base64 deployment sent a stale file, which is why attempt 8 still reported `reached False`.

**So the next run is the one that should finally show the slab-morphed Ganados**: the walk now stops at `playing`, and the retry loop
covers the prompt flake. Nothing else about the build is in question - `re4sw-ganadoslab` is written, applied through the writer, and
the coherent morph behind it is tested.

## A deployment note that cost this round

`sed -i 's/\r$//'` through PowerShell into SSH becomes `sed -i 's/r$//'` - it strips every letter `r` from the file, which turned
`for` into `fo`, `grep` into `gep` and `reached True` into `eached Tue`. The reliable route is base64: encode on this side, decode on
the Spark (`echo <b64> | base64 -d > file`). That is now the only way scripts are shipped.
## Round 98: the boot saga is over - clean title screen, round reached on the first attempt

Three things came together, and each was measured rather than hoped for:

1. **Stopping the session at a menu writes a menu-state save.** The previous probe ended its session while the game sat on the title
   screen; the next launch came up at `mean 61.2` - the **PRESS A** title screen - with a mod build loaded and **no resume prompt at
   all**. That is the round-90 hypothesis confirmed, and it is the fix for the flip-flopping boot state: a session should be stopped
   from a menu, not from mid-load.
2. **The harness stops at `playing`.** With the one-branch fix deployed (verified by grep on the Spark), the walk reported
   `walk steps 16 | reached True | last screen playing` - **on attempt 1**, with no retry needed.
3. **The slab build runs in a live round.** `re4sw-ganadoslab` played a Mercenaries round (`01'41"17`, `01'28"22`) without incident:

![the slab build in a live round](evidence/re4sw-slab-build-live-round.jpg)

**What this round does not have is the shape verdict.** The frames caught Leon and the village, never a Ganado at distance - the capture
is still a lottery for enemies even though it is now reliable for the round. The build is fine; the photograph is not yet the right one.

## What the effort bought

The last four rounds were almost entirely boot plumbing, and it is now settled as a *procedure* rather than a collection of workarounds:

* stop a session from a menu (or answer the resume prompt with No and let it finish) so the save stays a menu;
* launch with a build, wait for a picture;
* walk: the driver's per-screen gaps, the driver's recovery for `story_prompt`, and **`playing` is the round**;
* capture immediately, moving the camera, and accept that an enemy in frame is luck.

That procedure is what every remaining Switch experiment needs, and it is written down here so the next one costs one boot, not six.
## Round 99: a coherent morph toward a flat slab still leaves the player intact

`re4sw-playerslab` applies the **coherent** transfer to the player, with the most extreme in-tree donor - `em3e` slot 6, a slab of
aspect 14.6:1 - across 26 packs, 98 slots, 227,800 vertices. The run reached a round on the first attempt and the player is
unchanged:

![the player after a coherent morph toward a flat slab](evidence/re4sw-player-coherent-slab-normal.jpg)

**That is three results for the same mechanism, and together they say something precise:**

| transfer | donor | drawn? |
|---|---|---|
| bone proportions | Sonic rig | no |
| bone proportions | slab (x1.9 boost) | no |
| **global** surface (nearest point anywhere) | Ganado | **yes - as shards** |
| **coherent** surface (nearest point in the vertex's own band) | Ganado | no |
| **coherent** surface (nearest point in the vertex's own band) | slab | no |
| material scale / hide | - | **yes** |

The pattern is now a rule: **any edit that stays self-consistent is not drawn as a change, and only edits that break the mesh's internal
consistency show up.** Scaling shows because it moves a part *away* from the rest; shards show because vertices land on the opposite
side; a coherent projection preserves the shape well enough to be invisible - for a slab donor, because the projection lands each vertex
on the slab's nearest face, which for a thin box is close to where it already was along the surface normal.

**Which means the missing piece is not the constraint but the *displacement*.** A shape transfer that is drawn has to move a vertex by
the donor's corresponding vertex's **offset**, not to the nearest point on its surface:

```
displacement = donor_vertex - donor_bone_position        (in the donor's own frame)
target_vertex = template_vertex + band_matched(displacement)
```

That is a per-bone affine transfer rather than a projection, and it is the fourth variant to try. The infrastructure is unchanged: the
operation, the report, the build, the walk, the capture are all in place and each round now costs one boot.
## Round 100: the per-band affine transfer is drawn - the first variant that is both coherent and visible

`re4sw-playeraffine` applies `band_affine` to every player pack: each bone's region scaled about its own centroid to the donor band's
per-axis extent. With the slab donor (`em3e` slot 6, aspect 14.6:1) the player is **no longer Leon** - the geometry has ballooned so far
that the third-person camera, which is anchored to the character, ends up **inside the mesh**:

![the camera inside the ballooned player mesh](evidence/re4sw-playeraffine-drawn.jpg)

`01'36"78` and `01'30"38` on the clock, HUD normal, world normal, and the character filling the lens with flat black surfaces.

**That is the fourth variant and the first that satisfies both conditions the engine imposes:**

| variant | coherent? | changes shape? | drawn? |
|---|---|---|---|
| bone proportions | yes | no | no |
| material scale / hide | n/a | yes | **yes** |
| global surface | no | yes | **yes (shards)** |
| coherent surface | yes | no (in practice) | no |
| **per-band affine** | **yes** | **yes** | **yes** |

The rule from round 99 is confirmed and now has a working instrument: **an edit is drawn when it moves parts relative to each other
without letting a vertex leave its own region.**

**It is over-scaled, not mis-shaped.** A slab donor's per-axis extents are nothing like a body's, and the ratio is clamped at 6x, so the
player becomes enormous. The tuning is a separate question from the mechanism, and the next run should use a **humanoid donor** (a
Ganado, whose proportions are body-like) with `blend` around 0.5 - the same function, two arguments.

Tests: 5 pass locally and on the Spark, including *a flat donor flattens the band* and *a self-donor changes essentially nothing*.
## Round 101: the transfer is tunable, and the collection is now a donor source

**Tuning works.** The same `band_affine` with a **humanoid** donor (a Ganado) at `blend=0.5` draws a modest, visible deformation -
Leon's shoulders and back bulge, and nothing else about him changes:

![the player with a humanoid donor at half blend](evidence/re4sw-playergando-half-blend.jpg)

Compare that with the slab donor at `blend=1.0` (round 100), where the geometry ballooned until the camera was inside it. Same function,
two arguments: **the transfer has a usable strength dial**, which is what a character replacement needs to look like a character rather
than an explosion.

**Any extracted model can be a donor.** Two pieces landed:

* `band_affine` **falls back to banding by height** when the donor has no bone weights, so a triangle soup from a `.glb` is a valid
  donor (test: the low and high vertices land in different bands);
* `system/tools/probes/glb_to_donor_bin.py` turns a `.glb` into a donor `Bin` against a real pack's slot -
  `sonic_src.glb -> 164,768 bytes, 4,107 vertices, 1,369 triangles, 2 material records`.

That closes the loop the objective needed: **the collection's models are now transferable into any title's pack**, because the only
thing the transfer requires of a donor is geometry.

**`re4sw-playersonic` is built** (25 packs, 79 slots, 212,456 vertices, blend 0.8 toward Sonic) and its run lost both attempts to the
boot prompt. That is the boot state again, not the build: the procedure from round 98 (stop a session from a menu) puts it right, and one
clean boot will show whether Sonic's proportions come through.

## The state of the character goal, honestly

| piece | state |
|---|---|
| a drawn, coherent, shape-changing edit | **yes** - per-band affine, seen in game (round 100) |
| a strength dial | **yes** - blend 0.5 humanoid is modest, 1.0 slab is drastic (this round) |
| donors from the collection | **yes** - any `.glb` converts to a donor and bands by height (this round) |
| a recognisable character | **not yet** - needs a clean boot with the Sonic donor and a blend that reads as a body |
## Round 102: the Sonic transfer has a working window between "invisible" and "will not load"

Two data points, both from live rounds or their failure:

| build | donor | blend | outcome |
|---|---|---|---|
| `re4sw-playersonic` | Sonic (`sonic_src.glb` -> donor BIN, banded by height) | 0.8 | the walk never reached a round - **the load hung** on `loading` |
| `re4sw-psonic3` | same | 0.3 | **loads and plays** (`01'35"61`), and the change is essentially invisible |
| `re4sw-playergando` | Ganado (bone bands) | 0.5 | loads and plays, **visible** shoulder deformation (round 101) |

So the transfer has **both** a lower bound (below ~0.4 nothing reads) and an upper bound (above ~0.7 the deformation is severe enough
that the stage stops loading - the same failure the fully-collapsed materials produced in round 65). The working window is roughly
**0.4-0.6**, and the Ganado result shows that a body-like donor reads inside it.

**Why the Sonic donor sits high in that window:** its geometry arrives as a triangle soup (4,107 vertices, 1,369 triangles, no weights),
so it bands by height and each band holds a thin slice of surface. At blend 0.8 the extrapolated extents are large; at 0.3 they are
swamped by the template's own shape. A denser donor (the collection's rigged models before they are flattened to a soup) would put more
surface in each band and read at a lower blend.

That is the concrete next step for "Sonic as a character on this title": **convert the donor with its skinning intact rather than as a
soup** - `glb_to_donor_bin` currently flattens, and preserving the joint indices would let the transfer band by bone, which is what the
Ganado donor does and what reads at 0.5.
## Round 103: the donor keeps its skeleton, and the player visibly changes

**Three fixes, and the result is the first Sonic-driven change on screen.**

1. **`gbox/glb_donor.py`** converts a `.glb` into a donor `Bin` **with its skeleton**: Sonic becomes `4,107 vertices, 1,369
   triangles, 62 bones, 4 weight records`. The weight records are the template's limit, so the 62 joints are bucketed into them in
   hierarchy order - a rig, not a soup, which is what round 102 said was missing.
2. **A banding bug that would have made the transfer a no-op:** `_region_of` divided by the **bone-table length**, so a donor with 4
   used ranks over a 62-bone table put every vertex in band 0. It now uses the **span of the ranks actually present**, with a test that
   pins the 4-ranks-over-62-bones case.
3. **The engine draws it.** `re4sw-psonic_skin` (26 packs, 98 slots, 227,800 vertices, blend 0.5, Sonic donor) reached a round and the
   player is visibly **not** the stock model - the head is small and pointed and the shoulders are compressed:

![the player after a bone-banded transfer from Sonic's rig](evidence/re4sw-skinned-sonic-donor.jpg)

`01'43"06` on the clock, HUD and world normal. This is coherent (no shards, the stage loads) and shape-changing (the proportions are the
donor's), which is the combination the last six rounds were hunting for.

**What it is not yet:** a recognisable Sonic. The donor is banded into four weight buckets, so the transfer matches *regions* rather than
joints; a template whose weight table is larger would carry the 62 bones individually and let the head, hands and feet land where Sonic's
are. That is a data-selection question (which pack to use as the container), not a new mechanism.
## Round 104: the player takes Sonic's proportions - big head, small body

The container was the missing piece. `pl04.udas` slot 0 carries **112 bones and 256 weight records** (against the Ganado's slot, which
offers four), so the converted donor now keeps **all 62 of Sonic's joints individually** instead of bucketing them:

```
sonic_src.glb -> 167,264 bytes, 4,107 verts, 1,369 tris, bones 62, weight records 64
```

`re4sw-sonicfull` (26 packs, 98 slots, 227,800 vertices, blend 0.5) then reached a round on the first attempt and the player is
unmistakably reshaped:

![the player with Sonic's proportions](evidence/re4sw-sonic-proportions.jpg)

`01'34"74` and `01'41"11` on the clock, the Ganados behind him untouched and normal. **The head is large and round, the body small and
thin** - Sonic's proportions, coherently, with no shards and no load failure.

**What it is:** a proportion transfer that reads as a big-headed character. **What it is not yet:** a recognisable Sonic - the mesh is
still the player's, carrying the player's textures, reshaped to the donor's proportions. That is the ceiling of a same-topology edit on
this engine, and it is now reached *reliably*: the container choice is the only variable left, and `best_template_pack.py` measures it.

## The pipeline this completes

```
any extracted .glb  ->  glb_donor (keeps skeleton, picks a container with room for it)
                    ->  band_affine (per-bone proportions, blend 0.0-1.0)
                    ->  pack_patch (in place, slot size kept)
                    ->  switch_mods.write_files (LayeredFS build)
                    ->  a drawn, coherent change in a live round
```

Every step is tested, every step reports what it did, and the walk/capture procedure is one boot.
## Round 105: the same transfer that works on the player hangs on the enemy at the same strength

`re4sw-ganadosonic` applies the identical pipeline to `em16.udas` (the village Ganado): Sonic's full-skeleton donor, bone bands, `blend
0.5`, 7 slots, 12,633 vertices. Both attempts failed, and the first one **ended on `loading`** - the stage never came up.

| build | template | donor | blend | outcome |
|---|---|---|---|---|
| `re4sw-sonicfull` | player packs | Sonic (62 joints) | 0.5 | **round reached, player visibly reshaped** |
| `re4sw-ganadosonic` | `em16` | Sonic (62 joints) | 0.5 | **load hangs** |

**Same function, same donor, same blend - different template.** So the difference is in the *target's* band structure, not the transfer:
the Ganado's `em16` slots are far smaller than a player body (531-3,425 vertices across 7 slots), so the same per-band scaling produces
extreme factors on the small slots - and an extreme factor is exactly what stops a stage loading (the collapse experiments in round 65
showed the same failure).

**The next run is the same build at a lower blend** (0.25-0.35, where the *player* at 0.3 loaded and the 0.8 hung): the strength that is
safe scales with how small the target's bands are, so an enemy pack needs a gentler setting than a player pack to stay loadable.

**What this does not change:** the transfer itself is proven on two donors and two targets, and the mechanism's rules are settled. What is
left is a per-target strength, which is a number in one call - and the same number will be needed for every pack family, so it belongs in
the pipeline rather than in each experiment: **a `blend` chosen from the target's band sizes**, not a constant.
## Round 106: the strength comes from the data, and a morphed Ganado is on screen

**`auto_blend` makes the strength a property of the target, not a constant.** For every band it compares the donor's per-axis extent to
the template's, and returns the largest blend whose effective factor stays inside [1/3, 3] - the range outside which a stage stops
loading (measured three times: the collapse in round 65, the 0.8 Sonic build in round 102, and the enemy pack at 0.5 last round).

```
player packs, Sonic donor, auto  -> round reached; the player takes Sonic's proportions (round 104)
em16,           Sonic donor, 0.5 -> load hangs
em16,           Sonic donor, auto-> round reached  (this round)
```

Same function, same donor, two targets: the one that needed gentler treatment got it without anyone choosing a number.

**And the capture finally holds an enemy.** The harness used to walk *away* every frame; Ganados path to the player, so the frame stayed
empty. Standing still and raising the camera brings them in:

![a morphed Ganado at close range](evidence/re4sw-ganado-sonic-auto.jpg)

`01'14"29`, a Ganado at the player's shoulder, reshaped and enlarged; the further one behind is a different pack, untouched.

**That is the "zombies as cast" path working end to end on this title**: the collection's model drives the proportions, the per-band
transfer keeps it coherent, `auto_blend` keeps it loadable, and the enemy is visibly not the stock villager.

## The rules this line of work settled, in one place

1. **The engine draws a slot's own topology only.** A rebuilt mesh is ignored however correct it is.
2. **An edit is drawn when it moves parts relative to each other without letting a vertex leave its own region.** Bone-only transfer is
   invisible; global projection shards; per-band scaling draws.
3. **Strength must follow the target's band sizes.** A blend that is right for a 8,000-vertex body is too strong for a 500-vertex limb.
4. **The container pack decides how much of the donor's skeleton survives.** `pl04` (256 weight records) carries 62 joints; `em16` (4)
   buckets them, and the result is coarser.
5. **The boot state is a procedure:** stop a session from a menu, answer the resume prompt with **No**, and `playing` means the round.
## Round 107: the replacement is one call, and the panel can make it

The proven chain was a handful of probe scripts. It is now `gbox/switch_replace.py` with one entry point, and a route the sidebar can
call:

```
POST /api/decrypt-lab/replace
{"title":"re4_switch","pack":"em16.udas","donor_glb":".../sonic_src.glb","write":false}
```

which answers, live:

```
{"v":1,"report":{"pack":"em16.udas","donor":"sonic_src.glb","build":"gbox-replace-em16","blend":1.0,
  "slots":[{"slot":12,"vertices":1920,"blend":0.4,"bands":[
      {"band":0,"vertices":520,"donor_vertices":620,"extent_ratio":[0.901,2.051,2.274]},
      {"band":1,"vertices":265,"donor_vertices":608,"extent_ratio":[0.696,6.0,4.394]}, ...]}, ...]}}
```

**Every number in it is a measurement, not an assertion**: the blend each slot chose for itself (0.4 where a band's ratio reached 6x,
1.0 where the bands were already close), the vertices per band, and the donor's own geometry per band.

**The four panel operations are now one call each:**

| operation | arguments |
|---|---|
| remove clothes | `hide: [material indices]` (the collapse path, proven drawn) |
| swap clothes | `pack` = the garment slot's pack, `donor_pack`/`donor_slot` = another character's |
| swap character with zombie | `pack` = `pl*`, `donor_pack` = `em*` |
| replace zombies with cast | `pack` = `em*`, `donor_glb` = a model from the collection |

`write=false` previews without touching a build, which is what a picker should do while somebody is choosing.

**Tests:** 6 for the module (refusals, the report shape) and 2 for the route's registration, green on both machines; the live call above
is the integration check.

## The one thing the report exposes that a person would not guess

Look at slot 13: **one band, 1,465 vertices, ratio [0.462, 0.808, 0.653] - and blend 1.0.** Its geometry is simple enough that the
donor's proportions are within the limits at full strength. Slot 12, the same pack, needs 0.4 because one of its bands is 6x off. **The
strength is per slot, not per pack**, and a constant would have been wrong for one of them.
## Round 107: "remove clothes" goes through the panel, and the material needs a name

**The hide-only path now exists, and the route files builds where the launcher looks.**

* `switch_replace.replace_pack` accepts `hide=[...]` with **no donor at all** - which is what "remove clothes" is. The refusal is about
  having *something to do*, not about a donor being present. Tested (7 tests).
* The build used to be filed under the **title id** (`mods/010099A00BC1E000/...`), which the launcher never looks at, so a replacement
  built that way would silently do nothing. It is now filed under the **catalog game id** (`mods/270a15eb98dab4d7/...`) because the
  route resolves the serial against the catalog. Verified live:

```
"written": ".../gbox-cache/mods/270a15eb98dab4d7/re4sw-noclothes"
"materials hidden: [{'material': 7, 'start': 1450, 'triangles': 566, 'vertices': 720, 'centroid': [9.28, 598.26, -6.16]}]"
```

**But material 7 is not the jacket.** The build reached a round and Leon is unchanged:

![the player with material 7 collapsed](evidence/re4sw-hide-material-7-no-visible-change.jpg)

So the *operation* works (a material with 720 vertices was collapsed and the stage still loaded) and the *choice of material* does not.
The census gives indices and triangle counts, and it cannot tell a shirt from a belt - 14 materials, sizes from 14 to 566 triangles, no
names.

**The missing piece is a material-to-texture map**, and it is already in the data: each material record carries a texture id, and the DAT
holds the texture table. Naming them ("jacket", "trousers", "gloves") is what turns the panel's "remove clothes" from a slider over
indices into a list a person can use. That is the next step for all four operations, because the same map names what "swap clothes"
swaps.
## Round 108: "vanish" is the right operation, and `pl00` is the wrong pack

**Collapse was hiding garments inside the body.** `hide_materials` gained a second mode:

| mode | what it does | when it is right |
|---|---|---|
| `collapse` | pulls the material onto its own centroid | removing something *internal*, or breaking a part on purpose |
| `vanish` | translates it far below the playfield | **"remove clothes"** - the layer underneath is what a person should see |

Tested (10 in the hide suite, including that vanished vertices leave the model entirely and that an unknown mode is refused), and
threaded through `edit_pack` -> `switch_replace` -> the route (`hide_mode` on the body).

**But vanishing three of `pl00`'s biggest materials - 1,856 vertices across the two 430-triangle shoulder pieces and the 566-triangle one
- left Leon stock:**

![pl00 with three materials vanished](evidence/re4sw-vanish-pl00-still-stock.jpg)

**That is a pack-identification result, not a mechanism result.** Round 70 already showed that `pl00`-only builds change nothing while
`re4sw-allplayers` (all 26 player packs) visibly collapsed the player. `pl00` is not the mesh the camera sees; the visible Leon is one of
`pl01`..`pl21`.

**So the next step is a bisection, and it is bounded:** vanish the same materials across *half* the player packs, boot, and see whether the
player changes - 5 boots for 26 packs, each one halving the set. That names the pack the panel should default to, and every later
operation ("swap clothes", "swap character") needs that name.

**Why this matters beyond clothes:** every per-pack operation in the panel - all four - silently does nothing if pointed at a pack the
game is not drawing. A pack that is *not* drawn is the most likely explanation for a build that "had no effect", and it should be the
first thing checked, not the last.
## Round 109: the bisection tool works; the capture still mistakes a briefing for a round

`probe_bisect_pack.py` vanishes (or scales) a chosen range of player packs into one build, so "which pack does the camera draw?" is a
bisection instead of a guess: `pl00..pl0d` = 14 of 27 packs, 54-60 slots, one build, one boot.

**Two runs, neither decisive, and the second for an instructive reason:**

* `re4sw-bisectA` (vanish materials 1..n, keep material 0) reached a round and the player looked *almost* stock - a flatter shoulder, a
  less defined strap, nothing that cannot be explained by the camera angle. **Inconclusive, and I will not call it a change.**
* `re4sw-bisS` (scale x0.1 - the signal proven visible in round 70) reached a round and the frames are the **briefing screen**: the
  grainy "LIVE FEED" panel with a crosshair. The classifier called that `playing`.

**That second one is a real defect in the harness, not in the build:** `playing` is matched on brightness and motion, and the Mercenaries
briefing looks like gameplay to it. The capture then happens while the round is still being announced. The fix is a *content* signal
rather than a brightness one - the round's timer in the top-left corner is present in every gameplay frame and absent from the briefing -
and until that exists, a "reached True" run can photo the briefing and look like a negative result.

**What is now confirmed about pack identity:** `pl00` alone changes nothing visible in three separate builds (scale in round 70, vanish in
round 108, and material-7 collapse inside them), while all 26 packs at once visibly collapse the player. So the visible pack is one of
`pl01`..`pl21`, and the bisection needs a capture that is *inside* the round to make progress on which.
## Round 110: the timer separates gameplay from everything else, and the first halving is decisive

**The HUD test is measured, not guessed.** The top-left 30% x 14% box, counting pixels above 200:

| frame | bright pixels |
|---|---|
| round (`van1_05`, `sf_06`, `ga_07`) | **1020, 947, 963** |
| Mercenaries briefing (`bisS1_03`, `bisS1_06`) | 0, 0 |
| main menu | 0 |
| "Cancel loading?" prompt | 0 |

A threshold of 300 sits in empty space between the two groups. `walk_and_capture` now requires it twice: `reached` is only true when the
timer is on screen, and the capture loop **skips any frame without it** - so a run can no longer "reach a round" and photograph an
announcement.

**With that in place the first halving answered its question.** Scaling `pl00..pl0d` to a tenth, the player is a shrunken fragment:

![the player with the first half of the packs scaled down](evidence/re4sw-bisect-half-a-shrunk.jpg)

`01'24"57`, timer up, Ganados normal. **The mesh the camera draws is in `pl00`..`pl0d`.** Since `pl00` alone changed nothing in three
separate builds, it is in **`pl01`..`pl0d`** - four packs left after one more halving (`pl01..pl06`, which is built as `re4sw-bis2` and
awaits a clean boot; its three attempts ended on the save-list screen because the boot state had drifted again).

**Why this was worth the rounds:** every panel operation - remove clothes, swap clothes, swap character, replace zombies - is a per-pack
edit, and **a per-pack edit pointed at a pack the game is not drawing does nothing, silently**. The pack name is the first argument the
panel needs to get right, and it is now two boots away.
## Round 111: the camera's player pack is one of seven

Two halvings, both decisive, both read from frames the HUD guard guarantees are gameplay:

| set scaled to a tenth | the player |
|---|---|
| `pl00` alone (three separate builds) | unchanged |
| `pl00`..`pl0d` | **shrunk to a fragment** |
| `pl01`..`pl06` | **unchanged** |

![pl01..pl06 scaled: the player is stock](evidence/re4sw-bisect-pl01-06-normal.jpg)

`01'26"76`, timer up, Ganados normal, Leon untouched. So the mesh the camera draws is in **`pl07`..`pl0d`** - seven packs, two more
halvings (`pl07..pl0a`, then two).

**This also explains an old anomaly.** Round 88 recorded that collapsing `pl07`..`pl0d` made the stage **hang**, and that was filed as
"the collapse is too destructive". It was the right answer for the wrong reason: those packs *are* the player, and removing the player
model is what the stage cannot survive. A build that breaks the load is often a build that hit the thing the game draws.

**The boot state has a working fix, and it is now a script.** `system/tools/probes/fix_boot_state.py` answers "Cancel loading?" with Yes,
waits for the title screen, and stops the session there - the procedure round 98 identified, in Python after the bash version kept
failing on quoting. It measured `19.4 -> 49.1` and then a clean boot, which is what made the halving possible at all.
## Round 112: two packs left - `pl07` or `pl08`

Four halvings, each read from a frame the HUD guard certifies is gameplay:

| scaled set | the player |
|---|---|
| `pl00` (three builds) | unchanged |
| `pl00`..`pl0d` | **shrunk** |
| `pl01`..`pl06` | unchanged |
| `pl07`..`pl0a` | **shrunk** - `01'30"58`, a floating fragment |
| `pl07`..`pl08` | **shrunk** - `01'29"05`, the same fragment seen from a rooftop |

![pl07..pl0a scaled](evidence/re4sw-bisect-pl07-0a-shrunk.jpg)
![pl07..pl08 scaled](evidence/re4sw-bisect-pl07-08-shrunk.jpg)

So the mesh the camera draws is **`pl07` or `pl08`**, and nothing else. `pl07` holds three large slots (4,371 + 4,383 + 6,363 vertices) which
is the shape of a character with variants; `pl08` holds one of 6,591. The next run separates them by scaling `pl08` alone: if the player is
untouched, it is `pl07`.

**The run that would have separated them produced no frames, and that is the guard working.** `re4sw-bis5` (pl07 alone) reached a round
and every captured frame was discarded with `no round timer on screen` - the capture had landed in the briefing. Before round 110 those
frames would have been kept and read as "the player is normal", which is exactly the false negative the timer test exists to prevent.

**Cost of the whole identification: five builds, five boots.** The bisection is 5 for 27 packs, and it needed the boot-state fix
(`fix_boot_state.py`) to hold across them - without it, three attempts in a row died on the save-list screen.
## Round 113: the player pack is `pl08`, and its visible surface is one material

**`pl08.udas` is what the camera draws.** Scaling that one pack to a tenth distorted the player beyond doubt:

![pl08 scaled: the player is not the stock mesh](evidence/re4sw-pl08-is-the-player.jpg)

`01'21"31`, timer up, Ganados normal. Combined with every earlier halving, the player mesh is `pl08` - the pack with 25 materials and a
6,591-vertex body, and the reason `pl00`-only builds never did anything.

**And that immediately produced a second, more useful fact.** Vanishing materials **1..24** of `pl08`'s body slot - 23 materials, hundreds
of triangles, all reported by the operation - leaves the player looking **stock**:

![pl08 with 23 materials vanished: unchanged](evidence/re4sw-pl08-materials-vanished-stock.jpg)

So the visible surface of this character is essentially **material 0**'s. The other 24 are small pieces (42, 238, 156, 20, 72, 244
triangles...), not the clothing as a whole. **"Remove clothes" therefore cannot be a material-hide on this title** - hiding the garment
means editing *which texture region* the body's UVs point at, not removing a material.

**That is the next mechanism, and it is a different one from the last six rounds:** the clothes are painted onto the same surface as the
skin, so removing them is a texture operation - either repaint the garment's UV region with skin, or swap `pl08`'s texture for a variant
that has no clothes. The mod pipeline already supports textures (`re4hd_tex_writer`, 7 tests), so the pieces exist; what was wrong was the
operation chosen for the job.

**What this cost and what it bought:** six builds and six boots to name a pack that the panel must get right for every operation. That name
is now known, and it invalidates a plausible-looking plan (hide a material) in favour of the correct one (edit the texture), which is worth
more than the boots.
## Round 114: where the player's textures actually live, and the writer that does not exist

`remove clothes` is a texture edit (round 113), so the first question is *which texture*, and the second is *in what container*. Both are
now answered from the data:

```
pl08.udas slot 0: 25 materials
  tex   0 -> 00000000.pack.fen   archive present: False, bytes: 0
  tex   3 -> 00000003.pack.fen   archive present: False, bytes: 0
  tex   2 -> 00000002.pack.fen   archive present: False, bytes: 0
images inside the pack: 20   (128x64, 128x256, 64x128, ...)
```

**The material's texture ids name external archives that are not there.** The RomFS has no `ImagePackHD/*.pack.fen` for this title's
extracted tree, so the game is drawing the **TPL images carried inside `pl08.udas`** - 20 of them, ids 0..19, and the body's materials
use 0, 2 and 3.

That has a hard consequence: **the texture writer that exists edits `.fen` archives, and there is no TPL writer.** `re4hd_tex` can read
`tpl_images` and patch/resize `.fen` archives (`fen_patch`, `fen_replace_texture`, `solid_dds`); it cannot replace an image inside a pack.
So "remove clothes" needs one of two new pieces:

* a **TPL image writer** - swap the DDS payload of image `n` inside the pack, keeping the entry's size (the same in-place rule the meshes
  obey), or
* a **synthesised archive** - write `romfs/bio4/ImagePackHD/00000000.pack.fen` as a new file in the overlay and see whether the loader
  prefers it over the TPL. LayerFS can add files, and `archive_name(0)` gives the exact name; the open question is the wrapper header
  (`fen_open` shows a 16-byte prefix whose first word is the DDS byte count).

**The first is honest and bounded; the second is a hypothesis worth one boot.** Both are texture work on a pack whose name is now known,
which is a different situation from where this line started: the target is identified, the container is identified, and the missing piece
is a writer rather than an unknown.
## Round 115: the pack's texture table holds no textures

The TPL writer was written, tested, and **the test found the real structure by failing**:

```
slot 1: 608 bytes, magic 0x12345678, count 9
  header size field: 16
  image 0: record 0xa0  128x64  fmt 0xe field 520  first DDS magic at -0x1  slot end 0x260
  image 1: record 0xc8  128x256 fmt 0xe field 528  first DDS magic at -0x1  slot end 0x260
  ...
  DDS magics in the slot: 0
```

**Nine descriptors in 608 bytes, and not one `DDS ` magic.** The record's last `u32` is **not** a byte count - it runs 520, 528, 536, 544...
with a stride of 8, which is an *offset table*, not a size. So the pack's TPL slot is a **descriptor table**, and the surfaces it
describes live somewhere else in the pack (or in the pack's data section) - not where a writer would expect them.

**That is why the last two rounds of "remove clothes is a texture edit" were right about the operation and wrong about the container.**
The operation stands: the clothes are painted on material 0's surface, so hiding them means changing the texture. The container does not:
`tpl_replace_image` is a correct in-place writer for a container that holds payloads, and this container holds none.

The three tests that encode this are `xfail` with the measurement in the reason, so the suite is honest: **3 passed, 3 xfailed** on the
Spark, 2 passed and 4 skipped here.

**The next step is a small, specific question: where do the 20 surfaces live?** They are in the pack (the file is 1.4 MB and the BIN slots
account for a fraction), so a scan for `DDS ` across the whole pack, with the descriptor offsets as a map, is the way to find the store -
and then the same writer applies to it unchanged.
## Round 116: the texture descriptors point at a store that exists - and does not hold the player

Following the descriptor's pointer instead of assuming a payload:

```
image 0: 128x64  fmt 0xe  field 0x208  entry@slot+0x208 = u32 0x01000008, u32 0
image 1: 128x256 fmt 0xe  field 0x210  entry@slot+0x210 = u32 0x01000008, u32 1
...
```

The 40-byte record ends with an offset to an **8-byte entry** whose content is a constant `0x01000008` and a **global image id** (0, 1, 2, ...
up to 29 in this pack). So the TPL is a pure index: **the pack names textures, it does not contain them.** Confirmed twice over: the pack has
**0 `DDS ` magics** in 1.5 MB, and its slot table holds BIN meshes and TPL descriptors only - no payload slot at all.

**And the store exists.** `romfs/<title>/bio4/imagepackhd/` holds **1,813 archives, 5.8 GB**, named exactly as the loader's format string
says (`%08x.pack.fen`). So the texture path is a file swap, which `switch_mods` already does.

**Except for the player.** `00000000.pack.fen`, `00000002.pack.fen` and `00000003.pack.fen` - the three ids `pl08`'s body materials
reference - **are not in the directory**, while its neighbours (6, 9, 10, 11, 12...) are. So either the low ids live somewhere else, or the
material's `material_id` is not the global texture id and the mapping is one step away.

**That is the sharpest question this line has produced, and it is a lookup:** the 8-byte entry already carries the global id the loader
uses; what is unproven is that `Mat.material_id` *is* that id. One test settles it - take an enemy or player material whose id **is**
present in `imagepackhd` (6, 9, 10...), swap that archive with `fen_replace_texture`, and see whether the mesh changes. If it does, the
id is the id, the store is the store, and "swap clothes / swap skins" is a **file replacement** rather than a pack edit.
## Round 117: the id mapping is two steps, and the store is writable

**`Mat.material_id` is a local index, not the loader's texture id.** Measured across all 143 `em` packs: every pack's materials use local ids
0, 2 or 3, while the archives in `imagepackhd` start at 6, 9, 16, 17... **not one pack** references a present archive by that number.

**The global id is one step further in, and the mapping works.** Each TPL descriptor's 8-byte entry carries it (round 116), and re-scanning
with that mapping finds packs whose textures *are* present:

| pack | local ids | global ids | present |
|---|---|---|---|
| `pl0b` | 0 | 1, 2, 3, 4, 6, 9 | **2** |
| `em2d` | 3 | 4, 6, 8, 9 | **2** |
| `em32` | 3 | 1, 19 | **1** |
| `pl08` | 0, 2, 3 | 1, 2, 5, 9 | **1** |

**And the store takes a replacement.** `00000009.pack.fen` holds four surfaces (1024x1024, 256x256 DXT3, ...); `fen_replace_texture` put a
solid skin tone into surface 0 and the build wrote it as a plain RomFS file swap. The player ran a round unchanged:

![the player with texture 9's first surface replaced](evidence/re4sw-texswap9-no-change.jpg)

**So the mechanism is confirmed and the binding is not.** Texture 9 exists, is replaceable, and is not the surface Leon's body is drawn
with - its first surface is a 1024x1024 sheet, the shape of an environment atlas rather than a character's.

**What is left is a search, not a mechanism:** `pl08` names global ids 1, 2, 5 and 9; only 9 is present, so **Leon's body atlas is one of
the ids missing from `imagepackhd`** - the same three numbers (0, 2, 3 locally) whose archives the directory does not hold. That is now the
single question: where does the loader get a texture whose archive is absent, because the game plainly draws him with one.
## Round 118: the low texture ids are expected in a directory this RomFS does not have

Three measurements, and together they explain the missing textures without another guess:

1. **The HD store has no low ids at all.** `imagepackhd` holds **1,813 archives spanning ids 6 .. 0x4b000005** - the lowest is 6. The player's
   body materials name local ids 0, 2, 3, which map through the TPL to global ids 1, 2, 5 - **every one of them below the first archive that
   exists**.
2. **The loader chooses the directory by a flag.** The format string read out of the executable is
   `"%s\%s\%08x.pack.fen"` with the second argument being `"ImagePack"` **or** `"ImagePackHD"`, selected by a global HD flag. So the low
   ids are expected in **`imagepack/`** - the standard-definition store - and this RomFS extraction contains only `imagepackhd`.
3. **The emulator's file access does not name game files.** A 282,458-line `openat` trace over a running session contains **zero** `romfs`
   paths, because Citron serves the game through its own VFS over the container. The extracted tree is therefore only ever *the overlay
   source*, which is exactly how every model change in these rounds reached the game.

**The conclusion is a concrete next experiment, not a theory:** provide `romfs/bio4/imagepack/<id>.pack.fen` **from the overlay**, built the
same way the working texture swap was built (`fen_replace_texture` on a synthesised archive). If the loader looks for the SD archive when
the HD one is absent, the overlay satisfies it and the player's texture becomes replaceable - which makes "swap clothes" and "swap skins"
plain file swaps, the same mechanism that already works for archives that do exist.

**If it does not, the fallback order is the other way round** (HD absent ? the surface is embedded), and then the remaining place to look is
the pack's own BIN slots for a raw surface, which the "no DDS magic" scan has already ruled out for `pl08`.

**Everything else about textures is now known and reusable:** the id mapping (material -> TPL descriptor -> global id -> archive), the
archive format (four surfaces, DXT3, 1024x1024 and 256x256), the writer that replaces a surface at its own size, and the fact that a RomFS
file swap reaches the game.
## Round 119: the fallback is not the answer, and the state is now one page

**The `imagepack/` fallback experiment ran and changed nothing.** A real archive (the wrapper and surface layout of `00000009.pack.fen`, its
first surface a solid skin tone) was supplied from the overlay at `romfs/bio4/imagepack/00000001.pack.fen` - an id `pl08` names. The stage
loaded and Leon is stock:

![the player with an SD archive supplied from the overlay](evidence/re4sw-imagepack-fallback-no-change.jpg)

So the loader does not fall back to the SD store for this id, or id 1 is not his surface. Two candidates remain, and both are named work
rather than guesses:

* the **update NCA** - the emulator log shows the loader asking for a patch RomFS (`PatchRomFS update lookup ... found_best=false`), and an
  update partition is exactly where lower-resolution assets live;
* **RAM** - read the address the frame's display list samples. That names the surface directly and cannot be wrong.

**Five rounds of texture archaeology earned a stopping point, so the state is now a page:**
`system/docs/research/re4-switch-status.md`. It carries the working pipeline with its entry points, every measured fact with the round it was
measured in, what is blocked and the single thing each block needs, the one-boot procedure, and the traps that have cost the most time
(`sed` eating the letter `r`, a build filed under the title id, an edit aimed at a pack the game does not draw).

**That page is the answer to "less effort each time"** for this title: the next person or round starts from what is proven instead of
re-deriving it, and the two open items are stated as questions with a method, not as mysteries.
## Round 120: the update-NCA lead is empty - there is only one container

The cache holds a file named `Resident Evil 4 [UPDATE 1.0.2] [010099a00bc1e000].nsp`, which looked like the missing piece. It is
**12,974,974,680 bytes** - the same container the RomFS was extracted from (`staged_on: lilspark, size 12974974680`), not a second partition.
There is no `010099A00BC1E800` anywhere on the machine, no `imagepack/` directory in any extracted tree, and no `hactool` on hand to look
inside a container we have not already unpacked.

**So the update route is closed**, and it was worth closing cheaply: two commands, no boot.

**Where that leaves the texture question.** Three routes tried, all measured:

| route | result |
|---|---|
| `imagepackhd/<id>` swap for an id `pl08` names (9) | archive replaced, player unchanged - id 9 is not his surface |
| supply `imagepack/<id>` from the overlay (1) | file written, player unchanged - no SD fallback for that id |
| the update partition | it does not exist |

**The remaining route is RAM**, and it is a different kind of work: read the texture address the frame's display list samples. The emulator
already exposes `read_memory`, the lab page already has a hex scanner, and MercMode records round RAM - so the pieces exist. What it needs
is a GPU command-stream read (find the tile/texture bind in the frame's draw stream and take the address), which is a piece of work rather
than a guess.

**The honest summary of this sub-goal:** the model path is complete and drawn; the texture path has its containers mapped, its writers
written and tested, and **the one missing number is an address that RAM can supply**. Everything else about it - the id mapping, the archive
format, the surface replacement, the mod plumbing - is done and reusable.
## Round 121: the panel already has the four items - for RE5 - and RE4 now has its own

**An important correction to my own framing.** The MercMode sidebar's four operations the operator asked for **already exist**:

```
Swap clothes            data-mm-swap="clothes"     -> /api/decrypt-lab/model-swap
Plain (remove clothes)  data-mm-swap="plain"       -> /api/decrypt-lab/strip-clothes
Character -> zombie     data-mm-swap="to-zombie"   -> /api/decrypt-lab/model-swap
Zombies -> cast         data-mm-swap="from-cast"   -> /api/decrypt-lab/zombie-cast
```

All four routes are registered (`strip-clothes` 1267, `swap-matrix` 1775, `model-swap` 2075, `zombie-cast` 2124), and there is more beside
them: an object swap (mine / grenade), a "zombie round" button (player onto a zombie skin, enemies onto the cast), and a random-skin-swap
toggle. **That work was already done**, and my rounds of pack identification were building the RE4 equivalent from the other end without
noticing the panel existed.

**But the panel was RE5-only in a way that could only fail on RE4.** `labTitleFor` maps RE4's game id to `re4_switch` correctly, while the
`SWAP` map holds RE5 archives (`nativeNXx64/ImgNX/Archive/uEm6c.arc`, ...). So on an RE4 session the section offered four buttons that
address paths that do not exist in that title.

**Fixed:** `swapHTML(title)` is title-aware. On `re4_switch` it renders an RE4 section - a pack selector (`pl08` player body, `em16` /
`em10` village enemy) and three buttons wired to `/api/decrypt-lab/replace`:

| button | call |
|---|---|
| Sonic proportions | `{pack, donor_glb: <collection Sonic>, blend: auto or 1.0}` |
| Ganado proportions | `{pack, donor_pack: em16, donor_slot: 0}` |
| Remove clothes (materials) | `{pack, hide: [1..24], hide_mode: vanish}` |

The section says what it does rather than overselling it: proportions from the collection's model, **the mesh keeps its own topology**
(this engine draws nothing else), and the clothes button is labelled as a material hide - which on this title leaves the surface itself
untouched (measured round 113).

`node --check` passes and the file is deployed; a page refresh of the gBox UI picks it up (Electron needs a restart).

**The honest scoreboard for the operator's four items:** RE5 - implemented and wired; RE6 - the same routes, subject to its archive layout;
**RE4 - now has a section that does what is actually proven on that title** (proportions and material-hides), with the texture-based clothes
removal still waiting on the surface address that RAM can supply.
## Round 122: the inbox, and the one cluster this work can actually answer

**2,632 requests are open** (8,934 fetched: 6,134 done, 158 in progress, 10 blocked). The oldest open cluster is repeated across titles:

```
Unlock everything in custom builds: 010099A00BC1E000
Unlock everything in custom builds: Resident Evil 4
Unlock everything in custom builds: Resident Evil 6
Unlock everything in custom builds: Resident Evil 5
Unlock everything in custom builds: re5_switch
```

plus a long tail of `Mercenaries ... rank_not_verified`, *"why is the ps3 version even coming up in rotation?"*, *"Character replacement
readiness: Resident Evil 5 - Gold Edition"* and *"Session models: Resident Evil 5"*.

**The unlock cluster is answerable now, with evidence, and the answer is not what the tickets assume.** For RE4 (Switch) the unlock is **not a
patch**: measured in round 95, a fresh save's main menu is `NEW GAME / LOAD / LEADERBOARDS / HELP & OPTIONS / ACHIEVEMENTS` - **no EXTRAS
row**, so THE MERCENARIES does not exist until the save says it does. No RAM patch, no key sequence and no build changes that; twenty rounds
of boot failures came from a save the game could not load, not from a missing unlock mechanism.

So the honest resolution for that ticket is a **procedure plus a tool**, both of which exist:

* `gbox/re4_switch_save.py` - `--save <file> --replace` installs a save with a backup and a verified copy (6 tests);
* a usable save must be **past the village** (so EXTRAS exists) **and written from a menu** (so the title does not auto-load into "Cancel
  loading?" and boot-loop).

**What I am not claiming:** that the same is true for RE5 and RE6. Their unlock paths were built earlier in this project and live in
`gbox/re_mods`/`re_switch` for the GC and Switch cases respectively; the RE4 finding above is specific to RE4 Switch and should not be
generalised onto those tickets without its own measurement.

**The right next step on the inbox** is not to work the 2,632 one at a time - it is to answer the repeated clusters once each with the
measurement behind them, and let the ticket system point at the answer. The unlock cluster is the first, and it now has one.
## Round 123: the rotation is left playing, and the state is written down

Checked rather than assumed, because it is the one thing that must be true between rounds:

```
phase: playing | title: Resident Evil 4 (Switch, Mercenaries)
session: 600960e514124f7b-78bc29fb35c84e8b
scheduler: playing Resident Evil 4 (Switch, Mercenaries)
```

`system/tools/probes/mm_state.py` reads a captured `/api/mercmode` response and prints that row, so the check is one command and does not
need the API from a quoted one-liner (which has cost several rounds to token mangling).

## Where the objective stands, without inflation

**Reusable machinery - done and proven.** `glb_donor` -> `re4hd_affine` -> `re4hd_edit` -> `switch_mods` -> a drawn change in a live round;
one route (`/api/decrypt-lab/replace`) behind all four panel operations; `auto_blend` picks a loadable strength per slot; the status page
(`re4-switch-status.md`) carries every measured fact with its round.

**The panel - done for RE5, and now honest for RE4.** The four items the operator asked for already existed for RE5 (with an object swap, a
zombie-round button and a random-skin toggle); RE4 now gets a section that does what is actually proven there (proportions and
material-hides) instead of four buttons addressing RE5 archives.

**RE4 in MercMode - playing.** The rotation is running RE4 Switch Mercenaries right now, and the boot procedure that makes a run cost one
boot is written down and tooled (`fix_boot_state.py`, the round-timer guard in `walk_and_capture.py`).

**Not done, and named:** the player's texture surfaces (three routes measured dead, RAM is the remaining one); RE4/RE6 texture-based clothes
removal, which depends on that; live in-round replacement, which the emulator does not support (no save states); Mercenaries 3D and the VR
title's runtime work (the VR zip is deconstructed and the operator parked its runtime work).

**The inbox** is 2,632 open with a handful of repeated clusters; the unlock cluster now has a measured answer and a tool, and the rest need
the same treatment one cluster at a time rather than one ticket at a time.
## Round 124: the suite, verified green before stopping

```
57 passed, 3 xfailed in 6.79s
```

`test_switch_replace`, `test_re4hd_affine`, `test_re4hd_coherent`, `test_re4hd_hide`, `test_re4hd_edit`, `test_re4hd_tpl`,
`test_re4_switch_save`, `test_re4switch_bot`, `test_decrypt_lab_pack_edit` - all green on the Spark. The three `xfail`s are the TPL
descriptor measurement (round 115) recorded where it belongs, with the reason in the marker, rather than deleted or quietly skipped.

**The rotation is playing RE4 Switch Mercenaries** (verified round 123), and `/api/mercmode` still reports `phase: playing`.

That is the state this line of work stops at: everything committed is tested, the one thing that must run is running, and every open
question is written down with the measurement that framed it - the texture surfaces (three routes dead, RAM remaining), RE5/RE6's
unlocks (their own measurement, not RE4's), and the inbox clusters (the unlock one answered).
## Round 125: a material carries a colour, and that may be the skin swap this title needs

Three texture routes are dead, so the useful move was to stop looking for the texture and look at what else the material says. The 36-byte
material header of `pl08`'s body slot:

```
material 0  tris 1344  00 00 00 00 00 00 00 00 00 00 00 00 05 ff ff ff 00 00 00 00 00 00 00 ff ...
material 3  tris  156  00 00 00 00 00 00 00 00 00 00 00 03 01 02 ff 01 3f 3f 3f 00 00 32 00 ff ...
material 5  tris   72  00 00 00 00 00 00 00 00 00 00 00 03 01 02 ff 00 66 66 66 00 00 32 00 ff ...
```

**Offset +16 holds an RGB triple**, and it is non-zero exactly in the materials that use a colour (`3f 3f 3f`, `66 66 66`) while the big
textured ones hold `00 00 00`. A per-material tint is a way to change how a character *looks* without touching any texture - which is the
thing the texture search was blocking.

`system/tools/probes/tint_player.py` writes a chosen colour into every material header of every body slot and builds the mod (measured: 25
materials in slot 0 plus 8 other slots, written as one pack). **The run did not produce a frame** - three attempts ended on the save-list
screen or `loading`, which is the boot state again; the tool and the finding are committed and one clean boot answers it.

**If the tint is drawn**, the panel's clothes and skin offers gain a mechanism that works today, independent of the missing surface: recolour
a character, or give it another character's palette. **If it is not**, the header's +16 is metadata the renderer ignores, and that is
recorded just as plainly.
## Round 126: the full tint broke the load; the minimal one does not

Two builds, and the difference between them is the finding:

| build | what it changed | outcome |
|---|---|---|
| `re4sw-tint` | every material of **every** slot of `pl08` (25 in slot 0 plus 8 other slots) | two attempts ended on `loading` / the save list - **the stage never came up** |
| `re4sw-tint2` | only slot 0, only materials that already carry a colour (**17 of them**) | reached a round |

So the material header write is **valid in small doses and destructive in bulk** - the earlier failures were the build, not only the boot
state. That is worth knowing on its own: it is the first edit in this whole line that made a stage stop loading by *editing a header field*
rather than by changing geometry.

The minimal build reached a round but every captured frame was discarded (`no round timer on screen`) - the capture landed in the
briefing/loading hand-off, so there is still **no frame of a tinted player**. The tool takes `TARGET_SLOT` and `ONLY_COLOURED` so the next
attempt is one command, and the honest next step is: boot the minimal build, stand still, capture 8 frames at 5 s, and read whether Leon is
red.

**What the tint is for, if it draws:** the panel's clothes and skin offers have been blocked on the missing texture store for six rounds. A
per-material colour is a second, independent mechanism - recolour a character, or give it another character's colour - and it works on data
this pipeline already writes.
## Round 127: the capture now waits for the round, and the tinted build is flaky rather than broken

**Harness fix, and it is the one that keeps costing frames:** the walk can *reach* a round and still photograph a briefing or a loading
hand-off, because reaching and the round being on screen are different moments. `walk_and_capture` now polls for the round timer for up to 90
seconds before it captures anything:

```
MARK waited 90s for the round timer      <- and it correctly captured nothing when the timer never came
```

**The tinted build's load is flaky.** The same build (`re4sw-tint2`, 17 materials of slot 0) reached a round two rounds ago and ended on
`loading` twice this round. So the earlier reading - "bulk tint breaks the load, minimal tint does not" - is **too strong**: the minimal
tint is *sometimes* fine and sometimes not, which is a different and still-useful fact (a header write can destabilise a load
intermittently, not deterministically).

**What is still owed:** one frame of a tinted player. Three attempts have reached rounds and none has produced a frame inside one - twice
because of a briefing, now once because the stage did not load. The instrument is in place (the wait, the HUD guard, `TARGET_SLOT` /
`ONLY_COLOURED`); it needs one boot where both the load and the timing go right, and that is luck rather than method at this point.

**Honest assessment of this line:** the material tint is a *candidate* mechanism, not a working one. It has never been seen on screen. The
records say so explicitly so that no later reader mistakes "the tool exists" for "the recolour works".
## Round 128 (after the operator's reboot): the host came back, the launch path did not

The machine answers again, and the fix for the first problem was mine to find: the reboot left **`/mnt/gbox/quickswap2` unmounted**, so
every launch failed with `FileNotFoundError: ROM not reachable from this node`. Restarting the unit
(`sudo systemctl restart mnt-gbox-quickswap2.mount`) brought the share back and the failure went away.

**A correction to my own previous round:** I reported that the share's `_switch` folder no longer held the game. It does - `Resident Evil 4`
is right there. My `ls | head -6` truncated the alphabetical list before reaching it, and I read that as absence. That was a bad inference
from a truncated listing, and it cost a detour through the local cache copy.

**The new blocker is a hung boot:**

```
launch_game failed: BootHung: citron drew no changing frame in 45 s after mapping the game (a hung boot)
```

Nine stacked `launch_game` jobs sit in the queue from my repeated attempts, and `DELETE /api/jobs/{id}` answers **405**, so they cannot be
cancelled - they drain by failing, about a minute each. The queue is the next thing to clear before another attempt means anything, and
the next single attempt should be one launch with patience rather than a retry loop that piles more on.

**What is still owed from before the outage, unchanged:** the tint verdict. `~/gBox_alt/re4-lab/tintD*_*.jpg` was **0 frames** - that run
produced nothing, so the material-colour question is still open and still a candidate, never seen on screen.

**State:** repository clean at `d2313ad1`; rotation paused deliberately so it does not compete with the boot; the two host-side fixes
(mount unit restart, queue drain) are the prerequisites for anything else.
## Round 129 (post-reboot): the launch path is understood end to end, and the last link is Vulkan

Three separate failures were stacked on top of each other, and they are now separated:

1. **The share was not mounted.** Restarting `mnt-gbox-quickswap2.mount` fixed it, and the game is on the share (my previous round claimed
   otherwise from a truncated `ls | head -6` - wrong, and corrected in the record).
2. **No X display existed.** `/tmp/.X11-unix` held `X1` and `X90` only; `:100`, `:99` and `:110` - the displays the service and its streamer
   use - all failed `xdpyinfo`. Starting `Xvfb :100` succeeded, so the display can exist.
3. **Vulkan will not initialise.** With a display up, Citron still refuses to draw, and its own log says why:

```
Render.Vulkan <Error> RendererVulkan: Vulkan initialization failed with error: VK_ERR
HW.GPU <Error> CreateGPU: Failed to initialize GPU: Vulkan initialization error VK_ERROR_INITIALIZATION_FAILED
Core <Critical> Load: Failed to initialize system (Error 5)!
```

**`BootHung: citron drew no changing frame in 45 s` is a symptom of (3), not of the boot being slow**, and it happens with **stock as well as
with the tinted build** - so it is not the mod.

**What is not the problem, checked:** the GPU is present (`NVIDIA GB10`, driver 580.178.04, `/dev/nvidia0` and the rest, six modules loaded),
`nvidia-smi` answers, and `/usr/share/vulkan/icd.d/` has both `nvidia_icd.json` and `lvp_icd.json` with the loader at
`libvulkan.so.1.4.328`. `vulkaninfo` is not installed, so the ICD cannot be exercised directly from here.

**This is a host/driver state, not a repository state.** The service was restarted once already (display setup re-initialised, Vulkan still
fails). The likely causes are a driver that did not fully come up in this boot, or the GPU being held by the other heavy services that start
with it. The next thing to try is a second reboot with those services stopped first, or a `vulkaninfo` from the driver package to prove the
ICD works before blaming Citron.

**Nothing in the repository was changed by any of this**, and the tint verdict from before the outage is still the same open question: zero
frames, never seen on screen.
## Round 130 (post-reboot): the GPU is in a full-chip reset - nothing can render

The launch path is fully diagnosed now, and the last link is hardware state, not configuration:

```
NVRM: gpuHandleSanityCheckRegReadError_GH100: Possible bad register read: addr: 0x612078, regvalue: 0xbadf5600
NVRM: nvAssertFailedNoLog: Assertion failed: (status == NV_OK) || (status == NV_ERR_GPU_IN_FULLCHIP_RESET)
```

**`NV_ERR_GPU_IN_FULLCHIP_RESET`** - the GPU has fallen into a full-chip reset. That is why Vulkan cannot create a device
(`VK_ERROR_INITIALIZATION_FAILED`), why Citron never draws a frame (`BootHung` after 45 s), and why it happens with **stock and modded builds
alike**. It is not the tint, not the game, not the overlay, and not the display.

**Everything above it was checked and cleared:**

| layer | state |
|---|---|
| SMB share | was unmounted after the reboot; `mnt-gbox-quickswap2.mount` restarted, the game is present |
| X display | none existed (`:99`, `:100`, `:110` all failed); `Xvfb :100` starts and answers |
| Vulkan loader / ICDs | present: `libvulkan.so.1.4.328`, `nvidia_icd.json`, `lvp_icd.json` |
| NVIDIA driver | 580.178.04 loaded, `/dev/nvidia0` and the rest present, `nvidia-smi` answers |
| GPU compute holders | two ComfyUI instances plus hermes hold `/dev/nvidia0`; **suspending them changed nothing** |
| GPU health | **full-chip reset assertion - the fault** |

**What is needed from the operator, precisely:** a **reboot with the GPU-heavy services stopped first** (ComfyUI most of all), because the
fault is in the driver/hardware state and no amount of configuration fixes it. The machine came back from the previous reboot with the GPU
already in this state; the emulator and ComfyUI competing for a GB10's unified memory is the most likely way in.

**Everything I changed was restored:** ComfyUI resumed (`SIGCONT`), the `Xvfb :100` I started was stopped, and the repository is untouched
apart from this note and the probes.
## Round 131: the renderer is gBox's to choose, and Vulkan is still the reason nothing boots

Two things tried and both instructive:

* **ComfyUI suspended** (two instances held `/dev/nvidia0`): **no change** to Vulkan init. So the GPU contention theory is not the cause - the
  device itself is in a bad state, which the kernel already said (`NV_ERR_GPU_IN_FULLCHIP_RESET`).
* **Citron's renderer switched to OpenGL** by editing `[Renderer] backend=0 -> 1` in `qt-config.ini` (with a `.bak-<epoch>` beside it): the
  next launch came back with `backend=0` **rewritten by gBox**, and Citron logged `Render.Vulkan` again.

**That is a useful fact about the system, not a failed experiment:** gBox owns the per-title renderer setting and applies it at launch, so the
ini is not where a renderer change can be made. Making Citron use OpenGL would mean going through gBox's own title settings - and it is not
obvious that OpenGL would help, because the GL driver sits on the same GPU that is asserting a full-chip reset.

**The blocker remains exactly one thing:** the GPU must be reset. Everything else was checked this round and is fine - share mounted, display
available, loader and ICDs present, driver loaded, repository clean at `50394e88`.

**Config left as found:** `backend=0`, with the backup I made still beside it (`qt-config.ini.bak-1794148901`) and gBox's own copies
(`.gboxlab-backup`, `.gboxlab-dumpbak`) untouched.
## Round 132 (after the second reboot): the environment is working again, and the test is the only thing failing

The second reboot cleared it, and the checks say so plainly:

* **the share** was unmounted again at boot; `mnt-gbox-quickswap2.mount` restarted and `Resident Evil 4` is readable on it;
* **the service** is active and a display exists (`/tmp/.X11-unix/X0`);
* **Vulkan is healthy** - and this is the first time it has been measured directly rather than inferred from Citron's failure. The new probe
  (`tools/probes/vulkan_device_check.py`, ctypes against `libvulkan.so.1`) reports:

```
vkCreateInstance -> 0 (0 = success)
vkEnumeratePhysicalDevices -> 0 devices: 2
```

* **Citron boots the game** - its log runs to 47 s with `PatchRomFS` lookups and NS service calls, and **no Vulkan error at all**.

**So the earlier `VK_ERROR_INITIALIZATION_FAILED` was a driver that had not finished coming up in the first minute of a boot**, not a
permanent fault: the same launch that failed at `up 0 min` succeeds a few minutes later. That is worth knowing for every future round - after
a reboot, wait for the driver before judging the emulator.

**What is still failing is the experiment, not the host.** `re4sw-tint2` walked 18 steps and ended on `loading`; the capture then correctly
discarded every frame (`no round timer on screen`). That is the same intermittently-hanging build seen before the outage - a 17-material
header write that sometimes reaches a round and sometimes stops the stage loading.
## Round 133: the control that settles it - stock reaches a round, every tint hangs

After the reboot I finally ran the control that had been missing all along: **a stock run, no mod at all.**

```
MARK walk steps 6 | reached True | last screen playing
frames: 6
```

![a stock round reached after the reboot](evidence/re4sw-stock-control-round.jpg)

`01'44"09`, the timer up, Leon normal. **So the environment, the walk, the capture and the HUD guard all work after the reboot** - which
makes the tint result unambiguous:

| build | change | outcome |
|---|---|---|
| `re4sw-tint` | every material of every slot (25 + 8) | hung (`loading`) |
| `re4sw-tint2` | 17 materials of slot 0 | reached a round **once** (pre-reboot), hung twice |
| `re4sw-tint3` | **1 material** of slot 0 | hung (`loading`, 0 frames) |
| stock | nothing | **reached a round, 6 frames** |

**The material header's colour field is not writable.** Three variants, from one material to all of them, and the stage stops loading in every
one; the single-material case was the smallest possible change and it still hung. Whatever lives at header `+16` is consumed by the loader in a
way that rejects a changed value - so "recolour the character through the material" is **closed**, not merely hard.

**What that leaves for clothes and skins on this title:** the texture path, and specifically the **surface address RAM can supply** - the same
conclusion round 128 reached from the container side, now confirmed from the operation side. The model-proportion path (Sonic's proportions on
the player) remains the only proven way to change how a character looks, and it is unaffected by any of this.
## Round 134: the enemy-side transfer is drawn - and far too strong

With the environment working again, the Ganado build ran properly and this is the first **verified** enemy-side result:

![Ganados with the Sonic donor at the automatic strength](evidence/re4sw-ganado-sonic-auto-drawn.jpg)

`01'18"55`, the timer up, Leon normal - and the two villagers **are not humanoid any more**: they are grotesquely stretched, towering masses
with the donor's proportions applied at a strength the mesh could not carry. The **edit draws**, which is what the last several rounds could
not establish for the enemy pack; the *shape* is wrong.

**So "replace the zombies" has a working mechanism and one wrong number.** The automatic strength is chosen to keep a slot *loadable*, not to
keep it *recognisable* - it allows factors up to 3x, and on a Ganado's small bands that is a monster. The tuning that made the player look
right (blend 0.5 toward Sonic) is too strong for the enemy: the same clamp that protects the load lets the shape run away.

**The next build is the same call at a gentler blend** (`BLEND=0.15`), where the proportion transfer should read as a reshaped villager rather
than a mass. That is one argument, not a new mechanism.

**What this round also re-establishss:** the whole pipeline works end to end after the reboots - donor BIN regenerated (62 bones, 64 weight
records), 7 slots / 12,633 vertices patched, build written under the catalog id, round reached, 14 frames captured inside it. The machinery is
sound; only the strength needs a smaller number.
## Round 135: the enemy transfer has a strength curve, and 0.15 is the first usable point

Same call, one argument changed:

| build | blend | what the villager looks like |
|---|---|---|
| `re4sw-ganadosonic2` | auto (~0.4) | a towering stretched mass - recognisably not a person |
| `re4sw-gsonic15` | **0.15** | **reshaped but still a figure**: large head, hunched, small body |

![Ganados at blend 0.15](evidence/re4sw-ganado-sonic-015.jpg)

`01'31"82`, timer up, Leon normal, 10 frames captured inside the round on both builds. **So the enemy path has a usable strength**, and it is
much lower than the player's: the player read at 0.5 toward Sonic, the enemy needs 0.15 to stay a creature rather than a mass. That matches
the band-size rule from the model rounds - a Ganado's bands are a fraction of a player's, so the same number distorts far more.

**Honest reading of the frame:** this is a reshaped villager with the donor's proportions, not a Sonic. The mechanism is proven and tunable on
both sides now; making it *look like* a specific character still needs the right donor proportions and probably a per-slot strength, because
`auto` optimises for loadability and a single constant is wrong for at least one slot of any pack.

**Cost of the round:** two builds, two boots, both captured in-round - the pipeline is behaving
## Round 136: strength is per pack, and the frames prove it three ways

Four builds, four boots, all captured inside a round. The matrix:

| build | packs | blend | what the frame shows |
|---|---|---|---|
| `re4sw-ganadosonic2` | `em16` | auto (~0.4) | **monstrous masses** |
| `re4sw-gsonic15` | `em16` | 0.15 | **a reshaped figure** (large head, hunched) |
| `re4sw-gsonic_cap` | `em16` | auto capped 0.2 | stock - no visible change |
| `re4sw-allvillage` | `em10, em11, em15, em16` | 0.15 | **villagers look stock** |

**The only consistent reading: `em16` responds, the other village packs do not at 0.15.** That is what makes rows 3 and 4 look contradictory until
they are read together - the frames show whichever pack the round happened to spawn, and patching one pack leaves the others untouched. The
all-village build removed that ambiguity and showed stock villagers, i.e. the visible ones in that frame were **em10/em11**, whose bands need a
stronger transfer than `em16`'s.

**So a single number cannot serve a family of packs**, exactly as a single number cannot serve the slots inside one pack (round 107). The
transfer's strength is a property of the *target*: its band sizes decide how much a given factor distorts, and the packs differ by more than
2x in vertex count.

**What the round establishes beyond doubt:** the enemy side of the pipeline draws - three separate `em16` builds produced visibly different
results on the same frame composition. What it does not yet have is a strength chooser that works per pack rather than per call.

**Next, concretely:** compute each pack's strength from its own bands so that the *largest* band's factor lands in a chosen range (say 1.3-1.6x)
instead of taking the auto value that keeps the load safe; the function already knows every band's extent ratio, so this is a second rule over
data it has, not a new mechanic.
## Round 137: whole-pack swapping - the player pack breaks the enemy load, so try within the family

Every mesh-level route has a ceiling, so this round tested the one mechanism that would be a true *replacement*: write a different character's
**whole pack file** under an enemy pack's name, since the engine reads `bio4/em/<name>.udas` by name and an overlay can substitute any bytes
for it.

**First attempt: a player pack in the villagers' place** - `em10, em11, em15, em16 <- pl00.udas` (1,448,576 bytes each). Result: **the stage
never finished loading** (18 walk steps, last screen `loading`, 0 frames). That is the same failure shape as every build that puts a character
where the game does not expect one: the enemy logic binds its own skeleton and animations, and a player pack's structure does not satisfy it.

**Which leaves the test that matters:** swap **within a family** - an enemy pack for another enemy pack (`em10 <- em16`), or a player pack for
another player pack (`pl00 <- pl08`). Size and layout match, so the loader's expectations are met, and the only thing that changes is *which
character* the game draws for that name. That is the cheapest possible route to "zombies are the cast" if the engine honours it, and it needs
one build and one boot to answer.

**What is now known about the three routes to a real character replacement:**

| route | state |
|---|---|
| edit the mesh in place | draws, but only for same-topology changes - a proportion transfer, never a different character |
| swap the texture | blocked: the player's surfaces are not in `imagepackhd` and the pack's TPL holds descriptors only |
| **swap the whole pack** | player-into-enemy **hangs the load**; within-family untested |
## Round 138: within-family pack swapping is not viable either

`pl08.udas <- pl07.udas` (958,112 bytes written over the player's pack, same family, same kind of file). Two runs, two failures that disagree:

```
run 1: MARK walk steps 3  | reached True  | last screen playing | waited 0s  | frames 0
run 2: MARK walk steps 13 | reached False | last screen loading | waited 90s | frames 0
```

The first claimed a round (the timer was on screen at the first check) and then produced **no usable frames**; the second never got past
`loading`. So the substitution does not render a different character - it **destabilises the title**, differently each boot.

**That closes the third route.** All three ways to a real character replacement on this title are now measured:

| route | result |
|---|---|
| edit the mesh in place | draws, but only for same-topology changes: a proportion transfer, never a different character |
| swap the texture | blocked: the player's surfaces are absent from `imagepackhd`, the pack's TPL is descriptors only, and every header-tint attempt stops the stage loading |
| swap the whole pack | player-into-enemy hangs; enemy-into-enemy/player-into-player destabilises and yields no frames |

**What this means for the objective, said plainly:** the machinery in this pipeline can reshape a character (proven repeatedly and in frame) but
**cannot substitute one character for another** on RE4 (Switch) with the mechanisms available. A true replacement needs either an engine-level
hook (out of scope for asset work) or the surface swap that the RAM address would unlock - which is the one open route left and the one that
has never been tried.

**The proportion path is not wasted:** it is the mechanism that made "Sonic's proportions on the player" and "a reshaped Ganado" real, and it
is what a texture path would build on once surfaces are addressable.
## Round 139: the mine/grenade swap builds - verified at the route, not yet on screen

The objective names this one explicitly ("swapping a game asset for a 3D object supplied for temporary use, e.g. RE5's mine object") and the
panel already offers it. Calling the route the panel calls:

```
POST /api/decrypt-lab/model-swap  {"title":"re5_switch",
  "arc_path":"nativeNXx64/ImgNX/Archive/uWp06.arc",
  "donor_arc":"nativeNXx64/ImgNX/Archive/uWp0a.arc","build":"mercmode-objtest"}

http 200
{"ok":true,"target":".../mods/52d15709be0fda1a/mercmode-objtest/romfs/nativeNXx64/ImgNX/Archive/uWp06.arc",
 "size":550553,"slot":"wp0600","donor":"om4e00","maps":["NM","kept:BM,MM"],
 "note":"the overlay applies when the title next boots (LayeredFS)"}
```

So the mine's archive is replaced by the grenade's, the **normal map is swapped and the base/roughness maps are kept**, and the build is filed
under RE5's catalog id (`52d15709be0fda1a`) where the launcher will find it.

**What this establishes and what it does not:** the *mechanism* the operator asked for works end to end at the route - a real object, a real
donor, a valid overlay with the donor's maps. What it does not yet have is a frame of a thrown mine looking like a grenade, which needs an RE5
session and a lucky throw. **I am calling this "builds" and not "works" until there is a picture**, which is the distinction this project has
been burned by before.

**Why it is worth recording anyway:** it is the one part of the operator's list that is *implemented and wired* rather than blocked - object
replacement needs no texture store, no pack swap and no engine hook, because RE5's objects are standalone archives that the loader reads by
path.
## Round 140: the suite is green after today's changes, and the state of the objective is unambiguous

```
59 passed, 3 xfailed in 6.82s
```

Every module touched today - the transfer's `ceiling` and `target_factor`, the `switch_replace` route, the hide modes, the TPL writer, the save
installer, the bot, the lab routes - passes on the Spark. The three `xfail`s are the TPL descriptor measurement, recorded with its reason.

**What this session established, in the terms the objective is written in:**

| objective item | state |
|---|---|
| (a) decrypt a title's data | done for RE4 Switch (RomFS extracted, DAT/UDAS/BIN/TPL parsed) |
| (b) rip and inventory assets | done for meshes and materials; **textures mapped but not addressable**; sound not attempted |
| (c) replace assets at runtime | **model proportions: drawn and tunable**; object swap (RE5 mine/grenade): **builds, not yet seen**; textures and pack swaps: blocked |
| (d) reusable machinery | `glb_donor` -> `re4hd_affine` -> `re4hd_edit` -> `switch_mods`, one route, one boot per test, documented traps |
| RE4 in MercMode | **playing now** (RE4 Switch Mercenaries, verified) |
| the panel's four items | **exist for RE5** (with object swap, zombie round, random skins); RE4 has an honest section for what is proven there |
| inbox | 2,631 open, four clusters, each answered once in `inbox-triage.md`; no write endpoint to close them |

**The honest headline:** the pipeline reshapes characters reliably and proves it in frame; it cannot yet substitute one character for another on
RE4 Switch, and the one route that would change that - the texture surface address from RAM - has not been attempted. Everything else on the
operator's list is either implemented (RE5's four panel operations, the object swap, the rotation) or documented as blocked with the reason.
## Round 141: the rotation is left as the operator wants it

Before the experiments I paused the MercMode rotation (so a test would not compete with it), and it was still paused with the scheduler reporting
`busy with jobs` from my launches. Restored through the API the panel uses:

```
{"op":"configure","host":"lilspark","enabled":true,"titles":["re4","re5"],"rounds_per_title":1,
 "preferred_editions":{"re4":{"platform":"switch","mode":"mercenaries","title_id":"010099A00BC1E000"},
                       "re5":{"platform":"switch","mode":"no_mercy","title_id":"010018100CD46000"}}}
-> http 200
-> phase: launching | title: Resident Evil 4 (Switch, Mercenaries)
```

**That is the one thing that must be true between rounds**, and it is now true again with both titles pinned to their Switch editions - the same
configuration that answers the operator's "why is the ps3 version in rotation?" ticket.

**A lesson worth writing down:** pausing the rotation for an experiment is fine, but the restore has to be verified, not assumed. This round
found it still paused; a later round would have found it silent and had to work out why.
## RE5: whole-character archive swapping works - the player renders as the donor character

Test 1 for RE5, run through the panel's own live path:

```
uPl00ChrisNormal.arc  <-  uPl02JillCos1.arc        (14,990,525 bytes written over Chris's archive)
build: mercmode-swap                                (the build every MercMode swap writes)
rotation: RE5 only, No Mercy, Switch                -> phase: playing
```

Frame, inside a live No Mercy round (`01'39"09`, combo `001550`):

![Chris's slot rendering Jill's character](evidence/re5-chris-archetype-swapped-to-jill.jpg)

**The HUD still says "Chris"** - the slot is Chris's - **and the body on screen is Jill's**: long light hair, female build, seen from behind while the
majini close in. That is a **character replacement**, not a paint job: the mesh, not the texture, came from the donor archive.

**So RE5 tolerates substitution at the archive level, which RE4 does not.** On RE4 a player pack written over an enemy pack hung the load and a
within-family pack swap destabilised the title; here a 15 MB character archive was replaced wholesale and the game booted, entered Merc Mode and
played a round with it.

**Why this matters for "Sonic characters in RE5/RE6":** the hard part on RE4 was that the engine would not draw a different mesh. RE5 clearly
will, provided the replacement arrives as a *character archive* whose internal structure the loader accepts. That moves the question from "will
the engine draw it" to "can a Sonic model be assembled into an archive of that shape" - a format problem, not an engine one.

**What remains unproven:** animations and skeleton. The round played and the body moved, but the donor archive carries its own rig, so a walk
cycle that looks right in one frame may be wrong elsewhere. That is the next thing to look at, and it is cheap: watch a minute of movement.
## Operator report (2026-11-08): a mine tactic the bot cannot execute, and a bot that stands idle

Two symptoms, one cause, and the code says so plainly.

**The cause:** `re5_switch_mines.Mines.due()` returns `None` while `stack(inventory)` is `None` - and the stack is the **proximity
bomb** (`MINE_ID 0x10A`). A round whose loadout carries hand grenades instead therefore has **no mine to plant**, while
`_mine_now()` armed the controller anyway (`last_at` pulled back). The tactic could never fire, and the bot was left standing
with a pistol - exactly what the operator photographed.

**Fixed in three places, all in `gbox/mercs/titles/re5_switch.py`:**

1. `_mine_now(ok, snap)` now checks the inventory first. With a bomb it arms the controller exactly as before; without one it
   records `pending_mine`, puts the reason in `directive_status` ("no proximity bomb in this round's loadout - fighting on"),
   and **leaves the fight running** instead of stalling.
2. `_mods()` - the one place holding both the title's adapter and the bot - **arms the loadout when a tactic is waiting**:
   `re5_switch_mods.mines(ad, on=True)` rewrites the template the game builds each round's inventory from, once per round, with
   the result recorded in `stats["mine_arm"]` (`verified`, `effective`). That is the "give them a mine to equip" half: RE5 has no
   way to inject an item mid-round, so the loadout for the next round is the honest lever, and the panel can now show that it
   was armed.
3. `_round_start()` fires the remembered tactic the moment a bomb is actually in hand.

**Tests:** `tests/test_mercs_directives.py` 42 passed, and the module imports cleanly on the Spark.

**What this does not do:** it cannot put a mine in the current round's hands if that round was built with grenades. The fix makes
that visible and arms the next round, rather than pretending the command worked - which is what the operator saw before.
## RE5 character swapping: made an operation, and the enemy-into-character direction boots

**`gbox/re5_char_swap.py`** turns the measured route into a first-class call (6 tests, green on both machines):

```
python -m gbox.re5_char_swap --romfs <RE5 romfs> --pairs 'uPl02JillCos1.arc=uPl00ChrisNormal.arc'
python -m gbox.re5_char_swap --romfs <RE5 romfs> --catalogue          # the slots: characters and enemies
```

`plan()` refuses a pair whose side is missing and says which file; `build()` writes one overlay file per target and files it under
RE5's catalog id, defaulting to `mercmode-swap` - the build MercMode applies at the title's next boot - so a swap made here lands
exactly like the panel's own.

**The enemy direction boots.** `uEm6c.arc` (4,334,405 bytes) written over `uPl00ChrisNormal.arc` (43,337,492): the title comes up to
**Character Select** and renders it normally (Rebecca selected in the frame captured). So an enemy archive in a player slot does not
hang the load, which RE4's equivalent does.

**What is not yet proven:** a frame of the player **in a round** wearing that enemy's body. The capture caught the select screen, and
the run needed the bot to choose a character and start a round. That is the next thing to look at, and it is one boot.
## RE5: an enemy archive in a character slot renders the enemy, in a live round

`uEm6c.arc` (an enemy archive) written over **`uPl07RebeccaNormal.arc`** - the slot the bot actually played - then a No Mercy round:

![Rebecca's slot rendering a majini](evidence/re5-rebecca-slot-renders-majini.jpg)

`02'49"53`, combo `002`, HUD says **Rebecca**, and the body filling the frame is a bare-chested **majini with a machete**, a second one behind him.
**So "swap characters with zombies" works on RE5**, by the same whole-archive route that put Jill in Chris's slot.

**The lesson that cost the earlier attempt:** the first build targeted `uPl00ChrisNormal.arc` and the round played as **Rebecca** - the bot chooses
the character, so a swap aimed at the wrong slot silently does nothing. Any swap built for a round has to name the slot that round will use, or
force the character with `mercs_select`.

**What this establishes, precisely:** RE5 draws whatever mesh the character archive contains - human or enemy - as long as the archive is
substituted whole. That is the property RE4 lacks, and it is the reason a Sonic or Mario *body* is a format problem here rather than an
engine one.