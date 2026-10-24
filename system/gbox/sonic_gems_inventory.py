"""Owned-build inventory for Sonic Gems Collection (GameCube) - inbox request #2362.

Reads the operator-owned disc image strictly read-only and emits an authoritative
manifest: exact source identity (sha256 streamed from the file's own bytes), the
GameCube disc header, the ISO9660 member tree, the CRI AFS member tables of every
AFS container on the disc, and a first-bytes magic census.

The AFS header layout used here (little-endian uint32 count followed by
interleaved uint32 offset/size pairs) is the same shape gbox.jgr.afs_entries
parses for Jet Grind Radio; it is re-verified against these owned bytes rather
than assumed.

Nothing in this module writes to the owned source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

SECTOR = 2048
GC_ISO_BASE = 0x8000          # GameCube discs place the ISO9660 area at 0x8000
GC_HEADER_LEN = 0x440
AFS_MAGIC = b"AFS\x00"
ADX_MAGIC = b"ADX\x00"
AFS_NAME_REC = 48            # CRI AFS filename record size used by gbox.jgr
KNOWN_MEMBER_MAGICS = ("PLAY", "PTEX", "main", "EFTX")


def read_at(f, off, n):
    f.seek(off)
    return f.read(n)


def sha256_stream(path, chunk=1 << 20):
    """sha256 of the file's own bytes, streamed (never a reference hash)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def disc_header(path, n=GC_HEADER_LEN):
    with open(path, "rb") as f:
        return f.read(n)


def find_pvd(f):
    """Return (base_offset, pvd_bytes) for the ISO9660 primary volume descriptor."""
    for base in (0, GC_ISO_BASE):
        d = read_at(f, base + 16 * SECTOR, SECTOR)
        if len(d) >= 6 and d[1:6] == b"CD001":
            return base, d
    return None, None


def _dir_entry(buf, i):
    """Parse one ISO9660 directory record (33-byte fixed part + name)."""
    ln = buf[i]
    if ln == 0:
        return None, i
    if ln < 34:
        return None, i + ln
    rec = buf[i:i + ln]
    lba = struct.unpack_from("<I", rec, 2)[0]
    size = struct.unpack_from("<I", rec, 10)[0]
    flags = rec[25]
    nlen = rec[32]
    if nlen == 0:
        nm = "."
    elif nlen == 1 and rec[33] in (0, 1):
        nm = "." if rec[33] == 0 else ".."
    else:
        nm = rec[33:33 + nlen].decode("latin-1").split(";")[0]
    return {"name": nm, "lba": lba, "size": size, "dir": bool(flags & 2)}, i + ln


def walk_iso9660(path, max_entries=20000):
    """Walk the ISO9660 tree of a GameCube disc image -> (base, file entries)."""
    out = []
    with open(path, "rb") as f:
        base, pvd = find_pvd(f)
        if pvd is None:
            raise ValueError("no ISO9660 primary volume descriptor found")
        root = pvd[156:190]
        stack = [("", struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0])]
        seen = set()
        while stack and len(out) < max_entries:
            prefix, dlba, dsize = stack.pop(0)
            key = (dlba, dsize)
            if key in seen:
                continue
            seen.add(key)
            data = read_at(f, base + dlba * SECTOR, dsize)
            i = 0
            while i < len(data):
                ent, nxt = _dir_entry(data, i)
                if ent is None:
                    i = (i // SECTOR + 1) * SECTOR
                    continue
                i = nxt
                if ent["name"] in (".", ".."):
                    continue
                if ent["dir"]:
                    stack.append((prefix + "/" + ent["name"], ent["lba"], ent["size"]))
                else:
                    ent["path"] = (prefix + "/" + ent["name"]).lstrip("/")
                    ent["offset"] = base + ent["lba"] * SECTOR
                    out.append(ent)
    return base, out


def afs_table(f, off, size):
    """Parse a CRI AFS header at off: count, member offsets/sizes, validity."""
    head = read_at(f, off, 8)
    if head[:4] != AFS_MAGIC:
        return None
    count = struct.unpack_from("<I", head, 4)[0]
    if count <= 0 or count > 4096:
        return {"count": count, "offsets": [], "sizes": [], "ok": False,
                "reason": "count out of range", "table_end": 8}
    tbl = read_at(f, off + 8, 8 * count)
    pairs = struct.unpack("<" + "I" * (2 * count), tbl)
    offs = list(pairs[0::2])
    szs = list(pairs[1::2])
    table_end = 8 + 8 * count
    ok = all(o >= table_end and s >= 0 and o + s <= size for o, s in zip(offs, szs))
    return {"count": count, "offsets": offs, "sizes": szs, "ok": ok,
            "table_end": table_end, "name_dir_at": (min(offs) - 8) if offs else None}


def afs_names(f, off, table, limit=64):
    """CRI AFS filename directory (48-byte records) when the archive carries one."""
    at = table.get("name_dir_at")
    if at is None or at < 0:
        return []
    data = read_at(f, off + at, 8)
    if len(data) < 8:
        return []
    noff, nsize = struct.unpack("<II", data)
    if noff < 0 or nsize < AFS_NAME_REC * table["count"]:
        return []
    recs = read_at(f, off + noff, AFS_NAME_REC * table["count"])
    names = []
    for i in range(table["count"]):
        raw = recs[i * AFS_NAME_REC:i * AFS_NAME_REC + 32].split(b"\x00")[0]
        names.append(raw.decode("ascii", "replace"))
    return names[:limit]


def scan_afs(path, entries, per_container=256):
    """For every AFS container on the disc: entry count, members and member magics."""
    results = []
    with open(path, "rb") as f:
        for ent in entries:
            off, size = ent["offset"], ent["size"]
            if size < 8 or size > 512 * 1024 * 1024:
                continue
            if read_at(f, off, 4) != AFS_MAGIC:
                continue
            tbl = afs_table(f, off, size)
            if not tbl:
                continue
            names = afs_names(f, off, tbl)
            members = []
            for i, (mo, ms) in enumerate(zip(tbl["offsets"], tbl["sizes"])):
                if i >= per_container:
                    break
                mb = read_at(f, off + mo, 16) if mo + 16 <= size else b""
                magic = "".join(chr(c) if 32 <= c < 127 else "." for c in mb[:8])
                members.append({"index": i, "offset": mo, "size": ms, "magic": magic,
                                "known": magic[:4] in KNOWN_MEMBER_MAGICS})
            results.append({"container": ent["path"], "container_size": size,
                            "count": tbl["count"], "table_ok": tbl["ok"],
                            "names": names, "members": members})
    return results


def magic_census(path, entries, head=4):
    """First-bytes census over every disc member (playbook: magic-census)."""
    hist = {}
    ext = {}
    with open(path, "rb") as f:
        for e in entries:
            k = os.path.splitext(e["path"])[1].lower()
            ext[k] = ext.get(k, 0) + 1
            b = read_at(f, e["offset"], head)
            key = b[:4].hex() if b else "eof"
            hist[key] = hist.get(key, 0) + 1
    return {"extensions": dict(sorted(ext.items(), key=lambda kv: -kv[1])), "magics": hist}


def adx_candidates(path, entries):
    """CRI ADX wrappers found on the disc."""
    out = []
    with open(path, "rb") as f:
        for e in entries:
            if read_at(f, e["offset"], 4) == ADX_MAGIC:
                out.append({"path": e["path"], "size": e["size"], "offset": e["offset"]})
    return out


def walk_gcm_fst(path):
    """GameCube GCM filesystem (big-endian FST). Header 0x424/0x428 = FST offset/size.

    Real GameCube discs (and NKit images, which keep the FST valid) use this, not
    ISO9660. Returns [{path, offset, size}] with absolute image offsets.
    """
    with open(path, "rb") as f:
        h = read_at(f, 0, GC_HEADER_LEN)
        dol, fst_off, fst_size = struct.unpack(">III", h[0x420:0x42C])
        fs = read_at(f, fst_off, fst_size)
    n = struct.unpack(">I", fs[8:12])[0]
    st = n * 12
    out = []

    def nm(o):
        return fs[st + o:fs.index(b"\0", st + o)].decode("latin-1")

    def rec(i, end, pre):
        while i < end:
            fl = fs[i * 12]
            no = int.from_bytes(fs[i * 12 + 1:i * 12 + 4], "big")
            a, b = struct.unpack(">II", fs[i * 12 + 4:i * 12 + 12])
            if fl:
                rec(i + 1, b, pre + nm(no) + "/")
                i = b
            else:
                out.append({"path": pre + nm(no), "offset": a, "size": b})
                i += 1

    rec(1, n, "")
    out.append({"path": "<boot.dol>", "offset": dol, "size": 0})
    return out, {"dol_offset": dol, "fst_offset": fst_off, "fst_size": fst_size,
                 "fst_entries": n}


def walk_cvm(path, offset, size):
    """CRI CVM wrapper: 'CVMH' header, ISO9660 image begins 0x1800 into it."""
    with open(path, "rb") as f:
        if read_at(f, offset, 4) != b"CVMH":
            return None
        if read_at(f, offset + 0x1800 + 16 * SECTOR + 1, 5) != b"CD001":
            return None
        base = offset + 0x1800
        pvd = read_at(f, base + 16 * SECTOR, SECTOR)
        root = pvd[156:190]
        lba, rsz = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
        files = []

        def walk(lba, sz, pre):
            buf = read_at(f, base + lba * SECTOR, sz)
            i = 0
            while i < len(buf):
                e, nxt = _dir_entry(buf, i)
                if e is None:
                    i = (i // SECTOR + 1) * SECTOR if nxt == i else nxt
                    continue
                i = nxt
                if e["name"] in (".", ".."):
                    continue
                if e["dir"]:
                    walk(e["lba"], e["size"], pre + e["name"] + "/")
                else:
                    files.append({"path": pre + e["name"],
                                  "offset": base + e["lba"] * SECTOR, "size": e["size"]})
        walk(lba, rsz, "")
    return files


def scan_cvms(path, entries):
    out = []
    for e in entries:
        if e["path"].lower().endswith(".cvm"):
            fl = walk_cvm(path, e["offset"], e["size"])
            if fl is not None:
                out.append({"container": e["path"], "file_count": len(fl), "files": fl,
                            "census": magic_census(path, fl)})
    return out


def build_manifest(disc_path, gcz_path=None, expect_sha=None):
    size = os.path.getsize(disc_path)
    header = disc_header(disc_path)
    sha = sha256_stream(disc_path)
    m = {
        "disc_path": disc_path,
        "disc_size": size,
        "disc_sha256": sha,
        "gc_disc_id": header[0:8].decode("latin-1").rstrip("\x00").strip(),
        "game_code": header[0:4].decode("latin-1"),
        "maker_code": header[5:8].decode("latin-1"),
        "disc_number": header[8:10].decode("latin-1"),
        "gc_version": header[9] if len(header) > 9 else None,
        "header_title": header[0x20:0x60].decode("latin-1").split("\x00")[0].strip(),
        "byte_order": "little-endian AFS tables; PowerPC 750 big-endian code in the DOL",
        "expected_sha256_match": (expect_sha is None or expect_sha == sha),
    }
    if gcz_path and os.path.exists(gcz_path):
        m["gcz_path"] = gcz_path
        m["gcz_size"] = os.path.getsize(gcz_path)
        m["gcz_sha256"] = None       # gcz payload is gz-compressed; hash pending
    entries, m["gcm"] = walk_gcm_fst(disc_path)
    m["filesystem"] = "GCM FST (big-endian)"
    m["file_count"] = len(entries)
    m["files"] = [{"path": e["path"], "size": e["size"], "offset": e["offset"]} for e in entries]
    m["afs"] = scan_afs(disc_path, entries)
    m["cvm"] = scan_cvms(disc_path, entries)
    m["adx"] = adx_candidates(disc_path, entries)
    m["census"] = magic_census(disc_path, entries)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--disc", required=True)
    ap.add_argument("--gcz", default=None)
    ap.add_argument("--expect-sha256", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    m = build_manifest(a.disc, a.gcz, a.expect_sha256)
    txt = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(txt)
    print(json.dumps({k: v for k, v in m.items() if k not in ("files", "afs", "cvm", "adx", "census")}, indent=1))
    print("CVM:", [(c["container"], c["file_count"]) for c in m["cvm"]])
    print("AFS containers:", len(m["afs"]))


if __name__ == "__main__":
    main()
