"""Opt-in real HTTP media/input/RPC plumbing with explicitly synthetic actors."""
import concurrent.futures
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from gbox.config import Config
from gbox.desktop_bridge import DesktopBridge,Submissions
from gbox.store import Store


@unittest.skipUnless(os.environ.get('GBOX_TEST_DESKTOP_HTTP')=='1','opt-in isolated HTTP transport acceptance')
class DesktopTransportTests(unittest.TestCase):
    def test_continuous_jpeg_upload_and_actual_scoped_rpc_input(self):
        import uvicorn
        from fastapi import FastAPI
        from fastapi.responses import StreamingResponse
        from PIL import Image
        from gbox.server import create_app
        from gbox.tools import SESSIONS
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root=Path(temporary);servers=[];threads=[]
            def reserve():
                with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
            central_port,local_port=reserve(),reserve()
            central_url='http://127.0.0.1:'+str(central_port);local_url='http://127.0.0.1:'+str(local_port)
            cfg=Config(data_dir=root/'central',public_url=central_url,audio_cpp={'enabled':False},
                       hermes={'local':{'enabled':False},'grunt':{'enabled':False}})
            central=create_app(cfg)
            local_cfg=Config(data_dir=root/'local',public_url=local_url)
            local=FastAPI();local.state.store=Store(local_cfg.data_dir)
            sid='a'*16+'-'+'b'*16;authority='c'*64;secret='d'*64
            sent=[];calls={'media':0,'rpc':0}
            adapter=SimpleNamespace(name='fixture_only_no_emulator',send_input=lambda rows:sent.extend(rows))
            image=io.BytesIO();Image.new('RGB',(16,16),(20,120,180)).save(image,format='JPEG');jpeg=image.getvalue()

            @local.post('/api/jobs')
            def unused_job(body:dict):raise AssertionError('No test transport may execute a tool')
            @local.post('/api/autoplay-screensaver/round-boundary')
            def unused_boundary(body:dict):return {'saved':False}
            @local.post('/api/sessions/{session}/input')
            def inputs(session:str,body:dict):
                self.assertEqual(session,sid);adapter.send_input(body['events']);return {'queued':len(body['events'])}
            @local.post('/api/sessions/{session}/rpc')
            def rpc(session:str,body:dict):
                self.assertEqual(session,sid);self.assertEqual(body['op'],'info');calls['rpc']+=1
                return {'fixture_only':True,'echo':body['args'].get('test')}
            @local.get('/api/workers/{wid}/desktop/stream')
            def stream(wid:str,view:str,session:str):
                self.assertEqual(wid,'a'*16);self.assertEqual(view,'game');self.assertEqual(session,sid);calls['media']+=1
                def parts():
                    for _ in range(4):
                        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+jpeg+b'\r\n';time.sleep(.05)
                return StreamingResponse(parts(),media_type='multipart/x-mixed-replace; boundary=frame')
            def serve(app,port):
                server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',timeout_graceful_shutdown=1))
                thread=threading.Thread(target=server.run,daemon=True);servers.append(server);threads.append(thread);thread.start()
                deadline=time.monotonic()+15
                while not server.started and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(server.started)
            bridge=DesktopBridge(local,local_cfg,authority,SimpleNamespace(name='fixture',state={'running':True,'state':'running'}))
            bridge.remote=central_url;bridge.token=cfg.token();bridge.secret=secret;bridge.active_worker_id='a'*16
            bridge.submissions=Submissions(local.state.store,lambda *a:None,authority,central_url)
            bridge.watched={sid}
            fixture={'session_id':sid,'game_id':'explicit_transport_fixture','adapter':'fixture_only_no_emulator',
                     'state':'running','started':time.time(),'detail':{'fixture_only':True}}
            local.state.store.put('session',sid,fixture)
            try:
                serve(central,central_port);serve(local,local_port)
                with httpx.Client(base_url=central_url,headers=bridge._headers(),timeout=12) as client:
                    bridge._central(client,'POST','/snapshot',json={'epoch':bridge.epoch,
                        'worker':{'id':'a'*16,'name':'fixture','os':'windows','tools':['launch_game'],
                                  'idle_seconds':0},'sessions':[fixture]})
                    self.assertIsNotNone(bridge.clock_offset)
                    # Real central admission creates a queued job, while this
                    # fixture has no worker/executor that could launch a game.
                    rom=root/'local'/'disc.iso';rom.write_bytes(b'owned fixture')
                    original={'game_id':'fixture_cached_rom','title':'Explicit path fixture','platform':'gamecube',
                        'format':'iso','profile_id':'fixture_cached_rom','source_paths':['//unreachable.invalid/disc.iso'],
                        'size':13,'launch':{'kind':'emulator','path':'//unreachable.invalid/disc.iso',
                                          'mercmode':{'random_characters':True,'random_stages':True}}}
                    local.state.store.upsert_catalog([{**original,'source_paths':[str(rom)],
                                                        'launch':{'kind':'emulator','path':str(rom)}}])
                    queued=client.post('/api/jobs',json={'tool':'launch_game','input':{'game':original,'jump':True},
                                                       'require_worker':'a'*16})
                    queued.raise_for_status();central_job=queued.json()
                    from gbox.store import canon,sha256
                    command={k:central_job.get(k) for k in ('id','tool','input','actor','origin','agent_use')}
                    command['input_sha256']=sha256(canon(command['input']))
                    command['command_sha256']=sha256(canon({k:command[k] for k in ('tool','input')}))
                    def capture_job(command,worker,provenance):
                        row={'id':'e'*16,'tool':'launch_game','input':command['input'],'origin':provenance,'state':'queued'}
                        local.state.store.put('job',row['id'],row);return row
                    captured=Submissions(local.state.store,capture_job,authority,central_url,resolve=bridge.resolve_input) \
                        .accept(command,{'id':'a'*16,'name':'fixture','tools':['launch_game']})
                    self.assertEqual(captured['input']['game']['launch']['path'],str(rom))
                    self.assertEqual(captured['input']['game']['launch']['mercmode'],original['launch']['mercmode'])
                    self.assertEqual(central_job['input']['game']['launch']['path'],original['launch']['path'])
                    bridge._media('a'*16,sid)
                    health=client.get('/api/sessions/'+sid+'/stream/health').json()
                    self.assertEqual(calls['media'],1);self.assertEqual(health['uploads'],1)
                    self.assertEqual(client.get('/api/sessions/'+sid+'/frame.jpg').content,jpeg)
                    with patch.dict(SESSIONS,{sid:(adapter,{})}):
                        input_thread=threading.Thread(target=bridge._input,args=(sid,),daemon=True);input_thread.start()
                        client.post('/api/sessions/'+sid+'/input',json={'events':[{'key':'b','down':True,'src':'ui'}]}).raise_for_status()
                        deadline=time.monotonic()+5
                        while not sent and time.monotonic()<deadline:time.sleep(.02)
                        self.assertTrue(sent and sent[-1]['down']);self.assertNotIn('_gbox_desktop_input_lease',sent[-1])
                        result=client.post('/api/sessions/'+sid+'/rpc',json={'op':'info','args':{'test':'actual-rpc-roundtrip'}})
                        result.raise_for_status();self.assertEqual(result.json()['echo'],'actual-rpc-roundtrip')
                        self.assertEqual(calls['rpc'],1)
                        # A local/autobot hold shares the native button. Ending
                        # the remote lease must preserve that actual local hold.
                        adapter.send_input([{'key':'b','down':True}])
                        bridge.stop.set();input_thread.join(timeout=6)
                        self.assertFalse(input_thread.is_alive());self.assertTrue(sent[-1]['down'])
                    target=os.environ.get('GBOX_DESKTOP_TRANSPORT_RECEIPT')
                    if target:Path(target).write_text(json.dumps({'synthetic_transport_fixture_only':True,
                        'jpeg_frames':4,'continuous_uploads':health['uploads'],'local_capture_connections':calls['media'],
                        'scoped_rpc_roundtrips':calls['rpc'],'private_lease_stripped':True,'local_hold_preserved':True},indent=2))
            finally:
                bridge.stop.set()
                for server in servers:server.should_exit=True
                for thread in threads:thread.join(timeout=5)
                local.state.store.db.close();central.state.store.db.close()


if __name__=='__main__':unittest.main()
