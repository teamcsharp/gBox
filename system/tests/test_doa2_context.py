"""Synthetic native/container boundary regressions; no owned assets bundled."""
from pathlib import Path
import hashlib
import struct
import sys
import zlib

import pytest

from gbox import doa2_context as C
from gbox import doa2_bindings as B, doa2_geometry as G


def archive():
    material = bytearray(80)
    struct.pack_into("<4I", material, 0, 0x8000002C, 0x83000000, 0x20282452, 0x4C000000)
    struct.pack_into("<4f", material, 16, 0, 0, 0, 1)
    struct.pack_into("<ii", material, 32, 0, 1)
    struct.pack_into("<9f", material, 40, .75, 1, 1, 1, 1, 0, .2, .2, .2)
    quad = {"header": bytes(material), "vertices": [(0,0,0,0,0,1,0,0),
        (1,0,0,0,0,1,1,0),(1,1,0,0,0,1,1,-1),(0,1,0,0,0,1,0,-1)],
        "triangles": [(0,1,2),(0,2,3)]}
    out = bytearray(24)
    pointers = []
    for _ in range(2):
        pointers.append(0x0C300000 + len(out) - 24)
        out.extend(G.encode_model({"global_flags": (1,1)}, [quad]))
    out.extend(bytes(8))
    table = len(out)
    out.extend(struct.pack("<2I", *pointers))
    textures = len(out)
    out.extend(struct.pack("<3I", 8192, 0x08000000, 0x0C300000))
    struct.pack_into("<6I", out, 0, 24, table, textures, 2, 1, 0)
    return bytes(out)


def executable():
    out = bytearray(0x1C0000)
    for ordinal, offset in enumerate(C.FINGERPRINTS):
        out[offset:offset+128] = bytes((k*17 + ordinal*31) % 256 for k in range(128))
    for address, value in ((0x8C0DD86C,C.RAM_BASE+C.ACTOR_BASE),
        (0x8C0DD898,C.RAM_BASE+C.PRIMARY_TABLE),
        (0x8C0DD89C,C.RAM_BASE+C.MODEL_TABLE),(0x8C0DD0E4,B.SCRIPT_TABLE)):
        struct.pack_into("<I", out, address-B.BASE, value)
    # Two native costumes intentionally resolve KTE01 then KTE00.
    table, script, parts = 0x80000, 0x80100, 0x80200
    struct.pack_into("<I", out, B.SCRIPT_TABLE-B.BASE+3*4, B.BASE+table)
    struct.pack_into("<3I", out, table, B.BASE+script, B.BASE+script+8, 0)
    struct.pack_into("<4I", out, script, B.BASE+parts, 0, B.BASE+parts, 0)
    out[parts:parts+20] = bytes([0xFE]+[0]*15+[0xF9,1,1,0xFF])
    names = ("karate.bin","kte01.bin","kte01.chr","kte01.apv","kte01.sup",
             "kte00.bin","kte00.chr","kte00.apv","kte00.sup")
    cursor = 0x90000
    for index, name in enumerate(names):
        struct.pack_into("<I", out, B.FILE_NAMES-B.BASE+index*4, B.BASE+cursor)
        encoded = name.encode()+b"\0"
        out[cursor:cursor+len(encoded)] = encoded
        cursor += len(encoded)
    for costume, ids in ((0,(0,1,2,3,4)),(1,(0,5,6,7,8))):
        struct.pack_into("<5H", out, B.FILE_TABLE-B.BASE+costume*250+3*10, *ids)
    return bytes(out)


@pytest.fixture
def native(monkeypatch):
    exe = executable()
    monkeypatch.setattr(B, "EXECUTABLE_SHA256", hashlib.sha256(exe).hexdigest())
    ram = bytearray(C.RAM_BYTES)
    for o in C.FINGERPRINTS:
        ram[0x10000+o:0x10000+o+128] = exe[o:o+128]
    data = archive()
    decoded = G.decode_chr(data)
    base = 0x6A0000
    ram[base:base+len(data)] = data
    for k in range(3):
        offset = struct.unpack_from("<I", data, 4*k)[0]
        struct.pack_into("<I", ram, base+4*k, C.RAM_BASE+base+offset)
    table = decoded["model_table_offset"]
    pointers = [C.RAM_BASE+base+m["offset"] for m in decoded["models"]]
    struct.pack_into("<2I", ram, base+table, *pointers)
    struct.pack_into("<2I", ram, C.MODEL_TABLE, *pointers)
    struct.pack_into("<I", ram, C.RESOURCE_TABLE, C.RAM_BASE+base)
    actor = C.ACTOR_BASE
    ram[actor+1]=3
    ram[actor+0x53]=1
    ram[C.PRIMARY_TABLE:C.PRIMARY_TABLE+15]=bytes(15)
    return ram, exe, data, base, decoded


def rastate(mem):
    return b"RASTATE\1MEM "+struct.pack("<I",len(mem))+mem+bytes((-len(mem))%8)+b"END "+bytes(4)


def rzip(data):
    chunk=zlib.compress(data)
    return b"#RZIPv\1#"+struct.pack("<IQ",len(data),len(data))+struct.pack("<I",len(chunk))+chunk


def test_actual_native_filename_order_and_source_linkage(native):
    ram,exe,data,base,_=native
    row=C.source_identity(bytes(ram),exe,0,"DOA2/KTE01.CHR",data)
    assert (row["render_slot"],row["render_costume"],row["resource_cache"])==(3,0,0)
    assert row["source_structure_uv_verified"] and not row["full_cache_bytes_verified"]
    assert not row["operator_actor_verified"] and not row["native_reimport_verified"]
    assert (row["checked_inline_vertices"],row["checked_compact_references"])==(8,4)
    ram[C.ACTOR_BASE+2]=1
    row=C.source_identity(bytes(ram),exe,0,"KTE00.CHR",data)
    assert row["resource_filenames"]["geometry"]=="kte00.chr"


@pytest.mark.parametrize("version",[851,854])
def test_container_full_decode_unique_ram_and_immutable_inputs(native,version):
    ram,exe,_,_,_=native
    mem=struct.pack("<I",version)+bytes(19)+bytes(ram)+bytes(11)
    raw=rzip(rastate(mem)); before=hashlib.sha256(raw).hexdigest()
    actual,meta=C.ram_from_state(raw,exe)
    assert actual==ram and meta["ram_offset"]==23
    assert meta["serializer_version"]==version
    assert hashlib.sha256(raw).hexdigest()==before


def test_ambiguous_duplicate_ram_rejected(native):
    ram,exe,_,_,_=native
    with pytest.raises(ValueError,match="found 2"):
        C.ram_from_state(struct.pack("<I",851)+ram+ram,exe)


@pytest.mark.parametrize("version",[850,852,853,855,-1])
def test_unverified_serializer_rejected(native,version):
    ram,exe,_,_,_=native
    with pytest.raises(ValueError,match="unsupported actor-context serializer"):
        C.ram_from_state(struct.pack("<i",version)+ram,exe)


@pytest.mark.parametrize("offset",C.FINGERPRINTS)
def test_each_independent_code_fingerprint_required(native,offset):
    ram,exe,_,_,_=native
    ram[0x10000+offset]^=0xFF
    with pytest.raises(ValueError,match="fingerprint"):
        C.inspect_actor(bytes(ram),exe,0)
    with pytest.raises(ValueError,match="found 0"):
        C.ram_from_state(struct.pack("<I",851)+ram,exe)


def test_other_executable_rejected(native):
    ram,exe,_,_,_=native
    with pytest.raises(ValueError,match="executable identity"):
        C.inspect_actor(bytes(ram),exe[:-1]+b"\1",0)


@pytest.mark.parametrize("tail",[b"extra",None])
def test_container_trailing_or_missing_end_rejected(native,tail):
    ram,exe,_,_,_=native
    raw=rastate(struct.pack("<I",851)+ram)
    damaged=raw+tail if tail else raw[:-8]
    with pytest.raises(ValueError,match="END"):
        C.ram_from_state(damaged,exe)


def test_truncated_compressed_chunk_rejected(native):
    ram,exe,_,_,_=native
    with pytest.raises(ValueError,match="out-of-bounds RZIP chunk"):
        C.ram_from_state(rzip(rastate(struct.pack("<I",851)+ram))[:-1],exe)


def test_partial_ram_rejected(native):
    ram,exe,_,_,_=native
    with pytest.raises(ValueError,match="exactly 16 MiB"):
        C.inspect_actor(bytes(ram[:-1]),exe,0)
    with pytest.raises(ValueError,match="found 0"):
        C.ram_from_state(struct.pack("<I",851)+ram[:-1],exe)


@pytest.mark.parametrize("actor",[-1,2,True,"0",None])
def test_explicit_actor_index_required(native,actor):
    ram,exe,_,_,_=native
    with pytest.raises(ValueError,match="explicitly select"):
        C.inspect_actor(bytes(ram),exe,actor)


@pytest.mark.parametrize("field,value,reason",[(0x53,0,"draw gate"),(0x61,4,"four slots"),
    (1,25,"Invalid native"),(2,31,"no verified body")])
def test_invalid_actor_context_fails_closed(native,field,value,reason):
    ram,exe,_,_,_=native;ram[C.ACTOR_BASE+field]=value
    with pytest.raises(ValueError,match=reason):C.inspect_actor(bytes(ram),exe,0)


def test_native_primary_binding_mismatch_rejected(native):
    ram,exe,_,_,_=native;ram[C.PRIMARY_TABLE]=1
    with pytest.raises(ValueError,match="primary-model binding"):
        C.inspect_actor(bytes(ram),exe,0)


@pytest.mark.parametrize("pointer",[0,0x0C6A0000,0x8BFFFFFF,0x8CFFFFFF,0x8D000000])
def test_cache_pointer_not_masked_or_out_of_bounds(native,pointer):
    ram,exe,_,_,_=native;struct.pack_into("<I",ram,C.RESOURCE_TABLE,pointer)
    with pytest.raises(ValueError,match="resource pointer outside"):
        C.inspect_actor(bytes(ram),exe,0)


def test_native_draw_table_must_link_selected_cache(native):
    ram,exe,_,_,_=native;struct.pack_into("<I",ram,C.MODEL_TABLE,0x8C600018)
    with pytest.raises(ValueError,match="draw pointer table disagrees"):
        C.inspect_actor(bytes(ram),exe,0)


@pytest.mark.parametrize("field,value",[(4,0x8D000000),(8,0x8D000000),(12,0),(12,257),(16,4097)])
def test_native_relocated_header_bounds(native,field,value):
    ram,exe,_,base,_=native;struct.pack_into("<I",ram,base+field,value)
    with pytest.raises(ValueError):C.inspect_actor(bytes(ram),exe,0)


def test_native_model_pointer_order_and_overlap(native):
    ram,exe,_,base,decoded=native
    table=base+decoded["model_table_offset"]
    struct.pack_into("<I",ram,table+4,struct.unpack_from("<I",ram,table)[0])
    with pytest.raises(ValueError,match="non-monotonic"):
        C.inspect_actor(bytes(ram),exe,0)


def test_wrong_resource_name_rejected_even_if_same_layout(native):
    ram,exe,data,_,_=native
    with pytest.raises(ValueError,match="filename disagrees"):
        C.source_identity(bytes(ram),exe,0,"AYA00.CHR",data)


def test_shader_lighting_position_mutations_do_not_claim_full_byte_identity(native):
    ram,exe,data,base,decoded=native
    mesh=decoded["models"][0]["meshes"][0]
    struct.pack_into("<i",ram,base+mesh["offset"]+36,7)
    struct.pack_into("<f",ram,base+mesh["offset"]+48,.35)
    rec=next(r for r in mesh["records"] if not r["reference"])
    struct.pack_into("<6f",ram,base+rec["offset"],12,13,14,.1,.2,.3)
    row=C.source_identity(bytes(ram),exe,0,"kte01.chr",data)
    assert row["source_structure_uv_verified"] and not row["full_cache_bytes_verified"]


@pytest.mark.parametrize("kind",["uv","ref","length","texture","model_counts","terminator"])
def test_source_structure_corruption_rejected(native,kind):
    ram,exe,data,base,decoded=native;model=decoded["models"][0];mesh=model["meshes"][0]
    if kind=="uv":offset=next(r for r in mesh["records"] if not r["reference"])["offset"]+24
    elif kind=="ref":offset=next(r for r in mesh["records"] if r["reference"])["offset"]+4
    elif kind=="length":offset=mesh["offset"]+76
    elif kind=="texture":offset=mesh["offset"]+32
    elif kind=="model_counts":offset=model["offset"]
    else:offset=model["end_offset"]-4
    ram[base+offset]^=0x01
    with pytest.raises(ValueError,match="differ.*from source"):
        C.source_identity(bytes(ram),exe,0,"kte01.chr",data)


def test_aliased_geometry_uses_explicit_actor_cache_not_minimum_uv_match(native):
    ram,exe,data,_,decoded=native
    ram[C.ACTOR_BASE+0x61]=1
    ram[C.RESOURCE_TABLE+C.RESOURCE_STRIDE:C.RESOURCE_TABLE+2*C.RESOURCE_STRIDE]=ram[C.RESOURCE_TABLE:C.RESOURCE_TABLE+C.RESOURCE_STRIDE]
    ram[C.PRIMARY_TABLE+15:C.PRIMARY_TABLE+30]=ram[C.PRIMARY_TABLE:C.PRIMARY_TABLE+15]
    count=len(decoded["models"])
    ram[C.MODEL_TABLE+C.MODEL_STRIDE:C.MODEL_TABLE+C.MODEL_STRIDE+count*4]=ram[C.MODEL_TABLE:C.MODEL_TABLE+count*4]
    assert C.source_identity(bytes(ram),exe,0,"kte01.chr",data)["resource_cache"]==1


def test_mutable_position_difference_cannot_be_reported_as_full_identity(native):
    ram,exe,data,_,decoded=native
    source=bytearray(data)
    vertex=decoded["models"][0]["meshes"][0]["records"][0]["offset"]
    struct.pack_into("<f",source,vertex,125.0)
    row=C.source_identity(bytes(ram),exe,0,"kte01.chr",bytes(source))
    assert not row["full_cache_bytes_verified"] and not row["native_reimport_verified"]


@pytest.mark.parametrize("case", ["overlap4", "overlap20", "missing_end"])
def test_cached_models_have_separate_header_and_end_marker_room(native, case):
    ram, exe, _, base, decoded = native
    table = base + decoded["model_table_offset"]
    offset = table - 24 if case == "missing_end" else base + 24 + int(case[7:])
    struct.pack_into("<I", ram, table + 4, C.RAM_BASE + offset)
    struct.pack_into("<I", ram, C.MODEL_TABLE + 4, C.RAM_BASE + offset)
    with pytest.raises(ValueError, match="header/end-marker room"):
        C.inspect_actor(bytes(ram), exe, 0)


@pytest.mark.parametrize("kind", ["chr", "table", "texture", "model"])
def test_word_addressed_native_cache_requires_four_byte_alignment(native, kind):
    ram, exe, data, base, decoded = native
    if kind == "chr":
        ram[base+1:base+1+len(data)] = ram[base:base+len(data)]
        base += 1
        for k in range(3):
            relative = struct.unpack_from("<I", data, 4*k)[0]
            struct.pack_into("<I", ram, base+4*k, C.RAM_BASE+base+relative)
        pointers = [C.RAM_BASE+base+m["offset"] for m in decoded["models"]]
        struct.pack_into("<2I", ram, base+decoded["model_table_offset"], *pointers)
        struct.pack_into("<2I", ram, C.MODEL_TABLE, *pointers)
        struct.pack_into("<I", ram, C.RESOURCE_TABLE, C.RAM_BASE+base)
        with pytest.raises(ValueError, match="unaligned"):
            C.source_identity(bytes(ram), exe, 0, "KTE01.CHR", data)
        return
    if kind == "table":
        table = base+decoded["model_table_offset"]
        pointers = bytes(ram[table:table+8])
        ram[table-1:table+7] = pointers
        struct.pack_into("<I", ram, base+4, C.RAM_BASE+table-1)
    elif kind == "texture":
        pointer = struct.unpack_from("<I", ram, base+8)[0]
        struct.pack_into("<I", ram, base+8, pointer+1)
    else:
        pointer = C.RAM_BASE+base+decoded["models"][1]["offset"]+1
        struct.pack_into("<I", ram, base+decoded["model_table_offset"]+4, pointer)
        struct.pack_into("<I", ram, C.MODEL_TABLE+4, pointer)
    with pytest.raises(ValueError, match="unaligned"):
        C.inspect_actor(bytes(ram), exe, 0)
