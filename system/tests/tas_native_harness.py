"""Isolated core-boundary test driver. No window, physical controller, network, or shared saves."""
import ctypes as C
import json
import os
from pathlib import Path
import sys


def run(proxy, core, folder, mode, frames):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    os.environ.update(GBOX_TAS_CORE=str(core), GBOX_TAS_STATUS=str(folder/'status.json'))
    os.environ['GBOX_TAS_RECORD' if mode == 'record' else 'GBOX_TAS_PLAY'] = str(folder/'input.gbt')
    dll = C.CDLL(str(proxy))
    class Game(C.Structure):
        _fields_ = [('path', C.c_char_p), ('data', C.c_void_p), ('size', C.c_size_t), ('meta', C.c_char_p)]
    ENV=C.CFUNCTYPE(C.c_bool,C.c_uint,C.c_void_p)
    INPUT=C.CFUNCTYPE(C.c_int16,C.c_uint,C.c_uint,C.c_uint,C.c_uint)
    @ENV
    def env(cmd, data): return False
    current = 0
    @INPUT
    def inputs(port, device, index, key): return (current*7+port)%251
    dll.retro_set_environment(env); dll.retro_init(); dll.retro_set_input_state(inputs)
    dll.retro_load_game.argtypes=[C.POINTER(Game)]; dll.retro_load_game.restype=C.c_bool
    assert dll.retro_load_game(C.byref(Game(b'fixture.bin',None,0,None)))
    dll.retro_serialize_size.restype=C.c_size_t
    dll.retro_serialize.argtypes=[C.c_void_p,C.c_size_t];dll.retro_serialize.restype=C.c_bool
    dll.retro_unserialize.argtypes=[C.c_void_p,C.c_size_t];dll.retro_unserialize.restype=C.c_bool
    dll.retro_get_memory_data.argtypes=[C.c_uint];dll.retro_get_memory_data.restype=C.c_void_p
    for current in range(frames):
        if mode == 'record':
            if current == 200:
                state=C.create_string_buffer(dll.retro_serialize_size()); assert dll.retro_serialize(state,len(state))
            if 650 <= current < 660:
                assert dll.retro_unserialize(state,len(state))
            if current == 800:
                ram=C.cast(dll.retro_get_memory_data(2),C.POINTER(C.c_ubyte));ram[100] ^= 255
            if current == 1000: dll.retro_reset()
        dll.retro_run()
    ram=C.string_at(dll.retro_get_memory_data(2),2048)
    dll.retro_unload_game(); dll.retro_deinit()
    import hashlib
    return {'native':json.loads((folder/'status.json').read_text()), 'ram_sha256':hashlib.sha256(ram).hexdigest()}


if __name__ == '__main__':
    print(json.dumps(run(*sys.argv[1:5], int(sys.argv[5]))))
