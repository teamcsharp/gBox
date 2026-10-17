import hashlib
import os
from pathlib import Path
import struct
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from gbox import n64_mod_finalize as f
from gbox.romexport import n64_crc, n64_cic, n64_to_z64


def _rom(size=2 * 2**20):
    data = bytearray(size)
    data[:4] = bytes.fromhex("80371240")
    for i in range(0x1000, min(size, f.CHECKSUM_END), 4):
        struct.pack_into(">I", data, i, (i * 2654435761) & 0xFFFFFFFF)
    struct.pack_into(">II", data, 0x10, 0x0414CA61, 0x2E57B8AA)
    return bytes(data)


def _order(data, order):
    if order == "z64":
        return data
    out = bytearray(data)
    if order == "v64":
        out[0::2], out[1::2] = data[1::2], data[0::2]
    else:
        out[0::4], out[1::4], out[2::4], out[3::4] = data[3::4], data[2::4], data[1::4], data[0::4]
    return bytes(out)


@pytest.fixture
def unit_rom(monkeypatch):
    # Synthetic data isolates cache/output behavior. Owned-file tests below do
    # not request this fixture and exercise actual IPL3 detection unchanged.
    monkeypatch.setattr(f, "n64_cic", lambda rom: "6102")
    return _rom()


@pytest.mark.parametrize("size", [12 * 2**20, 12 * 2**20 + 1996, 2 * 2**20 + 1])
def test_crc_repair_never_infers_padding_from_size(unit_rom, size):
    data = _rom(size)
    out, report = f.finalize_bytes(data)
    assert len(out) == len(data) and not report["padded"] and report["crc_fixed"]
    assert struct.unpack_from(">II", out, 0x10) == n64_crc(out, "6102")
    assert out[:0x10] == data[:0x10] and out[0x18:] == data[0x18:]
    assert report["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert report["sha256"] == hashlib.sha256(out).hexdigest()
    assert report["gameplay_verified"] is False


@pytest.mark.parametrize("order", ["z64", "v64", "n64"])
def test_valid_byte_orders_are_passed_through(unit_rom, tmp_path, order):
    good, _ = f.finalize_bytes(unit_rom)
    image = tmp_path / ("good." + order)
    original = _order(good, order)
    image.write_bytes(original)
    assert f.launch_image(image) == (image, None)
    assert image.read_bytes() == original


def test_same_size_and_mtime_changes_cannot_reuse_wrong_rom(unit_rom, tmp_path):
    image = tmp_path / "build" / "game.z64"; image.parent.mkdir()
    image.write_bytes(unit_rom)
    first, report = f.launch_image(image)
    before = image.stat()
    changed = bytearray(unit_rom); changed[0x180000] ^= 0x55  # Outside header CRC window.
    image.write_bytes(changed)
    os.utime(image, ns=(before.st_atime_ns, before.st_mtime_ns))
    second, other = f.launch_image(image)
    assert first != second and report["source_sha256"] != other["source_sha256"]
    assert second.read_bytes()[0x180000] == changed[0x180000]
    assert image.read_bytes() == changed
    again, cached = f.launch_image(image)
    assert again == second and cached["cached"] and cached["crc"] == other["crc"]
    assert list(image.parent.iterdir()) == [image]


def test_valid_crc_wrong_payload_cache_is_preserved_and_recovered(unit_rom, tmp_path):
    image = tmp_path / "build" / "game.z64"; image.parent.mkdir(); image.write_bytes(unit_rom)
    first, _ = f.launch_image(image)
    wrong = bytearray(first.read_bytes()); wrong[0x180000] ^= 0x55
    assert not f.needs_finalize(wrong)  # Header CRC cannot authenticate the entire image.
    first.write_bytes(wrong)
    second, report = f.launch_image(image)
    assert second != first and report["cache_conflicts"] == 1 and not report["cached"]
    assert first.read_bytes() == wrong
    expected, _ = f.finalize_bytes(unit_rom)
    assert second.read_bytes() == expected
    assert f.launch_image(image)[0] == second


def test_existing_output_and_original_aliases_never_overwritten(unit_rom, tmp_path):
    image = tmp_path / "source.z64"; image.write_bytes(unit_rom)
    out = tmp_path / "existing.z64"; out.write_bytes(b"other user output")
    with pytest.raises(FileExistsError):
        f.finalize_file(image, out)
    assert out.read_bytes() == b"other user output"
    with pytest.raises(ValueError, match="original"):
        f.finalize_file(image, image)
    hard = tmp_path / "hard.z64"; os.link(image, hard)
    with pytest.raises(FileExistsError):
        f.finalize_file(image, hard)
    assert image.read_bytes() == unit_rom
    new = tmp_path / "new.z64"
    report = f.finalize_file(image, new)
    assert new.read_bytes() == f.finalize_bytes(unit_rom)[0] and report["crc_fixed"]
    assert not list(tmp_path.glob("*.part"))


def test_symlink_cache_or_output_cannot_redirect_a_write(unit_rom, tmp_path):
    image = tmp_path / "build" / "game.z64"; image.parent.mkdir(); image.write_bytes(unit_rom)
    victim = tmp_path / "other.z64"; victim.write_bytes(b"preserve me")
    link = tmp_path / "link.z64"
    try:
        link.symlink_to(victim)
    except OSError:
        pytest.skip("symlinks unavailable on this test host")
    with pytest.raises(FileExistsError):
        f.finalize_file(image, link)
    cache = tmp_path / ".build.n64final"; cache.mkdir()
    dst = cache / (f.CACHE_VERSION + "-" + hashlib.sha256(unit_rom).hexdigest() + ".z64")
    dst.symlink_to(victim)
    actual, report = f.launch_image(image)
    assert actual != dst and report["cache_conflicts"] == 1 and victim.read_bytes() == b"preserve me"


def test_concurrent_publication_is_complete_and_reused(unit_rom, tmp_path):
    image = tmp_path / "build" / "game.z64"; image.parent.mkdir(); image.write_bytes(unit_rom)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(f.launch_image, [image, image]))
    assert results[0][0] == results[1][0]
    assert results[0][0].read_bytes() == f.finalize_bytes(unit_rom)[0]
    assert sorted(r["cached"] for _, r in results) == [False, True]
    assert not list(results[0][0].parent.glob("*.part"))


def test_failed_publication_leaves_no_partial_artifact(unit_rom, tmp_path, monkeypatch):
    image = tmp_path / "game.z64"; image.write_bytes(unit_rom)
    out = tmp_path / "out.z64"
    def fail(*args, **kwargs):
        raise OSError("simulated publication failure")
    monkeypatch.setattr(f.os, "link", fail)
    with pytest.raises(OSError, match="publication failure"):
        f.finalize_file(image, out)
    assert not out.exists() and not list(tmp_path.glob("*.part"))


def test_unknown_ipl3_and_short_homebrew_do_not_get_rewritten(tmp_path):
    for name, data in [("custom", _rom()), ("small", _rom(0x4000))]:
        image = tmp_path / (name + ".z64"); image.write_bytes(data)
        with pytest.raises(f.UnsupportedChecksum):
            f.finalize_bytes(data)
        path, report = f.launch_image(image)
        assert path == image and report["status"] == "unverified" and not report["crc_fixed"]
        assert image.read_bytes() == data
    assert len(list(tmp_path.iterdir())) == 2


def test_bounded_input_rejects_oversize_growth_and_truncated_order(tmp_path, monkeypatch):
    image = tmp_path / "large.z64"; image.write_bytes(bytes(65))
    with pytest.raises(ValueError, match="byte limit"):
        f._read_bounded(image, 64)
    real = f.os.fstat
    def stale_size(fd):
        st = real(fd)
        return SimpleNamespace(st_mode=st.st_mode, st_size=64, st_mtime_ns=st.st_mtime_ns, st_ctime_ns=st.st_ctime_ns)
    monkeypatch.setattr(f.os, "fstat", stale_size)
    with pytest.raises(ValueError, match="grew beyond"):
        f._read_bounded(image, 64)
    for data in (b"nope" * 32, bytes.fromhex("37804012") + bytes(61), bytes.fromhex("40123780") + bytes(62)):
        with pytest.raises(ValueError):
            f.finalize_bytes(data)


@pytest.mark.parametrize("name,relative", [
    ("GOLDENEYE", "eecd1708cb2b8d14/ge_csuitbondz_cnatalya_torso/007 - GoldenEye (Europe).z64"),
    ("MARIO", "b7aecee966090bfa/sm64_writer_rt/Super Mario 64 writer-roundtrip (USA).z64"),
])
def test_owned_real_ipl3_all_byte_orders_and_copy_integrity(tmp_path, name, relative):
    path = Path(os.environ.get("GBOX_N64_" + name, str(Path.home() / "gbox-cache/mods" / relative)))
    if not path.is_file():
        pytest.skip("owned N64 evidence unavailable")
    original = f._read_bounded(path)
    source_hash = hashlib.sha256(original).hexdigest()
    native = n64_to_z64(original)
    cic = n64_cic(native)  # Actual IPL3, no monkeypatch.
    canonical, report = f.finalize_bytes(original)
    assert report["cic"] == cic
    assert len(canonical) == len(native) and canonical[:0x10] == native[:0x10] and canonical[0x18:] == native[0x18:]
    assert struct.unpack_from(">II", canonical, 0x10) == n64_crc(canonical, cic)
    from gbox.goldeneye_inventory import crc6102
    assert cic in ("6101", "6102", "7102")
    assert struct.unpack_from(">II", canonical, 0x10) == crc6102(canonical)
    for order in ("z64", "v64", "n64"):
        valid = tmp_path / (name + "." + order); valid.write_bytes(_order(canonical, order))
        assert f.launch_image(valid) == (valid, None)
        stale = bytearray(canonical); stale[0x10] ^= 1
        edited = _order(stale, order); valid.write_bytes(edited)
        output, evidence = f.launch_image(valid)
        assert evidence["crc_fixed"] and output.read_bytes() == canonical
        assert valid.read_bytes() == edited
    assert hashlib.sha256(f._read_bounded(path)).hexdigest() == source_hash
