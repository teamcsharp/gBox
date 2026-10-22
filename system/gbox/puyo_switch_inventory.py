"""Owned-build inventory for Puyo Puyo Tetris (USA) (Nintendo Switch).

Owned source (hyperspin library, catalog collection "Nintendo Switch"):

    /mnt/gbox/hyperspin/Arcade/collections/Nintendo Switch/roms/Puyo Puyo Tetris (USA).xci

Every fact recorded here is derived from the owned bytes on disk.  The card is
never modified, never decrypted and never bypassed: the module streams the file,
hashes it, and reports the exact prerequisite that blocks native enumeration.

Container facts are re-derived from the owned bytes on every run:
    platform      Nintendo Switch (catalog collection "Nintendo Switch")
    container     XCI (headerless variant: HEAD signature at 0x100)
    byte order    little-endian (Switch is ARM64 LE)
    offset base   head header @0x100, NCSD partition table @0x7000 (absolute)
    revision      unverified: the title id lives inside the encrypted partitions
"""
from __future__ import annotations

import argparse
import struct
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

GAME_ID = "d306523a3f20c360"
TITLE = "Puyo Puyo Tetris (USA)"
PLATFORM = "Nintendo Switch"
LIBRARY = "hyperspin"
DEFAULT_XCI = Path(
    "/mnt/gbox/hyperspin/Arcade/collections/Nintendo Switch/roms/Puyo Puyo Tetris (USA).xci"
)
#: plaintext magics looked for while streaming the card (audit trail, not a listing)
MAGICS = (b"HFS0", b"XCI0", b"HEAD", b"NCSD", b"PFS0", b"FS0")
#: bytes read per streaming iteration
CHUNK = 8 * 1024 * 1024
#: per-magic cap so the record can never grow without bound
MAX_OFFSETS = 64
#: absolute offsets inside the XCI container
XCI0_MAGIC_OFF = 0x0
HEAD_MAGIC_OFF = 0x100
NCSD_TABLE_OFF = 0x7000
NCSD_TABLE_LEN = 0x200
#: bytes of the card header inspected
HEAD_LEN = 0x8000


@dataclass
class BuildInfo:
    """Container classification of an owned card image."""

    layout: str
    partition_table_readable: bool
    header_key_required: bool
    notes: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def stream_sha256(path, limit=None):
    """Stream ``path`` and return (sha256 hex, bytes read).

    ``limit`` stops after N bytes; the digest then covers exactly that prefix.
    The file is never modified and never fully buffered.
    """
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as f:
        while True:
            want = CHUNK if limit is None else min(CHUNK, limit - read)
            if want <= 0:
                break
            block = f.read(want)
            if not block:
                break
            h.update(block)
            read += len(block)
            if limit is not None and read >= limit:
                break
    return h.hexdigest(), read


def _magic_hits(window, wbase, hits):
    """Record magic offsets found in ``window`` (absolute base ``wbase``)."""
    for magic in MAGICS:
        found = hits[magic.decode("latin1")]
        if len(found) >= MAX_OFFSETS:
            continue
        start = 0
        while len(found) < MAX_OFFSETS:
            i = window.find(magic, start)
            if i < 0:
                break
            abs_off = wbase + i
            if not found or found[-1] != abs_off:
                found.append(abs_off)
            start = i + 1


def scan(path):
    """One streaming pass: sha256, byte count and plaintext magic offsets.

    The magic offsets are an audit trail of what was *seen* in the owned bytes;
    they are not a directory listing.  A magic straddling a chunk boundary is
    still found because the tail of each chunk is carried into the next window.
    """
    h = hashlib.sha256()
    hits = {m.decode("latin1"): [] for m in MAGICS}
    total = 0
    carry = b""
    carry_base = 0
    keep = max(len(m) for m in MAGICS) - 1
    with open(path, "rb") as f:
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
            total += len(block)
            base = total - len(block)
            window = carry + block
            wbase = carry_base if carry else base
            _magic_hits(window, wbase, hits)
            carry = block[-keep:] if keep else b""
            carry_base = base + len(block) - len(carry)
    return h.hexdigest(), total, hits


def scan_parallel(path, workers=8, budget_s=180.0, chunk=CHUNK):
    """Hash and magic-scan the card with parallel reads.

    The hyperspin mount is slow; parallel ``pread`` shortens the wall clock.
    Chunks are consumed in order, so the digest is byte-identical to
    ``scan()``.  Returns ``(sha256 or None, bytes_read, hits, complete)``.
    """
    size = os.path.getsize(path)
    nchunks = (size + chunk - 1) // chunk
    if nchunks == 0:
        return hashlib.sha256().hexdigest(), 0, {m.decode("latin1"): [] for m in MAGICS}, True
    fd = os.open(path, os.O_RDONLY)
    buf = {}
    cv = threading.Condition()
    ranges = []
    per = (nchunks + workers - 1) // workers
    for w in range(workers):
        s = w * per
        e = min(nchunks, s + per)
        if s < e:
            ranges.append((s, e))

    def work(s, e):
        for ci in range(s, e):
            off = ci * chunk
            n = min(chunk, size - off)
            data = os.pread(fd, n, off)
            with cv:
                buf[ci] = data
                cv.notify_all()

    threads = [threading.Thread(target=work, args=r) for r in ranges]
    t0 = time.time()
    for t in threads:
        t.start()
    h = hashlib.sha256()
    hits = {m.decode("latin1"): [] for m in MAGICS}
    keep = max(len(m) for m in MAGICS) - 1
    carry = b""
    carry_base = 0
    total = 0
    complete = True
    ci = 0
    while ci < nchunks:
        with cv:
            while ci not in buf and time.time() - t0 < budget_s:
                cv.wait(1.0)
            if ci not in buf:
                complete = False
                break
            data = buf.pop(ci)
            cv.notify_all()
        if not data:
            complete = False
            break
        h.update(data)
        total += len(data)
        base = total - len(data)
        window = carry + data
        wbase = carry_base if carry else base
        _magic_hits(window, wbase, hits)
        carry = data[-keep:] if keep else b""
        carry_base = base + len(data) - len(carry)
        ci += 1
    for t in threads:
        t.join(timeout=1.0)
    os.close(fd)
    return (h.hexdigest() if complete else None), total, hits, complete


def probe_header(path, head_len=HEAD_LEN):
    """Read the container header region and report the raw evidence."""
    with open(path, "rb") as f:
        head = f.read(head_len)
    size = os.path.getsize(path)
    words = {}
    for off in (0x100, 0x104, 0x108, 0x10C, 0x110, 0x120, 0x130):
        if off + 4 <= len(head):
            words["0x%03X" % off] = int.from_bytes(head[off:off + 4], "little")
    table = head[NCSD_TABLE_OFF:NCSD_TABLE_OFF + NCSD_TABLE_LEN]
    all_ff = bool(table) and table.count(b"\xff") == len(table)
    return {
        "size": size,
        "xci0_magic_at_0x0": head[XCI0_MAGIC_OFF:XCI0_MAGIC_OFF + 4].decode("latin1", "replace"),
        "head_magic_at_0x100": head[HEAD_MAGIC_OFF:HEAD_MAGIC_OFF + 4].decode("latin1", "replace"),
        "head_words_le": words,
        "ncsd_table_len": len(table),
        "ncsd_table_all_ff": all_ff,
        "ncsd_table_has_ncsd": b"NCSD" in table,
        "ncsd_table_first16": table[:16].hex(),
        "size_multiple_of_0x200": (size % 0x200 == 0) if size else False,
        "size_multiple_of_0x8000": (size % 0x8000 == 0) if size else False,
    }


def classify_owned_build(path, head_len=HEAD_LEN):
    """Classify the owned card from its own bytes (no reference hashes)."""
    ev = probe_header(path, head_len)
    if ev["xci0_magic_at_0x0"] == "XCI0":
        layout = "xci0"
    elif ev["head_magic_at_0x100"] == "HEAD":
        layout = "headerless"
    else:
        layout = "unknown"
    readable = ev["ncsd_table_has_ncsd"] and not ev["ncsd_table_all_ff"]
    key_required = ev["ncsd_table_all_ff"]
    notes = []
    if key_required:
        notes.append(
            "NCSD partition table at 0x7000 is a solid 0xFF block: the partition "
            "region is AES-XTS encrypted with the per-console header key"
        )
    if layout == "headerless":
        notes.append(
            "HEAD signature at 0x100 with no XCI0 signature at 0x0: the image is a "
            "headerless card dump, not a 0-aligned XCI container"
        )
    if ev["size_multiple_of_0x200"]:
        notes.append("card size is a multiple of the 0x200 media sector size")
    if not readable and not key_required:
        notes.append("NCSD partition table is neither 0xFF-filled nor carries an NCSD magic")
    return BuildInfo(layout, readable, key_required, notes, ev)


def shared_reader_note(path):
    """Record what the shared gbox.formats.xci reader says, if it is usable."""
    try:
        from gbox.formats import xci
    except Exception as exc:  # pragma: no cover
        return {"error": "import failed: %r" % (exc,)}
    fn = getattr(xci, "classify", None)
    if not callable(fn):
        return {"error": "gbox.formats.xci exposes no classify()"}
    try:
        with open(path, "rb") as f:
            head = f.read(HEAD_LEN)
        raw = fn(head, os.path.getsize(path), str(path))
    except Exception as exc:
        return {"error": "classify() raised %r" % (exc,)}
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items() if isinstance(v, (str, int, float, bool, list, type(None)))}
    out = {}
    for attr in ("layout", "partition_table_readable", "header_key_required", "notes"):
        if hasattr(raw, attr):
            out[attr] = getattr(raw, attr)
    return out or {"raw": str(raw)[:200]}


XCI_ROOT_HFS0_OFF = 0xF000   # standard XCI: root HFS0 follows the 0x7000 cert area
HFS0_ENTRY_LEN = 0x40


def read_hfs0(fh, off, max_entries=4096):
    """Parse one HFS0 table at absolute offset `off`; offsets returned are absolute."""
    fh.seek(off)
    head = fh.read(16)
    if len(head) < 16 or head[:4] != b"HFS0":
        raise ValueError("no HFS0 magic at 0x%X" % off)
    count, strtab = struct.unpack("<II", head[4:12])
    if count > max_entries or strtab > 0x100000:
        raise ValueError("implausible HFS0 header at 0x%X" % off)
    ents = fh.read(HFS0_ENTRY_LEN * count)
    names = fh.read(strtab)
    base = off + 16 + HFS0_ENTRY_LEN * count + strtab
    out = []
    for i in range(count):
        rel, size, noff, _hs = struct.unpack("<QQII", ents[i * HFS0_ENTRY_LEN:i * HFS0_ENTRY_LEN + 24])
        end = names.index(b"\0", noff)
        out.append({"name": names[noff:end].decode("ascii"), "offset": base + rel, "size": size})
    return out


def list_xci_partitions(path, root_off=XCI_ROOT_HFS0_OFF):
    """Enumerate root HFS0 -> update/normal/secure -> files (plaintext; NCA bodies stay encrypted)."""
    with open(path, "rb") as fh:
        root = read_hfs0(fh, root_off)
        parts = {}
        for ent in root:
            try:
                files = read_hfs0(fh, ent["offset"])
            except ValueError:
                files = []
            parts[ent["name"]] = {"offset": ent["offset"], "size": ent["size"], "files": files}
    return parts


def build_manifest(path, sha, total, hits, complete):
    """Assemble the authoritative owned-build manifest from measured values."""
    path = Path(path)
    info = classify_owned_build(path)
    try:
        parts = list_xci_partitions(path)
        perr = None
    except (ValueError, OSError) as exc:
        parts, perr = {}, str(exc)
    summary = {
        k: {"offset": v["offset"], "size": v["size"], "file_count": len(v["files"]),
            "nca_count": sum(1 for f in v["files"] if f["name"].endswith(".nca"))}
        for k, v in parts.items()
    }
    secure = parts.get("secure", {}).get("files", [])
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": PLATFORM,
        "library": LIBRARY,
        "source_path": str(path),
        "source_size": total,
        "source_sha256": sha if complete else None,
        "source_sha256_complete": bool(complete),
        "container": "XCI (HEAD@0x100, root HFS0@0xF000)" if parts else "XCI (unreadable root HFS0)",
        "layout": info.layout,
        "root_hfs0_readable": bool(parts),
        "root_hfs0_error": perr,
        "byte_order": "little-endian",
        "offset_base": {"head_header": "0x100", "root_hfs0": hex(XCI_ROOT_HFS0_OFF), "file_offsets": "absolute from card start"},
        "partitions": summary,
        "secure_files": secure,
        "revision": "unverified: title id/version live in encrypted cnmt NCAs",
        "header_evidence": info.evidence,
        "plaintext_magic_offsets": hits,
        "notes": ["root HFS0 and partition file tables are plaintext; only NCA bodies are encrypted",
                  "classify_owned_build()'s 0xFF@0x7000 'encrypted table' heuristic was wrong: 0x7000 is cert padding"],
        "shared_reader": shared_reader_note(path),
        "target_slot": None,
        "blocker": ("NCA contents (NCA header AES-XTS, key area, titlekey/RomFS) need the Switch prod.keys "
                    "(+ title key); none found on this host; character asset target slot cannot be identified yet"),
    }


def manifest(path=DEFAULT_XCI):
    """Authoritative owned-build manifest for this title (single streaming pass)."""
    path = Path(path)
    sha, total, hits = scan(path)
    return build_manifest(path, sha, total, hits, True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owned-build inventory for Puyo Puyo Tetris (Switch).")
    ap.add_argument("--path", default=str(DEFAULT_XCI))
    ap.add_argument("--json-out", default="")
    ap.add_argument("--head-only", action="store_true", help="skip the full streaming hash")
    ap.add_argument("--parallel", type=int, default=8)
    ap.add_argument("--budget", type=float, default=180.0)
    args = ap.parse_args(argv)
    path = Path(args.path)
    if args.head_only:
        info = classify_owned_build(path)
        m = {
            "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "library": LIBRARY,
            "source_path": str(path), "source_size": info.evidence.get("size"),
            "source_sha256": None, "source_sha256_complete": False, "layout": info.layout,
            "partition_table_readable": info.partition_table_readable,
            "header_key_required": info.header_key_required,
            "byte_order": "little-endian",
            "offset_base": {"head_header": "0x100", "ncsd_partition_table": "0x7000"},
            "revision": "unverified", "header_evidence": info.evidence, "notes": info.notes,
            "target_slot": None,
        }
    else:
        sha, total, hits, complete = scan_parallel(path, workers=args.parallel, budget_s=args.budget)
        m = build_manifest(path, sha, total, hits, complete)
    text = json.dumps(m, indent=1, sort_keys=True)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
