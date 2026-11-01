import json,subprocess
from pathlib import Path
import psutil
gpu=subprocess.check_output(['powershell','-NoProfile','-Command','Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json -Compress'],text=True)
print('gpu',gpu.strip())
for process in psutil.process_iter(['pid','name','exe','cmdline']):
    if process.pid != 44952:continue
    row=process.info;print('emulator',row['pid'],row['exe'])
    args=row['cmdline'] or [];paths=[]
    for i,arg in enumerate(args):
        if arg in ('-c','--config','--appendconfig') and i+1<len(args):paths.extend(args[i+1].split('|'))
    if row['exe']:paths.append(str(Path(row['exe']).parent/'retroarch.cfg'))
    for path in dict.fromkeys(paths):
        p=Path(path)
        if not p.is_file():continue
        data=p.read_text(errors='replace').splitlines()
        selected=[s for s in data if s.startswith(('video_driver ', 'video_threaded ', 'video_vsync ', 'video_shader_enable ', 'video_max_swapchain_images ', 'input_poll_type_behavior ', 'core_options_path '))]
        print('config',str(p),json.dumps(selected))
        for s in data:
            if s.startswith('core_options_path = '):
                core=Path(s.split('=',1)[1].strip().strip('"'))
                if core.is_file():print('core',json.dumps([x for x in core.read_text(errors='replace').splitlines() if any(k in x.lower() for k in ('citra','vulkan','shader'))]))
