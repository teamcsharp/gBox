"""Focused tests for the Puyo Puyo Tetris (Switch) owned-build inventory.

The parser paths use a synthetic card; the owned-build test runs only when the
hyperspin library is mounted.  No pytest import is used, so the file also runs
standalone:  python3 tests/test_puyo_switch_inventory.py
"""
from __future__ import annotations

import hashlib
import inspect
import struct
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import puyo_switch_inventory as inv

XCI = Path(inv.DEFAULT_XCI)


def _synthetic(path, sig=b"HEAD", sig_off=0x100, hfs0_at=0x2000, table=None, head_len=0x8000):
    """A card-shaped image: container signature, encrypted NCSD slot, one HFS0."""
    buf = bytearray(b"\x00" * head_len)
    buf[sig_off:sig_off + 4] = sig
    struct.pack_into("<I", buf, 0x104, 0x0C01C0)       # image size word
    struct.pack_into("<I", buf, 0x108, 0xFFFFFFFF)    # sector size: not a power of two
    struct.pack_into("<I", buf, 0x110, 0xF80000)      # header size: not sane
    if table is None:
        table = b"\xff" * inv.NCSD_TABLE_LEN         # encrypted partition region
    buf[inv.NCSD_TABLE_OFF:inv.NCSD_TABLE_OFF + len(table)] = table
    buf[hfs0_at:hfs0_at + 4] = b"HFS0"
    path.write_bytes(bytes(buf))
    return path


def test_headerless_card_is_key_gated(tmp_path):
    card = _synthetic(tmp_path / "card.xci")
    info = inv.classify_owned_build(card)
    assert info.layout == "headerless"
    assert info.header_key_required is True
    assert info.partition_table_readable is False
    assert any("encrypted" in n for n in info.notes)


def test_xci0_layout_and_readable_table(tmp_path):
    card = _synthetic(tmp_path / "card.xci", sig=b"XCI0", sig_off=0,
                      table=b"NCSD" + b"\x00" * (inv.NCSD_TABLE_LEN - 4))
    info = inv.classify_owned_build(card)
    assert info.layout == "xci0"
    assert info.partition_table_readable is True
    assert info.header_key_required is False


def test_unknown_magic_is_reported_as_unknown(tmp_path):
    card = _synthetic(tmp_path / "card.xci", sig=b"ZZZZ")
    info = inv.classify_owned_build(card)
    assert info.layout == "unknown"


def test_scan_matches_independent_digest_and_finds_magic(tmp_path):
    card = _synthetic(tmp_path / "card.xci", hfs0_at=0x2000)
    sha, total, hits = inv.scan(card)
    assert total == 0x8000
    assert sha == hashlib.sha256(card.read_bytes()).hexdigest()
    assert 0x2000 in hits["HFS0"]
    assert 0x100 in hits["HEAD"]


def test_scan_finds_magic_straddling_a_chunk_boundary(tmp_path):
    card = _synthetic(tmp_path / "card.xci", hfs0_at=0x2000)
    old = inv.CHUNK
    try:
        inv.CHUNK = 0x2001            # 0x2000..0x2003 spans two chunks
        sha, total, hits = inv.scan(card)
    finally:
        inv.CHUNK = old
    assert sha == hashlib.sha256(card.read_bytes()).hexdigest()
    assert 0x2000 in hits["HFS0"]


def test_parallel_scan_matches_sequential_scan(tmp_path):
    card = _synthetic(tmp_path / "card.xci", hfs0_at=0x2000)
    seq_sha, seq_total, seq_hits = inv.scan(card)
    par_sha, par_total, par_hits, complete = inv.scan_parallel(card, workers=4, budget_s=30.0)
    assert complete is True
    assert par_sha == seq_sha
    assert par_total == seq_total
    assert par_hits["HFS0"] == seq_hits["HFS0"]


def test_stream_sha256_prefix_limit(tmp_path):
    card = _synthetic(tmp_path / "card.xci")
    sha, read = inv.stream_sha256(card, limit=0x1000)
    assert read == 0x1000
    assert sha == hashlib.sha256(card.read_bytes()[:0x1000]).hexdigest()


def test_manifest_records_blocker_and_no_target_slot(tmp_path):
    card = _synthetic(tmp_path / "card.xci")
    m = inv.manifest(card)
    assert m["source_sha256"] == hashlib.sha256(card.read_bytes()).hexdigest()
    assert len(m["source_sha256"]) == 64
    assert m["root_hfs0_readable"] is False and m["partitions"] == {}
    assert m["target_slot"] is None
    assert m["blocker"] and "prod.keys" in m["blocker"]
    assert m["byte_order"] == "little-endian"
    assert m["offset_base"]["root_hfs0"] == "0xf000"


def test_owned_build_header_probe():
    if not XCI.exists():
        return
    info = inv.classify_owned_build(XCI)
    ev = info.evidence
    assert ev["size"] > 0
    assert ev["head_magic_at_0x100"] in ("HEAD", "XCI0")
    assert ev["ncsd_table_len"] == inv.NCSD_TABLE_LEN


def _hfs0(files, base_off=0):
    names = b"".join(n.encode() + b"\0" for n, _ in files)
    ents, rel, pos = b"", 0, 0
    for n, data in files:
        ents += struct.pack("<QQII", rel, len(data), pos, 0) + b"\0" * 40
        rel += len(data)
        pos += len(n) + 1
    return b"HFS0" + struct.pack("<II", len(files), len(names)) + b"\0" * 4 + ents + names + b"".join(d for _, d in files)


def test_hfs0_partition_listing():
    inner = _hfs0([("a.nca", b"A" * 10), ("b.cnmt.nca", b"B" * 5)])
    root = _hfs0([("secure", inner)])
    img = bytearray(inv.XCI_ROOT_HFS0_OFF) + root
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.xci"
        p.write_bytes(bytes(img))
        parts = inv.list_xci_partitions(p)
    files = parts["secure"]["files"]
    assert [f["name"] for f in files] == ["a.nca", "b.cnmt.nca"]
    assert [f["size"] for f in files] == [10, 5]
    assert bytes(img[files[1]["offset"]:files[1]["offset"] + 5]) == b"B" * 5


def test_owned_card_root_hfs0():
    if not XCI.exists():
        return
    parts = inv.list_xci_partitions(XCI)
    assert set(parts) == {"update", "normal", "secure"}
    assert len(parts["secure"]["files"]) == 5
    assert sum(f["size"] for f in parts["secure"]["files"]) <= parts["secure"]["size"]


def _standalone():
    fns = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        params = inspect.signature(fn).parameters
        with tempfile.TemporaryDirectory() as td:
            kwargs = {"tmp_path": Path(td)} if "tmp_path" in params else {}
            try:
                fn(**kwargs)
                print("PASS", name)
            except Exception:
                failed += 1
                print("FAIL", name)
                traceback.print_exc()
    print("%d/%d passed" % (len(fns) - failed, len(fns)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_standalone())
