"""The inspector's RAM search (gbox/ram_search.py): Cheat Engine filters, label correlation (on / off samples narrow to
addresses whose on-values and off-values never overlap, with per-label value tables), the switch from whole samples to
sparse candidates, partial reads around few candidates, and the memory bound."""
import struct

import numpy as np
import pytest

from gbox import ram_search as S

BASE = 0x80000000


def region(size=1 << 20, seed=0):
    return bytearray(np.random.default_rng(seed).integers(0, 256, size, dtype=np.uint8).tobytes())


def test_cheat_engine_filters_find_a_counter():
    ram = region()
    s = S.Search(BASE, len(ram), "u16")
    s.sample(bytes(ram))
    addr = 0x2468                                            # a 16-bit health value: 100, then hits
    for hp, op in ((90, "decreased"), (90, "unchanged"), (75, "decreased")):
        struct.pack_into(">H", ram, addr, hp)
        st = s.sample(bytes(ram), op=op)
        assert st["after"] <= st["before"]
    s.sample(bytes(ram), op="equals", value=75)
    assert [c["address"] for c in s.candidates()] == [BASE + addr] and s.candidates()[0]["value"] == 75
    s.sample(bytes(ram), op="range", lo="0x40", hi=80)
    assert s.count() == 1
    s.sample(bytes(ram), op="not_equals", value=75)
    assert s.count() == 0


def test_increased_and_signed_and_float_compare_as_numbers():
    ram = bytearray(16)
    struct.pack_into(">h", ram, 0, -3)
    struct.pack_into(">f", ram, 4, 1.5)
    s16 = S.Search(BASE, 16, "s16")
    s16.sample(bytes(ram))
    struct.pack_into(">h", ram, 0, 2)
    s16.sample(bytes(ram), op="increased")
    assert BASE in [c["address"] for c in s16.candidates()] and s16.candidates()[0]["value"] == 2
    f = S.Search(BASE, 16, "f32")
    f.sample(bytes(ram), op="range", lo=1.0, hi=2.0)
    assert [c["address"] for c in f.candidates()] == [BASE + 4] and f.candidates()[0]["value"] == 1.5
    le = S.Search(BASE, 16, "u16", big_endian=False)
    le.sample(b"\x34\x12" + bytes(14), op="equals", value=0x1234)
    assert [c["address"] for c in le.candidates()] == [BASE]


def test_labels_keep_only_addresses_whose_on_and_off_values_never_overlap():
    rng = np.random.default_rng(1)
    ram = region(4 << 20, seed=2)
    noise = rng.integers(0, len(ram), 20000)                 # timers, positions, the frame buffer: change all the time
    prompt, door = 0x123457, 0x200001

    def frame(on, kind):
        a = np.frombuffer(bytes(ram), dtype=np.uint8).copy()
        a[noise] = rng.integers(0, 256, noise.size, dtype=np.uint8)
        a[prompt] = kind if on else 0
        a[door] = 1                                          # never changes with the event
        return a.tobytes()
    s = S.Search(BASE, len(ram), "u8", sparse_at=1 << 18)
    seq = [(True, 3), (False, 0), (True, 5), (False, 0)] * 6
    for on, kind in seq:
        s.sample(frame(on, kind), label="on" if on else "off")
    assert not s.dense and s.count() < 50                    # one on/off pair leaves the changing bytes only
    top = s.candidates(5)[0]
    assert top["address"] == BASE + prompt
    assert top["on"] == [{"value": 3, "n": 6}, {"value": 5, "n": 6}] and top["off"] == [{"value": 0, "n": 12}]
    assert BASE + door not in [c["address"] for c in s.candidates(1000)]
    st = s.status()
    assert st["samples"] == {"on": 12, "off": 12, "plain": 0} and st["dropped"]["overlap"] > 0
    assert st["dropped"]["too_many_values"] > 0              # noise takes more than K values in one label


def test_the_switch_to_sparse_keeps_the_correlation_exact():
    ram = bytearray(64)
    s = S.Search(BASE, 64, "u8", sparse_at=4)
    for on, v in ((True, 1), (True, 2), (False, 3)):         # dense: both "on" samples are kept whole
        ram[10], ram[20] = v, (7 if on else 9)
        ram[30] = v                                          # equals the off value 3 only in the off sample: fine
        s.sample(bytes(ram), label="on" if on else "off")
    assert s.dense is False
    rows = {c["address"] - BASE: c for c in s.candidates()}
    assert set(rows) == {10, 20, 30}
    assert rows[10]["on"] == [{"value": 1, "n": 1}, {"value": 2, "n": 1}] and rows[10]["off"] == [{"value": 3, "n": 1}]
    ram[10], ram[20], ram[30] = 1, 7, 3                       # address 30 shows its off value 3 while on: out
    s.sample(bytes(ram), label="on")
    assert sorted(c["address"] - BASE for c in s.candidates()) == [10, 20]


def test_tolerance_keeps_an_address_whose_labels_were_late_at_the_edges():
    # the prompt byte: 3 while the prompt shows, 0 otherwise; the labeler got one "on" sample late (the byte already 0)
    # and one "off" sample early (still 3); a noise byte overlaps a lot
    seq = [("on", 3, 7), ("off", 0, 7), ("on", 3, 9), ("off", 0, 9), ("on", 0, 7), ("off", 3, 9), ("on", 3, 9),
           ("off", 0, 7), ("on", 3, 7), ("off", 0, 9)]

    def run(tolerance, sparse_at):
        s = S.Search(BASE, 16, "u8", tolerance=tolerance, sparse_at=sparse_at)
        for lab, prompt, noise in seq:
            ram = bytearray(16)
            ram[4], ram[9] = prompt, noise
            s.sample(bytes(ram), label=lab)
        return s
    for sparse_at in (0, 1 << 20):                            # sparse from the start, and dense until the end
        exact = run(0, sparse_at)
        assert BASE + 4 not in [c["address"] for c in exact.candidates()]
        loose = run(2, sparse_at)
        c = {x["address"] - BASE: x for x in loose.candidates()}
        assert 4 in c and 9 not in c                          # 2 mislabels allowed: the prompt byte stays, noise goes
        if not loose.dense:
            assert loose.candidates()[0]["address"] == BASE + 4 and c[4]["mislabeled"] == 2
            assert c[4]["on"] == [{"value": 3, "n": 4}, {"value": 0, "n": 1}] and c[4]["off"] == [{"value": 0, "n": 4}, {"value": 3, "n": 1}]
    assert BASE + 4 not in [c["address"] for c in run(1, 0).candidates()]          # 1 allowed: still too many


def test_few_candidates_are_read_as_ranges_around_them():
    ram = region(1 << 16, seed=3)
    s = S.Search(BASE, len(ram), "u32", sparse_at=1 << 20)
    s.sample(bytes(ram))
    assert not s.dense and s.candidate_ranges() == [(BASE, len(ram))]   # 16 Ki candidates, all in one range
    for a in (0x100, 0x104, 0x9000):
        struct.pack_into(">I", ram, a, 0xDEAD0000 + a)
    s.sample(bytes(ram), op="changed")
    ranges = s.candidate_ranges()
    assert ranges == [(BASE + 0x100, 8), (BASE + 0x9000, 4)]
    blocks = [(a, bytes(ram[a - BASE:a - BASE + n])) for a, n in ranges]
    struct.pack_into(">I", ram, 0x104, 7)
    blocks[0] = (blocks[0][0], bytes(ram[0x100:0x108]))
    s.sample(blocks, op="unchanged")
    assert [c["address"] - BASE for c in s.candidates()] == [0x100, 0x9000]
    with pytest.raises(S.SearchError, match="were not in the sample"):
        s.sample([blocks[0]])


def test_memory_stays_bounded_while_dense():
    size = 1 << 20
    s = S.Search(BASE, size, "u8", max_bytes=6 << 20, sparse_at=1 << 10)
    for i in range(12):                                      # only "on" samples: nothing narrows, samples pile up
        s.sample(bytes([i % 256]) * size, label="on")
        assert s.memory() <= 6 << 20
    assert s.folded > 0 and s.dense
    assert s.candidates(10) == []                             # a million candidates: keep narrowing


def test_bad_requests():
    with pytest.raises(S.SearchError):
        S.Search(BASE, 16, "u24")
    with pytest.raises(S.SearchError):
        S.Search(BASE, 0)
    s = S.Search(BASE, 16)
    with pytest.raises(S.SearchError, match="compares with the previous sample"):
        s.sample(bytes(16), op="changed")
    with pytest.raises(S.SearchError, match="label is"):
        s.sample(bytes(16), label="maybe")
    with pytest.raises(S.SearchError, match="of the region"):
        s.sample(bytes(8))
