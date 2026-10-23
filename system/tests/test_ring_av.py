"""Replay AV preserves isolated emulator PCM and remains bounded during autoplay."""
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import ring_record as R
from test_ring_record import make_ring, filled_ring, emit, Popen


def test_autoplay_records_without_faking_operator_activity_and_stops_after_controller_ends(tmp_path, monkeypatch):
    thread = SimpleNamespace(is_alive=lambda: True)
    driver = SimpleNamespace(stopped=False)
    monkeypatch.setitem(sys.modules, 'gbox.tools', SimpleNamespace(AUTOPLAY={'w-1': {'thread': thread, 'driver': driver}}))
    ring, _, touch = make_ring(tmp_path)
    assert touch == [0.]
    ring.tick(1000.)
    assert ring.proc is not None and ring.status(1000.)['activity'] == 'autoplay'
    driver.stopped = True
    ring.tick(1001.)
    assert ring.proc is None and touch == [0.]


class Tap:
    def __init__(self): self.closed = False
    def alive(self): return not self.closed
    def take(self, size): return b''
    def close(self): self.closed = True


def test_isolated_audio_gets_a_single_pcm_input_and_aac_without_an_or_mic(tmp_path, monkeypatch):
    if os.name != 'posix': pytest.skip('inherited PCM fd is a POSIX capture path')
    threads = []
    monkeypatch.setattr(R.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: threads.append(kw)))
    ring, _, touch = make_ring(tmp_path)
    tap = Tap(); ring.audio_fn = lambda: tap; touch[0] = 1000.
    ring.tick(1000.)
    argv = ring.cur['argv']
    assert '-an' not in argv and '1:a:0' in argv and argv[argv.index('-c:a')+1] == 'aac'
    assert argv.count('-ac') == 2 and '128k' in argv
    assert not any('default' == v or 'microphone' in str(v) for v in argv)
    assert ring.cur['audio'] and len(threads) == 1
    # No child was created by this fixture, so close the test writer's owned fd.
    os.close(threads[0]['args'][1])
    ring.end(); assert tap.closed


def test_delayed_emulator_audio_restarts_only_the_owned_ring_and_retains_audio_identity(tmp_path, monkeypatch):
    if os.name != 'posix': pytest.skip('inherited PCM fd is a POSIX capture path')
    threads=[]
    monkeypatch.setattr(R.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: threads.append(kw)))
    ring, _, touch = make_ring(tmp_path)
    tap=Tap(); available=[False]; ring.audio_fn=lambda:tap if available[0] else None;touch[0]=1000.
    ring.tick(1000.);first=ring.proc;assert not ring.cur['audio']
    available[0]=True;ring.tick(1005.1)
    assert ring.proc is not first and first.stdin.data == b'q' and ring.cur['audio']
    assert ring.status(1005.1)['audio']
    os.close(threads[0]['args'][1]);ring.end()


def test_audio_writer_forwards_only_real_pcm_and_never_fills_gaps_with_fake_silence(tmp_path):
    if os.name != 'posix': pytest.skip('POSIX audio writer')
    ring, _, _ = make_ring(tmp_path);token=object();ring.proc=token
    pcm=struct.pack('<8h',1,2,3,4,5,6,7,8)
    class Once:
        used=False
        def alive(self): return not self.used
        def take(self,n): self.used=True;return pcm
    rd,wr=os.pipe();ring._write_audio(token,wr,Once())
    try: assert os.read(rd,1000) == pcm
    finally: os.close(rd);ring.proc=None


def test_av_export_reserves_audio_bitrate_and_drops_video_only_boot_prefix(tmp_path):
    ring, clock, _ = filled_ring(tmp_path)
    ring.run = subprocess.run
    for seg in ring.segments[2:]: seg['audio']=True
    result=ring.export(180,target_mb=1)
    assert result['audio'] is True and result['audio_source'] == 'isolated emulator playback'
    assert result['seconds'] == 20
    assert result['kbps'] == R.video_kbps(1,20,cap_kbps=ring.kbps,audio_kbps=128)
    result['file'].unlink()


def test_real_av_export_contains_decodable_video_and_audio(tmp_path):
    ff=shutil.which('ffmpeg')
    if not ff: pytest.skip('ffmpeg not installed')
    ring, _, _=make_ring(tmp_path,encoder='libx264')
    segment=ring.dir/'actual.ts'
    made=subprocess.run([ff,'-v','error','-f','lavfi','-i','testsrc2=s=320x240:r=30',
        '-f','lavfi','-i','sine=frequency=660:sample_rate=48000','-t','3','-c:v','libx264','-threads','2',
        '-c:a','aac','-f','mpegts',str(segment)],capture_output=True,timeout=30)
    assert made.returncode == 0,made.stderr
    ring.ffmpeg=[ff];ring.run=subprocess.run;ring.encoder={'encoder':'libx264','note':'test'}
    ring.segments=[{'file':segment,'start':0.,'end':3.,'bytes':segment.stat().st_size,'run':1,'idx':0,'size':[320,240],'audio':True}]
    result=ring.export(180,target_mb=1)
    decoded=subprocess.run([ff,'-v','error','-i',str(result['file']),'-map','0:v:0','-map','0:a:0','-f','null','-'],capture_output=True,timeout=30)
    assert decoded.returncode == 0,decoded.stderr
    assert result['audio'] and result['seconds'] == 3.
