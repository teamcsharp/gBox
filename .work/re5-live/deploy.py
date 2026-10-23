"""Backed-up, explicit deployment of the RE5 changes. Run on the Spark with a staged payload."""
import hashlib, json, shutil, sys, time
from pathlib import Path

root=Path('/home/ehm_eckx/gBox/system')
payload=root/'gbox-data/re5-deployment-payload'
manifest=json.loads((payload/'manifest.json').read_text())
stamp=time.strftime('%Y%m%d-%H%M%S',time.gmtime())
backup=root/'gbox-data/deploy-backups'/('re5-navigation-'+stamp)
backup.mkdir(parents=True)
receipt={'at':stamp,'files':[],'backup':str(backup)}
for rel in manifest:
    source=payload/rel
    target=root/rel
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Invalid deployment path')
    if source.suffix=='.py':
        compile(source.read_bytes(),str(source),'exec')
    if target.exists():
        saved=backup/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix(target.suffix+'.re5-new')
    shutil.copyfile(source,temp);temp.replace(target)
    receipt['files'].append({'path':rel,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
(root/'gbox-data/re5-deployment-receipt.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
