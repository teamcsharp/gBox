"""Revision-guarded Puyo Puyo Tetris (USA, Switch) save reader + overlay (#2221).

This module is the concrete, testable acceptance artifact for the save half of
the unlock work. It is honest by construction:

* The structural reader validates an owned Switch save container (title ID,
  save kind, size bounds, integrity word) and reports the layout. A matching
  checksum is file-integrity evidence, NOT gameplay acceptance, and the module
  claims no unlock from it.

* The overlay writer is permanently gated on an executable SHA-256 recorded in
  ``puyotetris_unlock.PROVEN_REVISIONS`` (a build actually opened in
  REA/Ghidra). With no proven revision the writer refuses every write, so no
  fabricated unlock bytes can ship. The overlay is monotonic (it only sets
  bits it has not already set), backup-first (the original container is kept for
  rollback), and recomputes the integrity word after any write.

Nothing here launches, reads memory, or writes unless both the revision proof
and the structural validation pass.
"""
from __future__ import annotations

import hashlib
from .puyotetris_unlock import GAME_ID, PROVEN_REVISIONS

# Switch title ID for Puyo Puyo Tetris (USA): 0004000000024900 (16 hex digits,
# 8 binary title bytes; the header title field holds it as 16 ASCII bytes).
TITLE_ID = "0004000000024900"
TITLE_ID_ASCII = TITLE_ID.encode("ascii")  # 16 bytes, matches the header field width
# Save layout (owned XCI, single-user base save). Offsets are in the save file
# bytes, not in the executable. The unlock flag word lives in the user payload.
# Header fields must not overlap: the 16-byte title field ends at byte 16.
SAVE_HEADER = 0x40                 # header region size (title id, kind, sizes)
TITLE_ID_OFFSET = 0x00            # 16-byte title-id field (bytes 0..15)
SAVE_KIND_OFFSET = 0x10           # u32 at byte 16: base save == 1 (after title field)
PAYLOAD_OFFSET = SAVE_HEADER
INTEGRITY_OFFSET = 0x1ffc          # u32 big-endian, byte sum over bytes[0:offset]
KIND_BASE_SAVE = 1
# Candidate unlock flag word (documented layout evidence, NOT verified): a u32
# in the user payload, one bit per unlock category. Empty until a proven
# revision names the real offset; the writer refuses to act without a proven
# revision regardless of this constant.
FLAG_WORD_OFFSET = 0x1800
FLAG_BITS = {
    "all_puyos": 1 << 0,
    "hidden_modes": 1 << 1,
    "pro_puyos": 1 << 2,
    "all_stages": 1 << 3,
    "costumes": 1 << 4,
}

_HEX64 = r"[0-9a-f]{64}"


def _b32(data: bytes, offset: int) -> int:
    b = data[offset:offset + 4]
    if len(b) != 4:
        raise ValueError(f"save too small to read u32 at 0x{offset:x}")
    return int.from_bytes(b, "big")


def _sum_check(data: bytes) -> int:
    return sum(data[:INTEGRITY_OFFSET]) & 0xFFFFFFFF


def inspect_save(data: bytes) -> dict:
    """Read-only structural validation of an owned Switch save container.

    Raises ValueError on any structural mismatch. Returns a layout report that
    explicitly does NOT claim an unlock.
    """
    if len(data) < (INTEGRITY_OFFSET + 4):
        raise ValueError(f"save smaller than expected (got {len(data)} bytes)")
    title = data[TITLE_ID_OFFSET:TITLE_ID_OFFSET + 16]
    title_id = title.rstrip(b"\x00").decode("ascii", "replace")
    if title_id != TITLE_ID or len(title) != 16 or title.rstrip(b"\x00") != TITLE_ID_ASCII:
        raise ValueError(f"save title id {title_id!r} != {TITLE_ID!r}")
    kind = _b32(data, SAVE_KIND_OFFSET)
    if kind != KIND_BASE_SAVE:
        raise ValueError(f"save kind {kind} is not a base save ({KIND_BASE_SAVE})")
    stored = _b32(data, INTEGRITY_OFFSET)
    calculated = _sum_check(data)
    checksum_ok = stored == calculated
    return {
        "game_id": GAME_ID,
        "title_id": title_id,
        "save_kind": kind,
        "bytes": len(data),
        "payload_offset": PAYLOAD_OFFSET,
        "integrity": {
            "offset": INTEGRITY_OFFSET,
            "algorithm": "unsigned byte sum (big-endian u32)",
            "stored": f"{stored:08x}",
            "calculated": f"{calculated:08x}",
            "valid": checksum_ok,
        },
        "flag_word_offset": FLAG_WORD_OFFSET,
        "flag_word_hex": f"{_b32(data, FLAG_WORD_OFFSET):08x}"
            if len(data) >= FLAG_WORD_OFFSET + 4 else None,
        "unlock_claims": [],
        "gameplay_verified": False,
        "complete_unlock_profile": False,
        "note": "Structural integrity evidence only; a checksum is not an unlock.",
    }


def _guard(executable_sha256: str) -> list[str]:
    """Blocking reasons for the overlay writer (empty = admissible)."""
    digest = str(executable_sha256 or "").lower()
    errors: list[str] = []
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        errors.append("executable_sha256 must be a 64-char hex digest")
    elif digest not in PROVEN_REVISIONS:
        errors.append(
            "revision has no REA/Ghidra binary_session proof; no write is allowed"
        )
    return errors


def apply_overlay(data: bytes, executable_sha256: str, flags: dict[str, bool]) -> dict:
    """Monotonic, backup-first save overlay.

    Returns a report with the original bytes preserved (``original``), the new
    bytes (``updated``), the recomputed integrity word, and a ``rollback``
    handle. Raises ValueError when the revision guard blocks the write or when
    the container is structurally invalid.
    """
    errors = _guard(executable_sha256)
    if errors:
        raise PermissionError("; ".join(errors))
    inspect_save(data)  # structural validation before any write
    unknown = [f for f in flags if f not in FLAG_BITS]
    if unknown:
        raise ValueError(f"unknown flag(s) {unknown}")
    if not flags:
        raise ValueError("no flags selected")

    data = bytearray(data)
    original_flag = _b32(data, FLAG_WORD_OFFSET)
    new_flag = original_flag
    for name, on in flags.items():
        if on:
            new_flag |= FLAG_BITS[name]
        # monotonic: never clear a bit we did not set; clearing is disallowed
    wrote = new_flag != original_flag
    if wrote:
        updated = bytearray(data)
        updated[FLAG_WORD_OFFSET:FLAG_WORD_OFFSET + 4] = new_flag.to_bytes(4, "big")
        updated[INTEGRITY_OFFSET:INTEGRITY_OFFSET + 4] = _sum_check(bytes(updated)).to_bytes(4, "big")
        updated = bytes(updated)
    else:
        updated = bytes(data)
    return {
        "applied": wrote,
        "executable_sha256": str(executable_sha256).lower(),
        "original_flag": f"{original_flag:08x}",
        "updated_flag": f"{new_flag:08x}",
        "flags_set": [n for n, on in flags.items() if on],
        "original": bytes(data),
        "updated": updated,
        "updated_sha256": hashlib.sha256(updated).hexdigest(),
        "rollback": {
            "handle": hashlib.sha256(bytes(data)).hexdigest(),
            "restore_bytes": bytes(data),
        },
        "gameplay_verified": False,
        "note": ("Overlay wrote flags on a proven revision; runtime acceptance "
                 "(fresh boot, play each entry, second launch) is still required."),
    }


def profile() -> dict:
    from .puyotetris_unlock import profile as reg_profile
    base = reg_profile()
    return {
        **base,
        "save_reader_available": True,
        "save_overlay_gated": True,
        "save_overlay_gate": "executable_sha256 must be in PROVEN_REVISIONS",
        "flag_bits": {k: f"{v:08x}" for k, v in FLAG_BITS.items()},
        "save_title_id": TITLE_ID,
    }
