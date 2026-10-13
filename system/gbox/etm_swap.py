"""Enter the Matrix (PS2 SLUS-20454) character writer: any collection character in place of any cast member.

The owned "Enter the Matrix (USA)" windows_native entry is the PS2 disc (a HyperSpin CHD filed under "Microsoft
XBOX"; no PC install exists), so a mod is a patched copy of that disc: the vanilla ISO is unpacked from the CHD once
per game (gbox.chd, ``cache/modbase/<game>/``), copied into the mod folder, and only the replaced
``actors\\<model>.dcn`` entries of ``WAD1.DFU`` / ``WAD1_B.DFU`` are rewritten in place (their bytes + their table
row: packed size, size). The catalog's install is never written.

The donor is fitted onto the shared 89-joint skeleton (``sm64_swap.retarget`` with the ETM joint map: rigid per
limb, one joint per vertex, in the game's A-pose) and written as a new .dcn that keeps the original's skeleton
checksum, joint arrays, header and config count: one mesh of plain textured triangles (the block the game draws for
low-poly models such as ``Morpheus.dcn``, every vertex {uv, position + joint, normal}), up to four 256 x 256 8-bit
pages (``gta_stories_models.pack_atlases``) and one material per page. It has to fit the entry's slot: the packed
(zlib) size within the original packed size and the file within the original size, so the fit shrinks the pages and
clusters vertices until it does. Every written entry is read back from the image (archive table, inflate, parse,
triangle count). Unverified in game: the operator's PCSX2 run is the remaining check (docs/matrix_pipeline.md).
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np

from . import etm_inventory as inv
from . import etm_models as M
from .shiny_dfu import Dfu, DfuError, image_patches

GAME_IDS = {inv.GAME_ID: "Enter the Matrix (USA) - the PS2 disc SLUS-20454 (HyperSpin CHD filed as windows_native)"}
PAGE = 256
PAGE_COUNTS = (4, 3, 2, 1)
CLUSTER = (0.0, 0.004, 0.007, 0.011, 0.016, 0.024, 0.035, 0.05)   # vertex-cluster cell, fraction of the height
MESH_FLAGS = 64                                       # the opaque render flags most meshes carry

# cast slot -> (display name, kind, model stems it replaces)
SLOTS = {
    "niobe": ("Niobe", "player", ["Niobe_Costume01", "Niobe_Costume02", "Niobe_Costume03", "Niobe_Costume04",
                                "Niobe_Costume05", "Niobe_1_phase", "Niobe_thermal"]),
    "ghost": ("Ghost", "player", ["Ghost_Costume01", "Ghost_Costume02", "Ghost_Costume03", "Ghost_Costume04",
                                "Ghost_Costume05", "Ghost_Gi", "Ghost_phasing"]),
    "agent_smith": ("Agent Smith", "character", ["AgentSmith"]),
    "agent_jackson": ("Agent Jackson", "enemy", ["AgentJackson"]),
    "agent_johnson": ("Agent Johnson", "character", ["agentjohnson"]),
    "agent_thompson": ("Agent Thompson", "enemy", ["AgentThompson"]),
    "agents": ("Agents (group)", "enemy", ["Agents_3"]),
    "trinity": ("Trinity", "character", ["Trinity_zen"]),
    "morpheus": ("Morpheus", "character", ["Morpheus_coat", "Morpheus"]),
    "neo": ("Neo", "character", ["Neo"]),
    "seraph": ("Seraph", "character", ["Seraph"]),
    "keymaker": ("Keymaker", "character", ["Keymaker"]),
    "merovingian": ("Merovingian", "character", ["merovingian"]),
    "twins": ("Twins", "character", ["Twin01"]),
    "vlad": ("Vlad", "character", ["Vlad"]),
    "cujo": ("Cujo", "character", ["cujo"]),
    "abel": ("Abel", "character", ["abel"]),
    "cain": ("Cain", "character", ["Cain"]),
    "bane": ("Bane", "character", ["Bane"]),
    "axel": ("Axel", "character", ["axel"]),
    "ballard": ("Ballard", "character", ["Ballard"]),
    "binary": ("Binary", "character", ["Binary"]),
    "malachi": ("Malachi", "character", ["Malachi"]),
    "corrupt": ("Corrupt", "character", ["Corrupt"]),
    "vector": ("Vector", "character", ["vector"]),
    "wurm": ("Wurm", "character", ["wurm"]),
    "soren": ("Captain Soren", "character", ["Captain_Soren"]),
    "ice": ("Captain Ice", "character", ["captain_ice"]),
    "sparks": ("Sparks", "character", ["Sparks"]),
    "swat": ("SWAT officers", "enemy", ["Swat", "Swat_armored", "Swat_sniper", "Swat_pilot", "Swat_sewer",
                                        "Swat_thermal", "Swat_xbox"]),
    "police": ("Police officers", "enemy", ["Cop", "Cop_LP"]),
    "security": ("Security guards", "enemy", ["security_guard"]),
    "vampires": ("Vampires", "enemy", ["Bloodsucker_1", "Bloodsucker_fem"]),
    "prisoners": ("Prisoners", "npc", ["prisoner_1"]),
    "workers": ("Workers (post office, power plant, airport)", "npc",
                ["postal_worker", "postal_sorter", "postal_operator", "pplant_repairman", "PPlant_welder",
                 "aport_mechanic", "janitor"]),
    "civilians": ("Civilians", "pedestrian", ["Civ_male01", "Civ_male02", "Civ_Female01", "Civ_Female02",
                                              "sewing_woman", "shopkeeper"]),
}
PLAYER = ("niobe", "ghost")
SIZE = {"agent_smith": 1.2, "agent_johnson": 1.2, "agent_jackson": 1.2, "agent_thompson": 1.2, "agents": 1.2,
        "morpheus": 1.2, "twins": 1.1, "seraph": 1.1, "vlad": 1.15, "cujo": 1.15, "abel": 1.1, "cain": 1.1,
        "trinity": 1.0, "niobe": 0.95, "ghost": 1.0, "keymaker": 0.9, "sparks": 0.95, "civilians": 1.0}


class SwapError(ValueError):
    pass


def cast_slots() -> list[dict]:
    """The cast menu / whole-cast swap: one slot per character group (costumes and variants of one character are
    one slot: every model file it lists is rewritten with the same donor); `player` = Niobe + Ghost (aggregate)."""
    out = [{"slot": "player", "name": "the playable heroes (Niobe, Ghost)", "kind": "player", "aggregate": True,
            "writer": "gbox.etm_swap"}]
    for s, (name, kind, stems) in SLOTS.items():
        out.append({"slot": s, "name": name, "kind": "player" if s in PLAYER else kind, "models": len(stems),
                    "size": SIZE.get(s, 1.0), "writer": "gbox.etm_swap"})
    return out


def resolve_slot(slot: str) -> list[str]:
    s = (slot or "player").split(":", 1)[-1]
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    if s == "player":
        return [m for k in PLAYER for m in SLOTS[k][2]]
    if s in SLOTS:
        return list(SLOTS[s][2])
    for k, (name, _kind, stems) in SLOTS.items():                 # a display name or one model file
        if s == re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"):
            return list(stems)
        for st in stems:
            if s == st.lower():
                return [st]
    raise SwapError(f"{slot!r} is not an Enter the Matrix cast slot (have: player, {', '.join(SLOTS)})")


# ---------------------------------------------------------------- fit
def target(m: dict) -> dict:
    """sm64_swap.retarget target: the shared skeleton's rest positions in glTF space (metres, facing +Z)."""
    T = M.to_gltf(m["joint_positions"])
    a = M.assemble(m, 0, 2)
    allp = np.concatenate([p["pos"] for p in a["prims"]])
    head = np.concatenate([p["pos"][(p["joints"][:, 0] == 15) | (p["joints"][:, 0] >= 60)] for p in a["prims"]])
    return {"T": T, "parent": m["parents"], "ground": float(allp[:, 1].min()),
            "head_h": float(np.ptp(head[:, 1])) if len(head) > 8 else 0.22, "joints": len(T)}


def fit(model: Path, roles: dict, tgt: dict, props=(), scale=None) -> dict:
    """Collection model -> retargeted triangles in glTF space: {prims (sm64_swap.retarget output), report}."""
    from .sm64_swap import load_rig, retarget
    if "hip" not in roles:
        raise SwapError("the character has no body roles (rig.roles): it can't be mapped onto the ETM skeleton")
    rig = load_rig(Path(model), roles, props)
    prims, rep = retarget(rig, tgt, scale, M.ROLE_JOINTS)
    head = M.ROLE_JOINTS["head"]
    hp = [np.asarray(p["pos"])[np.asarray(p["J"])[:, 0] == head] for p in prims]
    hp = np.concatenate([h for h in hp if len(h)]) if any(len(h) for h in hp) else np.zeros((0, 3))
    if len(hp) and not (scale or {}).get("head"):          # chibi heads (Sonic, Mario) on a realistic skeleton:
        hh = float(np.ptp(hp[:, 1]))                       # shrink to ~1.3 x the cast's head, never grow
        if hh > 1.6 * tgt["head_h"]:
            k = max(0.35, 1.3 * tgt["head_h"] / hh)
            prims, rep = retarget(rig, tgt, {**(scale or {}), "head": k}, M.ROLE_JOINTS)
            rep["auto_head_scale"] = round(k, 3)
    prims = [p for p in prims if len(p["tris"])]
    if not prims:
        raise SwapError("the character has no triangles")
    return {"prims": prims, "report": rep}


def _cluster(P: np.ndarray, J: np.ndarray, cell: float) -> np.ndarray:
    """Vertex clustering per joint: every corner position snaps to the mean of its (joint, cell) bucket."""
    if cell <= 0:
        return P
    key = np.concatenate([J[:, None].astype(np.int64), np.floor(P / cell).astype(np.int64)], 1)
    _u, inv_ = np.unique(key, axis=0, return_inverse=True)
    inv_ = inv_.reshape(-1)
    s = np.zeros((inv_.max() + 1, 3))
    np.add.at(s, inv_, P)
    n = np.bincount(inv_)[:, None]
    return (s / n)[inv_]


def triangles(fitted: dict, pages: int) -> dict:
    """Retargeted prims -> per-corner arrays (t, 3, *) in glTF space + the atlas pages (RGBA and 8-bit CLUT)."""
    from .gta_stories_models import pack_atlases
    prims = fitted["prims"]
    atl, maps = pack_atlases(prims, [(PAGE, PAGE)] * pages)
    P, Nn, UV, J, PG = [], [], [], [], []
    for p, (a, uv) in zip(prims, maps):
        T = np.asarray(p["tris"], int).reshape(-1, 3)
        P.append(np.asarray(p["pos"], float)[T])
        Nn.append(np.asarray(p["nrm"], float)[T])
        J.append(np.asarray(p["J"])[:, 0][T])
        UV.append(uv)
        PG.append(np.full(len(T), a))
    P, Nn, UV, J, PG = (np.concatenate(x) for x in (P, Nn, UV, J, PG))
    return {"pos": P, "nrm": Nn, "uv": UV, "joint": J, "page": PG, "pages": atl, "clut": [_quantize(a) for a in atl]}


def clustered(tri: dict, cluster: float) -> dict:
    """Fewer triangles: corners snapped per (joint, cell) and the collapsed triangles dropped (UVs stay per corner)."""
    if cluster <= 0:
        return tri
    P, J = tri["pos"], tri["joint"]
    h = float(np.ptp(P[..., 1]))
    flat = _cluster(P.reshape(-1, 3), J.reshape(-1), cluster * h).reshape(P.shape)
    a, b, c = flat[:, 0], flat[:, 1], flat[:, 2]
    keep = np.linalg.norm(np.cross(b - a, c - a), axis=1) > 1e-10
    return tri | {"pos": flat[keep], "nrm": tri["nrm"][keep], "uv": tri["uv"][keep], "joint": J[keep],
                  "page": tri["page"][keep]}


# ---------------------------------------------------------------- encode
def _quantize(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from .defjam_writer import quantize
    idx, pal = quantize(img, 256)
    return idx, pal


def encode(base: bytes, tri: dict) -> bytes:
    """A new .dcn: the base's header / skeleton, one mesh of plain triangles, the pages, one material per page and
    as many (identical) configs as the base had."""
    m = M.parse_dcn(base)
    nj = len(m["joint_positions"])
    pages = tri["pages"]
    npg = len(pages)
    ncfg = max(1, len(m["configs"]))
    used = sorted(set(int(p) for p in np.unique(tri["page"])))
    if not used:
        raise SwapError("no triangles to write")
    # model space: centimetres, z mirrored; stored winding is the mirror of glTF's front face (as the game's own)
    Pm = to_model(tri["pos"])
    Nm = np.asarray(tri["nrm"], float).copy()
    Nm[..., 2] *= -1
    Nm /= np.maximum(np.linalg.norm(Nm, axis=-1, keepdims=True), 1e-9)
    order = [0, 2, 1]
    if np.any(tri["joint"] >= nj) or np.any(tri["joint"] < 0):
        raise SwapError("a vertex is bound to a joint outside the skeleton")
    body = bytearray()
    for t in range(len(Pm)):
        body += struct.pack("<4I", int(tri["page"][t]), 10, 3, 0)
        for k in order:
            u, v = tri["uv"][t, k]
            x, y, z = Pm[t, k]
            nx, ny, nz = Nm[t, k]
            body += struct.pack("<2f2I", float(u), float(v), 0, 0)
            body += struct.pack("<3fI", float(x), float(y), float(z), int(tri["joint"][t, k]) * 4)
            body += struct.pack("<3fI", float(nx), float(ny), float(nz), 0)
    out = bytearray(base[:M.HEADER])
    struct.pack_into("<I", out, 0x24, npg)
    struct.pack_into("<I", out, 0x2C, npg)
    struct.pack_into("<I", out, 0x34, ncfg)
    struct.pack_into("<I", out, 0x40, 1)
    out += b"\0" * 4                                       # the one mesh pointer slot
    out += m["joint_offsets"].astype("<f4").tobytes() + m["joint_positions"].astype("<f4").tobytes()
    hdr = bytearray(M.SUB_HDR)
    hdr[:0x14] = b"gbox_etm\0".ljust(0x14, b"\0")
    struct.pack_into("<4I", hdr, 0x14, 0xFFFFFFFF, MESH_FLAGS, 0x78001045, 0)
    struct.pack_into("<4I", hdr, 0x24, 0, 0, len(Pm), 0)
    struct.pack_into("<iI", hdr, 0x34, -1, 0)
    struct.pack_into("<4I", hdr, 0x3C, 0, 0, len(body), 0)
    out += hdr + body
    tpl = next((t["header"] for t in m["textures"] if t["bpp"] == 8), None) or \
        (m["textures"][0]["header"] if m["textures"] else bytes(M.TEX_HDR))
    texdata = bytearray()
    for i, (idx, pal) in enumerate(tri.get("clut") or [_quantize(a) for a in pages]):
        th = bytearray(tpl)
        th[:0x20] = f"gbox_page{i}.tga".encode().ljust(0x20, b"\0")
        struct.pack_into("<2I", th, 0x20, PAGE, PAGE)
        struct.pack_into("<I", th, 0x2C, PAGE * PAGE)
        struct.pack_into("<I", th, 0x34, 1024)
        out += th
        texdata += idx.astype(np.uint8).tobytes() + pal.astype(np.uint8).tobytes()
    out += texdata
    mtpl = m["materials"][0]["raw"] if m["materials"] else bytes(M.MAT_SIZE)
    for i in range(npg):
        r = bytearray(mtpl)
        r[:0x20] = f"gbox_page{i}".encode().ljust(0x20, b"\0")
        struct.pack_into("<3i", r, 0x20, i, -1, -1)
        struct.pack_into("<f", r, 0x2C, 0.0)
        out += r
    for _c in range(ncfg):
        out += struct.pack("<5I", 0, 1, 0, 0, 0)
    for _c in range(ncfg):
        out += struct.pack("<i", 0) + struct.pack(f"<{npg}i", *range(npg))
    return bytes(out)


def verify(new: bytes, tri: dict) -> dict:
    """Read the written file with the reader: every triangle back, positions / joints / UVs as encoded, the
    skeleton block untouched (checksum), the config shows the mesh."""
    m = M.parse_dcn(new)
    pk = [p for p in m["meshes"][0]["patches"] if p["kind"] == "tri3"]
    want = len(tri["pos"])
    P = to_model(tri["pos"])[:, [0, 2, 1]]
    ok = len(pk) == want and m["checksum"] == inv.SKELETON_CHECKSUM and m["configs"][0]["meshes"] == [0]
    err = 0.0
    if ok and want:
        Q = np.stack([p["pos"] for p in pk])
        Jb = np.stack([p["joints"][:, 0] for p in pk])
        UVb = np.stack([p["uv"] for p in pk])
        err = float(np.abs(Q - P).max())
        ok = err < 1e-2 and np.array_equal(Jb, tri["joint"][:, [0, 2, 1]]) and \
            float(np.abs(UVb - tri["uv"][:, [0, 2, 1]]).max()) < 1e-5
    return {"ok": bool(ok), "triangles": len(pk), "expected": want, "max_position_error": round(err, 5)}


def to_model(p: np.ndarray) -> np.ndarray:
    """glTF space (m, facing +Z) -> the game's model space (cm, facing -Z)."""
    q = np.asarray(p, float) / M.GLTF_SCALE
    q[..., 2] *= -1
    return q


def fit_entry(base: bytes, packed_cap: int, fitted: dict, compressed: bool = True) -> dict:
    """The largest encoding (pages, vertex clustering) whose packed bytes fit the entry's slot and whose file is no
    bigger than the original. -> {data, triangles, pages, cluster, packed, verify}."""
    import zlib
    tried = []
    for pages in PAGE_COUNTS:
        full = triangles(fitted, pages)
        for cl in CLUSTER:
            tri = clustered(full, cl)
            data = encode(base, tri)
            packed = len(zlib.compress(data, 9)) if compressed else len(data)
            tried.append((pages, cl, len(tri["pos"]), len(data), packed))
            if packed <= packed_cap and len(data) <= len(base):
                v = verify(data, tri)
                if not v["ok"]:
                    raise SwapError(f"the encoded model does not read back: {v}")
                return {"data": data, "triangles": len(tri["pos"]), "pages": pages, "cluster": cl, "packed": packed,
                        "size": len(data), "verify": v, "tried": len(tried)}
    raise SwapError(f"the character doesn't fit the {packed_cap}-byte slot even at 1 page and the coarsest "
                    f"clustering (last try {tried[-1]})")


# ---------------------------------------------------------------- disc
def base_iso(cfg, game: dict, src: Path, progress=lambda p, m: None) -> Path:
    """The vanilla ISO, unpacked from the catalog CHD once per game (cache/modbase/<game>/<name>.iso)."""
    from . import filemods
    src = Path(src)
    if src.suffix.lower() == ".iso":
        return src
    out = filemods.base_dir(cfg, game["game_id"]) / (src.stem + ".iso")
    if not out.is_file():
        from .chd import ChdDisc
        progress(5, f"Unpacking {src.name} to a plain ISO (once per game, ~4 GB)")
        ChdDisc(src).write_iso(out, lambda d, n: progress(5 + 25 * d / max(n, 1), "unpacking the CHD"))
    return out


def build_disc(src_iso: Path, out_iso: Path, jobs: list[dict], progress=lambda p, m: None) -> dict:
    """jobs [{slot, model, roles, name, props, scale}] -> a copy of the ISO with each slot's .dcn entries rewritten.
    A job that fails (no roles, doesn't fit) is reported and skipped; the others are still written."""
    from .defjam_inventory import Iso
    disc = Iso(src_iso)
    ident = inv.identify(disc)
    if not ident["exact_build"]:
        raise SwapError(f"{ident['boot']}: the writer is built on {inv.SERIAL} only")
    dfu = Dfu(disc, "etm")
    patches, reports = [], []
    for k, jb in enumerate(jobs):
        rep = {"slot": jb["slot"], "character": jb["name"], "entries": [], "status": "failed"}
        try:
            stems = resolve_slot(jb["slot"])
            if "hip" not in (jb.get("roles") or {}):
                raise SwapError("the character has no body roles (rig.roles): it can't be mapped onto the ETM skeleton")
            have = [st for st in stems if M.model_path(st) in dfu]
            if not have:
                raise SwapError(f"none of the slot's models ({', '.join(stems)}) is on this disc")
            progress(30 + 50 * k / max(len(jobs), 1), f"Fitting {jb['name']} onto {jb['slot']} ({len(stems)} models)")
            first = dfu.read(M.model_path(have[0]))
            fitted = fit(jb["model"], jb["roles"], target(M.parse_dcn(first)), jb.get("props") or (), jb.get("scale"))
            for st in stems:                               # one file failing doesn't stop the slot's other files
                path = M.model_path(st)
                e = dfu.entry(path)
                if e is None:
                    rep["entries"].append({"model": path, "status": "missing"})
                    continue
                try:
                    r = fit_entry(dfu.read(e), e.packed, fitted, e.compressed)
                    plan = dfu.replace_plan(e, r["data"])
                except (SwapError, DfuError, M.FormatError) as x:
                    rep["entries"].append({"model": path, "status": "failed", "reason": str(x)[:300]})
                    continue
                patches += image_patches(disc, plan)
                rep["entries"].append({"model": path, "status": "built", "triangles": r["triangles"],
                                       "pages": r["pages"], "cluster": r["cluster"], "size": r["size"],
                                       "packed": r["packed"], "slot_bytes": e.packed, "data": r["data"]})
            built = [x for x in rep["entries"] if x["status"] == "built"]
            rep["status"] = "built" if len(built) == len(stems) else "partial" if built else "failed"
            rep["fit"] = {k2: v for k2, v in fitted["report"].items() if k2 in ("scale", "head_scale", "limb_stretch")}
        except (SwapError, DfuError, ValueError, KeyError) as x:
            rep["reason"] = str(x)[:400]
        reports.append(rep)
    if not patches:
        raise SwapError("; ".join(f"{r['slot']}: {r.get('reason', 'nothing written')}" for r in reports))
    out_iso = Path(out_iso)
    out_iso.parent.mkdir(parents=True, exist_ok=True)
    progress(82, f"Copying the disc image ({Path(src_iso).stat().st_size >> 20} MB)")
    shutil.copyfile(src_iso, out_iso)
    with open(out_iso, "r+b") as f:
        for off, blob in patches:
            f.seek(off)
            f.write(blob)
    progress(95, "Reading the written models back from the image")
    back = Dfu(Iso(out_iso), "etm")
    for rep in reports:
        for x in rep["entries"]:
            if x.get("status") != "built":
                continue
            got = back.read(x["model"])
            if got != x.pop("data"):
                raise SwapError(f"{x['model']} does not read back from the patched image")
            x["read_back"] = True
    return {"image": str(out_iso), "reports": reports}


# ---------------------------------------------------------------- characters op=use / op=match / cast
def mod_name(pairs: list[tuple[dict, str]], title: str | None = None) -> str:
    if title and len(pairs) > 1:
        return "etm_" + re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:48]
    return "etm_" + "_".join(f"{m['slug']}_as_{re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')}" for m, s in pairs)[:96]


def _job_of(root: Path, meta: dict, slot: str) -> dict:
    return {"slot": slot, "model": Path(root) / meta["slug"] / meta["model"],
            "roles": (meta.get("rig") or {}).get("roles") or {}, "name": meta["name"],
            "props": [p["node"] for p in meta.get("props") or []], "scale": (meta.get("rig") or {}).get("scale")}


def build_mod(cfg, game: dict, pairs: list[tuple[dict, str]], progress=lambda p, m: None, root: Path | None = None,
              title: str | None = None, name: str | None = None, src: Path | None = None) -> dict:
    from . import characters as C, filemods

    class Ctx:
        config = cfg

        @staticmethod
        def progress(p, m):
            progress(p, m)
    root = Path(root or C.library_root(cfg))
    src = Path(src) if src else M.source_disc(Ctx(), game)
    iso = base_iso(cfg, game, src, progress)
    name = name or mod_name(pairs, title)
    d = filemods.mod_dir(cfg, game["game_id"], name)
    if d.exists():
        shutil.rmtree(d)
    img = d / (src.stem + ".iso")
    b = build_disc(iso, img, [_job_of(root, m, s) for m, s in pairs], progress)
    mj = {"name": name, "game_id": game["game_id"], "image": img.name, "writer": "gbox.etm_swap",
          "title": title or ", ".join(f"{m['name']} as {s}" for m, s in pairs), "built": time.time(),
          "files": sorted({x["model"] for r in b["reports"] for x in r["entries"] if x.get("status") == "built"}),
          "characters": [m["slug"] for m, _s in pairs], "slots": [r | {"entries": r["entries"]} for r in b["reports"]],
          "launch": "PCSX2 with the image (the catalog entry launches the original disc through RocketLauncher)",
          "verified_in_game": False}
    (d / ".gbox-mod.json").write_text(json.dumps(mj, default=str))
    return {"mod": name, "image": str(img), "reports": b["reports"]}


def build_cast(cfg, game: dict, pairs: list[tuple[str, dict]], name: str, progress=lambda p, m: None,
               root: Path | None = None) -> dict:
    """cast_swap pairs builder: [(slot, meta)] -> one image; a slot whose donor fails is reported alone."""
    try:
        res = build_mod(cfg, game, [(m, s) for s, m in pairs], progress, root, name=name)
    except Exception as e:                                # noqa: BLE001 - every slot fails with the reason
        return {"mod": None, "slots": {s: {"status": "failed", "reason": str(e)[:500]} for s, _m in pairs}}
    per = {}
    for r in res["reports"]:
        st = r["status"]
        per[r["slot"]] = {"status": st} | ({"reason": r["reason"]} if r.get("reason") else {}) | \
            ({"reason": "; ".join(f"{x['model']}: {x['status']}" for x in r["entries"] if x["status"] != "built")}
             if st == "partial" else {})
    return {"mod": res["mod"], "slots": per, "detail": {"image": res["image"]}}


def needs(game: dict) -> dict:
    return {"have": "Enter the Matrix (USA) PS2 disc (SLUS-20454) as the catalog CHD or an ISO",
            "game_ids": sorted(GAME_IDS)}


def use(ctx, meta: dict, game: dict, inp, pairs: list | None = None, title: str | None = None) -> dict:
    """characters op=use / op=match: slot = a cast slot (niobe, ghost, agent_smith, swat ...; player = both heroes)."""
    from . import characters as C, filemods
    gid = game["game_id"]
    if gid not in GAME_IDS:
        return {"status": "missing", "missing": needs(game), "message": needs(game)["have"]}
    if not C.library_root(ctx.config).is_dir():           # not the control plane: build there
        cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
        args = {"op": inp.op, "character": inp.character, "game_id": gid, "slot": inp.slot, "rebuild": inp.rebuild,
                "launch": False, "pairs": getattr(inp, "pairs", None), "title": getattr(inp, "title", None)}
        j = C._job(ctx, "characters", args, cp, 7200)
        r = (j.get("output") or {}).get("result") or {}
        if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
            return {"status": "failed", "error": r.get("error") or j.get("error") or r}
        return r
    pairs = pairs or [(meta, inp.slot or "player")]
    for _m, s in pairs:
        resolve_slot(s)
    name = mod_name(pairs, title)
    have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
    built = None
    if inp.rebuild or not have:
        built = build_mod(ctx.config, game, pairs, ctx.progress, title=title)
        for m, slot in pairs:
            C._api(ctx, "POST", f"/api/characters/{m['slug']}/targets",
                   json={"game_id": gid, "slot": slot, "mod": name, "nodes": [C.HOST_OS],
                         "notes": "replaces the cast member's .dcn models in WAD1.DFU (the game's skeleton and "
                                  "animations); not yet verified in PCSX2"})
    return {"mod": name, "build": built, "replaces": ", ".join(f"{s} -> {m['name']}" for m, s in pairs),
            "verified_in_game": False, "status": "built" if built else "ready",
            "message": f"Mod {name} is built (a patched copy of the PS2 disc). Run the image in PCSX2; the catalog "
                       "entry starts the original through RocketLauncher, which takes no mod."}


def match(ctx, chars: list, game: dict, inp, pairs_in: list[tuple[str, str]], title: str | None = None) -> dict:
    from . import characters as C
    pairs = []
    for c, s in pairs_in:
        meta = C.best_match(chars, c) or C.find(chars, c)
        if not meta:
            raise ValueError(f"no library character matches {c!r}")
        pairs.append((meta, s or "player"))
    return use(ctx, pairs[0][0], game, inp, pairs, title)


def main(argv=None) -> int:
    """python -m gbox.etm_swap ETM.iso|chd OUT.iso SLOT=DONOR.glb[:roles.json] ... (roles default: the GLB's
    collection meta.json beside it)."""
    import sys
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) < 3:
        print(main.__doc__)
        return 2
    src = Path(a[0])
    if src.suffix.lower() == ".chd":                       # unpacked beside the output, never beside the source
        from .chd import ChdDisc
        iso = Path(a[1]).with_name(src.stem + ".base.iso")
        if not iso.is_file():
            ChdDisc(src).write_iso(iso, lambda d, n: print(f"unpacking {100 * d / max(n, 1):5.1f}%", flush=True))
        src = iso
    jobs = []
    for spec in a[2:]:
        slot, model = spec.split("=", 1)
        meta = json.loads((Path(model).parent / "meta.json").read_text())
        jobs.append({"slot": slot, "model": Path(model), "roles": (meta.get("rig") or {}).get("roles") or {},
                     "name": meta.get("name", Path(model).stem)})
    r = build_disc(src, Path(a[1]), jobs, lambda p, m: print(f"{p:5.1f}% {m}"))
    print(json.dumps(r, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
