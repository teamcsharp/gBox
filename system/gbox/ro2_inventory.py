"""Resident Evil Outbreak File #2 (USA) (PS2, SLUS-209.84): owned-source manifest.

Owned source (read-only, never modified): the HyperSpin library CHD
``Arcade/collections/Sony PlayStation 2/roms/USA/Resident Evil Outbreak File #2 (USA).chd``
- MAME CHD v5 (chdman ``createcd``), single MODE1 track, codecs cdlz/cdzl/cdfl,
  logical size 5,591,427,840 bytes = 2,284,080 x 2448-byte frames,
  hunk 19,584 bytes, unit 2,448 bytes, file 3,490,296,061 bytes.

The container is ISO9660.  ``gbox.chd.ChdDisc`` (CHD v5, CD type) opens it and walks
the directory tree; ``gbox.psxdisc.CHD`` is v4-only and used to reject this image
with ``NotImplementedError: CHD v5 not supported (v4 only)`` - the recorded
assimilate blockers (receipts 4e4a4bf68cb44069 / 6d76c768beb24f90).

Every number here is measured from the owned bytes: the CHD sha256 is streamed
from the file, member sizes come from the ISO9660 directory records and the
executable identity from its own ELF header.  A filename never counts as an asset.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path

from .chd import ChdDisc

SOURCE_RELATIVE = ("Arcade/collections/Sony PlayStation 2/roms/USA/"
                   "Resident Evil Outbreak File #2 (USA).chd")
GAME_ID = "e4513639538846c4"
EXPECTED_CHD_SIZE = 3490296061
EXPECTED_LOGICAL = 5591427840
EXPECTED_EXE = "SLUS_209.84"
EXPECTED_EXE_SIZE = 1482432
HEAD_SNIFF_LIMIT = 4 << 20


def sha256_file(path, chunk: int = 8 << 20) -> str:
    """Stream a file's bytes and return its sha256 (no reference hash is copied)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def parse_chd_header(raw: bytes) -> dict:
    """Independent big-endian parse of the 124-byte MAME CHD header (v4/v5)."""
    if len(raw) < 124 or raw[:8] != b"MComprHD":
        raise ValueError("not a CHD header")
    hlen, version = struct.unpack_from(">II", raw, 8)
    codecs = [raw[16 + 4 * i:20 + 4 * i].decode("ascii", "replace") for i in range(4)]
    logical, map_off, meta_off = struct.unpack_from(">QQQ", raw, 32)
    hunk_bytes, unit_bytes = struct.unpack_from(">II", raw, 56)
    return {"header_bytes": hlen, "version": version, "codecs": codecs,
            "logical_bytes": logical, "map_offset": map_off, "meta_offset": meta_off,
            "hunk_bytes": hunk_bytes, "unit_bytes": unit_bytes,
            "sha1": raw[64:84].hex(), "data_sha1": raw[84:104].hex()}


def elf_info(head: bytes) -> dict | None:
    """Parse an ELF32 header (the PS2 disc executable is little-endian MIPS)."""
    if len(head) < 52 or head[:4] != b"\x7fELF":
        return None
    ei_class, ei_data = head[4], head[5]
    if ei_class != 1:
        return None
    end = ">" if ei_data == 2 else "<"
    e_type, e_machine = struct.unpack_from(end + "HH", head, 16)
    (e_entry,) = struct.unpack_from(end + "I", head, 24)
    (e_phnum,) = struct.unpack_from(end + "H", head, 44)
    return {"ei_class": ei_class, "ei_data": ei_data,
            "byte_order": "big" if ei_data == 2 else "little",
            "e_type": e_type, "e_machine": e_machine,
            "elf_machine": {8: "EM_MIPS"}.get(e_machine, str(e_machine)),
            "e_entry": e_entry, "e_phnum": e_phnum}


def inventory(chd_path, chd_sha256=None, sniff_limit: int = HEAD_SNIFF_LIMIT) -> dict:
    """Build the owned-build manifest for the Outbreak File #2 (USA) disc."""
    chd_path = Path(chd_path)
    with open(chd_path, "rb") as fh:
        head = parse_chd_header(fh.read(124))
    if head["version"] != 5:
        raise ValueError(f"expected CHD v5, got v{head['version']}")
    disc = ChdDisc(chd_path)
    try:
        members, elves = [], []
        for name, (lba, size) in sorted(disc.files.items()):
            entry = {"path": name, "lba": lba, "size": size}
            if size <= sniff_limit:
                info = elf_info(disc.read(name, 0, min(size, 64)))
                if info:
                    entry["category"] = "elf"
                    entry["elf"] = info
                    elves.append({"path": name, "size": size, "lba": lba, "elf": info})
                else:
                    entry["category"] = "data"
            else:
                entry["category"] = "data_large"
            members.append(entry)
        # The disc executable is the one ELF member at the ISO9660 root; every other
        # ELF member is a sub-directory module.  Counted, not guessed from a filename.
        root_elf = [e for e in elves if "/" not in e["path"]]
        byte_orders = {}
        for e in elves:
            bo = e["elf"].get("byte_order", "unknown")
            byte_orders[bo] = byte_orders.get(bo, 0) + 1
        exe = None
        if len(root_elf) == 1:
            name, size, lba = root_elf[0]["path"], root_elf[0]["size"], root_elf[0]["lba"]
            blob = disc.read(name)
            exe = {"path": name, "size": size, "lba": lba,
                   "sha256": hashlib.sha256(blob).hexdigest()}
            einfo = elf_info(blob[:64])
            if einfo:
                exe.update(einfo)
        counts = {"members": len(members),
                  "elf_members": len(elves),
                  "root_elf_members": len(root_elf),
                  "subdir_elf_members": len(elves) - len(root_elf),
                  "byte_orders": byte_orders,
                  "members_ge_1MiB": sum(1 for m in members if m["size"] >= (1 << 20)),
                  "total_member_bytes": sum(m["size"] for m in members)}
        return {
            "game_id": GAME_ID,
            "title": "Resident Evil Outbreak File #2",
            "platform": "ps2",
            "revision": "SLUS-209.84 (USA)",
            "source": {"path": str(chd_path), "name": chd_path.name,
                       "size_bytes": chd_path.stat().st_size,
                       "sha256": chd_sha256,
                       "container": "MAME CHD v5, single MODE1 track, cdlz/cdzl/cdfl",
                       "header": head, "filesystem": "ISO9660"},
            "executable": exe,
            "counts": counts,
            "members": members,
        }
    finally:
        disc.close()


def _cache_key(path: Path) -> str:
    st = path.stat()
    return hashlib.sha256(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:32]


def cached_inventory(chd_path, cache_dir=None, **kw) -> dict:
    """Return the manifest, reusing a on-disk cache keyed by the owned file identity.

    The cache is keyed by path+size+mtime, so a changed source can never be served
    from a stale manifest.
    """
    path = Path(chd_path)
    if not cache_dir:
        return inventory(path, **kw)
    cdir = Path(cache_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    cf = cdir / f"ro2_{_cache_key(path)}.json"
    if cf.exists():
        try:
            blob = json.loads(cf.read_text(encoding="utf-8"))
            if blob.get("identity", {}).get("size") == path.stat().st_size:
                return blob["manifest"]
        except Exception:                                       # noqa: BLE001
            pass
    man = inventory(path, **kw)
    st = path.stat()
    cf.write_text(json.dumps({"identity": {"size": st.st_size, "mtime": int(st.st_mtime)},
                              "manifest": man}), encoding="utf-8")
    return man


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="RE Outbreak File #2 (USA) owned-source manifest")
    ap.add_argument("chd", nargs="?", default=None)
    ap.add_argument("--sha", default=None, help="pre-computed CHD sha256")
    ap.add_argument("--no-hash", action="store_true", help="skip streaming the CHD hash")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    chd = args.chd or os.environ.get("GBOX_REO2_CHD")
    if not chd:
        raise SystemExit("pass the owned .chd path or set GBOX_REO2_CHD")
    sha = args.sha
    if sha is None and not args.no_hash:
        sha = sha256_file(chd)
    man = inventory(chd, chd_sha256=sha)
    text = json.dumps(man, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
