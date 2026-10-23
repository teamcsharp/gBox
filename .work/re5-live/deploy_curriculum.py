import json,hashlib,shutil,time
from pathlib import Path
root=Path('/home/ehm_eckx/gBox/system')
stage=root/'gbox-data/mercs-upgrade-check'
manifest=json.loads((stage/'deploy-manifest.json').read_text(encoding='utf-8-sig'))
backup=root/'gbox-data/deploy-backups'/('mercs-curriculum-'+time.strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
for row in manifest:
 target=root/row['path'];source=stage/row['path']
 if row.get('expected') and (not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=row['expected']):
  raise ValueError('Live file changed since audit: '+row['path'])
 if row.get('new') and target.exists():raise ValueError('Unexpected existing file: '+row['path'])
 if source.suffix=='.py':compile(source.read_bytes(),str(source),'exec')
for row in manifest:
 target=root/row['path'];source=stage/row['path']
 if target.exists():
  saved=backup/row['path'];saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
 target.parent.mkdir(parents=True,exist_ok=True)
 tmp=target.with_suffix(target.suffix+'.mercs-new');shutil.copyfile(source,tmp);tmp.replace(target)
# Keep all other live adapter changes; add only the tested boot-hook call in the Linux RPCS3 class.
target=root/'gbox/adapters.py';text=target.read_text();start=text.index('class RPCS3LinuxAdapter(')
section=text[start:]
if 're5_hooks.install(d)' not in section:
 at=text.index('        d = self.home\n',start)+len('        d = self.home\n')
 changed=text[:at]+'        from .mercs.titles import re5_hooks\n        re5_hooks.install(d)\n'+text[at:]
 compile(changed,str(target),'exec');shutil.copy2(target,backup/'adapters.py')
 target.write_text(changed)
receipt={'backup':str(backup),'files':[r['path'] for r in manifest],'adapter_change':'exact-build boot hook only'}
(root/'gbox-data/mercs-curriculum-deployment.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
