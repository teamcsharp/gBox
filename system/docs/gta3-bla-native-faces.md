# GTA III original-body photo faces

`gta3_faces` builds a separate PS2 SLUS-20062 disc using an approved photo artifact. It retains each native body, head geometry, rig, animation, clothing and executable. It does not use Leon's body or reduce geometry.

The owned image is SHA-256 `707714a290e8a6b700fb424dc437ffe0ee580181243ad6fa56b2c025bdca9e68`. Its GTA3.IMG contains 129 actual `Shead` actor models and 130 head-material rasters, including player outfits, pedestrians, gangs, police and special/cutscene cast. The misleading `8ball.dff` placeholder is not a clump; actual 8-Ball models are `eight.dff` and `eight2.dff`. CUTS.IMG contains animation/speech/data rather than a separate model bank.

The writer projects the photo through each original head's frontal triangles into its native texture coordinates. It protects pixels shared by body or nonfacial head polygons, preserves alpha, reserves only palette entries unused by every unmasked mip level, and writes the original-sized native raster. It handles mirrored/repeating UV coordinates and every stored mip. It copies the original ISO once, changes the texture banks in all 12 mirrored IMG archives, and hashes each bank back. Every original actor DFF and the executable/animation archives are compared unchanged before publication.

The build marker records the photo hash, native actor identities, coverage and pending verification. `previews/` contains eight complete contact sheets plus standalone original/result atlases, masks and five fixed-geometry texture-blend snapshots for Claude, a police officer and 8-Ball. Complete per-actor originals remain in the analysis work directory. Sheet references include explicit crop rectangles. `photo_faces.previews` supplies three standalone before/after pairs to the loader. A build needs about 37 files rather than over 1,000 small transfers. These snapshots illustrate texture projection; they do not claim head-shape deformation.

These are experimental photo mappings requiring native visual review. A successful raster write does not prove that every face is aligned well or every cutscene is visually correct. Headwear, shared UVs and original eight-bit palettes constrain the result. For example, Claude has only ten available photo-palette entries while protecting all nonfacial colors, so highlights can be visibly banded. Prerecorded video is unchanged. Coverage deliberately records these limits separately from archive integrity.

Example tool request:

```json
{"tool":"gta3_faces","input":{"photo":"65d99957ebf5ac4a00558f6913bfcbddbee86b1ce4e2a0c44e893d1812781786","name":"gta3_bla_review","crop":[0.22,0.035,0.79,0.7],"opacity":1}}
```

Names must be unique; existing builds are never overwritten. Work is streamed per actor/bank and per IMG copy. No whole-disc or whole-archive in-memory copy is used.

## Native weapon inventory

`gta3_items` lists or grants the 11 ordinary carried weapons through the existing EE dispatcher and the game's original `CPed::GiveWeapon` function. It hashes five complete native routines from the owned SLUS-20062 executable, validates the player pointer and inventory layout, streams weapon models through native RequestModel/LoadAllRequestedModels, then reads every affected weapon slot back. It retains the equipped weapon. Unknown or timed-out mutations are not automatically retried.

```json
{"tool":"gta3_items","input":{"session_id":"<live-session>","op":"all_weapons","ammo":9999}}
```

`op="list"` is read-only; `give` and `all_weapons` require `memory_write`. `give` accepts a listed weapon name or native ID. A shared per-adapter transaction lock serializes the inventory tool, ordinary GTA mods, bootstrap, patch queue and call queue. A native bootstrap/mailbox write can be consumed before the external read-back; the tool accepts that only from exact payload/header/native-completion evidence, without repeating the write. A working remote-bomb detonator depends on the game's vehicle-bomb flow and is deliberately refused as a generic grant. Mission objects are not represented as a fabricated universal inventory.

The native evidence is the owned ELF SHA-256 `2a1322e74cfa41067fdbd3c7ec10b87c1b784e224f6f2c0a69cc36548dc06762`, its symbols and disassembly: GiveWeapon `0x1D8950`, GetWeaponSlot `0x1D8910`, weapon array `ped+0x3AC`, 20-byte slots, 13 native types. Automated tests cover refusal and transaction behavior; actual emulator execution is a separate verification step and must use an isolated agent-owned test session.

## Observed native verification, 2026-10-15

The separate face build cold-booted through the intro into live GTA III gameplay on idle i9-NUC using LRPS2. Claude's original prison outfit/body and animations remained present with the new face texture. All 11 ordinary weapon slots were absent before the native grant and present afterward; ammunition read back as 1 for the bat and 1,234 for each ranged/throwable weapon. Native clip capacities included pistol 12, Uzi 25 and M16 60. Unarmed remained selected until ordinary controller input cycled to the pistol. A gameplay screenshot then showed the new face, held pistol and native HUD ammunition 1,222 reserve + 12 in the clip. The test was agent-owned and did not touch JAY's running PSO session.

The final compact build is `gta3_bla_native_faces_compact_20261015`. Its ISO SHA-256 is `ff359e8545fdc44b9f325123925c7aaae60e2c7e9ec6a1bdf493c33660b2aea6`. The face/pistol gameplay frame artifact is `6e2548b09da2aaf1597de977d891fc39d9f1ffab7ccfb3feb4e0606e7324c34d`. These observations establish native boot, player-face rendering and weapon execution; they do not establish visual approval of all 129 faces or every cinematic. The immutable build marker conservatively retains pending in-game/whole-cast visual-review fields.
