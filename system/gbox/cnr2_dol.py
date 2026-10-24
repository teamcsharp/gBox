"""DOL (GameCube/Wii executable) header parsing plus a PowerPC cross-reference probe.

This module exists for the CNR2 (game_id 00063327fc44eced) FPK loader analysis:
the FPK container loader lives in ``DATA/sys/main.dol`` and references its
container format strings, so the analysis needs the runtime load address of
every DOL section and the code sites that materialise those addresses.

The probe is deliberately small and dependency free:

* parse the 0x100 byte big-endian DOL header,
* flatten the loaded sections into one image indexed by runtime address,
* report whether the header is self-consistent, and
* scan the text sections for PowerPC ``lis``/``addi`` and ``lis``/``ori``
  address-materialisation pairs that reference a given target address.

Header layout (Wii / GameCube DOL, 0x100 bytes, big endian u32 words).
The word groups are *not* interleaved per section; they are grouped by kind::

    word  0.. 6   text section file offsets
    word  7..17   data section file offsets
    word 18..24   text section load addresses
    word 25..35   data section load addresses
    word 36..42   text section sizes
    word 43..53   data section sizes
    word 54       bss address
    word 55       bss size
    word 56       entry point

The owned CNR2 disc copy of ``main.dol`` is a *plaintext* DOL: its sections are
file-contiguous and its load addresses are contiguous in RAM, so
``dol_header_is_consistent`` returns True for it.  Nothing here asserts loader
semantics: checksum-word handling and ``stored == size`` raw-entry behaviour
stay hypotheses until native decompilation confirms them.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

DOL_HEADER_SIZE = 0x100
NUM_TEXT_SECTIONS = 7
NUM_DATA_SECTIONS = 11

# Header word offsets (big endian u32 words inside the 0x100 byte header).
W_TEXT_FILE_OFFSET = 0
W_DATA_FILE_OFFSET = W_TEXT_FILE_OFFSET + NUM_TEXT_SECTIONS          # 7
W_TEXT_LOAD_ADDRESS = W_DATA_FILE_OFFSET + NUM_DATA_SECTIONS          # 18
W_DATA_LOAD_ADDRESS = W_TEXT_LOAD_ADDRESS + NUM_TEXT_SECTIONS         # 25
W_TEXT_SIZE = W_DATA_LOAD_ADDRESS + NUM_DATA_SECTIONS                 # 36
W_DATA_SIZE = W_TEXT_SIZE + NUM_TEXT_SECTIONS                         # 43
W_BSS_ADDRESS = W_DATA_SIZE + NUM_DATA_SECTIONS                       # 54
W_BSS_SIZE = W_BSS_ADDRESS + 1                                        # 55
W_ENTRY_POINT = W_BSS_SIZE + 1                                        # 56

WII_CODE_LOW = 0x80000000
WII_CODE_HIGH = 0x82000000

DEFAULT_NEEDLES: Sequence[str] = (
    "fpack/chr/%s/",
    "%s.fpk",
    "fpack",
    "chr/%s",
    "fpack -a -b",
)

CNR2_MAIN_DOL = (
    "/home/ehm_eckx/gBox_alt/gbox-cache/modbase/00063327fc44eced/disc/DATA/sys/main.dol"
)

CANDIDATE_DOL_PATHS: Sequence[str] = (
    CNR2_MAIN_DOL,
    "/home/ehm_eckx/gbox-cache/modbase/00063327fc44eced/disc/DATA/sys/main.dol",
    "/home/ehm_eckx/.hermes/cache/scratch/gbox_workdir/main.dol",
)

# PowerPC opcodes used by the probe.
OP_LIS = 0x3C000000       # addis rD, 0, imm  (used as "lis")
OP_ADDI = 0x38000000
OP_ORI = 0x60000000
OP_STDU_R1 = 0xF9000029   # stdu r1, -imm(r1)  (standard EABI function prologue)


def _sign16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def parse_dol_header(data: bytes) -> dict:
    """Return the DOL header as plain Python data.

    Raises ValueError when the buffer is too small to be a DOL.
    """
    if len(data) < DOL_HEADER_SIZE:
        raise ValueError("not a DOL: only %d bytes" % len(data))
    words = struct.unpack_from(">64I", data, 0)
    sections: List[dict] = []
    for index in range(NUM_TEXT_SECTIONS):
        sections.append(
            {
                "kind": "text",
                "index": index,
                "file_offset": words[W_TEXT_FILE_OFFSET + index],
                "load_address": words[W_TEXT_LOAD_ADDRESS + index],
                "size": words[W_TEXT_SIZE + index],
            }
        )
    for index in range(NUM_DATA_SECTIONS):
        sections.append(
            {
                "kind": "data",
                "index": index,
                "file_offset": words[W_DATA_FILE_OFFSET + index],
                "load_address": words[W_DATA_LOAD_ADDRESS + index],
                "size": words[W_DATA_SIZE + index],
            }
        )
    bss = []
    for index in range(NUM_TEXT_SECTIONS):
        address = words[W_BSS_ADDRESS + index]
        size = words[W_BSS_SIZE + index]
        if address or size:
            bss.append({"index": index, "address": address, "size": size})
    return {"sections": sections, "bss": bss, "entry_point": words[W_ENTRY_POINT]}


def present_sections(header: dict) -> List[dict]:
    """Sections that the header claims to load (non-zero address and size)."""
    return [s for s in header["sections"] if s["size"] and s["load_address"]]


def dol_header_is_consistent(data: bytes) -> bool:
    """True when the header describes sections that fit the file and Wii RAM.

    A truncated or garbage header fails this check: the random words produce
    absurd offsets, sizes and load addresses.
    """
    if len(data) < DOL_HEADER_SIZE:
        return False
    try:
        header = parse_dol_header(data)
    except (ValueError, struct.error):
        return False
    sections = present_sections(header)
    if not sections or not any(s["kind"] == "text" for s in sections):
        return False
    for section in sections:
        if section["file_offset"] + section["size"] > len(data):
            return False
        if not WII_CODE_LOW <= section["load_address"] < WII_CODE_HIGH:
            return False
    entry = header["entry_point"]
    return WII_CODE_LOW <= entry < WII_CODE_HIGH


def describe_dol(data: bytes) -> dict:
    """Human/machine readable summary of a DOL header."""
    header = parse_dol_header(data)
    sections = present_sections(header)
    base = min((s["load_address"] for s in sections), default=0)
    return {
        "file_size": len(data),
        "base_address": base,
        "entry_point": header["entry_point"],
        "consistent": dol_header_is_consistent(data),
        "sections": sections,
        "bss": header["bss"],
    }


def flatten_dol(data: bytes):
    """Flatten loaded DOL sections into one image indexed by runtime address.

    Returns ``(image_bytes, base_address, header)``.  Raises ValueError when
    the header is not self-consistent, because a bogus image would produce
    bogus cross references.
    """
    if not dol_header_is_consistent(data):
        raise ValueError("DOL header is not self-consistent (garbage or truncated)")
    header = parse_dol_header(data)
    sections = present_sections(header)
    base = min(s["load_address"] for s in sections)
    end = max(s["load_address"] + s["size"] for s in sections)
    image = bytearray(end - base)
    for section in sections:
        start = section["file_offset"]
        chunk = data[start : start + section["size"]]
        if len(chunk) != section["size"]:
            raise ValueError(
                "truncated %s section %d" % (section["kind"], section["index"])
            )
        offset = section["load_address"] - base
        image[offset : offset + section["size"]] = chunk
    return bytes(image), base, header


def find_strings(
    image: bytes, base: int, needles: Iterable[str] = DEFAULT_NEEDLES
) -> Dict[str, List[int]]:
    """Locate each needle in the flattened image, returning runtime addresses."""
    found: Dict[str, List[int]] = {}
    for needle in needles:
        raw = needle.encode("ascii")
        hits: List[int] = []
        start = image.find(raw)
        while start != -1:
            hits.append(base + start)
            start = image.find(raw, start + 1)
        found[needle] = hits
    return found


def find_ppc_xrefs(
    image: bytes,
    base: int,
    header: dict,
    targets: Iterable[int],
    lookahead: int = 8,
) -> List[dict]:
    """Find PowerPC address-materialisation pairs pointing at ``targets``.

    Handles ``lis rD, hi`` + ``addi rD, rD, lo`` and ``lis rD, hi`` +
    ``ori rD, rD, lo`` pairs inside the text sections.
    """
    wanted = set(targets)
    hits: List[dict] = []
    if not wanted:
        return hits
    for section in header["sections"]:
        if section["kind"] != "text" or not section["size"]:
            continue
        start = section["load_address"] - base
        size = section["size"]
        for offset in range(0, size - 3, 4):
            word1 = struct.unpack_from(">I", image, start + offset)[0]
            if word1 & 0xFC000000 != OP_LIS:  # lis
                continue
            dest = (word1 >> 21) & 0x1F
            high = word1 & 0xFFFF
            site = section["load_address"] + offset
            for step in range(1, lookahead + 1):
                other = offset + 4 * step
                if other + 4 > size:
                    break
                word2 = struct.unpack_from(">I", image, start + other)[0]
                opcode = word2 & 0xFC000000
                if opcode == OP_ADDI:
                    source = (word2 >> 16) & 0x1F
                    if source != dest:
                        continue
                    target = ((high << 16) + _sign16(word2 & 0xFFFF)) & 0xFFFFFFFF
                    kind = "lis+addi"
                elif opcode == OP_ORI:
                    source = (word2 >> 16) & 0x1F
                    if source != dest:
                        continue
                    target = ((high << 16) | (word2 & 0xFFFF)) & 0xFFFFFFFF
                    kind = "lis+ori"
                else:
                    continue
                if target in wanted:
                    hits.append(
                        {
                            "target": target,
                            "kind": kind,
                            "site": site,
                            "ref": section["load_address"] + other,
                            "text_section": section["index"],
                        }
                    )
    return hits


def find_function_start(image: bytes, base: int, address: int, limit: int = 0x2000) -> Optional[int]:
    """Walk backwards from ``address`` to the enclosing function prologue.

    Uses the standard PowerPC EABI prologue ``stdu r1, -imm(r1)``.  Returns the
    runtime address of the prologue, or None when no prologue is found within
    ``limit`` bytes.
    """
    offset = address - base
    if offset < 0 or offset >= len(image):
        return None
    start = max(0, offset - limit)
    # Prologue candidates are 4-byte aligned; scan backwards.
    for candidate in range(offset - (offset % 4), start - 1, -4):
        if candidate + 4 > len(image):
            continue
        word = struct.unpack_from(">I", image, candidate)[0]
        if (word & 0xFFFF0003) == OP_STDU_R1 and ((word >> 21) & 0x1F) == 1:
            return base + candidate
    return None


def group_xrefs_by_function(
    image: bytes, base: int, xrefs: Sequence[dict]
) -> List[dict]:
    """Attach the enclosing function start to every xref and group them."""
    grouped: Dict[int, dict] = {}
    for entry in xrefs:
        key = entry.get("function")
        if key is None:
            key = find_function_start(image, base, entry["site"]) or entry["site"]
            entry["function"] = key
        bucket = grouped.setdefault(
            key, {"function": key, "refs": [], "needles": [], "targets": []}
        )
        bucket["refs"].append({"site": entry["site"], "ref": entry["ref"], "kind": entry["kind"]})
        if entry.get("needle") and entry["needle"] not in bucket["needles"]:
            bucket["needles"].append(entry["needle"])
        if entry["target"] not in bucket["targets"]:
            bucket["targets"].append(entry["target"])
    return [grouped[key] for key in sorted(grouped)]


def cross_reference_dol(path: str, needles: Iterable[str] = DEFAULT_NEEDLES) -> dict:
    """Full probe: parse, flatten, locate strings and their code references."""
    blob = Path(path).read_bytes()
    image, base, header = flatten_dol(blob)
    strings = find_strings(image, base, needles)
    targets = [addr for hits in strings.values() for addr in hits]
    xrefs = find_ppc_xrefs(image, base, header, targets)
    for entry in xrefs:
        entry["needle"] = next(
            (name for name, hits in strings.items() if entry["target"] in hits), None
        )
    functions = group_xrefs_by_function(image, base, xrefs)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "file_size": len(blob),
        "base_address": base,
        "entry_point": header["entry_point"],
        "sections": present_sections(header),
        "bss": header["bss"],
        "strings": strings,
        "xrefs": xrefs,
        "functions": functions,
    }


def find_plaintext_dol(paths: Optional[Iterable[str]] = None) -> Optional[Path]:
    """First candidate path whose header is self-consistent, else None."""
    for candidate in paths or CANDIDATE_DOL_PATHS:
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            if dol_header_is_consistent(path.read_bytes()):
                return path
        except OSError:
            continue
    return None
