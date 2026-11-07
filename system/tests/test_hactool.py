"""`hactool`: command construction, output parsing and refusals, without needing a Switch title or a POSIX shell.

`_run` is the one place that talks to the binary, so the tests replace it: the fake records the arguments it was given
and returns the text hactool prints, creating the files a real run would create. That pins the wrapper's real job on every
platform the project runs on.
"""
import pathlib

import pytest

from gbox import hactool as H

LISTING = """PFS0:
Magic:                              PFS0
Number of files:                    2
Files:                              pfs0:/aaaa.nca 000000000000-00030551bc00
                                    pfs0:/bbbb.nca 00030551bc00-0003055e5600
Done!
"""

EXEFS = """Saving main to exefs/main...
Saving main.npdm to exefs/main.npdm...
Done!
"""

NSO = """    Sections:
        .text:                      00000000-00656000
        .rodata:                    00656000-00ae2000
Done!
"""


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A stand-in for `_run` that records calls, returns canned output and makes the files a real run would make."""
    calls = []

    def run(args, *, timeout=3600):
        calls.append(list(args))
        joined = " ".join(args)
        if "--listfiles" in args:
            return LISTING
        if any(arg.startswith("--exefsdir=") for arg in args):
            folder = pathlib.Path(next(a.split("=", 1)[1] for a in args if a.startswith("--exefsdir=")))
            folder.mkdir(parents=True, exist_ok=True)
            for name, size in (("main", 5260), ("main.npdm", 15), ("rtld", 73), ("sdk", 5103), ("subsdk0", 3344)):
                (folder / name).write_bytes(b"x" * size)
            return EXEFS
        if any(arg.startswith("--uncompressed=") for arg in args):
            out = pathlib.Path(next(a.split("=", 1)[1] for a in args if a.startswith("--uncompressed=")))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"nso")
            return NSO
        if "--outdir" in args:
            folder = pathlib.Path(args[args.index("--outdir") + 1])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "aaaa.nca").write_bytes(b"n" * 4)
            (folder / "bbbb.nca").write_bytes(b"n" * 2)
            return ""
        return ""

    monkeypatch.setattr(H, "_run", run)
    keys = tmp_path / "prod.keys"
    keys.write_text("master_key_00 = 00\n", encoding="utf-8")
    monkeypatch.setattr(H, "keys_path", lambda: keys)
    return {"calls": calls, "keys": keys, "tmp": tmp_path}


def test_available_reports_what_is_missing_without_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "binary", lambda: None)
    monkeypatch.setattr(H, "keys_path", lambda: None)
    state = H.available()
    assert state["ready"] is False and state["hactool"] is None and "libmbedtls" in state["note"]


def test_list_files_reads_names_and_sizes(fake):
    nsp = fake["tmp"] / "title.nsp"
    nsp.write_bytes(b"PFS0")
    rows = H.list_files(nsp)
    assert [r["name"] for r in rows] == ["aaaa.nca", "bbbb.nca"]
    assert rows[0]["size"] == 0x00030551bc00
    assert rows[1]["offset"] == 0x00030551bc00
    assert "--listfiles" in fake["calls"][0] and "pfs0" in fake["calls"][0]


def test_list_files_refuses_a_missing_title_file(fake):
    with pytest.raises(H.HactoolError, match="no such title file"):
        H.list_files(fake["tmp"] / "nope.nsp")


def test_extract_exefs_unpacks_an_nsp_and_returns_its_executable(fake):
    nsp = fake["tmp"] / "title.nsp"
    nsp.write_bytes(b"PFS0")
    out = fake["tmp"] / "exefs"
    result = H.extract_exefs(nsp, out)
    assert result["main"] == "main"
    assert [row["name"] for row in result["files"]][:2] == ["main", "sdk"]      # largest first
    assert (out / "subsdk0").is_file()
    kinds = [call[:2] for call in fake["calls"]]
    assert kinds[0] == ["-t", "pfs0"] and kinds[-1] == ["-t", "nca"]          # unpack, then read the program NCA


def test_extract_exefs_takes_an_nca_directly_and_needs_only_one_call(fake):
    nca = fake["tmp"] / "program.nca"
    nca.write_bytes(b"NCA3")
    result = H.extract_exefs(nca, fake["tmp"] / "e2")
    assert result["nca"] == "program.nca" and result["main"] == "main"
    assert len(fake["calls"]) == 1


def test_extract_exefs_refuses_an_empty_result(fake):
    nca = fake["tmp"] / "program.nca"
    nca.write_bytes(b"NCA3")
    folder = fake["tmp"] / "empty"
    original = H._run
    fake_calls = []

    def run(args, *, timeout=3600):
        fake_calls.append(args)
        folder.mkdir(parents=True, exist_ok=True)
        return ""

    monkeypatch_target = H
    monkeypatch_target._run = run
    try:
        with pytest.raises(H.HactoolError, match="no exefs files"):
            H.extract_exefs(nca, folder)
    finally:
        monkeypatch_target._run = original


def test_decompress_nso_reports_the_sections(fake):
    nso = fake["tmp"] / "main"
    nso.write_bytes(b"NSO0")
    out = fake["tmp"] / "main.bin"
    result = H.decompress_nso(nso, out)
    assert out.is_file() and result["bytes"] == 3
    assert [s["name"] for s in result["sections"]] == [".text", ".rodata"]


def test_a_missing_keys_file_is_named(fake, monkeypatch):
    nsp = fake["tmp"] / "title.nsp"
    nsp.write_bytes(b"PFS0")
    monkeypatch.setattr(H, "keys_path", lambda: None)
    with pytest.raises(H.HactoolError, match="no Switch keys"):
        H.list_files(nsp)


def test_a_failed_run_becomes_a_readable_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOX_HACTOOL", str(tmp_path / "nope"))
    monkeypatch.setattr(H, "binary", lambda: None)
    with pytest.raises(H.HactoolError, match="not installed"):
        H._run(["-t", "pfs0"])
