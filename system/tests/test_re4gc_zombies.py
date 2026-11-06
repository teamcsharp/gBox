"""re4gc_zombies: the fitting ladder and the padding rule, on injected swaps (no disc needed)."""
import pytest

from gbox import re4gc_zombies

ORIGINAL = 1000


def _read(name):
    return b"\1" * ORIGINAL


def _rig():
    return {"joints": [], "prims": [], "roles": {}}


class _FakeEnemies:
    """Stands in for re4gc_enemies: one body slot, a template, and primitives of known sizes."""
    @staticmethod
    def body_slots(pack):
        return [0, 1, 2]

    @staticmethod
    def retarget(rig, template):
        return [{"pos": [0] * 300}, {"pos": [0] * 120}, {"pos": [0] * 60}]

    @staticmethod
    def write_rigged_gltf(prims, template, path):
        path.write_text(str(len(prims)))
        return path


class _FakeModels:
    class ModelPack:
        def __init__(self, data):
            self.items = [("BIN", b"template")]

    @staticmethod
    def bin_read(data):
        return data


class _FakeAttachments:
    """Carries the primitive count from the written .gltf into the .glb, which is what swap() reads."""
    @staticmethod
    def pack(path):
        return {"count": path.read_text()}, b""

    @staticmethod
    def glb_bytes(doc, blob):
        return doc["count"].encode()


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(re4gc_zombies, "PACKS", ("em10",))
    monkeypatch.setattr(re4gc_zombies, "re4gc_enemies", _FakeEnemies)
    monkeypatch.setattr(re4gc_zombies, "re4gc_models", _FakeModels)
    monkeypatch.setattr(re4gc_zombies, "attachments", _FakeAttachments)


def test_the_ladder_runs_from_full_detail_to_thinning():
    plan = re4gc_zombies.attempts([4, 1])
    assert plan[0] == ("keep=4 tex=64", 4, 64, 1.0)
    assert plan[1] == ("keep=1 tex=64", 1, 64, 1.0)
    assert any(rung[2] == 16 for rung in plan)               # small textures before cutting geometry
    assert plan[-1][3] < 0.5 and "thin" in plan[-1][0]       # thinning is the last resort


def test_a_fitting_swap_is_padded_to_the_original_size(fake, tmp_path):
    seen = []

    def swap(original, glb, body, hide, max_tex):
        seen.append((max_tex, hide))
        return b"\2" * 900                        # smaller than the original

    report = re4gc_zombies.swap_ganados("iso", "model", tmp_path, rig=_rig(), read=_read, swap=swap, log=lambda *_: None)
    assert report["em10"]["fitted"] is True
    written = (tmp_path / "em10.drs").read_bytes()
    assert len(written) == ORIGINAL              # padded, so nothing of the original stays readable
    assert written[:900] == b"\2" * 900 and written[900:] == b"\0" * 100


def test_a_pack_that_cannot_fit_reports_its_best_size(fake, tmp_path):
    def swap(original, glb, body, hide, max_tex):
        return b"\2" * (ORIGINAL + 40)

    report = re4gc_zombies.swap_ganados("iso", "model", tmp_path, rig=_rig(), read=_read, swap=swap, log=lambda *_: None)
    assert report["em10"]["fitted"] is False
    assert "grows" in report["em10"]["reason"]
    assert not (tmp_path / "em10.drs").exists()


def test_the_ladder_keeps_the_biggest_primitive_when_that_is_what_fits(fake, tmp_path):
    calls = []

    def swap(original, glb, body, hide, max_tex):
        keep = int(glb.read_text())
        calls.append(keep)
        return b"\2" * (ORIGINAL if keep == 1 else ORIGINAL + 100)

    report = re4gc_zombies.swap_ganados("iso", "model", tmp_path, rig=_rig(), read=_read, swap=swap, log=lambda *_: None)
    assert report["em10"]["fitted"] is True
    assert calls == [3, 1]                        # every primitive first, then only the biggest
    assert "keep=1" in report["em10"]["how"]


def test_spare_bodies_are_always_collapsed(fake, tmp_path):
    hides = []

    def swap(original, glb, body, hide, max_tex):
        hides.append(hide)
        return b"\2" * 900

    re4gc_zombies.swap_ganados("iso", "model", tmp_path, rig=_rig(), read=_read, swap=swap, log=lambda *_: None)
    assert hides[0] == (1, 2)                     # every body slot but the one being replaced


def test_a_partial_rig_is_refused_rather_than_retargeted(fake):
    class _BadRigRoles:
        @staticmethod
        def named(joints, parent, names):
            return {"head": names[0]}

    with pytest.raises(ValueError, match="only 1 joint roles"):
        re4gc_zombies.derive_rig("model", characters=_FakeChars(), rig_roles=_BadRigRoles)


class _FakeChars:
    @staticmethod
    def _load(model):
        return {"nodes": [{"name": "n0"}]}, None, None, [[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]]

    @staticmethod
    def rig_from_gltf(model, roles):
        return {"joints": [], "prims": [], "roles": roles}
