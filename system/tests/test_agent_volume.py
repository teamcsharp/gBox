import sys
from types import SimpleNamespace

from gbox.audio_volume import keep_pc_at_two_percent


def test_agent_use_holds_every_active_output_at_two_percent(monkeypatch):
    levels = [0.7, 0.3]

    class Endpoint:
        def __init__(self, index):
            self.index = index

        def GetMasterVolumeLevelScalar(self):
            return levels[self.index]

        def SetMasterVolumeLevelScalar(self, level, _):
            levels[self.index] = level

    devices = [SimpleNamespace(EndpointVolume=Endpoint(i)) for i in range(2)]
    monkeypatch.setitem(sys.modules, "comtypes", SimpleNamespace(CoInitialize=lambda: None,
                                                                  CoUninitialize=lambda: None))
    monkeypatch.setitem(sys.modules, "pycaw", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", SimpleNamespace(AudioUtilities=SimpleNamespace(
        GetAllDevices=lambda *_: devices)))
    monkeypatch.setitem(sys.modules, "pycaw.constants", SimpleNamespace(
        EDataFlow=SimpleNamespace(eRender=SimpleNamespace(value=0)),
        DEVICE_STATE=SimpleNamespace(ACTIVE=SimpleNamespace(value=1))))
    assert keep_pc_at_two_percent() == 2
    assert levels == [0.02, 0.02]
