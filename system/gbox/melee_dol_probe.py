"""Bounded main.dol probe for Melee (GALE01): locates the fighter file-name table, per-fighter costume triples
{Pl<code><Costume>.dat, <X>_Share_joint, <X>_Share_matanim_joint} and the AJ (animation) file pointer table by
following big-endian PPC pointers into the DOL's string data. Pure bytes in, no disc access; hypotheses labelled."""
from __future__ import annotations

import re
import struct
import sys

FILE_RE = re.compile(rb"^Pl([A-Z][a-z])([A-Za-z]{2})?\.dat$")
AJ_RE = re.compile(rb"^Pl([A-Z][a-z])AJ\.dat$", re.I)


class Dol:
    def __init__(self, data: bytes):
        if len(data) < 0x100:
            raise ValueError("short DOL header")
        self.data = data
        self.text = struct.unpack(">18I", data[0:72])
        self.addr = struct.unpack(">18I", data[72:144])
        self.size = struct.unpack(">18I", data[144:216])
        self.entry = struct.unpack(">I", data[0xE0:0xE4])[0]
        for i in range(18):
            if self.size[i] and self.text[i] + self.size[i] > len(data):
                raise ValueError(f"section {i} exceeds file")

    def v2o(self, v: int):
        for i in range(18):
            if self.size[i] and self.addr[i] <= v < self.addr[i] + self.size[i]:
                return self.text[i] + v - self.addr[i]
        return None

    def word(self, v: int):
        o = self.v2o(v)
        return struct.unpack(">I", self.data[o:o + 4])[0] if o is not None and o + 4 <= len(self.data) else None

    def cstr(self, v: int, limit: int = 96):
        o = self.v2o(v) if v else None
        if o is None:
            return None
        e = self.data.find(b"\0", o, o + limit)
        if e <= o:
            return None
        s = self.data[o:e]
        return s if all(32 <= c < 127 for c in s) else None

    def data_words(self):
        """Yield (vaddr, word) for 4-aligned words in data sections (index>=7)."""
        for i in range(7, 18):
            for k in range(0, self.size[i] - 3, 4):
                yield self.addr[i] + k, struct.unpack(">I", self.data[self.text[i] + k:self.text[i] + k + 4])[0]


def probe(dol_bytes: bytes) -> dict:
    d = Dol(dol_bytes)
    fighters, costumes, aj = {}, {}, {}
    for va, w in d.data_words():
        s = d.cstr(w) if 0x80000000 <= w < 0x81800000 else None
        if not s:
            continue
        m = FILE_RE.match(s)
        if m and not m.group(2):  # base file; next word must be the ftData symbol
            n = d.word(va + 4)
            sym = d.cstr(n) if n else None
            if sym and sym.startswith(b"ftData"):
                fighters[m.group(1).decode()] = {"table_va": hex(va), "file": s.decode(), "symbol": sym.decode(),
                                                 "file_va": hex(w)}
        elif m and m.group(2) and m.group(2) != b"AJ":
            j, a = d.cstr(d.word(va + 4) or 0), d.cstr(d.word(va + 8) or 0)
            if j and j.endswith(b"_Share_joint") and (a is None or a.endswith(b"_matanim_joint")):
                costumes.setdefault(m.group(1).decode(), []).append(
                    {"va": hex(va), "file": s.decode(), "joint": j.decode(), "matanim": a.decode() if a else None})
        elif AJ_RE.match(s):
            aj.setdefault(AJ_RE.match(s).group(1).decode(), []).append({"va": hex(va), "file": s.decode()})
    return {"entry": hex(d.entry), "fighters": fighters, "costumes": costumes, "aj": aj}


if __name__ == "__main__":
    import json
    print(json.dumps(probe(open(sys.argv[1], "rb").read()), indent=1))
