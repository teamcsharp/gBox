"""Verified DOA2 LE render-script part assignments from the owned executable.

Independent interpretation of FUN_8c0dcfe8 (script loading), FUN_8c0dd826
(matrices 0..14), and FUN_8c0dd906 (matrices 15..16). No shape guesses.
"""
from __future__ import annotations

import hashlib
import struct

BASE = 0x8C010000
SCRIPT_TABLE = 0x8C1C85F4
FILE_TABLE = 0x8C17F5F4
FILE_NAMES = 0x8C17E774
EXECUTABLE_SHA256 = "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1"
SECTIONS = {0xFE: "primary", 0xFC: "skip", 0xFB: "shadow", 0xFD: "secondary",
            0xFA: "accessory", 0xF9: "extra"}


def parse_render_scripts(executable: bytes) -> list[dict]:
    """Return 25 native slot records, each with its actual costume entries.

    Slot IDs are native render-slot IDs. Do not presume every disc archive
    has a selectable slot entry, nor that slot IDs are filename-list IDs.
    """
    if hashlib.sha256(executable).hexdigest() != EXECUTABLE_SHA256:
        raise ValueError("Unsupported DOA2 executable: part script addresses are version-specific")

    def offset(address, size=1):
        i = address - BASE
        if i < 0 or i + size > len(executable):
            raise ValueError(f"Out-of-bounds native script pointer {address:#x}")
        return i

    def word(address):
        return struct.unpack_from("<I", executable, offset(address, 4))[0]

    def filename(index):
        start = offset(word(FILE_NAMES + index * 4))
        end = executable.find(b"\0", start, start + 256)
        if end < 0:
            raise ValueError("Native resource name has no terminator")
        return executable[start:end].decode("ascii")

    slots = []
    for slot in range(25):
        ptr = word(SCRIPT_TABLE + slot * 4)
        record = {"slot": slot, "table_address": ptr, "costumes": []}
        if ptr:
            for costume in range(32):
                entry = word(ptr + costume * 4)
                if entry == 0:
                    break
                sections = {name: [] for name in SECTIONS.values()}
                commands = []
                cursor = entry
                for _ in range(128):
                    command = word(cursor)
                    cursor += 4
                    if command == 0:
                        break
                    mode = 0
                    if command & 0xFFFF0000 == 0xFFFF0000:
                        mode = (command & 0xFFFF) // 0x1000
                        if mode not in range(5) or (command & 0xFFF):
                            raise ValueError(f"Unknown native script command {command:#x}")
                        command = word(cursor)
                        cursor += 4
                    commands.append({"mode": mode, "argument": command})
                    if mode == 0 and command:
                        i = offset(command)
                        section = "primary"
                        for _ in range(1024):
                            value = executable[i]
                            i += 1
                            if value == 0xFF:
                                break
                            if value in SECTIONS:
                                section = SECTIONS[value]
                            else:
                                sections[section].append(value)
                        else:
                            raise ValueError("Native part list has no terminator")
                else:
                    raise ValueError("Native script has no terminator")
                primary, extra = sections["primary"], sections["extra"]
                if primary and len(primary) != 15:
                    raise ValueError(f"Slot {slot} costume {costume} has {len(primary)} primary parts")
                if extra and len(extra) != 2:
                    raise ValueError(f"Slot {slot} costume {costume} has {len(extra)} extra parts")
                file_ids = struct.unpack_from("<5H", executable,
                                              offset(FILE_TABLE + costume * 250 + slot * 10, 10))
                files = {name: filename(i) for name, i in
                         zip(("control", "textures", "geometry", "morph", "skin"), file_ids)}
                record["costumes"].append({"costume": costume, "script_address": entry,
                                           "files": files,
                                           "sections": sections, "commands": commands,
                                           "emit_models": primary + extra})
            else:
                raise ValueError("Native costume table has no terminator")
        slots.append(record)
    return slots


def render_part_mapping(executable: bytes, slot: int, costume: int) -> dict:
    """Strict selected native binding; empty placeholder entries are rejected."""
    if not 0 <= slot < 25 or costume < 0:
        raise ValueError("Invalid native render slot/costume")
    records = parse_render_scripts(executable)[slot]["costumes"]
    if costume >= len(records) or not records[costume]["sections"]["primary"]:
        raise ValueError("This native slot/costume has no verified body part assignment")
    return records[costume]


def resolve_archive_binding(executable: bytes, archive: str) -> dict:
    """Resolve an actual CHR path through the native resource table.

    Script-only aliases 19..22 use Zack files with incompatible proxy maps
    and are not selected when resolving an owned costume archive.
    """
    name = archive.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not name.endswith(".chr"):
        raise ValueError("Native archive binding requires a CHR filename")
    matches = []
    for slot in parse_render_scripts(executable):
        if slot["slot"] in (19, 20, 21, 22):
            continue
        for entry in slot["costumes"]:
            if entry["files"]["geometry"] == name and entry["sections"]["primary"]:
                matches.append({**entry, "render_slot": slot["slot"]})
    if len(matches) != 1:
        raise ValueError(f"Archive {name} has {len(matches)} verified native body bindings")
    return matches[0]


def neutralize_accessory_init(executable: bytes, slot: int, costume: int) -> tuple[bytes, dict]:
    """Skip ACS cloth initialization while preserving subsequent script commands.

    FUN_8c0dcfe8 takes FFFF0000 + null as an empty mode-zero list and proceeds
    to the next command. This keeps later material/accessory directives intact.
    Native SUP seams and APV morphs must independently be disabled in their files.
    """
    binding = render_part_mapping(executable, slot, costume)
    output = bytearray(executable)
    cursor = binding["script_address"] - BASE
    changes = []
    for command in binding["commands"]:
        word = struct.unpack_from("<I", executable, cursor)[0]
        explicit = word & 0xFFFF0000 == 0xFFFF0000
        if command["mode"] == 2:
            if word != 0xFFFF2000 or command["argument"] != 0:
                raise ValueError("Unexpected native cloth initialization command layout")
            struct.pack_into("<I", output, cursor, 0xFFFF0000)
            changes.append({"file_offset": cursor, "ram_address": BASE + cursor,
                            "original": word, "replacement": 0xFFFF0000})
        cursor += 8 if explicit else 4
    return bytes(output), {"supplement": "ACS initialization", "render_slot": slot,
                           "render_costume": costume,
                           "policy": "original cloth initialization replaced with empty list",
                           "original_sha256": hashlib.sha256(executable).hexdigest(),
                           "patched_sha256": hashlib.sha256(output).hexdigest(),
                           "changed_bytes": sum(a != b for a, b in zip(executable, output)),
                           "changes": changes}
