# Twin Snakes and DOA2 native photo-face candidates

These builds put the approved Bla photograph into reviewed native face
materials. They retain each original body, mesh, rig, costume and animation.
They are separate copied discs, not Leon body swaps. No source disc or operator
save/card was modified.

| Game | Build | Native face coverage |
| --- | --- | --- |
| Twin Snakes GGSEA4 disc 1 | `tts_disc1_bla_native_faces_20261015_151943` | 109 material instances in 40 model hashes |
| Twin Snakes GGSEA4 disc 2 | `tts_disc2_bla_native_faces_20261015_151943` | 96 material instances in 39 model hashes |
| DOA2 Limited Edition Japan | `doa2_bla_native_faces_20261015_151033` | 79 fighter/costume archives, including bound story/boss variants |

The native image files are verified after reintegration. Twin Snakes verifies
every unselected decoded stage resource, including all models and motion data.
DOA2 verifies unchanged CHR/MOT/SUP files and restricts every write to a selected
native texture payload. Independent owned-disc checks confirmed that all 79
DOA2 texture filenames match the executable's render resource table. All selected
Twin Snakes TPL headers had min/max LOD zero and linear base-level filtering;
the writer rejects mipmapped faces until a full-chain writer exists.

The tools `twin_snakes_face_build` and `doa2_face_build` offer `op=plan` and
`op=build`, a photo artifact SHA-256, label, and per-native-profile crop,
head-space bounds, opacity and feather controls. Source texture identities and
native bindings cannot be overridden through those controls. A new photo or
actor placement remains a review candidate. Native iris/eyeball geometry stays
original; individual eye alignment and likeness are not certified by a file
verification check.

Twin Snakes uses authored mirrored face UVs. Sampling opposite photo halves at
nearly equal overlapping depths caused visible speckling. Canonical half-face
sampling resolves that conflict without modifying the mesh or UVs. Native head
GLBs rendered with the final texture show a continuous face; a center seam and
native facial proportions can remain. Source-photo alpha now controls paint
coverage while the native texture alpha remains unchanged. Native lighting
normals select front-facing triangles rather than modulating individual paint
pixels.

Each build keeps four actor before/after pairs available to the loading UI and
packs other native previews/masks into one verified ZIP. The final launch
folders contain 12, 12 and 15 files respectively. Future TTS previews include a
geometry hash so different stage variants cannot overwrite another pair.

These are partial coverage builds. Twin Snakes leaves `shared/face.dat` codec
portraits unchanged: that separate unpacked directory contains 1,528 portrait,
mouth and eye animation images (241 unique images), not the 3D head UV layout.
`demo.dat` streamed resources, prerecorded movies and unreviewed or fully
helmeted materials are also unchanged. Stage-native scene resources that reuse
the edited heads receive their face textures; this does not establish complete
cinematic coverage. `nja_def` and `nja_dmo` still exceed their compressed slots
by 2,048 bytes on both discs, after bounded standard zlib strategies; those
stages are preserved unchanged and listed in the reports. DOA2 leaves unbound
story archive `YTI00`, roster portraits and prerecorded videos unchanged. No
complete-cast or all-cutscene claim is made.

The final DOA2 copy cold-booted in a private Spark Flycast session, reached a
native fight and responded to controls. Twin Snakes disc 1 cold-booted in private
Dolphin with a new private card through its intro/title. A playable TTS stage,
disc 2 runtime, every costume and final likeness were not certified. All private
native proof processes stopped; JAY's operator game remained untouched. The
sanitized receipt is [twin-snakes-doa2-native-face-validation.json](twin-snakes-doa2-native-face-validation.json).

Twin Snakes inventory remains unsupported by these tools. The
[official Dolphin GGSEA4 settings](https://github.com/dolphin-emu/dolphin/blob/master/Data/Sys/GameSettings/GGSEA4.ini)
publish Action Replay candidates, but those are not independently validated
inventory operations for this owned executable. No speculative RAM writes were
added. DOA2 has no RPG item inventory, and no unverified roster/costume unlock
patch is included.
