"""`gta_live`: live GTA state as functions for the LLM (the in-game side of Ariane, on gBox's read/write_memory).

Ariane (Dryxio/ariane, https://github.com/Dryxio/ariane) is a GTA III / Vice City / San Andreas map viewer and editor
(aap's euryopa on librw). Its in-game half (ariane.asi, plugin-sdk) teleports the player and drives time and weather
while you edit. Ariane is GPL (it links LZO), so gBox vendors none of its code and does not run its editor or ASI; this
module gives the LLM the same live controls on the operator's own GTA sessions by reading and writing game memory:

  games | resolve | pools | player | vehicles | weather | time | wanted | teleport | spawn

Every write goes through gta_mods_tool.Mem: data memory only (never code), confirmed by read-back, with the previous
bytes returned so the change can be undone. Nothing on disk is touched; game files are never modified.

Address provenance. Each field carries `source` and `live_checked`. Every field here is live_checked=False: the values
come from gBox's gta_mods table (gbox/gta_games.py, which those mods use live) or are resolved from the game's own ELF
symbol table (op=resolve; GTA III's PS2 ELF ships its .symtab), with struct layouts from re3 where noted. A field that
no source gives is absent and the op says so, naming the playbook to map it (memory_search / re_dossier) instead of
guessing.

Owned versions (catalog, 2026-10-12):
  gta3  GTA III PS2 SLUS-20062   265819390074bb4e, 82173dff3bf1ad6d (the latter filed as windows_native, a PS2 .chd)
  lcs   Liberty City Stories PS2 SLUS-21423   002b9dca58a18ea1
  vc    Vice City PS2 SLUS-20552 5eacc9f11d9a5956 (filed windows_native, but a PS2 .chd)  - resolve-only
  vcs   Vice City Stories PS2 SLUS-21590   6f5a05916536492b (PSP 18d96224e254c7c4)       - resolve-only
  Vice City windows_native 1fd42f50b10252e6 is the Definitive Edition (Unreal Engine 4): not a RenderWare target;
  gta_live refuses it with that reason (see docs/gta_vc_pc_swap.md).

Register with:  from . import gta_live  # noqa: F401
"""
import json
import re
import struct
from pathlib import Path

from pydantic import BaseModel, Field

from .models import Permission as P
from .registry import tool

GTA_MODS = "gbox/gta_games.py (gta_mods table; used live by car_jump / ped_rain)"
RE3_WANTED = "re3 src/control/Wanted.h (CWanted: m_nChaos +0x0, m_nWantedLevel +0x18; plain struct, assumed same on PS2)"
SYMTAB = "the game's ELF .symtab (op=resolve)"


def F(addr, typ="u32", source=GTA_MODS):
    return {"addr": addr, "type": typ, "source": source, "live_checked": False}


# static member symbols op=resolve looks up: field -> (class, member, type)
SYMBOLS = {
    "clock_hours": ("CClock", "ms_nGameClockHours", "u8"),
    "clock_minutes": ("CClock", "ms_nGameClockMinutes", "u8"),
    "clock_seconds": ("CClock", "ms_nGameClockSeconds", "u16"),
    "weather_old": ("CWeather", "OldWeatherType", "i16"),
    "weather_new": ("CWeather", "NewWeatherType", "i16"),
    "weather_forced": ("CWeather", "ForcedWeatherType", "i16"),
    "players": ("CWorld", "Players", "u32"),
    "ped_pool_ptr": ("CPools", "ms_pPedPool", "u32"),
    "veh_pool_ptr": ("CPools", "ms_pVehiclePool", "u32"),
    "object_pool_ptr": ("CPools", "ms_pObjectPool", "u32"),
    "building_pool_ptr": ("CPools", "ms_pBuildingPool", "u32"),
    "dummy_pool_ptr": ("CPools", "ms_pDummyPool", "u32"),
}
WANTED_FN = ("CPlayerPed", "SetWantedLevel", "i")   # first `lw rX, imm(a0)` = CPlayerPed::m_pWanted

WEATHER = {
    "gta3": ["sunny", "cloudy", "rainy", "foggy"],                                     # re3 eWeatherType
    "vc": ["sunny", "cloudy", "rainy", "foggy", "extrasunny", "hurricane", "extracolours"],   # reVC eWeatherType
}
CHAOS = [0, 70, 200, 570, 1220, 2420, 4820]           # re3 CWanted::SetWantedLevel chaos per star level 0..6

GAMES = {
    "gta3": {
        "name": "Grand Theft Auto III (PS2, SLUS-20062)", "match": r"grand theft auto iii|gta ?3\b|gta iii",
        "serials": ["SLUS-20062"], "catalog": ["265819390074bb4e", "82173dff3bf1ad6d"], "weather": "gta3",
        "fields": {
            "players": F(0x00510380), "player_focus": F(0x004169D8, "u8"), "player_stride": F(0x110, "const"),
            "ped_pool_ptr": F(0x00416858), "veh_pool_ptr": F(0x0041685C),
            "ped_stride": F(0x5B0, "const"), "veh_stride": F(0x650, "const", GTA_MODS + "; veh_size = sizeof(CAutomobile), the pool's slot"),
            "off_pos": F(0x30, "const"), "off_model": F(0x70, "const"), "off_health": F(0x2C0, "const"),
            "off_ped_veh": F(0x354, "const"), "off_ped_in_veh": F(0x358, "const"), "off_ped_type": F(0x378, "const"),
            "ped_density": F(0x00413648, "f32"), "car_density": F(0x0041367C, "f32"),
            "wanted_chaos": F(0x0, "const", RE3_WANTED), "wanted_level": F(0x18, "const", RE3_WANTED),
        },
        "spawn": "gta_mods",     # spawn_vehicle runs CVehicle creation on the EE through gta_mods' hook
    },
    "lcs": {
        "name": "GTA: Liberty City Stories (PS2, SLUS-21423)", "match": r"liberty city stories|\blcs\b",
        "serials": ["SLUS-21423"], "catalog": ["002b9dca58a18ea1"], "weather": None,
        "fields": {
            "players": F(0x00408E40), "player_focus": F(0x003D9BC8, "u8"), "player_stride": F(0x190, "const"),
            "ped_pool_ptr": F(0x003D5AE8), "veh_pool_ptr": F(0x003D5AEC), "ped_stride": F(0xCD0, "const"),
            "off_pos": F(0x30, "const"), "off_model": F(0x58, "const"), "off_ped_veh": F(0x534, "const"),
            "off_ped_in_veh": F(0x538, "const"), "off_ped_type": F(0x560, "const"),
        },
    },
    "vcs": {
        "name": "GTA: Vice City Stories (PS2, SLUS-21590)", "match": r"vice city stories|\bvcs\b",
        "serials": ["SLUS-21590"], "catalog": ["6f5a05916536492b", "18d96224e254c7c4"], "weather": None, "fields": {},
    },
    "vc": {
        "name": "GTA: Vice City (PS2, SLUS-20552)", "match": r"vice city", "serials": ["SLUS-20552"],
        "catalog": ["5eacc9f11d9a5956"], "weather": "vc", "fields": {},
    },
}
UNSUPPORTED = {
    "1fd42f50b10252e6": "Vice City Definitive Edition (Unreal Engine 4, ViceCity.exe): none of the RenderWare-era "
                        "addresses or structures exist there; gta_live has no table for it (docs/gta_vc_pc_swap.md).",
}
ORDER = ["lcs", "vcs", "gta3", "vc"]


def detect(title: str = "", serial: str = "", game: str = "", game_id: str = ""):
    if game_id in UNSUPPORTED:
        raise ValueError(UNSUPPORTED[game_id])
    if game:
        if game not in GAMES:
            raise ValueError(f"unknown game {game!r}; one of {sorted(GAMES)}")
        return game
    for k in ORDER:
        if game_id and game_id in GAMES[k]["catalog"] or serial and serial.upper() in GAMES[k]["serials"]:
            return k
    t = re.sub(r"\s+", " ", (title or "").lower().replace(":", " ").replace("-", " "))
    if "definitive" in t:
        raise ValueError(UNSUPPORTED["1fd42f50b10252e6"])
    for k in ORDER:
        if re.search(GAMES[k]["match"], t):
            return k
    raise ValueError(f"no gta_live table for {title!r}; supported: " + ", ".join(GAMES[k]["name"] for k in ORDER))


# --- ELF symbol resolution (op=resolve) -------------------------------------------------------------------------------

def elf_symbols(data: bytes) -> dict[str, tuple[int, int]]:
    """{name: (value, size)} from an ELF32 little-endian .symtab (PS2 EE ELFs)."""
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ValueError("not a 32-bit little-endian ELF")
    shoff, = struct.unpack_from("<I", data, 0x20)
    shentsize, shnum = struct.unpack_from("<HH", data, 0x2E)
    secs = [struct.unpack_from("<10I", data, shoff + i * shentsize) for i in range(shnum)]
    out = {}
    for s in secs:
        if s[1] != 2:                                  # SHT_SYMTAB
            continue
        strtab = secs[s[6]]                            # sh_link
        so, ss = strtab[4], strtab[5]
        for o in range(s[4], s[4] + s[5], 16):
            name_off, value, size = struct.unpack_from("<3I", data, o)
            if not name_off:
                continue
            end = data.index(b"\0", so + name_off, so + ss)
            out[data[so + name_off:end].decode("latin-1")] = (value, size)
    return out


def member_names(cls: str, member: str) -> list[str]:
    """Spellings of a static data member: GCC 2.x (PS2 ee-gcc) '.'/'$' markers, Itanium (GCC 3+), plain."""
    return [f"_{len(cls)}{cls}.{member}", f"_{len(cls)}{cls}${member}",
            f"_ZN{len(cls)}{cls}{len(member)}{member}E", f"{cls}::{member}"]


def method_names(cls: str, method: str, args: str) -> list[str]:
    return [f"{method}__{len(cls)}{cls}{args}", f"_ZN{len(cls)}{cls}{len(method)}{method}E{args}", f"{cls}::{method}"]


def vaddr_bytes(data: bytes, vaddr: int, n: int) -> bytes | None:
    phoff, = struct.unpack_from("<I", data, 0x1C)
    phentsize, phnum = struct.unpack_from("<HH", data, 0x2A)
    for i in range(phnum):
        _, off, va, _, filesz, _, _, _ = struct.unpack_from("<8I", data, phoff + i * phentsize)
        if va <= vaddr < va + filesz:
            return data[off + vaddr - va:off + vaddr - va + n]
    return None


def first_load_offset(code: bytes, base_reg: int = 4) -> int | None:
    """The immediate of the first `lw rt, imm(base)` (MIPS opcode 0x23) in code: a member pointer's offset."""
    for i in range(0, len(code) - 3, 4):
        w, = struct.unpack_from("<I", code, i)
        if w >> 26 == 0x23 and (w >> 21) & 31 == base_reg:
            return struct.unpack("<h", struct.pack("<H", w & 0xFFFF))[0]
    return None


def resolve(data: bytes) -> dict:
    syms = elf_symbols(data)
    found, missing = {}, []
    for field, (cls, member, typ) in SYMBOLS.items():
        hit = next((n for n in member_names(cls, member) if n in syms), None)
        if hit:
            found[field] = {"addr": syms[hit][0], "type": typ, "source": f"{SYMTAB}: {hit}", "live_checked": False}
        else:
            missing.append(f"{cls}::{member}")
    cls, method, args = WANTED_FN
    hit = next((n for n in method_names(cls, method, args) if n in syms), None)
    code = vaddr_bytes(data, syms[hit][0], 32) if hit else None
    off = first_load_offset(code) if code else None
    if off is not None:
        found["off_wanted_ptr"] = {"addr": off, "type": "const", "live_checked": False,
                                   "source": f"{SYMTAB}: first lw from a0 in {hit} (CPlayerPed::m_pWanted)"}
    else:
        missing.append(f"{cls}::{method} (m_pWanted offset)")
    return {"symbols": len(syms), "found": found, "missing": missing}


# --- tables merged with resolutions -------------------------------------------------------------------------------------

def cache_path(config, key) -> Path:
    return config.data_dir / "gta_live" / f"{key}.json"


def table(config, key) -> dict:
    fields = dict(GAMES[key]["fields"])
    p = cache_path(config, key) if config is not None else None
    if p is not None and p.is_file():
        for k, v in json.loads(p.read_text(encoding="utf-8")).get("found", {}).items():
            fields.setdefault(k, v)                    # the curated table wins over a resolution
    return fields


class Unmapped(LookupError):
    pass


def need(fields, *names):
    miss = [n for n in names if n not in fields]
    if miss:
        raise Unmapped(f"not mapped for this game yet: {', '.join(miss)}. Map it with memory_search (find the value, "
                       f"change it in game, filter) or gta_live op=resolve elf_path=<the game's ELF from re_study>, then "
                       f"re_dossier op=record; never guess an address.")
    return [fields[n]["addr"] for n in names]


FMT = {"u8": "<B", "i8": "<b", "u16": "<H", "i16": "<h", "u32": "<I", "i32": "<i", "f32": "<f"}


def rd(m, field, fields):
    f = fields[field]
    fmt = FMT[f["type"]]
    return struct.unpack(fmt, m.rd(f["addr"], struct.calcsize(fmt)))[0]


def wr(m, field, fields, value):
    f = fields[field]
    m.wr(f["addr"], struct.pack(FMT[f["type"]], value))


def player_ped(m, fields):
    players, focus, stride = need(fields, "players", "player_focus", "player_stride")
    return m.u32(players + m.rd(focus, 1)[0] * stride)


def pool(m, ptr):
    p = m.u32(ptr)
    if not p:
        return None
    objs, flags, size = struct.unpack("<3I", m.rd(p, 12))
    if not 0 < size <= 4096:
        raise RuntimeError(f"pool header at {p:#x} looks wrong (size {size}): wrong game build or not in gameplay")
    return objs, m.rd(flags, size), size


def vec(m, a):
    return [round(v, 3) for v in struct.unpack("<3f", m.rd(a, 12))]


# --- ops ---------------------------------------------------------------------------------------------------------------

def op_pools(m, fields):
    out = {}
    for name in ("ped", "veh", "object", "building", "dummy"):
        f = f"{name}_pool_ptr"
        if f not in fields:
            continue
        p = pool(m, fields[f]["addr"])
        out[name] = None if p is None else {"size": p[2], "used": sum(1 for b in p[1] if not b & 0x80),
                                            "free": sum(1 for b in p[1] if b & 0x80), "objects": hex(p[0])}
    if not out:
        need(fields, "ped_pool_ptr")
    return out


def op_player(m, fields):
    ped = player_ped(m, fields)
    if not ped:
        return {"player": None, "note": "no player ped (not in gameplay?)"}
    pos_off, = need(fields, "off_pos")
    out = {"ped": hex(ped), "pos": vec(m, ped + pos_off)}
    if "off_health" in fields:
        out["health"] = round(struct.unpack("<f", m.rd(ped + fields["off_health"]["addr"], 4))[0], 2)
    if "off_ped_in_veh" in fields and "off_ped_veh" in fields:
        inveh = m.rd(ped + fields["off_ped_in_veh"]["addr"], 1)[0]
        out["in_vehicle"] = bool(inveh)
        if inveh:
            v = m.u32(ped + fields["off_ped_veh"]["addr"])
            out["vehicle"] = {"addr": hex(v), "pos": vec(m, v + pos_off)}
    if "off_wanted_ptr" in fields:
        out["wanted"] = op_wanted(m, fields)
    return out


def op_vehicles(m, fields, limit=50):
    ptr, stride, pos_off, mdl_off = need(fields, "veh_pool_ptr", "veh_stride", "off_pos", "off_model")
    p = pool(m, ptr)
    if p is None:
        return {"vehicles": [], "note": "vehicle pool not allocated yet"}
    objs, fl, size = p
    rows = []
    for i in range(size):
        if fl[i] & 0x80:
            continue
        a = objs + i * stride
        rows.append({"slot": i, "addr": hex(a), "model": struct.unpack("<h", m.rd(a + mdl_off, 2))[0], "pos": vec(m, a + pos_off)})
        if len(rows) >= limit:
            break
    return {"pool_size": size, "vehicles": rows}


def weather_name(key, v):
    names = WEATHER.get(GAMES[key]["weather"] or "", [])
    return names[v] if 0 <= v < len(names) else ("released" if v == -1 else v)


def op_weather(m, fields, key, value=None):
    need(fields, "weather_forced")
    if value is not None:
        names = WEATHER.get(GAMES[key]["weather"] or "", [])
        v = value.strip().lower() if isinstance(value, str) else value
        if v in ("release", "released", "normal", "-1", -1):
            v = -1
        elif isinstance(v, str) and v in names:
            v = names.index(v)
        else:
            try:
                v = int(v)
            except ValueError:
                raise ValueError(f"weather must be one of {names} (or release)") from None
            if not -1 <= v < max(len(names), 1):
                raise ValueError(f"weather must be one of {names} (or release)")
        wr(m, "weather_forced", fields, v)
        if v >= 0:     # change it now, not at the next weather interpolation step
            for f in ("weather_old", "weather_new"):
                if f in fields:
                    wr(m, f, fields, v)
    return {k: weather_name(key, rd(m, f, fields)) for k, f in
            (("forced", "weather_forced"), ("old", "weather_old"), ("new", "weather_new")) if f in fields} | \
        {"types": WEATHER.get(GAMES[key]["weather"] or "", [])}


def op_time(m, fields, hours=None, minutes=None):
    need(fields, "clock_hours", "clock_minutes")
    if hours is not None:
        if not 0 <= int(hours) <= 23:
            raise ValueError("hours must be 0..23")
        wr(m, "clock_hours", fields, int(hours))
    if minutes is not None:
        if not 0 <= int(minutes) <= 59:
            raise ValueError("minutes must be 0..59")
        wr(m, "clock_minutes", fields, int(minutes))
        if "clock_seconds" in fields:
            wr(m, "clock_seconds", fields, 0)
    h, mi = rd(m, "clock_hours", fields), rd(m, "clock_minutes", fields)
    return {"hours": h, "minutes": mi, "clock": f"{h:02d}:{mi:02d}"}


def op_wanted(m, fields, level=None):
    off, chaos_off, level_off = need(fields, "off_wanted_ptr", "wanted_chaos", "wanted_level")
    ped = player_ped(m, fields)
    w = m.u32(ped + off) if ped else 0
    if not w:
        raise RuntimeError("no CWanted for the player (not in gameplay?)")
    if level is not None:
        lv = int(level)
        if not 0 <= lv <= 6:
            raise ValueError("wanted level is 0..6")
        m.wr(w + chaos_off, struct.pack("<i", CHAOS[lv]))   # the game derives the level from chaos every frame
        m.wr(w + level_off, struct.pack("<i", lv))
    return {"level": struct.unpack("<i", m.rd(w + level_off, 4))[0], "chaos": struct.unpack("<i", m.rd(w + chaos_off, 4))[0],
            "wanted": hex(w), "hold": "freeze_memory the chaos word to keep it"}


def op_teleport(m, fields, x, y, z):
    pos_off, = need(fields, "off_pos")
    ped = player_ped(m, fields)
    if not ped:
        raise RuntimeError("no player ped (not in gameplay?)")
    target = ped
    if "off_ped_in_veh" in fields and m.rd(ped + fields["off_ped_in_veh"]["addr"], 1)[0]:
        target = m.u32(ped + fields["off_ped_veh"]["addr"])     # move the car with the player in it
    m.wr(target + pos_off, struct.pack("<3f", float(x), float(y), float(z)))
    return {"moved": hex(target), "pos": vec(m, target + pos_off)}


def run(ad, title, op, config=None, serial="", game="", game_id="", **kw):
    from .gta_mods_tool import Mem
    if op == "games":
        return {"games": {k: {"name": g["name"], "catalog": g["catalog"], "fields": table(config, k)} for k, g in GAMES.items()},
                "unsupported": UNSUPPORTED}
    key = detect(title, serial, game, game_id)
    if op == "resolve":
        path = kw.get("elf_path")
        if not path or not Path(path).is_file():
            raise FileNotFoundError("resolve needs elf_path: the game's executable ELF (re_study / re_executable extract it)")
        res = resolve(Path(path).read_bytes())
        if config is not None:
            p = cache_path(config, key)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(res | {"elf": str(path)}, indent=1), encoding="utf-8")
        return {"game": key, **res}
    fields = table(config, key)
    m = Mem(ad)
    if op == "pools":
        res = op_pools(m, fields)
    elif op == "player":
        res = op_player(m, fields)
    elif op == "vehicles":
        res = op_vehicles(m, fields, int(kw.get("limit") or 50))
    elif op == "weather":
        res = op_weather(m, fields, key, kw.get("value"))
    elif op == "time":
        res = op_time(m, fields, kw.get("hours"), kw.get("minutes"))
    elif op == "wanted":
        res = op_wanted(m, fields, kw.get("level"))
    elif op == "teleport":
        if None in (kw.get("x"), kw.get("y"), kw.get("z")):
            raise ValueError("teleport needs x, y, z (world coordinates)")
        res = op_teleport(m, fields, kw["x"], kw["y"], kw["z"])
    elif op == "spawn":
        if GAMES[key].get("spawn") != "gta_mods":
            raise Unmapped(f"vehicle spawn is not mapped for {GAMES[key]['name']} (gta_mods has no spawn_vehicle there)")
        if kw.get("model") is None:
            raise ValueError("spawn needs model (vehicle model id)")
        from .gta_mods_tool import run as gta_mods_run
        return {"game": key, "op": op, "result": gta_mods_run(ad, title, "spawn_vehicle", model=int(kw["model"])),
                "via": "gta_mods spawn_vehicle"}
    else:
        raise ValueError(f"unknown op {op!r}: games | resolve | pools | player | vehicles | weather | time | wanted | teleport | spawn")
    return {"game": key, "op": op, "result": res, "writes": m.log,
            "provenance": {k: {"source": v["source"], "live_checked": v["live_checked"]} for k, v in fields.items()}}


class GtaLiveIn(BaseModel):
    session_id: str
    op: str = Field("player", description="games | resolve | pools | player | vehicles | weather | time | wanted | teleport | spawn")
    game: str = ""               # force a table: gta3 | lcs | vc | vcs (default: detected from the session title)
    value: str | int | None = None   # weather: sunny | cloudy | rainy | foggy | ... | release
    hours: int | None = None
    minutes: int | None = None
    level: int | None = None     # wanted: 0..6 stars
    x: float | None = None
    y: float | None = None
    z: float | None = None
    model: int | None = None     # spawn: vehicle model id
    limit: int = 50
    elf_path: str | None = None  # resolve: the game's executable ELF


class GtaLiveOut(BaseModel):
    result: dict


@tool("gta_live", "1.0", GtaLiveIn, GtaLiveOut, capabilities=["runtime", "memory"], permissions=[P.READ, P.MEMORY_WRITE],
      timeout_s=120, side_effects=["writes game RAM (data only, read back; previous bytes returned in writes)"])
def gta_live(inp: GtaLiveIn, ctx):
    """Live GTA (PS2 GTA III / Liberty City Stories / Vice City / Vice City Stories): entity pools, the player (position,
    health, vehicle, wanted level), vehicles in the pool, weather, time of day, wanted level, teleport, vehicle spawn. The
    in-game controls of the Ariane map editor, on gBox's read/write_memory. Every address reports its source and
    live_checked; unmapped fields say how to map them."""
    from .tools import SESSIONS
    if inp.op == "games":
        return {"result": run(None, "", "games", ctx.config)}
    ad, g = SESSIONS[inp.session_id]
    title = g.get("title", "")
    return {"result": run(ad, title, inp.op, ctx.config, serial=str(g.get("serial") or ""), game=inp.game,
                          game_id=str(g.get("game_id") or ""), value=inp.value, hours=inp.hours, minutes=inp.minutes,
                          level=inp.level, x=inp.x, y=inp.y, z=inp.z, model=inp.model, limit=inp.limit, elf_path=inp.elf_path)}
