"""Same-part-table Sonic topology injection for every Majini model in uEm10/uEm11."""
import sys, zlib, struct, json, importlib.util
sys.path.insert(0,'/home/ehm_eckx/gBox/system')
import numpy as np
from pathlib import Path
from gbox import mt_arc, mt_model, characters, mtf_fit

ROOT=Path('/home/ehm_eckx/gBox_alt/switch/romfs/010018100CD46000/nativeNXx64/ImgNX/Archive')
SONIC=Path('/home/ehm_eckx/gBox_alt/gbox-cache/characters/sonic/sa2_sonic_0.glb')
FORMATS={0x2000D414:28, 0x1580B60C:20, 0x18B0FAA8:20, 0x1C201FC3:24}

def sonic_mesh():
    gl,acc,img,world=characters._load(SONIC)
    skin=max(gl.get('skins') or [], key=lambda s:len(s['joints']))
    joints=list(skin['joints']); ordinal={n:i for i,n in enumerate(joints)}
    P=[];N=[];UV=[];J=[];W=[];T=[]
    for node in gl.get('nodes') or []:
        if 'mesh' not in node: continue
        if 'skin' in node and gl['skins'][node['skin']] is not skin: continue
        for prim in gl['meshes'][node['mesh']]['primitives']:
            a=prim['attributes']
            if 'POSITION' not in a: continue
            p=acc(a['POSITION']).astype(float); n=acc(a['NORMAL']).astype(float) if 'NORMAL' in a else np.tile([0.,1,0],(len(p),1))
            uv=acc(a['TEXCOORD_0']).astype(float) if 'TEXCOORD_0' in a else np.zeros((len(p),2))
            if 'JOINTS_0' in a and 'WEIGHTS_0' in a:
                j=acc(a['JOINTS_0']).astype(int); w=acc(a['WEIGHTS_0']).astype(float)
                mapped=np.array([[ordinal.get(int(joints[k]),0) for k in row] for row in j],int)
            else:
                mapped=np.zeros((len(p),4),int); w=np.zeros((len(p),4),float); w[:,0]=1
            base=sum(len(x) for x in P); P.append(p); N.append(n); UV.append(uv); J.append(mapped); W.append(w)
            idx=acc(prim['indices']).astype(int).reshape(-1,3) if 'indices' in prim else np.arange(len(p),dtype=int).reshape(-1,3)
            T.append(idx+base)
    return np.concatenate(P),np.concatenate(N),np.concatenate(UV),np.concatenate(J),np.concatenate(W),np.concatenate(T),gl,joints

def inject(raw):
    m=mt_model.parse_mod(raw); h=m.header(); bounds=m.bounds()
    P,N,UV,J,W,T,gl,joints=sonic_mesh()
    src=mtf_fit.glb_roles(gl); roles=m.bone_roles(); tp=m.bone_world()
    mapping=mtf_fit.match(src,roles,tp)
    node_to_bone=dict(mapping)
    scale=roles['height']/max(src['height'],1e-9); ground=bounds['min']['y']; low=src['positions'][src['lowest']][1]
    inv={}
    for i,node in enumerate(joints):
        if node in node_to_bone: inv[i]=node_to_bone[node]
        else:
            pos=np.array(src['positions'].get(node,[0,0,0]))*scale+np.array([0,ground-low*scale,0])
            inv[i]=min(tp,key=lambda p:(p[1]-pos[0])**2+(p[2]-pos[1])**2+(p[3]-pos[2])**2)[0]
    ymin=P[:,1].min(); ymax=P[:,1].max(); s=bounds['max']['y']-bounds['min']['y']
    s=s/max(ymax-ymin,1e-9)
    cx=0.5*(bounds['min']['x']+bounds['max']['x']); cz=0.5*(bounds['min']['z']+bounds['max']['z'])
    pos=(P-np.array([0,ymin,0]))*s+np.array([cx,ground,cz])
    dom=np.array([inv[int(J[k,np.argmax(W[k])])] for k in range(len(P))])
    recs=m.meshes(); order=sorted(range(len(recs)), key=lambda i:(0 if recs[i]['vertex_format']==0x2000D414 else 1 if recs[i]['vertex_format']==0x1580B60C else 2 if recs[i]['vertex_format']==0x18B0FAA8 else 9, -recs[i]['vertex_count']))
    parts=[]; cap=0
    for i in order:
        f=recs[i]['vertex_format']; n=recs[i]['vertex_count']
        if f not in FORMATS or n<3: continue
        parts.append(i); cap+=n
        if cap>=len(P)+512: break
    local={i:[] for i in parts}; lut={i:{} for i in parts}; tri_parts={i:[] for i in parts}; cursor=0
    for tri in T:
        placed=False
        for k in range(len(parts)):
            pi=parts[(cursor+k)%len(parts)]
            new=sum(1 for v in tri if int(v) not in lut[pi])
            if len(local[pi])+new+3<=recs[pi]['vertex_count']:
                cursor=(cursor+k+1)%len(parts); placed=True
                for v in tri:
                    v=int(v)
                    if v not in lut[pi]: lut[pi][v]=len(local[pi]); local[pi].append(v)
                tri_parts[pi].append(tuple(lut[pi][int(v)] for v in tri)); break
        if not placed: break
    out=bytearray(raw); face_at=0
    for pi in parts:
        rec=recs[pi]; n=rec['vertex_count']; stride=rec['vertex_stride']; fmt=rec['vertex_format']
        # vertex_offset is the shared buffer base; vertex_index is this part's first slot in it
        base_off=h['offsets']['vertex_buffer']+rec['vertex_offset']+rec['vertex_index']*stride
        base=raw[base_off:base_off+n*stride]
        verts=[]
        for k in range(n):
            sv=local[pi][k] if k<len(local[pi]) else (local[pi][-1] if local[pi] else None)
            if sv is None: verts.append({'position':(cx,ground,cz),'normal':(0,1,0),'uv':(0,0),'bones':[0],'weights':[1.,0.],'bounds':bounds}); continue
            verts.append({'position':tuple(pos[sv]),'normal':tuple(N[sv]/max(np.linalg.norm(N[sv]),1e-9)),'uv':tuple(UV[sv]),'bones':[int(dom[sv])],'weights':[1.,0.],'bounds':bounds})
        packed=mt_model.pack_vertices(verts,fmt,stride,base=base); out[base_off:base_off+len(packed)]=packed
        # indices are global inside the shared vertex buffer; face_index is the original global index slot
        vb=rec['vertex_index']; fi=rec['face_index']; ib=bytearray()
        for (a,b,c) in tri_parts[pi]: ib+=struct.pack('<4H',a+vb,b+vb,c+vb,0xFFFF)
        rec_off=h['offsets']['meshes']+pi*56
        struct.pack_into('<I',out,rec_off+0x1c,max(0,len(ib)//2-1))
        out[h['offsets']['index_buffer']+2*fi:h['offsets']['index_buffer']+2*fi+len(ib)]=ib
        face_at+=len(ib)//2
    used=set(parts)
    for pi in range(len(recs)):
        if pi in used: continue
        rec_off=h['offsets']['meshes']+pi*56
        struct.pack_into('<I',out,rec_off+0x18,0); struct.pack_into('<I',out,rec_off+0x1c,0)
    return bytes(out),len(parts),len(T)

def build_arc(name):
    src=(ROOT/name).read_bytes(); arc=mt_arc.parse(src); done=[]
    for i,e in enumerate(arc.entries):
        try: raw=zlib.decompress(e.data)
        except: continue
        if raw[:4]!=mt_model.MOD_MAGIC: continue
        try: m=mt_model.parse_mod(raw)
        except: continue
        if m.variant!='model' or m.header()['vertex_count']<500: continue
        if 'evf' in e.name.lower() or 'em2100' in e.name.lower(): continue
        new,parts,tris=inject(raw)
        e.data=zlib.compress(new,9)[2:-4]; e.size=len(e.data); e.tag=(e.tag & 0xFF000000)|len(new)
        done.append((e.name,len(new),parts,tris))
    out=mt_arc.build(arc); Path('/tmp/'+name+'.sonic').write_bytes(out)
    print(name,'entries',len(done)); [print(' ',d) for d in done]
    return out

if __name__=='__main__':
    for n in sys.argv[1:] or ['uEm10.arc','uEm11.arc']:
        try: build_arc(n)
        except Exception as exc: print('FAIL',n,exc)
