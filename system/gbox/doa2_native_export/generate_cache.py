"""Reproduce private native cloth snapshots from an owned disc and Ghidra program.

This module ships code only. Seeds, executable, cache records and inventories
are owned game data and belong in the user's private analysis directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

import numpy as np

from . import complete as E
from . import acs_cloth_grids as V, actor_attachment_frame as A, native_cloth_cache as N
from . import source_binding as F


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _profile(disc, executable, stem, profiles, audit):
    binding = E.B.resolve_archive_binding(executable, stem+'.CHR')
    if profiles is not None:
        if isinstance(profiles, list):
            return profiles[binding['render_slot']]
        return profiles.get(stem, profiles.get(str(binding['render_slot'])))
    from gbox import doa2_rig as R
    return R.build_profile(executable, disc.read('DOA2/'+stem+'.CHR'),
                           slot=binding['render_slot'], costume=binding['costume'],
                           fighter=stem[:-2], costume_name=stem[-2:], audit=audit)


def prepare(disc, cache_directory, *, profiles=None):
    """Write one ordered manifest and hash-bound owned seeds for all source grids."""
    out = Path(cache_directory).resolve()
    out.mkdir(parents=True, exist_ok=True)
    executable = disc.read('1ST_READ.BIN')
    if _hash(executable) != E.B.EXECUTABLE_SHA256:
        raise ValueError('Cache generation requires the verified DOA2 LE JP executable')
    audit = None
    if profiles is None:
        from gbox import doa2_rig as R
        audit = R.collect_axes(disc)
    inventory, manifest, source_profiles = [], [], {}
    resources=F.costumes(disc,executable,include_unavailable=True)
    (out/'native_resource_inventory.json').write_text(json.dumps(resources,indent=2),encoding='utf-8')
    for record in resources:
        if not record['available']:continue
        stem=record['stem'];name=record['acs_path']
        chr_data = disc.read(record['chr_path'])
        acs = disc.read(name)
        grids = V.decode_grids(acs, chr_data)
        if not grids:
            continue
        profile = _profile(disc, executable, stem, profiles, audit)
        if not profile:
            raise ValueError('Missing source neutral profile for '+stem)
        binding = E.B.resolve_archive_binding(executable, stem+'.CHR')
        archive = E.G.decode_chr(chr_data)
        world, _, _, _ = E._rig(profile, executable, binding, acs, len(archive['models']))
        source_profiles[stem] = {**profile, 'executable_sha256':_hash(executable)}
        # Explicit studio coordinates, not a claim about a gameplay actor root.
        studio = world.copy()
        studio[:,1,3] += 2
        inverse = np.linalg.inv(studio)
        prefix = out/(stem+'_seed')
        prefix.with_suffix('.CHR').write_bytes(chr_data)
        prefix.with_suffix('.ACS').write_bytes(acs)
        prefix.with_suffix('.world').write_bytes(studio.transpose(0,2,1).astype('<f4').tobytes())
        roots = [g for g in grids if g['parent']==15]
        root_frame = None
        if roots:
            models = {g['model'] for g in roots}
            if len(models)!=1:
                raise ValueError('Native root-grid cache needs one verified authored controller model')
            root_frame = A.source_controller_frame(acs, studio, next(iter(models)))
            prefix.with_suffix('.base').write_bytes(root_frame['world'].T.astype('<f4').tobytes())
            prefix.with_suffix('.effect').write_bytes(struct.pack('<I',root_frame['descriptor']))
            inverse[15] = np.linalg.inv(root_frame['world'])
        prefix.with_suffix('.inverse').write_bytes(inverse.transpose(0,2,1).astype('<f4').tobytes())
        prefix.with_suffix('.models').write_bytes(struct.pack('<'+'I'*len(archive['models']),
            *[0x8c800000+m['offset'] for m in archive['models']]))
        for grid in grids:
            destination = out/(stem+'_'+str(grid['descriptor'])+'.bin')
            fields = [str(prefix.with_suffix('.ACS')), str(grid['descriptor']), str(destination), str(prefix)]
            if any('\t' in value or '\n' in value for value in fields):
                raise ValueError('Cache manifest paths cannot contain tabs or newlines')
            manifest.append('\t'.join(fields))
            row = {'name':name, 'stem':stem, 'descriptor':grid['descriptor'], 'parent':grid['parent'],
                   'native_acs_binding':record['native_acs_binding'],
                   'columns':grid['columns'], 'rows':grid['rows'], 'flags':grid['flags'],
                   'output':str(destination), 'seed':str(prefix), 'generated':True,
                   'source_chr_sha256':_hash(chr_data), 'source_acs_sha256':_hash(acs),
                   'executable_sha256':_hash(executable),
                   'pose':'native neutral rig translated Y+2; explicit virtual studio frame, not observed runtime pose',
                   'floor':'native no-stage fallback Y=1; unchanged native floor function',
                   'root_status':'core parent verified' if grid['parent']!=15 else 'exact authored mode4 controller frame; native comparison required'}
            if grid['parent']==15:
                row['root_source'] = {k:v for k,v in root_frame.items() if k!='world'}
            inventory.append(row)
    (out/'1ST_READ.BIN').write_bytes(executable)
    (out/'source_profiles.json').write_text(json.dumps(source_profiles,indent=2),encoding='utf-8')
    (out/'manifest.tsv').write_text('\n'.join(manifest)+'\n',encoding='utf-8')
    (out/'inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
    return {'grids':len(inventory), 'costumes':len(source_profiles), 'executable_sha256':_hash(executable),
            'owned_body_archives':sum(r['available'] for r in resources),
            'unavailable_native_sources':[{'stem':r['stem'],'missing_sources':r['missing_sources']} for r in resources if not r['available']],
            'manifest':str(out/'manifest.tsv'), 'owned_data':True, 'gameplay_verified':False}


def run_native(cache_directory, headless, project_directory, project_name, program_name, *, env=None):
    """Run original SH4 code in a caller-selected read-only Ghidra program."""
    directory = Path(cache_directory).resolve()
    # Ghidra validates the supplied project URL, not the resolved filesystem
    # target. A non-hidden symlink to a private .hermes directory is valid.
    if any(part.startswith('.') for part in Path(project_directory).absolute().parts) or project_name.startswith('.'):
        raise ValueError('Ghidra rejects project paths containing hidden directory/name elements; choose a separate project directory outside .hermes/.cache')
    scripts = Path(__file__).parent/'tools'
    arguments = [str(headless), str(project_directory), project_name, '-process',program_name,
                 '-noanalysis','-readOnly','-scriptPath',str(scripts.resolve()),
                 '-postScript','native_cloth_emulate.java','--manifest',str(directory/'manifest.tsv')]
    with (directory/'native_execution.log').open('w',encoding='utf-8') as log:
        result = subprocess.run(arguments,stdout=log,stderr=subprocess.STDOUT,check=False,env=env,timeout=3300)
    if result.returncode:
        raise RuntimeError('Ghidra cache execution failed; inspect '+str(directory/'native_execution.log'))
    return verify(directory)


def verify(cache_directory):
    """Independently verify finite cells, exact aliases, bounds and native root output."""
    out = Path(cache_directory).resolve()
    inventory = json.loads((out/'inventory.json').read_text(encoding='utf-8'))
    results = []
    for original_row in inventory:
        row = dict(original_row)
        try:
            path = out/N.cache_name(row['output'])
            seed = out/N.cache_name(row['seed'])
            row.update(output=str(path),seed=str(seed))
            columns, rows = row['columns'], row['rows']
            state = path.read_bytes()
            cells = Path(str(path)+'.cells').read_bytes()
            if len(state)!=8192 or len(cells)!=32768:
                raise ValueError('Native state/cell byte count differs from fixed allocations')
            pose = np.frombuffer(cells[:columns*(rows+1)*48],dtype='<f4').reshape(columns,rows+1,12)[:,:,:3]
            if not np.isfinite(pose).all():
                raise ValueError('Native cell positions contain NaN/Infinity')
            native = Path(str(path)+'.CHR').read_bytes()
            E.G.decode_chr(native)
            original = seed.with_suffix('.CHR').read_bytes()
            acs = seed.with_suffix('.ACS').read_bytes()
            if _hash(original)!=row['source_chr_sha256']:
                raise ValueError('Native source CHR hash changed')
            if row.get('source_acs_sha256',_hash(acs))!=_hash(acs):
                raise ValueError('Native source ACS hash changed')
            world = np.frombuffer(seed.with_suffix('.world').read_bytes(),dtype='<f4').reshape(-1,4,4).transpose(0,2,1)
            target = next(g for g in V.decode_grids(acs,original) if g['descriptor']==row['descriptor'])
            if any(row[k]!=target[k] for k in ('columns','rows','parent','flags')):
                raise ValueError('Cache inventory differs from the source grid descriptor')
            frame = world[target['parent']]
            root_verified = None
            if target['parent']==15:
                expected = np.frombuffer(seed.with_suffix('.base').read_bytes(),dtype='<f4').reshape(4,4).T
                observed = np.frombuffer(Path(str(path)+'.native-base').read_bytes(),dtype='<f4').reshape(4,4).T
                error = float(np.max(np.abs(expected-observed)))
                if not np.isfinite(observed).all() or error>1e-5:
                    raise ValueError('Actor controller native root comparison failed')
                authored = A.source_controller_frame(acs,world,target['model'])
                if not np.allclose(expected,authored['world'],rtol=0,atol=1e-5):
                    raise ValueError('Actor root is not its original source controller frame')
                frame = expected
                root_verified = {'maximum_matrix_error':error,'root_source':row['root_source']}
            inverse = np.linalg.inv(frame)
            local = pose@inverse[:3,:3].T+inverse[:3,3]
            source_model = E.G.decode_chr(original)['models'][target['model']]
            inline = {r['offset'] for m in source_model['meshes'] for r in m['records'] if not r['reference']}
            allowed = {i for address in inline for i in range(address,address+32)}
            previous = Path(str(path)+'.input.CHR').read_bytes()
            if len(native)!=len(original) or len(previous)!=len(original):
                raise ValueError('Native CHR byte count changed')
            if any(a!=b and i not in allowed for i,(a,b) in enumerate(zip(previous,native))):
                raise ValueError('Native writes escaped source model vertex records')
            component = bytearray(original)
            for address in inline:
                component[address:address+32] = native[address:address+32]
            errors = []
            for column in range(columns):
                for ri in range(rows):
                    for offset in target['mappings'][column][ri]:
                        actual = np.array(struct.unpack_from('<3f',native,target['model_offset']+offset))
                        if not np.isfinite(actual).all():
                            raise ValueError('Native CHR alias contains NaN/Infinity')
                        errors.append(float(np.max(np.abs(actual-local[column,ri+1]))))
            if errors and max(errors)>1e-5:
                raise ValueError('Native alias/inverse mismatch '+str(max(errors)))
            Path(str(path)+'.component.CHR').write_bytes(component)
            results.append({**row,'status':'native generator, finite world cells, CHR decoder and independent alias/inverse verified',
                'aliases':len(errors),'maximum_position_error':max(errors,default=0),
                'changed_bytes_confined_to_source_model_vertices':True,'cached_chr_sha256':_hash(component),
                'source_acs_sha256':_hash(acs),'native_actor_root_verified':root_verified,
                'descriptor_order':'native ACS directive order; prior grid writes retained before later normal calculation',
                'world_bounds':[pose.reshape(-1,3).min(0).tolist(),pose.reshape(-1,3).max(0).tolist()],
                'changed_bytes':sum(a!=b for a,b in zip(original,native))})
        except Exception as error:
            results.append({**row,'error':str(error)})
    summary = {'grids':len(results),'initializers_verified':sum('error' not in r for r in results),
               'full_native_generators_verified':sum('aliases' in r for r in results),
               'aliases_verified':sum(r.get('aliases',0) for r in results),
               'errors':[{'name':r.get('name',r.get('stem','unknown')),'descriptor':r.get('descriptor'),'error':r['error']} for r in results if 'error' in r],
               'root_effects_unexecuted':sum(not r.get('generated',False) for r in results),'gameplay_verified':False}
    (out/'verification.json').write_text(json.dumps({'summary':summary,'grids':results},indent=2),encoding='utf-8')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('prepare','verify','run','build'))
    parser.add_argument('--cache',required=True)
    parser.add_argument('--gdi')
    parser.add_argument('--profiles',help='Optional private precomputed neutral profiles; otherwise derive from owned SUP/rest data')
    parser.add_argument('--headless')
    parser.add_argument('--project-directory')
    parser.add_argument('--project-name')
    parser.add_argument('--program-name')
    args = parser.parse_args(argv)
    if args.phase in ('prepare','build'):
        if not args.gdi:
            parser.error('prepare/build needs --gdi')
        from gbox.gdrom import GDRom
        profiles = json.loads(Path(args.profiles).read_text(encoding='utf-8')) if args.profiles else None
        result = prepare(GDRom(args.gdi),args.cache,profiles=profiles)
    if args.phase in ('run','build'):
        if not all((args.headless,args.project_directory,args.project_name,args.program_name)):
            parser.error('run/build needs headless and Ghidra project/program arguments')
        result = run_native(args.cache,args.headless,args.project_directory,args.project_name,args.program_name)
    elif args.phase=='verify':
        result = verify(args.cache)
    print(json.dumps(result,indent=2))
    return 1 if result.get('errors') else 0


if __name__=='__main__':
    raise SystemExit(main())
