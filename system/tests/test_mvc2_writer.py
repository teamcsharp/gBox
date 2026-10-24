import hashlib
import random
from pathlib import Path

import pytest

from gbox import mvc2_dat as M
from gbox import mvc2_writer as W
from gbox.mvc2_chars import _dat_bytes

GDI = next((p for p in (Path.home() / "samples/gbox-cache/dc/mvc2_usa_chd/disc.gdi",
                        Path.home() / "gbox-cache/dc/02db6d37c0e20375/disc.gdi") if p.exists()), None)


def test_lzss_roundtrip_synthetic():
    rnd = random.Random(5)
    for data in (b"", b"a", b"\x00" * 300, bytes(rnd.randrange(16) for _ in range(777)),
                 bytes([1, 2, 3, 4] * 100)):
        assert M.decodeA(W.encodeA(data), len(data)) == data


@pytest.mark.skipif(GDI is None, reason="unpacked MVC2 disc cache not present")
class TestRealPL00:
    def test_noop_and_changed_donor(self):
        dat = _dat_bytes(GDI, 0)
        assert hashlib.sha256(dat).hexdigest() == (
            "751165ed1fc9f001961a8ed02ec437c5171c7712bf9718694e6a09b97667597b")
        # re-encode several real parts: pixels must survive decode->encode->decode
        for sel in (0, 1, 7, 100, 500, 1000):
            idx, w, h = M.part_indices(dat, sel)
            assert M.decodeA(W.encode_part_pixels(idx, w, h), w * h // 2) == \
                M.twiddle_pal4(M.vflip(idx, w, h), w, h)
            # no-op replace: part pixels identical, every other part byte-identical
            new = W.replace_part(dat, sel, idx)
            assert M.part_indices(new, sel)[0] == idx
            assert M.part_count(new) == M.part_count(dat)
            assert M.dat_sections(new)[1:] == [s + (len(new) - len(dat)) if s else 0
                                                  for s in M.dat_sections(dat)[1:]]
        # changed donor: invert a part with same geometry, other parts untouched
        sel = 7
        idx, w, h = M.part_indices(dat, sel)
        donor = bytes((v + 1) & 0xF for v in idx)
        new = W.replace_part(dat, sel, donor)
        assert M.part_indices(new, sel)[0] == donor
        for other in (0, 6, 8, 1200):
            assert M.part_indices(new, other) == M.part_indices(dat, other)
