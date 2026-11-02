import pytest
from test_pso_recovery import rig, death
from gbox.registry import Unsupported


@pytest.mark.parametrize('fault',['area','actor','death','unsupported','read_failure'])
def test_pre_call_native_drift_forces_caller_to_reobserve_without_input_or_native_publication(rig,fault):
    r=rig;death(r)
    if fault=='area':r.ad.floor=2
    elif fault=='actor':r.ad.pointers[1]+=0x1000
    elif fault=='death':r.ad.hp[1]=0
    else:
        original=r.recovery.factory
        def factory(*args,**kwargs):
            native=original(*args,**kwargs)
            def failed_check():raise (Unsupported('Native guard changed') if fault=='unsupported' else OSError('Native read failed'))
            native.check=failed_check
            return native
        r.recovery.factory=factory
    assert r.recovery.tick(r.state,menu_allowed=True) is True
    assert not r.ad.calls and not r.ad.equips
    assert not r.recovery.pending
    assert r.recovery.tick(r.state,menu_allowed=True) is False
