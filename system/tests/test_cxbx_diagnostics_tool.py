"""Trust boundaries for the historical Cxbx read-only collector."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from gbox import cxbx_diagnostics_tool as D
from gbox.store import canon, sha256

JOB = "a" * 16
STOP = "b" * 16
WORKER = "c" * 16
GAME = "d" * 16
RECEIPT = "e" * 16
STOP_RECEIPT = "f" * 16
SID = WORKER + "-" + JOB


def receipt(job, rid):
    return dict(id=rid, job_id=job["id"], tool=job["tool"], worker_id=job["worker_id"],
                input_sha256=sha256(canon(job["input"])), output_sha256=sha256(canon(job["output"])),
                started=job["started"], finished=job["finished"], validation_ok=True, validation_problems=[])


@pytest.fixture
def source(monkeypatch):
    job = dict(id=JOB, tool="launch_game", worker_id=WORKER, state="succeeded", error=None,
               receipt_id=RECEIPT, result_acceptance="complete", started=100., finished=105.,
               input={"game":{"game_id":GAME,"platform":"xbox"}},
               output={"adapter":"cxbx","session_id":SID,
                       "detail":{"rom":"D:/gBox/runtime/extract/rom-owned/default.xbe","worker_name":"i9-NUC"}})
    stop = dict(id=STOP, tool="session_op", worker_id=WORKER, state="succeeded", error=None,
                receipt_id=STOP_RECEIPT, result_acceptance="complete", started=110., finished=111.,
                input={"session_id":SID,"op":"stop_game"}, output={"ended":True,"session_id":SID})
    rows = {"/api/jobs/"+JOB:job, "/api/receipts/"+RECEIPT:receipt(job,RECEIPT),
            "/api/jobs/"+STOP:stop, "/api/receipts/"+STOP_RECEIPT:receipt(stop,STOP_RECEIPT)}
    monkeypatch.setattr(D,"_get",lambda ctx,path: deepcopy(rows[path]))
    ctx = SimpleNamespace(worker=WORKER,config=SimpleNamespace(runtime=Path("D:/gBox/runtime")))
    return rows,ctx


def request(**changes):
    return D.DiagnosticsIn(launch_job_id=JOB,game_id=GAME,**changes)


def test_exact_historical_launch_and_stop(source):
    rows,ctx=source
    value=D.trusted_launch(request(stop_job_id=STOP),ctx)
    assert value["session_id"]==SID and value["worker_id"]==WORKER
    assert value["ended"]["receipt_id"]==STOP_RECEIPT and value["ended"]["at"]==111
    assert value["worker_alias"] is None
    assert value["output_sha256"]==rows["/api/receipts/"+RECEIPT]["output_sha256"]


@pytest.mark.parametrize("field,value",[("path","D:/private"),("pid",1),("launch_job_id","../../bad"),("game_id","bad")])
def test_no_arbitrary_path_pid_or_identifier(field,value):
    data=dict(launch_job_id=JOB,game_id=GAME);data[field]=value
    with pytest.raises(ValidationError):D.DiagnosticsIn(**data)


@pytest.mark.parametrize("field,value",[("state","running"),("result_acceptance","pending"),("receipt_id","../x"),
    ("tool","echo_artifact"),("id",STOP),("error","failed")])
def test_reject_unaccepted_launch(source,field,value):
    rows,ctx=source;rows["/api/jobs/"+JOB][field]=value
    with pytest.raises(ValueError):D.trusted_launch(request(),ctx)


@pytest.mark.parametrize("field,value",[("validation_ok",False),("validation_problems",["bad"]),
    ("worker_id",STOP),("input_sha256","0"*64),("output_sha256","0"*64),("finished",106.),("id",STOP_RECEIPT)])
def test_receipt_must_match(source,field,value):
    rows,ctx=source;rows["/api/receipts/"+RECEIPT][field]=value
    with pytest.raises(ValueError):D.trusted_launch(request(),ctx)


def test_mutated_launch_path_rejected_before_files(source):
    rows,ctx=source;rows["/api/jobs/"+JOB]["output"]["detail"]["rom"]="D:/other/default.xbe"
    with pytest.raises(ValueError,match="bytes differ"):D.trusted_launch(request(),ctx)


@pytest.mark.parametrize("mutation",["wrong_game","wrong_platform","wrong_adapter","wrong_session","bad_times"])
def test_even_hash_valid_wrong_identity_rejected(source,mutation):
    rows,ctx=source;j=rows["/api/jobs/"+JOB]
    if mutation=="wrong_game":j["input"]["game"]["game_id"]=STOP
    elif mutation=="wrong_platform":j["input"]["game"]["platform"]="ps2"
    elif mutation=="wrong_adapter":j["output"]["adapter"]="retroarch"
    elif mutation=="wrong_session":j["output"]["session_id"]=WORKER+"-"+STOP
    else:j["finished"]=99.
    rows["/api/receipts/"+RECEIPT]=receipt(j,RECEIPT)
    with pytest.raises(ValueError):D.trusted_launch(request(),ctx)


def test_recorded_alias_allows_refreshed_same_node(source):
    rows,ctx=source;ctx.worker="1"*16
    rows["/api/background/workers/"+WORKER+"/status"]={"online":True,
        "worker":{"id":ctx.worker,"name":"i9-NUC","os":"windows"}}
    value=D.trusted_launch(request(),ctx)
    assert value["worker_id"]==WORKER and value["collection_worker_id"]==ctx.worker
    assert value["worker_alias"]["from"]==WORKER


@pytest.mark.parametrize("change",[{"id":"2"*16},{"name":"other"},{"os":"linux"}])
def test_name_alone_or_wrong_node_not_authorization(source,change):
    rows,ctx=source;ctx.worker="1"*16
    rows["/api/background/workers/"+WORKER+"/status"]={"online":True,
        "worker":{"id":ctx.worker,"name":"i9-NUC","os":"windows",**change}}
    with pytest.raises(ValueError,match="launch owner"):D.trusted_launch(request(),ctx)


@pytest.mark.parametrize("mutation",["other_session","not_ended","not_stop","before_launch"])
def test_stop_receipt_exact_scope(source,mutation):
    rows,ctx=source;j=rows["/api/jobs/"+STOP]
    if mutation=="other_session":j["input"]["session_id"]=WORKER+"-"+STOP
    elif mutation=="not_ended":j["output"]["ended"]=False
    elif mutation=="not_stop":j["input"]["op"]="query_runtime"
    else:j["started"]=101.
    rows["/api/receipts/"+STOP_RECEIPT]=receipt(j,STOP_RECEIPT)
    with pytest.raises(ValueError,match="Stop receipt"):D.trusted_launch(request(stop_job_id=STOP),ctx)


def test_non_windows_cannot_run_collector(source,monkeypatch):
    _,ctx=source;monkeypatch.setattr(D,"HOST_OS","linux")
    with pytest.raises(ValueError,match="Windows"):D.cxbx_diagnostics(request(),ctx)


def test_identity_fetch_bounded_and_no_redirects(monkeypatch):
    seen={}
    class Response:
        def raise_for_status(self):pass
        def iter_bytes(self,chunk_size):
            assert chunk_size==65536
            yield b"x"*(D.MAX_API_BYTES+1)
    @contextmanager
    def stream(method,url,**kw):
        seen.update(method=method,url=url,**kw);yield Response()
    monkeypatch.setattr(D.httpx,"stream",stream)
    ctx=SimpleNamespace(server="http://control",headers={"Authorization":"test"},execution_deadline_monotonic=None)
    with pytest.raises(ValueError,match="bounded limit"):D._get(ctx,"/api/jobs/"+JOB)
    assert seen["method"]=="GET" and seen["follow_redirects"] is False
    assert seen["timeout"]==10


def test_expired_deadline_does_not_read_network(monkeypatch):
    monkeypatch.setattr(D.httpx,"stream",lambda *a,**k:pytest.fail("network called"))
    ctx=SimpleNamespace(server="http://control",execution_deadline_monotonic=0)
    with pytest.raises(TimeoutError):D._get(ctx,"/api/jobs/"+JOB)


def test_readonly_collector_does_not_apply_agent_volume(monkeypatch,tmp_path):
    from gbox import worker as W
    from gbox.config import Config
    monkeypatch.setattr(W,"HOST_OS","windows")
    monkeypatch.setattr(W.deps,"install_for",lambda *a:pytest.fail("dependency install/volume path called"))
    monkeypatch.setattr(W,"execute",lambda name,inp,ctx:{"agent_use":ctx.agent_use})
    delivered=[]
    monkeypatch.setattr(W,"_deliver_finished",lambda *a:delivered.append(a[3]))
    job={"id":JOB,"tool":"cxbx_diagnostics","input":{},"agent_use":True}
    assert W._quiet_agent_job(job) is False
    assert W._quiet_agent_job(job|{"tool":"launch_game"}) is True
    assert W._quiet_agent_job(job|{"tool":"session_op"}) is True
    assert W._quiet_agent_job(job|{"agent_use":False}) is False
    W._run_job(job,Config(data_dir=tmp_path,runtime_dirs={"linux":str(tmp_path/"runtime"),"windows":str(tmp_path/"runtime")}),WORKER,"http://control",{},None,
               set(),set(),set(),None)
    assert delivered[0]["ok"] is True and delivered[0]["output"]["agent_use"] is True


def test_full_tool_emits_durable_bounded_report_for_ended_launch(source,monkeypatch,tmp_path):
    from gbox.config import Config
    from gbox.registry import Ctx
    rows,_=source
    runtime=tmp_path/"runtime";home=runtime/"xbox"/"cxbx";home.mkdir(parents=True)
    xbe=runtime/"extract"/"rom-owned"/"default.xbe";xbe.parent.mkdir(parents=True);xbe.write_bytes(b"XBEHfixture")
    (home/"cxbxr-ldr.exe").write_bytes(b"MZfixture")
    (home/"settings.ini").write_text("[video]\nVSync = false\n[network]\npassword = private\n")
    j=rows["/api/jobs/"+JOB];j["output"]["detail"]["rom"]=str(xbe)
    rows["/api/receipts/"+RECEIPT]=receipt(j,RECEIPT)
    monkeypatch.setattr(D,"HOST_OS","windows")
    ctx=Ctx(Config(data_dir=tmp_path/"data",runtime_dirs={"linux":str(runtime),"windows":str(runtime)}),job_id="0"*16,worker=WORKER)
    before={str(f):f.read_bytes() for f in runtime.rglob("*") if f.is_file()}
    out=D.cxbx_diagnostics(request(stop_job_id=STOP),ctx)
    assert len(ctx.artifacts)==1
    name,data,media,provenance=ctx.artifacts[0]
    assert name==D.ARTIFACT and media=="application/json" and sha256(data)==out["report_sha256"]
    report=json.loads(data)
    assert report["accepted_launch"]["ended"]["job_id"]==STOP
    assert report["files"]["default.xbe"]["sha256"]==sha256(b"XBEHfixture")
    assert report["process"]["state"]=="not_inspected" and b"private" not in data
    assert provenance["launch_job_id"]==JOB and provenance["collected_by"]==WORKER
    assert before=={str(f):f.read_bytes() for f in runtime.rglob("*") if f.is_file()}
