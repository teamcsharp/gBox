"""Synthetic GTA Vice City PC assets for the reader/writer tests: a 25-frame skinned ped clump with the VC bone
tags, D3D8 TXDs (PAL8 / DXT1 / 8888 rasters), an IMG v1 archive and a donor GLB. Built from the format helpers in
gbox.gta_vc_models and gbox.gta_rw; nothing here is read from a game file."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from gbox import gta_rw as R
from gbox import gta_vc_models as M

# (name, parent, bone tag, world position in GTA space: x left = -x, y forward, z up)
SKELETON = [
    ("player", -1, None, (0, 0, 0)),
    ("Root", 0, 0, (0, 0, 0)),
    ("Pelvis", 1, 1, (0, 0, 0)),
    ("Spine", 2, 2, (0, 0, 0.12)),
    ("Spine1", 3, 3, (0, 0, 0.35)),
    ("Neck", 4, 4, (0, 0, 0.55)),
    ("Head", 5, 5, (0, 0, 0.62)),
    ("Bip01 L Clavicle", 4, 21, (-0.07, 0, 0.5)),
    ("L UpperArm", 7, 22, (-0.2, 0, 0.5)),
    ("L Forearm", 8, 23, (-0.45, 0, 0.5)),
    ("L Hand", 9, 24, (-0.7, 0, 0.5)),
    ("L Finger", 10, 25, (-0.78, 0, 0.5)),
    ("Bip01 R Clavicle", 4, 31, (0.07, 0, 0.5)),
    ("R UpperArm", 12, 32, (0.2, 0, 0.5)),
    ("R Forearm", 13, 33, (0.45, 0, 0.5)),
    ("R Hand", 14, 34, (0.7, 0, 0.5)),
    ("R Finger", 15, 35, (0.78, 0, 0.5)),
    ("L Thigh", 2, 41, (-0.1, 0, -0.05)),
    ("L Calf", 17, 42, (-0.1, 0, -0.5)),
    ("L Foot", 18, 43, (-0.1, 0, -0.95)),
    ("L Toe0", 19, 44, (-0.1, 0.12, -0.98)),
    ("R Thigh", 2, 51, (0.1, 0, -0.05)),
    ("R Calf", 21, 52, (0.1, 0, -0.5)),
    ("R Foot", 22, 53, (0.1, 0, -0.95)),
    ("R Toe0", 23, 54, (0.1, 0.12, -0.98)),
]


def frames(names: bool = True, bones: bool = True) -> list[dict]:
    """Frame dicts for gta_vc_models.clump_build (local matrices from the world positions above)."""
    world = [np.eye(4) for _ in SKELETON]
    for i, (_n, _p, _b, pos) in enumerate(SKELETON):
        world[i][:3, 3] = pos
    out = []
    for i, (n, p, b, _pos) in enumerate(SKELETON):
        local = world[i] if p < 0 else np.linalg.inv(world[p]) @ world[i]
        out.append({"name": n if names else "", "local": local, "parent": p, "bone": b if bones else None, "world": world[i]})
    return out


def hanim_nodes() -> list[tuple[int, int, int]]:
    return [(b, k, 0) for k, (_n, _p, b, _pos) in enumerate(SKELETON[1:])]


def skin_template() -> M.Skin:
    fr = frames()
    inv = np.array([np.linalg.inv(fr[i]["world"]) for i in range(1, len(SKELETON))])
    return M.Skin(len(SKELETON) - 1, [], 1, np.zeros((0, 4), np.uint8), np.zeros((0, 4), np.float32), inv)


def cube_mesh(centers: list[tuple[float, float, float]], bones: list[int], size: float = 0.04):
    """A small cube per centre, every vertex rigid on the given skin bone."""
    P, N, U, B, T = [], [], [], [], []
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], float) * size
    faces = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                      [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    for c, b in zip(centers, bones):
        base = len(P) * 8
        P.append(corners + np.asarray(c, float))
        N.append(corners / np.linalg.norm(corners, axis=1, keepdims=True))
        U.append((corners[:, :2] / size + 1) / 2)
        B.append(np.full(8, b))
        T.append(faces + base)
    return (np.concatenate(P).astype(np.float32), np.concatenate(N).astype(np.float32), np.concatenate(U).astype(np.float32),
            np.concatenate(B), np.concatenate(T))


def ped_dff(texture: str = "player", names: bool = True, bones: bool = True, version: int = M.VC_VERSION) -> bytes:
    """A VC-like skinned ped: one atomic on frame 0, a cube on every bone, Skin PLG + HAnim."""
    fr = frames(names, bones)
    centers = [SKELETON[i][3] for i in range(1, len(SKELETON))]
    P, N, U, B, T = cube_mesh(centers, list(range(len(centers))))
    g = R.Geom(P, N, U, T)
    idx = np.c_[B, np.zeros((len(B), 3))].astype(np.uint8)
    w = np.c_[np.ones(len(B)), np.zeros((len(B), 3))].astype(np.float32)
    geom = M.geometry_chunk(g, M.geometry_template([texture], version), skin_template(), idx, w)
    return M.clump_build(fr, [geom], [(0, 0)], version, hanim_nodes() if bones else None, 1 if bones else None)


def rigid_dff(version: int = M.VC_VERSION) -> bytes:
    """Not a ped: three rigid frames, no HAnim, no skin (a prop)."""
    fr = [{"name": "prop", "local": np.eye(4), "parent": -1, "bone": None},
          {"name": "a", "local": np.eye(4), "parent": 0, "bone": None}, {"name": "b", "local": np.eye(4), "parent": 0, "bone": None}]
    P, N, U, _B, T = cube_mesh([(0, 0, 0)], [0])
    geom = M.geometry_chunk(R.Geom(P, N, U, T), M.geometry_template(["prop"], version), None)
    return M.clump_build(fr, [geom], [(1, 0)], version)


def rgb565(r, g, b) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def dxt1_flat(w: int, h: int, rgb) -> bytes:
    """Every 4x4 block one colour (c0 == c1, indices 0)."""
    c = rgb565(*rgb)
    return struct.pack("<HHI", c, c, 0) * (max(w // 4, 1) * max(h // 4, 1))


def pal8_raster(name: str, w: int, h: int, rgba: np.ndarray) -> M.D3dRaster:
    """rgba (h, w, 4) with at most 256 colours -> PAL8 raster."""
    flat = rgba.reshape(-1, 4)
    pal, inv = np.unique(flat, axis=0, return_inverse=True)
    palette = np.zeros((256, 4), np.uint8)
    palette[:len(pal)] = pal
    return M.D3dRaster(M.D3D8, 0x1101, name, "", 0x500 | M.PAL8, 1, w, h, 8, 1, 4, 0, palette.tobytes(),
                       [inv.reshape(-1).astype(np.uint8).tobytes()])


def dxt1_raster(name: str, w: int, h: int, rgb=(200, 40, 40), levels: int = 1) -> M.D3dRaster:
    mips, cw, ch = [], w, h
    for _ in range(levels):
        mips.append(dxt1_flat(cw, ch, rgb))
        cw, ch = max(cw // 2, 1), max(ch // 2, 1)
    return M.D3dRaster(M.D3D8, 0x1101, name, "", 0x100 | (M.MIPMAP if levels > 1 else 0), 0, w, h, 16, levels, 4, 1, None, mips)


def rgba_raster(name: str, rgba: np.ndarray) -> M.D3dRaster:
    tmpl = M.D3dRaster(M.D3D8, 0x1101, name, "", 0x500, 1, rgba.shape[1], rgba.shape[0], 32, 1, 4, 0, None, [b""])
    return M.raster_8888(tmpl, rgba, mips=False)


def ped_txd(name: str = "player", size: int = 64) -> bytes:
    """A TXD like a ped's: the main PAL8 raster named after the model, a DXT1 'extra' raster."""
    y, x = np.mgrid[0:size, 0:size]
    rgba = np.stack([(x * 255 // size), (y * 255 // size), np.full_like(x, 90), np.full_like(x, 255)], -1).astype(np.uint8)
    rgba[..., 0] &= 0xF0                     # <= 256 colours
    rgba[..., 1] &= 0xF0
    return M.txd_build([pal8_raster(name, size, size, rgba), dxt1_raster("extra", 16, 16)])


IDE = """# synthetic default.ide
peds
0, player, player, PLAYER1, STAT_PLAYER, player, 7f
1, cop, cop, COP, STAT_COP, cop, 7f
7, male01, male01, CIVMALE, STAT_STREET_GUY, man, 7f
end
"""


def write_img(folder: Path, entries: list[tuple[str, bytes]]) -> tuple[Path, Path]:
    """models/gta3.img + gta3.dir (IMG v1) from (name, bytes) in order."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    img, dr, sector = bytearray(), bytearray(), 0
    for name, data in entries:
        need = (len(data) + R.SECTOR - 1) // R.SECTOR
        img += data + b"\0" * (need * R.SECTOR - len(data))
        dr += struct.pack("<II", sector, need) + name.encode().ljust(24, b"\0")
        sector += need
    (folder / "gta3.img").write_bytes(bytes(img))
    (folder / "gta3.dir").write_bytes(bytes(dr))
    return folder / "gta3.img", folder / "gta3.dir"


def install(root: Path) -> dict:
    """A classic-port-shaped install: gta-vc.exe, data/default.ide, models/gta3.img with player, cop, male01, a prop
    (zzz.dff on another skeleton) and a collision file."""
    root = Path(root)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "gta-vc.exe").write_bytes(b"MZ" + b"\0" * 62)
    (root / "data" / "default.ide").write_text(IDE)
    (root / "anim").mkdir(exist_ok=True)
    (root / "anim" / "ped.ifp").write_bytes(b"ANPK" + b"\0" * 28)
    entries = [("generic.col", b"COLL" + bytes(range(256)) * 3)]
    for m in ("player", "cop", "male01"):
        entries += [(f"{m}.dff", ped_dff(m)), (f"{m}.txd", ped_txd(m))]
    entries += [("zzz.dff", rigid_dff()), ("zzz.txd", ped_txd("zzz", 16))]
    write_img(root / "models", entries)
    return M.locate_install(root / "gta-vc.exe")


# ------------------------------------------------------------------------------------------------ donor
DONOR_JOINTS = [("hip", -1, (0, 1.0, 0)), ("chest", 0, (0, 1.35, 0)), ("neck", 1, (0, 1.55, 0)), ("head", 2, (0, 1.62, 0)),
                ("l_upper", 1, (0.2, 1.5, 0)), ("l_fore", 4, (0.45, 1.5, 0)), ("l_hand", 5, (0.7, 1.5, 0)),
                ("r_upper", 1, (-0.2, 1.5, 0)), ("r_fore", 7, (-0.45, 1.5, 0)), ("r_hand", 8, (-0.7, 1.5, 0)),
                ("l_thigh", 0, (0.1, 0.95, 0)), ("l_shin", 10, (0.1, 0.5, 0)), ("l_foot", 11, (0.1, 0.05, 0)),
                ("r_thigh", 0, (-0.1, 0.95, 0)), ("r_shin", 13, (-0.1, 0.5, 0)), ("r_foot", 14, (-0.1, 0.05, 0))]
DONOR_ROLES = {n: f"j_{n}" for n, _p, _pos in DONOR_JOINTS}


def donor_glb(path: Path) -> Path:
    """A humanoid of cubes (glTF axes: Y up, facing +Z, left = +X), one joint per body role, a 32x32 texture."""
    centers = [pos for _n, _p, pos in DONOR_JOINTS]
    P, N, U, B, T = cube_mesh(centers, list(range(len(centers))), size=0.06)
    world = []
    for _n, _p, pos in DONOR_JOINTS:
        w = np.eye(4)
        w[:3, 3] = pos
        world.append(w)
    y, x = np.mgrid[0:32, 0:32]
    rgba = np.stack([x * 8, y * 8, np.full_like(x, 200), np.full_like(x, 255)], -1).astype(np.uint8)
    return R.write_skinned_glb(path, P, N, U, B, T, [f"j_{n}" for n, _p, _pos in DONOR_JOINTS],
                               [p for _n, p, _pos in DONOR_JOINTS], world, rgba, "donor")
