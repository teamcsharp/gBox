"""Read-only inventory by default. --close-orphans closes only proven legacy GBox test trees.

Legacy profile contents are always preserved; this never targets browser names
globally, user browser profiles, Electron or GBox workers.
"""
import argparse
import datetime
import json
from pathlib import Path
import re
import tempfile
import time

import psutil
try:
    from browser_lifecycle import alive
except ModuleNotFoundError:
    from scripts.browser_lifecycle import alive


def profile_of(args):
    return next((a.split('=',1)[1] for a in args if a.startswith('--user-data-dir=')), '')


def legacy_root(proc):
    try:
        args=proc.cmdline();profile=Path(profile_of(args))
        return (proc.name().lower() in ('msedge.exe','chrome.exe') and '--headless' in args
                and not any(a.startswith('--type=') for a in args)
                and re.fullmatch(r'gbox-(?:tk|72)-[A-Za-z0-9]+',profile.name)
                and profile.resolve().parent == Path(tempfile.gettempdir()).resolve()
                and proc.username() == psutil.Process().username())
    except (psutil.Error,OSError):return False


def parent_gone(proc):
    try:return psutil.Process(proc.ppid()).create_time()>proc.create_time()
    except psutil.NoSuchProcess:return True
    except psutil.AccessDenied:return False


def inventory():
    trees=[];edge=[]
    for proc in psutil.process_iter():
        try:
            if proc.name().lower()=='msedge.exe':edge.append(proc)
            if not legacy_root(proc):continue
            members=[proc]+proc.children(recursive=True)
            rows=[]
            for member in members:
                try:rows.append({'pid':member.pid,'created':member.create_time(),'ppid':member.ppid(),
                                 'rss':member.memory_info().rss,'handles':member.num_handles() if hasattr(member,'num_handles') else member.num_fds()})
                except psutil.Error:pass
            trees.append({'pid':proc.pid,'created':proc.create_time(),'parent_pid':proc.ppid(),
                          'profile':profile_of(proc.cmdline()),'exe':proc.exe(),'orphan':parent_gone(proc),'members':rows})
        except psutil.Error:pass
    rss=handles=0
    for p in edge:
        try:rss+=p.memory_info().rss;handles+=p.num_handles() if hasattr(p,'num_handles') else p.num_fds()
        except psutil.Error:pass
    return {'captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'edge_processes':len(edge),
            'edge_rss_bytes':rss,'edge_handles':handles,'legacy_sessions':len(trees),'confirmed_orphans':sum(t['orphan'] for t in trees),'trees':trees}


def close_orphans(report):
    outcomes=[]
    for tree in report['trees']:
        root=psutil.Process(tree['pid']) if alive(tree['pid'],tree['created']) else None
        if not root or not legacy_root(root) or not parent_gone(root) or root.exe()!=tree['exe']:
            outcomes.append({'pid':tree['pid'],'result':'skipped: identity or orphan status changed'});continue
        # Take a current snapshot, stop the validated browser root first, then
        # only its same-profile descendants using creation times (PID reuse safe).
        members=[root]+root.children(recursive=True)
        identities=[]
        for p in members:
            try:
                if p.exe()==tree['exe'] and profile_of(p.cmdline())==tree['profile']:
                    identities.append((p.pid,p.create_time()))
            except psutil.Error:pass
        stopped=[]
        for pid,created in identities:
            if not alive(pid,created):continue
            try:
                p=psutil.Process(pid)
                if p.exe()==tree['exe'] and profile_of(p.cmdline())==tree['profile']:
                    p.terminate();stopped.append(p)
            except psutil.NoSuchProcess:pass
        _,remaining=psutil.wait_procs(stopped,timeout=5)
        outcomes.append({'pid':tree['pid'],'stopped':len(stopped),'remaining':[p.pid for p in remaining],
                         'profile_preserved':tree['profile']})
    return outcomes


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--close-orphans',action='store_true');ap.add_argument('--out',type=Path)
    args=ap.parse_args();before=inventory();result={'before':before}
    if args.close_orphans:result.update(cleanup=close_orphans(before),after=inventory())
    if args.out:args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2))
    print(json.dumps({k:({x:y for x,y in v.items() if x!='trees'} if isinstance(v,dict) else v) for k,v in result.items()}))
