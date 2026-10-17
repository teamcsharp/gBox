"""Exact-source RE5 PS3 body anchors verified by controlled offline skin poses.

Native joint numbers differ between Chris and Sheva. These are literal measured
identities, not an animation-ID heuristic for other characters or edited files.
They establish body regions for offline fitting, not gameplay compatibility.
"""
from .re5ps3_arc import sha

ROLE_VERSION = 1
CHRIS_MODEL = 'd7ceb6b055b3854a27975f1609f758cd8e281611149e8fe0a96f53ea984776e6'
SHEVA_MODEL = '99fe7f291a80c32be3440028c9eb7bbf2bb8ec565fea68473ca49766604a8dbb'
ANIMATION_IDS = {
    'hip': 15, 'chest': 2, 'neck': 3, 'head': 4,
    'r_clav': 5, 'r_upper': 6, 'r_fore': 7, 'r_hand': 9,
    'l_clav': 10, 'l_upper': 11, 'l_fore': 12, 'l_hand': 14,
    'r_thigh': 16, 'r_shin': 17, 'r_foot': 18,
    'l_thigh': 20, 'l_shin': 21, 'l_foot': 22,
}
NATIVE_ROLES = {
    CHRIS_MODEL: {
        'hip': 111, 'chest': 2, 'neck': 3, 'head': 4,
        'r_clav': 45, 'r_upper': 46, 'r_fore': 50, 'r_hand': 54,
        'l_clav': 75, 'l_upper': 77, 'l_fore': 79, 'l_hand': 81,
        'r_thigh': 112, 'r_shin': 113, 'r_foot': 114,
        'l_thigh': 117, 'l_shin': 119, 'l_foot': 120,
    },
    SHEVA_MODEL: {
        'hip': 1, 'chest': 21, 'neck': 22, 'head': 23,
        'r_clav': 78, 'r_upper': 79, 'r_fore': 85, 'r_hand': 88,
        'l_clav': 107, 'l_upper': 108, 'l_fore': 112, 'l_hand': 115,
        'r_thigh': 2, 'r_shin': 3, 'r_foot': 4,
        'l_thigh': 8, 'l_shin': 9, 'l_foot': 10,
    },
}


def role_evidence(model):
    """Return verified mappings only for one of the two original native MODs."""
    digest = sha(model.data)
    roles = NATIVE_ROLES.get(digest)
    if roles is None:
        return None
    if any(model.anim_map[joint] != ANIMATION_IDS[role] for role, joint in roles.items()):
        raise ValueError('native role mapping differs from verified source')
    return {
        'version': ROLE_VERSION, 'source_model_sha256': digest,
        'scope': 'offline controlled skin/body anchors only',
        'method': 'Blender 4.0.2 +35 cm world-X translation; independent native descendant-weight readback',
        'position_tolerance_m': .00005,
        'roles': {role: f'j{joint:03d}' for role, joint in roles.items()},
        'native_joint_ids': dict(roles), 'native_animation_ids': dict(ANIMATION_IDS),
        'animation_compatibility_verified': False, 'gameplay_verified': False,
    }
