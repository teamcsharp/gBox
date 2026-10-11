"""Reproduce the bounded inbox #1216 DOA2 checkpoint repair offline.

Requires the exact reported original and the verified native-produced RGB565
buffer attached to its report. This fixes that checkpoint only. It does not
run an emulator, recover another save, modify a ROM, or replace missing pixels.

Usage: python scripts/doa2_recover_checkpoint.py --original ORIGINAL.state
       --native-buffer native-replayed-rtt-v2.bin --output NEW.state
RZIP v2 encoding requires the optional ``zstandard`` Python package.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import sys

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox.flycast_state import unpack, _zstd

ORIGINAL_SHA = "4f57b81700c67e64e52d78d6b27e5ef862d94a205539a4803d985f50b15732d5"
NATIVE_SHA = "b0771cc1c364f48f32cd571d5c92470ab07fd0af516f6b4ff496cb460da1771a"
OUTPUT_SHA = "9239cb198e94eb2e605d83b46702c68d247e101877773d72720f53387c9e622a"
RAM_SHA = "3aa5331fcbfc7ee7d287e727d16b769eea8580425c47124c11a173c6d22f302a"
ORIGINAL_BYTES, NATIVE_BYTES, OUTPUT_BYTES = 10070931, 262144, 10120183
MEM_OFFSET, RAM_OFFSET, RAM_BYTES = 8229803, 11990458, 0x1000000


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _decode(raw):
    """Validate the whole container, then retain canonical original chunks."""
    mem = unpack(raw)
    _require(raw.startswith(b"#RZIPv\x02#"), "requires the original RZIP v2 container")
    chunk_size, total = struct.unpack_from("<IQ", raw, 8)
    pos, offset, chunks = 20, 0, []
    while offset < total:
        n = struct.unpack_from("<I", raw, pos)[0]
        blob = raw[pos+4:pos+4+n]
        data = _zstd(blob, min(chunk_size, total-offset))
        _require(len(data) == min(chunk_size, total-offset), "noncanonical RZIP segmentation")
        chunks.append((offset, blob, data))
        pos += 4+n
        offset += len(data)
    container = b"".join(c[2] for c in chunks)
    _require(container.startswith(b"RASTATE\x01"), "requires the original RASTATE v1 container")
    pos = 8
    while container[pos:pos+4] != b"MEM ":
        n = struct.unpack_from("<I", container, pos+4)[0]
        pos += 8+((n+7)&~7)
    start = pos+8
    _require(container[start:start+len(mem)] == mem, "MEM/container mismatch")
    return mem, container, start, chunks


def _verify_preservation(original, derived, start, payload):
    old, new = _decode(original), _decode(derived)
    a, b = old[0], new[0]
    end = start+len(payload)
    _require(len(a) == len(b) and a[:start] == b[:start] and a[end:] == b[end:]
             and b[start:end] == payload, "decoded state changed outside the allowed RTT surface")
    _require(old[2] == new[2] and len(old[1]) == len(new[1])
             and old[1][:old[2]] == new[1][:new[2]]
             and old[1][old[2]+len(a):] == new[1][new[2]+len(b):],
             "opaque container blocks or padding changed")
    _require(original[:20] == derived[:20] and len(old[3]) == len(new[3]),
             "RZIP header or chunk count changed")
    changed = []
    for index, (before, after) in enumerate(zip(old[3], new[3])):
        _require(before[0] == after[0] and len(before[2]) == len(after[2]), "RZIP segmentation changed")
        if before[2] == after[2]:
            _require(before[1] == after[1], "unchanged RZIP chunk was altered")
        else:
            changed.append(index)
    return changed


def _patch_container(raw, start, payload):
    """Pure, bounds-checked patch; preserve opaque blocks and unchanged chunks."""
    mem, container, mem_start, chunks = _decode(raw)
    _require(type(start) is int and 0 <= start < len(mem) and payload
             and start+len(payload) <= len(mem), "invalid RTT patch range")
    updated = container[:mem_start+start]+payload+container[mem_start+start+len(payload):]
    import zstandard
    encoded = []
    compressor = zstandard.ZstdCompressor(level=3)
    for offset, blob, data in chunks:
        new_data = updated[offset:offset+len(data)]
        new_blob = blob if data == new_data else compressor.compress(new_data)
        encoded.append(struct.pack("<I", len(new_blob))+new_blob)
    result = raw[:20]+b"".join(encoded)
    changed = _verify_preservation(raw, result, start, payload)
    return result, changed


def recover(original, native_buffer):
    """Only the two verified report inputs are admitted; no runtime execution."""
    _require(len(original) == ORIGINAL_BYTES and _sha(original) == ORIGINAL_SHA,
             "original does not match the exact inbox #1216 checkpoint")
    _require(len(native_buffer) == NATIVE_BYTES and _sha(native_buffer) == NATIVE_SHA,
             "native buffer does not match the verified inbox #1216 RTT capture")
    mem = unpack(original)
    _require(len(mem) == 36439543 and struct.unpack_from("<I", mem)[0] == 854,
             "original MEM layout differs from the verified V59 checkpoint")
    _require(_sha(mem[RAM_OFFSET:RAM_OFFSET+RAM_BYTES]) == RAM_SHA,
             "original guest RAM differs from the verified checkpoint")
    output, changed = _patch_container(original, MEM_OFFSET, native_buffer)
    _require(len(output) == OUTPUT_BYTES and _sha(output) == OUTPUT_SHA,
             "encoded output differs from the verified recovery; refusing to write")
    _require(changed == [62, 63, 64], "unexpected changed compressed chunks")
    difference = sum(a != b for a, b in zip(mem[MEM_OFFSET:MEM_OFFSET+NATIVE_BYTES], native_buffer))
    _require(difference == 257384, "unexpected native RTT byte difference count")
    return output, {"scope": "inbox #1216 exact DOA2 checkpoint only",
                    "original_sha256": ORIGINAL_SHA, "native_buffer_sha256": NATIVE_SHA,
                    "output_sha256": OUTPUT_SHA, "output_bytes": len(output),
                    "allowed_mem_offset": MEM_OFFSET, "allowed_bytes": NATIVE_BYTES,
                    "changed_bytes": difference, "changed_compressed_chunks": changed,
                    "all_other_state_and_container_bytes_preserved": True,
                    "unchanged_compressed_chunks_preserved": True,
                    "original_guest_ram_preserved": True, "emulator_executed": False}


def write_checkpoint(original_path, native_path, output_path):
    original_path, native_path, output_path = map(Path, (original_path, native_path, output_path))
    if output_path.exists():
        raise FileExistsError("refusing to overwrite an existing checkpoint")
    _require(original_path.stat().st_size == ORIGINAL_BYTES, "original file has unexpected size")
    _require(native_path.stat().st_size == NATIVE_BYTES, "native buffer file has unexpected size")
    output, report = recover(original_path.read_bytes(), native_path.read_bytes())
    _require(_sha(original_path.read_bytes()) == ORIGINAL_SHA
             and _sha(native_path.read_bytes()) == NATIVE_SHA, "an input changed during recovery")
    with output_path.open("xb") as stream:
        stream.write(output)
    report["output"] = str(output_path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "native-buffer", "output"):
        parser.add_argument("--"+name, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(write_checkpoint(args.original, args.native_buffer, args.output), indent=2))


if __name__ == "__main__":
    main()
