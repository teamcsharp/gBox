import json,sys
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
from gbox.desktop_local import local_config,installation_key
from gbox.desktop_supervisor import install
config=Path('C:/_tools/gBox/system/gbox.toml')
cfg=local_config(config)
assert installation_key(config,cfg)=='2141adfbccd2e0d6e91a1f2f3b61913184cfe0ae555117619ed48ad477624670'
print(json.dumps(install(cfg,config,Path('C:/_tools/gBox/system'),opt_in=True)),flush=True)
