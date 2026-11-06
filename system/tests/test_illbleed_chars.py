"""Illbleed reader focused tests.

Unit-level (no disc): re-run the module selftest (gradient fixture PSNR,
CMCK framing no-op byte-identical, roster C04 key).
Disc-backed (self-locating, skip cleanly if the owned cache is absent):
real C04 replace_slot no-op byte-identical on all 5 slots, and
VQ encode->decode roundtrip on slot 0 above the 30 dB bar.
"""
from pathlib import Path

import pytest

from gbox.illbleed_chars import _selftest, load_character, pvr_slot_decode, pvr_slot_encode, replace_slot, _gbix_slot


def test_selftest_independent_fixtures():
    _selftest()


def test_real_c04_noop_roundtrip():
    for gdi in (
        Path.home() / "gbox-cache/dc/81a90290abc15a37/disc.gdi",
        Path("/home/ehm_eckx/gBox_alt/gbox-cache/dc/81a90290abc15a37/disc.gdi"),
    ):
        if not gdi.is_file():
            continue
        data, slots = load_character(gdi, "C04")
        assert len(slots) == 5
        for i, s in enumerate(slots):
            out = replace_slot(data, i, s)
            assert out == data, f"slot {i} no-op roundtrip failed"
        import numpy as np
        w, h, rgba, _ = pvr_slot_decode(slots[0])
        arr = np.frombuffer(rgba, np.uint8).reshape(h, w, 4)
        enc = pvr_slot_encode(arr)
        _, _, dec, _ = pvr_slot_decode(_gbix_slot(enc, w * h * 4))
        dec_arr = np.frombuffer(dec, np.uint8).reshape(h, w, 4).astype(float)
        mse = ((dec_arr[..., :3] - arr[..., :3].astype(float)) ** 2).mean()
        assert mse > 0
        psnr = 10 * np.log10(255.0 ** 2 / mse)
        assert psnr > 30, f"VQ roundtrip PSNR {psnr:.2f} dB below 30 dB bar"
        return
    pytest.skip("owned Illbleed disc not found on this host")
