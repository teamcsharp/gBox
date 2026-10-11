"""Portable regressions on frozen installed Hermes functions; no provider requests."""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
from datetime import datetime
import importlib.util
import json
import logging
from pathlib import Path
import sys
import threading
import time
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('strict_aux_patch', ROOT/'scripts/apply_hermes_strict_auxiliary_routes.py')
patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patch)


def fixture_sources():
    return json.loads((ROOT/'tests/fixtures/hermes_strict_auxiliary_runtime.json').read_text(encoding='utf-8'))['sources']


def runtime():
    sources, changed = patch.patch_sources(fixture_sources())
    assert changed
    namespace = {'__name__':'strict_aux_fixture', 'logger':logging.getLogger('strict_aux_fixture')}
    exec(compile(sources['agent/auxiliary_client.py'], '<frozen-auxiliary-client>', 'exec'), namespace)
    return namespace, sources


def policy(provider='nous', model='anthropic/claude-opus-5.5'):
    return {'vision':{'provider':provider,'model':model,'strict':True}}


def module(monkeypatch, name, **values):
    result=ModuleType(name)
    result.__dict__.update(values)
    monkeypatch.setitem(sys.modules, name, result)
    return result


def test_compatibility_idempotence_and_unknown_version_refusal():
    original=fixture_sources()
    once, changed=patch.patch_sources(original)
    twice, changed_again=patch.patch_sources(once)
    assert changed and not changed_again and twice==once
    unknown=dict(original)
    unknown['agent/auxiliary_client.py']=unknown['agent/auxiliary_client.py'].replace('if model and model.lower()', 'if model and model.upper()')
    with pytest.raises(patch.UnsupportedRuntime):patch.patch_sources(unknown)
    with pytest.raises(patch.UnsupportedRuntime):
        patch.patch_sources({**original,'cron/scheduler.py':once['cron/scheduler.py']})
    damaged=dict(once)
    damaged['agent/auxiliary_client.py']=damaged['agent/auxiliary_client.py'].replace('strict=true','strict=false')
    with pytest.raises(patch.UnsupportedRuntime):patch.patch_sources(damaged)


@pytest.mark.parametrize('bad', [[], {'compression':{}}, {'vision':None},
    {'vision':{'provider':'nous','model':'opus','strict':False}},
    {'vision':{'provider':'auto','model':'opus','strict':True}},
    {'vision':{'provider':'nous','model':'auto','strict':True}},
    {'vision':{'provider':'nous','model':'opus','strict':1}},
    {'vision':{'provider':'nous','model':'opus','strict':True,'api_key':'forbidden'}},
    {'vision':{'provider':'https://wrong.example','model':'opus','strict':True}},
    {'vision':{'provider':'nous','model':'opus\nother','strict':True}},
])
def test_invalid_policy_fails_before_binding(bad):
    ns,_=runtime()
    with pytest.raises(ValueError):ns['set_gbox_job_auxiliary_routes'](bad)
    assert ns['_gbox_job_auxiliary_route']('vision') is None


def test_nested_scopes_snapshot_input_and_restore():
    ns,_=runtime(); route=policy()
    first=ns['set_gbox_job_auxiliary_routes'](route)
    route['vision']['provider']='openrouter'
    copied=ns['_gbox_job_auxiliary_route']('vision');copied['provider']='other'
    assert ns['_gbox_job_auxiliary_route']('vision')['provider']=='nous'
    second=ns['set_gbox_job_auxiliary_routes'](policy('deepseek','vision-model'))
    assert ns['_gbox_job_auxiliary_route']('vision')['provider']=='deepseek'
    ns['reset_gbox_job_auxiliary_routes'](second)
    assert ns['_gbox_job_auxiliary_route']('vision')['provider']=='nous'
    ns['reset_gbox_job_auxiliary_routes'](first)
    assert ns['_gbox_job_auxiliary_route']('vision') is None


def test_strict_resolution_drops_global_and_call_route_credentials(monkeypatch):
    ns,_=runtime()
    cfg={'auxiliary':{'vision':{'provider':'openrouter','model':'google/gemini',
                              'api_key':'test-global-key','base_url':'https://unrelated.example',
                              'fallback_chain':[{'provider':'deepseek','model':'other'}]}}}
    module(monkeypatch,'hermes_cli.config',load_config_readonly=lambda:cfg)
    module(monkeypatch,'hermes_cli.plugins',get_plugin_auxiliary_tasks=lambda:[])
    module(monkeypatch,'hermes_cli.runtime_provider_custom',expand_direct_api_alias=lambda p,b:(p,b))
    ns['_canonical_api_mode']=lambda x:x
    ns['_scoped_key_env']=lambda x:None
    ns['_LOCAL_SERVER_ALIASES']=set()
    token=ns['set_gbox_job_auxiliary_routes'](policy())
    assert ns['_resolve_task_provider_model']('vision','openrouter','wrong','https://wrong.example','test-wrong-key') == (
        'nous','anthropic/claude-opus-5.5',None,None,None)
    assert ns['_get_auxiliary_task_config']('vision') == {
        'provider':'nous','model':'anthropic/claude-opus-5.5','strict':True,'fallback_chain':[]}
    ns['reset_gbox_job_auxiliary_routes'](token)
    assert ns['_get_auxiliary_task_config']('vision')==cfg['auxiliary']['vision']


def test_async_concurrent_jobs_keep_their_own_route_and_cleanup():
    ns,_=runtime()
    async def one(provider):
        token=ns['set_gbox_job_auxiliary_routes'](policy(provider,'vision-model'))
        try:
            await asyncio.sleep(0)
            return ns['_resolve_task_provider_model']('vision')[0]
        finally:ns['reset_gbox_job_auxiliary_routes'](token)
    async def all_jobs():return await asyncio.gather(one('nous'),one('openrouter'))
    assert asyncio.run(all_jobs())==['nous','openrouter']
    assert ns['_gbox_job_auxiliary_route']('vision') is None


def test_unavailable_strict_vision_never_calls_auto():
    ns,_=runtime();calls=[]
    ns['AuxiliaryClientUnavailable']=type('AuxiliaryClientUnavailable',(RuntimeError,),{})
    ns['resolve_vision_provider_client']=lambda **kw:(calls.append(kw) or ('nous',None,None))
    token=ns['set_gbox_job_auxiliary_routes'](policy())
    with pytest.raises(ns['AuxiliaryClientUnavailable'],match='provider=nous'):
        ns['_resolve_call_client']('vision',provider='nous',model='anthropic/claude-opus-5.5',
            base_url=None,api_key=None,resolved_provider='nous',resolved_model='anthropic/claude-opus-5.5',
            resolved_base_url=None,resolved_api_key=None,resolved_api_mode=None,main_runtime={},async_mode=True)
    assert len(calls)==1 and calls[0]['provider']=='nous'
    ns['reset_gbox_job_auxiliary_routes'](token)
    calls.clear()
    with pytest.raises(ns['AuxiliaryClientUnavailable']):
        ns['_resolve_call_client']('vision',provider='nous',model='anthropic/claude-opus-5.5',
            base_url=None,api_key=None,resolved_provider='nous',resolved_model='anthropic/claude-opus-5.5',
            resolved_base_url=None,resolved_api_key=None,resolved_api_mode=None,main_runtime={},async_mode=True)
    assert [c['provider'] for c in calls]==['nous','auto']


@pytest.mark.parametrize('actual_provider,actual_model',[('openrouter','anthropic/claude-opus-5.5'),('nous','other-model')])
def test_mismatched_resolved_provider_or_model_rejected_before_request(actual_provider,actual_model):
    ns,_=runtime();ns['set_gbox_job_auxiliary_routes'](policy())
    ns['resolve_vision_provider_client']=lambda **kw:(actual_provider,object(),actual_model)
    with pytest.raises(RuntimeError,match='violates strict job'):
        ns['_resolve_call_client']('vision',provider='nous',model='anthropic/claude-opus-5.5',
            base_url=None,api_key=None,resolved_provider='nous',resolved_model='anthropic/claude-opus-5.5',
            resolved_base_url=None,resolved_api_key=None,resolved_api_mode=None,main_runtime={},async_mode=False)


@pytest.mark.parametrize('async_mode',[False,True])
def test_matching_client_keeps_exact_enforced_route(async_mode):
    ns,_=runtime();ns['set_gbox_job_auxiliary_routes'](policy());client=object()
    ns['resolve_vision_provider_client']=lambda **kw:('nous',client,'anthropic/claude-opus-5.5')
    ns['_ResolvedAuxRoute']=lambda *a:a
    assert ns['_resolve_call_client']('vision',provider='nous',model='anthropic/claude-opus-5.5',
        base_url=None,api_key=None,resolved_provider='nous',resolved_model='anthropic/claude-opus-5.5',
        resolved_base_url=None,resolved_api_key=None,resolved_api_mode=None,main_runtime={},async_mode=async_mode)==(
            client,'anthropic/claude-opus-5.5','nous','nous')


@pytest.mark.parametrize('error',[RuntimeError('HTTP 402 credits exhausted'),RuntimeError('HTTP 429 quota'),
                                TimeoutError('timeout'),ConnectionError('connection')])
def test_strict_capacity_ladder_has_no_cross_provider_candidate(error):
    ns,_=runtime();ns['set_gbox_job_auxiliary_routes'](policy())
    def forbidden(*args,**kwargs):raise AssertionError('Cross-provider fallback attempted')
    ns['_try_configured_fallback_chain']=forbidden
    ns['_try_main_agent_model_fallback']=forbidden
    route=SimpleNamespace(task='vision')
    assert list(ns['_ladder_provider_fallback'](error,route))==[]


def test_strict_model_not_found_does_not_heal_to_another_model():
    ns,_=runtime();ns['set_gbox_job_auxiliary_routes'](policy())
    ns['_is_model_not_found_error']=lambda e:True
    ns['_is_payment_error']=lambda e:False
    ns['_is_auth_error']=lambda e:False
    ns['_refresh_nous_recommended_model']=lambda **kw:pytest.fail('Pinned model replaced with recommendation')
    error=RuntimeError('unknown model')
    gen=ns['_ladder_nous_rungs'](error,SimpleNamespace(client=object(),task='vision',tag=''),{},True)
    with pytest.raises(StopIteration) as result:next(gen)
    assert result.value.value==(None,error)


@pytest.mark.parametrize('provider',[None,'nous'])
def test_primary_and_same_provider_retry_account_to_strict_provider(monkeypatch,provider):
    ns,_=runtime();ns['set_gbox_job_auxiliary_routes'](policy());usage=[]
    module(monkeypatch,'agent.aux_accounting',record_aux_usage=lambda response,task,**kw:usage.append((response.model,task,kw)))
    module(monkeypatch,'agent.transports.chat_completions',is_router_timeout_shim=lambda response:False)
    ns['_RELAY_AUX_CALL_CONTEXT']=contextvars.ContextVar('test_relay_context',default=None)
    ns['_complete_relay_auxiliary_call']=lambda:None
    response=SimpleNamespace(model='anthropic/claude-opus-5.5',choices=[SimpleNamespace(message=SimpleNamespace(content='ok'))])
    assert ns['_validate_llm_response'](response,'vision',provider=provider) is response
    assert usage==[('anthropic/claude-opus-5.5','vision',{'provider':'nous','base_url':None})]
    with pytest.raises(RuntimeError,match='response route violates'):
        ns['_validate_llm_response'](response,'vision',provider='openrouter')
    assert len(usage)==1


def test_strict_prepare_overwrites_conflicting_call_arguments_before_client_build():
    ns,_=runtime();ns['set_gbox_job_auxiliary_routes'](policy());seen=[]
    ns['_get_task_extra_body']=lambda task:{}
    ns['_resolve_call_client']=lambda task,**kw:(seen.append(kw) or (SimpleNamespace(base_url='https://nous.example'),'anthropic/claude-opus-5.5','nous','nous'))
    ns['_effective_aux_timeout']=lambda task,timeout:30
    ns['CodexAuxiliaryClient']=type('CodexAuxiliaryClient',(),{})
    ns['AsyncCodexAuxiliaryClient']=type('AsyncCodexAuxiliaryClient',(),{})
    ns['_set_relay_auxiliary_route']=lambda *a:None
    ns['_record_route_info']=lambda *a:None
    ns['_fallback_provider_from_label']=lambda x:x
    ns['_build_call_kwargs']=lambda *a,**kw:{'messages':a[2]}
    ns['_is_anthropic_compat_endpoint']=lambda *a:False
    ns['_PreparedAuxRequest']=lambda *a:a
    result=ns['_prepare_aux_request']('vision',provider='openrouter',model='wrong',base_url='https://wrong.example',
        api_key='test-wrong-key',main_runtime={},messages=[],temperature=None,max_tokens=None,tools=None,
        timeout=None,extra_body=None,reasoning_config=None,extra_headers=None,api_mode='wrong',route_info=None,async_mode=True)
    assert result[0].base_url=='https://nous.example'
    assert seen[0]['provider']=='nous' and seen[0]['model']=='anthropic/claude-opus-5.5'
    assert all(seen[0][k] is None for k in ('base_url','api_key','resolved_base_url','resolved_api_key','resolved_api_mode'))


@pytest.mark.parametrize('fail_construction',[False,True])
def test_real_cron_context_binding_worker_propagation_and_exception_reset(monkeypatch,fail_construction):
    ns,sources=runtime();observed=[]
    aux_module=module(monkeypatch,'agent.auxiliary_client',**{k:ns[k] for k in (
        'set_gbox_job_auxiliary_routes','reset_gbox_job_auxiliary_routes')})
    class Agent:
        def run_conversation(self,*a,**kw):
            observed.append(ns['_resolve_task_provider_model']('vision'))
            return {'final':'ok'}
    module(monkeypatch,'run_agent',AIAgent=Agent)
    module(monkeypatch,'cron.scheduler_detached_worker',defer_teardown_to_running_worker=lambda *a:False)
    class Scope:
        workdir=None;task_id='test-task'
        def __init__(self,*a):pass
        def enter(self):pass
        def exit(self):pass
    scheduler={'__name__':'strict_cron_fixture','logger':logging.getLogger('strict_cron_fixture'),
        'concurrent':__import__('concurrent'),'contextvars':contextvars,'time':time,'threading':threading,
        '_CronRunScope':Scope,'_prepare_job_prompt':lambda *a:(None,'test prompt'),
        '_hermes_now':datetime.now,'_reload_dotenv_and_publish_delivery_target':lambda *a:None,
        '_load_cron_job_config':lambda *a:SimpleNamespace(cfg={},model='anthropic/claude-opus-5.5'),
        '_resolve_cron_agent_setup':lambda *a:SimpleNamespace(blocked=None,model='anthropic/claude-opus-5.5',fallback_notice=None),
        '_open_cron_session_db':lambda *a:None,'_FireAudit':lambda *a:SimpleNamespace(write=lambda *a:None),
        '_cron_inactivity_seconds':lambda:0,'_final_response_from_result':lambda *a:'ok',
        '_run_doc_header':lambda *a:'','_is_cron_silence_response':lambda s:False,
        '_teardown_cron_agent':lambda *a:None}
    def construct(*args,**kwargs):
        assert ns['_gbox_job_auxiliary_route']('vision')['provider']=='nous'
        if fail_construction:raise RuntimeError('test-construction-error')
        return Agent()
    scheduler['_construct_cron_agent']=construct
    module(monkeypatch,'cron.scheduler_diagnostics',format_run_error=lambda e:str(e))
    exec(compile(sources['cron/scheduler.py'],'<frozen-cron-scheduler>','exec'),scheduler)
    outer=ns['set_gbox_job_auxiliary_routes'](policy('openrouter','outer-model'))
    result=scheduler['run_job']({'id':'test-job','name':'test','auxiliary_routes':policy()})
    assert result[0] is not fail_construction
    assert observed==([] if fail_construction else [('nous','anthropic/claude-opus-5.5',None,None,None)])
    assert ns['_gbox_job_auxiliary_route']('vision')['provider']=='openrouter'
    ns['reset_gbox_job_auxiliary_routes'](outer)
    assert ns['_gbox_job_auxiliary_route']('vision') is None


def test_check_only_apply_backup_and_unknown_version_do_not_damage_files(tmp_path):
    sources=fixture_sources()
    for rel,src in sources.items():
        path=tmp_path/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(src,encoding='utf-8')
    initial={rel:(tmp_path/rel).read_bytes() for rel in sources}
    assert patch.apply_runtime(tmp_path)['status']=='compatible'
    assert {rel:(tmp_path/rel).read_bytes() for rel in sources}==initial
    receipt=patch.apply_runtime(tmp_path,apply=True)
    assert receipt['applied'] and receipt['restart_required']
    for rel,path in receipt['backups'].items():assert Path(path).read_bytes()==initial[rel]
    assert patch.apply_runtime(tmp_path,apply=True)['status']=='already_applied'
    path=tmp_path/'cron/scheduler.py';path.write_text(path.read_text(encoding='utf-8').replace('scope.enter()', 'scope.start()'),encoding='utf-8')
    damaged={rel:(tmp_path/rel).read_bytes() for rel in sources}
    with pytest.raises(patch.UnsupportedRuntime):patch.apply_runtime(tmp_path,apply=True)
    assert {rel:(tmp_path/rel).read_bytes() for rel in sources}==damaged


def test_partial_replace_failure_restores_prior_runtime_and_retains_backups(tmp_path,monkeypatch):
    sources=fixture_sources()
    for rel,src in sources.items():
        path=tmp_path/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(src,encoding='utf-8')
    original={rel:(tmp_path/rel).read_bytes() for rel in sources}
    replace=patch.os.replace;calls=[]
    def fail_second(src,dst):
        calls.append(str(dst))
        if len(calls)==2:raise OSError('test replace failure')
        return replace(src,dst)
    monkeypatch.setattr(patch.os,'replace',fail_second)
    with pytest.raises(OSError,match='test replace failure'):patch.apply_runtime(tmp_path,apply=True)
    assert {rel:(tmp_path/rel).read_bytes() for rel in sources}==original
    for rel in sources:
        backups=list((tmp_path/rel).parent.glob('*.gbox-strict-aux-*.bak'))
        assert len(backups)==1 and backups[0].read_bytes()==original[rel]
    assert not list(tmp_path.rglob('.gbox-strict-aux-*'))
