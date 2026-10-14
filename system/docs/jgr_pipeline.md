# Jet Grind Radio (USA): character pipeline

Disc `Jet Grind Radio (USA)`, Dreamcast, game_id `4187aeab4d67638c`. Reader `gbox/jgr.py`, writer
`gbox/jgr_swap.py`, which is routed by `characters op=use` and registered in `char_coverage.WRITERS`. Tests are in
`tests/test_jgr_pipeline.py`, `tests/test_jgr.py`, `tests/test_jgr_twins.py` and `tests/test_jgr_pick_1153.py`.
`docs/jgr_re_findings.md` has the container reverse engineering this builds on.

## Format facts

Every fact here was checked on the owned disc for all 16 PLAYER.AFS characters, unless the line says otherwise.

| Fact | Confidence | Evidence |
|---|---|---|
| `PLAY+8` points at the binding record. The record holds int32 native ID, then 6 draw groups × 4 u32 slots (each group's root object). | high | The slots match `play_model_roots` on all 16 characters. The ID is the one 1ST_READ's lookup compares. |
| `PTEX+8` points at a record of the same shape. Its slots are `NJS_TEXLIST*` = {names ptr (count × 12 zero bytes), count}, followed by `count` pointers to GBIX+PVRT data. Slot 0 is the default look. | high | Each pointer lands exactly on a texture `ptex_textures` found. `PTEX+4` is the relocation table, which lists these fields. On the Poison Jam / Noise Tanks leaders, slots 1-3 name alternate colour atlases (GBIX 355000/455000). |
| A strip's Ninja texture id indexes its own group's texlist, not the PTEX file order. | high | Rendered textured: Yo-Yo's spray-can body binds id 0 to the can (GBIX 760) and id 1 to the atlas. Gum's and Nuts' atlas is PTEX 1, and so is the Poison Jam leaders'. |
| Group roles: 0 gameplay body, 1 its low detail, 2 body with the spray can in hand node 15 (80 triangles on GBIX 760), 3 that body's low detail, 4 shadow volume (20 nodes, vertices only), 5 separate 4-node head (face-expression sheet; a single empty node on Goji/Pots). | high for 2-5 (structure). Groups 0/1 are the gameplay pair on Beat (Hermes #1156); the other characters are assumed to match. | Per-group node, triangle and texture counts for all 16 characters (`GROUP_ROLES`; `test_owned_groups_texlists_and_atlases`). |
| Strips with the ignore-light flag (`NJD_FST_IL`, bit 0 of the strip chunk flags) are the cel-shading outline. They form an inverted hull 0.08-0.13 unit outside the body, with normals reversed (median dot -1.00 against the nearest body normal). The hull has about one triangle per body triangle. It is drawn near-black, or with the shared tiny GBIX 2 texture on Combo, Corn, Gum and Nuts. | high | `test_owned_outline_is_a_reversed_hull_on_every_body` |
| Lit strips without UVs (chunk 0x40) draw in the material's diffuse colour. | medium | No gameplay body has such strips outside the outline. Gum has 16 transparent ones (alpha 0). |

## #1396: why the extracted character couldn't be recognised

The collector exported the 20-node tree with the most triangles. That tree is group 2, the spray-can body. The
export had three defects:

1. **The surrounding shell.** About half of every body is the outline hull, a dark copy of the body pushed 0.1 unit
   outward with its faces turned inward. The game culls its front side, so on screen only the silhouette edge shows.
   An ordinary viewer draws all of it, so the character sits inside a dark (or texel-coloured) shell.
2. **Wrong textures.** Texture ids were bound to PTEX file order. On Yo-Yo the whole body drew the 128×128
   face-expression sheet (orange hair), which is the orange blob in the report. Gum, Code, Reco, Nuts and the rival
   leaders were mis-textured the same way.
3. **Extras.** The spray can in the right hand came along with the body, as did group 2's different hand pose.

Fix (`jgr.export_character`, collection reader version 2): `<slug>.glb` is draw group 0 alone, textured through
its own texlist, without the outline hull. Everything else goes to `parts/` as a separate GLB with the same
skeleton: `<slug>_outline.glb`, `_body_lod`, `_body_spray`, `_body_spray_lod` and `_head`. The shadow is listed with
0 triangles and has no file. `meta.json` gains `jgr_reader: 2`, `draw_group` and `parts`. `characters.collect` /
`extract` re-extracts entries made by the old reader (`jgr.needs_refresh`), so re-running collection upgrades the 16
existing `jgr_charNN` entries.

## Writer (`gbox/jgr_swap.py`)

Slots:

- `player`: the character being played. If `active_id` (native ID 0-15) is given, that character. Otherwise Beat
  (native ID 0, archive 04), because a new game starts as him; the pick frames of #1150/#1153/#1156 show him at first
  control. The result carries `player_assumed` whenever it guessed.
- `character:<name>`: `beat` (`ereki`), `gum`, `corn`, `combo` (`conpo`), `code`, `nuts` (`nat`), `reco`, `bis`,
  `yoyo`, `plug` (`pench`), `goji`, `pots`, `rival_lshocker`, `rival_ntank`, `rival_pjam` and `rival_snpjam`. These
  names come from the disc's AFS directory and the 1ST_READ debug labels. No US marketing names are inferred.
- `id:N` (native ID) and `NN` / `jgr_charNN` (archive index) work as before.

`cast_slots()` feeds the cast menu that `characters op=collect` returns: `player` plus the 16 `character:` slots.

Build (`jgr.build_swap`, `jgr.build_mod`, `jgr.use`; cache schema 7):

1. **Fit.** `ninja_swap.fit` retargets the donor onto the shared 20-node body with `jgr.BODY_ROLES` (15 roles) and
   decimates it through `BUDGETS` until it fits the PLAY entry's own AFS room.
2. **Strips.** Every textured body group gets the new strips (groups 0-3; shadow and head stay as they are).
   - A group whose node bind matrices differ from the primary group's gets its own copy of that node's strips,
     re-expressed through `inv(W_twin) @ W_primary` (`twin_transforms`), so all groups show the donor in the same
     bind pose. Examples: Beat's moved hand, the turned or scaled can hand of Bis, Combo and the Love Shockers'
     leader, and Gum's rescaled low-detail limbs.
   - A group whose texlist id for the atlas differs gets its own copy too (`group_texture_ids`): Yo-Yo's, Code's
     and Reco's spray-can bodies, and Gum's low-detail body.
   - Each object has its own 24-byte model record, even when it shares immutable vertex/polygon lists with
     another group. Ghidra analysis of the owned US executable identifies `FUN_8c0c75f0` as the PLAY loader
     and `FUN_8c0c7278` as the recursive in-place relocation routine: it adds the PLAY base into model list
     pointers on every object visit, without a visited-model guard. Sharing records adds that base repeatedly.
     An offline transcription applied to the reported #1853 archive produced 100 invalid list pointers;
     the stock archive produced none. This is an offline loader simulation, not a live RAM capture.
     Schema 7 prevents reuse of builds produced by the earlier shared-record writer.
3. **Atlas.** The atlas is the largest texture in group 0's texlist (`atlas_texture`). It is re-encoded in place in
   the same PVR format and size.
4. **Disc.** PLAYER.AFS keeps its length and every other entry. `gdrom.patch_gdi` writes a new GD-ROM image into a
   new, identity-named mod directory. The owned disc and existing mods are never written.

`pso_player`'s NJ writer is not reused. A PLAY is a raw node tree without the NJCM wrapper, and its node structs
must stay where the binding record points. The writer only swaps model pointers.

Offline fit check: on the owned PLAYER.AFS, with a stub donor (`ninja_swap.fit` replaced, no Blender), all 16
characters build and all four body groups re-decode the atlas through their texlists. The triangle budgets that
fit are 300 (Gum, Noise Tanks leader), 400 (Yo-Yo, Code, Reco, Poison Jam leaders) and 500-950 (the rest; Beat 650).
A real donor's lists differ, so these numbers are indicative only.

Not done / unverified:

- The motion data (PLAY kinds 4-7) is untouched, so the donor plays JGR's own animations through the 20 nodes.
- Alternate colour slots 1-3 of the rival leaders still point at their original atlases.
- The reported v5 Beat build reached the tutorial in #1853 investigation captures, followed by a black frame.
  A matched stock comparison and a sustained failure in that build were not verified. Schema 7 fixes the
  offline relocation defect. The separate Amy build reached player control on idle i9-NUC, moved with the
  analog stick, jumped, and remained visible from timer 91.50 through 36.70. See [capture evidence](evidence/jgr-model-relocation/README.md).
  Front-view facial geometry/detail still needs review; this is not a claim that all visual defects are fixed.
  Spray-can groups and the other 15 replacement targets still lack live verification.

## Live check (do this before closing #1151/#1153/#1156)

1. Re-collect: `characters op=collect game="Jet Grind Radio (USA)"`. Open `jgr_char15` (Yo-Yo) in Assets. Expected:
   green frog hoodie, dark trousers, skates, no dark shell, no can, and `parts/` listing outline, body_lod,
   body_spray, body_spray_lod and head.
2. Build without launching (on the Spark control plane):
   `characters op=use character=sa2_amy_rose game="Jet Grind Radio (USA)" slot=player launch=false`. Expected:
   `replaced` = Beat (native 0, archive 04) with `player_assumed` set, and a new mod
   `jgr_sa2_amy_rose_04_<16 hex>` whose report has `atlas_texture: 0`, four `body_groups` and
   `texture_ids` all 0.
3. Launch on an idle worker, never over the operator's session:
   `start_job tool=@launch input={game_id: 4187aeab4d67638c, mod: <name from step 2>, node: <idle worker>}`.
   NEW GAME route: Start, Start, then mash B/Start to first control (Flycast maps RetroPad A to Dreamcast B; on
   Linux use the UDP network gamepad, port 47409). The timer starts at 96 to 100.
4. Pass: at timer ~92 (the pick frame), Amy stands where Beat stood (50 % / 56 %). She skates, steers and jumps with
   the pad, and her body is textured with her atlas, not stretched or exploded. Then let the timer run out or
   spray: TIME OVER and spraying draw the can bodies (groups 2/3), which should show Amy too.
5. Fail signs: an empty centre (vertex-span problem, see #1153), Beat still drawn (wrong group or archive), or Amy in
   flat colours / the wrong texture (texlist id). Attach the frames to #1153 with the mod name and the job id.
