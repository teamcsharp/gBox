"""gbox.pso_player.decode_texture_entry: the GVR/PVR routing that let the model build run on the GameCube disc."""
import numpy as np
import pytest

from gbox import ninja, pso_player


def test_a_gbix_entry_goes_to_the_gvr_decoder(monkeypatch):
    """GameCube character AFS entries start with GBIX (global index) then GVRT; they are GVR, not PVR."""
    calls = {}

    def fake_gvr(chunk):
        calls["gvr"] = chunk
        return np.zeros((4, 2, 4), dtype=np.uint8)      # (h, w, 4)

    monkeypatch.setattr("gbox.pso_gc.gvr_decode", fake_gvr)
    entry = b"GBIX" + b"\x08\x00\x00\x00" + b"\x00" * 8 + b"GVRT" + b"\x00" * 16
    w, h, rgba = pso_player.decode_texture_entry(entry)
    assert calls["gvr"] == entry
    assert (w, h) == (2, 4)
    assert isinstance(rgba, (bytes, bytearray)) and len(rgba) == 2 * 4 * 4


def test_a_gvrt_entry_also_goes_to_the_gvr_decoder(monkeypatch):
    monkeypatch.setattr("gbox.pso_gc.gvr_decode", lambda chunk: np.zeros((1, 1, 4), dtype=np.uint8))
    w, h, rgba = pso_player.decode_texture_entry(b"GVRT" + b"\x00" * 16)
    assert (w, h) == (1, 1) and len(rgba) == 4


def test_a_pvr_entry_still_goes_to_the_dreamcast_decoder(monkeypatch):
    """The same code path must keep working on a Dreamcast rip, where the entries are PVRT."""
    calls = {}

    def fake_pvr(entry):
        calls["pvr"] = entry
        return 2, 2, b"\x00" * 16, 0

    monkeypatch.setattr(ninja, "pvr_decode", fake_pvr)
    entry = b"PVRT" + b"\x00" * 16
    w, h, rgba = pso_player.decode_texture_entry(entry)
    assert calls["pvr"] == entry and (w, h) == (2, 2) and len(rgba) == 16


@pytest.mark.parametrize("magic", [b"GBIX", b"GVRT", b"PVRT"])
def test_the_returned_buffer_is_what_ninja_png_accepts(magic, monkeypatch):
    """ninja.png slices a flat RGBA buffer; returning a numpy array raised `S1 + uint8` inside it."""
    if magic in (b"GBIX", b"GVRT"):
        monkeypatch.setattr("gbox.pso_gc.gvr_decode", lambda chunk: np.zeros((2, 2, 4), dtype=np.uint8))
    else:
        monkeypatch.setattr(ninja, "pvr_decode", lambda entry: (2, 2, b"\x00" * 16, 0))
    w, h, rgba = pso_player.decode_texture_entry(magic + b"\x00" * 16)
    assert ninja.png(w, h, rgba)[:8] == b"\x89PNG\r\n\x1a\n"
