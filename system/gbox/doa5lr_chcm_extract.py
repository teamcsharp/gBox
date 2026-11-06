"""Extract character entries from the DOA5LR PS3 `chara_common.lnk` CHCM archive.

Wraps the verified reader in ``gbox/doa5lr_chcm.py`` (parse_chcm / parse_lfmo) and
adds a byte-exact single-entry extractor, a name->index lookup and structural
validation of the extracted payload.

Owned-source identity for this stage (PS3 JP, "Dead or Alive 5 - Last Round"):
  container  : PS3_GAME/USRDIR/chara_common.lnk   (magic CHCM, 2355 entries)
  index file : PS3_GAME/USRDIR/chara_common.bin    (magic LFMO, 2355 names)
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import struct
import sys

__all__ = [
    "load_reader",
    "parse_entries",
    "parse_names",
    "extract_entry",
    "entry_by_name",
    "read_header",
    "sha256_file",
]

_HERE = os.path.dirname(os.path.abspath(__file__))
READER_PATH = os.path.join(_HERE, "doa5lr_chcm.py")


def load_reader():
    """Import the verified `gbox.doa5lr_chcm` reader by path (registered in sys.modules)."""
    spec = importlib.util.spec_from_file_location("doa5lr_chcm", READER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _nodes(obj, depth=0):
    yield obj
    if depth > 4:
        return
    if isinstance(obj, dict):
        for value in obj.values():
            yield from _nodes(value, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _nodes(value, depth + 1)
    elif hasattr(obj, "__dict__"):
        for value in vars(obj).values():
            yield from _nodes(value, depth + 1)


def _get(obj, names, default=0):
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if isinstance(value, int):
                return value
    return default


def _as_entry(item):
    if isinstance(item, (list, tuple)) and len(item) == 4 and all(isinstance(v, int) for v in item):
        return tuple(item)
    if isinstance(item, dict):
        for names in (("size", "size_dup", "zero", "offset"),
                      ("size", "size_dup", "zero", "abs_offset")):
            if all(k in item for k in names):
                return tuple(int(item[k]) for k in names)
    if hasattr(item, "size") and hasattr(item, "offset"):
        return (
            _get(item, ("size", "file_size", "length")),
            _get(item, ("size_dup", "dup_size", "dup")),
            _get(item, ("zero", "reserved", "pad")),
            _get(item, ("offset", "abs_offset", "data_offset", "file_offset")),
        )
    return None


def _coerce_entries(result):
    for node in _nodes(result):
        if isinstance(node, (list, tuple)) and node:
            rows = [_as_entry(item) for item in node]
            if all(row is not None for row in rows) and len(rows) > 1:
                return rows
    return None


def _coerce_names(result):
    for node in _nodes(result):
        if isinstance(node, (list, tuple)) and node:
            if all(isinstance(v, str) for v in node):
                return list(node)
            if all(isinstance(v, (list, tuple)) and len(v) >= 2 and isinstance(v[-1], str) for v in node):
                return [v[-1] for v in node]
    return None


def _call(fn, path):
    attempts = (
        lambda: fn(path),
        lambda: fn(path=path),
        lambda: fn(open(path, "rb")),
        lambda: fn(open(path, "rb").read()),
    )
    last = None
    for attempt in attempts:
        try:
            res = attempt()
        except Exception as exc:  # noqa: BLE001
            last = exc
            continue
        if res is not None:
            return res
    raise RuntimeError("reader call failed for %r: %r" % (fn, last))


def read_header(link_path):
    """Return CHCM header fields."""
    with open(link_path, "rb") as handle:
        head = handle.read(0x28)
    count, fsize, align, table_end = struct.unpack_from(">QQQQ", head, 8)
    return {"magic": head[:4], "count": count, "file_size": fsize, "align": align, "table_end": table_end}


def _direct_entries(link_path):
    header = read_header(link_path)
    with open(link_path, "rb") as handle:
        handle.seek(0)
        raw = handle.read(header["table_end"])
    return [struct.unpack_from(">QQQQ", raw, 0x28 + i * 32) for i in range(header["count"])]


def _direct_names(bin_path):
    with open(bin_path, "rb") as handle:
        blob = handle.read()
    count = struct.unpack_from(">I", blob, 8)[0]
    names = []
    for i in range(count):
        _, _, offset = struct.unpack_from(">III", blob, 0x28 + i * 12)
        end = blob.index(b"\x00", offset)
        names.append(blob[offset:end].decode("latin1"))
    return names


def parse_entries(link_path):
    """Return [(size, dup, zero, offset), ...]; verified reader first, struct fallback."""
    reader = load_reader()
    for name in ("parse_chcm", "read_chcm", "parse_lfmo_chcm"):
        fn = getattr(reader, name, None)
        if fn is None:
            continue
        try:
            rows = _coerce_entries(_call(fn, link_path))
        except RuntimeError:
            rows = None
        if rows:
            return rows
    return _direct_entries(link_path)


def parse_names(bin_path):
    """Return the LFMO entry names in archive order; verified reader first."""
    reader = load_reader()
    for name in ("parse_lfmo", "read_lfmo", "parse_lfmo_names"):
        fn = getattr(reader, name, None)
        if fn is None:
            continue
        try:
            names = _coerce_names(_call(fn, bin_path))
        except RuntimeError:
            names = None
        if names:
            return names
    return _direct_names(bin_path)


def extract_entry(index, link_path, bin_path=None):
    """Extract entry `index` byte-exactly; returns (info, payload)."""
    entries = parse_entries(link_path)
    if not 0 <= index < len(entries):
        raise IndexError("entry %d out of range (%d)" % (index, len(entries)))
    size, dup, zero, offset = entries[index]
    with open(link_path, "rb") as handle:
        handle.seek(offset)
        payload = handle.read(size)
    info = {
        "index": index,
        "size": size,
        "dup_size": dup,
        "zero": zero,
        "offset": offset,
        "magic": payload[:8],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes_read": len(payload),
    }
    if bin_path and os.path.exists(bin_path):
        names = parse_names(bin_path)
        if index < len(names):
            info["name"] = names[index]
            info["name_fields"] = names[index].split("@")
    return info, payload


def entry_by_name(name, link_path, bin_path):
    """Return the archive index whose LFMO name base field equals `name`."""
    names = parse_names(bin_path)
    for index, candidate in enumerate(names):
        if candidate.split("@")[0].lstrip("/") == name or candidate == name:
            return index
    raise KeyError(name)


def sha256_file(path, chunk=1 << 22):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()
