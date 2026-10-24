"""Tom Clancy's Splinter Cell (USA) (GameCube, GCEE41) -- owned-disc inventory for character work.

Catalog game a4ed2cf4d1966815 is a Dolphin GCZ in the HyperSpin "Nintendo GameCube" collection:

  owned source  ~/gBox_alt/gbox-cache/a4ed2cf4d1966815/Tom Clancy's Splinter Cell (USA).gcz
  sha256       438e8491f3aa8bb86ffcd3f518bd9b88b777c8318bd04a02d2a414f538204db5   (1,394,281,067 B)
  unpacked     ~/gBox_alt/gbox-cache/modbase/a4ed2cf4d1966815/splinter.iso
  sha256       8c3c863eddc15ee2bdf8acd396387cf76b049146a31ee9a727a9d3e8cb12869a   (1,459,978,240 B)

`filemods.gcz_to_iso` unpacks the GCZ once; the GCZ itself is never modified.

Disc facts read from the owned bytes: id GCEE41, title "Tom Clancy's Splinter Cell", GameCube
magic 0xC2339F3D at 0x1C and no Wii magic at 0x18, bi2.bin region 1 (NTSC-U), 316 FST files.
main.dol sits at disc offset 0x1ec00, entry 0x80005308, 3,108,224 bytes of loaded segments.

Character/level data lives in `System/warlins.umd` (197,677,147 B) and `System/warship.umd`
(1,762,111 B).  A `.umd` file is a flat Ubisoft "Ubi Massive Data" chunk chain with no index:

    u32 BE uncompressed_size | u32 BE compressed_size | zlib payload

each record inflating independently.  The first warlins.umd record is 98304/37190 and inflates to
an Unreal Engine 3 package -- the head carries the level name "0_0_2.unr" and the inflated bytes
contain UE3 script text ("SceneManager : Affected actor is NULL!"), which is what the ticket's
assimilation fingerprint reported as "Unreal Engine 3 (0.76)".  `warship.umd` is NOT the same
format: it is plain INI text ("[DefaultComputer]", "Copyright Ubi Soft Ent. 2002").  So ".umd" is
not a format marker and every member has to be identified from its own bytes.

This module owns the read-only container reader and the owned-build manifest.  It deliberately
does NOT claim a character roster: the chunk -> member mapping is what the next stage has to
prove, and counting compressed records is not the same as counting characters.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path

GAME_IDS = {"a4ed2cf4d1966815": "Tom Clancy's Splinter Cell (USA)"}
DISC_ID = "GCEE41"
GC_MAGIC, WII_MAGIC = 0xC2339F3D, 0x5D1C9EA3
REGIONS = {0: "NTSC-J", 1: "NTSC-U", 2: "PAL", 4: "NTSC-K"}
CHUNK_HEADER = struct.Struct(">II")

# A level package names itself in its first bytes: "0_0_2.unr" and friends.  The name is a
# NUL-terminated ASCII token, so match printable runs and keep the ".unr" tail.
_NAME_RE = re.compile(rb"[ -~]{1,64}\.unr")


class UmdError(Exception):
    """A .umd record does not match its own header."""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _file_sha(path) -> str:
    """Stream the bytes of a real file; never report a reference hash."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def member_name(data: bytes) -> str | None:
    """The UE3 package file name at the head of an inflated level record, if there is one."""
    m = _NAME_RE.search(data[:512])
    if not m:
        return None
    name = m.group(0).decode("ascii", "replace")
    return name.split("\\")[-1].split("/")[-1]


def read_chunks_bytes(blob: bytes, label: str = "<bytes>") -> tuple[list[dict], int, int]:
    """Walk the flat (usize, csize, zlib) record chain of a .umd archive held in memory.

    Returns (chunks, chain_end_offset, size).  A record whose inflated length disagrees with its
    own header raises UmdError -- a silent skip would hide a corrupt member.
    """
    size = len(blob)
    chunks: list[dict] = []
    offset = 0
    while offset + CHUNK_HEADER.size <= size:
        usize, csize = CHUNK_HEADER.unpack_from(blob, offset)
        if usize == 0 or csize == 0:
            break
        if offset + CHUNK_HEADER.size + csize > size:
            break
        payload = blob[offset + CHUNK_HEADER.size: offset + CHUNK_HEADER.size + csize]
        try:
            data = zlib.decompress(payload)
        except zlib.error as exc:
            raise UmdError(f"{label}: record at 0x{offset:x} does not inflate: {exc}") from exc
        if len(data) != usize:
            raise UmdError(
                f"{label}: record at 0x{offset:x} inflated to {len(data)} B, header says {usize} B")
        chunks.append({
            "offset": offset,
            "uncompressed_size": usize,
            "compressed_size": csize,
            "sha256": _sha(data),
            "name": member_name(data),
        })
        offset += CHUNK_HEADER.size + csize
    return chunks, offset, size


def read_chunks(path, limit: int | None = None) -> tuple[list[dict], int, int]:
    """Same walk as read_chunks_bytes, over a file on disk."""
    blob = Path(path).read_bytes()
    chunks, end, size = read_chunks_bytes(blob, str(path))
    if limit is not None:
        chunks = chunks[:limit]
    return chunks, end, size


def disc_identity(head: bytes, bi2: bytes) -> dict:
    """Disc header (0x440 B) + bi2.bin: id, title, platform and region, from the real bytes."""
    gc = struct.unpack_from(">I", head, 0x1C)[0]
    wii = struct.unpack_from(">I", head, 0x18)[0]
    region = struct.unpack_from(">I", bi2, 0x18)[0]
    if gc == GC_MAGIC and wii != WII_MAGIC:
        platform = "gamecube"
    elif wii == WII_MAGIC:
        platform = "wii"
    else:
        platform = "unknown"
    return {
        "disc_id": head[:6].decode("ascii", "replace"),
        "title": head[0x20:0x60].split(b"\0")[0].decode("latin-1"),
        "platform": platform,
        "gamecube_magic": f"0x{gc:08x}",
        "wii_magic": f"0x{wii:08x}",
        "region_code": region,
        "region": REGIONS.get(region, f"unknown({region})"),
    }


def _extension(name: str) -> str:
    base = name.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def inventory(iso, source=None, source_sha256=None) -> dict:
    """Owned-build manifest for the GameCube build of Tom Clancy's Splinter Cell."""
    from .gcdisc import GCDisc

    iso = Path(iso)
    disc = GCDisc(str(iso))
    with open(iso, "rb") as f:
        head = f.read(0x440)
        f.seek(0x440)
        bi2 = f.read(0x440)
    ident = disc_identity(head, bi2)

    files = []
    by_ext: dict[str, dict] = {}
    for name, (off, size) in sorted(disc.files.items()):
        files.append({"path": name, "offset": off, "size": size})
        ext = _extension(name)
        slot = by_ext.setdefault(ext, {"count": 0, "bytes": 0})
        slot["count"] += 1
        slot["bytes"] += size

    dol = disc.dol()
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
    bss_addr, bss_size, entry = struct.unpack_from(">3I", dol, 0xD8)
    segments = [
        {"index": i, "addr": f"0x{addrs[i]:08x}", "size": sizes[i]}
        for i in range(18) if sizes[i]
    ]

    umd = {}
    with open(iso, "rb") as f:
        for entry_name in sorted(disc.files):
            if not entry_name.lower().endswith(".umd"):
                continue
            off, size = disc.files[entry_name]
            f.seek(off)
            blob = f.read(size)
            chunks, chain_end, _ = read_chunks_bytes(blob, entry_name)
            named = [c["name"] for c in chunks if c["name"]]
            umd[entry_name] = {
                "size": size,
                "sha256": _sha(blob),
                "is_ini_text": blob[:16].lstrip()[:1] == b"[" and b"\r\n" in blob[:256],
                "records": len(chunks),
                "chain_end": chain_end,
                "chain_covers_file": chain_end == size,
                "uncompressed_bytes": sum(c["uncompressed_size"] for c in chunks),
                "named_records": named[:64],
                "named_record_count": len(named),
                "chunks": chunks,
            }

    return {
        "game_ids": GAME_IDS,
        "source": {"path": str(source) if source else None, "sha256": source_sha256},
        "unpacked_iso": {"path": str(iso), "size": iso.stat().st_size, "sha256": _file_sha(iso)},
        "disc": ident,
        "file_count": len(files),
        "files": files,
        "bytes_by_extension": by_ext,
        "main_dol": {
            "disc_offset": struct.unpack(">I", head[0x420:0x424])[0],
            "sha256": _sha(dol),
            "size": len(dol),
            "entry": f"0x{entry:08x}",
            "bss": {"addr": f"0x{bss_addr:08x}", "size": bss_size},
            "segments": segments,
        },
        "umd_archives": umd,
    }


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m gbox.splinter_inventory <iso> [source] [source_sha256] [out.json]",
              file=sys.stderr)
        return 2
    iso = Path(argv[0])
    source = argv[1] if len(argv) > 1 else None
    source_sha256 = argv[2] if len(argv) > 2 else None
    out = Path(argv[3]) if len(argv) > 3 else None
    manifest = inventory(iso, source, source_sha256)
    text = json.dumps(manifest, indent=2, sort_keys=True)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print("wrote", out, _sha(text.encode()), "manifest sha256")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
