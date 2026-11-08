"""Installing a save must be safe: never overwrite silently, always keep the previous file, always verify the copy.

The stakes are concrete - the title boots by auto-loading its save, so the wrong file does not annoy a run, it boot-loops the title
(measured: `40.2 -> 19.4`, and the prompt returns after answering Yes). Losing the operator's only unlocked save would be worse, so
the backup and the refusal are both tested.
"""
import hashlib
import os
from pathlib import Path

import pytest

from gbox import re4_switch_save as S


def make_user(tmp_path: Path, payload: bytes = b"SAVE-DATA") -> Path:
    folder = tmp_path / "nand" / "user" / "save" / "0000000000000000" / "ACCOUNT" / S.TITLE_ID / "SAVEDATA000"
    folder.mkdir(parents=True)
    (folder / S.SAVE_NAME).write_bytes(payload)
    return tmp_path


def test_status_lists_the_live_save(tmp_path):
    user = make_user(tmp_path)
    report = S.status(user)
    assert report["current"] == S.SAVE_NAME
    assert report["current_sha256"] == hashlib.sha256(b"SAVE-DATA").hexdigest()[:16]
    assert report["files"] and report["files"][0]["bytes"] == len(b"SAVE-DATA")


def test_install_refuses_to_overwrite_without_replace(tmp_path):
    user = make_user(tmp_path)
    new = tmp_path / "new.sav"
    new.write_bytes(b"NEW")
    with pytest.raises(S.SaveError):
        S.install(user, new)


def test_install_keeps_the_previous_file_and_verifies_the_copy(tmp_path):
    user = make_user(tmp_path)
    new = tmp_path / "new.sav"
    new.write_bytes(b"A-MUCH-NEWER-SAVE")
    result = S.install(user, new, replace=True)
    assert Path(result["installed"]).read_bytes() == b"A-MUCH-NEWER-SAVE"
    assert result["backup"] and Path(result["backup"]).read_bytes() == b"SAVE-DATA"
    assert result["sha256"] == hashlib.sha256(b"A-MUCH-NEWER-SAVE").hexdigest()


def test_a_missing_save_is_refused(tmp_path):
    user = make_user(tmp_path)
    with pytest.raises(S.SaveError):
        S.install(user, tmp_path / "nope.sav", replace=True)


def test_a_missing_title_folder_is_refused(tmp_path):
    with pytest.raises(S.SaveError):
        S.status(tmp_path)


def test_the_cli_reports_an_error_rather_than_raising(tmp_path):
    assert S.main(["--user", str(tmp_path)]) == 2
