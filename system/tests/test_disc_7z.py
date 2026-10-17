import shutil
import subprocess

import pytest

from gbox.formats import disc

SLT = r"""
7-Zip [64] 16.02

Listing archive: x.7z

--
Path = x.7z
Type = 7z

----------
Path = game
Size = 0
Attributes = D....
Folder = +

----------
Path = game\default.xbe
Size = 12
Folder = -

Path = game\media\a.bin
Size = 3
Folder = -
"""


def test_parse_slt_skips_folders_and_normalises_paths():
    files = disc.parse_7z_slt(SLT)
    assert files == [{"path": "game/default.xbe", "size": 12}, {"path": "game/media/a.bin", "size": 3}]


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
    assert L.kind == "7z"
    paths = {f["path"]: f for f in L.files}
    assert paths["default.xbe"]["head"] == b"XBEH\0\0\0\0"
    assert paths["media/a.bin"]["size"] == 400
    assert arc.read_bytes() == before                     # read-only
