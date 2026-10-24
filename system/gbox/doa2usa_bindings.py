"""DOA2 (USA) 1ST_READ.BIN resource-name table — analysis-stage derivation.

The USA T-3601N V1.100 build (game 5f08ad9a86ebcc9a) is a *different* executable
than the DOA2 Limited Edition (T3601M V1.002) that ``doa2_bindings`` is pinned to.
Re-running the LE-pinned collector on it fails with "part script addresses are
version-specific" because the tables are not a simple address re-map:

* the USA name table carries a ``c:/doa2/`` path prefix on every resource name
  (LE names are bare ``kas00.chr``), and
* USA file records are six u16 indices (LE: five), but as in LE the FILE_TABLE
  sits immediately after FILE_NAMES (0x141264 + 4*642 = 0x141C6C).

This module derives the USA name table from the owned executable and resolves its
642-name roster. It also decodes the fighter file table and ACS table; it deliberately does *not*
invent the part SCRIPT_TABLE address: that is the next analysis step (Ghidra xref of the script-loading
function; the USA script-data region is already narrowed to ~0x1A9450-0x1A9DE0).

    python - <<'PY'
    from gbox.gdrom import GDRom
    from gbox import doa2usa_bindings as b
    exe = GDRom("disc.gdi").read("1ST_READ.BIN")
    assert b.locate_file_names(exe) == b.USA_FILE_NAMES_OFFSET
    names = b.resource_names(exe)
    print(len(names), names[0], names[-1])
    PY
"""
from __future__ import annotations

import hashlib
import struct

# 1ST_READ.BIN of the owned T-3601N V1.100 disc (recorded; differs from LE
# 27a014ae... whose addresses must not be reused for this build).
USA_EXECUTABLE_SHA256 = "105056d9ffef86bf5e470fa28dc5907443156f9ab1c6bc009f73661d9c047a85"
LE_EXECUTABLE_SHA256 = "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1"

# Dreamcast 1ST_READ.BIN load address.
BASE = 0x8C010000

# Verified against the owned USA executable this run:
USA_FILE_NAMES_OFFSET = 0x141264        # file offset of the name pointer table
USA_FILE_NAMES_ADDRESS = 0x8C151264     # load address (BASE + offset)
USA_NAME_COUNT = 642                    # entries in the USA name pointer table

# LE anchors (for the cross-build self-check):
LE_FILE_NAMES_OFFSET = 0x16E774
LE_NAME_COUNT = 928

RESOURCE_EXTENSIONS = (b".bin", b".chr", b".mot", b".sup", b".apv", b".acs",
                       b".mdl", b".adx", b".adt", b".pvr")
PATH_PREFIX = b"c:/doa2/"

# USA roster (select screen order). Leon (SAM) and PDG exist only on LE builds.
USA_FIGHTERS = ("KAS", "AYA", "LEI", "TIN", "BAS", "JAN", "GEN", "BAY", "RYU",
                "ZAC", "HIK", "TNG", "KTE")
USA_VARIANTS = ("LOR", "MAM", "WBA", "YTI")


def _name_at(data: bytes, offset: int, maxlen: int = 96) -> bytes | None:
    if offset < 0 or offset >= len(data) or maxlen <= 0:
        return None
    end = data.find(b"\0", offset, offset + maxlen)
    return data[offset:end] if end >= 0 else None


def is_resource_name(data: bytes, offset: int) -> bool:
    """A NUL-terminated printable string ending in a known resource extension."""
    name = _name_at(data, offset)
    if name is None or not 2 <= len(name) <= 96:
        return False
    if not all(0x20 <= b <= 0x7E for b in name):
        return False
    return any(name.lower().endswith(ext) for ext in RESOURCE_EXTENSIONS)


def locate_file_names(executable: bytes) -> int:
    """File offset of the longest run of 32-bit pointers to resource-name strings.

    The game keeps one pointer table per asset namespace (BGM, spot/light, and the
    resource FILE_NAMES). The resource table is the longest run whose every pointer
    targets a string ending in a resource extension, so this picks it out without
    any hard-coded address. Cross-validated: LE -> 0x16E774, USA -> 0x141264.
    """
    n = len(executable)
    best_start, best_len = 0, -1
    run_start, run_len = None, 0
    for o in range(0, n - 3, 4):
        p = struct.unpack_from("<I", executable, o)[0]
        if BASE <= p < BASE + n and is_resource_name(executable, p - BASE):
            run_start = o if run_start is None else run_start
            run_len += 1
        else:
            if run_len > best_len and run_start is not None:
                best_start, best_len = run_start, run_len
            run_start, run_len = None, 0
    if run_len > best_len and run_start is not None:
        best_start, best_len = run_start, run_len
    if best_len <= 0:
        raise ValueError("No resource-name pointer table found")
    return best_start


def read_names(executable: bytes, table_offset: int) -> list[bytes]:
    """Walk the name pointer table at ``table_offset`` until an invalid pointer."""
    n = len(executable)
    names: list[bytes] = []
    if table_offset < 0 or table_offset % 4 or table_offset + 4 > n:
        raise ValueError("Invalid resource-name table offset")
    while table_offset + (len(names) + 1) * 4 <= n:
        p = struct.unpack_from("<I", executable, table_offset + len(names) * 4)[0]
        if not (BASE <= p < BASE + n):
            break
        name = _name_at(executable, p - BASE)
        if name is None or not is_resource_name(executable, p - BASE):
            break
        names.append(name)
    return names


def bare(name: bytes) -> bytes:
    """Strip the USA ``c:/doa2/`` path prefix and lower-case (LE names are already bare)."""
    if name.lower().startswith(PATH_PREFIX):
        return name[len(PATH_PREFIX):].lower()
    return name.lower()


def resource_names(executable: bytes) -> list[bytes]:
    """Bare (lower-case, path-stripped) resource names for the owned executable."""
    return [bare(n) for n in read_names(executable, locate_file_names(executable))]


def fighter_families(names: list[bytes]) -> dict[str, list[str]]:
    """Prefix -> costume numbers, e.g. ``{"KAS": ["00", "01", ...]}``."""
    import re
    fam: dict[str, set[str]] = {}
    for n in names:
        m = re.match(rb"^([a-z]+)(\d+)\.chr$", n)
        if m:
            fam.setdefault(m.group(1).decode().upper(), set()).add(m.group(2).decode())
    return {k: sorted(v, key=int) for k, v in fam.items()}


# ---------------------------------------------------------------------------
# Render file table (derived this run; cross-validated against LE structure).
#
# In LE, FILE_TABLE sits immediately after the FILE_NAMES pointer table
# (FILE_NAMES + 4*928 == 0x8C17F5F4). The same contiguity holds in USA:
# 0x141264 + 4*642 == 0x141C6C. (The earlier "UTF-16 follows the table"
# claim was wrong -- the u16 index records start right at that offset.)
# USA records are six u16 name indices (12 bytes), 18 body slots x 6 costumes,
# costume-major (record = costume*18 + slot), then 20 stage records, etc.
# ---------------------------------------------------------------------------
USA_FILE_TABLE_OFFSET = USA_FILE_NAMES_OFFSET + 4 * USA_NAME_COUNT   # 0x141C6C
USA_FILE_TABLE_ADDRESS = BASE + USA_FILE_TABLE_OFFSET
USA_RECORD_FIELDS = ("control", "motion", "textures", "geometry", "skin", "sup")
USA_RECORD_SIZE = 12
USA_SLOT_ORDER = ("ZAC", "TIN", "JAN", "KTE", "RYU", "KAS", "GEN", "HIK", "BAY",
                  "BAS", "MAM", "RAI", "LEI", "AYA", "WBA", "IND", "LOR", "TNG")
USA_COSTUME_COUNT = 6
USA_FIGHTER_RECORDS = len(USA_SLOT_ORDER) * USA_COSTUME_COUNT        # 108
# Accessory (.acs) table: plain 6 x 18 u16 name indices (36-byte rows), directly
# after the stage/voice/movie records.
USA_ACS_TABLE_OFFSET = USA_FILE_TABLE_OFFSET + 150 * USA_RECORD_SIZE + 4  # 0x142378


def _check_usa(executable: bytes) -> None:
    if hashlib.sha256(executable).hexdigest() != USA_EXECUTABLE_SHA256:
        raise ValueError("Unsupported DOA2 executable: part script addresses are version-specific")


def parse_file_table(executable: bytes) -> list[dict]:
    """Resolve the 108 fighter file records to bare file names.

    Returns one dict per (slot, costume): slot index/code, costume, and the six
    resolved names (control .bin, motion .mot, textures .bin, geometry .chr,
    skin .apv, sup .sup). Every index is range-checked against the name table.
    """
    _check_usa(executable)
    names = resource_names(executable)
    out = []
    for costume in range(USA_COSTUME_COUNT):
        for slot, code in enumerate(USA_SLOT_ORDER):
            rec = USA_FILE_TABLE_OFFSET + (costume * len(USA_SLOT_ORDER) + slot) * USA_RECORD_SIZE
            idx = struct.unpack_from("<6H", executable, rec)
            if any(i >= len(names) for i in idx):
                raise ValueError("USA file-table index outside the name table")
            files = {f: names[i].decode() for f, i in zip(USA_RECORD_FIELDS, idx)}
            out.append({"slot": slot, "code": code, "costume": costume,
                        "table_offset": rec, "indices": idx, "files": files})
    return out


def fighter_files(executable: bytes, slot: int, costume: int) -> dict:
    if not 0 <= slot < len(USA_SLOT_ORDER) or not 0 <= costume < USA_COSTUME_COUNT:
        raise ValueError("Invalid USA slot/costume")
    return parse_file_table(executable)[costume * len(USA_SLOT_ORDER) + slot]


def resolve_archive_binding(executable: bytes, archive: str) -> dict:
    """Resolve a CHR filename to its unique (slot, costume) record."""
    name = archive.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not name.endswith(".chr"):
        raise ValueError("Native archive binding requires a CHR filename")
    hits = [r for r in parse_file_table(executable) if r["files"]["geometry"] == name]
    if not hits:
        raise ValueError(f"Archive {name} has no native file-table binding")
    return hits[0]   # shared (placeholder) CHRs may repeat; first record wins


def accessory_table(executable: bytes) -> list[dict]:
    _check_usa(executable)
    names = resource_names(executable)
    out = []
    for costume in range(USA_COSTUME_COUNT):
        for slot, code in enumerate(USA_SLOT_ORDER):
            off = USA_ACS_TABLE_OFFSET + (costume * len(USA_SLOT_ORDER) + slot) * 2
            i = struct.unpack_from("<H", executable, off)[0]
            if i >= len(names) or not names[i].endswith(b".acs"):
                raise ValueError("USA ACS table entry is not an .acs name")
            out.append({"slot": slot, "code": code, "costume": costume,
                        "filename": names[i].decode(), "table_offset": off})
    return out


def parse_render_scripts(executable: bytes) -> list[dict]:
    """Not yet derivable: the USA SCRIPT_TABLE (part scripts) is not located.

    ``doa2_bindings.parse_render_scripts`` is pinned to the LE addresses and raises
    for this executable. The USA FILE_NAMES table is located (see module docstring),
    but its FILE_TABLE / SCRIPT_TABLE / ACS_FILE_TABLE live elsewhere (the LE
    ``FILE_NAMES + N*4`` contiguity does not hold — UTF-16 text follows the USA
    table). Reject the executable rather than emit a guessed binding.
    """
    if hashlib.sha256(executable).hexdigest() != USA_EXECUTABLE_SHA256:
        raise ValueError("Unsupported DOA2 executable: part script addresses are version-specific")
    raise NotImplementedError(
        "DOA2 USA FILE_TABLE / SCRIPT_TABLE / ACS_FILE_TABLE not yet located; "
        "next step is a Ghidra xref of the script-loading function (LE FUN_8c0dcfe8) "
        "with the script-data region narrowed to ~0x1A9450-0x1A9DE0")
