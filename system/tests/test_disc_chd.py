import builtins
import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import assimilate, chd, psxdisc
from gbox.formats import disc
from matrix_synth import make_chd, make_iso


def files():
    return {'SYSTEM.CNF': b'BOOT2 = cdrom0:\\TEST_000.01;1\n',
            'TEST_000.01': b'\x7fELF' + b'executable' * 600,
            'BIG.BIN': bytes(range(256)) * 400, 'EMPTY.BIN': b''}


def v4(iso):
    # Real uncompressed v4 map and raw Mode1 frames, preserving ISO payload.
    frame, per = 2448, 8
    sectors = [bytes(15) + b'\x01' + iso[o:o+2048] + bytes(frame-16-2048)
               for o in range(0, len(iso), 2048)]
    raw = b''.join(sectors); hunk = frame*per; count = (len(raw)+hunk-1)//hunk
    raw = raw.ljust(count*hunk, b'\0')
    header = bytearray(0x6c); header[:8] = b'MComprHD'
    struct.pack_into('>IIIIIQQI', header, 8, 0x6c, 4, 0, 1, count, len(sectors)*frame, 0, hunk)
    start = len(header) + count*16
    table = b''.join(struct.pack('>QIHBB', start+i*hunk, 0, 0, 0, 2) for i in range(count))
    return bytes(header) + table + raw


@pytest.mark.parametrize('version', [4, 5])
def test_listing_dispatches_and_bounds_actual_reads(tmp_path, monkeypatch, version):
    p = tmp_path/'owned.chd'; iso=make_iso(files()); p.write_bytes(v4(iso) if version==4 else make_chd(iso))
    cls = psxdisc.PSXDisc if version==4 else chd.ChdDisc
    actual, opened = [], []
    original_read, original_close = cls.read, cls.close
    def read(self, name, offset=0, size=None):
        assert size is not None  # no whole-file read followed by slicing
        actual.append((name, offset, size))
        return original_read(self, name, offset, size)
    def close(self):
        original_close(self); opened.append(self.chd.f.closed)
    monkeypatch.setattr(cls, 'read', read); monkeypatch.setattr(cls, 'close', close)
    result = disc.listing(p, head=7, max_files=2, exe_limit=65, deep=1, deep_bytes=31)
    assert result.kind == 'iso9660' and result.executable_name == 'TEST_000.01'
    assert result.executable == files()['TEST_000.01'][:65]
    assert sum('head' in f for f in result.files) == 2
    assert next(f for f in result.files if f['path']=='BIG.BIN')['sample'] == files()['BIG.BIN'][:31]
    assert all(offset==0 and size<=max(512,65,31,7) for _,offset,size in actual)
    assert all(size<=len(files()[name]) for name,_,size in actual)
    assert opened == [True]
    assert assimilate.fingerprint_path(p, platform='ps2', head=7, deep=0)['executable']=='TEST_000.01'


def test_v4_bounded_reads_preserve_full_read_and_offset_behavior(tmp_path):
    p=tmp_path/'v4.chd';p.write_bytes(v4(make_iso(files())))
    d=psxdisc.PSXDisc(p)
    try:
        assert d.read('BIG.BIN') == files()['BIG.BIN']
        assert d.read('BIG.BIN', 2040, 32) == files()['BIG.BIN'][2040:2072]
        assert d.read('EMPTY.BIN', 0, 0) == b''
        with pytest.raises(ValueError):d.read('BIG.BIN', -1, 2)
        with pytest.raises(ValueError):d.read('BIG.BIN', len(files()['BIG.BIN']), 1)
    finally:d.close()


@pytest.mark.parametrize('version', [4,5])
def test_reader_handles_close_on_bad_header_and_bad_filesystem(tmp_path, monkeypatch, version):
    p=tmp_path/'bad.chd'; real_open=builtins.open; handles=[]
    def tracked(*a,**k):
        stream=real_open(*a,**k);handles.append(stream);return stream
    monkeypatch.setattr(builtins,'open',tracked)
    cls=psxdisc.PSXDisc if version==4 else chd.ChdDisc
    p.write_bytes(b'MComprHD' + struct.pack('>II', 124 if version==5 else 108, version))
    with pytest.raises((ValueError,struct.error,AssertionError,chd.ChdError)):cls(p)
    assert handles and all(f.closed for f in handles)
    handles.clear(); iso=bytearray(make_iso(files()));iso[16*2048+1:16*2048+6]=b'BADFS'
    p.write_bytes(v4(iso) if version==4 else make_chd(iso))
    with pytest.raises((ValueError,AssertionError,chd.ChdError)):cls(p)
    assert handles and all(f.closed for f in handles)


@pytest.mark.parametrize('version',[4,5])
def test_listing_closes_reader_when_population_raises(tmp_path,monkeypatch,version):
    p=tmp_path/'disc.chd';iso=make_iso(files());p.write_bytes(v4(iso) if version==4 else make_chd(iso))
    cls=psxdisc.PSXDisc if version==4 else chd.ChdDisc;closed=[];original=cls.close
    def close(self):original(self);closed.append(self.chd.f.closed)
    monkeypatch.setattr(cls,'close',close)
    def broken(*a):raise RuntimeError('listing aborted')
    monkeypatch.setattr(disc,'_populate',broken)
    with pytest.raises(RuntimeError,match='listing aborted'):disc.listing(p)
    assert closed==[True]


@pytest.mark.parametrize('data',[b'',b'wrong!!!'+bytes(8),b'MComprHD'+struct.pack('>II',124,6)])
def test_dispatch_rejects_invalid_or_unknown_headers(tmp_path,data):
    p=tmp_path/'bad.chd';p.write_bytes(data)
    with pytest.raises(ValueError):disc.listing(p)


@pytest.mark.parametrize('kw',[{'head':-1},{'max_files':-1},{'deep':-1},{'deep_bytes':-1},{'exe_limit':-1},{'head':True}])
def test_invalid_limits_rejected_before_open(tmp_path,kw):
    with pytest.raises(ValueError,match='nonnegative integer'):disc.listing(tmp_path/'missing.chd',**kw)


OWNED_DMC2 = Path(os.environ['GBOX_DMC2_PS2_CHD']) if os.environ.get('GBOX_DMC2_PS2_CHD') else None


@pytest.mark.skipif(OWNED_DMC2 is None or not OWNED_DMC2.exists(), reason='owned DMC2 Disc1 CHD not configured')
def test_owned_dmc2_fingerprint_reads_exact_executable_and_afs():
    result=disc.listing(OWNED_DMC2)
    assert len(result.files)==9 and result.executable_name=='SLUS_204.84'
    assert hashlib.sha256(result.executable).hexdigest()=='09040e703963acd105a8f52e72f850dd8c179d5b57934dfca70e4db763f422f0'
    fingerprint=assimilate.fingerprint_listing(result,platform='ps2',title='Devil May Cry 2 (USA) (Disc 1)')
    assert fingerprint['strings_checked']==4134
    assert any(row['id']=='afs' and row['files']>=3 for row in fingerprint['containers'])
