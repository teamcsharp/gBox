"""Focused tests for the Nintendo Switch NSP/PFS0 owned-build manifest layer.

Runs with plain `python3 tests/test_switch_nsp.py` (no pytest required) and is
also collected by pytest.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import struct
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODULE_PATH = os.path.join(_ROOT, "gbox", "switch_nsp.py")

_spec = importlib.util.spec_from_file_location("switch_nsp", _MODULE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load {_MODULE_PATH}")
switch_nsp = importlib.util.module_from_spec(_spec)
sys.modules["switch_nsp"] = switch_nsp
_spec.loader.exec_module(switch_nsp)


def _build_pfs0(members, stride=0x18):
    """Build a synthetic PFS0 container from (name, payload) pairs."""
    name_table = b""
    name_offsets = []
    for name, _payload in members:
        name_offsets.append(len(name_table))
        name_table += name.encode("utf-8") + b"\x00"
    header = struct.pack("<4sIII", b"PFS0", len(members), len(name_table), 0)
    entries = b""
    offset = 0
    payloads = b""
    for index, (_name, payload) in enumerate(members):
        if stride == 0x18:
            entries += struct.pack("<QQQ", offset, len(payload), name_offsets[index])
        else:
            entries += struct.pack("<QQ", offset, len(payload))
        offset += len(payload)
        payloads += payload
    return header + entries + name_table + payloads


def test_parse_pfs0_header_18byte_entries():
    members = [("a.cnmt.xml", b"meta"), ("b.nca", b"\x00" * 32)]
    blob = _build_pfs0(members, stride=0x18)
    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(blob)
        path = fh.name
    try:
        with open(path, "rb") as handle:
            image = switch_nsp.parse_pfs0_header(handle, len(blob))
        assert image.file_count == 2
        assert image.entry_stride == 0x18
        assert [e.name for e in image.entries] == ["a.cnmt.xml", "b.nca"]
        assert image.entries[0].size == 4
        with open(path, "rb") as handle:
            payload = switch_nsp.read_member(handle, image.data_offset, image.entries[0])
        assert payload == b"meta"
    finally:
        os.unlink(path)


def test_parse_pfs0_header_padded_name_table():
    """Real NSPs pad the name table with NULs (regression for Paper Mario NSP)."""
    members = [("only.nca", b"\x01" * 16), ("z.tik", b"\x02" * 8)]
    blob = _build_pfs0(members, stride=0x18)
    names_len = struct.unpack("<I", blob[8:12])[0]
    pad = 12
    blob = blob[:8] + struct.pack("<I", names_len + pad) + blob[12:16] \
        + blob[16:16 + 0x18 * 2 + names_len] + b"\x00" * pad + blob[16 + 0x18 * 2 + names_len:]
    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(blob)
        path = fh.name
    try:
        with open(path, "rb") as handle:
            image = switch_nsp.parse_pfs0_header(handle, len(blob))
        assert [e.name for e in image.entries] == ["only.nca", "z.tik"]
    finally:
        os.unlink(path)


def test_parse_pfs0_header_rejects_non_pfs0():
    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(b"NOTPFS0" + b"\x00" * 64)
        path = fh.name
    try:
        with open(path, "rb") as handle:
            try:
                switch_nsp.parse_pfs0_header(handle, 72)
            except ValueError as exc:
                assert "not a PFS0" in str(exc)
            else:
                raise AssertionError("expected ValueError for non-PFS0 data")
    finally:
        os.unlink(path)


CNMT_XML = """<?xml version="1.0" encoding="utf-8"?>
<ContentMeta>
  <Type>Application</Type>
  <Id>0x0100a3900c3e2000</Id>
  <Version>0</Version>
  <Content>
    <Type>Program</Type>
    <Id>4e9a28e91be8344f0c109a4f663fe19b</Id>
    <Size>16</Size>
    <Hash>4e9a28e91be8344f0c109a4f663fe19bd187d09634c6a9a8f78f0ae5995e6da6</Hash>
    <KeyGeneration>11</KeyGeneration>
  </Content>
  <Digest>b1ba637314ed0492c5887090749fea869c48646ce2264b59e869a907703568df</Digest>
  <KeyGenerationMin>11</KeyGenerationMin>
  <PatchId>0x0100a3900c3e2800</PatchId>
</ContentMeta>
"""


def test_parse_content_meta():
    meta = switch_nsp.parse_content_meta(CNMT_XML.encode("utf-8"))
    assert meta.title_id == "0x0100a3900c3e2000"
    assert meta.content_type == "Application"
    assert meta.key_generation_min == 11
    assert meta.patch_id == "0x0100a3900c3e2800"
    assert len(meta.contents) == 1
    assert meta.contents[0].type == "Program"
    assert meta.contents[0].size == 16
    found = meta.sha256_for_member("4e9a28e91be8344f0c109a4f663fe19b.nca")
    assert found == "4e9a28e91be8344f0c109a4f663fe19bd187d09634c6a9a8f78f0ae5995e6da6"
    assert meta.sha256_for_member("unrelated.nca") is None


def test_classify_nca_header():
    assert switch_nsp.classify_nca_header(b"NCA3" + b"\x00" * 60) == "plaintext"
    assert switch_nsp.classify_nca_header(b"\xd6\x75\x20\x72" + b"\x00" * 60) == "encrypted"
    assert switch_nsp.classify_nca_header(b"N") == "truncated"


def test_sha256_region_matches_hashlib():
    payload = b"paper mario" * 1000
    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(payload)
        path = fh.name
    try:
        with open(path, "rb") as handle:
            digest = switch_nsp.sha256_region(handle, 100, len(payload) - 100)
        assert digest == hashlib.sha256(payload[100:]).hexdigest()
    finally:
        os.unlink(path)


def test_build_manifest_cross_checks_published_hashes():
    program_payload = b"\xaa" * 16
    digest = hashlib.sha256(program_payload).hexdigest()
    xml = CNMT_XML.replace(
        "4e9a28e91be8344f0c109a4f663fe19bd187d09634c6a9a8f78f0ae5995e6da6", digest
    ).encode("utf-8")
    members = [
        ("4e9a28e91be8344f0c109a4f663fe19b.nca", program_payload),
        ("44193b1a45a7cd27eccb60e1cbdd9a7a.cnmt.xml", xml),
    ]
    blob = _build_pfs0(members, stride=0x18)
    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(blob)
        path = fh.name
    try:
        manifest = switch_nsp.build_manifest(path, container_sha256="0" * 64)
        assert manifest["container"]["format"] == "NSP (PFS0)"
        assert manifest["container"]["member_count"] == 2
        assert manifest["title"]["title_id"] == "0x0100a3900c3e2000"
        by_name = {m["name"]: m for m in manifest["members"]}
        assert by_name["4e9a28e91be8344f0c109a4f663fe19b.nca"]["sha256_verified"] is True
        assert by_name["4e9a28e91be8344f0c109a4f663fe19b.nca"]["payload_kind"] == "encrypted"
    finally:
        os.unlink(path)


def _main() -> int:
    failures = 0
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {exc}")
            else:
                print(f"ok   {name}")
    print("failures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main())
