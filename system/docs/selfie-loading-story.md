# Selfie construction snapshots during launch

Launching a build with an approved photo character shows its source selfie beside
face close-ups. The loading band cycles through the close-ups, and the main card
wipes between stages while the original UV texture slides away to reveal the photo
texture. Reduced motion shows the final snapshot without the transitions.

## What the snapshots mean

The current photo-skin pipeline projects the approved photograph onto existing UV
maps. It does not reconstruct or deform the head. The card therefore says
**Photo texture projection · mesh shape unchanged**.

`gbox/photo_story.py` renders five presentation snapshots at 0%, 25%, 50%, 75%, and
100% of the approved texture blend, using the actual source mesh, UVs, textures,
and a shared face camera. Intermediate images illustrate the blend; they are not
captures of a native game, a recorded geometry morph, or separate build results.
The source photo and both texture endpoints are retained with the accepted variant.
No source mesh, approved candidate, ROM, or save is changed by snapshot generation.

If a later pipeline supplies actual `geometry_snapshot` artifacts and marks the
story geometry as `deformed`, the viewer can show those recorded stages. It never
invents a face deformation from a selfie. An older approval without snapshots
falls back to a labelled comparison of its original and approved texture maps.

## Data and limits

`photo_skin_approval.story` contains a schema number, geometry status, source-photo
artifact digest, and ordered frames with `kind`, `label`, `fraction`, and `sha256`.
The client accepts SHA256 artifact references only and uses the existing
authenticated artifact route. It reads at most two photo-character approvals per
launch, with at most sixteen frames and four texture pairs per character. Photo
lookups share the existing 1.5-second launch-metadata deadline; they do not add
another waiting period or polling loop. Closing the loader discards stale results.

Automatic rendering is optional and limited to four selected maps, 50,000 source
triangles, 320-pixel images, and three million raster samples. Unsupported or
oversized meshes keep the normal texture approval and loading fallback.

## Activation and verification

The web client needs a reload to use the new slideshow. Automatic recording for
new photo approvals requires the backend to load the updated `photo_skin` module.
Existing approvals can receive story artifacts independently, preserving their
approved model and source checksums. Bla on Leon (`leon_photo_37b3a87d8e6f`) has
five snapshots from its approved model and texture maps; these are presentation
previews and still require gameplay verification of the native build.

Focused verification:

```text
python -m pytest tests/test_photo_story.py tests/test_photo_skin.py tests/test_selfie_models.py -q
node --test tests/test_launch_mods.cjs tests/test_selfie_loading.cjs tests/test_selfie_loading_ui.cjs
```

Tests cover texture endpoints and intermediate pixels on real triangle geometry,
unchanged vertex positions, approval persistence, invalid or excessive input,
metadata timeout and late-response disposal, and Chromium rendering of the photo,
face stages, texture animations, reduced-motion final stage, and loader cleanup.
