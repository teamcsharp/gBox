"""Owned-build inventory for Madden NFL 2001 (USA) on N64 (#1508): identify the exact ROM, verify the boot
stub's pack/decompressor sites in the build's own code, decode every packed entry, and classify the
character-relevant assets (rosters, models, textures, animation-like tables, portraits).

    python -m gbox.madden2001_inventory SRC [--out manifest.json] [--unpack DIR]

SRC is the owned zip / z64 / v64 / n64; it is only read. The build is keyed on the NFLE rev 0 header
(CRC1 eb38f792); any other build fails loudly instead of being parsed with the wrong tables.

Facts fixed for this exact build (z64 offsets). IPL3 copies ROM 0x1000 -> RAM 0x80200400 (entry 0x80200400):

  * Boot stub 0x802004FC reads the pack header at RAM 0x80200F68 (ROM 0x1B68, `lui v0,0x8020 / addiu
    v0,0xf68` at 0x80200534/38) and unpacks its entry 0 to RAM 0x80000400 (`lui/ori` at 0x80200554/58):
    the 0x69568-byte main code segment.
  * Pack table: ROM 0x1B00 (RAM 0x80200F00) holds 23 PI addresses 0xB0xxxxxx. Each pack starts with N
    12-byte entries {u32 data offset from pack start, u32 size, u32 flags|stored size}; the first offset is
    the header size (N*12). Bit 31 marks a compressed entry; stored size 0 or >= size means a raw copy of
    `size` bytes (the stub's `bnez` at 0x80200584). Packs and entries are byte-aligned in ROM.
  * Codec ("EA bit-LZ", 0x80200410 -> 0x80200A5C, getbits 0x80200718, unary 0x80200918): compressed input
    is split into independent 0x1000-byte bitstreams (`addiu v0,zero,0x1000` at 0x8020046C) that share one
    output window of 0x10000 (`lui v0,1` at 0x80200430). Bits are read MSB-first from big-endian words.
    The first stream starts with a 5-byte header whose first byte is 3. Per token: 1 flag bit;
    flag 1 = 7-bit count n then n literal bytes; flag 0 = match: unary g (count of 0s before a 1, max 7,
    8 bits), length = ((1<<g)|bits(g) if g else 1) + 2, then a truncated-binary distance over
    [0, min(out_pos, window)] with a bit width that grows with the output position. A stream ends when
    fewer than 8 bits remain or the output reaches the entry size.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

from . import n64_rom
from .wm2000_inventory import container, header

CODE_RAM = 0x80200400                          # ROM 0x1000 -> RAM 0x80200400 (IPL3 copy)
CODE_ROM = 0x1000
BUILD = (0xEB38F792, "NFLE", 0)                # CRC1, product code, revision of the owned build
SITES = {                                      # boot-stub sites (RAM address -> (role, instruction word))
    0x80200400: ("sp_hi", 0x3C1D803F),         # lui sp, 0x803f
    0x80200430: ("window", 0x3C020001),        # lui v0, 1          -> 0x10000-byte output window
    0x8020046C: ("chunk", 0x24021000),         # addiu v0, zero, 0x1000 (independent bitstream size)
    0x802004C4: ("jal_lz", 0x0C080297),        # jal 0x80200a5c (decoder)
    0x80200534: ("pack_hi", 0x3C028020),       # lui v0, 0x8020
    0x80200538: ("pack_lo", 0x24420F68),       # addiu v0, v0, 0xf68 -> pack header ROM 0x1B68
    0x80200554: ("dst_hi", 0x3C028000),        # lui v0, 0x8000
    0x80200558: ("dst_lo", 0x34420400),        # ori v0, v0, 0x400  -> main code at 0x80000400
    0x80200A5C: ("lz_entry", 0x27BDFFC8),      # addiu sp, sp, -0x38
    0x80200ACC: ("magic", 0x24020003),         # addiu v0, zero, 3  (first stream byte)
}
PACK_TABLE = 0x1B00
CODE_PACK = 0x1B68
CODE_SIZE = 0x69568
WINDOW = 0x10000
CHUNK = 0x1000
TEAM_STRIDE = 107                              # pack 13 entry 0: team records, nickname at +1
PLAYER_STRIDE = 50                             # pack 13 roster entries: NUL-terminated "F.LASTNAME" at +0
TAGS = {b"NMF1": "nmf1_model", b"TNMF": "tnmf_display_list_model", b"\\STA": "stadium_texture_set",
        b"BNKb": "audio_bank", b"CRDb": "audio_bank_index", b"XELA": "xela_table", b"\xff\xd8\xff\xe0": "jpeg",
        b"\x00\x08\x00\x01": "image_0008", b"\x00\x01\x00\x01": "table_0001", b"MD\x00\x01": "md_table"}


def ram2rom(a: int) -> int:
    return a - CODE_RAM + CODE_ROM


class _Bits:
    def __init__(self, src: bytes):
        self.src, self.pos, self.buf, self.bp, self.rem = src, 0, 0, -1, len(src) * 8

    def _word(self) -> int:
        w = int.from_bytes(self.src[self.pos:self.pos + 4].ljust(4, b"\0"), "big")
        self.pos += 4
        return w

    def get(self, n: int) -> int:
        self.rem -= n
        over = max(n - self.bp - 1, 0)
        if over:
            r = self.buf & ((1 << (n - over)) - 1)
            self.buf = self._word()
            self.bp += 32
            r = ((r << over) | (self.buf >> (32 - over))) & 0xFFFFFFFF
        else:
            r = (self.buf >> (self.bp - (n - 1))) & ((1 << n) - 1)
        self.bp -= n
        return r

    def unary(self) -> int:
        c, mask = -1, (1 << self.bp) if self.bp >= 0 else 0
        while True:
            if self.bp == -1:
                self.buf, self.bp, mask = self._word(), 31, 0x80000000
            bit = self.buf & mask
            c, mask, self.bp = c + 1, mask >> 1, self.bp - 1
            if bit or c >= 7:
                break
        self.rem -= c + 1
        return c


def _stream(src: bytes, out: bytearray, limit: int, window: int = WINDOW) -> None:
    b = _Bits(src)
    if not out:
        if src[:1] != b"\x03":
            raise ValueError(f"EA bit-LZ stream must start with 3, got {src[:8].hex()}")
        for _ in range(5):
            b.get(8)
    nb, pw = 1, 2
    while b.rem >= 8 and len(out) < limit:
        if b.get(1):
            for _ in range(b.get(7)):
                out.append(b.get(8))
            continue
        if b.rem < 0:
            raise ValueError("EA bit-LZ stream truncated")
        g = b.unary()
        ln = (((1 << g) | b.get(g)) if g else 1) + 2
        op = len(out)
        while op >= pw:
            if pw < window:
                nb += 1
            pw <<= 1
        unused = (1 << nb) - 1 - min(op, window)
        if unused != -1:
            d = b.get(nb - 1)
            if d >= unused:
                d = ((d << 1) | b.get(1)) - unused
        else:
            d = b.get(nb)
        s = op - d
        if s < 0 or d == 0:
            raise ValueError(f"bad match distance {d} at output {op:#x}")
        for i in range(ln):
            out.append(out[s + i])


def decompress(src: bytes, size: int) -> bytes:
    """Decode one packed entry (the stub's 0x80200410 loop): 0x1000-byte independent bitstreams."""
    out = bytearray()
    for off in range(0, len(src), CHUNK):
        _stream(src[off:off + CHUNK], out, size)
    if len(out) < size:
        raise ValueError(f"short output {len(out):#x} < {size:#x}")
    return bytes(out[:size])


def _u32(buf: bytes, off: int) -> int:
    if off < 0 or off + 4 > len(buf):
        raise ValueError(f"read of u32 at {off:#x} past end of {len(buf):#x}-byte buffer")
    return struct.unpack_from(">I", buf, off)[0]


def check_build(rom: bytes) -> dict:
    if len(rom) < 0x1000:
        raise ValueError(f"ROM too short ({len(rom):#x} bytes)")
    h = header(rom)
    if (int(h["crc1"], 16), h["code"], h["rev"]) != BUILD:
        raise ValueError(f"not the owned Madden NFL 2001 NFLE rev0 build: {h['code']} rev{h['rev']} crc1 {h['crc1']}")
    bad = {f"{a:#x}": role for a, (role, w) in SITES.items() if _u32(rom, ram2rom(a)) != w}
    if bad:
        raise ValueError(f"boot-stub sites differ: {bad}")
    return h


def packs(rom: bytes) -> list[int]:
    out, o = [], PACK_TABLE
    while (w := _u32(rom, o)) >> 24 == 0xB0:
        out.append(w & 0xFFFFFF)
        o += 4
    return out


def entries(rom: bytes, pack: int) -> list[dict]:
    hdr = _u32(rom, pack)
    if hdr % 12 or pack + hdr > len(rom):
        raise ValueError(f"pack {pack:#x} header {hdr:#x} is not a multiple of 12")
    out = []
    for k in range(hdr // 12):
        off, size, flags = struct.unpack_from(">3I", rom, pack + k * 12)
        stored = flags & 0x7FFFFFFF
        comp = bool(flags >> 31) and 0 < stored < size
        if pack + off + (stored if comp else size) > len(rom):
            raise ValueError(f"pack {pack:#x} entry {k} overruns the ROM")
        out.append({"idx": k, "rom_off": pack + off, "size": size, "stored": stored if comp else size,
                    "method": "ea_lz" if comp else "stored"})
    return out


def unpack(rom: bytes, e: dict) -> bytes:
    raw = rom[e["rom_off"]:e["rom_off"] + e["stored"]]
    return decompress(raw, e["size"]) if e["method"] == "ea_lz" else raw


def classify(data: bytes) -> str:
    return TAGS.get(data[:4], "other")


def teams(table: bytes) -> list[str]:
    out = []
    for o in range(1, len(table), TEAM_STRIDE):
        name = table[o:o + 20].split(b"\0")[0]
        if not re.fullmatch(rb"[A-Z0-9 .'\-]{2,}", name):
            break
        out.append(name.decode())
    return out


def roster(data: bytes) -> list[str]:
    if len(data) % PLAYER_STRIDE:
        return []
    names = [data[o:o + 20].split(b"\0")[0] for o in range(0, len(data), PLAYER_STRIDE)]
    return [n.decode() for n in names] if names and all(re.fullmatch(rb"[A-Z0-9][A-Z0-9 .'\-]+", n) for n in names) else []


def inventory(rom: bytes, unpack_dir: Path | None = None) -> dict:
    h = check_build(rom)
    plist = packs(rom)
    out_packs, rosters, team_names = [], [], []
    for pi, p in enumerate(plist):
        ents, kinds = entries(rom, p), Counter()
        for e in ents:
            data = unpack(rom, e)
            e["sha1"] = hashlib.sha1(data).hexdigest()
            e["kind"] = classify(data)
            kinds[e["kind"]] += 1
            if unpack_dir:
                unpack_dir.mkdir(parents=True, exist_ok=True)
                (unpack_dir / f"p{pi:02d}_{e['idx']:04d}.bin").write_bytes(data)
            if pi == 13 and e["idx"] == 0:
                team_names = teams(data)
            elif pi == 13 and (names := roster(data)):
                rosters.append({"entry": e["idx"], "players": len(names), "first": names[:3]})
        out_packs.append({"pack": pi, "rom": f"{p:#x}", "entries": len(ents), "kinds": dict(kinds),
                          "unpacked_bytes": sum(e["size"] for e in ents), "items": ents})
    code = unpack(rom, entries(rom, CODE_PACK)[0])
    return {"title": "Madden NFL 2001 (USA)", "platform": "n64", "header": h,
            "boot": {"entry_ram": f"{CODE_RAM:#x}", "pack_table_rom": f"{PACK_TABLE:#x}",
                     "code_pack_rom": f"{CODE_PACK:#x}", "code_size": len(code),
                     "code_sha256": hashlib.sha256(code).hexdigest(), "sites": {f"{a:#x}": r for a, (r, _) in SITES.items()}},
            "packs": out_packs, "entry_count": sum(p["entries"] for p in out_packs),
            "teams": team_names, "rosters": rosters, "players": sum(r["players"] for r in rosters),
            "launch": {"core": "parallel_n64", "windows": "parallel_n64 + angrylion + cxd4 RSP", "cic": h["cic"],
                       "prerequisites": "none beyond the owned cartridge image (no BIOS/disk)"}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Madden NFL 2001 (USA) N64 owned-build inventory")
    ap.add_argument("src")
    ap.add_argument("--out")
    ap.add_argument("--unpack")
    a = ap.parse_args(argv)
    src = Path(a.src)
    m = inventory(n64_rom.read(src), Path(a.unpack) if a.unpack else None)
    m["source"] = container(src)
    text = json.dumps(m, indent=1)
    Path(a.out).write_text(text) if a.out else print(text)
    print(f"{m['entry_count']} entries in {len(m['packs'])} packs, {len(m['teams'])} teams, {m['players']} players")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
