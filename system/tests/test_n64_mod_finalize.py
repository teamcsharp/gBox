import struct
import pytest
from gbox import n64_mod_finalize as f
from gbox.romexport import n64_crc, CIC_BY_IPL3


def _rom(size):
    # synthetic z64 using a known 6102 boot code is unavailable offline; monkeypatch CIC detection
    r = bytearray(size)
    r[:4] = bytes.fromhex("80371240")
    for i in range(0x1000, 0x101000, 4):
        struct.pack_into(">I", r, i, (i * 2654435761) & 0xFFFFFFFF)
    struct.pack_into(">II", r, 0x10, 0x0414CA61, 0x2E57B8AA)  # stale pair seen on #2366
    return bytes(r)


@pytest.fixture(autouse=True)
def _cic(monkeypatch):
    monkeypatch.setattr(f, "n64_cic", lambda rom: "6102")


def test_cart_size():
    assert f.cart_size(12 * 2**20 + 1996) == 16 * 2**20
    assert f.cart_size(8 * 2**20) == 8 * 2**20
    with pytest.raises(ValueError):
        f.cart_size(65 * 2**20)


def test_finalize_pads_and_fixes_crc():
    src = _rom(8 * 2**20 + 1996)
    out, rep = f.finalize_bytes(src)
    assert len(out) == 16 * 2**20 and rep["padded"] and rep["crc_fixed"]
    assert struct.unpack_from(">II", out, 0x10) == n64_crc(out, "6102")
    assert out[len(src):] == b"\xff" * (len(out) - len(src))
    assert out[0x18:len(src)] == src[0x18:]          # payload untouched


def test_refuses_in_place(tmp_path):
    p = tmp_path / "a.z64"; p.write_bytes(_rom(4 * 2**20))
    with pytest.raises(ValueError):
        f.finalize_file(p, p)
