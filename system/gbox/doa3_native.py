"""Pinned DOA3 USA native runtime; local disc views keep saves out of ROM caches."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import threading
import time
import zipfile

from .config import HOST_OS
from .registry import ToolUnavailable
from .xbox import XboxAdapter, _OwnedProcess, is_xbox_game, owned_windows, prepare_xbe

GAME_ID = "b8edf7040116f3aa"
# Read-only catalog.scan(lib_id="quickswap-xbox", do_hash=False) identity.
# Its extracted XBE was independently checked against XBE_SHA256 before adding it.
QUICKSWAP_GAME_ID = "f03a801797a90506"
QUICKSWAP_LIBRARY = "quickswap-xbox"
QUICKSWAP_ROM = "Dead or Alive 3 (USA) (En,Ja).7z"
XBE_SHA256 = "e523dd15d0765899a43a1824c023e0219d129e9a8b41e8213e4e645755d2bfa3"
PATCHED_XBE_SHA256 = "80bc5611b8c288fc3e7b26cec2d4275c25d5b12a182d680e0dbe45a75326ad41"
PROGRAM_SHA256 = "73f9be4f86bc8a7ce024c38b6d907f6b129237d10aa049b246527e005ab7febc"
RELEASE_SHA256 = "be2c13b4dfeb8723184a46705abc10a4e55694b28fb77ee09a76cf0342ac956f"
# Reviewed private build from the authenticated local disc and generated source.
BUNDLE_SHA256 = "c035a06e3f64695dd8b5238049d31a796e5d3a2dcd1cc7e067213a3ead7eec02"
RUNNER_SHA256 = "bf6f88e433142973e5e94e804b3611c37144a911a5d53201ebc4717c9d1fad6f"
SDL_SHA256 = "1f98969319302a100931f4385e5918a0bd53ab07773040682d22e7edb54858c0"
CRT_SHA256 = {
    "msvcp140.dll": "9057d39b36b6c7d054865ee2bf9cde7a490fe3b01ec4e82514687e24f576269f",
    "vcruntime140.dll": "da72e6677bd1bcd01c453c1998aaa19aeaf6659f4774cf6848409da8232a95b2",
    "vcruntime140_1.dll": "26e470b29bed3d873e0c328186e53f95e9edbfe0b0fd0cda44743a0b1a04a828",
}
MEMBERS = {"runner.exe", "SDL3.dll", "LICENSE", "NOTICE", "build-receipt.json"} | CRT_SHA256.keys()
_LOCK = threading.Lock()
_MAX_BUNDLE = 64 * 1024 * 1024


def supports_game(game: dict) -> bool:
    return is_xbox_game(game) and (game.get("game_id") == GAME_ID or (
        game.get("game_id") == QUICKSWAP_GAME_ID and game.get("library") == QUICKSWAP_LIBRARY
        and game.get("rel_path") == QUICKSWAP_ROM))


def install_dir(config) -> Path:
    return (config.runtime / "xbox" / "doa3-native-v0.2").absolute()


def _plain_path(path: Path):
    """Reject symlink/junction traversal before resolving or opening a path."""
    path = path.absolute()
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ToolUnavailable(f"Native DOA3 refuses linked/reparse paths: {part}")


def _sha(path: Path) -> str:
    _plain_path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_receipt(home: Path):
    if {item.name for item in home.iterdir()} != MEMBERS:
        raise ToolUnavailable("Native DOA3 runtime is incomplete or has unexpected files")
    for name in MEMBERS:
        _plain_path(home / name)
        if not (home / name).is_file():
            raise ToolUnavailable(f"Native DOA3 runtime member is not a regular file: {name}")
    path = home / "build-receipt.json"
    _plain_path(path)
    if path.stat().st_size > 16384:
        raise ToolUnavailable("Native DOA3 build receipt is too large")
    try:
        receipt = json.loads(path.read_text(encoding="utf8"))
    except (ValueError, UnicodeError) as error:
        raise ToolUnavailable("Native DOA3 build receipt is invalid") from error
    expected = {"format": "gbox-doa3-native-build-v1", "upstream": "https://github.com/NoRain211/doa3-re",
                "release": "v0.2", "release_sha256": RELEASE_SHA256, "xbe_sha256": XBE_SHA256,
                "program_sha256": PROGRAM_SHA256, "runner_sha256": RUNNER_SHA256, "sdl_sha256": SDL_SHA256,
                "crt_sha256": CRT_SHA256}
    if not isinstance(receipt, dict) or any(receipt.get(key) != value for key, value in expected.items()):
        raise ToolUnavailable("Native DOA3 build receipt does not match the reviewed build")
    for name, digest in (("runner.exe", RUNNER_SHA256), ("SDL3.dll", SDL_SHA256), *CRT_SHA256.items()):
        if _sha(home / name) != digest:
            raise ToolUnavailable(f"Native DOA3 runtime checksum mismatch: {name}")
        with (home / name).open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ToolUnavailable(f"Native DOA3 runtime is not a Windows PE: {name}")
    for item in home.iterdir():
        _plain_path(item)
        if item.name not in MEMBERS:
            raise ToolUnavailable(f"Unexpected file in the pinned DOA3 runtime: {item.name}")


def _download(server: str, headers: dict) -> bytes:
    import httpx
    body = bytearray()
    with httpx.stream("GET", server.rstrip("/") + "/api/artifacts/" + BUNDLE_SHA256,
                      headers=headers, timeout=180, follow_redirects=False) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > _MAX_BUNDLE:
                raise ToolUnavailable("Native DOA3 runtime bundle exceeds its size limit")
    return bytes(body)


def ensure_runtime(config, server: str, headers: dict, progress=lambda *_: None) -> Path:
    if HOST_OS != "windows":
        raise ToolUnavailable("The DOA3 native runtime requires a Windows worker")
    if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (BUNDLE_SHA256, RUNNER_SHA256, SDL_SHA256, *CRT_SHA256.values())):
        raise ToolUnavailable("The reviewed DOA3 native build is not available yet")
    home = install_dir(config)
    with _LOCK:
        _plain_path(home)
        if home.exists():
            _check_receipt(home)
            return home / "runner.exe"
        if not server:
            raise ToolUnavailable("The DOA3 native build needs the configured Spark artifact server")
        progress(12, "Installing the verified DOA3 native runtime")
        payload = _download(server, headers)
        if len(payload) > _MAX_BUNDLE or hashlib.sha256(payload).hexdigest() != BUNDLE_SHA256:
            raise ToolUnavailable("Native DOA3 runtime bundle checksum mismatch")
        home.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="doa3-install-", dir=home.parent) as temporary:
            stage = Path(temporary) / "runtime"
            stage.mkdir()
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                entries = archive.infolist()
                if len(entries) != len(MEMBERS) or {entry.filename for entry in entries} != MEMBERS:
                    raise ToolUnavailable("Native DOA3 bundle has unexpected or duplicate paths")
                if sum(entry.file_size for entry in entries) > _MAX_BUNDLE:
                    raise ToolUnavailable("Native DOA3 extracted bundle exceeds its size limit")
                for entry in entries:
                    if entry.is_dir() or entry.flag_bits & 1 or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ToolUnavailable("Native DOA3 bundle contains an unsupported entry")
                    (stage / entry.filename).write_bytes(archive.read(entry))
            _check_receipt(stage)
            os.replace(stage, home)
    return home / "runner.exe"


def _original_xbe(path: Path) -> bytes:
    _plain_path(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ToolUnavailable("DOA3 executable exceeds its expected size")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest == XBE_SHA256:
        return data
    if digest != PATCHED_XBE_SHA256:
        raise ToolUnavailable("Native DOA3 supports only the verified USA executable; this XBE differs")
    candidate = bytearray(data)
    base, cert = struct.unpack_from("<I", candidate, 0x104)[0], struct.unpack_from("<I", candidate, 0x118)[0]
    offset = cert - base
    if offset < 0 or offset + 0xA4 > len(candidate) or struct.unpack_from("<II", candidate, offset + 0x9C) != (0x400001FF, 7):
        raise ToolUnavailable("DOA3 certificate differs from the verified media/region patch")
    struct.pack_into("<II", candidate, offset + 0x9C, 2, 1)
    if hashlib.sha256(candidate).hexdigest() != XBE_SHA256:
        raise ToolUnavailable("DOA3 private executable did not match the original USA checksum")
    return bytes(candidate)


def _disc_files(root: Path):
    _plain_path(root)
    files, seen = [], set()
    def walk_error(error):
        raise ToolUnavailable("Native DOA3 could not read its complete disc inventory") from error
    for folder, directories, names in os.walk(root, followlinks=False, onerror=walk_error):
        parent = Path(folder)
        for name in directories + names:
            _plain_path(parent / name)
        if parent == root:
            directories[:] = [name for name in directories if name.lower() != ".recomp-storage"]
            names = [name for name in names if name.lower() != ".recomp-storage"]
        for name in names:
            path = parent / name
            if not path.is_file():
                raise ToolUnavailable("Native DOA3 disc includes a non-regular file")
            relative = path.relative_to(root).as_posix()
            if relative.lower() in seen:
                raise ToolUnavailable("Native DOA3 disc contains case-colliding paths")
            seen.add(relative.lower())
            files.append((relative, path))
            if len(files) > 100000:
                raise ToolUnavailable("Native DOA3 disc contains too many files")
    return sorted(files)


def _changed_disc_files(source: Path, game_id: str, mod: str) -> set[str] | None:
    """Use a completed asset build's change list; unknown layouts keep private copies."""
    if not mod:
        return None
    marker = source.parent.parent / ".gbox-mod.json"
    _plain_path(marker)
    try:
        if marker.stat().st_size > 4 * 1024 * 1024:
            return None
        meta = json.loads(marker.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(meta, dict) or meta.get("game_id") != game_id
            or meta.get("image") != source.relative_to(marker.parent).as_posix()
            or not isinstance(meta.get("files"), list)):
        return None
    names = list(meta["files"])
    changes = meta.get("file_changes", [])
    if not isinstance(changes, list) or any(not isinstance(row, dict) for row in changes):
        return None
    names.extend(row.get("path") for row in changes)
    changed = set()
    for name in names:
        if not isinstance(name, str) or not name or any(c in name for c in "\\:\x00\r\n"):
            return None
        parts = name.split("/")
        if any(part in ("", ".", "..") for part in parts):
            return None
        # The DOA3 writer's files are disc-relative; file_changes are build-relative.
        changed.add(name.lower())
        if parts[0].lower() == source.parent.name.lower():
            changed.add("/".join(parts[1:]).lower())
    return changed


def play_root(config) -> Path:
    """runtime/xbox/doa3-native-play (the play-disc copy of each build, with its saves), never on a Windows system
    drive (gbox/storage_policy.py: moved under the cache, or refused when the cache is on it too)."""
    from . import storage_policy
    return storage_policy.game_dir(config, Path(config.runtime) / "xbox" / "doa3-native-play", "doa3-native-play")


def prepare_play_disc(source: Path, config, game: dict, progress=lambda *_: None) -> Path:
    """Share unchanged build assets, preserve saves, and reject mismatched disc views."""
    if not supports_game(game):
        raise ToolUnavailable("This native adapter is restricted to the owned DOA3 USA catalog title")
    source = source.absolute()
    original = _original_xbe(source)
    game_id = game["game_id"]  # supports_game restricts this to reviewed catalog identities.
    base_parent = (play_root(config) / game_id).absolute()
    mod = game.get('mod') or ''
    if not isinstance(mod, str) or len(mod) > 160 or any(c in mod for c in '\x00\r\n'):
        raise ToolUnavailable('Native DOA3 needs a bounded build identity')
    progress(35, "Checking the DOA3 disc and its persistent save folder")
    inventory = []
    for relative, path in _disc_files(source.parent):
        inventory.append({"name": "default.xbe" if path == source else relative,
                          "size": path.stat().st_size,
                          "sha256": XBE_SHA256 if path == source else _sha(path)})
    fingerprint = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
    # Original saves keep their existing path. Every asset build/revision gets
    # its own verified play view and native storage, without replacing a prior
    # build or importing the operator's personal saves into an exported mod.
    parent = (base_parent / 'builds' / hashlib.sha256(mod.encode('utf8')).hexdigest()[:24] / fingerprint[:24]
              if mod else base_parent)
    disc, marker = parent / 'disc', parent / 'disc-receipt.json'
    _plain_path(parent)
    with _LOCK:
        _plain_path(parent)
        if disc.exists() or marker.exists():
            _plain_path(marker)
            try:
                if marker.stat().st_size > 32 * 1024 * 1024:
                    raise ValueError("oversized disc receipt")
                receipt = json.loads(marker.read_text(encoding="utf8"))
            except (OSError, ValueError) as error:
                raise ToolUnavailable("Existing DOA3 play disc has no valid receipt; it was left intact") from error
            if not isinstance(receipt, dict) or receipt.get("format") != 1 or receipt.get("game_id") != game_id or receipt.get("fingerprint") != fingerprint or receipt.get('mod', '') != mod:
                raise ToolUnavailable("Existing DOA3 play disc differs from this source; its saves were left intact")
            actual = {name: path for name, path in _disc_files(disc)}
            if set(actual) != {item["name"] for item in inventory}:
                raise ToolUnavailable("Existing DOA3 play disc inventory differs; its saves were left intact")
            for item in inventory:
                if actual[item["name"]].stat().st_size != item["size"] or _sha(actual[item["name"]]) != item["sha256"]:
                    raise ToolUnavailable("Existing DOA3 play disc content differs; its saves were left intact")
            # Native save/cache writes must not traverse a junction inserted
            # inside persistent storage between sessions.
            if (disc / ".recomp-storage").exists():
                _disc_files(disc / ".recomp-storage")
            return disc / "default.xbe"
        parent.mkdir(parents=True, exist_ok=True)
        changed = _changed_disc_files(source, game_id, mod)
        with tempfile.TemporaryDirectory(prefix="disc-stage-", dir=parent) as temporary:
            stage = Path(temporary) / "disc"
            stage.mkdir()
            for item in inventory:
                target = stage / item["name"]
                target.parent.mkdir(parents=True, exist_ok=True)
                if item["name"] == "default.xbe":
                    target.write_bytes(original)
                else:
                    src = source.parent / item["name"]
                    _plain_path(src)
                    if changed is not None and item["name"].lower() not in changed:
                        # Disc assets are read-only to the runner; only .recomp-storage
                        # is writable. Keep rebuilt assets private so a later rebuild
                        # cannot change an older play view or its saved revision.
                        try:
                            os.link(src, target)
                        except OSError:  # Cross-volume caches and filesystems without links.
                            shutil.copy2(src, target)
                    else:
                        shutil.copy2(src, target)
                if _sha(target) != item["sha256"]:
                    raise ToolUnavailable("DOA3 disc changed while its private copy was being prepared")
            receipt = {"format": 1, "game_id": game_id, "mod": mod, "fingerprint": fingerprint, "files": inventory}
            receipt_path = Path(temporary) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf8")
            os.replace(stage, disc)
            os.replace(receipt_path, marker)
    return disc / "default.xbe"


class _ChannelMemory:
    """The virtual pad's memory: always this adapter's current channel (a closed one is replaced on the next call)."""
    def __init__(self, adapter):
        self.adapter = adapter

    def read(self, address, length):
        return self.adapter.channel().read(address, length)

    def write(self, address, data):
        return self.adapter.channel().write(address, data)


class Doa3NativeAdapter(XboxAdapter):
    name = "doa3_native"
    render_class = "DOAXBVRecompPresenterWindow"
    # send_input: gBox's virtual pad on the game's 4th port, in guest RAM (gbox/doa3_pad.py)
    supported = XboxAdapter.supported | {"read_memory", "write_memory", "query_memory_map", "send_input"}
    checkpoint_reason = "The DOA3 native runtime has no verified in-place save-state interface"

    def __init__(self, config, game):
        super().__init__(config)
        self.game = game
        self.boot_frame_paths = []
        self._guest_memory = None
        self._memory_source = None
        self._channel = None
        self._pad = None
        self._pad_lock = threading.Lock()

    def channel(self):
        """The fast verified guest-RAM channel (doa3_memory.Channel) of this session's runner: per-frame reads for a
        bot, writes only to the virtual pad's block (doa3_pad.BLOCK)."""
        from .doa3_pad import BLOCK
        if self._channel is None or self._channel.broken:
            if self._channel is not None:
                self._channel.close()                   # its process handle closed before a new one is opened
            self._channel = None
            self._channel = self._memory().channel(BLOCK)
        return self._channel

    def pad(self):
        """gBox's virtual controller on the game's 4th port (doa3_pad.VirtualPad)."""
        from .doa3_pad import VirtualPad
        if self._pad is None:
            self._pad = VirtualPad(_ChannelMemory(self))
        return self._pad

    def send_input(self, events: list[dict]) -> dict:
        """gBox pad names (RetroPad positions: b = Xbox A, a = B, y = X, x = Y; l / r = White / Black; l2 / r2 = the
        triggers) on gBox's virtual pad, port 4. The player's own controller and the keyboard (port 1) are untouched."""
        with self._pad_lock:
            return self.pad().apply(events)

    def _drop_pad(self):
        """Neutral pad, then the channel closed (stop / relaunch). The claim stays: no disconnect pause mid-fight."""
        try:
            if self._pad is not None and self._channel is not None and not self._channel.broken:
                self._pad.release()
        except Exception:                           # noqa: BLE001 - the runner may already be gone
            pass
        channel, self._pad, self._channel = self._channel, None, None
        if channel is not None:
            channel.close()

    def stop_game(self):
        self._drop_pad()
        return super().stop_game()

    def _memory(self):
        from .doa3_memory import GuestMemory
        from .registry import Unsupported
        if not self._running() or not self.ready or not self._memory_source:
            raise Unsupported("Native DOA3 guest memory needs this adapter's verified running session")
        if self._guest_memory is None:
            self._guest_memory = GuestMemory(self, install_dir(self.config) / "runner.exe", self._memory_source,
                                             RUNNER_SHA256, XBE_SHA256)
        return self._guest_memory

    def query_memory_map(self):
        return self._memory().memory_map()

    def read_memory(self, address, length):
        return self._memory().read(address, length)

    def write_memory(self, address, data):
        return self._memory().write(address, data)

    def regions(self):
        memory = self.query_memory_map()
        return [(row["address"], row["size"]) for row in memory["regions"]]

    def query_runtime(self):
        from .registry import Unsupported
        result = super().query_runtime()
        if result["running"]:
            try:
                result["guest_memory"] = self.query_memory_map()
            except (Unsupported, OSError, ValueError) as error:
                result["guest_memory"] = {"verified": False, "reason": str(error)}
        return result

    def _boot_frame(self, *, fresh=False):
        """Only this runner's bounded back-buffer dumps can prove native output."""
        from PIL import Image, ImageStat
        for path in reversed(self.boot_frame_paths):
            try:
                _plain_path(path)
                info = path.stat()
                if info.st_size > 64 * 1024 * 1024 or (fresh and time.time() - info.st_mtime > 3):
                    continue
                with Image.open(path) as image:
                    if image.format != "BMP" or not (160 <= image.width <= 4096 and 120 <= image.height <= 4096):
                        continue
                    rgb = image.convert("RGB")
                    extrema, luminance = rgb.getextrema(), ImageStat.Stat(rgb.convert("L"))
                    if max(high for _, high in extrema) <= 8 or max(high - low for low, high in extrema) <= 8 \
                            or luminance.mean[0] <= 1 or luminance.var[0] <= 1:
                        continue
                    result = io.BytesIO()
                    rgb.save(result, "PNG")
                    return path, result.getvalue()
            except (OSError, ValueError):
                # The renderer may still be writing this BMP. Retry on the next poll.
                continue
        return None

    def get_frame(self):
        from .adapters import win_grab
        if not self._running():
            raise RuntimeError("The DOA3 native game window is not running")
        frame = self._boot_frame(fresh=True)
        return frame[1] if frame else win_grab(self.render_pid)

    def launch_game(self, rom: str) -> dict:
        import psutil
        from .adapters import capture_start, keep_offscreen
        progress = getattr(self, "progress", lambda *_: None)
        exe = ensure_runtime(self.config, getattr(self, "api_server", ""), getattr(self, "api_headers", {}), progress)
        source = prepare_xbe(rom, self.config, progress)
        xbe = prepare_play_disc(source, self.config, self.game, progress)
        self._drop_pad()
        self._memory_source, self._guest_memory = xbe, None
        progress(65, "Launching the verified DOA3 native disc")
        logs = xbe.parent.parent / "logs"
        _plain_path(logs)
        logs.mkdir(exist_ok=True)
        launch_id = time.time_ns()
        self.log_path = logs / f"native-{launch_id}.log"
        self.output_path = None
        self._output = self.log_path.open("wb")
        frame_prefix = logs / f"boot-{launch_id}"
        self.boot_frame_paths = [Path(f"{frame_prefix}.{index:03d}.bmp") for index in range(12)]
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("RECOMP_")}
        env.update(RECOMP_D3D_SCALE="1", RECOMP_D3D_WIDESCREEN="0", RECOMP_AUDIO_GAIN="1")
        env.update(RECOMP_D3D_FRAME_DUMP=str(frame_prefix), RECOMP_D3D_FRAME_DUMP_COUNT="12",
                   RECOMP_D3D_FRAME_DUMP_AT="1", RECOMP_D3D_FRAME_DUMP_INTERVAL_MS="2000")
        try:
            self.launcher = subprocess.Popen([str(exe), "--xbe", str(xbe.resolve()), "--vsync"], cwd=exe.parent,
                env=env, stdout=self._output, stderr=subprocess.STDOUT, startupinfo=capture_start())
            try:
                self._owned = {self.launcher.pid: psutil.Process(self.launcher.pid).create_time()}
            except psutil.NoSuchProcess:
                raise RuntimeError("DOA3 native runtime exited immediately. " + self.log_tail(3000)) from None
            self.proc = _OwnedProcess(self)
            # Leave the SW_SHOWNOACTIVATE window drawable until real GPU output
            # is proven: DXGI can suppress presentation when fully off-screen.
            deadline = time.monotonic() + float(getattr(self, "boot_timeout_s", 90))
            stable_since, stable_hwnd = None, None
            progress(76, "Waiting for the DOA3 native game window")
            last_progress = time.monotonic()
            while time.monotonic() < deadline:
                if time.monotonic() - last_progress >= 2:
                    progress(78, "Waiting for visible DOA3 back-buffer content")
                    last_progress = time.monotonic()
                live = self._live()
                if not live:
                    raise RuntimeError("DOA3 native runtime exited before its game window opened. " + self.log_tail(3000))
                windows = owned_windows(live)
                dialog = next((row for row in windows if row["class"] == "#32770"), None)
                if dialog:
                    raise RuntimeError(f"DOA3 native startup dialog: {dialog['title']}. {dialog.get('text', '')}")
                render = next((row for row in windows if row["class"] == self.render_class and not row["hung"]
                               and row["width"] >= 160 and row["height"] >= 120), None)
                if render:
                    if render["hwnd"] != stable_hwnd:
                        stable_hwnd, stable_since = render["hwnd"], time.monotonic()
                    frame = self._boot_frame()
                    if time.monotonic() - stable_since >= 3 and frame:
                        progress(90, "Verified visible DOA3 native output")
                        self.render_pid, self.render_window, self.ready = render["pid"], render, True
                        keep_offscreen(self.render_pid)
                        return {"pid": self.render_pid, "launch_pid": self.launcher.pid, "owned_pids": sorted(live),
                                "rom": str(xbe), "local_window": True, "worker_name": __import__("platform").node(),
                                "boot_validation": "Owned native window and nonblack renderer back buffer; gameplay not verified",
                                "boot_frame": str(frame[0]), "boot_frames": [str(path) for path in self.boot_frame_paths],
                                "log": str(self.log_path)}
                else:
                    stable_since, stable_hwnd = None, None
                time.sleep(0.25)
            raise RuntimeError("DOA3 native runtime did not produce a responsive game window with visible back-buffer content. " + self.log_tail(3000))
        except Exception:
            try:
                self.stop_game()
            finally:
                # The retained Windows Popen handle identifies our child even
                # when psutil could not obtain its creation time. No PID search.
                if self.launcher and not self._owned and self.launcher.poll() is None:
                    self.launcher.terminate()
                    try:
                        self.launcher.wait(3)
                    except subprocess.TimeoutExpired:
                        self.launcher.kill()
                        self.launcher.wait(5)
            raise
