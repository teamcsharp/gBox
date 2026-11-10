# DOA2 arcade (doa2m.zip) mpr-22110.ic11 scan validation

Source: /mnt/gbox/hyperspin/Arcade/collections/Mame/roms/doa2m.zip (read-only), member `mpr-22110.ic11`, 8388608 bytes, sha256 `73e2ce1b43ce4106db2925cbe889a91b565a39bc2c4f15e6c4fcc30d138bca1c`.

`naomilib.scan` (strict: declared vertex count == decoded, end marker, in-range refs): **1793 models, 195663 triangles**, span [480, 8387576], 150 distinct texture ids. Triangle histogram (bucket->count): {'0': 1736, '1000': 5, '3000': 6, '500': 42, '1500': 1, '2500': 1, '2000': 1, '5000': 1}.

Top models by triangles (offset, verts, tris, meshes):

- 0x276998: 10508 verts, 8162 tris, 19 meshes, radius 0.59
- 0x15150: 4090 verts, 3222 tris, 14 meshes, radius 0.23
- 0x658f8: 4078 verts, 3222 tris, 14 meshes, radius 0.23
- 0xb44b0: 4082 verts, 3222 tris, 14 meshes, radius 0.23
- 0x104a08: 3986 verts, 3096 tris, 17 meshes, radius 0.19
- 0x14a1c8: 3986 verts, 3096 tris, 17 meshes, radius 0.19
- 0x20f8c8: 3880 verts, 3058 tris, 16 meshes, radius 0.18
- 0x1cf7b8: 3581 verts, 2833 tris, 11 meshes, radius 0.15
- 0x24c438: 2828 verts, 2216 tris, 10 meshes, radius 0.22
- 0x18beb8: 2355 verts, 1779 tris, 14 meshes, radius 0.3

Hypotheses (unproved): the ~3.0-3.2k-tri, 13-17-mesh models at regular stride (0x15150, 0x65b78, 0xb4630, 0x104888, 0x14a248) are fighter body candidates; 0x276518 (8162 tris, 19 meshes, bbox ~0.6x1.0x0.5) is a larger object. No roster/texture mapping yet. Next: DMA loader FUN_8c1da924 via one decomp_pipeline prepare to map chip bases.
