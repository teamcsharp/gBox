"""`assimilate`: fingerprint a game before reverse engineering it. Step one of every readiness inventory.

Given a game (catalog game_id, or a path to its disc image / ROM / install folder) it lists the files with their first
bytes (gbox.formats.disc), samples the largest archives, extracts the executable's strings and ELF symbols, and ranks:

  containers / codecs / models / textures / animations   from magic bytes (heads and inside archives) and extensions
  engine / middleware                                     Ninja, RenderWare, Unreal 3/4, EAGL, Eurocom, MT Framework,
                                                          CRI, Tecmo, AKI, Yuke's, Shiny, Namco, Konami, Square, ...
                                                          from generic engine markers PLUS what gBox learned from every
                                                          title it already assimilated (gbox.assimilate_kb)
  nearest assimilated titles                              whose readers to start from
  reader skeleton                                         a module outline wired to the shared gbox.formats pieces

The engine ranking has two parts: fixed engine markers (strings/symbols/magics any game of that engine carries) and
evidence learned from the knowledge base (tokens that co-occur with an engine across assimilated titles: naive-Bayes
log odds over present tokens). evaluate() measures it leave-one-out over the knowledge base, so every title added to
gbox.assimilate_kb makes the next fingerprint better, and the measurement says by how much.

ops: fingerprint (game_id | path) | known (the knowledge base) | evaluate (leave-one-out accuracy)
"""
from __future__ import annotations

import math
import re
import struct
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from .assimilate_kb import KNOWN_TITLES
from .registry import tool

# ------------------------------------------------------------------------------------------- format signatures
# id: (kind, label, matcher, sample bytes for synthetic listings, engine hints)
# matcher: bytes = magic at offset 0; callable = predicate on the head.


def _tim(h: bytes) -> bool:
    return len(h) >= 8 and h[:4] == b"\x10\0\0\0" and h[4] in (0, 1, 2, 3, 8, 9) and h[5:8] == b"\0\0\0"


def _rw(kind: int):
    def m(h: bytes) -> bool:
        if len(h) < 12:
            return False
        t, _size, ver = struct.unpack_from("<III", h)
        return t == kind and ((ver & 0xFFFF) == 0xFFFF or ver in (0x302, 0x304, 0x310))
    return m


def _refpack(h: bytes) -> bool:
    return len(h) >= 5 and h[1] == 0xFB and (h[0] & 0x3E) == 0x10


def _zlib(h: bytes) -> bool:
    return len(h) >= 2 and h[0] == 0x78 and (h[0] << 8 | h[1]) % 31 == 0


SIGNATURES = {
    # containers
    "afs": ("container", "CRI AFS archive", b"AFS\0", b"AFS\0", ["cri"]),
    "cpk": ("container", "CRI CPK archive", b"CPK ", b"CPK ", ["cri"]),
    "cvm": ("container", "CRI CVM image", b"CVMH", b"CVMH", ["cri"]),
    "bigf": ("container", "EA BIG/VIV archive (BIGF)", b"BIGF", b"BIGF", ["ea", "eagl"]),
    "big4": ("container", "EA BIG4 archive", b"BIG4", b"BIG4", ["ea", "eagl"]),
    "rarc": ("container", "Nintendo RARC archive", b"RARC", b"RARC", ["nintendo_gc"]),
    "u8": ("container", "Nintendo U8 archive", b"U\xaa8-", b"U\xaa8-", ["nintendo_gc"]),
    "narc": ("container", "Nintendo NARC archive", b"NARC", b"NARC", ["nintendo_ds"]),
    "mt_arc": ("container", "Capcom MT Framework ARC", b"ARC\0", b"ARC\0", ["mt_framework"]),
    "dpac": ("container", "DPAC directory (Yuke's)", b"DPAC", b"DPAC", []),
    "yk_pac": ("container", "PAC entry (Yuke's)", b"PAC ", b"PAC ", []),
    "wrs": ("container", "WRS fighter container (AKI PS2)", b"WRS ", b"WRS ", []),
    "aki_pak": ("container", "PAK arena (AKI PS2)", b"PAK ", b"PAK ", []),
    "gnaf": ("container", "Fang master file (GNAF)", b"GNAF", b"GNAF", []),
    "paks": ("container", "PAKS/IPAC dictionary (Shenmue)", b"PAKS", b"PAKS", []),
    "pakf": ("container", "PAKF texture pack (Shenmue)", b"PAKF", b"PAKF", []),
    "play": ("container", "PLAY character container (JGR)", b"PLAY", b"PLAY", []),
    "edl": ("container", "Eurocom EDL level database", b"EDL", b"EDL\x81", ["eurocom"]),
    "ngc_restable": ("container", "EAGL .ngc chunk file (byte-reversed ids)", b"elbatser", b"elbatser", ["eagl"]),
    "ldm": ("model", "Rockstar Stories relocatable model ('ldm')", b"ldm\0", b"ldm\0", ["rockstar_stories"]),
    "xet": ("texture", "Rockstar Stories texture chunk ('xet')", b"xet\0", b"xet\0", ["rockstar_stories"]),
    "zip": ("container", "ZIP", b"PK\x03\x04", b"PK\x03\x04", []),
    # codecs
    "mio0": ("codec", "MIO0", b"MIO0", b"MIO0", ["nintendo_n64"]),
    "yaz0": ("codec", "Yaz0", b"Yaz0", b"Yaz0", ["nintendo_n64", "nintendo_gc"]),
    "yay0": ("codec", "Yay0", b"Yay0", b"Yay0", ["nintendo_n64"]),
    "rnc": ("codec", "RNC ProPack", lambda h: h[:3] == b"RNC" and h[3:4] in (b"\x01", b"\x02"), b"RNC\x01", []),
    "vpk0": ("codec", "VPK0", b"vpk0", b"vpk0", ["nintendo_n64"]),
    "refpack": ("codec", "EA RefPack (QFS)", _refpack, b"\x10\xfb\0\0\x10", ["ea"]),
    "zlib": ("codec", "zlib", _zlib, b"\x78\x9c", []),
    "gzip": ("codec", "gzip", b"\x1f\x8b", b"\x1f\x8b\x08", []),
    "bpe": ("codec", "BPE byte-pair packing", b"BPE ", b"BPE ", []),
    "lz77": ("codec", "Nintendo LZ77 tag + LZ10/LZ11 stream", lambda h: h[:4] == b"LZ77" and h[4:5] in (b"\x10", b"\x11"),
             b"LZ77\x10\x40\0\0", ["nintendo_ds"]),
    "lz10": ("codec", "Nintendo LZ10 (weak: one byte)", lambda h: h[:1] == b"\x10" and len(h) > 4 and h[1:4] != b"\0\0\0", b"\x10\x40\0\0", []),
    # models
    "njcm": ("model", "Ninja chunk model (NJCM)", b"NJCM", b"NJCM", ["ninja"]),
    "njtl": ("model", "Ninja texture list + model (NJTL)", b"NJTL", b"NJTL", ["ninja"]),
    "njbm": ("model", "Ninja basic model (NJBM)", b"NJBM", b"NJBM", ["ninja"]),
    "gjcm": ("model", "Ninja GC chunk model (GJCM)", b"GJCM", b"GJCM", ["ninja"]),
    "pof0": ("model", "Ninja pointer fixup (POF0)", b"POF0", b"POF0", ["ninja"]),
    "emd": ("model", "EMD model (Yuke's)", b"EMD ", b"EMD ", []),
    "hrcm": ("model", "MT5/HRCM model (Shenmue)", b"HRCM", b"HRCM", []),
    "mt_mod": ("model", "Capcom MT MOD", b"MOD\0", b"MOD\0", ["mt_framework"]),
    "rw_clump": ("model", "RenderWare clump (DFF)", _rw(0x10), struct.pack("<III", 0x10, 0x100, 0x1003FFFF), ["renderware"]),
    "j3d2": ("model", "Nintendo J3D (BMD/BDL)", b"J3D2", b"J3D2", ["nintendo_gc"]),
    "bres": ("model", "Nintendo BRRES", b"bres", b"bres", ["nintendo_gc"]),
    "ndp3": ("model", "Namco NUD (NDP3)", b"NDP3", b"NDP3", ["namco"]),
    "gpl": ("model", "GX .gpl mesh (Def Jam GC)", b"\x00\xb7\x49\xe0", b"\x00\xb7\x49\xe0", []),
    "gltf": ("model", "glTF binary", b"glTF", b"glTF", []),
    # textures
    "pvmh": ("texture", "Ninja PVM texture archive", b"PVMH", b"PVMH", ["ninja"]),
    "gvmh": ("texture", "Ninja GVM texture archive", b"GVMH", b"GVMH", ["ninja"]),
    "gbix": ("texture", "PowerVR texture (GBIX)", b"GBIX", b"GBIX", ["ninja"]),
    "pvrt": ("texture", "PowerVR texture (PVRT)", b"PVRT", b"PVRT", ["ninja"]),
    "gvrt": ("texture", "GameCube GVR texture", b"GVRT", b"GVRT", ["ninja"]),
    "ptex": ("texture", "PTEX texture set (JGR)", b"PTEX", b"PTEX", []),
    "texn": ("texture", "TEXN texture (Shenmue)", b"TEXN", b"TEXN", []),
    "tim": ("texture", "PS1 TIM", _tim, b"\x10\0\0\0\x09\0\0\0", []),
    "tim2": ("texture", "PS2 TIM2", b"TIM2", b"TIM2", []),
    "tpl": ("texture", "GameCube TPL", b"\x00\x20\xaf\x30", b"\x00\x20\xaf\x30", ["nintendo_gc"]),
    "rw_txd": ("texture", "RenderWare texture dictionary (TXD)", _rw(0x16), struct.pack("<III", 0x16, 0x100, 0x1003FFFF), ["renderware"]),
    "mt_tex": ("texture", "Capcom MT TEX", b"TEX\0", b"TEX\0", ["mt_framework"]),
    "ntp3": ("texture", "Namco NTP3", b"NTP3", b"NTP3", ["namco"]),
    "dds": ("texture", "DirectDraw Surface", b"DDS ", b"DDS ", []),
    "xpr0": ("texture", "Xbox XPR0", b"XPR0", b"XPR0", []),
    # animation
    "nmdm": ("animation", "Ninja motion (NMDM)", b"NMDM", b"NMDM", ["ninja"]),
    "yk_mot": ("animation", "MOT motion bank (Yuke's)", b"MOT ", b"MOT ", []),
    "cgam": ("animation", "CGAM motion bank (Illbleed .PMC)", b"CGAM", b"CGAM", []),
    "anpk": ("animation", "RenderWare-era IFP animation (ANPK/ANP3)", lambda h: h[:4] in (b"ANPK", b"ANP3"), b"ANPK", ["renderware"]),
    "mt_lmt": ("animation", "Capcom MT LMT", b"LMT\0", b"LMT\0", ["mt_framework"]),
    # executables / misc
    "ue_pkg_le": ("container", "Unreal package (LE)", b"\xc1\x83\x2a\x9e", b"\xc1\x83\x2a\x9e", ["unreal3", "unreal4"]),
    "ue_pkg_be": ("container", "Unreal package (BE, console)", b"\x9e\x2a\x83\xc1", b"\x9e\x2a\x83\xc1", ["unreal3"]),
    "elf": ("executable", "ELF", b"\x7fELF", b"\x7fELF", []),
    "psx_exe": ("executable", "PS-X EXE", b"PS-X EXE", b"PS-X EXE", []),
    "xex2": ("executable", "Xbox 360 XEX2", b"XEX2", b"XEX2", []),
    "mz": ("executable", "Windows PE (MZ)", b"MZ", b"MZ", []),
    "n64": ("executable", "N64 ROM header", b"\x80\x37\x12\x40", b"\x80\x37\x12\x40", ["nintendo_n64"]),
}
DEEP_OK = {k for k, v in SIGNATURES.items() if isinstance(v[2], bytes) and len(v[2]) >= 4 and k not in ("zip", "mz")}

# extensions -> engine hints (generic, documented middleware conventions)
EXT_HINTS = {
    "ninja": [".nj", ".njm", ".pvm", ".pvr", ".prs", ".bml", ".gvm", ".gvr", ".gj", ".njs", ".pvp"],
    "cri": [".afs", ".adx", ".sfd", ".cpk", ".usm", ".cvm", ".aix", ".ahx"],
    "renderware": [".dff", ".txd", ".col", ".ifp", ".rws", ".rwd"],
    "unreal4": [".pak", ".uasset", ".uexp", ".utoc", ".ucas", ".umap"],
    "unreal3": [".upk", ".u", ".xxx", ".ut3", ".udk"],
    "ea": [".big", ".viv", ".ast", ".ssh", ".fsh"],
    "mt_framework": [".arc", ".lmt", ".mrl"],
    "nintendo_gc": [".szs", ".rarc", ".bmd", ".bdl", ".brres", ".tpl", ".bfres"],
    "nintendo_ds": [".narc", ".nsbmd", ".nsbtx", ".ncgr", ".nclr"],
    "eagl": [".viv", ".gcm", ".gca", ".men"],
    "eurocom": [".edb", ".edl"],
    "namco": [".nud", ".nut", ".vbn"],
    "hal_sysdolphin": [".dat", ".usd"],
}

# generic engine markers in executable strings / symbols
ENGINE_MARKERS = {
    "ninja": [r"\bNJCM\b", r"\bnj[A-Z][A-Za-z]+\(", r"Ninja Library", r"\bnjInit"],
    "renderware": [r"RenderWare", r"\brwID_", r"\bRwEngine", r"\bRp(Clump|Skin|HAnim|World)", r"Criterion"],
    "unreal3": [r"UnrealScript", r"Unreal Engine 3", r"\bintA[A-Z]\w*exec[A-Z]", r"Cooked(PS3|Xenon|PC)\b"],
    "unreal4": [r"\+\+UE4\+", r"\+\+UE5\+", r"FPakPlatformFile", r"/Script/Engine"],
    "eagl": [r"\bEAGL\b", r"BOA_Expand"],
    "eurocom": [r"Eurocom", r"\bHT_File\b"],
    "ea": [r"Electronic Arts", r"\bBIGF\b", r"RefPack"],
    "cri": [r"CRI Middleware", r"\bCRI ADX\b", r"\bADX\b", r"criware", r"\bCRI\b"],
    "mt_framework": [r"MT Framework", r"\brArchive\b", r"\bMtObject\b"],
    "tecmo": [r"\bTECMO\b", r"[Tt]ecmo"],
    "aki": [r"\bAKI\b", r"\bASMIK\b", r"AKI Corp"],
    "yukes": [r"YUKE'?S", r"Yuke's"],
    "shiny": [r"Shiny Entertainment", r"\bSHINY\b"],
    "namco": [r"\bNAMCO\b", r"Namco"],
    "konami": [r"\bKONAMI\b", r"Konami"],
    "square": [r"\bSQUARE\b", r"SquareSoft", r"Square Co"],
    "hal_sysdolphin": [r"sysdolphin", r"\bHSD_[A-Z]"],
    "midway": [r"\bMIDWAY\b"],
    "nintendo_n64": [r"libultra", r"\bosCreateThread\b"],
}

ENGINE_LABELS = {
    "ninja": "Sega Ninja SDK (NJ/NJCM, PVR/PVM, NJM)", "naomilib": "SEGA AM2 NaomiLib", "renderware": "RenderWare (Criterion)",
    "unreal3": "Unreal Engine 3", "unreal4": "Unreal Engine 4/5", "eagl": "EA EAGL", "eurocom": "Eurocom engine",
    "ea": "Electronic Arts (BIG/RefPack)", "cri": "CRI Middleware (AFS/ADX/CPK)", "mt_framework": "Capcom MT Framework",
    "tecmo": "Tecmo", "aki": "AKI Corporation", "yukes": "Yuke's", "shiny": "Shiny Entertainment", "namco": "Namco",
    "konami": "Konami", "square": "Square", "hal_sysdolphin": "HAL sysdolphin (HSD)", "midway": "Midway",
    "nintendo_n64": "Nintendo 64 SDK (libultra; MIO0/Yaz0/VPK0)", "nintendo_gc": "Nintendo GC/Wii SDK formats",
    "nintendo_ds": "Nintendo DS SDK formats", "rockstar_stories": "Rockstar Leeds Stories engine",
    "fang": "Swingin' Ape Fang", "iguana_tengine": "Iguana tengine", "climax_landers": "Climax LANDERS",
    "sega_am2": "SEGA AM2 (Shenmue MT5)", "hitmaker_ct": "Hitmaker Crazy Taxi", "capcom_re4": "Capcom RE4 engine",
    "capcom_dc": "Capcom Dreamcast 2D", "capcom_re": "Capcom RE (PS1)", "capcom_dmc": "Capcom DMC (PS2)",
}

# where a new reader starts, per engine (beyond the nearest assimilated title)
ENGINE_READERS = {
    "ninja": "gbox.formats.ninja_chunk (decode/encode/fit); templates gbox.sa2_chars, gbox.pso_player, gbox.jgr",
    "naomilib": "gbox.naomilib (model scan) + gbox.doa2_chars (CHR), gbox.crazy_taxi2",
    "renderware": "gbox.gta_rw (IMG/DFF, write_skinned_glb) + gbox.gta_vc_models (TXD/DFF writer)",
    "unreal3": "gbox.ue3 (packages, script) + playbook unreal-script",
    "unreal4": "gbox.ue_pak -> gbox.ue_asset -> gbox.ue_mesh", "eagl": "gbox.auf_ngc (.ngc chunks, BOA LZ, .gcm)",
    "eurocom": "gbox.nightfire_edl (EDL decompressor, hash packs)", "ea": "gbox.refpack + gbox.mayhem_inventory (BIGF)",
    "cri": "gbox.jgr.afs_entries (AFS) + gbox.formats.lz", "mt_framework": "gbox.re6 / gbox.merc3d_mod (ARC, MOD, TEX)",
    "tecmo": "gbox.doa2_chars (Dreamcast) / gbox.doapp_* + gbox.formats.oracle (ZN arcade)",
    "aki": "gbox.aki_wrestling (N64) / gbox.defjam_models (PS2)", "yukes": "gbox.yukes_sd (DPAC/EMD/TIM, welded fit)",
    "konami": "gbox.mgs_kmd / gbox.mgs_vr_swap", "square": "gbox.ff7_models / gbox.pe2_models / gbox.parasite_eve",
    "hal_sysdolphin": "gbox.melee_models", "nintendo_n64": "gbox.n64_rom + gbox.formats.lz (MIO0/Yaz0/VPK0) + gbox.sm64_mario",
    "nintendo_gc": "gbox.gcdisc + gbox.re4gc_models (TPL)", "rockstar_stories": "gbox.gta_stories_models",
    "fang": "gbox.metal_arms", "iguana_tengine": "gbox.turok_inventory (RNC, CIndexedSet)",
}

PLATFORM_PRIORS = {
    "psx": ["iso9660", "tim", "psx_exe"], "ps2": ["iso9660", "tim2", "elf"], "dreamcast": ["gdrom", "pvrt", "gbix"],
    "gamecube": ["gc_fst", "tpl", "yaz0"], "wii": ["gc_fst", "tpl", "yaz0", "u8"], "n64": ["n64", "mio0", "yaz0", "rnc"],
    "xbox360": ["xex2"], "ps3": ["elf"], "windows_native": ["mz"],
}

STRING_RE = re.compile(rb"[\x20-\x7e]{5,120}")


# ------------------------------------------------------------------------------------------- evidence

def match_head(h: bytes) -> str | None:
    for sid, (_k, _l, m, _s, _e) in SIGNATURES.items():
        if (m(h) if callable(m) else h.startswith(m)):
            return sid
    return None


def inner_magics(sample: bytes, step: int = 4) -> Counter:
    """Strong (4+ byte) magics at aligned offsets inside an archive sample."""
    out = Counter()
    for sid in DEEP_OK:
        m = SIGNATURES[sid][2]
        i = sample.find(m)
        while i != -1:
            if i % step == 0:
                out[sid] += 1
            i = sample.find(m, i + 1)
    return out


def exe_strings(exe: bytes, limit: int = 200_000) -> list[str]:
    return [m.group().decode("ascii") for m, _ in zip(STRING_RE.finditer(exe), range(limit))]


def elf_symbols(exe: bytes, limit: int = 100_000) -> list[str]:
    """Names in an ELF's .symtab/.dynsym (Bond.elf keeps 17,636; GTA III's PS2 ELF ships one)."""
    if exe[:4] != b"\x7fELF" or len(exe) < 0x34:
        return []
    be = exe[5] == 2
    e = ">" if be else "<"
    is64 = exe[4] == 2
    try:
        if is64:
            shoff, = struct.unpack_from(e + "Q", exe, 0x28)
            shentsize, shnum = struct.unpack_from(e + "HH", exe, 0x3A)
        else:
            shoff, = struct.unpack_from(e + "I", exe, 0x20)
            shentsize, shnum = struct.unpack_from(e + "HH", exe, 0x2E)
        secs = []
        for i in range(shnum):
            o = shoff + i * shentsize
            if is64:
                _n, typ, _f, _a, off, size, link, _i, _al, entsize = struct.unpack_from(e + "IIQQQQIIQQ", exe, o)
            else:
                _n, typ, _f, _a, off, size, link, _i, _al, entsize = struct.unpack_from(e + "10I", exe, o)
            secs.append((typ, off, size, link, entsize))
        out = []
        for typ, off, size, link, entsize in secs:
            if typ not in (2, 11) or not entsize:
                continue
            _st, stroff, strsize, _l, _e = secs[link]
            strtab = exe[stroff:stroff + strsize]
            for k in range(off, off + size, entsize):
                name_off = struct.unpack_from(e + "I", exe, k)[0]
                if name_off and name_off < len(strtab):
                    n = strtab[name_off:strtab.index(b"\0", name_off)].decode("latin-1")
                    if n:
                        out.append(n)
                        if len(out) >= limit:
                            return out
        return out
    except (struct.error, ValueError, IndexError):
        return []


def _ext(path: str) -> str:
    suf = Path(path).suffix.lower()
    return suf if 1 < len(suf) <= 7 and not re.fullmatch(r"\.\d+", suf) else ""


def evidence(files: list[dict], strings: list[str], symbols: list[str], platform: str = "", title: str = "",
             exe_name: str = "") -> dict:
    """The raw observations: magic counts (heads / inside archives), extensions, path tokens, strings, symbols."""
    heads, inner, exts, dirs = Counter(), Counter(), Counter(), Counter()
    for f in files:
        p = f.get("path", "")
        if exe_name and p == exe_name:
            continue
        sid = match_head(f.get("head") or b"")
        if sid:
            heads[sid] += 1
        if f.get("sample"):
            inner.update(inner_magics(f["sample"]))
        if f.get("inner"):
            inner.update(f["inner"])
        e = _ext(p)
        if e:
            exts[e] += 1
        for part in re.split(r"[/\\]", p)[:-1]:
            if part:
                dirs[part.lower()] += 1
    return {"platform": platform, "title": title, "heads": heads, "inner": inner, "exts": exts, "dirs": dirs,
            "strings": strings, "symbols": symbols, "files": len(files)}


def tokens(ev: dict) -> set[str]:
    t = {f"platform:{ev['platform']}"} if ev.get("platform") else set()
    t |= {f"magic:{k}" for k in ev["heads"]} | {f"magic:{k}" for k in ev["inner"]}
    t |= {f"ext:{k}" for k in ev["exts"]} | {f"dir:{k}" for k in ev["dirs"]}
    for eng, pats in ENGINE_MARKERS.items():
        blob = "\n".join(ev["strings"][:50000] + ev["symbols"][:50000])
        if any(re.search(p, blob) for p in pats):
            t.add(f"marker:{eng}")
    title = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", ev.get("title") or "").lower()     # drop "(USA)", "(PS2)", ...
    t |= {f"title:{w}" for w in re.findall(r"[a-z0-9]+", title) if len(w) > 2 and w not in TITLE_STOP}
    return t


TITLE_STOP = {"the", "and", "for", "usa", "europe", "japan", "rev", "disc", "edition", "game"}
GENERIC_EXT = {".bin", ".dat", ".img", ".pac", ".pak", ".dir", ".exe", ".elf", ".dol", ".iso", ".txt", ".cfg", ".ini",
               ".cnf", ".mdl", ".tex", ".mot", ".arc"}


def token_weight(x: str) -> float:
    """How much one shared token says: format magics and markers most, titles (franchises) next, folder names least."""
    kind, _, val = x.partition(":")
    if kind == "ext":
        return 0.3 if val in GENERIC_EXT else 0.8
    return {"magic": 1.0, "marker": 1.0, "title": 0.9, "dir": 0.4, "platform": 0.0}.get(kind, 0.5)


# ------------------------------------------------------------------------------------------- learning from the KB

def kb_title_evidence(entry: dict) -> dict:
    """Synthetic evidence of an assimilated title from its documented layout (used to learn and to evaluate)."""
    files = []
    for path, head, inner in entry.get("files", []):
        files.append({"path": path, "head": SIGNATURES[head][3] + bytes(16) if head else b"",
                      "inner": Counter({i: 3 for i in inner})})
    return evidence(files, list(entry.get("strings", [])), [], entry.get("platform", ""), entry.get("title", ""))


class Model:
    """Token -> engine log odds learned from assimilated titles (Bernoulli naive Bayes over present tokens)."""

    def __init__(self, titles: list[dict]):
        self.titles = titles
        self.tok = [tokens(kb_title_evidence(t)) for t in titles]
        self.engines = sorted({e for t in titles for e in t["engines"]})
        self.df = Counter(x for ts in self.tok for x in ts)

    def engine_scores(self, toks: set[str]) -> dict[str, float]:
        n, out = len(self.titles), {}
        for eng in self.engines:
            idx = [i for i, t in enumerate(self.titles) if eng in t["engines"]]
            if not idx:
                continue
            s = 0.0
            for x in toks:
                if x.startswith("platform:"):
                    continue
                a = sum(x in self.tok[i] for i in idx)
                if not a:
                    continue
                b = self.df[x] - a
                s += token_weight(x) * max(0.0, math.log((a + 0.5) / (len(idx) + 1))
                                            - math.log((b + 0.5) / (n - len(idx) + 1)))
            out[eng] = s
        return out

    def neighbours(self, toks: set[str], k: int = 3) -> list[dict]:
        n = len(self.titles) or 1
        idf = {x: token_weight(x) * math.log(1 + n / (1 + self.df[x])) for x in toks | set().union(*self.tok) if x}
        out = []
        for t, ts in zip(self.titles, self.tok):
            inter = sum(idf[x] for x in toks & ts)
            union = sum(idf[x] for x in toks | ts) or 1
            if inter > 0:
                out.append({"id": t["id"], "title": t["title"], "similarity": round(inter / union, 3),
                            "engines": t["engines"], "reader": t["reader"], "shared": sorted(toks & ts)[:12]})
        return sorted(out, key=lambda r: -r["similarity"])[:k]


def _rank(counter: Counter, kind: str) -> list[dict]:
    rows = [{"id": sid, "format": SIGNATURES[sid][1], "files": n} for sid, n in counter.items() if SIGNATURES[sid][0] == kind]
    return sorted(rows, key=lambda r: -r["files"])


def rule_scores(ev: dict, toks: set[str]) -> tuple[dict[str, float], dict[str, list[str]]]:
    """Generic engine knowledge: magic engine hints, extension conventions, markers in strings/symbols."""
    score, why = Counter(), {}
    for src, ctr, w in (("magic", ev["heads"], 3.0), ("inside archives", ev["inner"], 2.5)):
        for sid, n in ctr.items():
            for eng in SIGNATURES[sid][4]:
                score[eng] += w * math.log2(1 + n)
                why.setdefault(eng, []).append(f"{src}: {SIGNATURES[sid][1]} x{n}")
    for eng, exts in EXT_HINTS.items():
        hits = {e: ev["exts"][e] for e in exts if ev["exts"].get(e)}
        if hits:
            score[eng] += 1.5 * math.log2(1 + sum(hits.values()))
            why.setdefault(eng, []).append("extensions " + ", ".join(f"{e} x{n}" for e, n in hits.items()))
    for x in toks:
        if x.startswith("marker:"):
            eng = x[7:]
            score[eng] += 4.0
            why.setdefault(eng, []).append("marker in executable strings/symbols")
    return dict(score), why


def fingerprint_evidence(ev: dict, known: list[dict] | None = None) -> dict:
    known = KNOWN_TITLES if known is None else known
    toks = tokens(ev)
    model = Model(known)
    rules, why = rule_scores(ev, toks)
    learned = model.engine_scores(toks)
    engines = []
    for eng in set(rules) | {e for e, s in learned.items() if s > 0}:
        s = rules.get(eng, 0.0) + learned.get(eng, 0.0)
        engines.append({"engine": eng, "label": ENGINE_LABELS.get(eng, eng), "score": round(s, 2),
                        "confidence": round(1 - math.exp(-s / 6), 3), "rules": round(rules.get(eng, 0.0), 2),
                        "learned": round(learned.get(eng, 0.0), 2), "why": why.get(eng, [])[:6]
                        + ([f"learned from {len([t for t in known if eng in t['engines']])} assimilated title(s)"]
                           if learned.get(eng) else [])})
    engines.sort(key=lambda r: -r["score"])
    allm = ev["heads"] + ev["inner"]
    out = {"platform": ev.get("platform"), "title": ev.get("title"), "files": ev["files"],
           "engines": engines[:6],
           "containers": _rank(allm, "container"), "codecs": _rank(allm, "codec"), "models": _rank(allm, "model"),
           "textures": _rank(allm, "texture"), "animations": _rank(allm, "animation"),
           "executables": _rank(ev["heads"], "executable"),
           "extensions": dict(ev["exts"].most_common(15)), "strings_checked": len(ev["strings"]),
           "symbols": len(ev["symbols"]), "nearest_titles": model.neighbours(toks)}
    out["proposal"] = propose(out)
    return out


def propose(fp: dict) -> dict:
    """What to start from: the nearest assimilated title's reader, the engine's reader family, the shared pieces."""
    top = fp["engines"][0] if fp["engines"] else None
    near = fp["nearest_titles"][0] if fp["nearest_titles"] else None
    shared = ["gbox.formats.disc (listing + executable)"]
    codecs = {r["id"] for r in fp["codecs"]}
    if codecs & {"mio0", "yaz0", "vpk0", "lz10"} or codecs & {"zlib", "gzip"}:
        shared.append("gbox.formats.lz")
    if "rnc" in codecs:
        shared.append("gbox.formats.rnc")
    if {r["id"] for r in fp["textures"]} & {"tim"}:
        shared.append("gbox.formats.texture (TIM)")
    if {r["id"] for r in fp["textures"]} & {"pvrt", "gbix", "pvmh", "gvrt", "gvmh"}:
        shared.append("gbox.formats.texture (twiddle) + gbox.ninja.pvr_decode")
    if fp.get("platform") in ("psx", "ps2"):
        shared.append("gbox.formats.iso9660")
    if fp.get("platform") in ("gamecube", "wii"):
        shared.append("gbox.formats.gcfst")
    shared.append("gbox.formats.rig (role maps) + gbox.sm64_swap.retarget (writer)")
    steps = ["re_study (executable as ELF in Ghidra)",
             "playbook asset-loader-format: Ghidra strings for the top extensions/magics above, refs -> loader",
             "first reader test: parse every file of the top container without errors (counts/offsets in range)",
             "round-trip proof before any writer (playbook round-trip-proof)"]
    if not fp["models"]:
        steps.insert(1, "no model magic seen: models are headerless or packed; search the executable for the loader "
                        "(playbook string-xref-loader) or capture RAM/frames (playbooks ram-capture, frame-capture)")
    eng = top["engine"] if top and top["confidence"] >= 0.5 else None
    return {"engine": eng, "start_from": (near["reader"] if near and near["similarity"] >= 0.2 else None),
            "engine_reader": ENGINE_READERS.get(eng) if eng else None, "shared": shared, "next_steps": steps,
            "skeleton": skeleton(fp, eng, near)}


def skeleton(fp: dict, eng: str | None, near: dict | None) -> str:
    title = fp.get("title") or "<title>"
    mod = re.sub(r"[^a-z0-9]+", "_", re.sub(r"\([^)]*\)", "", title).lower()).strip("_")[:24] or "newgame"
    cont = fp["containers"][0]["format"] if fp["containers"] else "unknown container"
    model = fp["models"][0]["format"] if fp["models"] else "unknown model format"
    lines = [f"# gbox/{mod}.py",
             f'"""{title}: reader (skeleton from gbox.assimilate). Engine: {ENGINE_LABELS.get(eng, eng) or "unknown"}.',
             f"Container: {cont}. Model: {model}.",
             f"Start from: {near['reader'] if near else 'gbox.formats'}"
             f"{' (nearest assimilated title: ' + near['title'] + ')' if near else ''}.", '"""',
             "from __future__ import annotations", "", "from .formats import disc, lz, rig, texture",
             ]
    if near:
        lines.append(f"from . import {near['reader'].split('.')[-1]} as ref   # nearest assimilated title's reader")
    lines += ["", "", "def inventory(path) -> dict:",
              '    """Stage 1: exact build identity + container layout + character asset census."""',
              "    L = disc.listing(path)", "    return {\"source\": L.source, \"executable\": L.executable_name, "
              "\"files\": len(L.files)}", "", "",
              "def read_model(blob: bytes) -> dict:",
              f'    """Stage 3: {model} -> nodes, vertices, triangles, materials (prove on every file of the build)."""',
              "    raise NotImplementedError", "", "",
              "def to_glb(model: dict, out) -> None:",
              '    """Rigged GLB for the character library (gbox.gta_rw.write_skinned_glb / melee_models.write_gltf)."""',
              "    raise NotImplementedError", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------- entry points

def fingerprint_listing(L, platform: str = "", title: str = "", known: list[dict] | None = None) -> dict:
    exe = getattr(L, "executable", b"") or b""
    ev = evidence(L.files, exe_strings(exe), elf_symbols(exe), platform, title, getattr(L, "executable_name", ""))
    fp = fingerprint_evidence(ev, known)
    fp.update(source="disc", path=L.source, kind=L.kind, executable=L.executable_name, notes=list(L.notes))
    return fp


def fingerprint_path(path, platform: str = "", title: str = "", **kw) -> dict:
    from .formats import disc
    return fingerprint_listing(disc.listing(path, **kw), platform, title)


def metadata_fingerprint(title: str, platform: str, known: list[dict] | None = None) -> dict:
    """No files reachable: title words + platform against the assimilated titles (a weaker prior, said so)."""
    ev = evidence([], [], [], platform, title)
    fp = fingerprint_evidence(ev, known)
    fp["source"] = "metadata"
    fp["platform_formats"] = PLATFORM_PRIORS.get(platform, [])
    fp["notes"] = ["no disc/ROM readable here: engine guess from the title and platform only; run assimilate "
                   "op=fingerprint on a worker that has the files"]
    return fp


def summary(fp: dict) -> str:
    """One paragraph for tickets and prompts."""
    eng = fp["engines"][0] if fp.get("engines") else None
    near = fp.get("nearest_titles") or []
    parts = [f"engine {eng['label']} ({eng['confidence']:.2f})" if eng else "engine unknown"]
    for k in ("containers", "codecs", "models", "textures", "animations"):
        if fp.get(k):
            parts.append(f"{k}: " + ", ".join(f"{r['format']} x{r['files']}" for r in fp[k][:3]))
    if near:
        parts.append("nearest: " + ", ".join(f"{n['title']} ({n['similarity']}, {n['reader']})" for n in near[:2]))
    pr = fp.get("proposal") or {}
    if pr.get("start_from") or pr.get("engine_reader"):
        parts.append(f"start from {pr.get('start_from') or pr.get('engine_reader')}")
    return f"[{fp.get('source', 'disc')}] " + "; ".join(parts)


def evaluate(known: list[dict] | None = None, rules: bool = True) -> dict:
    """Leave-one-out over the knowledge base: hide each title, fingerprint its documented layout with what is left.
    engine_top1: the title's primary engine family ranks first (titles whose family has a generic marker or another
    assimilated member; a family seen once with no marker is 'novel'). neighbour: the nearest remaining title shares an
    engine family (when one exists). container/model: the documented head/inner magics are recovered."""
    known = KNOWN_TITLES if known is None else known
    rows = []
    for i, t in enumerate(known):
        rest = known[:i] + known[i + 1:]
        ev = kb_title_evidence(t)
        if not rules:
            ev = dict(ev, strings=[], symbols=[])
        fp = fingerprint_evidence(ev, rest)
        if not rules:
            fp["engines"] = sorted([e for e in fp["engines"] if e["learned"] > 0], key=lambda e: -e["learned"])
        fam = t["engines"]
        # reachable: another assimilated member of the family exists, or the generic rules fire on this evidence
        reachable = any(set(fam) & set(r["engines"]) for r in rest) or bool(
            set(fam) & set(rule_scores(ev, tokens(ev))[0]))
        top = fp["engines"][0]["engine"] if fp["engines"] else None
        near = fp["nearest_titles"][0] if fp["nearest_titles"] else None
        sib = any(set(fam) & set(r["engines"]) for r in rest)
        rows.append({"id": t["id"], "engines": fam, "reachable": reachable, "top": top, "engine_ok": top in fam,
                     "has_sibling": sib, "nearest": near["id"] if near else None,
                     "neighbour_ok": bool(near and set(near["engines"]) & set(fam))})
    reach = [r for r in rows if r["reachable"]]
    sib = [r for r in rows if r["has_sibling"]]
    return {"titles": len(rows), "engine_reachable": len(reach),
            "engine_top1": round(sum(r["engine_ok"] for r in reach) / max(1, len(reach)), 3),
            "engine_top1_all": round(sum(r["engine_ok"] for r in rows) / max(1, len(rows)), 3),
            "with_sibling": len(sib), "neighbour_top1": round(sum(r["neighbour_ok"] for r in sib) / max(1, len(sib)), 3),
            "misses": [r for r in rows if r["reachable"] and not r["engine_ok"]], "rows": rows}


def ticket_fingerprint(game_id: str, title: str = "", platform: str = "", api=None, config=None,
                       max_files: int = 3000) -> dict:
    """Best-effort fingerprint for a new readiness ticket: the owned files when this host can read them, else the
    title/platform prior. Never raises (a ticket is never blocked on it); returns a compact dict."""
    fp, err = None, ""
    try:
        if api is not None:
            game = api(f"/api/catalog/{game_id}") or {}
            title, platform = game.get("title") or title, game.get("platform") or platform
            from .models import CatalogEntry
            from .tools import rom_path
            if config is None:                           # the queue runs from cron: find gbox.toml next to the package
                import os
                from .config import load
                config = load(os.environ.get("GBOX_CONFIG") or Path(__file__).resolve().parents[1] / "gbox.toml")
            p = rom_path(CatalogEntry.model_validate(game), config)
            if p.exists():
                fp = fingerprint_path(p, platform, title, max_files=max_files, deep=6, deep_bytes=1 << 19)
    except Exception as e:                               # noqa: BLE001  (file route optional)
        err = f"{type(e).__name__}: {e}"[:200]
    try:
        if fp is None:
            fp = metadata_fingerprint(title, platform)
            if err:
                fp["notes"].append(f"file route: {err}")
    except Exception as e:                               # noqa: BLE001
        return {"source": "error", "error": f"{type(e).__name__}: {e}"[:200], "summary": "fingerprint unavailable"}
    return compact(fp)


def compact(fp: dict) -> dict:
    pr = fp.get("proposal") or {}
    return {"source": fp.get("source", "disc"), "summary": summary(fp),
            "engines": [{k: e[k] for k in ("engine", "label", "confidence")} for e in fp.get("engines", [])[:3]],
            "containers": [r["format"] for r in fp.get("containers", [])[:3]],
            "codecs": [r["format"] for r in fp.get("codecs", [])[:3]],
            "models": [r["format"] for r in fp.get("models", [])[:3]],
            "textures": [r["format"] for r in fp.get("textures", [])[:3]],
            "nearest_titles": [{k: n[k] for k in ("id", "title", "similarity", "reader")} for n in fp.get("nearest_titles", [])[:3]],
            "start_from": pr.get("start_from"), "engine_reader": pr.get("engine_reader"),
            "next_steps": pr.get("next_steps", [])[:4], "notes": fp.get("notes", [])[:4]}


# ------------------------------------------------------------------------------------------- typed tool

class AssimilateIn(BaseModel):
    op: str = "fingerprint"            # fingerprint | known | evaluate
    game_id: str = ""
    path: str = ""                     # a disc image / ROM / folder on this worker instead of a catalog game
    max_files: int = 4000


class AssimilateOut(BaseModel):
    op: str
    result: dict


@tool("assimilate", "1.0", AssimilateIn, AssimilateOut, capabilities=["analysis"], timeout_s=1800,
      artifacts=["fingerprint.json"], side_effects=[])
def assimilate(inp: AssimilateIn, ctx):
    """Fingerprint a game before reverse engineering it (op=fingerprint game_id=... | path=...): ranked containers,
    codecs, model/texture/animation formats, engine/middleware, the nearest assimilated titles and a reader skeleton
    to start from. op=known lists what gBox has assimilated; op=evaluate is the leave-one-out accuracy."""
    import json
    if inp.op == "known":
        return {"op": "known", "result": {"titles": [{k: t.get(k) for k in ("id", "title", "platform", "engines", "reader",
                                                                          "techniques", "effort")} for t in KNOWN_TITLES]}}
    if inp.op == "evaluate":
        r = evaluate()
        r2 = evaluate(rules=False)
        return {"op": "evaluate", "result": {k: v for k, v in r.items() if k != "rows"} | {
            "learned_only": {k: r2[k] for k in ("engine_top1", "neighbour_top1")}}}
    if inp.op != "fingerprint":
        raise ValueError("op: fingerprint | known | evaluate")
    title = platform = ""
    if inp.path:
        p = Path(inp.path)
    elif inp.game_id:
        from .models import CatalogEntry
        from .re_lab_tool import _api
        from .tools import rom_path
        game = _api(ctx, "GET", f"/api/catalog/{inp.game_id}")
        title, platform = game.get("title", ""), game.get("platform", "")
        p = rom_path(CatalogEntry.model_validate(game), ctx.config)
    else:
        raise ValueError("fingerprint needs game_id or path")
    ctx.progress(5, f"listing {p.name}")
    if not p.exists():
        fp = metadata_fingerprint(title, platform)
        fp["notes"].append(f"{p} isn't readable on this node")
    else:
        fp = fingerprint_path(p, platform, title, max_files=inp.max_files)
    fp["game_id"] = inp.game_id
    ctx.artifact("fingerprint.json", json.dumps(fp, indent=1, default=str).encode(), "application/json",
                 game_id=inp.game_id)
    ctx.progress(100, summary(fp)[:200])
    return {"op": "fingerprint", "result": fp | {"summary": summary(fp)}}
