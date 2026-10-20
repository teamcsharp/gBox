# Sonic 2D sprite animations (Mega Drive, from the ROM)

`gbox/sonic2d_sprites.py` decodes the player characters of the Mega Drive Sonic games straight from the cartridge
image and writes every animation as a frame-exact 2D clip in the character collection: the spin dash (charge and
release), jump / roll ball, the level-complete moment (S3K victory pose; the signpost spin in Sonic 1 / 2) and every
other named animation (walk, run, push, wait, skid, balance, hurt, death, glide, ...). The clips feed the animation
collage helper (`gbox/sprite_collage.py`, below).

Nothing is captured from a running game and nothing is launched: the extractor reads the ROM the catalog points at.

## Games

| catalog game | game_id (owned dump) | reader | entries | requested clips |
|---|---|---|---|---|
| Sonic The Hedgehog (Japan, Korea) REV01 | f82de5b1456da0ce | `sonic2d_sonic1` | `sonic1_sonic` | jump, roll, level_complete (signpost) |
| Sonic the Hedgehog 2 (World) (also Rev A, the .7z) | 938e4ca5b120e344, 764582c25053f662 | `sonic2d_sonic2` | `sonic2_sonic`, `sonic2_tails` | spindash_charge, spindash_release, jump, roll, level_complete (signpost) |
| Sonic the Hedgehog 3 (USA) | 1936eeee6b541ca3 | `sonic2d_sonic3` | `sonic3_sonic`, `sonic3_tails` | spindash_charge, spindash_release, jump, roll, level_complete (victory pose) |
| Sonic & Knuckles + Sonic the Hedgehog 3 (World) (= S3K) | ed2bef5be2826deb | `sonic2d_s3k` | `s3k_sonic`, `s3k_tails`, `s3k_knuckles` | spindash_charge, spindash_release, jump, roll, level_complete (victory pose), signpost |
| Sonic & Knuckles (World) | 668e74c15d61a9a7, 9de16e5935b91323 | `sonic2d_sk` | `sk_sonic`, `sk_knuckles` | as S3K (Tails' art is on the Sonic 3 cart: lock-on only) |

The readers are registered in `gbox.characters.DEDICATED`, so `characters op=collect game_id=<id>` (and a favorite /
launch of these games) fills the entries. The catalog row `117cd862c2e9dbaf` "Sonic the Hedgehog" points at a zip that
holds **Sonic Spinball** (serial GM MK-1537); its collection fails with that message instead of guessing. Hacks with
their own titles (Sonic 2 Delta, ...) are not matched; zips under the official titles are read by code shape, so
close hacks usually work. Sonic CD (Sega CD), the Game Gear / Master System games and the Advance titles are other
engines and are not read.

## Formats (what is decoded)

All three engines share the scheme; sources are the sonicretro disassemblies (s1disasm, s2disasm, skdisasm) and the
Sonic Retro SCHG pages.

| piece | Sonic 1 | Sonic 2 | Sonic 3 / S&K / S3K |
|---|---|---|---|
| player art | uncompressed 4bpp tiles (`Art_Sonic`) | uncompressed (`ArtUnc_Sonic`, `ArtUnc_Tails`) | uncompressed; Sonic and Tails switch to a second bank (`..._Extra`) from frame $DA / $D1 |
| DPLC (per frame, tiles to stream into the player's VRAM slot) | byte count, words `(n-1)<<12 \| tile` | word count, same words | word count, same words (objects' `Perform_DPLC`: count-1, `tile<<4 \| n-1`) |
| mappings (per frame, sprite pieces) | byte count, 5-byte pieces `y, size, tile, x` | word count, 8-byte pieces (+ 2P tile word) | word count, 6-byte pieces |
| animation scripts | `Ani_Sonic` | `SonicAniData`, `TailsAniData` | `AniSonic`, `AniTails`, `AniKnuckles` |
| palette | `Pal_Index` entry 3 | `PalPointers` entry 3 | `PalPoint` entry 3 (Sonic/Tails), 5 (Knuckles) |
| signpost | object 0D, Nemesis art (PLC entry), `Ani_Sign` | object 0D, Nemesis art, `Ani_obj0D` | `Obj_EndSign`: uncompressed art + object DPLC, `AniRaw_EndSigns` |

Mapping tile words carry the palette line (bits 13-14), x/y flip (11/12) and priority (15); a piece's tiles run
column-major; the first piece is drawn on top (lower sprite index wins). Colours are VDP words `0000BBB0GGG0RRR0`,
each 3-bit level scaled linearly to 0..255; index 0 of a line is transparent. Codecs live in
`gbox/formats/sega_md.py` (Nemesis + Kosinski decode, encoders for tests, 4bpp tiles, palettes).

### Discovery (no offset tables)

* **DPLC loaders**: the table walk `add.w d0,d0; adda.w (a2,d0.w),a2; move.w (a2)+,d5; subq.w #1,d5; bmi.s` (S1: the
  byte-count variant) with the `lea (PLC).l,a2` before it (the first lea; a later one is the Super table, whose
  start bounds the frame count) and the art base next to it (`lea (Art).l,a1` S1, `addi.l #Art,d1` S2,
  `move.l #Art,d6` S3K, plus the `cmpi.w #2*N,d0; blo; move.l #Extra,d6` bank switch).
* **Characters**: S1/S2/S3 by the `Animate` routine (`lea (Ani).l,a1; moveq #0,d0; move.b anim(a0),d0; cmp.b
  prev_anim(a0),d0`) each loader follows, in code order (Sonic, then Tails); S&K/S3K by the `Perform_Player_DPLC`
  dispatch on `character_id` (gbox.sk_sprites), the closest preceding `Animate` routine giving the script table.
* **Mappings**: the `move.l #Map,mappings(a0)` immediate whose frames fit the character's DPLC frame for frame.
* **Palette table**: `lea (PalPointers).l,a1; lsl.w #3,d0; adda.w d0,a1; movea.l (a1)+,a2; movea.w (a1)+,a3`.
* **Tails' tails** (a separate object): `move.b Sel(pc,d0.w),anim(a0); lea (TailAni).l,a1`; S2 draws them from
  Tails' own art, S3K from `Map_Tails_Tail` / its DPLC / `ArtUnc_Tails_Tail`. They are composited behind Tails.
* **Signposts**: by the bytes of their spin scripts; S1/S2 then the object's `move.l #Map,mappings(a0); move.w
  #tile,art_tile(a0)` and the PLC entry that loads Nemesis art at that tile (the tightest art covering the mappings);
  S3K the `PLCPtr_EndSigns` pointers just before `AniRaw_EndSigns` and the `ObjSlot_EndSigns` mappings.

What discovery finds in the owned dumps is pinned in `tests/test_sonic2d_sprites.py` (e.g. Sonic 2: art $50000,
DPLC $714E0, mappings $6FBE0, scripts $1B624; S3K matches `gbox.sk_sprites.AUX`).

## Frame-exact timing

The clips are produced by running the games' animate routines one vertical blank at a time:

* a normal script is `delay, frames..., command`; each frame shows `delay + 1` game frames; `$FF` restarts, `$FE n`
  goes back n bytes, `$FD a` switches to animation a (the clip ends there), other commands stop. Sonic 1's Sonic
  treats every byte >= $80 as a command, Sonic 2 >= $F0, S3K >= $FC; objects (AnimateSprite) >= $80, Sonic 1 objects
  keep x/y flip in bits 5/6.
* speed-driven scripts (first byte $FF walk/run, $FE roll, $FD push) take their delay from the ground speed:
  walk/run `(0x800 - |v|) >> 8`, roll `(0x400 - |v|) >> 8`, push `(0x800 - |v|) >> 6`. Clips use: walk $400, run
  $600, fast run $700, roll at running speed $600, push $80; `jump` is the roll script at speed 0 (a standing jump:
  5 game frames per frame); `spindash_release` is 12 frames of revving then the roll at the minimum release speed $800.
* the loop point is where the engine state repeats; it is moved back to the earliest frame boundary the picture
  allows, and a whole-clip loop is rotated so no frame is split across the wrap.
* walk/run use flat ground (angle 0) facing right, so no slope rotation; Tails' tails "directional" script uses the
  moving-right set.

| clip | Sonic 1 | Sonic 2 | Sonic 3 / S3K |
|---|---|---|---|
| `spindash_charge` | (no spin dash) | anim 9, 10 frames x 1 game frame, loops | anim 9 |
| `spindash_release` | | 12 revving frames, then roll at $800 (loops on the roll) | same |
| `jump` | `Roll` at speed 0 | `Roll` at speed 0 | anim 2 at speed 0 |
| `roll` | `Roll2` at $600 | `Roll2` at $600 | anim 3 at $600 |
| `level_complete` | signpost: Eggman, 2 spin cycles of 61 frames, Sonic face (Sonic is forced right; S1 has no pose) | signpost: 1 + 61 spin frames then the player's face (Sonic / Tails) | victory pose, anim $13 (`Set_PlayerEndingPose`) |
| `signpost` | | | `Obj_EndSign` spin (96 frames) then the player's face (Sonic / Tails / Knuckles) |

Plus every other named animation of the character's script table as its own clip (names from the disassembly
labels; S3K ids named by their use in skdisasm, unknown ones `anim_NN`):

* Sonic 1 Sonic: walk, run, roll_fast, push, wait, balance, look_up, duck, warp1-4, skid, float1-4, spring, hang,
  leap1/2, surf, get_air, burnt, drown, death, shrink, hurt, slide.
* Sonic 2 Sonic: walk, run, roll_fast, push, wait, balance(2-4), look_up, duck, spindash, blink, get_up, skid,
  float(2), spring, hang(2), dash2/3, bubble, death_bw, drown, death, hurt(2), slide, super_transform, lying,
  lie_down. Tails: the same family plus run_fast (HaulAss) and fly.
* Sonic 3 / S3K Sonic: walk, run, roll_fast, push, wait, wait_end, balance(2-4), look_up, duck, spindash, get_up,
  skid, float(2), spring, hang(2), dash2, victory, bubble, burnt, drown, death, hurt(2), slide, super_transform,
  lying, lie_down, anim_22/23. Tails adds run_fast, fly(2), carry, ascend, tired(2/3), swim(2); Knuckles adds glide,
  glide_fall, glide_slide, glide_get_up, sphere_victory.

## Output (collection entries)

Each character is a `sprites` entry (`<game>_<char>`, e.g. `sonic2_sonic`): `overview.png` (the first frame of each
requested clip; the entry's model / preview) and `meta.animations[]`, one row per clip, the same shape
`sprite_capture` writes (`clip, name, dir, sheet, index, preview, webp, mp4, frames, fps, loop, canvas`) plus
`game_frames`, `duration_s`, `origin`, `kind` (`requested` / `animation`). A clip folder `clips/<clip>/` holds:

| file | what |
|---|---|
| `frames/frame_NNNN.png` | the frames in play order, RGBA, one canvas per clip |
| `sheet.png` | each distinct picture once |
| `sheet.json` | per frame: `duration_frames` (game frames) and `duration_ms`, `start_frame`, `mapping_frame`, flips, `anim`, `overlay_frame` (Tails' tails), `origin`/`hotspot` (same pixel in every frame), `bbox` (relative to the origin), `sheet` cell, `file`; clip: `fps` 60, `canvas`, `origin`, `loop` (`start`, `length` in frames, `start_game_frame`, `length_game_frames`) or null, `end` (`loop` / `goto` / `stop`), `total_game_frames`, the scripts used (`animations[]`: id, name, offset, bytes, speed) and the ROM offsets (`source`) |
| `preview.apng` (+ `preview.webp`) | looping preview |
| `clip.mp4` | 4x nearest neighbour over the collection grey, the loop played 3 times (ffmpeg; `mp4_unavailable` says why when missing) |

The **origin** is the object's `x_pos`/`y_pos` (the sprite's hotspot, between the feet / ball centre): put that
pixel where the character should be and every frame lines up, in every clip of the character.

CLI (no collection needed):

```
python -m gbox.sonic2d_sprites inventory "Sonic the Hedgehog 2 (World).zip"
python -m gbox.sonic2d_sprites extract "Sonic & Knuckles + Sonic the Hedgehog 3 (World).zip" --out out/ \
    --char knuckles --clips spindash_charge,level_complete [--no-mp4]
```

## Collage

`gbox/sprite_collage.py` tiles chosen clips onto one canvas along a timeline. It reads any collection sprites clip
(`sheet.json` + `sheet.png`; also `sprite_capture` clips, which time in ms and anchor on the centroid).

```json
{"canvas": [320, 120], "fps": 60, "frames": 180, "background": "#262830", "scale": 2,
 "items": [
  {"clip": "sonic2_sonic/spindash_charge", "x": 40, "y": 80},
  {"clip": "sonic2_sonic/spindash_release", "x": 100, "y": 80, "loops": 4, "hold": "hide"},
  {"clip": "sonic2_tails/jump", "x": 160, "y": 80, "start": 30},
  {"clip": "s3k_knuckles/level_complete", "x": 220, "y": 80},
  {"clip": "s3k_sonic/signpost", "x": 280, "y": 60, "flip": true},
  {"clip": "sonic1_sonic/walk", "x": 40, "y": 115, "z": 5}
 ]}
```

* `clip`: `<entry>/<clip>` under the collection root (or a clip folder / sheet.json path).
* `x`, `y`: where the clip's origin lands (canvas pixels); `flip` mirrors around it; `scale` per item.
* `start`, `end`: output frames the item is shown; `loops`: plays of the loop section (0 = forever), then `hold`
  `last` (keep the final frame) or `hide`; `speed`, `offset` (clip frames), `z` (higher on top).
* `frames`: collage length (default: the latest finite item end, else 4 s); `scale`: whole-output upscale;
  `background`: colour or `transparent`.

```
python -m gbox.sprite_collage layout.json --out collage/ [--root <collection root>] [--no-mp4]
```

writes `frames/collage_NNNN.png` (RGBA), `collage.json` (resolved layout + per-item clip info), `preview.apng` and
`collage.mp4`. From Python: `sprite_collage.render(layout, root)` returns the frames as arrays,
`sprite_collage.export(...)` writes them. Because clip times are game frames at 60 fps, a collage at `fps: 60` plays
every animation at the game's own speed; at other rates each clip is resampled by time.

## Tests

`tests/test_sonic2d_sprites.py`: Nemesis (both modes, short codes + inline escape) and Kosinski (known stream,
round trips), mapping/DPLC decode for the three layouts and the S3K object DPLC, script engines (loop, back, switch,
speed-driven delays, S1 object flip bits, S3K raw scripts, sequences), canvas alignment and flips, piece order, a
synthetic Sonic 2 shaped ROM through discovery to the clip files and sheet.json, title tests / DEDICATED
registration, and the collage (timeline, loops/hold/hide, flip, z-order, reading clip folders). The owned-ROM tests
pin the discovered offsets and the spin dash / jump / level-complete sequences, and skip when the dumps are not cached
at `~/gBox_alt/gbox-cache/<game_id>/source.zip` (override the folder with `GBOX_ROM_CACHE`).
