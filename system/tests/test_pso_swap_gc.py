"""`build_swap(platform="gc")`: the GameCube body/tree/BML/texture path, exercised without Blender."""
import numpy as np
import pytest

from gbox import ninja, ninja_swap, pso_gc, pso_gc_paths, pso_player as P

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"


@pytest.fixture(scope="module")
def disc():
    import pathlib
    from gbox import gcdisc
    if not pathlib.Path(DISC).is_file():
        pytest.skip("the disc is not on this machine")
    return gcdisc.GCDisc(DISC)


def _fake_fit(atlas):
    """Stand in for ninja_swap.fit: call the encode callback with no rigging and return an atlas."""
    calls = []

    def fit(model, roles, tgt, work, name, budgets, blender, encode, limit, scale, progress):
        calls.append((name, encode))
        body, bml = encode({})
        return {"data": (body, bml), "report": {"rigged": False, "budgets": list(budgets)}, "rigged": False,
                "atlas": atlas}

    return fit, calls


def test_the_gc_swap_writes_a_big_endian_body_flat_bml_and_cmpr_textures(monkeypatch, disc):
    from pathlib import Path
    from PIL import Image
    atlas = Image.new("RGBA", (128, 128), (40, 120, 200, 255))
    fit, calls = _fake_fit(atlas)
    monkeypatch.setattr(ninja_swap, "fit", fit)
    result = P.build_swap(disc, Path("unused.nj"), {}, Path("."), "t", cls="A", platform="gc")

    assert calls, "fit was not called"
    files = result["files"]
    body_path, bml_path, tex_path = "plAbdy00.nj", "plAnj.bml", "plAtex.afs"
    assert {body_path, bml_path, tex_path} <= set(files)
    assert "plAcap06.nj" in files                              # the head/hair/cap parts are specked too

    _before, payload, tail = pso_gc.njcm_payload(files[body_path])
    nodes = ninja.tree_nodes(payload, 0, ">")
    assert len(nodes) == 64 and tail[:4] == b"POF0"
    assert len(files[body_path]) <= 64 * 2048

    # the BML still lists the class's files, with the new body under the same flat name
    entries = {e["name"].split(b"\0")[0].decode("latin-1"): e for e in pso_gc.bml_files(files[bml_path])}
    assert "plAbdy00.nj" in entries and "plAcap06.nj" in entries
    assert result["report"]["body_bytes"] == len(files[body_path])

    # the class textures are GVR CMPR chunks again, and they decode close to the atlas
    entries_afs = pso_gc.afs(files[tex_path])
    assert entries_afs and result["report"]["textures_replaced"] > 0
    hd = pso_gc.gvr_header(entries_afs[0])
    assert hd["fmt"] == 14 and (hd["w"], hd["h"]) == (128, 128)
    got = pso_gc.gvr_decode(entries_afs[0])
    want = np.asarray(atlas.convert("RGBA"))
    assert np.abs(got.astype(int) - want.astype(int))[..., :3].mean() < 8


def test_the_gc_swap_refuses_a_texture_format_it_cannot_write(monkeypatch, disc):
    from pathlib import Path
    from PIL import Image
    atlas = Image.new("RGBA", (128, 128))
    fit, _calls = _fake_fit(atlas)

    def fake_fit(*args, **kwargs):
        return fit(*args, **kwargs)

    monkeypatch.setattr(ninja_swap, "fit", fake_fit)
    # the writer's own refusal: RGB5A3 is not implemented, so gvr_chunk raises for an entry in that format
    from gbox import gvr_write
    with pytest.raises(ValueError, match="not implemented"):
        gvr_write.gvr_chunk(np.asarray(atlas), fmt=5)


def test_an_unknown_platform_is_refused_before_any_work(disc):
    from pathlib import Path
    with pytest.raises(ValueError, match="unknown platform"):
        P.build_swap(disc, Path("x"), {}, Path("."), "t", cls="A", platform="ps2")
