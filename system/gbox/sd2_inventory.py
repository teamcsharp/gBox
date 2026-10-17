"""WWF SmackDown! 2 - Know Your Role (USA, PS1): inventory of the exact owned build (favorite queue #1332, stage 1).

Owned source: the HyperSpin CHD `collections/Sony Playstation/roms/WWF SmackDown! 2 - Know Your Role (USA).chd`
(507,482,150 B). It is a CHD **v5** (cdlz/cdzl/cdfl codecs, one MODE2_RAW track of 317,290 frames), which
`gbox.psxdisc.CHD` and `frame_rip.psx_chd_to_bin` (v4 only) cannot read, so `chdman extractcd` is a hard
prerequisite. `yukes_sd.base_bin` caches its output as cache/modbase/<game_id>/<stem>.bin, the image the native
writer copies. The disc is SLUS-01234: ISO9660 volume SLUS_01234, SYSTEM.CNF boots SLUS_012.34, a PS-X EXE with the
SCEA ("North America area") licence string, so NTSC-U.

`inventory(bin_path, chd=...)` only reads. It reports the CHD header and track metadata, SYSTEM.CNF, the PS-X EXE
header, every ISO9660 file (classified by magic and sector submode), each DPAC directory, the wrestler roster with its
head/body/leg model entries (EMD bones/slots/chunks/vertices/primitives and the BPE-packed TIM pages) and the motion
banks of M.PAC.

DPAC directories: "DPAC", u32 table bytes (= 8 + 4 * count), u32 data bytes, u32 7; the table at 0x800 is tag[4],
u16 count, u16 0. Bit 15 of count marks a flat table: count x {u16 id, u16 size in 0x100 units} from 0x808 (EXE, LD,
EV, PRE, DENT, CAW). Without it the 4-byte records may start with ASCII labels {char[4], u32}: ED1H/ED1B/ED1L carry one
("0   ") before their {id, units} records, ED2 two. M.PAC ("MOT ") holds only named records {char[4], u16 sector
index from 0x4000, u16 units}. Entries are stored from 0x4000, each 0x800-aligned. `yukes_sd.dpac_entries` takes the
raw u16 (bit 15 included) as the count and always starts at 0x810. That matches ED1* (checked by the tests), but on
a flat table it reads 32K records from the wrong start (EXE.PAC: 0x800D = 13 overlays). `roster()` still works only
because the first entry always sits at 0x4000 and BPE carries its own length.

    python -m gbox.sd2_inventory IMAGE.bin [--chd SRC.chd] [--out manifest.json] [--tims]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

GAME_ID = "276334ad218ffb46"
TITLE = "WWF SmackDown! 2 - Know Your Role (USA)"
SERIAL = "SLUS-01234"
OWNED_REL_PATH = "collections/Sony Playstation/roms/WWF SmackDown! 2 - Know Your Role (USA).chd"
CORE = "pcsx_rearmed"                      # the catalog's RetroArch core for this entry
REGIONS = {"North America": "NTSC-U", "Europe": "PAL", "Japan": "NTSC-J"}
MAGICS = [(b"DPAC", "dpac"), (b"PS-X EXE", "psx_exe"), (b"BOOT", "system_cnf"), (b"\x60\x01\x01\x80", "str_video"),
          (b"PAC ", "pac"), (b"BPE ", "bpe")]


def sha256_file(path, bs: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(bs):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- CHD container (header + track metadata only)

def chd_header(b: bytes) -> dict:
    """Parse a CHD v4/v5 header (first 124 bytes)."""
    if b[:8] != b"MComprHD":
        raise ValueError("not a CHD")
    hlen, ver = struct.unpack_from(">II", b, 8)
    out: dict = {"version": ver, "header_bytes": hlen}
    if ver == 5:
        out["compressors"] = [c.decode("latin-1") for c in (b[16 + 4 * i:20 + 4 * i] for i in range(4)) if c.strip(b"\0")]
        out["logical_bytes"], out["map_offset"], out["meta_offset"] = struct.unpack_from(">QQQ", b, 32)
        out["hunk_bytes"], out["unit_bytes"] = struct.unpack_from(">II", b, 56)
        out["raw_sha1"], out["sha1"] = b[64:84].hex(), b[84:104].hex()
    elif ver == 4:
        _flags, comp, out["hunks"] = struct.unpack_from(">III", b, 16)
        out["compressors"] = [f"v4:{comp}"]
        out["logical_bytes"], out["meta_offset"] = struct.unpack_from(">QQ", b, 28)
        out["hunk_bytes"] = struct.unpack_from(">I", b, 44)[0]
        out["sha1"], out["raw_sha1"] = b[48:68].hex(), b[88:108].hex()
    return out


def chd_tracks(f, meta_offset: int) -> list[dict]:
    """CD track metadata (CHT2/CHTR entries: u32 tag, u8 flags, u24 length, u64 next, then ASCII KEY:VALUE text)."""
    out, o, seen = [], meta_offset, 0
    while o and seen < 512:
        f.seek(o)
        h = f.read(16)
        if len(h) < 16:
            break
        tag, ln, nxt = h[:4], int.from_bytes(h[5:8], "big"), struct.unpack_from(">Q", h, 8)[0]
        data = f.read(ln)
        if tag in (b"CHT2", b"CHTR"):
            out.append(dict(re.findall(r"(\w+):(\S+)", data.rstrip(b"\0").decode("ascii", "replace"))))
        o, seen = nxt, seen + 1
    return out


def chd_info(path, hash_file: bool = True) -> dict:
    with open(path, "rb") as f:
        info = chd_header(f.read(124))
        info["tracks"] = chd_tracks(f, info.get("meta_offset", 0))
    info["bytes"] = Path(path).stat().st_size
    if hash_file:
        info["sha256"] = sha256_file(path)
    return info


# ---------------------------------------------------------------- boot files

def system_cnf(b: bytes) -> dict:
    out = {}
    for line in b.decode("latin-1").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().upper()] = v.strip()
    m = re.match(r"cdrom0?:\\?([^;]+)(;\d+)?$", out.get("BOOT", ""), re.I)
    out["boot_file"] = m.group(1).lstrip("\\") if m else None
    return out


def psx_exe(b: bytes) -> dict:
    if b[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    pc0, gp0, t_addr, t_size = struct.unpack_from("<4I", b, 0x10)
    sp = struct.unpack_from("<I", b, 0x30)[0]
    licence = b[0x4C:0x800].split(b"\0")[0].decode("latin-1")
    region = next((r for k, r in REGIONS.items() if k in licence), None)
    return {"pc0": hex(pc0), "gp0": hex(gp0), "t_addr": hex(t_addr), "t_size": t_size, "sp": hex(sp),
            "licence": licence, "region": region, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}


# ---------------------------------------------------------------- DPAC directories

def _ascii4(b: bytes) -> bool:
    return len(b) == 4 and all(0x20 <= c < 0x7F for c in b)


def dpac_table(b: bytes) -> dict:
    """{tag, kind: flat|labelled|named|other, count, labels, entries, valid, slack}. entries: {id|name, offset, units}."""
    if b[:4] != b"DPAC":
        raise ValueError("not a DPAC")
    tbytes, dbytes, ver = struct.unpack_from("<III", b, 4)
    raw = struct.unpack_from("<H", b, 0x804)[0]
    n, flat = raw & 0x7FFF, bool(raw & 0x8000)
    out = {"tag": b[0x800:0x804].decode("latin-1"), "count": n, "table_bytes": tbytes, "data_bytes": dbytes,
           "version": ver, "labels": [], "entries": []}
    end = 0x808 + 4 * n
    if 8 + 4 * n != tbytes or end > 0x4000:
        out["kind"] = "other"                  # several top-level directories (C2.PAC: FONT, 2MEN, CSEN, PHTO ...)
        out["top_tags"] = [b[p:p + 4].decode("latin-1") for p in range(0x800, min(0x800 + tbytes, 0x4000), 4)
                           if _ascii4(b[p:p + 4]) and b[p:p + 4].isupper()][:32]
        out["valid"] = None
        return out
    o = 0x808
    if not flat and n % 2 == 0 and n and all(_ascii4(b[p:p + 4]) for p in range(0x808, end, 8)):
        out["kind"] = "named"
        for p in range(0x808, end, 8):
            sec, units = struct.unpack_from("<HH", b, p + 4)
            out["entries"].append({"name": b[p:p + 4].decode("latin-1").strip(), "offset": 0x4000 + sec * 0x800,
                                   "units": units})
    else:
        while not flat and o < end and _ascii4(b[o:o + 4]):
            out["labels"].append([b[o:o + 4].decode("latin-1"), struct.unpack_from("<I", b, o + 4)[0]])
            o += 8
        out["kind"] = "flat" if flat else "labelled"
        pos = 0x4000
        for p in range(o, end, 4):
            eid, units = struct.unpack_from("<HH", b, p)
            if units:
                out["entries"].append({"id": eid, "offset": pos, "units": units})
                pos = (pos + units * 0x100 + 0x7FF) & ~0x7FF
    last = max((e["offset"] + e["units"] * 0x100 for e in out["entries"]), default=0x4000)
    out["slack"] = len(b) - last
    out["valid"] = 0 <= out["slack"] < 0x800 or (out["kind"] == "named" and out["slack"] >= 0)
    out["magics"] = dict(Counter(b[e["offset"]:e["offset"] + 4].hex() for e in out["entries"]).most_common(4))
    return out


# ---------------------------------------------------------------- characters and motions

def _part(files: dict, f: str, ents: list[dict], tims: bool) -> dict:
    from . import yukes_sd as Y
    part = {"costumes": [e["id"] & 15 for e in ents], "entry_ids": [hex(e["id"]) for e in ents],
            "bytes": sum(e["units"] * 0x100 for e in ents)}
    if not ents:
        return part
    e0 = next((e for e in ents if e["id"] & 15 == 0), ents[0])
    items = Y.pac_parse(files[f], e0["offset"])
    part["pac_types"] = sorted(Counter(t for t, _ in items).items())
    emd = Y.emd_parse(next(d for t, d in items if t == 0))
    chunks = [c for c in emd["chunks"] if c]
    prims = [p for c in chunks for p in c["prims"]]
    part["emd"] = {"bytes": len(emd["raw"]), "bones": len(emd["bones"]), "slots": len(emd["slots"]),
                   "descriptors": len(emd["desc"]), "chunks": len(chunks),
                   "vertices": sum(len(v) for c in chunks for _, v in c["groups"]),
                   "triangles": sum(len(i) == 3 for i, _ in prims), "quads": sum(len(i) == 4 for i, _ in prims),
                   "bones_used": sorted({b for c in chunks for b, v in c["groups"] if v})}
    tex = Y.pac_parse(next(d for t, d in items if t == 0x0A))
    part["tims"], part["tims_bpe"] = len(tex), sum(d[:4] == b"BPE " for _, d in tex)
    if tims:
        tt = [Y.tim_parse(Y.bpe_decode(d) if d[:4] == b"BPE " else d) for _, d in tex]
        part["tim_bpp"] = sorted({t["bpp"] for t in tt})
        part["tim_rects"] = [list(t["rect"]) for t in tt]
        part["clut_rows"] = sorted({t["clut_xy"][1] for t in tt if "clut_xy" in t})
    return part


def wrestlers(files: dict[str, bytes], roster: list[dict], tims: bool = False) -> dict:
    """Roster wrestlers -> their ED1H/ED1B/ED1L model groups (BCD roster id << 4 | costume) and costume-0 stats."""
    from . import yukes_sd as Y
    groups: dict[str, dict[int, list]] = {}
    for f in Y.PART_FILES:
        groups[f] = {}
        for e in dpac_table(files[f])["entries"]:
            groups[f].setdefault(e["id"] >> 4, []).append(e)
    rows = []
    for r in sorted(roster, key=lambda r: r["id"]):
        g = Y.bcd(r["id"])
        parts = {f: _part(files, f, groups[f].get(g, []), tims) for f in Y.PART_FILES}
        rows.append({"id": r["id"], "name": r["name"], "special": r.get("special"), "group": hex(g), "parts": parts,
                     "complete": all(p["costumes"] for p in parts.values())})
    known = {Y.bcd(r["id"]) for r in roster}
    other = {f: {"groups": len(gs), "non_roster_below_0x100": sorted(hex(g) for g in gs if g not in known and g < 0x100),
                 "groups_from_0x100": sum(g >= 0x100 for g in gs)} for f, gs in groups.items()}
    return {"wrestlers": rows, "part_files": other}


def motions(m: bytes) -> list[dict]:
    """M.PAC ("MOT ") named motion banks: CH0/CH1 (wrestler motion sets), CAS/LAD/CAGE (match props), 2PLA, WIN, EDIT."""
    out = []
    for e in dpac_table(m)["entries"]:
        body = m[e["offset"]:e["offset"] + e["units"] * 0x100]
        out.append({"name": e["name"], "offset": e["offset"], "bytes": len(body), "head": body[:16].hex(),
                    "bpe": body[:4] == b"BPE "})
    return out


# ---------------------------------------------------------------- the disc

def files_table(rb) -> list[dict]:
    out = []
    for name, (lba, size) in sorted(rb.files.items(), key=lambda kv: kv[1][0]):
        raw = rb.raw(lba)
        head = rb.data(lba)[:8]
        kind = next((k for m, k in MAGICS if head.startswith(m)), None)
        if kind is None:
            kind = "xa_audio" if raw[18] & 0x24 == 0x24 else ("filler" if not any(head) or name.startswith("DMY")
                                                              else "data")
        out.append({"name": name, "lba": lba, "bytes": size, "sectors": (size + 2047) // 2048, "kind": kind,
                    "submode": raw[18]})
    return out


def inventory(bin_path, chd=None, tims: bool = False, hash_chd: bool = True) -> dict:
    from . import yukes_sd as Y
    from .psxdisc import RawBin
    bin_path = Path(bin_path)
    rb = RawBin(bin_path, writable=False)
    try:
        pvd = rb.data(16)
        cnf = system_cnf(rb.read("SYSTEM.CNF"))
        boot = cnf["boot_file"]
        exe = psx_exe(rb.read(boot))
        listing = files_table(rb)
        dpacs = {}
        for f in (x["name"] for x in listing if x["kind"] == "dpac"):
            t = dpac_table(rb.read(f))
            dpacs[f] = {k: v for k, v in t.items() if k != "entries"} | {"used_entries": len(t["entries"])}
        files = {n: rb.read(n) for n in Y.PART_FILES + ("EXE.PAC", "M.PAC")}
    finally:
        rb.close()
    roster = Y.roster(exe=files["EXE.PAC"])
    chars = wrestlers(files, roster, tims=tims)
    src = chd_info(chd, hash_file=hash_chd) if chd else None
    tracks = (src or {}).get("tracks") or []
    out = {
        "game_id": GAME_ID, "title": TITLE,
        "source": {"owned_rel_path": OWNED_REL_PATH, "chd": src, "image": {
            "path": str(bin_path), "bytes": bin_path.stat().st_size, "sectors": bin_path.stat().st_size // 2352,
            "sha256": sha256_file(bin_path)}},
        "disc": {"system_id": pvd[8:40].decode("latin-1").strip(), "volume_id": pvd[40:72].decode("latin-1").strip(),
                 "volume_blocks": struct.unpack_from("<I", pvd, 80)[0], "serial": SERIAL,
                 "system_cnf": cnf, "boot": {"file": boot} | exe, "files": listing},
        "prerequisites": {
            "platform": "psx",
            "platform_evidence": "ISO9660 system id PLAYSTATION; SYSTEM.CNF boots a PS-X EXE with the SCEA licence",
            "region": exe["region"], "emulator": f"RetroArch {CORE} (catalog core)",
            "chd_reader": ("chdman extractcd (CHD v5; gbox.psxdisc.CHD and frame_rip read v4 only)"
                           if (src or {}).get("version") == 5 else "gbox.psxdisc.CHD"),
            "tracks": len(tracks) or None,
            "single_data_track": (len(tracks) == 1 and tracks[0].get("TYPE") == "MODE2_RAW") if tracks else None,
            "writer_image": "single-track MODE2/2352 .bin + .cue (yukes_sd.base_bin copy; files rewritten in place)",
            "bios": "not checked here (pcsx_rearmed falls back to its HLE BIOS)"},
        "dpac": dpacs,
        "characters": {"roster": len(roster), "complete": sum(w["complete"] for w in chars["wrestlers"])} | chars,
        "motions": motions(files["M.PAC"]),
    }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("image", help="raw MODE2/2352 .bin (chdman extractcd output)")
    ap.add_argument("--chd", help="the owned CHD (hashed and its header/track metadata recorded)")
    ap.add_argument("--out")
    ap.add_argument("--tims", action="store_true", help="decode every costume-0 TIM page (slower)")
    a = ap.parse_args(argv)
    inv = inventory(a.image, a.chd, tims=a.tims)
    text = json.dumps(inv, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text)
    c = inv["characters"]
    print(json.dumps({"serial": inv["disc"]["serial"], "boot": inv["disc"]["boot"]["file"],
                      "boot_sha256": inv["disc"]["boot"]["sha256"], "image_sha256": inv["source"]["image"]["sha256"],
                      "chd_sha256": (inv["source"]["chd"] or {}).get("sha256"), "roster": c["roster"],
                      "complete": c["complete"], "motions": [m["name"] for m in inv["motions"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
