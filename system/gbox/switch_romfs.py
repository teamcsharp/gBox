"""RomFS reading for NCAs: the header, the directory and file tables, and the path -> (offset, size) map.

Verified against the RE6 base NSP (18.8 GB program NCA): the RomFS sits after the IVFC hash levels (level 5's logical
offset, 0x22f8000 for that title), its ten-u64 header points at the hash/meta tables *relative to the RomFS header*,
and the tree walks to 60,645 files under `nativeNXx64/`. The base ExeFS of the same NCA decrypts to `PFS0` with the
same title key, so the two readers share `switch_nca`'s key handling.

The reader works on a caller-provided `read_virtual(offset, size)` (offset relative to the NCA's RomFS section, the
caller decrypting), so it also serves an in-memory NCA, a slice of an NSP, or an already-decrypted dump.
"""
import struct

EMPTY = 0xFFFFFFFF
HEADER_SIZE = 0x50


def parse_header(blob: bytes) -> dict:
    """The RomFS header's ten u64 fields (all offsets relative to the RomFS header itself)."""
    if len(blob) < HEADER_SIZE:
        raise ValueError(f"a RomFS header is {HEADER_SIZE:#x} bytes, got {len(blob)}")
    fields = struct.unpack("<10Q", blob[:HEADER_SIZE])
    if fields[0] != HEADER_SIZE:
        raise ValueError(f"not a RomFS header (header_size {fields[0]:#x})")
    return {"header_size": fields[0], "dir_hash_offset": fields[1], "dir_hash_size": fields[2],
            "dir_meta_offset": fields[3], "dir_meta_size": fields[4], "file_hash_offset": fields[5],
            "file_hash_size": fields[6], "file_meta_offset": fields[7], "file_meta_size": fields[8],
            "data_offset": fields[9]}


def _dir_entry(table: bytes, offset: int):
    parent, sibling, child, file, _hash, name_size = struct.unpack_from("<6I", table, offset)
    name = table[offset + 0x18:offset + 0x18 + name_size].decode("utf-8", "replace")
    return parent, sibling, child, file, name


def _file_entry(table: bytes, offset: int):
    parent, sibling = struct.unpack_from("<II", table, offset)
    file_offset, size = struct.unpack_from("<QQ", table, offset + 8)
    _hash, name_size = struct.unpack_from("<II", table, offset + 0x18)
    name = table[offset + 0x20:offset + 0x20 + name_size].decode("utf-8", "replace")
    return parent, sibling, file_offset, size, name


def walk(directories: bytes, files: bytes) -> list[dict]:
    """Every file as {path, offset, size}; `offset` is relative to the RomFS data area (add the header's data_offset)."""
    out: list[dict] = []
    seen: set[int] = set()

    def visit_files(offset: int, prefix: str) -> None:
        guard = 0
        while offset != EMPTY and guard < 1_000_000:
            _parent, sibling, file_offset, size, name = _file_entry(files, offset)
            out.append({"path": prefix + name, "offset": file_offset, "size": size})
            offset = sibling
            guard += 1

    def visit_dir(offset: int, prefix: str, depth: int) -> None:
        if depth > 64 or offset in seen or len(seen) > 1_000_000:
            return
        seen.add(offset)
        _parent, sibling, child, file, name = _dir_entry(directories, offset)
        here = prefix + (name + "/" if name else "")
        if file != EMPTY:
            visit_files(file, here)
        if child != EMPTY:
            visit_dir(child, here, depth + 1)
        if sibling != EMPTY:
            visit_dir(sibling, prefix, depth)

    visit_dir(0, "", 0)
    return out


def read(read_virtual, header_offset: int) -> dict:
    """The RomFS at `header_offset` of a section, through `read_virtual(offset, size)`: header + files."""
    header = parse_header(read_virtual(header_offset, HEADER_SIZE))
    directories = read_virtual(header_offset + header["dir_meta_offset"], header["dir_meta_size"])
    files = read_virtual(header_offset + header["file_meta_offset"], header["file_meta_size"])
    return {"header": header, "files": walk(directories, files)}
