# RE5 Sonic Mercenaries cast / Mario enemies: implementation handoff

2026-11-09. The requested scope is **RE5 only**, with multiple Sonic-franchise characters as the Mercenaries cast
and Mario-franchise characters as enemies. Do not modify RE4/RE6 or present one Sonic in every slot as the completed
cast. Current live session ownership and scheduler state belong to the root handoff; reread them before operating.

## What exists and what is proven

The latest full Sonic candidate is `re5_sonic_writer.build_grip_candidate(original_chris_arc, sonic_glb)`, a separate
unregistered callable. It reproduces archive SHA256
`d96c9c9e8efaee4cf3a0eda9f10ff12ef1515e1efd604f9c34d081cd3a80cb8a` exactly. Its only target is
`nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc`. Source `sonic/sa2_sonic_0.glb` SHA256 is
`5dd7cc07f3116a8f1f59ccc9bde8da5ccae65338cbf83d8c7151608c2ae74df4`; original target ARC SHA256 is
`8ab0dc181d1f6ec155e193c5820d1756d877acf711424863b16f7850b592f6c8`.

V15 retains the corrected 140 cm body, native T-pose arm/hand frames, cuff wrist pivots, source textures and normals,
native finger chains, and scaled root-Y motion. It fits palm contact dimensions to native Chris while preserving the
proximal cuff. Fifty-seven focused tests pass; 14 sampled frames preserve body/arm/wrist motion exactly and match
native wrist-local digit anchors within 0.000002 cm. The full V15 live acceptance result must be read from the latest
root report; these offline checks do not establish actual weapon contact. V14 booted and fought; visibility diagnostics
showed forward arms but oversized palms. The custom writer's default `build()` still emits V12, and dispatch is disabled.
Do not accidentally call that older default when reproducing V15.

The V15 headless/+65 cm visibility diagnostic SHA256 is
`99238b72667ddedb667b0e947d3e064f91464c8e52522f5ad409cbb937e499d0`. It is never a default or finished replacement.
Its 551 head triangles alone are degenerated; body/hand geometry is exact V15. It reuses the audited V14 lifted LMT
resources unchanged. Do not assess ground contact or procedural leg IK from that diagnostic.

Read-only SSH audit of `/home/ehm_eckx/gBox_alt/gbox-cache/mods/52d15709be0fda1a` found **120 build directories and zero
Mario mentions in their root JSON markers, names or overlay paths**. The live character library has no RE5 target
mapping for `mario`, `mario_hd`, `sm64_mario`, or `melee_mario`. There is no verified Mario enemy overlay to compose with
V15 in that audited cache. Existing `cast-inverted`, `bs-all14`, `re5-onemesh-all` and enemy harness names do not prove
the requested cast. Earlier `em1000` one-mesh Sonic V3 played sustained combat but nearby enemies still appeared stock.
Variant/group coverage was unresolved; do not use those artifacts as accepted enemy replacement.

Raw audit evidence stays local, outside git:

- `.scratch-merc-recovery/existing-re5-builds-audit.json`: all 120 names, markers and overlay file paths.
- `.scratch-merc-recovery/franchise-library-current-audit.json`: current model/provenance/rig metadata.
- `.scratch-merc-recovery/assets/v15-writer-reproduction.json` and `v15-motion-contact-audit.json`.
- `.scratch-merc-recovery/assets/sonic-player-grip-v15/` and `sonic-player-grip-lift65-diagnostic-v15/`.

## Existing source inventory and proposed first coverage

These entries were read from the current authenticated library. Existing role metadata is a starting point, not a
verified RE5 retarget. All listed donors have **no registered RE5 target**. The table is a practical proposed mapping;
only Sonic/Chris has been authored through this pipeline so far.

| Merc family target | Proposed donor slug | Source | Current coverage |
|---|---|---|---|
| Chris normal | `sonic` | SA2 USA, 62 joints | V15 authored; live grip acceptance tracked separately |
| Sheva normal | `sa2_tails` | SA2 USA, 62 joints | Inventory only |
| Jill Cos1 | `sa2_amy_rose` | SA2 USA, 62 joints | Inventory only |
| Wesker Cos1 | `sa2_shadow` | SA2 USA, 62 joints | Inventory only |
| Josh | `sa2_knuckles` | SA2 USA, 62 joints | Inventory only |
| Excella normal | `sa2_rouge` | SA2 USA, 62 joints | Inventory only |
| Barry normal | `sa2_dr_eggman` | SA2 USA, 46 joints | Inventory only; proportions need separate fit |
| Rebecca normal | `sa2_tikal` | SA2 USA, 62 joints | Inventory only |

SA2 source game is `d95ed7ed1e40552a`. Also present: `sa2_metal_sonic`, `sa2_super_sonic`, `sa2_super_shadow`,
`sa2_chaos_0` (62 joints each). SA1 USA `1a3f4cd416db9ffd` supplies `sa1_sonic`, `sa1_super_sonic`, `sa1_knuckles`,
`sa1_big` (74 joints), `sa1_amy` (79), `sa1_tails` (69), and `sa1_tikal` (104). These can populate additional costumes
after their model-specific roles, hands, materials and proportions are measured. Source role IDs and Sonic's glove
vertex selectors cannot be copied to these donors blindly.

Mario enemy candidates already extracted from owned games:

| Source | Available useful slugs | Rig notes |
|---|---|---|
| SM64 USA `b7aecee966090bfa` | `mario` | 20 joints; `mario_a197.gltf`; `gbox.sm64_mario` |
| SM64 DS USA `917483267d246594` | `sm64ds_mario`, `sm64ds_luigi`, `sm64ds_wario`, `sm64ds_peach`, `sm64ds_bowser`, `sm64ds_yoshi`, `sm64ds_toad` | 17/17/17/21/18/20/6 joints; role metadata present |
| Melee USA `181871982204517a` | `melee_mario`, `melee_luigi`, `melee_peach`, `melee_bowser`, `melee_yoshi` | 61/61/114/76/70 joints; finger geometry available, role labels require visual check |

`sm64_mario`, `sm64_bowser`, `sm64_peach`, `sm64_toad`, and `sm64_yoshi` also exist as operator-ROM/decomp exports;
their metadata uses a source hash and null game ID. Separate Render96 `*_hd` models exist but identify a model pack,
not an extracted owned-game donor. Keep that provenance distinction. No listed Mario-family entry is yet an RE5 build.

## Next implementation steps

1. Keep the full V15 Chris-normal artifact as the current reproducible experiment. Finish a clear native-engine idle,
   aimed-fire, movement and melee view. Record loaded overlay hash, character, advancing timer/score, hand contact and
   camera usability; do not infer them from black boot or an occluded frame. Preserve the user's existing MercMode
   settings and avoid enabling random characters while only one custom slot is covered.
   **2026-11-09 resume update:** the repeating queue survived four real terminal-round boundaries (sessions
   `d1257c16…`, `f8fc0664…`, `ce8c36cf…`, `43ab169e…`, `fc4ba1de…`), each relaunching the exact build/Chris BSAA/Public
   Assembly with advancing combat and fresh frames. **However, the committed `build_grip_candidate` no longer
   reproduces V15 byte-exactly:** stage-1 `build()` yields MOD97 `cec895d2…`, not the reviewed v12 `b87ecc87…`, and
   even the stored v12 MOD stitched through `re5_sonic_hands.author` yields `e9c2bf23…`, not pinned v14 `426ac8ad…`.
   Verified identical under the deployed share code, the clean deploy clone and a BOM/LF-normalized closure overlay on
   lilspark: recipe drift, not environment. The live overlay still hashes `d96c9c9e…` and the artifact store can
   restore it. Do not register/promote V15 until a faithful builder exists.
   **Correction (later 2026-11-09):** it was the environment. Those runs varied the code on one machine; the
   authoring PC rebuilds `d96c9c9e…`, and another BLAS kernel on that PC fails the same way. The model's kernel
   dependence is fixed in `gbox/re5_sonic_residue.py`; a lilspark run is still owed. See "Reproduce v15" in
   [the continuation guide](../DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md).
2. Inventory the extracted RE5 RomFS with `re5_char_swap.catalogue()`. Map actual selection IDs to **costume archive
   paths**, not only the eight family shortcuts in `skin_swap.CHARACTER_ARCS`. `re5_switch.CHARACTERS` labels 14 choices
   but its selector can learn a larger wrap count. The remote `re5-onemesh-all` folder contains 31 player archive paths,
   including armor/story variants; its filenames are inventory evidence, not proof that all are Mercenaries slots.
3. For each proposed donor, pin its bytes/provenance and make a reviewed role/palm/thumb frame profile. Retarget one
   target archive at a time using `re5_mesh_import`, retaining that target's native animation IDs, hierarchy, materials
   and motion resources. Reuse fixed MOD/ARC/envelope/TEX infrastructure, not Sonic-specific node indices, finger masks,
   exact hash guards or assumptions about target animation translation. Verify bounds, all triangles, skin sums, welded
   seams, bind inverse matrices, normal/tangent frames and paired motion before live testing each slot/costume.
4. For Mario enemies, first identify the archive/model/group actually drawn by one controlled Public Assembly enemy.
   **Done 2026-11-09 with live-RAM receipts (two boots of the owned repeating-queue session, enemy array walked at
   `sEnemy(main+0x1CF04B8) → +0x38 count / +0x48 pointer array`, classes named through the DTI vtable path exactly as
   `re5_switch.class_name` does, all through read-only `read_memory` jobs):** 40 slots each boot. Boot 1: `uEm10`×28
   (HP 800), `uEm11`×7 (HP 700), `uEm20`×1 (HP 8000 boss), `uEm62`×1 (dynamite prop HP 1), `uEmIntel10`, `cUnit`.
   Boot 2: `uEm10`×27, `uEm11`×8, `uEm21`×1 (dynamite carrier HP 1400), `uEm62`, `uEmIntel10`, `cUnit`. So the drawn
   Majini are classes **uEm10/uEm11 → `uEm10.arc`/`uEm11.arc`**; the raw audit also confirms 139 enemy archives via
   `re5_char_swap.catalogue()`. Inside `uEm10.arc` (pristine SHA-256 `1fa271890891ff31ac1aeb8d6dfc9a6d8bdcdd1ec252954b9d22a61519634a0c`)
   the measured models are MOD entries 234/235/236 = `em1000`/`em1000_low`/`em1000_mid` (paired MRLs 196-198) and
   237-239 = `em1001` variants (MRLs 199-201): ~341-351 mesh records each, 92 bones, 70 materials with `gam01_*_BM`
   albedos, groups 1..225 (head/costume/LOD option groups; **no group 0**, unlike the player archive). The prior failed
   coverage included `uEm0b`, `uEm10`, `uEm11`, `uEm12`, with `em1000/em1001` high/mid/low models and
   option groups. Target a visible body group and all its selected LODs; do not spread one character across mutually
   exclusive head/costume groups. The measured `uEm11 -> uEm10` class-rebind route requires its exact IPS and existing
   verified NSO build. It is not a generic cross-class archive-copy permission. Start with one Mario donor and one
   positively identified enemy, then extend the observed class/stage matrix.
   **Next bounded step:** the existing one-mesh `re5_mesh_import.build_archive` guards require a group-0 template, which
   enemy MODs lack, so a Mario enemy candidate needs a small new group-aware enemy writer (or an explicit reviewed
   relaxation of that guard) that replaces the body-group meshes of `em1000` + `em1000_mid` + `em1000_low` (and the
   matching `em1001` set if that variant is in scope) while retaining the native 92-bone skeleton, materials and motion.
   Candidate donor: `sm64ds_mario` GLB SHA-256 `ea509bdf870190e7…` (17 joints, complete role metadata) or `melee_mario`
   (61 joints, fingers). Build it as a separate `recovery-mario-*` overlay; never write into the live v15 build.
5. Compose accepted player and enemy archive changes into one tracked overlay with `switch_mods.write_files`, preserving
   existing unrelated entries and pending-edit/in-use handling. Refuse duplicate target-path collisions. Scope registration
   to RE5 title `010018100CD46000` / game `52d15709be0fda1a`; make source/slot coverage explicit. Do not alter RE4/RE6,
   overwrite original RomFS, register a generic arbitrary-donor writer, or claim complete cast coverage before every
   enabled rotation slot has a validated mapping.

See [the detailed experiment record](re5-same-table-sonic.md) for decoder, envelope, ARC framing, pose, root motion,
camera and glove findings. Older notes claiming that restructured MOD containers cannot load were superseded by the
global-envelope-count and wrapped-zlib fixes; do not repeat those failed hypotheses as current format limits.
