"""Dead or Alive 2 - Limited Edition (Japan) (Dreamcast) character assets: CHR mesh + BIN texture readers.

Ghidra-verified facts (analysis in docs/doa2_re_findings.md; 1ST_READ.BIN sha256
27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1, unscrambled, loads at 0x8C010000,
SuperH4:LE:32:default; NaomiLib NL1 model grammar cross-checked against the format references and
the owned KAS00/AYA00/GEN00 archives):

  CHR header (u32 LE): [0]=24, [1]=model-pointer-table offset, [2]=TEXTURE-descriptor-table offset,
    [3]=n_models, [4]=n_textures, [5]=0, [6]=1, [7]=1, [8]=0.  Model 0 starts at file offset 24
    (its first 24 bytes {2I flags, 4f sphere} overlap what the first reader slice mislabeled
    "character scale floats"); word[4] and the 12-byte tail table are TEXTURES, not bones.
  Model pointers are ABSOLUTE SH-4 work-RAM addresses: fighters (KAS/AYA/GEN/...) base 0x0C300000,
  system CHR (EFC0/FIX) base 0x0C400000; file offset = ptr - base + 24.
  Each model: {u32 global0, u32 global1, 4f bounding-sphere}, then submeshes until a {0, vertex_count}
  end marker (count must equal the walked inline+referenced vertex total) and zero padding.
  Each submesh: 80-byte native material header (word0>>29==4; +32 texture id, +36 shader, +76 payload
  length), then strip blocks {u32 flags, u32 count}: flags&8 = indexed triangle list (count triples),
  else triangle strip of count vertices; flags&3 = culling mode. Vertex records: inline (32 B:
    3f pos, 3f normal, 2f uv at +24; 56 B for shader -2; shader -3 packs the normal as 3 signed bytes)
  or 8-B back-references {0x5ff000xx tag, i32 rel} to an earlier inline record in the same submesh.
  Texture descriptors (12 B each): [u16 width, u16 height][u8 pixel, u8 format, u16 pad][u32 address];
  addresses are relative to the first texture's address and index the costume .BIN payload
  (sizes sum exactly to the BIN length: KAS00 55 textures -> 332,800 B).  pixel 0/1/2 =
  ARGB1555/RGB565/ARGB4444; format 1/0xD = twiddled 16-bit, 3 = 8-bit VQ (256-entry codebook).

This module is the READER: parse and decode read-only (owned disc, never written). The native writer
route lives in the doa2_swap stack (PR #8); the rig/skeleton is NOT in CHR (SUP/ACS carry it).
"""
from __future__ import annotations

import struct
from pathlib import Path

GAME_IDS = {"1de2e7634f3161ff": "Dead or Alive 2 - Limited Edition (Japan)"}


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


# --------------------------------------------------------------------------- containers
def parse_chr(data: bytes) -> dict:
    """Parse a DOA2 LE JP .CHR archive header. Corrected layout: word[4]/tail table describe
    TEXTURES (12-byte descriptors), not bones (the first reader slice misread this)."""
    if len(data) < 0x40:
        raise ValueError("too small for a CHR header")
    hdr = [u32(data, o) for o in range(0, 0x18, 4)]
    if hdr[0] != 24:
        raise ValueError(f"unexpected header size {hdr[0]}")
    tbl, tex_tbl, n_obj, n_tex = hdr[1], hdr[2], hdr[3], hdr[4]
    if not (0 < n_obj < 0x1000 and 0 <= n_tex < 0x1000):
        raise ValueError(f"implausible counts n_models={n_obj} n_textures={n_tex}")
    if tbl + 4 * n_obj > tex_tbl or tex_tbl + 12 * n_tex > len(data):
        raise ValueError("pointer tables outside the archive")
    ptrs = [u32(data, tbl + 4 * i) for i in range(n_obj)]
    base = min(ptrs)
    if base >> 24 not in (0x0C,):                       # absolute SH-4 address in work RAM
        raise ValueError(f"model table not absolute pointers (min {base:#x})")
    objs = [p - base + 24 for p in ptrs]                # -> file offsets (model 0 == 24)
    if objs != sorted(set(objs)) or objs[0] != 24:
        raise ValueError("non-monotonic model pointers")
    return {"n_objects": n_obj, "n_textures": n_tex, "ptr_base": base, "objects": objs,
            "model_table": tbl, "texture_table": tex_tbl,
            "model0_sphere": [round(f32(data, 32 + 4 * k), 5) for k in range(4)]}


def texture_size(width: int, height: int, pixel: int, fmt: int) -> int:
    """Native BIN payload size for one texture (VQ carries a 256-entry codebook)."""
    if pixel not in (0, 1, 2):
        raise ValueError(f"unsupported pixel format {pixel:#x}")
    if fmt == 3:
        return 2048 + width * height // 4
    if fmt in (1, 0x0D):
        return 2 * width * height
    raise ValueError(f"unsupported texture format {fmt:#x}")


def parse_textures(chr_data: bytes, bin_size: int) -> list[dict]:
    """Texture descriptors from the CHR tail; each addresses the costume .BIN (relative to the
    first texture). Validates power-of-two dimensions and BIN-allocation fit."""
    info = parse_chr(chr_data)
    raw = [struct.unpack_from("<III", chr_data, info["texture_table"] + 12 * i)
           for i in range(info["n_textures"])]
    base = raw[0][2] if raw else 0
    out = []
    for i, (wh, flags, addr) in enumerate(raw):
        w, h = wh & 0xFFFF, wh >> 16
        pixel, fmt = flags & 0xFF, (flags >> 8) & 0xFF
        if not w or not h or w & (w - 1) or h & (h - 1) or w > 4096 or h > 4096:
            raise ValueError(f"invalid texture dimensions at slot {i}: {w}x{h}")
        size = texture_size(w, h, pixel, fmt)
        off = addr - base
        end = (raw[i + 1][2] - base) if i + 1 < len(raw) else bin_size
        if off < 0 or end < off or end > bin_size or off + size > end:
            raise ValueError(f"texture {i} exceeds its BIN allocation")
        out.append({"index": i, "width": w, "height": h, "pixel": pixel, "format": fmt,
                    "offset": off, "size": size, "capacity": end - off})
    return out


def parse_sup(data: bytes) -> dict:
    """SUP: seam directory then per-seam skin records (CORRECTED from the slice-1 float-record
    misread; grammar verified on all 80 owned costume SUPs).

    Directory: u32 directory_size (== 4*(n+1), 4-aligned), then n monotonic u32 record starts,
    then one 0 sentinel; starts[0] == directory_size. Record: {u32 data_ptr, u8 bone_a, u8 bone_b,
    u8 model_id, u8 initialized} with data_ptr == offset+8, bones < 44 (MOTs carry 44 tracks),
    then 18 floats at data_ptr: two 3x3 orthonormal bases A, B (three column vectors each)
    linking the two joints' neutral orientations (native relation R_a*A = R_b*B; owned seams
    carry A = identity). model_id indexes the costume CHR's models (the seam/bridge mesh)."""
    if len(data) < 4:
        raise ValueError("truncated SUP directory")
    first = u32(data, 0)
    if first == 0:
        return {"seam_count": 0, "seams": [], "file_bytes": len(data)}
    if first & 3 or not 8 <= first <= len(data):
        raise ValueError("SUP directory size outside its allocation")
    vals = [u32(data, 4 * i) for i in range(first // 4)]
    if vals[-1] != 0 or any(v == 0 for v in vals[:-1]):
        raise ValueError("SUP directory must end with one zero sentinel")
    starts = vals[:-1]
    if starts != sorted(set(starts)) or starts[0] != first:
        raise ValueError("SUP seam offsets are non-monotonic")
    seams = []
    for i, s in enumerate(starts):
        limit = starts[i + 1] if i + 1 < len(starts) else len(data)
        if s + 80 > limit:                                  # 8-B header + 18 axis floats
            raise ValueError(f"SUP seam {i} lacks its header and axis bases")
        ptr, bone_a, bone_b, model, initialized = struct.unpack_from("<IBBBB", data, s)
        if ptr != s + 8 or bone_a >= 44 or bone_b >= 44 or initialized not in (0, 1):
            raise ValueError(f"SUP seam {i} has invalid pointer/joint fields")
        f = struct.unpack_from("<18f", data, ptr)
        # 18 floats = three interleaved column pairs (A_k, B_k) — the native layout the writer
        # lane reads as reshape(3,2,3); A/B are each 3x3 orthonormal bases (column-major triples)
        seams.append({"offset": s, "data_offset": ptr, "bone_a": bone_a, "bone_b": bone_b,
                      "model_id": model, "initialized": initialized, "bytes": limit - s,
                      "a_vectors": [list(f[6 * k:6 * k + 3]) for k in range(3)],
                      "b_vectors": [list(f[6 * k + 3:6 * k + 6]) for k in range(3)]})
    return {"seam_count": len(seams), "seams": seams, "file_bytes": len(data)}


# --------------------------------------------------------------------------- rig / skeleton
# Native rest-rig facts from the owned 1ST_READ.BIN (sha256 below), cross-checked against the
# writer lane's independent profile (gbox-doa2-animation/*_profile.json, PR #8 doa2_rest):
EXE_LOAD = 0x8C010000
EXE_SHA256 = "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1"
REST_TABLE = 0x8C1949A0                      # 25 u32 slot pointers -> 51f (17 joints x xyz)
SCRIPT_TABLE = 0x8C1C85F4                    # 25 u32 pointers -> per-slot costume script tables
FILE_TABLE = 0x8C17F5F4                      # 250-B stride: 5 filename ids per slot/costume
FILE_NAMES = 0x8C17E774                      # u32[] -> resource filename strings
# render-script section bytes (verified against FUN_8c0dd826/FUN_8c0dd906 matrix consumers)
SCRIPT_SECTIONS = {0xFE: "primary", 0xFC: "skip", 0xFB: "shadow", 0xFD: "secondary",
                   0xFA: "accessory", 0xF9: "extra"}
JOINT_PARENTS = [2, 0, -1, 7, 8, 4, 2, 6, 0, 13, 14, 10, 2, 12, 0, 1, 1]   # root = 2 (pelvis)
JOINT_ROLES = ["chest", "head", "pelvis", "left_foot", "left_elbow", "left_hand", "left_thigh",
               "left_shin", "left_shoulder", "right_foot", "right_elbow", "right_hand",
               "right_thigh", "right_shin", "right_shoulder", "left_breast", "right_breast"]
# verified render slots for the disc-anchored export route (writer-lane doa2_bindings resolution)
FIGHTER_SLOTS = {"KAS": 5, "GEN": 6}


def parse_rest_rig(exe: bytes, exe_sha256: str = EXE_SHA256) -> dict:
    """Per-slot local rest translations (17 joints x xyz floats) from the native rest-vector
    table. Refuses any executable other than the pinned owned build."""
    import hashlib

    digest = hashlib.sha256(exe).hexdigest()
    if digest != exe_sha256:
        raise ValueError("executable is not the verified DOA2 LE JP 1ST_READ.BIN")
    ptrs = struct.unpack_from("<25I", exe, REST_TABLE - EXE_LOAD)
    profiles = []
    for fid, addr in enumerate(ptrs):
        if not addr:
            profiles.append({"fighter_id": fid, "rest_address": None})
            continue
        v = struct.unpack_from("<51f", exe, addr - EXE_LOAD)
        profiles.append({"fighter_id": fid, "rest_address": f"{addr:#x}",
                         "local_translations": [list(v[i:i + 3]) for i in range(0, 51, 3)]})
    return {"exe_sha256": digest, "rest_table": f"{REST_TABLE:#x}", "n_slots": len(profiles),
            "roles": JOINT_ROLES, "parents": JOINT_PARENTS, "profiles": profiles}


def solve_joint_bases(seam_records: list[dict], anchor: int = 2,
                      joint_ids=range(15), tolerance: float = 1e-5) -> dict:
    """Recover each joint's neutral rotation basis from SUP seams: R_a*A = R_b*B with A, B the
    seam's orthonormal bases (owned seams carry A = identity, so a seam directly yields
    R_a = R_b*B). BFS from the anchor (pelvis = 2); duplicate seams across costumes must agree.
    Covers the 15 core joints (eye joints 15/16 have independent gaze; Tengu wing seams
    17..22 exist only on TNG costumes and are not part of the shared fighter rig)."""
    import numpy as np

    ids = set(joint_ids)
    if anchor not in ids:
        raise ValueError("seam anchor is outside the requested joint set")
    edges = []
    for rec in seam_records:
        a, b = rec["bone_a"], rec["bone_b"]
        if a not in ids or b not in ids:
            continue
        A = np.asarray(rec["a_vectors"], float).T          # vectors are matrix columns
        B = np.asarray(rec["b_vectors"], float).T
        for M in (A, B):
            if not np.isfinite(M).all() or not np.allclose(M.T @ M, np.eye(3), atol=tolerance) \
                    or not np.isclose(np.linalg.det(M), 1.0, atol=tolerance):
                raise ValueError(f"seam basis for joints {a}/{b} is not a proper rotation")
        edges.append((a, b, B @ A.T, rec.get("name", "?")))
    rot = {anchor: np.eye(3)}
    while True:
        previous = len(rot)
        for a, b, rel, src in edges:
            if b in rot and a not in rot:
                rot[a] = rot[b] @ rel
            elif a in rot and b not in rot:
                rot[b] = rot[a] @ rel.T
            elif a in rot and b in rot and not np.allclose(rot[a], rot[b] @ rel, atol=tolerance):
                raise ValueError(f"inconsistent seam orientation at joints {a}/{b} (source {src})")
        if len(rot) == previous:
            break
    missing = ids - rot.keys()
    if missing:
        raise ValueError(f"seam evidence does not connect joints {sorted(missing)} to anchor {anchor}")
    return {str(j): rot[j] for j in sorted(rot)}


def build_rig(exe: bytes, sup_files: dict[str, bytes], fighter_slot: int,
              exe_sha256: str = EXE_SHA256) -> dict:
    """World-space rest pose for one fighter slot: rotations solved from the disc-wide SUP seam
    graph, translations from the native rest-vector chain (pelvis at the origin). Result is the
    reader-lane equivalent of the writer lane's doa2-native-rig-v1 world matrices."""
    import numpy as np

    rest = parse_rest_rig(exe, exe_sha256)
    prof = rest["profiles"][fighter_slot]
    if not prof.get("rest_address"):
        raise ValueError(f"native rest slot {fighter_slot} is empty")
    records = [{"name": name, **seam}
               for name, data in sup_files.items() for seam in parse_sup(data)["seams"]]
    bases = solve_joint_bases(records)
    bases = {int(k): v for k, v in bases.items()}          # JSON-safe str keys -> int
    bases[15] = bases[16] = np.eye(3)                      # eyes: neutral gaze from head
    vec = prof["local_translations"]
    pos = {2: np.zeros(3)}
    for _ in range(len(JOINT_PARENTS)):
        for j, p in enumerate(JOINT_PARENTS):
            if j not in pos and (p == -1 or p in pos):
                origin = np.zeros(3) if p == -1 else pos[p]
                pos[j] = origin + np.asarray(vec[j], float)
    if len(pos) != 17:
        raise ValueError("rest-vector chain does not cover all 17 joints")
    world = []
    for j in range(17):
        M = np.eye(4)
        M[:3, :3] = bases[j]
        M[:3, 3] = pos[j]
        world.append(M.tolist())
    return {"format": "doa2-reader-rig-v1", "fighter_slot": fighter_slot,
            "rest_address": prof["rest_address"], "parents": JOINT_PARENTS, "roles": JOINT_ROLES,
            "world": world, "n_seam_records": len(records),
            "seam_sources": sorted(set(r["name"] for r in records)),
            "note": "world rest pose from native rest vectors + SUP seam bases; skin weights are "
                    "NOT in CHR/SUP (the render-script emit map is the writer lane's next slice)"}


def parse_render_scripts(exe: bytes, exe_sha256: str = EXE_SHA256) -> list[dict]:
    """Reader-side decode of the native render scripts (table 0x8c1c85f4).

    Each of the 25 render slots points at a per-costume table of script entries; each entry
    walks commands (mode-0: part-list pointer; modes 1..4: single argument) and each part
    list is a byte stream: section markers FE/FD/FC/FB/FA/F9 then model ids until FF.
    The 15 primary + 2 extra parts per costume ARE the model->joint emit map: primary[i]
    follows joint i for the 15 matrices of FUN_8c0dd826 and the extras follow the two
    breast matrices of FUN_8c0dd906 (geometrically verified: head-above-chest, exact
    left/right mirror of the assembled world-space part centers; a scrambled assignment
    is incoherent). Refuses any executable other than the pinned owned build."""
    import hashlib

    if exe_sha256 != "any" and hashlib.sha256(exe).hexdigest() != exe_sha256:
        raise ValueError("executable is not the verified DOA2 LE JP 1ST_READ.BIN")

    def word(addr: int) -> int:
        if addr < EXE_LOAD or addr + 4 > EXE_LOAD + len(exe):
            raise ValueError(f"script pointer {addr:#x} outside the executable")
        return struct.unpack_from("<I", exe, addr - EXE_LOAD)[0]

    def filename(idx: int) -> str:
        start = word(FILE_NAMES + idx * 4) - EXE_LOAD
        end = exe.find(b"\0", start, start + 256)
        if end < 0:
            raise ValueError("resource name has no terminator")
        return exe[start:end].decode("ascii")

    slots = []
    for slot in range(25):
        ptr = word(SCRIPT_TABLE + slot * 4)
        record = {"slot": slot, "table_address": ptr, "costumes": []}
        if not ptr:
            slots.append(record)
            continue
        for costume in range(32):
            entry = word(ptr + costume * 4)
            if not entry:
                break
            sections = {name: [] for name in SCRIPT_SECTIONS.values()}
            commands = []
            cursor = entry
            for _ in range(128):
                command = word(cursor)
                cursor += 4
                if not command:
                    break
                mode = 0
                if command & 0xFFFF0000 == 0xFFFF0000:
                    mode = (command & 0xFFFF) // 0x1000
                    if mode not in range(1, 5) or command & 0xFFF:
                        raise ValueError(f"unknown script command {command:#x}")
                    command = word(cursor)
                    cursor += 4
                commands.append({"mode": mode, "argument": command})
                if mode == 0 and command:
                    i = command - EXE_LOAD
                    section = "primary"
                    for _ in range(1024):
                        value = exe[i]
                        i += 1
                        if value == 0xFF:
                            break
                        if value in SCRIPT_SECTIONS:
                            section = SCRIPT_SECTIONS[value]
                        else:
                            sections[section].append(value)
                    else:
                        raise ValueError("part list has no terminator")
            else:
                raise ValueError("script has no terminator")
            primary, extra = sections["primary"], sections["extra"]
            if primary and len(primary) != 15:
                raise ValueError(f"slot {slot} costume {costume}: {len(primary)} primary parts")
            if extra and len(extra) != 2:
                raise ValueError(f"slot {slot} costume {costume}: {len(extra)} extra parts")
            ids = struct.unpack_from("<5H", exe, FILE_TABLE + costume * 250 + slot * 10 - EXE_LOAD)
            files = dict(zip(("control", "textures", "geometry", "morph", "skin"),
                             (filename(i) for i in ids)))
            record["costumes"].append({
                "costume": costume, "script_address": entry, "files": files,
                "sections": sections, "commands": commands,
                "emit_models": primary + extra})
        slots.append(record)
    return slots


def emit_skin_map(exe: bytes, slot: int, costume: int, n_models: int,
                  exe_sha256: str = EXE_SHA256) -> dict:
    """Model -> joint emit assignment for one native slot/costume (the render-script fact
    geometry cannot supply). Rigid: primary[i] and extra[i] bind joint 0..16 in order;
    accessories bind the chest (their world centers sit within ~4 cm of the chest origin);
    shadow parts are depth-projected blobs left unskinned; seam/bridge models are not
    emitted by the render script at all. Returns {model_id: joint} plus diagnostics."""
    records = parse_render_scripts(exe, exe_sha256)[slot]["costumes"]
    if costume >= len(records) or not records[costume]["sections"]["primary"]:
        raise ValueError(f"native slot {slot} costume {costume} has no verified body emit map")
    rec = records[costume]
    bind: dict[int, int] = {}
    for joint, model in enumerate(rec["sections"]["primary"] + rec["sections"]["extra"]):
        if model >= n_models:
            raise ValueError(f"emit part {model} outside the costume's {n_models} models")
        bind[model] = joint
    for model in rec["sections"]["accessory"]:
        if model >= n_models:
            raise ValueError(f"accessory part {model} outside the costume's {n_models} models")
        bind[model] = 0                                        # chest (geometric nearest-joint)
    shadows = [m for m in rec["sections"]["shadow"] if m < n_models]
    unskinned = sorted(set(shadows + rec["sections"]["skip"] + rec["sections"]["secondary"])
                       - set(bind))
    return {"slot": slot, "costume": costume, "script_address": rec["script_address"],
            "files": rec["files"], "bind": bind, "shadow_models": sorted(set(shadows)),
            "unskinned_models": unskinned,
            "n_seam_models": n_models - len(bind) - len(set(unskinned)),
            "source": "render scripts 0x8c1c85f4 (FUN_8c0dd826/FUN_8c0dd906 matrix consumers)"}


def parse_mot_table(data: bytes) -> dict:
    """MOT: leading u32 offset table (0 ends?), offsets into per-clip blobs."""
    offs = []
    o = 0
    while o < min(len(data), 0x4000):
        v = u32(data, o)
        if v == 0 or v >= len(data):
            break
        offs.append(v)
        o += 4
    return {"n_clips": len(offs), "offsets": offs}


# --------------------------------------------------------------------------- mesh decode
def _triangles(flags: int, indices: list[int]) -> list[tuple[int, int, int]]:
    culling = flags & 3
    if flags & 8:                                        # indexed list: count triples
        triples: list[tuple[int, int, int]] = [(indices[k], indices[k + 1], indices[k + 2])
                                               for k in range(0, len(indices), 3)]
        if culling == 2:
            triples = [(y, x, z) for x, y, z in triples]
    else:                                                # strip
        triples = []
        for k in range(len(indices) - 2):
            x, y, z = indices[k:k + 3]
            if (k % 2 == 0) == (culling == 2):
                x, y = y, x
            triples.append((x, y, z))
    return [t for t in triples if len(set(t)) == 3]


def parse_meshes(chr_data: bytes) -> dict:
    """Decode every NL1 model in a CHR: submeshes (80-B native material headers), strips,
    inline/referenced vertices (pos/normal/uv) and triangles. Validates each model's
    {0, vertex_count} end marker and rejects non-finite floats."""
    import math

    info = parse_chr(chr_data)
    objs, count = info["objects"], info["n_objects"]
    limit0 = info["model_table"]
    models = []
    for mid, start in enumerate(objs):
        model_limit = objs[mid + 1] if mid + 1 < count else limit0
        limit = model_limit - 8 if mid + 1 < count else limit0
        if start + 24 > limit:
            raise ValueError(f"model {mid} too short at {start:#x}")
        gp0, gp1 = struct.unpack_from("<2I", chr_data, start)
        sphere = struct.unpack_from("<4f", chr_data, start + 8)
        cursor = start + 24
        meshes, vertex_total, tri_total = [], 0, 0
        while cursor + 4 <= limit and u32(chr_data, cursor):
            if cursor + 80 > limit:
                raise ValueError(f"truncated submesh header at {cursor:#x}")
            header = chr_data[cursor:cursor + 80]
            if u32(header, 0) >> 29 != 4:
                raise ValueError(f"unsupported native parameter word at {cursor:#x}")
            texture_id = struct.unpack_from("<i", header, 32)[0]
            shader = struct.unpack_from("<i", header, 36)[0]
            length = u32(header, 76)
            position = cursor + 80
            stop = position + length
            if stop > model_limit:
                raise ValueError("submesh crosses model boundary")
            vertices, strips, triangles = [], [], []
            registered = {}
            while position < stop:
                if position + 8 > stop:
                    raise ValueError("short strip header")
                flags, n = struct.unpack_from("<2I", chr_data, position)
                if flags > 0x1FF or not 0 < n <= 65536:
                    raise ValueError(f"invalid strip at {position:#x}")
                logical = n * (3 if flags & 8 else 1)
                indices = []
                position += 8
                for _ in range(logical):
                    if position + 4 > stop:
                        raise ValueError("short vertex record")
                    tag = u32(chr_data, position)
                    if 0x5FF00000 <= tag <= 0x5FFFFFFF:   # back-reference to an inline record
                        if position + 8 > stop:
                            raise ValueError("short vertex reference")
                        rel = struct.unpack_from("<i", chr_data, position + 4)[0]
                        target = position + 8 + rel
                        if target not in registered:
                            raise ValueError(f"vertex reference misses earlier record at {position:#x}")
                        indices.append(registered[target])
                        position += 8
                    else:
                        size = 56 if shader == -2 else 32
                        if position + size > stop:
                            raise ValueError("inline vertex crosses submesh boundary")
                        raw = chr_data[position:position + size]
                        xyz = struct.unpack_from("<3f", raw, 0)
                        if shader == -3:                    # packed normal: 3 signed bytes
                            normal = tuple(max(-1.0, v / 127.0) for v in struct.unpack_from("<3b", raw, 12))
                            uv = struct.unpack_from("<2f", raw, 24)
                        else:
                            normal = struct.unpack_from("<3f", raw, 12)
                            uv = struct.unpack_from("<2f", raw, size - 8)
                        if not all(math.isfinite(v) for v in (*xyz, *normal, *uv)):
                            raise ValueError(f"non-finite vertex at {position:#x}")
                        registered[position] = len(vertices)
                        indices.append(len(vertices))
                        vertices.append((*xyz, *normal, *uv))
                        position += size
                strips.append({"flags": flags, "count": n, "indices": indices})
                triangles.extend(_triangles(flags, indices))
            meshes.append({"offset": cursor, "texture_id": texture_id, "shader": shader,
                           "vertices": vertices, "strips": strips, "triangles": triangles})
            vertex_total += sum(len(s["indices"]) for s in strips)
            tri_total += len(triangles)
            cursor = stop
        end = cursor
        if end + 8 > model_limit or u32(chr_data, end) != 0:
            raise ValueError(f"model {mid} has no end marker at {end:#x}")
        declared = u32(chr_data, end + 4)
        if declared != vertex_total:
            raise ValueError(f"model {mid} end-marker count {declared} != walked {vertex_total}")
        models.append({"id": mid, "offset": start, "global_flags": (gp0, gp1), "sphere": sphere,
                       "meshes": meshes, "vertex_count": vertex_total, "triangle_count": tri_total})
    total_v = sum(m["vertex_count"] for m in models)
    total_t = sum(m["triangle_count"] for m in models)
    return {"n_models": len(models), "n_submeshes": sum(len(m["meshes"]) for m in models),
            "n_vertices": total_v, "n_triangles": total_t, "models": models, **info}


# --------------------------------------------------------------------------- textures
def pvr_wrap(tex: dict, body: bytes) -> bytes:
    """Synthesize the PVRT chunk header the native BIN omits (payload bytes unchanged)."""
    if len(body) != tex["size"]:
        raise ValueError("texture body/descriptor size mismatch")
    return (b"PVRT" + struct.pack("<IBBHHH", len(body) + 8, tex["pixel"], tex["format"],
                                  0, tex["width"], tex["height"]) + body)


def decode_texture(tex: dict, bin_data: bytes):
    """One native BIN texture -> (width, height, RGBA bytes, description) via gbox.ninja."""
    from .ninja import pvr_decode
    body = bin_data[tex["offset"]:tex["offset"] + tex["size"]]
    return pvr_decode(pvr_wrap(tex, body))


# costume prefix -> (display name, aliases). Confirmed against the disc's arts_*.bin / *.mot tables
# (1ST_READ+0x16e7fc arts_*, +0x16e890 *_mot names: zack tina janlee ryu kasumi genfu bayman bass
# leifan ayane hika karate ind raido tengu sambo). KTE's display identity is unconfirmed.
FIGHTERS = [
    ("KAS", "Kasumi", ["Kasumi-chan", "DOA2 Kasumi"]),
    ("AYA", "Ayane", ["DOA2 Ayane"]),
    ("LEI", "Leifang", ["Lei Fang", "DOA2 Leifang"]),
    ("TIN", "Tina", ["Tina Armstrong", "DOA2 Tina"]),
    ("BAS", "Bass", ["Bass Armstrong", "DOA2 Bass"]),
    ("JAN", "Jann Lee", ["Jan Lee", "DOA2 Jann Lee"]),
    ("GEN", "Gen Fu", ["Genfu", "DOA2 Gen Fu"]),
    ("BAY", "Bayman", ["DOA2 Bayman"]),
    ("RYU", "Ryu Hayabusa", ["Ryu", "DOA2 Ryu"]),
    ("ZAC", "Zack", ["DOA2 Zack"]),
    ("HIK", "Helena", ["Helena Douglas", "DOA2 Helena"]),
    ("SAM", "Leon", ["DOA2 Leon"]),                       # arts_sam + sambo motion set
    ("TNG", "Tengu", ["Bankotsu-bo", "DOA2 Tengu"]),
    ("KTE", "KTE fighter", ["Ein", "Kasumi Alpha"]),      # costume family present; identity unconfirmed
]
# single-costume families that are not part of the selectable roster (boss/story variants)
VARIANTS = ["LOR", "MAM", "PDG", "WBA", "YTI"]
# motion files are named by the character's full nickname (1ST_READ+0x16e890: zack.mot tina.mot
# janlee.mot ryu.mot kasumi.mot genfu.mot bayman.mot bass.mot leifan.mot ayane.mot hika.mot
# karate.mot ind.mot raido.mot tengu.mot sambo.mot comon.mot). Only name-identical mappings here.
MOT_FILES = {"KAS": "KASUMI", "AYA": "AYANE", "LEI": "LEIFAN", "TIN": "TINA", "BAS": "BASS",
             "JAN": "JANLEE", "GEN": "GENFU", "BAY": "BAYMAN", "RYU": "RYU", "ZAC": "ZACK",
             "HIK": "HIKA", "TNG": "TENGU"}           # SAM/KTE motion names unconfirmed (sambo/karate/ind/raido)


def roster(disc_files: dict | None = None) -> list[dict]:
    """Costume entries from the disc listing (dict[str, tuple] like GDRom.files). With none, the
    static roster above."""
    import re
    fam: dict[str, list[str]] = {}
    if disc_files:
        for n in disc_files:
            m = re.match(r"^DOA2/([A-Z]+)(\d+)\.(?:CHR|SUP|BIN)$", n)
            if m and m.group(1) not in ("STAGE", "EFC", "FIX", "DV"):
                fam.setdefault(m.group(1), []).append(m.group(2))   # keep zero padding as-is
    out = []
    for pre, name, aliases in FIGHTERS:
        costumes = sorted(set(fam.get(pre, [])), key=int) or ["0"]
        out.append({"key": pre, "slug": f"doa2_{pre.lower()}", "name": name, "aliases": aliases,
                    "kind": "character", "costumes": costumes})
    for pre in VARIANTS:
        if not fam or pre in fam:
            out.append({"key": pre, "slug": f"doa2_{pre.lower()}", "name": f"{pre} (variant)",
                        "aliases": [], "kind": "variant", "costumes": sorted(set(fam.get(pre, ["0"])), key=int)})
    return out


# --------------------------------------------------------------------------- export
def export_assets(chr_data: bytes, bin_data: bytes, out_dir: str, name: str,
                  sup_data: bytes | None = None, rig: dict | None = None,
                  emit: dict | None = None) -> dict:
    """Decode one costume's CHR + BIN into a UAP manifest, per-texture PNGs and a .gltf.
    Textures attached by native texture id. With `rig` (build_rig output) the glTF carries the
    real 17-joint native skeleton (rest pose from the EXE rest table + SUP seam bases); with
    `emit` (emit_skin_map output) body parts carry rigid model->joint weights from the
    render-script emit order (primary[i]->joint i, extras->breast joints 15/16, accessories
    ->chest); shadow/projected parts stay unskinned (joint 0, weight 0)."""
    import json as _json

    import numpy as np

    from .melee_models import write_gltf
    from .ninja import png as png_bytes

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meshes = parse_meshes(chr_data)
    textures = parse_textures(chr_data, len(bin_data))
    files = []
    pngs = {}
    arrays = {}
    for tex in textures:
        w, h, rgba, desc = decode_texture(tex, bin_data)
        arrays[tex["index"]] = np.frombuffer(rgba, np.uint8).reshape(h, w, 4)
        pngs[tex["index"]] = (w, h, rgba)
        fn = f"{name}_tex{tex['index']:02d}_{w}x{h}.png"
        (out / fn).write_bytes(png_bytes(w, h, rgba))
        files.append(fn)
    bind = emit["bind"] if emit else {}
    shadow = set(emit.get("shadow_models", [])) if emit else set()
    worlds = ([np.asarray(m, np.float32) for m in rig["world"]] if rig is not None else None)
    prims = []
    for model in meshes["models"]:
        groups: dict[int, dict] = {}
        for mesh in model["meshes"]:
            g = groups.setdefault(mesh["texture_id"], {"pos": [], "nrm": [], "uv": [], "tris": []})
            base_idx = len(g["pos"])
            for v in mesh["vertices"]:
                g["pos"].append(v[0:3]); g["nrm"].append(v[3:6]); g["uv"].append(v[6:8])
            g["tris"].extend((a + base_idx, b + base_idx, c + base_idx) for a, b, c in mesh["triangles"])
        for tid, g in sorted(groups.items()):
            if not g["tris"]:
                continue
            n = len(g["pos"])
            joint = bind.get(model["id"], 0)
            weighted = model["id"] in bind and model["id"] not in shadow
            pos = np.array(g["pos"], np.float32)
            nrm = np.array(g["nrm"], np.float32)
            if weighted and worlds is not None:
                # write_gltf expects world-rest-pose vertices (its inverse binds are
                # translation-only): move bound parts into their joint's world frame
                M = worlds[joint]
                pos = pos @ M[:3, :3].T + M[:3, 3]
                nrm = nrm @ M[:3, :3].T
            prims.append({"name": f"{name}_m{model['id']:02d}_t{tid}",
                          "pos": pos, "nrm": nrm,
                          "uv": np.array(g["uv"], np.float32), "tris": np.array(g["tris"], np.int32),
                          "J": np.full((n, 4), joint, np.uint16),
                          "W": np.tile([1.0 if weighted else 0.0, 0, 0, 0], (n, 1)).astype(np.float32),
                          "tex": arrays.get(tid)})
    gltf = out / f"{name}.gltf"
    if rig is not None:
        joints = [{"parent": p, "world": np.asarray(m, dtype=np.float32)}
                  for p, m in zip(rig["parents"], rig["world"])]
        joint_names = [f"{n}_{j:02d}" for j, n in enumerate(rig["roles"])]
        write_gltf(gltf, joints, prims, 1.0, name, joint_names=joint_names)
    else:
        write_gltf(gltf, [{"parent": -1, "world": np.eye(4, dtype=np.float32)}], prims, 1.0, name)
    files.append(gltf.name)
    manifest = {
        "uap_version": "0.1", "name": name,
        "source": {"game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))],
                   "extraction_method": "gbox.doa2_chars (meshes + textures decoded)"},
        "coordinate_system": {"up": "Y", "forward": "-Z", "handedness": "right"},
        "geometry_facts": {"n_models": meshes["n_models"], "n_submeshes": meshes["n_submeshes"],
                           "n_vertices": meshes["n_vertices"], "n_triangles": meshes["n_triangles"],
                           "model_ptr_base": f"{meshes['ptr_base']:#x}"},
        "texture_facts": {"n_textures": len(textures),
                          "formats": sorted({(t["pixel"], t["format"]) for t in textures}),
                          "bin_bytes": sum(t["capacity"] for t in textures)},
        "skeleton_note": ("rig decoded: 17-joint native hierarchy from the EXE rest-vector table "
                          "0x8c1949a0 + disc-wide SUP seam bases; model->joint assignment from the "
                          "render-script emit map 0x8c1c85f4 (rigid per part)")
        if rig is not None else
        "rig is NOT stored in CHR (word[4] is the texture count; bones live in the "
        "SUP/ACS supplement route) - weights intentionally absent from the glTF",
        "skin_facts": ({"method": "render-script emit order", "table": "0x8c1c85f4",
                        "slot": emit["slot"], "costume": emit["costume"],
                        "script_address": emit["script_address"],
                        "n_bound_models": len(emit["bind"]),
                        "n_shadow_models": len(emit["shadow_models"]),
                        "n_unskinned_models": len(emit["unskinned_models"]),
                        "n_seam_models": emit["n_seam_models"]}
                       if emit is not None else None),
        "skeleton_facts": ({"n_joints": 17, "parents": rig["parents"], "roles": rig["roles"],
                            "rest_address": rig["rest_address"], "fighter_slot": rig["fighter_slot"],
                            "n_seam_records": rig["n_seam_records"],
                            "seam_sources": len(rig["seam_sources"])}
                           if rig is not None else None),
        "confidence": {"entity": "verified", "geometry": "verified", "materials": "verified",
                       "textures": "verified",
                       "skeleton": "verified" if rig is not None else "missing",
                       "skin_weights": "verified" if emit is not None else "missing",
                       "animations": "missing", "source_identity": "verified"},
    }
    (out / "manifest.json").write_text(_json.dumps(manifest, indent=1))
    files.append("manifest.json")
    return {"files": files, "manifest": manifest, "meshes": meshes, "textures": textures}


def export(gdi: str, out_dir: str, key: str, costume: str = "0") -> dict:
    """Extract one fighter's costume asset set read-only from the owned disc: containers plus
    decoded meshes, textures and the native 17-joint rig (UAP manifest + PNGs + skinned glTF)."""
    from .gdrom import GDRom

    disc = GDRom(gdi)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    costume = costume.zfill(2) if len(costume) == 1 else costume     # disc names are <KEY><NN>
    stem = f"{key}{costume}"
    files = []
    sups = None
    rig = None
    emit = None
    slot = FIGHTER_SLOTS.get(key)
    if slot is not None:
        try:
            exe = disc.read("1ST_READ.BIN")
            sups = {n: disc.read(n) for n in sorted(disc.files)
                    if n.startswith("DOA2/") and n.endswith(".SUP")}
            rig = build_rig(exe, sups, slot)
        except ValueError:
            rig = None                                    # non-pinned executable: rig stays off
        if rig is not None:
            try:
                emit = emit_skin_map(exe, slot, int(costume) % 32,
                                     parse_chr(disc.read(f"DOA2/{stem}.CHR"))["n_objects"])
            except ValueError:
                emit = None                               # costume without a verified emit map
        else:
            exe = None
    for ext in ("BIN", "CHR", "SUP"):
        data = disc.read(f"DOA2/{stem}.{ext}")
        (out / f"{stem}.{ext}").write_bytes(data)
        files.append(f"{stem}.{ext}")
    r = export_assets(disc.read(f"DOA2/{stem}.CHR"), disc.read(f"DOA2/{stem}.BIN"), str(out),
                      f"doa2_{key.lower()}_{costume}", rig=rig, emit=emit)
    manifest = r["manifest"]
    manifest["provenance"] = [{"file": f"DOA2/{stem}.{e}", "bytes": len(disc.read(f"DOA2/{stem}.{e}"))}
                              for e in ("BIN", "CHR", "SUP")]
    mot = MOT_FILES.get(key, key)
    if disc.files.get(f"DOA2/{mot}.MOT"):
        manifest["source"]["resource_ids"] = [f"DOA2/{stem}.{e}" for e in ("BIN", "CHR", "SUP")] + [f"DOA2/{mot}.MOT"]
    (out / "manifest.json").write_text(__import__("json").dumps(manifest, indent=1))
    return {"files": files + r["files"], "manifest": manifest}
