"""Recorded texture-projection snapshots on the real source mesh; never inferred head deformation."""
import hashlib
import io
from pathlib import Path
import numpy as np
from PIL import Image


def digest(image):
    return hashlib.sha256(np.asarray(image.convert('RGBA')).tobytes()).hexdigest()


def render_frames(triangles, maps, quad, size=320):
    """Orthographic, depth-tested textured face close-ups using the selected UV patch.

    All five frames reuse identical positions, camera and alpha. Only the approved
    before/after color maps blend; these are presentation snapshots, not new builds.
    """
    if not triangles or len(triangles)>50000:
        raise ValueError('Face snapshot requires at most 50,000 source triangles')
    lookup={digest(before):(before.convert('RGBA'),after.convert('RGBA')) for before,after in maps}
    cache={};compiled=[];focus=[]
    lo=np.min(quad,axis=0);hi=np.max(quad,axis=0)
    for positions,uv,image,color in triangles:
        key=None
        if image is not None:
            if id(image) not in cache:cache[id(image)]=hashlib.sha256(np.asarray(image).tobytes()).hexdigest()
            key=cache[id(image)]
        compiled.append((np.asarray(positions),np.asarray(uv),image,color,key))
        if key in lookup and np.all(np.max(uv,axis=0)>=lo) and np.all(np.min(uv,axis=0)<=hi):focus.append(positions)
    if not focus:raise ValueError('The selected photo patch has no source mesh triangles')
    points=np.concatenate(focus);center=(points.min(0)+points.max(0))/2
    extent=max(float(np.ptp(points[:,0])),float(np.ptp(points[:,1]))) * 1.25
    if not np.isfinite(extent) or extent<=1e-8:raise ValueError('Face patch has no visible area')
    # Cache triangle projection/coverage once; texture samples change across frames.
    raster=[];coverage=0
    for positions,uv,image,color,key in compiled:
        xy=(positions[:,:2]-center[:2])/extent*size+size/2;xy[:,1]=size-xy[:,1]
        left,top=np.maximum(np.floor(xy.min(0)).astype(int),0)
        right,bottom=np.minimum(np.ceil(xy.max(0)).astype(int),size-1)
        if right<left or bottom<top:continue
        a,b,c=xy;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-8:continue
        yy,xx=np.mgrid[top:bottom+1,left:right+1];xx=xx+.5;yy=yy+.5
        w0=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        w1=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den;w2=1-w0-w1
        mask=(w0>=-1e-6)&(w1>=-1e-6)&(w2>=-1e-6)
        if not mask.any():continue
        coverage+=int(mask.sum())
        if coverage>3_000_000:raise ValueError('Face raster exceeds the snapshot budget')
        ys,xs=np.where(mask);weights=np.stack([w0[mask],w1[mask],w2[mask]],axis=1)
        coords=weights@uv;depth=weights@positions[:,2]
        raster.append((ys+top,xs+left,coords,depth,image,color,key))
    result=[]
    for fraction in (0,.25,.5,.75,1):
        textures={key:np.asarray(Image.blend(before,after,fraction)) for key,(before,after) in lookup.items()}
        pixels=np.full((size,size,4),[22,26,32,255],dtype=np.uint8);z=np.full((size,size),-np.inf)
        for ys,xs,uv,depth,image,color,key in raster:
            tex=textures.get(key,image)
            if tex is not None:
                tex=np.asarray(tex);h,w=tex.shape[:2]
                samples=tex[np.minimum((uv[:,1]%1*h).astype(int),h-1),np.minimum((uv[:,0]%1*w).astype(int),w-1)]
            else:samples=np.tile(np.r_[np.clip(color,0,255),255].astype(np.uint8),(len(ys),1))
            visible=(depth>=z[ys,xs])&(samples[:,3]>40)
            pixels[ys[visible],xs[visible]]=samples[visible];z[ys[visible],xs[visible]]=depth[visible]
        if not np.isfinite(z).any():raise ValueError('Face snapshot is empty')
        out=io.BytesIO();Image.fromarray(pixels).save(out,format='PNG');result.append((fraction,out.getvalue()))
    return result


def record(model, settings, maps, emit):
    from .characters import _triangles,model_stats
    if not maps or model_stats(Path(model))['triangles']>50000:raise ValueError('Face snapshot model exceeds its budget')
    frames=render_frames(_triangles(Path(model)),maps,settings.quad)
    return {'schema':1,'geometry':'unchanged','source_photo':settings.photo,
            'notice':'Recorded photo-texture projection on the original mesh; face shape is unchanged.',
            'frames':[{'kind':'texture_projection','fraction':f,'label':f'Photo texture {round(f*100)}%',
                       'sha256':emit(f'photo-face-{round(f*100)}.png',data,'image/png')} for f,data in frames]}
