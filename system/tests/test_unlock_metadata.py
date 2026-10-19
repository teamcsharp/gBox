import asyncio

import pytest

from gbox import unlock_metadata as M
from gbox.mcp_server import CONVENIENCE

RID = 'a' * 16


def invoke(args, context=None):
    calls = []
    async def get(path):
        calls.append(('get', path))
        if path.startswith('/api/requests/'):
            return {'status':'open', 'context': context if context is not None else
                    {'custom_build_unlocks':'g', 'favorite_default':True}}
        return {'fixture': path}
    async def post(path, body):
        calls.append(('post', path, body))
        return {'accepted':True}
    result = asyncio.run(M.run({'game_id':'g','request_id':RID,**args}, get, post))
    return result, calls


@pytest.mark.parametrize('op,path', [('native_profile','/api/games/g/live-controls/profile'),
                                    ('unlock_profile','/api/custom-build-unlocks/g/profile'),
                                    ('verify','/api/custom-build-unlocks/g/%40original/verify')])
def test_exact_request_can_publish_only_typed_metadata(op,path):
    out,calls=invoke({'op':op,'body':{'evidence':'fixture'}})
    assert out['accepted'] and calls[-1]==('post',path,{'evidence':'fixture'})
    assert all('/launch' not in c[1] and '/run' not in c[1] and '/jobs' not in c[1] for c in calls)


@pytest.mark.parametrize('args,context', [({'op':'launch'},None), ({'op':'run'},None),
    ({'op':'manifest','build':'../../elsewhere'},None), ({'game_id':'g/other'},None),
    ({'op':'unlock_profile'},{'custom_build_unlocks':'another','favorite_default':True}),
    ({'op':'unlock_profile'},{'custom_build_unlocks':'g','favorite_default':False})])
def test_mutation_launch_traversal_or_wrong_request_scope_is_refused(args,context):
    with pytest.raises(ValueError): invoke(args,context)


def test_status_and_manifest_are_reads_and_mcp_exposes_required_binding():
    out,calls=invoke({'op':'status'})
    assert out['unlocks'] and out['native_controls'] and all(c[0]=='get' for c in calls)
    _,calls=invoke({'op':'manifest'})
    assert calls[-1]==('get','/api/custom-build-unlocks/g/%40original/manifest')
    assert set(CONVENIENCE['favorite_unlocks'][1]['required'])=={'game_id','request_id'}
