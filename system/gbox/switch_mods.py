"""Switch builds as LayeredFS overlays: a build is only the files it changes; the base NSP stays the only full copy.

Eden (and yuzu, which it continues) layers mod folders over a title's RomFS / ExeFS when the title boots. Read in Eden's
sources at v0.2.1 (the AppImage gBox runs, tag commit 58c1e20e) and master (26a03d24), 2026-10-26:

  * src/core/file_sys/bis_factory.cpp GetModificationLoadRoot: <data>/load/<title id as %016X>/. Updates (title ids
    with low 12 bits 0x800) get no load root: mods key on the base title id.
  * src/core/file_sys/patch_manager.cpp ApplyLayeredFS / PatchExeFS: every subfolder of that root is a mod, skipped
    when its name is in Settings::values.disabled_addons[title_id]; enabled mods' romfs/ (romfslite/, romfs_ext/) and
    exefs/ folders are layered over the game's own, folders sorted by name, the first layer holding a file wins
    (vfs_layered.cpp GetFileRelative), the game's RomFS last; CreateRomFS packs that once per boot.
    sdmc/atmosphere/contents/<TID> joins unless "SDMC" is disabled (gBox never adds that name).
  * src/frontend_common/config.cpp Read/SaveDisabledAddOnValues: the disabled names live in the global qt-config.ini,
    [DisabledAddOns], QSettings-style arrays: size=N, i\\title_id (decimal), i\\disabled\\size, i\\disabled\\j\\d, each value
    with an i\\...\\default=false twin (a missing twin reads as the default: title 0 / name ""). The per-game Add-Ons
    tab (src/yuzu/configuration/configure_per_game_addons.cpp) edits that same map, names = mod folder names, and drops
    <cache>/game_list/<TID>.pv.txt when it changes.
  * src/yuzu/main_window.cpp BootGame saves every setting from memory (config->SaveAllValues): Eden reads
    [DisabledAddOns] once, when it starts. gBox writes it while that Eden is down, right before starting it.
  * src/common/fs/fs.cpp IterateDirEntries follows symlinks (directory_entry::status): a linked folder is a mod.

So a Switch build is a folder in the mod collection, <cache>/mods/<game_id>/<build>/ (romfs/, exefs/, the .gbox-mod.json
marker with "layeredfs", .gbox-backup/<edit>/ holding what each edit replaced), linked into the emulator as
<load>/<TID>/<build> (a symlink; a junction on Windows; a small copy when no link can be made). Starting a build enables
its folder and disables the title's other gBox builds; the original game disables them all; a mod folder the operator
put there keeps the state they gave it (prepare_launch, called by the adapters while the emulator is down). Editing a build rewrites only the files named, in place; while a session
on this node runs that build the edit waits in .gbox-pending/ (node-local, never in the collection manifest) and lands
when the title restarts. An in-game swap is the edit plus one restart of the title in the same session
(SwitchLinuxAdapter.restart_title): Eden layers mods only at boot and has no save states, so the title boots again and
its own saves (NAND) stay. docs/switch-mods.md.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import stat as statmod
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from pydantic import BaseModel

from .models import Permission as P
from .registry import HOST_OS, tool

FORMAT = 1
MARKER = ".gbox-mod.json"
CONTAINERS = (".nsp", ".xci", ".nsz", ".xcz")
EDEN_DIRS = ("romfs", "romfslite", "romfs_ext", "exefs", "cheats", "manual_html")   # what the emulator reads in a mod
BACKUP, PENDING = ".gbox-backup", ".gbox-pending"
COPY_MARK = ".gbox-overlay.json"            # inside a copied (not linked) build in the emulator's load folder
SELECTION = "switch-overlays.json"          # node-local (runtime folder): the build each title was last started with
QUARANTINE = ".switch-full-copy."           # a converted full copy waits as <game>/.switch-full-copy.<build>.<stamp>
SECTION = "DisabledAddOns"
SPECIAL = set("!#$%^&*|;'\",<>?`~=")      # frontend_common/config.h special_characters: such values are written quoted
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")          # a new build: folder, Eden add-on and live-model safe
LINK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.~-]{0,159}")  # a launched folder may be a staged <build>~<key> copy
TID = re.compile(r"[0-9A-F]{16}")
HISTORY_MAX = 200                           # marker history rows kept (the backups of older edits stay on disk)


# --- the emulator's folders -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Emu:
    """One Switch emulator install as gBox drives it: where it looks for mods and keeps [DisabledAddOns]."""
    kind: str                     # eden (a Linux node, gBox's own) | yuzu (a Windows PC, its portable install)
    load: Path                    # <data>/load: one folder per base title id, one subfolder per mod
    config: Path                  # qt-config.ini
    cache: Path | None = None     # its cache folder: game_list/<TID>.pv.txt (the game list's add-on column)
    private: bool = True          # gBox may write its config and load folder (never a shared network install)
    why: str = ""                 # why not, when private is False

    def title_dir(self, title_id: str) -> Path:
        return self.load / title_id.upper()


def eden(cfg) -> Emu:
    """gBox's own Eden on a Linux node (provision.switch_linux_env points its XDG folders at the runtime folder)."""
    from . import provision
    return Emu("eden", provision.switch_linux_dir(cfg) / "load", provision.switch_linux_config(cfg),
               provision.switch_linux_home(cfg) / "cache" / "eden")


def yuzu(exe, cfg=None) -> Emu:
    """The portable Yuzu a Windows PC launches (user/ beside yuzu.exe). Private only as a local folder: a Yuzu on a
    network share serves every PC, and a link in its load folder would point at one PC's cache."""
    exe = Path(exe)
    user = exe.parent / "user"
    why = ""
    if str(exe).startswith(("\\\\", "//")):
        why = f"{exe.parent} is on a network share"
    elif not _local_drive(exe):
        why = f"{exe.parent} is not on a local drive"
    elif not user.is_dir():
        why = f"{exe.parent} has no portable user folder"
    return Emu("yuzu", user / "load", user / "config" / "qt-config.ini", user / "cache", not why, why)


def _local_drive(p: Path) -> bool:
    if os.name != "nt":
        return True
    import ctypes
    drive = os.path.splitdrive(os.path.abspath(p))[0]
    if not drive or drive.startswith(("\\\\", "//")):
        return False
    try:
        kind = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
    except (AttributeError, OSError):
        return False
    return kind in (2, 3)          # DRIVE_REMOVABLE, DRIVE_FIXED; 4 = DRIVE_REMOTE (a mapped share)


def local_emulators(cfg) -> list[Emu]:
    """The Switch emulator installs this node launches (for link cleanup when a build is deleted)."""
    if HOST_OS == "linux":
        return [eden(cfg)]
    if HOST_OS == "windows":
        try:
            from .adapters import YuzuAdapter
            return [yuzu(YuzuAdapter(cfg)._exe(), cfg)]
        except Exception:                                    # noqa: BLE001 - no Yuzu configured on this PC
            return []
    return []


def title_id_for(rom=None, serial=None) -> str | None:
    """The base title id LayeredFS keys on: the catalog serial when it is one, else the NSP's (ticket, cnmt.xml or a
    [TITLEID] tag in the file name). An update's id maps to its base: Eden gives updates no load root."""
    from . import switch_nsp
    tid = str(serial or "").strip().removeprefix("0x").removeprefix("0X").upper()
    if not TID.fullmatch(tid):
        tid = switch_nsp.title_id(rom) if rom else None
    return switch_nsp.base_title_id(tid) if tid else None


# --- [DisabledAddOns] in qt-config.ini (frontend_common/config.cpp) ----------------------------------------------------

def _read_text(path: Path) -> tuple[str, str, str]:
    """(text with \\n newlines and no BOM, the BOM it had, the newline it used)."""
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return "", "", "\n"
    bom = "﻿" if raw.startswith(b"\xef\xbb\xbf") else ""
    text = raw.decode("utf-8-sig", errors="replace")
    nl = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), bom, nl


def _sections(text: str) -> list[tuple[str | None, list[str]]]:
    """[(section name, its lines with the header first)] in file order; None = the lines before the first header."""
    out: list[tuple[str | None, list[str]]] = []
    name, cur = None, []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            out.append((name, cur))
            name, cur = s[1:-1].strip(), [line]
        else:
            cur.append(line)
    out.append((name, cur))
    return out


def _kv(lines: list[str]) -> dict[str, str]:
    out = {}
    for line in lines[1:]:
        s = line.strip()
        if not s or s[0] in ";#" or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _int(v) -> int:
    try:
        return int(str(v).strip().strip('"'))
    except (TypeError, ValueError):
        return 0


def _true(v) -> bool:
    return str(v or "").strip().strip('"').lower() in ("true", "1", "yes", "on")


def _quote(v: str) -> str:
    return f'"{v}"' if any(c in SPECIAL for c in v) else v           # AdjustOutputString


def parse_disabled(kv: dict[str, str]) -> dict[int, list[str]]:
    """[DisabledAddOns] keys -> {title id: [names]}, walked like ReadDisabledAddOnValues (size, i\\title_id,
    i\\disabled\\size, i\\disabled\\j\\d; quotes dropped as ReadStringSetting does). A value whose \\default twin says
    true reads as the default (title 0, name "") and is left out; a missing twin keeps the value (old QSettings yuzu)."""
    out: dict[int, list[str]] = {}
    for i in range(1, _int(kv.get("size")) + 1):
        key = f"{i}\\title_id"
        if key not in kv or _true(kv.get(key + "\\default")):
            continue
        names = []
        for j in range(1, _int(kv.get(f"{i}\\disabled\\size")) + 1):
            d = f"{i}\\disabled\\{j}\\d"
            if d in kv and not _true(kv.get(d + "\\default")):
                name = kv[d].replace('"', "")
                if name:
                    names.append(name)
        out[_int(kv[key])] = names                    # insert_or_assign: a later entry for the same title wins
    return out


def read_disabled(text: str) -> dict[int, list[str]]:
    table: dict[int, list[str]] = {}
    for name, lines in _sections(text):
        if name is not None and name.lower() == SECTION.lower():   # SimpleIni section names are case-insensitive
            table.update(parse_disabled(_kv(lines)))
    return table


def section_lines(table: dict[int, list[str]]) -> list[str]:
    """[DisabledAddOns] exactly as SaveDisabledAddOnValues writes it (titles in std::map order)."""
    lines = [f"[{SECTION}]"]
    for i, tid in enumerate(sorted(table), 1):
        lines += [f"{i}\\title_id\\default=false", f"{i}\\title_id={tid}"]
        for j, name in enumerate(table[tid], 1):
            lines += [f"{i}\\disabled\\{j}\\d\\default=false", f"{i}\\disabled\\{j}\\d={_quote(name)}"]
        lines.append(f"{i}\\disabled\\size={len(table[tid])}")
    lines.append(f"size={len(table)}")
    return lines


def write_disabled(text: str, table: dict[int, list[str]]) -> str:
    """text with its [DisabledAddOns] section(s) replaced by one holding `table`; every other line kept as it was."""
    out: list[str] = []
    placed = False
    for name, lines in _sections(text):
        if name is not None and name.lower() == SECTION.lower():
            if not placed:
                blank = 0
                while blank < len(lines) - 1 and not lines[len(lines) - 1 - blank].strip():
                    blank += 1                          # the blank separator (or final newline) the old section ended with
                out += section_lines(table) + [""] * blank
                placed = True
            continue
        out += lines
    if not placed:
        while out and not out[-1].strip():
            out.pop()
        if out:
            out.append("")
        out += section_lines(table) + [""]
    return "\n".join(out)


def set_title_disabled(emu: Emu, title_id: str, mods: Iterable[str], enabled: str | None) -> dict:
    """The title's disabled list: every mod folder in `mods` except `enabled`. Entries that are not mod folders here
    (Update, Update@<version>, Update (NAND), SDMC, cheat_* files, other titles) stay as the operator set them. Only
    call while that emulator is down: Eden reads the list when it starts and saves it again at BootGame."""
    text, bom, nl = _read_text(emu.config)
    table = read_disabled(text)
    tid = int(title_id, 16)
    mods = set(mods)
    old = list(table.get(tid, []))
    new = [n for n in old if n not in mods and n != enabled] + sorted(m for m in mods if m != enabled)
    changed = sorted(new) != sorted(old)
    if changed:
        table[tid] = new
        body = write_disabled(text, table)
        emu.config.parent.mkdir(parents=True, exist_ok=True)
        tmp = emu.config.with_name(emu.config.name + f".{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_bytes((bom + body.replace("\n", nl)).encode("utf-8"))
        os.replace(tmp, emu.config)
        if emu.cache is not None:                      # the per-game Add-Ons tab does the same when the list changes
            try:
                (emu.cache / "game_list" / f"{title_id.upper()}.pv.txt").unlink()
            except OSError:
                pass
    return {"title_id": title_id.upper(), "enabled": enabled, "disabled": new, "changed": changed,
            "config": str(emu.config)}


# --- the builds (the mod collection) --------------------------------------------------------------------------------------

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_SEQ = [0]


def _lock(folder) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(str(folder)))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _edit_id() -> str:
    with _LOCKS_GUARD:
        _SEQ[0] = (_SEQ[0] + 1) % 1000
        return f"e{int(time.time() * 1000):013d}-{_SEQ[0]:03d}"


def mods_root(cfg) -> Path:
    return Path(cfg.cache) / "mods"


def build_dir(cfg, game_id: str, name: str) -> Path:
    from . import filemods
    return filemods.mod_dir(cfg, game_id, name)


def read_meta(folder) -> dict:
    try:
        meta = json.loads((Path(folder) / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def is_overlay(meta) -> bool:
    lf = meta.get("layeredfs") if isinstance(meta, dict) else None
    return isinstance(lf, dict) and bool(TID.fullmatch(str(lf.get("title_id") or "")))


def overlay_of(cfg, game_id: str, folder_name: str) -> str | None:
    """The folder name when that build of the game is a LayeredFS overlay, else None (an older full-copy build boots its
    own image)."""
    if not folder_name:
        return None
    try:
        return folder_name if is_overlay(read_meta(build_dir(cfg, game_id, folder_name))) else None
    except ValueError:
        return None


def _write_meta(folder, meta: dict) -> None:
    p = Path(folder) / MARKER
    tmp = p.with_name(p.name + f".{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)


def _eden_dirs(folder: Path) -> list[str]:
    """The emulator-read folders this build has (as spelled on disk: Eden finds them case-insensitively)."""
    try:
        return sorted(e.name for e in os.scandir(folder) if e.is_dir() and e.name.lower() in EDEN_DIRS)
    except OSError:
        return []


def overlay_files(folder) -> list[dict]:
    """[{path, size}] of what the emulator sees in this build (romfs/..., exefs/...); markers, backups and pending
    edits are not part of it."""
    folder = Path(folder)
    out = []
    for d in _eden_dirs(folder):
        for p in sorted((folder / d).rglob("*")):
            if p.is_file() and not p.name.endswith((".part", ".tmp")):
                out.append({"path": p.relative_to(folder).as_posix(), "size": p.stat().st_size})
    return out


def pending_edits(folder) -> list[dict]:
    root = Path(folder) / PENDING
    out = []
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        try:
            out.append(json.loads((d / "edit.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _staged(folder: Path) -> bool:
    from . import filemods
    return filemods.STAGED_SEP in folder.name or (folder / filemods.STAGED_MARK).exists()


def builds_for(cfg, game_id: str, title_id: str | None = None) -> list[tuple[str, Path, dict]]:
    """(name, folder, marker) of the game's overlay builds on this node, for one title when given."""
    root = mods_root(cfg) / game_id
    out = []
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return out
    for e in entries:
        if e.name.startswith(".") or not e.is_dir(follow_symlinks=False):
            continue
        meta = read_meta(e.path)
        if is_overlay(meta) and (title_id is None or meta["layeredfs"]["title_id"] == title_id.upper()):
            out.append((e.name, Path(e.path), meta))
    return out


def default_build_name(game: dict) -> str:
    """The title's first overlay when the original game is selected and something is written: <title>_mods."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(game.get("title") or "").lower()).strip("_")[:60] or "switch"
    return f"{slug}_mods"


def new_meta(game_id: str, name: str, title_id: str, *, game_title: str = "", base: str = "", kind: str = "file",
             by: str = "") -> dict:
    from . import build_record
    now = time.time()
    meta = {"name": name, "game_id": game_id, "game_title": game_title, "title": name, "writer": "gbox.switch_mods",
            "built": now, "created": now, "platform": "switch",
            "layeredfs": {"format": FORMAT, "title_id": title_id.upper(), "base": base,
                          "load": f"load/{title_id.upper()}/{name}",
                          "note": "only the changed RomFS / ExeFS files; the base NSP is never copied"},
            "files": [], "file_changes": [], "history": [], **({"by": by} if by else {})}
    return build_record.stamp(meta, kind=kind if kind in build_record.KINDS else "file")


def create_build(cfg, game_id: str, name: str, title_id: str, *, game_title: str = "", base: str = "",
                 kind: str = "file", by: str = "") -> Path:
    """A new, empty overlay build (its marker only). An existing overlay of that name is returned as it is."""
    if not NAME.fullmatch(name or ""):
        raise ValueError(f"build name {name!r}: letters, digits, _ and - only (it names the emulator's mod folder)")
    if not TID.fullmatch(str(title_id or "").upper()):
        raise ValueError(f"title id {title_id!r}: 16 hex digits")
    folder = build_dir(cfg, game_id, name)
    with _lock(folder):
        meta = read_meta(folder)
        if is_overlay(meta):
            return folder
        if meta or (folder.exists() and any(folder.iterdir())):
            raise ValueError(f"{name} already exists as another kind of build of {game_id}: choose another name")
        from . import storage_policy                   # no build on a Windows system drive (operator 2026-10-26)
        storage_policy.require_off_system(cfg, folder, f"build {name}")
        folder.mkdir(parents=True, exist_ok=True)
        _write_meta(folder, new_meta(game_id, name, title_id, game_title=game_title, base=base, kind=kind, by=by))
    return folder


def norm_path(key: str) -> str:
    """'romfs/arc/x.arc' | 'exefs/main' | 'arc/x.arc' (a bare path is a RomFS path) -> the build-relative path."""
    p = str(key or "").replace("\\", "/").strip().strip("/")
    parts = p.split("/")
    if not p or ":" in p or "\0" in p or any(x in ("", ".", "..") for x in parts):
        raise ValueError(f"{key!r}: not a path inside the game's RomFS / ExeFS")
    if parts[0].lower() in EDEN_DIRS:
        parts[0] = parts[0].lower()
    else:
        parts = ["romfs", *parts]
    if len(parts) < 2 or any(x.startswith(".gbox") for x in parts):
        raise ValueError(f"{key!r}: names a folder or a gBox file, not a game file")
    return "/".join(parts)


def _base_file(romfs_base, path: str) -> Path:
    """The game's own file at a RomFS path, from an extracted RomFS of the title (gBox has no NCA decryption: the
    operator's Eden dump, File > Dump RomFS, lands in <data>/dump/<TID>/romfs)."""
    rel = norm_path(path)
    if not rel.startswith("romfs/"):
        raise ValueError(f"{path!r}: only RomFS files come from an extracted RomFS")
    if not romfs_base:
        raise ValueError(f"{path}: needs an extracted RomFS of the title (romfs_dir=..., or Eden's Dump RomFS in "
                         "<data>/dump/<TID>/romfs)")
    f = Path(romfs_base) / rel[len("romfs/"):]
    if not f.is_file():
        raise ValueError(f"{path}: not in the extracted RomFS {romfs_base}")
    return f


def _current(folder: Path, rel: str) -> Path | None:
    """The newest content of a build file: its latest pending copy, else the overlay's own file."""
    root = folder / PENDING
    for d in sorted(root.iterdir(), reverse=True) if root.is_dir() else []:
        f = d / "files" / rel
        if f.is_file():
            return f
    f = folder / rel
    return f if f.is_file() else None


def _content(folder: Path, rel: str, ch: dict, romfs_base):
    """The new bytes (or a file to copy) for one change."""
    if "from" in ch:
        p = Path(ch["from"])
        if not p.is_file():
            raise ValueError(f"{rel}: {p} is not a file")
        return p
    if "bytes" in ch:
        return bytes(ch["bytes"])
    if "b64" in ch:
        return base64.b64decode(ch["b64"], validate=True)
    if "romfs" in ch:
        return _base_file(romfs_base, ch["romfs"])
    if "patch" in ch:
        cur = _current(folder, rel) or _base_file(romfs_base, rel)
        data = bytearray(cur.read_bytes())
        for p in ch["patch"] or []:
            off, b = int(str(p["offset"]), 0), bytes.fromhex(p["hex"])
            if off < 0 or off + len(b) > len(data):
                raise ValueError(f"{rel}: patch at {off:#x} runs past the end of the file")
            data[off:off + len(b)] = b
        return bytes(data)
    raise ValueError(f"{rel}: a change is one of from, bytes, b64, romfs, patch, remove")


def _stage_edit(folder: Path, changes: dict, *, note: str = "", by: str = "", romfs_base=None) -> dict:
    """One edit into .gbox-pending/<edit>/ (files/ + edit.json); nothing of the build itself changes yet."""
    norm: dict[str, dict] = {}
    for key, ch in changes.items():
        rel = norm_path(key)
        if not isinstance(ch, dict):
            raise ValueError(f"{key}: each change is an object (from, bytes, b64, romfs, patch or remove)")
        if rel in norm:
            raise ValueError(f"{key}: named twice")
        norm[rel] = ch
    eid = _edit_id()
    stage = folder / PENDING / eid
    rows = []
    try:
        for rel, ch in norm.items():
            if ch.get("remove"):
                rows.append({"path": rel, "change": "removed"})
                continue
            got = _content(folder, rel, ch, romfs_base)
            dst = stage / "files" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(got, Path):
                shutil.copyfile(got, dst)
            else:
                dst.write_bytes(got)
            rows.append({"path": rel, "change": "patched" if "patch" in ch and not ({"from", "bytes", "b64"} & set(ch))
                         else "replaced", "size": dst.stat().st_size,
                         **({"from_romfs": norm_path(ch["romfs"])} if "romfs" in ch else {})})
        stage.mkdir(parents=True, exist_ok=True)
        edit = {"id": eid, "ts": time.time(), "by": by or "", "note": str(note or "")[:300], "files": rows,
                "state": "pending"}
        (stage / "edit.json").write_text(json.dumps(edit, indent=1), encoding="utf-8")
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return edit


def _prune_empty_dirs(folder: Path) -> None:
    """Empty folders go, the overlay's own romfs/ / exefs/ too: Eden takes an existing romfs/ as a layer and packs a
    new RomFS at every boot for it (patch_manager.cpp ApplyLayeredFS returns early only without layers)."""
    for d in _eden_dirs(folder):
        for p in sorted([*(folder / d).rglob("*"), folder / d], key=lambda q: -len(q.parts)):
            if p.is_dir():
                try:
                    p.rmdir()                        # only an empty one
                except OSError:
                    pass


def _refresh(folder: Path, meta: dict, history: list, kind: str | None) -> dict:
    from . import build_record
    files = overlay_files(folder)
    now = time.time()
    meta = dict(meta) | {"files": [f["path"] for f in files], "history": history[-HISTORY_MAX:], "built": now,
                         "edited": now}
    meta["file_changes"] = [build_record.file_change(f["path"], "replaced", f["size"], what="LayeredFS overlay file")
                            for f in files][:build_record.MAX_ROWS]
    if kind in build_record.KINDS:
        meta["kind"] = kind
    return meta


def apply_pending(folder, *, kind: str | None = None) -> dict:
    """Land the pending edits of a build, oldest first, while no emulator uses it: each file the build had moves to
    .gbox-backup/<edit>/ (the marker's history names it), the new one takes its place; a removal moves the overlay
    file to the backup, so the game's own file shows again. Re-running after a crash finishes the job."""
    folder = Path(folder)
    with _lock(folder):
        pend = folder / PENDING
        meta = read_meta(folder)
        edits = sorted(d for d in pend.iterdir() if d.is_dir()) if pend.is_dir() else []
        applied: list[str] = []
        history = list(meta.get("history") or [])
        for d in edits:
            try:
                edit = json.loads((d / "edit.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue                             # half staged (a crash while staging): left for inspection
            rows = []
            for f in edit.get("files") or []:
                rel = f["path"]
                dst, new, bak = folder / rel, d / "files" / rel, folder / BACKUP / edit["id"] / rel
                landed = f.get("change") != "removed" and not new.is_file()   # a re-run after a crash: already in place
                had = bak.is_file() or (dst.is_file() and not landed)
                if dst.is_file() and not bak.exists() and not landed:
                    bak.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(dst, bak)
                if f.get("change") == "removed":
                    change = "removed" if had else "unchanged"
                else:
                    if new.is_file():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(new, dst)
                    change = "patched" if f.get("change") == "patched" else ("replaced" if had else "new")
                rows.append({"path": rel, "change": change, "was": "overlay" if had else "base",
                             **({"backup": bak.relative_to(folder).as_posix()} if bak.is_file() else {}),
                             **({"size": dst.stat().st_size} if dst.is_file() else {}),
                             **({"from_romfs": f["from_romfs"]} if f.get("from_romfs") else {})})
            history.append({"id": edit["id"], "ts": edit.get("ts"), "applied": time.time(), "by": edit.get("by") or "",
                            "note": edit.get("note") or "", "files": rows})
            shutil.rmtree(d, ignore_errors=True)
            applied.append(edit["id"])
        try:
            pend.rmdir()
        except OSError:
            pass
        if applied:
            _prune_empty_dirs(folder)
            meta = _refresh(folder, meta, history, kind)
            _write_meta(folder, meta)
        elif kind and meta.get("kind") != kind:
            _write_meta(folder, meta | {"kind": kind})
        return {"applied": applied, "overlay": summary(folder, meta)}


def summary(folder, meta: dict | None = None) -> dict:
    folder = Path(folder)
    meta = read_meta(folder) if meta is None else meta
    files = overlay_files(folder)
    return {"build": folder.name, "title_id": (meta.get("layeredfs") or {}).get("title_id"), "files": len(files),
            "bytes": sum(f["size"] for f in files), "pending": [e.get("id") for e in pending_edits(folder)],
            "edits": len(meta.get("history") or []), "kind": meta.get("kind")}


def write_files(cfg, game_id: str, name: str, changes: dict, *, in_use: bool = False, note: str = "", by: str = "",
                romfs_base=None, create: dict | None = None, kind: str | None = None) -> dict:
    """Rewrite only the named files of overlay build `name`, in place: never a copy of the game or of the build.
    changes: {RomFS / ExeFS path: {"from": file} | {"bytes": raw} | {"b64": text} | {"romfs": another RomFS path of
    the game, from an extracted RomFS} | {"patch": [{"offset", "hex"}]} | {"remove": true}}. The edit is staged in
    .gbox-pending/ and, unless a running session on this node uses the build (in_use), lands at once (apply_pending);
    in use, it lands when the title restarts. create: {title_id, game_title, base, kind} makes the build first when
    it does not exist yet."""
    if not changes:
        raise ValueError("no changes to write")
    folder = build_dir(cfg, game_id, name)
    with _lock(folder):
        meta = read_meta(folder)
        if not is_overlay(meta):
            if meta or create is None:
                raise ValueError(f"{name} is not a Switch LayeredFS build of {game_id}")
            create_build(cfg, game_id, name, by=by, **create)
        edit = _stage_edit(folder, changes, note=note, by=by, romfs_base=romfs_base)
        out = {"mod": name, "dir": str(folder), "edit": edit["id"], "files": [f["path"] for f in edit["files"]]}
        if in_use:
            return out | {"pending": True, "applied": [], "overlay": summary(folder)}
        res = apply_pending(folder, kind=kind)
        return out | {"pending": False, "applied": res["applied"], "overlay": res["overlay"]}


def revert(cfg, game_id: str, name: str, edit: str = "last", paths: Iterable[str] = (), *, in_use: bool = False,
           by: str = "") -> dict:
    """Undo one applied edit (the last one by default), for some of its files when `paths` name them: each file goes
    back to the copy the edit kept in .gbox-backup, or out of the overlay when it came from the game itself. The undo
    is an edit of its own (with its own backups), so it can be undone too."""
    folder = build_dir(cfg, game_id, name)
    meta = read_meta(folder)
    if not is_overlay(meta):
        raise ValueError(f"{name} is not a Switch LayeredFS build of {game_id}")
    history = list(meta.get("history") or [])
    target = (history[-1] if history else None) if edit in ("", "last") else \
        next((h for h in history if h.get("id") == edit), None)
    if not target:
        raise ValueError(f"no edit {edit!r} in {name}")
    want = {norm_path(p) for p in paths}
    changes, skipped = {}, []
    for f in target.get("files") or []:
        if (want and f["path"] not in want) or f.get("change") == "unchanged":
            continue
        if f.get("backup") and (folder / f["backup"]).is_file():
            changes[f["path"]] = {"from": str(folder / f["backup"])}
        elif f.get("was") == "base":
            changes[f["path"]] = {"remove": True}
        else:
            skipped.append(f["path"])
    if not changes:
        raise ValueError(f"nothing to revert in {target['id']}" + (f" (no backup for {', '.join(skipped)})" if skipped else ""))
    out = write_files(cfg, game_id, name, changes, in_use=in_use, note=f"revert {target['id']}", by=by)
    return out | {"reverted": target["id"], **({"skipped": skipped} if skipped else {})}


def copy_build(cfg, game_id: str, src: str, dst: str, *, by: str = "") -> dict:
    """An explicit new build: only the overlay's own folders (romfs/, exefs/, ...) are copied, KB to MB, never the
    game; its history starts fresh (the backups and pending edits of the source stay with the source)."""
    if not NAME.fullmatch(dst or ""):
        raise ValueError(f"build name {dst!r}: letters, digits, _ and - only")
    s = build_dir(cfg, game_id, src)
    meta = read_meta(s)
    if not is_overlay(meta):
        raise ValueError(f"{src} is not a Switch LayeredFS build of {game_id}")
    d = build_dir(cfg, game_id, dst)
    if d.exists():
        raise ValueError(f"{dst} already exists")
    from . import storage_policy                       # no build on a Windows system drive (operator 2026-10-26)
    storage_policy.require_off_system(cfg, d, f"build {dst}")
    tmp = d.with_name(f".{dst}.tmp-{uuid.uuid4().hex[:8]}")
    tmp.mkdir(parents=True)
    try:
        with _lock(s):
            for name in _eden_dirs(s):
                shutil.copytree(s / name, tmp / name)
        now = time.time()
        drop = ("verified", "verified_in_game", "gameplay_verified", "job_id", "build_call", "edited", "copied_from",
                "converted_from")
        new = {k: v for k, v in meta.items() if k not in drop} | {
            "name": dst, "title": dst, "created": now, "copied_from": {"build": src, "ts": now},
            "layeredfs": dict(meta["layeredfs"]) | {"load": f"load/{meta['layeredfs']['title_id']}/{dst}"}}
        new = _refresh(tmp, new, [{"id": _edit_id(), "ts": now, "applied": now, "by": by, "note": f"copied from {src}",
                                   "files": []}], None)
        _write_meta(tmp, new)
        os.replace(tmp, d)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    files = overlay_files(d)
    return {"mod": dst, "from": src, "dir": str(d), "files": len(files), "bytes": sum(f["size"] for f in files),
            "pending_left_in_source": [e.get("id") for e in pending_edits(s)]}


# --- the emulator's view: links and the selection ------------------------------------------------------------------------

def _linked(p: Path) -> bool:
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return statmod.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)   # symlink | junction


def _link_text(p: Path) -> str | None:
    try:
        t = str(os.readlink(p))
    except (OSError, ValueError):
        return None
    return t[4:] if t.startswith("\\\\?\\") else t


def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _under(path, root) -> bool:
    a, b = _norm(path), _norm(root).rstrip("\\/")
    return a == b or a.startswith(b + os.sep)


def _ours(cfg, p: Path) -> bool:
    """A load-folder entry gBox made: a link into the mod collection, or a copy carrying COPY_MARK."""
    if _linked(p):
        root = mods_root(cfg)
        roots = [root, Path(os.path.realpath(root))]
        cands = [c for c in (_link_text(p), os.path.realpath(p)) if c]
        return any(_under(c, r) for c in cands for r in roots)
    return p.is_dir() and (p / COPY_MARK).is_file()


def _unlink(p: Path) -> None:
    if os.name == "nt":
        try:
            os.rmdir(p)                              # a junction or a directory symlink (never its target)
            return
        except OSError:
            pass
    os.unlink(p)


def _make_link(target: Path, link: Path) -> None:
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))      # no privilege needed, unlike a symlink
            return
        except (ImportError, AttributeError, OSError):
            pass
    os.symlink(target, link, target_is_directory=True)


def _copy_overlay(folder: Path, dst: Path) -> None:
    dst.mkdir(parents=True)
    for name in _eden_dirs(folder):
        shutil.copytree(folder / name, dst / name)
    (dst / COPY_MARK).write_text(json.dumps({"source": str(folder), "synced": time.time()}), encoding="utf-8")


def link_build(cfg, emu: Emu, title_id: str, folder: Path) -> dict:
    """<load>/<TID>/<build> -> the build folder: a symlink (a junction on Windows), else a copy of its emulator
    folders (rebuilt at each start). Only an entry gBox made is replaced; a foreign folder of that name is refused."""
    folder = Path(folder)
    tdir = emu.title_dir(title_id)
    tdir.mkdir(parents=True, exist_ok=True)
    p = tdir / folder.name
    if _linked(p):
        if _link_text(p) is not None and _norm(_link_text(p)) == _norm(folder) and p.is_dir():
            return {"mode": "link", "path": str(p), "target": str(folder)}
        if not _ours(cfg, p):
            raise ValueError(f"{p} is a link gBox did not make: rename or remove it first")
        _unlink(p)
    elif p.is_dir():
        if not (p / COPY_MARK).is_file():
            raise ValueError(f"{p} is a mod folder gBox did not make: rename or move it first")
        shutil.rmtree(p)                             # gBox's own copy (a few KB-MB): made again below
    elif p.exists():
        raise ValueError(f"{p} is a file, not a mod folder")
    try:
        _make_link(folder, p)
        mode = "link"
    except OSError:
        _copy_overlay(folder, p)
        mode = "copy"
    return {"mode": mode, "path": str(p), "target": str(folder)}


def sync_title(cfg, emu: Emu, game_id: str, title_id: str, launched: str | None = None) -> dict:
    """The title's load folder lists the game's overlay builds on this node (a staged <build>~<key> copy only while it
    is the one launched); entries gBox made whose build is gone are removed. Foreign folders are never touched."""
    tdir = emu.title_dir(title_id)
    modes: dict[str, str] = {}
    for name, folder, _ in builds_for(cfg, game_id, title_id):
        if name == launched or not _staged(folder):
            modes[name] = link_build(cfg, emu, title_id, folder)["mode"]
    pruned, foreign = [], []
    for e in sorted(tdir.iterdir()) if tdir.is_dir() else []:
        if e.name in modes:
            continue
        if _linked(e):
            if not _ours(cfg, e):
                foreign.append(e.name)
            elif not e.is_dir() or _staged(Path(os.path.realpath(e))):   # its build is gone / a staged copy not in use
                _unlink(e)
                pruned.append(e.name)
        elif e.is_dir():
            mark = e / COPY_MARK
            if not mark.is_file():
                foreign.append(e.name)
                continue
            try:
                src = json.loads(mark.read_text(encoding="utf-8")).get("source")
            except (OSError, ValueError):
                src = None
            if not src or not (Path(src) / MARKER).is_file():
                shutil.rmtree(e, ignore_errors=True)
                pruned.append(e.name)
    return {"linked": modes, "pruned": pruned, "foreign": foreign}


def forget_build(cfg, game_id: str, names: Iterable[str]) -> list[str]:
    """Builds > Delete: this node's links / copies of those build folders leave the emulator load folders too."""
    names = set(names)
    removed = []
    for emu in local_emulators(cfg):
        if not emu.private or not emu.load.is_dir():
            continue
        for tdir in emu.load.iterdir():
            for n in names:
                p = tdir / n
                try:
                    if _linked(p) and _ours(cfg, p):
                        _unlink(p)
                        removed.append(str(p))
                    elif p.is_dir() and (p / COPY_MARK).is_file():
                        src = json.loads((p / COPY_MARK).read_text(encoding="utf-8")).get("source") or ""
                        if Path(src).name == n and Path(src).parent.name == game_id:
                            shutil.rmtree(p)
                            removed.append(str(p))
                except (OSError, ValueError):
                    continue
    return removed


_STATE_LOCK = threading.Lock()


def _state_file(cfg) -> Path:
    return Path(cfg.runtime) / SELECTION


def remember(cfg, kind: str, title_id: str, game_id: str, build: str | None) -> None:
    with _STATE_LOCK:
        f = _state_file(cfg)
        try:
            d = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        except (OSError, ValueError):
            d = {}
        d[f"{kind}:{title_id.upper()}"] = {"game_id": game_id, "build": build or None, "ts": time.time()}
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_name(f.name + ".tmp")
            tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
            os.replace(tmp, f)
        except OSError:
            pass


def selected(cfg, kind: str, title_id: str) -> dict | None:
    try:
        return json.loads(_state_file(cfg).read_text(encoding="utf-8")).get(f"{kind}:{title_id.upper()}")
    except (OSError, ValueError, AttributeError):
        return None


def prepare_launch(cfg, emu: Emu, game_id: str | None, rom, build: str | None = None, *, serial=None,
                   apply: bool = True) -> dict:
    """Right before the emulator starts a Switch title (that emulator down): the build's pending edits land, its
    folder is linked into <load>/<TID>/ and enabled, the title's other gBox builds disabled; build=None starts the
    original game (every gBox build disabled). Mod folders gBox did not make keep the state the operator gave them.
    The result goes into the session detail ("overlay")."""
    tid = title_id_for(rom, serial)
    out = {"title_id": tid, "build": build or None, "emulator": emu.kind}
    if not tid:
        if build:
            raise ValueError(f"{Path(str(rom)).name}: no Switch title id, so the LayeredFS build {build} cannot be selected")
        return out | {"selection": "skipped", "reason": "no title id"}
    if not emu.private:
        if build:
            raise ValueError(f"{emu.kind}: {emu.why}; a LayeredFS build needs an emulator folder private to this PC")
        return out | {"selection": "skipped", "reason": emu.why}
    folder, applied = None, []
    if build:
        if not game_id:
            raise ValueError(f"no catalog game id for this launch, so the build {build} cannot be selected")
        if not LINK_NAME.fullmatch(build):
            raise ValueError(f"{build!r} is not a build folder name")
        folder = build_dir(cfg, game_id, build)
        meta = read_meta(folder)
        if not is_overlay(meta):
            raise ValueError(f"{build} is not a Switch LayeredFS build of this game")
        if meta["layeredfs"]["title_id"] != tid:
            raise ValueError(f"{build} was made for title {meta['layeredfs']['title_id']}; this file is {tid}")
        if apply:
            applied = apply_pending(folder)["applied"]
    sync = sync_title(cfg, emu, game_id, tid, launched=build) if game_id else {"linked": {}, "pruned": [], "foreign": []}
    tdir = emu.title_dir(tid)
    files = 0
    if build:
        entry = tdir / build
        files = len(overlay_files(folder))
        if not entry.is_dir() or (files and not any((entry / d).is_dir() for d in _eden_dirs(folder))):
            raise RuntimeError(f"the overlay {build} is not reachable in {tdir}: the game would start without it")
    entries = sorted(e for e in tdir.iterdir() if e.is_dir()) if tdir.is_dir() else []
    mods = [e.name for e in entries if _ours(cfg, e)]         # gBox's builds only: a mod folder the operator put there
    foreign = [e.name for e in entries if e.name not in mods]  # keeps the state they gave it, enabled or disabled
    dis = set_title_disabled(emu, tid, mods, build)
    remember(cfg, emu.kind, tid, game_id or "", build)
    return out | {"selection": "applied", "load": str(tdir), "mode": sync["linked"].get(build) if build else None,
                  "enabled": build or None, "disabled": dis["disabled"], "config_changed": dis["changed"],
                  "pending_applied": applied, "files": files, "foreign": foreign, "pruned": sync["pruned"]}


def running_users(game_id: str, folder_name: str) -> list[str]:
    """Sessions on this worker whose emulator booted this overlay folder (an edit of it waits for their restart)."""
    tools = sys.modules.get("gbox.tools")
    sessions = dict(getattr(tools, "SESSIONS", {}) or {}) if tools else {}
    out = []
    for sid, pair in sessions.items():
        try:
            ad, gd = pair
        except (TypeError, ValueError):
            continue
        proc = getattr(ad, "proc", None)
        if (getattr(ad, "overlay_build", None) == folder_name and (gd or {}).get("game_id") == game_id
                and proc is not None and proc.poll() is None):
            out.append(sid)
    return out


# --- the disk audit: full copies made by earlier build code ------------------------------------------------------------

def _size(folder: Path) -> tuple[int, int, int]:
    from .built_mods import folder_size
    got = folder_size(folder)
    return got if got else (0, 0, 0)


def _find(root: Path, depth: int):
    """(path, is_dir) of container files and romfs folders under root, at most `depth` levels down (a romfs folder is
    reported, not entered)."""
    stack = [(root, 0)]
    while stack:
        d, lv = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir():
                    if e.name.lower() == "romfs":
                        yield Path(e.path), True
                    elif lv + 1 < depth and not e.name.startswith(QUARANTINE):
                        stack.append((Path(e.path), lv + 1))
                elif e.name.lower().endswith(CONTAINERS):
                    yield Path(e.path), False
            except OSError:
                continue


def _recorded(meta: dict) -> list[dict]:
    rows = meta.get("file_changes")
    if isinstance(rows, list) and rows:
        return [r for r in rows if isinstance(r, dict)]
    return [{"path": str(f), "change": "unknown"} for f in meta.get("files") or []]


def base_romfs(cfg, title_id: str | None) -> Path | None:
    """An extracted RomFS of the title on this node: Eden's own Dump RomFS (<data>/dump/<TID>/romfs)."""
    if not title_id:
        return None
    from . import provision
    d = provision.switch_linux_dir(cfg) / "dump" / title_id.upper() / "romfs"
    return d if d.is_dir() else None


def _same_file(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        with open(a, "rb") as x, open(b, "rb") as y:
            while True:
                p, q = x.read(1 << 20), y.read(1 << 20)
                if p != q:
                    return False
                if not p:
                    return True
    except OSError:
        return False


def _tree_plan(build: Path, romfs: Path, meta: dict, base: Path | None) -> dict:
    """Which files of an extracted RomFS tree an overlay keeps: those the build recorded as changed, else those that
    differ from an extracted base RomFS of the title."""
    listed = []
    for r in _recorded(meta):
        p = str(r.get("path") or "").replace("\\", "/").lstrip("/")
        cand = build / p
        if not cand.is_file() and not p.lower().startswith("romfs/"):
            cand = romfs / p
        if cand.is_file() and _under(cand, romfs):
            listed.append(cand)
    if listed:
        keep = listed
        how = "the files the build recorded as changed"
    elif base is not None:
        keep = [p for p in romfs.rglob("*") if p.is_file()
                and not _same_file(p, base / p.relative_to(romfs))]
        how = f"the files that differ from the extracted base RomFS {base}"
    else:
        return {"convertible": False, "reason": "no record of which files changed and no extracted base RomFS of the "
                                                "title to compare with (Eden: File > Dump RomFS)"}
    return {"convertible": "overlay", "how": how,
            "keep": [{"path": "romfs/" + p.relative_to(romfs).as_posix(), "size": p.stat().st_size} for p in keep]}


def _switch_title(meta: dict) -> str | None:
    """A Switch application title id a marker names (0100...: 3DS ids start 0004, so a Citra build's romfs/ is not one)."""
    for v in (meta.get("title_id"), meta.get("serial"), (meta.get("layeredfs") or {}).get("title_id")):
        tid = str(v or "").removeprefix("0x").removeprefix("0X").upper()
        if TID.fullmatch(tid) and tid.startswith("01"):
            return tid
    return None


def audit(cfg, *, switch_ids: Iterable[str] = (), romfs_dir=None, libraries: Iterable = ()) -> dict:
    """Read-only: every full Switch copy gBox made on this node (container copies and extracted RomFS trees in the mod
    collection, staged copies, cache / export / extract copies) with sizes, and what converting each one would do.
    Nothing is changed. switch_ids: the catalog's Switch game ids, or {game id: title id} (their serials)."""
    titles = dict(switch_ids) if isinstance(switch_ids, dict) else {str(g): None for g in switch_ids}
    switch_ids = set(titles)
    libs = [Path(p) for p in libraries if p]
    mods = mods_root(cfg)
    items, overlays, quarantined = [], [], []
    for g in sorted(os.scandir(mods), key=lambda e: e.name) if mods.is_dir() else []:
        if not g.is_dir():
            continue
        for b in sorted(os.scandir(g.path), key=lambda e: e.name):
            if not b.is_dir(follow_symlinks=False):
                continue
            folder = Path(b.path)
            if b.name.startswith(QUARANTINE):
                size = _size(folder)
                quarantined.append({"id": f"mods/{g.name}/{b.name}", "path": str(folder), "game_id": g.name,
                                    "bytes": size[0], "own_bytes": size[1], "files": size[2]})
                continue
            meta = read_meta(folder)
            if is_overlay(meta):
                s = summary(folder, meta)
                overlays.append({"game_id": g.name, "build": b.name, "files": s["files"], "bytes": s["bytes"],
                                 "pending": s["pending"]})
                continue
            if not meta:
                continue
            found = list(_find(folder, 3))
            images = [p for p, is_dir in found if not is_dir]
            switch = g.name in switch_ids or bool(_switch_title(meta)) or str(meta.get("platform") or "") == "switch"
            trees = [p for p, is_dir in found if is_dir] if switch else []      # (a 3DS build has romfs/ folders too)
            if not images and not trees:
                continue
            size = _size(folder)
            staged = _staged(folder)
            tid = title_id_for(images[0] if images else None, _switch_title(meta) or titles.get(g.name))
            row = {"id": f"mods/{g.name}/{b.name}", "path": str(folder), "game_id": g.name, "build": b.name,
                   "bytes": size[0], "own_bytes": size[1], "files": size[2], "title_id": tid,
                   "switch_game": g.name in switch_ids or None, "recorded_changes": len(_recorded(meta)),
                   **({"staged_of": b.name.split("~")[0]} if staged else {})}
            if staged:
                items.append(row | {"kind": "staged_copy", "images": [str(p) for p in images],
                                    "convertible": "quarantine",
                                    "plan": "a staged copy of a build: the build itself carries its content; moved "
                                            "aside, deleted only by purge"})
            elif images:
                changes = _recorded(meta)
                row |= {"kind": "container_copy", "images": [{"path": str(p), "bytes": p.stat().st_size} for p in images]}
                if not changes:
                    items.append(row | {"convertible": "empty_overlay",
                                        "plan": "the copy changes nothing: the build becomes an empty overlay of the "
                                                "base NSP (same name, card and favorites)"})
                else:
                    items.append(row | {"convertible": False, "changes": changes[:20],
                                        "reason": "its changes were made to the container itself (byte patches in "
                                                  "encrypted NCAs), which no RomFS file carries: force_empty=true makes "
                                                  "it an empty overlay and drops them"})
            else:
                tree = trees[0]
                plan = _tree_plan(folder, tree, meta, Path(romfs_dir) if romfs_dir else base_romfs(cfg, tid))
                items.append(row | {"kind": "romfs_tree", "romfs": str(tree), **plan})
    cache, data, runtime = Path(cfg.cache), Path(cfg.data_dir), Path(cfg.runtime)
    others = [("cache_copy", cache / gid, cache) for gid in sorted(switch_ids)] + [
        ("modbase", cache / "modbase", cache), ("romexport_base", cache / "romexport_base", cache),
        ("export", data / "exports", data), ("extract", runtime / "extract", runtime)]
    for kind, root, base in others:
        if not root.is_dir() or any(_under(root, lib) or _under(lib, root) for lib in libs):
            continue
        for p, is_dir in _find(root, 4):
            size = _size(p) if is_dir else (p.stat().st_size, p.stat().st_size, 1)
            items.append({"id": f"{base.name}:{p.relative_to(base).as_posix()}",
                          "path": str(p), "kind": kind if not is_dir else f"{kind}_romfs_tree", "bytes": size[0],
                          "own_bytes": size[1], "files": size[2], "convertible": False,
                          "reason": {"cache_copy": "a launch-cache copy of the library file: the cache's own eviction "
                                                   "manages it",
                                     "export": "an export the operator asked for: delete it from the exports folder "
                                               "when it is not needed"}.get(kind, "not a build: listed for its size")})
    conv = [i for i in items if i.get("convertible")]
    return {"node": __import__("platform").node(), "cache": str(Path(cfg.cache)), "items": items,
            "overlays": overlays, "quarantined": quarantined,
            "totals": {"items": len(items), "bytes": sum(i["bytes"] for i in items),
                       "convertible": len(conv), "frees": sum(i.get("own_bytes") or 0 for i in conv),
                       "quarantined_bytes": sum(q["own_bytes"] for q in quarantined),
                       "overlay_bytes": sum(o["bytes"] for o in overlays)}}


def _quarantine(folder: Path) -> Path:
    """Move a full copy aside within its game folder (a rename, never a copy or a delete): its marker becomes
    .gbox-mod.json.full-copy so no gallery, heartbeat or launch sees it as a build."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = folder.with_name(f"{QUARANTINE}{folder.name}.{stamp}")
    marker = folder / MARKER
    if marker.is_file():
        os.replace(marker, folder / (MARKER + ".full-copy"))
    os.replace(folder, dest)
    from . import filemods
    side = filemods._hash_sidecar(folder)
    if side.is_file():
        os.replace(side, dest / side.name)
    return dest


def convert(cfg, *, items: Iterable[str] = (), dry_run: bool = True, force_empty: bool = False, romfs_dir=None,
            switch_ids: Iterable[str] = ()) -> dict:
    """Turn the audit's convertible full copies into overlays: dry_run (the default) only says what would happen.
    Applied, an overlay takes the build's name (only the kept files, copied), and the full copy moves aside as
    <game>/.switch-full-copy.<build>.<stamp> (a rename); nothing is deleted until purge(confirm=True)."""
    report = audit(cfg, switch_ids=switch_ids, romfs_dir=romfs_dir)
    want = set(items)
    done, skipped = [], []
    for it in report["items"]:
        if want and it["id"] not in want:
            continue
        conv = it.get("convertible") or ("empty_overlay" if force_empty and it.get("kind") == "container_copy" else False)
        if not conv:
            skipped.append({"id": it["id"], "reason": it.get("reason") or "not convertible"})
            continue
        step = {"id": it["id"], "kind": it["kind"], "action": conv, "frees": it.get("own_bytes") or 0}
        if dry_run:
            done.append(step | {"dry_run": True})
            continue
        folder = Path(it["path"])
        if conv == "quarantine":
            done.append(step | {"moved_to": str(_quarantine(folder))})
            continue
        gid, name = it["game_id"], it["build"]
        old = read_meta(folder)
        tid = it.get("title_id")
        if not tid:
            skipped.append({"id": it["id"], "reason": "no title id: name the game's NSP serial in the catalog first"})
            continue
        tmp = folder.with_name(f".{name}.overlay-tmp-{uuid.uuid4().hex[:8]}")
        tmp.mkdir()
        try:
            for f in (it.get("keep") or []) if conv == "overlay" else []:
                src = Path(it["romfs"]) / f["path"][len("romfs/"):]
                dst = tmp / f["path"]
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            images = it.get("images") or []
            base = Path(images[0]["path"]).name if images and isinstance(images[0], dict) else ""
            meta = new_meta(gid, name, tid, game_title=str(old.get("game_title") or ""), base=base,
                            kind=old.get("kind") if old.get("kind") in ("cast", "character", "file") else "file")
            keepers = {k: old[k] for k in ("title", "desc", "recipe", "requests", "request", "cast", "characters",
                                           "replaces", "slot") if k in old}
            meta |= keepers | {"converted_from": {"kind": it["kind"], "bytes": it["bytes"], "ts": time.time(),
                                                  "recorded_changes": it.get("recorded_changes")}}
            meta = _refresh(tmp, meta, [{"id": _edit_id(), "ts": time.time(), "applied": time.time(), "by": "convert",
                                         "note": f"converted from a {it['kind']} ({it['bytes']} bytes)", "files": []}],
                            None)
            _write_meta(tmp, meta)
            moved = _quarantine(folder)
            os.replace(tmp, folder)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        done.append(step | {"overlay": str(folder), "files": len(overlay_files(folder)), "moved_to": str(moved)})
    return {"dry_run": dry_run, "converted": done, "skipped": skipped,
            "frees": sum(d["frees"] for d in done), "next": "purge(confirm=True) deletes the moved full copies"
            if done and not dry_run else ("run again with dry_run=false to apply" if done else "")}


def purge(cfg, *, confirm: bool = False) -> dict:
    """The full copies convert() moved aside: listed; deleted only with confirm=True (nothing else is ever touched)."""
    from .build_retention import linked
    rows = audit(cfg)["quarantined"]
    if not confirm:
        return {"confirm": False, "would_delete": rows, "bytes": sum(r["own_bytes"] for r in rows)}
    root = mods_root(cfg).resolve()
    deleted, errors = [], []
    for r in rows:
        p = Path(r["path"])
        try:
            if (not p.name.startswith(QUARANTINE) or linked(p) or not p.resolve().is_relative_to(root)
                    or any(linked(q) for q in p.rglob("*"))):
                raise OSError("refusing a linked or foreign path")
            shutil.rmtree(p)
            deleted.append(r)
        except OSError as e:
            errors.append(f"{r['id']}: {e}")
    return {"confirm": True, "deleted": deleted, "bytes": sum(r["own_bytes"] for r in deleted), "errors": errors}


# --- character replacement on Switch titles ---------------------------------------------------------------------------

WRITERS: dict[str, Callable] = {}


def register_writer(title_id: str, writer: Callable) -> None:
    """A Switch writer for one title: writer(ctx, game, inp, meta) -> {"changes": {RomFS path: change}, "kind":
    "character" | "cast" | "file", "slots": [{slot, donor}], "note": str}. Its files go into the active overlay."""
    WRITERS[title_id.upper()] = writer


def _session_of(api, ctx, sid: str) -> dict | None:
    if not sid:
        return None
    try:
        return next((s for s in api(ctx, "GET", "/api/sessions") if s.get("session_id") == sid), None)
    except Exception:                                        # noqa: BLE001
        return None


def active_build(cfg, game: dict, session: dict | None = None, kind: str = "eden") -> str | None:
    """The build an edit goes into: the one the session shows, else the one this node last started the title with."""
    if session and session.get("game_id") == game.get("game_id"):
        from .built_mods import session_build
        name = session_build(session)
        return name or None
    tid = title_id_for(None, game.get("serial") or (game.get("launch") or {}).get("title_id"))
    row = selected(cfg, kind, tid) if tid else None
    return (row or {}).get("build") if (row or {}).get("game_id") in (None, "", game.get("game_id")) else None


def character_use(ctx, api, meta: dict | None, game: dict, inp, op: str = "use") -> dict:
    """characters op=use / live_use / cast_swap on a Switch title: the title's writer (register_writer) makes RomFS
    files and they go into the ACTIVE overlay build in place (the session's build, else the one last started, else a
    new <title>_mods overlay); a running session then restarts the title with it (POST /api/sessions/{sid}/swap: Eden
    restarts in the same session). Never a copy of the NSP. Without a writer for the title: the durable repair request
    (char_coverage.no_writer) plus where the files would go."""
    tid = title_id_for(None, game.get("serial") or (game.get("launch") or {}).get("title_id"))
    session = _session_of(api, ctx, getattr(inp, "session_id", "") or "")
    build = (getattr(inp, "mod_name", "") or "") or active_build(ctx.config, game, session)
    hint = {"layeredfs": True, "title_id": tid, "active_build": build,
            "how": "switch_mods op=write game_id=<id> build=<active build> changes={<RomFS path>: {artifact|from|romfs}}"
                   " (in place), op=apply_live session_id=<id> to restart the running title with it",
            "copies": "none: a Switch build is only its changed files, linked into the emulator's load folder"}
    writer = WRITERS.get(tid or "")
    if writer is None:
        need = {"target": f"{game.get('title')}: its character files in the RomFS",
                "format": "the title's own model files, written by a Switch writer for this title",
                "steps": ["a writer for this Switch title that outputs RomFS files (gbox.switch_mods.register_writer)",
                          "its files go into the active LayeredFS build in place (gbox.switch_mods.write_files)",
                          "a running session restarts the title in place to load them (Eden reads mods at boot)"],
                "have": "the LayeredFS overlay path (gbox.switch_mods): in-place edits with backups, title restart, "
                        "no NSP copies; no Switch model writer yet"}
        if meta and op != "cast_swap":
            from . import char_coverage
            res = char_coverage.no_writer(ctx, api, meta, game, need, inp)
        else:
            res = {"status": "missing", "missing": need, "native_replacement": False,
                   "message": f"No Switch writer for {game.get('title')} yet."}
        return res | {"switch_overlay": hint}
    plan = writer(ctx, game, inp, meta) or {}
    changes = plan.get("changes") or {}
    if not changes:
        return {"status": "failed", "reason": plan.get("reason") or "the writer produced no files",
                "switch_overlay": hint}
    folder_name = build or default_build_name(game)
    gid = game["game_id"]
    res = write_files(ctx.config, gid, folder_name, changes, in_use=bool(running_users(gid, folder_name)),
                      note=plan.get("note") or f"characters op={op}", by=f"job {getattr(ctx, 'job_id', '')}",
                      kind=plan.get("kind") or "character",
                      create={"title_id": tid, "game_title": game.get("title") or "",
                              "base": Path(str(game.get("rel_path") or "")).name, "kind": plan.get("kind") or "character"})
    out = {"status": "applied" if not res["pending"] else "pending_restart", "mod": folder_name, "edit": res["edit"],
           "files": res["files"], "slots": plan.get("slots") or [], "switch_overlay": hint | {"active_build": folder_name}}
    if session and session.get("state") == "running" and session.get("game_id") == gid:
        job = api(ctx, "POST", f"/api/sessions/{session['session_id']}/swap", json={"mod": folder_name, "keep_state": True})
        out |= {"status": "restarting", "swap_job": (job or {}).get("id"),
                "note": "the title restarts in this session with the edited build (Eden reads mods at boot)"}
    elif getattr(inp, "launch", False):
        job = api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": folder_name,
                                                                             "node": HOST_OS}})
        out |= {"launch": {"job": (job or {}).get("id"), "state": (job or {}).get("state")}}
    return out


# --- the tool ---------------------------------------------------------------------------------------------------------

class SwitchModsIn(BaseModel):
    op: str = "status"          # status | write | revert | new_build | select | apply_pending | apply_live | audit | convert | purge
    game_id: str = ""
    build: str | None = None    # the overlay build; None = the active one (the session's, else the one this node last started)
    session_id: str = ""        # apply_live: the running session (on this worker)
    changes: dict = {}          # write / apply_live: {RomFS path: {from|artifact|b64|romfs|patch|remove}}
    new_name: str = ""          # new_build: the new build (a copy of `build`'s overlay folder only, or empty)
    edit: str = "last"          # revert: which edit (its id from status, or last)
    paths: list[str] = []       # revert: only these files
    note: str = ""
    romfs_dir: str = ""         # write / convert: an extracted RomFS of the title ({"romfs": path} sources, base patches)
    dry_run: bool = True        # convert: report only (the default)
    items: list[str] = []       # convert: ids from the audit (empty: every convertible one)
    force_empty: bool = False   # convert: a container copy with byte patches becomes an empty overlay (patches dropped)
    confirm: bool = False       # purge: delete the full copies convert moved aside (nothing else)


class SwitchModsOut(BaseModel):
    result: dict


def _accept(store, out: SwitchModsOut, actor: str):
    """apply_live restarted the title in the same session: the session now shows that build (mod), and its Eden pid
    is new (detail.pid: re-docking, audio, re-adoption)."""
    r = out.result if isinstance(out.result, dict) else {}
    sid = r.get("session_id")
    if r.get("op") != "apply_live" or not r.get("same_session") or not sid:
        return
    with store.lock:
        s = store.get("session", sid)
        if not s or s.get("state") == "ended":
            return
        mod = r.get("build") or ""
        doc = {k: v for k, v in s.items() if k not in ("staged_mod", "launch_mod", "live_mod", "collection_mod")}
        doc["mod"] = mod
        launched = r.get("launch_mod") or mod
        if launched != mod:
            doc |= {"collection_mod": mod, "staged_mod": launched, "launch_mod": launched}
        doc["detail"] = (s.get("detail") or {}) | (r.get("session_detail") or {})
        store.put("session", sid, doc)
    store.audit(actor, "session.switch_overlay", sid, {"mod": mod, "launch_mod": launched,
                                                        "pid": (r.get("session_detail") or {}).get("pid")})


def _catalog(ctx, game_id: str) -> dict:
    import httpx
    if not game_id:
        raise ValueError("game_id required")
    r = httpx.get(f"{ctx.server}/api/catalog/{game_id}", headers=ctx.headers, timeout=30)
    r.raise_for_status()
    return r.json()


def _facts(ctx, game: dict) -> tuple[str, str]:
    """(title id, base file name) of a catalog Switch game on this node (a session's game: the file it booted)."""
    rom = Path(game["_rom_path"]) if game.get("_rom_path") else None
    if rom is None:
        try:
            from .models import CatalogEntry
            from .tools import rom_path
            rom = rom_path(CatalogEntry.model_validate({k: v for k, v in game.items() if not k.startswith("_")}),
                           ctx.config)
        except Exception:                                    # noqa: BLE001 - the library may not be mounted here
            rom = None
    tid = title_id_for(rom if rom is not None and rom.is_file() else None,
                       game.get("serial") or (game.get("launch") or {}).get("title_id"))
    if not tid:
        raise ValueError(f"{game.get('title') or game.get('game_id')}: no Switch title id (catalog serial or NSP ticket)")
    base = rom.name if rom is not None else Path(str(game.get("rel_path") or (game.get("launch") or {}).get("path") or "")).name
    return tid, base


def _resolve(ctx, changes: dict) -> dict:
    """{"artifact": sha256} -> {"bytes": ...} (a file uploaded to gBox, e.g. an edited model)."""
    out = {}
    for k, ch in (changes or {}).items():
        if isinstance(ch, dict) and "artifact" in ch:
            import httpx
            r = httpx.get(f"{ctx.server}/api/artifacts/{ch['artifact']}", headers=ctx.headers, timeout=300)
            r.raise_for_status()
            ch = {"bytes": r.content}
        out[k] = ch
    return out


def _switch_ids(ctx) -> dict[str, str | None]:
    """{game id: serial (title id)} of the catalog's Switch games, for the audit."""
    if not getattr(ctx, "server", None):
        return {}
    try:
        import httpx
        r = httpx.get(f"{ctx.server}/api/catalog", params={"platform": "switch", "limit": 500}, headers=ctx.headers,
                      timeout=30)
        return {e["game_id"]: e.get("serial") for e in r.json().get("items") or [] if e.get("game_id")}
    except Exception:                                        # noqa: BLE001 - the audit still finds copies by content
        return {}


def _emu_here(cfg) -> Emu:
    emus = local_emulators(cfg)
    if not emus:
        raise ValueError("no Switch emulator on this node")
    return emus[0]


def _collection_elsewhere(ctx, game_id: str, name: str) -> bool:
    """A build the central collection holds, edited on a node that is not the collection: the edit would vanish at
    this node's next launch (it stages the collection's copy). Edits run where the collection lives."""
    if HOST_OS == "linux" or not getattr(ctx, "server", None):
        return False
    try:
        import httpx
        return httpx.get(f"{ctx.server}/api/modfiles/{game_id}/{name}", headers=ctx.headers, timeout=30).status_code == 200
    except Exception:                                        # noqa: BLE001
        return False


def file_mod_build(ctx, game: dict, rom, name: str, changes: dict) -> dict:
    """file_mod op=build on a Switch game: the changes (keys are RomFS / ExeFS paths) go into overlay build `name` in
    place, made when new; nothing else of the build changes and the NSP is never copied."""
    gid = game["game_id"]
    tid = title_id_for(rom if rom is not None and Path(rom).is_file() else None,
                       game.get("serial") or (game.get("launch") or {}).get("title_id"))
    if not tid:
        raise ValueError(f"{game.get('title') or gid}: no Switch title id (catalog serial or NSP ticket)")
    if _collection_elsewhere(ctx, gid, name):
        raise ValueError(f"{name} lives in the central collection: build it there (require_os=linux); this PC fetches "
                         "it when it next starts it")
    res = write_files(ctx.config, gid, name, changes, in_use=bool(running_users(gid, name)), note="file_mod build",
                      by=f"job {getattr(ctx, 'job_id', '')}", romfs_base=base_romfs(ctx.config, tid),
                      create={"title_id": tid, "game_title": game.get("title") or "",
                              "base": Path(str(rom)).name if rom is not None else ""})
    return res | {"layeredfs": True, "title_id": tid}


def apply_live(ctx, inp: SwitchModsIn) -> dict:
    """One action for the running game: the edit (if any) goes into the build, then the title restarts with that build
    enabled. Eden (Linux) restarts the title in the same session on the same display (restart_title); another emulator
    (Yuzu) relaunches through the control plane's swap (a new session). Eden has no save states: the title boots
    again, its own saves stay."""
    from . import adapters, filemods, tools
    pair = tools.SESSIONS.get(inp.session_id)
    if not pair:
        raise ValueError(f"session {inp.session_id} is not running on this worker")
    ad, gd = pair
    gid = gd.get("game_id")
    if inp.game_id and inp.game_id != gid:
        raise ValueError(f"session {inp.session_id} runs {gid}, not {inp.game_id}")
    if str(gd.get("platform") or "") != "switch":
        raise ValueError("apply_live is for Switch sessions")
    current = getattr(ad, "overlay_build", None)
    target = current if inp.build is None else (inp.build or None)
    if target and target != current and ctx.server and not overlay_of(ctx.config, gid, target):
        target = filemods.stage(ctx.config, ctx.server, ctx.headers, gid, target, ctx.progress)   # KB-MB, not GB
    edit = None
    if inp.changes:
        tid, base = _facts(ctx, gd)
        target = target or default_build_name(gd)
        edit = write_files(ctx.config, gid, target, _resolve(ctx, inp.changes),
                           in_use=target == current or bool(running_users(gid, target)), note=inp.note,
                           by=f"job {ctx.job_id}", romfs_base=inp.romfs_dir or base_romfs(ctx.config, tid),
                           create={"title_id": tid, "game_title": gd.get("title") or "", "base": base})
    build = (target or "").split("~")[0]
    if isinstance(ad, adapters.SwitchLinuxAdapter):
        ctx.progress(20, f"Restarting {gd.get('title')} " + (f"with {build}" if build else "(original)") +
                     " in this session: Eden layers mods only at boot")
        out = ad.restart_title(overlay=target, wait=True, progress=ctx.progress)
        gd["mod"] = target or ""
        tools.track_emulator(ctx.config, inp.session_id, ad.proc.pid)
        return {"op": "apply_live", "session_id": inp.session_id, "same_session": True, "build": build,
                "launch_mod": target or "", "edit": edit, "restart": out,
                "session_detail": {"pid": ad.proc.pid, "overlay": out.get("overlay")},
                "notes": ["Eden has no save states: the title booted again; its own saves are kept."]}
    import httpx
    r = httpx.post(f"{ctx.server}/api/sessions/{inp.session_id}/swap", json={"mod": build, "keep_state": True},
                   headers=ctx.headers, timeout=60)
    r.raise_for_status()
    return {"op": "apply_live", "session_id": inp.session_id, "same_session": False, "build": build, "edit": edit,
            "swap_job": r.json().get("id"),
            "notes": [f"{ad.name} relaunches the title with the build (a new session); no moment is kept."]}


@tool("switch_mods", "1.0", SwitchModsIn, SwitchModsOut, capabilities=["mod"], permissions=[P.EXECUTE], timeout_s=1800,
      side_effects=["writes LayeredFS overlay files (only the changed ones) in place, with backups",
                    "links builds into the Switch emulator's load folder and writes its [DisabledAddOns]",
                    "apply_live restarts the session's title (Eden: same session)",
                    "convert moves full copies aside (rename); purge confirm=true deletes them"],
      on_accept=_accept)
def switch_mods_tool(inp: SwitchModsIn, ctx):
    """Switch builds as LayeredFS overlays (docs/switch-mods.md): a build is only its changed RomFS / ExeFS files,
    linked into Eden's (or a local Yuzu's) load/<title id>/; the base NSP is never copied.
    status game_id: the overlay builds, the active one, the load folder. | write game_id [build] changes: rewrite
    only those files of the active build in place (backups kept; waits for the restart while it runs here). |
    revert [edit] [paths] | new_build new_name [build]: a copy of the overlay folder only (KB-MB) | select [build]: the
    build the next start enables ("" = the original) | apply_pending | apply_live session_id [build] [changes]: the
    edit + one restart of the running title (Eden: same session) | audit: full Switch copies on this node with sizes |
    convert [items] dry_run=false [force_empty]: into overlays, the copies moved aside | purge confirm=true."""
    cfg = ctx.config
    if inp.op == "audit":
        return {"result": {"op": "audit", **audit(cfg, switch_ids=_switch_ids(ctx), romfs_dir=inp.romfs_dir or None)}}
    if inp.op == "convert":
        return {"result": {"op": "convert", **convert(cfg, items=inp.items, dry_run=inp.dry_run,
                                                      force_empty=inp.force_empty, romfs_dir=inp.romfs_dir or None,
                                                      switch_ids=_switch_ids(ctx))}}
    if inp.op == "purge":
        return {"result": {"op": "purge", **purge(cfg, confirm=inp.confirm)}}
    if inp.op == "apply_live":
        return {"result": apply_live(ctx, inp)}
    game = _catalog(ctx, inp.game_id)
    if str(game.get("platform") or "") != "switch":
        raise ValueError(f"{game.get('title')} is not a Switch game")
    gid = game["game_id"]
    tid, base = _facts(ctx, game)
    emu = _emu_here(cfg) if inp.op in ("status", "select") else None
    active = inp.build if inp.build is not None else active_build(cfg, game, None, emu.kind if emu else (
        "eden" if HOST_OS == "linux" else "yuzu"))
    by = f"job {getattr(ctx, 'job_id', '')}"
    if inp.op == "status":
        tdir = emu.title_dir(tid)
        entries = sorted(e.name for e in tdir.iterdir() if e.is_dir()) if tdir.is_dir() else []
        text, _, _ = _read_text(emu.config)
        disabled = read_disabled(text).get(int(tid, 16), [])
        return {"result": {"op": "status", "game_id": gid, "title_id": tid, "emulator": emu.kind,
                           "private": emu.private, "why": emu.why, "load": str(tdir), "active": active,
                           "selected": selected(cfg, emu.kind, tid),
                           "builds": [summary(f, m) | {"in_use": running_users(gid, n),
                                                       "history": (m.get("history") or [])[-10:]}
                                      for n, f, m in builds_for(cfg, gid, tid)],
                           "load_entries": [{"name": n, "gbox": _ours(cfg, tdir / n), "enabled": n not in disabled}
                                            for n in entries]}}
    if inp.op in ("write", "revert", "apply_pending", "new_build") and active and _collection_elsewhere(ctx, gid, active):
        raise ValueError(f"{active} lives in the central collection: edit it there (switch_mods with require_os=linux); "
                         "this PC fetches the edited build when it next starts it")
    if inp.op == "write":
        name = active or default_build_name(game)
        res = write_files(cfg, gid, name, _resolve(ctx, inp.changes), in_use=bool(running_users(gid, name)),
                          note=inp.note, by=by, romfs_base=inp.romfs_dir or base_romfs(cfg, tid),
                          create={"title_id": tid, "game_title": game.get("title") or "", "base": base})
        return {"result": {"op": "write", **res, "note": "restart the title to load it (op=apply_live)" if res["pending"]
                           else "in place; a running game loads it at its next start (op=apply_live restarts it now)"}}
    if not active and inp.op in ("revert", "apply_pending"):
        raise ValueError("no active build for this title on this node: name one (build=...)")
    if inp.op == "revert":
        return {"result": {"op": "revert", **revert(cfg, gid, active, inp.edit, inp.paths,
                                                    in_use=bool(running_users(gid, active)), by=by)}}
    if inp.op == "apply_pending":
        users = running_users(gid, active)
        if users:
            raise ValueError(f"{active} is running in {', '.join(users)}: op=apply_live restarts it with the edits")
        return {"result": {"op": "apply_pending", **apply_pending(build_dir(cfg, gid, active))}}
    if inp.op == "new_build":
        if active:
            return {"result": {"op": "new_build", **copy_build(cfg, gid, active, inp.new_name, by=by)}}
        folder = create_build(cfg, gid, inp.new_name, tid, game_title=game.get("title") or "", base=base, by=by)
        return {"result": {"op": "new_build", "mod": inp.new_name, "dir": str(folder), "files": 0, "bytes": 0}}
    if inp.op == "select":
        rom = None
        build = inp.build or None
        users = [s for n, _, _ in builds_for(cfg, gid, tid) for s in running_users(gid, n)]
        res = prepare_launch(cfg, emu, gid, rom, build, serial=tid, apply=not users)
        return {"result": {"op": "select", **res, "note": "takes effect when the title next starts"
                           + (f" (running now in {', '.join(users)}: op=apply_live restarts it)" if users else "")}}
    raise ValueError(f"unknown op {inp.op}")
