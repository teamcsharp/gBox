"""Select an existing full JDK for local analysis without installing or changing host settings."""
import os
from pathlib import Path
import re
import shutil

def valid_java_home(path):
    if not path:return False
    home=Path(path)
    suffix='.exe' if os.name=='nt' else ''
    if not all((home/'bin'/(tool+suffix)).is_file() for tool in ('java','javac')):
        return False
    try:
        with (home/'release').open(encoding='utf-8') as stream:
            release=stream.read(65537)
    except (OSError,UnicodeError):
        return False
    if len(release)>65536:return False
    version=re.search(r'^JAVA_VERSION="(\d+)',release,re.M)
    arch=re.search(r'^OS_ARCH="([^"]+)"',release,re.M)
    return bool(version and int(version[1])>=21 and arch and arch[1].lower() in
                {'amd64','x86_64','aarch64','arm64','ppc64','ppc64le','s390x','riscv64'})

def apply_java_home(config,env):
    """Keep explicit configuration and valid inherited JDKs; repair stale inherited paths.

    Missing local dependencies remain unavailable. No download, process restart,
    global environment mutation, or persistent configuration change occurs.
    """
    if 'JAVA_HOME' in config.rea_env or valid_java_home(env.get('JAVA_HOME')):
        return env
    from .provision import jdk21
    candidates=[jdk21(config)]
    candidates.extend(sorted(config.runtime.glob('jdk-*'),reverse=True)[:64])
    if javac:=shutil.which('javac'):
        candidates.append(Path(javac).resolve().parent.parent)
    for home in candidates:
        if home and valid_java_home(home):
            env['JAVA_HOME']=str(Path(home).resolve())
            break
    return env
