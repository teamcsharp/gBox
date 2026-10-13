"""A slow sound device never fails or blocks a launch (gbox/game_audio.py).

The fixtures are real RetroArch logs from JAYBUILTFINALE (2026-10-13, CRLF -> LF):
- xaudio_init_stalled.log        the DOA2 boot up to '[WARN] [Audio] Driver "xaudio" has not returned from init after
                                 2 seconds; the device is not opening.' (the audio driver has not come back yet)
- xaudio_late_loop_silent.log    the whole log of failed job 19cff4fd02724017: audio opened late, then the core's loop
                                 never answered GET_STATUS ("content not running after 30s")
- xaudio_slow_then_running.log   the retry that played (emulator_start_s 20.4): same warning, then the game ran
- no_audio_warning.log           an earlier launch whose audio init returned at once
"""
import time
from pathlib import Path
from types import SimpleNamespace

from gbox import adapters, game_audio as ga
from gbox.config import Config, EmulatorConfig, GameAudioConfig

FIX = Path(__file__).parent / "fixtures" / "retroarch_boot"
WARN = '[WARN] [Audio] Driver "xaudio" has not returned from init after 2 seconds; the device is not opening.'


def log(name: str) -> str:
    return (FIX / name).read_text()


# ------------------------------------------------------------------------------------------------ device choice

ARCTIS = {"index": 1, "id": "{0.0.0.00000000}.{3dfad92f}", "name": "Headphones (2- Arctis Nova Pro Wireless)", "state": 1}
LG = {"index": 0, "id": "{0.0.0.00000000}.{1e7cb079}", "name": "LG ULTRAWIDE (NVIDIA High Definition Audio)", "state": 1}
REALTEK = {"index": 2, "id": "{0.0.0.00000000}.{c8d19a58}", "name": "Speakers (Realtek(R) Audio)", "state": 1}


def test_active_default_device_is_used():
    pick = ga.pick_output({"default_id": ARCTIS["id"], "endpoints": [LG, ARCTIS, REALTEK]})
    assert pick["id"] == ARCTIS["id"] and pick["default"] is True and "default" in pick["why"]


def test_inactive_default_falls_to_the_first_active_device():
    # the default endpoint is a headset that is unplugged / asleep: it is not in the ACTIVE list
    pick = ga.pick_output({"default_id": "{0.0.0.00000000}.{tp7-unplugged}", "endpoints": [LG, ARCTIS]})
    assert pick["id"] == LG["id"] and pick["default"] is False and "not active" in pick["why"]
    stale = dict(ARCTIS, state=4)                         # listed but DEVICE_STATE_NOTPRESENT
    assert ga.pick_output({"default_id": ARCTIS["id"], "endpoints": [stale, REALTEK]})["id"] == REALTEK["id"]
    assert ga.pick_output({"default_id": None, "endpoints": [REALTEK]})["why"].startswith("no default")


def test_configured_device_wins_when_active():
    listing = {"default_id": ARCTIS["id"], "endpoints": [LG, ARCTIS, REALTEK]}
    assert ga.pick_output(listing, "speakers (realtek(r) audio)")["id"] == REALTEK["id"]
    assert ga.pick_output(listing, "Realtek")["id"] == REALTEK["id"]                       # part of the name
    assert ga.pick_output(listing, "OP-1")["id"] == ARCTIS["id"]                           # not active: the default


def test_no_device_and_no_list_are_different():
    assert ga.pick_output({"default_id": None, "endpoints": []}).get("none") is True
    unknown = ga.pick_output({"default_id": None, "endpoints": [], "error": "Core Audio did not answer in 2 s"})
    assert unknown.get("unknown") is True and not unknown.get("none")
    assert ga.dolphin_backend({"chosen": {"none": True}}) == "No Audio Output"
    assert ga.dolphin_backend({"chosen": unknown}) == "Cubeb"              # no list: Dolphin keeps its own default
    assert ga.xenia_apu({"chosen": {"none": True}}) == "nop" and ga.xenia_apu({"chosen": ARCTIS}) is None
    assert "Renderer: Null" in ga.rpcs3_audio_yaml({"chosen": {"none": True}})
    assert "Renderer: Cubeb" in ga.rpcs3_audio_yaml({"chosen": ARCTIS})


def test_retroarch_device_is_the_unique_name_else_the_index():
    listing = {"endpoints": [LG, ARCTIS, REALTEK]}
    assert ga.retroarch_device(listing, ARCTIS) == "Headphones (2- Arctis Nova Pro Wireless)"
    twin = dict(REALTEK, name=ARCTIS["name"])
    assert ga.retroarch_device({"endpoints": [LG, ARCTIS, twin]}, twin) == "2"
    assert ga.retroarch_device(listing, {"unknown": True}) == ""


# ------------------------------------------------------------------------------------------------ fallback decision

def test_driver_chain_and_next_driver():
    assert ga.driver_chain(["xaudio", "wasapi", "null"]) == ["xaudio", "wasapi", "null"]
    assert ga.driver_chain(["xaudio", "wasapi", "null"], first="wasapi") == ["wasapi", "xaudio", "null"]
    assert ga.driver_chain(["xaudio"]) == ["xaudio", "null"]          # silence is always the last resort
    assert ga.driver_chain(["bogus"]) == ["xaudio", "wasapi", "null"]
    assert ga.next_driver("xaudio") == "wasapi" and ga.next_driver("wasapi") == "null" and ga.next_driver("null") is None


def test_a_driver_that_took_over_starts_first_next_time_but_null_never_does(tmp_path):
    ga.remember(tmp_path, ARCTIS["id"], "wasapi", "xaudio")
    assert ga.first_driver(tmp_path, ARCTIS["id"], 24) == "wasapi"
    assert ga.first_driver(tmp_path, LG["id"], 24) is None                          # per device
    assert ga.first_driver(tmp_path, ARCTIS["id"], 24, now=time.time() + 25 * 3600) is None   # expires
    ga.remember(tmp_path, LG["id"], "null", "wasapi")
    assert ga.first_driver(tmp_path, LG["id"], 24) is None


# ------------------------------------------------------------------------------------------------ boot log

def test_boot_phase_reads_the_real_logs():
    stalled = ga.boot_phase(log("xaudio_init_stalled.log"))
    assert stalled["content"] and stalled["audio_started"] and stalled["audio_slow"] and not stalled["audio_done"]
    assert stalled["audio_driver"] == "xaudio" and not stalled["netcmd"]
    late = ga.boot_phase(log("xaudio_late_loop_silent.log"))
    assert late["content"] and late["audio_slow"] and late["audio_done"] and late["netcmd"] and not late["audio_flowing"]
    ok = ga.boot_phase(log("xaudio_slow_then_running.log"))
    assert ok["audio_slow"] and ok["audio_done"] and ok["audio_flowing"]
    clean = ga.boot_phase(log("no_audio_warning.log"))
    assert clean["audio_started"] and clean["audio_done"] and not clean["audio_slow"]
    assert ga.boot_phase("")["content"] is False


def watch(**kw):
    return ga.BootWatch(0.0, **{"boot_wait_s": 30, "extended_wait_s": 120, "init_grace_s": 3, "stall_s": 6} | kw)


def test_audio_init_past_the_grace_asks_for_the_next_driver():
    w = watch()
    head = log("xaudio_init_stalled.log").split(WARN)[0]
    w.observe(head, 1.0)                                    # audio started at ~1 s, not returned yet
    assert w.decide(2.5, running=False) == "wait"
    w.observe(head + WARN + "\n", 3.0)                      # RetroArch's own 2 s warning
    assert w.warning == ga.AUDIO_WARNING
    assert w.decide(3.5, running=False) == "wait"           # 2.5 s into audio init
    assert w.decide(4.1, running=False) == "fallback" and "audio init not returned" in w.reason


def test_without_a_fallback_slow_audio_extends_the_wait_instead_of_failing():
    w = watch(can_fallback=False)
    w.observe(log("xaudio_init_stalled.log"), 1.0)
    assert w.decide(31.0, running=False) == "wait"          # content loaded, audio still opening: past the 30 s
    assert w.deadline() == 120.0
    assert w.decide(119.0, running=False) == "wait"
    assert w.decide(120.5, running=False) == "fail" and "audio still opening" in w.reason


def test_audio_opened_late_but_the_loop_stays_silent_is_an_audio_stall_too():
    w = watch()
    w.observe(log("xaudio_late_loop_silent.log"), 5.0)      # the failed job's log: device came back, loop never answered
    assert w.decide(8.0, running=False) == "wait"
    assert w.decide(11.5, running=False) == "fallback" and "loop still not answering" in w.reason
    w2 = watch(can_fallback=False)                          # last driver: the long wait, never the 30 s failure
    w2.observe(log("xaudio_late_loop_silent.log"), 5.0)
    assert w2.decide(60.0, running=False) == "wait"


def test_slow_audio_then_running_is_ready_with_a_warning():
    w = watch()
    w.observe(log("xaudio_slow_then_running.log"), 2.0)
    assert w.decide(2.5, running=True) == "ready"
    assert w.decide(4.0, running=False) == "wait" and w.warning == ga.AUDIO_WARNING


def test_a_boot_that_is_not_about_audio_still_fails_at_30s():
    w = watch()
    w.observe("[INFO] RetroArch 1.22.2\n[INFO] [Core] Loading dynamic libretro core\n", 0.5)
    assert w.decide(29.0, running=False) == "wait"
    assert w.decide(30.1, running=False) == "fail" and w.reason == "content not running after 30s"
    clean = watch()
    clean.observe(log("no_audio_warning.log"), 1.0)
    assert clean.decide(30.1, running=False) == "fail" and clean.warning is None


# ------------------------------------------------------------------------------------------------ RetroArch launch

class FakeProc:
    pid = 4242

    def __init__(self, log_path: Path, text: str):
        log_path.write_text(text)
        self.alive = True

    def poll(self):
        return None if self.alive else 1

    def kill(self):
        self.alive = False

    def wait(self, *a):
        return 1


def test_retroarch_restarts_with_wasapi_when_xaudio_stalls(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    exe = tmp_path / "ra" / "retroarch.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    core = tmp_path / "flycast_libretro.dll"
    core.write_bytes(b"core")
    from gbox import gamepads, graphics
    monkeypatch.setattr(gamepads, "retroarch_driver", lambda exe: "sdl3")
    monkeypatch.setattr(gamepads, "emulator_environment", lambda env: env)
    monkeypatch.setattr(graphics, "get", lambda *a: {})
    monkeypatch.setattr(graphics, "retroarch_opts", lambda *a: {})
    monkeypatch.setattr(adapters.provision, "retroarch_exe", lambda cfg: str(exe))
    monkeypatch.setattr(adapters.provision, "runtime_check",
                        lambda cfg, plat, core_name, exe: {"core": core, "cached": True, "bios_copied": []})
    sel = {"listing": {"default_id": ARCTIS["id"], "endpoints": [LG, ARCTIS]}, "chosen": ARCTIS | {"default": True, "why": "default playback device is active"},
           "retroarch_device": ARCTIS["name"], "active": 2, "error": None}
    monkeypatch.setattr(adapters, "_audio_selection", lambda ad, wait_s=1.0: sel)
    monkeypatch.setattr(adapters, "_examine_ok", lambda proc, wait_s=0.0: False)
    cfg = Config(data_dir=tmp_path, runtime_dirs={"windows": str(tmp_path / "rt")},
                 game_audio=GameAudioConfig(init_grace_s=0.3, stall_s=0.3, boot_wait_s=3, extended_wait_s=6))
    ad = adapters.RetroArchAdapter(EmulatorConfig(core="flycast"), config=cfg, platform="dreamcast", port=50123)
    launched = []

    def popen(_ad, argv, **kw):
        text = Path(argv[argv.index("--config") + 1]).read_text()
        driver = text.split('audio_driver = "')[1].split('"')[0]
        launched.append((driver, 'audio_device = "Headphones (2- Arctis Nova Pro Wireless)"' in text,
                         'audio_wasapi_exclusive_mode = "false"' in text))
        stalled = log("xaudio_init_stalled.log")
        return FakeProc(ad.log_path, stalled if driver == "xaudio" else log("xaudio_slow_then_running.log").replace(WARN, ""))
    monkeypatch.setattr(adapters, "_popen", popen)
    monkeypatch.setattr(adapters, "_kill_tree", lambda proc: proc and proc.kill())

    def status(timeout=2.0):
        if ad.audio_driver == "wasapi":
            return {"running": True, "state": "PLAYING", "content": "dreamcast,doa2,crc32=0"}
        raise RuntimeError("retroarch did not answer GET_STATUS")
    monkeypatch.setattr(ad, "query_runtime", status)
    rom = tmp_path / "doa2.chd"
    rom.write_bytes(b"chd")
    t = time.monotonic()
    out = ad.launch_game(str(rom))
    assert time.monotonic() - t < 5                                   # never the 30 s wait
    assert launched == [("xaudio", True, True), ("wasapi", True, True)]   # a named, active device both times
    audio = out["audio"]
    assert audio["driver"] == "wasapi" and audio["device"] == ARCTIS["name"] and audio["default_device"] is True
    assert [a["driver"] for a in audio["attempts"]] == ["xaudio", "wasapi"]
    assert audio["attempts"][0]["outcome"] == "fallback" and audio["attempts"][1]["outcome"] == "ready"
    assert audio["warning"].startswith(ga.AUDIO_WARNING) and out["warnings"] == [audio["warning"]]
    assert (ad.log_path.with_name(f"{ad.log_path.stem}-xaudio.log")).read_text().endswith(WARN + "\n")   # evidence kept
    assert ga.first_driver(cfg.runtime, ARCTIS["id"], 24) == "wasapi"     # the next launch starts with wasapi
    assert ad._audio_plan()["chain"] == ["wasapi", "xaudio", "null"]


def test_linux_sessions_keep_null_audio_and_the_plain_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    ad = adapters.RetroArchAdapter(EmulatorConfig(core="x"), config=SimpleNamespace(runtime=tmp_path), platform="snes", port=50124)
    plan = ad._audio_plan()
    assert plan["chain"] == ["null"] and plan["sel"] is None
