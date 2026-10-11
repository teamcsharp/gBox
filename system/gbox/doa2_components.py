"""Native accessory attachment reconstruction from owned ACS bytes.

Wing matrices follow DOA2LE FUN_8c0d9b32 / FUN_8c0d9c3c. They reproduce
the initialized native wing pose, rather than substituting made-up bind axes.
"""
import math
import struct
import hashlib

import numpy as np

EXE_SHA256='27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1'


def _require(data, offset, size, what):
    if offset < 0 or size < 0 or offset+size > len(data):
        raise ValueError(f'{what} exceeds ACS bounds')


def entries(data):
    """Read the native 8-byte directive list without following invalid pointers."""
    result=[]
    for offset in range(0,len(data),8):
        _require(data,offset,8,'ACS directive')
        mode,pointer=struct.unpack_from('<II',data,offset)
        if mode&255==255:
            return result
        if mode&255 not in (253,254) and pointer not in (0,0xffffffff):
            _require(data,pointer,4,'ACS directive payload')
        result.append({'mode':mode&255,'pointer':pointer,'offset':offset})
    raise ValueError('ACS directive list has no terminator')


def _rotation(axis,angle):
    theta=(int(angle)&0xffff)*math.tau/65536
    c,s=math.cos(theta),math.sin(theta)
    matrix=np.eye(4)
    if axis==0:
        matrix[:3,:3]=[[1,0,0],[0,c,-s],[0,s,c]]
    elif axis==1:
        matrix[:3,:3]=[[c,0,s],[0,1,0],[-s,0,c]]
    else:
        matrix[:3,:3]=[[c,-s,0],[s,c,0],[0,0,1]]
    return matrix


def eye_attachments(executable, native_slot, head_world, *, gaze_angles=None):
    """Reconstruct native eye joints15/16 under head1, from the real rest table.

    FUN_8c07859e loads head matrix+0x40, translates vectors15/16, stores at
    +0x3c0/+0x400, then optionally applies gaze rotation around Y and X.
    Native meshes are two tiny ocular hemispheres, not breast geometry.
    """
    if hashlib.sha256(executable).hexdigest()!=EXE_SHA256:
        raise ValueError('Executable is not the verified DOA2 LE JP build')
    if not isinstance(native_slot,int) or not 0<=native_slot<25:
        raise ValueError('Native slot outside rest table')
    head=np.asarray(head_world,dtype=float)
    if head.shape!=(4,4) or not np.isfinite(head).all():
        raise ValueError('Head world matrix must be finite 4x4')
    address=struct.unpack_from('<I',executable,0x8c1949a0-0x8c010000+native_slot*4)[0]
    if not address:
        raise ValueError('Native fighter has no eye rest vectors')
    offset=address-0x8c010000+15*12
    _require(executable,offset,24,'Eye native rest vectors')
    vectors=np.array(struct.unpack_from('<6f',executable,offset)).reshape(2,3)
    angles=np.zeros((2,2),int) if gaze_angles is None else np.asarray(gaze_angles)
    if angles.shape!=(2,2) or not np.isfinite(angles).all():
        raise ValueError('Eye gaze needs two pairs of finite Y/X native angles')
    world={}
    for side in range(2):
        t=np.eye(4);t[:3,3]=vectors[side]
        world[15+side]=head@t@_rotation(1,angles[side,0])@_rotation(0,angles[side,1])
    return {'world':world,'parent':{15:1,16:1},
            'evidence':[{'consumer':'0x8c07859e','parent_matrix_offset':'0x40',
                         'eye_matrix_offsets':['0x3c0','0x400'],'rest_vectors':vectors.tolist(),
                         'gaze_angles':angles.tolist(),'rest_table_address':hex(address),
                         'anatomy':'left/right eyes; independent gaze joints, not breast components'}]}


def wing_attachments(acs_data, chest_world, *, model_count=None, frame=None):
    """Return all six genuine Tengu matrices and their original CHR models.

    frame=None selects the ACS initializer's independent three-triplet pose.
    A numeric frame selects each of the three recorded native wing channels.
    Left and right share angles, with native X translation and Y/Z angle
    mirroring. Each side is a cumulative three-link chain rooted at chest0.
    """
    chest=np.asarray(chest_world,dtype=float)
    if chest.shape!=(4,4) or not np.isfinite(chest).all():
        raise ValueError('Chest world matrix must be finite 4x4')
    directives=[entry for entry in entries(acs_data) if entry['mode']==5]
    if not directives:
        return {'world':{},'models':{},'parent':{},'evidence':[]}
    if len(directives)!=1:
        raise ValueError('Multiple native wing controllers require separate joint allocations')
    pointer=directives[0]['pointer']
    _require(acs_data,pointer,28,'Wing descriptor')
    count,initial,*channels,model_table,translation_table=struct.unpack_from('<7I',acs_data,pointer)
    _require(acs_data,initial,18,'Wing initial angles')
    _require(acs_data,model_table,12,'Wing model table')
    _require(acs_data,translation_table,36,'Wing translations')
    if frame is None:
        angles=np.array(struct.unpack_from('<9h',acs_data,initial)).reshape(3,3)
    else:
        if not isinstance(frame,int) or not 0<=frame<count:
            raise ValueError('Wing frame exceeds native channel bounds')
        for channel in channels:
            _require(acs_data,channel,6*count,'Wing animation channel')
        angles=np.array([struct.unpack_from('<3h',acs_data,channel+frame*6) for channel in channels])
    model_ids=struct.unpack_from('<6H',acs_data,model_table)
    if model_count is not None and any(model>=model_count for model in model_ids):
        raise ValueError('Wing model ID exceeds CHR model bounds')
    translations=np.array(struct.unpack_from('<9f',acs_data,translation_table)).reshape(3,3)
    if not np.isfinite(translations).all():
        raise ValueError('Wing translations must be finite')
    world,models,parent={},{},{}
    for side in range(2):
        matrix=chest.copy()
        for link in range(3):
            joint=17+side*3+link
            t=np.eye(4);t[:3,3]=translations[link]
            xyz=angles[link].copy()
            if side:
                t[0,3]*=-1
                xyz[1:]*=-1
            matrix=matrix@t@_rotation(2,xyz[2])@_rotation(1,xyz[1])@_rotation(0,xyz[0])
            world[joint]=matrix.copy()
            models[model_ids[side*3+link]]=joint
            parent[joint]=0 if link==0 else joint-1
    return {'world':world,'models':models,'parent':parent,
            'evidence':[{'initializer':'0x8c0d9b32','consumer':'0x8c0d9c3c',
                         'first_body_matrix_offset':'0x440','frame':frame,
                         'angles':angles.tolist(),'translations':translations.tolist(),
                         'models':list(model_ids),'ACS_descriptor_offset':pointer}]}
