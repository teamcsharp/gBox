"""audio.cpp as a gBox local speech service (#816): discovery, the managed process (a fake audiocpp_server),
the audio_cpp worker tool, voice-director routing and the server endpoints."""
import base64
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import free_port
from gbox import audio_cpp, speech
from gbox.config import AudioCppConfig, Config, VoiceConfig
from gbox.registry import Ctx, ToolUnavailable, execute

FAKE = Path(__file__).with_name("fake_audiocpp_server.py")


def _models(root: Path, tts=True, stt=True) -> Path:
    if tts:
        (root / "Kokoro-82M-GGUF").mkdir(parents=True, exist_ok=True)
        (root / "Kokoro-82M-GGUF" / "kokoro-82m-bf16.gguf").write_bytes(b"GGUF")
        (root / "Kokoro-82M-GGUF" / "kokoro-82m-q8_0.gguf").write_bytes(b"GGUF")
    if stt:
        (root / "Qwen3-ASR-0.6B-GGUF").mkdir(parents=True, exist_ok=True)
        (root / "Qwen3-ASR-0.6B-GGUF" / "qwen3-asr-0.6b-q8_0.gguf").write_bytes(b"GGUF")
    return root


def _cfg(tmp_path, *, binary=FAKE, args=(), voice=None, **kw) -> Config:
    a = AudioCppConfig(binary=str(binary) if binary else None, args=list(args), port=free_port(),
                       models_dir=str(_models(tmp_path / "models")), start_timeout_s=60, **kw)
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", api_port=free_port(), audio_cpp=a,
                  voice=voice or VoiceConfig())


@pytest.fixture
def router(monkeypatch):
    r = speech.Router()
    monkeypatch.setattr(speech, "ROUTER", r)
    return r


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """A running fake audiocpp_server managed by gBox, shared by this module's tests; stopped afterwards."""
    cfg = _cfg(tmp_path_factory.mktemp("live"))
    svc = audio_cpp.service(cfg)
    svc.start(wait=True)
    yield cfg
    svc.stop()


def _requests(cfg) -> list[dict]:
    p = cfg.runtime / "audio_cpp" / "requests.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


# --- discovery and config ---------------------------------------------------------------------------------------

def test_absent_binary_makes_audio_cpp_unavailable_with_a_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_cpp.shutil, "which", lambda _: None)
    monkeypatch.setattr(audio_cpp, "_roots", lambda cfg: [tmp_path / "nowhere"])
    cfg = _cfg(tmp_path, binary=None)
    assert audio_cpp.find_binary(cfg) is None
    assert "audiocpp_server not found" in audio_cpp.available(cfg)
    assert audio_cpp.autostart(cfg) is False
    assert "not found" in audio_cpp.available(_cfg(tmp_path, binary=tmp_path / "missing.exe"))
    assert "disabled" in audio_cpp.available(_cfg(tmp_path, enabled=False))


def test_binary_discovered_in_a_build_tree_prefers_release(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_cpp.shutil, "which", lambda _: None)
    tree = tmp_path / "audio.cpp" / "build"
    for preset in ("windows-cuda-debug", "windows-cuda-release"):
        (tree / preset / "bin").mkdir(parents=True)
        (tree / preset / "bin" / audio_cpp.EXE).write_bytes(b"MZ")
    (tmp_path / "audio.cpp" / "model_specs").mkdir()
    cfg = _cfg(tmp_path, binary=None, search=[str(tmp_path / "audio.cpp")])
    found = audio_cpp.find_binary(cfg)
    assert found.parent.parent.name == "windows-cuda-release"
    assert audio_cpp._repo_root(found) == tmp_path / "audio.cpp"      # model_specs/ is found from the checkout
    assert audio_cpp.available(cfg) is None


def test_server_config_finds_models_and_maps_gpu_flag(tmp_path):
    cfg = _cfg(tmp_path, threads=4, models=[{"id": "pocket", "family": "pocket_tts", "path": "/m/pocket", "task": "tts"}])
    conf = audio_cpp.server_config(cfg)
    assert conf["backend"] == "cuda" and conf["port"] == cfg.audio_cpp.port and conf["threads"] == 4
    ids = {m["id"]: m for m in conf["models"]}
    assert ids["gbox-tts"]["family"] == "kokoro_tts" and ids["gbox-tts"]["path"].endswith("kokoro-82m-q8_0.gguf")
    assert ids["gbox-stt"]["task"] == "asr" and ids["gbox-stt"]["path"].endswith("qwen3-asr-0.6b-q8_0.gguf")
    assert "pocket" in ids
    assert audio_cpp.server_config(_cfg(tmp_path, gpu=False))["backend"] == "cpu"
    assert audio_cpp.server_config(_cfg(tmp_path, backend="vulkan"))["backend"] == "vulkan"


def test_no_models_is_a_reason_not_a_crash(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.audio_cpp.models_dir = str(tmp_path / "empty")
    why = audio_cpp.available(cfg)
    assert "no audio.cpp models" in why and "audiocpp_model_manager install kokoro_82m_q8_0" in why
    with pytest.raises(audio_cpp.Down):
        audio_cpp.service(cfg).start()


# --- the managed service ----------------------------------------------------------------------------------------

def test_service_starts_speaks_and_transcribes(live):
    svc = audio_cpp.service(live)
    st = svc.status()
    assert st["running"] and st["healthy"] and st["managed"] and st["pid"] and st["health"]["models"] == 2
    assert json.loads(Path(st["config"]).read_text())["models"][0]["id"] == "gbox-tts"
    before = len(_requests(live))
    wav = audio_cpp.speak(live, "Hello there", voice="bm_george", speed=1.2)
    assert wav[:4] == b"RIFF"
    assert audio_cpp.transcribe(live, speech.wav_bytes(b"\0\0" * 1600, 16000)) == "hello from audio.cpp"
    sent = _requests(live)[before:]
    assert sent[0]["model"] == "gbox-tts" and sent[0]["voice"] == "bm_george" and sent[0]["speed"] == 1.2
    assert sent[0]["busy_timeout_ms"] == 20000 and "language" not in sent[0]     # Kokoro takes it from the voice
    assert sent[1] == {"route": "transcriptions", "wav": True, "model": "gbox-stt", "language": True}
    assert audio_cpp.voices(live) == ["af_heart", "bm_george"]


def test_default_voice_and_non_wav_audio_goes_through_ffmpeg(live, monkeypatch):
    audio_cpp.speak(live, "Hi")
    assert _requests(live)[-1]["voice"] == "af_heart"
    monkeypatch.setattr(speech, "to_pcm16k", lambda audio: b"\0\0" * 800)       # webm -> pcm (ffmpeg in real life)
    assert audio_cpp.transcribe(live, b"\x1aE\xdf\xa3webm...") == "hello from audio.cpp"
    assert _requests(live)[-1]["wav"] is True


def test_busy_server_raises_busy_and_stop_ends_the_process(tmp_path):
    cfg = _cfg(tmp_path, args=["--fake-busy"])
    svc = audio_cpp.service(cfg)
    proc = svc.start() and svc.proc
    try:
        with pytest.raises(audio_cpp.Busy):
            audio_cpp.speak(cfg, "Hi")
    finally:
        st = svc.stop()
    assert proc.poll() is not None and not st["running"] and not st["healthy"]


def test_a_server_already_on_the_port_is_adopted_not_restarted_or_killed(live, tmp_path):
    other = Config(data_dir=tmp_path / "other", audio_cpp=live.audio_cpp)          # a second gBox process, same port
    svc = audio_cpp.service(other)
    assert svc is not audio_cpp.service(live)
    st = svc.start()
    assert st["adopted"] and st["healthy"] and not st["running"]
    svc.stop()
    assert audio_cpp.service(live).health() is not None                             # the owner's server still answers


def test_supervisor_restarts_a_crashed_server(tmp_path):
    cfg = _cfg(tmp_path)
    assert audio_cpp.autostart(cfg) is True
    svc = audio_cpp.service(cfg)
    try:
        end = time.time() + 20
        while svc.health() is None and time.time() < end:
            time.sleep(0.1)
        first = svc.proc.pid
        svc.proc.kill()
        svc.proc.wait()
        end = time.time() + 30
        while not (svc.running() and svc.proc.pid != first and svc.health() is not None) and time.time() < end:
            time.sleep(0.1)
        assert svc.running() and svc.proc.pid != first and svc.restarts == 1
    finally:
        svc.stop()
        svc.supervisor.join(10)
    assert not svc.supervisor.is_alive()


def test_external_url_is_used_but_never_started_or_stopped(live, tmp_path):
    ext = Config(data_dir=tmp_path / "ext", audio_cpp=AudioCppConfig(url=audio_cpp.service(live).url, binary=None))
    assert audio_cpp.available(ext) is None and audio_cpp.autostart(ext) is False
    svc = audio_cpp.service(ext)
    assert svc.start()["managed"] is False and svc.proc is None
    assert audio_cpp.speak(ext, "Hi")[:4] == b"RIFF"                                 # model id falls back to gbox-tts
    svc.stop()
    assert audio_cpp.service(live).health() is not None


# --- the worker tool --------------------------------------------------------------------------------------------

def test_worker_tool_speak_transcribe_status(live):
    ctx = Ctx(live)
    out = execute("audio_cpp", {"op": "speak", "text": "Hello", "voice": "af_heart"}, ctx)
    assert out["artifact"] == "speech.wav" and out["bytes"] > 44
    assert ctx.artifacts[0][0] == "speech.wav" and ctx.artifacts[0][1][:4] == b"RIFF" and ctx.artifacts[0][2] == "audio/wav"
    b64 = base64.b64encode(speech.wav_bytes(b"\0\0" * 1600, 16000)).decode()
    assert execute("audio_cpp", {"op": "transcribe", "audio_b64": b64}, Ctx(live))["text"] == "hello from audio.cpp"
    assert execute("audio_cpp", {"op": "status"}, Ctx(live))["status"]["healthy"] is True


def test_worker_tool_validates_and_reports_absence(tmp_path, monkeypatch):
    from pydantic import ValidationError
    cfg = _cfg(tmp_path)
    with pytest.raises(ValidationError):
        execute("audio_cpp", {"op": "speak"}, Ctx(cfg))
    with pytest.raises(ValidationError):
        execute("audio_cpp", {"op": "transcribe", "audio_b64": "AA==", "audio_path": "x.wav"}, Ctx(cfg))
    absent = _cfg(tmp_path, binary=tmp_path / "missing.exe")
    with pytest.raises(ToolUnavailable, match="not found"):
        execute("audio_cpp", {"op": "status"}, Ctx(absent))


# --- routing ----------------------------------------------------------------------------------------------------

def test_without_audio_cpp_the_director_path_is_unchanged(tmp_path, monkeypatch, router):
    cfg = _cfg(tmp_path, binary=tmp_path / "missing.exe", voice=VoiceConfig(default_assistant="audio_cpp"))
    calls = []
    monkeypatch.setattr(speech, "tts", lambda *a: calls.append(("tts", a)) or (b"RIFFdirector", "xtts"))
    monkeypatch.setattr(speech, "transcribe", lambda *a: calls.append(("stt", a)) or "from whisper")
    monkeypatch.setattr(audio_cpp, "speak", lambda *a, **k: pytest.fail("audio.cpp must not be called"))
    assert speech.route_tts(cfg, "hi", None, "xtts:vl_1") == (b"RIFFdirector", "xtts")
    assert speech.route_stt(cfg, b"webm", "en") == ("from whisper", "director")
    assert calls[0] == ("tts", ("hi", "http://127.0.0.1:8090", "xtts", "xtts:vl_1"))
    assert calls[1] == ("stt", (b"webm", "127.0.0.1", 10300, "en"))


def _fake_assistants(monkeypatch, director=None, audio=None):
    calls = []

    def d_tts(text, url, engine, voice):
        calls.append(("director", text))
        return (director or (lambda: (b"RIFFd", engine)))()

    def a_speak(cfg, text, voice=None, speed=None, wait_start=True):
        calls.append(("audio_cpp", text, voice, wait_start))
        return (audio or (lambda: b"RIFFa"))()

    monkeypatch.setattr(audio_cpp, "available", lambda cfg: None)
    monkeypatch.setattr(speech, "director_tts", d_tts)
    monkeypatch.setattr(audio_cpp, "speak", a_speak)
    return calls


def test_default_assistant_audio_cpp_takes_requests_first(tmp_path, monkeypatch, router):
    calls = _fake_assistants(monkeypatch)
    cfg = _cfg(tmp_path, voice=VoiceConfig(default_assistant="audio_cpp"))
    assert speech.route_tts(cfg, "hi", None, "kokoro:af_bella") == (b"RIFFa", "audio_cpp")
    assert calls == [("audio_cpp", "hi", "af_bella", True)]                         # default: waits for a cold start
    assert speech.route_tts(cfg, "hi", None, "", default="director") == (b"RIFFd", "xtts")   # runtime override wins


def test_busy_director_sends_the_parallel_request_to_audio_cpp(tmp_path, monkeypatch, router):
    entered, release = threading.Event(), threading.Event()

    def slow():
        entered.set()
        release.wait(5)
        return b"RIFFd", "xtts"

    calls = _fake_assistants(monkeypatch, director=slow)
    cfg = _cfg(tmp_path)                                                             # default: director, 1 slot
    first = {}
    t = threading.Thread(target=lambda: first.update(r=speech.route_tts(cfg, "one", None, "xtts:vl_1")))
    t.start()
    assert entered.wait(5)
    assert speech.route_tts(cfg, "two", None, "xtts:vl_1") == (b"RIFFa", "audio_cpp")
    release.set()
    t.join(5)
    assert first["r"] == (b"RIFFd", "xtts")
    assert ("audio_cpp", "two", None, False) in calls                                # cloned voice -> audio.cpp default
    assert router.snapshot()["served"] == {"tts:director": 1, "tts:audio_cpp": 1}


def test_failed_director_goes_down_and_audio_cpp_answers_until_cooldown(tmp_path, monkeypatch, router):
    def broken():
        raise RuntimeError("director 500")

    calls = _fake_assistants(monkeypatch, director=broken)
    cfg = _cfg(tmp_path)
    assert speech.route_tts(cfg, "a")[1] == "audio_cpp"
    assert speech.route_tts(cfg, "b")[1] == "audio_cpp"
    assert [c[0] for c in calls] == ["director", "audio_cpp", "audio_cpp"]           # skipped while down
    assert router.snapshot()["down"] == ["director"]


def test_busy_audio_cpp_default_falls_back_to_the_director_and_piper_last(tmp_path, monkeypatch, router):
    def busy():
        raise audio_cpp.Busy("503")

    _fake_assistants(monkeypatch, audio=busy)
    cfg = _cfg(tmp_path, voice=VoiceConfig(default_assistant="audio_cpp"))
    assert speech.route_tts(cfg, "hi") == (b"RIFFd", "xtts")
    cfg.voice.fallback = False
    monkeypatch.setattr(speech, "_piper", lambda text, host, port: b"RIFFp")
    assert speech.route_tts(cfg, "hi") == (b"RIFFp", "piper")


def test_explicit_audio_cpp_voice_always_goes_to_audio_cpp(tmp_path, monkeypatch, router):
    calls = _fake_assistants(monkeypatch)
    assert speech.route_tts(_cfg(tmp_path), "hi", None, "audio_cpp:bm_george")[1] == "audio_cpp"
    assert calls == [("audio_cpp", "hi", "bm_george", True)]


def test_stt_routes_like_tts(tmp_path, monkeypatch, router):
    monkeypatch.setattr(audio_cpp, "available", lambda cfg: None)
    monkeypatch.setattr(audio_cpp, "transcribe", lambda cfg, audio, language=None, wait_start=True: "from audio.cpp")
    monkeypatch.setattr(speech, "transcribe", lambda *a: (_ for _ in ()).throw(ConnectionRefusedError("whisper down")))
    assert speech.route_stt(_cfg(tmp_path), b"webm", "en") == ("from audio.cpp", "audio_cpp")
    monkeypatch.setattr(audio_cpp, "transcribe", lambda *a, **k: (_ for _ in ()).throw(audio_cpp.Down("off")))
    with pytest.raises(RuntimeError, match="whisper down|skipped"):
        speech.route_stt(_cfg(tmp_path), b"webm", "en")


# --- server endpoints -------------------------------------------------------------------------------------------

def test_server_endpoints_with_audio_cpp_absent(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, binary=tmp_path / "missing.exe")
    from gbox.server import create_app
    c = TestClient(create_app(cfg),
                   headers={"authorization": f"Bearer {cfg.token()}"})
    a = c.get("/api/voice/assistants").json()
    assert a["default"] == "director" and a["audio_cpp"]["available"] is False
    assert c.put("/api/voice/default", json={"assistant": "audio_cpp"}).status_code == 409
    assert c.post("/api/audio_cpp/start").status_code == 409
    groups = c.get("/api/voice/voices").json()["groups"]
    assert [g["label"] for g in groups] == ["XTTS v2 · cloned voices (Pine Box library)", "Kokoro · fast"]


def test_server_routes_tts_and_stt_to_audio_cpp_when_it_is_the_default(live, monkeypatch, router):
    from gbox.server import create_app
    c = TestClient(create_app(live), headers={"authorization": f"Bearer {live.token()}"})
    assert c.get("/api/audio_cpp/status").json()["healthy"] is True
    voices = c.get("/api/voice/voices").json()
    assert voices["groups"][-1]["voices"][1] == {"id": "audio_cpp:bm_george", "name": "George (UK m)"}
    assert c.put("/api/voice/default", json={"assistant": "audio_cpp"}).json() == {"default_assistant": "audio_cpp"}
    r = c.post("/api/tts", json={"text": "Hello", "voice": "kokoro:af_heart"})
    assert r.status_code == 200 and r.headers["x-gbox-tts-engine"] == "audio_cpp" and r.content[:4] == b"RIFF"
    r = c.post("/api/stt", content=speech.wav_bytes(b"\0\0" * 1600, 16000))
    assert r.json() == {"text": "hello from audio.cpp", "assistant": "audio_cpp"}
    assert c.get("/api/voice/assistants").json()["routing"]["last"] == {"tts": "audio_cpp", "stt": "audio_cpp"}
    assert c.put("/api/voice/default", json={"assistant": None}).json() == {"default_assistant": "director"}
