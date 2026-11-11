# RE4 Switch donor fit: winding / normals / head-seat QA (request #9531) - milestone 1, measured

Scope: read-and-report. No code under `system/gbox` changed. Game files stay on lilspark disk; only these tables are in git.

## What the fit code does today (read in `gbox/re4_switch_models.py`)
- `FIT_GATE` (line ~711) checks height ratio, depth, floor/sole, segment stretch, span, head-size ratio, far-vertex share, limb skin.
  **None of its keys looks at triangle winding, normal direction, head-joint height, or neck length.**
- A grep of the file for `det`, `flip`, `mirror`, `reverse`, `winding`, `[::-1]` finds no winding handling: donor faces go
  through `mtf_materials.source_mesh` -> `fit` -> `A.soup` unchanged (faces are emitted as triangle *lists*, `PRIM_LIST`, not strips),
  so a strip-parity mismatch is not the mechanism for a list-written mesh. A negative-determinant transform inside `fit` was
  **not determined** (not traced line by line this run); settle it by asserting `det(R)>0` for each role transform in `fit`.

## Measurement (method)
Parsed with the repository's parsers: `A.pack_slots(udas_bytes)` -> `A.HdBin.parse(slot)` -> `.positions()`, `.normals()`,
`.materials()`, `A.triangles(materials)`, from the built overlay
`gbox-cache/mods/270a15eb98dab4d7/recovery-re4-fit-v4-20261110/romfs/bio4/em/pl*.udas` (slots 0 body-far, 2 body, 4 head, 5 face/hair
parts where present). Columns:
- `winding_vs_stored`: share of triangles whose geometric normal (b-a)x(c-a) has positive dot with the sum of the 3 stored vertex normals.
- `stored_inward`: share of vertices whose stored normal points toward the slot's vertex mean (centroid test; unreliable on concave parts).
- `signed_volume`: sum a.(bxc)/6 over triangles; positive = CCW-outward on a closed mesh (units of the slot; slot 0 is in a different scale).

| file | slot | tris | winding_vs_stored | stored_inward | signed_volume |
|---|---|---|---|---|---|
| pl06 | 0 | 732 | 0.985 | 0.31 | +2.03e8 |
| pl06 | 2 | 1666 | 1.000 | 0.12 | -8.28e4 |
| pl08 | 0 | 1629 | 0.996 | 0.31 | +1.11e8 |
| pl08 | 2 | 958 | 1.000 | 0.20 | +9.15e4 |
| pl08 | 4 | 900 | 0.990 | 0.27 | -3.86e4 |
| pl0a | 0 | 3699 | 0.976 | 0.31 | +9.29e7 |
| pl0a | 2 | 2447 | 0.998 | 0.13 | +1.09e5 |
| pl0a | 4 | 3250 | 1.000 | 0.12 | +3.73e5 |
| pl0b | 0 | 2044 | 0.976 | 0.27 | +1.65e8 |
| pl0b | 2 | 1545 | 1.000 | 0.05 | +3.96e4 |
| pl0b | 4 | 1977 | 0.999 | 0.18 | -1.48e4 |
| pl0d | 0 | 1095 | 1.000 | **0.61** | **-1.08e8** |
| pl0d | 2 | 2258 | 1.000 | 0.20 | +9.61e4 |
| pl0d | 4 | 770 | 1.000 | 0.17 | -4.58e4 |

(pl08 slot 5 and pl0b slot 5 are 38-39 small parts; per-material numbers are in the run output, many 1-sided cards with inward share 0 or 1.)

## Findings
1. Winding agrees with the *stored* normals in 97.6-100% of triangles everywhere, so stored normals and winding are mutually
   consistent: an inversion, if present, is in both together (fits "whole mesh inverted"), and a stored-normal-vs-winding check
   would **not** catch it. The gate needs the centroid/signed-volume test or the donor's source normals.
2. **pl0d slot 0** is the one part flagged by both independent tests: 61% of normals inward (>50% threshold in the request) and
   negative signed volume. The other body parts are outward by volume/centroid test (pl06 slot 2, pl08/pl0b slot 4, pl0d slot 4 are
   negative-volume but open/concave head or hair meshes; the sign is not conclusive there).
3. Which slot is Wesker's, and so the operator-seen donor, is **not determined** from the overlay: `.gbox-mod.json` names the files but not
   the cast mapping. Settle it by reading the cast table written by the build job `ae6e9f3c63d24ba1` (`cast_pool`).
4. No head-seat measurement yet (head joint height vs shoulder line, neck length vs target) - **not determined**; needs the donor
   skeletons (`library_donor` records `joints`/`role_nodes`) which this run did not load.
5. Live-frame QA and before/after renders (items 2-3 of the request): **not done**; they need a game session and a render, both excluded by this ticket's rules.

## Next milestone
Run the same table on the source donors (`library_donor(...)['faces']` vs normals) to separate donor-inherited inversion from fit-introduced inversion;
trace `det` of each role transform in `fit`; add the head-seat numbers. Proposed code change (needs lifting the no-code rule): add `winding` and `head_seat`
checks to `FIT_GATE`/`fit_report` with pass/fix/reject, flipping a part's triangle order when >50% inward.

## Milestone 2 (2026-11-10 night): root cause measured, fixed in the shared loader

Measured with `gbox.mesh_orientation.measure` on the posed `mtf_materials.source_mesh` output of all 650 usable donors
of `scratch/re4-greybox-all/library-survey.json` (outward = area share of triangles facing away from their welded
part's centre; volume = share of the parts' signed volume that is positive):

| exporter (glTF `asset.generator`) | donors | outward area | outward volume | stored normals vs winding | verdict |
|---|---|---|---|---|---|
| `gbox ff7_models` (FF7 battle + field) | 7 | 0.02-0.18 | 0.00 | agree (face normals of the winding) | inside-out, normals too |
| `gbox.stranglehold_models` | 39 | 0.10-0.34 | 0.00 | agree | inside-out, normals too |
| `gbox melee_models` Smash fighters | 20 | 0.07-0.27 | 0.00-0.01 | against (normals outward) | winding inside-out (the RE5 survey's "cw") |
| `gbox melee_models` Fighting Wire Frames (no NORMAL) | 2 | 0.22-0.23 | 0.00 | face-normal fallback | inside-out |
| `gbox soulcalibur2` | 4 | 0.17-0.27 | 0.00-0.01 | against | winding inside-out ("cw") |
| every other exporter (578 donors) | 578 | 0.61-1.00 | 0.99-1.00 | agree | outward |

- Native RE6 body records: winding vs normals 0.99-1.0, outward 0.68-1.0 (one inner Leon record 0.02, legitimately inward). The RE4 / RE5 / RE6 writers keep the source's
  orientation exactly (RE6 enemy-cast-01 donor records read back with the source numbers to 4 digits), so the inversion
  is the donor's: no writer step mirrors, and the RE4 `fit` role transforms are proper rotations times positive scales.
- pl0d slot 0 (milestone 1) is `ff7_earith` (FF7 Aerith, battle model): outward 0.046 as written, every part negative.
- Only RE5 turned the "cw" donors (survey `rig.winding`); RE4 and RE6 turned none, and no title caught the
  FF7 / Stranglehold / wire-frame donors, whose normals agree with their wrong winding.

Fix: `gbox/mesh_orientation.py` decides one orientation per model from the geometry (inside-out when both shares are
<= 0.4, outward when both >= 0.6, else left alone; a part is never turned alone, so a mouth or a lining stays), turns
the winding and negates the stored normals when they point against it. `mtf_materials.source_mesh` (RE4, RE5, RE6
textured and enemy-cast loads) and `re6_switch_models._source_geometry` apply it, and both turn back faces mirrored by
a node or joint with a negative determinant (glTF rule). `re5_mesh_import` turns a "cw" donor only while it is still
wound against its normals, so the stored survey's flags cannot turn an oriented donor twice. After the fix all 650
donors load outward through both loaders (72 turned, 46 with their normals negated); offline, Aerith on RE4 pl0d reads
back outward 0.954 (was 0.046) and on the RE6 Leon slot 0.937 (was 0.063). Tests: `tests/test_mesh_orientation.py`.
