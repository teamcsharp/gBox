import numpy as np
import pytest

from gbox.aki_wcw import tex_decode, tex_encode, texture_colours


def test_revenge_ci4_with_two_palette_banks():
    header = bytes.fromhex('031f002000000205')  # 4 x 32, 32 palette entries, 4-bit pixels
    tex = header + bytes([0x12, 0x34] * 32)
    palette = np.arange(32, dtype='>u2').tobytes()
    assert texture_colours(tex) == 16
    decoded = tex_decode(tex, palette)
    assert decoded.shape == (32, 4, 4)
    encoded, banks = tex_encode(header, decoded, 16)
    assert len(encoded) == len(tex)
    assert len(banks) == 64 and banks[:32] == banks[32:]
    assert tex_decode(encoded, banks).shape == decoded.shape


def test_head_ci8_and_truncated_pixels():
    header = bytes.fromhex('0303010000000202')
    assert texture_colours(header + bytes(16)) == 256
    with pytest.raises(ValueError, match='truncated'):
        texture_colours(header + bytes(7))


def test_revenge_player_detection_uses_revenge_slot_address(monkeypatch):
    from types import SimpleNamespace
    from gbox import characters, aki_wcw
    seen = []
    def read(ctx, tool, inp, worker, limit):
        seen.append(inp['address'])
        return {'state':'succeeded', 'output':{'sha256':'fixture'}}
    monkeypatch.setattr(characters, '_job', read)
    monkeypatch.setattr('httpx.get', lambda *args, **kwargs: SimpleNamespace(content=bytes.fromhex('0201') + bytes(14)))
    wrestler = {'code':0x201, 'name':'Hollywood Hogan'}
    ctx = SimpleNamespace(server='fixture', headers={})
    assert aki_wcw._player1(ctx, {'session_id':'w-1'}, [wrestler],
                            aki_wcw.PROFILES[('NW2E',0)]['slot_code']) == wrestler
    assert seen == [0x8006A2A4]
