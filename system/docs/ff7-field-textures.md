# FF7 field face detail

The field writer previously sampled donor textures only at triangle corners and emitted Gouraud colours. Texture interiors such as Mario's eyes, moustache and cap emblem disappeared. Decimation could also delete the small textured surfaces beneath the cap.

Writer version 4 keeps those surfaces out of the field decimation pass and emits native textured triangles. It uses Cloud's two existing 32x32 face banks and one 15-colour palette in FIELD.TDB. Up to eight 16x16 cells fit; spare cells widen maps with greater colour variation. Original UVs keep their proportions on the mesh. The fixed PS1 allocation still reduces source-map detail.

Only Cloud's exclusive image indices 0 and 5 and palette 0 change. The FIELD.BIN overlay's Cloud expression selection rows point at these static maps so blink/mouth updates cannot replace them with stock textures. Skeletal animations remain unchanged; this does not preserve animated blinking or mouth-expression textures. Unknown expression layouts and shared image allocations are refused.

Exact byte-cost LZSS parsing, including flag-byte overhead, makes the texture database fit its original compressed allocation. Gzip/LZS tails are cleared across the full original file size. Model size, per-part indices, texture coordinates and GPU packet memory remain bounded. Native readback previews retain UVs and show the encoded mesh rather than the larger pre-decimation fit. The battle writer also emits neutral 0x80 texture brightness instead of zero modulation.

Verification used the owned USA Disc 1 and Mario donor. The new field contains 332 triangles, including all 50 donor textured triangles; BCX is 7,050/7,072 bytes and GPU packets use 9,876/11,764 bytes. FIELD.TDB's encoded stream is 13,619/13,631 bytes. Readback preserves field skeleton/animations, 16 weapons and 111 other battle sections; only eight Cloud expression-selection bytes change in the decompressed field module. No other face's images or palette are overwritten.

Real i9-NUC gameplay checks cover the opening station: front/side/rear walking views, transition into the first battle and a normal attack. Mario's face, sideburns and emblem are visible and the reported cap opening was absent in these views. These checks do not certify later/special-scene models, every animation, prerecorded movies or an entire replacement cast. Original builds remain available under their existing names.

Native packet and face-bank references: [field renderer and texture loader](https://github.com/Akari1982/q-gears_reverse/blob/master/ffvii/DISC/FIELD/FIELD.BIN_model_render.cpp). The addresses in the writer refer to the USA field overlay at 0x800a0000.
