"""Autoplay coaching notes (gbox/coaching.py): one ticket per game, each note's moment captured on the session's PC (frame,
save state through gBox's own slot, main RAM as a gzip with a JSON header) and attached to that note; RE4 GC notes carry a
decoded Mercenaries summary; the last notes per game are readable for autoplay and the watch panel."""
import gzip
import hashlib
import io
import json
import os
import shutil
import struct
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from gbox import coaching, ram_dump, re4_merc_bot as R, screensaver, state_snapshot, tools
from gbox.registry import REGISTRY, Unsupported
from gbox.server import create_app

GID, OTHER = "re4gc0000000001", "doa20000000002"
MEM1 = 0x80000000


def re4_ram(room=0x400, timer_s=87.3, combo=12, leon=(1000.0, 0.0, 2000.0), rot=0.0,
            ganados=((1000.0, 0.0, 4000.0), (5000.0, 0.0, 2000.0))) -> bytes:
    """A GameCube MEM1 image with RE4's Mercenaries structures where gbox.re4_merc_bot reads them."""
    ram = bytearray(0x1800000)

    def put(addr, fmt, *v):
        struct.pack_into(fmt, ram, addr - MEM1, *v)
    ram[:6] = b"G4BE08"
    pg, pl, em, stride = 0x80400000, 0x80500000, 0x80600000, 0x400
    put(R.P_GLOBAL, ">I", pg)
    put(pg + R.G_ROOM, ">H", room)
    put(R.P_PLAYER, ">I", pl)
    put(pl + 0x94, ">3f", *leon)
    put(pl + 0xA4, ">f", rot)
    put(R.EMMGR, ">III", em, len(ganados) + 1, stride)
    for k, pos in enumerate(ganados, start=1):
        put(em + k * stride, ">I", 1)
        put(em + k * stride + 0x94, ">3f", *pos)
    put(R.MERC_TIMER, ">I", round(timer_s * 30))
    put(R.MERC + 0x28, ">I", combo)
    return bytes(ram)


def png(color=(90, 120, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(out, "PNG")
    return out.getvalue()


class FakeRam:
    """An adapter whose memory reads come from an image (RetroArch-like: no shared-memory view)."""
    name = "fake"

    def __init__(self, ram: bytes, base: int = MEM1):
        self.ram, self.base, self.reads = ram, base, []

    def read_memory(self, addr, n):
        self.reads.append((addr, n))
        off = addr - self.base
        if off < 0 or off >= len(self.ram):
            raise ValueError(f"{addr:#x} unmapped")
        return self.ram[off:off + n]


class FakeDolphin(FakeRam):
    """Standalone Dolphin as state_snapshot sees it: a demo slot (jump_save); slot 1 is the operator's."""
    name, JUMP_SLOT, gecko_id = "dolphin", 10, "G4BE08"

    def jump_save(self, dest):
        Path(dest).write_bytes(b"dolphin-slot-10-state")
        return 21

    def save_state(self, *a, **k):
        raise AssertionError("the operator's slot 1 must never be used for a coaching snapshot")

    def get_frame(self):
        return png()


# --- the worker side: RAM dump ---------------------------------------------------------------------------------------
def test_ram_dump_is_one_gzip_with_a_json_header_and_the_whole_main_ram():
    ram = re4_ram()
    ad = FakeRam(ram)
    blob, meta = ram_dump.dump(ad, {"platform": "gamecube", "game_id": GID, "title": "RE4"}, "w1-abc")
    raw = gzip.decompress(blob)
    header = json.loads(raw[:raw.index(b"\n")])
    assert header == meta and raw[meta["header_size"] - 1:meta["header_size"]] == b"\n"
    assert (header["platform"], header["base"], header["base_hex"], header["length"]) == ("gamecube", MEM1, "0x80000000", 0x1800000)
    assert header["sha256"] == hashlib.sha256(ram).hexdigest() and header["big_endian"] is True
    region = header["regions"][0]
    assert (region["name"], region["offset"], region["complete"]) == ("MEM1", 4096, True)
    assert raw[region["offset"]:region["offset"] + region["length"]] == ram
    assert header["disc_id"] == "G4BE08" and header["partial"] is False and header["missing"] == []
    assert max(n for _, n in ad.reads) <= ram_dump.CHUNK                  # pieces, never one 24 MiB request
    assert ram_dump.read_header(blob) == meta
    loaded_meta, regions = ram_dump.load(blob)
    assert loaded_meta == meta and regions[0][1] == ram


def test_ram_dump_tool_result_passes_control_plane_validation(monkeypatch):
    ram = re4_ram()
    monkeypatch.setitem(tools.SESSIONS, "w1-abc", (FakeRam(ram), {"platform": "gamecube", "game_id": GID}))
    arts = []
    ctx = SimpleNamespace(artifact=lambda name, data, mt, **prov: arts.append((name, data, mt, prov)))
    out = ram_dump.ram_dump(ram_dump.RamDumpIn(session_id="w1-abc"), ctx)
    (name, blob, mt, prov), = arts
    assert (name, mt, prov["session"], prov["base"], prov["partial"]) == ("ram.gz", "application/gzip", "w1-abc", "0x80000000", False)
    res = out["result"]
    assert res["artifact"] == hashlib.sha256(blob).hexdigest() and res["length"] == len(ram) and res["disc_id"] == "G4BE08"
    t = REGISTRY["ram_dump"]
    parsed = t.Out.model_validate(out)
    assert t.validate(parsed, {"ram.gz": blob}) == []
    bad = t.Out.model_validate({"result": res | {"sha256": "0" * 64}})
    assert t.validate(bad, {"ram.gz": blob}) and t.validate(parsed, {}) == ["ram.gz missing"]


def test_ram_dump_budget_gives_a_partial_dump_that_says_what_is_missing():
    ticks = iter(range(1000))
    blob, meta = ram_dump.dump(FakeRam(re4_ram()), {"platform": "gamecube"}, budget_s=2.5, clock=lambda: next(ticks))
    assert meta["partial"] is True and meta["length"] == 2 << 20
    assert meta["missing"] == [[MEM1 + (2 << 20), 0x1800000 - (2 << 20)]]
    assert "budget" in meta["regions"][0]["error"] and meta["regions"][0]["complete"] is False


def test_ram_dump_through_a_gdb_stub_reads_small_pieces_and_lets_the_game_run():
    class GdbDebugger:                                   # the stub halts the CPU while it answers
        pass
    ad = FakeRam(re4_ram())
    ad.dbg = GdbDebugger()
    sleeps = []
    blob, meta = ram_dump.dump(ad, {"platform": "gamecube"}, sleep=sleeps.append)
    assert max(n for _, n in ad.reads) == ram_dump.GDB_CHUNK < ram_dump.CHUNK
    assert len(sleeps) == len(ad.reads) - 1 and set(sleeps) == {ram_dump.GDB_GAP_S}
    assert "GDB" in meta["source"] and meta["partial"] is False


def test_dolphin_on_linux_is_read_through_its_own_shared_memory_view_without_the_debugger(monkeypatch):
    mem1, host = re4_ram(), 0x7F0000000000
    monkeypatch.setattr(ram_dump, "HOST_OS", "linux")
    monkeypatch.setattr(ram_dump, "_descendants", lambda pid: [4243, 4244] if pid == 4242 else [])   # flatpak -> bwrap -> dolphin
    views = {4243: [], 4244: [(0x7E0000000000, 0x2000000, 0x2040000),       # same size, not MEM1 (fake VMEM)
                              (host, 0x2000000, 0)]}                        # MEM1: 32 MiB at file offset 0
    monkeypatch.setattr(ram_dump, "_views", lambda pid: views.get(pid, []))
    opened = []
    monkeypatch.setattr(ram_dump.os, "open", lambda path, flags: opened.append(path) or 99)
    monkeypatch.setattr(ram_dump.os, "close", lambda fd: None)

    def pread(fd, n, offset):
        assert host <= offset < host + 0x2000000                           # only the MEM1 view is ever read
        return mem1[offset - host:offset - host + n]
    monkeypatch.setattr(ram_dump.os, "pread", pread, raising=False)
    ad = FakeDolphin(b"")
    ad.proc = SimpleNamespace(pid=4242)
    ad.read_memory = lambda *a: pytest.fail("the shared view is read, not the (halting) debugger")
    blob, meta = ram_dump.dump(ad, {"platform": "gamecube"})
    assert meta["source"].startswith("Dolphin shared memory (/proc/4244/mem") and opened == ["/proc/4244/mem"]
    assert meta["sha256"] == hashlib.sha256(mem1).hexdigest() and meta["disc_id"] == "G4BE08" and not meta["partial"]
    ad.proc = SimpleNamespace(pid=1)                                        # another Dolphin's tree: never read
    assert ram_dump.ShmRam.find(ad) is None


def test_ram_dump_uses_the_adapters_own_regions_and_reports_what_the_size_cap_left_out(monkeypatch):
    class Guest:                                         # Xenia-like: committed guest regions instead of MAIN_RAM
        name = "xenia"

        def regions(self):
            return [(0x40000000, 2 << 20), (0x82000000, 2 << 20)]

        def read_memory(self, addr, n):
            return bytes([addr >> 24]) * n
    monkeypatch.setattr(ram_dump, "MAX_BYTES", 3 << 20)
    blob, meta = ram_dump.dump(Guest(), {"platform": "xbox360"})
    assert [(r["name"], r["base"], r["length"]) for r in meta["regions"]] == [("region 0", 0x40000000, 2 << 20),
                                                                           ("region 1", 0x82000000, 1 << 20)]
    assert meta["partial"] and meta["missing"] == [[0x82000000 + (1 << 20), 1 << 20]]
    assert meta["big_endian"] and any("first 3 MiB" in n for n in meta["notes"])
    _, regions = ram_dump.load(blob)
    assert regions[1][1] == b"\x82" * (1 << 20)


def test_ram_dump_refuses_a_platform_without_a_main_ram_layout():
    with pytest.raises(Unsupported):
        ram_dump.dump(FakeRam(b""), {"platform": "3do"})


# --- the worker side: a save state through gBox's own slot ---------------------------------------------------------------
def test_dolphin_snapshot_goes_through_the_demo_slot_never_slot_1():
    data, details = state_snapshot.take(FakeDolphin(b""), {"game_id": GID})
    assert data == b"dolphin-slot-10-state"
    assert (details["file"], details["slot"], details["operator_slot"]) == ("G4BE08.s10", 10, 1)


def test_state_transfer_snapshot_uploads_the_snapshot(monkeypatch, tmp_path):
    monkeypatch.setitem(tools.SESSIONS, "w1-abc", (FakeDolphin(b""), {"game_id": GID}))
    arts = []
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), artifact=lambda *a, **k: arts.append((a, k)))
    res = tools.state_transfer(tools.StateXIn(session_id="w1-abc", op="snapshot"), ctx)["result"]
    assert res["artifact"] == hashlib.sha256(b"dolphin-slot-10-state").hexdigest() and res["file"] == "G4BE08.s10"
    (args, prov), = arts
    assert args[0] == "G4BE08.s10" and args[1] == b"dolphin-slot-10-state"
    assert prov["snapshot"] is True and prov["session"] == "w1-abc" and prov["slot"] == 10


class FakeRetroArch:
    name = "retroarch"

    def __init__(self, states: Path, slot=0, land=None):
        self.states, self.slot, self.land, self.steps = states, slot, land, []

    def _slot(self, slot):
        self.steps.append(slot)
        self.slot = slot
        return slot

    def save_state(self, slot=None):
        self._slot(slot)
        actual = slot if self.land is None else self.land       # land: a dropped slot command saves elsewhere
        f = self.states / f"Game.state{actual if actual else ''}"
        f.write_bytes(b"coach-snapshot")
        self.slot = actual
        return {"verified": True, "path": str(f), "slot": actual, "bytes": f.stat().st_size}


def _operator_files(states: Path) -> dict:
    mine = states / "Game.state"
    mine.write_bytes(b"operator slot 0")
    os.utime(mine, (1_700_000_000, 1_700_000_000))
    return {f.name: (f.read_bytes(), f.stat().st_mtime) for f in states.iterdir()}


def test_retroarch_snapshot_uses_slot_9_and_gives_the_operator_everything_back(tmp_path):
    states = tmp_path / "states"
    states.mkdir()
    before = _operator_files(states)
    ad = FakeRetroArch(states, slot=0)
    data, details = state_snapshot.take(ad, {"_rom_path": "/roms/Game.chd"}, states)
    assert data == b"coach-snapshot" and details["slot"] == 9 and details["operator_slot"] == 0
    assert ad.slot == 0 and ad.steps[-1] == 0                       # switched back to the operator's slot
    assert {f.name: (f.read_bytes(), f.stat().st_mtime) for f in states.iterdir()} == before   # no slot 9 file left


def test_retroarch_snapshot_landing_in_the_operators_slot_puts_their_save_back(tmp_path):
    states = tmp_path / "states"
    states.mkdir()
    before = _operator_files(states)
    data, details = state_snapshot.take(FakeRetroArch(states, slot=0, land=0), {"_rom_path": "Game.chd"}, states)
    assert data == b"coach-snapshot" and "slot 0" in details["warning"]
    assert {f.name: (f.read_bytes(), f.stat().st_mtime) for f in states.iterdir()} == before


def test_retroarch_snapshot_keeps_an_existing_slot_9_file(tmp_path):
    states = tmp_path / "states"
    states.mkdir()
    (states / "Game.state9").write_bytes(b"someone's slot 9")
    state_snapshot.take(FakeRetroArch(states, slot=3), {"_rom_path": "Game.chd"}, states)
    assert (states / "Game.state9").read_bytes() == b"someone's slot 9"


def test_snapshot_refuses_without_a_slot_of_gbox_own_or_the_games_file_names(tmp_path):
    with pytest.raises(Unsupported):
        state_snapshot.take(SimpleNamespace(name="duckstation"), {})
    ad = FakeRetroArch(tmp_path, slot=0)
    with pytest.raises(RuntimeError, match="no snapshot"):
        state_snapshot.take(ad, {}, tmp_path)
    assert ad.steps == []                                       # nothing saved, no slot switched


# --- the control coach_app: tickets, notes, captures ------------------------------------------------------------------------
@pytest.fixture
def coach_app(cfg, monkeypatch):
    app = create_app(cfg)
    store = app.state.store
    spawned = []
    monkeypatch.setattr(coaching, "_spawn", lambda fn, *args: spawned.append((fn, args)))
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    client.post("/api/workers/register", json={"id": "w1", "name": "spark", "os": "linux",
                                                "tools": ["get_frame", "state_transfer", "ram_dump", "session_op"]}).raise_for_status()
    store.upsert_catalog([{"game_id": GID, "title": "Resident Evil 4", "platform": "gamecube", "source_paths": ["re4.iso"],
                           "format": "iso", "profile_id": GID},
                          {"game_id": OTHER, "title": "Dead or Alive 2", "platform": "dreamcast", "source_paths": ["doa2.gdi"],
                           "format": "gdi", "profile_id": OTHER}])
    for sid, gid, adapter in (("w1-abc", GID, "dolphin"), ("w1-def", GID, "dolphin"), ("w1-ghi", OTHER, "duckstation")):
        store.put("session", sid, {"session_id": sid, "game_id": gid, "title": "t", "adapter": adapter, "state": "running",
                                   "started": time.time(), "detail": {"worker_name": "spark"}})
    screensaver.TELEMETRY.clear()
    screensaver.telemetry_put("w1-abc", {"running": True, "mode": "playbook", "mission": "playbook: re4_merc_bot",
                                         "title": "Resident Evil 4", "stats": {"combo": 12, "hops": 1}})
    client.store, client.spawned = store, spawned
    return client


def note(client, sid, text):
    r = client.post(f"/api/sessions/{sid}/coach", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_notes_go_to_one_ticket_per_game_with_the_moment_and_the_sessions_worker(coach_app):
    first = note(coach_app, "w1-abc", "  stop walking into walls ")
    assert first["note"] == 1 and set(first["jobs"]) == {"frame", "state", "ram"} and all(first["jobs"].values())
    req = coach_app.get(f"/api/requests/{first['request_id']}").json()
    assert req["title"] == "Autoplay coaching: Resident Evil 4" and req["source"] == "coach" and req["number"] == first["number"]
    assert req["context"] == {"coaching": True, "game_id": GID, "title": "Resident Evil 4"}
    assert req["automated"] is False and req["status"] == "open"
    msg = req["messages"][-1]
    assert msg["id"] == first["message_id"] and msg["author"] == "operator"
    assert msg["text"].startswith("stop walking into walls\n\n[coach note #1 · ")
    assert "spark · session w1-abc" in msg["text"] and "autoplay playing (playbook): playbook: re4_merc_bot" in msg["text"]
    assert msg["coach"]["telemetry"]["stats"] == {"combo": 12, "hops": 1} and msg["coach"]["text"] == "stop walking into walls"
    expect = {"frame": ("get_frame", {"session_id": "w1-abc", "region": None}),
              "state": ("state_transfer", {"session_id": "w1-abc", "op": "snapshot", "artifact": "", "slot": None, "not_before": 0}),
              "ram": ("ram_dump", {"session_id": "w1-abc", "budget_s": coaching.RAM_BUDGET_S})}
    for kind, (tool, inp) in expect.items():
        job = coach_app.get(f"/api/jobs/{first['jobs'][kind]}").json()
        assert (job["tool"], job["input"], job["require_worker"]) == (tool, inp, "w1")
        assert job["parent_request_id"] == first["request_id"] and job["state"] == "queued"
        assert job["origin"]["via"] == "autoplay coach"
    assert [args[1:] for fn, args in coach_app.spawned] == [(first["request_id"], first["message_id"])]

    second = note(coach_app, "w1-def", "that's not an enemy")              # another session of the same game: same ticket
    assert (second["request_id"], second["note"]) == (first["request_id"], 2)
    other = note(coach_app, "w1-ghi", "go after the enemy")                # another game: its own ticket
    assert other["request_id"] != first["request_id"] and other["note"] == 1
    assert other["captures"]["state"]["state"] == "skipped" and other["jobs"]["state"] is None   # no slot of gBox's own
    assert other["jobs"]["frame"] and other["jobs"]["ram"]

    coach_app.post(f"/api/requests/{first['request_id']}/status", json={"status": "done"}).raise_for_status()
    fresh = note(coach_app, "w1-abc", "aim at the enemy")                  # a closed ticket stays closed: a new one starts
    assert fresh["request_id"] != first["request_id"] and fresh["note"] == 1


def test_notes_without_a_live_game_or_pc_are_filed_with_nothing_captured(coach_app):
    coach_app.store.put("session", "w1-old", {"session_id": "w1-old", "game_id": GID, "adapter": "dolphin", "state": "ended"})
    ended = note(coach_app, "w1-old", "you got stuck on the fence")
    assert {c["state"] for c in ended["captures"].values()} == {"skipped"} and not any(ended["jobs"].values())
    w = coach_app.store.get("worker", "w1")
    coach_app.store.put("worker", "w1", w | {"last_seen": time.time() - 120})
    offline = note(coach_app, "w1-abc", "shoot the hourglass")
    assert all("offline" in c["detail"] for c in offline["captures"].values())
    assert offline["request_id"] == ended["request_id"] and offline["note"] == 2
    assert coach_app.post("/api/sessions/w1-nope/coach", json={"text": "hi"}).status_code == 404
    assert coach_app.post("/api/sessions/w1-abc/coach", json={"text": "   "}).status_code == 422


def finish(store, job_id, out, arts):
    """What the worker's result does: the job's artifacts stored, the job succeeded with its output."""
    for name, data, mt, prov in arts:
        store.put_artifact(data, name, mt, prov | {"job": job_id})
    job = store.get("job", job_id)
    store.put("job", job_id, job | {"state": "succeeded", "output": out, "finished": time.time()})


def run_tool(monkeypatch, fn, inp, sid, ad, g):
    monkeypatch.setitem(tools.SESSIONS, sid, (ad, g))
    arts = []
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=Path(".")), server=None, headers={},
                          artifact=lambda name, data, mt="application/octet-stream", **prov: arts.append((name, data, mt, prov)))
    return fn(inp, ctx), arts


def test_finished_captures_attach_to_the_note_with_the_ram_header_and_the_re4_summary(coach_app, monkeypatch):
    sent = note(coach_app, "w1-abc", "stop walking into walls")
    ad, g = FakeDolphin(re4_ram()), {"game_id": GID, "title": "Resident Evil 4", "platform": "gamecube"}
    st = coach_app.get(f"/api/sessions/w1-abc/coach/{sent['message_id']}").json()
    assert not st["done"] and {c["state"] for c in st["captures"].values()} == {"pending"}

    out, arts = run_tool(monkeypatch, tools.get_frame, tools.FrameIn(session_id="w1-abc"), "w1-abc", ad, g)
    finish(coach_app.store, sent["jobs"]["frame"], out, arts)
    st = coach_app.get(f"/api/sessions/w1-abc/coach/{sent['message_id']}").json()
    assert st["captures"]["frame"]["state"] == "done" and st["captures"]["ram"]["state"] == "pending" and not st["done"]
    out, arts = run_tool(monkeypatch, tools.state_transfer, tools.StateXIn(session_id="w1-abc", op="snapshot"), "w1-abc", ad, g)
    finish(coach_app.store, sent["jobs"]["state"], out, arts)
    out, arts = run_tool(monkeypatch, ram_dump.ram_dump, ram_dump.RamDumpIn(session_id="w1-abc"), "w1-abc", ad, g)
    finish(coach_app.store, sent["jobs"]["ram"], out, arts)

    st = coach_app.get(f"/api/sessions/w1-abc/coach/{sent['message_id']}").json()
    assert st["done"] and {c["state"] for c in st["captures"].values()} == {"done"}
    assert "slot 10" in st["captures"]["state"]["detail"] and "24.0 MiB at 0x80000000" in st["captures"]["ram"]["detail"]
    msg = coach_app.get(f"/api/requests/{sent['request_id']}").json()["messages"][-1]
    names = [a["name"] for a in msg["attachments"]]
    assert names == ["coach-1-frame.png", "coach-1-G4BE08.s10", "coach-1-G4BE08-ram.gz", "coach-1-re4-summary.json"]
    by = {a["name"]: a for a in msg["attachments"]}
    assert coach_app.get(f"/api/artifacts/{by['coach-1-G4BE08.s10']['sha256']}").content == b"dolphin-slot-10-state"
    blob = coach_app.get(f"/api/artifacts/{by['coach-1-G4BE08-ram.gz']['sha256']}").content
    header = ram_dump.read_header(blob)
    assert (header["platform"], header["base_hex"], header["length"]) == ("gamecube", "0x80000000", 0x1800000)
    assert header["sha256"] == hashlib.sha256(re4_ram()).hexdigest()
    summary = coach_app.get(f"/api/artifacts/{by['coach-1-re4-summary.json']['sha256']}").json()
    assert (summary["room"], summary["timer_s"], summary["combo"], summary["in_mercenaries"]) == ("r400", 87.3, 12, True)
    assert summary["leon"] == {"ptr": "0x80500000", "pos": [1000.0, 0.0, 2000.0], "facing_deg": 0.0}
    assert summary["ganados_live"] == 2 and summary["ganados"][0] == {"slot": 1, "pos": [1000.0, 0.0, 4000.0],
                                                                      "distance": 2000, "bearing_deg": 0.0}
    assert summary["ganados"][1]["bearing_deg"] == 90.0 and summary["addresses"]["enemy_manager"] == "0x8027df20"
    assert st["summary"] == msg["coach"]["summary"] and msg["text"].endswith(st["summary"])
    assert "room r400 · clock 87.3 s · combo 12 · Leon at (1000, 0, 2000) facing 0°" in st["summary"]
    assert "2 Ganados live, nearest 2000 away ahead" in st["summary"]

    # attaching twice (the watcher and a status read racing) changes nothing
    again = coach_app.get(f"/api/sessions/w1-abc/coach/{sent['message_id']}").json()
    assert again == st and len(coach_app.get(f"/api/requests/{sent['request_id']}").json()["messages"][-1]["attachments"]) == 4

    # what autoplay reads, and what the watch panel shows
    doc = coach_app.get(f"/api/coaching/{GID}").json()
    entry = doc["notes"][-1]
    assert (doc["request_id"], doc["number"], entry["text"], entry["request_id"]) == (sent["request_id"], sent["number"],
                                                                                      "stop walking into walls", sent["request_id"])
    assert entry["captures"]["ram"]["sha256"] == by["coach-1-G4BE08-ram.gz"]["sha256"] and entry["summary"] == st["summary"]
    assert entry["captures"]["frame"]["state"] == "done" and entry["telemetry"]["mission"] == "playbook: re4_merc_bot"
    latest = coach_app.get("/api/sessions/w1-def/coach").json()
    assert latest["latest"]["text"] == "stop walking into walls" and latest["count"] == 1 and latest["latest"]["age_s"] >= 0
    assert latest["latest"]["captures"] == {"frame": "done", "state": "done", "ram": "done"}


def test_failed_or_late_captures_are_reported_and_a_late_result_still_attaches(coach_app, monkeypatch):
    sent = note(coach_app, "w1-abc", "aim at him")
    store = coach_app.store
    job = store.get("job", sent["jobs"]["state"])
    store.put("job", job["id"], job | {"state": "failed", "error": "fast-forward is on: no jump state now"})
    st = coaching.watch(store, sent["request_id"], sent["message_id"], limit_s=0, sleep=lambda s: None)
    assert st["done"] and st["captures"]["state"] == {"tool": "state_transfer", "job": job["id"], "state": "failed",
                                                      "detail": "fast-forward is on: no jump state now"}
    assert st["captures"]["frame"]["timed_out"] and "job queued" in st["captures"]["frame"]["detail"]
    assert coach_app.get(f"/api/coaching/{GID}").json()["notes"][-1]["captures"]["frame"]["timed_out"] is True
    out, arts = run_tool(monkeypatch, tools.get_frame, tools.FrameIn(session_id="w1-abc"), "w1-abc", FakeDolphin(b""), {"game_id": GID})
    finish(store, sent["jobs"]["frame"], out, arts)
    # the watch panel's poll (no read of this note's own status) is enough for the late frame to land on the note
    latest = coach_app.get("/api/sessions/w1-abc/coach").json()["latest"]
    assert latest["captures"] == {"frame": "done", "state": "failed", "ram": "failed"}
    msg = coach_app.get(f"/api/requests/{sent['request_id']}").json()["messages"][-1]
    assert [a["name"] for a in msg["attachments"]] == ["coach-1-frame.png"]
    st = coach_app.get(f"/api/sessions/w1-abc/coach/{sent['message_id']}").json()
    assert st["captures"]["frame"]["state"] == "done" and st["captures"]["ram"]["state"] == "failed"


def test_a_capture_the_pc_cannot_run_fails_at_once_and_the_note_still_goes_in(coach_app):
    coach_app.post("/api/workers/register", json={"id": "w1", "name": "spark", "os": "linux",
                                              "tools": ["get_frame", "state_transfer"]}).raise_for_status()
    sent = note(coach_app, "w1-abc", "go after the enemy")
    assert sent["captures"]["ram"]["state"] == "failed" and "can't run ram_dump" in sent["captures"]["ram"]["detail"]
    assert sent["captures"]["frame"]["state"] == "pending"


def test_ram_dump_header_grows_in_whole_pages_when_the_json_is_long():
    meta = {"format": ram_dump.FORMAT, "regions": [{"name": f"region {i}", "note": "x" * 100} for i in range(60)]}
    head, written = ram_dump.header_block(meta, [16] * 60)
    size = written["header_size"]
    assert size > ram_dump.HEADER and size % ram_dump.HEADER == 0 and len(head) == size and head.endswith(b"\n")
    assert json.loads(head) == written
    assert [r["offset"] for r in written["regions"][:3]] == [size, size + 16, size + 32]


def test_end_to_end_the_real_worker_captures_a_note(plane, monkeypatch):
    """The HTTP control plane + a real worker thread: the note's three jobs run on the session's worker, their results
    come back like any job's, and the watcher attaches them (with the RE4 summary) without a status read."""
    wid = next(w["id"] for w in plane.get("/api/workers").json() if w["name"] == "test-worker")
    sid, store = f"{wid}-coach", plane.app.state.store
    store.upsert_catalog([{"game_id": GID, "title": "Resident Evil 4", "platform": "gamecube", "source_paths": ["re4.iso"],
                           "format": "iso", "profile_id": GID}])
    store.put("session", sid, {"session_id": sid, "game_id": GID, "title": "Resident Evil 4", "adapter": "dolphin",
                               "state": "running", "started": time.time(), "detail": {"worker_name": "test-worker"}})
    monkeypatch.setitem(tools.SESSIONS, sid, (FakeDolphin(re4_ram()), {"game_id": GID, "title": "Resident Evil 4",
                                                                      "platform": "gamecube"}))
    sent = plane.post(f"/api/sessions/{sid}/coach", json={"text": "stop walking into walls"}).raise_for_status().json()
    end = time.time() + 90
    while True:
        note_ = next(m for m in plane.get(f"/api/requests/{sent['request_id']}").json()["messages"] if m.get("id") == sent["message_id"])
        caps = note_["coach"]["captures"]
        if all(c["state"] != "pending" for c in caps.values()) or time.time() > end:
            break
        time.sleep(0.2)
    assert caps["state"]["state"] == "done" and caps["ram"]["state"] == "done", caps
    assert caps["frame"]["state"] == "done" or not shutil.which("ffmpeg"), caps     # get_frame needs ffmpeg on the worker
    assert "RE4 Mercenaries at this note" in note_["coach"]["summary"]
    names = {a["name"] for a in note_["attachments"]}
    assert {"coach-1-G4BE08.s10", "coach-1-G4BE08-ram.gz", "coach-1-re4-summary.json"} <= names
