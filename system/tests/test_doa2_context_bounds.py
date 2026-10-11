"""Independent context-only adversarial checks; no emulator or owned bytes.

The two expected-refusal checks intentionally expose current prototype gaps.
All inputs are synthetic and copied before mutations.
"""
from pathlib import Path
import hashlib
import struct
import sys

import pytest

from test_doa2_context import native, rastate, rzip
from gbox import doa2_context as C
from gbox import doa2_geometry as G


def _linked_model(ram, base, decoded, index, address):
    table = base + decoded["model_table_offset"]
    struct.pack_into("<I", ram, table + index * 4, address)
    struct.pack_into("<I", ram, C.MODEL_TABLE + index * 4, address)


@pytest.mark.parametrize("step", [4, 20])
def test_overlapping_distinct_native_model_headers_must_be_refused(native, step):
    ram, exe, _, base, decoded = native
    _linked_model(ram, base, decoded, 1, C.RAM_BASE + base + 24 + step)
    # Sorted/unique and draw-table agreement cannot validate overlapping headers.
    with pytest.raises(ValueError):
        C.inspect_actor(bytes(ram), exe, 0)


def test_final_native_model_must_have_room_for_end_marker(native):
    ram, exe, _, base, decoded = native
    table = base + decoded["model_table_offset"]
    _linked_model(ram, base, decoded, 1, C.RAM_BASE + table - 24)
    with pytest.raises(ValueError):
        C.inspect_actor(bytes(ram), exe, 0)


@pytest.mark.parametrize("kind", ["chr", "table", "texture", "model"])
def test_native_word_resource_pointers_must_be_aligned(native, kind):
    ram, exe, data, base, decoded = native
    if kind == "chr":
        # Relocate the whole cache, matching all source offsets and draw links,
        # to an impossible unaligned native u32-addressed resource.
        ram[base+1:base+1+len(data)] = ram[base:base+len(data)]
        base += 1
        for k in range(3):
            relative = struct.unpack_from("<I", data, 4*k)[0]
            struct.pack_into("<I", ram, base+4*k, C.RAM_BASE+base+relative)
        for index, model in enumerate(decoded["models"]):
            _linked_model(ram, base, decoded, index, C.RAM_BASE+base+model["offset"])
        struct.pack_into("<I", ram, C.RESOURCE_TABLE, C.RAM_BASE+base)
        with pytest.raises(ValueError):
            C.source_identity(bytes(ram), exe, 0, "KTE01.CHR", data)
        return
    if kind == "table":
        original = base + decoded["model_table_offset"]
        pointers = ram[original:original+8]
        ram[original-1:original+7] = pointers
        struct.pack_into("<I", ram, base+4, C.RAM_BASE+original-1)
    elif kind == "texture":
        value = struct.unpack_from("<I", ram, base+8)[0]
        struct.pack_into("<I", ram, base+8, value+1)
    else:
        model = C.RAM_BASE+base+decoded["models"][1]["offset"]+1
        _linked_model(ram, base, decoded, 1, model)
    with pytest.raises(ValueError):
        C.inspect_actor(bytes(ram), exe, 0)


@pytest.mark.parametrize("delta", [-4, 4])
def test_texture_extent_cannot_cross_ram_end(native, delta):
    ram, exe, _, base, _ = native
    # Keep the table after geometry but give a one-descriptor range off RAM.
    struct.pack_into("<I", ram, base + 8, C.RAM_BASE + C.RAM_BYTES - 12 + delta)
    if delta > 0:
        with pytest.raises(ValueError, match="outside Dreamcast RAM"):
            C.inspect_actor(bytes(ram), exe, 0)
    else:
        # An in-RAM descriptor extent alone does not prove resource allocation.
        row = C.inspect_actor(bytes(ram), exe, 0)
        assert row["texture_table_offset"] == C.RAM_BYTES - 16 - base
        assert row["gameplay_verified"] is False


@pytest.mark.parametrize("which", ["before_geometry", "table_overlap", "model_into_table"])
def test_linked_tables_reject_impossible_order_even_when_draw_table_agrees(native, which):
    ram, exe, _, base, decoded = native
    if which == "before_geometry":
        struct.pack_into("<I", ram, base + 4, C.RAM_BASE + base + 20)
    elif which == "table_overlap":
        struct.pack_into("<I", ram, base + 8, C.RAM_BASE + base + decoded["model_table_offset"] + 4)
    else:
        _linked_model(ram, base, decoded, 1,
                      C.RAM_BASE + base + decoded["model_table_offset"])
    with pytest.raises(ValueError):
        C.inspect_actor(bytes(ram), exe, 0)


@pytest.mark.parametrize("actor", [0, 1])
def test_inactive_actor_cannot_be_rescued_by_valid_foreign_cache(native, actor):
    ram, exe, _, _, _ = native
    if actor:
        start = C.ACTOR_BASE + C.ACTOR_STRIDE
        ram[start:start+C.ACTOR_STRIDE] = ram[C.ACTOR_BASE:C.ACTOR_BASE+C.ACTOR_STRIDE]
    ram[C.ACTOR_BASE + actor*C.ACTOR_STRIDE + 0x53] = 0
    with pytest.raises(ValueError, match="draw gate"):
        C.inspect_actor(bytes(ram), exe, actor)


def test_matching_headers_do_not_accept_other_source_uv(native):
    ram, exe, data, _, decoded = native
    supplied = bytearray(data)
    record = decoded["models"][1]["meshes"][0]["records"][0]
    struct.pack_into("<f", supplied, record["offset"] + 24, .375)
    with pytest.raises(ValueError, match="inline UV bytes differ"):
        C.source_identity(bytes(ram), exe, 0, "KTE01.CHR", bytes(supplied))


def test_source_decoder_rejects_overlapping_headers_independently(native):
    _, _, data, _, decoded = native
    supplied = bytearray(data)
    table = decoded["model_table_offset"]
    first = struct.unpack_from("<I", supplied, table)[0]
    struct.pack_into("<I", supplied, table + 4, first + 4)
    with pytest.raises(ValueError, match="short NaomiLib model"):
        G.decode_chr(bytes(supplied))


def test_source_decoder_rejects_forward_reference_to_missing_inline(native):
    ram, exe, data, _, decoded = native
    supplied = bytearray(data)
    ref = next(row for row in decoded["models"][0]["meshes"][0]["records"]
               if row["reference"])
    struct.pack_into("<i", supplied, ref["offset"] + 4, 32)
    with pytest.raises(ValueError, match="misses earlier inline"):
        C.source_identity(bytes(ram), exe, 0, "KTE01.CHR", bytes(supplied))


def test_matching_structure_does_not_prove_source_positions_or_shader(native):
    ram, exe, data, _, decoded = native
    supplied = bytearray(data)
    mesh = decoded["models"][1]["meshes"][0]
    inline = next(row for row in mesh["records"] if not row["reference"])
    struct.pack_into("<f", supplied, inline["offset"], 11.125)
    struct.pack_into("<i", supplied, mesh["offset"] + 36, 4)
    assert hashlib.sha256(supplied).digest() != hashlib.sha256(data).digest()
    row = C.source_identity(bytes(ram), exe, 0, "KTE01.CHR", bytes(supplied))
    assert row["source_structure_uv_verified"] is True
    assert row["full_cache_bytes_verified"] is False
    assert row["native_reimport_verified"] is False
    assert row["operator_actor_verified"] is False
    assert row["gameplay_verified"] is False


def test_complete_envelope_and_ram_are_not_full_core_state_validation(native):
    ram, exe, _, _, _ = native
    # Deliberately lacks all other native serializer objects. The API diagnoses
    # RAM; it must never be used as proof that the core accepts this payload.
    raw = rzip(rastate(struct.pack("<I", 854) + ram))
    extracted, metadata = C.ram_from_state(raw, exe)
    assert extracted == ram and metadata["mem_bytes"] == 4 + C.RAM_BYTES
    assert "load_verified" not in metadata and "complete_core_state" not in metadata


@pytest.mark.parametrize("mode", ["raw_ram_prefix_missing", "truncated_chunk", "end_missing"])
def test_container_or_code_damage_refused_before_actor_search(native, mode):
    ram, exe, _, _, _ = native
    if mode == "raw_ram_prefix_missing":
        ram[0x10000+C.FINGERPRINTS[2]+71] ^= 1
        raw = struct.pack("<I", 854) + ram
    elif mode == "truncated_chunk":
        raw = rzip(rastate(struct.pack("<I", 854) + ram))[:-2]
    else:
        raw = rastate(struct.pack("<I", 854) + ram)[:-8]
    with pytest.raises(ValueError):
        C.ram_from_state(raw, exe)
