"""Focused tests for the True Crime: New York City (GameCube) owned-build manifest.

The fixture is a synthetic GCZ built here (not produced by the code under test):
a tiny image with a disc header, a FST (gbox.formats.gcfst.build_fst), the
executable at the header's DOL offset and one data file, wrapped in a real GCZ
container (magic 0xB10BC001, 16 KiB blocks, zlib blocks, Adler32 block hashes).
read_manifest must then report exactly that layout, and must not touch the file.
"""
import hashlib
import struct
import zlib

from gbox.formats.gcfst import build_fst
from gbox.tcnyc_inventory import extension_of, read_manifest, write_manifest

GCZ_MAGIC = 0xB10BC001
BLOCK = 0x4000


def _gcz_bytes(image: bytes) -> bytes:
    """Wrap a raw disc image in a GCZ container (Dolphin CompressedBlob layout)."""
    nblocks = (len(image) + BLOCK - 1) // BLOCK
    stored, ptrs, blob = [], [], b""
    for i in range(nblocks):
        chunk = image[i * BLOCK:(i + 1) * BLOCK].ljust(BLOCK, b"\0")
        comp = zlib.compress(chunk, 6)
        if len(comp) >= len(chunk):
            ptrs.append((1 << 63) | len(blob))
            stored.append(chunk)
        else:
            ptrs.append(len(blob))
            stored.append(comp)
        blob = b"".join(stored)
    data = blob
    hdr = struct.pack("<IIQQII", GCZ_MAGIC, 0, len(data), len(image), BLOCK, nblocks)
    return (hdr + struct.pack(f"<{nblocks}Q", *ptrs)
            + b"".join(struct.pack("<I", zlib.adler32(s) & 0xFFFFFFFF) for s in stored)
            + data)


def _fixture(tmp_path):
    hdr = bytearray(0x100)
    struct.pack_into(">I", hdr, 0, 0x100)          # text0 file offset
    struct.pack_into(">I", hdr, 0x90, 0x10)        # text0 size
    struct.pack_into(">I", hdr, 0xE0, 0x80003100)  # entry
    dol = bytes(hdr) + b"\xAA" * 0x10
    char = b"CHARASSET" + b"\x11" * 7
    fst = build_fst([("main.dol", 0x440, len(dol)),
                     ("data/char.g", 0x440 + len(dol), len(char))])
    iso_off = 0x440 + len(dol) + len(char)
    image = bytearray(iso_off + len(fst))
    image[0:6] = b"GTCNYC"
    image[0x20:0x28] = b"TRUE_CR"
    struct.pack_into(">III", image, 0x420, 0x440, iso_off, len(fst))
    image[0x440:0x440 + len(dol)] = dol
    image[0x440 + len(dol):0x440 + len(dol) + len(char)] = char
    image[iso_off:iso_off + len(fst)] = fst
    p = tmp_path / "fixture.gcz"
    p.write_bytes(_gcz_bytes(bytes(image)))
    return p, dol, char


def test_manifest_reports_container_disc_and_native_target(tmp_path):
    p, dol, char = _fixture(tmp_path)
    m = read_manifest(str(p))
    assert m["container"]["format"] == "gcz"
    assert m["disc"]["game_id"] == "GTCNYC"
    assert m["disc"]["title"] == "TRUE_CR"
    assert m["file_count"] == 2
    assert m["source"]["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert m["source"]["sha256_method"] == "streamed by read_manifest"
    assert m["source"]["size"] == p.stat().st_size
    # the identified native target: hashed from the bytes read out of the image
    t = m["native_target_executable"]
    assert t["path"] == "main.dol"
    assert t["size"] == len(dol)
    assert t["sha256"] == hashlib.sha256(dol).hexdigest()
    assert t["header_dol_matches_fst"] is True
    assert t["match"] == "exact_offset"
    paths = {f["path"]: f for f in m["files"]}
    assert paths["data/char.g"]["size"] == len(char)
    assert m["filename_extension_counts"] == {"dol": 1, "g": 1}
    b = m["boot_dol"]
    assert (b["offset"], b["size"], b["entry"]) == (0x440, len(dol), 0x80003100)
    assert b["sha256"] == hashlib.sha256(dol).hexdigest()
    assert m["notes"], "the manifest must label filename counts as unproven"


def test_manifest_probes_selected_files_and_stays_read_only(tmp_path):
    p, _dol, _char = _fixture(tmp_path)
    before = p.read_bytes()
    m = read_manifest(str(p), probe_exts=(".g",), probe_limit=4)
    assert [x["path"] for x in m["probed_files"]] == ["data/char.g"]
    assert bytes.fromhex(m["probed_files"][0]["head_hex"]) == b"CHARASSET" + b"\x11" * 7
    assert p.read_bytes() == before, "the owned image must not be modified"


def test_manifest_accepts_supplied_source_digest(tmp_path):
    p, _dol, _char = _fixture(tmp_path)
    m = read_manifest(str(p), source_sha256="a" * 64)
    assert m["source"]["sha256"] == "a" * 64
    assert "supplied" in m["source"]["sha256_method"]


def test_write_manifest_returns_digest(tmp_path):
    import json
    out = tmp_path / "m.json"
    digest = write_manifest({"a": 1}, str(out))
    assert digest == hashlib.sha256(out.read_bytes()).hexdigest()
    assert json.loads(out.read_text()) == {"a": 1}


def test_extension_of():
    assert extension_of("data/char.g") == "g"
    assert extension_of("main.dol") == "dol"
    assert extension_of("noext") == ""
