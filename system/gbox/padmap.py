"""Controller maps: which control on the operator's pad drives which console function, per platform.

The play view's controller picture opens "Map N64 C-up to..." on right-click (clients/web/viz/pad-map.js). A map is
{source: output} over RetroPad names, identity by default - the model of RetroArch's own remap files:

    source = the physical control, named the way RetroArch's positional autoconfig names it
             (Xbox A = "b", B = "a", X = "y", Y = "x", RB = "r", LT = "l2", right stick up = "rup", ...)
    output = the RetroPad input the core receives ("rup" = right analog up = C-up on parallel-n64 / mupen64plus-next)

Default N64 layout (the cores' own, made explicit): N64 stick = left stick, C buttons = right stick, A = Xbox A,
B = Xbox X, Z = LT, L/R = LB/RB, Start = Menu; holding RT is the cores' "C buttons mode" (an extra).

Stored on the control plane (store "setting"/"controller_maps"), so every PC and every launch uses the same map:
  - streamed games: the web client maps the pad before forwarding it (pad-map.js read())
  - native RetroArch windows (Windows): the worker writes the core's remap file at launch (apply_retroarch).
    RetroArch applies remaps to the physical pad only, never to its network RetroPad (input_state_device: "Don't
    process binds if input is coming from Remote RetroPad"), so the two paths never map twice.

    register(app, auth)          GET/POST /api/controller-maps[/{platform}]
    fetch(server, headers, p)    worker: the platform's map at launch (None when the server can't say)
    apply_retroarch(...)         worker: <remap dir>/<core library name>/<core library name>.rmp
"""
import re
import time
from pathlib import Path

SETTING = "controller_maps"
# RETRO_DEVICE_ID_JOYPAD_* 0-15, then RetroArch's analog binds 16-23 (RARCH_ANALOG_LEFT_X_PLUS ... RIGHT_Y_MINUS):
# the ids an .rmp file assigns (configuration.c input_remapping_load_file key_strings)
BUTTONS = ("b", "y", "select", "start", "up", "down", "left", "right", "a", "x", "l", "r", "l2", "r2", "l3", "r3")
STICK_DIRS = ("lright", "lleft", "ldown", "lup", "rright", "rleft", "rdown", "rup")
RA_ID = {name: i for i, name in enumerate(BUTTONS + STICK_DIRS)}
RA_STK = {"lright": "l_x+", "lleft": "l_x-", "ldown": "l_y+", "lup": "l_y-",
          "rright": "r_x+", "rleft": "r_x-", "rdown": "r_y+", "rup": "r_y-"}
FAMILIES = {"n64": "n64", "n64dd": "n64", "nintendo64": "n64"}
# consoles whose sticks are console inputs (sources and outputs); every other console maps its buttons only, and the
# web client keeps its "left stick as d-pad" switch for them
STICK_FAMILIES = {"n64"}
# retro_get_system_info().library_name: RetroArch names the remap folder and file after it (config_load_remap).
# Checked against the cores' sources and the installed parallel_n64_libretro.dll / .info files.
CORE_LIBRARY = {"parallel_n64": "ParaLLEl N64", "mupen64plus_next": "Mupen64Plus-Next"}
MARK = "# gBox controller map"


def family(platform) -> str:
    """The key a map is saved under: the console family (n64 and n64dd share one controller)."""
    key = re.sub(r"[^a-z0-9]", "", str(platform or "").lower())
    if key in FAMILIES:
        return FAMILIES[key]
    return "n64" if "nintendo64" in key else key


def names(fam: str) -> tuple[str, ...]:
    """Sources a map may move for this family; outputs are the same names (identity is the default)."""
    return BUTTONS + STICK_DIRS if fam in STICK_FAMILIES else BUTTONS


def clean(fam: str, m) -> dict:
    """A valid map for `fam` without identity entries. Raises ValueError on anything else."""
    if m is None:
        return {}
    if not isinstance(m, dict):
        raise ValueError("a controller map is an object {control: function}")
    ok = set(names(fam))
    out = {}
    for src, dst in m.items():
        if src not in ok:
            raise ValueError(f"{src!r} is not a control gBox maps for {fam or 'this console'}")
        if dst not in ok:
            raise ValueError(f"{dst!r} is not an input {fam or 'this console'} can receive")
        if src != dst:
            out[src] = dst
    return out


def _valid_family(fam: str) -> str:
    if not re.fullmatch(r"[a-z0-9]{1,40}", fam or ""):
        raise ValueError("unknown platform")
    return fam


def _all(store) -> dict:
    rec = store.get("setting", SETTING) or {}
    return rec if isinstance(rec, dict) else {}


def get(store, platform) -> dict:
    fam = family(platform)
    try:
        return clean(fam, (_all(store).get("maps") or {}).get(fam) or {})
    except ValueError:                                  # a stored map from an older layout: the default again
        return {}


def put(store, platform, m, actor: str = "") -> dict:
    fam = _valid_family(family(platform))
    m = clean(fam, m)
    rec = _all(store)
    maps, updated = dict(rec.get("maps") or {}), dict(rec.get("updated") or {})
    if m:
        maps[fam] = m
    else:
        maps.pop(fam, None)                             # empty = the console's default layout
    updated[fam] = {"by": actor, "at": time.time()}
    store.put("setting", SETTING, {"maps": maps, "updated": updated})
    return m


def rmp_text(fam: str, m) -> str:
    """RetroArch remap file for Player 1: every control's target id (identity unless the map moves it).

    RetroArch moves stick axes as wholes: once either direction of a physical axis is remapped, input_state_device
    zeroes that axis and only remapped directions come back (the poll loop skips identity ones). The web dialog never
    moves one direction alone on a single bind (pad-map.js bind) and warns when a map does it anyway."""
    m = clean(fam, m)
    lines = [f"{MARK} ({fam or 'console'}): right-click the controller picture in gBox's play view to change it"]
    lines += [f'input_player1_btn_{name} = "{RA_ID[m.get(name, name)]}"' for name in BUTTONS]
    if fam in STICK_FAMILIES:
        lines += [f'input_player1_stk_{RA_STK[name]} = "{RA_ID[m.get(name, name)]}"' for name in STICK_DIRS]
    return "\n".join(lines) + "\n"


def _info_library(stem: str, dirs) -> str | None:
    """corename from the core's .info file (RetroArch keeps them in info/ next to its executable)."""
    for d in dirs:
        try:
            text = (Path(d) / f"{stem}.info").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r'^\s*corename\s*=\s*"([^"]+)"', text, re.M)
        if m:
            return m.group(1)
    return None


def core_library(core, info_dirs=()) -> str | None:
    """The core's library_name, which RetroArch uses for its remap folder ("ParaLLEl N64")."""
    core = Path(str(core))
    short = re.sub(r"_libretro$", "", core.stem)
    if short in CORE_LIBRARY:
        return CORE_LIBRARY[short]
    return _info_library(core.stem, [*info_dirs, core.parent / "info", core.parent.parent / "info", core.parent])


def remap_path(directory: Path, library: str) -> Path | None:
    if not library or re.search(r'[\\/:*?"<>|]', library) or library.strip(". ") != library:
        return None                                      # not a name RetroArch could have made a folder of
    return Path(directory) / library / f"{library}.rmp"


def write_core_remap(directory: Path, library: str, text: str | None) -> Path | None:
    """Write (or with text=None remove gBox's own) core remap file. A file gBox didn't write (saved from RetroArch's
    menu) is never removed, and is kept once as <name>.rmp.gbox-original before gBox's map replaces it."""
    path = remap_path(directory, library)
    if path is None:
        return None
    try:
        old = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        old = None
    if text is None:
        if old is not None and old.startswith(MARK):
            path.unlink(missing_ok=True)
        return None
    if old == text:
        return path
    if old is not None and not old.startswith(MARK):
        backup = path.with_name(path.name + ".gbox-original")
        if not backup.exists():
            backup.write_text(old, encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".rmp.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def apply_retroarch(directory: Path, core, platform, m, info_dirs=()) -> Path | None:
    """At a native launch: the platform's map as the core's RetroArch remap file.

    m=None (the server could not be asked): an existing file stays as it was; with none yet, the default is written.
    N64 always gets a file (its default layout written out); other consoles only while they have a map."""
    fam = family(platform)
    library = core_library(core, info_dirs)
    path = remap_path(directory, library) if library else None
    if path is None:
        return None
    if m is None:
        if path.exists():
            return path
        m = {}
    m = clean(fam, m)
    if fam not in STICK_FAMILIES and not m:
        write_core_remap(directory, library, None)
        return None
    return write_core_remap(directory, library, rmp_text(fam, m))


def fetch(server: str, headers: dict | None, platform, timeout: float = 5.0) -> dict | None:
    """Worker: the saved map for this platform, or None when the control plane can't be asked (never raises)."""
    if not server:
        return None
    fam = family(platform)
    try:
        import httpx
        r = httpx.get(f"{server}/api/controller-maps/{fam}", headers=headers or {}, timeout=timeout)
        r.raise_for_status()
        return clean(fam, (r.json() or {}).get("map") or {})
    except Exception:                                     # noqa: BLE001 - a launch never waits on this
        return None


def register(app, auth_dependency) -> None:
    from fastapi import Depends, HTTPException
    from pydantic import BaseModel

    class MapIn(BaseModel):
        map: dict = {}

    def store():
        return app.state.store

    @app.get("/api/controller-maps")
    def controller_maps(actor=Depends(auth_dependency)):
        """Every console's controller map ({family: {control: input}}); a console without one uses its default layout."""
        rec = _all(store())
        out = {}
        for fam, m in (rec.get("maps") or {}).items():
            try:
                cm = clean(fam, m)
            except ValueError:
                continue
            if cm:
                out[fam] = cm
        return {"maps": out, "updated": rec.get("updated") or {}}

    @app.get("/api/controller-maps/{platform}")
    def controller_map(platform: str, actor=Depends(auth_dependency)):
        fam = family(platform)
        return {"platform": fam, "map": get(store(), fam), "sticks": fam in STICK_FAMILIES}

    @app.post("/api/controller-maps/{platform}")
    def controller_map_set(platform: str, body: MapIn, actor=Depends(auth_dependency)):
        """Save a console's controller map (an empty map = its default layout). Streamed games use it at once; games in
        a native RetroArch window from their next start (the worker writes the core's remap file at launch)."""
        try:
            m = put(store(), platform, body.map, str(actor or ""))
        except ValueError as e:
            raise HTTPException(422, str(e))
        fam = family(platform)
        store().audit(str(actor or ""), "controller_map.set", fam, {"map": m})
        return {"platform": fam, "map": m, "sticks": fam in STICK_FAMILIES}
