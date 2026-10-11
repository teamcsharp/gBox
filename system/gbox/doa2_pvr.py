"""Opt-in DOA2 native material header builder, pending live-game validation.

Mutates only documented PCW/ISP/TSP/TCW texture/render fields and the native
texture ID. It retains the NaomiLib shader, 32-byte vertex representation,
lighting floats and geometry length. See KallistiOS dc/pvr/pvr_header.h.
"""
from __future__ import annotations

import math
import struct


def build_header(template: bytes, tex, *, alpha: str = 'opaque', validated_opt_in: bool = False) -> bytes:
    """Create a descriptor-compatible header without resizing its allocation.

    The caller must explicitly opt in while this path is being validated.
    ``template`` must be a genuine DOA Lambert/constant header whose vertex
    representation is preserved. The renderer supplies texture VRAM addresses
    through the texture ID; stored original headers use an address of zero.
    """
    if not validated_opt_in:
        raise ValueError('native header synthesis requires explicit validation opt-in')
    if len(template) != 80:
        raise ValueError('native material template must contain 80 bytes')
    pcw, isp, tsp, tcw = struct.unpack_from('<4I', template)
    shader = struct.unpack_from('<i', template, 36)[0]
    if pcw >> 29 != 4 or shader not in (0, 1):
        raise ValueError('template must be a native polygon with shader 0 or 1')
    if alpha not in ('opaque', 'binary', 'graded'):
        raise ValueError('unknown alpha class')
    if alpha == 'graded' and tex.pixel != 2:
        raise ValueError('graded alpha requires ARGB4444')
    if alpha == 'binary' and tex.pixel not in (0, 2):
        raise ValueError('binary alpha requires an ARGB native texture')
    if tex.pixel not in (0, 1, 2) or tex.format not in (1, 3, 13):
        raise ValueError('unsupported native texture representation')
    for dimension in (tex.width, tex.height):
        if not 8 <= dimension <= 1024 or dimension & (dimension - 1):
            raise ValueError('PVR texture dimensions must be powers of two from 8 to 1024')
    if tex.format == 3 and tex.width != tex.height:
        raise ValueError('rectangular native VQ encoding is not implemented')
    if tcw & 0x1ffffff:
        raise ValueError('template has a fixed VRAM texture address; dynamic texture ID cannot be assumed')
    # Keep color encoding, UV encoding, Gouraud/specular, clipping and culling.
    pcw = (pcw & ~(7 << 24)) | ((0 if alpha == 'opaque' else 2) << 24) | 8
    isp |= 1 << 25  # Texturing's second enable bit.
    # Replace UV size and texture environment; MODULATE preserves texture alpha.
    tsp = (tsp & ~0xff) | (int(math.log2(tex.width // 8)) << 3) | int(math.log2(tex.height // 8)) | (1 << 6)
    # Preserve the original game's vertex-alpha setting. Texture alpha is a
    # separate bit; the documented source/destination blend selectors control
    # whether that texture alpha contributes to final color.
    tsp &= ~((7 << 29) | (7 << 26) | (1 << 19))
    if alpha == 'opaque':
        tsp |= (1 << 29) | (1 << 19)  # ONE/ZERO, ignore texture alpha.
    else:
        tsp |= (4 << 29) | (5 << 26)  # SRCALPHA/INVSRCALPHA.
    # The native formats here are twiddled without mipmaps or stride. The CHR
    # carries system-RAM pointers, not the VRAM address the game fills at draw.
    tcw = (tex.pixel << 27) | ((tex.format == 3) << 30)
    out = bytearray(template)
    struct.pack_into('<4I', out, 0, pcw, isp, tsp, tcw)
    struct.pack_into('<i', out, 32, tex.index)
    return bytes(out)


def extend_bank(archive: dict, textures: list, existing: dict[int, list[dict]]) -> dict[int, list[dict]]:
    """Add explicit synthetic options while retaining original header options."""
    templates = [(model['id'], i, mesh['header']) for model in archive['models']
                 for i, mesh in enumerate(model['meshes'])
                 if len(mesh['header']) == 80
                 and struct.unpack_from('<i', mesh['header'],36)[0] in (0, 1)
                 and struct.unpack_from('<i', mesh['header'],32)[0] >= 0
                 and struct.unpack_from('<I', mesh['header'],12)[0] & 0x1ffffff == 0]
    if not templates:
        raise ValueError('no safe native Lambert/constant template for synthesis')
    result = {slot: list(options) for slot, options in existing.items()}
    for tex in textures:
        same_slot = [t for t in templates if struct.unpack_from('<i', t[2],32)[0] == tex.index]
        pool = same_slot or templates
        model_id, mesh_index, template = min(pool, key=lambda t: (struct.unpack_from('<i',t[2],36)[0] != 1, t[0],t[1]))
        for alpha in (('opaque','graded') if tex.pixel == 2 else ('opaque','binary') if tex.pixel == 0 else ('opaque',)):
            header = build_header(template, tex, alpha=alpha, validated_opt_in=True)
            option = {'header': header, 'model_id': model_id, 'mesh_index': mesh_index,
                      'shader': struct.unpack_from('<i',header,36)[0],
                      'list_type': 0 if alpha == 'opaque' else 2,
                      'alpha': alpha != 'opaque', 'binary_alpha': alpha != 'opaque',
                      'synthetic': True}
            if all(o['header'] != header for o in result.get(tex.index, [])):
                result.setdefault(tex.index, []).append(option)
    return result


def sampler(header, wrap=(10497,10497)):
    """Apply GLTF S/T repeat, clamp or mirror to native PVR mode2 bits."""
    if len(header)!=80 or len(wrap)!=2 or any(w not in (10497,33071,33648) for w in wrap):
        raise ValueError('Unsupported native sampler')
    result=bytearray(header)
    tsp=struct.unpack_from('<I',header,8)[0] & ~sum(1<<bit for bit in (15,16,17,18))
    for value,clamp,mirror in zip(wrap,(16,15),(18,17)):
        if value==33071:tsp|=1<<clamp
        if value==33648:tsp|=1<<mirror
    struct.pack_into('<I',result,8,tsp)
    return bytes(result)
