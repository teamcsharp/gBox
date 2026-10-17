from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import tools
from gbox.config import Library
from gbox.models import CatalogEntry
from gbox.registry import HOST_OS, ToolUnavailable


def _entry(**kw):
    base = dict(game_id="eecd1708cb2b8d14", title="007 - GoldenEye (Europe)", platform="n64",
                source_paths=["/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms/Europe/007 - GoldenEye (Europe).zip"],
                launch={"kind": "rom", "platform": "n64"}, format="zip", size=0, profile_id="eecd1708cb2b8d14")
    base.update(kw)
    return CatalogEntry(**base)


def test_rom_path_remaps_foreign_source_path_without_keyerror(tmp_path):
    lib = Library(id="hyperspin", paths={"linux": "/mnt/gbox/hyperspin/Arcade", "windows": "/mnt/gbox/hyperspin/Arcade",
                                         HOST_OS: str(tmp_path)})
    p = tools.rom_path(_entry(), SimpleNamespace(libraries=[lib]))
    assert p == tmp_path / "collections/Nintendo 64/roms/Europe/007 - GoldenEye (Europe).zip"


def test_rom_path_unresolvable_raises_tool_unavailable():
    with pytest.raises(ToolUnavailable):
        tools.rom_path(_entry(source_paths=["/nonexistent/x.zip"]), SimpleNamespace(libraries=[]))


def test_rom_path_explicit_launch_path_kept():
    p = tools.rom_path(_entry(launch={"kind": "rom", "path": "/x/y.zip"}), SimpleNamespace(libraries=[]))
    assert p == Path("/x/y.zip")
