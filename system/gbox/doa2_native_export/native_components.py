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


def _affine(matrix, name):
    matrix=np.asarray(matrix,dtype=float)
    if matrix.shape!=(4,4) or not np.isfinite(matrix).all() or not np.allclose(matrix[3],[0,0,0,1]):
        raise ValueError(f'{name} must be a finite affine 4x4 matrix')
    if abs(np.linalg.det(matrix[:3,:3]))<1e-9:
        raise ValueError(f'{name} must be invertible')
    return matrix


def _unit(vector, what):
    norm=np.linalg.norm(vector)
    if not np.isfinite(norm) or norm<1e-10:
        raise ValueError(f'{what} has a singular direction')
    return vector/norm


def _chain_basis(direction):
    """Exact basis construction used by native draw style1 at8c0d5bf8."""
    direction=np.asarray(direction,dtype=float)
    y=_unit(-direction,'Native chain Y axis')
    z=_unit(np.array([0,direction[2],-direction[1]]),'Native chain Z axis')
    matrix=np.eye(4)
    matrix[:3,:3]=np.column_stack((np.cross(y,z),y,z))
    return matrix


def accessory_attachments(acs_data, world, *, model_count=None, chain_displacements=None,
                          base_world=None,descriptor_offsets=None):
    """Decode native held props and repeated mesh chains without deduplicating.

    Observed ``chain_displacements`` maps ACS descriptor offsets to count x3
    world-space vectors from native scratch records+0xc (each record0x30 bytes).
    Their mesh attachment transform exactly follows8c0d5a6c. Without observed
    records the configured initialization direction follows native gravity and
    length rules, but does not claim stage/body collision simulation. Vertex
    deformation and grid descriptors are explicitly reported, not fabricated.
    Special parent15 means actor world transform, not eye joint15.
    """
    world=np.asarray(world,dtype=float)
    if world.ndim!=3 or world.shape[1:]!=(4,4) or not len(world):
        raise ValueError('Accessory world matrices require an Nx4x4 pose')
    for matrix in world:_affine(matrix,'Accessory world')
    observed={} if chain_displacements is None else chain_displacements
    instances=[];deformations=[];unsupported=[];hidden=[];evidence=[]
    def parent_matrix(parent):
        if parent==15:
            if base_world is None:
                raise ValueError('Native accessory parent15 requires actor base_world')
            return _affine(base_world,'Actor base world')
        if parent>=len(world):raise ValueError('Accessory parent exceeds native joint bounds')
        return world[parent]
    def valid_model(model):
        if model_count is not None and model>=model_count:
            raise ValueError('Accessory model ID exceeds CHR model bounds')
    directives=entries(acs_data)
    if descriptor_offsets is not None:
        selected=set(descriptor_offsets)
        if selected-{entry['pointer'] for entry in directives}:
            raise ValueError('Selected accessory descriptor is absent')
        directives=[entry for entry in directives if entry['pointer'] in selected]
    for entry in directives:
        mode,p=entry['mode'],entry['pointer']
        if mode==0:
            _require(acs_data,p,48,'Held-prop descriptor')
            kind,parent,flags0,flags1=struct.unpack_from('<4B',acs_data,p)
            model=struct.unpack_from('<H',acs_data,p+0x2e)[0]
            valid_model(model)
            if kind==3:
                hidden.append({'descriptor':p,'mode':0,'model':model,'reason':'native kind3 immediately returns without drawing'})
                continue
            anchor=np.array(struct.unpack_from('<3f',acs_data,p+0x1c))
            if not np.isfinite(anchor).all():raise ValueError('Held-prop anchor must be finite')
            xyz=struct.unpack_from('<3h',acs_data,p+0x28)
            t=np.eye(4);t[:3,3]=anchor
            matrix=parent_matrix(parent)@t@_rotation(2,xyz[2])@_rotation(1,xyz[1])@_rotation(0,xyz[0])
            instances.append({'descriptor':p,'link':0,'mode':0,'kind':kind,'model':model,
                              'parent':parent,'world':matrix,'pose':'native initialized attached state1'})
            evidence.append({'descriptor':p,'initializer':'0x8c0d7f82','consumer':'0x8c0d8160',
                             'anchor':anchor.tolist(),'angles':list(xyz),'model':model})
        elif mode==1:
            _require(acs_data,p,96,'Chain descriptor')
            count,parent,flags,style=struct.unpack_from('<4B',acs_data,p)
            floats=np.array(struct.unpack_from('<14f',acs_data,p+4))
            if not np.isfinite(floats).all():raise ValueError('Chain controls must be finite')
            length,gravity=floats[:2];anchor=floats[4:7];direction=floats[7:10]
            carry=floats[10]
            if length<0:raise ValueError('Native chain length cannot be negative')
            table=struct.unpack_from('<I',acs_data,p+0x44)[0]
            _require(acs_data,table,2,'Chain model table')
            first=struct.unpack_from('<H',acs_data,table)[0]
            if first in (0xffff,0xfffe):
                _require(acs_data,table,4,'Chain deformation target')
                model=struct.unpack_from('<H',acs_data,table+2)[0]&0x7fff;valid_model(model)
                deformations.append({'descriptor':p,'mode':1,'count':count,'parent':parent,
                                     'model':model,'marker':first,'style':style,
                                     'source_pointer':struct.unpack_from('<I',acs_data,p+0x48)[0],
                                     'destination_pointer':struct.unpack_from('<I',acs_data,p+0x4c)[0],
                                     'reason':'native runtime vertex reconstruction needed; original placeholder positions are not exported'})
                continue
            _require(acs_data,table,count*2,'Chain model table')
            ids=struct.unpack_from('<'+str(count)+'H',acs_data,table)
            if style not in (0,1):
                unsupported.append({'descriptor':p,'mode':1,'style':style,'reason':'unverified mesh draw style'})
                continue
            parent_world=parent_matrix(parent)
            matrix=parent_world.copy();matrix[:3,3]=(parent_world@np.r_[anchor,1])[:3]
            if p in observed:
                displacement=np.asarray(observed[p],dtype=float)
                if displacement.shape!=(count,3) or not np.isfinite(displacement).all():
                    raise ValueError('Observed chain displacement count or shape is invalid')
                local=displacement@np.linalg.inv(parent_world[:3,:3]).T
                pose='native observed world displacement; exact attachment transforms'
            else:
                # FUN8c0d4e92: subtract gravity from worldY, normalize to segment
                # length, then scale previous configured direction by carry.
                current=parent_world[:3,:3]@direction
                displacements=[]
                for link in range(count):
                    candidate=current.copy();candidate[1]-=gravity
                    displacement=_unit(candidate,'Configured chain initialization')*length if length else np.zeros(3)
                    displacements.append(displacement);current=current*carry
                local=np.array(displacements).reshape(count,3)@np.linalg.inv(parent_world[:3,:3]).T
                pose='configured native gravity/length initialization; stage/body collision is not simulated'
            for link,raw_id in enumerate(ids):
                model=raw_id&0x7fff;valid_model(model)
                matrix[:3,:3]=parent_world[:3,:3]
                if style==1:matrix=matrix@_chain_basis(local[link])
                instances.append({'descriptor':p,'link':link,'mode':1,'style':style,'model':model,
                                  'parent':parent,'world':matrix.copy(),'pose':pose,
                                  'native_projected_uv_flag':bool(raw_id&0x8000)})
                matrix[:3,3]-=length*matrix[:3,1]
            evidence.append({'descriptor':p,'initializer':'0x8c0d4dea/0x8c0d4e92','consumer':'0x8c0d5a6c',
                             'models':list(ids),'parent':parent,'style':style,'pose':pose,
                             'anchor':anchor.tolist(),'local_displacements':local.tolist()})
        elif mode==2:
            unsupported.append({'descriptor':p,'mode':2,'reason':'native cloth grid initializer/deformation requires reconstruction'})
        elif mode not in (5,253,254):
            unsupported.append({'descriptor':p,'mode':mode,'reason':'native special accessory controller requires separate reconstruction'})
    return {'instances':instances,'deformations':deformations,'unsupported':unsupported,
            'hidden':hidden,'evidence':evidence}


def assemble_instances(chr_data, bin_data, instances):
    """Bake verified native ACS mesh instances, rigidly attached to their parent.

    The result preserves duplicate geometry/UVs/materials for every link. The
    donor's frozen accessory pose follows the parent during later retargeting;
    native accessory physics is not asserted to be retained in the donor GLTF.
    """
    try:
        from gbox import doa2_geometry as G,doa2_textures as T
    except ImportError:
        import doa2_geometry as G,doa2_textures as T
    archive=G.decode_chr(chr_data);directory=T.descriptors(chr_data,bin_data)
    textures={};primitives=[]
    for instance in instances:
        model,joint=instance['model'],instance['parent']
        if not 0<=model<len(archive['models']):raise ValueError('Accessory instance model exceeds CHR bounds')
        if joint==15:raise ValueError('Actor-world accessory needs explicit donor skeleton root mapping')
        matrix=_affine(instance['world'],'Accessory instance world')
        normal_matrix=np.linalg.inv(matrix[:3,:3]).T
        for mesh_index,mesh in enumerate(archive['models'][model]['meshes']):
            attrs=np.array(mesh['vertices'])
            if not len(attrs):continue
            normals=attrs[:,3:6]@normal_matrix.T
            normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-12)
            slot=mesh['texture_id'];tex=None
            if slot>=0:
                if slot>=len(directory):raise ValueError('Accessory instance references missing native texture')
                if slot not in textures:textures[slot]=np.asarray(T.decode(directory[slot],bin_data),dtype=np.uint8)
                tex=textures[slot]
            color=struct.unpack_from('<4f',mesh['header'],44)
            rgba=tuple(int(round(max(0,min(1,value))*255)) for value in (*color[1:],color[0]))
            mode2=struct.unpack_from('<I',mesh['header'],8)[0]
            wrap=tuple(33071 if mode2&(1<<clamp) else 33648 if mode2&(1<<mirror) else 10497
                       for clamp,mirror in ((16,18),(15,17)))
            count=len(attrs);joints=np.zeros((count,4),np.uint16);joints[:,0]=joint
            weights=np.zeros((count,4),np.float32);weights[:,0]=1
            primitives.append({'name':f'ACS{instance["descriptor"]}_link{instance["link"]}_model{model}_mesh{mesh_index}',
                               'native_model':model,'native_texture':slot,
                               'pos':attrs[:,:3]@matrix[:3,:3].T+matrix[:3,3],
                               'nrm':normals,'uv':attrs[:,6:8].copy(),'tris':np.array(mesh['triangles'],dtype=np.int32),
                               'J':joints,'W':weights,'owner':joints[:,0],'tex':tex,'color':rgba,'prop':False,'wrap':wrap})
    return {'prims':primitives,'report':{'native_instances':len(instances),'triangles':sum(len(p['tris']) for p in primitives),
                                      'vertices':sum(len(p['pos']) for p in primitives),'textures':len(textures),
                                      'export_physics':'accessory pose baked and rigidly follows original parent; native physics is not preserved'}}
