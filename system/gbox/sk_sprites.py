"""Sonic & Knuckles (World) standalone cart: owned-build identity and player sprite inventory.

Favorite 668e74c15d61a9a7 (#1365). The owned file is the HyperSpin
``Sonic & Knuckles (World).zip``; its one member is a flat (not interleaved)
2 MiB image named ``.md``. Header serial ``GM MK-1563 -00``, region JUE, and the
header checksum matches the computed one. CRC32/SHA-1 match the No-Intro
"Sonic & Knuckles (World)" dump.

S&K is a 2D sprite game (Sonic 3 & Knuckles engine). A player character is:

* uncompressed 4bpp art (8x8 tiles, 32 bytes each), DMA'd per frame;
* a DPLC table ("PLC_<char>"): u16 offsets, per frame u16 count then u16 entries
  ``(tiles-1) << 12 | first_tile`` naming art tiles to stream into the player's
  VRAM slot;
* a mapping table ("Map_<char>"): u16 offsets, per frame u16 piece count then
  6-byte pieces ``s8 y, u8 size, u16 tile, s16 x`` where tile indexes the tiles
  the DPLC just streamed (so per-frame mapping tiles must fit the DPLC total);
* an animation script table and a 16-colour palette line.

Nothing here is taken from a table of guessed offsets: the DPLC loaders are found
by their 68k instruction sequence, the character a loader belongs to comes from the
``Perform_Player_DPLC`` dispatch on ``character_id`` (+$38), and the mapping table
of each character is the ``move.l #Map,mappings(a0)`` target whose frames fit that
character's DPLC frame-for-frame. Animation tables and palettes are located by the
``lea``/PalPoint references named in :data:`AUX`, whose bytes were matched against
the sonicretro/skdisasm sources for this build (see tests).

Tails' loader in this cart streams art from 0x3200E0/0x336620, i.e. from the
attached Sonic 3 cartridge's address space: standalone S&K carries only
``ArtUnc_Tails_Extra``, so Tails is a lock-on-only character here.

CLI: ``python -m gbox.sk_sprites SRC [--out manifest.json]``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zipfile
import zlib
from pathlib import Path

ROM_EXT = (".bin", ".md", ".gen")
CART_SIZE = 0x200000  # anything at/after this address is the lock-on cartridge
NO_INTRO = {"name": "Sonic & Knuckles (World)", "crc32": "0658f691",
            "sha1": "88d6499d874dcb5721ff58d76fe1b9af811192e3"}
CHAR_IDS = {0: "sonic", 1: "tails", 2: "knuckles"}

# Ani_/Pal_ references for this exact build: (data offset, size, offset of the long
# that references it — the ``lea (Ani).l,a1`` operand or the PalPoint entry).
# Located by content match against skdisasm and confirmed by the code reference.
AUX = {
    "sonic": {"anim": (0x12AA6, 526, 0x12602), "palette": (0xA8A3C, 32, 0xA8744)},
    "tails": {"anim": (0x15AB0, 398, 0x15864), "palette": (0xA8A3C, 32, 0xA8744)},
    "knuckles": {"anim": (0x17EF4, 538, 0x17D32), "palette": (0xA8AFC, 32, 0xA8754)},
}


class SkError(ValueError):
    pass


def read_rom(path: str | Path) -> tuple[bytes, dict]:
    p = Path(path)
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as zf:
            members = [i for i in zf.infolist() if not i.is_dir()]
            if len(members) != 1:
                raise SkError(f"expected one ROM member, found {len(members)}")
            name, d = members[0].filename, zf.read(members[0])
    elif p.suffix.lower() in ROM_EXT:
        name, d = p.name, p.read_bytes()
    else:
        raise SkError(f"unsupported source {p}")
    if d[0x100:0x110] not in (b"SEGA GENESIS    ", b"SEGA MEGA DRIVE "):
        raise SkError("no flat Genesis header at 0x100 (interleaved SMD is not handled)")
    return d, {"member": name, "size": len(d)}


def header(d: bytes) -> dict:
    h = d[0x100:0x200]
    return {
        "console": h[0:16].decode("ascii"), "copyright": h[16:32].decode("ascii"),
        "domestic": h[32:80].decode("latin1").strip(), "overseas": h[80:128].decode("latin1").strip(),
        "serial": h[128:142].decode("ascii"), "checksum": h[142:144].hex(),
        "rom_end": int.from_bytes(h[164:168], "big"), "region": h[240:243].decode("ascii").strip(),
    }


def checksum(d: bytes) -> int:
    s = 0
    for (w,) in struct.iter_unpack(">H", d[0x200:len(d) & ~1]):
        s = (s + w) & 0xFFFF
    return s


def _u16(d, o):
    return struct.unpack_from(">H", d, o)[0]


def _u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


# add.w d0,d0; adda.w (a2,d0.w),a2; move.w (a2)+,d5; subq.w #1,d5; bmi.s
_DPLC_CORE = re.compile(rb"\xd0\x40\xd4\xf2\x00\x00\x3a\x1a\x53\x45\x6b.", re.S)
# tst.b $38(a1); beq.s S; cmpi.b #1,$38(a1); beq.w T; bra.w K
_DISPATCH = re.compile(rb"\x4a\x29\x00\x38\x67(.)\x0c\x29\x00\x01\x00\x38\x67\x00(..)\x60\x00(..)", re.S)


def find_dplc_loaders(d: bytes) -> list[dict]:
    """Every S3K-style player DPLC loader: PLC table, art base and VRAM byte address."""
    out = []
    for m in _DPLC_CORE.finditer(d):
        c = m.start()
        back = d[max(0, c - 24):c]
        leas = [x for x in range(len(back) - 5) if back[x:x + 2] == b"\x45\xf9"]
        # the first lea is the default table; a later one is a flag-selected override
        i = leas[0] if leas else -1
        fwd = d[m.end():m.end() + 24]
        j = fwd.find(b"\x2c\x3c")
        if i < 0 or j < 0:
            continue
        plc = _u32(back, i + 2)
        art = _u32(fwd, j + 2)
        k = (back + fwd).find(b"\x38\x3c")
        vram = _u16(back + fwd, k + 2) if k >= 0 else None
        rec = {"code": c, "plc": plc, "art": art, "vram": vram, "entry_from": c - len(back) + i}
        # optional: cmpi.w #2*N,d0; blo.s; move.l #Extra,d6 (Sonic's second art bank)
        tail = fwd[j + 6:j + 18]
        if tail[:2] == b"\x0c\x40" and tail[4:5] == b"\x65" and tail[6:8] == b"\x2c\x3c":
            rec["extra_art"] = _u32(tail, 8)
            rec["extra_from_frame"] = _u16(tail, 2) // 2
        # an alternate table may be picked just before (lea PLC_SuperSonic after a flag test)
        alts = [_u32(back, x + 2) for x in leas[1:]]
        if alts:
            rec["alt_plc"] = alts
        out.append(rec)
    return out


def player_dispatch(d: bytes) -> dict[str, int]:
    """Branch targets of Perform_Player_DPLC, keyed by character name."""
    m = _DISPATCH.search(d)
    if not m:
        raise SkError("Perform_Player_DPLC dispatch not found")
    s = m.start() + 6 + struct.unpack("b", m.group(1))[0]
    t = m.start() + 14 + struct.unpack(">h", m.group(2))[0]
    k = m.start() + 18 + struct.unpack(">h", m.group(3))[0]
    return {"_at": m.start(), "sonic": s, "tails": t, "knuckles": k}


def _offsets(d: bytes, off: int, stop: int | None = None, count: int | None = None) -> list[int]:
    """Frame offsets of a u16 table. ``stop`` ends a table that another one follows
    directly (PLC_Sonic is followed by PLC_SuperSonic, and both share frame data)."""
    first = _u16(d, off)
    if first == 0 or first & 1 or first > 0x2000:
        raise SkError(f"bad frame table at 0x{off:x}")
    n = first // 2 if stop is None or stop <= off else min(first, stop - off) // 2
    if count is not None:
        if count > n:
            raise SkError(f"table at 0x{off:x} has {n} frames, need {count}")
        n = count
    return [_u16(d, off + 2 * i) for i in range(n)]


def parse_dplc(d: bytes, off: int, stop: int | None = None,
               count: int | None = None) -> list[list[tuple[int, int]]]:
    """Per frame: [(first_tile, tiles)]."""
    frames = []
    for rel in _offsets(d, off, stop, count):
        p = off + rel
        n = _u16(d, p)
        if n > 0x40:
            raise SkError(f"DPLC frame at 0x{p:x} claims {n} entries")
        frames.append([((w & 0xFFF), (w >> 12) + 1) for w in struct.unpack_from(f">{n}H", d, p + 2)])
    return frames


def parse_mappings(d: bytes, off: int, count: int | None = None) -> list[list[dict]]:
    """Per frame: pieces {y, w, h, tile, pal, pri, hf, vf, x} (S3K 6-byte pieces).

    ``count`` bounds the table: Map_Sonic is followed by a second table, so its
    first offset over-states the frame count; the DPLC frame count is authoritative."""
    frames = []
    for rel in _offsets(d, off, count=count):
        p = off + rel
        n = _u16(d, p)
        if n > 0x50:
            raise SkError(f"mapping frame at 0x{p:x} claims {n} pieces")
        ps = []
        for k in range(n):
            y, size, tile, x = struct.unpack_from(">bBHh", d, p + 2 + 6 * k)
            ps.append({"y": y, "w": ((size >> 2) & 3) + 1, "h": (size & 3) + 1, "tile": tile & 0x7FF,
                       "pal": (tile >> 13) & 3, "pri": tile >> 15, "hf": (tile >> 11) & 1,
                       "vf": (tile >> 12) & 1, "x": x})
        frames.append(ps)
    return frames


def _table_end(d: bytes, off: int, piece: int, stop: int | None = None, count: int | None = None) -> int:
    return max(off + rel + 2 + piece * _u16(d, off + rel) for rel in _offsets(d, off, stop, count))


def mapping_fits(maps, dplc) -> bool:
    """Every mapping frame uses only the tiles its DPLC frame streams."""
    if len(maps) != len(dplc):
        return False
    for ps, ents in zip(maps, dplc):
        have = sum(n for _, n in ents)
        need = max((pc["tile"] + pc["w"] * pc["h"] for pc in ps), default=0)
        if need > have:
            return False
    return True


def map_targets(d: bytes) -> dict[int, list[int]]:
    """move.l #Map,mappings(a0|a1) targets -> code offsets."""
    out: dict[int, list[int]] = {}
    for m in re.finditer(rb"[\x21\x23]\x7c(....)\x00\x0c", d, re.S):
        v = _u32(m.group(1), 0)
        if 0x200 <= v < len(d) - 2 and not v & 1:
            out.setdefault(v, []).append(m.start())
    return out


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def player_inventory(d: bytes) -> dict:
    disp = player_dispatch(d)
    loaders = find_dplc_loaders(d)
    targets = map_targets(d)
    chars = {}
    for name in ("sonic", "tails", "knuckles"):
        entry = disp[name]
        ld = min((x for x in loaders if 0 <= x["code"] - entry <= 0x40), key=lambda x: x["code"], default=None)
        if ld is None:
            raise SkError(f"no DPLC loader after {name} entry 0x{entry:x}")
        rec = {"load_plc_entry": entry, "loader_code": ld["code"], "vram_byte": ld["vram"],
               "vram_tile": ld["vram"] // 32 if ld["vram"] is not None else None}
        tables = [("plc", ld["plc"])] + [("alt_plc", a) for a in ld.get("alt_plc", [])]
        rec["art"] = {"offset": ld["art"], "in_cart": ld["art"] < CART_SIZE}
        if "extra_art" in ld:
            rec["extra_art"] = {"offset": ld["extra_art"], "from_frame": ld["extra_from_frame"]}
        if ld["plc"] >= len(d):
            rec["status"] = "lock_on_only"
            rec["plc"] = {"offset": ld["plc"], "in_cart": False}
            chars[name] = rec
            continue
        stop = min((a for a in ld.get("alt_plc", []) if a > ld["plc"]), default=None)
        dplc = parse_dplc(d, ld["plc"], stop)
        split = ld.get("extra_from_frame", len(dplc))
        main_tiles = max((t + n for f in dplc[:split] for t, n in f), default=0)
        extra_tiles = max((t + n for f in dplc[split:] for t, n in f), default=0)
        end = _table_end(d, ld["plc"], 2, stop)
        rec["plc"] = {"offset": ld["plc"], "frames": len(dplc), "size": end - ld["plc"],
                      "sha256": _sha(d[ld["plc"]:end]),
                      "max_tiles_per_frame": max(sum(n for _, n in f) for f in dplc),
                      "xref": ld["entry_from"]}
        for kind, off in tables[1:]:
            a = {"offset": off}
            try:
                # same mapping_frame numbering as the default table (Super Sonic)
                alt = parse_dplc(d, off, count=len(dplc))
                e2 = _table_end(d, off, 2, count=len(dplc))
                a.update({"frames": len(alt), "size": e2 - off, "sha256": _sha(d[off:e2]),
                          "art_tiles": max((t + n for f in alt[:split] for t, n in f), default=0)})
            except (SkError, struct.error) as e:
                a["unparsed"] = str(e)
            rec.setdefault("alt_plc", []).append(a)
        rec["art"].update({"tiles": main_tiles, "size": main_tiles * 32})
        if rec["art"]["in_cart"]:
            rec["art"]["sha256"] = _sha(d[ld["art"]:ld["art"] + main_tiles * 32])
        if "extra_art" in rec:
            x = rec["extra_art"]
            x.update({"tiles": extra_tiles, "size": extra_tiles * 32,
                      "sha256": _sha(d[x["offset"]:x["offset"] + extra_tiles * 32])})
        fits = []
        for t, refs in sorted(targets.items()):
            try:
                maps = parse_mappings(d, t, len(dplc))
            except (SkError, struct.error):
                continue
            if mapping_fits(maps, dplc):
                fits.append((t, refs, maps))
        if not fits:
            raise SkError(f"{name}: no mapping table fits the DPLC")
        # characters with look-alike frames: the table set up nearest the loader wins
        fits.sort(key=lambda f: min(abs(r - ld["code"]) for r in f[1]))
        t, refs, maps = fits[0]
        me = _table_end(d, t, 6, count=len(maps))
        rec["mappings"] = {"offset": t, "fitting_tables": len(fits), "frames": len(maps), "size": me - t, "sha256": _sha(d[t:me]),
                           "pieces": sum(len(f) for f in maps), "xrefs": refs[:8], "xref_count": len(refs),
                           "max_pieces_per_frame": max(len(f) for f in maps),
                           "palette_lines": sorted({p["pal"] for f in maps for p in f})}
        aux = AUX.get(name, {})
        for key, (off, size, xref) in aux.items():
            if off + size > len(d):
                continue
            ok = xref + 4 <= len(d) and _u32(d, xref) == off  # xref = the long operand
            rec[key] = {"offset": off, "size": size, "sha256": _sha(d[off:off + size]), "xref": xref,
                        "xref_ok": ok}
        if "anim" in rec and rec["anim"]["size"]:
            rec["anim"]["scripts"] = _u16(d, rec["anim"]["offset"]) // 2
        rec["status"] = "in_cart" if rec["art"]["in_cart"] else "lock_on_only"
        chars[name] = rec
    return {"dispatch": disp["_at"], "characters": chars}


def inventory(src: str | Path) -> dict:
    p = Path(src)
    raw = p.read_bytes()
    d, meta = read_rom(p)
    h = header(d)
    calc = checksum(d)
    ident = {"crc32": f"{zlib.crc32(d) & 0xFFFFFFFF:08x}", "sha1": hashlib.sha1(d).hexdigest(),
             "sha256": _sha(d)}
    if h["serial"] != "GM MK-1563 -00":
        raise SkError(f"not Sonic & Knuckles: serial {h['serial']!r}")
    return {
        "source": {"path": str(p), "sha256": _sha(raw), "size": len(raw), **meta},
        "rom": {**ident, "no_intro_match": ident["crc32"] == NO_INTRO["crc32"] and ident["sha1"] == NO_INTRO["sha1"],
                "layout": "flat", "header": h, "checksum_calc": f"{calc:04x}",
                "checksum_ok": f"{calc:04x}" == h["checksum"]},
        "platform": {"system": "genesis", "cpu": "68000", "core": "genesis_plus_gx",
                     "launch": "RetroArch genesis_plus_gx (gbox.systems genesis row), no BIOS; "
                     "standalone S&K, no lock-on cart attached, so Tails is not selectable"},
        "format_notes": {
            "art": "uncompressed 4bpp 8x8 tiles (32 B), streamed per frame by DPLC to the player VRAM slot",
            "dplc": "u16 offset table; frame = u16 n, n x u16 ((tiles-1)<<12 | first_tile)",
            "mappings": "u16 offset table; frame = u16 n, n x {s8 y, u8 size(w-1<<2|h-1), u16 tile, s16 x}",
            "palette": "one 16-colour line (Genesis 0000BBB0GGG0RRR0), shared line 0 for the player",
        },
        **player_inventory(d),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="S&K (World) player sprite inventory")
    ap.add_argument("src")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = inventory(a.src)
    s = json.dumps(m, indent=1, default=lambda v: v)
    if a.out:
        Path(a.out).write_text(s)
    print(s if not a.out else f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
