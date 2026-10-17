"""audio.cpp as a gBox-managed local speech service (#816, docs/audio_cpp.md).

audio.cpp (github.com/mirek190/audio.cpp, Apache-2.0) is a C++/ggml runtime for speech models with an OpenAI-style HTTP
server, `audiocpp_server`. On a machine that has the binary gBox writes `<runtime>/audio_cpp/server.json` (a Kokoro TTS
model and a Qwen3-ASR model found under models_dir, plus any extra entries), starts `audiocpp_server --config` there,
keeps it alive, and talks to it:

- POST /v1/audio/speech          text -> WAV (gbox-tts)
- POST /v1/audio/transcriptions  multipart WAV -> {"text"} (gbox-stt)
- GET  /health                   readiness

When the binary is absent nothing starts and available() says why; every caller (speech routing, the worker tool,
the server endpoints) then keeps its previous behaviour. [audio_cpp] url points gBox at a server it does not manage.
"""
import atexit
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field, model_validator

from .config import Config
from .models import Permission as P
from .registry import HOST_OS, ToolUnavailable, tool

TTS_ID, STT_ID = "gbox-tts", "gbox-stt"
EXE = "audiocpp_server.exe" if HOST_OS == "windows" else "audiocpp_server"
# model_specs/<family>.json package layouts (audiocpp_model_manager install <package> --models-dir <models_dir>)
KNOWN_MODELS = {
    "kokoro_tts": ["Kokoro-82M-GGUF/*.gguf"],
    "qwen3_asr": ["Qwen3-ASR-1.7B-GGUF/*.gguf", "Qwen3-ASR-0.6B-GGUF/*.gguf", "Qwen3-ASR-1.7B*", "Qwen3-ASR-0.6B*"],
}
PACKAGES = {"kokoro_tts": "kokoro_82m_q8_0", "qwen3_asr": "qwen3_asr_0_6b_q8_0"}


class Busy(RuntimeError):
    """audio.cpp answered 503 (server_busy / insufficient_memory): another assistant should take the request."""


class Down(RuntimeError):
    """No audio.cpp service answers here (absent, disabled, stopped, crashed or still starting)."""


def _path(s: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(s)))


def _roots(cfg: Config) -> list[Path]:
    roots = [_path(d) for d in cfg.audio_cpp.search] + [cfg.runtime / "audio_cpp", Path.home() / "audio.cpp"]
    if HOST_OS == "windows":
        roots.append(Path("C:/_tools/audio.cpp"))
    return roots


def find_binary(cfg: Config) -> Path | None:
    """[audio_cpp] binary, else audiocpp_server on PATH, else a build tree under the searched folders."""
    a = cfg.audio_cpp
    if a.binary:
        p = _path(a.binary)
        return p.absolute() if p.is_file() else None
    if hit := shutil.which("audiocpp_server"):
        return Path(hit)
    for root in _roots(cfg):
        for pattern in (EXE, f"bin/{EXE}", f"build/bin/{EXE}", f"build/*/bin/{EXE}", f"build/*/bin/*/{EXE}"):
            hits = sorted(root.glob(pattern), key=lambda p: ("release" not in str(p).lower(), str(p)))
            if hits:
                return hits[0]
    return None


def models_dir(cfg: Config) -> Path:
    return _path(cfg.audio_cpp.models_dir) if cfg.audio_cpp.models_dir else cfg.runtime / "audio_cpp" / "models"


def find_model(cfg: Config, family: str, explicit: str | None) -> Path | None:
    """An explicit path (relative = under models_dir), else the family's installed package under models_dir."""
    root = models_dir(cfg)
    if explicit:
        p = _path(explicit)
        p = p if p.is_absolute() else root / p
        return p if p.exists() else None
    for pattern in KNOWN_MODELS.get(family, []):
        hits = sorted(root.glob(pattern), key=lambda p: ("q8_0" not in p.name.lower(), p.name))
        if hits:
            return hits[0]
    return None


def server_config(cfg: Config) -> dict:
    """The server.json gBox hands audiocpp_server (app/server/README.md 'Config')."""
    a = cfg.audio_cpp
    models = []
    if tts := find_model(cfg, a.tts_family, a.tts_model):
        models.append({"id": TTS_ID, "family": a.tts_family, "path": str(tts), "task": "tts", "mode": "offline"})
    if stt := find_model(cfg, a.stt_family, a.stt_model):
        models.append({"id": STT_ID, "family": a.stt_family, "path": str(stt), "task": "asr", "mode": "offline"})
    models += [dict(m) for m in a.models]
    conf = {"host": a.host, "port": a.port, "backend": a.backend or ("cuda" if a.gpu else "cpu"), "device": a.device,
            "lazy_load": a.lazy_load, "max_loaded_models": a.max_loaded_models, "idle_unload_ms": a.idle_unload_ms,
            "busy_timeout_ms": a.busy_timeout_ms, "models": models}
    if a.threads:
        conf["threads"] = a.threads
    return conf


def model_id(cfg: Config, task: str) -> str | None:
    """The configured model serving task ('tts' | 'asr'): gBox's own entry first, then an extra entry."""
    for m in server_config(cfg)["models"]:
        if m.get("task") == task:
            return m.get("id")
    return None


def available(cfg: Config) -> str | None:
    """None when audio.cpp can serve on this machine, else the reason it can't (callers keep their old path)."""
    a = cfg.audio_cpp
    if not a.enabled:
        return "audio.cpp is disabled ([audio_cpp] enabled = false)"
    if a.url:
        return None
    if not find_binary(cfg):
        where = a.binary or f"PATH or {', '.join(str(r) for r in _roots(cfg))}"
        return f"audiocpp_server not found ({where}); build it or set [audio_cpp] binary (docs/audio_cpp.md)"
    if not server_config(cfg)["models"]:
        return (f"no audio.cpp models under {models_dir(cfg)}: audiocpp_model_manager install "
                f"{PACKAGES.get(a.tts_family, a.tts_family)} --models-dir {models_dir(cfg)} (docs/audio_cpp.md)")
    return None


_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _http() -> httpx.Client:
    """One pooled client for every audio.cpp call (building one per request costs seconds; no proxy for a local port)."""
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(trust_env=False, timeout=30)
        return _client


def _repo_root(binary: Path) -> Path:
    """audio.cpp finds model_specs/ relative to its working folder: the checkout that built the binary, if any."""
    for p in binary.parents:
        if (p / "model_specs").is_dir():
            return p
    return binary.parent


class Service:
    """One audiocpp_server process gBox started on this machine (or an adopted / external one it only talks to)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.supervisor: threading.Thread | None = None
        self.adopted = False             # something else already served the port when gBox looked
        self.restarts = 0
        self.started_at: float | None = None
        self.last_error = ""

    @property
    def dir(self) -> Path:
        return self.cfg.runtime / "audio_cpp"

    @property
    def url(self) -> str:
        a = self.cfg.audio_cpp
        host = "127.0.0.1" if a.host in ("0.0.0.0", "::", "") else a.host
        return (a.url or f"http://{host}:{a.port}").rstrip("/")

    @property
    def managed(self) -> bool:
        return not self.cfg.audio_cpp.url

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def health(self, timeout: float = 2.0) -> dict | None:
        u = httpx.URL(self.url)
        try:                                       # a closed local port costs ~2 s per HTTP attempt on Windows
            socket.create_connection((u.host, u.port or 80), timeout=min(timeout, 0.5)).close()
        except OSError:
            return None
        try:
            r = _http().get(f"{self.url}/health", timeout=timeout)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        try:
            body = r.json()
        except ValueError:
            body = {}
        return body if isinstance(body, dict) else {"body": body}

    def start(self, wait: bool = True, _supervisor: bool = False) -> dict:
        """Start audiocpp_server (no-op when it already answers or the server is external). Raises Down on failure.
        An explicit start re-arms the service; the supervisor's own restarts never override a stop()."""
        with self.lock:
            if _supervisor:
                if self.stopping.is_set():
                    return self.status()
            else:
                self.stopping.clear()
            if not self.managed or self.running():
                return self._wait() if wait and self.managed else self.status()
            if self.health(1.0) is not None:
                self.adopted = True
                return self.status()
            if reason := available(self.cfg):
                self.last_error = reason
                raise Down(reason)
            binary = find_binary(self.cfg)
            self.dir.mkdir(parents=True, exist_ok=True)
            conf = self.dir / "server.json"
            conf.write_text(json.dumps(server_config(self.cfg), indent=2), encoding="utf-8")
            # a .py "binary" is a stand-in server (tests/fake_audiocpp_server.py) run by this Python
            cmd = ([sys.executable, str(binary)] if binary.suffix == ".py" else [str(binary)])
            cmd += [*self.cfg.audio_cpp.args, "--config", str(conf)]
            log = open(self.dir / "server.log", "ab")
            log.write(f"\n--- gBox starting {cmd} at {time.ctime()}\n".encode())
            log.flush()
            try:
                self.proc = subprocess.Popen(cmd, cwd=str(_repo_root(binary)), stdin=subprocess.DEVNULL, stdout=log,
                                             stderr=subprocess.STDOUT,
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError as e:
                self.last_error = f"audiocpp_server did not start: {e}"
                raise Down(self.last_error) from e
            finally:
                log.close()
            self.adopted, self.started_at = False, time.time()
        return self._wait() if wait else self.status()

    def _wait(self) -> dict:
        end = time.monotonic() + self.cfg.audio_cpp.start_timeout_s
        while time.monotonic() < end:
            if self.stopping.is_set() and self.proc is None:
                raise Down("audio.cpp was stopped while starting")
            if self.health(1.0) is not None:
                self.last_error = ""
                return self.status()
            if self.proc is not None and self.proc.poll() is not None:
                self.last_error = f"audiocpp_server exited with {self.proc.returncode}: {self.log_tail()}"
                raise Down(self.last_error)
            time.sleep(0.2)
        self.last_error = f"audiocpp_server not healthy after {self.cfg.audio_cpp.start_timeout_s}s: {self.log_tail()}"
        raise Down(self.last_error)

    def stop(self) -> dict:
        """Stop the process gBox started (never one it adopted or an external server)."""
        self.stopping.set()
        with self.lock:
            proc, self.proc = self.proc, None
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            self.adopted = False
        return self.status()

    def ensure(self, wait_start: bool = True) -> None:
        """Make sure a server answers. wait_start=False (a fallback) never waits for a cold start: Down instead."""
        if self.health() is not None:
            return
        if not self.managed:
            raise Down(f"audio.cpp at {self.url} does not answer")
        if not wait_start:
            if not self.running() and available(self.cfg) is None and self.cfg.audio_cpp.autostart:
                threading.Thread(target=self._quiet_start, daemon=True).start()
            raise Down("audio.cpp is not running yet")
        self.start(wait=True)

    def _quiet_start(self):
        try:
            self.start(wait=True)
        except Down:
            pass

    def supervise(self, every_s: float = 5.0) -> None:
        """Start the server and restart it when it exits (backoff 5 s .. 5 min), until stop()."""
        backoff = every_s
        while not self.stopping.is_set():
            if not self.running() and not (self.adopted and self.health() is not None):
                if self.proc is not None:                  # it was running and exited
                    self.restarts += 1
                if self.stopping.is_set():
                    break
                try:
                    self.start(wait=True, _supervisor=True)
                    backoff = every_s
                except Down:
                    backoff = min(backoff * 2, 300.0)
                    self.stopping.wait(backoff)
                    continue
            self.stopping.wait(every_s)

    def keep_alive(self) -> None:
        """Run supervise() in the background unless it already runs."""
        with self.lock:
            if self.managed and (self.supervisor is None or not self.supervisor.is_alive()):
                self.stopping.clear()
                self.supervisor = threading.Thread(target=self.supervise, name="audio_cpp", daemon=True)
                self.supervisor.start()

    def log_tail(self, n: int = 600) -> str:
        try:
            return (self.dir / "server.log").read_bytes()[-n:].decode(errors="replace").strip()
        except OSError:
            return ""

    def status(self) -> dict:
        reason = available(self.cfg)
        binary = find_binary(self.cfg)
        health = self.health(1.0) if reason is None else None
        return {"available": reason is None, "reason": reason, "url": self.url, "managed": self.managed,
                "binary": str(binary) if binary else None, "models_dir": str(models_dir(self.cfg)),
                "models": [{k: m.get(k) for k in ("id", "family", "task", "path")} for m in server_config(self.cfg)["models"]],
                "running": self.running(), "adopted": self.adopted, "pid": self.proc.pid if self.running() else None,
                "healthy": health is not None, "health": health, "restarts": self.restarts, "last_error": self.last_error,
                "backend": server_config(self.cfg)["backend"], "config": str(self.dir / "server.json"),
                "log": str(self.dir / "server.log"), "started_at": self.started_at}


_services: dict[tuple, Service] = {}
_lock = threading.Lock()


def service(cfg: Config) -> Service:
    key = (str(cfg.runtime), cfg.audio_cpp.model_dump_json())
    with _lock:
        if key not in _services:
            _services[key] = Service(cfg)
        return _services[key]


def autostart(cfg: Config) -> bool:
    """Worker / control-plane startup: supervise audiocpp_server when it is on this machine. False = nothing to start."""
    a = cfg.audio_cpp
    if not (a.enabled and a.autostart) or a.url or available(cfg):
        return False
    service(cfg).keep_alive()
    return True


def stop_all():
    for s in list(_services.values()):
        if s.managed and s.proc is not None:
            s.stop()


atexit.register(stop_all)


# --- client ---------------------------------------------------------------------------------------------------

def _check(r: httpx.Response, what: str):
    if r.status_code == 503:
        raise Busy(f"audio.cpp {what} busy: {r.text[:200]}")
    if r.status_code != 200:
        raise RuntimeError(f"audio.cpp {what} failed ({r.status_code}): {r.text[:300]}")


def speak(cfg: Config, text: str, voice: str | None = None, speed: float | None = None,
          wait_start: bool = True) -> bytes:
    """Text -> WAV through audio.cpp's /v1/audio/speech. Raises Down / Busy / RuntimeError."""
    if reason := available(cfg):
        raise Down(reason)
    s = service(cfg)
    s.ensure(wait_start)
    a = cfg.audio_cpp
    if not (mid := model_id(cfg, "tts") or (None if s.managed else TTS_ID)):
        raise Down("audio.cpp has no text-to-speech model configured")
    body = {"model": mid, "input": text[:2000], "response_format": "wav", "voice": voice or a.tts_voice}
    if a.tts_language:
        body["language"] = a.tts_language
    if speed:
        body["speed"] = speed
    if a.busy_timeout_ms:
        body["busy_timeout_ms"] = a.busy_timeout_ms
    try:
        r = _http().post(f"{s.url}/v1/audio/speech", json=body, timeout=180)
    except httpx.HTTPError as e:
        raise Down(f"audio.cpp unreachable: {e}") from e
    _check(r, "speech")
    if r.content[:4] != b"RIFF":
        raise RuntimeError("audio.cpp speech returned no WAV")
    return r.content


def as_wav(audio: bytes) -> bytes:
    """audio.cpp's default build decodes WAV only: browser recordings (webm/ogg/mp3) go through ffmpeg to 16 kHz mono."""
    if audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        return audio
    from . import speech
    return speech.wav_bytes(speech.to_pcm16k(audio), 16000)


def transcribe(cfg: Config, audio: bytes, language: str | None = None, wait_start: bool = True) -> str:
    """Recording -> text through audio.cpp's /v1/audio/transcriptions (multipart, OpenAI Whisper style)."""
    if reason := available(cfg):
        raise Down(reason)
    s = service(cfg)
    s.ensure(wait_start)
    a = cfg.audio_cpp
    if not (mid := model_id(cfg, "asr") or (None if s.managed else STT_ID)):
        raise Down("audio.cpp has no speech-to-text model configured")
    data = {"model": mid}
    if lang := (language if language is not None else a.stt_language):
        data["language"] = lang
    if a.busy_timeout_ms:
        data["busy_timeout_ms"] = str(a.busy_timeout_ms)
    try:
        r = _http().post(f"{s.url}/v1/audio/transcriptions", data=data,
                       files={"file": ("speech.wav", as_wav(audio), "audio/wav")}, timeout=180)
    except httpx.HTTPError as e:
        raise Down(f"audio.cpp unreachable: {e}") from e
    _check(r, "transcription")
    return (r.json().get("text") or "").strip()


def voices(cfg: Config) -> list[str]:
    """The TTS model's voices as audio.cpp lists them (GET /v1/audio/voices); [] when it doesn't answer."""
    s = service(cfg)
    mid = model_id(cfg, "tts") or TTS_ID
    try:
        r = _http().get(f"{s.url}/v1/audio/voices", params={"model": mid}, timeout=3)
        return [str(v) for v in r.json().get("voices", [])] if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError, AttributeError):
        return []


# --- worker tool ------------------------------------------------------------------------------------------------

class AudioCppIn(BaseModel):
    op: Literal["status", "start", "stop", "speak", "transcribe"] = "status"
    text: str | None = Field(None, max_length=2000, description="speak: the words")
    voice: str | None = Field(None, description="speak: a voice id (Kokoro: af_heart, bm_george ...); unset = [audio_cpp] tts_voice")
    speed: float | None = Field(None, gt=0, le=4)
    audio_b64: str | None = Field(None, description="transcribe: the recording (wav; webm/ogg/mp3 are converted with ffmpeg)")
    audio_path: str | None = Field(None, description="transcribe: a recording file on this worker")
    language: str | None = Field(None, description="transcribe: language code; unset = [audio_cpp] stt_language")

    @model_validator(mode="after")
    def _shape(self):
        if self.op == "speak" and not (self.text or "").strip():
            raise ValueError("speak needs text")
        if self.op == "transcribe" and (self.audio_b64 is None) == (self.audio_path is None):
            raise ValueError("transcribe needs exactly one of audio_b64 or audio_path")
        return self


class AudioCppOut(BaseModel):
    op: str
    status: dict = {}
    text: str | None = None
    artifact: str | None = None
    bytes: int = 0


@tool("audio_cpp", "1.0", AudioCppIn, AudioCppOut, capabilities=["speech", "tts", "stt"],
      permissions=[P.READ, P.EXECUTE], side_effects=["starts or stops this machine's audiocpp_server"],
      artifacts=["speech.wav"], timeout_s=300, check=available)
def audio_cpp_tool(inp: AudioCppIn, ctx):
    """audio.cpp local speech service on this machine (docs/audio_cpp.md): op=status | start | stop | speak text=..
    (voice=, speed=; the WAV is the speech.wav artifact) | transcribe audio_b64=.. or audio_path=.. (language=)."""
    s = service(ctx.config)
    try:
        if inp.op == "start":
            ctx.progress(5, "Starting audio.cpp")
            st = s.start(wait=True)
            s.keep_alive()
            return {"op": inp.op, "status": st}
        if inp.op == "stop":
            return {"op": inp.op, "status": s.stop()}
        if inp.op == "speak":
            wav = speak(ctx.config, inp.text, inp.voice, inp.speed)
            ctx.artifact("speech.wav", wav, "audio/wav", engine="audio_cpp", voice=inp.voice or ctx.config.audio_cpp.tts_voice)
            return {"op": inp.op, "artifact": "speech.wav", "bytes": len(wav)}
        if inp.op == "transcribe":
            audio = Path(inp.audio_path).read_bytes() if inp.audio_path else base64.b64decode(inp.audio_b64)
            return {"op": inp.op, "text": transcribe(ctx.config, audio, inp.language)}
    except Down as e:
        raise ToolUnavailable(str(e)) from e
    return {"op": inp.op, "status": s.status()}
