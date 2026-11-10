"""Tests for gbox.crazy_taxi2_analysis (request #2454). Synthetic pools always; the owned CDI when present."""
import os
import struct
from pathlib import Path

import pytest

from gbox import crazy_taxi2 as c2
from gbox import crazy_taxi2_analysis as an

CDI = Path("/mnt/gbox/quickswap2/Emulation/_emulation/_dc iso/Crazy Taxi 2.cdi")


def test_literal_refs_only_aligned_hits():
    exe = bytearray(64)
    struct.pack_into("<I", exe, 8, 0x0C135D78)
    struct.pack_into("<I", exe, 33, 0x0C135D78)     # unaligned: ignored
    assert an.literal_refs(bytes(exe), 0x0C135D78) == [c2.EXE_BASE + 8]


def test_literal_refs_none():
    assert an.literal_refs(b"\0" * 16, 0x1234) == []


@pytest.mark.skipif(not CDI.exists() or os.environ.get("CT2_SKIP_CDI"), reason="owned CDI not mounted")
def test_owned_build_tables_match_files():
    r = an.probe(c2.open_disc(CDI))
    assert r["known_build"] and r["loader_in_exe"]
    ok = [m for m in r["models"] if "error" not in m]
    assert len(ok) >= 8
    for m in ok:
        assert m["slots_subset_of_objects"] and m["tex_layout_ok"] and m["alloc_ok"], m
    assert any(r["table_literal_refs"].values())
