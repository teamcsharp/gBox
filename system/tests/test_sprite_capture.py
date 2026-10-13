"""gbox.sprite_capture: a sprite's animation out of a running 2D game, from the point the operator highlighted
(#1438 scope b, #1384). Synthetic frames: a coloured sprite cycling through poses over a textured scenery."""
import io
import json
import shutil
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from gbox import sprite_capture as S
from gbox import tools
from gbox.config import Config
from gbox.registry import Ctx, Unsupported

W, H = 160, 120
RED = (250, 20, 20)
BLUE = (20, 20, 250)


def backdrop(seed=7, w=W, h=H):
    rng = np.random.default_rng(seed)
    base = rng.integers(40, 200, size=(h // 8, w // 8, 3))
    return np.kron(base, np.ones((8, 8, 1))).astype(np.uint8)          # blocky textured scenery


def pose(name):
    """16x16 pose canvases: A a 12x16 body, B the body minus a notch, C the body plus an arm to the left."""
    m = np.zeros((16, 16), bool)
    m[:, 4:16] = True
    if name == "B":
        m[0:4, 12:16] = False
    if name == "C":
        m[6:9, 0:4] = True
    return m


def draw(frame, x, y, name, colour=RED):
    out = frame.copy()
    out[y:y + 16, x:x + 16][pose(name)] = colour
    return out


def expected_box(x, y, name, margin=2):
    ys, xs = np.nonzero(pose(name))
    x0, y0, x1, y1 = x + xs.min(), y + ys.min(), x + xs.max() + 1, y + ys.max() + 1
    return [x0 - margin, y0 - margin, x1 - x0 + 2 * margin, y1 - y0 + 2 * margin]


def static_scene(n=24):
    """The sprite walks right 2 px a frame, poses A B C each held for two frames; a blue distractor bobs far away."""
    bg = backdrop()
    frames, poses = [], []
    for i in range(n):
        p = "ABC"[(i // 2) % 3]
        f = draw(bg, 20 + 2 * i, 50, p)
        frames.append(draw(f, 120, 20 + (i % 2), "A", BLUE))
        poses.append(p)
    return frames, poses


def scrolling_scene(n=30):
    """The camera scrolls 3 px a frame over a wide scenery; the sprite keeps its screen position (poses A, B)."""
    world = backdrop(11, 400, H)
    frames, poses = [], []
    for i in range(n):
        p = "AB"[(i // 3) % 2]
        frames.append(draw(world[:, 3 * i:3 * i + W].copy(), 60, 40, p))
        poses.append(p)
    return frames, poses


def check_cutout(crop, name, colour=RED):
    """Opaque pixels are exactly the pose, in the sprite's colour; everything else is transparent black."""
    alpha = crop[..., 3]
    assert set(np.unique(alpha).tolist()) <= {0, 255}
    assert int((alpha == 255).sum()) == int(pose(name).sum())
    assert (crop[alpha == 255][:, :3] == colour).all()
    assert not crop[alpha == 0].any()


def png(frame):
    b = io.BytesIO()
    Image.fromarray(frame, "RGB").save(b, "PNG")
    return b.getvalue()


def make_ctx(tmp_path):
    return Ctx(Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache"), job_id="job1234567890")


# ------------------------------------------------------------------------------------------------ analysis

def test_register_measures_the_scroll_between_frames():
    a = backdrop(3)
    frames = [a, np.roll(a, -3, axis=1), np.roll(a, -6, axis=1), np.roll(np.roll(a, -6, axis=1), 2, axis=0)]
    assert S.register(frames, 24) == [(0, 0), (-3, 0), (-6, 0), (-6, 2)]


def test_static_scene_tracks_the_sprite_cuts_it_out_and_finds_the_loop():
    frames, poses = static_scene()
    a = S.analyze(frames, seed=(30, 58), margin=2, tolerance=24, fps=30)
    assert a["background"] == "static" and a["scrolling"] is False and a["lost"] == []
    assert a["offsets"] == [(0, 0)] * 24                      # the sprite moving does not fool the registration
    for i, p in enumerate(poses):
        assert a["boxes"][i] == expected_box(20 + 2 * i, 50, p)
    assert a["runs"] == [[2 * k, 2 * k + 1] for k in range(12)]   # each pose held two frames -> one unique frame
    assert a["durations_ms"] == [67] * 12
    assert a["loop"] == {"start": 0, "length": 3, "repeats": 4.0, "frames": [0, 1, 2]}
    assert len(a["frames"]) == 12 and a["canvas"] == [20, 21]
    for k, crop in enumerate(a["frames"]):
        check_cutout(crop, "ABC"[k % 3])
    assert np.array_equal(a["frames"][0], a["frames"][3])    # the same pose cuts out identically wherever it is
    assert not np.array_equal(a["frames"][0], a["frames"][1])


def test_scrolling_scenery_is_registered_and_removed():
    frames, poses = scrolling_scene()
    a = S.analyze(frames, seed=(70, 48), margin=2, tolerance=24, fps=30)
    assert a["background"] == "scrolling" and a["scrolling"] is True and a["lost"] == []
    assert a["offsets"][:4] == [(0, 0), (-3, 0), (-6, 0), (-9, 0)]
    assert a["bg_quality"] > 0.95
    for i, p in enumerate(poses):
        assert a["boxes"][i] == expected_box(60, 40, p)
    assert len(a["frames"]) == 10 and a["durations_ms"] == [100] * 10
    assert a["loop"]["start"] == 0 and a["loop"]["length"] == 2
    for k, crop in enumerate(a["frames"]):
        check_cutout(crop, "AB"[k % 2])


def test_consecutive_identical_frames_merge_into_durations():
    flat = np.full((H, W, 3), (90, 90, 90), np.uint8)
    held = "AAABAAAB"
    frames = [draw(flat, 40 + i, 30, p) for i, p in enumerate(held)]   # walking 1 px a frame, poses held 3, 1, 3, 1
    a = S.analyze(frames, seed=(50, 38), fps=30)
    assert a["background"] == "flat"
    assert a["runs"] == [[0, 1, 2], [3], [4, 5, 6], [7]]       # the same image merges; the boxes keep the motion
    assert a["durations_ms"] == [100, 33, 100, 33]
    assert [b[0] for b in a["boxes"]] == [42 + i for i in range(8)]
    assert a["loop"] == {"start": 0, "length": 2, "repeats": 2.0, "frames": [0, 1]}
    frames = [draw(backdrop(5), 40, 30, p) for p in held]        # idle over textured scenery: nothing to go on
    with pytest.raises(Unsupported, match="not a flat colour"):
        S.analyze(frames, seed=(50, 38), fps=30)


def test_no_loop_when_the_sequence_does_not_repeat():
    flat = np.full((H, W, 3), (10, 10, 10), np.uint8)

    def loop_of(poses):
        frames = [draw(flat, 30 + 2 * i, 30, p) for i, p in enumerate(poses)]
        return S.analyze(frames, seed=(40, 38), fps=30)["loop"]
    assert loop_of("ABCAB") == {"start": 0, "length": 3, "repeats": 1.67, "frames": [0, 1, 2]}
    assert loop_of("CABCABC") == {"start": 0, "length": 3, "repeats": 2.33, "frames": [0, 1, 2]}
    assert loop_of("BCABAB") == {"start": 2, "length": 2, "repeats": 2.0, "frames": [2, 3]}   # a lead-in, then the loop
    assert loop_of("ABCBA") is None
    assert loop_of("ABCA") is None                                 # one repeated frame is not evidence of a loop
    assert S.find_loop([np.zeros((4, 4, 4), np.uint8)], 24) is None


def test_idle_sprite_on_a_flat_colour_uses_the_border_colour():
    flat = np.full((H, W, 3), (90, 90, 90), np.uint8)
    frames = [draw(flat, 50, 40, "A")] * 3
    a = S.analyze(frames, seed=(58, 48), fps=30)
    assert a["background"] == "flat" and len(a["frames"]) == 1 and a["durations_ms"] == [100] and a["loop"] is None
    check_cutout(a["frames"][0], "A")
    assert S.analyze(frames[:1], seed=(58, 48), fps=30)["canvas"] == [16, 20]   # one frame works too


def test_a_box_seed_takes_the_sprite_inside_it_and_a_miss_is_reported():
    frames, poses = static_scene(24)
    a = S.analyze(frames, box=(14, 44, 28, 28), fps=30)
    assert a["boxes"][0] == expected_box(20, 50, "A") and len(a["frames"]) == 12
    with pytest.raises(Unsupported, match="no sprite at that point"):
        S.analyze(frames, seed=(80, 100), fps=30)             # empty scenery: nothing moves, nothing flat
    with pytest.raises(ValueError):
        S.analyze(frames, fps=30)


def test_expand_repeats_the_loop_section():
    assert S.expand([67, 67, 33], 30) == [0, 0, 1, 1, 2]
    assert S.expand([33, 33, 33], 30, loops=2, loop={"start": 1, "length": 2}) == [0, 1, 2, 1, 2]
    assert S.expand([33, 33], 30, loops=2) == [0, 1, 0, 1]


def test_sheet_index_locates_every_frame():
    frames, _ = static_scene(24)
    a = S.analyze(frames, seed=(30, 58), fps=30)
    index, files, reason = S.package(a, {"capture": "c", "name": "hero", "clip": "walk", "game": {}, "session": "s"},
                                     want_mp4=False)
    assert reason == "not requested" and "clip.mp4" not in files
    sheet = np.asarray(Image.open(io.BytesIO(files["sheet.png"])).convert("RGBA"))
    assert index["columns"] == 4 and index["rows"] == 3 and sheet.shape == (3 * 21, 4 * 20, 4)
    for f in index["frames"]:
        x, y, w, h = f["sheet"]
        cell = sheet[y:y + h, x:x + w]
        assert np.array_equal(cell, np.asarray(Image.open(io.BytesIO(files[f["file"]])).convert("RGBA")))
        assert f["duration_ms"] == 67 and len(f["source_frames"]) == 2 and f["box"] == a["boxes"][f["source_frames"][0]]
    assert index["loop"]["length"] == 3
    with zipfile.ZipFile(io.BytesIO(files["frames.zip"])) as z:
        assert sorted(z.namelist()) == sorted([f["file"] for f in index["frames"]] + ["sheet.json"])
    apng = files["preview.apng"]
    assert apng.startswith(S.PNG_SIG) and b"acTL" in apng          # an animated PNG
    gif = S.preview_bytes(a["frames"], a["durations_ms"], "gif")
    assert gif[:6] in (b"GIF89a", b"GIF87a")


# ------------------------------------------------------------------------------------------------ the tool

def live_session(monkeypatch, frames, sid="worker-game"):
    """A fake running game: get_frame hands out the frames in order, then fails like a closed window."""
    it = iter([png(f) for f in frames])

    def get_frame():
        try:
            return next(it)
        except StopIteration:
            raise RuntimeError("the game window isn't open")
    ad = SimpleNamespace(get_frame=get_frame, supported={"get_frame"})
    monkeypatch.setitem(tools.SESSIONS, sid, (ad, {"game_id": "owned-game", "title": "Hero Quest (USA)", "platform": "snes"}))
    monkeypatch.setattr(S, "_sleep", lambda s: None)


def test_tool_capture_without_ffmpeg_reports_the_mp4_unavailable_and_delivers_the_rest(monkeypatch, tmp_path):
    frames, _ = static_scene(24)
    live_session(monkeypatch, frames)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    ctx = make_ctx(tmp_path)
    out = S.sprite_capture(S.SpriteIn(session_id="worker-game", x=30 / W, y=58 / H, seconds=0.8, fps=30,
                                      name="Hero", clip="walk", save=False), ctx)
    r = out["result"]
    assert r["op"] == "capture" and r["frames"] == 12 and r["source_frames"] == 24 and r["fps"] == 30
    assert r["mp4"] == "unavailable" and "ffmpeg" in r["mp4_reason"] and r["artifacts"]["mp4"] is None
    assert r["loop"]["length"] == 3 and r["boxes"][0] == expected_box(20, 50, "A") and r["collection"] is None
    names = [n for n, *_ in ctx.artifacts]
    assert "clip.mp4" not in names
    assert {"sheet.png", "sheet.json", "preview.apng", "frames.zip", "frame_0000.png", "frame_0011.png"} <= set(names)
    arts = {n: d for n, d, *_ in ctx.artifacts}
    assert S._validate(S.SpriteOut(result=r), arts) == []
    assert S._validate(S.SpriteOut(result=r), {"sheet.png": arts["frame_0000.png"]}) == ["sheet.png hash mismatch"]
    prov = next(p for n, d, mt, p in ctx.artifacts if n == "sheet.png")
    assert prov["session"] == "worker-game" and prov["game"] == "owned-game" and prov["capture"] == r["capture"]
    index = json.loads(arts["sheet.json"])
    assert index["frames"][0]["sheet"] == [0, 0, 20, 21] and index["picture"] == [W, H]
    stored = S.captures_root(ctx.config) / r["capture"]
    assert (stored / "capture.json").is_file() and (stored / "frame_0011.png").is_file()
    listed = S.sprite_capture(S.SpriteIn(op="list"), ctx)["result"]
    assert [c["capture"] for c in listed["captures"]] == [r["capture"]]
    assert S.sprite_capture(S.SpriteIn(op="list", name="nobody"), ctx)["result"]["captures"] == []


def test_tool_export_rescales_and_loops_a_stored_capture(monkeypatch, tmp_path):
    frames, _ = static_scene(24)
    live_session(monkeypatch, frames)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    ctx = make_ctx(tmp_path)
    cid = S.sprite_capture(S.SpriteIn(session_id="worker-game", x=30, y=58, seconds=0.8, fps=30, save=False), ctx)["result"]["capture"]
    ctx.artifacts.clear()
    r = S.sprite_capture(S.SpriteIn(op="export", capture=cid, fmt="gif", scale=2, loops=3), ctx)["result"]
    assert r["size"] == [40, 42] and r["frames"] == 12
    name, data, mt, prov = ctx.artifacts[0]
    assert name == f"{cid}.gif" and mt == "image/gif" and data[:6] == b"GIF89a"
    assert int.from_bytes(data[6:8], "little") == 40 and int.from_bytes(data[8:10], "little") == 42
    assert b"NETSCAPE2.0" in data and prov["loops"] == 3
    r = S.sprite_capture(S.SpriteIn(op="export", capture=cid, fmt="mp4", scale=1), ctx)["result"]
    assert r["artifact"] == "unavailable" and "ffmpeg" in r["reason"]
    with pytest.raises(ValueError, match="no capture"):
        S.sprite_capture(S.SpriteIn(op="export", capture="nope"), ctx)
    with pytest.raises(ValueError, match="fmt is"):
        S.sprite_capture(S.SpriteIn(op="export", capture=cid, fmt="avi"), ctx)


def test_a_session_that_cannot_provide_frames_fails_clearly(monkeypatch, tmp_path):
    ctx = make_ctx(tmp_path)
    with pytest.raises(Unsupported, match="no longer available"):
        S.sprite_capture(S.SpriteIn(session_id="gone-session", x=0.5, y=0.5), ctx)
    live_session(monkeypatch, [])                                 # the window closed before the first frame
    with pytest.raises(Unsupported, match="cannot provide frames .*window isn't open"):
        S.sprite_capture(S.SpriteIn(session_id="worker-game", x=0.5, y=0.5, seconds=1), ctx)
    with pytest.raises(ValueError, match="highlighted point"):
        S.sprite_capture(S.SpriteIn(session_id="worker-game"), ctx)
    with pytest.raises(ValueError, match="unknown op"):
        S.sprite_capture(S.SpriteIn(op="dance"), ctx)
    monkeypatch.setattr(S, "_sleep", lambda s: None)
    frames, _ = static_scene(5)
    got, times = S.grab_frames(live_session(monkeypatch, frames) or tools.SESSIONS["worker-game"][0].get_frame, 2, 30)
    assert len(got) == 5 and len(times) == 5                      # the window closing mid-capture keeps what we have


def test_capture_files_a_2d_entry_in_the_character_collection(monkeypatch, tmp_path):
    from gbox import characters as C
    monkeypatch.setenv("GBOX_CHARACTERS", str(tmp_path / "chars"))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    ctx = make_ctx(tmp_path)
    frames, _ = static_scene(24)
    live_session(monkeypatch, frames)
    r = S.sprite_capture(S.SpriteIn(session_id="worker-game", x=30, y=58, seconds=0.8, fps=30, name="Hero", clip="walk"), ctx)["result"]
    assert r["collection_error"] is None and r["collection"] == {"slug": "hero", "root": str(tmp_path / "chars"),
                                                                 "clip": "walk", "animations": 1, "kind": "sprites"}
    root = tmp_path / "chars"
    meta = C.get(root, "hero")
    assert meta["kind"] == "sprites" and meta["model"] == "sheet.png" and meta["picture"] == "2d"
    assert meta["source"] == {"game_title": "Hero Quest (USA)", "game_id": "owned-game", "platform": "snes",
                              "from": "sprite_capture", "session": "worker-game"}
    assert (root / "hero" / "preview.png").is_file() and (root / "hero" / "clips" / "walk" / "preview.apng").is_file()
    clip = meta["animations"][0]
    assert clip["clip"] == "walk" and clip["frames"] == 12 and clip["loop"]["length"] == 3 and clip["mp4"] is None
    assert clip["sheet"] == "clips/walk/sheet.png" and json.loads((root / "hero" / clip["index"]).read_text())["frames"]
    checked = C.verify_entry(root, meta)
    assert checked["model_bytes"] and checked["preview"]["coverage"] > 0.1   # the small sheet is scaled up, not a smudge
    assert [m["slug"] for m in C.list_all(root)] == ["hero"]
    frames, _ = scrolling_scene(30)
    live_session(monkeypatch, frames)
    r = S.sprite_capture(S.SpriteIn(session_id="worker-game", x=70, y=48, seconds=1.0, fps=30, name="Hero", clip="Run"), ctx)["result"]
    assert r["collection"]["animations"] == 2
    meta = C.get(root, "hero")
    assert [c["clip"] for c in meta["animations"]] == ["walk", "run"] and meta["model"] == "sheet.png"
    assert (root / "hero" / "clips" / "run" / "sheet.json").is_file()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
def test_mp4_through_ffmpeg():
    frames, _ = static_scene(6)
    a = S.analyze(frames, seed=(30, 58), fps=30)
    data = S.mp4_bytes(a["frames"], a["durations_ms"], 30, loops=2, loop=a["loop"])
    assert data[4:8] == b"ftyp"


# ------------------------------------------------------------------------------------------------ inputs

def test_picture_coordinates_accept_fractions_or_pixels():
    assert S.picture_coords(S.SpriteIn(x=0.5, y=1.0), 640, 480) == ((320, 479), None)
    assert S.picture_coords(S.SpriteIn(x=33, y=44), 640, 480) == ((33, 44), None)
    assert S.picture_coords(S.SpriteIn(box=[0.25, 0.5, 0.1, 0.2]), 640, 480) == (None, (160, 240, 64, 96))
    assert S.picture_coords(S.SpriteIn(box=[10, 20, 30, 40]), 640, 480) == (None, (10, 20, 30, 40))
    with pytest.raises(ValueError):
        S.picture_coords(S.SpriteIn(box=[1, 2]), 640, 480)


def test_game_rate_defaults():
    assert S.game_fps({"title": "Sonic (Europe)", "platform": "md"}) == 50
    assert S.game_fps({"title": "Sonic (USA)", "platform": "md"}) == 60
    assert S.game_fps({"fps": "59.94"}) == 59.94
    assert S.game_fps({}) == 0 and S.game_fps(None) == 0


def test_grab_frames_keeps_to_the_budget_and_stops_on_repeated_failures(monkeypatch):
    monkeypatch.setattr(S, "_sleep", lambda s: None)
    calls = []

    def get():
        calls.append(1)
        if len(calls) > 3:
            raise RuntimeError("gone")
        return np.zeros((8, 8, 3), np.uint8)
    got, times = S.grab_frames(get, 20, 60)
    assert len(got) == 3 and len(calls) == 3 + 5                  # five failures in a row end the capture
    monkeypatch.setattr(S, "MAX_FRAMES", 10)
    got, _ = S.grab_frames(lambda: np.zeros((8, 8, 3), np.uint8), 20, 60)
    assert len(got) == 10
    monkeypatch.setattr(S, "MAX_BYTES", 5 * 100)
    got, _ = S.grab_frames(lambda: b"x" * 100, 20, 60)
    assert len(got) == 5
    with pytest.raises(Unsupported, match="cannot provide frames"):
        S.grab_frames(lambda: b"", 1, 30)


def test_frames_decode_bytes_and_arrays_alike():
    f = backdrop(2)
    fr = S.Frames([png(f), f, f[..., 0]])
    assert len(fr) == 3 and np.array_equal(fr[0], f) and np.array_equal(fr[1], f) and fr[2].shape == f.shape
    assert np.array_equal(fr[-1][..., 1], f[..., 0])
