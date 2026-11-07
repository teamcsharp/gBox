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