import pytest
from gbox import goldeneye_pal_unlock as g


def _fake():
    rom = bytearray(0x60000)
    rom[g.FUNC_OFFSET:g.FUNC_OFFSET + len(g.ORIGINAL)] = g.ORIGINAL
    return bytes(rom)


def test_rejects_unverified_rom():
    with pytest.raises(ValueError):
        g.apply(_fake())


def test_patch_only_touches_function(monkeypatch):
    rom = _fake()
    monkeypatch.setattr(g, 'ROM_SHA256', __import__('hashlib').sha256(rom).hexdigest())
    out = g.apply(rom)
    assert len(out) == len(rom)
    diff = [i for i in range(len(rom)) if rom[i] != out[i]]
    assert diff and min(diff) >= g.FUNC_OFFSET and max(diff) < g.FUNC_OFFSET + 12
    assert out[g.FUNC_OFFSET:g.FUNC_OFFSET + 12] == g.PATCH
