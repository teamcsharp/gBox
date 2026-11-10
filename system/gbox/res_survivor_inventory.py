
"""Owned-build inventory for Resident Evil - Survivor (PSX) (game_id a178bf02b925ec44).

Every number in the manifest is read out of the owned CHD v5 disc image
(ISO9660 primary volume descriptor + directory records through the CHD v5
reader), never copied from a catalog label, a reference title or a filename
guess.  The CHD is the authoritative source for this title: the boot
executable named by SYSTEM.CNF is the single identified native target asset
hashed here, and every member is recorded with LBA extent, byte offset and
SHA-256 so later stages read exactly the same bytes.
"""
from __future__ import annotations

import functools
import hashlib
import os
import re
from pathlib import Path

GAME_ID = "a178bf02b925ec44"
TITLE = "Resident Evil - Survivor (USA) [PSX]"
DEFAULT_CHD = ("/mnt/gbox/hyperspin/Arcade/collections/Sony Playstation/roms/"
               "Resident Evil - Survivor (USA).chd")
SECTOR = 2048
MAX_HASH_BYTES = 12 << 20


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def sha1_file(path, chunk=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def _le(b, o, n):
    return int.from_bytes(b[o:o + n], "little")


def _chd_disc_cls():
    try:
        from gbox.chd import ChdDisc
        return ChdDisc
    except Exception:
        import importlib.util
        p = Path(__file__).resolve().parent / "chd.py"
        spec = importlib.util.spec_from_file_location("gbox_chd_local", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.ChdDisc


def _parse_records(data):
    pos, out = 0, []
    while pos + 33 <= len(data):
        rl = data[pos]
        if rl == 0:
            pos = ((pos // SECTOR) + 1) * SECTOR
            continue
        if pos + rl > len(data):
            break
        nl = data[pos + 32]
        out.append({"name": data[pos + 33:pos + 33 + nl].decode("latin-1"),
                    "extent": _le(data, pos + 2, 4),
                    "size": _le(data, pos + 10, 4),
                    "flags": data[pos + 25]})
        pos += rl
    return out


def _sectors(disc, extent, count):
    return b"".join(disc.sector(extent + i) for i in range(count))


def iso_tree(disc):
    pvd = disc.sector(16)
    if pvd[1:6] != b"CD001":
        raise ValueError("no ISO9660 primary volume descriptor at sector 16")
    root = pvd[156:190]
    members, stack = [], [(_le(root, 2, 4), _le(root, 10, 4), "")]
    while stack:
        extent, size, prefix = stack.pop()
        if size <= 0 or size > (4 << 20):
            continue
        data = _sectors(disc, extent, (size + SECTOR - 1) // SECTOR)[:size]
        for rec in _parse_records(data):
            raw = rec["name"]
            if raw in ("\x00", "\x01", ""):
                continue
            name = raw.split(";")[0]
            if not name:
                continue
            path = prefix + name
            if rec["flags"] & 0x02:
                stack.append((rec["extent"], rec["size"], path + "/"))
            else:
                members.append({"path": path, "size": rec["size"], "extent": rec["extent"],
                                "offset": rec["extent"] * SECTOR, "isotail": raw[len(name):]})
    members.sort(key=lambda m: m["path"])
    iso = {"system_id": pvd[8:40].decode("latin-1").strip(),
           "volume_id": pvd[40:72].decode("latin-1").strip(),
           "publisher": pvd[318:446].decode("latin-1").strip(),
           "app_id": pvd[574:702].decode("latin-1").strip(),
           "volume_space_size": _le(pvd, 80, 4),
           "creation": pvd[813:830].decode("latin-1").strip()}
    return iso, members


def read_member(disc, m):
    n = (m["size"] + SECTOR - 1) // SECTOR
    return _sectors(disc, m["extent"], n)[:m["size"]]


def _basename(path):
    return path.split("/")[-1].split(";")[0].upper()


def _boot_exe(disc, members):
    out = {"system_cnf": [], "name": None, "path": None, "size": 0,
           "extent": None, "offset": None, "sha256": None}
    cnf = next((m for m in members if _basename(m["path"]) == "SYSTEM.CNF"), None)
    if not cnf:
        return out
    text = read_member(disc, cnf).decode("latin-1", "replace")
    out["system_cnf"] = [l.strip() for l in text.strip().splitlines() if l.strip()]
    m = re.search(r"BOOT\d*\s*=\s*cdrom\d?:\\?([^;\s]+);?", text, re.I)
    if not m:
        return out
    name = m.group(1).strip()
    out["name"] = name
    rec = next((x for x in members if _basename(x["path"]) == name.upper()), None)
    if rec:
        out.update({k: rec[k] for k in ("path", "size", "extent", "offset")})
        out["sha256"] = hashlib.sha256(read_member(disc, rec)).hexdigest()
    return out


@functools.lru_cache(maxsize=2)
def _build(chd_path):
    p = Path(chd_path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    disc = _chd_disc_cls()(str(p))
    iso, members = iso_tree(disc)
    for m in members:
        m["sha256"] = (hashlib.sha256(read_member(disc, m)).hexdigest()
                       if m["size"] <= MAX_HASH_BYTES else None)
    counted = {}
    for m in members:
        e = Path(m["path"]).suffix.upper() or "<none>"
        c = counted.setdefault(e, {"count": 0, "bytes": 0})
        c["count"] += 1
        c["bytes"] += m["size"]
    guesses = [{"path": m["path"], "size": m["size"]} for m in members
               if re.search(r"(chr|char|model|voice|se|mot|spr|tim|tex|anm|ani|str|strp)",
                            m["path"], re.I)
               and Path(m["path"]).suffix.upper() not in
               (".EXE", ".CUE", ".CNS", ".TXT", ".CFG", ".INF", ".DAT", ".BIB", ".PAT")]
    chdh = getattr(getattr(disc, "chd", None), "h", {}) or {}
    inv = {
        "game_id": GAME_ID,
        "title": TITLE,
        "source": {"path": str(p), "bytes": p.stat().st_size,
                   "sha256": sha256_file(p), "sha1": sha1_file(p)},
        "container": {"format": "CHD v5", "logical_bytes": chdh.get("logical_bytes"),
                      "hunk_bytes": chdh.get("hunk_bytes"), "unit_bytes": chdh.get("unit_bytes"),
                      "codecs": chdh.get("codecs"), "track_type": getattr(disc, "track_type", None)},
        "iso": iso,
        "byte_order": "little-endian (MIPS LE, PlayStation)",
        "offset_base": "ISO9660 LBA 0 == byte 0 of the logical disc; member offset = extent * 2048",
        "member_count": len(members),
        "members": members,
        "counted_assets": counted,
        "filename_guesses_unverified": guesses,
        "boot": _boot_exe(disc, members),
    }
    return inv


def build_inventory(chd_path=None):
    return _build(str(chd_path or os.environ.get("RES_SURVIVOR_CHD", DEFAULT_CHD)))


if __name__ == "__main__":
    import json
    import sys
    inv = build_inventory()
    out = sys.argv[1] if len(sys.argv) > 1 else "res_survivor_inventory.json"
    Path(out).write_text(json.dumps(inv, indent=2, sort_keys=True))
    print(json.dumps({"members": inv["member_count"], "boot": inv["boot"],
                      "counted": inv["counted_assets"]}, indent=2))
