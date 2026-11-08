# MTF mesh authoring: the part table and weight envelopes, decoded

2026-11-08. This note records what was measured while turning the RE5 Switch `MOD` container from "parse and carry" into
"write a model". The short version: the 56-byte mesh records and the 144-byte envelope records are now understood and a
one-mesh model can be built and re-parsed, but the engine still refuses a restructured part table at the character load.
The proven rendering path remains an in-place geometry write, so a Sonic/Mario body has to be written through the
target's existing mesh records, not as a new one-mesh table.

## The mesh table is fully described

The published Mesh156/Mesh210 layout is the same record family; Switch version 211 uses a 56-byte record. The fields
used by the writer, checked against the model corpus:

| offset | field | width | notes |
|---|---|---|---|
| 0x00 | mesh type | u16 | `0xffff` on most meshes, `0x2010`/`0x1020` on some body meshes |
| 0x02 | vertex count | u16 | sums to the header's `vertex_count` |
| 0x05 | material index | u8 | values are material IDs in steps of 16, not always below `material_count` |
| 0x06 | level of detail | u8 | |
| 0x08 | class | u8 | `0x09` / `0x21` etc. |
| 0x09 | mesh class | u8 | |
| 0x0a | vertex stride | u8 | must agree with the FVF's documented stride |
| 0x0b | render mode | u8 | 4 on the parts measured |
| 0x0c | vertex index | u32 | start in the model vertex space |
| 0x10 | vertex offset | u32 | byte offset into the vertex buffer |
| 0x14 | vertex format | u32 | written **big-endian** |
| 0x18 | face index | u32 | start in the ushort index stream |
| 0x1c | face count | u32 | `sum(mesh.face_count) + mesh_count == header.face_count` |
| 0x20 | face offset | u32 | 0 in the models measured |
| 0x24 | bone map index | u8 | |
| 0x25 | **vertex group count** | u8 | **the field that sizes the envelope table** |
| 0x28 / 0x2a | min / max index | u16 | local vertex range |

`sum(vertex_group_count) * 144 == vertex_buffer_offset - meshes_offset - 56 * mesh_count` held on **1,421 of 1,421**
model-variant containers in RE5's archive tree. That equality is the writer's invariant: a new mesh table must be
followed by exactly one 144-byte record per declared group.

## The envelope records

Each 144-byte record is the published `WEIGHT_BOUNDING`:

```
+0x00 u32   bone index
+0x04 12 B  zero padding
+0x10 4 f   sphere (centre xyz, radius)
+0x20 4 f   min (xyz, 0)
+0x30 4 f   max (xyz, 0)
+0x40 16 f  identity matrix, translation = sphere centre
+0x80 4 f   half extents (xyz, 0)
```

`ModFile.weight_bounds()` returns these; `mtf_author.pack_weight_bound()` writes one from a point set. The coordinates
are not the model-space centimetres the vertex decoder reports, which is why reusing the original records is safer than
inventing values until the space is pinned.

## Authoring in code

`gbox/mtf_author.py`:

* `combine(ModFile)` decodes every mesh it can, keeps each vertex's dominant bone, and returns one vertex/triangle list;
* `build_one_mesh(...)` keeps the target's bones, groups, materials and bounding box, writes a one-bone vertex buffer
  (`0x18B0FAA8`, stride 20) and an envelope record per used bone;
* `replace_archive_model(...)` updates the `.arc` entry and its uncompressed-size tag.

`mt_model.rebuild_mod(..., mesh_trailer=...)` now takes the envelope table as a first-class argument, so a one-mesh
model is a normal rebuild rather than a byte splice. Tests: `tests/test_mtf_author.py` (four cases) plus the existing
container tests, 54 passed locally on 2026-11-08.

## What the engine does with it

The offline result is valid: the one-mesh model re-parses, `split_valid()` is true, the mesh's vertex count and face
count account for the buffers, and the envelope count matches the declared groups.

The live result is **not** a clean character. Two one-mesh builds on RE5 Switch (Rebecca `pl0700` and Sheva `pl0600`,
written into their own archives) booted through the menus but hung on the character load when the modified archive was
first read; the round never started. That is the same class of limit the earlier one-part collapse measured (menus, then
black), and it means the engine still requires the original part table even when the envelope table is consistent.

**Consequence:** a clean Sonic/Mario body cannot be delivered by restructured `MOD` containers on this engine. The route
that renders is the in-place one: keep every mesh record, vertex count and index buffer, and change each vertex's
position through its own mesh's vertex memory. The surface-fit prototype follows that route (Sonic's fitted surface
sampled onto the target's existing vertex positions); its live acceptance is the next measurement.

## RE6 Switch

The same `MOD` family is present under `arc/NX`, but RE6's characters are split across body, head and hand archives
(`uPl00LeonUsa.arc`, `uPl00HeadLeonUsa.arc`, ...), not one archive per character. Its MercMode selection and archive
mapping have not been measured yet. Nothing in this note is an RE6 result.
