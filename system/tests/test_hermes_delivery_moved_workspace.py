"""Task-workspace records survive the move of the side folders into ~/gBox_alt."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import hermes_delivery as HD

RID = "89c27bd5d1d9449c"


class _Home:
    def __init__(self, home): self.home = home
    def __enter__(self):
        self.old = Path.home
        Path.home = classmethod(lambda cls: self.home)
        return self.home
    def __exit__(self, *a):
        Path.home = self.old


def test_workspace_path_resolves_a_moved_folder(tmp_path):
    home = tmp_path / "home"
    new = home / "gBox_alt" / "gbox-hermes-tasks" / RID
    new.mkdir(parents=True)
    old = home / "gbox-hermes-tasks" / RID
    with _Home(home):
        assert HD._workspace_path(old) == new
        assert HD._workspace_path(new) == new
        assert HD._workspace_path(old / "system") == new / "system"
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        assert HD._workspace_path(outside) == outside


def test_normalise_workspace_rewrites_pre_move_paths(tmp_path):
    home = tmp_path / "home"
    (home / "gBox_alt" / "gbox-hermes-tasks" / RID / "system").mkdir(parents=True)
    (home / "gBox_alt" / "gbox-hermes-repo").mkdir(parents=True)
    rec = {"request_id": RID, "number": 2868,
           "path": str(home / "gbox-hermes-repo"),
           "workdir": str(home / "gbox-hermes-tasks" / RID / "system"),
           "branch": "hermes/request-2868-1"}
    with _Home(home):
        out = HD._normalise_workspace(dict(rec))
    assert out["path"] == str(home / "gBox_alt" / "gbox-hermes-repo")
    assert out["workdir"] == str(home / "gBox_alt" / "gbox-hermes-tasks" / RID / "system")
    assert out["branch"] == "hermes/request-2868-1"
    assert out["request_id"] == RID
