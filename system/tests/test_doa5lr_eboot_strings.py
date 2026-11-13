"""Focused checks for gbox.doa5lr_eboot_strings against the cached EBOOT.elf."""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import doa5lr_eboot_strings as M

EBOOT = os.environ.get("DOA5LR_EBOOT", M.EBOOT_CACHE)
_data = None


def _load():
    global _data
    if _data is None:
        assert os.path.exists(EBOOT), f"EBOOT.elf cache missing: {EBOOT}"
        with open(EBOOT, "rb") as f:
            _data = f.read()
    return _data


def test_identity():
    data = _load()
    assert len(data) == M.EBOOT_SIZE
    assert hashlib.sha256(data).hexdigest() == M.EBOOT_SHA256


def test_locators_and_absence():
    r = M.locate(_load())
    for name, v in r.items():
        if "match_at_expected" in v:
            assert v["match_at_expected"], f"{name}: bytes at {v['expected_offset']:#x} != locator"
        else:
            assert v["absent"], f"{name} unexpectedly present"


def test_target_second_table_tail():
    data = _load()
    off = 0x010ED69C
    n = len(M.TARGET_NAME_PREFIX)
    assert data[off : off + n] == M.TARGET_NAME_PREFIX.encode()
    assert data[off + n : off + n + 15] == b"DBSH17O{TEAL71M"
    assert data[off + n + 15] == 0


def test_verify_helper():
    assert M.verify(_load()) is True


if __name__ == "__main__":
    for fn in (test_identity, test_locators_and_absence, test_target_second_table_tail, test_verify_helper):
        fn()
        print("PASS", fn.__name__)
    print("ALL PASS")
