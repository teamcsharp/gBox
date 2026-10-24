"""Prepare the existing Pine public door for an independent media gateway.

Only app.py and compose.yaml are patched. The command defaults to inspection;
applying requires their reviewed hashes. It never starts or restarts services.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass,field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

OLD='uvicorn.Config(PublicListenerGate(app), host="0.0.0.0",'
NEW='uvicorn.Config(PublicListenerGate(app), host=os.getenv("PINE_GBOX_PUBLIC_BACKEND_HOST", "0.0.0.0"),'
ENV={'SPARK_PUBLIC_PORT':'18097','PINE_GBOX_PUBLIC_BACKEND_HOST':'127.0.0.1'}
LIMITS={'spark-agent/app.py':32*1024*1024,'compose.yaml':1024*1024}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def patch_existing_app(text):
    """Change exactly the public listener host inside its existing startup hook."""
    if not re.search(r'^import os(?:\s|$)',text,re.M):
        raise ValueError('The existing app must already import os')
    headers=list(re.finditer(r'^async def _startup_public_door\(\) -> None:\r?$',text,re.M))
    if len(headers)!=1:raise ValueError('Expected exactly one existing public-door startup function')
    begin=headers[0].end()
    following=re.search(r'^[^\s#]',text[begin:],re.M)
    end=begin+following.start() if following else len(text)
    block=text[begin:end]
    if block.count(NEW)==1 and OLD not in block:return text
    if block.count(OLD)!=1 or NEW in block:
        raise ValueError('Unexpected public-door listener shape; no changes prepared')
    return text[:begin]+block.replace(OLD,NEW,1)+text[end:]


def patch_compose(text):
    """Add two scalar environment entries without reserializing YAML or secrets."""
    lines=text.splitlines(keepends=True)
    if any('\t' in line[:len(line)-len(line.lstrip())] for line in lines):
        raise ValueError('Compose indentation must use spaces')
    services=[i for i,line in enumerate(lines) if re.fullmatch(r'services:\s*(?:#.*)?(?:\r?\n)?',line)]
    if len(services)!=1:raise ValueError('Expected one top-level services mapping')
    top_end=next((i for i in range(services[0]+1,len(lines)) if re.match(r'^[^\s#]',lines[i])),len(lines))
    starts=[i for i in range(services[0]+1,top_end) if re.fullmatch(r'  spark-agent:\s*(?:#.*)?(?:\r?\n)?',lines[i])]
    if len(starts)!=1:raise ValueError('Expected exactly one spark-agent service')
    begin=starts[0]
    end=next((i for i in range(begin+1,top_end) if re.match(r'^  [^\s#]',lines[i])),top_end)
    envs=[i for i in range(begin+1,end) if re.match(r'^    environment\s*:',lines[i])]
    if len(envs)!=1 or not re.fullmatch(r'    environment:\s*(?:#.*)?(?:\r?\n)?',lines[envs[0]]):
        raise ValueError('Expected one block mapping for spark-agent environment')
    env=envs[0]
    env_end=next((i for i in range(env+1,end) if re.match(r'^    [^\s#]',lines[i])),end)
    block=lines[env+1:env_end]
    if any(re.match(r'^      (?:-|<<|[&*])',line) for line in block):
        raise ValueError('Environment lists, merges and anchors are not supported')
    if any(re.match(r'^      [^\s#]',line) and not re.match(r'^      [A-Za-z_][A-Za-z0-9_]*\s*:',line)
           for line in block):
        raise ValueError('Expected unquoted environment mapping keys')
    if not any(re.match(r'^      [A-Za-z_][A-Za-z0-9_]*\s*:',line) for line in block):
        raise ValueError('Expected existing scalar environment entries')
    newline='\r\n' if lines[env].endswith('\r\n') else '\n'
    additions=[]
    for key,value in ENV.items():
        matches=[line for line in block if re.match(r'^      '+re.escape(key)+r'\s*:',line)]
        canonical=f"      {key}: '{value}'"
        if len(matches)>1 or matches and matches[0].rstrip('\r\n')!=canonical:
            raise ValueError('Existing gateway environment value conflicts: '+key)
        if not matches:additions.append(canonical+newline)
    if not additions:return text
    lines[env+1:env+1]=additions
    return ''.join(lines)


@dataclass(frozen=True)
class Change:
    name:str
    path:Path
    before:bytes=field(repr=False)
    after:bytes=field(repr=False)
    mode:int

    def summary(self):
        return {'file':self.name,'before_sha256':digest(self.before),'after_sha256':digest(self.after),
                'changed':self.before!=self.after}


def prepare(root):
    """Read, validate and compile the complete two-file plan; never write."""
    root=Path(root).resolve(strict=True)
    result=[]
    for name,limit in LIMITS.items():
        path=root/name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Installer targets must be regular files inside the named stack')
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size>limit:
            raise ValueError('Unexpected installer file type or size: '+name)
        with path.open('rb') as source:raw=source.read(limit+1)
        if len(raw)>limit:raise ValueError('Installer source grew beyond its bound: '+name)
        text=raw.decode('utf-8')
        patched=patch_existing_app(text) if name.endswith('app.py') else patch_compose(text)
        if name.endswith('app.py'):compile(patched,str(path),'exec')
        result.append(Change(name,path,raw,patched.encode('utf-8'),stat.S_IMODE(info.st_mode)))
    return result


def atomic_replace(path,raw,mode):
    temporary=path.with_name('.'+path.name+'.gbox-gateway-'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as output:
            os.chmod(temporary,mode)
            output.write(raw);output.flush();os.fsync(output.fileno())
        temporary.replace(path)
        if os.name!='nt':
            fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
    finally:temporary.unlink(missing_ok=True)


def install(root,*,expected_app_sha256,expected_compose_sha256):
    """Backup and atomically replace each reviewed file, rolling back failures."""
    root=Path(root).resolve(strict=True);plan=prepare(root)
    expected={'spark-agent/app.py':expected_app_sha256,'compose.yaml':expected_compose_sha256}
    if any(not re.fullmatch(r'[a-f0-9]{64}',str(value)) for value in expected.values()):
        raise ValueError('Two reviewed SHA256 values are required to apply')
    if any(digest(item.before)!=expected[item.name] for item in plan):
        raise ValueError('A reviewed file changed; prepare and review again')
    changed=[item for item in plan if item.before!=item.after]
    if not changed:return {'changed':[],'backup':None,'restarted':False}
    base=root/'spark-agent'/'backups'
    if not base.resolve().is_relative_to(root):raise ValueError('Backup location escaped the named stack')
    backup=base/('gbox-media-gateway-'+str(time.time_ns())+'-'+uuid.uuid4().hex[:8])
    backup.mkdir(parents=True,mode=0o700)
    # All backups are durable before either active file is replaced.
    for item in changed:
        saved=backup/item.name;saved.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        atomic_replace(saved,item.before,0o600)
    written=[]
    try:
        for item in changed:
            if item.path.is_symlink() or item.path.read_bytes()!=item.before:
                raise ValueError('Installer source changed concurrently: '+item.name)
            written.append(item);atomic_replace(item.path,item.after,item.mode)
    except BaseException:
        for item in reversed(written):
            current=item.path.read_bytes()
            if current==item.before:continue
            if current!=item.after:
                raise RuntimeError('Concurrent edit preserved; restore the reviewed backup manually') from None
            atomic_replace(item.path,item.before,item.mode)
        raise
    return {'changed':[item.summary() for item in changed],'backup':str(backup),'restarted':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path,help='Existing pinevoice-stack directory')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--app-sha256')
    parser.add_argument('--compose-sha256')
    args=parser.parse_args()
    receipt=install(args.root,expected_app_sha256=args.app_sha256,expected_compose_sha256=args.compose_sha256) \
        if args.apply else {'plan':[item.summary() for item in prepare(args.root)],'restarted':False}
    print(json.dumps(receipt,indent=2))
