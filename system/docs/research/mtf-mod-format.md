# The MT Framework MOD format is documented - and the "split" was never missing

2026-11-06. After several rounds of blind reverse engineering, the container turned out to be publicly documented. The
structures below come from a preserved copy of the research by **mariokart64n** (2013) and **bastien** (2016), reposted
at [nexusmods: MOD format specifications from RE6](https://forums.nexusmods.com/topic/7048756-backup-mod-format-specifications-from-re6/),
which itself credits Surveyor, revelation, chrrox, Rick and shadowmoy from the XeNTaX work in 2008. Treat that page as
the source; this file records only what was **checked against our own Switch files**.

## The header, checked field by field

`uWp06.arc`'s `wp0600` geometry, as the document describes it (little endian):

| offset | field | our value | was called |
|---|---|---|---|
| 0x00 | id_magic `MOD\0` | `MOD\0` | magic |
| 0x04 | version (ubyte), version_rev | **211** (0xd3), 0 | "two packed fields" |
| 0x05 | bone_count (ushort) | 3 | |
| 0x07 | mesh_count (ushort) | **15** | |
| 0x09 | material_count (ushort) | 9 | |
| 0x0b | vertex_count (ushort) | **1567** | "vertex count" - correct |
| 0x0d | face_count (ushort) | **2317** | "index count" - it is faces |
| 0x0f | edge_count (ushort) | 1415 | |
| 0x11 | vertex_buffer_size (uint) | **25764** | "geometry bytes" - correct |
| 0x15 | vertex_buffer_2_size | 0 | |
| 0x19 | group_count (uint) | **2** | "submesh count" - it is **bone groups** |
| 0x1d | (reserved) | 0 | |
| 0x28 | groups_offset | 164 | block 0 |
| 0x30 | materials_offset | 876 | block 1 |
| 0x38 | meshes_offset | 940 | block 2 |
| 0x40 | vertex_buffer_offset | 2092 | block 4 |
| 0x48 | index_buffer_offset | 5092 | block 5 |
| 0x58 | file_size | 35492 (+4) = 35496 | last block |

Version 211 stores the offsets as **u64** (a low dword every 8 bytes), where the 2013 document describes u32 for version
156 - that is the only layout difference found so far, and it is why the earlier probes kept reading offsets with the
wrong stride.

## What this corrects

* the count we called "submeshes" is the **group count** (bone groups), not meshes - which is why no per-submesh table
  could be found: the per-part data is in the **mesh table**;
* the count we called "index count" is **face_count**; the index buffer is `ushort[face_count]` (our 4636 bytes vs
  2 x 2317 = 4634, plus padding);
* the block we called "block 2" is the **mesh table** (`meshes_offset`), and `block 3` was the **material** table - the
  128-byte strings are the material/texture names, not mesh names.

## The mesh record - where the split actually lives

The document's `Mesh210` / `Mesh156` give each mesh its own:

```
vertex_count, face_count, vertex_stride, vertex_format, level_of_detail,
vertex_offset, face_offset, material_index, group_index, bone_map_index, vertex_group_count
```

So per-part geometry is described **once per mesh**, and a model's parts are those mesh records - which is exactly what
the writer needs. For version 211 the record size is larger than the documented 156/210 layouts (the 15 meshes occupy
more than 15 x 48 bytes), so the next step is to measure the record size from `meshes_offset` to the next offset and
decode the fields against the document rather than by guessing.

## Why this matters for the objective

The writer's plan changes from "reverse engineer the geometry" to "implement a documented layout":

1. parse the header (done) and the mesh table into records;
2. validate: the sum of the meshes' vertex counts equals `vertex_count`, their strides land on 16/20/24/28/32, and their
   offsets stay inside the vertex buffer;
3. then a fitted GLB can be written as: bone table (bind pose + parents from the document's `Bone`), mesh records with
   strides, vertex buffer, index buffer - the same step the GameCube writer (`gbox/re4gc_models.py`) already does for
   RE4 GC, which is why that pipeline was always the closer one.

Until step 2 passes, nothing is written into a game.
