import json,sys
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
from gbox.desktop_local import local_config
from gbox.desktop_supervisor import directory
cfg=local_config('C:/_tools/gBox/system/gbox.toml')
p=directory(cfg)/'health.json'
print(json.dumps(json.loads(p.read_text()) if p.exists() else {'missing':True}))
