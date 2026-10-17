# RE5 Gold PS3 bounded native writer

`gbox.re5ps3_write` writes a new Chris/Sheva ARC containing one edited native
resource. The original pack must match the exact owned BLUS30491 normal-player
fingerprint. It verifies the modified resource and **every unrelated resource**
before creating an exclusive output file. Original game files and saves are not
written, and no emulator is launched.

This is a fixed-layout asset writer, not the complete Sonic/Mario cast writer.
It is deliberately absent from `char_coverage.WRITERS`: that interface promises
cast-replacement slots and needs arbitrary donor geometry and verified fitting.

## Model edits

Export with `gbox.re5ps3_models` first. `--geometry-glb` accepts that GLB with
edited positions, normals, UVs, numeric joint assignments and weights. Native
mesh-index extras, primitive topology/order, skeleton hierarchy, bind matrices
and joint order must remain intact. It accepts LOD masks 1, 2 and 4, but edits
only the explicitly selected native mesh records. Unselected native mesh
payloads stay byte-identical. A mesh whose native mask includes several LODs
is shared: editing it affects every included LOD. Receipts record each changed
mesh's native mask and all affected LOD views. The owned Chris pack has 69
mesh records with mask 255; Sheva has one.

```sh
python -m gbox.re5ps3_write OWNED_CHRIS.arc \
  --member 'pawn\pl\pl00\model\pl0000' \
  --expected-sha256 51df8884b6a114101356e19fcc608b69c196e7c0cd56c626a3f7660aeb99d867 \
  --geometry-glb EDITED_CHRIS.glb --out NEW_CHRIS.arc
```

The GLB must identify the source MOD SHA-256. External buffers, sparse or
strided accessors, changed indices, missing primitives, changed rig transforms,
animations and morph targets are rejected. A general Blender export that
reorders vertices or removes native primitive metadata is not accepted. The
low-level `patch_model` API also accepts arrays keyed by native mesh index;
positions there use the game's centimetres, while the GLB route uses metres.

The native writer changes only verified vertex fields. Positions retain the
original signed-16-bit quantization bounds, UVs retain big-endian half floats,
and normals retain the native three-byte encoding. Weights are normalized to
an exact byte sum of 255 with deterministic largest-remainder allocation. Joint
assignments must be expressible through that mesh's original palette/fallback
map and remain within its declared influence count. Unchanged decoded values
preserve the original bytes, including accepted native weight sums 253–257.
Models with overlapping native vertex spans are rejected, including aliases
between selected and unselected meshes. The two owned targets have no such
overlaps.

Topology, skeleton, animation maps, palettes, material flags, tangents, culling
metadata and unknown records are preserved. Large deformations may need new
bounds/tangents or other engine metadata: they have not been proven by this
writer. Numeric bone IDs remain numerical identities; they do not establish
semantic roles or motion compatibility.

## Texture edits

`--texture-png` replaces an exact TEX resource with a PNG of the same native
dimensions. It retains TEX 102 header fields, layout, mip offsets, gaps and
trailing bytes; all existing mip payloads are regenerated as their original
DXT1/DXT5 format. Native DXT blocks are little endian on this PS3 build.

```sh
python -m gbox.re5ps3_write OWNED_CHRIS.arc \
  --member EXACT_NATIVE_TEX_RESOURCE \
  --expected-sha256 51df8884b6a114101356e19fcc608b69c196e7c0cd56c626a3f7660aeb99d867 \
  --texture-png EDITED_TEXTURE.png --out NEW_CHRIS_TEXTURE.arc
```

The DDS encoder's payload is checked for exact format and block extent before
being inserted. Every mip is decoded again, and compression error is recorded.
DXT1 input must have binary alpha; if the codec cannot preserve its cutout mask,
writing fails explicitly. A texture identical to the decoded original is an
exact no-op, preserving the original compressed bytes and lower mips.

Pillow 11.2.1 or newer supplies compressed DDS writing; the project dependency
now requires that minimum. See the [primary Pillow DDS documentation](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#dds).
Owned proof currently uses Pillow 12.3.0. Texture compression remains lossy;
shader equivalence, normal/mask-map semantics and engine acceptance are separate.

## Verification and limits

Tests independently read native bytes and verify byte-exact no-op geometry
round trips for both owned normal player models at all three LOD masks. Changed
geometry and changed texture proofs rebuild copied ARCs, decode the result and
verify every untouched resource. Synthetic known-color mip blocks test exact
layout and preserved unknown bytes. Invalid geometry, identity, dimensions,
non-finite values and unsupported edits create no output artifact.

The first API/CLI handles **one native resource per output pack**, from the
original exact-build pack. Combining multiple changed resources, arbitrary
Sonic/Mario donor topology, semantic retargeting roles, rebuilt bounds/tangents,
animation acceptance, full cast discovery, an installable modified game,
unlocks and live sidebar inventory/equipment remain separate work. No gameplay
or full-cast completion is claimed.
