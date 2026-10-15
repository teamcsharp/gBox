# Native sprite face editor and game build requests

The lady button beside a session's search opens a request pinned to that game and current build. Free-form requests enter the existing durable engineering queue. Explicit native recipes build Sonic 2's player sprites into Super Mario Bros., or publish an accepted photo preview. Closing the dialog does not cancel submitted work. Play/download controls appear only after a completed build marker and payload exist.

The face editor accepts original photo pixels, crops, mirroring, elliptical/rectangular masks, feathering and up to eight layers. Each layer has translation, rotation, scale, visibility, opacity and normal/multiply/screen/overlay/darken/lighten blending. Profiles are retained locally per game. Debounced live previews permit one request at a time and discard stale responses. Each accepted preview names an immutable, source-hashed ROM snapshot. Requesting that snapshot publishes exactly those bytes, never an approximation of the preview.

## Supported native layouts

* Super Mario Bros., catalog `49b6a2f65aca26a2`: all 26 native player animation rows; NES three-opaque-color quantization. Shared pattern pixels used outside a face mask are preserved. Sonic replacement uses 67 of 91 player-exclusive tiles and patches the native player palette reload table, including fire colors.
* Sonic the Hedgehog 2, catalogs `938e4ca5b120e344` and `764582c25053f662`: real mappings/DPLC and 4bpp art nibbles, original player palette, shared-pixel voting/protection and recalculated Genesis checksum. Only visible face regions are edited; rolling/blank frames can remain unchanged.
* Super Mario 64, catalogs `b7aecee966090bfa` and `66062703301f4969`: the owned PAL layout, original gameplay head geometry, 32×64 RGBA16 projection. Yaw, pitch, projection width/height and center are adjustable alongside the image layers. Before/after orbit viewers load glTFs decoded from the original and patched ROMs. The output retains 752 triangles and 20 joints, without decimation. Resulting models appear in Models under their source selfie tag and can use the existing download/Blender workflow.

This is live ROM **preview**, followed by a build and normal emulator launch. It does not continuously inject edits into an operator's running emulator. Other games and revisions require their own verified native readers/writers; “NES through N64” is not a promise that every ROM has the same asset layout.

Mario 64's boot-screen Goddard head is a separate target. Its textured projection writer is **not implemented**. The UI supports an explicit boot/both engineering request and refuses to publish the gameplay-only recipe as both. No mock head or simulated deformation is labeled as native output. The [native intro script](https://github.com/n64decomp/sm64/blob/master/levels/intro/script.c) loads that head separately from gameplay Mario.

## Mario 64 repeatedly opening Options

The catalog entry labeled USA contains the same PAL `NSMP` ROM as the Europe entry: SHA-1 `4ac5721683d0e0b6bbb561b58a71740845dceea9`, matching the [decomp project's EU identity](https://github.com/n64decomp/sm64/blob/master/sm64.eu.sha1). The PAL [file-select source](https://github.com/n64decomp/sm64/blob/master/src/menu/file_select.c) sets `sOpenLangSettings` when no save slot exists, so fresh build filenames repeatedly force Options after Start.

`sm64_startup` fingerprints the 64-byte PAL menu-init block at ROM `0x206A4C`. At `0x206A88`, it changes `sb s2, 0(s1)` to `sb zero, 0(s1)`: one byte differs. The empty-save auto-open flag remains false; manually selecting Options and language controls works normally. Other instructions, title sequence and EEPROM are unchanged. Unknown fingerprints are refused, and US/nonmatching headers are not patched. New native Mario builds include this correction; existing base/build launches use a separate cached copy with the same basename so existing save filenames remain usable. Original library files are never edited. TAS playback bypasses launch-time patching to preserve recorded timing.

## Verification and limits

Managed browser checks cover pinned requests, uncertain-response retries, build availability, native photo previews, layer invalidation/coalescing, profile retention and the boot/gameplay distinction. Python checks exercise actual server registration, request binding, candidate ownership, shared-tile protection, native pixel writes, blending, projection geometry preservation, disposable preview limits and the one-byte startup patch.

Private owned-ROM tests booted the resulting NES and Genesis images for 1,600 frames in Mesen and Genesis Plus GX. The corrected Mario 64 photo ROM booted and reached Castle Grounds after 6,000 frames in ParaLLEl N64 using its [software rendering option](https://github.com/libretro/parallel-n64/blob/master/libretro/libretro.c). An unmodified PAL control reproduced forced Options under identical input; the corrected ROM reached gameplay with a blank isolated save. These tests establish boot/gameplay execution, not full-game completion or final approval of facial alignment. A real WebGL preview was inspected. Low resolution, native palettes, original facial geometry and shared tiles limit photographic likeness; alignment remains editable and subject to operator review. No original photos or ROM bytes are committed.

Unsubmitted preview snapshots are capped at 32 / 128 MiB; snapshots referenced by requests or build jobs remain pinned. Requests contain source-photo artifact hashes and exact mappings, not arbitrary filesystem paths. Models use authenticated, game-bound candidate URLs. Build output names derive from the actual ROM hash and existing outputs must match before reuse.

## Loading images

Native sprite builds do not need a separately extracted character-library entry to show their artwork. Build details declare original/source/result preview URLs. The authenticated preview handler decodes the original ROM, donor sprite and the exact finished build, stores content-bound PNG artifacts, and serves crisp images with contain sizing. The loading cards show both original player → native result and source asset → native result. Mario 64 images are explicitly labeled as gameplay face textures. Preparing these cached images never edits a build marker or payload, so already downloaded builds use the same workflow without replacing their immutable files.
