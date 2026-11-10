"""DOA5 Last Round (PS3, BLJM61258) decrypted EBOOT.elf probe (request #2450).

Read-only: parses the ELF64-BE PPC64 headers of an EBOOT that was decrypted
from the owned disc (e.g. ``rpcs3 --decrypt EBOOT.BIN``) and locates the
archive-name anchors (chara_common / chara_rtm .lnk/.bin, LFMO tag).
"""
import hashlib
import re
import struct

PT_LOAD = 1
ANCHORS = (b"chara_common.lnk", b"chara_common.bin", b"chara_rtm.lnk",
           b"chara_rtm.bin", b"LFMO")


def probe_elf(data: bytes) -> dict:
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 2:
        raise ValueError("not ELF64 big-endian")
    machine = struct.unpack(">H", data[18:20])[0]
    entry = struct.unpack(">Q", data[0x18:0x20])[0]
    phoff = struct.unpack(">Q", data[0x20:0x28])[0]
    phentsize, phnum = struct.unpack(">HH", data[0x36:0x3A])
    segs = []
    for i in range(phnum):
        t, fl, off, va, _pa, fs, ms, al = struct.unpack(
            ">IIQQQQQQ", data[phoff + i * phentsize: phoff + i * phentsize + 56])
        segs.append({"type": t, "flags": fl, "offset": off, "vaddr": va,
                     "filesz": fs, "memsz": ms})
    return {"machine": machine, "entry": entry, "segments": segs}


def find_anchors(data: bytes, anchors=ANCHORS) -> dict:
    return {a.decode(): [m.start() for m in re.finditer(re.escape(a), data)]
            for a in anchors}


def file_offset_to_vaddr(info: dict, off: int):
    for s in info["segments"]:
        if s["type"] == PT_LOAD and s["filesz"] and \
                s["offset"] <= off < s["offset"] + s["filesz"]:
            return s["vaddr"] + off - s["offset"]
    return None


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()
