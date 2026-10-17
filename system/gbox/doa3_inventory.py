"""Exact-build inventory for Dead or Alive 3 (USA), original Xbox (game b8edf7040116f3aa).

The catalog labels this game ``windows_native``, but the owned artifact is the HyperSpin
``collections/Microsoft XBOX/roms/Dead or Alive 3 (USA).7z``: one solid LZMA block holding an
extracted Xbox DVD folder (``default.xbe`` + CRI ``.afs`` archives + ``.sfd`` movies + an ``.aix``
stream). It is an Xbox title (Cxbx-Reloaded / xemu class), not a Windows PE.

This module reads the unpacked folder read-only and writes a JSON manifest:

* source identity: the owned 7z sha256 (``source_sha256``) and every member's sha256,
* the ``default.xbe`` header, certificate (title ID / name / region / version), sections
  and linked XDK library versions, decoded with the retail or debug XOR keys,
* every AFS archive's table, CRI name directory and per-entry magic classification, and
* a per-fighter grouping of the ``loadfile.afs`` entries whose names carry a fighter code.

    python -m gbox.doa3_inventory GAME_DIR --source-7z OWNED.7z --out manifest.json

Nothing is modified; a later writer must keep each AFS entry inside its own room (its
size rounded up to the archive's alignment, up to the next entry's offset).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

GAME_ID = "b8edf7040116f3aa"
TITLE = "Dead or Alive 3 (USA)"
CATALOG_PLATFORM = "windows_native"
ACTUAL_PLATFORM = "xbox"

XBE_MAGIC = b"XBEH"
# (entry-point key, kernel-thunk key) per XBE build type
XBE_KEYS = {"retail": (0xA8FC57AB, 0x5B6D40B6), "debug": (0x94859D4B, 0xEFB1F152),
            "chihiro": (0x40B5C16E, 0x2290059D)}
REGIONS = {0x1: "NA", 0x2: "JP", 0x4: "ROW", 0x80000000: "MFG"}

# DOA3 roster (15 selectable fighters plus the boss Omega, Genra's transformed form); codes are
# filled from the archive names by ``fighter_groups`` and never assumed.
ROSTER = ["Kasumi", "Ayane", "Hitomi", "Leifang", "Tina", "Helena", "Christie", "Ryu Hayabusa",
          "Jann Lee", "Zack", "Bass", "Gen Fu", "Brad Wong", "Bayman", "Ein", "Omega"]


def sha256_file(path: str | Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


# ----------------------------------------------------------------------------- XBE

def _wstr(b: bytes) -> str:
    return b.decode("utf-16-le", "replace").split("\x00", 1)[0]


def _cstr(b: bytes, off: int, limit: int = 64) -> str:
    if not 0 <= off < len(b):
        return ""
    return b[off:off + limit].split(b"\x00", 1)[0].decode("latin-1")


def parse_xbe(data: bytes) -> dict:
    """Header, certificate, sections and library versions of an Xbox XBE image."""
    if len(data) < 0x178 or data[:4] != XBE_MAGIC:
        raise ValueError(f"not an XBE (magic {data[:4]!r})")
    u = lambda o: struct.unpack_from("<I", data, o)[0]  # noqa: E731
    base = u(0x104)
    if base != 0x10000:
        raise ValueError(f"unexpected XBE base address {base:#x}")
    rel = lambda va: va - base  # noqa: E731  (headers are mapped 1:1 from the file start)
    hdr_size = u(0x108)
    if hdr_size > len(data):
        raise ValueError("XBE header size exceeds the file")
    ep_raw, thunk_raw = u(0x128), u(0x158)
    kind, ep, thunk = None, None, None
    for name, (k_ep, k_th) in XBE_KEYS.items():
        e, t = ep_raw ^ k_ep, thunk_raw ^ k_th
        if base <= e < base + u(0x10C) and base <= t < base + u(0x10C):
            kind, ep, thunk = name, e, t
            break
    if kind is None:
        raise ValueError("XBE entry point/thunk do not decode with a known key")
    c = rel(u(0x118))
    if not 0 < c < hdr_size:
        raise ValueError("XBE certificate outside the header")
    cu = lambda o: struct.unpack_from("<I", data, c + o)[0]  # noqa: E731
    tid = cu(0x08)
    region = cu(0xA0)
    cert = {
        "size": cu(0x00), "timedate": cu(0x04), "title_id": f"{tid:08X}",
        "title_code": f"{chr(tid >> 24 & 0xFF)}{chr(tid >> 16 & 0xFF)}-{tid & 0xFFFF:03d}",
        "title_name": _wstr(data[c + 0x0C:c + 0x5C]), "allowed_media": f"{cu(0x9C):08X}",
        "game_region": f"{region:08X}",
        "regions": [n for bit, n in REGIONS.items() if region & bit],
        "game_ratings": cu(0xA4), "disk_number": cu(0xA8), "version": cu(0xAC),
    }
    nsec, sec_va = u(0x11C), rel(u(0x120))
    sections = []
    for i in range(nsec):
        o = sec_va + 0x38 * i
        if o + 0x38 > hdr_size:
            raise ValueError("XBE section table outside the header")
        flags, va, vsz, raw, rsz, name_va = struct.unpack_from("<6I", data, o)
        if raw + rsz > len(data):
            raise ValueError(f"XBE section {i} raw data outside the file")
        sections.append({"name": _cstr(data, rel(name_va)), "flags": flags, "va": va,
                         "vsize": vsz, "raw": raw, "rsize": rsz,
                         "sha256": hashlib.sha256(data[raw:raw + rsz]).hexdigest()})
    libs = []
    nlib, lib_va = u(0x160), u(0x164)
    for i in range(nlib if lib_va else 0):
        o = rel(lib_va) + 0x10 * i
        if o + 0x10 > hdr_size:
            break
        nm = data[o:o + 8].split(b"\x00", 1)[0].decode("latin-1")
        major, minor, build, fl = struct.unpack_from("<4H", data, o + 8)
        libs.append({"name": nm, "version": f"{major}.{minor}.{build}", "flags": fl})
    return {"type": kind, "base": base, "header_size": hdr_size, "image_size": u(0x10C),
            "timedate": u(0x114), "entry_point": f"{ep:#010x}", "kernel_thunk": f"{thunk:#010x}",
            "certificate": cert, "sections": sections, "libraries": libs}


# ----------------------------------------------------------------------------- AFS

def afs_table(head: bytes, archive_size: int | None = None) -> dict:
    """AFS header: entry (offset, size) pairs and the CRI name-directory pair."""
    if len(head) < 8 or head[:4] != b"AFS\x00":
        raise ValueError(f"not an AFS archive (magic {head[:4]!r})")
    n = struct.unpack_from("<I", head, 4)[0]
    if len(head) < 16 + 8 * n:
        raise ValueError(f"AFS header truncated: {n} entries need {16 + 8 * n} bytes")
    tab = struct.unpack_from(f"<{2 * n}I", head, 8)
    offs, sizes = list(tab[0::2]), list(tab[1::2])
    prev = 0
    for i, (o, z) in enumerate(zip(offs, sizes)):
        if z and o < prev:
            raise ValueError(f"AFS entry {i} overlaps the previous entry")
        if archive_size is not None and o + z > archive_size:
            raise ValueError(f"AFS entry {i} extends outside the archive")
        if z:
            prev = o + z
    nd = struct.unpack_from("<II", head, 8 + 8 * n)
    name_dir = tuple(nd) if nd[1] == 48 * n and nd[0] else None
    return {"count": n, "offsets": offs, "sizes": sizes, "name_dir": name_dir}


def afs_names(blob: bytes, n: int) -> list[dict]:
    """CRI 48-byte name records: name[32], u16 y/m/d/h/m/s, u32 size."""
    if len(blob) < 48 * n:
        raise ValueError("AFS name directory truncated")
    out = []
    for i in range(n):
        r = blob[48 * i:48 * i + 48]
        y, mo, d, h, mi, s = struct.unpack_from("<6H", r, 32)
        out.append({"name": r[:32].split(b"\x00", 1)[0].decode("latin-1"),
                    "date": f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}",
                    "size": struct.unpack_from("<I", r, 44)[0]})
    return out


def entry_rooms(offs: list[int], sizes: list[int], archive_size: int,
                barriers: tuple[int, ...] = ()) -> list[int]:
    """Bytes each entry may occupy without moving another: up to the next entry's offset,
    a barrier (e.g. the CRI name directory) or the archive end. Empty entries get 0."""
    starts = sorted({o for o, z in zip(offs, sizes) if z} | set(barriers) | {archive_size})
    room = [0] * len(offs)
    for i, (o, z) in enumerate(zip(offs, sizes)):
        if z:
            room[i] = next(s for s in starts if s > o) - o
    return room


def sniff(head: bytes) -> str:
    """Short magic/class for an archive entry (printable 4CC, known codecs, else hex)."""
    if not head:
        return "empty"
    if head[:4] == b"AFS\x00":
        return "AFS"
    if head[:4] in (b"XPR0", b"XPR1", b"XPR2"):
        return head[:4].decode()
    if head[:4] == b"RIFF":
        return "RIFF:" + head[8:12].decode("latin-1", "replace")
    if head[:2] == b"\x78\x9c" or head[:2] == b"\x78\xda":
        return "zlib"
    if head[:4] == b"DDS ":
        return "DDS"
    m = head[:4]
    if len(m) == 4 and all(0x20 <= c < 0x7F for c in m):
        return m.decode()
    return "hex:" + head[:4].hex()


def read_afs(path: str | Path, sniff_bytes: int = 16) -> dict:
    p = Path(path)
    size = p.stat().st_size
    with open(p, "rb") as f:
        head = f.read(16)
        n = struct.unpack_from("<I", head, 4)[0] if head[:4] == b"AFS\x00" else 0
        f.seek(0)
        head = f.read(16 + 8 * n)
        t = afs_table(head, size)
        names = None
        nd = t["name_dir"]
        if nd is None and t["count"] and t["offsets"][0] >= 8:
            # CRI layout: the pair sits in the 8 bytes before the first entry
            f.seek(t["offsets"][0] - 8)
            o, z = struct.unpack("<II", f.read(8))
            if z == 48 * t["count"] and o + z <= size:
                nd = (o, z)
        if nd and nd[0] + nd[1] <= size:
            f.seek(nd[0])
            names = afs_names(f.read(nd[1]), t["count"])
        entries = []
        rooms = entry_rooms(t["offsets"], t["sizes"], size, (nd[0],) if nd else ())
        for i, (o, z) in enumerate(zip(t["offsets"], t["sizes"])):
            f.seek(o)
            h = f.read(min(z, sniff_bytes))
            e = {"index": i, "offset": o, "size": z, "room": rooms[i], "magic": sniff(h)}
            if names:
                e["name"] = names[i]["name"]
                e["date"] = names[i]["date"]
                if names[i]["size"] != z:
                    e["name_size_mismatch"] = names[i]["size"]
            entries.append(e)
    return {"file": p.name, "size": size, "count": t["count"],
            "name_dir": list(nd) if nd else None,
            "magics": dict(Counter(e["magic"] for e in entries).most_common()),
            "entries": entries}


_CODE = re.compile(r"^([A-Za-z]{2,4})[_\-]?(?:\d|[A-Za-z_]|$)")


def fighter_groups(entries: list[dict], codes: list[str] | None = None) -> dict[str, list[str]]:
    """Group named entries by leading letter code (e.g. ``KAS_C01.xpr`` -> ``KAS``).

    When ``codes`` is given, only those prefixes are kept; otherwise every prefix with at
    least two entries is returned so the analysis stage can map codes to fighters.
    """
    g: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        nm = e.get("name")
        if not nm:
            continue
        stem = nm.rsplit(".", 1)[0]
        if codes:
            for c in codes:
                if stem.upper().startswith(c.upper()):
                    g[c].append(nm)
                    break
            continue
        m = _CODE.match(stem)
        if m:
            g[m.group(1).upper()].append(nm)
    return {k: sorted(v) for k, v in sorted(g.items()) if codes or len(v) >= 2}


def xpr_header(head: bytes) -> dict:
    """XPR0 packed-resource header: total size, header (resource) size and the first
    resource. DOA3 costume XPRs start with a user-data resource (type 0x80000000) tagged
    ``MDL`` that holds the model, followed by D3D texture resources."""
    if len(head) < 0x20 or head[:4] != b"XPR0":
        raise ValueError(f"not an XPR0 resource (magic {head[:4]!r})")
    total, hsize = struct.unpack_from("<II", head, 4)
    if not 12 <= hsize <= total:
        raise ValueError("XPR0 header size outside the resource")
    rtype, rsize = struct.unpack_from("<II", head, 12)
    tag = head[20:24].split(b"\x00", 1)[0].decode("latin-1") if rtype == 0x80000000 else None
    return {"total": total, "header_size": hsize, "first_type": f"{rtype:08X}",
            "first_size": rsize if rtype == 0x80000000 else None, "first_tag": tag}


def fighter_families(entries: list[dict]) -> list[dict]:
    """Fighter families from the loadfile.afs layout.

    Each family starts with ``<nick>.bin`` immediately followed by a ``.mot`` (the
    nickname bank, e.g. ``kasumi.bin`` + ``kasumi.mot`` + ``m_kasumi.mot``) and owns the
    ``<code>NN.xpr`` / ``<code>NN.cat`` costume pairs that follow it up to the next family.
    Display names are NOT assigned here: several nicknames (karate, ninja, koryu, suiken,
    gokei, chin, sambo, bosnin, hika) need the executable's select table to map.
    """
    live = [e for e in entries if e.get("name") and e.get("magic") not in ("wwww", "empty")]
    fams: list[dict] = []
    cur = None
    for k, e in enumerate(live):
        nm = e["name"]
        nxt = live[k + 1]["name"] if k + 1 < len(live) else ""
        if nm.endswith(".bin") and nxt.endswith(".mot") and not nm.startswith("anime"):
            cur = {"nick": nm[:-4], "bin": e["index"], "mot": [], "costumes": {}}
            fams.append(cur)
            continue
        if cur is None:
            continue
        if nm.endswith(".mot") and not nm.startswith("t_") and not cur["costumes"]:
            cur["mot"].append(nm)
            continue
        m = re.fullmatch(r"([a-z]{3})(\d{2})\.(xpr|cat)", nm)
        if m:
            c = cur["costumes"].setdefault(m.group(1) + m.group(2), {})
            c[m.group(3)] = e["index"]
            continue
        if nm.endswith(".bin") or nm.startswith(("t_", "stg")):
            cur = None
    for f in fams:
        codes = sorted({c[:3] for c in f["costumes"]})
        f["code"] = codes[0] if len(codes) == 1 else (codes or None)
        f["complete_costumes"] = sorted(c for c, v in f["costumes"].items() if {"xpr", "cat"} <= set(v))
    return fams


# ----------------------------------------------------------------------------- build

def build(game_dir: str | Path, *, source_7z: str | Path | None = None,
          source_sha256: str | None = None, hashes: dict[str, str] | None = None) -> dict:
    d = Path(game_dir)
    xbe_path = d / "default.xbe"
    if not xbe_path.is_file():
        raise FileNotFoundError(f"{xbe_path} missing: not an extracted Xbox title folder")
    if source_7z and not source_sha256:
        source_sha256 = sha256_file(source_7z)
    files = []
    for p in sorted(d.iterdir()):
        if p.is_file():
            files.append({"name": p.name, "size": p.stat().st_size,
                          "sha256": (hashes or {}).get(p.name) or sha256_file(p)})
    xbe = parse_xbe(xbe_path.read_bytes())
    archives = {}
    for p in sorted(d.glob("*.afs")):
        archives[p.name] = read_afs(p)
    lf = archives.get("loadfile.afs")
    groups = fighter_groups(lf["entries"]) if lf else {}
    fams = fighter_families(lf["entries"]) if lf else []
    if lf and fams:
        by_index = {e["index"]: e for e in lf["entries"]}
        with open(d / "loadfile.afs", "rb") as f:
            for fam in fams:
                for cos in fam["costumes"].values():
                    if "xpr" in cos:
                        e = by_index[cos["xpr"]]
                        f.seek(e["offset"])
                        try:
                            cos["xpr_header"] = xpr_header(f.read(0x40))
                        except ValueError as exc:
                            cos["xpr_header"] = {"error": str(exc)}
    return {
        "game_id": GAME_ID, "title": TITLE,
        "catalog_platform": CATALOG_PLATFORM, "actual_platform": ACTUAL_PLATFORM,
        "platform_note": "HyperSpin 'Microsoft XBOX' collection; default.xbe is an Xbox XBE, "
                         "not a Windows PE. Needs an Xbox emulator (Cxbx-Reloaded runs the "
                         "folder; xemu needs an XISO rebuilt from it).",
        "source": {"path": str(source_7z) if source_7z else None, "sha256": source_sha256},
        "files": files,
        "xbe": xbe,
        "archives": {k: {kk: vv for kk, vv in v.items() if kk != "entries"}
                     for k, v in archives.items()},
        "loadfile_entries": lf["entries"] if lf else [],
        "loadfile_code_groups": groups,
        "fighter_families": fams,
        "counts": {"families": len(fams),
                   "families_with_costumes": sum(1 for f in fams if f["complete_costumes"]),
                   "costumes": sum(len(f["complete_costumes"]) for f in fams),
                   "xpr_with_mdl": sum(1 for f in fams for c in f["costumes"].values()
                                       if c.get("xpr_header", {}).get("first_tag") == "MDL")},
        "movies": sorted(f["name"] for f in files if f["name"].endswith(".sfd")),
        "roster_expected": ROSTER,
    }


# --------------------------------------------------------------------------- Cxbx-Reloaded unlock
#
# DOA3 on Cxbx-Reloaded uses a save-file unlock, not a memory patch.  The Xbox
# save (``UDATA``) lives in the emulator's save directory and is a binary blob
# that the game reads at the character-select screen.  The unlock path is:
#
#   1.  Pin the exact XBE (title ID ``B8EDF704``) so we know which save layout
#       we are targeting.
#   2.  Locate the existing save in the Cxbx-Reloaded save directory
#       (``<save_root>/UDATA/<profile>/``).
#   3.  Plan a save-file write that sets every character slot to "owned"
#       and every stage / item / bonus to "unlocked".
#   4.  The actual write is performed by a Cxbx-Reloaded save-editor helper
#       (``cxbx_save_editor``), invoked through the existing
#       ``start_job`` / ``get_job`` remote path on the designated worker.
#
# This function only *plans*; it does not write the save.  A later writer
# must keep every write inside the save's own room and must back up the
# original save before the first write.


DOA3_TITLE_ID = "B8EDF704"
DOA3_UNLOCK_PROFILE = "doa3-cxbx-save-unlock-v1"


def cxbx_unlock_plan(
    game: dict,
    worker: dict,
    *,
    session_id: str = "",
    save_root: str = "",
    allow_save_upgrade: bool = False,
) -> dict:
    """Plan the Cxbx-Reloaded DOA3 save-unlock job.

    Parameters
    ----------
    game:
        Catalog game record; must carry ``game_id == GAME_ID`` and
        ``platform == "xbox"``.
    worker:
        Worker record; must target the designated testing worker
        (``i9-NUC`` or ``sparkDeux`` — never ``JAYBUILTFINALE``).
    session_id:
        Optional live session id; required for the live write job.
    save_root:
        Root directory of the Cxbx-Reloaded save partition.  When empty the
        planner marks the plan as ``save_root_required`` and refuses to emit
        a write job.
    allow_save_upgrade:
        Must be ``True`` to get a write job; the save is modified.

    Returns a dict with ``status``, ``profile``, ``jobs`` (empty until all
    prerequisites are met), and ``reason``.  No jobs are dispatched.
    """
    # --- gate: exact game identity ----------------------------------------
    if game.get("game_id") != GAME_ID or game.get("platform") != "xbox":
        return {
            "status": "unsupported_game",
            "profile": None,
            "jobs": [],
            "reason": f"DOA3 Cxbx unlock requires exact game_id={GAME_ID!r} on xbox; got {game.get('game_id')!r}/{game.get('platform')!r}.",
        }

    # --- gate: designated testing worker ------------------------------------
    allowed_workers = {"i9-nuc", "sparkdeux"}
    wname = (worker.get("name") or "").casefold()
    if wname not in allowed_workers:
        return {
            "status": "wrong_worker",
            "profile": None,
            "jobs": [],
            "reason": f"DOA3 Cxbx unlock must target i9-NUC or sparkDeux; got {wname!r}. Never target the operator play PC.",
        }

    # --- gate: save upgrade opt-in ------------------------------------------
    if not allow_save_upgrade:
        return {
            "status": "save_upgrade_opt_in_required",
            "profile": DOA3_UNLOCK_PROFILE,
            "jobs": [],
            "reason": "DOA3 save unlock modifies the save file; explicit allow_save_upgrade=True is required.",
        }

    # --- gate: save root ----------------------------------------------------
    if not save_root:
        return {
            "status": "save_root_required",
            "profile": DOA3_UNLOCK_PROFILE,
            "jobs": [],
            "reason": "save_root (Cxbx-Reloaded save partition directory) is required before a write job can be planned.",
        }

    # --- gate: live session for the write ------------------------------------
    if not session_id:
        return {
            "status": "session_required",
            "profile": DOA3_UNLOCK_PROFILE,
            "jobs": [],
            "reason": "A live Cxbx-Reloaded session_id is required to plan the save-write job. Launch the game first, then call cxbx_unlock_plan with the returned session id.",
        }

    # --- plan the jobs -------------------------------------------------------
    common = {
        "require_worker": worker["id"],
        "agent_use": True,
        "parent_request_id": None,
    }
    backup_job = common | {
        "tool": "doa3_cxbx_save",
        "input": {
            "op": "backup_save",
            "save_root": save_root,
            "title_id": DOA3_TITLE_ID,
            "session_id": session_id,
        },
    }
    write_job = common | {
        "tool": "doa3_cxbx_save",
        "input": {
            "op": "unlock_all",
            "save_root": save_root,
            "title_id": DOA3_TITLE_ID,
            "session_id": session_id,
            "chars": list(ROSTER),
        },
    }
    verify_job = common | {
        "tool": "doa3_cxbx_save",
        "input": {
            "op": "verify_unlock",
            "save_root": save_root,
            "title_id": DOA3_TITLE_ID,
            "session_id": session_id,
        },
    }
    return {
        "status": "planned",
        "profile": DOA3_UNLOCK_PROFILE,
        "jobs": [backup_job, write_job, verify_job],
        "executed": False,
        "roster": list(ROSTER),
        "audio_policy": "agent_use on the designated worker enforces 2% volume",
        "save_policy": "Original save is backed up before the first write; the write is monotonic (only upgrades slots).",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("game_dir")
    ap.add_argument("--source-7z")
    ap.add_argument("--source-sha256")
    ap.add_argument("--hashes", help="sha256sum-format file for the folder members")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    hashes = None
    if a.hashes:
        hashes = {}
        for line in Path(a.hashes).read_text().splitlines():
            if line.strip():
                h, n = line.split(None, 1)
                hashes[n.lstrip("*")] = h
    m = build(a.game_dir, source_7z=a.source_7z, source_sha256=a.source_sha256, hashes=hashes)
    s = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(s)
    else:
        sys.stdout.write(s + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
