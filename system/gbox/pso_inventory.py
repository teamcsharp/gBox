"""Phantasy Star Online Episode I & II Plus (USA) — GameCube inventory.

Owned source: hyperspin catalog entry
`collections/Nintendo GameCube/roms/Phantasy Star Online Episode I & II Plus (USA).gcz`
(1,178,288,344 bytes), sha256
253c42a85fc4f16a6b89cf4e486c13b617f541cd324e8b4aa707cd9074014ce2.

GCZ ("GameCubeZip") container layout, as found in the operator's library
(magic 0xB10BC001; every multibyte container value is little-endian):

  0x00 u32 magic 0xB10BC001
  0x04 u32 version (0)
  0x08 u32 size field (informational; unused by this reader)
  0x10 u32 uncompressed disc size (0x57058000)
  0x18 u32 block size (0x4000)
  0x1C u32 block count
  0x28 per-block records: {u32 cumulative stream end, u32 flags} for every
       block except the last; the last block's end is implied by EOF (its
       record slot is the first word of the CRC table that follows)
  then one u32 per block (CRC32 of the uncompressed block data)
  then the zlib streams, concatenated, one per block.

Each stream inflates to exactly one 0x4000-byte disc block.  A record whose
cumulative value equals its predecessor's describes an all-zero block.
Records with the 0x80000000 flag set still carry a stream.

`python -m gbox.pso_inventory SRC [--out manifest.json] [--iso path]`
"""
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

GCZ_MAGIC = 0xB10BC001
BLOCK_SIZE = 0x4000
DISC_MAGIC = bytes.fromhex("c2339f3d")  # GC disc header, offset 0x1C
PSO_PLUS_GAME_ID = "GPOE8P"

# Disc regions the game keeps player character data in (PSO GC layout).
# Populated per-extension after the FST scan; kept here for clarity.
CHAR_DIRS = ("charac", "pl", "player")


def gcz_header(src: Path) -> dict:
    with open(src, "rb") as f:
        h = f.read(0x28)
    magic, version = struct.unpack_from("<II", h, 0)
    disc_size = struct.unpack_from("<I", h, 0x10)[0]
    block_size, num_blocks = struct.unpack_from("<II", h, 0x18)
    if magic != GCZ_MAGIC:
        raise ValueError(f"not a GCZ container: magic {magic:#x}")
    return {
        "magic": magic,
        "version": version,
        "disc_size": disc_size,
        "block_size": block_size,
        "num_blocks": num_blocks,
    }


def _find_data_start(f, num_blocks: int) -> int:
    """First zlib stream that inflates to a 0x4000 GC disc block, probing just
    past the record/CRC tables.  The probe window covers the CRC table plus
    slack (2 MiB) without reading the whole file."""
    probe_base = 0x28 + (num_blocks - 1) * 8
    f.seek(probe_base)
    chunk = f.read(2 * 1024 * 1024)
    for off in range(len(chunk) - 1):
        try:
            out = zlib.decompress(chunk[off:off + BLOCK_SIZE + 0x200], 15)
        except zlib.error:
            continue
        if len(out) == BLOCK_SIZE and out[0x1C:0x20] == DISC_MAGIC:
            return probe_base + off
    raise ValueError("block-0 stream not found past the tables")


def gcz_to_iso(src: Path, dst: Path) -> str:
    """Decompress a GCZ container to a raw GameCube ISO; returns the sha256.

    The per-block zlib streams live in one contiguous data region, so the
    reader slurps that region sequentially (CIFS bulk reads) and slices the
    streams out locally instead of seeking per block."""
    info = gcz_header(src)
    num_blocks = info["num_blocks"]
    assert info["block_size"] == BLOCK_SIZE
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as f:
        f.seek(0x28)
        words = struct.unpack(f"<{2 * (num_blocks - 1)}I", f.read(8 * (num_blocks - 1)))
        offsets = words[0::2]  # cumulative stream ends; last block's end = EOF
        flags = words[1::2]    # record i's 0x80000000 flag marks block i+1 raw
        data_start = _find_data_start(f, num_blocks)
        f.seek(data_start)
        data = f.read()  # to EOF

    # sanity: block 0 is the disc header
    b0 = zlib.decompress(data[: offsets[0]], 15)
    assert len(b0) == BLOCK_SIZE and b0[0x1C:0x20] == DISC_MAGIC

    h = hashlib.sha256()
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    out = open(tmp, "wb")
    zero = b"\0" * BLOCK_SIZE
    prev = 0
    for i, end in enumerate(offsets):
        if end == prev:
            block = zero
        elif i > 0 and flags[i - 1] & 0x80000000:
            block = data[prev:end]  # stored raw, no zlib
            if len(block) != BLOCK_SIZE:
                raise ValueError(f"raw block {i} is {len(block)} bytes")
        else:
            block = zlib.decompress(data[prev:end], 15)
            if len(block) != BLOCK_SIZE:
                raise ValueError(f"block {i} inflates to {len(block)} bytes")
        prev = end
        out.write(block)
        h.update(block)
    tail = zlib.decompress(data[prev:], 15)
    assert len(tail) == BLOCK_SIZE, len(tail)
    out.write(tail)
    h.update(tail)
    out.close()
    tmp.replace(dst)
    return h.hexdigest()


def disc_identity(iso: Path) -> dict:
    with open(iso, "rb") as f:
        h = f.read(0x440)
    game_id = h[:6].decode("ascii", "replace")
    title = h[0x20:0x60].split(b"\0")[0].decode("latin-1")
    dol_off = struct.unpack_from(">I", h, 0x420)[0]
    fst_off, fst_size, fst_max = struct.unpack_from(">III", h, 0x424)
    return {
        "game_id": game_id,
        "disc_number": h[6],
        "revision": h[7],
        "region_byte": h[3],
        "maker": h[0x4:0x6].decode("ascii", "replace"),
        "title": title,
        "dol_offset": dol_off,
        "fst_offset": fst_off,
        "fst_size": fst_size,
        "fst_max": fst_max,
    }


def _classify(name: str, data: bytes) -> str:
    """Cheap content probe used for the manifest's file classes."""
    if data[:4] in (b"NJCM", b"NJTL", b"NJTX"):
        return "ninja_chunk"
    if data[:4] == b"NMDM":
        return "ninja_motion"
    if data[:4] in (b"GVMH", b"PVMH"):
        return "texture_archive"
    if data[:4] == b"GNJM" or data[:4] == b"GCNJ":
        return "gsl_rel"
    # PRS compression has no magic: a file is PRS if it decodes under the
    # Sega PRS scheme.  Skipped here; recorded only when probed (probe_prs).
    return "unknown"


def probe_prs(data: bytes) -> bool:
    """True when `data` is a Sega PRS stream that decodes to a sane size."""
    if len(data) < 3 or data[0] != 0:
        return False
    # flags byte at 0, then 16-bit BE pairs of (flag byte, count byte) while
    # the flag byte is nonzero
    i = 1
    while i + 1 < len(data) and data[i] != 0:
        i += 2
    if i + 1 >= len(data):
        return False
    try:
        return _prs_decode(data) is not None
    except Exception:
        return False


def _prs_decode(src: bytes):
    """Minimal PRS decoder (returns decoded bytes or None)."""
    if not src or src[0] != 0:
        return None
    pos = 1
    ctl = 0
    out = bytearray()
    flag_pairs = []
    while True:
        if pos + 1 >= len(src):
            return None
        fb, cb = src[pos], src[pos + 1]
        if fb == 0:
            break
        flag_pairs.append((fb, cb))
        pos += 2
    # flag byte, count byte -> total compressed length (big-endian) is
    # implied by file size; decompression proper:
    pos = len(src)
    bit = 0
    try:
        while pos > 1:
            if bit == 0:
                ctl = src[pos - 1]
                pos -= 1
                bit = 8
            if ctl & 1:
                if pos < 1:
                    return None
                out.append(src[pos - 1])
                pos -= 1
            else:
                if pos < 2:
                    return None
                b1, b2 = src[pos - 2], src[pos - 1]
                pos -= 2
                l = b1 & 0x0F
                if l == 0:
                    if pos < 1:
                        return None
                    l = src[pos - 1] + 0x10
                    pos -= 1
                else:
                    l += 2
                d = (b1 >> 4) | (b2 << 4)
                if d == 0:
                    return None
                for _ in range(l):
                    if len(out) < d + 1:
                        return None
                    out.append(out[-1 - d])
            ctl >>= 1
            bit -= 1
    except Exception:
        return None
    return bytes(reversed(out))


def build_manifest(iso: Path) -> dict:
    """Full disc inventory: identity, executable hash, container layout,
    per-directory counts and the character-asset file list."""
    from gbox.gcdisc import GCDisc

    d = GCDisc(iso)
    ident = disc_identity(iso)
    dol = d.dol()
    dol_sha = hashlib.sha256(dol).hexdigest()
    files = {}
    dirs = {}
    extensions = {}
    char_files = []
    for name, (off, size) in d.files.items():
        parent = name.rsplit("/", 1)[0] if "/" in name else ""
        dirs.setdefault(parent, []).append((name, size))
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        extensions[ext] = extensions.get(ext, 0) + 1
        low = name.lower()
        if any(c in low for c in CHAR_DIRS) or low.startswith("pl"):
            char_files.append((name, off, size))
    # read + classify the first character-ish files (bounded)
    char_entries = []
    for name, off, size in sorted(char_files)[:64]:
        head = d._r(off, min(size, 16))
        char_entries.append(
            {"file": name, "size": size, "cls": _classify(name, head)}
        )
    return {
        "source": {
            "gcz_sha256": "253c42a85fc4f16a6b89cf4e486c13b617f541cd324e8b4aa707cd9074014ce2",
        },
        "identity": ident,
        "dol": {"size": len(dol), "sha256": dol_sha},
        "fst": {
            "files": len(d.files),
            "dirs": {k: len(v) for k, v in sorted(dirs.items())},
        },
        "extensions": dict(sorted(extensions.items(), key=lambda kv: -kv[1])),
        "char_files": char_entries,
    }


def main(argv):
    src = Path(argv[0])
    iso = Path(argv[1]) if len(argv) > 1 and argv[1] != "--iso" else None
    out_path = None
    args = iter(argv[1:])
    for a in args:
        if a == "--iso":
            iso = Path(next(args))
        elif a == "--out":
            out_path = Path(next(args))
    if iso is None:
        iso = Path(src).with_suffix(".iso")
    sha = gcz_to_iso(src, iso)
    print(f"decompressed {src} -> {iso} sha256={sha}", file=sys.stderr)
    manifest = build_manifest(iso)
    manifest["iso_sha256"] = sha
    text = json.dumps(manifest, indent=1)
    if out_path:
        out_path.write_text(text)
        print(f"manifest -> {out_path}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
