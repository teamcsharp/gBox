"""Resident Evil 4 PS2 (SLUS-21134 v1.01, #1321): executable symbol map and the model/texture formats the loader uses.

Everything here is pinned to code in the owned boot ELF (sha256 465d144f...f1ad), not guessed from data:

* The ELF's `.sndata` section (vaddr 0x35E900) starts with an "SNR2" export table the `.rel` actor modules link
  against: u32 magic, u32 table vaddr (0x382EDC), 0, u32 table vaddr, u32 count (0x1CF1), then 12-byte records
  (name vaddr, address, info).  `exe_symbols` reads it: 7408 named functions/objects (GCC 2.9 mangling).

* `cPlLeon::setModel` (0x159BB0) takes the player DAT pack at `*(*(0x325308)+0x58)` and calls
  `cModel::modelInit(bin, tpl)` / `cModInfoMgr::create(bin, tpl)` with `pack + u32(pack + 0x10 + 4*slot)`, i.e. a BIN
  slot and a TPL slot of the DAT.  `set_model_pairs` re-derives those (bin, tpl) slot pairs from the instructions.

* `cModelInfo::init(bin, tpl)` (0x22DCC8) and `cModel::initJoint` (0x22C680) read the BIN header (little-endian):
      0x00 u16 header size (0x30)    0x04 u32 bone table offset   0x09 u8 bone count (initJoint: 0 = rigid)
      0x0A u16 object count (-> info+0x28)   0x0C u32 packet data offset (-> info+0x20)
      0x10/0x14 copied but unused on PS2 (0xCD fill in shipped files)   0x1C u32 offset of the table after the bones
      0x20 u32 optional offset (non-zero sets info flag 2)   0x28 u32 bounding-box offset (getBoundingBox 0x22E478:
      two vec3 at +0 and +0x10)
  Bones are the GC layout: 16 B {u8 id, u8 parent (0xFF root), 2 pad, f32 x, y, z relative to the parent}.
* `PS2TEX::Assign(TEXPalette*)` (0x2510F0) relocates a TPL in place: u32 tag (0x1000), u32 count, u32 table offset,
  u32 flags (bit 0x08000000 = already relocated), then 0x30-byte records: u16 w, u16 h, u16 format (GX enum kept
  from the GC port: 8 = C4, 9 = C8, 0xE = CMPR ...), u16, u16, u16 (clamped to < 3), u32 size/32, u32 sub-record
  offsets at +0x10/+0x14 (mip levels, each with its own +0x20/+0x24), u32 image offset +0x20, u32 palette offset +0x24.
"""
from __future__ import annotations

import struct

ELF_SHA256 = "465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad"
SNDATA_VADDR = 0x35E900
PACK_GLOBAL = 0x325308            # *(PACK_GLOBAL)+0x58 = the player's DAT pack
GX_FORMATS = {0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "RGB565", 5: "RGB5A3", 6: "RGBA8", 8: "C4", 9: "C8",
              10: "C14X2", 14: "CMPR"}
LOADERS = ("setModel__7cPlLeon", "setModel__9cPlAshley", "modelInit__6cModelUiUi", "init__10cModelInfoUiUi",
           "initJoint__6cModelP10cModelData", "getBoundingBox__FP10cModelDataP12cBoundingBox",
           "Assign__6PS2TEXP10TEXPalette", "create__11cModInfoMgrUiUi", "addModel__6cModelP10cModelInfo",
           "GetDat__6DatTblPUiPUcPCcPi", "SetDat__6DatTblPCcUiUcUiUcPi")


# ---------------------------------------------------------------- executable

def _segments(elf: bytes) -> list[tuple[int, int, int]]:
    if elf[:4] != b"\x7fELF" or struct.unpack_from("<H", elf, 18)[0] != 8:
        raise ValueError("not a little-endian MIPS ELF")
    phoff = struct.unpack_from("<I", elf, 28)[0]
    phnum = struct.unpack_from("<H", elf, 44)[0]
    out = []
    for i in range(phnum):
        t, off, va, _pa, fsz = struct.unpack_from("<5I", elf, phoff + 32 * i)
        if t == 1:
            out.append((off, va, fsz))
    return out


class Exe:
    """Vaddr-addressed view of the boot ELF's PT_LOAD segments."""

    def __init__(self, elf: bytes):
        self.d = elf
        self.segs = _segments(elf)

    def off(self, va: int) -> int:
        for off, base, fsz in self.segs:
            if base <= va < base + fsz:
                return off + va - base
        raise ValueError(f"vaddr {va:#x} is outside the file image")

    def u32(self, va: int) -> int:
        return struct.unpack_from("<I", self.d, self.off(va))[0]

    def cstr(self, va: int) -> str:
        o = self.off(va)
        return self.d[o:self.d.index(b"\0", o)].decode("latin-1")

    def words(self, va: int, n: int) -> tuple[int, ...]:
        return struct.unpack_from(f"<{n}I", self.d, self.off(va))


def exe_symbols(elf: bytes, sndata: int = SNDATA_VADDR) -> dict[str, int]:
    """name -> address from the SNR2 export table at the start of `.sndata`."""
    x = Exe(elf)
    magic, table, _z, table2, count = x.words(sndata, 5)
    if magic != 0x32524E53 or table != table2 or not 0 < count < 100000:
        raise ValueError("no SNR2 export table at .sndata")
    out = {}
    for i in range(1, count):                       # record 0 is the empty name
        nva, addr, _info = x.words(table + 12 * i, 3)
        out[x.cstr(nva)] = addr
    return out


def _func_end(syms: dict[str, int], start: int) -> int:
    later = [a for a in syms.values() if a > start]
    return min(later) if later else start + 0x400


def set_model_pairs(elf: bytes, func: str = "setModel__7cPlLeon", syms: dict | None = None) -> list[dict]:
    """(bin slot, tpl slot) per model the player's setModel creates, re-derived from its MIPS code.

    Each call to modelInit/create is preceded by `lw a1, 0x10+4*bin(pack)` and `lw a2|v0, 0x10+4*tpl(pack)`.
    """
    syms = syms if syms is not None else exe_symbols(elf)
    x = Exe(elf)
    start = syms[func]
    end = _func_end(syms, start)
    callees = {syms["modelInit__6cModelUiUi"]: "modelInit", syms["create__11cModInfoMgrUiUi"]: "create"}
    out, a1, tpl = [], None, None
    for va in range(start, end, 4):
        w = x.u32(va)
        op = w >> 26
        if op == 0x23:                               # lw rt, imm(rs)
            rt, imm = (w >> 16) & 31, w & 0xFFFF
            if 0x10 <= imm < 0x200 and imm % 4 == 0 and imm != 0x58:
                if rt == 5:
                    a1 = imm
                elif rt in (2, 6):
                    tpl = imm
        elif op == 3:                                # jal
            tgt = ((w & 0x3FFFFFF) << 2) | (va & 0xF0000000)
            if tgt in callees and a1 is not None and tpl is not None:
                out.append({"call": va, "callee": callees[tgt], "bin_slot": (a1 - 0x10) // 4,
                            "tpl_slot": (tpl - 0x10) // 4})
            a1 = tpl = None                          # arguments never survive a call
    return out


# ---------------------------------------------------------------- BIN / TPL

def bin_header(b: bytes) -> dict:
    """Header fields `cModelInfo::init`/`initJoint`/`getBoundingBox` read, plus the bone table."""
    if len(b) < 0x30:
        raise ValueError("BIN shorter than its header")
    hsz, flags, bones_off = struct.unpack_from("<HHI", b, 0)
    nb = b[9]
    nobj, data_off = struct.unpack_from("<HI", b, 0xA)
    tab_off, opt_off, _x24, bbox_off = struct.unpack_from("<4I", b, 0x1C)
    if hsz != 0x30 or not hsz <= bones_off <= len(b) or not 0 < data_off <= len(b):
        raise ValueError("not a RE4 PS2 BIN header")
    if bones_off + 16 * nb > len(b) or bbox_off + 0x1C > len(b):
        raise ValueError("BIN tables run past the end of the file")
    bones = [struct.unpack_from("<BB2x3f", b, bones_off + 16 * i) for i in range(nb)]
    seen: set[int] = set()
    for i, (bid, par, *_xyz) in enumerate(bones):          # ids need not equal the index (sub-models start at 2)
        if bid in seen or (par != 0xFF and par not in seen):
            raise ValueError(f"bone {i}: id {bid} parent {par} is not a parent-first table")
        seen.add(bid)
    bb = struct.unpack_from("<3f4x3f", b, bbox_off)
    return {"header_size": hsz, "flags": flags, "bones_offset": bones_off, "bone_count": nb,
            "object_count": nobj, "data_offset": data_off, "after_bones_offset": tab_off,
            "optional_offset": opt_off, "bbox_offset": bbox_off, "bbox": [list(bb[:3]), list(bb[3:])],
            "bones": [{"id": i, "parent": p, "t": [x, y, z]} for i, p, x, y, z in bones],
            "bone_ids_are_index": all(b[0] == i for i, b in enumerate(bones)),
            "unused_cd_fill": b[0x10:0x18] == b"\xcd" * 8}


def tpl_header(t: bytes) -> dict:
    """Texture records as `PS2TEX::Assign` relocates them (offsets relative to the TPL start)."""
    tag, n, table, flags = struct.unpack_from("<4I", t, 0)
    if tag != 0x1000 or not 0 < n < 512 or table + 0x30 * n > len(t):
        raise ValueError("not a RE4 PS2 TPL")
    recs = []
    for i in range(n):
        r = table + 0x30 * i
        w, h, fmt, f6, f8, fa, size32, sub0, sub1 = struct.unpack_from("<6H3I", t, r)
        img, pal = struct.unpack_from("<II", t, r + 0x20)
        if not (0 < img < len(t)) or pal >= len(t):
            raise ValueError(f"TPL record {i}: offsets outside the file")
        recs.append({"w": w, "h": h, "format": fmt, "format_name": GX_FORMATS.get(fmt, f"0x{fmt:x}"),
                     "field6": f6, "field8": f8, "levels_field": fa, "size_div32": size32,
                     "sub": [sub0, sub1], "image_offset": img, "palette_offset": pal})
    return {"count": n, "table": table, "relocated": bool(flags & 0x08000000), "textures": recs}


def dat_slots(pack: bytes) -> list[tuple[int, str]]:
    n = struct.unpack_from("<I", pack, 0)[0]
    if not 0 < n < 4096 or pack[4:16] != b"\0" * 12:
        raise ValueError("not a RE4 DAT pack")
    offs = struct.unpack_from(f"<{n}I", pack, 16)
    exts = [pack[16 + 4 * n + 4 * k:20 + 4 * n + 4 * k].rstrip(b"\0").decode("latin-1") for k in range(n)]
    return list(zip(offs, exts))


def slot_bytes(pack: bytes, k: int) -> bytes:
    slots = dat_slots(pack)
    o = slots[k][0]
    nxt = sorted(x for x, _e in slots if x > o)
    return pack[o:nxt[0] if nxt else len(pack)]


def bin_objects(b: bytes) -> list[dict]:
    """The object table at the BIN's packet data offset: `object_count` 16-byte records whose u32 +0xC is the offset
    of that object's packet.  A packet starts with a 16-byte header (bone indices used by the object), then a DMA
    chain: each qword is a DMAtag (u16 qwc, id in bits 28-30) whose upper 8 bytes are two VIF codes (STCYCL, UNPACK),
    followed by `qwc` quadwords of UNPACK payload for VU1."""
    h = bin_header(b)
    out = []
    for i in range(h["object_count"]):
        r = h["data_offset"] + 16 * i
        rec = b[r:r + 16]
        pkt = struct.unpack_from("<I", rec, 12)[0]
        if not 0 < pkt < len(b):
            raise ValueError(f"object {i}: packet offset {pkt:#x} outside the BIN")
        out.append({"index": i, "record": rec.hex(), "packet": pkt, "bone_list": list(b[pkt:pkt + 16]),
                    "dma": dma_chain(b, pkt + 16, limit=4)})
    return out


def dma_chain(b: bytes, o: int, limit: int = 1 << 16) -> list[dict]:
    """Walk CNT/END DMA tags carrying VIF code pairs; stop at END (id 7), a non-CNT tag, or the end of the data."""
    out = []
    while o + 16 <= len(b) and len(out) < limit:
        qwc_id, _addr, v0, v1 = struct.unpack_from("<4I", b, o)
        qwc, tid = qwc_id & 0xFFFF, (qwc_id >> 28) & 7
        vif = []
        for w in (v0, v1):
            cmd, num, imm = (w >> 24) & 0x7F, (w >> 16) & 0xFF, w & 0xFFFF
            if cmd >= 0x60:
                vif.append({"cmd": "UNPACK", "vn": ((cmd >> 2) & 3) + 1, "vl": 32 >> (cmd & 3), "num": num or 256,
                            "addr": imm & 0x3FF, "flg": bool(imm & 0x8000), "usn": bool(imm & 0x4000)})
            else:
                vif.append({"cmd": {0: "NOP", 1: "STCYCL", 0x10: "FLUSHE", 0x11: "FLUSH", 0x14: "MSCAL",
                                    0x17: "MSCNT"}.get(cmd, f"0x{cmd:02x}"), "num": num, "imm": imm})
        out.append({"offset": o, "qwc": qwc, "id": tid, "vif": vif})
        if tid not in (1, 7):
            break
        o += 16 + 16 * qwc
        if tid == 7:
            break
    return out


def probe(pack: bytes, pairs: list[dict]) -> list[dict]:
    """Decode the header of every BIN/TPL pair a setModel uses from this pack."""
    slots = dat_slots(pack)
    out = []
    for p in pairs:
        bk, tk = p["bin_slot"], p["tpl_slot"]
        if slots[bk][1] != "BIN" or slots[tk][1] != "TPL":
            raise ValueError(f"slot pair {bk}/{tk} is {slots[bk][1]}/{slots[tk][1]}, not BIN/TPL")
        bb = slot_bytes(pack, bk)
        bh = bin_header(bb)
        th = tpl_header(slot_bytes(pack, tk))
        out.append({**p, "bin_offset": slots[bk][0], "tpl_offset": slots[tk][0],
                    "bin": {k: v for k, v in bh.items() if k != "bones"},
                    "root_bones": [b["id"] for b in bh["bones"] if b["parent"] == 0xFF],
                    "objects": bin_objects(bb), "tpl": th})
    return out


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("dat")
    ap.add_argument("--func", default="setModel__7cPlLeon")
    a = ap.parse_args()
    elf = open(a.elf, "rb").read()
    syms = exe_symbols(elf)
    pairs = set_model_pairs(elf, a.func, syms)
    print(json.dumps({"loaders": {k: syms.get(k) for k in LOADERS}, "pairs": probe(open(a.dat, "rb").read(), pairs)},
                     indent=1))
