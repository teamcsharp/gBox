import struct
import pytest
from gbox.formats import avlz as A

@pytest.mark.parametrize('inclusive',[False,True])
def test_hand_encoded_literals_and_overlapping_reference(inclusive):
    # flag 00000111: A B C then copy six bytes from ring slot 0xfee.
    stream=b'\x07ABC\xee\xf3'
    raw=struct.pack('<II',len(stream)+(8 if inclusive else 0),9)+stream
    assert A.decompress(raw)==b'ABCABCABC'

def test_zero_initialized_ring_and_empty_stream():
    assert A.decompress_stream(b'\0\0\0',3)==bytes(3)
    assert A.decompress(struct.pack('<II',0,0))==b''

@pytest.mark.parametrize('stream,size',[(b'',1),(b'\x01',1),(b'\0\0',3),(b'\x01Agarbage',1),(b'\0',0),(b'',-1),(b'\x01A',True)])
def test_malformed_streams(stream,size):
    with pytest.raises(A.AvLzError): A.decompress_stream(stream,size)

def test_output_bound_applies_before_decoding():
    with pytest.raises(A.AvLzError): A.decompress_stream(b'\x07ABC\xee\xf3',9,max_output_size=8)

@pytest.mark.parametrize('raw',[b'',bytes(7),struct.pack('<II',100,1)])
def test_bad_header(raw):
    with pytest.raises(A.AvLzError): A.decompress(raw)
