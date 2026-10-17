"""Verified PSO DC US v2 critical-hit patch in the native encrypted executable.

Format reference: newserv DCSerialNumbers.cc, revision
ce2273a8e48c5c6fec9e21d85c490028498d8682 (MIT). Uses gBox's PRS and PSOV2 codecs.
This writer accepts the hash-identified retail files only; no RAM-offset guessing.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from .psotext import PSOV2Cipher
from .formats.lz import prs_compress

FILES = ('DP_ADDRESS.JPN', 'KATSUO.SEA', 'IWASHI.SEA')
SHA256 = dict(zip(FILES, (
    'cd684f304b71ff746b2de2f3eefed0e73ba1df9d63cee1347d9575321515d952',
    '62f1d5552206bd59d958eb5364a5d57cd6d9139f0e1fd50ac4a14d1d53982f5f',
    '88c30eccdbf69ef4e35c8980b51ec5be13a0a95de54e4a5fdab28afee573d25d')))
RAW_SHA256 = 'c3f17d16215da4fe568b1ebcfbea556b9fe909b71059f3985cd19b37b92f5884'
PATCH_OFFSET = 0x37BC0
MAX_EXECUTABLE = 8 << 20


def _pointer(data, slot, base):
    if slot + 4 > len(data):
        raise ValueError('Truncated PSO executable fixup table')
    offset = struct.unpack_from('<I', data, slot)[0] - base
    if not 0 <= offset < len(data):
        raise ValueError('PSO executable fixup pointer is outside its table')
    return offset


def _unpack(data, expected):
    """Strict PRS decoding with a declared output limit and a required terminator."""
    out = bytearray(); pos = bits = control = 0
    def byte():
        nonlocal pos
        if pos >= len(data): raise ValueError('Truncated PSO PRS stream')
        value = data[pos]; pos += 1
        return value
    def bit():
        nonlocal bits, control
        if not bits: control = byte(); bits = 8
        value = control & 1; control >>= 1; bits -= 1
        return value
    while True:
        if bit():
            if len(out) >= expected: raise ValueError('PSO PRS exceeds declared executable size')
            out.append(byte()); continue
        if bit():
            word = byte() | byte() << 8
            distance = (word >> 3) - 8192
            if distance == -8192: break
            length = (word & 7) + 2 if word & 7 else byte() + 1
        else:
            length = ((bit() << 1) | bit()) + 2
            distance = byte() - 256
        if len(out) + length > expected or len(out) + distance < 0:
            raise ValueError('Invalid PSO PRS backreference or output extent')
        for _ in range(length): out.append(out[len(out) + distance])
    if len(out) != expected: raise ValueError('PSO executable decoded size mismatch')
    return bytes(out)


def _compressed(executable, indexes, values):
    if not 8 <= len(executable) <= MAX_EXECUTABLE:
        raise ValueError('Invalid PSO packed executable size')
    size, seed = struct.unpack_from('<II', executable)
    if not 0 < size <= MAX_EXECUTABLE: raise ValueError('Invalid PSO executable output size')
    packed = bytearray(PSOV2Cipher(seed).crypt(executable[8:]))
    index = _pointer(indexes, 0x3BFC, 0x8C008400)
    value = _pointer(values, 0x3FFC, 0x8C004000)
    offset = 0
    while True:
        if index >= len(indexes): raise ValueError('Unterminated PSO fixup table')
        step = indexes[index]
        if not step: break
        offset += step * 4
        if index + 2 > len(indexes) or value + 4 > len(values) or offset + 4 > len(packed):
            raise ValueError('PSO fixup exceeds its executable or value table')
        packed[offset:offset+4] = values[value:value+4]
        index += 2; value += 4
    return bytes(packed), size


def decode(executable, indexes, values):
    packed, size = _compressed(executable, indexes, values)
    return _unpack(packed, size)


def _rewrite(packed, target):
    """Preserve the retail PRS references; replace only references invalidated by the edit.

    A fresh generic compressor can exceed the tightly packed native disc extent.
    Retaining the game's own parse keeps this two-byte edit within its sector budget.
    Every retained reference is checked against the requested output, including overlap.
    """
    pos = bits = control = offset = 0
    out = bytearray(); slot = used = 0
    def read():
        nonlocal pos
        if pos >= len(packed): raise ValueError('Truncated retail PRS stream')
        value=packed[pos];pos+=1;return value
    def bit():
        nonlocal bits,control
        if not bits: control=read();bits=8
        value=control&1;control>>=1;bits-=1;return value
    def put(value):
        nonlocal slot,used
        if not used: slot=len(out);out.append(0)
        out[slot] |= value << used;used=(used+1)%8
    while True:
        if bit():
            read()
            if offset >= len(target): raise ValueError('Retail PRS output exceeds target')
            put(1);out.append(target[offset]);offset+=1;continue
        long=bit()
        if long:
            a=read();b=read();word=a|(b<<8);distance=(word>>3)-8192
            if distance == -8192:
                put(0);put(1);out.extend((0,0));break
            extra=None if word&7 else read();length=(word&7)+2 if word&7 else extra+1
        else:
            hi=bit();lo=bit();a=read();length=(hi<<1|lo)+2;distance=a-256
        if offset+length>len(target) or offset+distance<0: raise ValueError('Invalid retail PRS reference')
        if all(target[offset+i]==target[offset+distance+i] for i in range(length)):
            put(0);put(long)
            if long:
                out.extend((a,b))
                if extra is not None: out.append(extra)
            else: put(hi);put(lo);out.append(a)
        else:
            for value in target[offset:offset+length]: put(1);out.append(value)
        offset+=length
    if offset != len(target): raise ValueError('Retail PRS target size mismatch')
    result=bytes(out)
    if _unpack(result,len(target)) != target: raise ValueError('Retail PRS rewrite failed readback')
    return result


def encode(raw, indexes, seed):
    if not 0 < len(raw) <= MAX_EXECUTABLE: raise ValueError('Invalid PSO executable size')
    packed = prs_compress(raw)
    encoded = struct.pack('<II', len(raw), seed) + PSOV2Cipher(seed).crypt(packed)[:len(packed)]
    updated = bytearray(indexes)
    updated[_pointer(indexes, 0x3BFC, 0x8C008400)] = 0  # new stream has no obscured words
    return encoded, bytes(updated)


def prepare(disc):
    source = {name: disc.read(name) for name in FILES}
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in source.items()}
    if hashes != SHA256:
        raise ValueError('PSO ROM patch requires the verified US v2 retail executable and fixup tables; this disc differs')
    raw = decode(source[FILES[0]], source[FILES[1]], source[FILES[2]])
    if hashlib.sha256(raw).hexdigest() != RAW_SHA256 or raw[PATCH_OFFSET:PATCH_OFFSET+2] != bytes.fromhex('1a89'):
        raise ValueError('PSO US v2 executable or critical-hit instruction does not match')
    modified = bytearray(raw); modified[PATCH_OFFSET:PATCH_OFFSET+2] = bytes.fromhex('0900')
    packed, _ = _compressed(source[FILES[0]], source[FILES[1]], source[FILES[2]])
    repacked = _rewrite(packed, bytes(modified))
    seed = struct.unpack_from('<I',source[FILES[0]],4)[0]
    encoded = struct.pack('<II',len(modified),seed)+PSOV2Cipher(seed).crypt(repacked)[:len(repacked)]
    indexes = bytearray(source[FILES[1]])
    indexes[_pointer(indexes,0x3BFC,0x8C008400)] = 0
    indexes = bytes(indexes)
    if decode(encoded, indexes, source[FILES[2]]) != modified:
        raise ValueError('PSO executable encode/decode verification failed')
    return {FILES[0]: encoded, FILES[1]: indexes}, {
        'patch': 'crit_always', 'address': '0x8C047BC0', 'executable_offset': PATCH_OFFSET,
        'before': '1a89', 'after': '0900', 'changed_executable_bytes': 2,
        'source_sha256': hashes, 'decoded_source_sha256': RAW_SHA256,
        'decoded_target_sha256': hashlib.sha256(modified).hexdigest(),
        'codec_roundtrip_verified': True, 'gameplay_verified': False,
    }


def export(cfg, game, rom, name, progress=None):
    """Publish a complete GDI set and per-native-file BPS patches; never overwrite an export."""
    import json, tempfile, time
    from . import gdrom, romexport, filemods
    progress = progress or (lambda *_: None)
    filemods.mod_dir(cfg, game['game_id'], 'pso_critical')  # validate the catalog path component
    if Path(rom).suffix.lower() == '.gdi': gdi = Path(rom)
    else:
        from .chd import write_gdi
        cache = Path(cfg.cache) / 'dc' / game['game_id'] / 'disc.gdi'
        if cache.is_file(): gdi = cache
        else:
            cache.parent.mkdir(parents=True, exist_ok=True)
            gdi = write_gdi(rom, cache.parent)
    disc = gdrom.GDRom(gdi)
    try:
        progress(10, 'Verifying and decoding PSO US v2 executable')
        changes, proof = prepare(disc)
        source = {key: disc.read(key) for key in changes}
    finally:
        for f in disc._fh.values(): f.close()
    parent = romexport.exports_root(cfg) / game['game_id']; parent.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='pso_critical_', dir=parent))
    progress(50, 'Writing PSO executable and fixup table to a new GDI set')
    image = gdrom.patch_gdi(gdi, out, 'pso_critical', changes)
    verified = gdrom.GDRom(image)
    try:
        for key,data in changes.items():
            if verified.read(key) != data: raise ValueError('PSO disc readback failed: '+key)
        decoded = decode(*(verified.read(key) for key in FILES))
        if hashlib.sha256(decoded).hexdigest() != proof['decoded_target_sha256']:
            raise ValueError('PSO rebuilt disc executable verification failed')
    finally:
        for f in verified._fh.values(): f.close()
    patches=[]
    with tempfile.TemporaryDirectory(prefix='pso-patches-') as scratch:
        for key,data in changes.items():
            before=Path(scratch)/'before';after=Path(scratch)/'after';before.write_bytes(source[key]);after.write_bytes(data)
            target=out/(key+'.bps');entry=romexport.make_bps(before,after,target)
            if romexport.apply_bps(source[key],target.read_bytes()) != data: raise ValueError('PSO patch round trip failed')
            patches.append(entry|{'apply_to':key,'verified':True})
    proof['disc_readback_verified']=True
    (out/'verification.json').write_text(json.dumps(proof,indent=2))
    result={'name':out.name,'title':name or 'Every attack is a critical hit','game_id':game['game_id'],
            'game':game.get('title'),'platform':'dreamcast','dir':str(out),'rel_dir':f"exports/{game['game_id']}/{out.name}",
            'built':time.time(),'image':image.name,'patches':patches,'cheat_files':[],
            'steps':[{'step':'PSO native executable patch',**proof}], 'components':[{'kind':'pso_code_patch','patch':'crit_always'}],
            'verification':proof,'note':'Download the GDI and every referenced track together. Gameplay validation is separate.'}
    return romexport._finish(result,out)
