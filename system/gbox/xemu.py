"""Original Xbox titles that Cxbx-Reloaded cannot draw run in xemu (a low-level Xbox emulator) instead.

Jet Set Radio Future reaches 'Initializing Direct3D' in Cxbx and never presents a frame (#2412). xemu emulates
the console's hardware, so it needs the real system files: an MCPX boot ROM, a flash BIOS, an HDD image and an
EEPROM. Those come from the library's read-only emulator folder and are copied once into this worker's runtime.
Discs boot from an XISO image built with the same pinned XboxDev extract-xiso that xbox_disc.py uses.

Only titles in XEMU_TITLES (or every Xbox title, with [emulators.xbox] adapter = "xemu") take this path;
the rest keep Cxbx exactly as before (adapters.for_game).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import tomllib
import zipfile

from .config import HOST_OS, Config
from .registry import ToolUnavailable, Unsupported
from .xbox import XboxAdapter, _copy_missing, unpack_archive

_INSTALL_LOCK = threading.Lock()
_DISC_LOCK = threading.Lock()
# Pinned official release. The asset digest is the one GitHub publishes for it; the executable hash is that
# archive's xemu.exe, so a changed or self-updated binary is refused instead of silently trusted.
XEMU_TAG = "v0.8.136"
XEMU_ASSET = "xemu-0.8.136-windows-x86_64.zip"
XEMU_URL = f"https://github.com/xemu-project/xemu/releases/download/{XEMU_TAG}/{XEMU_ASSET}"
XEMU_SHA256 = "b25a6c24a2c2c36a0843a153cd9ee59ca6833ef87bdcd855ba0824930e4ddd1d"
XEMU_EXE_SHA256 = "7da537938ea2ac09f894186ba793c9ae51dff37c95903b0002273b8d363818b7"
ARCHIVE_MEMBERS = {"xemu.exe", "LICENSE.txt"}
MAX_DOWNLOAD = 64 * 1024**2

# Catalog game ids or normalized titles (title_key) that boot in xemu. Everything else stays on Cxbx.
XEMU_TITLES = frozenset({
    "bb6edc3dfcf32822",            # Jet Set Radio Future (USA): Cxbx renders it black (#2412)
    "jet set radio future",
})

# The library's emulator folder (QuickSwap2 Emulation/_emulation/XBOX(og) ISO). Read-only: files are copied out.
SYSTEM_FOLDER = ("_emulation", "XBOX(og) ISO")
FLASH_SIZES = (256 * 1024, 1024 * 1024)
# role -> (file name in the emulator folder, what it is for the error message)
SYSTEM_FILES = {
    "bootrom": ("mcpx_1.0.bin", "MCPX boot ROM"),
    "flashrom": ("xbox-3944_256k.bin", "retail flash BIOS"),
    "hdd": ("xbox_hdd.qcow2", "HDD image"),
}
EEPROM = "eeprom.bin"                       # xemu generates a fresh 256-byte EEPROM here when it is missing
# SDL3's default Win32 window class; xemu's single game window. Its message boxes are #32770 dialogs.
RENDER_CLASS = "SDL_app"


def title_key(value: str) -> str:
    """'Jet Set Radio Future (USA) [!].7z' -> 'jet set radio future' (region/dump tags and punctuation dropped)."""
    value = re.sub(r"\.(7z|zip|iso|xiso)$", "", str(value or "").strip(), flags=re.I)
    value = re.sub(r"[(\[][^)\]]*[)\]]", " ", value)
    return " ".join(re.sub(r"[^0-9a-z]+", " ", value.lower()).split())


def wants_xemu(game: dict, override=None) -> bool:
    """[emulators.xbox] adapter = "xemu"/"cxbx" decides for every title; otherwise the XEMU_TITLES allowlist."""
    choice = getattr(override, "adapter", None)
    if choice in ("xemu", "cxbx"):
        return choice == "xemu"
    if str(game.get("game_id") or "") in XEMU_TITLES:
        return True
    launch = game.get("launch") or {}
    names = (game.get("title"), game.get("name"),
             *(Path(str(p).replace("\\", "/")).name for p in (launch.get("rel_path"), game.get("rel_path")) if p))
    return any(title_key(name) in XEMU_TITLES for name in names if name)


def install_dir(config: Config) -> Path:
    return config.runtime / "xbox" / "xemu"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_xemu(home: Path, progress) -> None:
    """Pinned official build: exactly xemu.exe and its license; nothing else from the archive is written."""
    import httpx
    progress(15, f"Installing official xemu {XEMU_TAG} in this worker's local runtime")
    payload = bytearray()
    with httpx.stream("GET", XEMU_URL, timeout=180, follow_redirects=True) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            payload.extend(chunk)
            if len(payload) > MAX_DOWNLOAD:
                raise ToolUnavailable("xemu download exceeds its expected size")
    if hashlib.sha256(payload).hexdigest() != XEMU_SHA256:
        raise ToolUnavailable("Official xemu download checksum did not match the reviewed release")
    home.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xemu-install-", dir=home.parent) as temporary:
        stage = Path(temporary) / "runtime"
        stage.mkdir()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if {item.filename for item in entries} != ARCHIVE_MEMBERS or len(entries) != len(ARCHIVE_MEMBERS):
                raise ToolUnavailable("Official xemu archive has unexpected paths")
            for item in entries:
                if item.is_dir() or item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ToolUnavailable("Official xemu archive contains an unsupported member")
                (stage / item.filename).write_bytes(archive.read(item))
        if _sha(stage / "xemu.exe") != XEMU_EXE_SHA256:
            raise ToolUnavailable("xemu executable checksum did not match the pinned release")
        receipt = {"source": XEMU_URL, "tag": XEMU_TAG, "sha256": XEMU_SHA256, "at": time.time()}
        (stage / ".gbox-installed.json").write_text(json.dumps(receipt, indent=1), encoding="utf8")
        if home.exists():
            # System copies, saves (the HDD) and xemu.toml may already be here; keep every existing file.
            _copy_missing(stage, home)
        else:
            os.replace(stage, home)


def ensure_xemu(config: Config, progress=lambda *_: None) -> Path:
    if HOST_OS != "windows":
        raise ToolUnavailable("Original Xbox games run in xemu on a Windows worker")
    arch = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64")
    if arch.lower() not in ("amd64", "x86_64"):
        raise ToolUnavailable(f"The pinned xemu build is Windows x86_64; this worker is {arch}")
    home = install_dir(config)
    exe = home / "xemu.exe"
    with _INSTALL_LOCK:
        if not exe.exists():
            _download_xemu(home, progress)
        if not exe.is_file() or _sha(exe) != XEMU_EXE_SHA256:
            raise ToolUnavailable(f"xemu executable is not the pinned {XEMU_TAG} build: {exe}. "
                                  "Move it aside to reinstall; system files, saves and xemu.toml can remain.")
    return exe


def system_sources(config: Config) -> list[Path]:
    """Candidate read-only emulator folders: '_emulation/XBOX(og) ISO' at or above each configured library root."""
    found = []
    for library in config.libraries:
        root = library.root(HOST_OS)
        if not root:
            continue
        # A library inside '_emulation' (e.g. 'GC ISO') shares that folder; any other root may hold one directly.
        bases = [Path(*root.parts[:index]) for index, part in enumerate(root.parts)
                 if index and part.casefold() == SYSTEM_FOLDER[0].casefold()] or [root]
        for base in bases:
            folder = base.joinpath(*SYSTEM_FOLDER)
            if folder not in found:
                found.append(folder)
    return found


def _check_system_file(role: str, path: Path) -> str | None:
    """Why this file cannot be the given system file, or None."""
    size = path.stat().st_size
    if role == "bootrom" and size != 512:
        return f"{path.name} must be 512 bytes (MCPX boot ROM), found {size}"
    if role == "flashrom" and size not in FLASH_SIZES:
        return f"{path.name} must be 256 KiB or 1 MiB (flash BIOS), found {size}"
    if role == "hdd":
        with path.open("rb") as reader:
            if reader.read(4) != b"QFI\xfb":
                return f"{path.name} is not a qcow2 HDD image"
    if role == "eeprom" and size != 256:
        return f"{path.name} must be 256 bytes (Xbox EEPROM), found {size}"
    return None


def ensure_system(config: Config, home: Path, progress=lambda *_: None) -> dict[str, Path]:
    """This worker's own copies of the system files. Existing copies are never replaced: the HDD holds saves.

    The library share is only read. The HDD copy is writable and private to this worker (xemu locks it while
    running), so two workers never share one save disk."""
    target = home / "system"
    paths = {role: target / name for role, (name, _) in SYSTEM_FILES.items()}
    paths["eeprom"] = target / EEPROM
    missing = [role for role in SYSTEM_FILES if not paths[role].is_file()]
    sources = []
    if missing:
        # Only probe the network share when something is not installed yet.
        sources = [folder for folder in system_sources(config) if folder.is_dir()]
    for role in missing:
        name, what = SYSTEM_FILES[role]
        source = next((folder / name for folder in sources if (folder / name).is_file()), None)
        if source is None:
            looked = ", ".join(str(folder) for folder in system_sources(config)) or "no library roots are configured"
            raise ToolUnavailable(f"xemu needs {name} ({what}); it is not in the library's emulator folder "
                                  f"({looked}). Copy it to {paths[role]}")
        problem = _check_system_file(role, source)
        if problem:
            raise ToolUnavailable(f"xemu cannot use {source}: {problem}")
        progress(20, f"Copying the Xbox {what} to this worker")
        target.mkdir(parents=True, exist_ok=True)
        part = paths[role].with_name(paths[role].name + ".gbox-part")
        # copyfile, not copy2: the share's read-only attribute must not follow the writable HDD copy.
        shutil.copyfile(source, part)
        if part.stat().st_size != source.stat().st_size:
            part.unlink()
            raise ToolUnavailable(f"Copying {source} was incomplete")
        os.replace(part, paths[role])
    for role, path in paths.items():
        if path.is_file():
            problem = _check_system_file(role, path)
            if problem:
                raise ToolUnavailable(f"xemu cannot use this worker's {path}: {problem}. It was left intact.")
    return paths


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and not math.isfinite(value):
        return "nan" if math.isnan(value) else ("inf" if value > 0 else "-inf")
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        # JSON's escapes (\" \\ \n \uXXXX ...) are all valid TOML basic-string escapes.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise ValueError(f"Unsupported xemu.toml value: {value!r}")


def dump_toml(data: dict) -> str:
    """Write xemu's settings tree back: plain tables, arrays of tables (gamepad mappings, port forwards), scalars."""
    lines = []

    def is_tables(value):
        return isinstance(value, list) and value and all(isinstance(item, dict) for item in value)

    def table(path: list[str], values: dict, header: str | None):
        scalars = [(k, v) for k, v in values.items() if not isinstance(v, dict) and not is_tables(v)]
        if header and (scalars or not values):
            lines.extend(["", header])
        lines.extend(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in scalars)
        for key, value in values.items():
            name = ".".join(_toml_key(part) for part in path + [key])
            if isinstance(value, dict):
                table(path + [key], value, f"[{name}]")
            elif is_tables(value):
                for item in value:
                    lines.extend(["", f"[[{name}]]"])
                    table(path + [key], item, None)

    table([], data, None)
    return "\n".join(lines).strip() + "\n"


def _merge(base: dict, changes: dict) -> dict:
    out = dict(base)
    for key, value in changes.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def settings(files: dict[str, Path], disc: Path) -> dict:
    """The keys gBox owns in xemu.toml (names from xemu's config_spec.yml at XEMU_TAG)."""
    return {
        # show_welcome=true holds autostart and opens the first-boot window; updates would replace the pinned exe.
        "general": {"show_welcome": False, "skip_boot_anim": True, "updates": {"check": False}},
        "display": {
            "window": {"fullscreen_on_startup": False},     # windowed: gBox captures and docks the game window
            "ui": {"show_menubar": False, "show_notifications": False},   # no overlay over captured frames
        },
        # The window is parked off-screen without focus; SDL drops gamepad events of unfocused windows otherwise.
        "input": {"background_input_capture": True},
        "sys": {"files": {
            "bootrom_path": str(files["bootrom"]), "flashrom_path": str(files["flashrom"]),
            "eeprom_path": str(files["eeprom"]), "hdd_path": str(files["hdd"]), "dvd_path": str(disc),
        }},
    }


def write_config(home: Path, files: dict[str, Path], disc: Path) -> Path:
    """xemu.toml beside xemu.exe (its presence also selects xemu's portable mode). The operator's other keys,
    such as controller bindings set in xemu's own menu, are kept; only gBox's keys are rewritten."""
    path = home / "xemu.toml"
    current = {}
    if path.exists():
        try:
            current = tomllib.loads(path.read_text(encoding="utf8"))
        except (tomllib.TOMLDecodeError, UnicodeError) as error:
            raise ToolUnavailable(f"{path} is not valid TOML ({error}); fix or move it aside. It was left intact.") from error
    part = path.with_name(path.name + ".gbox-part")
    part.write_text(dump_toml(_merge(current, settings(files, disc))), encoding="utf8")
    os.replace(part, path)
    return path


def launch_args(exe: Path, config_path: Path, disc: Path) -> list[str]:
    # ui/xemu.c reads -config_path before loading settings; system/vl.c lets -dvd_path override sys.files.dvd_path.
    return [str(exe), "-config_path", str(config_path), "-dvd_path", str(disc)]


# --- Disc images -------------------------------------------------------------------------------------------------

def _receipt_ok(home: Path, key: str) -> bool:
    from . import xbox_disc
    marker, iso = home / "receipt.json", home / "game.iso"
    xbox_disc._plain(home)
    if {item.name for item in home.iterdir()} != {"receipt.json", "game.iso"} or marker.stat().st_size > 1024**2:
        return False
    try:
        receipt = json.loads(marker.read_text(encoding="utf8"))
        return (isinstance(receipt, dict) and receipt.get("format") == 1 and receipt.get("key") == key
                and receipt.get("extractor_sha256") == xbox_disc.EXE_SHA256 and receipt.get("size") == iso.stat().st_size
                and xbox_disc.layout(iso)["base"] == 0)
    except (ValueError, UnicodeError, Unsupported):
        return False


def _listing(tool: Path, image: Path) -> dict[str, int]:
    """{path: size} of every file in an Xbox disc image, from the pinned extractor's checked listing."""
    from . import xbox_disc
    output = xbox_disc._run([tool, "-m", "-l", image], limit=xbox_disc.MAX_LISTING, timeout=60)
    return xbox_disc.listing(output.decode("utf8", "strict"), image.stat().st_size)[0]


def _link_or_copy(source: Path, target: Path):
    """A hard link costs no space and leaves the source name untouched; another volume gets a copy."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def _publish(config: Config, key: str, need: int, source: dict, build, progress) -> Path:
    """Build an XISO in a private stage, check its listing against the source files, then publish it once.

    build(tool, work) -> (new image inside work, {path: size} it must list). Nothing outside work is written."""
    from . import xbox_disc
    root = (config.runtime / "xbox" / "xiso").absolute()
    xbox_disc._plain(root)
    home = root / ("xiso-" + key[:24])
    with _DISC_LOCK:
        if home.exists():
            if not _receipt_ok(home, key):
                raise ValueError(f"Existing xemu disc cache differs from its receipt; it was left intact: {home}")
            return home / "game.iso"
        tool = xbox_disc.ensure_extractor(config)
        root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(root).free < need + 64 * 1024**2:
            raise OSError("Not enough local disk space to prepare the Xbox disc image for xemu")
        with tempfile.TemporaryDirectory(prefix="xiso-stage-", dir=root) as temporary:
            work = Path(temporary)
            xbox_disc._plain(work)
            if not work.resolve().is_relative_to(root.resolve()):
                raise ValueError("xemu disc staging directory escaped its runtime")
            image, expected = build(tool, work)
            if not image.is_file():
                raise ValueError("XboxDev did not produce an XISO image")
            if xbox_disc.layout(image)["base"] != 0:
                raise ValueError("XboxDev output is not an XISO image")
            if _listing(tool, image) != expected:
                raise ValueError("The XISO built for xemu differs from its source disc files")
            publish = work / "publish"
            publish.mkdir()
            os.replace(image, publish / "game.iso")
            receipt = {"format": 1, "key": key, "extractor_sha256": xbox_disc.EXE_SHA256,
                       "size": (publish / "game.iso").stat().st_size, "source": source, "files": len(expected)}
            (publish / "receipt.json").write_text(json.dumps(receipt, sort_keys=True), encoding="utf8")
            os.replace(publish, home)
    progress(70, "Xbox disc image ready for xemu")
    return home / "game.iso"


def _from_folder(folder: Path, config: Config, progress) -> Path:
    """A DVD folder (default.xbe at its root) becomes an XISO with extract-xiso -c."""
    from . import xbox_disc
    folder = folder.absolute()
    progress(33, "Checking Xbox DVD files")
    files, directories = xbox_disc._inventory(folder)
    files.pop(".gbox-extracted.json", None)          # rom_archives' marker when default.xbe is at the archive root
    boots = [name for name in files if name.lower() == "default.xbe"]
    if len(boots) != 1:
        raise ValueError(f"Xbox DVD folder must contain one default.xbe: {folder}")
    with (folder / boots[0]).open("rb") as reader:
        if reader.read(4) != b"XBEH":
            raise ValueError(f"Not an Xbox XBE executable: {folder / boots[0]}")
    expected = {name: meta["size"] for name, meta in files.items()}
    # Keyed by every file's size and SHA-256, like xbox_disc.prepare keys its DVD cache by the image's SHA-256.
    key = hashlib.sha256(json.dumps({"create": files, "directories": sorted(directories)}, sort_keys=True).encode()).hexdigest()

    def build(tool, work):
        tree = folder
        if (folder / ".gbox-extracted.json").exists():
            # The disc must contain exactly its own files: stage a linked tree without gBox's marker.
            tree = work / "disc"
            for name in directories:
                (tree / name).mkdir(parents=True, exist_ok=True)
            for name in files:
                _link_or_copy(folder / name, tree / name)
        image = work / "game.iso"
        progress(40, "Building an Xbox disc image for xemu without changing game files")
        # -m: no .xbe media patching, so the image holds the game's exact bytes. -c <dir> <name> writes <name>.
        xbox_disc._run([tool, "-m", "-q", "-c", tree, image], limit=65536, timeout=1800,
                       progress=lambda: progress(42, "Building the Xbox disc image"))
        return image, expected

    return _publish(config, key, sum(expected.values()), {"kind": "folder", "path": str(folder)}, build, progress)


def _from_image(image: Path, config: Config, progress) -> Path:
    """An XISO boots as is; a full redump-style DVD image is rewritten (extract-xiso -r) into a cached XISO."""
    from . import xbox_disc
    image = image.absolute()
    descriptor = xbox_disc.layout(image)
    if descriptor["base"] == 0:
        return image
    progress(33, "Checking Xbox disc image content")
    before = image.stat()
    digest = xbox_disc._sha(image)
    key = hashlib.sha256(json.dumps({"rewrite": digest, "size": before.st_size}, sort_keys=True).encode()).hexdigest()

    def build(tool, work):
        # The listing also refuses unsafe names and requires one root default.xbe (Xbox 360 discs fail here).
        expected = _listing(tool, image)
        # -r renames its operand to <name>.old before rewriting: give it a private link, never the source name.
        operand, out = work / "in" / "source.iso", work / "out"
        out.mkdir()
        _link_or_copy(image, operand)
        progress(40, "Rewriting the Xbox DVD image as an XISO for xemu")
        xbox_disc._run([tool, "-m", "-q", "-r", "-d", out, operand], limit=65536, timeout=1800,
                       progress=lambda: progress(42, "Rewriting the Xbox disc image"))
        after = image.stat()
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise ValueError("Xbox source image changed during preparation")
        return out / "source.iso", expected

    # A copy (when no hard link is possible) plus the rewritten image.
    return _publish(config, key, 2 * before.st_size, {"kind": "image", "sha256": digest, "layout": descriptor},
                    build, progress)


def prepare_xiso(source: str | Path, config: Config, progress=lambda *_: None) -> Path:
    """The XISO xemu boots for a DVD folder, a default.xbe, an ISO/XISO, or a .7z/.zip holding one of them."""
    source = Path(source)
    if source.suffix.lower() in (".7z", ".zip"):
        source = unpack_archive(source, config, progress)
    if source.is_file() and source.name.lower() == "default.xbe":
        source = source.parent
    if source.is_dir():
        return _from_folder(source, config, progress)
    if source.suffix.lower() in (".iso", ".xiso"):
        return _from_image(source, config, progress)
    raise Unsupported("xemu needs a DVD folder/default.xbe, a recognized Xbox ISO/XISO, or its .7z/.zip archive. "
                      "Other image formats, including CHD, need conversion first.")


class XemuAdapter(XboxAdapter):
    """Same owned-process tracking, window checks and capture as Cxbx (xbox.XboxAdapter); xemu is one process.

    Input: xemu reads SDL gamepads itself (input.auto_bind puts the first one on port 1), like Cxbx reads XInput,
    so there is no send_input here either."""
    name = "xemu"
    label = "xemu"
    display_name = "xemu"
    render_class = RENDER_CLASS
    checkpoint_reason = "xemu snapshots need its QEMU monitor, which gBox does not drive yet"

    def launch_game(self, rom: str) -> dict:
        progress = getattr(self, "progress", lambda *_: None)
        exe = ensure_xemu(self.config, progress)
        files = ensure_system(self.config, exe.parent, progress)
        disc = prepare_xiso(rom, self.config, progress)
        # One active launch per worker; xemu rewrites xemu.toml itself when it exits.
        config_path = write_config(exe.parent, files, disc)
        # Without a parent console xemu writes stdout/stderr to xemu.log in its working directory.
        self.log_path = exe.parent / "xemu.log"
        self.output_path = exe.parent / "gbox-launch.log"
        self._output = self.output_path.open("wb")
        return self._boot(launch_args(exe, config_path, disc), exe.parent, disc, progress)

    def stop_game(self):
        """Ask xemu's window to close first so the qcow2 HDD (saves) is flushed, then end what is left."""
        from . import xbox
        live = self._live() if HOST_OS == "windows" and self.render_window else set()
        hwnd = self.render_window["hwnd"] if live else None
        # Only a window still owned by this launch's process identity gets the message.
        if hwnd and any(row["hwnd"] == hwnd for row in xbox.owned_windows(live, hwnd)):
            import ctypes
            from ctypes import wintypes as w
            user = ctypes.WinDLL("user32")              # private instance: argtypes here never affect other callers
            user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
            user.PostMessageW(hwnd, 0x0010, 0, 0)       # WM_CLOSE: SDL's quit request
            deadline = time.monotonic() + 5
            while self._live() and time.monotonic() < deadline:
                time.sleep(0.1)
        return super().stop_game()
