"""Bounded, deterministic UV-space lattice and liquify edits to a photo layer.

The recipe contains forward edits; rendering inverts them and bilinearly samples
premultiplied RGBA. It never changes the native texture or mesh. Coordinates are
normalized texture UVs with pixel centres at ``(x + .5) / width``. The browser
editor uses the same triangle split, stroke falloff, and 16 inverse iterations.
"""
from __future__ import annotations

import hashlib
import json
import math
from numbers import Real

import numpy as np

MAX_GRID = 9
MAX_STROKES = 256
INVERSE_ITERATIONS = 16
_EPS = 1e-8


def _number(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{name} must be a finite number')
    value = float(value)
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{name} must be between {lo} and {hi}')
    return value


def _keys(value, allowed, name):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f'Invalid {name} fields')


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _intersects(a, b, c, d):
    """Inclusive segment intersection; non-adjacent boundary touches fold too."""
    if max(a[0], b[0]) < min(c[0], d[0])-_EPS or max(c[0], d[0]) < min(a[0], b[0])-_EPS:
        return False
    if max(a[1], b[1]) < min(c[1], d[1])-_EPS or max(c[1], d[1]) < min(a[1], b[1])-_EPS:
        return False
    ab_c, ab_d = _cross(a,b,c), _cross(a,b,d)
    cd_a, cd_b = _cross(c,d,a), _cross(c,d,b)
    return ab_c*ab_d <= _EPS*_EPS and cd_a*cd_b <= _EPS*_EPS


def _triangles(columns, rows):
    for row in range(rows-1):
        for col in range(columns-1):
            a = row*columns+col
            yield a, a+1, a+columns+1
            yield a, a+columns+1, a+columns


def normalize_deformation(value=None):
    """Return a canonical JSON recipe, rejecting folds and unbounded work.

    Lattice cells split along top-left to bottom-right. Strictly positive
    triangles and a simple outer boundary keep the resulting piecewise affine
    map one-to-one. Liquify displacement is at most a quarter of its radius,
    which makes the smooth compact-support push invertible by contraction.
    """
    if value is None or value == {}:
        return {'version': 1, 'lattice': None, 'strokes': []}
    _keys(value, ('version','lattice','strokes'), 'deformation')
    if type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('Unsupported face deformation version')
    lattice = value.get('lattice')
    result = {'version': 1, 'lattice': None, 'strokes': []}
    if lattice is not None:
        _keys(lattice, ('columns','rows','points'), 'lattice')
        columns, rows = lattice.get('columns'), lattice.get('rows')
        if type(columns) is not int or type(rows) is not int or not (2 <= columns <= MAX_GRID and 2 <= rows <= MAX_GRID):
            raise ValueError('Lattice dimensions must be integers from 2 to 9')
        points = lattice.get('points')
        if not isinstance(points, list) or len(points) != columns*rows:
            raise ValueError('Lattice needs one row-major point per grid vertex')
        checked = []
        for point in points:
            _keys(point, ('x','y'), 'lattice point')
            checked.append({'x': _number(point.get('x'),'Lattice x',-.5,1.5),
                            'y': _number(point.get('y'),'Lattice y',-.5,1.5)})
        xy = [(p['x'], p['y']) for p in checked]
        if any(_cross(xy[a],xy[b],xy[c]) <= _EPS for a,b,c in _triangles(columns,rows)):
            raise ValueError('Lattice would fold or collapse a triangle')
        boundary = list(range(columns))
        boundary += [r*columns+columns-1 for r in range(1,rows)]
        boundary += [(rows-1)*columns+c for c in range(columns-2,-1,-1)]
        boundary += [r*columns for r in range(rows-2,0,-1)]
        edges = [(xy[boundary[i]],xy[boundary[(i+1)%len(boundary)]]) for i in range(len(boundary))]
        for i,(a,b) in enumerate(edges):
            for j in range(i+2,len(edges)):
                if i == 0 and j == len(edges)-1:
                    continue
                if _intersects(a,b,*edges[j]):
                    raise ValueError('Lattice boundary intersects itself')
        result['lattice'] = {'columns': columns, 'rows': rows, 'points': checked}
    strokes = value.get('strokes', [])
    if not isinstance(strokes, list) or len(strokes) > MAX_STROKES:
        raise ValueError('At most 256 liquify strokes are allowed')
    for stroke in strokes:
        _keys(stroke, ('x','y','dx','dy','radius'), 'liquify stroke')
        s = {key: _number(stroke.get(key), f'Liquify {key}', lo, hi)
             for key,lo,hi in (('x',0,1),('y',0,1),('dx',-.25,.25),('dy',-.25,.25),('radius',.005,1))}
        if math.hypot(s['dx'],s['dy']) > s['radius']*.25+1e-12:
            raise ValueError('Liquify drag exceeds a quarter of its brush radius')
        result['strokes'].append(s)
    return result


def is_identity(deformation=None):
    recipe = normalize_deformation(deformation)
    if any(s['dx'] or s['dy'] for s in recipe['strokes']):
        return False
    grid = recipe['lattice']
    return grid is None or all(abs(p['x']-(i%grid['columns'])/(grid['columns']-1)) < 1e-12
                              and abs(p['y']-(i//grid['columns'])/(grid['rows']-1)) < 1e-12
                              for i,p in enumerate(grid['points']))


def recipe_report(deformation=None):
    recipe = normalize_deformation(deformation)
    encoded = json.dumps(recipe,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return {'recipe': recipe, 'sha256': hashlib.sha256(encoded).hexdigest(),
            'identity': is_identity(recipe), 'sampling': 'premultiplied-bilinear',
            'coordinates': 'normalized-UV-pixel-centres', 'inverse_iterations': INVERSE_ITERATIONS}


def inverse_points(x, y, deformation=None):
    """Map destination normalized UV arrays back to the undeformed photo layer."""
    recipe = normalize_deformation(deformation)
    x, y = np.broadcast_arrays(np.asarray(x,dtype=float),np.asarray(y,dtype=float))
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Warp sample coordinates must be finite')
    x=x.copy();y=y.copy()
    for s in reversed(recipe['strokes']):
        if not (s['dx'] or s['dy']):
            continue
        # Only points in the forward support can move. Restricting each local
        # solve matters on a large texture with a small liquify brush.
        extent=s['radius']+math.hypot(s['dx'],s['dy'])
        active=(np.abs(x-s['x']) <= extent)&(np.abs(y-s['y']) <= extent)
        if not active.any():
            continue
        qx=x[active].copy();qy=y[active].copy();px=qx.copy();py=qy.copy()
        for _ in range(INVERSE_ITERATIONS):
            falloff=np.maximum(0,1-((px-s['x'])**2+(py-s['y'])**2)/(s['radius']**2))**2
            px=qx-s['dx']*falloff;py=qy-s['dy']*falloff
        x[active]=px;y[active]=py
    grid=recipe['lattice']
    if grid is None:
        return x,y,(x>=0)&(x<=1)&(y>=0)&(y<=1)
    columns,rows=grid['columns'],grid['rows'];points=grid['points']
    sx=np.zeros_like(x);sy=np.zeros_like(y);valid=np.zeros(x.shape,bool)
    for ids in _triangles(columns,rows):
        a,b,c=[(points[i]['x'],points[i]['y']) for i in ids]
        candidates=(~valid)&(x>=min(a[0],b[0],c[0])-_EPS)&(x<=max(a[0],b[0],c[0])+_EPS)&(y>=min(a[1],b[1],c[1])-_EPS)&(y<=max(a[1],b[1],c[1])+_EPS)
        if not candidates.any():
            continue
        px=x[candidates];py=y[candidates];den=_cross(a,b,c)
        wa=((b[1]-c[1])*(px-c[0])+(c[0]-b[0])*(py-c[1]))/den
        wb=((c[1]-a[1])*(px-c[0])+(a[0]-c[0])*(py-c[1]))/den;wc=1-wa-wb
        inside=(wa>=-_EPS)&(wb>=-_EPS)&(wc>=-_EPS)
        flat=np.flatnonzero(candidates)[inside]
        tx=[(i%columns)/(columns-1) for i in ids];ty=[(i//columns)/(rows-1) for i in ids]
        sx.flat[flat]=np.clip((wa*tx[0]+wb*tx[1]+wc*tx[2])[inside],0,1)
        sy.flat[flat]=np.clip((wa*ty[0]+wb*ty[1]+wc*ty[2])[inside],0,1)
        valid.flat[flat]=True
    return sx,sy,valid


def apply_layer(rgba, deformation=None, clipmask=None):
    """Return float RGBA (0..255), deforming only the supplied photo layer.

    ``clipmask`` is destination coverage in 0..1. It clips the warped alpha and
    clears pixels outside that coverage; callers composite onto an unchanged
    native texture and preserve its alpha. Transparent colour is sampled in
    premultiplied form to avoid dragging hidden RGB into the face.
    """
    recipe=normalize_deformation(deformation)
    source=np.asarray(rgba,dtype=float)
    if source.ndim!=3 or source.shape[2]!=4 or not min(source.shape[:2]) or max(source.shape[:2])>4096 or source.shape[0]*source.shape[1]>16_777_216:
        raise ValueError('Photo layer must be bounded RGBA, at most 4096 pixels per side')
    if not np.isfinite(source).all() or source.min()<0 or source.max()>255:
        raise ValueError('Photo layer RGBA must be finite and between 0 and 255')
    h,w=source.shape[:2]
    if clipmask is not None:
        clipmask=np.asarray(clipmask,dtype=float)
        if clipmask.shape!=(h,w) or not np.isfinite(clipmask).all() or clipmask.min()<0 or clipmask.max()>1:
            raise ValueError('Photo layer coverage must match the image and be between 0 and 1')
    if is_identity(recipe):
        out=source.copy()
    else:
        # Tile the inverse map so a 4K face atlas does not allocate full-image
        # coordinate/weight temporaries for every stroke and lattice triangle.
        out=np.zeros_like(source)
        for y0 in range(0,h,64):
            xx,yy=np.meshgrid((np.arange(w)+.5)/w,(np.arange(y0,min(h,y0+64))+.5)/h)
            sx,sy,valid=inverse_points(xx,yy,recipe)
            fx=np.clip(sx*w-.5,0,w-1);fy=np.clip(sy*h-.5,0,h-1)
            ix=np.floor(fx).astype(int);iy=np.floor(fy).astype(int);jx=np.minimum(ix+1,w-1);jy=np.minimum(iy+1,h-1)
            dx=fx-ix;dy=fy-iy
            result=np.zeros((*xx.shape,4),float)
            for cy,cx,weight in ((iy,ix,(1-dx)*(1-dy)),(iy,jx,dx*(1-dy)),(jy,ix,(1-dx)*dy),(jy,jx,dx*dy)):
                pixels=source[cy,cx];alpha=pixels[...,3]/255
                result[...,:3]+=pixels[...,:3]*(alpha*weight)[...,None]
                result[...,3]+=alpha*weight
            visible=valid&(result[...,3]>0)
            result[visible,:3]/=result[visible,3,None]
            result[...,3]*=255;result[~visible]=0
            out[y0:y0+xx.shape[0]]=result
    if clipmask is not None:
        out[...,3]*=clipmask;out[clipmask==0]=0
    return out
