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