# Native DOA3 asset inventory

`gbox.doa3_assets` inventories the reviewed USA Xbox executable and its
`loadfile.afs`, then preserves explicitly selected native members in a reusable
bundle. It does not stage or copy the movies, whole disc, executable, or saves.
The source folder is read only; output must be a separate directory.

The clean USA XBE and the independently verified media/region-patched XBE are
the only accepted executable revisions. The inventory records the actual XBE,
AFS and member SHA-256 values. An optional upstream archive digest is marked
`caller_supplied`; this reader does not claim to have rehashed that larger ROM.

```python
from gbox.doa3_assets import inventory, export_selected

index = inventory(disc_folder, game_id=game_id)
bundle = export_selected(disc_folder, title_asset_folder,
                         game_id=game_id, costume="zac00")
```

Exactly one export selector is required: `fighter=<native nickname>`,
`costume=<native costume code>`, `entry_ids=[AFS indices]`, or `all_assets=True`.
Fighter/costume selections include the native `.bin`, motion banks, known shared
motion/data members, and complete XPR/CAT pairs. AFS indices distinguish duplicate
names on the actual disc. `all_assets` omits placeholder members.

The schema is `gbox-doa3-native-assets-v1`. Inventory returns `members`, `fighters`,
`source` and `capabilities`. Members carry index, filename, source offset, size,
SHA-256, magic/format, native kind, and an explicit `placeholder` boolean.
Fighter families expose `.bin`, `motion_indices`, `shared_indices`, and costume
XPR/CAT indices. Exports add `selection`, output-relative member paths, `counts`,
`bundle_dir` and `reused`. The bundle contains native files and `manifest.json`.
Partial member selections report `missing_companion_indices`; they do not claim
that a costume is complete when its CAT, motion or native data is absent.

All results explicitly state `raw=true`, `decoded=false`, `writable=false`,
`reimportable=false`, and `full_character_replacement=false`. XPR0's first `MDL`
user-data tag identifies a model resource; it does not establish that its meshes,
rig, CAT morph/joint data or motions have been decoded. No GLB, texture preview,
retargetable character, full cast build or working game replacement is implied.

Input is bounded to 8,192 entries, a 2 GiB archive, 128 MiB per member, and 1,024
selected members/512 MiB per bundle. Header/name-table ranges, source filenames,
overlaps and declared sizes are checked before output. Output names include
the source index, preventing same-name collisions. Publication is atomic after
member and source hashes are rechecked; reuse verifies the complete bundle.
Changed or unexpected existing bundle files fail without being overwritten.

The native runner derives its disc root from the directory containing `--xbe`.
Thus future asset-only builds can retain the pinned generated program, but they
still need a verified native MDL/CAT encoder, rig conversion and game validation.
See the [official native runner](https://github.com/NoRain211/doa3-re/blob/v0.2/recomp-runtime/runner.cpp)
and [kernel file bridge](https://github.com/NoRain211/doa3-re/blob/v0.2/recomp-runtime/kernel_file.c).
