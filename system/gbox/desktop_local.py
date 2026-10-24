"""This PC's loopback authority. No remote calls, emulator adoption or launch replay.

Use the installed config/data/cache/runtime and existing local token. A worker
waits when an older worker still owns a native game; it never kills that game.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import threading
import time

from fastapi import Request

from .config import Config, HOST_OS, load

DEFAULT_PORT = 18765


def network_path(value):
    return str(value).replace('\\', '/').startswith('//')


def local_config(source, port=DEFAULT_PORT):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Expected a loopback port from 1024 through 65535')
    cfg = load(source)
    if network_path(cfg.data_dir) or network_path(cfg.runtime) or network_path(cfg.cache):
        raise ValueError('Local gBox requires its data, runtime and cache on this PC; configured network paths were preserved')
    return cfg.model_copy(deep=True, update={'api_host':'127.0.0.1', 'api_port':port,
                                           'public_url':f'http://127.0.0.1:{port}'})


def installation_key(config_path, cfg):
    return hashlib.sha256((str(Path(config_path).resolve())+'\n'+str(cfg.data_dir.resolve())).encode()).hexdigest()


def local_entry(row, cfg):
    """Keep source identity only when its actual local file/cache copy exists.

    Do not stat a UNC source just to find out that a sleeping server is absent.
    No source file, original entry, executable setting or game ID is changed.
    """
    from .models import CatalogEntry
    try:
        entry = CatalogEntry.model_validate(row).model_dump()
        gid = entry['game_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', gid):
            return None
        candidates=[]
        if entry.get('library') and entry.get('rel_path'):
            try:
                root=cfg.library(entry['library']).root()
                if root and not network_path(root):
                    rel=Path(entry['rel_path'])
                    if not rel.is_absolute() and '..' not in rel.parts:
                        candidates.append(root/rel)
            except KeyError:
                pass
        launch=entry.get('launch') or {}
        if launch.get('path'):candidates.append(Path(launch['path']))
        candidates.extend(Path(p) for p in entry.get('source_paths') or ())
        names={str(p).replace('\\','/').rsplit('/',1)[-1] for p in candidates}
        candidates.extend(cfg.cache/gid/name for name in sorted(names) if name and name not in ('.','..'))
        for candidate in candidates:
            if network_path(candidate) or not candidate.is_absolute():continue
            if launch.get('kind')=='steam' and candidate.is_dir():
                appid=str(launch.get('appid',''))
                if not re.fullmatch(r'[0-9]{1,12}',appid) or candidate.parent.name.lower()!='common' \
                        or candidate.parent.parent.name.lower()!='steamapps':continue
                manifest=candidate.parent.parent/('appmanifest_'+appid+'.acf')
                from .catalog import parse_vdf
                if not manifest.is_file() or manifest.stat().st_size>1024*1024:continue
                state=parse_vdf(manifest.read_text(errors='replace')).get('AppState') or {}
                if str(state.get('appid'))!=appid or state.get('installdir')!=candidate.name \
                        or str(state.get('StateFlags'))!='4':continue
                entry.update(library=None,rel_path=None,source_paths=[str(candidate)],launch=dict(launch))
                entry['local_availability']={'verified':True,'source':'installed_steam_manifest','observed_at':time.time()}
                return entry
            if not candidate.is_file():continue
            if candidate.name.endswith(('.part','.tmp')):continue
            if entry.get('size') and candidate.stat().st_size != entry['size']:continue
            entry.update(library=None,rel_path=None,source_paths=[str(candidate)],
                         launch={**launch,'path':str(candidate)})
            entry['local_availability']={'verified':True,'source':'existing_local_file',
                                         'observed_at':time.time()}
            return entry
    except (ValueError,TypeError,OSError,KeyError):
        pass
    return None


def seed_catalog(cfg, store, rows):
    accepted=[item for row in rows if isinstance(row,dict) and (item:=local_entry(row,cfg)) is not None]
    if accepted:store.upsert_catalog(accepted)
    return len(accepted)


def legacy_worker_owner(cfg):
    """A pre-bridge worker keeps its adapters; never race or adopt that process."""
    if HOST_OS!='windows':return None
    import psutil
    expected = os.path.normcase(str(Path(cfg.config_path).resolve())) if getattr(cfg,'config_path',None) else None
    for process in psutil.process_iter(['pid','cmdline']):
        try:
            args=process.info.get('cmdline') or []
            if process.pid==os.getpid() or '-m' not in args:continue
            module=args.index('-m')+1
            if module>=len(args) or args[module]!='gbox' or 'worker' not in args[module+1:]:continue
            if '--config' not in args:continue
            index=args.index('--config')+1
            if index>=len(args):continue
            candidate=Path(args[index])
            if not candidate.is_absolute() or network_path(candidate):continue
            # cfg.config_path is not provided by older Config objects. Compare
            # the declared config's runtime instead, never just a process name.
            if expected:
                same=os.path.normcase(str(candidate.resolve()))==expected
            else:
                try:same=load(candidate).runtime.resolve()==cfg.runtime.resolve()
                except (OSError,ValueError):same=False
            if same:return process.pid
        except (psutil.Error,OSError,ValueError,IndexError):continue
    return None


class LocalWorker:
    def __init__(self, cfg, name=None):
        self.cfg,self.name=cfg,name
        self.stop=threading.Event();self.thread=None;self.lock=threading.Lock()
        self.state={'running':False,'state':'stopped','reason':''}
        self.on_stopped=lambda:None

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():return dict(self.state)
            self.stop.clear();self.state={'running':False,'state':'starting','reason':''}
            self.thread=threading.Thread(target=self._run,daemon=True,name='desktop-local-worker')
            self.thread.start()
            return dict(self.state)

    def _run(self):
        from . import worker
        from .worker_results import ResultOutbox
        from .tools import _running_file
        while not self.stop.is_set():
            # Reuse the established ownership witness instead of bypassing
            # worker.run's native-session protection or adopting stale PIDs.
            try:
                previous=legacy_worker_owner(self.cfg)
                if previous:
                    self.state={'running':False,'state':'waiting_worker_owner',
                        'reason':'An older worker still owns this runtime; it was preserved and no duplicate dispatcher started.'}
                    self.stop.wait(3.);continue
                held=ResultOutbox(self.cfg.runtime,self.cfg.public_url,self.name or __import__('platform').node()) \
                    .protected_sessions(_running_file(self.cfg))
                if held:
                    self.state={'running':False,'state':'waiting_native_owner',
                        'reason':'Another worker still owns a live game; it was preserved and no second game worker started.'}
                    self.stop.wait(3.);continue
                self.state={'running':True,'state':'running','reason':''}
                worker.run(self.cfg.public_url,self.cfg.token(),self.cfg,self.name,stop=self.stop)
                if not self.stop.is_set():raise RuntimeError('Local worker exited before stop was requested')
            except Exception as exc:
                self.state={'running':False,'state':'retrying','reason':type(exc).__name__+': '+str(exc)[:240]}
                self.stop.wait(5.)
        self.state={'running':False,'state':'stopped','reason':''}
        self.on_stopped()


def create_app(cfg, key, *, worker_name=None, start_worker=True):
    from fastapi import Depends, HTTPException
    from .server import create_app as server_app
    app=server_app(cfg);worker=LocalWorker(cfg,worker_name);app.state.desktop_worker=worker
    catalog_file=cfg.data_dir/'desktop-local-catalog.json'
    token=cfg.token()
    def auth(request:Request):
        got=request.headers.get('authorization','').removeprefix('Bearer ')
        if not hmac.compare_digest(got.encode(),token.encode()):raise HTTPException(401,'bad token')

    @app.get('/api/desktop-local')
    def status():
        return {'ok':True,'kind':'gbox.desktop-local/1','installation':key,
                'worker':dict(worker.state),'authority':cfg.public_url}

    @app.post('/api/desktop-local/worker')
    def start(_actor=Depends(auth)):
        return worker.start()

    @app.post('/api/desktop-local/catalog')
    async def import_catalog(request:Request,_actor=Depends(auth)):
        body=await request.json();rows=body.get('items') if isinstance(body,dict) else None
        if not isinstance(rows,list) or len(rows)>500:raise HTTPException(400,'Expected at most 500 catalog records')
        accepted=seed_catalog(cfg,app.state.store,rows)
        # A local catalog is durable. This route imports verified local files
        # only; it never copies remote jobs, sessions, credentials or actions.
        return {'accepted':accepted,'offered':len(rows),'launches_replayed':0}

    def index():
        try:
            if catalog_file.is_file() and catalog_file.stat().st_size<=32*1024*1024:
                rows=json.loads(catalog_file.read_text(encoding='utf-8'))
                if isinstance(rows,list):seed_catalog(cfg,app.state.store,rows)
            from . import catalog
            entries=[]
            for lib in cfg.libraries:
                root=lib.root()
                if not root or network_path(root):continue
                if lib.kind=='attract':rows,_,_=catalog.scan_attract(root,lib.id,{})
                else:rows,_=catalog.scan([root],{},lib_id=lib.id,do_hash=False,platform_hint=lib.platform,
                    recursive=lib.recursive,exclude_dirs=lib.exclude_dirs,exclude_files=lib.exclude_files)
                entries.extend(e.model_dump() for e in rows)
            if entries:app.state.store.upsert_catalog(entries)
        except Exception as exc:
            print('Local catalog indexing: '+type(exc).__name__,flush=True)

    @app.on_event('startup')
    def ready():
        threading.Thread(target=index,daemon=True,name='desktop-local-index').start()
        if start_worker:worker.start()

    @app.on_event('shutdown')
    def stop():worker.stop.set()
    from .desktop_bridge import install as install_bridge
    install_bridge(app,cfg,key,worker,auth)
    return app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--port',type=int,default=DEFAULT_PORT)
    parser.add_argument('--name');parser.add_argument('--no-worker',action='store_true')
    args=parser.parse_args()
    # A remote worker's inherited pairing token must not become this authority's
    # credential. Config.token keeps the existing local file or creates it once.
    os.environ.pop('GBOX_TOKEN',None)
    cfg=local_config(args.config,args.port);key=installation_key(args.config,cfg)
    print(json.dumps({'event':'desktop-local-config','installation':key,'authority':cfg.public_url,
                      'token_file':str(cfg.data_dir/'api_token')}),flush=True)
    app=create_app(cfg,key,worker_name=args.name,start_worker=not args.no_worker)
    import uvicorn
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=cfg.api_port,log_level='warning',
                                       timeout_graceful_shutdown=3))
    app.state.desktop_worker.on_stopped=lambda:setattr(server,'should_exit',True)
    server.run()


if __name__=='__main__':main()
