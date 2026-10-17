from pathlib import Path
from gbox.gamepads import bind_savemgo_xinput


def profile(tmp_path, handler='SDL', device='DualSense Wireless Controller 1'):
    path=tmp_path/'config/input_configs/global/Default.yml'
    path.parent.mkdir(parents=True)
    path.write_bytes((f'Player 1 Input:\r\n  Handler: {handler}\r\n  Device: {device}\r\n  Config:\r\n'
        '    Square: West\r\n    Cross: South\r\n    Circle: East\r\n    Triangle: North\r\n'
        '    L1: LB\r\n    R2: RT\r\n    Stick Deadzone: 37\r\n'
        'Player 2 Input:\r\n  Handler: SDL\r\n  Device: Personal second pad\r\n').encode())
    return path


def test_connected_xinput_replaces_stock_device_and_preserves_settings(tmp_path):
    p=profile(tmp_path); before=p.read_bytes()
    assert bind_savemgo_xinput(tmp_path,[2])
    after=p.read_bytes()
    assert b'Device: "XInput Pad #3"' in after
    assert b'Cross: A\r\n' in after and b'Square: X\r\n' in after
    assert b'Stick Deadzone: 37\r\n' in after
    assert after.split(b'Player 2 Input:')[1]==before.split(b'Player 2 Input:')[1]
    assert p.with_name(p.name+'.gbox-original').read_bytes()==before
    assert not bind_savemgo_xinput(tmp_path,[0])
    assert p.read_bytes()==after


def test_no_device_and_custom_mapping_unchanged(tmp_path):
    p=profile(tmp_path,device='My custom pad'); before=p.read_bytes()
    assert not bind_savemgo_xinput(tmp_path,[0])
    assert not bind_savemgo_xinput(tmp_path,[])
    assert p.read_bytes()==before
    assert not p.with_name(p.name+'.gbox-original').exists()
