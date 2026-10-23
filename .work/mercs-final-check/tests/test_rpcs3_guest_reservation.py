"""A nonzero NVIDIA/host mapping cannot stand in for RPCS3's guest while the game is still booting."""
from types import SimpleNamespace

import pytest

from gbox import adapters as A
from gbox.config import Config

BASE, HOST, OTHER = 0x300000000, 0xE22B00000000, 0x7F2000000000
CODE = b'\x7c\x08\x02\xa6'*4


def maps(base):
    return [f'{base:x}-{base+0x10000:x} ---p 00000000 00:00 0',
            f'{base+0x10000:x}-{base+0x2000000:x} r--s 00000000 00:01 5 /memfd: (deleted)',
            f'{base+0x2000000:x}-{base+(1<<32):x} ---p 00000000 00:00 0']


@pytest.mark.parametrize('path,flags', [('/dev/nvidiactl','rw-s'),('/usr/lib/libLLVM.so','r-xp'),('', 'rw-p')])
def test_nonzero_host_mapping_does_not_confirm_a_booted_guest(path,flags):
    lines=[f'{HOST+0x10000:x}-{HOST+0x30000:x} {flags} 00000000 00:07 1073 {path}']
    reads=[]
    def read(address,size):
        reads.append(address)
        return CODE if address==HOST+0x10000 else b'\0'*size
    with pytest.raises(RuntimeError,match='guest memory not found'):
        A.rpcs3_guest_base(123,read=read,maps=lines)
    assert HOST+0x10000 not in reads
    lines+=maps(BASE)
    assert A.rpcs3_guest_base(123,read=lambda address,size:CODE if address==BASE+0x10000 else b'\0'*size,maps=lines)==BASE


def test_nonstandard_fallback_requires_complete_reservation_and_full_probe():
    read=lambda address,size:CODE if address==OTHER+0x10000 else b'\0'*size
    with pytest.raises(RuntimeError):A.rpcs3_guest_base(123,read=read,maps=maps(OTHER)[:-1])
    assert A.rpcs3_guest_base(123,read=read,maps=maps(OTHER))==OTHER
    with pytest.raises(RuntimeError):A.rpcs3_guest_base(123,read=lambda a,n:b'\x01',maps=maps(OTHER))
    contaminated=maps(OTHER)
    contaminated[-1]=f'{OTHER+0x2000000:x}-{OTHER+(1<<32):x} rw-p 00000000 00:00 0'
    with pytest.raises(RuntimeError):A.rpcs3_guest_base(123,read=read,maps=contaminated)


def test_cached_host_base_is_replaced_before_any_memory_operation(tmp_path,monkeypatch):
    ad=A.RPCS3LinuxAdapter(Config(data_dir=tmp_path/'data',cache_dir=tmp_path/'cache'))
    ad.proc=SimpleNamespace(pid=123,poll=lambda:None)
    ad._mem=(123,HOST)
    finder=A.rpcs3_guest_base
    calls=[]
    def find(pid):
        calls.append(pid)
        return finder(pid,read=lambda address,size:CODE if address==BASE+0x10000 else b'\0'*size,maps=maps(BASE))
    monkeypatch.setattr(A,'rpcs3_guest_base',find)
    assert ad._guest()==(123,BASE)
    assert ad._mem_verified==(123,BASE) and calls==[123]
    assert ad._guest()==(123,BASE) and calls==[123]


def test_valid_fallback_cache_is_rechecked_and_prefers_real_guest_when_it_appears(tmp_path,monkeypatch):
    ad=A.RPCS3LinuxAdapter(Config(data_dir=tmp_path/'data',cache_dir=tmp_path/'cache'))
    ad.proc=SimpleNamespace(pid=123,poll=lambda:None)
    ad._mem=ad._mem_verified=(123,OTHER)
    ad._mem_checked_at=100.
    state={'now':100.1,'loaded':False}
    monkeypatch.setattr(A.time,'monotonic',lambda:state['now'])
    finder=A.rpcs3_guest_base
    def find(pid):
        lines=maps(OTHER)+(maps(BASE) if state['loaded'] else [])
        return finder(pid,read=lambda address,size:CODE if address in (BASE+0x10000,OTHER+0x10000) else b'\0'*size,maps=lines)
    monkeypatch.setattr(A,'rpcs3_guest_base',find)
    assert ad._guest()==(123,OTHER)
    state.update(now=101.1,loaded=True)
    assert ad._guest()==(123,BASE)
