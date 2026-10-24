"""Durable completed-round transfer between a local authority and central Reviewer.

Only measured per-round Atlas/Notebook rows travel. No RAM dump, SQLite file,
aggregate navigation policy, original SVG or claimed semantic-delivery flag is
imported. Authentication proves the reporting authority, not a central RAM read.
"""
from __future__ import annotations

from contextlib import closing
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
import zlib

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..store import canon,sha256

MAX_RAW=8*1024*1024
CHUNK=512*1024
MAX_COMPRESSED=4*1024*1024
MAX_ROWS=12000
HEX=re.compile(r'[a-f0-9]{64}\Z')
ROUND=re.compile(r'([a-f0-9]{32})(?::[A-Za-z0-9_-]{1,100})?\Z')
TITLES={'G4BE08':('78ab9efa2e310db4','e42c9b780c07c437'),'BLUS30491':('e7ca89bbeb67360d',)}
STATE_FILES={'index.json','blocked.json','scan.json'}
_IMPORT_LOCK=threading.RLock()


def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('wb') as stream:
        stream.write(data);stream.flush()
        __import__('os').fsync(stream.fileno())
    temporary.replace(path)


def read_rows(path,query,args=()):
    if not path.is_file():return []
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
        return [dict(row) for row in db.execute(query,args)]


def finite_json(value):
    json.dumps(value,allow_nan=False)


def export_round(data_dir,title,rid,session):
    """A closed immutable row, with explicit recorder session provenance."""
    if title not in TITLES or not ROUND.fullmatch(rid):raise ValueError('Unknown exact title/round')
    root=Path(data_dir).resolve()/'mercs'
    atlas=root/'navigation'/title/'atlas.sqlite'
    rows=read_rows(atlas,'SELECT * FROM rounds WHERE id=? AND ended IS NOT NULL AND outcome IS NOT NULL',(rid,))
    if len(rows)!=1:raise ValueError('Round is not closed')
    row=rows[0];metadata=json.loads(row['metadata'])
    if metadata.get('source_session_id')!=session['session_id'] or session.get('game_id') not in TITLES[title]:
        raise ValueError('Exact persisted round/session origin is required')
    stage=read_rows(atlas,'SELECT * FROM stages WHERE key=?',(row['stage'],))[0]
    stage={**stage,'geometry':json.loads(stage['geometry']),'metadata':json.loads(stage['metadata'])}
    row={k:row[k] for k in ('id','stage','started','ended','outcome')}
    row.update(metadata=metadata,review=json.loads(rows[0]['review'] or '{}'))
    samples=read_rows(atlas,'SELECT seq,at,payload FROM samples WHERE round_id=? ORDER BY seq LIMIT ?',
                      (rid,MAX_ROWS+1))
    events=read_rows(atlas,'SELECT seq,at,kind,payload FROM events WHERE round_id=? ORDER BY seq LIMIT ?',
                     (rid,MAX_ROWS+1))
    if len(samples)>MAX_ROWS or len(events)>MAX_ROWS:raise ValueError('Round exceeds bounded sample/event transfer')
    for item in samples+events:item['payload']=json.loads(item['payload'])
    base=ROUND.fullmatch(rid).group(1)
    notes=read_rows(root/'curriculum'/title/'rounds.sqlite','SELECT * FROM rounds WHERE id=?',(base,))
    if not notes or notes[0]['stage']!=row['stage'] or notes[0]['mode']!=metadata.get('mode'):
        raise ValueError('Matching Notebook review is not saved yet; local evidence was retained')
    note={k:notes[0][k] for k in ('id','ts','stage','mode','character','outcome')}
    note['observed']=json.loads(notes[0]['data'])
    bundle={'schema':'gbox.mercs.completed-round/1','title':title,
        'source':{'session_id':session['session_id'],'game_id':session['game_id']},
        'stage':stage,'round':row,'samples':samples,'events':events,'notebook':note}
    finite_json(bundle)
    raw=canon(bundle)
    if len(raw)>MAX_RAW:raise ValueError('Round exceeds 8 MiB JSON bound; local evidence was retained')
    return bundle,raw


class Receiver:
    def __init__(self,store,config,federation):
        self.store,self.config,self.federation=store,config,federation
        self.root=Path(config.data_dir)/'mercs'
        self.notebooks={}

    def scope(self,owner,source,title):
        if title not in TITLES or not isinstance(source,dict):raise ValueError('Unsupported measured title')
        sid=source.get('session_id');session=self.store.get('session',sid) if isinstance(sid,str) else None
        wid=sid.split('-',1)[0] if isinstance(sid,str) else ''
        worker=self.store.get('worker',wid) if wid else None
        if not session or not worker or session.get('worker_id',wid)!=wid \
                or (worker.get('federation') or {}).get('authority')!=owner['authority'] \
                or (session.get('federation') or {}).get('authority')!=owner['authority'] \
                or source.get('game_id')!=session.get('game_id') or source.get('game_id') not in TITLES[title]:
            raise PermissionError('Round origin does not match an acknowledged authority session')
        return sid

    def chunk_path(self,authority,digest):
        if not HEX.fullmatch(str(digest)):raise ValueError('Invalid chunk identity')
        return self.root/'evidence-chunks'/authority/(digest+'.part')

    def put_chunk(self,owner,digest,data):
        if not 0<len(data)<=CHUNK or sha256(data)!=digest:raise ValueError('Chunk size/hash mismatch')
        path=self.chunk_path(owner['authority'],digest)
        with _IMPORT_LOCK:
            if path.exists():
                if path.read_bytes()!=data:raise ValueError('Existing chunk identity changed')
            else:atomic(path,data)
        return {'stored':True,'sha256':digest}

    def import_manifest(self,owner,manifest):
        finite_json(manifest)
        if len(canon(manifest))>24000:raise ValueError('Manifest is too large')
        digest=manifest.get('sha256');title=manifest.get('title');source=manifest.get('source')
        if not HEX.fullmatch(str(digest)):raise ValueError('Invalid completed-round content hash')
        sid=self.scope(owner,source,title)
        prior=self.store.get('mercs_evidence',digest)
        if prior:
            if prior['authority']!=owner['authority']:raise PermissionError('Evidence belongs to another authority')
            if prior['source_session_id']!=sid or prior['title']!=title:raise PermissionError('Evidence origin changed')
            for chunk in prior.get('chunks',[]):self.chunk_path(owner['authority'],chunk).unlink(missing_ok=True)
            return prior['ack']
        chunks=manifest.get('chunks')
        if not isinstance(chunks,list) or not 1<=len(chunks)<=32:raise ValueError('A bounded chunk manifest is required')
        pieces=[];size=0
        for item in chunks:
            if not isinstance(item,dict) or type(item.get('size')) is not int or not 0<item['size']<=CHUNK:
                raise ValueError('Invalid chunk size')
            data=self.chunk_path(owner['authority'],item.get('sha256')).read_bytes()
            if len(data)!=item['size'] or sha256(data)!=item['sha256']:raise ValueError('Stored chunk does not verify')
            size+=len(data)
            if size>MAX_COMPRESSED:raise ValueError('Compressed round exceeds bound')
            pieces.append(data)
        decoder=zlib.decompressobj(31)
        raw=decoder.decompress(b''.join(pieces),MAX_RAW+1)
        if len(raw)>MAX_RAW or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
            raise ValueError('Invalid or oversized completed-round gzip')
        if sha256(raw)!=digest or len(raw)!=manifest.get('bytes'):raise ValueError('Completed-round digest/size mismatch')
        bundle=json.loads(raw);finite_json(bundle)
        if canon(bundle)!=raw or bundle.get('title')!=title or bundle.get('source')!=source:
            raise ValueError('Manifest does not match canonical evidence')
        ack=self.import_bundle(owner,bundle,digest,sid)
        receipt=self.store.get('mercs_evidence',digest)
        self.store.put('mercs_evidence',digest,receipt|{'chunks':[item['sha256'] for item in chunks]})
        # The durable content receipt handles a lost final response. Re-uploading
        # shared chunks is harmless; source evidence and pending outboxes remain.
        for item in chunks:self.chunk_path(owner['authority'],item['sha256']).unlink(missing_ok=True)
        return ack

    def import_bundle(self,owner,bundle,digest,sid=None):
        title=bundle.get('title');sid=sid or self.scope(owner,bundle.get('source'),title)
        if bundle.get('schema')!='gbox.mercs.completed-round/1':raise ValueError('Unknown evidence schema')
        row=bundle.get('round');stage=bundle.get('stage');samples=bundle.get('samples');events=bundle.get('events')
        if not isinstance(row,dict) or not ROUND.fullmatch(str(row.get('id'))) or not isinstance(stage,dict) \
                or not isinstance(samples,list) or not samples or len(samples)>MAX_ROWS \
                or not isinstance(events,list) or len(events)>MAX_ROWS:
            raise ValueError('Bounded closed round rows are required')
        rid=row['id'];base=ROUND.fullmatch(rid).group(1);geometry=stage.get('geometry')
        meta=row.get('metadata')
        if not isinstance(meta,dict) or meta.get('source_session_id')!=sid or stage.get('title')!=title \
                or not isinstance(row.get('stage'),str) or row['stage']!=stage.get('key') \
                or type(row.get('started')) not in (int,float) or type(row.get('ended')) not in (int,float) \
                or row['ended']<row['started'] or not isinstance(row.get('outcome'),str) \
                or not row['outcome'] or len(row['outcome'])>64 or not isinstance(geometry,dict):
            raise ValueError('Closed round/title/stage/source identity does not verify')
        finite_json(bundle)
        if title=='G4BE08':
            if geometry.get('geometry_available') is not False or geometry.get('units_per_m')!=1000 \
                    or any(geometry.get(key) for key in ('points','triangles','links','boundaries','action_links')):
                raise ValueError('RE4 coordinate-only evidence must not claim collision geometry')
        else:
            from .reviewer import _load_mesh
            if geometry.get('units_per_m',100)!=100:raise ValueError('Wrong native RE5 units')
            _load_mesh(geometry,row['stage'])
        for rows,event in ((samples,False),(events,True)):
            for seq,item in enumerate(rows):
                if not isinstance(item,dict) or item.get('seq')!=seq or type(item.get('at')) not in (int,float) \
                        or not row['started']<=item['at']<=row['ended'] or not isinstance(item.get('payload'),dict) \
                        or event and (not isinstance(item.get('kind'),str) or len(item['kind'])>64):
                    raise ValueError('Measured row sequence/time/payload does not verify')
        for item in samples:
            payload=item['payload'];frame=payload.get('frame')
            if set(payload)&{'seq','at'} or not isinstance(frame,dict) or frame.get('title')!=title:
                raise ValueError('Samples require their exact native title and unshadowed envelope')
            if title=='G4BE08' and frame.get('units_per_m')!=1000 \
                    or title=='BLUS30491' and frame.get('units','cm')!='cm':
                raise ValueError('Sample native units do not match the measured title')
        note=bundle.get('notebook')
        if not isinstance(note,dict) or note.get('id')!=base or note.get('stage')!=row['stage'] \
                or note.get('mode')!=meta.get('mode') or note.get('outcome')!=row['outcome'] \
                or not isinstance(note.get('character'),str) or not isinstance(note.get('observed'),dict) \
                or type(note.get('ts')) not in (int,float) or not math.isfinite(note['ts']) or note['ts']<0:
            raise ValueError('Notebook must match the exact round, geometry, mode and outcome')
        if note is not None:
            observed=note['observed']
            if observed.get('source_session_id') not in (None,sid):
                raise ValueError('Notebook explicitly names a different source session')
            numeric=('kills','score','bonuses_taken','accuracy','stuck','nav_route_arrivals',
                     'motion_idle_spin_s','nav_oscillations')
            if any(observed.get(key) is not None and type(observed[key]) not in (int,float) for key in numeric) \
                    or observed.get('assistance') is not None and not isinstance(observed['assistance'],dict):
                raise ValueError('Notebook measured feature types do not verify')
        from .atlas import NavigationAtlas,render_map,_safe
        from .notebook import Notebook
        provenance={'authority':owner['authority'],'source_session_id':sid,'sha256':digest,
                    'evidence':'authenticated worker-reported native evidence; not an independent central RAM read'}
        metadata=meta|{'evidence_import':provenance}
        plain_samples=[{**item['payload'],'at':item['at']} for item in samples]
        plain_events=[{**item['payload'],'at':item['at'],'kind':item['kind']} for item in events]
        landmarks=[]
        for event in plain_events:
            if event['kind']=='checkpoint_acquired' and isinstance(event.get('key'),str) \
                    and isinstance(event.get('pos'),list) and len(event['pos'])==3 \
                    and all(type(v) in (int,float) for v in event['pos']):
                landmarks.append({'key':event['key'],'kind':event['key'].split(':')[0],
                                  'pos':event['pos'],'acquired':1})
        artifact={'version':1,'round_id':rid,'title':title,'stage':row['stage'],'outcome':row['outcome'],
            'review':row.get('review') or {},'geometry':geometry,'metadata':metadata,
            'landmarks':landmarks,'samples':plain_samples,'events':plain_events}
        # Validate rendering before either database receives this round.
        svg=render_map(geometry,plain_samples,plain_events,landmarks).encode()
        dest=self.root/'navigation'/title/'rounds'/_safe(rid)
        with _IMPORT_LOCK:
            notebook=self.notebooks.get(title)
            if notebook is None:
                notebook=Notebook(self.root,title);self.notebooks[title]=notebook
            if notebook is not None:
                with notebook.connect() as db:
                    old=db.execute('SELECT data FROM rounds WHERE id=?',(base,)).fetchone()
                    if old and json.loads(old[0]).get('source_evidence_sha256')!=digest:
                        raise ValueError('A different immutable Notebook round already has this identity')
            atlas=NavigationAtlas(self.root/'navigation',title)
            try:
                old=atlas.db.execute('SELECT metadata FROM rounds WHERE id=?',(rid,)).fetchone()
                if old and (json.loads(old[0]).get('evidence_import') or {}).get('sha256')!=digest:
                    raise ValueError('A different immutable round already has this identity')
                existing=atlas.db.execute('SELECT geometry FROM stages WHERE key=?',(row['stage'],)).fetchone()
                if existing and json.loads(existing[0])!=geometry:raise ValueError('Stage geometry identity changed')
                with atlas.db:
                    atlas.db.execute('INSERT OR IGNORE INTO stages(key,title,geometry,metadata) VALUES(?,?,?,?)',
                        (row['stage'],title,json.dumps(geometry),json.dumps(stage.get('metadata') or {})))
                    atlas.db.execute('INSERT OR IGNORE INTO rounds VALUES(?,?,?,?,?,?,?,?,?)',
                        (rid,row['stage'],row['started'],row['ended'],row['outcome'],json.dumps(metadata),
                         json.dumps(row.get('review') or {}),str(dest/'round.json'),str(dest/'map.svg')))
                    atlas.db.executemany('INSERT OR IGNORE INTO samples VALUES(?,?,?,?)',
                        [(rid,item['seq'],item['at'],json.dumps(item['payload'])) for item in samples])
                    atlas.db.executemany('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?)',
                        [(rid,item['seq'],item['at'],item['kind'],json.dumps(item['payload'])) for item in events])
                    atlas.db.execute('UPDATE stages SET rounds=(SELECT count(*) FROM rounds WHERE stage=?) WHERE key=?',
                                     (row['stage'],row['stage']))
                atomic(dest/'round.json',canon(artifact))
                atomic(dest/'map.svg',svg)
            finally:atlas.close()
            if note is not None:
                observed={key:value for key,value in note['observed'].items()
                          if not key.startswith(('round_semantic_','re4_shared_'))
                          and key not in ('semantic_recall','knowledge_delivered')}
                observed=observed|{'source_authority':owner['authority'],'source_session_id':sid,
                                            'source_evidence_sha256':digest,'source_note_ts':note['ts']}
                notebook.finish(note['stage'],note['mode'],note['character'],note['outcome'],observed,round_id=base)
            ack={'imported':True,'sha256':digest,'round_id':rid,'title':title,'notebook_imported':note is not None,
                 'knowledge_delivered':False}
            self.store.put('mercs_evidence',digest,{'authority':owner['authority'],'title':title,'round_id':rid,
                'source_session_id':sid,'received_at':time.time(),'ack':ack})
            if notebook is not None:
                notebook.publish(self.config.public_url or 'http://127.0.0.1:'+str(self.config.api_port),self.config.token())
            return ack


class Service:
    def __init__(self,bridge):
        self.bridge=bridge;self.root=Path(bridge.cfg.data_dir)/'mercs'/'evidence-outbox'/bridge.authority
        self.state={'running':True,'pending':0,'delivered':0,'origin_missing':0,'last_error':None}
        self.thread=threading.Thread(target=self.run,name='mercs-completed-evidence',daemon=True)
        self.counts()

    def counts(self):
        records=[json.loads(path.read_text()) for path in self.root.glob('*.json') if path.name not in STATE_FILES]
        self.state.update(pending=sum(not r.get('delivered') for r in records),
                          delivered=sum(bool(r.get('delivered')) for r in records))

    def blocked(self,identity,reason):
        path=self.root/'blocked.json';blocked=json.loads(path.read_text()) if path.is_file() else {}
        blocked[identity]={'reason':str(reason)[:200],'at':time.time()}
        blocked=dict(sorted(blocked.items(),key=lambda item:item[1]['at'])[-200:])
        atomic(path,canon(blocked));self.state['origin_missing']=len(blocked)

    def scan(self):
        root=Path(self.bridge.cfg.data_dir).resolve()/'mercs'
        index_path=self.root/'index.json'
        index=json.loads(index_path.read_text()) if index_path.is_file() else {}
        scan_path=self.root/'scan.json'
        cursors=json.loads(scan_path.read_text()) if scan_path.is_file() else {}
        for title in TITLES:
            path=root/'navigation'/title/'atlas.sqlite'
            offset=cursors.get(title,0)
            if type(offset) is not int or offset<0:offset=0
            rows=read_rows(path,'SELECT id,metadata FROM rounds WHERE ended IS NOT NULL AND outcome IS NOT NULL '
                                'ORDER BY ended DESC,id DESC LIMIT 100 OFFSET ?',(offset,))
            for n,row in enumerate(rows):
                identity=title+':'+row['id']
                if identity in index:continue
                try:
                    metadata=json.loads(row['metadata']);sid=metadata.get('source_session_id')
                    session=self.bridge.store.get('session',sid) if isinstance(sid,str) else None
                    if session is None:raise ValueError('Exact persisted recorder/session origin is missing')
                    bundle,raw=export_round(self.bridge.cfg.data_dir,title,row['id'],session)
                    compressed=gzip.compress(raw,mtime=0)
                    if len(compressed)>MAX_COMPRESSED:raise ValueError('Compressed measured round exceeds 4 MiB bound')
                except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:
                    self.blocked(identity,exc);continue
                digest=sha256(raw)
                chunks=[compressed[i:i+CHUNK] for i in range(0,len(compressed),CHUNK)]
                manifest={'sha256':digest,'title':title,'source':bundle['source'],'bytes':len(raw),
                          'chunks':[{'sha256':sha256(chunk),'size':len(chunk)} for chunk in chunks]}
                atomic(self.root/(digest+'.gz'),compressed)
                atomic(self.root/(digest+'.json'),canon({'manifest':manifest,'delivered':False}))
                index[identity]=digest;atomic(index_path,canon(index))
                cursors[title]=offset+n+1;atomic(scan_path,canon(cursors));self.counts()
                return True
            cursors[title]=offset+len(rows) if len(rows)==100 else 0
        atomic(scan_path,canon(cursors))
        return False

    def flush_one(self,client):
        import httpx
        for path in sorted(self.root.glob('*.json')):
            if path.name in STATE_FILES:continue
            record=json.loads(path.read_text());manifest=record['manifest']
            if record.get('delivered') or record.get('retry_after',0)>time.time():continue
            compressed=path.with_suffix('.gz').read_bytes()
            try:
                for i,chunk in enumerate(manifest['chunks']):
                    part=compressed[i*CHUNK:(i+1)*CHUNK]
                    response=client.put('/api/federation/'+self.bridge.authority+'/evidence/chunks/'+chunk['sha256'],
                                        content=part,headers={'content-type':'application/octet-stream'})
                    response.raise_for_status()
                response=client.post('/api/federation/'+self.bridge.authority+'/evidence/import',json=manifest)
                response.raise_for_status();ack=response.json()
            except httpx.HTTPStatusError as exc:
                if not 400<=exc.response.status_code<500:raise
                # A rejected package remains pending, but must not prevent the
                # next valid completed round from reaching the reviewer.
                atomic(path,canon(record|{'retry_after':time.time()+60,
                                          'last_http_status':exc.response.status_code}))
                continue
            if ack.get('imported') is not True or ack.get('sha256')!=manifest['sha256']:
                raise ValueError('Central did not acknowledge this exact measured-round content')
            atomic(path,canon(record|{'delivered':True,'ack':ack,'delivered_at':time.time()}))
            done=[]
            for other in self.root.glob('*.json'):
                if other.name not in STATE_FILES:
                    item=json.loads(other.read_text())
                    if item.get('delivered'):done.append((item.get('delivered_at',0),other))
            for _,old in sorted(done)[:-100]:
                old.with_suffix('.gz').unlink(missing_ok=True);old.unlink(missing_ok=True)
            self.counts()
            return True
        return False

    def run(self):
        import httpx
        while not self.bridge.stop.is_set():
            try:
                if not self.bridge.active_worker_id:self.bridge.stop.wait(2);continue
                self.scan()
                with httpx.Client(base_url=self.bridge.remote,headers=self.bridge._headers(),timeout=10) as client:
                    self.flush_one(client)
                self.state['last_error']=None
            except Exception as exc:self.state['last_error']=type(exc).__name__+': '+str(exc)[:160]
            self.bridge.stop.wait(5)
        self.state['running']=False


def start(bridge):
    service=getattr(bridge,'_completed_evidence_sync',None)
    if service is None:
        service=Service(bridge);bridge._completed_evidence_sync=service;service.thread.start()
    return service.state


def routes(app,store,config,auth,federation):
    receiver=Receiver(store,config,federation);app.state.mercs_evidence_sync=receiver
    def owner(authority,request):
        return federation.owner(authority,request.headers.get('x-gbox-federation-key',''))
    def error(exc):
        if isinstance(exc,PermissionError):return HTTPException(403,str(exc))
        if isinstance(exc,FileNotFoundError):return HTTPException(409,'An evidence chunk is missing; retry its upload')
        return HTTPException(422,str(exc)[:300])

    @app.put('/api/federation/{authority}/evidence/chunks/{digest}')
    async def chunk(authority:str,digest:str,request:Request,actor=Depends(auth)):
        try:
            scoped=owner(authority,request);data=bytearray()
            async for part in request.stream():
                data.extend(part)
                if len(data)>CHUNK:raise ValueError('Chunk exceeds 512 KiB')
            return await run_in_threadpool(receiver.put_chunk,scoped,digest,bytes(data))
        except (ValueError,PermissionError,OSError) as exc:raise error(exc) from None

    @app.post('/api/federation/{authority}/evidence/import')
    def imported(authority:str,body:dict,request:Request,actor=Depends(auth)):
        try:return receiver.import_manifest(owner(authority,request),body)
        except (ValueError,KeyError,IndexError,TypeError,PermissionError,OSError,zlib.error,sqlite3.Error) as exc:raise error(exc) from None
