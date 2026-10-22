"""Local working cards with Spark snapshots; game processes never write a network share."""
import base64,hashlib,json,threading,time,uuid
from pathlib import Path
from typing import Literal
import httpx
from pydantic import BaseModel,Field,ConfigDict
from . import memory_card_emulators as native

_contexts={};_locks={};_guard=threading.RLock()


def lock(sid):
    with _guard:return _locks.setdefault(sid,threading.RLock())


def api(ctx,path,body=None,raw=False):
    with httpx.Client(base_url=ctx.server,headers=ctx.headers,timeout=5) as client:
        response=client.post(path,json=body) if body is not None else client.get(path)
        if response.status_code>=400:
            try:message=response.json().get('detail',response.text)
            except ValueError:message=response.text
            raise RuntimeError(str(message))
        return response.content if raw else response.json()


def stable(path,platform,final=False):
    """Read twice from a stable path identity; reject native partial filesystem writes."""
    path=Path(path);before=path.stat()
    if not final and time.time()-before.st_mtime<2:raise RuntimeError('The game is writing this card; wait for the save to finish and sync again')
    a=path.read_bytes();time.sleep(.1);after=path.stat();b=path.read_bytes()
    if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino) or a!=b:raise RuntimeError('The memory card changed during sync; local save kept for the next attempt')
    if not native.describe(a,platform)['formatted']:raise RuntimeError('The game has not finished a valid card image; local save kept')
    return a


def journal(context):
    # Recovery files include exact card identity/base revision and are retained
    # after failed upload. They never contain credentials.
    folder=Path(context['work_dir']);folder.mkdir(parents=True,exist_ok=True)
    row={k:v for k,v in context.items() if k not in ('adapter','ctx','thread','game')}
    tmp=folder/'sync-journal.tmp';tmp.write_text(json.dumps(row,indent=2));tmp.replace(folder/'sync-journal.json')


def launched(ad):
    """Record process identity immediately, before potentially slow boot checks."""
    context=getattr(ad,'memory_card_context',None)
    if context is None:return
    context['pid']=ad.proc.pid
    try:context['process_created']=__import__('psutil').Process(ad.proc.pid).create_time()
    except Exception:pass
    journal(context)


def row_for(context,slot,card,path):
    return {'slot':slot,'card_id':card['id'],'name':card['name'],'revision':card['revision'],'sha256':card['sha256'],
            'path':str(path),'capacity':card['capacity'],'sync_state':'synced','last_synced':time.time()}


def owner(sid,ctx,takeover=''):return {'owner':sid,'worker_id':ctx.worker}|({'takeover_from':takeover} if takeover else {})


def import_file(sid,ad,game,ctx,slot,path):
    data=stable(path,game['platform'])
    key=hashlib.sha256((__import__('platform').node()+'|'+game['platform']+'|'+str(Path(path).resolve())).encode()).hexdigest()
    card=api(ctx,'/api/memory-cards',{'name':f'{__import__("platform").node()} · original {slot}','platform':game['platform'],
        'source_key':key,'data_b64':base64.b64encode(data).decode()})
    if card['sha256']!=hashlib.sha256(data).hexdigest():
        # An existing cloud version must never be replaced by an unknown older
        # legacy file that was already open when management attached.
        card=api(ctx,'/api/memory-cards',{'name':f'{__import__("platform").node()} · recovered local {slot}','platform':game['platform'],
            'source_key':hashlib.sha256((key+hashlib.sha256(data).hexdigest()).encode()).hexdigest(),'data_b64':base64.b64encode(data).decode()})
    return card


def checkout(sid,ad,game,ctx,operator_cards=False,keep=''):
    """Before launch, lease selected cloud revisions and stage exact local copies.

    Cloud cards are an enhancement, not a precondition: when the control plane is
    unreachable or slow (an httpx transport error) the launch falls back to local
    cards instead of failing, and no cloud sync starts for this session.

    Agent-owned launches leave the operator's cards alone, except a demo that asks for them
    (operator_cards: the screensaver, so the operator's saved characters load; #2817, operator
    2026-10-20: "get my memory card ... use it with screensaver for playing the game"). Such a
    demo only inserts cards already selected for the game, plays without them when another
    session holds one, and the operator's own launch takes a card back from it (memory_cards.lease).
    """
    if game.get('platform') not in ('dreamcast','gamecube') or not ctx.server:return None
    if not supported(ad,game):return None
    if getattr(ad,'tas_playback',None) or getattr(ad,'capture_backend',None):return None
    demo=bool(getattr(ctx,'agent_use',False))
    if demo and not operator_cards:return None
    try:
        return _checkout(sid,ad,game,ctx,selected_only=demo,keep=keep)
    except httpx.HTTPError as error:
        ad.memory_card_unavailable=f'{type(error).__name__}: {error}'
        print(f'gBox: cloud memory cards unavailable at launch ({ad.memory_card_unavailable}); playing from local cards', flush=True)
        return None
    except RuntimeError as error:
        if not demo:raise
        ad.memory_card_unavailable=str(error)[:300]       # e.g. the operator's game holds the card right now
        print(f"gBox: this demo plays without the operator's memory card ({ad.memory_card_unavailable})", flush=True)
        return None


def _checkout(sid,ad,game,ctx,selected_only=False,keep=''):
    platform=game['platform'];listing=api(ctx,f'/api/memory-cards?platform={platform}&game_id={game["game_id"]}')
    selected=dict(listing['selection']);cards={r['id']:r for r in listing['cards']}
    warnings=[]
    if not selected and selected_only:return None     # a demo never imports, creates or selects cards for the operator
    if not selected:
        for r in native.discover(ad,game):
            try:
                card=import_file(sid,ad,game,ctx,r['slot'],r['path']);cards[card['id']]=card;selected[r['slot']]=card['id']
            except Exception as error:warnings.append(f'{r["slot"]}: {str(error)[:250]}')
        if not selected:
            card=api(ctx,'/api/memory-cards',{'name':game['title']+' · card','platform':platform})
            cards[card['id']]=card;selected['A1' if platform=='dreamcast' else 'A']=card['id']
        for slot,cid in selected.items():api(ctx,'/api/memory-cards/selection',{'game_id':game['game_id'],'platform':platform,'slot':slot,'card_id':cid})
    if len(set(selected.values()))!=len(selected):raise RuntimeError('The same cloud card cannot be inserted in two writable slots')
    context={'platform':platform,'work_dir':str(ctx.config.data_dir/'memory-cards'/'sessions'/sid),'slots':{},'session_id':sid,'worker_id':ctx.worker,'game_id':game['game_id'],'pending':{},'warnings':warnings}
    folder=Path(context['work_dir']);folder.mkdir(parents=True,exist_ok=True)
    acquired=[]
    old=_contexts.get(keep) if keep and keep!=sid else None
    if old and old.get('game_id')==game['game_id']:      # restart relaunch: bank the live copy's save, then take its card over
        sync(old,ctx)
    else:keep=''
    try:
        for slot,cid in selected.items():
            card=api(ctx,f'/api/memory-cards/{cid}/lease',owner(sid,ctx,keep))
            acquired.append(cid)
            data=api(ctx,f'/api/memory-cards/{cid}/data?revision={card["revision"]}',raw=True)
            if hashlib.sha256(data).hexdigest()!=card['sha256'] or not native.describe(data,platform)['formatted']:raise RuntimeError('Cloud card download failed its native hash/format check')
            path=folder/(slot+'.'+('bin' if platform=='dreamcast' else 'raw'))
            if path.exists():raise RuntimeError('A recovery card already exists for this session; it was not overwritten')
            path.write_bytes(data);context['slots'][slot]=row_for(context,slot,card,path)
        ad.memory_card_context=context;journal(context)
        return context
    except Exception:
        for cid in acquired:
            try:api(ctx,f'/api/memory-cards/{cid}/release',owner(sid,ctx))
            except Exception:pass
        raise


def sync(context,ctx,slot=None,final=False):
    rows=context['slots'].values() if slot is None else [context['slots'][slot]]
    errors=[]
    for row in rows:
        try:
            data=stable(row['path'],context['platform'],final)
            card=api(ctx,f'/api/memory-cards/{row["card_id"]}/sync',{'owner':context['session_id'],'worker_id':context.get('worker_id',ctx.worker)}|{
                'base_revision':row['revision'],'data_b64':base64.b64encode(data).decode(),'release':final})
            row.update(revision=card['revision'],sha256=card['sha256'],capacity=card['capacity'],sync_state='synced',last_synced=time.time())
            row.pop('error',None)
        except Exception as error:
            row.update(sync_state='conflict' if 'newer cloud' in str(error) or 'another session' in str(error) else 'pending',error=str(error)[:500])
            errors.append(str(error))
    journal(context)
    return errors


def status(context):
    return {'supported':True,'live_switch':False,'reason':'This emulator caches its memory card. A selected replacement is inserted on the next launch; the current game and saves stay intact.',
        'warnings':context.get('warnings',[]),
        'slots':[{k:v for k,v in row.items() if k!='path'}|({'pending_card_id':context['pending'][slot]} if slot in context.get('pending',{}) else {}) for slot,row in context['slots'].items()]}


def publish(context,ctx):
    try:api(ctx,f'/api/sessions/{context["session_id"]}/detail',{'memory_cards':status(context)})
    except Exception:pass


def attach(sid,ad,game,ctx):
    """Attach management to existing files without replacing a running core's cached card."""
    if sid in _contexts:return _contexts[sid]
    if not supported(ad,game):raise RuntimeError(getattr(ad,'memory_card_unavailable','Managed cards currently support Flycast through RetroArch and standalone Dolphin'))
    context=getattr(ad,'memory_card_context',None)
    if context is None:
        context={'platform':game['platform'],'work_dir':str(ctx.config.data_dir/'memory-cards'/'sessions'/sid),'slots':{},'session_id':sid,'worker_id':ctx.worker,'game_id':game['game_id'],'pending':{},'warnings':[]}
        for item in native.discover(ad,game):
            try:
                card=import_file(sid,ad,game,ctx,item['slot'],item['path'])
                card=api(ctx,f'/api/memory-cards/{card["id"]}/lease',owner(sid,ctx))
                context['slots'][item['slot']]=row_for(context,item['slot'],card,item['path'])
            except Exception as error:context['warnings'].append(f'{item["slot"]}: {str(error)[:250]}')
        if not context['slots']:raise RuntimeError('No native memory-card file is available yet. Let the emulator finish initializing its card, then refresh')
        ad.memory_card_context=context
    _contexts[sid]=context;journal(context)
    return context


def watch(sid,ad,game,ctx):
    context=attach(sid,ad,game,ctx)
    if context.get('watching'):return status(context)
    context['watching']=True
    if getattr(ad,'proc',None):
        context['pid']=ad.proc.pid
        try:context['process_created']=__import__('psutil').Process(ad.proc.pid).create_time()
        except Exception:pass
    journal(context)
    def run():
        from .tools import SESSIONS
        while sid in SESSIONS and (getattr(ad,'proc',None) is None or ad.proc.poll() is None):
            time.sleep(15)
            with lock(sid):
                if sid in _contexts and not context.get('closed'):sync(context,ctx);publish(context,ctx)
        with lock(sid):
            proc=getattr(ad,'proc',None)
            if sid in _contexts and proc is not None and proc.poll() is not None:finish(sid,ad,ctx)
    threading.Thread(target=run,name='memory-cards-'+sid,daemon=True).start()
    return status(context)


def finish(sid,ad,ctx):
    """Flush only after confirmed process exit, retaining failed local snapshots."""
    with lock(sid):
        context=_contexts.get(sid) or getattr(ad,'memory_card_context',None)
        if not context or context.get('closed'):return
        proc=getattr(ad,'proc',None)
        if proc is None or proc.poll() is None:return
        errors=sync(context,ctx,final=True);context['closed']=True;context['pending_upload']=bool(errors)
        journal(context);_contexts.pop(sid,None)


def supported(ad,game):
    matches=(game.get('platform')=='dreamcast' and getattr(ad,'name','')=='retroarch' or
             game.get('platform')=='gamecube' and getattr(ad,'name','')=='dolphin')
    if not matches:return False
    rom=getattr(ad,'memory_card_rom',None) or game.get('_rom_path')
    if game.get('platform')=='gamecube' and rom:
        try:native.gc_region(ad,rom)
        except ValueError as error:
            ad.memory_card_unavailable=str(error)
            return False
    return True


def abandon(ad,ctx):
    """Preserve startup writes on failed launches; never touch a live process."""
    context=getattr(ad,'memory_card_context',None)
    proc=getattr(ad,'proc',None)
    if not context or (proc is not None and proc.poll() is None):return
    try:
        changed=any(hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()!=row['sha256'] for row in context['slots'].values())
    except OSError:changed=True
    errors=[]
    if changed:errors=sync(context,ctx,final=True)
    else:
        for row in context['slots'].values():
            try:api(ctx,f'/api/memory-cards/{row["card_id"]}/release',{'owner':context['session_id'],'worker_id':context.get('worker_id',ctx.worker)})
            except Exception as error:errors.append(str(error))
    context['closed']=True;context['pending_upload']=bool(errors);journal(context)


def recover_pending(ctx):
    """Retry only closed/crashed local cards under their original CAS lease identity."""
    if ctx is None or not getattr(ctx,'server',None):return
    root=ctx.config.data_dir/'memory-cards'/'sessions'
    for path in root.glob('*/sync-journal.json'):
        try:
            c=json.loads(path.read_text());sid=c['session_id']
            if sid in _contexts or (c.get('closed') and not c.get('pending_upload')):continue
            if c.get('pid'):
                import psutil
                try:
                    process=psutil.Process(c['pid'])
                    if not c.get('process_created') or process.create_time()==c['process_created']:continue
                except psutil.NoSuchProcess:pass
            errors=sync(c,ctx,final=True);c.update(closed=True,pending_upload=bool(errors));journal(c)
        except Exception:continue


class Command(BaseModel):
    model_config=ConfigDict(extra='forbid')
    op:Literal['status','select','sync','import_current']='status'
    slot:str=Field(default='A1',max_length=2)
    card_id:str=Field(default='',pattern='^(?:[a-f0-9]{32})?$')


def validate(store,sid,body):
    if not isinstance(body,dict) or set(body)!={'command_id','expires','input'}:raise ValueError('Memory-card command requires its ID, expiry and input')
    uuid.UUID(body['command_id'])
    expiry=body['expires']
    if type(expiry) not in (int,float) or not time.time()<expiry<=time.time()+15:raise ValueError('Memory-card command expired; no change applied')
    value=Command.model_validate(body['input'])
    s=store.get('session',sid)
    if not s or s.get('state')!='running':raise ValueError('Select a running session to manage its inserted cards')
    game=store.catalog_get(s.get('game_id')) or {}
    if game.get('platform') not in ('dreamcast','gamecube'):raise ValueError('Memory-card management supports Dreamcast and GameCube')
    worker=store.get('worker',s.get('worker_id') or sid.split('-')[0]) or {}
    for name in ('memory_card_sessions.py','memory_card_emulators.py','tools.py','adapters.py'):
        if worker.get('build_sources',{}).get('gbox/'+name)!=hashlib.sha256((Path(__file__).parent/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest():
            raise ValueError('This worker needs an idle update to load memory-card management. The current game was kept running')
    return value


def execute(sid,body,ctx):
    from .tools import SESSIONS
    from .models import Permission
    if ctx is None or Permission.STAGE not in ctx.config.granted_permissions:raise PermissionError('stage permission is required for memory-card sync')
    if not time.time()<body.get('expires',0):raise ValueError('Memory-card command expired')
    value=Command.model_validate(body['input']);ad,game=SESSIONS[sid]
    if not lock(sid).acquire(blocking=False):raise RuntimeError('A memory-card sync is in progress; no extra operation was queued')
    try:
        existed=sid in _contexts
        context=attach(sid,ad,game,ctx)
        if not existed:watch(sid,ad,game,ctx)
        if value.op=='select':
            if value.slot not in native.slots(game['platform']):raise ValueError('Choose a valid native card slot')
            api(ctx,'/api/memory-cards/selection',{'game_id':game['game_id'],'platform':game['platform'],'slot':value.slot,'card_id':value.card_id})
            context['pending'][value.slot]=value.card_id;journal(context)
            return status(context)|{'pending':True,'message':'Card selected for the next launch. The current game was not restarted and its inserted card was not replaced.'}
        if value.op=='sync':
            if value.slot not in context['slots']:raise ValueError('No card is inserted in this slot')
            errors=sync(context,ctx,value.slot)
            return status(context)|{'message':' '.join(errors) if errors else 'Memory card synced to Spark.'}
        return status(context)
    finally:lock(sid).release()
