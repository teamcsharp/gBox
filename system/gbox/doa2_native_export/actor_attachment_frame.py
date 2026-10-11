"""Native mode4 initialized controller frame, not an inferred actor pelvis."""
import struct
import numpy as np
try:
    from . import native_components as C
except ImportError:
    import native_components as C


def source_controller_frame(acs_data,world,model_id):
    matches=[]
    for entry in C.entries(acs_data):
        if entry['mode']!=4:continue
        p=entry['pointer'];C._require(acs_data,p,48,'Native mode4 controller')
        parent=acs_data[p];model=struct.unpack_from('<H',acs_data,p+2)[0]
        if model!=model_id:continue
        if parent==15 or parent>=len(world):raise ValueError('Mode4 controller requires verified core parent')
        anchor=np.array(struct.unpack_from('<3f',acs_data,p+4));angles=struct.unpack_from('<3h',acs_data,p+0x10)
        if not np.isfinite(anchor).all():raise ValueError('Mode4 source anchor non-finite')
        translation=np.eye(4);translation[:3,3]=anchor
        matrix=C._affine(world[parent],'Mode4 source parent')@translation@C._rotation(2,angles[2])@C._rotation(1,angles[1])@C._rotation(0,angles[0])
        matches.append({'descriptor':p,'parent':parent,'model':model,'world':matrix,
                        'anchor':anchor.tolist(),'angles':list(angles),'scale':1,
                        'initializer':'0x8c0d9370 sets runtime+0x2c=1',
                        'consumer':'0x8c0d93e0 loads native parent, translates, rotates Z/Y/X, scales',
                        'root_writer':'0x8c0d99f4 invokes0x8c137320 ->0x8c2a73c8',
                        'draw':'native mode4 controller draws model before later root-grid writeback; freeze uses generated next draw'})
    if len(matches)!=1:raise ValueError('Actor grid needs exactly one matching verified mode4 controller')
    return matches[0]


def source_held_prop_frames(acs_data,world):
    """Native attached props that publish the actor-frame matrix before chains.

    Initializer0x8c0d7f82 sets state1 and copies source+2 to runtime+3.
    At0x8c0d9012, attached consumer0x8c0d8160 calls matrix-save0x8c137320
    with destination0x8c2a73c8, then writes valid-byte0x8c2a8854=1.
    These are authored prop frames; neither eye15 nor the pelvis is substituted.
    """
    result=[]
    for entry in C.entries(acs_data):
        if entry['mode']!=0:continue
        p=entry['pointer'];C._require(acs_data,p,48,'Native held-prop controller')
        kind,parent,flag,_=struct.unpack_from('<4B',acs_data,p)
        if not flag or kind==3:continue
        if parent==15 or parent>=len(world):
            raise ValueError('Held-prop actor frame requires a verified core parent')
        attached=C.accessory_attachments(acs_data,world,descriptor_offsets={p})
        if len(attached['instances'])!=1:raise ValueError('Held-prop actor frame must draw once')
        instance=attached['instances'][0]
        result.append({'descriptor':p,'parent':parent,'model':instance['model'],
                       'world':instance['world'],'kind':kind,'root_flag':flag,
                       'initializer':'0x8c0d7f82: runtime state1; source+2 -> runtime+3',
                       'consumer':'0x8c0d8160 attached-state branch',
                       'root_writer':'0x8c0d9012 ->0x8c137320 ->0x8c2a73c8; valid-byte0x8c2a8854=1',
                       'scope':'native initialized attached frame; combat prop transitions are not simulated'})
    return result
