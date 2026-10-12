"""gbox.frame_ab: stock/mod A/B evidence for a player-model swap, without a vision model (#1364)."""
import numpy as np

from gbox import frame_ab as F


def _scene(seed=7, h=240, w=320):
    rng = np.random.default_rng(seed)
    base = rng.integers(40, 200, size=(h // 8, w // 8, 3))
    return np.kron(base, np.ones((8, 8, 1))).astype(np.uint8)          # blocky textured background


def _mario(img, x, y):
    out = img.copy()
    out[y:y + 16, x:x + 24] = (230, 10, 10)                            # cap + shirt red (384 px)
    out[y + 16:y + 36, x:x + 24] = (10, 20, 220)                       # overalls blue
    return out


def _dark_figure(img, x, y):
    out = img.copy()
    out[y:y + 36, x:x + 24] = (40, 44, 52)
    return out


def test_swap_is_one_blob_where_mario_red_vanishes():
    bg = _scene()
    stock, mod = _mario(bg, 160, 120), _dark_figure(bg, 160, 120)
    r = F.compare(mod, stock)
    x1, y1, x2, y2 = r["bbox"]
    assert x1 <= 160 and y1 <= 120 and x2 >= 184 and y2 >= 156
    assert r["blob_blocks"] == r["all_blocks"] > 0
    assert r["stock_red"] == 384 and r["mod_red"] == 0 and r["stock_blue"] > 0 and r["mod_blue"] == 0
    assert r["swapped"] is True


def test_identical_frames_have_no_blob_and_no_swap():
    f = _mario(_scene(), 100, 100)
    r = F.compare(f, f.copy())
    assert r["bbox"] is None and r["all_blocks"] == 0 and r["swapped"] is False


def test_mario_still_present_is_not_a_swap():
    bg = _scene()
    stock = _mario(bg, 160, 120)
    mod = _mario(bg, 168, 120)                                         # same character, slightly shifted
    assert F.compare(mod, stock)["swapped"] is False


def test_scattered_differences_are_not_one_blob():
    bg = _scene()
    stock, mod = _mario(bg, 40, 40), _dark_figure(bg, 40, 40)
    for x, y in ((200, 40), (40, 180), (240, 180), (150, 100)):         # other changes elsewhere: not a clean swap
        mod[y:y + 24, x:x + 24] = 255 - mod[y:y + 24, x:x + 24]
    r = F.compare(mod, stock)
    assert r["blob_blocks"] < 0.8 * r["all_blocks"] and r["swapped"] is False


def test_best_pairs_aligns_each_mod_frame_to_its_own_scene_and_spaces_them():
    scenes = [_scene(s) for s in (1, 2, 3)]
    stock = [(10.0 + i, s) for i, s in enumerate(scenes)]
    mod = [(20.0, _dark_figure(scenes[2], 50, 50)), (20.5, scenes[2]), (23.0, scenes[0])]
    pairs = F.best_pairs(mod, stock, k=4, min_gap=2.0)
    got = {(i, j) for _, i, j in pairs}
    assert (1, 2) in got and (2, 0) in got
    assert not ({(0, 2), (1, 2)} <= got)                                # 20.0 and 20.5 s are < 2 s apart: one kept
    assert pairs == sorted(pairs)


def test_cli_reads_timed_frames_and_reports(tmp_path):
    from PIL import Image
    bg = _scene(5)
    (tmp_path / "m").mkdir()
    (tmp_path / "s").mkdir()
    Image.fromarray(_dark_figure(bg, 160, 120)).save(tmp_path / "m" / "mod_045.10.png")
    Image.fromarray(_dark_figure(bg, 160, 120)).save(tmp_path / "m" / "mod_045.10.jpg", quality=100)
    Image.fromarray(_mario(bg, 160, 120)).save(tmp_path / "s" / "stock_043.79.jpg", quality=100)
    Image.fromarray(_mario(bg, 160, 120)).save(tmp_path / "s" / "stock_010.00.jpg", quality=100)  # outside the window
    rep = F.main([str(tmp_path / "m"), str(tmp_path / "s"), "--json", str(tmp_path / "r.json")])
    assert len(rep["pairs"]) == 1 and rep["pairs"][0]["stock"] == "stock_043.79.jpg"
    assert rep["swapped"] is True and (tmp_path / "r.json").is_file()
