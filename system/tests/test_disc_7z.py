import shutil
import subprocess

import pytest

from gbox.formats import disc

@pytest.mark.skipif(not (shutil.which("7z") or shutil.which("7za")), reason="no 7z")
def test_listing_7z_reads_members_and_executable(tmp_path):
    src = tmp_path / "src"
    (src / "media").mkdir(parents=True)
    (src / "default.xbe").write_bytes(b"XBEH" + b"\0" * 60)
    (src / "media" / "a.bin").write_bytes(b"AFS\0" * 100)
    arc = tmp_path / "Game (USA).7z"
    exe = shutil.which("7z") or shutil.which("7za")
    subprocess.run([exe, "a", "-y", str(arc), "default.xbe", "media"], cwd=src, check=True, capture_output=True)
    before = arc.read_bytes()
    L = disc.listing(arc, head=8)
    assert L.kind == "archive"
    paths = {f["path"]: f for f in L.files}
    assert paths["default.xbe"]["head"] == b"XBEH\0\0\0\0"
    assert paths["media/a.bin"]["size"] == 400
    assert arc.read_bytes() == before                     # read-only



def _xiso(files: dict[str, bytes], sub: dict[str, bytes]) -> bytes:
    """Minimal plain XDVDFS image: root dir at sector 40 (root holds files + 'Media' dir), data after."""
    import struct as st

    def table(entries):                                   # right-linked list: each entry's right -> next
        out, offs = bytearray(), []
        for name, *_ in entries:
            offs.append(len(out))
            out += b"\0" * ((14 + len(name) + 3) & ~3)
        for i, (name, sec, size, attr) in enumerate(entries):
            right = offs[i + 1] // 4 if i + 1 < len(entries) else 0
            st.pack_into("<HHIIBB", out, offs[i], 0, right, sec, size, attr, len(name))
            out[offs[i] + 14:offs[i] + 14 + len(name)] = name.encode()
        return bytes(out)
    data_sec, blobs, ents, sub_ents = 48, [], [], []
    for name, b in sub.items():
        sub_ents.append((name, data_sec, len(b), 0x20)); blobs.append((data_sec, b)); data_sec += (len(b) + 2047) // 2048 + 1
    for name, b in files.items():
        ents.append((name, data_sec, len(b), 0x20)); blobs.append((data_sec, b)); data_sec += (len(b) + 2047) // 2048 + 1
    subt = table(sub_ents)
    ents.append(("Media", 44, len(subt), 0x10))
    root = table(ents)
    img = bytearray(data_sec * 2048 + 2048)
    img[32 * 2048:32 * 2048 + 28] = b"MICROSOFT*XBOX*MEDIA" + st.pack("<II", 40, len(root))
    img[40 * 2048:40 * 2048 + len(root)] = root
    img[44 * 2048:44 * 2048 + len(subt)] = subt
    for sec, b in blobs:
        img[sec * 2048:sec * 2048 + len(b)] = b
    return bytes(img)


def test_xdvdfs_stream_listing_one_pass_finds_xbe_and_subdirs():
    import io
    xbe = b"XBEH" + bytes(range(256)) * 20
    img = _xiso({"default.xbe": xbe, "data.afs": b"AFS\0" * 3000}, {"bgm.afs": b"AFS\0zz"})
    files, en, ex, notes = disc.xdvdfs_stream_listing(io.BytesIO(img), head=4, deep_bytes=1024, deep=1)
    by = {f["path"]: f for f in files}
    assert en == "default.xbe" and ex == xbe
    assert by["Media/bgm.afs"]["head"] == b"AFS\0" and by["Media/bgm.afs"]["size"] == 6
    assert by["data.afs"]["sample"] == (b"AFS\0" * 3000)[:1024]
    assert notes == []


def test_xdvdfs_stream_rejects_non_xbox():
    import io
    with pytest.raises(ValueError):
        disc.xdvdfs_stream_listing(io.BytesIO(b"\0" * (40 * 2048)))


@pytest.mark.skipif(not (shutil.which("7z") or shutil.which("7za")), reason="no 7z")
def test_listing_7z_with_single_xiso_member(tmp_path):
    xbe = b"XBEH" + b"\1" * 5000
    (tmp_path / "Game (USA).xiso.iso").write_bytes(_xiso({"default.xbe": xbe}, {"a.bin": b"ABCD"}))
    (tmp_path / "readme.txt").write_bytes(b"hi")
    arc = tmp_path / "Game (USA).7z"
    exe = shutil.which("7z") or shutil.which("7za")
    subprocess.run([exe, "a", "-y", str(arc), "Game (USA).xiso.iso", "readme.txt"], cwd=tmp_path, check=True,
                   capture_output=True)
    before = arc.read_bytes()
    L = disc.listing(arc, head=4)
    assert L.kind == "xdvdfs" and L.executable_name == "default.xbe" and L.executable == xbe
    assert {f["path"] for f in L.files} == {"default.xbe", "Media/a.bin"}
    assert arc.read_bytes() == before


def test_xbox_image_in_zip_uses_the_shared_stream_reader(tmp_path):
    import zipfile
    xbe = b"XBEH" + b"x" * 5000
    arc = tmp_path / "game.zip"
    with zipfile.ZipFile(arc, "w") as archive:
        archive.writestr("game.iso", _xiso({"default.xbe": xbe}, {}))
    result = disc.listing(arc, head=4)
    assert result.kind == "xdvdfs" and result.executable == xbe


def test_non_xbox_archive_retains_member_listing(tmp_path):
    import zipfile
    arc = tmp_path / "game.zip"
    with zipfile.ZipFile(arc, "w") as archive:
        archive.writestr("game.iso", b"other disc format")
    result = disc.listing(arc, head=4)
    assert result.kind == "zip" and result.files[0]["head"] == b"othe"
