"""Opt-in real HTTP smoke: two temporary authorities, one executor, no emulator.

GBOX_TEST_DESKTOP_HTTP=1 python -m unittest tests.test_desktop_federation_http
"""
import concurrent.futures
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from gbox.store import canon,sha256


@unittest.skipUnless(os.environ.get('GBOX_TEST_DESKTOP_HTTP')=='1','opt-in isolated HTTP/worker acceptance')
class DesktopFederationHttpTests(unittest.TestCase):
    def test_actual_worker_job_and_central_replay_use_one_local_execution(self):
        source=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root=Path(temporary);processes=[];logs=[]
            def port():
                with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
            def start(label,worker):
                profile=root/label;profile.mkdir();config=profile/'gbox.toml'
                config.write_text('data_dir="data"\n[audio_cpp]\nenabled=false\n'
                    '[hermes.local]\nenabled=false\n[hermes.grunt]\nenabled=false\n')
                chosen=port();base='http://127.0.0.1:'+str(chosen)
                env={**os.environ,'PYTHONPATH':str(source),'GBOX_LAUNCH_FAILURES':'0','PYTHONUNBUFFERED':'1'}
                env.pop('GBOX_TOKEN',None);env.pop('GBOX_CLIENT_CONTROL',None)
                log=(profile/'service.log').open('w',encoding='utf-8');logs.append(log)
                child=subprocess.Popen([sys.executable,'-P','-m','gbox.desktop_local','--config',str(config),
                    '--port',str(chosen),'--name',label]+([] if worker else ['--no-worker']),
                    env=env,cwd=source,stdout=log,stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                processes.append(child)
                marker=None;deadline=time.monotonic()+70
                while time.monotonic()<deadline:
                    if child.poll() is not None:raise AssertionError(label+' service exited')
                    try:
                        with urlopen(base+'/api/desktop-local',timeout=.5) as response:marker=json.load(response)
                        if marker.get('ok'):break
                    except (OSError,URLError):time.sleep(.15)
                self.assertTrue(marker and marker.get('ok'),label+' service startup timed out')
                token=(profile/'data/api_token').read_text().strip()
                def api(path,body=None):
                    request=Request(base+path,data=None if body is None else json.dumps(body).encode(),
                        headers={'authorization':'Bearer '+token,'content-type':'application/json'})
                    with urlopen(request,timeout=10) as response:return json.load(response)
                return api,base,profile
            def until(fn,condition,seconds=35):
                end=time.monotonic()+seconds;last=None
                while time.monotonic()<end:
                    last=fn()
                    if condition(last):return last
                    time.sleep(.2)
                self.fail('Timed out waiting for actual state: '+str(last)[:500])
            try:
                central,remote,central_profile=start('isolated-central',False)
                local,_,local_profile=start('isolated-local',True)
                workers=until(lambda:local('/api/workers'),lambda rows:any(row.get('online') for row in rows))
                actual=next(row for row in workers if row.get('online'))
                # A real local API job executes while central is unconfigured.
                ordinary=local('/api/jobs',{'tool':'echo_artifact','input':{'message':'local offline acceptance'},
                                           'require_worker':actual['id']})
                ordinary=until(lambda:local('/api/jobs/'+ordinary['id']),lambda row:row['state']=='succeeded')
                self.assertEqual(ordinary['output']['length'],24)
                paired=local('/api/desktop-local/bridge',{'remote_url':remote,
                             'token':(central_profile/'data/api_token').read_text().strip()})
                self.assertTrue(paired['configured'])
                mirrored=until(lambda:central('/api/workers'),lambda rows:any(row['id']==actual['id'] for row in rows))
                self.assertEqual([row['id'] for row in mirrored],[actual['id']], 'central is not a second executor')
                central_job=central('/api/jobs',{'tool':'echo_artifact','input':{'message':'one central command'},
                                                'require_worker':actual['id']})
                finished=until(lambda:central('/api/jobs/'+central_job['id']),lambda row:row['state'] in ('succeeded','failed','invalid'))
                self.assertEqual(finished['state'],'succeeded',finished.get('error'))
                command={k:central_job.get(k) for k in ('id','tool','input','actor','origin','agent_use')}
                command['input_sha256']=sha256(canon(command['input']))
                command['command_sha256']=sha256(canon({k:command[k] for k in ('tool','input')}))
                # Deliberately discard the first recovered response, then replay
                # concurrently as if the response/connection had been lost.
                local('/api/desktop-local/federated-jobs',command)
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                    retries=list(pool.map(lambda _:local('/api/desktop-local/federated-jobs',command),range(12)))
                self.assertEqual(len({row['id'] for row in retries}),1)
                local_jobs=local('/api/jobs?limit=100')
                relayed=[row for row in local_jobs if row['input'].get('message')=='one central command']
                self.assertEqual(len(relayed),1)
                self.assertEqual(retries[0]['id'],relayed[0]['id'])
                receipt=central('/api/receipts/'+finished['receipt_id'])
                self.assertTrue(receipt['validation_ok']);self.assertEqual(len(receipt['artifacts']),1)
                self.assertEqual(local('/api/sessions'),[]);self.assertEqual(central('/api/sessions'),[])
                # Simulate central loss. The same local worker and tools remain
                # functional; no remote launch has been queued for reconnect.
                remote_child=processes[0]
                if os.name=='nt':subprocess.run(['taskkill','/T','/F','/PID',str(remote_child.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                else:remote_child.terminate()
                remote_child.wait(timeout=8)
                offline=local('/api/jobs',{'tool':'echo_artifact','input':{'message':'offline still works'},'require_worker':actual['id']})
                offline=until(lambda:local('/api/jobs/'+offline['id']),lambda row:row['state']=='succeeded')
                self.assertEqual(offline['worker_id'],actual['id'])
                self.assertEqual(local('/api/sessions'),[])
                receipt={'local_job_executed':True,'central_job_validated':True,'central_retry_count':13,
                    'local_executions_for_central_job':len(relayed),'single_worker_id':actual['id'],
                    'local_work_survives_central_loss':True,'sessions':0}
                target=os.environ.get('GBOX_DESKTOP_HTTP_RECEIPT')
                if target:Path(target).write_text(json.dumps(receipt,indent=2))
            finally:
                for child in reversed(processes):
                    if child.poll() is None:
                        if os.name=='nt':subprocess.run(['taskkill','/T','/F','/PID',str(child.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                        else:child.terminate()
                        try:child.wait(timeout=8)
                        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
                for log in logs:log.close()


if __name__=='__main__':unittest.main()
