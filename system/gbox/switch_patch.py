"""Reconstructing a base RomFS file from a BKTR patch: base bytes with the patched virtual ranges replaced.

A BKTR patch replaces *ranges* of the virtual RomFS space, not whole files (the RE6 update's 52 regions cut across
file boundaries), so an overlay build needs each affected file rebuilt as base bytes plus the patch's ranges. This
module is that recombination, independent of how the caller decrypts either side: it takes a `base_read(virtual,
size)` and a `patch_read(virtual, size)` and returns the file's new bytes plus the ranges that changed.

`patched_files` finds the files that need it: a file's virtual range is `romfs_offset + data_offset + offset` (the
address `hactool` seeks), and any patch region overlapping it makes the file a candidate.
"""
DEFAULT_CHUNK = 0x100000


def patched_files(files: list[dict], regions: list[dict], romfs_offset: int, data_offset: int) -> list[dict]:
    """Files whose virtual range overlaps a patch region: [{path, size, virtual, regions: [...]}]."""
    out = []
    for entry in files:
        if not entry.get("size"):
            continue
        start = romfs_offset + data_offset + entry["offset"]
        end = start + entry["size"]
        hits = [r for r in regions if r["virt"] < end and r["end"] > start]
        if hits:
            out.append({"path": entry["path"], "size": entry["size"], "virtual": start,
                        "regions": [{"virt": max(r["virt"], start), "end": min(r["end"], end),
                                     "region": r} for r in hits]})
    return out


def rebuild(base_read, patch_read, file: dict, chunk: int = DEFAULT_CHUNK) -> bytes:
    """The file's bytes with every intersection of its range replaced by the patch's read of that range."""
    start = file["virtual"]
    size = file["size"]
    out = bytearray()
    pieces = []
    cursor = start
    for hit in sorted(file["regions"], key=lambda h: h["virt"]):
        if hit["virt"] > cursor:
            pieces.append(("base", cursor, hit["virt"] - cursor))
        pieces.append(("patch", hit["virt"], hit["end"] - hit["virt"]))
        cursor = hit["end"]
    if cursor < start + size:
        pieces.append(("base", cursor, start + size - cursor))
    for kind, at, length in pieces:
        read = base_read if kind == "base" else patch_read
        pos = 0
        while pos < length:
            want = min(chunk, length - pos)
            data = read(at + pos, want)
            if len(data) != want:
                raise ValueError(f"{file['path']}: {kind} read at {at + pos:#x} returned {len(data)} of {want}")
            out += data
            pos += want
    return bytes(out)


def changed_ranges(file: dict) -> list[dict]:
    """The file's patched ranges as {offset, size} relative to the file (what a rebuild replaces)."""
    start = file["virtual"]
    return [{"offset": hit["virt"] - start, "size": hit["end"] - hit["virt"]} for hit in file["regions"]]
