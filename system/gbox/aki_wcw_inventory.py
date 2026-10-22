"""Owned-build inventory for AKI's WCW games on N64 (#1317): identify the exact ROM, port a gbox.aki_wcw profile to
another regional build of the same game, and list the file table, wrestlers, costumes, part models and textures.

    python -m gbox.aki_wcw_inventory ROM [--base ROM] [--out manifest.json] [--derive]

derive_profile(base, target) works for builds that share the asset set (WCW/nWo Revenge USA NW2E -> Europe NW2P):
it finds the base build's file table in the target, matches every writer patch site with MIPS immediates and jump
targets masked (the instruction stream is the same, only addresses move), and reads each table/slot address from the
target's own lui + immediate pair at the matched cross-references, so no address is assumed from a constant shift.
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

import numpy as np

from . import aki_wcw as W
from . import n64_rom

CODE_RAM = 0x80000400        # the boot segment: ROM 0x1000 -> RAM 0x80000400 (gbox.aki_wcw.Rom.r2r)
IMM16 = frozenset({0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B,
                   0x31, 0x35, 0x39, 0x3D})               # I-type ops whose low half is an immediate / offset
ADDR_KEYS = ("set_tbl", "costume_lists", "head_tbl", "body_tbl", "part_map", "slot_code", "slot_costume", "costume_tbl")
CIC_BOOT = {0x90BB6CB5: "6102/7101", 0x6170A4A1: "6101", 0x0B050EE0: "6103/7103", 0x98BC2C86: "6105/7105",
            0xACC8580A: "6106/7106"}                       # crc32 of the IPL3 boot code (ROM 0x40-0x1000)
BYTE_ORDER = {b"\x80\x37\x12\x40": "z64 (big-endian)", b"\x37\x80\x40\x12": "v64 (byte-swapped)",
              b"\x40\x12\x37\x80": "n64 (word-swapped)"}


def words(rom: bytes, lo: int, hi: int) -> np.ndarray:
    return np.frombuffer(rom[lo:hi], ">u4").astype(np.uint32)


def masked(w: np.ndarray) -> np.ndarray:
    """Instruction words with the address-carrying fields cleared (16-bit immediates, j/jal targets)."""
    op = w >> 26
    m = w.copy()
    m[np.isin(op, list(IMM16))] &= 0xFFFF0000
    m[(op == 2) | (op == 3)] &= 0xFC000000
    return m


def match(base_m: np.ndarray, target_m: np.ndarray, i: int, halves=(6, 10, 16)) -> int | None:
    """Target index of base instruction i, from the first unique masked window around it (None: no unique match)."""
    for h in halves:
        lo, hi = max(0, i - h), min(len(base_m), i + h)
        sig = base_m[lo:hi]
        if not len(sig) or len(sig) > len(target_m):
            return None
        view = np.lib.stride_tricks.sliding_window_view(target_m, len(sig))
        hits = np.nonzero((view == sig).all(1))[0]
        if len(hits) == 1:
            return int(hits[0]) + (i - lo)
        if not len(hits):
            return None
    return None


def imm_addr(hi_word: int, lo_word: int) -> int:
    """The address formed by lui hi_word and the signed 16-bit immediate of lo_word."""
    return (((hi_word & 0xFFFF) << 16) + (((lo_word & 0xFFFF) ^ 0x8000) - 0x8000)) & 0xFFFFFFFF


def lui_refs(w: np.ndarray, wanted: set[int], reach: int = 10) -> dict[int, list[tuple[int, int]]]:
    """{address: [(lui index, user index)]} for lui rX + (load/store/addiu off(rX)) pairs that form a wanted address."""
    out: dict[int, list[tuple[int, int]]] = {}
    for i in np.nonzero((w >> 26) == 0x0F)[0]:
        i = int(i)
        hw = int(w[i])
        rt = (hw >> 16) & 31
        for j in range(i + 1, min(i + reach, len(w))):
            x = int(w[j])
            op = x >> 26
            if op in IMM16 and op != 0x0F and (x >> 21) & 31 == rt:
                a = imm_addr(hw, x)
                if a in wanted:
                    out.setdefault(a, []).append((i, j))
            if op == 0x0F and (x >> 16) & 31 == rt:
                break
    return out


def _key(rom: bytes) -> tuple[str, int]:
    return rom[0x3B:0x3F].decode("ascii", "replace"), rom[0x3F]


def derive_profile(base: bytes, target: bytes, base_key: tuple[str, int] | None = None) -> dict:
    """gbox.aki_wcw profile of target, ported from the profiled base build (raises if they don't share the assets)."""
    p = W.PROFILES[base_key or _key(base)]
    n = p["nfiles"] + 1
    table = base[p["ft"]:p["ft"] + 4 * n]
    ft = target.find(table[:64])
    if ft < 0 or target[ft:ft + 4 * n] != table:
        raise ValueError("the base build's file table isn't in the target ROM (a different asset set)")
    if target.find(table[:64], ft + 1) >= 0:
        raise ValueError("the base build's file table head occurs twice in the target ROM")
    first = p["first"] - (p["ft"] - ft)
    wb, wt = words(base, 0x1000, p["first"]), words(target, 0x1000, first)
    mb, mt = masked(wb), masked(wt)
    r2i = lambda a: (a - CODE_RAM) // 4
    i2r = lambda k: CODE_RAM + 4 * k
    patch = []
    for ram, ins, kind in p["patch"]:
        if int(wb[r2i(ram)]) != ins:
            raise ValueError(f"base ROM code at {ram:#x} is {int(wb[r2i(ram)]):08x}, not {ins:08x}")
        k = match(mb, mt, r2i(ram))
        if k is None:
            raise ValueError(f"patch site {kind} ({ram:#x}) has no unique match in the target code")
        new = int(wt[k])
        same = (new >> 26) == (ins >> 26) if (ins >> 26) in (2, 3) else (new >> 16) == (ins >> 16)
        if not same:
            raise ValueError(f"patch site {kind}: target instruction {new:08x} isn't the base's {ins:08x} op/registers")
        patch.append((i2r(k), new, kind))
    out: dict = dict(p, first=first, ft=ft, patch=patch)
    refs = lui_refs(wb, {p[k] for k in ADDR_KEYS if k in p})
    for k in ADDR_KEYS:
        if k not in p:
            continue
        votes = Counter()
        for i, j in refs.get(p[k], []):
            ti = match(mb, mt, i)
            if ti is not None:
                votes[imm_addr(int(wt[ti]), int(wt[ti + j - i]))] += 1
        if not votes:
            raise ValueError(f"{k}: no cross-reference of {p[k]:#x} matched in the target code")
        addr, nv = votes.most_common(1)[0]
        if 3 * nv < 2 * sum(votes.values()):
            raise ValueError(f"{k}: target cross-references disagree: {dict(votes)}")
        out[k] = addr

    def where(ram: int, step: int) -> int:                 # a unique non-blank 48-byte window of the base data
        for t in range(16):
            o = W.Rom.r2r(ram + step * t)
            s = base[o:o + 48]
            if len(set(s)) <= 4:
                continue
            at = target.find(s, 0x1000, first)
            if at >= 0 and target.find(s, at + 1, first) < 0:
                return at - 0x1000 + CODE_RAM - step * t
        raise ValueError(f"profile strings near {ram:#x} aren't uniquely in the target")
    lo, hi = p["profile_area"]
    out['profile_area'] = name_area(base, target, p, first, where)
    return out


def header(rom: bytes) -> dict:
    u32 = lambda o: struct.unpack_from(">I", rom, o)[0]
    region = chr(rom[0x3E])
    return {"name": rom[0x20:0x34].decode("ascii", "replace").strip(), "code": rom[0x3B:0x3F].decode("ascii", "replace"),
            "rev": rom[0x3F], "region": {"E": "USA", "P": "Europe", "J": "Japan"}.get(region, region),
            "crc1": f"{u32(0x10):08x}", "crc2": f"{u32(0x14):08x}", "entry": f"{u32(0x08):08x}",
            "cic": CIC_BOOT.get(zlib.crc32(rom[0x40:0x1000]), "unknown"), "size": len(rom),
            "sha256_z64": hashlib.sha256(rom).hexdigest(), "md5_z64": hashlib.md5(rom).hexdigest()}


def container(path: Path) -> dict:
    """The owned file as stored (hash, archive members, actual byte order vs. the member's extension)."""
    raw = path.read_bytes()
    out = {"path": str(path), "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            ms = []
            for m in z.infolist():
                with z.open(m) as f:
                    order = BYTE_ORDER.get(f.read(4), "unknown")
                ext = Path(m.filename).suffix.lower().lstrip(".")
                ms.append({"name": m.filename, "size": m.file_size, "crc32": f"{m.CRC:08x}", "byte_order": order,
                           "extension_matches": order.startswith(ext)})
            out["members"] = ms
    else:
        out["byte_order"] = BYTE_ORDER.get(raw[:4], "unknown")
    return out


def wrestlers(rom: bytes) -> list[dict]:
    R = W.Rom(rom)
    out = []
    for w in W.roster(rom):
        cost = []
        for ci in range(len(w["costumes"])):
            parts = W.rest_parts(R, w, ci)
            cost.append({"body": parts["_costume"]["body"], "head": list(parts.get("_head", ())),
                         "parts": {str(k): [v["mid"], v["tex"], v["pal"]] for k, v in parts.items()
                                   if not str(k).startswith("_")}})
        out.append({"code": f"{w['code']:#05x}", "group": w["group"], "member": w["member"], "name": w["name"],
                    "heads": len(w["heads"]), "costumes": cost})
    return out


def inventory(rom: bytes, source: Path | None = None, base: bytes | None = None) -> dict:
    """Manifest of one owned build (and, with a profiled base build, what differs and whether the profile re-derives)."""
    R = W.Rom(rom)
    p = R.p
    raw = R.ft.raw
    ws = wrestlers(rom)
    ids = lambda i: {v[i] for w in ws for c in w["costumes"] for v in c["parts"].values()}
    m = {"build": header(rom), "source": container(source) if source else None, "profile": list(_key(rom)),
         "layout": {"boot": [0x40, 0x1000], "code_rom": [0x1000, p["first"]], "code_ram": CODE_RAM,
                    "assets_rom": [p["first"], p["first"] + max(x & ~1 for x in raw)],
                    "file_table_rom": [p["ft"], p["ft"] + 4 * len(raw)]},
         "file_table": {"files": p["nfiles"], "lzss": sum(1 for x in raw[:-1] if x & 1)},
         "roster": {"wrestlers": len(ws), "costumes": sum(len(w["costumes"]) for w in ws),
                    "unnamed": [w["code"] for w in ws if w["name"].startswith("Wrestler ")],
                    "part_models": len(ids(0)), "textures": len(ids(1)), "palettes": len(ids(2)),
                    "parts_per_body": p["nmodels"], "bodies": p["bodies"]},
         "formats": {"models": "AkiModel (<=127 vertices / faces, int8 xyz + 16 * offset, rest pose)",
                     "textures": "CI4 bodies (16-colour banks) / CI8 heads, RGBA5551 palettes",
                     "animations": "not parsed: a part-model swap keeps the game's own skeleton and animations"},
         "wrestlers": ws}
    if base is not None:
        B = W.Rom(base)
        same = B.ft.raw == raw
        diff = [f for f in range(1, p["nfiles"] + 1) if B.ft.get(f) != R.ft.get(f)] if same else None
        bw = {w["code"]: w for w in wrestlers(base)}
        m["vs_base"] = {"base": header(base), "file_table_equal": same, "files_differing": diff,
                        "names_equal": all(bw.get(w["code"], {}).get("name") == w["name"] for w in ws) and len(bw) == len(ws),
                        "costume_parts_equal": all(bw.get(w["code"], {}).get("costumes") == w["costumes"] for w in ws)}
        try:
            d = derive_profile(base, rom)
            m["vs_base"]["profile_rederived"] = _norm(d) == _norm(p)
        except ValueError as e:
            m["vs_base"]["profile_rederived"] = f"failed: {e}"
    return m


def _norm(p: dict) -> dict:
    return json.loads(json.dumps(p, default=list))


def _hexed(p: dict) -> dict:
    h = lambda v: hex(v) if isinstance(v, int) and v > 9 else v
    return {k: ([[h(x) for x in t] for t in v] if k == "patch" else [h(x) for x in v] if isinstance(v, tuple) else h(v))
            for k, v in p.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.aki_wcw_inventory", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("rom", type=Path)
    ap.add_argument("--base", type=Path, help="an already-profiled build of the same game (e.g. Revenge USA)")
    ap.add_argument("--out", type=Path, help="write the JSON manifest here")
    ap.add_argument("--derive", action="store_true", help="print the profile derived from --base and exit")
    a = ap.parse_args(argv)
    rom = n64_rom.read(a.rom)
    base = n64_rom.read(a.base) if a.base else None
    if a.derive:
        if base is None:
            ap.error("--derive needs --base")
        print(json.dumps(_hexed(derive_profile(base, rom)), indent=1))
        return 0
    m = inventory(rom, a.rom, base)
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
    summary = {k: m[k] for k in ("build", "profile", "layout", "file_table", "roster")} | (
        {"vs_base": {k: v for k, v in m["vs_base"].items() if k != "base"}} if "vs_base" in m else {})
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _find_block(base, target, ram, step, N=256):
    """Find a unique non-blank 48-byte window of `base` (at RAM address `ram`) inside `target`.

    Returns the target RAM address of the same window, or None.  The search
    range is wide because the reference build's region above the name strings
    is often blank, which hides the match from a narrow scan.
    """
    for t in range(N):
        o = W.Rom.r2r(ram + step * t)
        if o < 0 or o + 48 > len(base):
            continue
        s = bytes(base[o:o + 48])
        if len(set(s)) <= 4:
            continue
        at = target.find(s, 0x1000)
        if at >= 0 and target.find(s, at + 1) < 0:
            return at - 0x1000 + CODE_RAM - step * t
    return None


def name_area(base, target, p, first, where=None):
    """Bounds of the target build's name region, derived from the owned bytes."""
    lo, hi = p["profile_area"]
    if where is not None:
        try:
            lo_b, hi_b = where(lo, 0x40), where(hi - 0x40, -0x40)
            return (lo_b & ~0xFFF, (hi_b + 0x40 + 0xFFF) & ~0xFFF)
        except Exception:
            pass
    lo2 = _find_block(base, target, lo, 0x40)
    if lo2 is None:
        raise ValueError("name area: the lower block isn't uniquely in the target")
    hi2 = _find_block(base, target, hi - 0x40, -0x40)
    if hi2 is not None and hi2 > lo2:
        return (lo2 & ~0xFFF, (hi2 + 0x40 + 0xFFF) & ~0xFFF)
    return (lo2 & ~0xFFF, (lo2 + (hi - lo) + 0xFFF) & ~0xFFF)
