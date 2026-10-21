"""Inventory acceptance for the owned Crazy Taxi (USA) GameCube build (request #2513).

Five focused checks, all executed against the owned source before being committed:
hash the real ISO, confirm the GCTE51 disc and container hashes, count the shape
bank, parse every shape, and confirm the four driver rig slots plus the identified
native target asset. Constants come from gbox.crazy_taxi so a wrong owned build fails.

The full-disc checks stream the owned ISO, so they skip when this machine does not
hold it; the bank/bank-derived checks run against a pre-extracted bank file when
GBOX_CT_BANK is set, which lets CI cover the reader without the disc.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import gbox.crazy_taxi as ct

def _owned_iso() -> Path:
    """The owned disc: GBOX_CT_ISO overrides, then the two known cache roots (this
    worker's gBox_alt cache and the prime Spark's gbox-cache). A wrong hardcoded
    path made the whole suite skip silently - see request #2513."""
    env = os.environ.get("GBOX_CT_ISO")
    for candidate in (Path(env) if env else None,
                      Path("/home/ehm_eckx/gBox_alt/gbox-cache/modbase/bc02bb68790ce2e7/"
                           "Crazy Taxi (USA).iso"),
                      Path("/home/ehm_eckx/gbox-cache/modbase/bc02bb68790ce2e7/"
                           "Crazy Taxi (USA).iso")):
        if candidate is not None and candidate.is_file():
            return candidate
    return Path("/nonexistent/Crazy Taxi (USA).iso")


ISO_PATH = _owned_iso()
BANK_ENV = "GBOX_CT_BANK"

EXPECTED_SHAPES = 1586
EXPECTED_VERTICES = 46532
EXPECTED_TRIANGLES = 72084
EXPECTED_DRIVER_TRIS = {"axel": 393, "bd_joe": 506, "gena": 555, "gus": 583}
TARGET = "MP_YH_plyrA_atama.shp"
TARGET_SIZE = 2912
TARGET_VERTS = 64
TARGET_TRIS = 77


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stream_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bank_bytes() -> bytes:
    env = os.environ.get(BANK_ENV)
    if env:
        return Path(env).read_bytes()
    if not ISO_PATH.is_file():
        pytest.skip(f"owned ISO not on this machine: {ISO_PATH}")
    from gbox.gcdisc import GCDisc

    return GCDisc(ISO_PATH).read(ct.BANK)


requires_iso = pytest.mark.skipif(not ISO_PATH.is_file(), reason=f"owned ISO absent: {ISO_PATH}")


@requires_iso
def test_owned_iso_identity():
    """The owned disc is byte-identical to the checkpointed source hash."""
    assert _stream_sha256(ISO_PATH) == ct.ISO_SHA256


@requires_iso
def test_disc_header_and_container_hashes():
    """GCTE51 disc 0 rev 0; main.dol / polDC0.all / motDC.bin match module constants."""
    from gbox.gcdisc import GCDisc

    disc = GCDisc(ISO_PATH)
    assert disc.game_id == ct.DISC_ID == "GCTE51"
    dol = disc.dol()
    assert len(dol) == 2_190_496 and _sha256_bytes(dol) == ct.DOL_SHA256
    bank = disc.read(ct.BANK)
    assert len(bank) == 2_555_360 and _sha256_bytes(bank) == ct.BANK_SHA256
    motion = disc.read(ct.MOTION)
    assert len(motion) == 2_854_048 and _sha256_bytes(motion) == ct.MOTION_SHA256


def test_shape_bank_count_and_blob_bounds():
    """read_bank counts 1586 records and the blob region ends exactly at EOF."""
    bank = _bank_bytes()
    records = ct.read_bank(bank)
    assert len(records) == EXPECTED_SHAPES
    assert max(off + size for _n, off, size in records) == len(bank)


def test_every_shape_record_parses():
    """All 1586 shapes decode with zero failures and the checkpointed geometry totals."""
    bank = _bank_bytes()
    vertices = triangles = 0
    for name, off, size in ct.read_bank(bank):
        shape = ct.read_shape(bank[off:off + size], name)
        vertices += len(shape.pos)
        triangles += len(shape.tris)
    assert (vertices, triangles) == (EXPECTED_VERTICES, EXPECTED_TRIANGLES)


def test_driver_rigs_complete_and_target_asset():
    """60/60 driver parts present with checkpointed triangle totals; MP_YH_plyrA_atama
    is the identified native head target (2912 B, 64 verts, 77 tris, white.tex)."""
    bank = _bank_bytes()
    entries = ct.read_bank(bank)
    inv = ct.inventory(bank)
    for slug, tris in EXPECTED_DRIVER_TRIS.items():
        parts = inv["drivers"][slug]["parts"]
        assert len(parts) == len(ct.PARTS) == 15, (slug, sorted(parts))
        assert inv["drivers"][slug]["tris"] == tris
    by = {n: (o, s) for n, o, s in entries}
    off, size = by[TARGET]
    assert size == TARGET_SIZE
    shape = ct.read_shape(bank[off:off + size], TARGET)
    assert (len(shape.pos), len(shape.tris)) == (TARGET_VERTS, TARGET_TRIS)
    assert "white.tex" in shape.textures
