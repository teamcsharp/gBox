"""Native body/ACS cross-table associations must replace filename guesses."""
import pytest
from .. import source_binding as F


class OwnedDisc:
    def __init__(self,files):self.files=files


def fixture(monkeypatch):
    bodies=[{'files':{'geometry':name},'sections':{'primary':[1]}} for name in ('jan01.chr','jan02.chr','bay02.chr')]
    monkeypatch.setattr(F.B,'parse_render_scripts',lambda data:[{'slot':2,'costumes':bodies},
        {'slot':19,'costumes':[{'files':{'geometry':'proxy.chr'},'sections':{'primary':[1]}}]}])
    monkeypatch.setattr(F.B,'resolve_archive_binding',lambda data,name:{'render_slot':2,'costume':1 if name.startswith('jan02') else 0})
    monkeypatch.setattr(F.B,'accessory_filename',lambda data,slot,costume:{'filename':'shared01.acs','render_slot':slot,'render_costume':costume},raising=False)
    return OwnedDisc(['DOA2/JAN01.CHR','DOA2/JAN02.CHR','DOA2/BAY02.CHR','DOA2/SHARED01.ACS'])


def test_every_native_archive_is_enumerated_without_suffix_acs_file(monkeypatch):
    result=F.costumes(fixture(monkeypatch),b'owned-test')
    assert [r['stem'] for r in result]==['BAY02','JAN01','JAN02']
    assert {r['acs_path'] for r in result}=={'DOA2/SHARED01.ACS'}
    assert result[-1]['native_acs_binding']['render_costume']==1


def test_missing_or_ambiguous_native_file_is_rejected(monkeypatch):
    disc=fixture(monkeypatch);disc.files.remove('DOA2/SHARED01.ACS')
    with pytest.raises(ValueError,match='one owned'):F.costumes(disc,b'owned-test')
    disc.files+=['DOA2/SHARED01.ACS','doa2/shared01.acs']
    with pytest.raises(ValueError,match='one owned'):F.costumes(disc,b'owned-test')


def test_missing_native_resolver_cannot_fall_back_to_suffix(monkeypatch):
    monkeypatch.delattr(F.B,'accessory_filename',raising=False)
    with pytest.raises(ValueError,match='update the binding module'):
        F.native_acs(b'owned-test',{'render_slot':2,'costume':1})


def test_unavailable_native_declaration_is_recorded_without_fabricated_archive(monkeypatch):
    disc=fixture(monkeypatch);disc.files.remove('DOA2/BAY02.CHR')
    available=F.costumes(disc,b'owned-test')
    assert [r['stem'] for r in available]==['JAN01','JAN02']
    declared=F.costumes(disc,b'owned-test',include_unavailable=True)
    assert len(declared)==3 and declared[0]['available'] is False
    assert declared[0]['chr_path'] is None and declared[0]['missing_sources']==['bay02.chr']
