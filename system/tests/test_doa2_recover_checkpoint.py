"""Portable synthetic container tests; no game or saved-state payloads in Git."""
import struct

import pytest

from gbox.flycast_state import unpack
from scripts import doa2_recover_checkpoint as recovery


def _fixture():
    zstd = pytest.importorskip("zstandard")
    def block(tag, data):
        return tag+struct.pack("<I", len(data))+data+b"P"*((-len(data))%8)
    mem = bytes((i*17+3)&255 for i in range(400))
    container = (b"RASTATE\x01"+block(b"RPLY", b"opaque!")+block(b"MEM ", mem)
                 +block(b"META", b"keep")+b"END "+bytes(4))
    chunks = [zstd.ZstdCompressor(level=7).compress(container[i:i+64])
              for i in range(0, len(container), 64)]
    raw = b"#RZIPv\x02#"+struct.pack("<IQ", 64, len(container))
    return raw+b"".join(struct.pack("<I", len(c))+c for c in chunks), mem


def test_patch_crosses_chunks_preserving_every_other_byte_and_compressed_chunk():
    raw, mem = _fixture()
    payload = b"NATIVE"*15
    output, changed = recovery._patch_container(raw, 45, payload)
    assert unpack(output) == mem[:45]+payload+mem[45+len(payload):]
    assert len(changed) >= 2
    assert recovery._verify_preservation(raw, output, 45, payload) == changed
    assert raw[:20] == output[:20]


def test_noop_retains_byte_exact_original_encoding():
    raw, mem = _fixture()
    output, changed = recovery._patch_container(raw, 8, mem[8:100])
    assert output == raw and changed == []


@pytest.mark.parametrize("start,payload", [(-1, b"X"), (400, b"X"), (399, b"XX"), (0, b""), (True, b"X")])
def test_invalid_patch_bounds_rejected(start, payload):
    raw, _ = _fixture()
    with pytest.raises(ValueError, match="patch range"):
        recovery._patch_container(raw, start, payload)


def test_actual_outside_mem_change_rejected():
    raw, _ = _fixture()
    output, _ = recovery._patch_container(raw, 45, b"NATIVE")
    bad, _ = recovery._patch_container(output, 120, b"outside")
    with pytest.raises(ValueError, match="outside"):
        recovery._verify_preservation(raw, bad, 45, b"NATIVE")


def test_opaque_block_or_padding_change_rejected():
    raw, _ = _fixture()
    output, _ = recovery._patch_container(raw, 45, b"NATIVE")
    zstd = pytest.importorskip("zstandard")
    _, container, _, _ = recovery._decode(output)
    bad = bytearray(container); bad[18] ^= 1
    chunks = [zstd.ZstdCompressor(level=3).compress(bad[i:i+64]) for i in range(0, len(bad), 64)]
    altered = output[:20]+b"".join(struct.pack("<I", len(c))+c for c in chunks)
    with pytest.raises(ValueError, match="opaque"):
        recovery._verify_preservation(raw, altered, 45, b"NATIVE")


def test_truncated_or_trailing_compressed_container_rejected():
    raw, _ = _fixture()
    for bad in (raw[:-1], raw+b"extra"):
        with pytest.raises(ValueError):
            recovery._patch_container(bad, 45, b"NATIVE")


def test_recompressed_unchanged_chunk_rejected():
    raw, mem = _fixture()
    zstd = pytest.importorskip("zstandard")
    _, container, _, _ = recovery._decode(raw)
    chunks = [zstd.ZstdCompressor(level=3, write_checksum=True).compress(container[i:i+64])
              for i in range(0, len(container), 64)]
    altered = raw[:20]+b"".join(struct.pack("<I", len(c))+c for c in chunks)
    assert unpack(altered) == mem
    with pytest.raises(ValueError, match="unchanged RZIP"):
        recovery._verify_preservation(raw, altered, 45, mem[45:51])


def test_unknown_original_never_admitted():
    raw, _ = _fixture()
    with pytest.raises(ValueError, match="exact inbox"):
        recovery.recover(raw, b"X"*recovery.NATIVE_BYTES)


def test_write_refuses_existing_output_without_reading_inputs(tmp_path):
    output = tmp_path/"existing.state"; output.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        recovery.write_checkpoint(tmp_path/"missing", tmp_path/"also-missing", output)
    assert output.read_bytes() == b"keep"
