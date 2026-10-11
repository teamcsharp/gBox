"""Decode native ACS cloth grids and replay supplied native world-grid writes.

8c0d63ca initializes columns; 8c0d664c produces world rows; 8c0d6162
applies the parent inverse and writes model-relative XYZ plus processed marker.
Supplied poses must carry explicit provenance. No collision state is invented.
"""
import hashlib
import struct

import numpy as np
try:
    from . import native_components as C
except ImportError:
    import native_components as C
try:
    from gbox import doa2_geometry as G
except ImportError:
    import doa2_geometry as G


def _word(data,offset,label):
    C._require(data,offset,4,label)
    return struct.unpack_from('<I',data,offset)[0]


def decode_grids(acs_data,chr_data):
    archive=G.decode_chr(chr_data);grids=[]
    for entry in C.entries(acs_data):
        if entry['mode']!=2:continue
        p=entry['pointer'];C._require(acs_data,p,252,'Cloth grid descriptor')
        kind,parent,draw,model,columns,rows,centre,flags=struct.unpack_from('<8B',acs_data,p)
        if not 0<columns<=16 or not 0<rows<=12:
            raise ValueError('Cloth grid dimensions exceed native descriptor arrays')
        if model>=len(archive['models']):raise ValueError('Cloth grid model exceeds CHR bounds')
        native=archive['models'][model]
        inline={r['offset']-native['offset'] for m in native['meshes'] for r in m['records'] if not r['reference']}
        pointers={off:_word(acs_data,p+off,'Cloth grid pointer') for off in range(0xe0,0xfc,4)}
        source=pointers[0xe0];anchor_start=source;anchors=[]
        for column in range(columns):
            C._require(acs_data,source,12,'Cloth column anchor')
            anchor=np.array(struct.unpack_from('<3f',acs_data,source));source+=12
            anchor_parent=parent
            if flags&1 and anchor[0]==999:
                C._require(acs_data,source,12,'Cloth alternate-parent anchor')
                anchor=np.array(struct.unpack_from('<3f',acs_data,source));source+=12
                anchor_parent=parent+4
            if not np.isfinite(anchor).all():raise ValueError('Cloth anchor is non-finite')
            anchors.append({'parent':anchor_parent,'position':anchor})
        cursor=pointers[0xe4];start=cursor;mappings=[]
        if not cursor:
            mappings=[[[] for row in range(rows)] for column in range(columns)]
        else:
            for column in range(columns):
                groups=[]
                for row in range(rows):
                    word=_word(acs_data,cursor,'Cloth vertex mapping');cursor+=4;offsets=[]
                    if word!=0xffffffff:
                        while True:
                            offset=word&0xfffffffe
                            if offset not in inline or native['offset']+offset+12>native['end_offset']:
                                raise ValueError('Cloth destination is not a complete inline CHR vertex')
                            offsets.append(offset)
                            if not word&1:break
                            word=_word(acs_data,cursor,'Cloth vertex alias');cursor+=4
                            if word==0xffffffff:raise ValueError('Cloth alias cannot end with a skipped vertex')
                    groups.append(offsets)
                mappings.append(groups)
        pin_vertices=[]
        if flags&32:
            C._require(acs_data,pointers[0xf8],columns*4,'Cloth pinned-vertex map')
            pin_vertices=list(struct.unpack_from('<'+str(columns)+'I',acs_data,pointers[0xf8]))
            if any(offset not in inline for offset in pin_vertices):
                raise ValueError('Cloth pinned anchor is not an inline CHR position')
        lengths=np.array(struct.unpack_from('<'+str(rows)+'f',acs_data,p+0x30))
        controls=np.array(struct.unpack_from('<10f',acs_data,p+8))
        speeds=np.array(struct.unpack_from('<'+str(columns)+'f',acs_data,p+0xa0))
        if not np.isfinite(np.r_[lengths,controls,speeds]).all() or (lengths<0).any():
            raise ValueError('Cloth grid controls or row lengths are invalid')
        grids.append({'descriptor':p,'kind':kind,'parent':parent,'draw':draw,'model':model,
                      'columns':columns,'rows':rows,'centre':columns//2 if centre==255 else centre,
                      'flags':flags,'model_offset':native['offset'],'anchors':anchors,'mappings':mappings,
                      'controls':controls,'lengths':lengths,
                      'angles':list(struct.unpack_from('<'+str(columns)+'i',acs_data,p+0x60)),
                      'speeds':speeds,'pin_vertices':pin_vertices,'pointers':pointers,
                      'anchor_bytes':source-anchor_start,'mapping_bytes':cursor-start,
                      'normal_pointers':{hex(off):pointers[off] for off in (0xec,0xf0,0xf4)}})
    return grids


def bake_world_grids(chr_data,acs_data,world,grid_positions,*,pose_evidence,base_world=None,base_evidence=None):
    """Replay exact native positional writeback from supplied columns x(rows+1)x3 WORLD rows."""
    if not pose_evidence:raise ValueError('Cloth grid bake needs explicit native pose provenance')
    world=np.asarray(world,dtype=float)
    if world.ndim!=3 or world.shape[1:]!=(4,4):raise ValueError('Cloth world pose must be Nx4x4')
    for matrix in world:C._affine(matrix,'Cloth joint world')
    output=bytearray(chr_data);owners={};reports=[];instances=[]
    for grid in decode_grids(acs_data,chr_data):
        p,parent=grid['descriptor'],grid['parent']
        if parent==15:
            if base_world is None or not base_evidence:
                raise ValueError('Cloth parent15 requires explicit actor base_world and provenance')
            parent_world=C._affine(base_world,'Actor base world')
        elif parent<len(world):parent_world=world[parent]
        else:raise ValueError('Cloth parent exceeds supplied joint pose')
        if p not in grid_positions:raise ValueError(f'Cloth grid {p} lacks native world rows')
        positions=np.asarray(grid_positions[p],dtype=float)
        shape=(grid['columns'],grid['rows']+1,3)
        if positions.shape!=shape or not np.isfinite(positions).all():
            raise ValueError('Cloth world grid has invalid dimensions or non-finite positions')
        inverse=np.linalg.inv(parent_world)
        local=positions@inverse[:3,:3].T+inverse[:3,3]
        for column in range(grid['columns']):
            for row in range(grid['rows']):
                payload=struct.pack('<3f',*local[column,row+1])
                payload=struct.pack('<I',struct.unpack_from('<I',payload)[0]|1)+payload[4:]
                for offset in grid['mappings'][column][row]:
                    address=grid['model_offset']+offset
                    output[address:address+12]=payload
                    owners[address]={'model':grid['model'],'parent':parent,'descriptor':p,'column':column,'row':row+1}
        if grid['draw']:
            instances.append({'descriptor':p,'link':0,'mode':2,'model':grid['model'],'parent':parent,
                              'world':parent_world.copy(),'chr_data':bytes(output),'pose':pose_evidence})
        reports.append({'descriptor':p,'consumer':'0x8c0d6162','world_generator':'0x8c0d664c',
                        'model':grid['model'],'parent':parent,'columns':grid['columns'],'rows':grid['rows'],
                        'draw':bool(grid['draw']),'writes':sum(len(v) for c in grid['mappings'] for v in c),
                        'normal_pointers':grid['normal_pointers'],'pose_provenance':pose_evidence})
    return {'chr_data':bytes(output),'instances':instances,'vertex_owners':owners,
            'report':{'native_grids':reports,'position_writes':len(owners),
                      'source_chr_sha256':hashlib.sha256(chr_data).hexdigest(),
                      'baked_chr_sha256':hashlib.sha256(output).hexdigest(),
                      'normals':'original normals retained; optional cloth normal recomputation is not yet replayed'}}
