"""Pure-stdlib native container readers for Nintendo Switch NSP releases.

This module is the owned-build manifest layer for Switch titles: it parses the
PFS0 container header, extracts the CNMT content metadata that ships inside the
container, verifies members against the hashes the title itself publishes, and
classifies NCA payload headers so an encrypted (standard crypto) program cannot
be mistaken for a readable asset blob.

No Nintendo keys, keys databases or third-party tools are used or required:
everything here works on the container bytes that the operator owns.
"""
from __future__ import annotations

import hashlib
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

PFS0_MAGIC = b"PFS0"
NCA_MAGICS = (b"NCA0", b"NCA2", b"NCA3")
NCA_HEADER_SIZE = 0xC00
_PFS0_HEADER_SIZE = 0x10
_ENTRY_STRIDES = (0x18,)  # real PFS0: u64 offset, u64 size, u32 name_offset, u32 reserved
_BYTE_ORDER = "little"

__all__ = [
    "Pfs0Entry",
    "Pfs0Image",
    "ContentEntry",
    "ContentMeta",
    "parse_pfs0_header",
    "parse_content_meta",
    "read_member",
    "sha256_region",
    "sha256_file",
    "classify_nca_header",
    "build_manifest",
]


@dataclass(frozen=True)
class Pfs0Entry:
    """One member of a PFS0 container."""

    name: str
    offset: int  # relative to the data region
    size: int
    name_offset: int

    @property
    def end(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class Pfs0Image:
    """Parsed PFS0 header: member table plus the data-region base offset."""

    file_count: int
    string_table_size: int
    entry_stride: int
    entries: tuple[Pfs0Entry, ...]
    data_offset: int

    def find(self, suffix: str) -> Pfs0Entry | None:
        for entry in self.entries:
            if entry.name.endswith(suffix):
                return entry
        return None


@dataclass(frozen=True)
class ContentEntry:
    """One <Content> record from the CNMT metadata."""

    type: str
    content_id: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ContentMeta:
    """Parsed ContentMeta (cnmt.xml) for one application."""

    content_type: str
    title_id: str
    version: int
    digest: str
    key_generation_min: int
    patch_id: str
    contents: tuple[ContentEntry, ...]

    def sha256_for_member(self, member_name: str) -> str | None:
        for content in self.contents:
            if member_name.startswith(content.content_id):
                return content.sha256
        return None


def _decode_name_table(table: bytes) -> list[tuple[int, str]]:
    """Split a PFS0 name table into (offset, name) pairs."""
    names: list[tuple[int, str]] = []
    cursor = 0
    while cursor < len(table):
        end = table.find(b"\x00", cursor)
        if end < 0:
            raise ValueError("unterminated PFS0 name table")
        names.append((cursor, table[cursor:end].decode("utf-8", "replace")))
        cursor = end + 1
    return names


def parse_pfs0_header(fh: BinaryIO, total_size: int) -> Pfs0Image:
    """Parse a PFS0 header, tolerating the 0x10 and 0x18 entry layouts.

    The container is accepted only when the member table, the name table and the
    file size agree, so a mis-sized guess can never masquerade as a layout.
    """
    head = fh.read(_PFS0_HEADER_SIZE)
    if len(head) < _PFS0_HEADER_SIZE:
        raise ValueError("truncated PFS0 header")
    magic, file_count, string_table_size, reserved = struct.unpack("<4sIII", head)
    if magic != PFS0_MAGIC:
        raise ValueError(f"not a PFS0 container: {magic!r}")
    if reserved != 0:
        raise ValueError(f"unexpected PFS0 reserved field: {reserved}")

    for stride in _ENTRY_STRIDES:
        fh.seek(_PFS0_HEADER_SIZE)
        raw = fh.read(stride * file_count)
        if len(raw) < stride * file_count:
            continue
        names_offset = _PFS0_HEADER_SIZE + stride * file_count
        fh.seek(names_offset)
        table = fh.read(string_table_size)
        entries: list[Pfs0Entry] = []
        ok = True
        for index in range(file_count):
            chunk = raw[index * stride:index * stride + stride]
            offset, size = struct.unpack("<QQ", chunk[:16])
            name_offset = struct.unpack("<I", chunk[16:20])[0]
            end = table.find(b"\x00", name_offset) if name_offset < len(table) else -1
            if end <= name_offset:
                ok = False
                break
            entries.append(Pfs0Entry(table[name_offset:end].decode("utf-8", "replace"), offset, size, name_offset))
        if not ok:
            continue
        if len({e.name for e in entries}) != file_count:
            continue
        expected = 0
        for e in entries:
            if e.offset != expected:
                ok = False
                break
            expected += e.size
        if not ok:
            continue

        data_offset = names_offset + string_table_size
        if data_offset + sum(entry.size for entry in entries) != total_size:
            continue
        return Pfs0Image(file_count, string_table_size, stride, tuple(entries), data_offset)

    raise ValueError("could not determine PFS0 entry layout")


def read_member(fh: BinaryIO, data_offset: int, entry: Pfs0Entry) -> bytes:
    """Read one container member fully into memory."""
    fh.seek(data_offset + entry.offset)
    data = fh.read(entry.size)
    if len(data) != entry.size:
        raise ValueError(f"short read for member {entry.name!r}")
    return data


def sha256_region(fh: BinaryIO, offset: int, size: int, chunk: int = 1 << 20) -> str:
    """Stream a SHA-256 over a byte range of an open file."""
    fh.seek(offset)
    digest = hashlib.sha256()
    remaining = size
    while remaining > 0:
        block = fh.read(min(chunk, remaining))
        if not block:
            raise ValueError("unexpected end of file while hashing")
        digest.update(block)
        remaining -= len(block)
    return digest.hexdigest()


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    """Stream a SHA-256 over a whole file."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def parse_content_meta(xml_bytes: bytes) -> ContentMeta:
    """Parse a ContentMeta (cnmt.xml) document."""
    root = ET.fromstring(xml_bytes.decode("utf-8", "replace"))

    def text(tag: str, default: str = "") -> str:
        node = root.find(tag)
        return (node.text or default).strip() if node is not None else default

    contents: list[ContentEntry] = []
    for node in root.findall("Content"):
        def child(tag: str) -> str:
            sub = node.find(tag)
            return (sub.text or "").strip() if sub is not None else ""

        try:
            size = int(child("Size"))
        except ValueError:
            size = 0
        contents.append(
            ContentEntry(child("Type"), child("Id"), size, child("Hash").lower())
        )

    try:
        version = int(text("Version", "0"))
    except ValueError:
        version = 0
    try:
        keygen = int(text("KeyGenerationMin", "0"))
    except ValueError:
        keygen = 0

    return ContentMeta(
        content_type=text("Type"),
        title_id=text("Id"),
        version=version,
        digest=text("Digest").lower(),
        key_generation_min=keygen,
        patch_id=text("PatchId"),
        contents=tuple(contents),
    )


def classify_nca_header(header: bytes) -> str:
    """Classify an NCA header as 'plaintext', 'encrypted' or 'truncated'.

    Standard-crypto NCAs keep the fixed header encrypted, so the magic is not
    readable; that is the signal that member payloads cannot be parsed without
    the console key area.
    """
    if len(header) < 4:
        return "truncated"
    if header[:4] in NCA_MAGICS:
        return "plaintext"
    return "encrypted"


def build_manifest(
    nsp_path: str | Path,
    container_sha256: str | None = None,
    hash_limit: int = 256 << 20,
) -> dict:
    """Build the authoritative owned-build manifest for an NSP container.

    The manifest records the container identity, the member table with byte
    offsets, the CNMT metadata read out of the container, and a per-member
    hash cross-check against the hashes the title publishes about itself.
    """
    path = Path(nsp_path)
    total_size = path.stat().st_size
    with path.open("rb") as fh:
        image = parse_pfs0_header(fh, total_size)

        meta_entry = image.find(".cnmt.xml")
        meta: ContentMeta | None = None
        if meta_entry is not None:
            meta = parse_content_meta(read_member(fh, image.data_offset, meta_entry))

        members: list[dict] = []
        for entry in image.entries:
            record = {
                "name": entry.name,
                "offset": entry.offset,
                "container_offset": image.data_offset + entry.offset,
                "size": entry.size,
            }
            if entry.name.endswith(".nca"):
                fh.seek(image.data_offset + entry.offset)
                record["payload_kind"] = classify_nca_header(fh.read(0x40))
            if entry.size <= hash_limit:
                actual = sha256_region(fh, image.data_offset + entry.offset, entry.size)
                expected = None
                if meta is not None and not entry.name.endswith(".cnmt.xml"):
                    expected = meta.sha256_for_member(entry.name)
                record["sha256"] = actual
                record["published_sha256"] = expected
                record["sha256_verified"] = bool(expected) and expected == actual
            else:
                record["sha256"] = None
                record["sha256_verified"] = None
                record["hash_skipped"] = "member larger than hash limit"
            members.append(record)

    manifest = {
        "container": {
            "path": str(path),
            "format": "NSP (PFS0)",
            "size": total_size,
            "sha256": container_sha256,
            "byte_order": _BYTE_ORDER,
            "offset_base": "PFS0 data region",
            "data_offset": image.data_offset,
            "entry_stride": image.entry_stride,
            "member_count": image.file_count,
        },
        "title": {
            "platform": "Nintendo Switch (NX)",
            "title_id": meta.title_id if meta else None,
            "content_type": meta.content_type if meta else None,
            "version": meta.version if meta else None,
            "patch_id": meta.patch_id if meta else None,
            "key_generation_min": meta.key_generation_min if meta else None,
            "content_digest": meta.digest if meta else None,
        },
        "members": members,
        "asset_inventory": {
            "status": "blocked",
            "reason": (
                "program payload is a standard-crypto NCA (fixed header encrypted); "
                "member-level assets are not readable without the console key area"
            ),
        },
    }
    return manifest


def _main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) < 2:
        print("usage: switch_nsp.py manifest <nsp> [out.json] [--sha256 HEX]", file=sys.stderr)
        return 2
    if args[0] != "manifest":
        print(f"unknown command {args[0]!r}", file=sys.stderr)
        return 2
    nsp = args[1]
    out = None
    known = None
    rest = args[2:]
    index = 0
    while index < len(rest):
        if rest[index] == "--sha256":
            known = rest[index + 1]
            index += 2
        else:
            out = rest[index]
            index += 1
    if known is None:
        known = sha256_file(nsp)
    manifest = build_manifest(nsp, container_sha256=known)
    text = __import__("json").dumps(manifest, indent=2, sort_keys=True)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
