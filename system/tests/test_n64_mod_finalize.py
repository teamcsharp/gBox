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


def test_launch_image_finalizes_copy_and_caches(tmp_path):
    mod = tmp_path / "ge_mod"; mod.mkdir()
    img = mod / "007.z64"; src = _rom(8 * 2**20 + 1996); img.write_bytes(src)
    path, rep = f.launch_image(img)
    assert path != img and path.parent.name == ".ge_mod.n64final"   # outside the manifest folder
    assert img.read_bytes() == src                                  # built mod untouched
    assert not f.needs_finalize(path.read_bytes()) and rep["crc_fixed"]
    again, rep2 = f.launch_image(img)
    assert again == path and rep2["cached"]
    assert list(mod.iterdir()) == [img]


def test_launch_image_passthrough_when_valid(tmp_path):
    good, _ = f.finalize_bytes(_rom(8 * 2**20))
    img = tmp_path / "ok.z64"; img.write_bytes(good)
    assert f.launch_image(img) == (img, None)


def test_valid_12mib_image_not_rewritten(tmp_path):
    r = bytearray(_rom(12 * 2**20)); struct.pack_into(">II", r, 0x10, *n64_crc(bytes(r), "6102"))
    img = tmp_path / "ge.z64"; img.write_bytes(bytes(r))
    assert not f.needs_finalize(bytes(r)) and f.launch_image(img) == (img, None)
