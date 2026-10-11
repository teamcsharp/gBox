"""Native NL1 strip encoder preserving oriented triangle topology.

Material/global normalization uses the existing verified triangle encoder.
Only the polygon stream changes to the original native0x71 strip grammar.
GPU acceptance is deliberately separate from source-format roundtrip tests.
"""
from __future__ import annotations
import collections
import struct
from gbox import doa2_geometry as G
_TRIANGLE_ENCODER=G.encode_model


def _cyclic(face):
    a,b,c=face
    return min((a,b,c),(b,c,a),(c,a,b))


def _strip_faces(vertices):
    result=[]
    for k in range(len(vertices)-2):
        a,b,c=vertices[k:k+3]
        result.append((b,a,c) if k&1 else (a,b,c))
    return result


def stripify(triangles,*,preserve_order=False):
    """Greedy edge-adjacent strips; retain duplicates, seams and face winding."""
    faces=[tuple(face) for face in triangles]
    if any(len(face)!=3 or any(not isinstance(i,int) for i in face) for face in faces):
        raise ValueError('strip topology requires integer triangle triples')
    edges=collections.defaultdict(list)
    for index,(a,b,c) in enumerate(faces):
        if len({a,b,c})<3:continue
        for edge,other in (((a,b),c),((b,c),a),((c,a),b)):
            edges[edge].append((index,other))
    pending=set(range(len(faces)))
    strips=[]
    while pending:
        seed=min(pending)
        face=faces[seed]
        if len(set(face))<3:
            pending.remove(seed);strips.append(list(face));continue
        trials=[]
        for rotation in range(3):
            seq=list(face[rotation:]+face[:rotation]);used={seed}
            while True:
                odd=(len(seq)-2)&1
                edge=(seq[-1],seq[-2]) if odd else (seq[-2],seq[-1])
                candidates=[(i,v) for i,v in edges.get(edge,()) if i in pending and i not in used]
                if preserve_order:
                    following=seed+len(used)
                    candidates=[item for item in candidates if item[0]==following]
                if not candidates:break
                def score(candidate):
                    index,vertex=candidate
                    following=(seq[-1],vertex) if odd else (vertex,seq[-1])
                    onward=sum(i in pending and i not in used and i!=index for i,_ in edges.get(following,()))
                    return (onward==0,onward,index,vertex)
                index,vertex=min(candidates,key=score)
                used.add(index);seq.append(vertex)
            trials.append((seq,used))
        seq,used=min(trials,key=lambda result:(-len(result[1]),tuple(result[0])))
        pending.difference_update(used);strips.append(seq)
    expected=collections.Counter(_cyclic(face) for face in faces)
    actual=collections.Counter(_cyclic(face) for strip in strips for face in _strip_faces(strip))
    if actual!=expected:
        raise AssertionError('strip conversion changed oriented triangle multiplicity')
    if preserve_order and [_cyclic(face) for strip in strips for face in _strip_faces(strip)]!=list(map(_cyclic,faces)):
        raise AssertionError('ordered strip conversion reordered transparent faces')
    return strips


def _raw(vertex):
    value=bytearray(struct.pack('<8f',*vertex))
    for offset in (0,28):
        struct.pack_into('<I',value,offset,struct.unpack_from('<I',value,offset)[0]|1)
    return bytes(value)


def encode_model(template,meshes,*,references=True):
    """Same caller contract as G.encode_model, emitting native strip groups."""
    meshes=[mesh for mesh in meshes if mesh['triangles']]
    baseline=_TRIANGLE_ENCODER(template,meshes,references=references)
    out=bytearray(baseline[:24]);cursor=24;logical_total=0
    for mesh in meshes:
        header=bytearray(baseline[cursor:cursor+80])
        cursor+=80+struct.unpack_from('<I',header,76)[0]
        # PVR translucent list2 requires retaining its original face order.
        translucent=(struct.unpack_from('<I',header)[0]>>24)&7==2
        strips=stripify(mesh['triangles'],preserve_order=translucent)
        stream=bytearray();seen={};dma_vertex=0
        for strip in strips:
            stream.extend(struct.pack('<2I',0x51|(0x20 if references else 0),len(strip)))
            # NOT_GP remains0: each group emits a32-byte global packet. A
            # constant first-group intensity packet prefix cancels in deltas.
            dma_vertex+=32
            for index in strip:
                raw=_raw(mesh['vertices'][index])
                previous=seen.get(raw) if references else None
                if previous is None or dma_vertex-previous[1]>0xfffff:
                    seen[raw]=(len(stream),dma_vertex);stream.extend(raw)
                else:
                    position,target_dma=previous
                    stream.extend(struct.pack('<Ii',0x60000000-(dma_vertex-target_dma),position-(len(stream)+8)))
                dma_vertex+=32;logical_total+=1
        struct.pack_into('<I',header,76,len(stream))
        out.extend(header);out.extend(stream)
    out.extend(struct.pack('<2I',0,logical_total))
    return bytes(out)
