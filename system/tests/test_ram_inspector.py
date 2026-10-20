"""The RAM inspector (gbox/ram_inspector.py, gbox/ram_reader.py): live named fields, events with the stream's frame,
hex with pointer chains, search with operator labels and labelers, add to map, the session-channel reader (read_ranges
and the read_memory fallback for older workers) and the read budget. Read-only throughout: the fakes fail any write."""
import io
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from gbox import ram_inspector, ram_map, ram_reader, tools
from gbox.server import create_app
from test_ram_map import Batched, FakeRam, re4_ram

GID, SID, MEM1 = "78ab9efa2e310db4", "w1-re4", 0x80000000


class DolphinProcMem:                    # named like Windows Dolphin's process-memory reader: no halt, a big budget
    pass


class FakeAd:
    """A session's adapter: reads come from RE4's RAM image; anything that would change the game fails the test."""
    name = "dolphin"

    def __init__(self, fake):
        self.fake, self.dbg = fake, DolphinProcMem()

    def read_memory(self, addr, n):
        return self.fake.read(addr, n)

    def write_memory(self, *a):
        pytest.fail("the inspector never writes game memory")

    def send_input(self, *a):
        pytest.fail("the inspector never sends input")


def jpeg(color=(10, 20, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def app(cfg, monkeypatch):
    a = create_app(cfg)
    store = a.state.store
    client = TestClient(a, headers={"Authorization": f"Bearer {cfg.token()}"})
    store.upsert_catalog([{"game_id": GID, "title": "Resident Evil 4", "platform": "gamecube", "source_paths": ["re4.iso"],
                           "format": "iso", "profile_id": GID}])
    for sid in (SID, "w1-old"):
        store.put("session", sid, {"session_id": sid, "game_id": GID, "title": "Resident Evil 4", "adapter": "dolphin",
                                   "state": "running", "started": time.time(), "detail": {"worker_name": "spark"}})
    fake = re4_ram()
    monkeypatch.setitem(tools.SESSIONS, SID, (FakeAd(fake), {"platform": "gamecube", "game_id": GID}))
    client.store, client.fake, client.cfg = store, fake, cfg
    yield client
    ram_inspector.close_all()


def live(client, since=0):
    r = client.get(f"/api/sessions/{SID}/ram/live", params={"since": since})
    assert r.status_code == 200, r.text
    return r.json()


def test_live_rows_come_from_the_games_map_read_in_process(app):
    out = live(app)
    rows = {r["name"]: r for r in out["rows"]}
    assert out["map"] == "G4BE08" and out["reader"]["kind"] == "procmem" and not out["error"]
    assert rows["merc.timer"]["display"] == "87.3 s" and rows["merc.combo"]["value"] == 12
    assert rows["game.room"]["label"] == "Mercenaries: Pueblo (village)" and rows["pad.held"]["label"] == "R, A"
    assert rows["player.pos"]["value"] == [1000.0, 0.0, 2000.0] and rows["player.pos"]["address"] == "0x810D3094"
    assert [r["index"] for r in rows["enemies"]["rows"]] == [1, 2] and rows["enemies"]["display"] == "2 live of 4"
    reads = len(app.fake.reads)
    live(app)                                              # within 0.1 s: the same evaluation, no new reads
    assert len(app.fake.reads) == reads
    st = app.get(f"/api/sessions/{SID}/ram").json()
    assert st["map"]["id"] == "G4BE08" and st["watching"] is True and st["reader"]["kind"] == "procmem"


def test_state_changes_are_events_with_the_streams_frame(app):
    first = live(app)
    frame = jpeg()
    app.post(f"/api/sessions/{SID}/frame", content=frame).raise_for_status()
    app.fake.put(0x80287EA2, ">H", 0x0100)                 # R let go, A still held
    app.fake.put(0x8027F7D0 + 0x4FA8, ">H", 0x0401)        # another room
    insp = ram_inspector._INSPECTORS[SID]
    insp.last_at = -1e9                                     # read now (the watcher may already have)
    insp.values()
    out = live(app, since=first["seq"])
    ev = {e["field"]: e for e in out["events"]}
    assert set(ev) == {"pad.held", "game.room"}
    assert (ev["pad.held"]["old_label"], ev["pad.held"]["new_label"]) == ("R, A", "A")
    assert (ev["game.room"]["old"], ev["game.room"]["new"]) == (0x400, 0x401) and ev["game.room"]["new_label"] is None
    fid = ev["pad.held"]["frame"]
    assert fid and ev["game.room"]["frame"] == fid
    got = app.get(f"/api/sessions/{SID}/ram/frames/{fid}.jpg")
    assert got.status_code == 200 and got.content == frame and got.headers["content-type"] == "image/jpeg"
    assert live(app, since=out["seq"])["events"] == []
    assert app.get(f"/api/sessions/{SID}/ram/events", params={"since": 0}).json()["seq"] == out["seq"]


def test_hex_reads_a_range_and_follows_a_pointer_chain(app):
    r = app.get(f"/api/sessions/{SID}/ram/hex", params={"address": "0x802B3044", "length": 4}).json()
    assert r["hex"] == "810d3000" and r["address_hex"] == "0x802B3044" and r["chain"] == []
    r = app.get(f"/api/sessions/{SID}/ram/hex", params={"pointer": "0x802B3044,0x94", "length": 12}).json()
    assert r["address"] == 0x810D3094 and bytes.fromhex(r["hex"])[:4] == bytes.fromhex("447a0000")       # 1000.0
    assert r["chain"] == [{"at": "0x802B3044", "value": "0x810D3000", "offset": "0x94"}]
    bad = app.get(f"/api/sessions/{SID}/ram/hex", params={"pointer": "0x80001000,0x10"})
    assert bad.status_code == 422 and "null pointer" in bad.text
    assert app.get(f"/api/sessions/{SID}/ram/hex", params={"address": "0x90000000"}).status_code == 502


def test_search_with_operator_labels_finds_the_prompt_byte_and_adds_it_to_the_map(app):
    st = app.post(f"/api/sessions/{SID}/ram/search", json={"type": "u8"}).json()
    assert (st["base"], st["size"], st["samples"]["plain"]) == (MEM1, 0x1800000, 1)
    prompt = 0x80456789
    for kind in (3, 0, 5, 0, 3, 0):                         # the prompt shows (TAKE / JUMP OVER), goes away...
        app.fake.ram[prompt - MEM1] = kind
        app.fake.put(0x80279308, ">I", 1000 + kind * 7 + len(app.fake.reads))     # the clock runs regardless
        r = app.post(f"/api/sessions/{SID}/ram/search/sample", json={"label": "on" if kind else "off"})
        assert r.status_code == 200, r.text
    st = app.get(f"/api/sessions/{SID}/ram/search", params={"limit": 5}).json()
    top = st["candidates_list"][0]
    assert top["address"] == prompt and top["address_hex"] == "0x80456789"
    assert top["on"] == [{"value": 3, "n": 2}, {"value": 5, "n": 1}] and top["off"] == [{"value": 0, "n": 3}]
    assert st["samples"] == {"on": 3, "off": 3, "plain": 1} and st["candidates"] < 10
    r = app.post(f"/api/sessions/{SID}/ram/promote", json={"name": "prompt.action", "address": prompt, "type": "u8",
                                                           "description": "the action the prompt offers",
                                                           "enum": {"0": "none", "3": "TAKE", "5": "JUMP OVER"}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["map"] == "G4BE08" and out["field"]["enum"] == {"0": "none", "3": "TAKE", "5": "JUMP OVER"}
    over = ram_map.load("G4BE08")
    spec = over.fields["prompt.action"].spec
    assert spec["source"] == "scan" and "3 on / 3 off / 1 plain samples" in spec["evidence"] and spec["by"]
    assert (app.cfg.data_dir / "ram_maps" / "G4BE08-ram.json").is_file()
    app.fake.ram[prompt - MEM1] = 5
    ram_inspector._INSPECTORS[SID].last_at = -1e9
    rows = {r["name"]: r for r in live(app)["rows"]}
    assert rows["prompt.action"]["label"] == "JUMP OVER"
    assert any(a["action"] == "ram_map.promote" for a in app.store.audit_for("G4BE08"))
    assert app.delete(f"/api/ram/maps/G4BE08/fields/prompt.action").json() == {"ok": True}
    assert app.delete(f"/api/ram/maps/G4BE08/fields/merc.combo").status_code == 404     # repo fields: in a PR
    assert app.delete(f"/api/sessions/{SID}/ram/search").json() == {"active": False}


def test_cheat_engine_filters_through_the_api(app):
    app.post(f"/api/sessions/{SID}/ram/search", json={"type": "u32", "base": "0x80279000", "size": 4096}).raise_for_status()
    app.fake.put(0x80279308, ">I", 100)
    app.post(f"/api/sessions/{SID}/ram/search/sample", json={"op": "changed"}).raise_for_status()
    app.fake.put(0x80279308, ">I", 90)
    st = app.post(f"/api/sessions/{SID}/ram/search/sample", json={"op": "decreased"}).json()
    assert [c["address"] for c in st["candidates_list"]] == [0x80279308] and st["candidates_list"][0]["value"] == 90
    bad = app.post(f"/api/sessions/{SID}/ram/search/sample", json={"op": "sideways"})
    assert bad.status_code == 422


def test_a_ram_map_field_labels_the_search(app):
    app.post(f"/api/sessions/{SID}/ram/search", json={"type": "u8", "base": "0x80400000", "size": 0x10000}).raise_for_status()
    insp = ram_inspector._INSPECTORS[SID]
    label = ram_inspector.field_labeler(insp, "pad.held", {"mask": "0x100", "ne": 0})     # "A held" is the event
    auto = ram_inspector.AutoLabel(insp, "field", label, stable=1, settle_s=0, after_s=0)
    flag = 0x80401234
    took = []
    for held in (True, True, False, True, False, False):
        app.fake.put(0x80287EA2, ">H", 0x100 if held else 0)
        app.fake.ram[flag - MEM1] = 1 if held else 0
        insp.last_at = -1e9                                   # a fresh read for each check
        took.append(auto.step())
    assert took == [None, "on", None, None, None, "off"]       # each label sampled once it held, at its change
    assert auto.samples == {"on": 1, "off": 1}
    assert insp.search.candidates(3)[0]["address"] == flag
    r = app.post(f"/api/sessions/{SID}/ram/search/auto", json={"source": "field", "field": "pad.held",
                                                                "cond": {"mask": "0x100", "ne": 0}, "hz": 2})
    assert r.status_code == 200 and r.json()["source"] == "field" and r.json()["running"] is True
    assert app.get(f"/api/sessions/{SID}/ram/search").json()["auto"]["source"] == "field"
    assert app.post(f"/api/sessions/{SID}/ram/search/auto", json={"source": "off"}).json() == {"source": "off"}
    bad = app.post(f"/api/sessions/{SID}/ram/search/auto", json={"source": "field", "field": "enemies"})
    assert bad.status_code == 422


def prompt_jpeg(shown: bool) -> bytes:
    """A 640x480 RE4 frame, with the A prompt's teal-green disc where the game draws it when shown."""
    import numpy as np
    img = np.zeros((480, 640, 3), np.uint8)
    img[:, :] = (90, 80, 60)
    if shown:
        yy, xx = np.ogrid[:480, :640]
        img[(yy - 386) ** 2 + (xx - 259) ** 2 <= 100] = (40, 134, 104)
    out = io.BytesIO()
    Image.fromarray(img).save(out, "JPEG", quality=95)
    return out.getvalue()


def test_the_screen_prompt_labels_the_search_from_the_streams_frames(app):
    app.post(f"/api/sessions/{SID}/ram/search", json={"type": "u8", "base": "0x80400000", "size": 0x1000}).raise_for_status()
    insp = ram_inspector._INSPECTORS[SID]
    label = ram_inspector.prompt_labeler(insp)
    assert label() == (None, "no fresh frame")
    auto = ram_inspector.AutoLabel(insp, "screen_prompt", label, stable=1, settle_s=0, after_s=0)
    shown_jpeg, hidden_jpeg = prompt_jpeg(True), prompt_jpeg(False)
    for shown in (True, False, True, False):
        app.post(f"/api/sessions/{SID}/frame", content=shown_jpeg if shown else hidden_jpeg).raise_for_status()
        app.fake.ram[0x400100] = 4 if shown else 0         # the game's own prompt state, which the search is after
        auto.step()
        auto.step()
    assert auto.samples == {"on": 2, "off": 2} and auto.note in ("no prompt", "same frame")
    assert insp.search.candidates(1)[0]["address"] == 0x80400100
    r = app.post(f"/api/sessions/{SID}/ram/search/auto", json={"source": "screen_prompt", "button": "a"})
    assert r.status_code == 200 and r.json()["source"] == "screen_prompt" and r.json()["button"] == "a"


def test_a_labeled_read_counts_only_when_the_label_still_holds_after_it(app):
    app.post(f"/api/sessions/{SID}/ram/search", json={"type": "u8", "base": "0x80400000", "size": 0x1000}).raise_for_status()
    insp = ram_inspector._INSPECTORS[SID]
    now = [1000.0]
    insp.clock = lambda: now[0]
    labels = iter([])
    auto = ram_inspector.AutoLabel(insp, "test", lambda: (next(labels), "scripted"), stable=2, settle_s=0.25, after_s=0.3)
    took = []
    for t, lab, ram in [(0.0, "on", 3), (0.13, "on", 3), (0.26, "on", 3), (0.40, "on", 3), (0.60, "on", 3),   # read, then confirmed
                        (0.70, "off", 0), (0.83, "off", 3), (0.96, "off", 3), (1.10, "on", 3),   # read at 0.96, the label flips: not counted
                        (1.20, "on", 3), (1.40, "on", 3), (1.50, "on", 3), (1.80, "on", 3)]:
        now[0], labels = 1000.0 + t, iter([lab])
        app.fake.ram[0x400200] = ram
        took.append(auto.step())
    assert took == [None, None, None, None, "on", None, None, None, None, None, None, None, "on"]
    assert auto.samples == {"on": 2, "off": 0} and auto.discarded == 1 and auto.status()["discarded"] == 1


def test_a_session_on_another_pc_is_read_through_its_channel(app, monkeypatch):
    # the session is not in this process: the inspector asks its worker (read_ranges over the session channel)
    remote = FakeAd(app.fake)
    monkeypatch.delitem(tools.SESSIONS, SID)
    answered = []

    def worker(stop, refuse_ranges=False):
        while not stop.is_set():
            for ev in app.get(f"/api/sessions/{SID}/input", params={"wait": 0.2}).json():
                if "rpc" not in ev:
                    continue
                answered.append(ev["op"])
                try:
                    if ev["op"] == "read_ranges" and refuse_ranges:
                        raise ValueError("rpc op read_ranges not allowed (read_memory, ...)")
                    data = (ram_reader.serve(SID, remote, ev["args"]) if ev["op"] == "read_ranges"
                            else remote.read_memory(ev["args"]["address"], ev["args"]["length"]).hex())
                    res = {"ok": True, "data": data}
                except Exception as e:                       # noqa: BLE001
                    res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                app.post(f"/api/sessions/{SID}/rpc/{ev['rpc']}", json=res)
    stop = threading.Event()
    t = threading.Thread(target=worker, args=(stop,), daemon=True)
    t.start()
    try:
        out = live(app)
        rows = {r["name"]: r for r in out["rows"]}
        assert out["reader"]["kind"] == "rpc" and rows["merc.combo"]["value"] == 12 and not out["error"]
        batched = re4_ram(Batched)
        ram_map.load("G4BE08").read(batched)                  # the map's batches: one per pointer level
        assert set(answered) == {"read_ranges"} and len(answered) % len(batched.batches) == 0   # a round trip each
        assert "procmem" in out["reader"]["how"]
    finally:
        stop.set()
        t.join(2)
    ram_inspector.close_all()                                # its watcher's last reads are done
    app.get(f"/api/sessions/{SID}/input")                    # (and nothing of it is left in the channel)
    answered.clear()
    stop = threading.Event()
    t = threading.Thread(target=worker, args=(stop,), kwargs={"refuse_ranges": True}, daemon=True)   # an older worker
    t.start()
    try:
        out = live(app)
        assert {r["name"]: r for r in out["rows"]}["merc.combo"]["value"] == 12
        assert answered[0] == "read_ranges" and set(answered[1:]) == {"read_memory"}        # asked once, then never
        assert "older worker" in out["reader"]["how"]
    finally:
        stop.set()
        t.join(2)


def test_a_worker_that_does_not_answer_is_left_alone_for_a_moment():
    now, calls = [0.0], []

    def rpc(sid, op, args, wait):
        calls.append(op)
        raise TimeoutError("session did not answer")
    r = ram_reader.RpcReader("w9-x", rpc, clock=lambda: now[0])
    assert isinstance(r.read_many([(MEM1, 4)])[0], TimeoutError) and calls == ["read_ranges"]
    assert "did not answer" in str(r.read_many([(MEM1, 4)])[0]) and calls == ["read_ranges"]   # no new request
    now[0] += ram_reader.RpcReader.QUIET_S + 0.1
    r.read_many([(MEM1, 4)])
    assert calls == ["read_ranges", "read_ranges"] and r.ranges_op                               # asked again
    bad = ram_reader.RpcReader("w9-x", lambda *a: (_ for _ in ()).throw(RuntimeError("ValueError: read_ranges takes 1..512 ranges")))
    bad.read_many([(MEM1, 4)])
    assert bad.ranges_op                                     # an error about the request is not an old worker


def test_read_ranges_is_an_allowed_read_only_op_with_limits(app):
    assert ram_reader.serve(SID, FakeAd(app.fake), {"ranges": [[0x80279308, 4], [0x90000000, 4]]})["errors"][1]
    with pytest.raises(ValueError, match="1..512 ranges"):
        ram_reader.serve(SID, FakeAd(app.fake), {"ranges": []})
    with pytest.raises(ValueError, match="at most"):
        ram_reader.serve(SID, FakeAd(app.fake), {"ranges": [[MEM1, 3 << 20]]})
    r = app.post(f"/api/sessions/{SID}/rpc", json={"op": "read_ranges", "args": {"ranges": [[MEM1, 6]]}})
    assert r.status_code != 422                                # allowed (no worker answers this test: 504)


def test_the_read_budget_throttles_and_live_serves_the_last_values(app):
    out = live(app)
    insp = ram_inspector._INSPECTORS[SID]
    insp.reader.budget = ram_reader.Budget(rate=1, calls=0.01, burst_s=1.0)    # nothing left for a long while
    insp.reader.budget.calls_left = insp.reader.budget.bytes_left = 0
    insp.last_at = -1e9
    again = live(app)
    assert again["rows"] == out["rows"] and insp.throttled >= 1
    assert app.get(f"/api/sessions/{SID}/ram/hex", params={"address": "0x80000000", "length": 64}).status_code == 429


def test_budget_waits_for_its_bytes_then_refuses():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s
    b = ram_reader.Budget(rate=1000, calls=10, burst_s=1.0, clock=lambda: now[0], sleep=sleep)
    b.take(1000)
    b.take(500, wait=1.0)                                      # waits ~0.5 s for the bytes
    assert 0.4 < sum(slept) < 0.7
    with pytest.raises(ram_reader.Throttled):
        b.take(1000, wait=0.1)


def test_a_gdb_stub_is_read_in_one_halt_per_batch():
    halts = []

    class GdbDebugger:
        def paused(self):
            class P:
                def __enter__(s):
                    halts.append("halt")

                def __exit__(s, *a):
                    halts.append("resume")
            return P()
    fake = FakeRam(0x1000)

    class Ad:
        name, dbg = "mame", GdbDebugger()

        def read_memory(self, a, n):
            return fake.read(a, n)
    r = ram_reader.AdapterReader(Ad())
    assert r.kind == "gdb" and r.piece == 64 << 10
    got = r.read_many([(MEM1, 4), (MEM1 + 16, 4), (MEM1 + 0x2000, 4)])
    assert halts == ["halt", "resume"] and isinstance(got[2], ValueError) and got[0] == bytes(4)


def test_a_reader_that_reads_nothing_any_more_is_made_again(app):
    live(app)
    insp = ram_inspector._INSPECTORS[SID]
    old = insp.reader

    class Gone(ram_reader.Reader):                         # the emulator process went away under the reader
        def _many(self, ranges):
            return [OSError("No such process")] * len(ranges)
    insp.reader = Gone("shm")
    insp.last_at = insp.remade_at = -1e9
    insp.values()
    assert insp.reader is not old and insp.reader.kind == "procmem" and "reading the session again" in insp.error
    insp.last_at = -1e9
    assert insp.values()["merc.combo"] == 12 and insp.error is None


def test_ended_sessions_are_refused_and_their_inspectors_closed(app):
    live(app)
    insp = ram_inspector._INSPECTORS[SID]
    app.store.put("session", SID, app.store.get("session", SID) | {"state": "ended"})
    r = app.get(f"/api/sessions/{SID}/ram/live")
    assert r.status_code == 409 and insp.closed and SID not in ram_inspector._INSPECTORS
    assert app.get("/api/sessions/nope/ram").status_code == 404


def test_maps_api(app):
    maps = app.get("/api/ram/maps").json()
    assert any(m["id"] == "G4BE08" and GID in m["game_ids"] for m in maps)
    m = app.get("/api/ram/maps/G4BE08").json()
    assert m["platform"] == "gamecube" and any(f["name"] == "enemies" and f["stride"] == "@emmgr.stride" for f in m["fields"])
    assert app.get("/api/ram/maps/NOPE").status_code == 404
    r = app.post("/api/ram/maps/G4BE08/fields", json={"name": "door.state", "field": {"address": "0x80300000", "type": "u8",
                                                                                     "enum": {"1": "open"}, "source": "scan"}})
    assert r.status_code == 200 and "door.state" in r.json()["overlay_fields"]
    bad = app.post("/api/ram/maps/G4BE08/fields", json={"name": "door.bad", "field": {"type": "u8"}})
    assert bad.status_code == 422 and "address or a pointer" in bad.text
