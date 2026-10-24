"""A reconnect relays to one real local job, never a second execution."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from gbox.desktop_bridge import DesktopBridge, Submissions, SubmissionHeld, jpeg_parts, origin
from gbox.store import Store, canon, sha256


class DesktopBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root)
        self.calls=[];self.worker={'id':'a'*16,'name':'this-pc','tools':['launch_game','autoplay','session_op']}
        self.command={'id':'b'*16,'tool':'launch_game','input':{'game_id':'owned_game'},'actor':'operator'}
        self.command['input_sha256']=sha256(canon(self.command['input']))
        self.command['command_sha256']=sha256(canon({k:self.command[k] for k in ('tool','input')}))
        self.submissions=Submissions(self.store,self.submit,'c'*64,'http://central.example:8765')

    def tearDown(self):self.store.db.close();self.tmp.cleanup()

    def submit(self,command,worker,provenance):
        self.calls.append(command)
        row={'id':'d'*16,'tool':command['tool'],'input':command['input'],'state':'queued','origin':provenance}
        self.store.put('job',row['id'],row);return row

    def test_lost_reply_and_concurrent_redelivery_execute_submission_once(self):
        jobs=[];errors=[]
        def invoke():
            try:jobs.append(self.submissions.accept(self.command,self.worker))
            except Exception as error:errors.append(error)
        threads=[threading.Thread(target=invoke) for _ in range(12)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(errors,[]);self.assertEqual(len(self.calls),1)
        self.assertEqual({job['id'] for job in jobs},{'d'*16})
        restarted=Submissions(self.store,self.submit,'c'*64,'http://central.example:8765')
        self.assertEqual(restarted.accept(self.command,self.worker)['id'],'d'*16)
        self.assertEqual(len(self.calls),1)

    def test_crash_after_durable_job_before_mapping_recovers_actual_job(self):
        def lost_reply(command,worker,provenance):
            self.submit(command,worker,provenance);raise RuntimeError('lost local response')
        self.submissions.submit=lost_reply
        with self.assertRaises(RuntimeError):self.submissions.accept(self.command,self.worker)
        self.submissions.submit=self.submit
        self.assertEqual(self.submissions.accept(self.command,self.worker)['id'],'d'*16)
        self.assertEqual(len(self.calls),1)

    def test_crash_before_job_commit_is_held_instead_of_repeating_unknown_effect(self):
        def ambiguous(*args):self.calls.append(args);raise RuntimeError('process interrupted')
        self.submissions.submit=ambiguous
        with self.assertRaises(RuntimeError):self.submissions.accept(self.command,self.worker)
        with self.assertRaises(SubmissionHeld):self.submissions.accept(self.command,self.worker)
        self.assertEqual(len(self.calls),1)

    def test_identity_cannot_change_input_or_tool_even_after_a_restart(self):
        self.submissions.accept(self.command,self.worker)
        changed={**self.command,'tool':'autoplay'}
        changed['command_sha256']=sha256(canon({k:changed[k] for k in ('tool','input')}))
        with self.assertRaisesRegex(ValueError,'cannot change'):self.submissions.accept(changed,self.worker)
        self.assertEqual(len(self.calls),1)

    def test_unavailable_tools_forged_digest_and_foreign_sessions_never_submit(self):
        for changed in ({'tool':'@launch'},{'input_sha256':'0'*64},
                        {'input':{'session_id':'f'*16+'-other'}}, {'require_worker':'another-pc'}):
            command={**self.command,**changed}
            if 'input' in changed:
                command['input_sha256']=sha256(canon(command['input']))
                command['command_sha256']=sha256(canon({k:command[k] for k in ('tool','input')}))
            with self.assertRaises(ValueError):self.submissions.accept(command,self.worker)
        self.assertEqual(self.calls,[])

    def test_exact_remote_origin_has_its_own_durable_namespace(self):
        self.submissions.accept(self.command,self.worker)
        other=Submissions(self.store,self.submit,'c'*64,'http://another.example:8765')
        self.assertNotEqual(self.submissions.key(self.command['id']),other.key(self.command['id']))
        self.assertEqual(len(other.rows()),0)

    def test_only_actual_ready_worker_can_be_mirrored(self):
        bridge=DesktopBridge.__new__(DesktopBridge);bridge.store=self.store
        bridge.worker=SimpleNamespace(name='this-pc',state={'running':False,'state':'waiting_native_owner'})
        self.store.put('worker',self.worker['id'],{**self.worker,'last_seen':__import__('time').time()})
        self.assertIsNone(bridge.actual_worker())
        bridge.worker.state={'running':True,'state':'running'}
        self.assertEqual(bridge.actual_worker()['id'],self.worker['id'])
        bridge.worker.name='other-pc';self.assertIsNone(bridge.actual_worker())

    def test_snapshot_contains_exact_owner_sessions_including_actual_ends(self):
        bridge=DesktopBridge.__new__(DesktopBridge);bridge.store=self.store
        own={'session_id':self.worker['id']+'-real','state':'ended','ended':123,'detail':{'pid':42}}
        self.store.put('session',own['session_id'],own)
        self.store.put('session','f'*16+'-foreign',{'session_id':'f'*16+'-foreign','state':'running'})
        self.assertEqual(bridge.sessions(self.worker),[own])

    def test_results_keep_native_session_and_actual_artifact_bytes(self):
        bridge=DesktopBridge.__new__(DesktopBridge);bridge.store=self.store
        artifact=self.store.put_artifact(b'actual run','run.json','application/json',{'run':'native'})
        self.store.put('receipt','r',{'artifacts':[artifact.model_dump()]})
        native_sid=self.worker['id']+'-actual-local-launch-id'
        result=bridge.result({'state':'succeeded','output':{'session_id':native_sid},'receipt_id':'r'},self.command['id'])
        self.assertEqual(result['job_id'],self.command['id']);self.assertEqual(result['output']['session_id'],native_sid)
        self.assertEqual(__import__('base64').b64decode(result['artifacts'][0]['b64']),b'actual run')
        self.assertEqual(result['artifacts'][0]['provenance']['local_sha256'],artifact.sha256)

    def test_one_held_result_does_not_starve_other_results_or_controls(self):
        bridge=DesktopBridge.__new__(DesktopBridge);bridge.store=self.store;bridge.state={}
        bridge.submissions=self.submissions
        first=self.submissions.accept(self.command,self.worker)
        self.store.put('job',first['id'],first|{'state':'succeeded','receipt_id':'huge'})
        self.store.put('receipt','huge',{'artifacts':[{'sha256':'0'*64,'size':100*1024*1024}]})
        good={'id':'e'*16,'local_job_id':'f'*16,'remote':self.submissions.remote,'tool':'echo_artifact'}
        self.store.put('desktop_bridge_job',self.submissions.key(good['id']),good)
        self.store.put('job',good['local_job_id'],{'id':good['local_job_id'],'state':'succeeded','output':{'actual':True}})
        reports=[]
        bridge._central=lambda client,method,path,**kwargs:reports.append((path,kwargs)) or {'accepted':True}
        bridge._report_jobs(None)
        self.assertEqual([path for path,kwargs in reports],['/jobs/'+good['id']])
        self.assertEqual(len(bridge.state['delivery_holds']),1)
        self.assertEqual(bridge.state['delivery_holds'][0]['central_job_id'],self.command['id'])
        self.assertTrue(self.store.get('desktop_bridge_job',self.submissions.key(good['id']))['central_acked'])

    def test_multipart_chunks_are_bounded_and_do_not_mix_frames(self):
        one=b'\xff\xd8one\xff\xd9';two=b'\xff\xd8two\xff\xd9'
        body=b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+one+b'\r\n--frame\r\n\r\n'+two
        chunks=[body[i:i+3] for i in range(0,len(body),3)]
        self.assertEqual(list(jpeg_parts(chunks)),[one,two])
        with self.assertRaises(ValueError):list(jpeg_parts([b'\xff\xd8'+b'x'*8_000_001]))

    def test_origin_cannot_embed_a_token_or_credentials_or_path(self):
        self.assertEqual(origin('http://central.example:8765/'),'http://central.example:8765')
        for value in ('file:///secret','http://user:secret@central.example','http://central.example/?token=secret',
                      'http://central.example/api','not a URL'):
            with self.assertRaises(ValueError):origin(value)

    def test_remote_expiry_uses_conservative_measured_server_clock(self):
        from unittest.mock import patch
        bridge=DesktopBridge.__new__(DesktopBridge);bridge.authority='c'*64;bridge.clock_offset=None
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'server_time':101.7}
        client=SimpleNamespace(request=lambda *args,**kwargs:Response())
        with patch('gbox.desktop_bridge.time.time',return_value=100):
            bridge._central(client,'GET','/watch')
        self.assertAlmostEqual(bridge.clock_offset,1.7)
        # PC wall time 100 does not make an already expired central event valid.
        self.assertGreater(100+bridge.clock_offset,101.5)

    def test_key_up_expiring_in_transit_clears_only_its_remote_lease(self):
        from gbox.desktop_bridge import remote_pad_events
        from gbox.desktop_input_lease import InputLease,MARKER
        sent=[];lease=InputLease(lambda rows:sent.extend(rows),'private')
        lease([{'key':'fire','down':True},{'key':'fire','down':True,MARKER:'private'},
               {'key':'forward','down':True,MARKER:'private'}]);sent.clear()
        self.assertEqual(remote_pad_events([
            {'key':'forward','down':False,'_federation_expires_at':101},
            {'key':'fire','down':False,'_federation_expires_at':101},
            {'key':'new_stale_press','down':True}],lease,'private',102),[])
        self.assertEqual(sent,[{'key':'forward','down':False},{'key':'fire','down':True}])
        fresh=remote_pad_events([{'key':'aim','down':True,'_federation_expires_at':104,MARKER:'forged'}],lease,'private',102)
        self.assertEqual(fresh,[{'key':'aim','down':True,MARKER:'private'}])

    def test_launch_resolves_verified_local_path_preserving_original_digest_and_mercmode_flags(self):
        from gbox.config import Config
        bridge=DesktopBridge.__new__(DesktopBridge);bridge.store=self.store;bridge.cfg=Config(data_dir=self.root/'data')
        rom=self.root/'disc.iso';rom.write_bytes(b'owned fixture')
        game={'game_id':'owned_game','title':'Fixture','platform':'gamecube','format':'iso','profile_id':'owned_game',
              'source_paths':['//unreachable.invalid/games/disc.iso'],'size':13,
              'launch':{'kind':'emulator','path':'//unreachable.invalid/games/disc.iso',
                        'mercmode':{'random_characters':True,'random_stages':True}}}
        self.store.upsert_catalog([{**game,'source_paths':[str(rom)],'launch':{'kind':'emulator','path':str(rom)}}])
        inp={'game':game,'jump':True};before=canon(inp)
        command={**self.command,'input':inp,'input_sha256':sha256(before),
                 'command_sha256':sha256(canon({'tool':'launch_game','input':inp}))}
        submissions=Submissions(self.store,self.submit,'c'*64,'http://central.example:8765',resolve=bridge.resolve_input)
        def crash(command,worker,provenance):
            self.submit(command,worker,provenance);raise RuntimeError('reply lost after local commit')
        submissions.submit=crash
        with self.assertRaises(RuntimeError):submissions.accept(command,self.worker)
        recovered=submissions.accept(command,self.worker)
        self.assertEqual(recovered['input']['game']['launch']['path'],str(rom))
        self.assertEqual(recovered['input']['game']['launch']['mercmode'],game['launch']['mercmode'])
        self.assertEqual(canon(command['input']),before,'central command never changes')
        mapping=self.store.get('desktop_bridge_job',submissions.key(command['id']))
        self.assertEqual(mapping['input_sha256'],sha256(before))
        self.assertNotEqual(mapping['execution_input_sha256'],mapping['input_sha256'])
        self.assertEqual(len(self.calls),1)

    def test_demo_pending_install_is_atomic_and_never_reinstalled_after_consumption(self):
        from gbox import screensaver as S
        bridge=DesktopBridge.__new__(DesktopBridge);bridge.store=self.store;bridge.submissions=self.submissions
        command={**self.command,'input':{'game':{'game_id':'owned_game'}},
                 'autoplay_on_launch':{'game_id':'owned_game','actor':'operator','agent':False}}
        job={'id':'e'*16,'tool':'launch_game','input':command['input']}
        self.assertTrue(bridge.install_demo_marker(command,job))
        self.assertEqual(self.store.get(S.PENDING,job['id'])['game_id'],'owned_game')
        self.store.delete(S.PENDING,job['id'])
        self.assertFalse(bridge.install_demo_marker(command,job))
        self.assertIsNone(self.store.get(S.PENDING,job['id']))
        foreign={**command,'id':'f'*16,'autoplay_on_launch':{'game_id':'different'}}
        with self.assertRaises(ValueError):bridge.install_demo_marker(foreign,job)

    def test_mapped_autoplay_reports_only_exact_parent_session(self):
        bridge=DesktopBridge.__new__(DesktopBridge);bridge.store=self.store;bridge.submissions=self.submissions
        sid=self.worker['id']+'-'+'1'*16;parent='2'*16
        self.store.put('job',parent,{'id':parent,'tool':'autoplay','input':{'session_id':sid,'op':'start'}})
        self.store.put('desktop_bridge_job',self.submissions.key('3'*16),
                       {'id':'3'*16,'remote':self.submissions.remote,'tool':'autoplay','local_job_id':parent})
        self.assertIsNotNone(bridge.mapped_autoplay({'session_id':sid},parent))
        self.assertIsNone(bridge.mapped_autoplay({'session_id':sid},'4'*16))
        self.assertIsNone(bridge.mapped_autoplay({'session_id':'other'},parent))

    def test_handover_report_is_durable_offline_and_replayed_once_for_exact_parent(self):
        from unittest.mock import patch
        import httpx
        bridge=DesktopBridge.__new__(DesktopBridge);bridge.store=self.store;bridge.submissions=self.submissions
        bridge.remote=self.submissions.remote;bridge.token='fixture';bridge.secret='f'*64;bridge.authority='c'*64
        sid=self.worker['id']+'-'+'1'*16;parent='2'*16
        self.store.put('job',parent,{'id':parent,'tool':'autoplay','input':{'session_id':sid,'op':'start'}})
        self.store.put('desktop_bridge_job',self.submissions.key('3'*16),
                       {'id':'3'*16,'remote':bridge.remote,'tool':'autoplay','local_job_id':parent})
        with patch.object(bridge,'_central',side_effect=httpx.ConnectError('offline')):
            result=bridge.autoplay_report('yield',{'session_id':sid,'reason':'mouse'},parent)
        self.assertTrue(result['queued'])
        queued=self.store.all('desktop_bridge_report');self.assertEqual(len(queued),1)
        self.assertEqual(queued[0]['payload']['local_job_id'],parent)
        calls=[];bridge._central=lambda *args,**kwargs:calls.append(kwargs['json']) or {'saved':True}
        bridge._reports(None);bridge._reports(None)
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['body']['reason'],'mouse')
        self.assertIsNone(bridge.autoplay_report('yield',{'session_id':sid,'reason':'pad'},'4'*16))

    def test_handover_rejects_only_exact_automatic_stop_even_at_final_native_callsite(self):
        from unittest.mock import patch
        from gbox import desktop_bridge as B,tools
        from gbox.config import Config
        from gbox.registry import Unsupported
        from gbox.screensaver import ACTOR
        bridge=DesktopBridge.__new__(DesktopBridge);bridge.store=self.store;bridge.submissions=self.submissions
        bridge.authority='c'*64;bridge.remote=self.submissions.remote
        cfg=Config(data_dir=self.root);sid=self.worker['id']+'-'+'1'*16;parent='2'*16
        self.store.put('session',sid,{'session_id':sid,'state':'running'})
        self.store.put('job',parent,{'id':parent,'tool':'autoplay','input':{'session_id':sid,'op':'start'}})
        parentmap={'id':'3'*16,'remote':bridge.remote,'tool':'autoplay','local_job_id':parent}
        self.store.put('desktop_bridge_job',self.submissions.key(parentmap['id']),parentmap)
        stopid='4'*16;centralstop='5'*16;key=self.submissions.key(centralstop)
        stop={'id':stopid,'tool':'session_op','input':{'session_id':sid,'op':'stop_game'},'state':'queued','actor':ACTOR,
              'origin':{'desktop_federation_authority':bridge.authority,'desktop_federation_key':key,
                        'central_origin':{'via':'autoplay screensaver','session_id':sid}}}
        self.store.put('job',stopid,stop)
        self.store.put('desktop_bridge_job',key,{'id':centralstop,'remote':bridge.remote,'local_job_id':stopid,'tool':'session_op'})
        operator={**stop,'id':'6'*16,'actor':'operator'};self.store.put('job',operator['id'],operator)
        bridge.note_handover({'session_id':sid,'reason':'pad'},parent,parentmap)
        self.assertEqual(self.store.get('job',stopid)['state'],'rejected')
        self.assertEqual(self.store.get('job',operator['id'])['state'],'queued')
        # A previously claimed automatic stop is checked again immediately
        # before the actual adapter mutation; an operator Stop is permitted.
        self.store.put('job',stopid,stop|{'state':'running'})
        ctx=SimpleNamespace(config=cfg,job_id=stopid)
        called=[];adapter=SimpleNamespace(stop_game=lambda:called.append(True))
        with patch.dict(B._LOCAL_AUTHORITIES,{str(cfg.data_dir.resolve()):bridge}),patch.dict(tools.SESSIONS,{sid:(adapter,{})}):
            with self.assertRaises(Unsupported):tools._stop_session(sid,{},ctx)
            self.assertEqual(called,[])
            B.check_stop(SimpleNamespace(config=cfg,job_id=operator['id']),sid)
            self.store.put('session',sid,{'session_id':sid,'state':'ended'})
            B.check_stop(ctx,sid)


if __name__=='__main__':unittest.main()
