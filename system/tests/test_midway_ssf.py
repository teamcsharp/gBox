import os, struct, pytest
from gbox.formats.midway_ssf import parse_ssf_directory, validate_ssf_directory, PpcElf

def _synth():
    ents = [(1, 0x800, 0x1000, 0), (2, 0x2000, 0x10, 0)]
    b = b"SEC " + struct.pack(">6I", 4, 0, 3, 0x14, 0x323938, 0x3000)
    for e in ents:
        b += struct.pack(">4I", *e)
    b += bytes(16)
    return b

def test_synth_dir():
    d = parse_ssf_directory(_synth())
    assert d["count"] == 2 and validate_ssf_directory(d)
    d["entries"][1]["offset"] = 0x2801
    assert not validate_ssf_directory(d)

def test_bad_magic():
    with pytest.raises(ValueError):
        parse_ssf_directory(b"XXXX" + b"\0" * 40)

ELF = os.environ.get("MKD_ELF", os.path.expanduser("~/.hermes/cache/scratch/mkd.elf"))
SSF = os.environ.get("MKD_ASHRAH_SSF", os.path.expanduser("~/.hermes/cache/scratch/ashrah.ssf"))

@pytest.mark.skipif(not (os.path.exists(ELF) and os.path.exists(SSF)), reason="owned GQNE5D files absent")
def test_real_ashrah_table_matches_ssf():
    e = PpcElf(open(ELF, "rb").read())
    t = e.file_table("ashrah_file_table")
    d = parse_ssf_directory(open(SSF, "rb").read())
    assert t["ssf"]["name"] == "ashrah.ssf" and d["count_field"] == 126 and d["count"] == len(t["sections"]) == 20 and validate_ssf_directory(d)
    offs = {(x["offset"], x["size"]) for x in d["entries"]}
    assert t["sections"][0]["name"] == "ashrah.sec"
    assert all((s["offset"], s["size"]) in offs for s in t["sections"])
    assert "HEAD_SCORPION" in e.char_names()
