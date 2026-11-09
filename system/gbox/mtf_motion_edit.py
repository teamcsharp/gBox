"""Bounded LMT v67 translation authoring for an explicitly retargeted root.

Only measured reference/quantized XYZ track layouts are written. Positive Y
scaling changes pose height and vertical gait; it does not preserve vertical
velocity. Key data, timing, rotations, X/Z, and virtual root255 are untouched.
"""
from __future__ import annotations

from bisect import bisect_left
import hashlib
import math
import struct

from . import mtf_motion


def scale_root_y(data: bytes, scale: float):
    """Return (LMT bytes, receipt) with animation-ID0 local translation Y scaled.

    This is paired with a corresponding root bind-height change. It cannot be
    applied to a live character independently. Unsupported target codecs and
    aliases into another track's quantization bounds fail before any write.
    """
    if isinstance(scale, bool) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('root height scale must be finite and positive')
    original = bytes(data)
    offsets = mtf_motion._offsets(original)
    tables, tracks, headers, edits = set(), {}, [], {}
    target_count = 0
    def edit(offset):
        value = struct.unpack_from('<f',original,offset)[0] * scale
        if not math.isfinite(value) or abs(value) > 3.402823466e38:
            raise ValueError('root height scaling overflows a native float')
        edits[offset] = value
    for offset in set(offsets) - {0}:
        mtf_motion._range(original,offset,96,'v67 clip header')
        start,count,frames,loop = struct.unpack_from('<QIIi',original,offset)
        if not 1 <= count <= 4096 or not 1 <= frames <= 1000000:
            raise ValueError('invalid native clip frame/track count')
        mtf_motion._range(original,start,count*48,'track table')
        headers.append((offset,offset+96))
        tables.add((start,count))
    for start,count in tables:
        for index in range(count):
            offset = start+index*48
            if offset in tracks:
                continue
            codec,usage,joint,bone,weight,size,ptr,x,y,z,w,bounds = struct.unpack_from('<4BfQQ4fQ',original,offset)
            mtf_motion._range(original,ptr,size,'track key buffer')
            if bounds:
                mtf_motion._range(original,bounds,32,'track quantization bounds')
            selected = bone == 0 and usage in (1,4)
            tracks[offset] = (selected,ptr,size,bounds)
            if not selected:
                continue
            if usage != 1 or not math.isfinite(weight) or abs(weight-1.) > 1e-5:
                raise ValueError('root authoring requires unblended local translation tracks')
            if not all(math.isfinite(v) for v in (x,y,z,w)):
                raise ValueError('root translation reference must be finite')
            if size:
                stride = {4:8,5:4}.get(codec)
                if stride is None or not ptr or not bounds or size % stride:
                    raise ValueError('root authoring supports only measured quantized vector tracks')
                values = struct.unpack_from('<8f',original,bounds)
                if not all(math.isfinite(v) for v in values):
                    raise ValueError('root quantization bounds must be finite')
                edit(bounds+4)   # Y range
                edit(bounds+20)  # Y offset
            elif codec != 1 or bounds:
                raise ValueError('root authoring supports reference-only vector3 tracks without bounds')
            edit(offset+28)
            target_count += 1
    words = sorted(edits)
    def overlaps(start,end):
        index = bisect_left(words,start-3)
        return words[index] if index < len(words) and words[index] < end else None
    if overlaps(0,8+len(offsets)*8) is not None or any(overlaps(a,b) is not None for a,b in headers):
        raise ValueError('root fields alias native clip metadata')
    for offset,(selected,ptr,size,bounds) in tracks.items():
        allowed = offset+28 if selected else None
        index = bisect_left(words,offset-3)
        if any(word != allowed for word in words[index:bisect_left(words,offset+48)]):
            raise ValueError('root fields alias another track field')
        if overlaps(ptr,ptr+size) is not None:
            raise ValueError('root fields alias key data; key bits must remain unchanged')
        if bounds:
            allowed_bounds = {bounds+4,bounds+20} if selected else set()
            index = bisect_left(words,bounds-3)
            if any(word not in allowed_bounds for word in words[index:bisect_left(words,bounds+32)]):
                raise ValueError('root quantization bounds are shared with another track')
    output = bytearray(original)
    for offset,value in edits.items():
        struct.pack_into('<f',output,offset,value)
    result = bytes(output)
    return result, {'animation_id':0,'usage':'local_translation','axis':'y','scale':float(scale),
                    'tracks':target_count,'float_fields':len(edits),'key_data_unchanged':True,
                    'xz_unchanged':True,'virtual_root255_unchanged':True,
                    'vertical_gait_scaled':True,'source_sha256':hashlib.sha256(original).hexdigest(),
                    'written_sha256':hashlib.sha256(result).hexdigest(),'live_verified':False}
