import hashlib,json,shutil,time
from pathlib import Path

root=Path('/home/ehm_eckx/gBox/system')
stage=root/'gbox-data/mercs-final-check'
paths=json.loads((stage/'manifest.json').read_text(encoding='utf-8-sig'))
stamp=time.strftime('%Y%m%d-%H%M%S',time.gmtime())
backup=root/'gbox-data/deploy-backups'/('mercs-learning-'+stamp)
backup.mkdir(parents=True)
receipt={'at':stamp,'backup':str(backup),'files':[]}
for rel in paths:
    target=root/rel; source=stage/rel
    if not target.resolve().is_relative_to(root.resolve()):raise ValueError('Invalid target')
    if source.suffix=='.py':compile(source.read_bytes(),str(source),'exec')
    if source.suffix=='.json':json.loads(source.read_text(encoding='utf-8-sig'))
for rel in paths:
    target=root/rel;source=stage/rel
    before=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    after=hashlib.sha256(source.read_bytes()).hexdigest()
    if before==after:continue
    if target.exists():
        saved=backup/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix(target.suffix+'.learning-new')
    shutil.copyfile(source,temp);temp.replace(target)
    receipt['files'].append({'path':rel,'before':before,'sha256':after})
(root/'gbox-data/re5-learning-deployment.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps({'deployed':len(receipt['files']),'backup':str(backup)}))
