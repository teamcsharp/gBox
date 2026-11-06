"""re4gc_zombies.body_candidates: the known body slots, and the skinned-BIN fallback for other enemy files."""
from gbox import re4gc_zombies


class _Bin:
    def __init__(self, bones):
        self.bones = bones


class _Pack:
    def __init__(self, items):
        self.items = items


class _Enemies:
    def __init__(self, slots):
        self._slots = slots

    def body_slots(self, pack):
        return list(self._slots)


def test_the_known_layout_wins_when_it_has_slots():
    pack = _Pack([("BIN", b"a")])
    assert re4gc_zombies.body_candidates(pack, _Enemies([3, 5])) == [3, 5]


def test_without_known_slots_the_biggest_skeleton_is_the_body(monkeypatch):
    """em21/em2b hold the same skinned BIN at other indices; the biggest skeleton is the body."""
    pack = _Pack([("TPL", b"t"), ("BIN", b"small"), ("BIN", b"big"), ("BIN", b"junk")])
    sizes = {b"small": 12, b"big": 74}

    def fake_bin_read(payload):
        if payload not in sizes:
            raise ValueError("not a BIN")
        return _Bin(bones=[0] * sizes[payload])

    monkeypatch.setattr(re4gc_zombies.re4gc_models, "bin_read", fake_bin_read)
    assert re4gc_zombies.body_candidates(pack, _Enemies([])) == [2, 1]      # biggest first


def test_a_pack_with_no_skinned_bin_still_reports_nothing(monkeypatch):
    pack = _Pack([("BIN", b"junk"), ("TPL", b"t")])
    monkeypatch.setattr(re4gc_zombies.re4gc_models, "bin_read", lambda payload: _Bin(bones=[]))
    assert re4gc_zombies.body_candidates(pack, _Enemies([])) == []
