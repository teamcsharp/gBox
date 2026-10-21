"""Metal Arms (GameCube) normal table: gbox.metal_arms regenerates the engine's boot-time table (0x8028E608) instead of
shipping a RAM dump. These checks pin its layout against an independent plain-math reference, its octant symmetry, the
digest of the dump it replaces, and the nearest-normal lookup the writer uses, on a synthetic table and the real one."""
import hashlib
import math

import numpy as np
import pytest

from gbox import metal_arms as MA

# sha256 of the 98400 S8 bytes at 0x804B90F4 (dumped from the running game on 2026-10-07; the file that held it,
# gbox/metal_arms_normals.bin, left the repository once the generator reproduced it byte for byte)
RAM_DUMP_SHA256 = "d4e08c68b3f99429457c32b814458483d4d469ed4fcf7c248935ec5c37a19ce1"
SIGNS = [(1, 1, 1), (-1, 1, 1), (-1, 1, -1), (1, 1, -1), (1, -1, 1), (-1, -1, 1), (-1, -1, -1), (1, -1, -1)]
AXES = [(0, 64, 0), (0, -64, 0), (64, 0, 0), (-64, 0, 0), (0, 0, 64), (0, 0, -64)]


def reference_block() -> list[tuple[int, int, int]]:
    """Block 0 from the formula alone (double precision, truncation): rings of theta entries for theta = 1..90."""
    out = [(0, 0, 0)]
    for k in range(1, 91):
        th = math.radians(k)
        y = math.trunc(64 * math.cos(th))
        for j in range(k, 0, -1):
            ph = math.radians(90.0 * j / k)
            out.append((math.trunc(64 * math.sin(th) * math.sin(ph)), y, math.trunc(64 * math.sin(th) * math.cos(ph))))
    return out


@pytest.fixture(scope="module")
def s8():
    return MA.normal_table_s8()


def test_layout_eight_octant_blocks_then_the_axes(s8):
    assert s8.shape == (MA.NORMAL_ENTRIES, 3) == (32800, 3) and s8.dtype == np.int8
    for b in range(8):
        assert tuple(s8[4096 * b]) == (0, 0, 0)                # every block starts with the zero normal
    assert [tuple(int(v) for v in r) for r in s8[32768:32774]] == AXES
    assert not s8[32774:].any()                                # the allocation is rounded up to 0x18060 bytes


def test_block_zero_rings_match_the_plain_math_reference(s8):
    ref = np.array(reference_block(), np.int64)
    assert len(ref) == 4096
    block = s8[:4096].astype(np.int64)
    assert [tuple(r) for r in block[1:4]] == [(1, 63, 0), (2, 63, 0), (1, 63, 1)]
    assert [tuple(r) for r in block[7:11]] == [(4, 63, 0), (4, 63, 1), (3, 63, 3), (1, 63, 4)]   # theta 4: phi 90, 67.5, 45, 22.5
    diff = np.abs(block - ref)
    assert diff.max() <= 1                                     # float32 vs double rounding only ever moves one unit
    assert (diff.any(axis=1)).mean() < 0.025                   # and only where a product sits on an integer


def test_other_blocks_are_sign_flips_of_block_zero(s8):
    block = s8[:4096].astype(np.int64)
    for i, sg in enumerate(SIGNS):
        assert np.array_equal(s8[4096 * i:4096 * (i + 1)].astype(np.int64), block * np.array(sg)), i


def test_generated_table_equals_the_engine_ram_dump(s8):
    assert hashlib.sha256(s8.tobytes()).hexdigest() == RAM_DUMP_SHA256


def test_float_table_is_unit_length_with_six_fraction_bits(s8):
    t = MA.normal_table()
    assert t.shape == (32800, 3) and t.dtype == np.float32 and not t.flags.writeable
    assert MA.normal_table() is t                              # cached for the process
    assert np.array_equal(t * 64, s8.astype(np.float32))
    norms = np.linalg.norm(t[1:32774].astype(np.float64), axis=1)
    norms = norms[norms > 0]
    assert len(norms) == 32774 - 1 - 7 and norms.min() > 0.95 and norms.max() <= 1.0 + 1e-6


def test_nearest_normals_on_a_synthetic_table_and_on_the_real_one():
    synth = np.array(AXES + [(37, 37, 37)], np.float32) / 64.0
    want = np.array([[0.1, 0.9, 0.0], [0.0, -1.0, 0.1], [1.0, 0.2, 0.0], [-0.9, 0.0, 0.1], [0.0, 0.0, 1.0],
                     [0.1, 0.1, -1.0], [1.0, 1.0, 1.0]])
    assert MA._nearest_normals(want, synth).tolist() == [0, 1, 2, 3, 4, 5, 6]
    real = MA.normal_table()
    picked = MA._nearest_normals(np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, -1.0]]), real)
    assert (real[picked] * 64).tolist() == [[0, 64, 0], [64, 0, 0], [0, 0, -64]]   # the exact axis entries win
    assert picked[0] == 32768 and picked[2] == 32773           # +Y and -Z exist only in the axis list; +X is also ring 90's first
    want = np.array([0.3, 0.8, -0.5]) / np.linalg.norm([0.3, 0.8, -0.5])
    picked = MA._nearest_normals(want[None], real)[0]
    assert 4096 * 3 <= picked < 4096 * 4                       # the (+x, +y, -z) octant block
    assert real[picked] @ want / np.linalg.norm(real[picked]) > 0.999
