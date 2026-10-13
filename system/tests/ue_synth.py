"""Synthetic Unreal Engine archives and packages for the ue_pak / ue_asset / ue_mesh tests.

Everything is built in memory from the documented layouts (IPlatformFilePak.h, PackageFileSummary.cpp,
SkeletalMeshLODRenderData.cpp); no game data is used or committed."""
import hashlib
import struct
import zlib

import numpy as np

MAGIC = 0x5A6F12E1


def fstring(s: str) -> bytes:
    if not s:
        return struct.pack("<i", 0)
    b = s.encode("latin-1") + b"\0"
    return struct.pack("<i", len(b)) + b


def _method_index(version: int, method: str) -> int:
    if version >= 8:
        return {"None": 0, "Zlib": 1, "Oodle": 2, "Gzip": 3}[method]
    return {"None": 0, "Zlib": 1, "Gzip": 2, "Oodle": 4}[method]


def _entry_bytes(version, offset, size, usize, midx, blocks, flags, block_size, u8_method=False) -> bytes:
    b = struct.pack("<qqq", offset, size, usize)
    if version >= 8:
        b += struct.pack("<B", midx) if u8_method else struct.pack("<I", midx)
    else:
        b += struct.pack("<i", midx)
    if version < 2:
        b += struct.pack("<q", 0)
    b += b"\x11" * 20
    if version >= 3:
        if midx:
            b += struct.pack("<i", len(blocks)) + b"".join(struct.pack("<qq", s, e) for s, e in blocks)
        b += struct.pack("<BI", flags, block_size)
    return b


def _compress(method: str, data: bytes) -> bytes:
    if method == "Zlib":
        return zlib.compress(data)
    if method == "Gzip":
        c = zlib.compressobj(wbits=31)
        return c.compress(data) + c.flush()
    return b"OODLE" + data[:8]            # never decompressed in tests (no DLL)


def _encode_entry(offset, size, usize, midx, enc, block_sizes, block_size) -> bytes:
    nblocks = len(block_sizes)
    v = 0
    bs_field = block_size >> 11
    extra_bs = bs_field > 0x3E or (block_size & 0x7FF)
    v |= 0x3F if extra_bs else bs_field
    v |= (nblocks & 0xFFFF) << 6
    if enc:
        v |= 1 << 22
    v |= (midx & 0x3F) << 23
    tail = b""
    if extra_bs:
        tail += struct.pack("<I", block_size)
    if offset < 1 << 32:
        v |= 1 << 31
        tail += struct.pack("<I", offset)
    else:
        tail += struct.pack("<q", offset)
    if usize < 1 << 32:
        v |= 1 << 30
        tail += struct.pack("<I", usize)
    else:
        tail += struct.pack("<q", usize)
    if midx:
        if size < 1 << 32:
            v |= 1 << 29
            tail += struct.pack("<I", size)
        else:
            tail += struct.pack("<q", size)
    if nblocks > 1 or (enc and nblocks):
        tail += b"".join(struct.pack("<I", s) for s in block_sizes)
    return struct.pack("<I", v) + tail


def build_pak(files: dict, version: int = 11, method: str = "None", mount: str = "../../../",
              encrypt_index: bool = False, encrypted: tuple = (), footer: str = "", block_size: int = 0x10000,
              full_dir: bool = True, listed: tuple = (), legacy_names: bool = False) -> bytes:
    """A pak of `files` {path relative to mount: bytes}. footer="4.22" writes the 4-name v8 footer (uint8 methods).
    `listed` names go to the v10+ non-encoded entry list instead of the encoded blob."""
    u8 = version == 8 and footer == "4.22"
    midx = _method_index(version, method)
    out = bytearray()
    meta = {}
    for name, data in files.items():
        offset = len(out)
        flags = 1 if name in encrypted else 0
        if midx:
            chunks = [data[i:i + block_size] for i in range(0, len(data), block_size)] or [b""]
            comp = [_compress(method, c) for c in chunks]
            hdr_len = len(_entry_bytes(version, 0, 0, 0, midx, [(0, 0)] * len(comp), flags, block_size, u8))
            base = 0 if version >= 5 else offset
            blocks, cur = [], hdr_len
            for c in comp:
                blocks.append((base + cur, base + cur + len(c)))
                cur += len(c)
            size, body = sum(map(len, comp)), b"".join(comp)
            bsz = block_size if len(chunks) > 1 else len(data)
        else:
            blocks, size, body, bsz, comp = [], len(data), data, 0, []
        hdr = _entry_bytes(version, 0, size, len(data), midx, blocks, flags, bsz, u8)
        out += hdr + body
        meta[name] = (offset, size, len(data), blocks, flags, bsz, [len(c) for c in comp])
    index_offset = len(out)
    if version < 10:
        idx = fstring(mount) + struct.pack("<i", len(files))
        for name, (offset, size, usize, blocks, flags, bsz, _) in meta.items():
            idx += fstring(name) + _entry_bytes(version, offset, size, usize, midx, blocks, flags, bsz, u8)
        secondary = b""
    else:
        enc_blob, listed_entries, locs = b"", [], {}
        for name, (offset, size, usize, blocks, flags, bsz, csizes) in meta.items():
            if name in listed:
                locs[name] = -(len(listed_entries) + 1)
                listed_entries.append(_entry_bytes(version, offset, size, usize, midx, blocks, flags, bsz))
            else:
                locs[name] = len(enc_blob)
                enc_blob += _encode_entry(offset, size, usize, midx, bool(flags), csizes, block_size if midx else 0)
        dirs: dict = {}
        for name in meta:
            d, _, f = name.rpartition("/")
            dirs.setdefault(d + "/" if d else "/", []).append((f, locs[name]))
        fdi = struct.pack("<i", len(dirs))
        for d, fl in dirs.items():
            fdi += fstring(d) + struct.pack("<i", len(fl)) + b"".join(fstring(f) + struct.pack("<i", l) for f, l in fl)
        phi = struct.pack("<i", len(locs)) + b"".join(struct.pack("<Qi", i * 7919 + 1, l) for i, l in enumerate(locs.values()))
        phi += struct.pack("<i", 0)
        tail = struct.pack("<i", len(enc_blob)) + enc_blob + struct.pack("<i", len(listed_entries)) + b"".join(listed_entries)
        head = fstring(mount) + struct.pack("<iQ", len(files), 0)
        primary_len = len(head) + 4 + 36 + 4 + (36 if full_dir else 0) + len(tail)
        phi_off = index_offset + primary_len
        fdi_off = phi_off + len(phi)
        idx = head + struct.pack("<I", 1) + struct.pack("<qq", phi_off, len(phi)) + hashlib.sha1(phi).digest()
        idx += struct.pack("<I", 1 if full_dir else 0)
        if full_dir:
            idx += struct.pack("<qq", fdi_off, len(fdi)) + hashlib.sha1(fdi).digest()
        idx += tail
        assert len(idx) == primary_len
        secondary = phi + (fdi if full_dir else b"")
    out += idx + secondary
    sha = hashlib.sha1(idx).digest()
    names = [b"Zlib", b"Oodle", b"Gzip", b"", b""][: 4 if u8 else 5]
    if version >= 7:
        foot = b"\0" * 16 + struct.pack("<BIIqq", int(encrypt_index), MAGIC, version, index_offset, len(idx)) + sha
        if version == 9:
            foot += b"\0"
        if version >= 8:
            foot += b"".join(n.ljust(32, b"\0") for n in names)
    else:
        foot = (struct.pack("<B", int(encrypt_index)) if version >= 4 else b"")
        foot += struct.pack("<IIqq", MAGIC, version, index_offset, len(idx)) + sha
    return bytes(out + foot)


def build_utoc(entries: int = 3, flags: int = 1) -> bytes:
    h = b"-==--==--==--==-" + struct.pack("<BBH", 3, 0, 0)
    h += struct.pack("<IIIIIIIII", 144, entries, 5, 12, 1, 32, 0x10000, 64, 1)
    h += struct.pack("<Q", 0x1234) + b"\0" * 16 + struct.pack("<BBHI", flags, 0, 0, 0) + struct.pack("<Q", 0)
    return h + b"\0" * (144 - len(h))


# ---------------------------------------------------------------------- packages

PKG_FILTER_EDITOR_ONLY = 0x80000000


class Names:
    def __init__(self):
        self.names, self.idx = [], {}

    def add(self, s: str) -> int:
        if s not in self.idx:
            self.idx[s] = len(self.names)
            self.names.append(s)
        return self.idx[s]

    def fname(self, s: str) -> bytes:
        return struct.pack("<ii", self.add(s), 0)


def build_package(imports: list, exports: list, bodies: list, names: Names | None = None, ue4: int = 522,
                  unversioned: bool = True, pkg_flags: int = PKG_FILTER_EDITOR_ONLY, split: bool = True):
    """(uasset, uexp). imports: (class_package, class_name, outer, object_name); exports: (class_index,
    super_index, outer, name, flags). bodies: serialized export bytes (in the .uexp when split)."""
    N = names or Names()
    for cp, cn, _o, on in imports:
        N.add(cp); N.add(cn); N.add(on)
    for e in exports:
        N.add(e[3])
    N.add("None")

    def summary(name_off, imp_off, exp_off, total, bulk_start):
        s = struct.pack("<Iii", 0x9E2A83C1, -7, 864)
        s += struct.pack("<ii", 0, 0) if unversioned else struct.pack("<ii", ue4, 0)
        s += struct.pack("<i", 0)                                  # custom versions
        s += struct.pack("<i", total) + fstring("None") + struct.pack("<I", pkg_flags)
        s += struct.pack("<ii", len(N.names), name_off)
        s += struct.pack("<ii", 0, 0)                              # gatherable text
        s += struct.pack("<ii", len(exports), exp_off) + struct.pack("<ii", len(imports), imp_off)
        s += struct.pack("<i", 0)                                  # depends
        s += struct.pack("<ii", 0, 0) + struct.pack("<i", 0) + struct.pack("<i", 0) + b"\0" * 16
        s += struct.pack("<i", 1) + struct.pack("<ii", len(exports), len(N.names))
        s += struct.pack("<HHHI", 4, 27, 2, 0) + fstring("++UE4+Release-4.27")
        s += struct.pack("<HHHI", 4, 27, 0, 0) + fstring("")
        s += struct.pack("<I", 0) + struct.pack("<i", 0) + struct.pack("<I", 0) + struct.pack("<i", 0)
        s += struct.pack("<i", 0) + struct.pack("<q", bulk_start) + struct.pack("<i", 0) + struct.pack("<i", 0)
        s += struct.pack("<ii", 0, 0)
        return s

    def tables(name_off, total, serial_base):
        nm = b"".join(fstring(n) + struct.pack("<I", 0) for n in N.names)
        imp = b"".join(N.fname(cp) + N.fname(cn) + struct.pack("<i", o) + N.fname(on) for cp, cn, o, on in imports)
        exp, off = b"", serial_base
        for (ci, si, outer, name, flags), body in zip(exports, bodies):
            exp += struct.pack("<iiii", ci, si, 0, outer) + N.fname(name) + struct.pack("<I", flags)
            exp += struct.pack("<qq", len(body), off) + struct.pack("<iii", 0, 0, 0) + b"\0" * 16
            exp += struct.pack("<I", 0) + struct.pack("<ii", 0, 1) + b"\0" * 20
            off += len(body)
        return nm, imp, exp

    # Two passes: sizes first, then real offsets.
    s0 = summary(0, 0, 0, 0, 0)
    nm, imp, exp = tables(0, 0, 0)
    name_off = len(s0)
    imp_off = name_off + len(nm)
    exp_off = imp_off + len(imp)
    total = exp_off + len(exp)
    body_blob = b"".join(bodies)
    bulk_start = total + len(body_blob)
    s = summary(name_off, imp_off, exp_off, total, bulk_start)
    assert len(s) == len(s0)
    nm, imp, exp = tables(name_off, total, total)
    uasset = s + nm + imp + exp
    if split:
        return uasset, body_blob + struct.pack("<I", 0x9E2A83C1)
    return uasset + body_blob, None


# ---------------------------------------------------------------------- skeletal mesh (UE 4.27 cooked layout)

def tagged_props(N: Names, props: list) -> bytes:
    """props: (name, type, value). Bool -> tag-only, Int -> 4 bytes."""
    b = b""
    for name, ptype, value in props:
        b += N.fname(name) + N.fname(ptype)
        if ptype == "BoolProperty":
            b += struct.pack("<ii", 0, 0) + struct.pack("<B", int(value)) + b"\0"
        else:
            b += struct.pack("<ii", 4, 0) + b"\0" + struct.pack("<i", value)
    return b + N.fname("None")


def ref_skeleton(N: Names, bones: list) -> bytes:
    """bones: (name, parent, translation xyz)."""
    b = struct.pack("<i", len(bones)) + b"".join(N.fname(n) + struct.pack("<i", p) for n, p, _ in bones)
    b += struct.pack("<i", len(bones))
    for _n, _p, t in bones:
        b += struct.pack("<4f", 0, 0, 0, 1) + struct.pack("<3f", *t) + struct.pack("<3f", 1, 1, 1)
    b += struct.pack("<i", len(bones)) + b"".join(N.fname(n) + struct.pack("<i", i) for i, (n, _p, _t) in enumerate(bones))
    return b


def _bulk(arr: np.ndarray, esize: int) -> bytes:
    raw = np.ascontiguousarray(arr).tobytes()
    return struct.pack("<ii", esize, len(raw) // esize) + raw


def streamed_lod(pos, nrm, uv, idx, joints, weights, max_inf=4, minor=27) -> bytes:
    n = len(pos)
    b = b"\0\0" + struct.pack("<B", 2) + _bulk(np.asarray(idx, "<u2"), 2)
    b += struct.pack("<ii", 12, n) + _bulk(np.asarray(pos, "<f4"), 12)
    tz = np.clip(np.round(np.asarray(nrm) * 127.5 + 127.5), 0, 255).astype(np.uint8) ^ 0x80
    tan = np.zeros((n, 2, 4), np.uint8)
    tan[:, 1, :3] = tz
    b += b"\0\0" + struct.pack("<ii", 1, n) + struct.pack("<II", 1, 0)
    b += _bulk(tan, 8) + _bulk(np.asarray(uv, "<f4"), 8)
    if minor >= 25:
        b += b"\0\0" + struct.pack("<IIII", 0, max_inf, max_inf * n, n) + struct.pack("<I", 0)
        rows = np.concatenate([np.asarray(joints, np.uint8), np.asarray(weights, np.uint8)], axis=1)
        b += _bulk(rows.reshape(-1), 1)
        b += b"\0\0" + struct.pack("<i", 0) + struct.pack("<ii", 4, 0)
    else:
        rows = np.concatenate([np.asarray(joints, np.uint8), np.asarray(weights, np.uint8)], axis=1)
        b += b"\0\0" + struct.pack("<III", int(max_inf > 4), 0, n) + _bulk(rows, rows.shape[1])
    return b


def section(n_verts, base_vertex, n_tris, base_index, bone_map, max_inf=4, minor=27) -> bytes:
    b = b"\0\0" + struct.pack("<hii", 0, base_index, n_tris) + struct.pack("<I", 0)
    if minor >= 26:
        b += b"\0"
    b += struct.pack("<I", 1) + struct.pack("<I", base_vertex) + struct.pack("<i", 0)
    b += struct.pack("<i", len(bone_map)) + b"".join(struct.pack("<H", x) for x in bone_map)
    b += struct.pack("<ii", n_verts, max_inf) + struct.pack("<h", -1) + b"\0" * 16 + struct.pack("<i", -1)
    b += struct.pack("<i", 0) + struct.pack("<i", 0) + struct.pack("<I", 0)
    return b


def triangle_mesh(max_inf=4):
    """Two triangles, three bones; vertex 3 is shared between two influences."""
    pos = np.array([[0, 0, 0], [100, 0, 0], [0, 100, 0], [0, 0, 100]], float)
    nrm = np.array([[0, 0, 1]] * 4, float)
    uv = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], float)
    idx = [0, 1, 2, 0, 2, 3]
    joints = np.zeros((4, max_inf), int)
    weights = np.zeros((4, max_inf), int)
    joints[:, 0] = [0, 1, 1, 2]
    weights[:, 0] = [255, 255, 128, 255]
    joints[2, 1], weights[2, 1] = 2, 127
    return pos, nrm, uv, idx, joints, weights


def skeletal_mesh_body(N: Names, inlined=True, minor=27, max_inf=4, props=None):
    """(export body, ubulk payload or None) for a 3-bone, 4-vertex SkeletalMesh."""
    pos, nrm, uv, idx, joints, weights = triangle_mesh(max_inf)
    bones = [("root", -1, (0, 0, 0)), ("spine", 0, (0, 0, 50)), ("head", 1, (0, 0, 40))]
    b = tagged_props(N, props if props is not None else [("bHasVertexColors", "BoolProperty", False),
                                                          ("LODInfoCount", "IntProperty", 1)])
    b += struct.pack("<I", 0)                                       # no object guid
    b += struct.pack("<BB", 1, 0)                                   # editor data stripped
    b += struct.pack("<7f", 0, 0, 0, 1, 1, 1, 1)
    b += struct.pack("<i", 1) + struct.pack("<i", 0) + N.fname("Body") + struct.pack("<I", 0) + b"\0" * 24
    b += ref_skeleton(N, bones)
    b += struct.pack("<I", 1) + struct.pack("<i", 1)                # bCooked, 1 LOD
    b += b"\0\0" + struct.pack("<II", 0, int(inlined))
    b += struct.pack("<i", 3) + struct.pack("<3h", 0, 1, 2)
    b += struct.pack("<i", 1) + section(4, 0, 2, 0, [0, 1, 2], max_inf, minor)
    b += struct.pack("<i", 3) + struct.pack("<3h", 0, 1, 2) + struct.pack("<I", 0)
    lod = streamed_lod(pos, nrm, uv, idx, joints, weights, max_inf, minor)
    if inlined:
        return b + lod, None
    # FByteBulkData in the .ubulk (PayloadInSeperateFile | NoOffsetFixUp) at offset 0
    b += struct.pack("<IiIq", 0x100 | 0x10000, len(lod), len(lod), 0)
    return b, lod


def skeleton_body(N: Names) -> bytes:
    b = tagged_props(N, []) + struct.pack("<I", 0)
    return b + ref_skeleton(N, [("root", -1, (0, 0, 0)), ("spine", 0, (0, 0, 50))]) + struct.pack("<i", 0) + b"\0" * 16


def mesh_package(inlined=True, minor=27, max_inf=4, unversioned_props=False):
    """(uasset, uexp, ubulk) of a package with SK_Test (SkeletalMesh) and SK_Test_Skeleton (Skeleton)."""
    N = Names()
    body, ubulk = skeletal_mesh_body(N, inlined, minor, max_inf)
    imports = [("/Script/CoreUObject", "Package", 0, "/Script/Engine"),
               ("/Script/CoreUObject", "Class", -1, "SkeletalMesh"),
               ("/Script/CoreUObject", "Class", -1, "Skeleton")]
    exports = [(-2, 0, 0, "SK_Test", 0x1), (-3, 0, 0, "SK_Test_Skeleton", 0x1)]
    flags = PKG_FILTER_EDITOR_ONLY | (0x2000 if unversioned_props else 0)
    ua, ue = build_package(imports, exports, [body, skeleton_body(N)], N, pkg_flags=flags)
    return ua, ue, ubulk


def anim_actor_packages():
    """Packages for the inventory: an AnimSequence and a Character blueprint that references a mesh + anim BP."""
    seq = build_package([("/Script/CoreUObject", "Package", 0, "/Script/Engine"),
                         ("/Script/CoreUObject", "Class", -1, "AnimSequence"),
                         ("/Script/CoreUObject", "Package", 0, "/Game/Char/SK_Test_Skeleton"),
                         ("/Script/Engine", "Skeleton", -3, "SK_Test_Skeleton")],
                        [(-2, 0, 0, "Run_Fwd", 0x1)], [b"\0" * 64])
    bp = build_package([("/Script/CoreUObject", "Package", 0, "/Script/Engine"),
                        ("/Script/CoreUObject", "Class", -1, "BlueprintGeneratedClass"),
                        ("/Script/CoreUObject", "Class", -1, "Character"),
                        ("/Script/CoreUObject", "Package", 0, "/Game/Char/SK_Test"),
                        ("/Script/Engine", "SkeletalMesh", -4, "SK_Test"),
                        ("/Script/CoreUObject", "Package", 0, "/Game/Char/ABP_Test"),
                        ("/Script/Engine", "AnimBlueprintGeneratedClass", -6, "ABP_Test_C")],
                       [(-2, -3, 0, "BP_Hero_C", 0x1), (1, 0, 0, "Default__BP_Hero_C", 0x10)], [b"\0" * 32, b"\0" * 16])
    child = build_package([("/Script/CoreUObject", "Package", 0, "/Script/Engine"),
                           ("/Script/CoreUObject", "Class", -1, "BlueprintGeneratedClass"),
                           ("/Script/CoreUObject", "Package", 0, "/Game/Char/BP_Hero"),
                           ("/Script/Engine", "BlueprintGeneratedClass", -3, "BP_Hero_C")],
                          [(-2, -4, 0, "BP_Villain_C", 0x1)], [b"\0" * 8])
    return {"Game/Content/Char/Run_Fwd": seq, "Game/Content/Char/BP_Hero": bp, "Game/Content/Char/BP_Villain": child}


def game_files() -> dict:
    """All synthetic package files of a small game, keyed by in-pak path (relative to ../../../)."""
    files = {}
    ua, ue, _ = mesh_package()
    files["Game/Content/Char/SK_Test.uasset"] = ua
    files["Game/Content/Char/SK_Test.uexp"] = ue
    for base, (a, e) in anim_actor_packages().items():
        files[base + ".uasset"] = a
        files[base + ".uexp"] = e
    files["Game/Config/DefaultGame.ini"] = b"[/Script/EngineSettings.GeneralProjectSettings]\n"
    return files
