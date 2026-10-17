"""Exact-build inventory for Mega Man 64 (USA), N64 (favorite 7815f5fed884d651).

The owned HyperSpin zip holds one ``.n64``-named member that is really
byte-swapped v64 data, so the ROM is always read through
:func:`gbox.n64_rom.read` (normalised big-endian z64).  The normalised image is
the No-Intro "Mega Man 64 (USA)" dump (sha1 f24fe0af...): game code NM6E rev 0,
internal name "Mega Man 64", CIC-NUS-6102, built on NuSystem 2.07 (the resident
strings call it "ROCK MAN DASH 64").

Layout recovered from the ROM itself (nothing written, no emulator):

* IPL3 loads ROM 0x1000.. to the entry point 0x80025C00, so RAM = ROM +
  0x80024C00.  The entry stub clears BSS 0x800D34D0 (+0x14A500) and jumps to
  main 0x80089FD0, so the resident segment is ROM 0x1000-0xAE8D0.
* Asset directories are arrays of 8-byte ``{u32 offset, u32 flags<<24 | size}``
  records whose offsets chain (next = align4(offset + size)).  Each directory
  is the file table of one contiguous ROM archive whose start/end are code
  constants (lui/addiu pairs in resident or overlay code); the archive length
  equals the directory span rounded up to 16.
* Every flag-0x80 entry is ``u32 unpacked_size`` followed by an Okumura-style
  LZSS stream (4 KiB zero-filled ring, write index 0xFEE, LSB-first flag bits
  with 1 = literal, 2-byte back-reference ``offset = b0 | (b1 & 0xF0) << 4``,
  ``length = (b1 & 0x0F) + 3``).  The streams end exactly at the stored size.

``python -m gbox.mm64_inventory SOURCE.zip --out manifest.json`` writes the
manifest.  It refuses any other ROM (gBox mods included) unless
``strict=False``.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile

from . import n64_rom
from .mkmyth_inventory import header_crc, ipl3_cic, parse_header
from .formats.lz import lzss_decompress  # noqa: F401  (shared codec, moved to gbox.formats)

GAME_ID = "7815f5fed884d651"
TITLE = "Mega Man 64 (USA)"

# Exact build identity (normalised z64), pinned from the owned source.
KNOWN = {
    "z64_sha1": "f24fe0aff01aec018e2dd558ec4f076cf328129f",  # No-Intro good dump
    "z64_md5": "3620674acb51e436d5150738ac1c0969",
    "z64_size": 0x2000000,
    "game_code": "NM6E",
    "version": 0,
}

ENTRY_POINT = 0x80025C00
RAM_DELTA = ENTRY_POINT - 0x1000        # resident segment: RAM = ROM + RAM_DELTA
FLAG_LZSS = 0x80
_M = 0xFFFFFFFF


class WrongBuild(ValueError):
    """Raised when the ROM is not the pinned NM6E rev 0 build."""


def rom_to_ram(off: int) -> int:
    return (off + RAM_DELTA) & _M


def ram_to_rom(addr: int) -> int:
    return (addr - RAM_DELTA) & _M


def _sext16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


# --------------------------------------------------------------------------- codec



def unpack_entry(rom: bytes, base: int, off: int, size: int) -> tuple[bytes | None, dict]:
    """Decode one directory entry; returns (payload or None, facts)."""
    start = base + off
    if size < 5 or start + size > len(rom):
        return None, {"codec": "raw"}
    usz = struct.unpack_from(">I", rom, start)[0]
    if usz > 0x800000:
        return None, {"codec": "raw"}
    data, used = lzss_decompress(rom, start + 4, usz, start + size)
    if len(data) == usz and used + 4 <= size:
        return data, {"codec": "lzss", "unpacked": usz, "slack": size - used - 4}
    return None, {"codec": "raw"}


# ----------------------------------------------------------------- directories

def scan_directories(rom: bytes, lo: int = 0, hi: int | None = None,
                     min_len: int = 4) -> list[dict]:
    """Find chained ``{offset, flags<<24|size}`` directories in ``rom[lo:hi]``."""
    hi = len(rom) if hi is None else hi
    found = []
    for phase in (0, 4):
        cur: list[tuple[int, int, int]] = []
        i = lo + phase
        while True:
            a = size = flag = 0
            ok = i + 8 <= hi
            if ok:
                a, b = struct.unpack_from(">II", rom, i)
                size, flag = b & 0xFFFFFF, b >> 24
                ok = flag in (0x00, 0x40, 0x80, 0xC0) and 0 < size < 0x400000 and a < len(rom)
            if ok and cur and a == (cur[-1][0] + cur[-1][1] + 3) & ~3:
                cur.append((a, size, flag))
            else:
                if len(cur) >= min_len:
                    start = i - 8 * len(cur)
                    found.append({"rom": start, "entries": cur})
                cur = [(a, size, flag)] if ok else []
            if i + 8 > hi:
                break
            i += 8
    found.sort(key=lambda d: d["rom"])
    return found


def directory_span(entries: list[tuple[int, int, int]]) -> int:
    return entries[-1][0] + entries[-1][1]


def rom_constants(rom: bytes, lo: int, hi: int, low: int = 0x2C0000,
                  high: int | None = None) -> dict[int, list[int]]:
    """lui + addiu/ori/lw/sw constants in ``[low, high)`` built inside ``rom[lo:hi]``."""
    high = len(rom) if high is None else high
    out: dict[int, list[int]] = {}
    lui: dict[int, tuple[int, int]] = {}
    for off in range(lo, hi - 3, 4):
        ins = struct.unpack_from(">I", rom, off)[0]
        op, rs, rt, imm = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, ins & 0xFFFF
        if op == 0x0F:
            lui[rt] = (imm << 16, off)
            continue
        if op in (0x09, 0x0D, 0x23, 0x2B) and rs in lui and off - lui[rs][1] <= 0x40:
            hi16 = lui[rs][0]
            val = (hi16 | imm) if op == 0x0D else (hi16 + _sext16(imm)) & _M
            if low <= val < high:
                out.setdefault(val, []).append(off)
    return out


def candidate_bases(dirs: list[dict], constants: list[int]) -> dict[int, list[int]]:
    """Directory ROM offset -> archive bases where base + span rounds up to a constant."""
    cs = sorted(set(constants))
    cset = set(cs)
    out: dict[int, list[int]] = {}
    for d in dirs:
        span = directory_span(d["entries"])
        if span < 0x800:
            continue
        hits = [a for a in cs if any((a + span + pad) in cset for pad in range(16))]
        if hits:
            out[d["rom"]] = hits
    return out


def classify_payload(data: bytes) -> str:
    """Structural kind of a decoded entry (no semantic claims)."""
    if not data:
        return "empty"
    if len(data) >= 8:
        n = struct.unpack_from(">I", data, 0)[0]
        if 1 <= n <= 512 and 4 * (n + 1) <= len(data):
            offs = struct.unpack_from(">%dI" % n, data, 4)
            if (offs[0] >= 4 * (n + 1) and all(a < b for a, b in zip(offs, offs[1:]))
                    and offs[-1] <= len(data)):
                return "container:%d" % n
    return "blob"


def verify_archive(rom: bytes, base: int, entries: list[tuple[int, int, int]],
                   detail: bool = True) -> dict:
    rows, kinds, codecs = [], Counter(), Counter()
    packed = unpacked = bad = 0
    for idx, (off, size, flag) in enumerate(entries):
        data, facts = unpack_entry(rom, base, off, size)
        packed += size
        if data is None:
            blob = rom[base + off:base + off + size]
            kind = "raw"
            if flag & FLAG_LZSS:
                bad += 1
            unpacked += size
        else:
            blob = data
            kind = classify_payload(data)
            unpacked += len(data)
        codecs[facts["codec"]] += 1
        kinds[kind] += 1
        if detail:
            rows.append({"i": idx, "off": off, "size": size, "flag": flag,
                         "codec": facts["codec"], "unpacked": len(blob), "kind": kind,
                         "sha1": hashlib.sha1(blob).hexdigest()})
    end = base + directory_span(entries)
    return {"base": base, "end": end, "entries": len(entries),
            "packed_bytes": packed, "unpacked_bytes": unpacked,
            "flags": {"%02x" % k: v for k, v in sorted(Counter(e[2] for e in entries).items())},
            "codecs": dict(codecs), "kinds": dict(kinds.most_common()),
            "lzss_failures": bad, "verified": bad == 0,
            "region_sha1": hashlib.sha1(rom[base:end]).hexdigest(),
            "rows": rows}


# ------------------------------------------------------------------- identity

def decode_entry_stub(rom: bytes, off: int = 0x1000, count: int = 16) -> dict:
    regs: dict[int, int] = {}
    for i in range(count):
        ins = struct.unpack_from(">I", rom, off + 4 * i)[0]
        op, rs, rt, imm = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, ins & 0xFFFF
        if op == 0x0F:
            regs[rt] = imm << 16
        elif op == 0x09 and rs == rt and rs in regs:
            regs[rt] = (regs[rt] + _sext16(imm)) & _M
    bss, size = regs.get(8), regs.get(9)
    return {"bss_start": bss, "bss_size": size, "main": regs.get(10),
            "stack_top": regs.get(29),
            "bss_end": None if bss is None or size is None else bss + size,
            "resident_rom_end": None if bss is None else ram_to_rom(bss)}


def load(path: str | Path) -> tuple[dict, bytes]:
    path = Path(path)
    raw = path.read_bytes()
    src = {"path": str(path), "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            info = z.infolist()[0]
            head = z.open(info).read(4)
            src.update(member=info.filename, member_size=info.file_size,
                       member_crc32="%08x" % info.CRC)
    else:
        head = raw[:4]
    src["byte_order"] = {b"\x80\x37\x12\x40": "z64", b"\x37\x80\x40\x12": "v64",
                         b"\x40\x12\x37\x80": "n64"}.get(head, head.hex())
    rom = n64_rom.read(path)
    src.update(z64_sha256=hashlib.sha256(rom).hexdigest(),
               z64_sha1=hashlib.sha1(rom).hexdigest(),
               z64_md5=hashlib.md5(rom).hexdigest(), z64_size=len(rom))
    return src, rom


def check_build(src: dict, header: dict) -> None:
    bad = [k for k in ("z64_sha1", "z64_md5", "z64_size") if src[k] != KNOWN[k]]
    if header["game_code"] != KNOWN["game_code"] or header["version"] != KNOWN["version"]:
        bad.append("game_code/version")
    if bad:
        raise WrongBuild("not the owned NM6E rev 0 build (%s)" % ", ".join(bad))


def _gaps(spans: list[tuple[int, int]], lo: int, hi: int) -> list[tuple[int, int]]:
    out, cur = [], lo
    for a, b in sorted(spans):
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    if cur < hi:
        out.append((cur, hi))
    return out


def _describe_gap(rom: bytes, a: int, b: int) -> dict:
    head = rom[a:a + 0x40]
    info = {"start": a, "end": b, "size": b - a, "head": head[:16].hex()}
    for tag in (b"N64 WaveTables", b"N64 PtrTables"):
        if tag in head:
            info["magic"] = tag.decode()
    usz = struct.unpack_from(">I", rom, a)[0] if b - a >= 8 else 0
    if 0 < usz <= 0x800000:
        data, used = lzss_decompress(rom, a + 4, usz, b)
        if len(data) == usz:
            info["lzss_head"] = {"unpacked": usz, "packed": used + 4,
                                 "magic": data[:16].decode("ascii", "replace")
                                 if data[:3] == b"N64" else None}
    return info


def inventory(path: str | Path, strict: bool = True, detail: bool = True) -> dict:
    src, rom = load(path)
    header = parse_header(rom)
    if strict:
        check_build(src, header)
    cic, ipl_crc = ipl3_cic(rom)
    crc_ok = bool(cic) and header_crc(rom, cic) == (header["crc1"], header["crc2"])
    stub = decode_entry_stub(rom)
    resident_end = stub["resident_rom_end"] or 0xAE8D0
    end = len(rom)
    while end and rom[end - 1] in (0, 0xFF):
        end -= 1

    dirs = scan_directories(rom, 0x1000, 0x2C0000)
    consts = rom_constants(rom, 0x1000, resident_end)
    overlay_consts = rom_constants(rom, resident_end, 0x2C0000)
    all_consts = sorted(set(consts) | set(overlay_consts))
    bases = candidate_bases(dirs, all_consts)

    archives, rejected = [], []
    for d in dirs:
        for base in bases.get(d["rom"], []):
            rep = verify_archive(rom, base, d["entries"], detail=detail)
            rep.update(directory_rom=d["rom"],
                       directory_ram=rom_to_ram(d["rom"]) if d["rom"] < resident_end else None,
                       directory_in="resident" if d["rom"] < resident_end else "overlay")
            if rep["verified"]:
                archives.append(rep)
                break
            rejected.append(rep)
    # one archive per base: keep the verified directory that covers the most entries
    by_base: dict[int, dict] = {}
    for a in archives:
        if a["base"] not in by_base or a["entries"] > by_base[a["base"]]["entries"]:
            by_base[a["base"]] = a
    archives = sorted(by_base.values(), key=lambda a: a["base"])
    claimed = {a["directory_rom"] for a in archives}
    unresolved = [{"rom": d["rom"], "entries": len(d["entries"]),
                   "span": directory_span(d["entries"])}
                  for d in dirs if d["rom"] not in claimed]

    spans = [(0x1000, 0x2C0000)] + [(a["base"], (a["end"] + 15) & ~15) for a in archives]
    gaps = [_describe_gap(rom, a, b) for a, b in _gaps(spans, 0x1000, end)]
    totals = Counter()
    kinds = Counter()
    for a in archives:
        totals["entries"] += a["entries"]
        totals["packed"] += a["packed_bytes"]
        totals["unpacked"] += a["unpacked_bytes"]
        kinds.update(a["kinds"])
    covered = sum((a["end"] - a["base"]) for a in archives)
    strings = {s: rom.find(s.encode(), 0x1000, resident_end)
               for s in ("ROCK MAN DASH 64", "RockManDashN64 SaveSlot Exist",
                         "NuSystem2.07", "This game is not designed for use")}
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": "n64",
        "source": src,
        "no_intro_match": src["z64_sha1"] == KNOWN["z64_sha1"],
        "header": header,
        "boot": {"cic": cic, "ipl3_crc32": "%08x" % ipl_crc, "header_crc_matches": crc_ok},
        "launch": {"core": "parallel_n64 / mupen64plus-next", "cic": cic,
                   "rom_size_mbit": len(rom) * 8 // 0x100000,
                   "byte_order_on_disk": src["byte_order"],
                   "expansion_pak_required": (stub["bss_end"] or 0) > 0x80400000,
                   "notes": "member is byte-swapped v64; always normalise with n64_rom.read; "
                            "Windows N64 adapter pins angrylion + cxd4 LLE RSP"},
        "layout": {
            "ram_delta": RAM_DELTA,
            "resident": {"rom_start": 0x1000, "rom_end": resident_end,
                         "ram_start": header["entry_point"], **stub},
            "overlay_region": {"rom_start": resident_end, "rom_end": 0x2C0000,
                               "notes": "code overlays + overlay-resident directories"},
            "archives": len(archives),
            "archive_bytes": covered,
            "unresolved_directories": unresolved,
            "rejected_matches": [{"directory_rom": r["directory_rom"], "base": r["base"],
                                  "lzss_failures": r["lzss_failures"]} for r in rejected],
            "gaps": gaps,
            "data_end": end,
            "padding": [end, len(rom)],
            "code_rom_constants": [c for c in all_consts if c >= 0x2C0000],
        },
        "codec": {"name": "lzss_okumura_4k_zero_ring",
                  "header": "u32 big-endian unpacked size",
                  "verified_entries": sum(a["codecs"].get("lzss", 0) for a in archives)},
        "assets": {"entries": totals["entries"], "packed_bytes": totals["packed"],
                   "unpacked_bytes": totals["unpacked"], "kinds": dict(kinds.most_common(24))},
        "characters": {
            "player": "Mega Man Volnutt",
            "rom_name_table": None,
            "notes": "No plain-text roster/debug name table in the retail ROM; decoded "
                     "archives hold no ASCII names.  The 445-entry archive at 0x2CAC60 "
                     "(directory RAM 0x800BDF70, read by code at ROM 0x5C8B8/0x5CB14) is the "
                     "first model-archive candidate; entry->character ids need the loader xref.",
        },
        "string_hints": strings,
        "archives_detail": archives,
        "unverified": [
            "archive entry -> character/NPC/enemy id mapping (needs loader xrefs in Ghidra)",
            "sub-container section semantics (mesh / texture / palette / animation)",
            "unresolved directories at RAM 0x800A7DA8.. (base not a code constant)",
            "gap regions that are not code-referenced archives (audio banks, streamed data)",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inventory the owned Mega Man 64 USA N64 build.")
    ap.add_argument("source")
    ap.add_argument("--out")
    ap.add_argument("--no-strict", action="store_true")
    ap.add_argument("--summary", action="store_true", help="omit per-entry rows")
    a = ap.parse_args(argv)
    m = inventory(a.source, strict=not a.no_strict, detail=not a.summary)
    text = json.dumps(m, indent=1, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
