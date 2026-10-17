import hashlib
from pathlib import Path
import struct
import pytest
from gbox import merc3d_exe as M

@pytest.mark.parametrize('word,target',[(0xe28f0074,0x10007c),(0xe28f0c01,0x100108),(0xe24f0c01,0x0fff08),(0xe28f0102,0x80100008)])
def test_arm_modified_immediate_and_subtraction(word,target):
    assert M.arm_adr_refs(struct.pack('<I',word),[(target,target+1)])==[{'site':0x100000,'target':target,'kind':'arm_adr'}]

def test_arm_unconditional_encoding_is_not_adr_or_bl():
    assert M.arm_adr_refs(struct.pack('<I',0xf28f0074),[(0,2**32)])==[]
    assert M.arm_b_bl(struct.pack('<I',0xfa000000))==[]

def test_plain_branch_is_not_reported_as_call():
    raw=struct.pack('<II',0xea000000,0xeb000000)
    assert M.arm_b_bl(raw)==[(0x100000,0x100008),(0x100004,0x10000c)]
    calls=[r for r in M.callers_of(raw,[(0x100000,0x100100)]) if r['kind']=='arm_bl']
    assert calls==[{'site':0x100004,'target':0x10000c,'kind':'arm_bl'}]

@pytest.mark.parametrize('raw,target',[(bytes.fromhex('00f000f8'),0x100004),(bytes.fromhex('fff7feff'),0x100000),(bytes.fromhex('00f400f8'),0xffd00004)])
def test_armv6_thumb_bl(raw,target):
    assert M.thumb_bl(raw)==[(0x100000,target & 0xffffffff)]

def test_thumb2_branch_form_is_not_supported_on_arm11():
    assert M.thumb_bl(bytes.fromhex('00f000d0'))==[]

def test_adr_alias_is_not_duplicated():
    refs=M.CodeImage(bytes.fromhex('00a0')).refs_to([(0x100004,0x100005)])
    assert [r['kind'] for r in refs]==['thumb_adr']

@pytest.mark.parametrize('count',[-1,65,True])
def test_invalid_roster_bound(count):
    with pytest.raises(M.ExeError):M.upl_table(b'uPl< X >\0',addr=0,base=0,max_names=count)

def test_owned_executable_targets():
    from gbox.ctr_romfs import CtrImage,blz_decompress
    source=Path.home()/'gbox-cache/3ds/0ed22ae742e1b56b/Resident Evil - The Mercenaries.3ds'
    extracted=source.parent/'inventory/code.bin'
    if extracted.exists():
        code=extracted.read_bytes()
    elif source.exists():
        with CtrImage(source) as image:
            raw=image.exefs_file('.code');code=blz_decompress(raw) if image.exheader()['code_compressed'] else raw
    else:
        pytest.skip('Owned Mercenaries executable not mounted')
    assert hashlib.sha256(code).hexdigest()=='85a34c86eb62597d89f1dc48b2e75dc7f4b25fdfeed7def086f93e875e5821be'
    site=0x4d6c68
    assert M.arm_adr_refs(code[site-M.BASE:site-M.BASE+4],[(0x4d6ce4,0x4d6ce5)],base=site)==[{'site':site,'target':0x4d6ce4,'kind':'arm_adr'}]
    rows=M.upl_table(code)
    assert len(rows)==18 and len({r["name"] for r in rows})==16
    assert rows[0]['name']=='uPl< Chris >' and rows[15]['name']=='uPl< WeskerCos2 >'
    assert rows[-1]['name']=='uPl< Jill >'
    assert all(not r['layout_verified'] and len(r['following_words'])<=4 for r in rows)


def test_names_are_candidates_not_invented_descriptor_arrays():
    raw=b'uPl< Chris >\0'.ljust(16,b'\0')+bytes.fromhex('000000eb')+b'uPl< Jill >\0'
    rows=M.upl_table(raw,addr=0,base=0)
    assert [r['name'] for r in rows]==['uPl< Chris >','uPl< Jill >']
    assert all('descs' not in r and r['layout_verified'] is False for r in rows)
    assert len(M.upl_table(raw,addr=0,base=0,max_names=1))==1
    assert M.upl_table(b'uPl< truncated >',addr=0,base=0)==[]
