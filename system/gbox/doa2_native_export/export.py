"""Owned-source integration test/export; no game archive is a shipped fixture."""
import argparse,base64,hashlib,json,sys
from pathlib import Path
import numpy as np
from gbox.gdrom import GDRom
from . import complete as E
from . import source_binding as F


def verify_gltf(path,result):
    gl=json.loads(path.read_text());count=len(result['world'])
    if len(gl['skins'][0]['joints'])!=count:raise ValueError('GLTF skeleton size mismatch')
    worlds=[]
    for joint,parent in enumerate(result['parent']):
        local=np.asarray(gl['nodes'][joint]['matrix']).reshape(4,4).T
        worlds.append(local)
    # Native joint numbering is not topological: chest0 has pelvis2 as parent.
    computed={}
    def world(j):
        if j not in computed:
            parent=result['parent'][j]
            computed[j]=world(parent)@worlds[j] if parent>=0 else worlds[j]
        return computed[j]
    for j in range(count):np.testing.assert_allclose(world(j),result['world'][j],atol=1e-7)
    blob=base64.b64decode(gl['buffers'][0]['uri'].split(',',1)[1])
    accessor=gl['accessors'][gl['skins'][0]['inverseBindMatrices']]
    view=gl['bufferViews'][accessor['bufferView']]
    offset=accessor.get('byteOffset',0)+view.get('byteOffset',0)
    inverse=np.frombuffer(blob[offset:offset+count*64],dtype='<f4').reshape(count,4,4).transpose(0,2,1)
    for j in range(count):np.testing.assert_allclose(world(j)@inverse[j],np.eye(4),atol=2e-7)
    if set(E.ROLES.values())-set(gl['skins'][0]['joints']):raise ValueError('GLTF donor roles missing')
    for role,joint in E.ROLES.items():
        if gl['nodes'][joint]['name']!=role:raise ValueError('GLTF donor role name mismatch')
    if len(gl['meshes'][0]['primitives'])!=len(result['prims']):raise ValueError('GLTF draw count mismatch')
    return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,
            'primitives':len(result['prims']),'native_skin_matrices_verified':count}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--gdi',required=True);parser.add_argument('--cache',required=True)
    parser.add_argument('--profiles');parser.add_argument('--output',required=True)
    parser.add_argument('--only',nargs='*');args=parser.parse_args(argv)
    disc=GDRom(args.gdi);exe=disc.read('1ST_READ.BIN')
    profiles=json.loads(Path(args.profiles).read_text()) if args.profiles else None
    audit=None
    if profiles is None:
        from gbox import doa2_rig as R
        audit=R.collect_axes(disc)
    from .generate_cache import _profile
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    rows=[]
    resources=F.costumes(disc,exe,include_unavailable=True)
    (out/'native_resource_inventory.json').write_text(json.dumps(resources,indent=2))
    for record in resources:
        if not record['available']:continue
        name=record['acs_path'];stem=record['stem']
        if args.only and stem not in args.only:continue
        try:
            binding=E.B.resolve_archive_binding(exe,stem+'.CHR')
            data={extension:disc.read(F.owned_path(disc,stem+'.'+extension)) for extension in ('CHR','BIN','SUP')}
            data['ACS']=disc.read(name)
            hashes={key:hashlib.sha256(value).hexdigest() for key,value in data.items()}
            result=E.assemble_native(exe,stem,data['CHR'],data['BIN'],data['SUP'],data['ACS'],
                                     _profile(disc,exe,stem,profiles,audit),cache_directory=args.cache,acs_filename=name)
            if any(result['report']['source_hashes'][key]!=value for key,value in hashes.items()):
                raise ValueError('Source provenance hash mismatch')
            path=out/(stem+'.gltf');E.write_complete(path,result)
            validation=verify_gltf(path,result)
            (out/(stem+'.report.json')).write_text(json.dumps(result['report'],indent=2))
            row={'stem':stem,'status':'verified complete neutral source decomposition',
                 'triangles':result['report']['triangles'],'vertices':result['report']['vertices'],
                 'joints':result['report']['joints'],'source_hashes':hashes,'roles':E.ROLES,
                 'native_acs_binding':record['native_acs_binding'],
                 'draws':len(result['report']['native_draws']),
                 'chains':len(result['report']['native_chains']),
                 'cloth_grids':len(result['report']['native_cloth']['verified_native_grids']),
                 'projected_uv_unreplayed':result['report']['projected_uv_unreplayed'],**validation}
            rows.append(row);print(json.dumps({'stem':stem,'triangles':row['triangles'],'draws':row['draws']}),flush=True)
        except Exception as error:
            rows.append({'stem':stem,'error':str(error)});print(json.dumps(rows[-1]),flush=True)
    summary={'archives':len(rows),'exported':sum('error' not in r for r in rows),
             'native_declared_archives':len(resources),
             'unavailable_native_sources':[{'stem':r['stem'],'missing_sources':r['missing_sources']} for r in resources if not r['available']],
             'triangles':sum(r.get('triangles',0) for r in rows),'vertices':sum(r.get('vertices',0) for r in rows),
             'draws':sum(r.get('draws',0) for r in rows),'chains':sum(r.get('chains',0) for r in rows),
             'cloth_grids':sum(r.get('cloth_grids',0) for r in rows),'errors':[r for r in rows if 'error' in r],
             'gameplay_verified':False}
    (out/'verification.json').write_text(json.dumps({'summary':summary,'costumes':rows},indent=2))
    print(json.dumps(summary,indent=2),flush=True)
    if summary['errors']:return 1
    return 0

if __name__=='__main__':raise SystemExit(main())

