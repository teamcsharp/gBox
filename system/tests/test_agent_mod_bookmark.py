from gbox.agent import _modifies_game


def test_read_only_mod_calls_do_not_create_replay_cards():
    assert not _modifies_game("mod", {"op": "list"})
    assert not _modifies_game("mod", {"op": "verify", "name": "example"})
    assert not _modifies_game("mod", {"op": "save", "name": "example"})
    assert not _modifies_game("re_mods", {"op": "list"})
    assert not _modifies_game("session_info", {})


def test_live_mod_apply_and_memory_write_are_bookmarked():
    assert _modifies_game("mod", {"op": "apply", "name": "example"})
    assert _modifies_game("write_memory", {"address": "0x80000000", "hex": "00"})
