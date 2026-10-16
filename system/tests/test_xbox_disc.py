"""Disc preparation rejects untrusted paths and publishes only verified copies."""
import hashlib
from contextlib import contextmanager
import io
import json
from pathlib import Path
import struct
import sys
import zipfile

import pytest

from gbox import xbox, xbox_disc as disc
from gbox.config import Config
from gbox.registry import ToolUnavailable, Unsupported


def config(tmp_path):
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")


def image(tmp_path, base=0):
    path = tmp_path / "game.iso"
    header = bytearray(2048)
    header[:20] = header[-20:] = disc.MAGIC
    struct.pack_into("<II", header, 20, 34, 256)
    with path.open("wb") as writer:
        writer.seek(base + 0x10000)
        writer.write(header)
        writer.seek(base + 0x20000 - 1)
        writer.write(b"\0")
    return path


def valid_listing():
    return ("extract-xiso v2.7.1\nlisting game.iso:\n"
            "/default.xbe (8 bytes)\n/assets/ (32 bytes)\n/assets/body.bin (4 bytes)\n"
            "2 files in game.iso total 12 bytes\n")


def fake_tool(monkeypatch, *, listing=None, change_image=False, extra=False):
    calls = []
    monkeypatch.setattr(disc, "ensure_extractor", lambda cfg: Path("extract-xiso.exe"))
    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[1] == "-m", "Media patching must be explicitly disabled"
        if "-l" in argv:
            return (listing or valid_listing()).encode()
        assert "-x" in argv and "-r" not in argv and "-c" not in argv
        target = Path(argv[argv.index("-d") + 1])
        target.mkdir()
        (target / "default.xbe").write_bytes(b"XBEHboot")
        (target / "assets").mkdir()
        (target / "assets" / "body.bin").write_bytes(b"body")
        if extra:
            (target / "unlisted.bin").write_bytes(b"unexpected")
        if change_image:
            with Path(argv[-1]).open("r+b") as stream:
                stream.seek(-1, 2)
                stream.write(b"x")
        return b""
    monkeypatch.setattr(disc, "_run", run)
    return calls


@pytest.mark.parametrize("base", disc.BASES)
def test_layout_recognizes_xiso_and_full_dvd_descriptor_offsets(tmp_path, base):
    path = image(tmp_path, base)
    assert disc.layout(path) == {"base": base, "root_sector": 34, "root_bytes": 256}


def test_unknown_truncated_descriptor_and_out_of_bounds_root_fail(tmp_path):
    path = image(tmp_path)
    with path.open("r+b") as stream:
        stream.seek(0x107EC)
        stream.write(b"broken")
    with pytest.raises(ValueError, match="incomplete"):
        disc.layout(path)
    path = image(tmp_path)
    with path.open("r+b") as stream:
        stream.seek(0x10014)
        stream.write(struct.pack("<II", 0xFFFFFFFF, 256))
    with pytest.raises(ValueError, match="bounds"):
        disc.layout(path)
    path.write_bytes(b"not an image")
    with pytest.raises(Unsupported, match="size"):
        disc.layout(path)


def test_ambiguous_xdvdfs_volumes_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(disc, "BASES", (0, 0x20000))
    path = image(tmp_path, 0x20000)
    with path.open("r+b") as stream:
        stream.seek(0x30000)
        header = stream.read(2048)
        stream.seek(0x10000)
        stream.write(header)
    with pytest.raises(Unsupported, match="ambiguous"):
        disc.layout(path)


@pytest.mark.parametrize("name", ["../escape.xbe", "safe/../../escape", "C:/escape", "CON.txt", "a./file", "name ", "a\\..\\file", "a//file", "a/<bad>", "NUL", "COM\u00b9.txt"])
def test_listing_rejects_unsafe_windows_names(name):
    text = f"/{name} (8 bytes)\n1 files in bad.iso total 8 bytes\n"
    with pytest.raises(ValueError, match="unsafe|invalid"):
        disc.listing(text, 1024)


@pytest.mark.parametrize("text", [
    "/default.xbe (8 bytes)\n/DEFAULT.XBE (8 bytes)\n2 files in bad.iso total 16 bytes\n",
    "/default.xbe (8 bytes)\n/assets (4 bytes)\n/assets/body.bin (4 bytes)\n3 files in bad.iso total 16 bytes\n",
    "/default.xbe (8 bytes)\n1 files in bad.iso total 9 bytes\n",
    "/default.xbe (8 bytes)\n",
    "/default.xbe (4294967296 bytes)\n1 files in bad.iso total 4294967296 bytes\n",
])
def test_listing_rejects_collisions_file_parents_bad_summary_and_oversize(text):
    with pytest.raises(ValueError):
        disc.listing(text, disc.MAX_IMAGE)


def test_xbox360_disc_cannot_be_treated_as_original_xbox():
    with pytest.raises(Unsupported, match="Xbox 360"):
        disc.listing("/default.xex (8 bytes)\n1 files in xbox360.iso total 8 bytes\n", 1024)


def test_image_copy_cache_is_atomic_content_checked_and_source_unchanged(tmp_path, monkeypatch):
    source = image(tmp_path)
    original = source.read_bytes()
    cfg = config(tmp_path)
    calls = fake_tool(monkeypatch)
    result = disc.prepare(source, cfg)
    assert result.read_bytes() == b"XBEHboot"
    assert source.read_bytes() == original
    assert (result.parent / "assets" / "body.bin").read_bytes() == b"body"
    assert result.is_relative_to(cfg.runtime)
    assert not (result.parent / ".recomp-storage").exists()
    before = result.stat()
    assert disc.prepare(source, cfg) == result and len(calls) == 2
    assert result.stat().st_ino == before.st_ino and result.stat().st_mtime_ns == before.st_mtime_ns
    (result.parent / "assets" / "body.bin").write_bytes(b"oops")
    with pytest.raises(ValueError, match="cache content differs"):
        disc.prepare(source, cfg)
    assert source.read_bytes() == original


@pytest.mark.parametrize("options,error", [({"extra": True}, "differs"), ({"change_image": True}, "source image changed")])
def test_failed_extraction_or_changed_source_never_publishes_cache(tmp_path, monkeypatch, options, error):
    source, cfg = image(tmp_path), config(tmp_path)
    fake_tool(monkeypatch, **options)
    with pytest.raises(ValueError, match=error):
        disc.prepare(source, cfg)
    assert not list((cfg.runtime / "xbox" / "discs").glob("disc-*"))


def test_unsafe_listing_never_invokes_extract_mode(tmp_path, monkeypatch):
    source, cfg = image(tmp_path), config(tmp_path)
    calls = fake_tool(monkeypatch, listing="/../escape (1 bytes)\n1 files in bad.iso total 1 bytes\n")
    with pytest.raises(ValueError, match="unsafe"):
        disc.prepare(source, cfg)
    assert len(calls) == 1 and "-l" in calls[0]


def test_archive_with_one_image_is_prepared_then_extracted_and_ambiguity_fails(tmp_path, monkeypatch):
    archive, cfg = tmp_path / "game.zip", config(tmp_path)
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("disc/game.xiso.iso", b"image")
        writer.writestr("source.txt", b"metadata")
    def prepare(source, config, progress):
        assert source.read_bytes() == b"image"
        xbe = source.parent / "default.xbe"
        xbe.write_bytes(b"XBEH")
        return xbe
    monkeypatch.setattr(disc, "prepare", prepare)
    assert xbox.prepare_xbe(archive, cfg).read_bytes() == b"XBEH"
    with zipfile.ZipFile(archive, "a") as writer:
        writer.writestr("another.iso", b"ambiguous")
    with pytest.raises(ValueError, match="exactly one"):
        xbox.prepare_xbe(archive, cfg)


@pytest.mark.parametrize("unsafe", ["NUL.txt", "DISC/game.iso"])
def test_image_archive_unsafe_names_and_case_collisions_fail_before_unpack(tmp_path, monkeypatch, unsafe):
    archive, cfg = tmp_path / "game.zip", config(tmp_path)
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("disc/game.iso", b"image")
        writer.writestr(unsafe, b"unsafe")
    from gbox import rom_archives
    monkeypatch.setattr(rom_archives, "prepare", lambda *a: pytest.fail("unsafe archive must not unpack"))
    with pytest.raises(ValueError, match="unsafe|colliding|exactly one"):
        xbox.prepare_xbe(archive, cfg)


def test_extractor_install_pins_checksum_and_existing_binary(tmp_path, monkeypatch):
    import httpx
    binary = b"MZ" + b"\0" * 1000
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("artifacts/extract-xiso.exe", binary)
        archive.writestr("artifacts/LICENSE.TXT", b"upstream license")
    content = payload.getvalue()
    monkeypatch.setattr(disc, "HOST_OS", "windows")
    monkeypatch.setattr(disc, "ZIP_SHA256", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(disc, "EXE_SHA256", hashlib.sha256(binary).hexdigest())
    @contextmanager
    def stream(*args, **kwargs):
        yield httpx.Response(200, content=content, request=httpx.Request("GET", disc.URL))
    monkeypatch.setattr(httpx, "stream", stream)
    cfg = config(tmp_path)
    exe = disc.ensure_extractor(cfg)
    assert exe.read_bytes() == binary
    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: pytest.fail("must reuse pinned install"))
    assert disc.ensure_extractor(cfg) == exe
    unexpected = exe.parent / "msvcrt.dll"
    unexpected.write_bytes(b"must never load a local DLL")
    with pytest.raises(ToolUnavailable, match="changed"):
        disc.ensure_extractor(cfg)
    unexpected.unlink()
    exe.write_bytes(b"changed")
    with pytest.raises(ToolUnavailable, match="changed"):
        disc.ensure_extractor(cfg)


def test_native_tool_output_and_cycle_timeout_are_bounded():
    with pytest.raises(ValueError, match="size limit"):
        disc._run([sys.executable, "-c", "import sys;sys.stdout.write('x'*1000000)"], limit=1024, timeout=5)
    with pytest.raises(TimeoutError, match="time limit"):
        disc._run([sys.executable, "-c", "import time;time.sleep(30)"], limit=1024, timeout=0.1)
