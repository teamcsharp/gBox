import io
import threading
import time

from fastapi.testclient import TestClient
from PIL import Image

from gbox import adapters, remote_desktop, tools, worker
from gbox.remote_desktop import (crop_jpeg, frame_for_view, game_rects_header, parse_game_rects, shown_on_screen,
                                 still_jpeg, stream_parts, window_fraction)
from gbox.server import create_app


def test_app_view_crops_desktop_to_window():
    source = Image.new("RGB", (400, 200), "red")
    source.paste(Image.new("RGB", (200, 100), "blue"), (100, 50))
    data = io.BytesIO()
    source.save(data, format="JPEG")
    cropped = crop_jpeg(data.getvalue(), (0.25, 0.25, 0.5, 0.5))
    with Image.open(io.BytesIO(cropped)) as image:
        assert image.size == (200, 100)
        assert image.getpixel((100, 50))[2] > 200


def test_app_view_does_not_expose_desktop_without_window():
    assert crop_jpeg(b"unused", None) is None
    assert crop_jpeg(b"unused", (0, 0, 2, 1)) is None
    assert frame_for_view(b"desktop pixels", "app", None) is None
    assert frame_for_view(b"desktop pixels", "desktop", None) == b"desktop pixels"


# --- #2858: a game another PC plays, watched alone in the Sessions view ------------------------------------------
GBOX = (0.25, 0.25, 0.5, 0.5)          # the gBox window on that PC's screen (blue)
GAME = (0.375, 0.375, 0.25, 0.25)      # the game docked inside it (green)


def desktop_jpeg() -> bytes:
    source = Image.new("RGB", (800, 400), "red")
    source.paste(Image.new("RGB", (400, 200), "blue"), (200, 100))
    source.paste(Image.new("RGB", (200, 100), (0, 255, 0)), (300, 150))
    data = io.BytesIO()
    source.save(data, format="JPEG", quality=95)
    return data.getvalue()


def picture(part: bytes) -> Image.Image:
    head = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    assert part.startswith(head) and part.endswith(b"\r\n")
    return Image.open(io.BytesIO(part[len(head):-2]))


def test_window_fraction_clips_to_the_virtual_desktop_and_skips_slivers():
    screen = (-1920, 0, 3840, 1080)                                   # a monitor left of the primary one
    assert window_fraction((-1920, 0, 0, 1080), screen) == (0.0, 0.0, 0.5, 1.0)
    assert window_fraction((-100, -50, 300, 250), screen) == (1820 / 3840, 0.0, 400 / 3840, 250 / 1080)
    assert window_fraction((1800, 900, 2400, 1400), screen) is None    # only 120 x 180 of it on the screen
    assert window_fraction((-16000, -16000, -14720, -15040), screen) is None   # a GPU capture source parked off-screen
    assert window_fraction((0, 0, 1280, 960), (0, 0, 0, 0)) is None


def test_a_window_counts_as_shown_only_when_most_of_it_is_its_own_pixels():
    box = (100, 100, 900, 700)
    assert shown_on_screen(box, 42, lambda x, y: 42)
    assert not shown_on_screen(box, 42, lambda x, y: 7)               # gBox in front of a warming capture source
    assert shown_on_screen(box, 42, lambda x, y: 7 if (x, y) == (500, 400) else 42)   # a menu over the middle
    assert not shown_on_screen(box, 42, lambda x, y: 42 if y < 300 else 0)            # 3 of 9 points: covered
    assert not shown_on_screen((5, 5, 5, 9), 42, lambda x, y: 42)


def test_game_rect_header_round_trips_and_drops_malformed_entries():
    rects = {"a68af3144f704f75-4a979744f8bc46d4": (0.25, 0.1, 0.5, 0.8), "w1-s8": (0.0, 0.0, 1.0, 1.0)}
    assert parse_game_rects(game_rects_header(rects)) == rects
    junk = ("w1-s7=0.1,0.1,0.5;bad id=0,0,1,1;w1-s9=0,0,1.5,1;w1-s10=nan,0,1,1;w1-s11=0,0,0,1;=0,0,1,1;"
            "w1-s12=a,b,c,d;w1-s13=0.1,0.2,0.3,0.4")
    assert parse_game_rects(junk) == {"w1-s13": (0.1, 0.2, 0.3, 0.4)}
    assert parse_game_rects("") == {} and parse_game_rects(None) == {}
    many = ";".join(f"w-s{i}=0,0,1,1" for i in range(40))
    assert len(parse_game_rects(many)) == remote_desktop.GAME_RECTS_MAX


def test_game_view_shows_the_game_window_alone_and_never_the_desktop():
    with Image.open(io.BytesIO(frame_for_view(desktop_jpeg(), "game", GAME))) as game:
        assert game.size == (200, 100)
        r, g, b = game.getpixel((100, 50))
        assert g > 200 and r < 60 and b < 60
    assert frame_for_view(desktop_jpeg(), "game", None) is None


def frames(*items):
    """next_frame for stream_parts: the given frames in turn, then the last one again; records each `seen` asked for."""
    asked, queue = [], list(items)

    def next_frame(seen):
        asked.append(seen)
        return queue.pop(0) if queue else items[-1]
    return next_frame, asked


def test_stream_crops_each_new_frame_and_hands_control_back_when_there_is_nothing_to_send():
    image, now, renewals = desktop_jpeg(), 1000.0, []
    shown = {"seq": 1, "ts": now, "image": image, "app_rect": GBOX}
    hidden = {"seq": 2, "ts": now, "image": image, "app_rect": None}         # no gBox window on that screen
    old = {"seq": 3, "ts": now - 30, "image": image, "app_rect": GBOX}       # that PC stopped sending long ago
    next_frame, asked = frames(shown, shown, hidden, old)
    gen = stream_parts(next_frame, "app", renew=lambda: renewals.append(1), clock=lambda: now)
    with picture(next(gen)) as first:
        assert first.size == (400, 200)
    # b"" (sends nothing) instead of looping inside the generator: the server notices a viewer that left, the watch
    # stops being renewed and that PC stops capturing its screen
    assert [next(gen) for _ in range(4)] == [b""] * 4
    assert asked == [0, 1, 1, 2, 3], "an old frame counts as seen: the next wait blocks instead of spinning"
    assert len(renewals) == 5


def test_game_stream_crops_to_that_sessions_window_only():
    image, now = desktop_jpeg(), 1000.0
    mine = {"seq": 1, "ts": now, "image": image, "app_rect": GBOX, "game_rects": {"w1-s7": GAME}}
    other = {"seq": 2, "ts": now, "image": image, "app_rect": GBOX, "game_rects": {"w1-s8": GAME}}
    gen = stream_parts(frames(mine, other)[0], "game", "w1-s7", clock=lambda: now)
    with picture(next(gen)) as game:
        assert game.size == (200, 100) and game.getpixel((100, 50))[1] > 200
    assert next(gen) == b"", "another session's window is never shown for this one"
    with picture(next(stream_parts(frames(mine)[0], "desktop", clock=lambda: now))) as whole:
        assert whole.size == (800, 400)


def test_status_lists_the_game_windows_that_screen_shows_and_the_game_view_needs_a_session(cfg):
    app = create_app(cfg)
    app.state.store.put("worker", "jay", {"id": "jay", "name": "JAYBUILTFINALE", "os": "windows", "tools": [],
                                          "unavailable": {}, "last_seen": time.time()})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    up = client.post("/api/workers/jay/desktop/frame", content=desktop_jpeg(),
                     headers={"x-gbox-app-rect": "0.25,0.25,0.5,0.5", "x-gbox-game-rects": "jay-s1=0.375,0.375,0.25,0.25;junk"})
    assert up.status_code == 200, up.text
    status = client.get("/api/workers/jay/desktop/status").json()
    assert status["games"] == ["jay-s1"] and status["app_available"] is True and status["frames"] == 1
    assert client.get("/api/workers/jay/desktop/stream", params={"view": "game"}).status_code == 422
    assert client.get("/api/workers/jay/desktop/stream", params={"view": "everything"}).status_code == 422
    # a worker without the game crop sends no such header: nothing listed, its frames still count
    assert client.post("/api/workers/jay/desktop/frame", content=desktop_jpeg()).status_code == 200
    status = client.get("/api/workers/jay/desktop/status").json()
    assert status["games"] == [] and status["app_available"] is False and status["frames"] == 2


def test_worker_reports_its_shown_game_windows_and_a_failing_lookup_never_ends_the_stream(monkeypatch):
    class Proc:
        pid = 4242

    class Native:
        proc = Proc()

    class Streamed:
        proc = None
    monkeypatch.setattr(worker._builtin, "SESSIONS", {"w-s1": (Native(), {}), "w-s2": (Streamed(), {})})
    asked = {}
    monkeypatch.setattr(remote_desktop, "game_window_rects", lambda pids: asked.update(pids) or {"w-s1": GAME})
    assert worker._game_rects() == {"w-s1": GAME} and asked == {"w-s1": 4242}
    monkeypatch.setattr(remote_desktop, "game_window_rects", lambda pids: 1 / 0)
    assert worker._game_rects() == {}


def test_desktop_frames_carry_the_game_windows_next_to_the_gbox_window(monkeypatch):
    stop, posts = threading.Event(), []

    class Stream:
        def __init__(self, *args, **kwargs):
            self.proc, self.seq, self.latest = None, 1, b"\xff\xd8frame\xff\xd9"

        def wait(self, seen, timeout):
            return True

        def close(self):
            pass

    class Reply:
        def __init__(self, data=None):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url):
            return Reply({"watch": True})

        def post(self, url, content=None, headers=None, timeout=None):
            posts.append((url, headers))
            stop.set()
            return Reply()
    monkeypatch.setattr(worker, "HOST_OS", "windows")
    monkeypatch.setattr(worker.httpx, "Client", Client)
    monkeypatch.setattr(adapters, "MjpegStream", Stream)
    monkeypatch.setattr(remote_desktop, "gbox_window_rect", lambda: GBOX)
    monkeypatch.setattr(worker, "_game_rects", lambda: {"w-s1": GAME})
    worker._desktop_stream(stop, "w", "http://spark", {}, None)
    url, headers = posts[0]
    assert url == "/api/workers/w/desktop/frame"
    assert headers["x-gbox-app-rect"] == "0.250000,0.250000,0.500000,0.500000"
    assert parse_game_rects(headers["x-gbox-game-rects"]) == {"w-s1": GAME}


# --- a native game's stills make "a picture of it came recently" true for it too (#2858 follow-up) ---------------
def test_a_still_is_a_small_jpeg_and_a_black_window_gives_none():
    still = still_jpeg(Image.new("RGB", (1920, 1080), (40, 90, 160)))
    with Image.open(io.BytesIO(still)) as image:
        assert image.format == "JPEG" and image.size == (960, 540)
    with Image.open(io.BytesIO(still_jpeg(Image.new("RGB", (640, 480), (40, 90, 160))))) as small:
        assert small.size == (640, 480), "never enlarged"
    assert still_jpeg(Image.new("RGB", (1280, 720), (3, 3, 3))) is None, "a sleeping display is no picture"


class _Posts:
    """httpx.Client stand-in for the stills loop: records each post."""
    def __init__(self, sink):
        self.sink = sink

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, content=None, headers=None):
        self.sink.append((url, content, headers))


def test_native_stills_post_while_the_game_lives_and_never_fail_it(monkeypatch):
    class Proc:
        pid = 100

    class Native:
        proc = Proc()
    posts, grabs, ad = [], [], Native()
    sessions = {"w-s1": (ad, {})}
    monkeypatch.setattr(tools, "SESSIONS", sessions)
    monkeypatch.setattr(tools.httpx, "Client", _Posts(posts))
    script = [b"\xff\xd8one\xff\xd9", None, RuntimeError("grab failed"), b"\xff\xd8two\xff\xd9"]

    def grab(pid):
        grabs.append(pid)
        step = script.pop(0)
        if len(grabs) == 3:
            Proc.pid = 200                     # the emulator relaunched in place (RPCS3 load state): a new pid
        if not script:
            sessions.clear()                   # the game ended: the loop stops
        if isinstance(step, Exception):
            raise step
        return step
    tools._native_stills("w-s1", ad, "http://spark", {}, every=0, grab=grab)
    assert grabs == [100, 100, 100, 200]
    assert [(url, content) for url, content, _ in posts] == [("/api/sessions/w-s1/frame", b"\xff\xd8one\xff\xd9"),
                                                            ("/api/sessions/w-s1/frame", b"\xff\xd8two\xff\xd9")]
    assert posts[0][2] == {"content-type": "image/jpeg"}


def test_a_worker_off_windows_posts_no_stills(monkeypatch):
    monkeypatch.setattr(tools, "HOST_OS", "linux")
    monkeypatch.setattr(tools.httpx, "Client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")))
    assert tools._native_stills("w-s1", object(), "http://spark", {}) is None
