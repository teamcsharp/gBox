"""Speech for gBox: two assistants and the routing between them (docs/audio_cpp.md).

- director: the Pine Box Voice Director (XTTS v2 clones, Kokoro) for speech, the Spark's Wyoming faster-whisper
  (Home Assistant voice stack on :10300) for dictation, Wyoming Piper as the last resort.
- audio_cpp: the local audio.cpp server gBox runs (gbox.audio_cpp), when its binary is on this machine.

route_tts / route_stt send a request to [voice] default_assistant first; when it is busy (director_slots in use) or
down, the other one takes it in parallel. Without audio.cpp they are exactly the old Director path.
"""
import json
import socket
import subprocess
import threading
import time


def voices(lib_dir: str) -> list[dict]:
    """The Pine Box voice library (spark-agent/data/voices/vl_*/meta.json) - cloned voices for XTTS v2."""
    import glob
    import os
    out = []
    for d in sorted(glob.glob(os.path.join(lib_dir, "vl_*"))):
        try:
            name = json.load(open(os.path.join(d, "meta.json"))).get("name") or os.path.basename(d)
        except (OSError, ValueError):
            name = os.path.basename(d)
        out.append({"id": os.path.basename(d), "name": name})
    return sorted(out, key=lambda v: v["name"].lower())


KOKORO_VOICES = [("af_heart", "Heart (US f)"), ("af_bella", "Bella (US f)"), ("af_nicole", "Nicole (US f)"), ("af_sarah", "Sarah (US f)"),
                 ("af_sky", "Sky (US f)"), ("af_nova", "Nova (US f)"), ("am_adam", "Adam (US m)"), ("am_michael", "Michael (US m)"),
                 ("am_fenrir", "Fenrir (US m)"), ("am_puck", "Puck (US m)"), ("am_echo", "Echo (US m)"), ("bf_emma", "Emma (UK f)"),
                 ("bf_isabella", "Isabella (UK f)"), ("bm_george", "George (UK m)"), ("bm_lewis", "Lewis (UK m)"), ("bm_fable", "Fable (UK m)")]

# The Voice Director's stock Kokoro recipe resolves an ancient transformers/tokenizers that has no arm64 wheel
# (needs Rust to build); these pins resolve to modern wheels. Applied at runtime through the Director's own API.
KOKORO_LAUNCH = {"kind": "uv", "port": 8776, "script": "kokoro_server.py",
                 "with": ["kokoro", "soundfile", "numpy", "misaki", "transformers>=4.40", "tokenizers>=0.19",
                          "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"]}


def ensure_engine(director_url: str, engine: str, wait_s: int = 120) -> bool:
    """Start a Voice Director engine if it's down (Kokoro gets the fixed launch recipe first)."""
    import httpx
    import time
    base = director_url.rstrip("/")
    st = httpx.get(f"{base}/director/engine/{engine}/status", timeout=10).json()
    if st.get("ready"):
        return True
    if engine == "kokoro":
        httpx.put(f"{base}/director/engine/kokoro", json={"launch": KOKORO_LAUNCH}, timeout=10)
    if st.get("manageable", True):
        httpx.post(f"{base}/director/engine/{engine}/deploy", timeout=30)
    for _ in range(wait_s // 3):
        time.sleep(3)
        if httpx.get(f"{base}/director/engine/{engine}/status", timeout=10).json().get("ready"):
            return True
    return False


def director_tts(text: str, director_url: str, engine: str = "xtts", voice: str = "") -> tuple[bytes, str]:
    """Speak through the Voice Director (OpenAI-style /v1/audio/speech). Returns (wav, engine); raises when it can't.
    voice may be "engine:voice" (e.g. "kokoro:af_heart", "xtts:vl_0bc8104e")."""
    import httpx
    if ":" in voice:
        engine, voice = voice.split(":", 1)
    try:
        ensure_engine(director_url, engine, wait_s=90)
    except Exception:
        pass
    r = httpx.post(f"{director_url.rstrip('/')}/v1/audio/speech", timeout=120,
                   json={"model": engine, "voice": voice, "input": text[:1200], "response_format": "wav"})
    if r.status_code == 200 and r.content[:4] == b"RIFF":
        return r.content, engine
    raise RuntimeError(f"Voice Director answered {r.status_code}: {r.text[:200]}")


def tts(text: str, director_url: str, engine: str = "xtts", voice: str = "", piper=("127.0.0.1", 10200)) -> tuple[bytes, str]:
    """Speak through the Voice Director; fall back to Wyoming Piper. Returns (wav, engine)."""
    try:
        return director_tts(text, director_url, engine, voice)
    except Exception:
        pass
    return _piper(text, *piper), "piper"


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    """Raw 16-bit mono PCM -> a WAV file."""
    import struct
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + \
        b"data" + struct.pack("<I", len(pcm)) + pcm


def _piper(text: str, host: str, port: int) -> bytes:
    with socket.create_connection((host, port), timeout=60) as s:
        _send(s, "synthesize", {"text": text[:1200]})
        f, pcm, rate = s.makefile("rb"), b"", 22050
        while True:
            hdr = json.loads(f.readline())
            n = hdr.get("data_length", 0)
            data = json.loads(f.read(n)) if n else {}
            if hdr.get("payload_length"):
                pcm += f.read(hdr["payload_length"])
            if hdr["type"] == "audio-start":
                rate = data.get("rate", rate)
            if hdr["type"] == "audio-stop":
                break
    return wav_bytes(pcm, rate)


def to_pcm16k(audio: bytes) -> bytes:
    """Any browser recording (webm/opus, ogg, wav...) -> raw 16 kHz mono s16le via ffmpeg."""
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
                       input=audio, capture_output=True, timeout=60)
    if r.returncode:
        raise RuntimeError(f"audio decode failed: {r.stderr.decode()[-300:]}")
    return r.stdout


def _send(sock, typ: str, data: dict | None = None, payload: bytes = b""):
    hdr = {"type": typ}
    body = json.dumps(data or {}).encode()
    hdr["data_length"] = len(body)
    if payload:
        hdr["payload_length"] = len(payload)
    sock.sendall(json.dumps(hdr).encode() + b"\n" + body + payload)


def transcribe(audio: bytes, host: str = "127.0.0.1", port: int = 10300, language: str | None = "en") -> str:
    pcm = to_pcm16k(audio)
    fmt = {"rate": 16000, "width": 2, "channels": 1}
    with socket.create_connection((host, port), timeout=60) as s:
        _send(s, "transcribe", {"language": language} if language else {})
        _send(s, "audio-start", fmt)
        for i in range(0, len(pcm), 32000):                     # 1 s chunks
            _send(s, "audio-chunk", fmt, pcm[i:i + 32000])
        _send(s, "audio-stop", {})
        f = s.makefile("rb")
        while True:
            line = f.readline()
            if not line:
                raise RuntimeError("speech service closed the connection")
            hdr = json.loads(line)
            n = hdr.get("data_length", 0)
            data = json.loads(f.read(n)) if n else hdr.get("data", {})
            if hdr.get("payload_length"):
                f.read(hdr["payload_length"])
            if hdr.get("type") == "transcript":
                return (data.get("text") or "").strip()


# --- speech assistants (#816) ---------------------------------------------------------------------------------------

ASSISTANTS = ("director", "audio_cpp")


class Router:
    """Requests in flight per assistant, recent failures, and who served what (shared by every request of a process)."""

    def __init__(self):
        self.cond = threading.Condition()
        self.active: dict[str, int] = {}        # "director:tts" / "director:stt" -> requests in flight
        self.down_until: dict[str, float] = {}  # assistant -> monotonic time its cooldown ends
        self.served: dict[str, int] = {}        # "tts:audio_cpp" -> count
        self.last: dict[str, str] = {}          # kind -> the assistant that served the last request

    def take(self, key: str, slots: int, wait: bool) -> bool:
        with self.cond:
            while self.active.get(key, 0) >= max(1, slots):
                if not wait:
                    return False
                self.cond.wait()
            self.active[key] = self.active.get(key, 0) + 1
            return True

    def release(self, key: str):
        with self.cond:
            self.active[key] = max(0, self.active.get(key, 0) - 1)
            self.cond.notify_all()

    def mark_down(self, who: str, cooldown_s: float):
        self.down_until[who] = time.monotonic() + cooldown_s

    def is_down(self, who: str) -> bool:
        return time.monotonic() < self.down_until.get(who, 0)

    def record(self, kind: str, who: str):
        with self.cond:
            self.served[f"{kind}:{who}"] = self.served.get(f"{kind}:{who}", 0) + 1
            self.last[kind] = who

    def snapshot(self) -> dict:
        with self.cond:
            return {"active": dict(self.active), "served": dict(self.served), "last": dict(self.last),
                    "down": sorted(w for w in ASSISTANTS if self.is_down(w))}


ROUTER = Router()


def order(cfg, default: str | None = None) -> list[str]:
    """The default assistant, then (with [voice] fallback) the other one."""
    first = default if default in ASSISTANTS else cfg.voice.default_assistant
    other = "audio_cpp" if first == "director" else "director"
    return [first, other] if cfg.voice.fallback else [first]


def _dispatch(cfg, kind: str, seq: list[str], director_call, audio_call):
    """Run the request on the first assistant in seq that can take it now. Returns (result, assistant).

    The Director takes at most [voice] director_slots requests of a kind at once; a further one goes to audio.cpp in
    parallel instead of queueing, and so does every request while the Director is in its failure cooldown. audio.cpp
    as the default waits for its own cold start; as the fallback it never does (Down -> the Director after all)."""
    errors, director_busy = [], False
    key, slots = f"director:{kind}", cfg.voice.director_slots

    def director():
        try:
            out = director_call()
        except Exception as e:
            ROUTER.mark_down("director", cfg.voice.down_cooldown_s)
            errors.append(f"director: {e}")
            return None
        finally:
            ROUTER.release(key)
        ROUTER.record(kind, "director")
        return out, "director"

    for i, who in enumerate(seq):
        more = i < len(seq) - 1
        if who == "director":
            if more and ROUTER.is_down("director"):
                errors.append("director: skipped after a recent failure")
                continue
            if not ROUTER.take(key, slots, wait=not more):
                director_busy = True
                continue
            if (hit := director()) is not None:
                return hit
        else:
            try:
                out = audio_call(i == 0)
            except Exception as e:
                errors.append(f"audio_cpp: {e}")
                continue
            ROUTER.record(kind, "audio_cpp")
            return out, "audio_cpp"
    if director_busy:                              # audio.cpp couldn't help: wait for the Director's slot after all
        ROUTER.take(key, slots, wait=True)
        if (hit := director()) is not None:
            return hit
    raise RuntimeError("; ".join(errors) or "no speech assistant available")


def audio_cpp_voice(cfg, voice: str) -> str | None:
    """A gBox voice id ("audio_cpp:af_heart", "kokoro:af_heart", "xtts:vl_...") -> the audio.cpp voice, or None for
    its default (a cloned XTTS voice has no audio.cpp twin)."""
    eng, _, v = (voice or "").rpartition(":")
    kokoro = cfg.audio_cpp.tts_family == "kokoro_tts"
    if eng == "audio_cpp" or (kokoro and (eng == "kokoro" or (not eng and v in dict(KOKORO_VOICES)))):
        return v or None
    return None


def route_tts(cfg, text: str, engine: str | None = None, voice: str = "", default: str | None = None) -> tuple[bytes, str]:
    """Speak a reply. Returns (wav, what spoke: the Director engine, "audio_cpp" or "piper")."""
    from . import audio_cpp
    url = cfg.agent.get("voice_director", "http://127.0.0.1:8090")
    engine = engine or cfg.agent.get("tts_engine", "xtts")
    voice = voice or ""
    if audio_cpp.available(cfg):                   # no audio.cpp here: the Director path exactly as before
        return tts(text, url, engine, voice)
    used = {}

    def director():
        wav, used["engine"] = director_tts(text, url, engine, voice)
        return wav

    seq = ["audio_cpp"] if voice.startswith("audio_cpp:") else order(cfg, default)
    try:
        wav, who = _dispatch(cfg, "tts", seq, director,
                             lambda wait: audio_cpp.speak(cfg, text, audio_cpp_voice(cfg, voice), wait_start=wait))
    except RuntimeError:
        return _piper(text, "127.0.0.1", 10200), "piper"
    return wav, (used.get("engine", engine) if who == "director" else who)


def route_stt(cfg, audio: bytes, language: str | None = "en", default: str | None = None) -> tuple[str, str]:
    """Dictation. Returns (text, "director" | "audio_cpp"); raises when no assistant could transcribe."""
    from . import audio_cpp
    host, port = cfg.agent.get("stt_host", "127.0.0.1"), int(cfg.agent.get("stt_port", 10300))
    if audio_cpp.available(cfg):
        return transcribe(audio, host, port, language), "director"
    return _dispatch(cfg, "stt", order(cfg, default), lambda: transcribe(audio, host, port, language),
                     lambda wait: audio_cpp.transcribe(cfg, audio, language, wait_start=wait))


def assistants(cfg, default: str | None = None) -> dict:
    """What /api/voice/assistants shows: the default, the fallback rule, both assistants and the routing counters."""
    from . import audio_cpp
    return {"default": default if default in ASSISTANTS else cfg.voice.default_assistant, "fallback": cfg.voice.fallback,
            "director_slots": cfg.voice.director_slots, "options": list(ASSISTANTS),
            "director": {"url": cfg.agent.get("voice_director", "http://127.0.0.1:8090"),
                         "stt": f"{cfg.agent.get('stt_host', '127.0.0.1')}:{cfg.agent.get('stt_port', 10300)}"},
            "audio_cpp": audio_cpp.service(cfg).status(), "routing": ROUTER.snapshot()}
