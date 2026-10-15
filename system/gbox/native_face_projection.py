"""Bake an approved photograph through native face triangles, without changing geometry.

Coordinates and material selection must come from a reviewed per-game profile.
No face detector, arbitrary atlas rectangle, rig inference, or mesh reduction is used.
The returned preview is RGBA; a game writer must round-trip its native encoding.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import numpy as np
from PIL import Image


@dataclass
class Projection:
    image: Image.Image
    mask: np.ndarray
    report: dict


def compact_previews(folder,faces,keep=4):
    """Keep a few loader pairs; pack the other new-build previews in one ZIP."""
    from pathlib import Path
    from zipfile import ZipFile,ZIP_DEFLATED
    root=Path(folder).resolve();directory=root/'face-previews';kept=[];actors=set();loose=set()
    for face in faces:
        actor=face.get('native_actor')or face.get('archive')or face.get('model')
        if actor in actors or len(kept)>=keep:continue
        before=face.get('preview_before','');after=face.get('preview_after','')
        if not all((root/p).is_file()for p in (before,after)):continue
        actors.add(actor);loose.update((before,after));kept.append({'before':before,'after':after,'label':actor})
    packed=[]
    for path in sorted(directory.glob('*.png')):
        resolved=path.resolve()
        if resolved.parent!=directory.resolve()or resolved.is_symlink():raise ValueError('Preview file escapes build directory')
        rel=path.relative_to(root).as_posix()
        if rel not in loose:packed.append((path,rel))
    if packed:
        archive=root/'face-previews.zip'
        if archive.exists():raise FileExistsError('Preview archive already exists')
        with ZipFile(archive,'w',compression=ZIP_DEFLATED,compresslevel=6)as z:
            for path,rel in packed:z.write(path,rel)
        with ZipFile(archive)as z:
            if z.testzip()is not None:raise ValueError('Preview archive did not verify')
        names={rel for _,rel in packed}
        for face in faces:
            for key in ('preview_before','preview_after'):
                if face.get(key)in names:face[key]='face-previews.zip!'+face[key]
        for path,_ in packed:path.unlink()
    return {'previews':kept,'archive':'face-previews.zip'if packed else None,'loose_pair_count':len(kept),'packed_files':len(packed)}


def project(original, photo, primitives, *, crop=(0., 0., 1., 1.), bounds=None,
            opacity=1., feather=.12, normal_min=.15, flip_x=True, wrap=True,respect_alpha=True,mirror_x=False):
    """Project photo XY onto reviewed +Z-facing native triangles in their UVs.

    ``primitives`` contain finite ``pos``, ``nrm``, ``uv``, ``tris`` arrays. Only
    these primitives are writable. UV coordinates are top-left texture sampling
    coordinates, with repeat allowed for native tiled coordinates. ``bounds``
    is [left,bottom,right,top] in native head space; auto bounds are a preview
    candidate derived from the supplied geometry, never an approval assertion.
    Native alpha and pixels outside the face mask are preserved exactly.
    """
    base=np.asarray(original.convert('RGBA') if isinstance(original,Image.Image) else Image.fromarray(np.asarray(original,dtype=np.uint8)).convert('RGBA'))
    source=np.asarray(photo.convert('RGBA') if isinstance(photo,Image.Image) else Image.open(photo).convert('RGBA'))
    crop=np.asarray(crop,dtype=float)
    if crop.shape!=(4,) or not np.isfinite(crop).all() or not (0<=crop[0]<crop[2]<=1 and 0<=crop[1]<crop[3]<=1):
        raise ValueError('Photo crop must be normalized left/top/right/bottom')
    if not 0<=opacity<=1 or not 0<feather<=1 or not -1<=normal_min<=1:
        raise ValueError('Invalid projection blend settings')
    pp=[]
    for p in primitives:
        pos=np.asarray(p['pos'],dtype=float);nrm=np.asarray(p['nrm'],dtype=float);uv=np.asarray(p['uv'],dtype=float);tri=np.asarray(p['tris'],dtype=int)
        if (pos.ndim!=2 or pos.shape[1]!=3 or nrm.shape!=pos.shape or uv.shape!=(len(pos),2)
                or tri.ndim!=2 or tri.shape[1]!=3 or not all(np.isfinite(a).all() for a in (pos,nrm,uv))
                or (tri.size and (tri.min()<0 or tri.max()>=len(pos)))):
            raise ValueError('Invalid native face geometry')
        if np.max(np.abs(uv),initial=0)>16:raise ValueError('Native UV exceeds bounded repeat range')
        pp.append((pos,nrm,uv,tri))
    if not pp or not sum(len(p[3]) for p in pp):raise ValueError('No native face triangles')
    if bounds is None:
        points=np.concatenate([p[0] for p in pp]);lo=points.min(0);hi=points.max(0)
        bounds=[lo[0],lo[1],hi[0],hi[1]]
    bounds=np.asarray(bounds,dtype=float)
    if bounds.shape!=(4,) or not np.isfinite(bounds).all() or not (bounds[0]<bounds[2] and bounds[1]<bounds[3]):
        raise ValueError('Invalid native projection bounds')
    h,w=base.shape[:2];mask=np.zeros((h,w),float);sample=np.zeros((h,w,3),float);depth=np.full((h,w),-np.inf)
    accepted=0
    for pos,nrm,uv,tris in pp:
        for ids in tris:
            ns=nrm[ids];length=np.linalg.norm(ns,axis=1);nz=ns[:,2]/np.maximum(length,1e-9)
            if float(nz.mean())<normal_min:continue
            # Rasterize each repeated tile separately, preserving original UV
            # interpolation. Individually wrapping vertices would tear seams.
            t=uv[ids];p=pos[ids]
            tiles_x=range(int(np.floor(t[:,0].min())),int(np.floor(t[:,0].max()))+1) if wrap else [0]
            tiles_y=range(int(np.floor(t[:,1].min())),int(np.floor(t[:,1].max()))+1) if wrap else [0]
            accepted+=1
            for tile_x in tiles_x:
                for tile_y in tiles_y:
                    q=(t-[tile_x,tile_y])*[w,h]-.5
                    x0=max(0,int(np.ceil(q[:,0].min())));x1=min(w-1,int(np.floor(q[:,0].max())))
                    y0=max(0,int(np.ceil(q[:,1].min())));y1=min(h-1,int(np.floor(q[:,1].max())))
                    if x0>x1 or y0>y1:continue
                    a,b,c=q;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
                    if abs(den)<1e-10:continue
                    xx,yy=np.meshgrid(np.arange(x0,x1+1),np.arange(y0,y1+1))
                    wa=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
                    wb=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den;wc=1-wa-wb
                    inside=(wa>=-1e-7)&(wb>=-1e-7)&(wc>=-1e-7)
                    point=wa[...,None]*p[0]+wb[...,None]*p[1]+wc[...,None]*p[2]
                    sample_x=point[...,0]
                    if mirror_x:
                        # Native mirrored face UVs cannot represent two
                        # differently lit photo halves. Canonicalize ownership
                        # before sampling; near-equal overlapping depths must
                        # not alternate between halves pixel by pixel.
                        center=(bounds[0]+bounds[2])*.5
                        sample_x=center+np.abs(sample_x-center)
                    sx=(sample_x-bounds[0])/(bounds[2]-bounds[0]);sy=1-(point[...,1]-bounds[1])/(bounds[3]-bounds[1])
                    radius=np.sqrt(((sx-.5)/.5)**2+((sy-.5)/.5)**2)
                    alpha=np.clip((1-radius)/feather,0,1)*opacity
                    # Normals select anatomical front triangles. Modulating
                    # each UV texel by interpolated native lighting normals
                    # punches pale freckles through otherwise continuous skin
                    # (many authored meshes use strong per-corner normals).
                    valid=inside&(alpha>0)&(sx>=0)&(sx<=1)&(sy>=0)&(sy<=1)&(point[...,2]>depth[y0:y1+1,x0:x1+1])
                    if not valid.any():continue
                    if flip_x:sx=1-sx
                    fx=np.clip((crop[0]+sx*(crop[2]-crop[0]))*(source.shape[1]-1),0,source.shape[1]-1)
                    fy=np.clip((crop[1]+sy*(crop[3]-crop[1]))*(source.shape[0]-1),0,source.shape[0]-1)
                    ix=np.floor(fx).astype(int);iy=np.floor(fy).astype(int);jx=np.minimum(ix+1,source.shape[1]-1);jy=np.minimum(iy+1,source.shape[0]-1)
                    dx=(fx-ix)[...,None];dy=(fy-iy)[...,None]
                    col=(source[iy,ix]*(1-dx)+source[iy,jx]*dx)*(1-dy)+(source[jy,ix]*(1-dx)+source[jy,jx]*dx)*dy
                    alpha*=col[...,3]/255
                    valid&=alpha>0
                    region=sample[y0:y1+1,x0:x1+1];region[valid]=col[valid,:3]
                    mask[y0:y1+1,x0:x1+1][valid]=alpha[valid]
                    depth[y0:y1+1,x0:x1+1][valid]=point[...,2][valid]
    if respect_alpha:mask*=base[...,3]/255
    result=base.copy();active=mask>0
    result[active,:3]=np.rint(base[active,:3]*(1-mask[active,None])+sample[active]*mask[active,None]).astype(np.uint8)
    return Projection(Image.fromarray(result),mask,{'format':'native-face-projection-v1','bounds':bounds.tolist(),'crop':crop.tolist(),
        'opacity':opacity,'feather':feather,'normal_min':normal_min,'flip_x':flip_x,'wrap':wrap,'respect_alpha':respect_alpha,'mirror_x':mirror_x,
        'triangles':sum(len(p[3]) for p in pp),'front_triangles':accepted,'masked_pixels':int(active.sum()),
        'outside_mask_unchanged':bool(np.array_equal(base[~active],result[~active])),
        'alpha_unchanged':bool(np.array_equal(base[...,3],result[...,3])),
        'source_photo_pixels_sha256':hashlib.sha256(source.tobytes()).hexdigest(),
        'geometry_modified':False,'review_status':'projection candidate; native likeness review required'})
