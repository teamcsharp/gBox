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


class SwapIn(BaseModel):
    """Replace one game asset with another game asset from the same title's RomFS."""
    title: str
    from_path: str            # the asset to replace (stays at this RomFS path)
    to_path: str              # the asset whose bytes are used instead
    build: str = "gbox-lab"   # LayeredFS overlay name


class ArcSwapIn(BaseModel):
    """Replace one model entry inside an MT Framework .arc, keeping the slot's own entry table."""
    title: str
    arc_path: str             # the .arc to patch (e.g. nativeNXx64/ImgNX/Archive/uWp06.arc)
    entry: str                # the entry inside it (e.g. pawn\wp\wp06\model\wep06_00_BM)
    donor_arc: str            # the .arc that supplies the replacement model
    donor_entry: str          # the entry inside the donor arc
    build: str = "gbox-lab"


class ModelSwapIn(BaseModel):
    """Swap a slot's whole model group with a donor archive's, without naming every entry.

    Used by the Mercenaries panel's character actions (clothes, cast, zombies): the first entry whose name contains
    '\\model\\' in each archive is the slot's model group, so the caller only names the two archives.
    """
    title: str
    arc_path: str
    donor_arc: str
    build: str = "gbox-lab"
    # objects also take the donor's mesh entries (its shape), not only its material maps. MEASURED BROKEN (2026-11-05,
    # twice): the title reaches select_player and then sits at screen=loading with a dark frame. The second attempt used
    # tag_follow so the donor's materials were internally consistent, and it still stalled - a donor mesh refers to
    # parts/materials the slot archive does not carry. Kept for experiments; the panel never sets it.
    with_mesh: bool = False
    tag_follow: bool = False  # a map of another size moves too, its tag travelling with it (an experiment)


class StripClothesIn(BaseModel):
    """Repaint a character's clothing groups with its own body skin maps (the 'remove clothes' action).

    A character archive holds a body group and separate clothing groups, each with a base/mask/normal map. Copying
    the body's maps over the clothing groups' maps of the same tag (same dimensions and format) leaves the
    character's skin everywhere the clothing was; a mismatched tag is skipped instead of corrupting the slot.
    """
    title: str
    arc_path: str
    build: str = "gbox-lab"



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

    def _game_id_for(title: str) -> str:
        """The catalog game id a mod build must be keyed by (the lab's shorthand is not it).

        gBox resolves a launch's mod through the catalog game id, so a build filed under 're5_switch' is invisible
        to the launcher. Match the title id against the catalog's serial and use that entry's game id.
        """
        tid = _title_id(title)
        try:
            rows = store.db.execute(
                "SELECT game_id, body FROM catalog WHERE json_extract(body,'$.platform')='switch'").fetchall()
            for game_id, body in rows:
                try:
                    entry = json.loads(body)
                except (TypeError, ValueError):
                    continue
                if str(entry.get("serial") or "").upper() == tid:
                    return str(game_id)
        except Exception:
            pass
        return title

    def _mod_build(title: str, name: str) -> Path:
        """The LayeredFS overlay folder for this title, created through switch_mods when available."""
        tid = _title_id(title)
        game_id = _game_id_for(title)
        try:
            from . import switch_mods
            folder = switch_mods.create_build(_CONFIG, game_id, name, tid, game_title=title, kind="file")
            return Path(folder)
        except Exception:
            base = Path(getattr(_CONFIG, "cache", None) or Path.home() / "gBox" / "gBox-cache") / "mods" / game_id / name
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

    @app.get("/api/decrypt-lab/preview", dependencies=[Depends(auth)])
    def decrypt_lab_preview(title: str, path: str):
        """A thumbnail for one asset. Images pass through; videos (USM/MP4) are decoded with ffmpeg."""
        try:
            return _preview(title, path)
        except HTTPException:
            raise
        except Exception as exc:                      # surface the cause instead of an opaque 500
            raise HTTPException(500, f"preview failed: {type(exc).__name__}: {exc}") from exc

    def _preview(title: str, path: str):
        from fastapi.responses import FileResponse
        import shutil
        import subprocess
        tid = _title_id(title)
        root = _romfs_root(tid)
        if root is None:
            raise HTTPException(409, "the RomFS tree has not been extracted yet")
        inner = path.strip().lstrip("/")
        if not inner or ".." in inner.split("/"):
            raise HTTPException(400, "path must be a relative RomFS path")
        target = (root / inner).resolve()
        if not str(target).startswith(str(root.resolve())) or not target.is_file():
            raise HTTPException(404, "the extracted tree does not hold this file")
        lower = inner.lower()
        if lower.endswith((".png", ".jpg", ".jpeg", ".gif")):
            return FileResponse(target)
        if not lower.endswith((".usm", ".mp4", ".webm")):
            raise HTTPException(415, "no previewer for this asset type yet")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise HTTPException(409, "ffmpeg is not installed on this server")
        cache = Path(getattr(_CONFIG, "cache", Path.home() / "gBox" / "gbox-cache")) / "previews"
        cache.mkdir(parents=True, exist_ok=True)
        thumb = cache / (uuid.uuid5(uuid.NAMESPACE_URL, f"{tid}/{inner}").hex + ".png")
        if not thumb.is_file() or thumb.stat().st_mtime < target.stat().st_mtime:
            # Some USM containers refuse a seek, and many clips open on a fade. Try a representative frame and a
            # few timestamps, then keep the brightest — a black first frame makes a useless preview.
            attempts = (
                [ffmpeg, "-v", "error", "-y", "-i", str(target), "-vf", "thumbnail,scale=480:-1",
                 "-frames:v", "1"],
                [ffmpeg, "-v", "error", "-y", "-ss", "5", "-i", str(target), "-frames:v", "1",
                 "-vf", "scale=480:-1"],
                [ffmpeg, "-v", "error", "-y", "-ss", "20", "-i", str(target), "-frames:v", "1",
                 "-vf", "scale=480:-1"],
                [ffmpeg, "-v", "error", "-y", "-ss", "45", "-i", str(target), "-frames:v", "1",
                 "-vf", "scale=480:-1"],
            )
            best, best_score, errors = None, -1.0, []
            for attempt_index, cmd in enumerate(attempts):
                # one unique temp per attempt: reusing a name made a better-scoring frame overwrite (and then
                # delete) the previous best, so the final move failed
                tmp = thumb.with_suffix(f".{attempt_index}.tmp.png")
                proc = subprocess.run([*cmd, str(tmp)], capture_output=True, text=True, timeout=180)
                if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
                    errors.append((proc.stderr or "").strip()[-120:])
                    tmp.unlink(missing_ok=True)
                    continue
                score = 0.0
                try:
                    from PIL import Image, ImageStat
                    with Image.open(tmp) as im:
                        score = sum(ImageStat.Stat(im.convert("RGB")).mean) / 3
                except Exception:
                    score = 1.0 if tmp.stat().st_size > 4000 else 0.0
                if score > best_score:
                    if best is not None:
                        best.unlink(missing_ok=True)
                    best, best_score = tmp, score
                else:
                    tmp.unlink(missing_ok=True)
            if best is None:
                raise HTTPException(415, "ffmpeg could not decode this file: " + " | ".join(e for e in errors if e))
            best.replace(thumb)
        return FileResponse(thumb, media_type="image/png")

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

    @app.post("/api/decrypt-lab/swap", dependencies=[Depends(auth)])
    def decrypt_lab_swap(body: SwapIn):
        """Swap one game asset for another: B's bytes are written over A's RomFS path in the overlay.

        This is the mine / grenade / skin primitive: keep the slot the game asks for and supply another asset's
        bytes there, so a placed mine can render an item model or a character can wear another character's skin.
        Both paths must already exist in the title's extracted RomFS tree.
        """
        tid = _title_id(body.title)
        root = _romfs_root(tid)
        if root is None:
            raise HTTPException(409, "the RomFS tree has not been extracted yet (extract_tree)")
        inner_from = body.from_path.strip().lstrip("/")
        inner_to = body.to_path.strip().lstrip("/")
        for inner in (inner_from, inner_to):
            if not inner or len(inner) > 400 or inner.startswith("/") or ".." in inner.split("/"):
                raise HTTPException(400, "paths must be relative RomFS paths")
        source = (root / inner_to).resolve()
        if not str(source).startswith(str(root.resolve())) or not source.is_file():
            raise HTTPException(404, "the extracted tree does not hold the replacement asset")
        size = source.stat().st_size
        if size > 64 * 1024 * 1024:
            raise HTTPException(413, "replacement asset larger than 64 MiB")
        folder = _mod_build(body.title, body.build)
        target = folder / "romfs" / inner_from
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        lab_state.event(body.title, "swap", f"swapped {inner_from} <- {inner_to} ({size} bytes) into {body.build}",
                        {"build": body.build, "size": size, "from": inner_from, "to": inner_to})
        return {"v": FORMAT, "ok": True, "target": str(target), "source": str(source), "size": size,
                "note": "the overlay applies when the title next boots (LayeredFS)"}

    @app.post("/api/decrypt-lab/strip-clothes", dependencies=[Depends(auth)])
    def decrypt_lab_strip_clothes(body: StripClothesIn):
        """Repaint a character's clothing groups with its body skin maps: the MercMode panel's 'remove clothes'.

        The body group is the model group whose base map is largest (the body carries the most skin pixels); every
        other group's base/mask/normal map is replaced by the body's map of the SAME tag (same dimensions and
        format), so only format-compatible slots are touched and a mismatch is reported instead of corrupting the
        character's materials.
        """
        from . import mt_arc
        tid = _title_id(body.title)
        root = _romfs_root(tid)
        if root is None:
            raise HTTPException(409, "the RomFS tree has not been extracted yet (extract_tree)")
        inner = (body.arc_path or "").strip().lstrip("/")
        if not inner or len(inner) > 400 or inner.startswith("/") or ".." in inner.split("/"):
            raise HTTPException(400, "path must be a relative RomFS path")
        arc_file = (root / inner).resolve()
        if not str(arc_file).startswith(str(root.resolve())) or not arc_file.is_file():
            raise HTTPException(404, "the extracted tree does not hold that archive")
        try:
            arc = mt_arc.parse(arc_file.read_bytes())
        except mt_arc.ArcError as exc:
            raise HTTPException(400, str(exc)) from exc

        def group_of(name: str):
            """(directory, group, map) for a '...\\model\\<group>_<map>' entry, else None."""
            base = name.rsplit("\\", 1)[-1]
            if "\\model\\" not in name:
                return None
            for suffix in ("_BM", "_MM", "_NM"):
                if base.endswith(suffix):
                    directory = name.rsplit("\\", 2)[0]          # ...\model
                    return directory, base[:-len(suffix)], suffix[1:]
            return None

        groups: dict = {}
        for entry in arc.entries:
            parsed = group_of(entry.name)
            if parsed:
                groups.setdefault((parsed[0], parsed[1]), {})[parsed[2]] = entry
        # The body is a character model group ('pawn\pl\...') whose own '_01' base map is the largest: the body group
        # carries the skin; clothing is every other group in that SAME directory (effect\tex\... is never touched).
        characters = {k: v for k, v in groups.items()
                      if k[0].lower().startswith("pawn\\pl\\") and v.get("BM")}
        if not characters:
            raise HTTPException(404, "this archive holds no character model (pawn\\pl\\...\\model)")
        # The body is the character's own skin group: the 'evfXXXX_01' base set both characters use, else a group
        # named Body/Skin, else a '_01' group, else the largest. Clothing/armour is everything else in the directory.
        base = {k: v for k, v in characters.items() if k[1].lower().startswith("evf") and "_01" in k[1]}
        named = {k: v for k, v in characters.items() if any(w in k[1].lower() for w in ("body", "skin"))}
        prime = base or named or {k: v for k, v in characters.items() if "_01" in k[1]} or characters
        body_group, body_maps = max(prime.items(), key=lambda kv: kv[1]["BM"].size)
        body_dir = body_group[0]
        replaced, skipped, patched_entries = [], [], []
        for (directory, group), maps in characters.items():
            if directory != body_dir or group == body_group[1]:
                continue
            for kind in ("BM", "MM", "NM"):
                dst, src = maps.get(kind), body_maps.get(kind)
                if dst is None or src is None:
                    continue
                if dst.tag != src.tag:                     # different dimensions/format: leave the slot alone
                    skipped.append(dst.name)
                    continue
                patched_entries.append((dst.name, src.data))
                replaced.append(dst.name)
        if not replaced:
            raise HTTPException(409, "no clothing map shares the body's format: nothing could be repainted safely")
        data = arc_file.read_bytes()
        for name, payload in patched_entries:
            data = mt_arc.replace(data, name, payload)
        folder = _mod_build(body.title, body.build)
        target = folder / "romfs" / inner
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        lab_state.event(body.title, "strip-clothes",
                        f"{len(replaced)} clothing map(s) repainted with {body_group[1]}'s skin in {inner}",
                        {"build": body.build, "replaced": len(replaced), "skipped": len(skipped)})
        return {"v": FORMAT, "ok": True, "target": str(target), "size": len(data), "body_group": body_group[1],
                "replaced": replaced[:64], "skipped": skipped[:64],
                "note": "the overlay applies when the title next boots (LayeredFS)"}

    @app.post("/api/decrypt-lab/arc-swap", dependencies=[Depends(auth)])
    def decrypt_lab_arc_swap(body: ArcSwapIn):
        """Swap one model entry inside an .arc: the slot keeps its name, the donor's bytes replace the payload.

        This is the in-slot model swap (a character wearing another character's model, a mine rendering another
        object). The destination archive's entry table is preserved, so the game still finds the names it asks for.
        """
        from . import mt_arc
        tid = _title_id(body.title)
        root = _romfs_root(tid)
        if root is None:
            raise HTTPException(409, "the RomFS tree has not been extracted yet (extract_tree)")

        def resolve(inner: str) -> Path:
            inner = (inner or "").strip().lstrip("/")
            if not inner or len(inner) > 400 or inner.startswith("/") or ".." in inner.split("/"):
                raise HTTPException(400, "paths must be relative RomFS paths")
            target = (root / inner).resolve()
            if not str(target).startswith(str(root.resolve())) or not target.is_file():
                raise HTTPException(404, f"the extracted tree does not hold {inner}")
            return target

        arc_file = resolve(body.arc_path)
        donor_file = resolve(body.donor_arc)
        try:
            donor = mt_arc.parse(donor_file.read_bytes())
        except mt_arc.ArcError as exc:
            raise HTTPException(400, f"donor archive: {exc}") from exc
        donor_entry = donor.find(body.donor_entry)
        if donor_entry is None:
            raise HTTPException(404, "the donor archive has no such entry")
        try:
            patched = mt_arc.replace(arc_file.read_bytes(), body.entry, donor_entry.data)
        except mt_arc.ArcError as exc:
            raise HTTPException(400, str(exc)) from exc
        folder = _mod_build(body.title, body.build)
        target = folder / "romfs" / body.arc_path.strip().lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(patched)
        lab_state.event(body.title, "arc-swap",
                        f"{body.entry} <- {body.donor_entry} ({len(donor_entry.data)} B) in {body.arc_path}",
                        {"build": body.build, "size": len(donor_entry.data), "arc": body.arc_path})
        return {"v": FORMAT, "ok": True, "target": str(target), "size": len(patched),
                "entry_bytes": len(donor_entry.data),
                "note": "the overlay applies when the title next boots (LayeredFS)"}

    @app.get("/api/decrypt-lab/swap-matrix", dependencies=[Depends(auth)])
    def decrypt_lab_swap_matrix(title: str):
        """Which swaps of this title's slots are actually possible: a donor moves only the maps whose tag matches.

        The panel asks before it offers a pair, so an action can never be clicked into a refusal: gbox.skin_swap
        refuses a donor whose maps are a different size or format, and most enemy/character pairs are.
        """
        from . import mt_arc, skin_swap
        tid = _title_id(title)
        root = _romfs_root(tid)
        if root is None:
            raise HTTPException(409, "the RomFS tree has not been extracted yet (extract_tree)")
        arcs = dict(skin_swap.CHARACTER_ARCS.get(str(tid).upper()) or {})
        arcs.update({"uEm6c": "nativeNXx64/ImgNX/Archive/uEm6c.arc",
                     "uEm71": "nativeNXx64/ImgNX/Archive/uEm71.arc",
                     "mine": "nativeNXx64/ImgNX/Archive/uWp06.arc",
                     "mine2": "nativeNXx64/ImgNX/Archive/uWp07.arc",
                     "grenade": "nativeNXx64/ImgNX/Archive/uWp0a.arc"})
        tags: dict = {}
        for name, inner in arcs.items():
            path = root / inner
            if not path.is_file():
                continue
            try:
                parsed = mt_arc.parse(path.read_bytes())
            except mt_arc.ArcError:
                continue
            groups = skin_swap.material_groups(parsed)
            body = skin_swap.body_group(groups)
            if body is None:
                continue
            tags[name] = {k: v.tag for k, v in groups[body].items()}
        pairs = {}
        for slot, slot_maps in tags.items():
            for donor, donor_maps in tags.items():
                if slot == donor:
                    continue
                moved = [k for k in ("BM", "MM", "NM") if slot_maps.get(k) is not None
                         and slot_maps.get(k) == donor_maps.get(k)]
                pairs[f"{slot}|{donor}"] = {"maps": moved, "ok": bool(moved)}
        return {"v": FORMAT, "arcs": arcs, "tags": tags, "pairs": pairs}

    @app.get("/api/decrypt-lab/triage", dependencies=[Depends(auth)])
    def decrypt_lab_triage():
        """The inbox by class, next to the inference fleet that has to work it off.

        What is waiting, how old the oldest is, and how many lanes can take it: the page can show a queue that is
        actually draining (or one that is not) instead of a raw list of thousands.
        """
        from . import hermes_pool

        def klass(title: str) -> str:
            """The inbox by what a ticket IS: generated classes first, then the standing per-game work, then the
            operator's own words (the largest bucket was "other" only because nothing named it - it is operator
            requests and the named lanes like "RAM hook: RE5")."""
            t = (title or "").casefold()
            for key, label in (("rank_not_verified", "rank not verified"),
                               ("<agent-message", "agent message"),
                               ("launch failed", "launch failure"),
                               ("mercenaries", "mercenaries"),
                               ("ram hook", "RAM hook"),
                               ("damage batch", "damage evidence"),
                               ("autoplay coaching", "autoplay coaching"),
                               ("session models", "session models"),
                               ("improve ", "improve a title")):
                if t.startswith(key) if key in ("improve ",) else key in t:
                    return label
            if t.startswith("unlock"):
                return "unlocked content"
            if "character replacement" in t:
                return "character replacement"
            return "operator request"

        buckets: dict = {}
        total = open_total = 0
        rows = store.all("request")
        total = len(rows)
        for row in rows:
            if str(row.get("status") or "").casefold() not in ("open", "new", "in_progress", "pending"):
                continue
            open_total += 1
            name = klass(str(row.get("title") or ""))
            bucket = buckets.setdefault(name, {"class": name, "open": 0, "oldest": None})
            bucket["open"] += 1
            created = row.get("created")
            if isinstance(created, (int, float)) and (bucket["oldest"] is None or created < bucket["oldest"]):
                bucket["oldest"] = created
        nodes = []
        try:
            for name, node in hermes_pool.node_settings().items():
                nodes.append({"name": name, "enabled": bool(getattr(node, "enabled", False)),
                              "lanes": getattr(node, "max_parallel_jobs", None),
                              "upstream": getattr(node, "upstream", None)})
        except Exception:                                        # noqa: BLE001 - the page shows what it can
            pass
        return {"v": FORMAT, "total": total, "open": open_total,
                "classes": sorted(buckets.values(), key=lambda b: -b["open"]),
                "fleet": {"nodes": nodes, "lanes": sum(n["lanes"] or 0 for n in nodes if n["enabled"])},
                "at": time.time()}

    @app.post("/api/decrypt-lab/model-swap", dependencies=[Depends(auth)])
    def decrypt_lab_model_swap(body: ModelSwapIn):
        """Swap a slot's character skin with a donor archive's (the panel's clothes / cast / zombie actions).

        Both archives' body skin groups are resolved (evfXXXX_01, else Body/Skin, else the largest base map) and the
        slot's base/mask/normal maps are replaced: the FIRST `\\model\\` entry is a stub on real characters, so it is
        never used as the model. The entry swapped is reported, so the operator can see exactly what moved.
        """
        from . import mt_arc, skin_swap
        tid = _title_id(body.title)
        root = _romfs_root(tid)
        if root is None:
            raise HTTPException(409, "the RomFS tree has not been extracted yet (extract_tree)")

        def resolve(inner: str) -> Path:
            inner = (inner or "").strip().lstrip("/")
            if not inner or len(inner) > 400 or inner.startswith("/") or ".." in inner.split("/"):
                raise HTTPException(400, "paths must be relative RomFS paths")
            target = (root / inner).resolve()
            if not str(target).startswith(str(root.resolve())) or not target.is_file():
                raise HTTPException(404, f"the extracted tree does not hold {inner}")
            return target

        arc_file = resolve(body.arc_path)
        donor_file = resolve(body.donor_arc)
        try:
            data, slot_group, donor_group = skin_swap.swap_arc(arc_file.read_bytes(), donor_file.read_bytes(),
                                                              follow_tag=bool(body.tag_follow))
        except mt_arc.ArcError as exc:
            raise HTTPException(400, str(exc)) from exc
        meshes = []
        moved_maps = []
        try:                                   # which maps actually moved: a 2/3 swap keeps one map of the slot's own
            slot_arc, donor_arc = mt_arc.parse(arc_file.read_bytes()), mt_arc.parse(donor_file.read_bytes())
            slot_maps = skin_swap.material_groups(slot_arc).get(slot_group) or {}
            donor_maps = skin_swap.material_groups(donor_arc).get(donor_group) or {}
            moved_maps = [k for k in ("BM", "MM", "NM")
                          if slot_maps.get(k) is not None and donor_maps.get(k) is not None
                          and (body.tag_follow or slot_maps[k].tag == donor_maps[k].tag)]
            kept = [k for k in ("BM", "MM", "NM") if k not in moved_maps and slot_maps.get(k) is not None]
            if kept:
                moved_maps.append(f"kept:{','.join(kept)}")
            retagged = [k for k in moved_maps if k in ("BM", "MM", "NM")
                        and slot_maps[k].tag != donor_maps[k].tag]
            if retagged:
                moved_maps.append(f"retagged:{','.join(retagged)}")
        except mt_arc.ArcError:
            pass
        if body.with_mesh:
            # an object's shape lives in the entries named after its group (uWp06.arc carries two `wp0600`: the placed
            # mine's mesh), so those travel with the material maps when the operator asks for the whole object
            slot_arc, donor_arc = mt_arc.parse(arc_file.read_bytes()), mt_arc.parse(donor_file.read_bytes())

            def mesh_indices(arc, group):
                named = [i for i, e in enumerate(arc.entries)
                         if "\\model\\" in e.name and e.name.rsplit("\\", 1)[-1] == group]
                if named:
                    return named
                # a donor whose mesh is not named after its material group (uWp0a's grenade mesh is wep0a_00, its
                # materials om4e00): the largest model entry that is not a base/mask/normal map is that mesh
                maps = {i for i, e in enumerate(arc.entries)
                        if e.name.rsplit("\\", 1)[-1].endswith(("_BM", "_MM", "_NM"))}
                candidates = [i for i, e in enumerate(arc.entries) if "\\model\\" in e.name and i not in maps]
                return [max(candidates, key=lambda i: arc.entries[i].size)] if candidates else []

            for slot_i, donor_i in zip(mesh_indices(slot_arc, slot_group), mesh_indices(donor_arc, donor_group)):
                data = mt_arc.replace_at(data, slot_i, donor_arc.entries[donor_i].data)
                meshes.append(slot_arc.entries[slot_i].name)
        folder = _mod_build(body.title, body.build)
        target = folder / "romfs" / body.arc_path.strip().lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        lab_state.event(body.title, "model-swap",
                        f"{slot_group} <- {donor_group} skin ({len(data)} B) in {body.arc_path}",
                        {"build": body.build, "size": len(data)})
        return {"v": FORMAT, "ok": True, "target": str(target), "size": len(data),
                "slot": slot_group, "donor": donor_group, "mesh": meshes, "maps": moved_maps,
                "note": "the overlay applies when the title next boots (LayeredFS)"}
