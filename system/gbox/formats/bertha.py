"""Read-only reader for the owned NFL Blitz 2003 (PS2) disc containers.

Verified against the owned build (ISO sha256
7927f812724eb7c30d672903c5c277b5358d25d20b61b1590d376a796270d513):

  SLUS_204.74        main executable, 2 417 112 bytes
  DATA/BERTHA.ZIP    asset container: a stored ZIP holding the game assets
  DATA/BERTHA.ZIH    asset index: the engine's NUL separated name roster

Nothing in this module writes to the mounted share; every accessor opens the
image read-only and seeks inside it.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

SECTOR = 2048
EOCD_SIG = b"PK\x05\x06"
CEN_SIG = b"PK\x01\x02"
LOC_SIG = b"PK\x03\x04"


@dataclass(frozen=True)
class IsoMember:
    name: str
    lba: int
    size: int
    offset: int


@dataclass(frozen=True)
class ZipEntry:
    name: str
    method: int
    crc: int
    compressed_size: int
    size: int
    local_header_offset: int


def _read_at(fh, offset: int, size: int) -> bytes:
    fh.seek(offset)
    return fh.read(size)


def iso_members(iso_path: str) -> List[IsoMember]:
    """Every file in the ISO9660 image, with byte offsets in the image."""
    from gbox.formats import iso9660

    with open(iso_path, "rb") as fh:
        def read_lba(lba: int, size: int) -> bytes:
            return _read_at(fh, lba * SECTOR, size)

        pvd = read_lba(16, SECTOR)
        root_lba, root_size = iso9660.pvd_root(pvd)
        found = iso9660.files(read_lba, root_lba, root_size)

    return [
        IsoMember(name, int(lba), int(size), int(lba) * SECTOR)
        for name, (lba, size) in sorted(found.items())
    ]


def zip_entries(fh, zip_offset: int, zip_size: int) -> List[ZipEntry]:
    """Central directory of a ZIP container embedded inside another file."""
    window = min(zip_size, 65536)
    tail = _read_at(fh, zip_offset + zip_size - window, window)
    idx = tail.rfind(EOCD_SIG)
    if idx < 0:
        raise ValueError("zip end-of-central-directory record not found")
    eocd = tail[idx:idx + 22]
    if len(eocd) < 22:
        raise ValueError("truncated end-of-central-directory record")
    n_entries = struct.unpack_from("<H", eocd, 10)[0]
    cd_size, cd_offset = struct.unpack_from("<II", eocd, 12)
    cd = _read_at(fh, zip_offset + cd_offset, cd_size)

    entries: List[ZipEntry] = []
    off = 0
    while off + 46 <= len(cd) and cd[off:off + 4] == CEN_SIG:
        method = struct.unpack_from("<H", cd, off + 10)[0]
        crc = struct.unpack_from("<I", cd, off + 16)[0]
        csize = struct.unpack_from("<I", cd, off + 20)[0]
        usize = struct.unpack_from("<I", cd, off + 24)[0]
        nlen = struct.unpack_from("<H", cd, off + 28)[0]
        elen = struct.unpack_from("<H", cd, off + 30)[0]
        clen = struct.unpack_from("<H", cd, off + 32)[0]
        lho = struct.unpack_from("<I", cd, off + 42)[0]
        name = cd[off + 46:off + 46 + nlen].decode("latin-1")
        entries.append(ZipEntry(name, method, crc, csize, usize, lho))
        off += 46 + nlen + elen + clen

    if len(entries) != n_entries:
        raise ValueError(
            "zip central directory mismatch: parsed %d of %d" % (len(entries), n_entries)
        )
    return entries


def zip_member_bytes(fh, zip_member: IsoMember, entry: ZipEntry) -> bytes:
    """Raw bytes of one container member, read straight out of the ISO."""
    if entry.method != 0:
        raise NotImplementedError("compressed zip member: %s" % entry.name)
    base = zip_member.offset + entry.local_header_offset
    header = _read_at(fh, base, 30)
    if header[:4] != LOC_SIG:
        raise ValueError("bad local header for %s" % entry.name)
    nlen, elen = struct.unpack_from("<H", header, 26)[0], struct.unpack_from("<H", header, 28)[0]
    return _read_at(fh, base + 30 + nlen + elen, entry.size)


def roster_names(zih_bytes: bytes) -> List[str]:
    """The engine's asset name roster: NUL separated file names."""
    names: List[str] = []
    for token in zih_bytes.split(b"\x00"):
        if not token or len(token) > 128:
            continue
        try:
            text = token.decode("ascii")
        except UnicodeDecodeError:
            continue
        if "." in text and all(32 <= ord(c) < 127 for c in text):
            names.append(text)
    return names


def zih_records(zih_bytes: bytes) -> List[Tuple[int, int, int]]:
    """Fixed 12-byte records in the index header (semantics not yet decoded)."""
    count = len(zih_bytes) // 12
    return [struct.unpack_from("<3I", zih_bytes, i * 12) for i in range(count)]


def extension_histogram(names: List[str]) -> Dict[str, int]:
    hist: Dict[str, int] = {}
    for name in names:
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else "(none)"
        hist[ext] = hist.get(ext, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))


def build_manifest(iso_path: str, iso_sha256: Optional[str] = None) -> dict:
    """Authoritative manifest of the owned build, straight from the bytes."""
    import hashlib

    members = iso_members(iso_path)
    by_name = {m.name: m for m in members}
    manifest: dict = {
        "iso": {
            "path": iso_path,
            "size": os.path.getsize(iso_path),
            "sha256": iso_sha256,
        },
        "members": [
            {"name": m.name, "lba": m.lba, "size": m.size} for m in members
        ],
    }

    with open(iso_path, "rb") as fh:
        zih = by_name.get("DATA/BERTHA.ZIH")
        if zih is not None:
            blob = _read_at(fh, zih.offset, zih.size)
            names = roster_names(blob)
            records = zih_records(blob)
            manifest["bertha_zih"] = {
                "size": zih.size,
                "sha256": hashlib.sha256(blob).hexdigest(),
                "roster_count": len(names),
                "record_count": len(records),
                "extensions": extension_histogram(names),
                "roster": names,
            }

        container = by_name.get("DATA/BERTHA.ZIP")
        if container is not None:
            entries = zip_entries(fh, container.offset, container.size)
            manifest["bertha_zip"] = {
                "size": container.size,
                "entry_count": len(entries),
                "entries": [
                    {
                        "name": e.name,
                        "size": e.size,
                        "compressed_size": e.compressed_size,
                        "method": e.method,
                        "crc": e.crc,
                    }
                    for e in entries
                ],
            }
            roster = set(manifest.get("bertha_zih", {}).get("roster", []))
            lower = {n.lower(): n for n in roster}
            target = None
            for e in entries:
                if e.name.lower() in lower and e.name.lower().endswith(".dff") and e.size:
                    target = e
                    break
            if target is None:
                for e in entries:
                    if e.size:
                        target = e
                        break
            if target is not None:
                data = zip_member_bytes(fh, container, target)
                manifest["target_asset"] = {
                    "container": "DATA/BERTHA.ZIP",
                    "name": target.name,
                    "size": target.size,
                    "crc": target.crc,
                    "method": target.method,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "in_roster": target.name.lower() in lower,
                }
    return manifest
