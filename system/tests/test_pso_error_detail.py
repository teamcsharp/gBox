import httpx
import pytest
from gbox import pso_campaign as P


@pytest.mark.parametrize('body', [{'error':'prompt too long\n'+'x'*1000}, {'other':'private-body'},
                                 ['not','an','object'], 'invalid json'])
def test_provider_error_is_bounded_actionable_and_never_retried(body):
    calls=[]
    def handler(request):
        calls.append(request)
        if isinstance(body, str): return httpx.Response(400, text=body)
        return httpx.Response(400, json=body)
    planner=P.Planner.__new__(P.Planner)
    planner.model='fixture';planner.ollama=True;planner.native_url='http://local'
    planner.api=httpx.Client(base_url='http://local',transport=httpx.MockTransport(handler))
    planner.native_settings=lambda deadline: ({}, {}, True)
    try:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            planner(b'private-image', {'private':'prompt'})
        text=str(caught.value)
        assert text.startswith('PSO route planner HTTP 400: ')
        assert len(text)<=530 and '\n' not in text
        assert 'private' not in text and len(calls)==1
        assert caught.value.response.status_code==400
        if isinstance(body,dict) and 'error' in body: assert 'prompt too long' in text
    finally: planner.close()


def test_redirect_remains_a_failure_without_parsing_as_a_plan():
    planner=P.Planner.__new__(P.Planner)
    planner.model='fixture';planner.ollama=True;planner.native_url='http://local'
    planner.api=httpx.Client(base_url='http://local',transport=httpx.MockTransport(
        lambda request:httpx.Response(302,headers={'location':'http://elsewhere'})))
    planner.native_settings=lambda deadline: ({}, {}, True)
    try:
        with pytest.raises(httpx.HTTPStatusError): planner(b'image', {})
    finally: planner.close()
