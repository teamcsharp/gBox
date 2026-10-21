"""The firing package opts in explicitly and cannot write across process generations."""
import pytest

from gbox import re5_mods_tool as T
from test_re5_fire_animation import Memory, snapshot, rates


class Adapter(Memory):
    def __init__(self):
        super().__init__()
        self.pack(T.DEF_TABLE, ">2I", *T.DEF_SIGNATURE)
        self.pack(T.UPG_TABLE, ">I", T.UPG_SIGNATURE)

    read_memory = Memory.rd

    def write_memory(self, address, data):
        return self.wr(address, data)


@pytest.fixture(autouse=True)
def isolated_state():
    T.ORIG.clear()
    yield
    T.ORIG.clear()


def configured(monkeypatch):
    adapter = Adapter()
    T.ORIG[id(adapter)] = {"fps_set": 80.0, "fire_animation_on": True}
    monkeypatch.setattr(T, "_animation_scope", lambda ad: (id(ad), 123, "start-1", 0))
    return adapter


def test_disabled_package_does_not_read_memory_or_acquire_process_scope(monkeypatch):
    def unexpected(*args):
        pytest.fail("disabled animation package must do no process I/O")
    monkeypatch.setattr(T, "_animation_scope", unexpected)
    assert not T.maintain_fire_animation(object(), snapshot())["enabled"]


def test_explicit_fire_package_caps_animation_and_releases_on_stop(monkeypatch):
    adapter = configured(monkeypatch)
    result = T.maintain_fire_animation(adapter, snapshot())
    assert result["active"] and rates(adapter) == [8.0] * 3
    result = T.maintain_fire_animation(adapter, enabled=False)
    assert result["verified"] and result["restored"] == 3 and rates(adapter) == [1.0] * 3


def test_process_generation_change_between_guard_and_write_refuses_write(monkeypatch):
    adapter = configured(monkeypatch)
    scopes = iter(((id(adapter), 123, "start-1", 0), (id(adapter), 123, "start-2", 0)))
    monkeypatch.setattr(T, "_animation_scope", lambda ad: next(scopes))
    result = T.maintain_fire_animation(adapter, snapshot())
    assert not result["verified"] and not adapter.writes


def test_prompt_disables_only_owned_animation_rates(monkeypatch):
    adapter = configured(monkeypatch)
    assert T.maintain_fire_animation(adapter, snapshot())["active"]
    snap = snapshot() | {"prompt": "mash", "recovery_active": True}
    result = T.maintain_fire_animation(adapter, snap, enabled=False)
    assert result["restored"] == 3 and not result["active"] and rates(adapter) == [1.0] * 3


def test_missing_process_identity_does_not_write(monkeypatch):
    adapter = configured(monkeypatch)
    def missing(ad):
        raise OSError("process exited")
    monkeypatch.setattr(T, "_animation_scope", missing)
    result = T.maintain_fire_animation(adapter, snapshot())
    assert not result["verified"] and not adapter.writes
