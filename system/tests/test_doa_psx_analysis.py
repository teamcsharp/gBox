"""Focused tests for gbox.doa_psx_analysis against the owned Dead or Alive (USA) disc."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gbox import psxdisc  # noqa: E402
from gbox.doa_psx_analysis import (  # noqa: E402
    asset_tiers,
    classify_entry,
    cumulative_offsets,
    decode_asset_ref,
    id_grid,
    load_table_summary,
    ram_offset,
)

DISC = os.environ.get("DOA_PSX_DISC", "/home/ehm_eckx/gbox-cache/5b699968cf37a8ac/disc.bin")


@pytest.fixture(scope="module")
def doa():
    if not os.path.exists(DISC):
        pytest.skip(f"owned disc not present: {DISC}")
    d = psxdisc.RawBin(DISC, writable=False)
    return d.read("PS_DOA.BIN")


def test_ram_offset_byte_rotation():
    # entry 1 ref 0x00730200 -> code lives at file offset 0x27300 (MIPS confirmed)
    assert ram_offset(0x00730200) == 0x27300
    # entry 2 ref 0x00040300 -> 0x30400
    assert ram_offset(0x00040300) == 0x30400
    # entry 8 ref 0x00210600 -> 0x62100
    assert ram_offset(0x00210600) == 0x62100


def test_asset_ref_packing():
    assert decode_asset_ref(0x00000001) == (1, 0, 0)      # entry 85
    assert decode_asset_ref(0x00100101) == (1, 1, 16)     # entry 86
    assert decode_asset_ref(0x00190201) == (1, 2, 25)     # entry 87
    assert decode_asset_ref(0x00551002) == (2, 16, 85)    # entry 150
    assert decode_asset_ref(0x00020205) == (5, 2, 2)      # entry 337


def test_table_split_into_84_ram_and_253_asset(doa):
    s = load_table_summary(doa)
    assert s["entries"] == 338
    # entry 0 is the main block, so 1 + 84 = 85 RAM/code entries total
    assert len(s["ram_load"]) == 85
    assert len(s["asset_index"]) == 253


def test_ram_offsets_are_aligned_and_low(doa):
    s = load_table_summary(doa)
    for idx, size, ref, off in s["ram_load"][1:]:        # skip entry 0 (off 0)
        assert ref & 0xFF == 0
        assert off % 0x100 == 0
        assert off < 0x800000


def test_asset_count_tiers_are_monotonic(doa):
    s = load_table_summary(doa)
    tiers = asset_tiers(s["asset_index"])
    counts = [t[0] for t in tiers]
    assert counts == [1, 2, 3, 4, 5]
    # tier boundaries are contiguous and cover all 253 entries
    assert tiers[0][1] == 85 and tiers[-1][2] == 337
    for (c, a, b), (c2, a2, b2) in zip(tiers, tiers[1:]):
        assert b + 1 == a2
        assert c < c2


def test_asset_id_grid_is_six_groups_of_ten(doa):
    s = load_table_summary(doa)
    grid = id_grid(s["asset_index"])
    assert set(grid) == {0, 1, 2, 3, 4, 5}
    for group, types in grid.items():
        assert all(0 <= t <= 9 for t in types)


def test_asset_page_range(doa):
    s = load_table_summary(doa)
    pages = [p for *_, p in s["asset_index"]]
    assert 0 <= min(pages) and max(pages) <= 116


def test_cumulative_offsets_fit_within_file(doa):
    blocks = cumulative_offsets(doa)
    for idx, off, size in blocks:
        assert off + size <= len(doa)
    # total of all sizes leaves only a small trailing region
    total = blocks[-1][1] + blocks[-1][2]
    assert len(doa) - total < 0x100000
