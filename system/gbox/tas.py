"""Frame-exact libretro tapes, including state loads and rewind branches.

This protocol is independent of BSV, so ordinary user save-state loads remain valid.
All paths are private run directories; no operator save slot is used by the recorder.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import threading
import time
import uuid
import zipfile
import zlib

MAGIC = b'GBTAS001' + struct.pack('<II', 1, 0)
MAX_RECORD = 32 * 2**20
MAX_STATE = 16 * 2**20
MAX_TAPE = 512 * 2**20
_build_lock = threading.Lock()


def fingerprint(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


def decode_state(payload, previous=b''):
    if len(payload) < 14:
        raise ValueError('Truncated state record')
    frame, reason, delta, size = struct.unpack_from('<QBBI', payload)
    if reason > 3 or delta > 1 or not 0 < size <= MAX_STATE or delta and len(previous) != size:
        raise ValueError('Invalid state record')
    result = bytearray(size)
    pos, out = 14, 0
    while pos < len(payload):
        if pos + 3 > len(payload):
            raise ValueError('Truncated state encoding')
        count, kind = struct.unpack_from('<HB', payload, pos)
        pos += 3
        if not count or kind > 1 or out + count > size or kind and pos + count > len(payload):
            raise ValueError('Invalid state encoding')
        if kind:
            result[out:out+count] = payload[pos:pos+count]
            pos += count
        out += count
    if out != size:
        raise ValueError('State size mismatch')
    if delta:
        # States are small for NES. Keep only the current/previous snapshot in memory.
        result = bytearray(a ^ b for a, b in zip(result, previous))
    return frame, reason, bytes(result)


def records(path):
    with open(path, 'rb') as stream:
        if stream.read(16) != MAGIC:
            raise ValueError('Unsupported TAS format')
        while True:
            offset = stream.tell()
            header = stream.read(5)
            if not header:
                raise ValueError('TAS has no completed footer; retain it for recovery')
            if len(header) != 5:
                raise ValueError('Truncated TAS record')
            tag, size = struct.unpack('<cI', header)
            if size > MAX_RECORD:
                raise ValueError('TAS record exceeds limit')
            payload = stream.read(size)
            if len(payload) != size:
                raise ValueError('Truncated TAS payload')
            yield offset, tag, payload
            if tag == b'E':
                if stream.read(1):
                    raise ValueError('Data after TAS footer')
                return


def index(path, *, checkpoint_dir=None):
    """Validate a tape and index chronological segments; backwards restores never erase prior frames."""
    path = Path(path)
    if path.stat().st_size > MAX_TAPE + MAX_RECORD:
        raise ValueError('TAS exceeds archive limit')
    previous, count, restores, last_level = b'', 0, 0, None
    checkpoints, segments, pending, wins = [], [], None, []
    for offset, tag, payload in records(path):
        if tag == b'S':
            frame, reason, previous = decode_state(payload, previous)
            if frame != count:
                raise ValueError('State frame counter is not chronological')
            if reason == 1:
                restores += 1
            row = {'frame': frame, 'offset': offset, 'after': offset+5+len(payload), 'reason': reason,
                   'state_sha256': hashlib.sha256(previous).hexdigest(), 'size': len(previous)}
            if checkpoint_dir is not None:
                folder = Path(checkpoint_dir); folder.mkdir(parents=True, exist_ok=True)
                target = folder/(row['state_sha256']+'.state')
                if not target.exists():
                    target.write_bytes(previous)
            checkpoints.append(row)
        elif tag == b'F':
            if len(payload) < 28:
                raise ValueError('Truncated TAS frame')
            frame, queries, reserved, ram_hash, elapsed = struct.unpack_from('<QHHII', payload)
            if frame != count or queries > 4096 or reserved or len(payload) != 28+queries*7 or not checkpoints:
                raise ValueError('Invalid TAS frame sequence')
            world, level, area, mode, task, sub, small, fc = payload[20:28]
            label = f'{world+1}-{level+1}' if world < 8 and level < 4 and mode in (1, 2) and task == 3 and sub else None
            if label is None:
                last_level = None
            if label is not None and label != last_level:
                if pending is not None:
                    pending['end_frame'] = count
                pending = {'id': f'level-{count}', 'label': label, 'start_frame': count, 'end_frame': None,
                           'checkpoint_frame': checkpoints[-1]['frame']}
                segments.append(pending)
                last_level = label
            if world == 7 and level == 3 and mode == 2 and not wins:
                wins.append(count)
            count += 1
        elif tag == b'R':
            if payload:
                raise ValueError('Invalid reset record')
        elif tag == b'E':
            if len(payload) != 8 or struct.unpack('<Q', payload)[0] != count or count < 1:
                raise ValueError('Incomplete TAS footer')
        else:
            raise ValueError('Unknown TAS record type')
    if pending is not None:
        pending['end_frame'] = count
    return {'format': 'gbox-tas-v1', 'frames': count, 'state_restores': restores, 'checkpoints': checkpoints,
            'segments': segments, 'sha256': fingerprint(path), 'bytes': path.stat().st_size,
            'complete': True, 'replay_verified': False, 'game_completion_frames': wins}


def rom_bytes(path):
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            entries = [i for i in archive.infolist() if i.filename.lower().endswith('.nes')]
            if len(entries) != 1 or entries[0].file_size > 2**20:
                raise ValueError('Select a single small NES ROM')
            return archive.read(entries[0])
    if path.stat().st_size > 2**20:
        raise ValueError('NES replay content exceeds limit')
    return path.read_bytes()


def smb_identity(data):
    if len(data) != 40976 or data[:4] != b'NES\x1a' or data[4:6] != b'\x02\x01' or data[6] & 0xF4 or data[7] & 0xF0:
        raise ValueError('Replay sprite variants require the owned NROM SMB1 layout')
    prg = data[16:32784]
    if zlib.crc32(prg) != 0x5CF548D3:
        raise ValueError('SMB1 program differs; an exact replay cannot be assumed')
    return {'rom_sha256': hashlib.sha256(data).hexdigest(), 'header_sha256': hashlib.sha256(data[:16]).hexdigest(), 'prg_sha256': hashlib.sha256(prg).hexdigest(),
            'chr_sha256': hashlib.sha256(data[32784:]).hexdigest()}


def encode_state(frame, state, reason=0):
    """Independent literal snapshot, used only for the start of a trimmed tape."""
    out = bytearray(struct.pack('<QBBI', frame, reason, 0, len(state)))
    for off in range(0, len(state), 65535):
        part = state[off:off+65535]
        out += struct.pack('<HB', len(part), 1) + part
    return bytes(out)


def slice_tape(source, target, start, end):
    """Start from the nearest preceding checkpoint; preserve all subsequent restore branches."""
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError('Choose a nonempty chronological frame range')
    info = index(source)
    if end > info['frames']:
        raise ValueError('Segment extends beyond the recorded run')
    checkpoint = max((c for c in info['checkpoints'] if c['frame'] <= start), key=lambda c: c['frame'])
    previous, seed = b'', None
    for offset, tag, payload in records(source):
        if tag == b'S':
            _, _, previous = decode_state(payload, previous)
        if offset == checkpoint['offset']:
            seed = previous
            break
    if seed is None:
        raise ValueError('Segment checkpoint is missing')
    def write(stream, tag, data):
        stream.write(struct.pack('<cI', tag, len(data)) + data)
    with open(target, 'xb') as stream:
        stream.write(MAGIC)
        write(stream, b'S', encode_state(0, seed))
        for offset, tag, payload in records(source):
            if offset <= checkpoint['offset']:
                continue
            if tag in (b'S', b'F'):
                frame = struct.unpack_from('<Q', payload)[0]
                if frame >= end:
                    break
                payload = struct.pack('<Q', frame-checkpoint['frame']) + payload[8:]
            if tag == b'E':
                break
            write(stream, tag, payload)
        write(stream, b'E', struct.pack('<Q', end-checkpoint['frame']))
    return {'start_frame': start-checkpoint['frame'], 'end_frame': end-checkpoint['frame'],
            'source_start': start, 'source_end': end, 'checkpoint_frame': checkpoint['frame']}


def rebind_graphics(source, target, original_rom, variant_rom):
    """Mesen format-13 state header migration for CHR-only SMB1 variants.

    Header/PRG must be identical. Only the documented ROM identity field changes;
    emulated RAM, CPU/PPU state, input events and every expected frame hash stay intact.
    Original tapes are immutable. Every replay still checks emulated RAM each frame.
    """
    a, b = smb_identity(original_rom), smb_identity(variant_rom)
    if a['prg_sha256'] != b['prg_sha256'] or a['header_sha256'] != b['header_sha256']:
        raise ValueError('Only CHR graphics may change for sprite replay')
    expected = hashlib.sha1(original_rom).hexdigest().upper().encode()
    replacement = hashlib.sha1(variant_rom).hexdigest().upper().encode()
    previous = b''
    with open(target, 'xb') as stream:
        stream.write(MAGIC)
        for _, tag, payload in records(source):
            if tag == b'S':
                frame, reason, previous = decode_state(payload, previous)
                if (len(previous) < 58 or previous[:3] != b'MST' or struct.unpack_from('<I', previous, 7)[0] != 13
                        or previous[11:14] != bytes(3) or previous[14:54] != expected):
                    raise ValueError('State does not match the verified Mesen mapper-0 format and source ROM')
                state = previous[:14] + replacement + previous[54:]
                payload = encode_state(frame, state, reason)
            stream.write(struct.pack('<cI', tag, len(payload)) + payload)
    return {'source_rom': a, 'variant_rom': b, 'migration': 'Mesen format 13 ROM hash only; PRG/header identical'}


def compile_proxy(runtime, server='', headers=None):
    source = Path(__file__).parent/'native/tas_core.c'
    digest = fingerprint(source)[:16]
    folder = Path(runtime)/'tas-core'/digest
    target = folder/('gbox_tas_libretro.dll' if os.name == 'nt' else 'gbox_tas_libretro.so')
    with _build_lock:
        if target.is_file():
            return target
        folder.mkdir(parents=True, exist_ok=True)
        # PCs without the C toolchain can use the source-bound binary built by
        # the operator's Windows machine and archived on their own Spark.
        if os.name == 'nt' and server:
            try:
                import httpx
                base = server+'/api/tas/runtime/windows/'+fingerprint(source)
                response = httpx.get(base+'/manifest', headers=headers or {}, timeout=10)
                response.raise_for_status(); manifest = response.json()
                if manifest['source_sha256'] != fingerprint(source):
                    raise ValueError('Native runtime source identity differs')
                with httpx.stream('GET', base+'/file', headers=headers or {}, timeout=30) as response:
                    response.raise_for_status()
                    temp = folder/'download.tmp'
                    with temp.open('wb') as out:
                        size = 0
                        for block in response.iter_bytes(65536):
                            size += len(block)
                            if size > 4*2**20:
                                raise ValueError('Native runtime exceeds binary limit')
                            out.write(block)
                if fingerprint(temp) != manifest['sha256']:
                    raise ValueError('Native runtime download failed SHA-256 verification')
                temp.replace(target)
                return target
            except (OSError, ValueError, KeyError, httpx.HTTPError):
                (folder/'download.tmp').unlink(missing_ok=True)
        if os.name == 'nt':
            finder = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
            location = subprocess.check_output([str(finder), '-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True, timeout=15).strip()
            vcvars = Path(location)/'VC/Auxiliary/Build/vcvars64.bat'
            if not location or not vcvars.is_file():
                raise ValueError('Visual C++ compiler is needed for native TAS capture')
            script = folder/'build.cmd'
            script.write_text(f'@echo off\ncall "{vcvars}" >nul\ncl /nologo /O2 /LD /std:c11 "{source}" /Fe:"{target}" /Fo:"{folder / "tas_core.obj"}" /link /OUT:"{target}"\n', encoding='utf8')
            command = ['cmd.exe', '/d', '/c', str(script)]
        else:
            command = ['cc', '-std=c11', '-shared', '-fPIC', '-O2', str(source), '-o', str(target), '-ldl']
        subprocess.run(command, cwd=folder, check=True, capture_output=True, timeout=90,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if not target.is_file():
            raise ValueError('TAS proxy compilation produced no library')
    return target


def prepare(ad, core, rom):
    if not getattr(ad, 'capture_gameplay', False) or not getattr(ad.config, 'gameplay_memory_enabled', True):
        return None
    if getattr(ad, 'platform', '') != 'nes':
        return None
    if os.name != 'nt':
        return None  # this capture integration currently retains/replays Windows Mesen engines
    if not Path(core).name.lower().startswith('mesen_libretro'):
        return None  # native capture/replay compatibility has been verified with Mesen
    identity = smb_identity(rom_bytes(rom))
    root = ad.config.runtime/'tas-runs'
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 8*2**30 or sum(p.stat().st_size for p in root.glob('*/input.gbt')) >= 20*2**30:
        ad.tas_capture = {'state': 'budget_hold', 'reason': 'Native TAS capture needs 8 GiB free and less than 20 GiB retained tapes'}
        return None
    proxy = compile_proxy(ad.config.runtime, getattr(ad, 'tas_server', ''), getattr(ad, 'tas_headers', {}))
    core_hash = fingerprint(core)
    kept_core = ad.config.runtime/'tas-cores'/core_hash/Path(core).name
    kept_core.parent.mkdir(parents=True, exist_ok=True)
    if not kept_core.is_file():
        shutil.copyfile(core, kept_core)
    if fingerprint(kept_core) != core_hash:
        raise ValueError('Retained replay core failed SHA-256 verification')
    core = kept_core
    folder = root/uuid.uuid4().hex
    folder.mkdir()
    meta = {'id': folder.name, 'state': 'recording', 'format': 'gbox-tas-v1', 'path': str(folder/'input.gbt'),
            'core': str(core), 'content': str(rom), 'started': time.time(), 'replay_verified': False,
            'capture': 'all native input callbacks and successful state restores, including rewind branches'}
    meta.update(identity)
    options = ad.config.runtime/'retroarch/core-options.cfg'
    meta['core_options'] = options.read_text()[:65536] if options.is_file() else ''
    (folder/'manifest.json').write_text(json.dumps(meta, indent=2))
    ad.tas_capture = meta
    ad.tas_real_core = str(core)
    ad.tas_environment = {'GBOX_TAS_CORE': str(core), 'GBOX_TAS_RECORD': meta['path'],
                          'GBOX_TAS_STATUS': str(folder/'status.json'), 'GBOX_TAS_SEAL': str(folder/'seal')}
    return proxy


def finalize(ad):
    """Seal only this recorder before gBox stops its emulator. Never touch an operator save slot."""
    meta = getattr(ad, 'tas_capture', None)
    proc = getattr(ad, 'proc', None)
    if not meta or meta.get('state') != 'recording' or not proc or proc.poll() is not None:
        return
    folder = Path(meta['path']).parent
    try:
        (folder/'seal').write_text('finish native input tape')
        # A running core notices within 15 frames. A paused core still unloads normally on QUIT.
        ad.cmd('QUIT')
        until = time.monotonic()+.8
        while proc.poll() is None and time.monotonic() < until:
            try:
                state = json.loads((folder/'status.json').read_text()).get('state')
                if state in ('captured', 'budget_stop', 'failed'):
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.025)
    except OSError:
        pass


def start(sid, ad, game, server, headers, alive):
    meta = getattr(ad, 'tas_capture', None)
    if not meta:
        return {'state': 'unsupported', 'reason': 'Native rewind-preserving capture currently supports the owned SMB1 NES program'}
    if meta.get('state') != 'recording':
        return dict(meta)
    meta.update(session_id=sid, game_id=game.get('game_id'), title=game.get('title'), mod=game.get('mod') or '')
    folder = Path(meta['path']).parent
    def save():
        temp = folder/'manifest.tmp'
        temp.write_text(json.dumps(meta, indent=2))
        temp.replace(folder/'manifest.json')
    def watch():
        import httpx
        try:
            meta['core_sha256'] = fingerprint(meta['core'])
            meta['proxy_sha256'] = fingerprint(Path(__file__).parent/'native/tas_core.c')
            save()
            reported = 0
            while alive():
                proc = getattr(ad, 'proc', None)
                if proc is not None and proc.poll() is not None:
                    break
                try:
                    native = json.loads((folder/'status.json').read_text())
                    meta['native_status'] = native
                    if server and (time.monotonic()-reported > 10 or native.get('state') != 'recording'):
                        reported = time.monotonic()
                        try:
                            httpx.post(server+f'/api/sessions/{sid}/detail', headers=headers, timeout=3,
                                       json={'tas_capture': {'id': meta['id'], **native}})
                        except httpx.HTTPError:
                            pass
                    if native.get('state') in ('captured', 'budget_stop', 'failed'):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(2)
            path = Path(meta['path'])
            # Finalization occurs inside retro_unload_game. Never stop or alter a human game.
            previous = None
            for _ in range(10):
                stamp = (path.stat().st_size, path.stat().st_mtime_ns)
                if stamp == previous:
                    break
                previous = stamp; time.sleep(.5)
            info = index(path)
            meta.update(state='retained', index=info, sha256=info['sha256'])
            save()
            if not server:
                return
            # Retain the exact engine, so a future core update cannot strand the run.
            core_path = Path(meta['core'])
            with core_path.open('rb') as stream:
                response = httpx.post(server+'/api/tas/cores/'+meta['core_sha256'], headers=headers,
                                      content=iter(lambda: stream.read(2**20), b''), timeout=120)
            response.raise_for_status()
            public = {k: v for k, v in meta.items() if k not in ('path', 'core', 'content', 'index')}
            for wait in (0, 5, 20):
                if wait:
                    time.sleep(wait)
                try:
                    with path.open('rb') as stream:
                        response = httpx.post(server+f'/api/tas/captures/{sid}/{meta["id"]}', headers=headers | {'x-gbox-tas-meta': json.dumps(public)},
                                              content=iter(lambda: stream.read(2**20), b''), timeout=120)
                    response.raise_for_status()
                    archived = response.json()
                    if archived.get('sha256') != info['sha256']:
                        raise ValueError('Archived TAS digest differs')
                    meta.update(state='archived', archive_id=archived['id']); meta.pop('archive_error', None); save()
                    return
                except (OSError, ValueError, httpx.HTTPError) as error:
                    meta['archive_error'] = str(error)[:240]; save()
        except Exception as error:
            meta.update(state='retained_unverified', reason=str(error)[:240]); save()
    threading.Thread(target=watch, daemon=True, name='tas-capture-'+sid).start()
    return dict(meta)
