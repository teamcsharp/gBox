"""Regression: GoldenEye body write-back must go through the writer."""
from gbox import goldeneye_swap as S


class _Entry:
    def __init__(self, name):
        self.name = name
        self.rom_offset = 0x1000
        self.rom_size = 0x100


class _GE:
    def __init__(self, names):
        self.files = [_Entry(n) for n in names]

    def file_by_name(self, name):
        for e in self.files:
            if e.name == name:
                return e
        raise KeyError(name)


def test_write_body_uses_the_writer(monkeypatch, tmp_path):
    seen = {}

    def fake_splice(ge, filename, new_data, level=9):
        seen["filename"] = filename
        seen["data"] = new_data
        return b"ROMBYTES"

    monkeypatch.setattr("gbox.goldeneye_writer.splice_file", fake_splice)
    rom = tmp_path / "rom.z64"
    rom.write_bytes(b"OLDROM")
    assert S._write_body(_GE(["CdjbondZ"]), rom, "CdjbondZ", b"BODY") == 4
    assert seen["filename"] == "CdjbondZ"
    assert seen["data"] == b"BODY"
    assert rom.read_bytes() == b"ROMBYTES"


def test_write_body_resolves_file_table_name(monkeypatch, tmp_path):
    seen = {}

    def fake_splice(ge, filename, new_data, level=9):
        seen["filename"] = filename
        return b"ROM"

    monkeypatch.setattr("gbox.goldeneye_writer.splice_file", fake_splice)
    rom = tmp_path / "rom.z64"
    S._write_body(_GE(["cdjbondZ.z"]), rom, "CdjbondZ", b"B")
    assert seen["filename"] == "cdjbondZ.z"
