"""Original Xbox launches without RocketLauncher.

Xbox archives contain complete DVD folders or disc images, not Windows programs.
Cxbx-Reloaded boots their prepared default.xbe directly. Its portable installation and saves
are kept on this worker; the library's emulator, settings and game files are read-only.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile

from .config import HOST_OS, Config
from .registry import ToolUnavailable, Unsupported

_INSTALL_LOCK = threading.Lock()
# Upstream's standalone automation entry initializes Settings/EmuShared itself.
# The GUI additionally asks about retail signatures, including legitimate mods.
EXES = ("cxbxr-ldr.exe", "cxbx.exe")
CXBX_TAG = "CI-585c49a"
CXBX_URL = f"https://github.com/Cxbx-Reloaded/Cxbx-Reloaded/releases/download/{CXBX_TAG}/CxbxReloaded-Release.zip"
CXBX_SHA256 = "010d1e85bee9f82f05ae57ca483e7ae61fecba06c1637bf6b5a74ca09b03bf43"


def is_xbox_game(game: dict) -> bool:
    """Also recognize old catalog rows without confusing Xbox 360 or PS2 discs."""
    platform = game.get("platform")
    if platform == "xbox":
        return True
    if platform != "windows_native":
        return False
    launch = game.get("launch") or {}
    rel = str(launch.get("rel_path") or game.get("rel_path") or "").replace("\\", "/")
    folder = re.match(r"collections/([^/]+)(?:/|$)", rel, re.I)
    # The physical ROM collection outranks misleading virtual collection labels.
    if folder:
        return bool(re.fullmatch(r"(?:Microsoft\s+)?Xbox", folder.group(1), re.I))
    if Path(rel or str(launch.get("path") or "")).suffix.lower() == ".xbe":
        return True
    return any(re.fullmatch(r"(?:Microsoft\s+)?Xbox", str(value).strip(), re.I)
               for value in (game.get("system"), launch.get("emulator"), *(game.get("collections") or [])))


def install_dir(config: Config) -> Path:
    return config.runtime / "xbox" / "cxbx"


def _executable(home: Path) -> Path | None:
    return next((home / name for name in EXES if (home / name).is_file()), None)


def _copy_missing(source: Path, target: Path):
    """Never replace this worker's settings, EEPROM, saves or existing binaries."""
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_symlink():
            continue
        dst = target / item.name
        if item.is_dir():
            _copy_missing(item, dst)
        elif item.is_file() and not dst.exists():
            # A partial interrupted transfer must not count as an installed DLL.
            temp = dst.with_name(dst.name + ".gbox-part")
            shutil.copy2(item, temp)
            os.replace(temp, dst)


def _download_cxbx(config: Config, progress) -> Path:
    """Pinned official binary; never mix a newer loader with an older emulation DLL."""
    import httpx
    from .rom_archives import safe_name
    home = install_dir(config)
    progress(15, f"Installing official Cxbx-Reloaded {CXBX_TAG} in this worker's local runtime")
    response = httpx.get(CXBX_URL, timeout=180, follow_redirects=True)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != CXBX_SHA256:
        raise ToolUnavailable("Official Cxbx download checksum did not match the reviewed release")
    home.parent.mkdir(parents=True, exist_ok=True)
    import io
    with tempfile.TemporaryDirectory(prefix="cxbx-install-", dir=home.parent) as temporary:
        stage = Path(temporary) / "runtime"
        stage.mkdir()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for member in archive.infolist():
                name = safe_name(member.filename)
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ToolUnavailable("Official Cxbx archive contains a symbolic link")
                if member.is_dir():
                    continue
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as writer:
                    shutil.copyfileobj(source, writer)
        for name in ("cxbx.exe", "cxbxr-ldr.exe", "cxbxr-emu.dll", "SDL2.dll"):
            if not (stage / name).is_file():
                raise ToolUnavailable(f"Official Cxbx archive is incomplete: {name}")
        # A fresh profile uses reviewed defaults. Never import the collection's
        # unrelated save files, admin toggle, old paths or graphics workarounds.
        (stage / "settings.ini").write_text(DEFAULT_SETTINGS, encoding="utf8")
        receipt = {"source": CXBX_URL, "tag": CXBX_TAG, "sha256": CXBX_SHA256,
                   "at": time.time()}
        (stage / ".gbox-installed.json").write_text(json.dumps(receipt, indent=1), encoding="utf8")
        if home.exists():
            # A settings-only custom directory is valid; preserve every existing file.
            _copy_missing(stage, home)
        else:
            os.replace(stage, home)
    return home


DEFAULT_SETTINGS = """[gui]
DataStorageToggle = 0x1
[core]
AllowAdminPrivilege = false
[video]
FullScreen = false
MaintainAspect = true
RenderResolution = 1
[input-port-0]
Type = 0
DeviceName = XInput/0/Gamepad
ProfileName = "XBOX 360"
[input-profile-0]
Type = 0
ProfileName = "XBOX 360"
DeviceName = XInput/0/Gamepad
D Pad Up = Pad N
D Pad Down = Pad S
D Pad Left = Pad W
D Pad Right = Pad E
Start = Start
Back = Back
L Thumb = Thumb L
R Thumb = Thumb R
A = Button A
B = Button B
X = Button X
Y = Button Y
Black = Shoulder R
White = Shoulder L
L Trigger = Trigger L
R Trigger = Trigger R
Left Axis X+ = Left X+
Left Axis X- = Left X-
Left Axis Y+ = Left Y+
Left Axis Y- = Left Y-
Right Axis X+ = Right X+
Right Axis X- = Right X-
Right Axis Y+ = Right Y+
Right Axis Y- = Right Y-
Motor =
"""


def ensure_cxbx(config: Config, progress=lambda *_: None) -> Path:
    if HOST_OS != "windows":
        raise ToolUnavailable("Original Xbox games run in Cxbx-Reloaded on a Windows worker")
    if os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64").lower() not in ("amd64", "x86_64") \
            and not os.environ.get("PROCESSOR_ARCHITEW6432"):
        raise ToolUnavailable("Cxbx-Reloaded requires 64-bit Windows (its emulator uses WoW64)")
    home = install_dir(config)
    with _INSTALL_LOCK:
        if not _executable(home):
            # Refuse mixed old/new components in an interrupted custom install.
            if home.exists() and any(home.glob("*.dll")):
                raise ToolUnavailable(f"Cxbx installation has DLLs but no executable: {home}. "
                                      "Restore that complete build or move its binaries aside; settings and saves can remain.")
            _download_cxbx(config, progress)
        exe = _executable(home)
        if not exe or exe.stat().st_size < 1024:
            raise ToolUnavailable(f"Cxbx-Reloaded executable is incomplete: {home}")
        with exe.open("rb") as reader:
            if reader.read(2) != b"MZ":
                raise ToolUnavailable(f"Cxbx-Reloaded executable is not a Windows PE: {exe}")
        if not (home / "cxbxr-emu.dll").is_file():
            raise ToolUnavailable(f"Cxbx-Reloaded installation lacks cxbxr-emu.dll: {home}")
        if not (home / "settings.ini").exists():
            (home / "settings.ini").write_text(DEFAULT_SETTINGS, encoding="utf8")
    return exe


def _set_ini(path: Path, sections: dict[str, dict[str, str]]):
    """Edit only requested keys; Cxbx's repeated profile/history keys are meaningful."""
    source = path.read_text(encoding="utf8", errors="replace") if path.exists() else ""
    pending = {section.lower(): dict(values) for section, values in sections.items()}
    out, section = [], None

    def flush():
        if section in pending:
            out.extend(f"{key} = {value}" for key, value in pending.pop(section).items())

    for line in source.splitlines():
        match = re.match(r"\s*\[([^]]+)\]", line)
        if match:
            flush()
            section = match.group(1).lower()
        elif section in pending and "=" in line:
            key = line.split("=", 1)[0].strip()
            values = pending[section]
            if key in sections.get(section, {}):
                if key in values:
                    out.append(f"{key} = {values.pop(key)}")
                continue
        out.append(line)
    flush()
    for name, values in pending.items():
        out += ["", f"[{name}]"] + [f"{key} = {value}" for key, value in values.items()]
    path.write_text("\n".join(out) + "\n", encoding="utf8")


def prepare_xbe(source: str | Path, config: Config, progress=lambda *_: None) -> Path:
    from . import rom_archives
    source = Path(source)
    if source.is_dir():
        candidates = [p for p in source.iterdir() if p.is_file() and p.name.lower() == "default.xbe"]
        if len(candidates) != 1:
            raise ValueError(f"Xbox DVD folder must contain one default.xbe: {source}")
        source = candidates[0]
    elif source.suffix.lower() in (".7z", ".zip"):
        entries = rom_archives.members(source)
        choices = [e["name"] for e in entries if PurePosixPath(e["name"].replace("\\", "/")).name.lower() == "default.xbe"]
        images = [e["name"] for e in entries if PurePosixPath(e["name"].replace("\\", "/")).suffix.lower() in (".iso", ".xiso")]
        if len(choices) == 1:
            source = rom_archives.prepare(source, config, choices[0], progress)
        elif not choices and len(images) == 1:
            from .xbox_disc import validate_archive
            validate_archive(entries)
            source = rom_archives.prepare(source, config, images[0], progress)
        else:
            raise ValueError(f"Xbox archive must contain exactly one default.xbe or one DVD image: {source.name}")
    if source.suffix.lower() in (".iso", ".xiso"):
        from .xbox_disc import prepare
        source = prepare(source, config, progress)
    if source.suffix.lower() != ".xbe":
        raise Unsupported("This Xbox runtime needs a DVD folder/default.xbe, a recognized Xbox ISO/XISO, or its .7z/.zip archive. "
                          "Other image formats, including CHD, need conversion first.")
    with source.open("rb") as reader:
        if reader.read(4) != b"XBEH":
            raise ValueError(f"Not an Xbox XBE executable: {source}")
    return source


def dialog_controls(hwnd: int) -> list[dict]:
    """Read the body of this owned dialog, including cross-process Edit controls.

    GetWindowText alone returns only a remote dialog's caption. WM_GETTEXT with
    a short timeout obtains its actual explanation without hanging on a broken
    emulator. Do not click buttons or dismiss warnings on the operator's behalf.
    """
    import ctypes
    from ctypes import wintypes as w
    user = ctypes.windll.user32
    user.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user.SendMessageTimeoutW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM,
                                         w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    controls = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def each(control, _):
        if len(controls) >= 32:
            return False
        name = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(control, name, len(name))
        if name.value.lower() not in ("static", "edit", "button") and not name.value.lower().startswith("richedit"):
            return True
        text, result = ctypes.create_unicode_buffer(4096), ctypes.c_size_t()
        # SMTO_BLOCK | SMTO_ABORTIFHUNG, WM_GETTEXT. The destination is our buffer.
        ok = user.SendMessageTimeoutW(control, 0x000D, len(text), ctypes.addressof(text),
                                      0x3, 150, ctypes.byref(result))
        if not ok:
            user.GetWindowTextW(control, text, len(text))
        value = text.value.strip()
        if value:
            controls.append({"class": name.value, "text": value})
        return True
    user.EnumChildWindows(hwnd, each, 0)
    return controls


def owned_windows(pids: set[int], known_hwnd: int | None = None) -> list[dict]:
    """CxbxRender is the emulator's game window, distinct from its library GUI."""
    import ctypes
    from ctypes import wintypes as w
    user = ctypes.windll.user32
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.IsHungAppWindow.argtypes = [w.HWND]
    user.IsWindow.argtypes = [w.HWND]
    rows = []
    seen = set()

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def each(hwnd, _):
        if not user.IsWindow(hwnd):
            return True
        if int(hwnd) in seen:
            return True
        seen.add(int(hwnd))
        pid, rect = w.DWORD(), w.RECT()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        name, title = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(1024)
        user.GetClassNameW(hwnd, name, len(name))
        user.GetWindowTextW(hwnd, title, len(title))
        user.GetClientRect(hwnd, ctypes.byref(rect))
        row = {"pid": pid.value, "hwnd": int(hwnd), "class": name.value, "title": title.value,
               "width": rect.right - rect.left, "height": rect.bottom - rect.top,
               "hung": bool(user.IsHungAppWindow(hwnd))}
        if name.value == "#32770":
            row["controls"] = dialog_controls(int(hwnd))
            row["text"] = "\n".join(dict.fromkeys(control["text"] for control in row["controls"]))[:8000]
        rows.append(row)
        return True

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def top(hwnd, _):
        each(hwnd, 0)
        # The GUI fallback or a native host can parent the renderer before gBox
        # first sees it. Search child windows too, still filtering by owned PID.
        user.EnumChildWindows(hwnd, each, 0)
        return True
    user.EnumWindows(top, 0)
    # SetParent docks this renderer into Electron: it is no longer a top-level
    # window, but its previously verified HWND and process identity remain valid.
    if known_hwnd and not any(row["hwnd"] == known_hwnd for row in rows):
        each(known_hwnd, 0)
    return rows


class _OwnedProcess:
    """Process-like session lifetime follows the renderer, including Cxbx child reboots."""
    def __init__(self, owner):
        self.owner = owner

    @property
    def pid(self):
        return self.owner.render_pid or self.owner.launcher.pid

    @property
    def returncode(self):
        return self.poll()

    def poll(self):
        return None if self.owner._running() else (self.owner.launcher.poll() or 0)


class XboxAdapter:
    name = "cxbx"
    render_class = "CxbxRender"
    supported = {"launch_game", "stop_game", "query_runtime", "get_frame"}
    checkpoint_state = False
    checkpoint_reason = "Cxbx-Reloaded has no verified in-place save-state interface"

    def __init__(self, config: Config):
        self.config, self.proc, self.launcher = config, None, None
        self.render_pid, self.render_window, self._owned = None, None, {}
        self.ready = False
        self.log_path = None
        self._render_missing_since = None
        import threading
        self._capture_local = threading.local()

    def get_capabilities(self):
        from .adapters import OPS
        return {op: "supported" if op in self.supported else "unsupported" for op in OPS}

    def _live(self):
        import psutil
        if not self.launcher:
            return set()
        # Record descendant identities while the parent lives; never search by executable name.
        for pid, born in list(self._owned.items()):
            try:
                parent = psutil.Process(pid)
                if abs(parent.create_time() - born) > 0.01:
                    continue
                for child in parent.children(recursive=True):
                    self._owned.setdefault(child.pid, child.create_time())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        alive = set()
        for pid, born in self._owned.items():
            try:
                process = psutil.Process(pid)
                if abs(process.create_time() - born) < 0.01 and process.is_running() \
                        and process.status() != psutil.STATUS_ZOMBIE:
                    alive.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return alive

    def _running(self):
        live = self._live()
        if not self.ready:
            return bool(live)
        windows = owned_windows(live, self.render_window["hwnd"] if self.render_window else None)
        render = next((row for row in windows if row["class"] == self.render_class), None)
        if render:
            self.render_pid, self.render_window = render["pid"], render
            self._render_missing_since = None
            return True
        # Some titles reboot the emulated Xbox and create a replacement child.
        # Only an already validated game gets this brief handoff grace.
        if self._render_missing_since is None:
            self._render_missing_since = time.monotonic()
        return bool(live) and time.monotonic() - self._render_missing_since < 5

    def launch_game(self, rom: str) -> dict:
        import psutil
        from .adapters import capture_start, keep_offscreen
        progress = getattr(self, "progress", lambda *_: None)
        exe = ensure_cxbx(self.config, progress)
        xbe = prepare_xbe(rom, self.config, progress)
        self.log_path = exe.parent / "gbox-kernel.log"
        # One active launch per worker; do not rewrite settings of a running Cxbx instance.
        _set_ini(exe.parent / "settings.ini", {
            "core": {"KrnlDebugMode": "0x2", "KrnlDebugLogFile": str(self.log_path)},
            "video": {"FullScreen": "false", "MaintainAspect": "true"},
        })
        self.output_path = exe.parent / "gbox-launch.log"
        self._output = self.output_path.open("wb")
        if exe.name.lower() == "cxbxr-ldr.exe":
            # cxbxr-emu.cpp requires /load. CxbxKrnlSetupVerboseLog reads /dm
            # and /df from CLI (not Settings), so retain the real kernel log.
            args = [str(exe), "/load", str(xbe.resolve()), "/dm", "2", "/df", str(self.log_path.resolve())]
        else:
            args = [str(exe), str(xbe.resolve())]
        try:
            self.launcher = subprocess.Popen(args, cwd=exe.parent, stdout=self._output, stderr=subprocess.STDOUT,
                                             startupinfo=capture_start())
            try:
                self._owned = {self.launcher.pid: psutil.Process(self.launcher.pid).create_time()}
            except psutil.NoSuchProcess:
                raise RuntimeError(f"Cxbx exited immediately (exit {self.launcher.poll()}). {self.log_tail(3000)}") from None
            self.proc = _OwnedProcess(self)
            # Cxbx honors SW_SHOWDEFAULT for its render window. A minimized
            # startup yields a 0x0 client and can prevent the GPU from starting;
            # show without focus, parking it until the desktop docks it.
            keep_offscreen(self.launcher.pid)
            progress(76, "Waiting for the Xbox game's Cxbx render window")
            stable_since, stable_hwnd = None, None
            deadline = time.monotonic() + float(getattr(self, "boot_timeout_s", 90))
            while time.monotonic() < deadline:
                live = self._live()
                if not live:
                    raise RuntimeError(f"Cxbx exited before an Xbox render window opened (exit {self.launcher.poll()}). {self.log_tail(3000)}")
                windows = owned_windows(live)
                dialog = next((row for row in windows if row["class"] == "#32770"), None)
                if dialog:
                    explanation = dialog.get("text") or "\n".join(control.get("text", "") for control in dialog.get("controls", []))
                    raise RuntimeError(f"Cxbx displayed a startup dialog: {dialog['title']}. "
                                       f"{explanation}\n{self.log_tail(3000)}")
                render = next((row for row in windows if row["class"] == "CxbxRender" and not row["hung"]
                               and row["width"] >= 160 and row["height"] >= 120), None)
                if render:
                    if stable_hwnd != render["hwnd"]:
                        stable_hwnd, stable_since = render["hwnd"], time.monotonic()
                    if time.monotonic() - stable_since >= 3:
                        self.render_pid, self.render_window, self.ready = render["pid"], render, True
                        keep_offscreen(self.render_pid)
                        return {"pid": self.render_pid, "launch_pid": self.launcher.pid, "owned_pids": sorted(live),
                                "rom": str(xbe), "local_window": True, "worker_name": __import__("platform").node(),
                                "boot_validation": "CxbxRender window stable for 3 seconds; rendering and gameplay not verified",
                                "window_ready": True, "rendering_verified": False, "gameplay_verified": False,
                                "log": str(self.log_path)}
                else:
                    stable_since, stable_hwnd = None, None
                time.sleep(0.25)
            raise RuntimeError("Cxbx did not open a responsive Xbox game render window before the boot timeout. " + self.log_tail(3000))
        except Exception:
            self.stop_game()
            raise

    def log_tail(self, limit=60000):
        tails = []
        for path in (getattr(self, "output_path", None), self.log_path):
            if path and path.is_file():
                with path.open("rb") as reader:
                    reader.seek(max(0, path.stat().st_size - limit))
                    tails.append(reader.read().decode("utf8", "replace"))
        return "\n".join(tails)[-limit:]

    def query_runtime(self):
        running = self._running()
        return {"running": running, "pid": self.render_pid if running else None,
                "launch_pid": self.launcher.pid if self.launcher else None,
                "owned_pids": sorted(self._live()), "ready": running and self.ready,
                "window_ready": running and self.ready, "rendering_verified": False, "gameplay_verified": False}

    def stop_game(self):
        import psutil
        live = self._live()
        for pid in sorted(live, key=lambda value: value == (self.launcher.pid if self.launcher else None)):
            try:
                process = psutil.Process(pid)
                if abs(process.create_time() - self._owned[pid]) < 0.01:
                    process.terminate()
                    try:
                        process.wait(3)
                    except psutil.TimeoutExpired:
                        process.kill()
                        process.wait(5)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        self.ready = False
        if getattr(self, "_output", None):
            self._output.close()
        return {"stopped": not self._live(), "returncode": self.launcher.poll() if self.launcher else None}

    def frame_capture_state(self):
        state = getattr(vars(self).get("_capture_local"), "state", None)
        return dict(state) if state is not None else None

    def get_frame(self):
        from .cxbx_capture import capture_window
        import threading
        local = vars(self).setdefault("_capture_local", threading.local())
        local.state = {}
        if not self._running() or not self.render_window:
            raise RuntimeError("The Xbox game render window is not running")
        pid, hwnd = self.render_pid, self.render_window["hwnd"]
        born = self._owned.get(pid)
        if born is None or pid not in self._live():
            raise RuntimeError("The Xbox render process identity is unavailable")
        data, state = capture_window(hwnd, pid, render_class=self.render_class, source_prefix=self.name)
        # A reboot/replacement during capture cannot authorize an old image.
        if (not self.render_window or pid != self.render_pid or hwnd != self.render_window["hwnd"]
                or born != self._owned.get(pid) or pid not in self._live()):
            raise RuntimeError("The Xbox render process changed during capture")
        local.state = state
        return data

    def __getattr__(self, operation):
        from .adapters import OPS
        if operation in OPS:
            def unsupported(*args, **kwargs):
                raise Unsupported(f"Cxbx-Reloaded does not support {operation} in gBox")
            return unsupported
        raise AttributeError(operation)
