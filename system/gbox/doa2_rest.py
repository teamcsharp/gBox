"""Read exact LE JP skeleton vectors; this does not invent bind rotations."""
import struct, hashlib

LOAD = 0x8c010000
EXPECTED_SHA256 = '27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1'
REST_TABLE = 0x8c1949a0
ROLE_NAMES = ['chest', 'head', 'pelvis', 'left_foot', 'left_elbow', 'left_hand',
              'left_thigh', 'left_shin', 'left_shoulder', 'right_foot',
              'right_elbow', 'right_hand', 'right_thigh', 'right_shin',
              'right_shoulder', 'left_breast', 'right_breast']
# Edges established by native SUP seam records / head matrix builder. Unknown
# edges remain null instead of being presented as native proof.
VERIFIED_PARENT = {0:2, 1:0, 3:7, 4:8, 5:4, 6:2, 7:6, 8:0,
                   9:13, 10:14, 11:10, 12:2, 13:12, 14:0}

def extract_rest_vectors(data: bytes) -> dict:
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError('Executable is not the verified DOA2 LE JP build')
    pointers = struct.unpack_from('<25I', data, REST_TABLE - LOAD)
    profiles = []
    for fighter_id, address in enumerate(pointers):
        if not address:
            profiles.append({'fighter_id': fighter_id, 'rest_address': None})
            continue
        values = struct.unpack_from('<51f', data, address - LOAD)
        profiles.append({'fighter_id': fighter_id, 'rest_address': hex(address),
                         'local_translations': [list(values[i:i+3]) for i in range(0,51,3)],
                         'roles': ROLE_NAMES, 'verified_parent_edges': VERIFIED_PARENT,
                         'status': 'verified_native_translations; bind_rotations_pending'})
    limb_map = [list(struct.unpack_from('<4I', data, 0x8c19582c - LOAD + i*16)) for i in range(4)]
    return {'exe_sha256': digest, 'table_address': hex(REST_TABLE),
            'body_matrix_buffer': '0x8c237888 + player * 0x5c0',
            'matrix_stride': 64, 'limb_matrix_indices': limb_map,
            'profiles': profiles}

