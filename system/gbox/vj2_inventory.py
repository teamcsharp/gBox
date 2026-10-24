"""Viewtiful Joe 2 (GameCube, G2VE08) owned-build inventory over NKit v01 ISO.

Finding: the .nkit.iso keeps the GC header, FST (header 0x424) and contiguous file data, so gbox.gcdisc.GCDisc
reads it in place; no NKit decompression is needed for FST walks/file extraction (only junk padding is removed).
Character containers are etc/pl0N.dusgc (big-endian header words; word0 exceeds file size => likely decompressed size)."""
import hashlib
import struct

from .gcdisc import GCDisc

NKIT_MAGIC = b"NKIT v01"
CHAR_PREFIX = "etc/pl"


def sha256_stream(path, chunk=1 << 24):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while c := f.read(chunk):
            h.update(c)
    return h.hexdigest()


def inventory(path):
    d = GCDisc(path)
    d.f.seek(0x200)
    nkit = d.f.read(8) == NKIT_MAGIC
    afs = {}
    for n, (o, s) in d.files.items():
        if n.endswith(".afs"):
            if d._r(o, 4) != b"AFS\0":
                raise ValueError(f"{n}: bad AFS magic")
            cnt = struct.unpack("<I", d._r(o + 4, 4))[0]
            ents = [struct.unpack_from("<II", d._r(o + 8, cnt * 8), i * 8) for i in range(cnt)]
            if not all(a + b <= s for a, b in ents):
                raise ValueError(f"{n}: AFS entry out of range")
            afs[n] = cnt
    chars = {}
    for n, (o, s) in d.files.items():
        if n.startswith(CHAR_PREFIX) and n.endswith(".dusgc"):
            hdr = struct.unpack(">4I", d._r(o, 16))
            chars[n] = {"offset": o, "size": s, "word0": hdr[0], "sha256": hashlib.sha256(d.read(n)).hexdigest()}
    dol = d.dol()
    return {"game_id": d.game_id, "title": d.title, "nkit": nkit, "files": len(d.files), "afs": afs,
            "dol_sha256": hashlib.sha256(dol).hexdigest(), "dol_size": len(dol), "characters": chars}
