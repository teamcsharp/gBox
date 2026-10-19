"""PZLE01 The Legend of Zelda: Collector's Edition (USA, GameCube) - disc inventory.

Owned source: hyperspin library `Nintendo GameCube/roms/Legend of Zelda, The -
Collector's Edition (USA).gcz` (Dolphin GCZ).  The disc contains .tgc
containers holding N64 ROMs; this module verifies the container layout against
the actual files and extracts the two character-relevant ROMs (Ocarina of Time
and Majora's Mask) with full hashes.  OoT reuses gbox.oot_writer knowledge and
MM matches gbox.mm_inventory (the assimilation-fingerprint nearest titles).

Layout discovered (PZLE01):
  * boot.dol: main executable (disc header 0x420, not in the FST).
  * arc/archive_00.arc: RARC-variant menu archive.  Header at 0x20:
    u32 node_count, node_table_offset, file_table_offset, string_table_offset,
    u32 file_count (0x30), u32 string_table_size (0x34).  Node records are
    0x10 bytes: 4-char inline name, u32 flags, u16 name_hash, u16 entry_count,
    u32 first_entry (cumulative, always == sum of previous counts).
    File-table walk (0x14-byte records at 0x20+file_table_offset) is deferred
    to the analysis stage - these are menu UI assets, not characters.
  * tgc/<name>.tgc: emulator blobs (header ~0x40 bytes, entry-like value
    0xae0f38a2) followed by data; the OoT ROM sits RAW (z64) at the tail of
    zelda_ENG_090903.tgc and the MM ROM RAW at a fixed offset inside
    majora_ENG_091003.tgc.  Both are found by magic scan, not by assuming the
    offsets.  retrospec05.tgc holds the OoT Master Quest payload in a codec
    with no magic; its high-entropy regions are reported for analysis.
"""
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

N64_MAGICS = {b"\x80\x37\x12\x40": "z64", b"\x37\x80\x40\x12": "v64", b"\x12\x40\x80\x37": "n32"}

# sha256 -> identity, from the owned PZLE01 disc (crc stored by Nintendo is
# NOT recomputed on these CE builds, so crc_valid is expected False).
KNOWN_ROMS = {
    "00712c4951c3823978898b6e1b7b084ab9b7a1d09ad3189307ca8556ef53c761": {
        "slug": "oot_ce_usa", "title": "THE LEGEND OF ZELDA",
        "note": "Ocarina of Time, CE build (USA); nearest reader gbox.oot_writer"},
    "e951a0cd34c137267a6434c62b97947e62486212aab5dd412e17131428c6e5d5": {
        "slug": "mm_ce_usa", "title": "ZELDA MAJORA'S MASK",
        "note": "Majora's Mask, CE build (USA); nearest reader gbox.mm_inventory"},
}


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class _FlatReader:
    """Random-access reads over a .gcz/.iso with flat memory (per-read cache)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.suffix.lower() == ".gcz":
            from gbox.gcz import GCZ
            self._gcz = GCZ(str(self.path))
            self._plain = None
        else:
            self._gcz = None
            self._plain = open(self.path, "rb")

    def read(self, off: int, n: int) -> bytes:
        if self._gcz is not None:
            out = self._gcz.read(off, n)
            self._gcz._cache.clear()  # keep memory flat over whole-file walks
            return out
        self._plain.seek(off)
        return self._plain.read(n)


def rarc_node_sanity(data: bytes):
    """Validate the PZLE01 RARC-variant header; return node summary or None."""
    if len(data) < 0x40 or data[:4] != b"RARC":
        return None
    nc, noff, foff, soff = struct.unpack_from(">4I", data, 0x20)
    nfiles = struct.unpack_from(">I", data, 0x30)[0]
    strsize = struct.unpack_from(">I", data, 0x34)[0]
    if nc == 0 or nc > 0x4000 or 0x20 + noff + 0x10 * nc > len(data):
        return None
    nodes, total = [], 0
    for i in range(nc):
        name4, unk, hsh, cnt, first = struct.unpack_from(">4sIHHI", data, 0x20 + noff + i * 0x10)
        name = name4.decode("latin-1").rstrip("\0")
        if not name or not all(32 <= ord(c) < 127 for c in name):
            return None
        if first != total:
            return None
        total += cnt
        nodes.append({"name": name, "hash": hsh, "entries": cnt, "first": first})
    return {"nodes": nodes, "file_count": nfiles, "string_table_size": strsize,
            "file_table_offset": foff, "string_table_offset": soff}


def scan_magics(reader, base, size, needles, chunk=1 << 23):
    """Streaming scan for byte needles on 4-byte boundaries; yields (offset, kind)."""
    off = 0
    while off < size:
        blob = reader.read(base + off, min(chunk, size - off))
        for mag, kind in needles.items():
            i = blob.find(mag)
            while i != -1:
                if i % 4 == 0:
                    yield off + i, kind
                i = blob.find(mag, i + 4)
        off += len(blob)


def rom_info(reader, off):
    """Read + validate an N64 ROM header at off; None if not a real ROM."""
    try:
        head = reader.read(off, 0x101000)
    except Exception:
        return None
    if head[:4] != b"\x80\x37\x12\x40":
        return None
    title = head[0x20:0x34].split(b"\0")[0].decode("ascii", "replace").strip()
    if not title or not all(32 <= ord(c) < 127 for c in title):
        return None
    crc1, crc2 = struct.unpack_from(">II", head, 0x10)
    c1 = zlib.crc32(head[0x40:0x1000]) & 0xFFFFFFFF
    c2 = zlib.crc32(head[0x1000:0x101000]) & 0xFFFFFFFF
    return {"offset": off, "title": title, "crc_stored": f"{crc1:08x}/{crc2:08x}",
            "crc_calc": f"{c1:08x}/{c2:08x}", "crc_valid": (c1, c2) == (crc1, crc2)}


def entropy_regions(reader, base, size, block=1 << 20, threshold=0.97):
    """1 MiB-block zlib-ratio entropy map -> list of high-entropy (off, end, mib)."""
    segs = []
    off = 0
    while off < size:
        blob = reader.read(base + off, min(block, size - off))
        segs.append(len(zlib.compress(blob, 1)) / max(1, len(blob)))
        off += len(blob)
    out = []
    i = 0
    while i < len(segs):
        if segs[i] > threshold:
            j = i
            while j < len(segs) and segs[j] > threshold:
                j += 1
            out.append({"offset": i * block, "end": j * block, "mib": j - i})
            i = j
        else:
            i += 1
    return out


def inventory(src, out_dir=None):
    """Full PZLE01 inventory.  src: .gcz (or .iso); out_dir: where to write
    roms/*.z64 + manifest.json (defaults to the source's cache directory)."""
    src = Path(src)
    reader = _FlatReader(src)
    disc_header = reader.read(0, 0x440)
    game_id = disc_header[:6].decode("ascii", "replace")
    title = disc_header[0x20:0x60].split(b"\0")[0].decode("latin-1")

    from gbox.gcdisc import GCDisc
    disc = GCDisc(src)
    files = [{"path": p, "offset": o, "size": s} for p, (o, s) in sorted(disc.files.items())]
    boot = disc.dol()

    tgc = []
    roms = []
    for f in files:
        if not f["path"].startswith("tgc/"):
            continue
        base, size = f["offset"], f["size"]
        hdr = reader.read(base, 0x40)
        entry = {"name": f["path"], "size": size, "header_hex": hdr.hex()}
        for off, kind in scan_magics(reader, base, size, N64_MAGICS):
            info = rom_info(reader, base + off)
            if info is None:
                continue
            info.update(kind=kind, file=f["path"])
            tgc.append(entry)
            roms.append(info)
    tgc = [t[1] for t in {e["name"]: e for e in tgc}.items()]
    seen = {e["name"] for e in tgc}
    for f in files:
        if f["path"].startswith("tgc/") and f["path"] not in seen:
            tgc.append({"name": f["path"], "size": f["size"],
                        "header_hex": reader.read(f["offset"], 0x40).hex()})
    arc_name = "arc/archive_00.arc"
    arc_sanity = None
    if arc_name in disc.files:
        arc_sanity = rarc_node_sanity(disc.read(arc_name))
        if arc_sanity:
            arc_sanity.update(offset=disc.files[arc_name][0], container=arc_name)

    retro = None
    if "tgc/retrospec05.tgc" in disc.files:
        base, size = disc.files["tgc/retrospec05.tgc"]
        retro = {"name": "tgc/retrospec05.tgc", "size": size,
                 "high_entropy_regions": entropy_regions(reader, base, size),
                 "note": "OoT Master Quest payload suspected; codec has no magic - analysis stage"}

    out = {
        "source_path": str(src),
        "game_id": game_id, "title": title,
        "file_count": len(files), "files": files,
        "boot_dol": {"sha256": _sha256(boot), "size": len(boot)},
        "tgc": tgc, "roms": roms, "rarc": arc_sanity,
        "retrospec05": retro,
    }
    h = hashlib.sha256()
    with open(src, "rb") as fh:
        while True:
            b = fh.read(1 << 22)
            if not b:
                break
            h.update(b)
    out["source_sha256"] = h.hexdigest()

    out["identified"] = []
    if out_dir is not None:
        out_dir = Path(out_dir)
        romdir = out_dir / "roms"
        romdir.mkdir(parents=True, exist_ok=True)
        for info in roms:
            known = KNOWN_ROMS.get(_sha256(_read_rom(reader, info)))
            if not known:
                continue
            info.update(slug=known["slug"], note=known["note"])
            data = _read_rom(reader, info)
            p = romdir / f"{known['slug']}.z64"
            p.write_bytes(data)
            info["sha256"] = _sha256(data)
            info["md5"] = hashlib.md5(data).hexdigest()
            info["size"] = len(data)
            info["stored_as"] = str(p)
            out["identified"].append(info)
        (out_dir / "manifest.json").write_text(json.dumps(out, indent=2))
        out["manifest"] = str(out_dir / "manifest.json")
    return out


def _read_rom(reader, info):
    # ROM size: the two CE ROMs are 32 MiB; read the standard ROM span.
    return reader.read(info["offset"], 32 * 1024 * 1024)


def main():
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src:
        raise SystemExit("usage: python -m gbox.pzle_inventory <source.gcz|iso> [out_dir]")
    out_dir = sys.argv[2] if len(sys.argv) > 2 else None
    inv = inventory(src, out_dir)
    print(f"{inv['game_id']} {inv['title']}")
    print(f"source_sha256: {inv['source_sha256']}")
    print(f"boot.dol: {inv['boot_dol']['sha256']} ({inv['boot_dol']['size']} bytes)")
    for r in inv["identified"]:
        print(f"ROM {r['slug']}: {r['title']!r} {r['size']} bytes @ {r['file']}+{r['offset']:#x}")
        print(f"  md5={r['md5']} sha256={r['sha256']}")
        print(f"  crc stored={r['crc_stored']} calc={r['crc_calc']} valid={r['crc_valid']}")
    if inv["rarc"]:
        print("RARC arc/archive_00.arc:", [(n["name"], n["entries"]) for n in inv["rarc"]["nodes"]])
    if inv["retrospec05"]:
        print("retrospec05 HE regions:", [(hex(r["offset"]), r["mib"]) for r in inv["retrospec05"]["high_entropy_regions"][:8]])


if __name__ == "__main__":
    main()
