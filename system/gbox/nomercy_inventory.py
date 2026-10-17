"""Owned-build inventory for WWF No Mercy on N64 (AKI engine, #1329): identify the exact ROM, check the
gbox.aki_wrestling NW4E rev 1 profile against the build's own boot code, and list the file table, wrestlers, costumes,
part models, textures and palettes that the native reader (characters "nomercy") and writer (NMWriter) use.

    python -m gbox.nomercy_inventory SRC [--out manifest.json]

SRC is the owned zip / z64 / v64 / n64; it is only read. The profile's file-table offset and id bound are re-read from
the boot segment's lui/addiu and sltiu at the sites the writer patches, and FirstFile from its own lui/addiu pairs, so
another revision fails loudly instead of being parsed with the wrong table.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zipfile
import zlib
from collections import Counter
from pathlib import Path

from . import aki_wrestling as A
from . import n64_rom

CODE_RAM = 0x80000400            # boot segment: ROM 0x1000 -> RAM 0x80000400 (aki_wrestling._ram2rom)
SITES = {"ft_hi": 0x80003ADC, "ft_lo": 0x80003AE0, "bound": 0x80003BD8}   # NMWriter's file-table patch sites
CIC_BOOT = {0x90BB6CB5: "6102/7101", 0x6170A4A1: "6101", 0x0B050EE0: "6103/7103", 0x98BC2C86: "6105/7105",
            0xACC8580A: "6106/7106"}                       # crc32 of the IPL3 boot code (ROM 0x40-0x1000)
BYTE_ORDER = {b"\x80\x37\x12\x40": "z64 (big-endian)", b"\x37\x80\x40\x12": "v64 (byte-swapped)",
              b"\x40\x12\x37\x80": "n64 (word-swapped)"}
REGISTERED = 64                  # characters.DEDICATED "nomercy" roster (aki_wrestling.roster_entries)


def ram2rom(a: int) -> int:
    return a - CODE_RAM + 0x1000


def word(rom: bytes, ram: int) -> int:
    return struct.unpack_from(">I", rom, ram2rom(ram))[0]


def _pair(hi_w: int, lo_w: int) -> int:
    lo = lo_w & 0xFFFF
    if lo_w >> 26 == 0x09:                                 # addiu: sign-extended
        lo -= (lo & 0x8000) << 1
    return (((hi_w & 0xFFFF) << 16) + lo) & 0xFFFFFFFF


def code_refs(rom: bytes) -> dict:
    """The file table's ROM offset (lui a0 / addiu a0) and id bound (sltiu) as 0x80003ab0/0x80003bd0 load them."""
    hi_w, lo_w, b_w = (word(rom, SITES[k]) for k in ("ft_hi", "ft_lo", "bound"))
    rt = (hi_w >> 16) & 31
    ok = (hi_w >> 26 == 0x0F and lo_w >> 26 in (0x09, 0x0D) and (lo_w >> 21) & 31 == rt and b_w >> 26 == 0x0B)
    return {"ok": bool(ok), "ft_rom": _pair(hi_w, lo_w) if ok else None, "entries": (b_w & 0xFFFF) if ok else None,
            "sites": {k: f"{v:#010x}" for k, v in SITES.items()},
            "words": [f"{w:08x}" for w in (hi_w, lo_w, b_w)]}


def imm_pairs(rom: bytes, lo: int, hi: int, reach: int = 8) -> list[tuple[int, int]]:
    """(RAM address of the lui, value) for every lui rX / (addiu|ori) rY, rX pair in ROM [lo, hi)."""
    n = (min(hi, len(rom)) - lo) // 4
    w = struct.unpack_from(f">{n}I", rom, lo)
    out = []
    for i, x in enumerate(w):
        if x >> 26 != 0x0F:
            continue
        rt = (x >> 16) & 31
        for y in w[i + 1:i + 1 + reach]:
            if y >> 26 in (0x09, 0x0D) and (y >> 21) & 31 == rt:
                out.append((CODE_RAM + lo - 0x1000 + 4 * i, _pair(x, y)))
                break
    return out


def lui_pairs(rom: bytes, target: int, lo: int, hi: int, reach: int = 8) -> list[int]:
    """RAM addresses of the lui/addiu (or ori) pairs in ROM [lo, hi) that build `target`."""
    return [a for a, v in imm_pairs(rom, lo, hi, reach) if v == target]


MAGIC = {b"N64 PtrTablesV2": "sound bank .ctl (N64 PtrTablesV2)", b"N64 WaveTables": "sound bank .tbl (N64 WaveTables)"}


def region_refs(rom: bytes, pairs: list[tuple[int, int]], lo: int, hi: int) -> list[dict]:
    """Code-referenced ROM offsets inside [lo, hi): what the boot code DMAs from outside the file table."""
    seen: dict[int, list[int]] = {}
    for a, v in pairs:
        if lo <= v < hi:
            seen.setdefault(v, []).append(a)
    out = []
    for v in sorted(seen):
        kind = next((k for m, k in MAGIC.items() if rom[v:v + len(m)] == m), "data")
        out.append({"rom": f"{v:#x}", "kind": kind, "refs": [f"{a:#010x}" for a in seen[v][:4]]})
    return out


def header(rom: bytes) -> dict:
    u32 = lambda o: struct.unpack_from(">I", rom, o)[0]
    region = chr(rom[0x3E]) if 32 <= rom[0x3E] < 127 else f"{rom[0x3E]:#x}"
    return {"name": rom[0x20:0x34].decode("ascii", "replace").strip(), "code": rom[0x3B:0x3F].decode("ascii", "replace"),
            "rev": rom[0x3F], "region": {"E": "USA", "P": "Europe", "J": "Japan"}.get(region, region),
            "crc1": f"{u32(0x10):08x}", "crc2": f"{u32(0x14):08x}", "entry": f"{u32(0x08):08x}",
            "cic": CIC_BOOT.get(zlib.crc32(rom[0x40:0x1000]), "unknown"), "size": len(rom),
            "sha256": hashlib.sha256(rom).hexdigest(), "md5": hashlib.md5(rom).hexdigest(),
            "sha1": hashlib.sha1(rom).hexdigest()}


def _order(head: bytes) -> str:
    return BYTE_ORDER.get(bytes(head[:4]), "unknown")


def container(path: Path) -> dict:
    """The owned file as stored: its sha256 (the stage source identity) and each member's byte order."""
    path = Path(path)
    raw = path.read_bytes()
    out = {"path": str(path), "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if zipfile.is_zipfile(path):
        ms = []
        with zipfile.ZipFile(path) as z:
            for m in z.infolist():
                with z.open(m) as f:
                    order = _order(f.read(4))
                ext = Path(m.filename).suffix.lower().lstrip(".")
                ms.append({"name": m.filename, "size": m.file_size, "crc32": f"{m.CRC:08x}", "byte_order": order,
                           "extension_matches": order.startswith(ext)})
        out["members"] = ms
    else:
        out["byte_order"] = _order(raw)
    return out


def tex_format(tex: bytes) -> dict:
    """AKI texture header {w-1, h-1, u16 colours, ...} + pixels: CI8 when w*h index bytes follow, else CI4 (w*h/2).
    The size decides, as gbox.aki_wcw.texture_colours does: CI4 headers can count two 16-colour banks (32)."""
    if len(tex) < 8:
        return {"w": 0, "h": 0, "colours": 0, "fmt": "truncated", "size_ok": False}
    w, h, colours = tex[0] + 1, tex[1] + 1, struct.unpack_from(">H", tex, 2)[0]
    if len(tex) >= 8 + w * h:
        fmt = "ci8"
    elif len(tex) >= 8 + (w * h + 1) // 2:
        fmt = "ci4"
    else:
        return {"w": w, "h": h, "colours": colours, "fmt": "truncated", "size_ok": False}
    return {"w": w, "h": h, "colours": colours, "fmt": fmt, "size_ok": True}


def tail_free(rom: bytes, start: int) -> dict:
    tail = rom[start:]
    if not tail:
        return {"from": start, "fill": None, "free": 0, "all_fill": True}
    fill = tail[-1]
    free = len(tail) - len(tail.rstrip(bytes([fill])))
    return {"from": start, "fill": fill, "free": free, "all_fill": free == len(tail)}


def wrestlers(rom: bytes, ft: A.FileTable) -> list[dict]:
    cs = A.costumes(rom, ft)
    names = A.ring_names(rom)
    out = []
    for w in A.roster(rom):
        n = w["number"]
        cost = []
        for ci in range(4):
            c = cs[4 * (n - 1) + ci]
            _bp, cls = A.body_parts(rom, c[0])
            parts = A.part_list_static(rom, n, ci)
            cost.append({"body": c[0], "class": cls, "face": c[29],
                         "face_tex": A.face_tex(rom, c[29]) if c[29] < 0x7F else None,
                         "parts": [[o, *parts[o]] for o in sorted(parts)]})
        try:
            k = A.name_slot(names, w["name"])
            ring = names[3 * k:3 * k + 3]
        except Exception:                                  # noqa: BLE001 - template slots carry no ring name
            k, ring = None, []
        out.append({"number": n, "name": w["name"], "slug": A.slug_of(w["name"]), "registered": n <= REGISTERED,
                    "name_slot": k, "ring_names": ring, "costumes": cost})
    return out


def assets(ft: A.FileTable, ws: list[dict]) -> dict:
    use: dict[str, dict[int, list]] = {"model": {}, "texture": {}, "palette": {}}
    for w in ws:
        for ci, c in enumerate(w["costumes"]):
            for off, m, t, p in c["parts"]:
                for kind, fid in (("model", m), ("texture", t), ("palette", p)):
                    if fid:
                        use[kind].setdefault(fid, []).append([w["number"], ci, off])
    vmax = fmax = 0
    bad_models = []
    for fid in sorted(use["model"]):
        d = ft.get(fid)
        nv, nf = d[1] & 0x7F, d[2] & 0x7F
        if len(d) < 8 + 8 * nv + 3 * nf:
            bad_models.append(fid)
            continue
        vmax, fmax = max(vmax, nv), max(fmax, nf)
    fmts, sizes, odd = Counter(), Counter(), []
    for fid in sorted(use["texture"]):
        f = tex_format(ft.get(fid))
        fmts[f["fmt"]] += 1
        sizes[f"{f['w']}x{f['h']}"] += 1
        if f["fmt"] != "ci8" or not f["size_ok"]:
            odd.append({"id": fid, **f, "uses": len(use["texture"][fid]), "used_by": use["texture"][fid][:8]})
    pal = Counter(len(ft.get(fid)) for fid in use["palette"])
    return {"models": {"count": len(use["model"]), "max_vertices": vmax, "max_faces": fmax,
                       "writer_limits": [A.MAX_V, A.MAX_F], "unparsable": bad_models},
            "textures": {"count": len(use["texture"]), "formats": dict(fmts), "sizes": dict(sizes.most_common()),
                         "not_ci8": odd},
            "palettes": {"count": len(use["palette"]), "byte_sizes": {str(k): v for k, v in sorted(pal.items())}}}


def inventory(rom: bytes, source: Path | None = None) -> dict:
    p = A.profile(rom)                                     # raises for builds with no AKI profile
    if p.get("game") != "nomercy":
        raise ValueError(f"not a No Mercy build: profile {p.get('game')}")
    if A.modded(rom):
        raise ValueError("this ROM is a gBox-written mod (moved file table), not an original build")
    refs = code_refs(rom)
    if not refs["ok"] or refs["ft_rom"] != p["ft"] or refs["entries"] != p["nfiles"] + 1:
        raise ValueError(f"boot code disagrees with the NW4E rev 1 profile: {refs}")
    ft = A.FileTable(rom, p)
    raw = ft.raw
    pairs = imm_pairs(rom, 0x1000, p["first"])
    first_refs = [a for a, v in pairs if v == p["first"]]
    cs_raw = ft.get(p["costumes_fid"])
    ws = wrestlers(rom, ft)
    end = p["first"] + (raw[-1] & ~1)
    ft_end = p["ft"] + 4 * len(raw)
    return {
        "build": header(rom), "source": container(source) if source else None,
        "profile": {"key": ["NW4E", 1], "game": p["game"], "writer": bool(p.get("writer"))},
        "code_refs": {**refs, "first_file_rom": f"{p['first']:#x}",
                      "first_file_refs": [f"{a:#010x}" for a in first_refs]},
        "layout": {"boot": [0x40, 0x1000], "code_rom": [0x1000, p["first"]], "code_ram": f"{CODE_RAM:#x}",
                   "assets_rom": [p["first"], end], "file_table_rom": [p["ft"], ft_end],
                   "after_table": {**tail_free(rom, ft_end),
                                   "code_refs": region_refs(rom, pairs, ft_end, len(rom))}},
        "file_table": {"entries": len(raw), "files": len(raw) - 1, "lzss": sum(1 for x in raw[:-1] if x & 1),
                       "monotonic": all((raw[i] & ~1) <= (raw[i + 1] & ~1) for i in range(len(raw) - 1)),
                       "assets_end_at_table": end == p["ft"]},
        "roster": {"blocks": len(ws), "registered": sum(w["registered"] for w in ws),
                   "unregistered": [w["name"] for w in ws if not w["registered"]], "costumes": 4 * len(ws),
                   "costume_record_bytes": 38, "costume_file_ok": len(cs_raw) == 38 * 4 * len(ws),
                   "body_types": sorted({c["body"] for w in ws for c in w["costumes"]}),
                   "body_classes": sorted({c["class"] for w in ws for c in w["costumes"]}),
                   "ring_name_strings": len(A.ring_names(rom))},
        "parts_layout": {f"{o:#04x}": list(v) for o, v in sorted(A.PARTS.items())},
        "assets": assets(ft, ws),
        "formats": {"container": "AKI file table: u32 (offset from FirstFile) | 1 = Asmik LZSS (00 + 24-bit size)",
                    "models": "AkiModel (int8 xyz + 16 * offset, rest pose, <= 63 vertices / 84 faces for the writer)",
                    "textures": "AKI CI8, or CI4 when only w*h/2 index bytes follow (header may count 2 x 16 "
                                "colour banks) + RGBA5551 palettes",
                    "audio": "libultra sound banks and other code-DMA'd data after the file table (not character data)",
                    "attire": "overlay layers at part list +0xE0..+0x24F, composited at load; not in the static list",
                    "animations": "not parsed: a part swap keeps the game's own skeleton, moves and animations"},
        "launch": {"core": "parallel_n64", "cic": header(rom)["cic"],
                   "stock_ram": "4 MB", "mod_ram": "8 MB (Expansion Pak): gBox mods load the moved file table, hook "
                                                   "and part lists at 0x80700000",
                   "rebuild": "recompute the CIC-6102 header CRCs after any write"},
        "wrestlers": ws,
    }


def summary(m: dict) -> dict:
    return {k: v for k, v in m.items() if k not in ("wrestlers", "parts_layout")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.nomercy_inventory", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("src")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    src = Path(a.src)
    m = inventory(n64_rom.read(src), src)
    if a.out:
        Path(a.out).write_text(json.dumps(m, separators=(",", ":")))
    print(json.dumps(summary(m), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
