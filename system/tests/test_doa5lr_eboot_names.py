import hashlib
from pathlib import Path

import pytest

from gbox import doa5lr_eboot_names as N
from gbox import doa5lr_lfmo as L

ELF = Path("/home/ehm_eckx/gBox_alt/gbox-cache/research/doa5lr_samples_2450/eboot/EBOOT.elf")
LFMO = Path("/home/ehm_eckx/gBox_alt/gbox-cache/research/doa5lr_samples_2450/lfmo_chara_common.bin")
ELF_SHA = "7747903ecdda5b686658654bcfbcd4590815f6416220e24ef458338ca446533c"


def test_extract_synthetic():
    blob = b"xx\x00BR87Y@10T10000@DD1]T]D\x00chara_dlccos_none\x00" \
           b"7S87Y@10T10000@8C1S\x00lowercase\x00"
    names = N.extract_names(blob, 0, len(blob))
    assert [n.base for n in names] == ["BR87Y", "7S87Y"]
    assert names[0].offset == 3


def test_family_census():
    c = N.family_census(["BR87Y", "7S87Y", "2Z052", "bad"])
    assert c == {"87Y": [("7", "S"), ("B", "R")], "052": [("2", "Z")]}
    with pytest.raises(ValueError):
        N.family("ABC")


@pytest.mark.skipif(not (ELF.exists() and LFMO.exists()), reason="samples not on host")
def test_real_elf_vs_lfmo():
    data = ELF.read_bytes()
    assert hashlib.sha256(data).hexdigest() == ELF_SHA
    names = N.extract_names(data)
    assert len(names) > 1000
    elf_fam = N.family_census(n.base for n in names)
    m = L.parse(LFMO.read_bytes())
    lf_fam = N.family_census(L.base_code(e.name) for e in m.entries)
    assert "87Y" in elf_fam and "87Y" in lf_fam
    # target slot 18's family is present in both sources
    assert N.family(L.base_code(m.name_at(18))) == "87Y"
    assert set(lf_fam) & set(elf_fam)
