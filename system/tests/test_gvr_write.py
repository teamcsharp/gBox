"""The GVR writer: a texture it produces must read back identically (RGBA8) or within CMPR's quantisation."""
import numpy as np
import pytest

from gbox import gvr_write as GW, pso_gc as P


def _rgba(rng, h, w):
    return rng.integers(0, 256, (h, w, 4), dtype=np.uint8)


@pytest.mark.parametrize("h,w", [(8, 8), (16, 8), (32, 32), (5, 7), (1, 1)])
def test_a_written_rgba8_texture_reads_back_identically(h, w):
    rng = np.random.default_rng(h * 31 + w)
    rgba = _rgba(rng, h, w)
    chunk = GW.gvr_chunk(rgba, gbix=0x1234, fmt=GW.GVR_RGBA8)
    header = P.gvr_header(chunk)
    assert header["fmt"] == GW.GVR_RGBA8
    assert (header["w"], header["h"]) == (w, h)
    assert header["gbix"] == 0x1234
    assert np.array_equal(P.gvr_decode(chunk), rgba)


def test_a_flat_cmpr_texture_of_565_colours_round_trips_exactly():
    img = np.zeros((8, 8, 4), np.uint8)
    for y in range(8):
        for x in range(8):
            colour = (255, 255, 255) if (x < 4) == (y < 4) else ((0, 0, 0) if x < 4 else (0, 0, 255))
            img[y, x] = (*colour, 255)
    chunk = GW.gvr_chunk(img, fmt=GW.GVR_CMPR)
    assert P.gvr_header(chunk)["fmt"] == GW.GVR_CMPR
    assert np.array_equal(P.gvr_decode(chunk), img)


def test_a_cmpr_gradient_is_close_not_exact():
    img = np.zeros((8, 8, 4), np.uint8)
    for y in range(8):
        for x in range(8):
            img[y, x] = (x * 8, y * 8, 128, 255)
    back = P.gvr_decode(GW.gvr_chunk(img, fmt=GW.GVR_CMPR))
    diff = np.abs(back.astype(int) - img.astype(int))
    assert diff[..., :3].mean() < 8 and diff[..., :3].max() <= 24      # block compression is lossy by design


def test_without_a_gbix_the_chunk_starts_at_gvrt():
    chunk = GW.gvr_chunk(np.zeros((4, 4, 4), np.uint8))
    assert chunk.startswith(b"GVRT") and P.gvr_header(chunk)["gbix"] is None


def test_an_unsupported_format_is_refused():
    with pytest.raises(ValueError, match="not implemented"):
        GW.gvr_chunk(np.zeros((4, 4, 4), np.uint8), fmt=5)          # RGB5A3 is not written yet


def test_a_non_rgba_image_is_refused():
    with pytest.raises(ValueError, match="RGBA"):
        GW.gvr_chunk(np.zeros((4, 4, 3), np.uint8))


def test_a_real_disc_texture_survives_decode_encode_decode():
    import pathlib
    from gbox import gcdisc
    disc = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                        r"\Phantasy Star Online Episode I & II Plus (USA).iso")
    if not disc.is_file():
        pytest.skip("the disc is not on this machine")
    d = gcdisc.GCDisc(str(disc))
    gvm = next((n for n in d.files if n.lower().endswith(".gvm")), None)
    assert gvm, "no GVM on the disc"
    _name, chunk = P.gvm_entries(d.read(gvm))[0]
    original = P.gvr_decode(chunk)
    # lossless in RGBA8
    assert np.array_equal(P.gvr_decode(GW.gvr_chunk(original, fmt=GW.GVR_RGBA8)), original)
    # and within CMPR's quantisation in the block format the game uses
    again = P.gvr_decode(GW.gvr_chunk(original, fmt=GW.GVR_CMPR))
    diff = np.abs(again.astype(int) - original.astype(int))[..., :3]
    assert diff.mean() < 2.0 and diff.max() <= 16
