"""Isolated PSO observed-input demonstrations, never advertised as exact TAS.

Native checkpoints periodically realign an approximate controller timeline. Every
external item/stat action is reissued in order and verified independently. A demo
only owns its newly launched emulator, cloned cards and private save-state folder.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
import uuid

import httpx
from pydantic import BaseModel, Field

from . import adapters, background_testing as background
from .models import CatalogEntry, Permission
from .registry import tool
from .tas_tool import admission
from .gameplay_actions import digest

MAX_DEMO_BYTES=20*2**30


def demo_bytes(root):
    root=Path(root)
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) if root.exists() else 0


def cleanup_demo(folder,root,proc):
    """Remove only this completed private UUID directory, after confirmed exit."""
    folder,root=Path(folder),Path(root)
    if proc is None or proc.poll() is None:return False
    if not re.fullmatch('[a-f0-9]{32}',folder.name) or folder.resolve().parent!=root.resolve():return False
    shutil.rmtree(folder)
    return True


class Play(BaseModel):
    run_id: str = Field(pattern=r'^[\w-]{1,120}$')
    game: CatalogEntry
    loop: bool = False
    idle_demo: bool = False
    max_seconds: int = Field(default=3600, ge=10, le=3600)
    source_revision: str = Field(default='',pattern=r'^(|[a-f0-9]{64})$')


def plan_revision(plan):
    return hashlib.sha256(json.dumps({'checkpoint':plan['checkpoint']['sha256'],'end_id':plan['end_id']},
                                     sort_keys=True).encode()).hexdigest()


def get(ctx,path,**params):
    response=httpx.get(ctx.server+path,headers=ctx.headers,params=params,timeout=15)
    response.raise_for_status()
    return response.json()


def download(ctx,ref,folder):
    sha=ref.get('sha256','')
    if not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('Invalid checkpoint or card identity')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    path=folder/(sha+'.blob')
    if path.is_file() and digest(path)==sha:return path
    tmp=folder/(sha+'.tmp')
    try:
        root=folder.parent.parent
        used=demo_bytes(root)
        if used>=MAX_DEMO_BYTES:raise ValueError('Private demonstration storage budget reached; retained copies were kept')
        with httpx.stream('GET',ctx.server+'/api/gameplay-memory/blobs/'+sha,headers=ctx.headers,timeout=120) as response:
            response.raise_for_status();size=0
            with tmp.open('wb') as stream:
                for block in response.iter_bytes(2**20):
                    size+=len(block)
                    if size>128*2**20:raise ValueError('Checkpoint exceeds observed-demo budget')
                    if used+size>MAX_DEMO_BYTES or shutil.disk_usage(folder).free<4*2**30:
                        raise ValueError('Private demonstration storage or free-disk budget reached')
                    stream.write(block)
        if digest(tmp)!=sha:raise ValueError('Downloaded checkpoint/card failed its digest check')
        tmp.replace(path)
        return path
    finally:tmp.unlink(missing_ok=True)


def visible_frame(data):
    """Reject missing/black capture evidence before arming an idle loop."""
    import io
    from PIL import Image,ImageStat
    try:
        image=Image.open(io.BytesIO(data)).convert('RGB')
        image.thumbnail((160,120))
        stat=ImageStat.Stat(image)
        return max(stat.mean)>3 and max(stat.stddev)>1
    except (OSError,ValueError):return False


class PrivateRetroArch(adapters.RetroArchAdapter):
    def _write_cfg(self):
        path=super()._write_cfg()
        folder=Path(self.gameplay_demo_folder)
        from .memory_card_emulators import _cfg
        values=_cfg(path)
        values.update(system_directory=str(folder/'system'),savefile_directory=str(folder/'saves'),
                      savestate_directory=str(folder/'states'),screenshot_directory=str(folder/'shots'),
                      core_options_path=str(folder/'core-options.cfg'),rewind_enable='false',
                      savestate_auto_load='false',savestate_auto_save='false',input_joypad_driver='null',
                      input_autodetect_enable='false',apply_cheats_after_load='false',
                      input_enable_hotkey_btn='nul')
        for sub in ('system/dc','saves','states','shots'):(folder/sub).mkdir(parents=True,exist_ok=True)
        path=folder/'retroarch.cfg'
        path.write_text(''.join(f'{k} = "{v}"\n' for k,v in values.items()))
        self.states_override=folder/'states'
        return path


def prepare_adapter(ctx,game,snapshot,folder,rom):
    """Select the captured runtime and clone card bytes; cloud leases are never borrowed."""
    identity=snapshot['identity'];platform=game.platform
    if platform=='gamecube':
        if os.name!='nt':raise ValueError('Observed PSO GameCube replay currently requires the exact captured Windows Dolphin build')
        ad=adapters.DolphinWinAdapter(ctx.config,platform)
        # Bind only the private window's injected keyboard. A real controller
        # remains an operator-return signal and never drives a demo character.
        lines=[]
        for line in ad.PAD_INI_WIN.splitlines():
            if line.startswith('Device ='):line='Device = DInput/0/Keyboard Mouse'
            elif ' = ' in line:
                key,value=line.split(' = ',1)
                dpad={'D-Pad/Up':'T','D-Pad/Down':'G','D-Pad/Left':'F','D-Pad/Right':'H'}
                if key in dpad:value='`'+dpad[key]+'`'
                elif 'DInput/0/Keyboard Mouse:' in value:
                    value='`'+value.split('DInput/0/Keyboard Mouse:',1)[1].split('`',1)[0]+'`'
                elif '`' in value:value=''
                line=key+' = '+value
            lines.append(line)
        ad.PAD_INI_WIN='\n'.join(lines)+'\n'
        ad.gameplay_demo_user=folder/'User'
        (ad.gameplay_demo_user/'StateSaves').mkdir(parents=True,exist_ok=True)
        exe=ad._exe()
        if digest(exe)!=identity.get('emulator_sha256'):raise ValueError('Dolphin build differs from the captured checkpoint')
        slots={}
        for card in snapshot['cards']:
            slot=card['slot']
            if slot not in ('A','B'):raise ValueError('Invalid captured GameCube memory-card slot')
            from .memory_card_emulators import gc_region,describe
            path=ad.gameplay_demo_user/'GC'/f'MemoryCard{slot}.{gc_region(ad,str(rom))}.raw'
            path.parent.mkdir(parents=True,exist_ok=True)
            source=download(ctx,card,folder/'blobs')
            if not describe(source.read_bytes(),'gamecube')['formatted']:raise ValueError('Invalid captured GameCube card')
            shutil.copyfile(source,path);slots[slot]={'path':str(path)}
        # Native configuration helper already knows region-specific raw paths.
        # `closed` guarantees the regular cloud sync finalizer ignores this
        # disposable copy; no card_id/revision/lease is present or requested.
        ad.memory_card_context={'platform':platform,'work_dir':str(folder),'slots':slots,'closed':True,'sandbox':True}
    elif platform=='dreamcast':
        cfg=ctx.config.emulators.get(platform)
        if cfg is None:raise ValueError('Configure the captured Flycast runtime before playback')
        cfg=cfg.model_copy(update={'adapter':'retroarch','args':[]})
        ad=PrivateRetroArch(cfg,ctx.config,platform)
        ad.gameplay_demo_folder=folder
        from . import provision
        runtime=provision.runtime_check(ctx.config,platform,cfg.core,cfg.executable or provision.retroarch_exe(ctx.config))
        if digest(runtime['core'])!=identity.get('core_sha256'):raise ValueError('Flycast build differs from the captured checkpoint')
        exe=cfg.executable or provision.retroarch_exe(ctx.config)
        if digest(exe)!=identity.get('emulator_sha256'):raise ValueError('RetroArch build differs from the captured checkpoint')
        system=folder/'system/dc';system.mkdir(parents=True,exist_ok=True)
        for name in ('dc_boot.bin','dc_flash.bin','dc_nvmem.bin'):
            source=ctx.config.runtime/'system/dc'/name
            if source.is_file():shutil.copyfile(source,system/name)
        original=ctx.config.runtime/'retroarch/core-options.cfg'
        from .memory_card_emulators import _cfg,describe
        options=_cfg(original)
        options['reicast_per_content_vmus']='disabled'
        assigned=set()
        for card in snapshot['cards']:
            slot=card['slot']
            if not re.fullmatch('[A-D][12]',slot):raise ValueError('Invalid captured Dreamcast VMU slot')
            source=download(ctx,card,folder/'blobs')
            if not describe(source.read_bytes(),'dreamcast')['formatted']:raise ValueError('Invalid captured Dreamcast VMU')
            shutil.copyfile(source,system/f'vmu_save_{slot}.bin');assigned.add(slot)
        for port,letter in enumerate('ABCD',1):
            for slot in (1,2):options[f'reicast_device_port{port}_slot{slot}']='VMU' if f'{letter}{slot}' in assigned else 'None'
        (folder/'core-options.cfg').write_text(''.join(f'{k} = "{v}"\n' for k,v in options.items()))
    else:raise ValueError('Observed demonstrations currently support PSO on GameCube and Dreamcast')
    ad.capture_gameplay=False
    ad.rewind_on=False
    ad.examine=False
    ad.progress=ctx.progress
    ad.game_id,ad.serial=game.game_id,game.serial
    return ad


def load_checkpoint(ctx,ad,payload,folder,rom):
    source=download(ctx,payload,folder/'blobs')
    if ad.name=='dolphin':
        # Only the demo's own StateSaves slot 8 is ever written.
        if not getattr(ad,'gameplay_demo_user',None):raise ValueError('Dolphin checkpoint needs a private demo user folder')
        serial=ad._disc_id(str(rom))
        if not re.fullmatch('[A-Z0-9]{6}',serial):raise ValueError('Invalid GameCube disc identity')
        target=Path(ad.state_dir())/(serial+'.s08')
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        ad.checkpoint_load()
    else:
        if not getattr(ad,'gameplay_demo_folder',None):raise ValueError('RetroArch checkpoint needs a private demo folder')
        target=Path(ad.state_dir())/(Path(rom).stem+'.state')
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        ad.load_state(0)
    # Save-state loading is asynchronous. The next native action's revision and
    # player checks run after this settling period, never while loading.
    time.sleep(.75)


def pad_events(payload,platform=None):
    allowed={'up','down','left','right','a','b','x','y','l','r','l2','r2','z','start',
             'cup','cdown','cleft','cright','lup','ldown','lleft','lright'}
    events=[{'key':str(e.get('key','')).lower(),'down':bool(e.get('down',True))}
            for e in payload.get('events',[])[:100] if isinstance(e,dict) and str(e.get('key','')).lower() in allowed]
    # Physical XInput reports are positional RetroPad labels (Xbox A=b), while
    # /input UI/stream events are already the adapter's requested buttons.
    # Existing physical observations are identified by their always-present
    # stick dictionaries; streamed observations do not carry these fields.
    physical=isinstance(payload.get('stick'),dict) or isinstance(payload.get('rstick'),dict)
    if platform=='gamecube' and physical:
        mapping={'a':'b','b':'a','x':'y','y':'x','r':'z','l2':'l','r2':'r',
                 'up':'t','down':'g','left':'f','right':'h'}
        events=[{**event,'key':mapping.get(event['key'],event['key'])} for event in events if event['key']!='l']
    # Observations carry normalized analog values, while these adapters expose
    # digital injected controls. Quantize explicitly; never call this exact TAS.
    for name,negative,positive in (('stick','lleft' if platform=='dreamcast' else 'left','lright' if platform=='dreamcast' else 'right'),('rstick','cleft','cright')):
        stick=payload.get(name)
        if not isinstance(stick,dict):continue
        for axis,neg,pos in (('x',negative,positive),('y',('lup' if platform=='dreamcast' else 'up') if name=='stick' else 'cup',('ldown' if platform=='dreamcast' else 'down') if name=='stick' else 'cdown')):
            value=stick.get(axis,0)
            if type(value) not in (int,float):continue
            events.extend([{'key':neg,'down':value<-.3},{'key':pos,'down':value>.3}])
    return events


def replay_action(sid,payload,ctx,identity,gear):
    if not payload.get('replayable'):return {'skipped':True,'reason':payload.get('reason','No executable action receipt')}
    inp=dict(payload.get('replay_input') or {})
    if inp.get('op')=='equipment_cycle':
        from .pso_gc_extras import Extras
        from .tools import SESSIONS
        ad,g=SESSIONS[sid]
        if g.get('platform')!='gamecube':raise ValueError('Resolved equipment cycles need their captured GameCube PSO runtime')
        from .pso_controls import session_lock
        from .models import Permission
        if Permission.MEMORY_WRITE not in ctx.config.granted_permissions:raise PermissionError('memory_write permission was removed')
        with session_lock(sid):
            m=Extras(ad);m.check()
            for row in inp.get('gear',[]):
                code=row.get('code','');kind=row.get('kind','')
                if not re.fullmatch('[a-f0-9]{6}',code) or kind not in ('weapon','armor','shield','mag'):
                    raise ValueError('Invalid recorded equipment cycle')
                old=gear.get(kind)
                if len(m.inventory())>=30 and old is not None:m.remove_generated(old);gear.pop(kind,None);old=None
                result=m.give(code)
                if not result.get('verified') or len(result.get('ids',[]))!=1:raise RuntimeError('Demo gear creation was not verified')
                item_id=result['ids'][0]
                if not m.equip_id(item_id):raise RuntimeError('Demo gear equip was not verified')
                if old is not None:m.remove_generated(old)
                gear[kind]=item_id
                if kind=='mag' and row.get('properties'):m.mag_set(item_id,row['properties'])
        return {'verified':True,'gear':list(gear)}
    if inp.get('op') in ('mag_set','mag_feed'):
        # Item IDs are runtime identities, not transferable references.
        from .tools import SESSIONS
        from .pso_gc_extras import Extras
        inp['item_id']=Extras(SESSIONS[sid][0]).mag()['mag']['id']
    from .pso_live import execute
    result=execute(sid,{'command_id':str(uuid.uuid5(uuid.NAMESPACE_URL,identity)),
                       'expires':time.time()+12,'input':inp},ctx)
    if result.get('verified') is False:raise RuntimeError('A replayed PSO action failed native read-back')
    if inp.get('op')=='give' and result.get('created',inp.get('count',1))!=inp.get('count',1):
        raise RuntimeError('The demo could not reproduce the recorded inventory insertion')
    return result


def iterate(ctx,run_id,plan):
    at,event_id=plan['start'],0
    while True:
        rows=get(ctx,f'/api/gameplay-memory/runs/{run_id}/demo/events',after_at=at,after_id=event_id,end_id=plan['end_id'])['events']
        if not rows:return
        for row in rows:
            at,event_id=row['at'],row['id']
            yield row


def run_timeline(events,*,start,clock,sleep,active,send,restore,apply,remaining,platform=None):
    """Bounded deterministic scheduler; source timestamps are approximate wall time."""
    began=clock();seen=set();count={'pads':0,'actions':0,'restores':0,'skipped':0}
    for event in events:
        if not active():raise InterruptedError('Observed demo yielded to operator activity or admission change')
        wait=max(0,float(event['at'])-start)
        if wait>remaining:return count|{'completed':False}
        while clock()-began<wait:
            if not active():raise InterruptedError('Observed demo yielded to operator activity or admission change')
            sleep(min(.1,wait-(clock()-began)))
        marker=event['id']
        if marker in seen:continue
        seen.add(marker)
        kind,payload=event['kind'],event['payload']
        if kind in ('pad','sampled_pad'):
            rows=pad_events(payload,platform)
            if rows:send(rows);count['pads']+=1
        elif kind=='checkpoint' and payload.get('schema')==1:
            restore(payload);count['restores']+=1
        elif kind=='mod_action':
            result=apply(event)
            if result.get('skipped'):count['skipped']+=1
            else:count['actions']+=1
    return count|{'completed':True}


def _accept(store,out,actor):
    from .tools import _launch_accept
    _launch_accept(store,out,actor)
    store.put('slabel',out.session_id,{'owner':'agent','task':'PSO observed-input demonstration'})


@tool('gameplay_demo','1.0',Play,__import__('gbox.tools',fromlist=['LaunchOut']).LaunchOut,
      permissions=[Permission.EXECUTE,Permission.STAGE,Permission.MEMORY_WRITE],capabilities=['runtime'],
      platforms=['windows'],timeout_s=900,on_accept=_accept)
def play(inp,ctx):
    """Replay a recorded PSO input/action timeline in a separate idle-PC session with cloned cards. This is an
    approximate demonstration, not frame-exact TAS. Native checkpoints realign the run; applied mods and resolved
    random equipment repeat in order. It yields on operator input, pressure or a failed read-back, never uses a
    human save slot, and never starts while another emulator is registered on this worker."""
    from . import tools,filemods
    if not ctx.server or not getattr(ctx,'agent_use',False):raise ValueError('Observed demos require an agent-owned idle test job')
    admission(ctx)
    with tools._LAUNCH_LOCK:
        if tools.SESSIONS:raise ValueError('A game is already running; observed replay waits without closing it')
        plan=get(ctx,f'/api/gameplay-memory/runs/{inp.run_id}/demo')
        if not plan.get('ready'):raise ValueError(plan.get('reason','A verified native checkpoint is required'))
        if inp.source_revision and plan_revision(plan)!=inp.source_revision:
            raise ValueError('Recorded run changed while queued; the next idle check will assess the new prefix')
        row=plan
        if row.get('game_id')!=inp.game.game_id:raise ValueError('The recorded run belongs to a different game')
        from .pso_controls import is_pso
        if not is_pso(inp.game.model_dump()):raise ValueError('Choose the recorded PSO game')
        root=ctx.config.runtime/'gameplay-demos';root.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(root).free<4*2**30 or demo_bytes(root)>=MAX_DEMO_BYTES:
            raise ValueError('Observed replay needs 4 GiB free and less than 20 GiB of retained private copies')
        folder=root/uuid.uuid4().hex;folder.mkdir()
        source=tools.rom_path(inp.game,ctx.config)
        if row.get('mod'):
            name=filemods.stage(ctx.config,ctx.server,ctx.headers,inp.game.game_id,row['mod'],ctx.progress)
            source=filemods.launch_path(ctx.config,inp.game.game_id,source,name)
        checkpoint=plan['checkpoint']
        if digest(source)!=checkpoint['identity'].get('rom_sha256'):raise ValueError('ROM differs from the checkpoint; save-state compatibility is not assumed')
        ad=prepare_adapter(ctx,inp.game,checkpoint,folder,source)
        download(ctx,checkpoint,folder/'blobs')
        admission(ctx)
        if tools.SESSIONS:raise ValueError('Another game started during preparation; it stays running')
        try:detail=ad.launch_game(str(source))
        except Exception:
            if getattr(ad,'proc',None):ad.stop_game()
            raise
        sid=f'{ctx.worker}-{ctx.job_id}';game=inp.game.model_dump()|{'_rom_path':str(source),'mod':row.get('mod','')}
        tools.SESSIONS[sid]=(ad,game)
        detail.update(_game={'game_id':inp.game.game_id,'title':inp.game.title},mod=row.get('mod',''),
            gameplay_demo={'run_id':inp.run_id,'isolated':True,'mode':'observed input; approximate, not exact TAS','loop':inp.loop})
        tools.track_emulator(ctx.config,sid,detail.get('pid'))
        threading.Thread(target=tools._pump,args=(sid,ad,ctx.server,ctx.headers,ctx),daemon=True).start()
        def watch():
            status={'state':'starting','loops':0,'pads':0,'actions':0,'restores':0,'skipped':0,'verified':False}
            next_check=0;deadline=time.monotonic()+inp.max_seconds
            def active():
                nonlocal next_check
                if tools.SESSIONS.get(sid,(None,))[0] is not ad or ad.proc.poll() is not None or time.monotonic()>=deadline:return False
                from .padstate import player_active
                if player_active(sid,within=4):return False
                if time.monotonic()>=next_check:
                    admission(ctx);next_check=time.monotonic()+2
                    if inp.idle_demo and not get(ctx,f'/api/gameplay-memory/runs/{inp.run_id}/demo/idle').get('enabled'):return False
                return True
            try:
                while active():
                    load_checkpoint(ctx,ad,checkpoint,folder,source)
                    gear={};loop=status['loops']
                    def restore(payload):
                        if payload['sha256']==checkpoint['sha256'] and payload['captured_at']==checkpoint['captured_at']:return
                        if payload.get('identity')!=checkpoint['identity']:raise ValueError('Runtime/content identity changed inside the recorded run')
                        load_checkpoint(ctx,ad,payload,folder,source);gear.clear()
                    count=run_timeline(iterate(ctx,inp.run_id,plan),start=plan['start'],clock=time.monotonic,sleep=time.sleep,
                        active=active,send=ad.send_input,restore=restore,
                        apply=lambda event:replay_action(sid,event['payload'],ctx,f'{sid}:{loop}:{event["id"]}',gear),
                        remaining=max(0,deadline-time.monotonic()),platform=inp.game.platform)
                    completed=count.pop('completed')
                    for key,value in count.items():status[key]+=value
                    if not completed:
                        status.update(state='bounded_prefix',verified=False,reason='Demo duration limit reached before the recorded prefix ended')
                        break
                    status['loops']+=1;status['state']='finished';status['verified']=True
                    # A screenshot is real rendered evidence, not an invented
                    # claim the replay reached the original game's outcome.
                    image=ad.get_frame()
                    if not visible_frame(image):raise RuntimeError('Observed demo did not produce a visible gameplay frame; no idle success was recorded')
                    if len(image)>8*2**20:raise ValueError('Observed demo evidence frame exceeds 8 MiB')
                    evidence=httpx.post(ctx.server+'/api/artifacts',headers=ctx.headers,content=image,
                        params={'name':'pso-observed-demo.png','media_type':'image/png',
                                'provenance':json.dumps({'gameplay_demo':inp.run_id,'job':ctx.job_id,'loop':status['loops']})},timeout=20)
                    evidence.raise_for_status()
                    status['frame_sha256']=evidence.json()['sha256']
                    httpx.post(ctx.server+f'/api/gameplay-memory/runs/{inp.run_id}/demo/result',headers=ctx.headers,
                        json={'job_id':ctx.job_id,'status':status},timeout=10).raise_for_status()
                    if not inp.loop:break
                    status['state']='playing'
            except InterruptedError as error:status.update(state='yielded',reason=str(error),verified=False)
            except Exception as error:status.update(state='failed',reason=str(error)[:240],verified=False)
            finally:
                try:
                    httpx.post(ctx.server+f'/api/gameplay-memory/runs/{inp.run_id}/demo/result',headers=ctx.headers,
                               json={'job_id':ctx.job_id,'status':status},timeout=10)
                except Exception:pass
                if tools.SESSIONS.get(sid,(None,))[0] is ad:
                    try:ad.send_input([{'key':key,'down':False} for key in ('up','down','left','right','a','b','x','y','l','r','start')])
                    except Exception:pass
                    try:ad.stop_game()
                    finally:
                        try:cleanup_demo(folder,root,ad.proc)
                        except OSError:pass
        threading.Thread(target=watch,daemon=True,name='gameplay-demo-'+sid).start()
        return {'session_id':sid,'adapter':ad.name,'capabilities':ad.get_capabilities(),'detail':detail}


def install(app,store,config,auth,submit,workers,archive):
    from fastapi import Depends,HTTPException
    from .server import JobRequest
    class Request(BaseModel):
        worker:str=''
        loop:bool=False
    class Idle(BaseModel):
        enabled:bool
    class Result(BaseModel):
        job_id:str
        status:dict
    def launch(sid,body,actor,idle=False):
        source=store.get('session',sid)
        if not source:raise HTTPException(404,'Recorded session not found')
        plan=archive.demo(sid)
        if not plan['ready']:raise HTTPException(409,plan['reason'])
        game=store.catalog_get(source.get('game_id'))
        if not game:raise HTTPException(404,'Recorded game is no longer in the owned library')
        choices=[w for w in workers() if w.get('online') and w.get('os')=='windows' and 'gameplay_demo' in w.get('tools',[])
                 and not w.get('active_jobs') and (not body.worker or body.worker in (w['id'],w['name']))]
        reasons=[background.guarded_reason(store,w,require_gpu=False) for w in choices]
        chosen=next((w for w,reason in zip(choices,reasons) if not reason),None)
        if not chosen:raise HTTPException(409,next((r for r in reasons if r),'Waiting for an available idle PC; current games stay running'))
        return submit(JobRequest(tool='gameplay_demo',input={'run_id':sid,'game':game,'loop':body.loop,'idle_demo':idle,
                                 'source_revision':plan_revision(plan)},
                                 agent_use=True,low_priority=True,require_worker=chosen['id']),actor=actor,
                      origin={'via':'PSO observed-input demonstration','run_id':sid})
    @app.post('/api/gameplay-memory/runs/{sid}/demo/play')
    def request(sid:str,body:Request,actor=Depends(auth)):return launch(sid,body,actor)
    @app.get('/api/gameplay-memory/runs/{sid}/demo/idle')
    def pref(sid:str,actor=Depends(auth)):return store.get('gameplay_demo_idle',sid) or {'enabled':False}
    @app.post('/api/gameplay-memory/runs/{sid}/demo/idle')
    def preference(sid:str,body:Idle,actor=Depends(auth)):
        if not store.get('session',sid):raise HTTPException(404,'Recorded session not found')
        store.put('gameplay_demo_idle',sid,body.model_dump()|{'run_id':sid})
        return {'enabled':body.enabled,'scope':'separate idle test sessions','exact_tas':False}
    @app.post('/api/gameplay-memory/runs/{sid}/demo/result')
    def result(sid:str,body:Result,actor=Depends(auth)):
        job=store.get('job',body.job_id)
        if not job or job.get('tool')!='gameplay_demo' or job.get('input',{}).get('run_id')!=sid:
            raise HTTPException(409,'Demo result does not belong to this run')
        status={k:v for k,v in body.status.items() if k in ('state','loops','pads','actions','restores','skipped','reason','verified','frame_sha256')}
        for name in ('loops','pads','actions','restores','skipped'):
            if type(status.get(name)) is not int or status[name]<0:raise HTTPException(422,'Invalid observed-demo counters')
        if status.get('verified'):
            sha=status.get('frame_sha256','')
            if not re.fullmatch('[a-f0-9]{64}',sha) or not store.get('artifact',sha):
                raise HTTPException(422,'A successful observed demo needs its captured gameplay frame')
        # Verified here means the selected observed events and native actions
        # completed, never exact input/AI policy learning/level completion.
        row={'job_id':body.job_id,'at':time.time(),'status':status,'exact_tas':False}
        store.put('gameplay_demo_result',body.job_id,row)
        return row
    def tick():
        if any(j.get('tool')=='gameplay_demo' and j.get('state') in ('queued','running') for j in store.all('job')):return
        if any(s.get('state')=='running' and (s.get('detail') or {}).get('gameplay_demo') for s in store.running_sessions()):return
        if not getattr(config,'gameplay_memory_enabled',True):return
        # The operator asked every completed PSO run to become a demonstration.
        # Existing PC opt-in/admission still controls where it may execute, and
        # an explicit per-run disabled preference always wins over discovery.
        from .pso_controls import is_pso
        for run in archive.runs(limit=50):
            sid=run['id'];source=store.get('session',sid) or {}
            if source.get('state')!='ended':continue
            if background.agent_owned(store.get('slabel',sid),store.get('job',sid.split('-',1)[-1])):continue
            game=store.catalog_get(source.get('game_id')) or source
            if not is_pso(game) or not run.get('observed_demo',{}).get('ready'):continue
            if store.get('gameplay_demo_idle',sid) is None:
                store.put('gameplay_demo_idle',sid,{'run_id':sid,'enabled':True,'automatic':True})
        for sidpref in store.all('gameplay_demo_idle'):
            # Some stores return documents without their key. Store the source
            # explicitly in preferences below rather than infer a run identity.
            sid=sidpref.get('run_id')
            if not sid or not sidpref.get('enabled') or time.time()-sidpref.get('last',0)<300:continue
            source=store.get('session',sid) or {}
            if source.get('state')!='ended':continue
            plan=archive.demo(sid)
            if not plan.get('ready'):continue
            revision=plan_revision(plan)
            last_job=store.get('job',sidpref.get('last_job','')) or {}
            last_result=store.get('gameplay_demo_result',sidpref.get('last_job','')) or {}
            if sidpref.get('attempt_revision')==revision and (last_job.get('state') in ('failed','invalid','rejected') or
                    last_result.get('status',{}).get('state')=='failed'):
                continue
            verified=any((store.get('job',r.get('job_id')) or {}).get('input',{}).get('run_id')==sid and
                         (store.get('job',r.get('job_id')) or {}).get('input',{}).get('source_revision')==revision and
                         r.get('status',{}).get('verified') and r.get('status',{}).get('state')=='finished'
                         for r in store.all('gameplay_demo_result'))
            # One automatic verification per immutable prefix. A failed run is
            # retained for inspection rather than repeatedly launched forever.
            if not verified and sidpref.get('verification_attempt')==revision:continue
            try:
                job=launch(sid,Request(loop=verified),'gameplay-screensaver',idle=True)
                update={'last':time.time(),'last_job':job.get('id') or job.get('job_id'),
                        'phase':'looping' if verified else 'verification_queued','attempt_revision':revision}
                if not verified:update['verification_attempt']=revision
                store.put('gameplay_demo_idle',sid,sidpref|update)
                break
            except HTTPException:pass
    app.state.gameplay_demo_idle_tick=tick
    stopped=threading.Event()
    def loop():
        while not stopped.wait(30):
            try:tick()
            except Exception:pass
    app.on_event('startup')(lambda:threading.Thread(target=loop,daemon=True,name='gameplay-demo-idle').start())
    app.on_event('shutdown')(stopped.set)
