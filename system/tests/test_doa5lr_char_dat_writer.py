"""Focused writer-stage acceptance for the DOA5LR char_dat writer (request #2450).

    python3 -m pytest tests/test_doa5lr_char_dat_writer.py -q

Entry-level tests use the preserved owned-source payloads; container-level
tests are skipped (not failed) when the owned PS3 source is not mounted.
"""
import hashlib
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gbox import doa5lr_char_dat  # noqa: E402
from gbox.doa5lr_char_dat_writer import (  # noqa: E402
    WriterError,
    container_sha256,
    encode_noop,
    replace_entry_in_container,
)

SAMPLE18 = "/home/ehm_eckx/gBox_alt/gbox-cache/research/doa5lr_samples_2450/char_entry_0018.payload.bin"
SAMPLE940 = os.path.join(ROOT, "inventory", "doa5lr", "evidence", "char_entry_0940.char_dat")
USRDIR = os.environ.get(
    "DOA5LR_USRDIR",
    "/home/ehm_eckx/gbox-cache/research/doa5lr_samples_2450/"
    "extract/Dead or Alive 5 - Last Round (Japan)/PS3_GAME/USRDIR",
)
LINK = os.path.join(USRDIR, "chara_common.lnk")
INDEX = os.path.join(USRDIR, "chara_common.bin")
TARGET = 18
ENTRY_SHA = "d0b7226709bdd4c8a266fdc7d4ac140efa1ce6df519ed8967acc47a4235972e6"
ENTRY_SIZE = 58484
CONTAINER_SHA = "02af8aef6511d56e2b9179d0ee3d18521b8a3e2395f452aacf132f21c8931c18"
SCRATCH = "/home/ehm_eckx/.hermes/cache/scratch/doa5lr_writer_2450"


def _load(path):
    return open(path, "rb").read()


def test_encode_noop_entry0018_byte_exact():
    d = _load(SAMPLE18)
    assert len(d) == ENTRY_SIZE
    out = encode_noop(d)
    assert out == d
    assert hashlib.sha256(out).hexdigest() == ENTRY_SHA
    # re-parsed model is identical to the original
    a = doa5lr_char_dat.parse_char_dat(d)
    b = doa5lr_char_dat.parse_char_dat(out)
    assert a["section_ptrs"] == b["section_ptrs"]
    assert a["ptable"] == b["ptable"]
    assert a["geometry_table"] == b["geometry_table"]
    assert a["texture_table"] == b["texture_table"]
    assert a["sections"] == b["sections"]


def test_encode_noop_entry0940_byte_exact():
    d = _load(SAMPLE940)
    out = encode_noop(d)
    assert len(out) == 7357824
    assert out == d


@pytest.mark.skipif(not os.path.exists(LINK), reason="owned PS3 source not mounted")
def test_replace_entry_same_size_noop_container_unchanged():
    from gbox import doa5lr_chcm_extract as chcm

    assert container_sha256(LINK) == CONTAINER_SHA
    info, payload = chcm.extract_entry(TARGET, LINK, INDEX)
    assert info["sha256"] == ENTRY_SHA
    assert len(payload) == ENTRY_SIZE

    os.makedirs(SCRATCH, exist_ok=True)
    work = os.path.join(SCRATCH, "chara_common.lnk.copy")
    if os.path.exists(work):
        os.unlink(work)
    shutil.copy2(LINK, work)
    try:
        receipt = replace_entry_in_container(
            LINK, TARGET, payload, output_path=work, expected_sha256=CONTAINER_SHA
        )
        assert receipt["size"] == ENTRY_SIZE
        assert receipt["entry_sha256_before"] == ENTRY_SHA
        assert receipt["entry_sha256_after"] == ENTRY_SHA
        assert receipt["container_sha256"] == CONTAINER_SHA
        # the owned source must be untouched
        assert container_sha256(LINK) == CONTAINER_SHA
    finally:
        if os.path.exists(work):
            os.unlink(work)


@pytest.mark.skipif(not os.path.exists(LINK), reason="owned PS3 source not mounted")
def test_size_mismatch_rejected_before_write():
    d = _load(SAMPLE18)
    try:
        replace_entry_in_container(LINK, TARGET, d[:-4])
        assert False, "expected WriterError"
    except WriterError:
        pass
    # source untouched
    assert container_sha256(LINK) == CONTAINER_SHA
