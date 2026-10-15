"""Planar face projection on the original gameplay Mario mesh; title Goddard is a separate target."""
import numpy as np

GAME_IDS=('b7aecee966090bfa','66062703301f4969')
SIZE=(32,64)


def uv(point,projection=None):
    # Verified native joint-3 axes: X is up, +Y is front and Z is horizontal.
    if projection is None:
        from .sprite_faces import Projection
        projection=Projection()
    x,y,z=point
    yaw,pitch=np.deg2rad([projection.yaw,projection.pitch])
    horizontal=z*np.cos(yaw)-y*np.sin(yaw)
    forward=y*np.cos(yaw)+z*np.sin(yaw)
    vertical=x*np.cos(pitch)-forward*np.sin(pitch)
    return (.5+(horizontal-projection.center_x)/projection.width,.5-(vertical-projection.center_y)/projection.height)


def source(rom):
    from . import sm64_mario as M,sm64_writer as W
    model=M.extract(rom,197);parts,mats=W.parts_from_extract(model)
    selected=[]
    for index,(material,triangle) in enumerate(parts[3]):
        m=mats[material];r,g,b=m['diffuse'];points=np.array([p for p,n,t in triangle])
        if r>200 and 100<g<230 and 50<b<180 and points[:,1].mean()>20:
            selected.append(index)
    if not selected:raise ValueError('Original Mario face materials were not identified')
    return model,parts,mats,selected


def atlas(rom):
    from . import sm64_mario as M,sm64_writer as W
    model=M.extract(rom,197);parts,mats=W.parts_from_extract(model)
    for m in mats:
        if tuple(m['diffuse'])==(255,255,255) and m.get('tex') is not None and m['tex'].shape[:2]==(64,32):
            return m['tex'].astype(np.uint8)
    model,parts,mats,selected=source(rom)
    out=np.full((64,32,4),(254,193,121,255),np.uint8);depth=np.full((64,32),-1e9,float)
    for index in selected:
        mi,tri=parts[3][index];m=mats[mi];positions=np.array([p for p,n,u in tri],float)
        p=np.array([uv(v) for v in positions])*np.array(SIZE)
        matrix=np.array([[p[0,0],p[1,0],p[2,0]],[p[0,1],p[1,1],p[2,1]],[1,1,1]],float)
        if abs(np.linalg.det(matrix))<1e-6:continue
        inverse=np.linalg.inv(matrix);tex=m.get('tex')
        for y in range(max(0,int(p[:,1].min())),min(64,int(p[:,1].max())+1)):
            for x in range(max(0,int(p[:,0].min())),min(32,int(p[:,0].max())+1)):
                weights=inverse@np.array([x+.5,y+.5,1])
                if weights.min()<-.001:continue
                z=weights@positions[:,1]
                if z<depth[y,x]:continue
                depth[y,x]=z;color=np.array([*m['diffuse'],255],float)
                if tex is not None:
                    st=weights@np.array([u for p,n,u in tri]);tx=int(st[0]*tex.shape[1])%tex.shape[1];ty=int(st[1]*tex.shape[0])%tex.shape[0]
                    sample=tex[ty,tx].astype(float);a=sample[3]/255;color[:3]=sample[:3]*a+color[:3]*(1-a)
                out[y,x]=np.clip(color,0,255).astype(np.uint8)
    return out


def apply(rom,photo,mapping,photos=None):
    from . import sm64_swap as S,sm64_writer as W
    from .sprite_faces import composite
    S.check_rom(rom);model,parts,mats,selected=source(rom);before=atlas(rom)
    rgb,weight=composite(before,photo,mapping,mapping.rectangles.get('0') or [.08,.04,.92,.96],photos)
    # Match native RGBA16 quantization before showing or injecting the texture.
    a=np.concatenate([np.clip(rgb,0,255).astype(np.uint8),np.full((64,32,1),255,np.uint8)],axis=2)
    a[:,:,:3]=np.round((a[:,:,:3]>>3).astype(float)*255/31).astype(np.uint8)
    mi=len(mats);mats.append({'diffuse':(255,255,255),'ambient':(127,127,127),'tex':a})
    for index in selected:
        old,triangle=parts[3][index]
        parts[3][index]=(mi,tuple((p,n,uv(p,mapping.projection)) for p,n,t in triangle))
    output=W.inject(rom,parts,mats)
    original_triangles=sum(len(j['tris']) for j in model['joints'])
    return output,{'frames':[0],'rectangles':{'0':[.08,.04,.92,.96]},'changed_pixels':int(np.any(a!=before,axis=2).sum()),
        'shared_pixels_preserved':0,'shared_face_conflicts':0,'native_palette':False,'native_format':'N64 RGBA16 32x64',
        'mapping':mapping.model_dump(),'projection_target':'gameplay','boot_screen':'unchanged; separate Goddard writer required',
        'triangles_preserved':original_triangles,'face_triangles_projected':len(selected),'joints_preserved':len(model['joints']),
        'geometry_decimation':False}
