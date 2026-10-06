"""Speech-to-text through the Spark's Wyoming faster-whisper service (Home Assistant voice stack on :10300)."""
import json
import socket
import subprocess


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


def tts(text: str, director_url: str, engine: str = "xtts", voice: str = "", piper=("127.0.0.1", 10200)) -> tuple[bytes, str]:
    """Speak through the Voice Director (OpenAI-style /v1/audio/speech); fall back to Wyoming Piper. Returns (wav, engine).
    voice may be "engine:voice" (e.g. "kokoro:af_heart", "xtts:vl_0bc8104e")."""
    import httpx
    if ":" in voice:
        engine, voice = voice.split(":", 1)
    try:
        ensure_engine(director_url, engine, wait_s=90)
    except Exception:
        pass
    try:
        r = httpx.post(f"{director_url.rstrip('/')}/v1/audio/speech", timeout=120,
                       json={"model": engine, "voice": voice, "input": text[:1200], "response_format": "wav"})
        if r.status_code == 200 and r.content[:4] == b"RIFF":
            return r.content, engine
    except Exception:
        pass
    return _piper(text, *piper), "piper"


def _piper(text: str, host: str, port: int) -> bytes:
    import struct
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
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + \
        b"data" + struct.pack("<I", len(pcm)) + pcm


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
