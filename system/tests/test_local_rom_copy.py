"""A dropped library share never stops a title this PC already holds (operator 2026-11-09: "for the titles in merc
mode, I want those roms on the lilspark itself so it is ironclad")."""
from types import SimpleNamespace

from gbox import catalog, mercmode


def test_the_staged_copy_stands_in_only_when_the_share_is_out_of_reach(tmp_path):
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    share = tmp_path / "share" / "Resident Evil 5" / "Resident Evil 5.nsp"
    staged = cfg.cache / "52d15709be0fda1a" / "Resident Evil 5.nsp"
    assert catalog.local_copy(share, "52d15709be0fda1a", cfg) is None          # neither exists
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"")
    assert catalog.local_copy(share, "52d15709be0fda1a", cfg) is None          # an empty file is not a game
    staged.write_bytes(b"NSP")
    assert catalog.local_copy(share, "52d15709be0fda1a", cfg) == staged        # the share is down: this PC's copy
    assert catalog.local_copy(share, "another-game", cfg) is None              # only this game's own folder
    share.parent.mkdir(parents=True)
    share.write_bytes(b"NSP")
    assert catalog.local_copy(share, "52d15709be0fda1a", cfg) is None          # the share answers: it is the source


def test_mercmode_counts_a_title_playable_from_its_local_copy(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    share = tmp_path / "share" / "Resident Evil 5.nsp"
    from gbox import tools
    monkeypatch.setattr(tools, "rom_path", lambda entry, config: share)
    game = {"game_id": "52d15709be0fda1a", "title": "Resident Evil 5", "platform": "switch",
            "source_paths": [str(share)], "format": "nsp", "profile_id": "switch"}
    out = mercmode.inspect_rom_access(cfg, game)
    assert out["reachable"] is False and "not reachable" in out["reason"]
    staged = cfg.cache / "52d15709be0fda1a" / "Resident Evil 5.nsp"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"NSP")
    out = mercmode.inspect_rom_access(cfg, game)
    assert out["reachable"] is True and out["path"] == str(staged) and "local cache copy" in out["source"]
