"""Read-only DOA2 LE actor/resource context from an immutable Flycast snapshot.

The exact owned executable and four independent code fingerprints pin this
layout. Native actor draw gates and cache links identify resources, not who the
operator controls or whether a displayed frame is correct. Source identity is
limited to relocated structure and every stored UV/reference; positions,
normals, texture residency, SUP/APV/ACS state and GPU submission need separate
checks. This module neither edits a snapshot nor initializes an emulator.
"""
from __future__ import annotations

import hashlib
import struct

from gbox import doa2_bindings as B, doa2_geometry as G, flycast_state as F

RAM_BYTES = 16 * 1024 * 1024
RAM_BASE = 0x8C000000
ACTOR_BASE = 0x2376B8
ACTOR_STRIDE = 0x68
RESOURCE_TABLE = 0x236710
RESOURCE_STRIDE = 28
PRIMARY_TABLE = 0x2AD5C0
MODEL_TABLE = 0x23C92C
MODEL_STRIDE = 0x400
FINGERPRINTS = (0x1000, 0x20000, 0x40000, 0x60000)
SUPPORTED_SERIALIZERS = (851, 854)  # actual bounded V56 and V59 fixtures


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("native word outside available bytes")
    return struct.unpack_from("<I", data, offset)[0]


def _executable(executable: bytes) -> None:
    if _sha(executable) != B.EXECUTABLE_SHA256:
        raise ValueError("unsupported DOA2 executable identity")
    # Independently checked literal pools in the native draw/script consumers.
    literals = {0x8C0DD86C: RAM_BASE + ACTOR_BASE,
                0x8C0DD898: RAM_BASE + PRIMARY_TABLE,
                0x8C0DD89C: RAM_BASE + MODEL_TABLE,
                0x8C0DD0E4: B.SCRIPT_TABLE}
    for address, expected in literals.items():
        if _u32(executable, address - B.BASE) != expected:
            raise ValueError("native actor/cache literal disagrees with pinned layout")


def _ram(ram: bytes, executable: bytes) -> None:
    _executable(executable)
    if len(ram) != RAM_BYTES:
        raise ValueError("snapshot must contain exactly 16 MiB of Dreamcast RAM")
    for offset in FINGERPRINTS:
        if ram[0x10000 + offset:0x10000 + offset + 128] != executable[offset:offset + 128]:
            raise ValueError("snapshot RAM code fingerprint disagrees with owned executable")


def _pointer(pointer: int, size: int = 1) -> int:
    # Reject unrelated MMIO, 0x0c aliases and guessed low24 masks. The actual
    # pinned native renderer stores 0x8c RAM pointers in these resource tables.
    offset = pointer - RAM_BASE
    if size < 0 or offset < 0 or offset + size > RAM_BYTES:
        raise ValueError("native resource pointer outside Dreamcast RAM")
    if pointer & 3:
        raise ValueError("unaligned native word resource pointer")
    return offset


def ram_from_state(raw: bytes, executable: bytes) -> tuple[bytes, dict]:
    """Decode all container bytes, then uniquely locate RAM using code evidence.

    RAM is deliberately not assigned a fixed serialization offset: preceding
    PVR/TA/VRAM objects vary with the saved frame. A valid container alone does
    not establish the title or supported native actor layout.
    """
    _executable(executable)
    mem = F.unpack(raw)
    version = F.version(mem)
    if version not in SUPPORTED_SERIALIZERS:
        raise ValueError(f"unsupported actor-context serializer {version}")
    needle = executable[FINGERPRINTS[0]:FINGERPRINTS[0] + 128]
    candidates = []
    position = 0
    while True:
        hit = mem.find(needle, position)
        if hit < 0:
            break
        position = hit + 1
        start = hit - 0x10000 - FINGERPRINTS[0]
        if 0 <= start <= len(mem) - RAM_BYTES and all(
            mem[start + 0x10000 + o:start + 0x10000 + o + 128]
            == executable[o:o + 128] for o in FINGERPRINTS
        ):
            candidates.append(start)
    if len(candidates) != 1:
        raise ValueError(f"expected one executable-identified RAM image, found {len(candidates)}")
    offset = candidates[0]
    ram = mem[offset:offset + RAM_BYTES]
    _ram(ram, executable)
    return ram, {"state_sha256": _sha(raw), "mem_sha256": _sha(mem),
                 "mem_bytes": len(mem), "serializer_version": version,
                 "ram_offset": offset, "ram_bytes": len(ram),
                 "ram_sha256": _sha(ram), "executable_sha256": _sha(executable),
                 "code_fingerprint_offsets": list(FINGERPRINTS)}


def inspect_actor(ram: bytes, executable: bytes, actor_index: int) -> dict:
    """Require a drawable actor with a consistent selected binding and cache.

    Choose actor_index explicitly (0 or 1). No menu cursor, filename suffix,
    human/CPU byte or controller port is used to guess a marked target.
    """
    _ram(ram, executable)
    if type(actor_index) is not int or actor_index not in (0, 1):
        raise ValueError("actor_index must explicitly select native actor 0 or 1")
    actor = ACTOR_BASE + actor_index * ACTOR_STRIDE
    slot, costume, draw, cache = (ram[actor + o] for o in (1, 2, 0x53, 0x61))
    if not draw:
        raise ValueError("native actor draw gate is disabled; no drawable context")
    if cache >= 4:
        raise ValueError("actor resource-cache index exceeds the native four slots")
    binding = B.render_part_mapping(executable, slot, costume)
    expected = binding["sections"]["primary"]
    primary = list(ram[PRIMARY_TABLE + 15 * cache:PRIMARY_TABLE + 15 * cache + 15])
    if primary != expected:
        raise ValueError("cached primary-model binding disagrees with actor slot/costume")
    resources = list(struct.unpack_from("<7I", ram, RESOURCE_TABLE + RESOURCE_STRIDE * cache))
    base = _pointer(resources[0], 24)
    first, table_ptr, texture_ptr, count, ntex, reserved = struct.unpack_from("<6I", ram, base)
    if first != resources[0] + 24 or not 0 < count <= MODEL_STRIDE // 4 or ntex > 4096:
        raise ValueError("invalid relocated native CHR header/counts")
    table, textures = _pointer(table_ptr, 4 * count), _pointer(texture_ptr, 12 * ntex)
    if not base + 24 <= table or table + 4 * count > textures:
        raise ValueError("native CHR model/texture tables overlap or precede geometry")
    pointers = list(struct.unpack_from(f"<{count}I", ram, table))
    offsets = [_pointer(p, 24) for p in pointers]
    if offsets != sorted(set(offsets)) or offsets[0] != base + 24 or offsets[-1] + 24 > table:
        raise ValueError("non-monotonic or out-of-bounds cached model pointers")
    boundaries = offsets[1:] + [table]
    if any(start + 32 > end for start, end in zip(offsets, boundaries)):
        raise ValueError("cached model spans overlap or lack header/end-marker room")
    linked = list(struct.unpack_from(f"<{count}I", ram, MODEL_TABLE + cache * MODEL_STRIDE))
    if linked != pointers:
        raise ValueError("native draw pointer table disagrees with selected CHR cache")
    if any(m >= count for m in binding["emit_models"]):
        raise ValueError("selected native body model exceeds cached model count")
    return {"format": "doa2-native-moment-context-v1", "actor_index": actor_index,
            "actor_address": f"{RAM_BASE + actor:08x}", "render_slot": slot,
            "render_costume": costume, "draw_gate_raw": draw,
            "resource_cache": cache, "chr_address": f"{resources[0]:08x}",
            "chr_offset": base, "model_count": count, "texture_count": ntex,
            "model_table_offset": table - base, "texture_table_offset": textures - base,
            "model_offsets": [p - base for p in offsets],
            "primary_models": primary, "emit_models": list(binding["emit_models"]),
            "resource_filenames": dict(binding["files"]),
            "resource_pointers_raw": [f"{p:08x}" for p in resources],
            "ram_sha256": _sha(ram), "executable_sha256": _sha(executable),
            "operator_actor_verified": False, "gameplay_verified": False}


def source_identity(ram: bytes, executable: bytes, actor_index: int,
                    archive_name: str, chr_data: bytes) -> dict:
    """Match one explicitly supplied source CHR against the selected native cache.

    Check every model offset, mesh texture-ID/length, inline UV and compact vertex
    reference, including unselected/shadow models. Actual relocated headers and
    the separately maintained native draw table must agree. This is not a
    byte-for-byte content hash: native animation mutates position/normal bytes
    and texture-address/header state. Empty archives cannot pass by vacuous UV
    comparison. No search across aliased caches is used to infer an actor.
    """
    context = inspect_actor(ram, executable, actor_index)
    name = archive_name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name != context["resource_filenames"]["geometry"]:
        raise ValueError("supplied CHR filename disagrees with the selected native resource")
    source = G.decode_chr(chr_data)
    table, textures, count, ntex = struct.unpack_from("<4I", chr_data, 4)
    if (table, textures, count, ntex) != (context["model_table_offset"],
            context["texture_table_offset"], context["model_count"], context["texture_count"]):
        raise ValueError("cached CHR structure differs from the supplied source")
    source_ptrs = struct.unpack_from(f"<{count}I", chr_data, table)
    source_offsets = [p - source_ptrs[0] + 24 for p in source_ptrs]
    if source_offsets != context["model_offsets"]:
        raise ValueError("cached model offsets differ from the supplied source")
    base = context["chr_offset"]
    if base + len(chr_data) > RAM_BYTES:
        raise ValueError("supplied CHR exceeds available native RAM")
    if ram[base + 20:base + 24] != chr_data[20:24]:
        raise ValueError("cached CHR reserved header differs from source")
    inline = refs = meshes = 0
    for model in source["models"]:
        # GP counts determine native material setup; centers are animation state.
        start = context["model_offsets"][model["id"]]
        if ram[base + start:base + start + 8] != chr_data[start:start + 8]:
            raise ValueError("cached model GP counts differ from source")
        end = model["end_offset"]
        if ram[base + end - 8:base + end] != chr_data[end - 8:end]:
            raise ValueError("cached model terminator/vertex count differs from source")
        for mesh in model["meshes"]:
            meshes += 1
            offset = mesh["offset"]
            # Native material/ACS setup changes shader and lighting words too,
            # beyond the first32 GP bytes. Only the texture ID and stream byte
            # count are stable in all three independently checked live saves.
            if any(ram[base + offset + k:base + offset + k + 4]
                   != chr_data[offset + k:offset + k + 4] for k in (32, 76)):
                raise ValueError("cached mesh texture ID/stream length differs from source")
            for record in mesh["records"]:
                pos, raw = base + record["offset"], record["raw"]
                if record["reference"]:
                    refs += 1
                    if ram[pos:pos + len(raw)] != raw:
                        raise ValueError("cached compact vertex reference differs from source")
                else:
                    inline += 1
                    if len(raw) != 32:
                        raise ValueError("source identity currently supports 32-byte fighter vertices only")
                    # An inline record starts with position.x, not a control
                    # word; SUP/APV/ACS legitimately deform its first24 bytes.
                    if ram[pos + 24:pos + 32] != raw[24:]:
                        raise ValueError("cached inline UV bytes differ from source")
    if not inline or not meshes:
        raise ValueError("source identity requires actual inline fighter geometry")
    return {**context, "source_chr_name": name, "source_chr_bytes": len(chr_data),
            "source_chr_sha256": _sha(chr_data), "source_structure_uv_verified": True,
            "checked_models": count, "checked_meshes": meshes,
            "checked_inline_vertices": inline, "checked_compact_references": refs,
            "full_cache_bytes_verified": False, "native_reimport_verified": False}
