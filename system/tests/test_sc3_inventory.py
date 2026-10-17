"""Focused tests for gbox.sc3_inventory: OLK table, package children, ELF OLK name table."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gbox import sc3_inventory as s  # noqa: E402


def make_olk(payloads, data_start=0x800):
    n = len(payloads)
    body = bytearray()
    recs = []
    for p in payloads:
        recs.append((len(body), len(p)))
        body += p
        body += b"\0" * (-len(body) % 0x800)
    head = bytearray(data_start)
    struct.pack_into("<I4sII", head, 0, n, b"olnk", 0x800, 0)
    struct.pack_into("<IIII", head, 16, data_start, len(body), 0, 0)
    for i, (o, sz) in enumerate(recs):
        struct.pack_into("<IIII", head, 32 + 16 * i, o, sz, 0x4332e2e0, 0)
    return bytes(head + body)


def test_olk_table_offsets_are_relative_to_data_start():
    blob = make_olk([b"A" * 10, b"", b"B" * 0x900])
    t = s.olk_table(blob)
    assert t["count"] == 3 and t["data_start"] == 0x800
    e0, e1, e2 = t["entries"]
    assert blob[e0["offset"]:e0["offset"] + e0["size"]] == b"A" * 10
    assert e1["size"] == 0
    assert blob[e2["offset"]:e2["offset"] + 4] == b"BBBB"
    assert s.olk_check(t, len(blob)) == []


def test_olk_check_flags_out_of_range_and_bad_magic():
    blob = make_olk([b"A" * 0x100])
    t = s.olk_table(blob)
    assert s.olk_check(t, 0x810)  # truncated archive
    with pytest.raises(ValueError):
        s.olk_table(b"\x01\0\0\0nope" + b"\0" * 40)


def test_nested_olk_parses_inside_parent():
    inner = make_olk([b"mmp\0" + b"\0" * 60, b"vtb\0" + b"\0" * 12], data_start=0x800)
    outer = make_olk([inner])
    t = s.olk_table(outer)
    child = outer[t["entries"][0]["offset"]:]
    ti = s.olk_table(child)
    assert ti["count"] == 2
    assert s.magic_label(child[ti["entries"][0]["offset"]:]) == "mmp"
    assert s.magic_label(child[ti["entries"][1]["offset"]:]) == "vtb"


def test_package_children_sizes_and_rejects_non_packages():
    pkg = bytearray(0x200)
    struct.pack_into("<4I", pkg, 0, 3, 0x80, 0, 0x100)
    pkg[0x80:0x84] = b"mmp\0"
    kids = s.package_children(bytes(pkg))
    assert kids == [(0x80, 0x80), (0x100, 0x100)]
    assert s.package_children(b"\x09\x0e\x1c\x0b" + b"\0" * 60) is None
    assert s.package_children(struct.pack("<3I", 2, 0x100, 0x80) + b"\0" * 0x200) is None


def make_elf(names_counts):
    vaddr = 0x100000
    blob = bytearray(0x1000)
    struct.pack_into("<4s", blob, 0, b"\x7fELF")
    struct.pack_into("<I", blob, 0x1C, 0x34)
    struct.pack_into("<H", blob, 0x2C, 1)
    struct.pack_into("<8I", blob, 0x34, 1, 0, vaddr, vaddr, 0x1000, 0x1000, 5, 0x10)
    so = 0x800
    tab = 0x400
    for i, (n, c) in enumerate(names_counts):
        blob[so:so + len(n) + 1] = n.encode() + b"\0"
        struct.pack_into("<4I", blob, tab + 16 * i, vaddr + 0x700, vaddr + so, 0, c)
        so += 0x20
    return bytes(blob)


def test_elf_olk_table_reads_names_and_counts():
    elf = make_elf([("root.olk", 8), ("motinfo.olk", 174), ("human.olk", 1413)])
    t = s.elf_olk_table(elf)
    assert [r["name"] for r in t["records"]] == ["root.olk", "motinfo.olk", "human.olk"]
    assert [r["count"] for r in t["records"]] == [8, 174, 1413]
    assert t["table_vaddr"] == 0x100400


def test_real_disc_when_staged():
    iso = os.path.expanduser("~/gbox-cache/ps2/afe447a632bd5e6b/disc.iso")
    if not os.path.exists(iso):
        pytest.skip("owned SC3 disc image not staged")
    m = s.inventory(iso)
    assert m["boot"]["sha256"] == "3f9102baa6b5a84fde9ee4161dd8e0c70f4ba7cb8bec8c5dea27b555f1185570"
    assert m["root_olk"]["problems"] == []
    g = m["groups"]
    for name in ("cpudata", "cdata", "event", "stage", "creation", "human", "contac"):
        assert g[name]["count_matches_elf"] and g[name]["problems"] == []
    assert g["human"]["olk_count"] == 1413 and g["human"]["nonempty"] == 1078
