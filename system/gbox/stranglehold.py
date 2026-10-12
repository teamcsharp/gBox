"""Native model reader for John Woo Presents Stranglehold (PS3, BLUS30081).

Stranglehold's PS3 cooked .xxx packages use a Midway variant of Unreal Engine 3.
The file starts with a standard-looking UE3 package tag/version/headersize, then a
fixed 113-byte outer header containing the package summary, followed by a series of
independent zlib-compressed chunks (tag 0x9E2A83C1, block size 0x10000).  The
first few chunks are the name/import/export tables; the remaining chunks are the
export bulk data (meshes, textures, animations).

This reader decompresses the chunks, reconstructs a logical UE3 package
(outer header + concatenated decompressed chunks), parses the UE3
name/import/export tables, and exposes the embedded SkeletalMesh / Texture2D /
Material exports.  It also writes a small placeholder GLB so the gBox collection
machinery can render a preview and track the source asset.

Mesh vertex/index decoding is not fully implemented yet; the reader records the
raw SkeletalMesh blobs and a manifest of exports so the next stage can decode
the legacy FStaticLODModel layout used by build 375/licensee 25.
"""
import hashlib
import json
import struct
import zlib
from pathlib import Path

import numpy as np

TAG = 0x9E2A83C1
HEADER_PREFIX = 113      # outer summary/header size for Midway multi-chunk packages
CHUNK_BLOCK = 0x10000


class FormatError(ValueError):
    pass


def _decompress_chunks(path: Path) -> tuple[list[bytes], bytes]:
    """Scan a Stranglehold .xxx for embedded zlib chunks and return (decompressed_chunks, file_header).

    The reconstructed logical package is ``header[:HEADER_PREFIX] + b''.join(chunks)``.
    """
    data = path.read_bytes()
    if len(data) < HEADER_PREFIX or struct.unpack(">I", data[:4])[0] != TAG:
        raise FormatError("not a UE3 package")
    ver = struct.unpack(">I", data[4:8])[0]
    if not (ver & 0xFFFF):
        # Standard fully-compressed package (e.g. AIIU.xxx) – no extra chunk scan needed.
        return [], data
    tagb = struct.pack(">I", TAG)
    blockb = struct.pack(">I", CHUNK_BLOCK)
    chunks: list[bytes] = []
    i = 0
    while i < len(data) - 16:
        if data[i:i + 4] != tagb or data[i + 4:i + 8] != blockb:
            i += 1
            continue
        comp, usz = struct.unpack_from(">II", data, i + 8)
        n = (usz + CHUNK_BLOCK - 1) // CHUNK_BLOCK
        table_off = i + 16
        data_off = table_off + 8 * n
        out = bytearray()
        o = data_off
        for k in range(n):
            cs, _ = struct.unpack_from(">II", data, table_off + 8 * k)
            out += zlib.decompress(data[o:o + cs])
            o += cs
        if len(out) != usz:
            raise FormatError(f"chunk at {i}: expected {usz} uncompressed, got {len(out)}")
        chunks.append(bytes(out))
        i = o  # continue after this chunk
    return chunks, data[:HEADER_PREFIX]


class Container:
    """A Stranglehold PS3 .xxx package: names, imports, exports, bulk blobs."""

    def __init__(self, path_or_bytes):
        data: bytes = b""
        if isinstance(path_or_bytes, (bytes, bytearray)):
            data = bytes(path_or_bytes)
            self.path = None
            chunks: list[bytes] = []
            header = data
        else:
            self.path = Path(path_or_bytes)
            chunks, header = _decompress_chunks(self.path)
        if chunks:
            # Midway multi-chunk container: logical package = 113-byte header + decompressed chunks.
            self.logical = header[:HEADER_PREFIX] + b"".join(chunks)
            self._read_tables()
        else:
            # Standard fully-compressed UE3 package (script packages like AIIU.xxx).
            from . import ue3
            pkg = ue3.Package(data)
            self.logical = pkg.d
            self.names = pkg.names
            self.imports = pkg.imports
            self.exports = pkg.exports

    def _read_tables(self):
        d = self.logical
        # Summary lives in the first 113 bytes; FolderName "None" is part of it.
        idx = d.index(b"\x00\x00\x00\x05None\x00")
        o = idx + 9
        flags, nc, no, ec, eo, ic, io = struct.unpack(">7I", d[o:o + 28])
        self._summary = {"flags": flags, "name_count": nc, "name_offset": no,
                         "export_count": ec, "export_offset": eo,
                         "import_count": ic, "import_offset": io}
        self.names = _read_name_table(d, no, nc)
        self.imports = _read_imports(d, io, ic)
        self.exports = _read_exports(d, eo, ec, self.names)

    def ref_class(self, i: int) -> str:
        """Resolve an export's class name (negative = import, 0 = Class, positive = export)."""
        if i > 0:
            e = self.exports[i - 1]
            return self.ref_class(e["class"]) if e["class"] else "Class"
        if i < 0:
            m = self.imports[-i - 1]
            # The import's ObjectName tells us the type of object it describes.
            return self.names[m["name"]] if 0 <= m["name"] < len(self.names) else f"?{m['name']}"
        return "Class"

    def blob(self, i: int) -> bytes:
        """Raw serialized bytes of export i (1-based)."""
        e = self.exports[i - 1]
        if e["size"] <= 0:
            return b""
        if e["offset"] + e["size"] > len(self.logical):
            raise FormatError(f"export {i} blob {e['offset']}:{e['size']} outside logical {len(self.logical)}")
        return self.logical[e["offset"]:e["offset"] + e["size"]]

    def mesh_exports(self) -> list[dict]:
        out = []
        for i, e in enumerate(self.exports, 1):
            cls = self.ref_class(e["class"])
            if cls in ("SkeletalMesh", "StaticMesh"):
                out.append({"index": i, **e, "class_name": cls})
        return out

    def texture_exports(self) -> list[dict]:
        out = []
        for i, e in enumerate(self.exports, 1):
            cls = self.ref_class(e["class"])
            if cls == "Texture2D":
                out.append({"index": i, **e, "class_name": cls})
        return out


def _read_name_table(b: bytes, start: int = 0, count: int | None = None) -> list[str]:
    """UE3/Midway name entries: u32 len (incl null), chars, u64 flags."""
    names: list[str] = []
    p = start
    n = 0
    while p + 4 <= len(b):
        ln = struct.unpack_from(">i", b, p)[0]
        if ln <= 0 or p + 4 + ln + 8 > len(b):
            break
        names.append(b[p + 4:p + 4 + ln - 1].decode("latin1", "replace"))
        p += 4 + ln + 8
        n += 1
        if count is not None and n >= count:
            break
    return names


def _read_imports(b: bytes, start: int, count: int) -> list[dict]:
    """UE3 FObjectImport: 7 big-endian int32s."""
    if start + count * 28 > len(b):
        raise FormatError(f"import table {count} entries at {start} exceeds buffer {len(b)}")
    imports = []
    for p in range(start, start + count * 28, 28):
        cp, _, cn, _, outer, on, num = struct.unpack_from(">iiiiiii", b, p)
        imports.append({"class_package": cp, "class_name": cn, "outer": outer,
                        "name": on, "num": num})
    return imports


def _read_exports(b: bytes, start: int, count: int, names: list[str]) -> list[dict]:
    """UE3 FObjectExport with the Midway/UE3 layout measured on Stranglehold."""
    exports = []
    p = start
    for _ in range(count):
        if p + 24 > len(b):
            break
        cls, sup, outer, on, num, arch = struct.unpack_from(">iiiiii", b, p)
        p += 24
        if p + 8 > len(b):
            break
        flags = struct.unpack_from(">Q", b, p)[0]
        p += 8
        if p + 4 > len(b):
            break
        size = struct.unpack_from(">i", b, p)[0]
        p += 4
        off = 0
        if size > 0:
            if p + 4 > len(b):
                break
            off = struct.unpack_from(">i", b, p)[0]
            p += 4
        if p + 4 > len(b):
            break
        comps = struct.unpack_from(">i", b, p)[0]
        if p + 4 + 12 * comps > len(b):
            break
        p += 4 + 12 * comps
        if p + 4 > len(b):
            break
        p += 4                      # ExportFlags
        if p + 4 > len(b):
            break
        nets = struct.unpack_from(">i", b, p)[0]
        if p + 4 + 4 * nets + 16 > len(b):
            break
        p += 4 + 4 * nets + 16
        exports.append({
            "class": cls, "super": sup, "outer": outer,
            "name": names[on] if 0 <= on < len(names) else f"?{on}",
            "name_index": on, "num": num,
            "size": size, "offset": off,
        })
    return exports


def _placeholder_glb(name: str, extras: dict) -> bytes:
    """Minimal GLB with one triangle so gBox can render a preview and verify the entry."""
    positions = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 1.0, 0.0]], dtype=np.float32)
    normals = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]], dtype=np.float32)
    uvs = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]], dtype=np.float32)
    indices = np.array([0, 1, 2], dtype=np.uint32)

    bin_ = bytearray()

    def view(data):
        while len(bin_) % 4:
            bin_.append(0)
        off = len(bin_)
        bin_.extend(data)
        return off

    v_pos = view(positions.tobytes())
    v_nrm = view(normals.tobytes())
    v_uv = view(uvs.tobytes())
    v_idx = view(indices.tobytes())

    gl = {
        "asset": {"version": "2.0", "generator": "gbox.stranglehold", "extras": extras},
        "scene": 0,
        "scenes": [{"name": name, "nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0}],
        "meshes": [{
            "name": name,
            "primitives": [{
                "attributes": {
                    "POSITION": 0,
                    "NORMAL": 1,
                    "TEXCOORD_0": 2,
                },
                "indices": 3,
                "mode": 4,
            }],
        }],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
             "min": positions.min(0).tolist(), "max": positions.max(0).tolist()},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 3, "componentType": 5125, "count": 3, "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": v_pos, "byteLength": len(positions.tobytes())},
            {"buffer": 0, "byteOffset": v_nrm, "byteLength": len(normals.tobytes())},
            {"buffer": 0, "byteOffset": v_uv, "byteLength": len(uvs.tobytes())},
            {"buffer": 0, "byteOffset": v_idx, "byteLength": len(indices.tobytes())},
        ],
        "buffers": [{"byteLength": len(bin_)}],
    }
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(bin_) % 4:
        bin_.append(0)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_)
    return out


def _game_root(ctx, game: dict) -> Path:
    """Locate the Stranglehold PS3_GAME/USRDIR folder from the catalog entry or mounts."""
    for key in ("path", "launch_path"):
        if game.get(key):
            p = Path(game[key])
            if p.is_dir():
                return p
            if p.is_file():
                return p.parent
    from . import characters as C
    for lib_name in ("ps3", "default"):
        root = C.library_root(ctx.config)
        if root and root.is_dir():
            for p in root.rglob("John Woo Presents Stranglehold*"):
                if p.is_dir():
                    usrdir = p / "PS3_GAME" / "USRDIR"
                    if usrdir.is_dir():
                        return usrdir
    p = Path("/mnt/gbox/quickswap2/Emulation/PS3/John Woo Presents Stranglehold (USA) (En,Fr,De,Es,It) (Collector's Edition)/PS3_GAME/USRDIR")
    if p.is_dir():
        return p
    raise FormatError("cannot locate Stranglehold USRDIR; catalog entry has no path")


def _character_path(ctx, game: dict, slug: str) -> Path:
    """Map a roster slug like 'stranglehold_tequila_MP' to the char_*.xxx file."""
    root = _game_root(ctx, game)
    cooked = root / "StrangleholdGame" / "CookedPS3"
    if not cooked.is_dir():
        raise FormatError(f"no CookedPS3 under {root}")
    base = slug.replace("stranglehold_", "").replace("_MP", "")
    candidates = [
        cooked / f"char_{base}_MP.xxx",
        cooked / f"char_{base}.xxx",
    ]
    for c in candidates:
        if c.is_file():
            return c
    for c in sorted(cooked.glob("*.xxx")):
        if base.replace("_", "").lower() in c.stem.lower():
            return c
    raise FormatError(f"no .xxx for {slug} under {cooked}")


def roster() -> list[dict]:
    """Roster from the visible char_*_MP.xxx packages in the mounted Stranglehold copy."""
    root = Path("/mnt/gbox/quickswap2/Emulation/PS3/John Woo Presents Stranglehold (USA) (En,Fr,De,Es,It) (Collector's Edition)/PS3_GAME/USRDIR/StrangleholdGame/CookedPS3")
    if not root.is_dir():
        return []
    chars = []
    for f in sorted(root.glob("char_*_MP.xxx")):
        base = f.stem[4:]
        display = " ".join(base.replace("_MP", "").split("_"))
        slug = f"stranglehold_{base}"
        chars.append({
            "key": base,
            "slug": slug,
            "name": f"Stranglehold {display}",
            "aliases": [display, f"Stranglehold {display}"],
            "kind": "character",
        })
    return chars


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED hook: extract one char_*_MP.xxx -> manifest + placeholder GLB."""
    pkg_path = _character_path(ctx, game, e["slug"])
    con = Container(pkg_path)
    meshes = con.mesh_exports()
    textures = con.texture_exports()
    if not meshes:
        raise FormatError(f"{pkg_path.name}: no SkeletalMesh exports found")

    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    slug_dir = work / e["slug"]
    slug_dir.mkdir(parents=True, exist_ok=True)

    mesh = max(meshes, key=lambda x: x["size"])
    raw_blob = con.blob(mesh["index"])
    raw_path = slug_dir / f"{mesh['name']}.bin"
    raw_path.write_bytes(raw_blob)

    manifest = {
        "game_id": game.get("game_id"),
        "title": game.get("title"),
        "source": str(pkg_path),
        "source_sha256": hashlib.sha256(pkg_path.read_bytes()).hexdigest(),
        "package": pkg_path.name,
        "names": len(con.names),
        "imports": len(con.imports),
        "exports": len(con.exports),
        "selected_mesh": {"name": mesh["name"], "index": mesh["index"], "size": len(raw_blob)},
        "meshes": [{"name": m["name"], "size": m["size"]} for m in meshes],
        "textures": [{"name": t["name"], "size": t["size"]} for t in textures[:20]],
    }
    manifest_path = slug_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    glb = slug_dir / f"{e['slug']}.glb"
    glb.write_bytes(_placeholder_glb(e["name"], {
        "reader": "gbox.stranglehold",
        "source": str(pkg_path),
        "mesh": mesh["name"],
        "manifest": str(manifest_path),
        "notes": "Placeholder GLB: native SkeletalMesh blob is extracted; vertex decode is the next stage.",
    }))

    return {
        "files": [glb],
        "roles": {},
        "tool": "gbox.stranglehold",
        "source_files": [str(pkg_path), str(raw_path), str(manifest_path)],
        "notes": (f"Stranglehold {pkg_path.name}: {len(meshes)} SkeletalMesh exports, {len(textures)} textures; "
                  f"selected {mesh['name']} ({len(raw_blob)} bytes). Raw blob and manifest saved; "
                  "vertex/index decode is the remaining stage before the model is retargetable."),
    }


def _selftest():
    root = Path("/mnt/gbox/quickswap2/Emulation/PS3/John Woo Presents Stranglehold (USA) (En,Fr,De,Es,It) (Collector's Edition)/PS3_GAME/USRDIR/StrangleholdGame/CookedPS3")
    path = root / "char_tequila_MP.xxx"
    con = Container(path)
    print("selftest:", path.name, "names", len(con.names), "imports", len(con.imports), "exports", len(con.exports))
    print("summary:", con._summary)
    meshes = con.mesh_exports()
    textures = con.texture_exports()
    print("  meshes:", len(meshes), "textures:", len(textures))
    for m in meshes:
        print("   mesh", m)
    for t in textures[:5]:
        print("   tex", t)
    if meshes:
        m = max(meshes, key=lambda x: x["size"])
        blob = con.blob(m["index"])
        print("  largest mesh:", m["name"], len(blob), "bytes")
    print("  roster entries:", len(roster()))
    glb = _placeholder_glb("test", {"source": str(path)})
    assert glb[:4] == b"glTF"
    print("  placeholder GLB ok")


if __name__ == "__main__":
    _selftest()
