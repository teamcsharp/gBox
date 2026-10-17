import time
from gbox import background_status as B
from gbox.re_agent import run_loop
from tests.test_inspection_builds import Store,worker


def test_background_snapshot_keeps_bounded_presentation_and_never_arbitrary_inputs():
    s=Store();w=worker(time.time())
    s.put('job','j',{'id':'j','tool':'characters','worker_id':w['id'],'state':'running','agent_use':True,
        'input':{'op':'cast_swap','character':'sonic','api_key':'secret','prompt':'private'},
        'progress_log':['line'+str(n) for n in range(100)],
        'fitting':{'current':'m0','order':['m'+str(n) for n in range(80)],'models':{
            'm'+str(n):{'label':'Sonic','snapshot':'/api/jobs/j/fitting/files/model.glb'} for n in range(80)}}})
    before=s.get('job','j')
    out=B.snapshot(s,w,online=True)['active'][0]
    assert out['input']=={'op':'cast_swap','character':'sonic'}
    assert out['agent_use'] and out['worker_name']==w['name']
    assert len(out['stage_log'])==50 and out['stage_log'][0]=='line50'
    assert len(out['fitting']['models'])<=12 and 'm0' in out['fitting']['models']
    assert out['fitting']['reported_total']==80
    assert before==s.get('job','j')


def test_reconstruction_progress_shows_real_code_and_checks_without_altering_result():
    def query(op,**kw):
        return {'name':'test_fn','address':'0x10','decompiled':'int test_fn(){ return 1; }','callees':[]}
    replies=iter(['```cpp\nint test_fn(){ return 1; }\n```',
                  '{"verdict":"PASS","summary":"constant matches","issues":[],"fix_instructions":[]}'])
    logs=[]
    result=run_loop('0x10',query,lambda messages:next(replies),progress=logs.append)
    assert result['status']=='hypothesis' and result['success']
    assert any('Ghidra decompiled' in m and 'return 1;' in m for m in logs)
    assert any('Candidate reconstruction' in m for m in logs)
    assert 'gameplay verification pending' in logs[-1] and 'return 1;' in logs[-1]
    assert all(len(m)<2800 for m in logs)
