"""Disable original DOA2 morph/seam writes before replacing vertex layouts.

APV absence checks: owned executable FUN_8c0de204 checks section offset >=0.
SUP termination: FUN_8c0e6dc8 stops at table entry0 and emits a zero seam list.
These helpers retain file lengths and all bytes beyond the disabling headers.
Native acceptance still requires loading a patched copy through the game.
"""
from __future__ import annotations

import hashlib
import struct


def inspect_apv(data: bytes) -> dict:
    if len(data) < 4:
        raise ValueError('truncated APV section count')
    count = struct.unpack_from('<I',data)[0]
    if count not in (7,9) or len(data) < 4 + 4 * count:
        raise ValueError('expected a complete seven/nine-section DOA2 APV header')
    table_end=4+4*count
    offsets = struct.unpack_from('<'+str(count)+'i',data,4)
    present = [i for i,value in enumerate(offsets) if value >= 0]
    for i in present:
        offset = offsets[i]
        if offset < table_end or offset + 12 > len(data) or offset & 3:
            raise ValueError(f'APV section {i} lies outside its allocation')
        keys, index_start, first_frame = struct.unpack_from('<3I',data,offset)
        if keys > 4096 or index_start < 4*(keys+3) or index_start & 3 or first_frame & 3 or first_frame <= index_start:
            raise ValueError(f'APV section {i} has an invalid morph table')
        if offset + first_frame > len(data):
            raise ValueError(f'APV section {i} index table exceeds the file')
        if struct.unpack_from('<I',data,offset+first_frame-4)[0] != 0xffffffff:
            raise ValueError(f'APV section {i} vertex offset list lacks its -1 terminator')
    return {'section_count':count, 'section_offsets':list(offsets),
            'enabled_sections':present, 'file_bytes':len(data)}


def inspect_sup(data: bytes) -> dict:
    if len(data) < 4:
        raise ValueError('truncated SUP seam directory')
    first = struct.unpack_from('<I',data)[0]
    if first == 0:
        return {'seam_count':0,'seams':[],'file_bytes':len(data)}
    if first & 3 or not 8 <= first <= len(data):
        raise ValueError('SUP directory size lies outside its allocation')
    values=struct.unpack_from('<'+str(first//4)+'I',data)
    if values[-1] != 0 or any(not value for value in values[:-1]):
        raise ValueError('SUP directory must end with one zero sentinel')
    starts=values[:-1]
    if list(starts) != sorted(set(starts)) or starts[0]!=first:
        raise ValueError('SUP seam offsets are non-monotonic')
    seams=[]
    for i,start in enumerate(starts):
        limit=starts[i+1] if i+1<len(starts) else len(data)
        if start+128>limit:
            raise ValueError(f'SUP seam {i} lacks its matrix and vertex mapping header')
        pointer,bone_a,bone_b,model,initialized=struct.unpack_from('<IBBBB',data,start)
        # Tengu's original wing seams use joints17..22; DOA MOTs contain44 tracks.
        if pointer != start+8 or bone_a>=44 or bone_b>=44 or initialized not in (0,1):
            raise ValueError(f'SUP seam {i} has invalid pointer/joint fields')
        seams.append({'offset':start,'data_offset':pointer,'bone_a':bone_a,'bone_b':bone_b,
                      'model_id':model,'initialized':initialized,'bytes':limit-start})
    return {'seam_count':len(seams),'seams':seams,'file_bytes':len(data)}


def _result(before: bytes, after: bytes, kind: str, prior: dict) -> tuple[bytes,dict]:
    if len(before)!=len(after):
        raise AssertionError('supplement allocation size changed')
    return after, {'supplement':kind,'file_bytes':len(before),'before':prior,
                   'original_sha256':hashlib.sha256(before).hexdigest(),
                   'patched_sha256':hashlib.sha256(after).hexdigest(),
                   'changed_bytes':sum(a!=b for a,b in zip(before,after)),
                   'policy':'original vertex morphs disabled' if kind=='APV' else 'original seam skinning disabled'}


def disable_apv(data: bytes) -> tuple[bytes,dict]:
    """Use existing signed -1 markers for all original seven/nine slots."""
    prior=inspect_apv(data)
    count=prior['section_count']
    patched=data[:4]+struct.pack('<'+str(count)+'i',*([-1]*count))+data[4+4*count:]
    return _result(data,patched,'APV',prior)


def disable_sup(data: bytes) -> tuple[bytes,dict]:
    """An empty original seam list prevents old-offset writes into donor meshes."""
    prior=inspect_sup(data)
    return _result(data,bytes(4)+data[4:],'SUP',prior)
