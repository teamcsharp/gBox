"""Read-only ROM-export planning and concrete recovery instructions."""
from __future__ import annotations

import shutil
from pathlib import Path


def selection(inp, saved):
    indexed = {m['id']: m for m in saved}
    ids = ([inp.get('mod_id')] if inp.get('mod_id') else [])
    if ids and ids[0] not in indexed:
        raise ValueError('Saved mod no longer exists; select a current saved mod or built mod')
    ids += [name for name in inp.get('mods', []) if name in indexed]
    docs = [indexed[key] for key in dict.fromkeys(ids)]
    names = [name for name in inp.get('mods', []) if name not in indexed]
    gid = inp.get('game_id') or next((c.get('input', {}).get('game_id') for d in docs for c in d.get('calls', [])
                                    if c.get('tool') == '@launch' and c.get('input', {}).get('game_id')), '')
    gid = gid or (docs[0].get('game_id', '') if docs else '')
    if not gid: raise ValueError('Select a game or saved mod before exporting')
    return gid, docs, names


def plan(cfg, game, docs=(), names=(), changes=None, saved=(), original=False):
    from . import filemods, romexport
    gid = game['game_id']
    filemods.mod_dir(cfg, gid, 'export-plan')
    components = [c for d in docs for c in romexport.classify(d, cfg)]
    components += [{'kind':'file_mod','game_id':gid,'name':n,'label':n} for n in names]
    if changes: components.append({'kind':'file_changes','label':'Explicit file changes'})
    options = [{'kind':'original','id':'original','label':'Original game file (unchanged)',
                'input':{'op':'export','game_id':gid,'original':True}}]
    for mod in saved:
        if mod.get('game_id') == gid:
            options.append({'kind':'saved_mod','id':mod['id'],'label':mod.get('title') or mod['id'],
                            'input':{'op':'export','game_id':gid,'mod_id':mod['id']}})
    for mod in filemods.list_mods(cfg, gid):
        name = mod.get('name')
        if name: options.append({'kind':'file_mod','id':name,'label':mod.get('title') or name,
                                 'input':{'op':'export','game_id':gid,'mods':[name]}})
    issues = []
    if original and components:
        issues.append({'code':'original_with_mods','blocking':True,'message':'Original-file export cannot include modifications.',
                       'next_step':'Choose either the unchanged original or a modified build.'})
    if not components and not original:
        issues.append({'code':'selection_required','blocking':True,
                       'message':'No modification was selected. Choose a saved mod, a built mod, or explicit file changes. '
                                 'The game title alone does not specify what to bake into a modified ROM.',
                       'next_step':'Select an export option below. If you want the original game, request an original-file export instead.'})
    for c in components:
        if c.get('game_id') and c['game_id'] != gid:
            issues.append({'code':'wrong_game','blocking':True,'message':c.get('label','Mod')+' belongs to another game.',
                           'next_step':'Export that catalog entry or select a build made for this exact game.'})
        if c['kind'] == 'none':
            issues.append({'code':'live_mod','blocking':False,'message':c.get('why','No static writer for this component'),
                           'next_step':'Use analyze_binary/ghidra_script to map the runtime change to native files; '
                                       'build a version-checked writer and verify rebuilt-file readback before exporting.'})
    bakeable = [c for c in components if c['kind'] != 'none']
    if components and not bakeable:
        issues.append({'code':'writer_required','blocking':True,'message':'The selected changes have no static export writer yet.',
                       'next_step':'Implement and verify a native writer; repeating the same export cannot repair this.'})
    pso = [c for c in components if c['kind'] == 'pso_code_patch']
    if pso and (game.get('platform') != 'dreamcast' or any(c['kind'] != 'pso_code_patch' for c in components)):
        issues.append({'code':'pso_combination','blocking':True,'message':'The PSO critical-hit writer exports its verified Dreamcast disc separately.',
                       'next_step':'Select the critical-hit saved mod alone; other changes need a separately verified writer.'})
    ready = not any(i['blocking'] for i in issues)
    return {'status':'ready' if ready and not issues else 'ready_with_omissions' if ready else 'needs_selection' if not components else 'needs_writer',
            'ready':ready,'game_id':gid,'game':game.get('title'),'platform':game.get('platform'),
            'components':components,'issues':issues,'options':options,'mode':'original' if original else 'modified',
            'tools':{'bps':'built in; verified by patch round trip', 'ips':'built in; limited to 16 MiB',
                     'xdelta3':shutil.which('xdelta3'), 'chdman':shutil.which('chdman'),
                     'archive_reader':shutil.which('7z') or shutil.which('7zz'),
                     'dolphin_cli':str(Path(cfg.runtime)/'dolphin/Dolphin-x64/DolphinTool.exe')
                         if (Path(cfg.runtime)/'dolphin/Dolphin-x64/DolphinTool.exe').is_file() else shutil.which('dolphin-tool'),
                     'dreamcast_chd_reader':'built in, v4/v5', 'pso_critical_writer':'hash-checked US v2 executable, GDI readback, BPS round trip'},
            'engineering':{'guide':'docs/rom-export-recovery.md',
                           'steps':['Inspect the exact failed input and error; do not repeat an unchanged deterministic failure.',
                                    'Plan with the selected saved/build mod and exact game ID.',
                                    'Fingerprint source files; use native decompilation tools for missing format or loader knowledge.',
                                    'Write only a new output, validate expected source bytes, read rebuilt native files back, and apply patches to verify equality.',
                                    'Report file verification and actual gameplay verification separately.']}}


def require_ready(result):
    if not result['ready']:
        raise ValueError('Export needs repair: '+' '.join(i['message']+' '+i['next_step'] for i in result['issues'] if i['blocking']))


def export_original(cfg, game, rom, name='', progress=None):
    """Explicit unchanged-file export; archive files remain archives, never called rebuilt images."""
    import hashlib, tempfile, time
    from . import filemods, romexport
    filemods.mod_dir(cfg,game['game_id'],'original')
    source=Path(rom)
    if not source.is_file() or source.name.upper()=='EBOOT.BIN':
        raise ValueError('Original export requires a complete library file/archive; use folder export for an extracted disc tree')
    before=source.stat()
    parent=romexport.exports_root(cfg)/game['game_id'];parent.mkdir(parents=True,exist_ok=True)
    out=Path(tempfile.mkdtemp(prefix='original_',dir=parent));target=out/source.name
    digest=hashlib.sha256();count=0
    with source.open('rb') as src,target.open('xb') as dst:
        for block in iter(lambda:src.read(4<<20),b''):
            dst.write(block);digest.update(block);count+=len(block)
            if progress:progress(min(80,80*count/max(before.st_size,1)),'Copying unchanged original game file')
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or count!=before.st_size:
        raise ValueError('Original library file changed during export; output not published')
    check=hashlib.sha256()
    with target.open('rb') as stream:
        for block in iter(lambda:stream.read(4<<20),b''):check.update(block)
    if check.digest()!=digest.digest():raise ValueError('Original export readback SHA-256 mismatch')
    result={'name':out.name,'title':name or 'Original game file','game_id':game['game_id'],'game':game.get('title'),
            'platform':game.get('platform'),'dir':str(out),'rel_dir':f"exports/{game['game_id']}/{out.name}",
            'built':time.time(),'image':target.name,'image_size':count,'mode':'original','patches':[],
            'cheat_files':[],'components':[],'steps':[{'step':'unchanged source copy','sha256':digest.hexdigest(),'readback_verified':True}],
            'note':'Unchanged original library file. Archives remain archives and may need extraction before use. No modification was applied.'}
    return romexport._finish(result,out)


def main():
    """Fresh-process recovery remains available while long-running workers await a safe refresh."""
    import argparse, json, httpx
    from .config import load
    from .registry import Ctx
    from .tools import RomExportIn, rom_export
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='gbox.toml');parser.add_argument('--server')
    parser.add_argument('--job',required=True);parser.add_argument('--mod-id');parser.add_argument('--mod',action='append')
    parser.add_argument('--original',action='store_true',help='Explicitly export the unchanged original library file')
    parser.add_argument('--execute',action='store_true',help='Export only after the selected recipe passes planning')
    args=parser.parse_args();cfg=load(args.config)
    server=(args.server or cfg.public_url or f'http://127.0.0.1:{cfg.api_port}').rstrip('/')
    headers={'Authorization':'Bearer '+cfg.token()}
    with httpx.Client(headers=headers,timeout=60) as client:
        response=client.get(server+'/api/jobs/'+args.job);response.raise_for_status();job=response.json()
    if job.get('tool')!='rom_export': parser.error('The selected job is not a ROM export')
    inp=dict(job['input']);inp['op']='plan'
    if args.mod_id is not None:inp['mod_id']=args.mod_id
    if args.mod is not None:inp['mods']=args.mod
    if args.original:inp.update(original=True,mod_id='',mods=[],changes={})
    ctx=Ctx(cfg,job_id='rom-export-repair-'+args.job);ctx.server=server;ctx.headers=headers
    checked=rom_export(RomExportIn.model_validate(inp),ctx)['result']
    if args.execute:
        require_ready(checked);inp['op']='export'
        checked=rom_export(RomExportIn.model_validate(inp),ctx)['result']
    print(json.dumps({'original_job':args.job,'executed':args.execute,'result':checked},indent=2,default=str))


if __name__=='__main__':main()
