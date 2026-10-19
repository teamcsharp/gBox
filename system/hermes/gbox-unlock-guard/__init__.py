"""Bootstrap the reviewed guard from the repository this plugin links to."""
from pathlib import Path
import hashlib
import sys

_LOADED = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
           for name in ('__init__.py', 'plugin.yaml')}


def register(ctx):
    system = str(Path(__file__).resolve().parents[2])
    if system not in sys.path:
        sys.path.insert(0, system)
    from gbox.hermes_unlock_guard import register as install_hook
    install_hook(ctx, bootstrap=_LOADED)
