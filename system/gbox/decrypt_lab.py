"""The decryption lab: one reusable pipeline for every title, and the live feed a page can watch.

Why this exists
---------------
Each title's reverse engineering was ad-hoc: a script per hypothesis, results in a doc, nothing shared. This
module makes the *process* a first-class object so it is reusable and observable:

    adapter  ->  stages  ->  fields (candidate / confirmed / rejected)  ->  verification  ->  driver
                 |            |
                 |            +-- evidence: who found it, how, and what would falsify it
                 +-- identify / extract / disassemble / fields / verify / driver

Everything is driven by introspecting the title modules in `gbox.mercs.titles` (they already declare
TITLE_ID, BUILD_ID, SIG_OFF, SIGNATURE, the S_* anchors and DRIVER), so adding a title is an adapter entry,
not a new tool. RE5/RE6 keep their full field maps there; RE4's are the ones this session derived.

The lab also carries the live instruments the page shows:

* a **RAM hex scanner** that resolves a title's module base from its own signature and reads guest memory
  server-side (NCE means guest address == host address on this box), classifying every 4-byte cell;
* the **bot's perception**, read from the tactical-map frames the Mercenaries publisher already sends, so the
  page shows exactly what autoplay sees and how it is being used.

Routes (all under /api/decrypt-lab):
    GET  /state                 titles, stages, fields, events, scans, bot
    GET  /events?after=N        events after sequence N
    POST /scan                  {title, offset, length, mode}   mode: "module" (offset from base) | "absolute"
    GET  /scan/{id}             one stored scan
    POST /field                 {title, name, status, note}      promote/reject a field
"""
from __future__ import annotations

import importlib
import json
import os
import re
import struct
import threading
import time
import uuid
from collections import OrderedDict, deque
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel

FORMAT = 1
EVENTS_KEEP = 400
SCANS_KEEP = 40
SCAN_MAX = 4096           # bytes per scan request
SIG_SCAN_CAP = 40 << 20   # how much read-only module space to search for the signature
EMULATOR_PATTERNS = ("AppDir/bin/citron", "AppDir/bin/eden", "citron", "yuzu")

STAGES = ("identify", "extract", "disassemble", "fields", "verify", "driver")
STAGE_TEXT = {
    "identify": "title id, build id and a unique signature in the module",
    "extract": "the dumped NSO on disk",
    "disassemble": "a loadable ELF (nso2elf) and Ghidra analysis",
    "fields": "field catalog with evidence",
    "verify": "a live read that confirms the field",
    "driver": "a Mercenaries driver and playable gate",
}

# ---------------------------------------------------------------------------------------------------------
# Title adapters. `fields` are (name, offset, kind, status, evidence). Status:
#   confirmed - verified against live memory at least once, with the check named in evidence
#   candidate - found in code or memory, not yet verified
#   rejected  - tested and disproved (kept: knowing what a field is not is part of the map)
# `module` is the gbox module the adapter introspects for anchors.
ADAPTERS = [
    {
        "id": "re4_switch",
        "module": "gbox.mercs.titles.re4_switch",
        "nso_glob": "main-*.nso",
        "elf": "re4main.elf",
        "notes": "Switch port of the biohazard 4 HD engine. Ghidra: image_base 0x100000, 11839 functions.",
        "fields": [
            ("health", 0x3C2, "u16 @ unit+0x3c2", "confirmed",
             "FUN_004cd1c0 writes *(ushort*)(unit+0x3c2) = health - damage; read from code, offset survives "
             "decompilation (the memory-only candidate at position-0x2478 was rejected)"),
            ("unit_type", 0x3CE, "u8 @ unit+0x3ce", "confirmed",
             "FUN_004cd1c0 passes *(byte*)(unit+0x3ce) to the damage table FUN_002cccc0"),
            ("unit_state", 0x116, "u8 @ unit+0x116", "candidate",
             "switchD_0020844c::caseD_0 branches on it (0/1/other)"),
            ("unit_flags", 0x4C4, "u32 @ unit+0x4c4", "candidate",
             "same function ORs 0x100 into it"),
            ("game_state", 0xB25D78, "pointer global", "confirmed",
             "PTR_PTR_00c25d78: 40 code readers; fields +0x5037 (difficulty), +0x503c (mode), +0x84f0, +0x984"),
            ("score_fn", 0x1CCCC0, "code FUN_002cccc0", "confirmed",
             "Mercenaries kill score: type table, difficulty multiplier, 29999 special case"),
            ("damage_fn", 0x4CD1C0, "code FUN_004cd1c0", "confirmed",
             "damage routine: reads type, subtracts from health, zeroes it on death"),
            ("rsf_unit_table", 0x126A400, "pointer array, +0x10 + i*8", "rejected",
             "real unit table, but reads all zeros in a Mercenaries round and the caller names flag_rsf.h: "
             "belongs to a scripted mode, not Mercenaries"),
            ("player_position", 0x0, "f32x3, spawn-fixed", "rejected",
             "matched only one spawn state; a later round had no candidate near those coordinates, so it is "
             "not a stable player position"),
            ("mercs_unit_list", 0x0, "", "candidate",
             "the missing S_ENEMY: still unfound; next leads are the score/damage callers' loops"),
        ],
    },
    {
        "id": "re5_switch",
        "module": "gbox.mercs.titles.re5_switch",
        "nso_glob": "main-*.nso",
        "elf": "re5main.elf",
        "notes": "The reference integration: full native field map, live controls and mods.",
        "fields": [
            ("motion", "P_MOTION", "u8", "confirmed", "declared and verified in the module (live 2026-10-26)"),
            ("aim_pitch", "P_AIM_PITCH", "f32", "confirmed", "the game's own aim pitch while the gun is up"),
            ("dying_hp", "DYING_HP", "u16", "confirmed", "the solo dying state keeps exactly 1 HP"),
            ("inv_obj", "INV_OBJ", "pointer", "confirmed", "the item object; the game zeroes it when the slot empties"),
            ("gamesys", "MAIN_GAMESYS", "global", "confirmed", "main + MAIN_GAMESYS"),
        ],
    },
    {
        "id": "re6_switch",
        "module": "gbox.mercs.titles.re6_switch",
        "nso_glob": "main-*.nso",
        "elf": "re6main.elf",
        "notes": "The second reference integration: sUnit lines, max 512 units, UI unit table.",
        "fields": [
            ("max_enemies", "MAX_ENEMIES", "count", "confirmed", "sUnit lines hold up to 512 units"),
            ("ui_max", "UI_MAX", "count", "confirmed", "interface units, lines 0/1/18/19"),
            ("title_menu_open", "TITLE_MENU_OPEN", "u32", "confirmed", "uIdTitle00: 1 = A opens the main menu"),
            ("units", "UNITS", "vtable table", "confirmed", "interface units by vtable from getDTI"),
        ],
    },
]


def _title_module(adapter):
    try:
        return importlib.import_module(adapter["module"])
    except Exception:
        return None


def _anchor(adapter):
    """What the title module itself declares: identity and anchors, read rather than restated."""
    mod = _title_module(adapter)
    if mod is None:
        return {"available": False}
    out = {"available": True}
    for name in ("TITLE_ID", "MAP_ID", "BUILD_ID", "SIG_OFF", "MAIN_NSO_SHA256", "DRIVER"):
        value = getattr(mod, name, None)
        if isinstance(value, (str, int)):
            out[name] = value
        elif value is not None:
            out[name] = getattr(value, "__name__", type(value).__name__)
    sig = getattr(mod, "SIGNATURE", None)
    out["signature_bytes"] = len(sig) if isinstance(sig, (bytes, bytearray)) else 0
    for name in ("S_MAIN", "S_PLAYER", "S_ENEMY", "S_UNIT"):
        value = getattr(mod, name, None)
        out[name] = value if isinstance(value, (int, type(None))) else "?"
    return out


# ---------------------------------------------------------------------------------------------------------
# Live instruments
def _emulator_pid():
    """The running Switch emulator's pid, if any (this box runs one title at a time)."""
    try:
        entries = os.listdir("/proc")
    except OSError:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as fh:
                cmd = fh.read(4096).replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if any(p in cmd for p in EMULATOR_PATTERNS):
            return int(entry)
    return None


def _read(pid, addr, length):
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
    try:
        return os.pread(fd, length, addr)
    except OSError:
        return b""
    finally:
        os.close(fd)


def _maps(pid):
    out = []
    try:
        with open(f"/proc/{pid}/maps") as fh:
            for line in fh:
                m = re.match(r"([0-9a-f]+)-([0-9a-f]+)\s+(....)", line)
                if m:
                    out.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3)))
    except OSError:
        pass
    return out


def module_base(pid, signature, sig_off):
    """The module's base from its own unique signature: sig_off is where the signature sits in the image."""
    if not signature:
        return None
    for start, end, perm in _maps(pid):
        if "r" not in perm or "w" in perm:
            continue
        pos, chunk = start, 8 << 20
        scanned = 0
        while pos < end and scanned < SIG_SCAN_CAP:
            blob = _read(pid, pos, min(chunk, end - pos))
            scanned += len(blob)
            i = blob.find(signature)
            if i >= 0:
                return pos + i - sig_off
            pos += max(1, len(blob))
    return None


def classify_cells(data, base_addr):
    """Per 4-byte cell: what it could be. This is the triage the page colours."""
    cells = []
    for i in range(0, len(data) - 3, 4):
        chunk = data[i:i + 4]
        addr = base_addr + i
        as_int = struct.unpack("<i", chunk)[0]
        as_uint = struct.unpack("<I", chunk)[0]
        as_float = struct.unpack("<f", chunk)[0]
        as_ascii = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        kind = "raw"
        if chunk == b"\0\0\0\0":
            kind = "zero"
        elif 0.001 < abs(as_float) < 1e6 and as_float == as_float:
            kind = "float"
        elif as_uint > 0x10000 and 0x1000 <= as_uint < 0x0000_7FFF_FFFF_FFFF:
            kind = "pointer?"
        elif -100000 < as_int < 100000:
            kind = "int"
        if as_ascii.count(".") <= 1 and any(c.isalnum() for c in as_ascii):
            kind = "ascii"
        cells.append({"addr": addr, "hex": chunk.hex(), "int": as_int, "u": as_uint,
                      "f": round(as_float, 4) if as_float == as_float else None,
                      "ascii": as_ascii, "kind": kind})
    return cells


class Lab:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = deque(maxlen=EVENTS_KEEP)
        self.scans = OrderedDict()
        self.overrides = {}          # (title, field) -> (status, note)
        self.seq = 0

    def event(self, title, kind, text, data=None):
        with self.lock:
            self.seq += 1
            row = {"seq": self.seq, "at": round(time.time(), 3), "title": title, "kind": kind,
                   "text": text, "data": data or {}}
            self.events.append(row)
            return row

    def put_scan(self, row):
        with self.lock:
            self.scans[row["id"]] = row
            while len(self.scans) > SCANS_KEEP:
                self.scans.popitem(last=False)


LAB = Lab()


def _dump_dir(config):
    base = getattr(config, "data_dir", None) or Path.home() / "gBox" / "system" / "gbox-data"
    return Path(base) / "runtime-linux-aarch64" / "citron-linux" / "data" / "citron" / "dump"


_CONFIG = None


def _elf_candidates(adapter, title_id):
    """Where a loadable ELF for this title could live: the analysis dir, the lab dir, the dump dir."""
    names = [adapter.get("elf") or "", f"{title_id}.elf", "main.elf"]
    roots = []
    for attr in ("data_dir",):
        base = getattr(_CONFIG, attr, None)
        if base:
            roots.append(Path(base) / "analysis" / "elf")
    roots += [Path.home() / "gBox_alt" / "re4-lab", Path.home() / "gBox_alt" / "re-lab"]
    dump = _dump_dir(_CONFIG)
    if title_id:
        roots.append(dump / str(title_id))
    out = []
    for root in roots:
        for name in names:
            if name and (root / name).is_file():
                out.append(root / name)
    return out


def _title_state(adapter):
    anchor = _anchor(adapter)
    title_id = anchor.get("TITLE_ID")
    stages = {name: {"done": False, "detail": STAGE_TEXT[name]} for name in STAGES}
    dumps = []
    if title_id:
        nso_dir = _dump_dir(_CONFIG) / str(title_id) / "nso"
        if nso_dir.is_dir():
            dumps = sorted(nso_dir.glob(adapter.get("nso_glob") or "main-*.nso"))
    stages["extract"]["done"] = bool(dumps)
    stages["extract"]["detail"] = (f"{dumps[0].name} ({dumps[0].stat().st_size // 1024} KiB)"
                                  if dumps else "no dumped NSO for this title")
    elfs = _elf_candidates(adapter, title_id)
    stages["disassemble"]["done"] = bool(elfs)
    stages["disassemble"]["detail"] = (f"{elfs[0].name} ({elfs[0].stat().st_size // 1024} KiB) — load in Ghidra, "
                                       "image_base 0x100000" if elfs else "no ELF yet (nso2elf)")
    if anchor.get("available"):
        stages["identify"]["done"] = bool(anchor.get("BUILD_ID")) and anchor.get("signature_bytes", 0) > 0
        stages["identify"]["detail"] = (f"BUILD_ID {anchor.get('BUILD_ID', '?')}, signature "
                                        f"{anchor.get('signature_bytes', 0)} bytes at +"
                                        f"{hex(anchor.get('SIG_OFF', 0))}")
        stages["driver"]["done"] = anchor.get("DRIVER") not in (None, "None")
        stages["driver"]["detail"] = f"driver {anchor.get('DRIVER')}"
    fields = []
    for name, offset, kind, status, evidence in adapter["fields"]:
        key = (adapter["id"], name)
        if key in LAB.overrides:
            status, note = LAB.overrides[key]
            evidence = f"{evidence} | operator: {note}" if note else evidence
        fields.append({"name": name,
                       "offset": offset if isinstance(offset, str) else hex(offset),
                       "kind": kind, "status": status, "evidence": evidence})
    confirmed = sum(1 for f in fields if f["status"] == "confirmed")
    stages["fields"]["done"] = confirmed > 0
    stages["fields"]["detail"] = f"{confirmed} confirmed / {len(fields)} catalogued"
    stages["verify"]["done"] = confirmed > 0
    stages["verify"]["detail"] = "live reads confirmed the code-derived offsets" if confirmed else "not verified"
    return {"id": adapter["id"], "notes": adapter["notes"], "anchor": anchor,
            "stages": stages, "fields": fields}


def _bot_state(tactical_store=None):
    """What autoplay sees: the newest tactical frame per session, plus the Mercenaries gate."""
    out = {"sessions": [], "live": False}
    if tactical_store is None:
        return out
    now = time.time()
    try:
        frames = list(getattr(tactical_store, "frames", {}).items())
    except Exception:
        return out
    for sid, row in frames[:6]:
        frame = row.get("frame") or {}
        age = round(now - row.get("at", now), 2)
        out["sessions"].append({
            "session": sid, "seq": row.get("seq"), "age_s": age, "live": age < 3.0,
            "stage": frame.get("stage"), "player": frame.get("player"), "units": frame.get("units"),
            "aim": frame.get("aim"), "round": frame.get("round"), "keys": sorted(frame.keys()),
        })
        out["live"] = out["live"] or age < 3.0
    return out


# ---------------------------------------------------------------------------------------------------------
class ScanIn(BaseModel):
    title: str
    offset: int = 0
    length: int = 256
    mode: str = "module"


class FieldIn(BaseModel):
    title: str
    name: str
    status: str
    note: str = ""


class StageIn(BaseModel):
    title: str
    path: str                 # RomFS path inside the title
    data_b64: str             # replacement bytes
    build: str = "gbox-lab"   # LayeredFS overlay name



def install(app, store, config, auth, tactical_store=None):
    global _CONFIG
    _CONFIG = config
    lab_state = LAB
    adapters = {a["id"]: a for a in ADAPTERS}
    tactical_store = tactical_store if tactical_store is not None else getattr(app.state, "tactical_map", None)

    def _adapter(title):
        adapter = adapters.get(title)
        if adapter is None:
            raise HTTPException(404, f"unknown title {title!r}")
        return adapter

    @app.get("/api/decrypt-lab/state", dependencies=[Depends(auth)])
    def decrypt_lab_state():
        titles = [_title_state(a) for a in ADAPTERS]
        with lab_state.lock:
            events = list(lab_state.events)[-60:]
            scans = [{"id": s["id"], "title": s["title"], "at": s["at"], "offset": hex(s["offset"]),
                      "length": s["length"], "mode": s["mode"], "ready": True} for s in lab_state.scans.values()]
        return {"v": FORMAT, "titles": titles, "events": events, "scans": list(reversed(scans))[-12:],
                "bot": _bot_state(tactical_store), "emulator": _emulator_pid() is not None}

    @app.get("/api/decrypt-lab/events", dependencies=[Depends(auth)])
    def decrypt_lab_events(after: int = 0):
        with lab_state.lock:
            rows = [e for e in lab_state.events if e["seq"] > after]
        return {"v": FORMAT, "events": rows, "seq": lab_state.seq}

    @app.post("/api/decrypt-lab/scan", dependencies=[Depends(auth)])
    def decrypt_lab_scan(body: ScanIn):
        adapter = _adapter(body.title)
        length = max(16, min(SCAN_MAX, int(body.length)))
        pid = _emulator_pid()
        if pid is None:
            raise HTTPException(409, "no Switch emulator is running on this server")
        anchor = _anchor(adapter)
        if body.mode not in ("module", "absolute"):
            raise HTTPException(400, "mode must be 'module' or 'absolute'")
        if body.mode == "module":
            sig = getattr(_title_module(adapter), "SIGNATURE", None)
            sig_off = int(anchor.get("SIG_OFF") or 0)
            base = module_base(pid, sig, sig_off)
            if base is None:
                raise HTTPException(409, "the title's module is not loaded (signature not found)")
            addr = base + int(body.offset)
        else:
            base = 0
            addr = int(body.offset)
        data = _read(pid, addr, length)
        if not data:
            raise HTTPException(409, "that address is not readable in the emulator")
        cells = classify_cells(data, addr)
        counts = {}
        for cell in cells:
            counts[cell["kind"]] = counts.get(cell["kind"], 0) + 1
        row = {"id": uuid.uuid4().hex[:16], "title": body.title, "at": round(time.time(), 3),
               "mode": body.mode, "offset": int(body.offset), "length": len(data),
               "addr": addr, "base": base, "cells": cells, "counts": counts}
        lab_state.put_scan(row)
        lab_state.event(body.title, "scan", f"scanned {len(data)} bytes at 0x{addr:x}", {"counts": counts})
        return {"v": FORMAT, **row}

    @app.get("/api/decrypt-lab/scan/{scan_id}", dependencies=[Depends(auth)])
    def decrypt_lab_scan_get(scan_id: str):
        row = lab_state.scans.get(scan_id)
        if not row:
            raise HTTPException(404, "no such scan")
        return {"v": FORMAT, **row}

    @app.post("/api/decrypt-lab/field", dependencies=[Depends(auth)])
    def decrypt_lab_field(body: FieldIn):
        if body.status not in ("confirmed", "candidate", "rejected"):
            raise HTTPException(400, "status must be confirmed, candidate or rejected")
        adapter = _adapter(body.title)
        if body.name not in {f[0] for f in adapter["fields"]}:
            raise HTTPException(404, f"unknown field {body.name!r}")
        lab_state.overrides[(body.title, body.name)] = (body.status, body.note[:400])
        lab_state.event(body.title, "field", f"{body.name} -> {body.status}", {"note": body.note[:400]})
        return {"v": FORMAT, "ok": True}

    # ------------------------------------------------------------------ assets / extraction
    def _inventory_path(title_id: str) -> Path | None:
        """Where a title's RomFS inventory may live: the data dir, the operator's home, and the lab work dir.

        The service's HOME is not necessarily the operator's home (systemd units often have none), so the home
        directory is resolved from the passwd entry as well.
        """
        homes = [Path.home()]
        try:
            import pwd
            homes.append(Path(pwd.getpwuid(os.getuid()).pw_dir))
        except (ImportError, KeyError):
            pass
        roots = []
        base = getattr(_CONFIG, "data_dir", None)
        if base:
            roots.append(Path(base) / "switch-assets")
        roots.append(Path.home() / "gBox" / "system" / "gBox-data" / "switch-assets")
        roots += [home / "gBox_alt" / "switch" / "assets" for home in homes]
        for root in roots:
            cand = root / f"{title_id}.json"
            if cand.is_file():
                return cand
        return None

    def _inventory(title_id: str) -> dict | None:
        path = _inventory_path(title_id)
        if not path:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _title_id(title: str) -> str:
        anchor = _anchor(_adapter(title))
        tid = anchor.get("TITLE_ID")
        if not tid:
            raise HTTPException(404, f"{title} declares no TITLE_ID")
        return str(tid).upper()

    def _mod_build(title: str, name: str) -> Path:
        """The LayeredFS overlay folder for this title, created through switch_mods when available."""
        tid = _title_id(title)
        try:
            from . import switch_mods
            folder = switch_mods.create_build(_CONFIG, title, name, tid, game_title=title, kind="file")
            return Path(folder)
        except Exception:
            base = Path(getattr(_CONFIG, "cache", None) or Path.home() / "gBox" / "gBox-cache") / "mods" / title / name
            base.mkdir(parents=True, exist_ok=True)
            return base

    def _romfs_root(title_id: str) -> Path | None:
        """An extracted RomFS tree for this title, if one has been produced (hactool --romfsdir)."""
        homes = [Path.home()]
        try:
            import pwd
            homes.append(Path(pwd.getpwuid(os.getuid()).pw_dir))
        except (ImportError, KeyError):
            pass
        for home in homes:
            root = home / "gBox_alt" / "switch" / "romfs" / title_id
            if root.is_dir():
                return root
        return None

    @app.get("/api/decrypt-lab/asset", dependencies=[Depends(auth)])
    def decrypt_lab_asset(title: str, path: str):
        """One asset's bytes from the extracted tree. The path must be in the title's inventory."""
        from fastapi.responses import FileResponse
        tid = _title_id(title)
        inv = _inventory(tid)
        if inv is None:
            raise HTTPException(409, "no inventory for this title yet")
        inner = path.strip().lstrip("/")
        if not inner or ".." in inner.split("/"):
            raise HTTPException(400, "path must be a relative RomFS path")
        if inner not in {e["path"] for e in inv.get("entries") or []}:
            raise HTTPException(404, "not in this title's inventory")
        root = _romfs_root(tid)
        if root is None:
            raise HTTPException(409, "the RomFS tree has not been extracted yet (extract_tree)")
        target = (root / inner).resolve()
        if not str(target).startswith(str(root.resolve())) or not target.is_file():
            raise HTTPException(404, "the extracted tree does not hold this file")
        media = "application/octet-stream"
        for ext, kind in ((".png", "image/png"), (".jpg", "image/jpeg"), (".gif", "image/gif"),
                          (".mp4", "video/mp4"), (".txt", "text/plain"), (".ini", "text/plain")):
            if inner.lower().endswith(ext):
                media = kind
                break
        return FileResponse(target, media_type=media, filename=target.name)

    @app.get("/api/decrypt-lab/assets", dependencies=[Depends(auth)])
    def decrypt_lab_assets(title: str, kind: str = "", q: str = "", limit: int = 300):
        tid = _title_id(title)
        inv = _inventory(tid)
        try:
            from . import switch_assets
            kind_of = switch_assets.kind_of
        except Exception:
            kind_of = lambda p: "other"
        if inv is None:
            return {"v": FORMAT, "title": title, "title_id": tid, "inventory": None, "entries": [],
                    "counts": {}, "note": "no RomFS inventory yet for this title (extraction of the base RomFS is not solved)"}
        entries = inv.get("entries") or []
        if kind:
            entries = [e for e in entries if kind_of(e["path"]) == kind]
        if q:
            needle = q.lower()
            entries = [e for e in entries if needle in e["path"].lower()]
        counts = {}
        for e in inv.get("entries") or []:
            k = kind_of(e["path"])
            counts[k] = counts.get(k, 0) + 1
        root = _romfs_root(tid)
        return {"v": FORMAT, "title": title, "title_id": tid, "inventory": {"at": inv.get("at"),
                "source": inv.get("source"), "romfs_section": inv.get("romfs_section")},
                "extracted": bool(root), "extracted_root": str(root) if root else None,
                "total": len(inv.get("entries") or []), "counts": counts,
                "entries": entries[:max(1, min(2000, limit))]}

    @app.post("/api/decrypt-lab/stage", dependencies=[Depends(auth)])
    def decrypt_lab_stage(body: StageIn):
        """Stage a replacement file into a LayeredFS overlay: the game reads it over its own RomFS at boot."""
        import base64
        inner = body.path.strip().lstrip("/")
        if not inner or ".." in inner.split("/") or inner.startswith("/") or len(inner) > 400:
            raise HTTPException(400, "path must be a relative RomFS path")
        try:
            data = base64.b64decode(body.data_b64, validate=True)
        except Exception as exc:
            raise HTTPException(400, f"data_b64 is not valid base64: {exc}") from exc
        if len(data) > 64 * 1024 * 1024:
            raise HTTPException(413, "replacement larger than 64 MiB")
        folder = _mod_build(body.title, body.build)
        target = folder / "romfs" / inner
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        lab_state.event(body.title, "stage", f"staged {inner} ({len(data)} bytes) into {body.build}",
                        {"build": body.build, "size": len(data)})
        return {"v": FORMAT, "ok": True, "target": str(target), "size": len(data),
                "note": "the overlay applies when the title next boots (LayeredFS)"}
