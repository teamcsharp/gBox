"""gbox.side_dirs: the Spark's gBox side folders in ~/gBox_alt (operator 2026-10-20), found before and after the move."""
from pathlib import Path

from gbox import side_dirs as S


def test_a_side_folder_is_used_where_it_is(tmp_path):
    (tmp_path / "gbox-cache").mkdir()
    assert S.side_dir("gbox-cache", home=tmp_path) == tmp_path / "gbox-cache"            # not moved yet: the old place
    (tmp_path / "gBox_alt" / "gbox-cache").mkdir(parents=True)
    assert S.side_dir("gbox-cache", home=tmp_path) == tmp_path / "gBox_alt" / "gbox-cache"   # both: the new one
    (tmp_path / "gbox-cache").rmdir()
    assert S.side_dir("gbox-cache", home=tmp_path) == tmp_path / "gBox_alt" / "gbox-cache"
    assert S.side_dir("gBox-src", home=tmp_path) == tmp_path / "gBox_alt" / "gBox-src"   # neither yet: made in gBox_alt


def test_old_and_new_paths_name_the_same_place(tmp_path):
    old = tmp_path / "gbox-hermes-tasks" / "abc"
    new = tmp_path / "gBox_alt" / "gbox-hermes-tasks" / "abc"
    new.mkdir(parents=True)
    assert S.moved(old, home=tmp_path) == new                                             # a record written before
    assert S.moved(new, home=tmp_path) == new
    new.rename(tmp_path / "x")
    old.parent.mkdir()
    (tmp_path / "x").rename(old)
    assert S.moved(new, home=tmp_path) == old                                             # the new name before the move
    assert S.moved(tmp_path / "samples" / "gbox-cache", home=tmp_path) == tmp_path / "samples" / "gbox-cache"
    assert S.moved(Path("/elsewhere/gbox-cache"), home=tmp_path) == Path("/elsewhere/gbox-cache")


def test_the_cache_in_gbox_toml_follows_the_move(tmp_path, monkeypatch):
    from gbox import config
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "gBox_alt" / "gbox-cache").mkdir(parents=True)
    cfg = config.Config(cache_dirs={config.HOST_OS: str(tmp_path / "gbox-cache")})
    assert cfg.cache == tmp_path / "gBox_alt" / "gbox-cache"


def test_the_default_data_dir_is_never_the_working_directory(tmp_path, monkeypatch):
    from gbox import config
    monkeypatch.chdir(tmp_path)
    assert config.Config().data_dir.is_absolute() and config.Config().data_dir.name == "gbox-data"
    assert tmp_path not in config.Config().data_dir.parents


def test_the_hermes_repo_follows_its_env_path(tmp_path, monkeypatch):
    from gbox import hermes_delivery
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "gBox_alt" / "gbox-hermes-repo").mkdir(parents=True)
    monkeypatch.setenv("GBOX_HERMES_REPO", str(tmp_path / "gbox-hermes-repo"))        # the service's old setting
    assert hermes_delivery.repository() == tmp_path / "gBox_alt" / "gbox-hermes-repo"
    monkeypatch.delenv("GBOX_HERMES_REPO")
    assert hermes_delivery.repository() == tmp_path / "gBox_alt" / "gbox-hermes-repo"
