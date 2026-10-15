"""Durable gameplay observations on Spark; native replay is separate from semantic memory."""
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import struct
import threading
import time
import os
import tempfile
import shutil

DIM = 128
EVENTS = {'pad', 'sampled_pad', 'mod_action', 'checkpoint', 'note', 'native_replay', 'gap', 'frame'}


def vector(text):
    """Dependency-free signed feature hashing, not a neural/LLM embedding."""
    v = [0.] * DIM
    for word in re.findall(r'[\w]+', text.lower())[:2048]:
        h = hashlib.blake2b(word.encode(), digest_size=4).digest()
        v[int.from_bytes(h[:2], 'little') % DIM] += 1 if h[2] & 1 else -1
    norm = math.sqrt(sum(x*x for x in v)) or 1
    return struct.pack('<128f', *(x/norm for x in v))


class Archive:
    def __init__(self, root, max_mb=4096):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'gameplay-memory.sqlite3'
        self.max_bytes = max_mb * 2**20
        self.lock = threading.RLock()
        self.error = None
        with self.connect() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, meta TEXT NOT NULL, started REAL, updated REAL);
              CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, run TEXT, kind TEXT, at REAL, payload BLOB, token TEXT UNIQUE);
              CREATE INDEX IF NOT EXISTS run_events ON events(run,id);
              CREATE TABLE IF NOT EXISTS segments(run TEXT, bucket INTEGER, summary TEXT, embedding BLOB, events INTEGER,
                PRIMARY KEY(run,bucket));
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.execute('PRAGMA synchronous=NORMAL')
        return db

    def record(self, session, kind, payload, *, token=None, at=None):
        if kind not in EVENTS: raise ValueError('Unknown gameplay event kind')
        if not isinstance(payload,dict):raise ValueError('Gameplay payload must be an object')
        sid = str(session.get('session_id') or '')
        if not re.fullmatch(r'[\w-]{1,120}', sid): raise ValueError('Invalid session id')
        raw = json.dumps(payload, ensure_ascii=True, allow_nan=False)
        if len(raw) > 16384: raise ValueError('Gameplay event exceeds 16 KiB')
        at = time.time() if at is None else float(at)
        if not math.isfinite(at) or at < 0: raise ValueError('Invalid event timestamp')
        meta = {k:session.get(k) for k in ('session_id','game_id','title','mod','adapter','started')}
        meta['capture'] = 'observations; native replay availability is recorded separately'
        with self.lock, self.connect() as db:
            if db.execute('PRAGMA page_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0] > self.max_bytes:
                self.error = 'Gameplay memory budget reached; old runs retained, new observations paused'
                raise ValueError(self.error)
            db.execute('INSERT INTO runs VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated',
                       (sid, json.dumps(meta), session.get('started') or at, at))
            cur = db.execute('INSERT OR IGNORE INTO events(run,kind,at,payload,token) VALUES(?,?,?,?,?)',
                             (sid, kind, at, gzip.compress(raw.encode(), mtime=0), token))
            if not cur.rowcount: return False
            bucket = int(at // 60)
            old = db.execute('SELECT summary,events,embedding FROM segments WHERE run=? AND bucket=?',(sid,bucket)).fetchone()
            label = f"{meta.get('title') or meta.get('game_id')} {kind} "
            if kind in ('note','mod_action','native_replay','checkpoint'): label += raw[:1200]
            elif kind in ('pad','sampled_pad'):
                entries=payload.get('events')
                label += 'controller input ' + ' '.join(str(e.get('key','')) for e in (entries[:40] if isinstance(entries,list) else []) if isinstance(e,dict))
            # Repeated controller samples do not evict the useful annotations or
            # re-embed six KiB thirty times a second.
            quiet = kind in ('pad','sampled_pad') and old is not None
            summary = old[0] if quiet else ((old[0] + '\n') if old else '') + label
            summary = summary[-6000:]
            db.execute('INSERT OR REPLACE INTO segments VALUES(?,?,?,?,?)',
                       (sid,bucket,summary,old[2] if quiet else vector(summary),(old[1] if old else 0)+1))
        self.error = None
        return True

    def runs(self, game_id='', limit=50):
        with self.connect() as db:
            rows = db.execute("SELECT id,meta,updated FROM runs WHERE (?='' OR json_extract(meta,'$.game_id')=?) ORDER BY updated DESC LIMIT ?", (game_id,game_id,min(limit,200))).fetchall()
            result = []
            for sid,meta,updated in rows:
                m=json.loads(meta)
                if game_id and m.get('game_id') != game_id: continue
                counts=dict(db.execute('SELECT kind,count(*) FROM events WHERE run=? GROUP BY kind',(sid,)))
                result.append(m | {'id':sid,'updated':updated,'events':counts,
                    'replay_status':'native file recorded; validation required' if counts.get('native_replay') else 'observations only; not a TAS'})
            return result

    def events(self, sid, after=0, limit=100):
        with self.connect() as db:
            return [{'id':i,'kind':k,'at':t,'payload':json.loads(gzip.decompress(p))} for i,k,t,p in
                    db.execute('SELECT id,kind,at,payload FROM events WHERE run=? AND id>? ORDER BY id LIMIT ?',
                               (sid,max(0,after),min(max(1,limit),500)))]

    def search(self, text, limit=20, game_id=''):
        q=struct.unpack('<128f',vector(text))
        with self.connect() as db:
            # Bounded recent candidate window keeps search memory predictable.
            rows=db.execute("SELECT run,bucket,summary,embedding,events FROM segments JOIN runs ON runs.id=segments.run WHERE (?='' OR json_extract(meta,'$.game_id')=?) ORDER BY bucket DESC LIMIT 5000",(game_id,game_id)).fetchall()
        ranked=[{'run_id':r,'minute':b,'summary':s,'events':n,'score':sum(x*y for x,y in zip(q,struct.unpack('<128f',v)))} for r,b,s,v,n in rows]
        return sorted(ranked,key=lambda r:r['score'],reverse=True)[:min(max(1,limit),100)]

    def status(self):
        with self.connect() as db:
            counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('runs','events','segments')}
        return counts | {'file':str(self.path),'vector_kind':'signed feature hashing, 128 dimensions; not neural embeddings',
                         'max_mb':self.max_bytes//2**20,'error':self.error,'exact_replay':False}


def install(app, store, config, auth):
    from fastapi import Depends, HTTPException, Request
    from pydantic import BaseModel, Field
    archive=Archive(config.data_dir/'gameplay-memory')
    app.state.gameplay_memory=archive
    def capture(sid,kind,payload,token=None):
        if not getattr(config,'gameplay_memory_enabled',True):return False
        session=store.get('session',sid)
        if not session:return False
        from .background_testing import agent_owned
        if agent_owned(store.get('slabel',sid),store.get('job',sid.split('-',1)[-1])):return False
        try:
            archive.record(session,kind,payload,token=token)
            return True  # Includes a previously accepted idempotency token.
        except (ValueError,OSError,sqlite3.Error) as e:archive.error=str(e)[:200]
        return False
    app.state.capture_gameplay=capture

    @app.get('/api/gameplay-memory')
    def status(game_id:str='',q:str='',actor=Depends(auth)):
        return archive.status() | {'enabled':getattr(config,'gameplay_memory_enabled',True),
            'runs':archive.runs(game_id),'matches':archive.search(q[:2000],game_id=game_id) if q else [],
            'demonstrations':{'scope':'separate test sessions on available idle PCs',
                'state':'waiting_for_validated_native_run',
                'reason':'Observations cannot recreate unrecorded input. Native files require core/content/checkpoint and replay validation before unattended use; PSO replay is not yet verified.'}}

    @app.post('/api/gameplay-memory/runs/{sid}/native')
    async def native(sid:str,request:Request,actor=Depends(auth)):
        """Stream native files to Spark without buffering a half-GiB movie in RAM."""
        session=store.get('session',sid)
        if not session:raise HTTPException(404,'Session not found')
        folder=archive.root/'native';folder.mkdir(exist_ok=True)
        if shutil.disk_usage(folder).free<4*2**30:raise HTTPException(507,'Less than 4 GiB free on the native archive drive')
        # Bound central retention separately from the small indexed observation DB.
        if sum(p.stat().st_size for p in folder.glob('*.bsv')) >= 64*2**30:
            raise HTTPException(507,'64 GiB native archive budget reached; worker retains its recording')
        fd,tmp=tempfile.mkstemp(dir=folder,prefix='upload-')
        h=hashlib.sha256();size=0
        try:
            with os.fdopen(fd,'wb') as f:
                async for block in request.stream():
                    size+=len(block)
                    if size>512*2**20:raise HTTPException(413,'Native recording exceeds 512 MiB')
                    h.update(block);f.write(block)
            if size<24:raise HTTPException(422,'Native recording is too small')
            digest=h.hexdigest();dest=folder/(digest+'.bsv')
            if not dest.exists():os.replace(tmp,dest)
            # Native recordings stay in their bounded archive, not the general
            # artifact store (whose readers materialize the whole file).
            return {'sha256':digest,'size':size,'url':f'/api/gameplay-memory/native/{digest}'}
        finally:
            Path(tmp).unlink(missing_ok=True)

    @app.get('/api/gameplay-memory/native/{digest}')
    def native_file(digest:str,actor=Depends(auth)):
        from fastapi.responses import FileResponse
        if not re.fullmatch('[a-f0-9]{64}',digest):raise HTTPException(404,'Native file not found')
        path=archive.root/'native'/(digest+'.bsv')
        if not path.is_file():raise HTTPException(404,'Native file not found')
        return FileResponse(path,media_type='application/octet-stream',filename=digest+'.bsv')

    @app.get('/api/gameplay-memory/runs/{sid}')
    def events(sid:str,after:int=0,actor=Depends(auth)):
        return {'session_id':sid,'events':archive.events(sid,after)}

    class Note(BaseModel):
        text:str=Field(min_length=1,max_length=2000)
    @app.post('/api/gameplay-memory/runs/{sid}/note')
    def note(sid:str,body:Note,actor=Depends(auth)):
        s=store.get('session',sid)
        if not s:raise HTTPException(404,'Session not found')
        archive.record(s,'note',{'text':body.text,'source':'operator annotation; not an inferred level completion'})
        return {'saved':True}

    class Observation(BaseModel):
        kind:str
        payload:dict
        token:str=Field(min_length=1,max_length=200)
    @app.post('/api/gameplay-memory/runs/{sid}/observe')
    def observe(sid:str,body:Observation,actor=Depends(auth)):
        if body.kind not in EVENTS:raise HTTPException(422,'Unsupported event kind')
        try:saved=capture(sid,body.kind,body.payload,body.token)
        except ValueError as e:raise HTTPException(422,str(e)) from e
        return {'saved':saved,'error':archive.error if not saved else None}


from pydantic import BaseModel, Field
from .registry import tool


class MemoryIn(BaseModel):
    op: str = 'status'
    game_id: str = ''
    session_id: str = ''
    query: str = Field(default='',max_length=2000)
    after: int = Field(default=0,ge=0)


class MemoryOut(BaseModel):
    result: dict


@tool('gameplay_memory','1.0',MemoryIn,MemoryOut,timeout_s=30)
def memory(inp,ctx):
    """Read the Spark's bounded searchable gameplay archive. status/search returns recent runs and matched minute
    segments; events pages the actual inputs/mod receipts/notes. Observations are not a TAS, native files are not
    verified replays, and annotations are not level-completion proof. Never inject this history into a human game."""
    import httpx
    from urllib.parse import quote
    if not ctx.server:raise ValueError('Control plane required')
    path='/api/gameplay-memory'
    params={'game_id':inp.game_id,'q':inp.query}
    if inp.op=='events':
        if not inp.session_id:raise ValueError('Choose a recorded session_id')
        path+='/runs/'+quote(inp.session_id,safe='');params={'after':inp.after}
    elif inp.op not in ('status','search'):raise ValueError('Use status, search or events')
    r=httpx.get(ctx.server+path,params=params,headers=ctx.headers,timeout=20)
    r.raise_for_status();return {'result':r.json()}
