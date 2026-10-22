"""Spark's revisioned memory-card vault. Leases and CAS prevent concurrent save loss."""
import base64,hashlib,json,time,uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from fastapi import Depends,HTTPException
from fastapi.responses import Response
from pydantic import BaseModel,Field

Platform=Literal['dreamcast','gamecube']
KIND='memory_card'


class CardIn(BaseModel):
    name:str=Field(min_length=1,max_length=80)
    platform:Platform
    game_id:str=Field(default='',max_length=64)
    data_b64:str|None=Field(default=None,max_length=24*1024*1024)
    source_key:str=Field(default='',pattern='^(?:[a-f0-9]{64})?$')
    clone_from:str=Field(default='',pattern='^(?:[a-f0-9]{32})?$')


class Owner(BaseModel):
    owner:str=Field(min_length=3,max_length=128)
    worker_id:str=Field(min_length=1,max_length=64)
    takeover_from:str=Field(default='',max_length=128)    # a restart relaunch: the same worker's session it replaces


class SyncIn(Owner):
    base_revision:int=Field(ge=1)
    data_b64:str=Field(max_length=24*1024*1024)
    release:bool=False


class SelectionIn(BaseModel):
    game_id:str=Field(min_length=1,max_length=64)
    platform:Platform
    slot:str=Field(max_length=2)
    card_id:str=Field(pattern='^[a-f0-9]{32}$')


def routes(app,store,config,auth):
    from . import memory_card_emulators as native
    root=config.data_dir/'memory-cards'/'blobs';root.mkdir(parents=True,exist_ok=True)
    def read(kind,key):
        r=store.db.execute('SELECT body FROM docs WHERE kind=? AND id=?',(kind,key)).fetchone()
        return json.loads(r[0]) if r else None
    def write(kind,key,row):
        store.db.execute('INSERT OR REPLACE INTO docs(kind,id,body) VALUES(?,?,?)',(kind,key,json.dumps(row)))
    @contextmanager
    def tx():
        with store.lock:
            store.db.execute('BEGIN IMMEDIATE')
            try:yield;store.db.commit()
            except BaseException:store.db.rollback();raise
    def card(cid):
        r=read(KIND,cid)
        if not r:raise HTTPException(404,'Memory card not found')
        return r
    def validate(raw,platform):
        if not 0<len(raw)<=16*1024*1024:raise HTTPException(422,'Memory-card image exceeds the supported size')
        try:info=native.describe(raw,platform)
        except (ValueError,IndexError) as e:raise HTTPException(422,'Invalid or incomplete native memory-card image; original cloud card kept') from e
        if not info.get('formatted'):raise HTTPException(422,'Invalid or incomplete native memory-card image; original cloud card kept')
        return info
    def decode(data):
        try:return base64.b64decode(data,validate=True)
        except (ValueError,TypeError) as e:raise HTTPException(422,'Invalid memory-card data') from e
    def blob(raw):
        sha=hashlib.sha256(raw).hexdigest();path=root/sha
        if not path.exists():
            tmp=root/(sha+'.'+uuid.uuid4().hex+'.tmp');tmp.write_bytes(raw);tmp.replace(path)
        return sha
    def identity(value):
        if value.owner.split('-',1)[0]!=value.worker_id or not read('worker',value.worker_id):
            raise HTTPException(403,'Memory-card lease must belong to its session worker')
        s=read('session',value.owner)
        if s and s.get('worker_id',value.worker_id)!=value.worker_id:raise HTTPException(403,'Session belongs to another worker')
    def owned(row,value):
        identity(value)
        lease=row.get('lease') or {}
        if lease.get('owner')!=value.owner or lease.get('worker_id')!=value.worker_id:
            raise HTTPException(409,'This card is held by another session. Your local save was kept; no cloud version was overwritten')
    def public(row):
        return {k:v for k,v in row.items() if k not in ('source_key',)}
    def selection(gid,platform):return read('memory_card_selection',gid+'-'+platform) or {'game_id':gid,'platform':platform,'slots':{}}

    @app.get('/api/memory-cards')
    def listing(platform:Platform,session_id:str='',game_id:str='',actor=Depends(auth)):
        with store.lock:
            s=read('session',session_id) or {};gid=game_id or s.get('game_id','')
            rows=[public(json.loads(r[0])) for r in store.db.execute('SELECT body FROM docs WHERE kind=?',(KIND,)) if json.loads(r[0]).get('platform')==platform]
            return {'platform':platform,'cards':sorted(rows,key=lambda c:c.get('updated',0),reverse=True),'selection':selection(gid,platform)['slots'],'session':s.get('detail',{}).get('memory_cards')}

    @app.post('/api/memory-cards')
    def create(value:CardIn,actor=Depends(auth)):
        name=value.name.strip()
        if not name:raise HTTPException(422,'Give the card a name')
        if value.game_id:
            g=store.catalog_get(value.game_id)
            if not g or g.get('platform')!=value.platform:raise HTTPException(422,'Choose a game on the card platform')
        if value.clone_from and value.data_b64 is not None:raise HTTPException(422,'Choose an existing card or uploaded image, not both')
        try:
            if value.clone_from:
                with store.lock:
                    source=card(value.clone_from)
                    if source['platform']!=value.platform:raise HTTPException(422,'Source card must use the same platform')
                    raw=(root/source['sha256']).read_bytes()
                if value.platform=='dreamcast' and value.game_id:
                    # Explicit dedicated PSO creation keeps its native files,
                    # leaving other games on the original card to recover space.
                    game=store.catalog_get(value.game_id) or {}
                    if 'phantasy star online' in game.get('title','').lower():
                        names=[f['name'] for f in source['capacity']['files'] if f['name'].upper().startswith('PSO')]
                        raw=native.copy_saves(raw,native.blank('dreamcast'),names)
            else:raw=decode(value.data_b64) if value.data_b64 is not None else native.blank(value.platform)
        except ValueError as e:raise HTTPException(422,str(e)) from e
        capacity=validate(raw,value.platform);sha=blob(raw);now=time.time()
        with tx():
            if value.source_key:
                old=next((json.loads(r[0]) for r in store.db.execute('SELECT body FROM docs WHERE kind=?',(KIND,)) if json.loads(r[0]).get('source_key')==value.source_key),None)
                if old:
                    if old['platform']!=value.platform:raise HTTPException(409,'An imported card key belongs to another platform')
                    return public(old)
            cid=uuid.uuid4().hex
            row={'id':cid,'name':name,'platform':value.platform,'revision':1,'sha256':sha,'capacity':capacity,
                 'game_id':value.game_id,'source_key':value.source_key,'copied_from':value.clone_from,'created':now,'updated':now,'lease':None,
                 'versions':[{'revision':1,'sha256':sha,'created':now}]}
            write(KIND,cid,row)
            if value.game_id:
                s=selection(value.game_id,value.platform);s['slots']['A1' if value.platform=='dreamcast' else 'A']=cid
                write('memory_card_selection',value.game_id+'-'+value.platform,s)
        store.audit(actor,'memory_card.create',cid,{'platform':value.platform,'imported':value.data_b64 is not None})
        return public(row)

    @app.post('/api/memory-cards/selection')
    def select(value:SelectionIn,actor=Depends(auth)):
        with tx():
            row=card(value.card_id)
            g=store.catalog_get(value.game_id)
            if not g or g.get('platform')!=value.platform or row['platform']!=value.platform or value.slot not in native.slots(value.platform):
                raise HTTPException(422,'Card, game and slot must use the same platform')
            s=selection(value.game_id,value.platform)
            if any(slot!=value.slot and cid==value.card_id for slot,cid in s['slots'].items()):
                raise HTTPException(409,'The same card cannot be inserted into two writable slots at once')
            s['slots'][value.slot]=row['id'];write('memory_card_selection',value.game_id+'-'+value.platform,s)
        return s

    @app.get('/api/memory-cards/{cid}/data')
    def download(cid:str,revision:int|None=None,actor=Depends(auth)):
        with store.lock:
            row=card(cid);version=next((v for v in row['versions'] if v['revision']==revision),None) if revision else row
            if not version:raise HTTPException(404,'Memory-card revision not found')
            raw=(root/version['sha256']).read_bytes()
        return Response(raw,media_type='application/octet-stream',headers={'X-Memory-Card-Revision':str(version['revision']),'ETag':version['sha256'],'Cache-Control':'no-store'})

    @app.post('/api/memory-cards/{cid}/lease')
    def lease(cid:str,value:Owner,actor=Depends(auth)):
        with tx():
            identity(value);row=card(cid);old=row.get('lease')
            if old and (old.get('owner')!=value.owner or old.get('worker_id')!=value.worker_id):
                s=read('session',old['owner']);job=read('job',old['owner'].split('-',1)[-1])
                active=(s or {}).get('state')=='running' or (job or {}).get('state') in ('queued','running')
                # The operator's own launch takes a card back from an agent-owned demo (the screensaver, #2817): the
                # demo's later syncs are refused (409), its local save is kept, no cloud version is overwritten.
                mine=read('job',value.owner.split('-',1)[-1]) or {}
                demo=bool((job or {}).get('agent_use')) and bool(mine) and not mine.get('agent_use')
                # A restart relaunch (session_reset) on the same worker replaces its own live session: the card moves to
                # the new copy, the old copy's later syncs are refused (409) and its local save is kept.
                restart=bool(value.takeover_from) and old.get('owner')==value.takeover_from and old.get('worker_id')==value.worker_id
                if (active or time.time()-old['updated']<90) and not demo and not restart:raise HTTPException(409,'This card is already inserted in another session. Sync and close that session before sharing it')
            row['lease']={'owner':value.owner,'session_id':value.owner,'worker_id':value.worker_id,'updated':time.time()}
            write(KIND,cid,row)
        return public(row)

    @app.post('/api/memory-cards/{cid}/release')
    def release(cid:str,value:Owner,actor=Depends(auth)):
        with tx():
            row=card(cid);owned(row,value);row['lease']=None;write(KIND,cid,row)
        return public(row)

    @app.post('/api/memory-cards/{cid}/sync')
    def sync(cid:str,value:SyncIn,actor=Depends(auth)):
        raw=decode(value.data_b64)
        with store.lock:platform=card(cid)['platform']
        capacity=validate(raw,platform);sha=blob(raw)
        with tx():
            row=card(cid);owned(row,value)
            if row['revision']!=value.base_revision:raise HTTPException(409,'A newer cloud save exists. Local save kept for recovery; no version was overwritten')
            if sha!=row['sha256']:
                row.update(revision=row['revision']+1,sha256=sha,capacity=capacity,updated=time.time())
                row['versions'].append({'revision':row['revision'],'sha256':sha,'created':row['updated']})
                row['versions']=row['versions'][-32:]
            row['lease']=None if value.release else row['lease']|{'updated':time.time()}
            write(KIND,cid,row)
        return public(row)
