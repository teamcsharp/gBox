import concurrent.futures
import threading
import time
from pathlib import Path

import pytest
from pydantic import BaseModel
from gbox import registry as R
from gbox.config import Config
from test_re2gc_state import build
from test_re2gc_items import harness


class Output(BaseModel):
    result:dict


def test_queued_inventory_past_outer_timeout_cannot_write(monkeypatch,tmp_path,build):
    memory,events,run,inp=harness(monkeypatch,build)
    ctx=R.Ctx(Config(cache_dir=tmp_path/'cache',data_dir=tmp_path/'data'))
    blocker=threading.Event();started=threading.Event();done=threading.Event();observed={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda:(started.set(),blocker.wait(5)))
        assert started.wait(1)
        monkeypatch.setattr(R,'_pool',pool)
        def operation(inp,ctx):
            try:
                observed['deadline']=ctx.execution_deadline_monotonic
                observed['started']=time.monotonic()
                # Harness normally uses a deterministic clock; real monotonic
                # time here ties the actual RE2 final write gate to submission.
                return {'result':run(execution_deadline=ctx.execution_deadline_monotonic,
                                     clock=time.monotonic)}
            except Exception as exc:observed['error']=str(exc);raise
            finally:done.set()
        tool=R.Tool(name='re2-deadline-proof',version='1',fn=operation,In=BaseModel,Out=Output,timeout_s=.025,retries=0)
        try:
            with pytest.raises(concurrent.futures.TimeoutError):R._execute(tool,None,ctx)
            assert not done.is_set() and not memory.events
        finally:blocker.set()
        assert done.wait(3)
    assert observed['started']>observed['deadline']
    assert 'preparation expired' in observed['error']
    assert not memory.events
    assert ctx.execution_deadline_monotonic is None


def test_deadline_is_per_execution_even_when_context_is_reused(tmp_path):
    ctx=R.Ctx(Config(cache_dir=tmp_path/'cache',data_dir=tmp_path/'data'))
    other=R.Ctx(ctx.config);barrier=threading.Barrier(2)
    def operation(wanted,active):
        barrier.wait(timeout=2)
        assert active.execution_deadline_monotonic==wanted
        assert other.execution_deadline_monotonic is None
        return wanted
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(R._run_with_fitting,operation,10,ctx,10)
        b=pool.submit(R._run_with_fitting,operation,20,ctx,20)
        assert (a.result(),b.result())==(10,20)
    assert ctx.execution_deadline_monotonic is None
    def fail(inp,ctx):
        assert ctx.execution_deadline_monotonic==30
        raise ValueError('expected')
    with pytest.raises(ValueError):R._run_with_fitting(fail,None,ctx,30)
    assert ctx.execution_deadline_monotonic is None
