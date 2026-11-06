"""Focused tests for gbox.doa5lr_lfmo (request #2450, DOA5LR LFMO parser).

Synthetic-LFMO tests run anywhere; the preserved-sample test is skip-gated
on the research artifact (owned PS3 build evidence)."""
import importlib.util
import struct
import sys
from pathlib import Path

import pytest


def _load():
    p = Path(__file__).resolve().parents[1] / "gbox" / "doa5lr_lfmo.py"
    spec = importlib.util.spec_from_file_location("doa5lr_lfmo", str(p))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


L = _load()


def build_lfmo(names, order="test.order"):
    count = len(names)
    table_end = L.HEADER_SIZE + count * L.ROW_SIZE
    name_start = table_end + len(order.encode("latin1")) + 1
    offsets, pos = [], name_start
    for n in names:
        offsets.append(pos)
        pos += len(n.encode("latin1")) + 1
    data = bytearray(b"LFMO" + struct.pack(">II", 0, count))
    data += b"\x00" * (L.HEADER_SIZE - len(data))
    for i in range(count):
        data += struct.pack(">III", 0, i, offsets[i])
    assert len(data) == table_end
    data += order.encode("latin1") + b"\x00"
    for n in names:
        data += n.encode("latin1") + b"\x00"
    return bytes(data)


def test_parse_synthetic():
    names = ["/BR87Y@10T10000@X", "/BS87Y@10T10000@Y", "/2R052@1S100@Z", "/D00_931"]
    m = L.parse(build_lfmo(names, "chara_common.order"))
    assert m.count == 4
    assert m.table_end == L.HEADER_SIZE + 4 * L.ROW_SIZE
    assert m.order_name == "chara_common.order"
    assert [e.name for e in m.entries] == names
    assert m.name_at(1) == "/BS87Y@10T10000@Y"


def test_seq_matches_index():
    m = L.parse(build_lfmo(["/AB123", "/CD456"]))
    assert [e.seq for e in m.entries] == [0, 1]


def test_base_code_and_variant():
    assert L.base_code("/BR87Y@10T10000@X") == "BR87Y"
    assert L.variant_index("/BR87Y@10T10000@X") == 1
    assert L.variant_index("/BS87Y@10T10000@X") == 2


def test_group_and_candidates():
    m = L.parse(build_lfmo(["/BR87Y@10T10000@X", "/BS87Y@10T10000@X", "/2R052@1S100@Y"]))
    assert L.group_by_base(m.entries) == {"BR87Y": [0], "BS87Y": [1], "2R052": [2]}
    assert L.char_magic_candidates(m.entries) == [0, 1, 2]


def test_rejects_bad_magic_and_truncation():
    with pytest.raises(ValueError):
        L.parse(b"CHCM" + b"\x00" * 32)
    with pytest.raises(ValueError):
        L.parse(build_lfmo(["/AB123"])[: L.HEADER_SIZE])


SAMPLE = Path(
    "/home/ehm_eckx/gBox_alt/gbox-cache/research/doa5lr_samples_2450/"
    "lfmo_chara_common.bin"
)


@pytest.mark.skipif(not SAMPLE.exists(), reason="preserved LFMO sample not on this host")
def test_preserved_sample():
    m = L.parse(SAMPLE.read_bytes())
    assert m.count == 2355
    assert m.table_end == 28300
    assert m.order_name == "chara_common.order"
    assert len(set(e.name for e in m.entries)) == 2355
    assert m.name_at(18) == "/BR87Y@10T10000@DD1]T]D128K00RJ1M1J1G1DK1DBSH17O{TEAL71M"
    assert m.name_at(940) == "/BR1J7@1S100C@]]2J3623D1PQF1100DN10002{26210"
