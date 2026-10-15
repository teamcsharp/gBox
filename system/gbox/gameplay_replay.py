"""Native RetroArch BSV capture on new human launches. No synthetic TAS from sampled pads."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid
import struct
import re

import httpx

_support = {}


def prepare(ad, exe, core, rom):
    if not getattr(ad,'capture_gameplay',False) or not getattr(ad.config,'gameplay_memory_enabled',True):return []
    if not getattr(ad.config,'gameplay_native_replay_enabled',False):
        ad.gameplay_replay={'state':'observations_only','reason':'Experimental native BSV capture is off pending core/save-state compatibility validation'}
        return []
    root=ad.config.runtime/'gameplay-runs';root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free < 8*2**30:
        ad.gameplay_replay={'state':'paused','reason':'Less than 8 GiB free for native gameplay capture'};return []
    # Local retained recordings have an explicit cap; never erase an unarchived run.
    if sum(p.stat().st_size for p in root.glob('*/input.bsv')) >= 20*2**30:
        ad.gameplay_replay={'state':'paused','reason':'20 GiB retained native replay budget reached'};return []
    try:
        key=(str(exe),Path(exe).stat().st_mtime_ns)
        if key not in _support:
            r=subprocess.run([str(exe),'--help'],capture_output=True,text=True,timeout=4,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            _support[key]='--bsvrecord' in r.stdout+r.stderr
        if not _support[key]:raise ValueError('This RetroArch build does not advertise --bsvrecord')
    except (OSError,ValueError,subprocess.SubprocessError) as e:
        ad.gameplay_replay={'state':'unsupported','reason':str(e)[:200]};return []
    folder=root/uuid.uuid4().hex;folder.mkdir()
    ad.gameplay_replay={'state':'starting','path':str(folder/'input.bsv'),'format':'retroarch-bsv',
                        'core':str(core),'emulator':str(exe),'content':str(rom),'started':time.time(),
                        'replay_verified':False,'capture_scope':'native inputs and native replay checkpoints; external mod actions journaled separately'}
    stat=Path(rom).stat()
    ad.gameplay_replay['content_identity']={'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,
        'sha256':None,'note':'stat fingerprint only; exact content identity not verified'}
    (folder/'manifest.json').write_text(json.dumps(ad.gameplay_replay,indent=2))
    return ['--bsvrecord='+str(folder/'input.bsv')]


def fingerprint(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def halt_owned(ad,path):
    """Stop only the replay whose identifier matches our unique file's header.
    Layout: upstream input/bsv/bsvmovie.h (v1/v2 identifier at byte 16).
    Unknown formats/interfaces fail closed; never halt a different user replay.
    """
    try:
        with path.open('rb') as f:header=f.read(40)
        if len(header)<24:return False
        magic,version=struct.unpack_from('<II',header)
        if magic!=0x42535632 or version not in (1,2):return False
        ident=struct.unpack_from('<q',header,16)[0]
        reply=ad.cmd('GET_CONFIG_PARAM active_replay',reply=True) or ''
        match=re.search(r'active_replay\s+(-?\d+)\s+(\d+)\s+(-?\d+)\s*$',reply)
        if not match or not ident or int(match[1])!=ident:return False
        ad.cmd('HALT_REPLAY');return True
    except (OSError,ValueError,struct.error):return False


def start(sid,ad,game,server,headers,alive):
    meta=getattr(ad,'gameplay_replay',None)
    if not meta:return {'state':'observations_only','reason':'No native recorder for this adapter/current launch'}
    if meta.get('state')!='starting':return meta
    meta.update(session_id=sid,game_id=game.get('game_id'),mod=game.get('mod') or '')
    path=Path(meta['path']);manifest=path.with_name('manifest.json')
    def save():manifest.write_text(json.dumps(meta,indent=2))
    def loop():
        try:
            # Native capture already runs; hashes are computed off the launch path.
            meta['core_sha256']=fingerprint(meta['core']);meta['emulator_sha256']=fingerprint(meta['emulator'])
            save()
            while alive():
                proc=getattr(ad,'proc',None)
                if proc and proc.poll() is not None:break
                if path.exists():
                    meta.update(state='recording',bytes=path.stat().st_size);save()
                    if path.stat().st_size > 256*2**20 or shutil.disk_usage(path.parent).free<4*2**30:
                        # This uniquely created command-line recording belongs to us.
                        halted=halt_owned(ad,path)
                        meta.update(state='budget_stop' if halted else 'ownership_unknown',
                            reason='Native budget reached; recording halted' if halted else 'Native budget reached but active replay ownership could not be confirmed; no stop command sent')
                        save();break
                time.sleep(5)
            # HALT our capture while the process is still present, or collect the
            # file after process exit. Never load/reset/stop the human game.
            if alive():time.sleep(1)
            if not path.exists() or path.stat().st_size<24:
                meta.update(state='failed',reason='Native recorder produced no usable file');save();return
            # A removed session entry is not proof the emulator finished writing.
            before=path.stat();time.sleep(2);after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                meta.update(state='incomplete',reason='Recording is still changing; retained locally without upload');save();return
            digest=fingerprint(path);meta.update(state='retained',sha256=digest,bytes=path.stat().st_size,replay_verified=False);save()
            if not server:return
            # Retain the worker copy even after upload. A failed network transfer
            # leaves the manifest and bytes available for explicit retry.
            for delay in (0,5,20):
                if delay:time.sleep(delay)
                try:
                    with path.open('rb') as stream:
                        r=httpx.post(server+f'/api/gameplay-memory/runs/{sid}/native',headers=headers,
                            content=iter(lambda:stream.read(1024*1024),b''),timeout=120)
                    r.raise_for_status();ref=r.json()
                    if ref.get('sha256')!=digest:raise ValueError('Native archive hash mismatch')
                    meta.update(state='archived',native_sha256=digest,native_url=ref.get('url'));save()
                    r=httpx.post(server+f'/api/gameplay-memory/runs/{sid}/observe',headers=headers,
                        json={'kind':'native_replay','token':'native:'+digest,'payload':{k:v for k,v in meta.items() if k not in ('path','core','emulator','content')}},timeout=15)
                    r.raise_for_status()
                    if not r.json().get('saved'):raise ValueError('Archive did not accept replay metadata')
                    meta.pop('archive_error',None);save();break
                except (OSError,ValueError,httpx.HTTPError) as e:meta['archive_error']=type(e).__name__;save()
        except Exception as e:meta.update(state='failed',reason=type(e).__name__);save()
    threading.Thread(target=loop,daemon=True,name='gameplay-native-'+sid).start()
    return dict(meta)
