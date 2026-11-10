"""Twilight Princess (GZ2E01, GameCube) main.dol analysis probe (analysis stage, request #2001).

Reproducible, capstone-free findings from the owned main.dol (sha256 e7f19743...60e8), found by instruction-shape
search (no Ghidra needed; same addresses to be loaded into a BE PowerPC Ghidra project when lilspark is online):

  JKRDecomp::checkCompressed  0x802dbcf8  'Y''a''z'/'y'/'0' compare chain: returns 1=Yay0(SZP) 2=Yaz0(SZS) 3=ASR 0=none
  JKRDecomp::decode           0x802db9dc  calls checkCompressed, dispatches 1 -> decodeSZP, 2 -> decodeSZS
  JKRDecomp::decodeSZP (Yay0) 0x802dba58  reads BE size@4, link@8, chunk@0xC from the 0x10 header
  JKRDecomp::decodeSZS (Yaz0) 0x802dbc14
  "/res/Object/" string       0x8037904b, 0x8039a00a, 0x8039a2a8 ... (actor archive directory prefix)
  fileSel loader              0x802587a4  mounts /res/Object/ archive via lis/addi pair at 0x802587d4..0x802587e8

Actor archives are therefore Yaz0 (or raw) RARC files under /res/Object/*.arc, read through the JKR archive
mounter; the reader path is Yaz0 -> RARC -> J3D (bmd/bck/btk/brk/bti) already validated in tp_inventory.
"""
from __future__ import annotations

import struct

DOL_TEXT_SECTIONS = 7
KNOWN = {
    "JKRDecomp::checkCompressed": 0x802DBCF8,
    "JKRDecomp::decode": 0x802DB9DC,
    "JKRDecomp::decodeSZP": 0x802DBA58,
    "JKRDecomp::decodeSZS": 0x802DBC14,
}


class Dol:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.off = struct.unpack_from(">18I", raw, 0)
        self.addr = struct.unpack_from(">18I", raw, 0x48)
        self.size = struct.unpack_from(">18I", raw, 0x90)
        self.bss_addr, self.bss_size, self.entry = struct.unpack_from(">3I", raw, 0xD8)

    def sections(self):
        return [(i, self.off[i], self.addr[i], self.size[i], i < DOL_TEXT_SECTIONS)
                for i in range(18) if self.size[i]]

    def a2o(self, a: int):
        for _, o, ad, n, _t in self.sections():
            if ad <= a < ad + n:
                return o + a - ad
        return None

    def word(self, a: int) -> int:
        return struct.unpack_from(">I", self.raw, self.a2o(a))[0]

    def cstr(self, a: int) -> bytes:
        o = self.a2o(a)
        return self.raw[o:self.raw.index(b"\0", o)]

    def insns(self):
        for _, o, ad, n, text in self.sections():
            if text:
                for k in range(0, n, 4):
                    yield ad + k, struct.unpack_from(">I", self.raw, o + k)[0]

    def find_all(self, needle: bytes):
        out, start = [], 0
        while (i := self.raw.find(needle, start)) >= 0:
            for _, o, ad, n, _t in self.sections():
                if o <= i < o + n:
                    out.append(ad + i - o)
            start = i + 1
        return out

    def bl_callers(self, target: int):
        out = []
        for a, w in self.insns():
            if w >> 26 == 18 and w & 1 and not w & 2:
                off = w & 0x03FFFFFC
                off -= 0x4000000 if off & 0x2000000 else 0
                if (a + off) & 0xFFFFFFFF == target:
                    out.append(a)
        return out

    def lis_addi_refs(self, target: int):
        """Addresses of `addi rY,rX,lo` whose rX was set by `lis rX,hi` within 64 bytes (string xrefs)."""
        hi, lo = ((target + 0x8000) >> 16) & 0xFFFF, target & 0xFFFF
        last, out = {}, []
        for a, w in self.insns():
            op = w >> 26
            if op == 15 and (w >> 16) & 31 == 0 and w & 0xFFFF == hi:
                last[(w >> 21) & 31] = a
            elif op == 14 and w & 0xFFFF == lo and (w >> 16) & 31 in last and a - last[(w >> 16) & 31] < 64:
                out.append(a)
        return out

    def find_check_compressed(self):
        """Function whose body compares byte0..3 against 'Y','a','z'/'y','0' and returns 1/2/3."""
        words = dict(self.insns())
        hits = []
        for a, w in words.items():
            if w >> 26 == 11 and w & 0xFFFF == 0x59:        # cmpwi rX,'Y'
                vals = {words.get(a + 4 * k, 0) & 0xFFFF for k in range(0, 14)
                        if words.get(a + 4 * k, 0) >> 26 == 11}
                if {0x61, 0x30, 0x79, 0x7A} <= vals:
                    hits.append(a - 4)                       # preceded by lbz r4,0(r3)
        return hits


def probe(dol_bytes: bytes) -> dict:
    d = Dol(dol_bytes)
    cc = KNOWN["JKRDecomp::checkCompressed"]
    callers = d.bl_callers(cc)
    dec = KNOWN["JKRDecomp::decode"]
    return {
        "entry": d.entry,
        "sections": [(i, hex(a), hex(n), t) for i, _o, a, n, t in d.sections()],
        "check_compressed_found": d.find_check_compressed(),
        "check_compressed_callers": callers,
        "decode_calls_szp": KNOWN["JKRDecomp::decodeSZP"] in [a + (d.word(a) & 0x03FFFFFC) for a in d.bl_callers(KNOWN["JKRDecomp::decodeSZP"])] or bool(d.bl_callers(KNOWN["JKRDecomp::decodeSZP"])),
        "decode_dispatch_to_szs": bool(d.bl_callers(KNOWN["JKRDecomp::decodeSZS"])),
        "res_object_strings": d.find_all(b"/res/Object/\0"),
        "fileSel_xref": d.lis_addi_refs(0x8039A2A8),
    }
