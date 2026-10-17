import struct
import pytest
from gbox.formats.rarc import parse,walk,RARCError
from gbox.formats.lz import yaz0_decompress

def archive():
    # Node order root, B, A; root entry order A, B intentionally differs.
    b=bytearray(0x180);b[:4]=b'RARC'
    struct.pack_into('>4I',b,4,len(b),0x20,0x140,0x20)
    struct.pack_into('>6I',b,0x20,3,0x20,4,0x50,0x20,0xc0)
    strings=b'root\0B\0A\0a.bin\0b.bin\0'
    b[0xe0:0xe0+len(strings)]=strings
    for i,(name,count,first) in enumerate([(0,2,0),(5,1,3),(7,1,2)]):
        struct.pack_into('>4sIHHI',b,0x40+i*16,b'DIR ',name,0,count,first)
    for i,(name,flags,loc,size) in enumerate([(7,2,2,16),(5,2,1,16),(9,0x11,0,3),(15,0x11,3,3)]):
        struct.pack_into('>HHIIII',b,0x70+i*20,0,0,(flags<<24)|name,loc,size,0)
    b[0x160:0x166]=b'AAABBB'
    return b

def test_directory_indices_not_physical_order():
    b=archive();entries=walk(b)
    assert entries==[('A/a.bin',0x160,3),('B/b.bin',0x163,3)]
    assert [bytes(b[o:o+n]) for _,o,n in entries]==[b'AAA',b'BBB']

@pytest.mark.parametrize('off,value',[(4,0xffffffff),(8,0xffff),(0xc,0x160),(0x20,0xffffffff),(0x2c,0xffff),(0x30,0xffff),(0x48,0xffff),(0x78,3),(0xa0,0x1000),(0x9c,0x11ffffff)])
def test_rejects_invalid_extents_and_names(off,value):
    b=archive();struct.pack_into('>I',b,off,value)
    with pytest.raises(RARCError):walk(b)

def test_rejects_cycles():
    b=archive();struct.pack_into('>I',b,0x78,0)
    with pytest.raises(RARCError,match='cycle'):walk(b)

@pytest.mark.parametrize('n',[0,4,31,63,100,0x17f])
def test_truncated_archive(n):
    with pytest.raises(RARCError):parse(archive()[:n])

def test_yaz0_independent_literal_and_overlapping_reference():
    raw=b'Yaz0'+struct.pack('>I',9)+bytes(8)+bytes.fromhex('e04142434002')
    assert yaz0_decompress(raw,max_output=9)==b'ABCABCABC'
    with pytest.raises(ValueError,match='limit'):yaz0_decompress(raw,max_output=8)
    with pytest.raises(ValueError):yaz0_decompress(raw[:-1])

@pytest.mark.parametrize('payload,size',[(bytes.fromhex('001000'),3),(bytes.fromhex('80411000'),3),(bytes.fromhex('8041000000'),4)])
def test_yaz0_bad_reference_or_output_overrun(payload,size):
    with pytest.raises(ValueError):yaz0_decompress(b'Yaz0'+struct.pack('>I',size)+bytes(8)+payload)
