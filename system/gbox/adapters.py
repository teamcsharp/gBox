"""Runtime/emulator adapters behind one capability interface (plan §6). Unsupported ops raise Unsupported."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import provision
from .config import HOST_OS, Config, EmulatorConfig
from .registry import ToolUnavailable, Unsupported

OPS = ["launch_game", "stop_game", "pause", "resume", "get_frame", "get_audio", "send_input", "read_memory",
       "write_memory", "query_memory_map", "save_state", "load_state", "step_frames", "set_breakpoint",
       "remove_breakpoint", "trace_execution", "query_runtime", "stream_session", "rewind", "fast_forward"]

# Rewind policy per platform.
# No rewind where snapshotting every few frames would cost frame rate (Dolphin/PCSX2/Citra cores).
NO_REWIND = {"gamecube", "wii", "ps2", "3ds", "wiiu", "switch"}
# 3D / CD systems: snapshot every 15 frames (coarser steps, cheap); 8/16-bit: every 4 frames (smooth).
COARSE_REWIND = {"n64", "n64dd", "psx", "dreamcast", "naomi", "saturn", "psp", "segacd", "pcecd", "3do", "jaguar", "neocd", "cdi", "pcfx"}
# Pads whose games actually use L2/R2 (triggers): never steal those for rewind / fast-forward.
TRIGGERS_USED = {"psx", "ps2", "dreamcast", "naomi", "gamecube", "wii", "n64", "n64dd", "3ds", "wiiu", "switch"}


class Adapter:
    name = "base"
    supported: set[str] = set()

    def get_capabilities(self) -> dict[str, str]:
        return {op: ("supported" if op in self.supported else "unsupported") for op in OPS}

    def __getattr__(self, op):
        if op in OPS:
            def unsupported(*a, **k):
                raise Unsupported(f"{self.name} does not support {op}")
            return unsupported
        raise AttributeError(op)


def _kill_tree(proc: subprocess.Popen | None):
    if not proc or proc.poll() is not None:
        return
    if HOST_OS == "windows":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


class CommandAdapter(Adapter):
    """Any emulator launched by a command template. Process lifetime only; no introspection."""
    name = "command"
    supported = {"launch_game", "stop_game", "query_runtime"}

    def __init__(self, cfg: EmulatorConfig):
        self.cfg, self.proc = cfg, None

    def _argv(self, rom: str) -> list[str]:
        return [self.cfg.executable] + [a.replace("{rom}", rom) for a in self.cfg.args]

    def launch_game(self, rom: str) -> dict:
        if not shutil.which(self.cfg.executable or "") and not Path(self.cfg.executable or "").exists():
            raise ToolUnavailable(f"emulator not found: {self.cfg.executable}")
        self.proc = subprocess.Popen(self._argv(rom))
        return {"pid": self.proc.pid}

    def stop_game(self) -> dict:
        _kill_tree(self.proc)
        return {"returncode": self.proc.poll() if self.proc else None}

    def query_runtime(self) -> dict:
        return {"running": bool(self.proc and self.proc.poll() is None), "pid": self.proc and self.proc.pid}


# --- virtual display (linux) ---------------------------------------------------------------

class Display:
    """A private Xvfb display per session so sessions never overlap and frames/input are isolated."""
    def __init__(self, w: int = 960, h: int = 720):          # = stream size: no rescale per frame
        self.w, self.h, self.proc = w, h, None
        for n in range(90, 140):
            if not Path(f"/tmp/.X11-unix/X{n}").exists() and not Path(f"/tmp/.X{n}-lock").exists():
                self.name = f":{n}"
                break
        else:
            raise RuntimeError("no free X display numbers")
        self.proc = subprocess.Popen(["Xvfb", self.name, "-screen", "0", f"{w}x{h}x24", "+extension", "GLX", "-nolisten", "tcp"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if subprocess.run(["xdpyinfo", "-display", self.name], capture_output=True).returncode == 0:
                return
            time.sleep(0.1)
        raise RuntimeError(f"Xvfb {self.name} did not start")

    def close(self):
        _kill_tree(self.proc)


def grab_png(display: str | None, region: list[int] | None = None) -> bytes:
    """One frame: x11grab on linux (display), gdigrab desktop on windows."""
    out = Path(tempfile.mkdtemp()) / "frame.png"
    if HOST_OS == "windows":
        src = ["-f", "gdigrab"]
        if region:
            x, y, w, h = region
            src += ["-offset_x", str(x), "-offset_y", str(y), "-video_size", f"{w}x{h}"]
        src += ["-i", "desktop"]
    else:
        src = ["-f", "x11grab"]
        disp = display or os.environ.get("DISPLAY", ":0")
        if region:
            x, y, w, h = region
            src += ["-video_size", f"{w}x{h}", "-i", f"{disp}+{x},{y}"]
        else:
            src += ["-i", disp]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *src, "-frames:v", "1", str(out)], check=True, timeout=30)
    data = out.read_bytes()
    shutil.rmtree(out.parent, ignore_errors=True)
    return data


class MjpegStream:
    """Persistent ffmpeg grab -> MJPEG pipe; `latest` always holds the newest complete JPEG.
    ponytail: MJPEG over HTTP (~60 fps on LAN, no audio); move to H.264/NVENC over WebRTC if bandwidth/latency bite."""
    def __init__(self, display: str | None, fps: int = 60, size: tuple[int, int] | None = None):
        if HOST_OS == "windows":
            src = ["-f", "gdigrab", "-draw_mouse", "0", "-framerate", str(fps), "-i", "desktop"]
        else:
            src = ["-f", "x11grab", "-draw_mouse", "0", "-framerate", str(fps),
                   *(["-video_size", f"{size[0]}x{size[1]}"] if size else []), "-i", display or ":0"]
        self.proc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-fflags", "nobuffer", *src,
                                      "-vf", "scale='min(960,iw)':-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-pix_fmt", "yuvj420p",
                                      "-q:v", "7", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.latest, self.seq, self.cond = None, 0, threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()

    def wait(self, seen: int, timeout: float) -> bool:
        """Block until a frame newer than `seen` exists."""
        with self.cond:
            return self.cond.wait_for(lambda: self.seq != seen and self.latest is not None, timeout)

    def _read(self):
        buf = b""
        while chunk := self.proc.stdout.read1(262144):
            buf += chunk
            while (s := buf.find(b"\xff\xd8")) >= 0 and (e := buf.find(b"\xff\xd9", s + 2)) >= 0:
                with self.cond:
                    self.latest, self.seq, buf = buf[s:e + 2], self.seq + 1, buf[e + 2:]
                    self.cond.notify_all()

    def close(self):
        _kill_tree(self.proc)


# RetroPad button -> X keysym per player. P1 = RetroArch defaults; P2 is bound in the session config (_write_cfg).
# Hotkeys are gated behind scroll_lock (never sent), so pad keys can't trigger pause/fast-forward/fullscreen etc.
PAD_KEYS = {
    1: {"up": "Up", "down": "Down", "left": "Left", "right": "Right", "a": "x", "b": "z", "x": "s", "y": "a",
        "l": "q", "r": "w", "start": "Return", "select": "Shift_R", "l2": "e", "r2": "r", "l3": "d", "r3": "f"},
    2: {"up": "i", "down": "k", "left": "j", "right": "l", "a": "n", "b": "b", "x": "h", "y": "u",
        "l": "y", "r": "o", "start": "p", "select": "t", "l2": "g", "r2": "v", "l3": "c", "r3": "m"},
}
_RA_KEYNAME = {"Up": "up", "Down": "down", "Left": "left", "Right": "right", "Return": "enter", "Shift_R": "rshift"}


VGLRUN = "/opt/VirtualGL/bin/vglrun"


def _pad_binds() -> dict:
    """retroarch.cfg lines binding both players' RetroPad buttons to the keys above."""
    out = {"input_enable_hotkey": "scroll_lock"}
    for player, keys in PAD_KEYS.items():
        for btn, ks in keys.items():
            out[f"input_player{player}_{btn}"] = _RA_KEYNAME.get(ks, ks)
    return out


class RetroArchAdapter(CommandAdapter):
    """RetroArch + libretro core, controlled through RetroArch's UDP network command interface.

    Linux: each session runs on its own Xvfb display (frames via x11grab, input via xdotool).
    Cores, core assets and BIOS are resolved automatically (provision.ensure_platform).
    Memory ops depend on the core exposing a memory map; failures come back as explicit errors.
    """
    name = "retroarch"
    supported = {"launch_game", "stop_game", "pause", "resume", "read_memory", "write_memory", "save_state",
                 "load_state", "step_frames", "query_runtime", "get_frame", "send_input", "stream_session", "rewind", "fast_forward"}

    def __init__(self, cfg: EmulatorConfig, config: Config | None = None, platform: str | None = None,
                 port: int | None = None, host: str = "127.0.0.1"):
        super().__init__(cfg)
        self.config, self.platform = config, platform
        if port is None:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
        self.addr, self.display, self.stream, self.log_path = (host, port), None, None, None
        self.rewind_on = (platform or "") not in NO_REWIND
        self.granularity = 15 if (platform or "") in COARSE_REWIND else 4
        self.trigger_hotkeys = self.rewind_on and (platform or "") not in TRIGGERS_USED   # L2 = rewind, R2 = fast-forward
        if HOST_OS == "windows":
            # local native play: the RetroArch window IS the display; real pads/keyboard go straight in, nothing to stream
            self.supported = self.supported - {"stream_session", "send_input", "get_frame"}

    def _write_cfg(self) -> Path:
        rt = self.config.runtime
        d = {k: rt / k for k in ("system", "saves", "states", "screenshots", "logs", "retroarch", "extract")}
        for p in d.values():
            p.mkdir(parents=True, exist_ok=True)
        cfg = d["retroarch"] / f"session-{self.addr[1]}.cfg"
        opts = {"system_directory": d["system"], "savefile_directory": d["saves"], "savestate_directory": d["states"],
                # cores that need a real file (Citra, PPSSPP...) get .zip/.7z content extracted here first
                "cache_directory": d["extract"],
                "screenshot_directory": d["screenshots"], "network_cmd_enable": "true", "network_cmd_port": self.addr[1],
                "config_save_on_exit": "false", "pause_nonactive": "false",
                # linux: fill the private Xvfb display exactly, so frames are never cropped; RetroArch letterboxes
                "video_fullscreen": "true" if HOST_OS == "linux" else "false", "video_windowed_fullscreen": "true",
                "video_driver": "gl", "audio_driver": "null" if HOST_OS == "linux" else "xaudio",
                "menu_driver": "rgui", "savestate_auto_index": "false", "video_vsync": "false",
                # no audio clock or vsync on a virtual display: pace emulation to the core's exact frame rate
                "vrr_runloop_enable": "true", "audio_sync": "false", "video_threaded": "false",
                "input_driver": "x" if HOST_OS == "linux" else "dinput", "libretro_log_level": "1",
                "core_options_path": d["retroarch"] / "core-options.cfg", "global_core_options": "true",
                "gamemode_enable": "false",          # GameMode needs a D-Bus session bus; services have none (abort -6)
                "suspend_screensaver_enable": "false", "video_font_enable": "false"}
        if self.rewind_on:
            opts.update({"rewind_enable": "true", "rewind_granularity": str(self.granularity),
                         "rewind_buffer_size": "1024" if self.granularity > 4 else "512", "rewind_buffer_size_step": "64"})
        if self.trigger_hotkeys:
            if HOST_OS == "windows":       # XInput LT = axis +4, RT = axis +5
                opts.update({"input_rewind_axis": "+4", "input_hold_fast_forward_axis": "+5"})
            else:                          # streamed: the pad's L2/R2 keys, sent together with the hotkey-enable key
                opts.update({"input_rewind": "e", "input_hold_fast_forward": "r"})
        opts["fastforward_ratio"] = "4.0"
        if HOST_OS == "windows":
            # native local play: vsync + real audio clock, XInput pads via RetroArch's built-in autoconfig, hotkeys on
            opts.update({"video_fullscreen": "false", "video_windowed_fullscreen": "true", "video_vsync": "true",
                         "vrr_runloop_enable": "false", "audio_sync": "true", "audio_driver": "xaudio",
                         "input_driver": "dinput", "input_joypad_driver": "xinput", "input_autodetect_enable": "true",
                         "video_window_save_positions": "false", "custom_viewport_width": "0",
                         "video_windowed_position_width": "1280", "video_windowed_position_height": "960",
                         # the window is embedded inside the G-Box app: no menu bar, no decorations, no companion UI
                         "ui_menubar_enable": "false", "video_window_show_decorations": "false",
                         "ui_companion_enable": "false", "ui_companion_start_on_boot": "false", "video_window_auto_width_max": "0"})
        else:
            opts |= _pad_binds()
        cfg.write_text("".join(f'{k} = "{v}"\n' for k, v in opts.items()))
        return cfg

    def _argv(self, rom: str) -> list[str]:
        core = self.cfg.core
        if self.config is not None:
            self._p(10, f"Resolving core {core or self.platform} (downloads on first use)")
            core = str(provision.ensure_platform(self.config, self.platform, self.cfg.core)[0])
            self._p(25, f"Core ready: {Path(core).name}")
        elif not core:
            raise ToolUnavailable("retroarch adapter needs 'core' configured")
        exe = self.cfg.executable or (provision.retroarch_exe(self.config) if self.config else "retroarch")
        cfg = self._write_cfg() if self.config is not None else None
        return [exe, *(["--config", str(cfg)] if cfg else []), "-L", core, "--verbose", *self.cfg.args, rom]

    def launch_game(self, rom: str) -> dict:
        argv = self._argv(rom)
        env = dict(os.environ)
        if HOST_OS == "linux":
            self.display = Display()
            env["DISPLAY"] = self.display.name
            # GPU: Xvfb alone renders on the CPU (Mesa llvmpipe). VirtualGL's EGL back end runs the core's OpenGL on
            # the NVIDIA GPU and hands finished frames to the private Xvfb display (verified: "NVIDIA GB10, GL 4.6").
            if Path(VGLRUN).exists():
                argv = [VGLRUN, "-d", "egl", *argv]
        logs = (self.config.runtime / "logs") if self.config else Path(tempfile.gettempdir())
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs / f"retroarch-{self.addr[1]}.log"
        self.proc = subprocess.Popen(argv, env=env, stdout=open(self.log_path, "wb"), stderr=subprocess.STDOUT)
        self._p(78, "Emulator process started" + (" on the GPU (VirtualGL)" if argv[0] == VGLRUN else ""))
        for i in range(150):                                   # wait for the command interface to answer
            if i % 5 == 0:
                tail = [ln for ln in self.log_tail(4000).splitlines() if ln.strip()]
                try:
                    self._p(80 + 18 * i / 150, tail[-1][:160] if tail else "Waiting for content to start")
                except Exception:                              # cancelled: don't leave an emulator running
                    self.stop_game()
                    raise
            if self.proc.poll() is not None:
                if self.display:
                    self.display.close()
                raise RuntimeError(f"retroarch exited {self.proc.returncode}: {self.log_tail()}")
            try:
                st = self.query_runtime(timeout=0.3)
                if st.get("state") in ("PLAYING", "PAUSED"):
                    return {"pid": self.proc.pid, "display": self.display and self.display.name, "port": self.addr[1],
                            "local_window": HOST_OS == "windows", "worker_name": __import__("platform").node(),
                            "core": argv[argv.index("-L") + 1], "status": st, "log": str(self.log_path),
                            "renderer": self.renderer()}
            except RuntimeError:
                pass
            time.sleep(0.2)
        tail = self.log_tail()
        self.stop_game()
        raise RuntimeError(f"retroarch started but content not running after 30s: {tail}")

    def _p(self, pct, msg):
        cb = getattr(self, "progress", None)
        if cb:
            cb(pct, msg)

    def renderer(self) -> str | None:
        """The GL renderer RetroArch actually got (evidence for GPU vs CPU rendering), from the session log."""
        for line in self.log_tail(200000).splitlines():
            if "[GL] Vendor:" in line or "Renderer:" in line:
                return line.split("]", 1)[-1].strip()[:120]
        return None

    def log_tail(self, n: int = 1500) -> str:
        try:
            return self.log_path.read_text(errors="replace")[-n:]
        except (OSError, AttributeError):
            return ""

    def stop_game(self) -> dict:
        if self.stream:
            self.stream.close()
        try:
            self.cmd("QUIT")
            self.proc and self.proc.wait(5)
        except Exception:
            pass
        _kill_tree(self.proc)
        if self.display:
            self.display.close()
        return {"returncode": self.proc.poll() if self.proc else None}

    def cmd(self, text: str, reply: bool = False, timeout: float = 2.0) -> str | None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(text.encode(), self.addr)
            if not reply:
                return None
            try:
                return s.recvfrom(65536)[0].decode().strip()
            except (TimeoutError, ConnectionResetError):
                raise RuntimeError(f"retroarch did not answer {text.split()[0]} on {self.addr}")

    def query_runtime(self, timeout: float = 2.0) -> dict:
        status = self.cmd("GET_STATUS", reply=True, timeout=timeout)     # "GET_STATUS PLAYING system,game,crc32=..."
        parts = status.split(" ", 2)
        return {"running": bool(self.proc and self.proc.poll() is None), "state": parts[1] if len(parts) > 1 else None,
                "content": parts[2] if len(parts) > 2 else None}

    def pause(self) -> dict:
        if self.query_runtime()["state"] != "PAUSED":
            self.cmd("PAUSE_TOGGLE")
        return self.query_runtime()

    def resume(self) -> dict:
        if self.query_runtime()["state"] == "PAUSED":
            self.cmd("PAUSE_TOGGLE")
        return self.query_runtime()

    def rewind(self, seconds: float = 5.0) -> dict:
        """Jump back in time through RetroArch's rewind buffer (one REWIND step per frame; each step = granularity frames)."""
        if not self.rewind_on:
            raise Unsupported(f"rewind is off for {self.platform} (snapshotting would cost frame rate)")
        steps = max(1, round(seconds * 60 / self.granularity))
        for _ in range(steps):
            self.cmd("REWIND")
            time.sleep(1 / 60)
        return {"rewound_s": seconds, "steps": steps}

    def fast_forward(self, on: bool | None = None) -> dict:
        """Toggle fast-forward (4x)."""
        self.cmd("FAST_FORWARD")
        return {"fast_forward": "toggled"}

    def step_frames(self, n: int = 1) -> dict:
        for _ in range(n):
            self.cmd("FRAMEADVANCE")
        return {"stepped": n}

    def save_state(self) -> dict:
        self.cmd("SAVE_STATE")
        return {"slot": "current"}

    def load_state(self) -> dict:
        self.cmd("LOAD_STATE")
        return {"slot": "current"}

    def get_frame(self) -> bytes:
        return grab_png(self.display.name if self.display else None)

    def stream_session(self) -> MjpegStream:
        if not self.stream:
            self.stream = MjpegStream(self.display.name if self.display else None,
                                      size=(self.display.w, self.display.h) if self.display else None)
        return self.stream

    def send_input(self, events: list[dict]) -> dict:
        """events: [{"key": "<pad button or X keysym>", "down": bool}] delivered to this session's display."""
        if HOST_OS != "linux" or not self.display:
            raise Unsupported("send_input needs a linux session display")
        args = []
        for ev in events:
            keys = PAD_KEYS.get(int(ev.get("player", 1)), PAD_KEYS[1])
            key = keys.get(ev["key"], ev["key"])              # pad button name, or a raw X keysym from a keyboard
            down = ev.get("down", True)
            if self.trigger_hotkeys and ev["key"] in ("l2", "r2") and int(ev.get("player", 1)) == 1:
                # L2 = rewind, R2 = fast-forward (held): hotkeys need the hotkey-enable key held with them
                args += (["keydown", "Scroll_Lock", "keydown", key] if down else ["keyup", key, "keyup", "Scroll_Lock"])
                continue
            args += ["keydown" if down else "keyup", key]
        if args:
            subprocess.run(["xdotool", *args], env={**os.environ, "DISPLAY": self.display.name}, timeout=5)
        return {"sent": len(events)}

    # Native address -> RetroAchievements RAM offset, for cores without a libretro memory map (Flycast, Dolphin):
    # (segment mask, segment value, offset mask): Dreamcast main RAM 0x0C000000 with P1/P2 mirrors 0x8C/0xAC000000
    # (verified with Flycast: rcheevos registers 16MB SYSTEM RAM at $0); GameCube/Wii MEM1 at 0x80000000/0xC0000000.
    RAM_WINDOWS = {"dreamcast": (0x1F000000, 0x0C000000, 0x00FFFFFF), "naomi": (0x1F000000, 0x0C000000, 0x00FFFFFF),
                   "gamecube": (0x3E000000, 0x00000000, 0x01FFFFFF), "wii": (0x3E000000, 0x00000000, 0x01FFFFFF),
                   "n64": (0x1F800000, 0x00000000, 0x007FFFFF)}

    def _ram_offset(self, address: int) -> int:
        w = self.RAM_WINDOWS.get(self.platform or "")
        if w and address > w[2] and (address & w[0]) == w[1]:   # native address -> offset into RAM
            return address & w[2]
        return address                                          # already a RAM offset

    def _read(self, verb: str, address: int, length: int) -> bytes | str:
        out = bytearray()
        for off in range(0, length, 256):                       # keep each reply well under UDP limits
            n = min(256, length - off)
            r = self.cmd(f"{verb} {address + off:x} {n}", reply=True).split()
            if len(r) < 3 or r[2] == "-1":
                return " ".join(r)
            out += bytes(int(b, 16) for b in r[2:])
        return bytes(out)

    def read_memory(self, address: int, length: int) -> bytes:
        """Core memory map first (native addresses); else the RAM view RetroArch exposes for achievements."""
        r = self._read("READ_CORE_MEMORY", address, length)
        if isinstance(r, bytes):
            return r
        r2 = self._read("READ_CORE_RAM", self._ram_offset(address), length)
        if isinstance(r2, bytes):
            return r2
        raise RuntimeError(f"memory read failed: {r} | {r2}")

    def write_memory(self, address: int, data: bytes) -> dict:
        hexs = " ".join(f"{b:02x}" for b in data)
        r = self.cmd(f"WRITE_CORE_MEMORY {address:x} {hexs}", reply=True).split()
        if len(r) >= 3 and r[2] != "-1":
            return {"written": int(r[2]), "via": "core_memory_map"}
        self.cmd(f"WRITE_CORE_RAM {self._ram_offset(address):x} {hexs}")    # no reply in RetroArch's protocol
        if self.read_memory(address, len(data)) != data:
            raise RuntimeError(f"memory write not confirmed by read-back ({' '.join(r)})")
        return {"written": len(data), "via": "core_ram", "verified": True}


class RocketLauncherAdapter(Adapter):
    """Windows node: launch any HyperSpin game through the drive's own RocketLauncher + bundled emulators."""
    name = "rocketlauncher"
    supported = {"launch_game", "stop_game", "query_runtime", "get_frame", "stream_session"}

    def __init__(self, root: Path):
        self.root, self.proc, self.stream = Path(root), None, None

    def launch_game(self, emulator: str, name: str) -> dict:
        exe = self.root / "RocketLauncher" / "RocketLauncher.exe"
        if HOST_OS != "windows" or not exe.exists():
            raise ToolUnavailable(f"RocketLauncher needs a Windows node with {exe}")
        self.proc = subprocess.Popen([str(exe), "-s", emulator, "-r", name, "-p", "AttractMode"], cwd=exe.parent)
        return {"pid": self.proc.pid, "emulator": emulator, "rom": name}

    def stop_game(self) -> dict:
        if self.stream:
            self.stream.close()
        _kill_tree(self.proc)
        return {"returncode": self.proc.poll() if self.proc else None}

    def query_runtime(self) -> dict:
        return {"running": bool(self.proc and self.proc.poll() is None)}

    def get_frame(self) -> bytes:
        return grab_png(None)

    def stream_session(self) -> MjpegStream:
        self.stream = self.stream or MjpegStream(None)
        return self.stream


class SteamAdapter(Adapter):
    """Launch installed Steam apps through the Steam client. No process control or introspection."""
    name = "steam"
    supported = {"launch_game"}

    def launch_game(self, appid: str) -> dict:
        url = f"steam://rungameid/{int(appid)}"
        if sys.platform == "win32":
            os.startfile(url)  # noqa: S606 — url built from an int
        else:
            subprocess.Popen(["xdg-open", url])
        return {"url": url}


def for_game(game: dict, config: Config) -> Adapter:
    """Pick the adapter for a catalog entry on THIS node."""
    plat = game["platform"]
    if plat == "pc_steam":
        return SteamAdapter()
    override = config.emulators.get(plat)
    if override and override.adapter == "command":
        return CommandAdapter(override)
    if HOST_OS == "windows" and game.get("launch", {}).get("kind") == "attract" and not game.get("core"):
        return RocketLauncherAdapter(config.library(game["library"]).root("windows"))   # no libretro core: drive's own emulators
    core = (override.core if override else None) or game.get("core")
    if not core:
        hint = " (runs on a Windows node via RocketLauncher)" if HOST_OS != "windows" else ""
        raise ToolUnavailable(f"no runtime for platform '{plat}' on {HOST_OS}: no libretro core mapped{hint}")
    return RetroArchAdapter(override or EmulatorConfig(core=core), config=config, platform=plat)


def for_platform(platform: str, config: Config) -> Adapter:
    """Back-compat: adapter by platform only (requires an explicit [emulators.<platform>] entry)."""
    if platform != "pc_steam" and platform not in config.emulators:
        raise ToolUnavailable(f"no emulator configured for platform '{platform}' (set [emulators.{platform}] in gbox.toml)")
    return for_game({"platform": platform, "launch": {}}, config)
