"""Native TAS playback owns its emulator and never switches an operator's game."""
import json
from pathlib import Path
import shutil
import threading
import time
import uuid

import httpx
from pydantic import BaseModel, Field

from . import adapters, tas
from .models import CatalogEntry, Permission
from .registry import tool


class PlayIn(BaseModel):
    run_id: str = Field(pattern='^[a-f0-9]{32}$')
    game: CatalogEntry
    segment: str = ''
    loop: bool = False
    idle_demo: bool = False
    sprite: str = ''  # built-in native HD sprite, sprite:gallery_slug, or chr:build_name


def admission(ctx):
    """Recheck at execution: queued requests can outlive the idle window."""
    from .background_testing import admission_reason
    response = httpx.get(ctx.server+'/api/testing/workers', headers=ctx.headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    worker = next((w for w in data['workers'] if w['id'] == ctx.worker), None)
    if not worker:
        raise ValueError('Playback worker is no longer registered')
    why = admission_reason(worker, data.get('excluded', []), worker.get('budget_percent', 70), require_gpu=False)
    if why:
        raise ValueError(why)
    return worker


def player_only(original, variant):
    """Shared HUD/background tiles can affect sprite-zero timing; only player tiles may differ."""
    from .smb1_inventory import _player_rows
    a, b = tas.smb_identity(original), tas.smb_identity(variant)
    if a['header_sha256'] != b['header_sha256'] or a['prg_sha256'] != b['prg_sha256']:
        raise ValueError('Replay skins must preserve the SMB1 program and cartridge header')
    allowed = {t for row in _player_rows(original[16:32784]) for t in row if t != 0xFC}
    for tile in range(512):
        start = 32784+tile*16
        if tile not in allowed and original[start:start+16] != variant[start:start+16]:
            raise ValueError('Replay skin changes shared/background tiles; exact TAS compatibility is not established')
    return b


def _accept(store, out, actor):
    from .tools import _launch_accept
    _launch_accept(store, out, actor)
    store.put('slabel', out.session_id, {'owner': 'agent', 'task': 'native TAS replay'})


@tool('tas_play', '1.0', PlayIn, __import__('gbox.tools', fromlist=['LaunchOut']).LaunchOut,
      permissions=[Permission.EXECUTE], capabilities=['runtime'], platforms=['windows'], timeout_s=900, on_accept=_accept)
def play(inp, ctx):
    """Play an archived native SMB1 tape or level segment in a separate idle-PC test session. Loops stop on
    human input, opt-out, resource pressure or desync. Original saves and human games are never replaced.
    Sprites use native Mesen tile replacement; the SMB1 executable/physics stay unchanged."""
    from . import tools, filemods
    if not ctx.server:
        raise ValueError('Native archive playback requires the control plane')
    admission(ctx)
    with tools._LAUNCH_LOCK:
        if tools.SESSIONS:
            raise ValueError('A game is already running here; TAS playback waits without closing it')
        response = httpx.get(ctx.server+'/api/tas/runs/'+inp.run_id, headers=ctx.headers, timeout=20)
        response.raise_for_status(); row = response.json()
        if row['game_id'] != inp.game.game_id:
            raise ValueError('Native tape belongs to another game')
        # The format version is validated below. Source hashes are provenance;
        # compatible proxy fixes must not strand earlier tapes.
        root = ctx.config.runtime/'tas-playback'
        root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(root).free < 4*2**30 or sum(p.stat().st_size for p in root.glob('*/*.gbt')) >= 20*2**30:
            raise ValueError('Playback needs 4 GiB free and less than 20 GiB of retained private copies')
        folder = root/uuid.uuid4().hex; folder.mkdir()
        tape = folder/'source.gbt'
        with httpx.stream('GET', ctx.server+'/api/tas/runs/'+inp.run_id+'/file', headers=ctx.headers, timeout=120) as r:
            r.raise_for_status()
            size = 0
            with tape.open('xb') as out:
                for block in r.iter_bytes(2**20):
                    size += len(block)
                    if size > tas.MAX_TAPE + tas.MAX_RECORD:
                        raise ValueError('Archive exceeds native playback budget')
                    out.write(block)
        if tas.fingerprint(tape) != row['sha256']:
            raise ValueError('Downloaded native recording failed its SHA-256 check')
        info = tas.index(tape)
        start, end = 0, info['frames']
        if inp.segment:
            segment = next((s for s in info['segments'] if s['id'] == inp.segment), None)
            if not segment:
                raise ValueError('Level segment not found')
            selected = folder/'segment.gbt'
            cut = tas.slice_tape(tape, selected, segment['start_frame'], segment['end_frame'])
            tape, start, end = selected, cut['start_frame'], cut['end_frame']
        source = tools.rom_path(inp.game, ctx.config)
        if row.get('mod'):
            name = filemods.stage(ctx.config, ctx.server, ctx.headers, inp.game.game_id, row['mod'], ctx.progress)
            source = filemods.launch_path(ctx.config, inp.game.game_id, source, name)
        original = tas.rom_bytes(source)
        if tas.smb_identity(original)['rom_sha256'] != row['rom_sha256']:
            raise ValueError('Owned ROM differs from the recorded run; original input tape remains available')
        content = original
        pack = None
        if inp.sprite.startswith('chr:'):
            name = filemods.stage(ctx.config, ctx.server, ctx.headers, inp.game.game_id, inp.sprite[4:], ctx.progress)
            content = tas.rom_bytes(filemods.launch_path(ctx.config, inp.game.game_id, source, name))
            player_only(original, content)
            rebound = folder/'sprite.gbt'
            tas.rebind_graphics(tape, rebound, original, content)
            tape = rebound
        elif inp.sprite:
            from . import tas_sprites
            pack = tas_sprites.prepare(ctx, inp.sprite, original, folder)
        rom = folder/'replay.nes'; rom.write_bytes(content)
        # Force the recorded engine. The exact binary check is repeated inside the adapter before spawn.
        cfg = ctx.config.emulators.get('nes')
        if cfg is None:
            from .config import EmulatorConfig
            cfg = EmulatorConfig(adapter='retroarch', core='mesen')
        cfg = cfg.model_copy(update={'adapter': 'retroarch', 'core': 'mesen', 'args': []})
        ad = adapters.RetroArchAdapter(cfg, ctx.config, 'nes')
        ad.capture_gameplay, ad.rewind_on, ad.examine = False, False, False
        ad.supported = ad.supported - {'send_input', 'write_memory', 'load_state', 'rewind'}
        ad.tas_server, ad.tas_headers = ctx.server, ctx.headers
        ad.progress = ctx.progress
        ad.tas_playback = {'folder': str(folder), 'tape': str(tape), 'status': str(folder/'status.json'),
                           'start_frame': start, 'end_frame': end, 'loop': inp.loop,
                           'core_sha256': row['core_sha256'], 'core_options': row.get('core_options', '')}
        if pack:
            import re
            options = re.sub(r'^mesen_hdpacks\s*=.*$', '', ad.tas_playback['core_options'], flags=re.M)
            ad.tas_playback['core_options'] = options+'\nmesen_hdpacks = "enabled"\n'
        # Runtime preparation can be slow; check again before allocating the emulator.
        kept_core = ctx.config.runtime/'tas-cores'/row['core_sha256']/'mesen_libretro.dll'
        kept_core.parent.mkdir(parents=True, exist_ok=True)
        if not kept_core.is_file():
            with httpx.stream('GET', ctx.server+'/api/tas/cores/'+row['core_sha256'], headers=ctx.headers, timeout=120) as r:
                r.raise_for_status()
                temp = kept_core.with_suffix('.tmp')
                try:
                    size = 0
                    with temp.open('wb') as out:
                        for block in r.iter_bytes(2**20):
                            size += len(block)
                            if size > 64*2**20:
                                raise ValueError('Replay engine exceeds its archive budget')
                            out.write(block)
                    if tas.fingerprint(temp) != row['core_sha256']:
                        raise ValueError('Recorded Mesen binary failed SHA-256 verification')
                    temp.replace(kept_core)
                finally:
                    temp.unlink(missing_ok=True)
        if tas.fingerprint(kept_core) != row['core_sha256']:
            raise ValueError('Recorded Mesen binary failed SHA-256 verification')
        ad.cfg = cfg.model_copy(update={'core': str(kept_core)})
        admission(ctx)
        if tools.SESSIONS:
            raise ValueError('Another game started during replay preparation; it stays running')
        try:
            detail = ad.launch_game(str(rom))
        except Exception:
            ad.stop_game()
            raise
        sid = f'{ctx.worker}-{ctx.job_id}'
        tools.SESSIONS[sid] = (ad, inp.game.model_dump())
        detail.update(_game={'game_id': inp.game.game_id, 'title': inp.game.title},
                      mod=row.get('mod', ''), tas={'run_id': inp.run_id, 'sprite': inp.sprite,
                      'segment': inp.segment, 'loop': inp.loop, 'isolated': True, 'verified': False, 'sprite_pack': pack})
        tools.track_emulator(ctx.config, sid, detail.get('pid'))
        threading.Thread(target=tools._pump, args=(sid, ad, ctx.server, ctx.headers, ctx), daemon=True).start()
        def watch():
            duration = 3600 if inp.loop else max(3600, min(86400, (end-start)/40+600))
            deadline = time.monotonic()+duration
            preference_checked = 0
            reported_loops = -1
            status = {'state': 'starting', 'mismatches': 0}
            try:
                while sid in tools.SESSIONS and ad.proc.poll() is None:
                    time.sleep(2)
                    try:
                        status = json.loads((folder/'status.json').read_text())
                    except (OSError, ValueError):
                        continue
                    if status.get('state') in ('finished', 'failed') or status.get('loops', 0) > reported_loops:
                        reported_loops = status.get('loops', 0)
                        try:
                            httpx.post(ctx.server+f'/api/tas/runs/{inp.run_id}/result', headers=ctx.headers,
                                       json={'job_id': ctx.job_id, 'status': status}, timeout=10).raise_for_status()
                        except httpx.HTTPError:
                            pass
                    if status.get('state') in ('finished', 'failed'):
                        break
                    from .padstate import player_active
                    if player_active(sid, within=4):
                        break
                    if inp.idle_demo and time.monotonic()-preference_checked > 10:
                        preference_checked = time.monotonic()
                        response = httpx.get(ctx.server+'/api/tas/runs/'+inp.run_id, headers=ctx.headers, timeout=10)
                        response.raise_for_status(); pref = response.json().get('idle') or {}
                        if not pref.get('enabled') or pref.get('sprite', '') != inp.sprite:
                            break
                    admission(ctx)  # missing control plane, operator return or pressure yields this test
                    if time.monotonic() >= deadline:
                        break
            except Exception:
                pass
            finally:
                # Identity check prevents a stale watcher from stopping any replacement/human session.
                if tools.SESSIONS.get(sid, (None,))[0] is ad:
                    try:
                        ad.stop_game()
                    finally:
                        # _pump records the normal process exit and releases its own session.
                        tools.track_emulator(ctx.config, sid, detail.get('pid'), add=False)
                if ad.proc.poll() is not None:
                    # Private playback copies are disposable; the archive/original recording is not.
                    for name in ('source.gbt', 'segment.gbt', 'sprite.gbt', 'replay.nes'):
                        (folder/name).unlink(missing_ok=True)
        threading.Thread(target=watch, daemon=True, name='tas-play-'+sid).start()
        return {'session_id': sid, 'adapter': ad.name, 'capabilities': ad.get_capabilities(), 'detail': detail}
