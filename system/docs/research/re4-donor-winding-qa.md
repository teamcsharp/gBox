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

## Milestone 2 (measured 2026-11-10 evening)

### Wesker = pl0d (measured from `gbox/re4_switch_models.py` `PackLayout`/ROSTER, line 45 and 93)
`PackLayout("pl0d")`: slot 0 = upper body + coat, slot 6 = legs (bones 17-25), slot 4 face, slot 7 glasses, slots 14/16/18/20 hands.
So the operator-seen donor in Wesker's slot is pl0d of `recovery-re4-fit-v4-20261110`, and the part that was already flagged
(pl0d slot 0: 61% stored normals inward, signed volume -1.08e8) **is the donor's torso/body**. This settles item 3 of milestone 1.

### pl0d, every parseable slot (same parsers/columns as above, plus `geom_outward`)
`geom_outward` = share of triangles whose geometric normal (b-a)x(c-a) has positive dot with (face centroid - slot vertex mean). Concave parts blur it;
`signed_volume` is the more reliable sign for closed bodies. Slots that fail `HdBin.parse` (1, 3, 13, 22-49: GameCube-format or empty-header entries) are not meshes of this format and are not measured.

| slot | role (PackLayout) | tris | winding_vs_stored | stored_inward | geom_outward | signed_volume |
|---|---|---|---|---|---|---|
| 0 | upper body + coat | 1095 | 1.000 | **0.61** | **0.39** | **-1.08e8** |
| 2 | head | 2258 | 1.000 | 0.20 | 0.80 | +9.61e4 |
| 4 | face | 770 | 1.000 | 0.17 | 0.85 | -4.58e4 (open mesh) |
| 6 | legs (hidden part slot, y 449..563 in the overlay) | 1967 | 1.000 | 0.31 | 0.66 | -8.38e4 |
| 7 | glasses | 118 | 0.992 | 0.00 | 0.97 | +5.39e4 |
| 8 | (extra) | 2694 | 0.983 | 0.10 | 0.87 | +5.11e3 |
| 14/16/18/20 | hand poses | 592 each | 0.998-1.000 | 0.34-0.35 | 0.60-0.61 | +567..+580 |

### Transform determinant (item "negative-determinant transform in `fit`") - settled for `fit`
`fit` builds `rotation @ (I*cross + (along-cross)*axis axis^T)` with `cross, along > 0` (SCALES positive, ratio of norms). `mtf_retarget._aim_rotation`
= `frame(target) @ frame(source).T`, where each `frame` has columns (axis, across, forward=across x axis), which is left-handed (det -1), so the product is det +1.
Measured: 2000 random (source, target) pairs plus three degenerate-direction cases -> det in [0.9999999999999991, 1.0000000000000009]. So **`fit` never
mirrors**; a negative determinant is **not** the cause. Not checked: `proportional_fit` (line 575) uses the same `_aim_rotation`, and the glTF->native axis swap
in `source_mesh`/`load_donor` (not traced).

### Reading
- Winding and stored normals agree (1.000) in slot 0, so if the body is inside-out both are: the inversion entered with the donor's faces + normals (or with the
  glTF->RE4 handedness conversion), not with the fit's linear map. A winding-vs-normal consistency check cannot catch it; the signed-volume / centroid test does
  (slot 0 trips both: >50% inward and negative volume).
- Not determined: whether the *source* donor (glTF) was already inward (needs `library_donor(...)['faces']` vs `['vertices'][i]['normal']`, signed volume, for the
  donor named in the cast table of build `ae6e9f3c63d24ba1`), and which of the 19 pool donors sits in pl0d. That separates donor-inherited from conversion-introduced.
- Not determined: head seat (joint height / neck length) - needs the donor `joints` from `library_donor`.
- Still excluded by the ticket rules: live-frame QA, renders, the code change (`winding`/`head_seat` in `FIT_GATE`/`fit_report`: flip part triangle order when
  signed volume < 0 or >50% inward).

## Milestone 3 (measured 2026-11-10 evening): source donor, all five cast donors
Method: throwaway script (outside system/gbox, `$TMPDIR/all.py`) run from `system/` with the repo's `gbox.re4_switch_models.library_donor(lib, slug, roles=...)`
on `gbox-cache/characters`; cast table = `scratch/re4-fit-v2/out-v4/cast/receipt.json` (`slots.<name>.donor`, `.fit.head`). Columns: `signed vol` = sum(a.(b x c))/6 over the donor's
own faces (positive = outward winding); `geom_out` = share of faces whose geometric normal points away from the vertex centroid; `stored_inward` = share of vertices whose
stored normal points toward the centroid; head/shoulder heights = donor joint y minus hip joint y (donor units).

| slot | donor slug | tris | signed vol | geom_out | stored_inward | head-hip | shoulder-hip | fit head scale / donor_rise / native_rise |
|---|---|---|---|---|---|---|---|---|
| leon | auf_thug_alpine_inside_paint_84c082d37209 | 1629 | +1.55e4 | 0.68 | 0.33 | 31 | 22 | 20.08 / 10.16 / 187.0 |
| hunk | jgr_char05_bd43233f27d78508 | 732 | +222 | 0.69 | 0.33 | 6 | 5 | 103.3 / 2.59 / 204.5 |
| krauser | sc_voldo | 3699 | +0.114 | 0.66 | 0.34 | 1 | 0 | 942.8 / 0.200 / 191.6 |
| **wesker** | **ff7_earith (Aerith)** | 1095 | **-1.47e7** | **0.39** | **0.61** | 306 | 172 | 0.881 (capped: size) / 26.14 / 198.4 |
| ada | djv_ps2_redman | 2044 | +0.186 | 0.68 | 0.29 | 1 | 1 | 974.3 / 0.227 / 186.2 |

### Findings (settled by the above)
1. **The inversion is donor-inherited, not introduced by the fit or the format conversion.** Wesker's donor mesh is already inside-out in `ff7_earith.gltf` itself:
   read straight from the glTF accessors (indices/POSITION/NORMAL, no `source_mesh`): the main primitive has 1090 tris, signed volume -1.51e7, geom_out 0.384, stored
   normals inward 0.610, winding agrees with stored normals 0.994 (so the file's normals were authored/exported consistently with an inverted winding). All 33 glTF node world matrices
   have det > 0 (0 negative; mesh node 32 det 1.0), so no mirrored node transform. This matches the fitted slot-0 numbers (0.61 inward, 0.39 outward, same 1095 faces).
2. The other four cast donors are outward (signed vol > 0, geom_out 0.66-0.69). Only Wesker's needs the flip; a signed-volume < 0 test trips on exactly one of five.
   (The stored_inward ~0.33 of the good donors is the centroid test's own noise on non-convex bodies; it is below 50%, so the ">50% inward" rule separates them, but signed volume separates them far more widely.)
3. Wesker's donor head is **not** sunk in the source: head joint 306 above hip vs shoulders 172, head top 48 above the head joint. The sunk look arises in the fit: head scale 0.881
   (capped by `size`) on a donor head rise of 26.14 gives ~23 above the head joint against the native 198.4 - roughly 12% of the native head rise - i.e. the head shrinks onto the shoulders while the body
   is scaled to native unit. Not determined: the visual cause between "head too small" and "neck too short" - needs the fitted joint/neck lengths and a render (excluded here).
4. The scale/rise columns for leon/hunk/krauser/ada (head scale 20-974 on rises 0.2-10 units) show these donors' units differ by orders of magnitude; those scales are not an error in themselves
   but a head-seat check must be done in fitted (native) units, not donor units.

### Next
Code (excluded by this ticket's read-only rule; to be a separate ticket): in `FIT_GATE`/`fit_report`, per part, reverse triangle order (and keep normals) when signed volume < 0 (fallback: >50% inward);
head-seat check in fitted units (head-joint height above shoulder line, neck length vs native). Test the flip on `ff7_earith` first.
