$ErrorActionPreference = 'Stop'
$names = @('python.exe','pythonw.exe','git.exe','git-remote-https.exe','electron.exe','azahar.exe','lime3ds.exe','node.exe','cmd.exe')
$rows = Get-CimInstance Win32_Process | Where-Object { $_.Name -in $names }
foreach ($row in $rows) {
  $p = Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
  $waits = @($p.Threads | ForEach-Object { if ($_.ThreadState -eq 'Wait') { $_.WaitReason.ToString() } else { $_.ThreadState.ToString() } } | Group-Object | ForEach-Object { "$($_.Name):$($_.Count)" })
  [pscustomobject]@{pid=$row.ProcessId;parent=$row.ParentProcessId;name=$row.Name;path=$row.ExecutablePath;created=$row.CreationDate.ToString('o');cpu=$p.CPU;session=$p.SessionId;threads=$waits} | ConvertTo-Json -Compress
}
Get-ChildItem 'D:\gBox\runtime' -Force | Select-Object Name,LastWriteTime | ConvertTo-Json -Compress
Get-ScheduledTask | Where-Object { $_.TaskName -match 'gbox' } | Select-Object TaskName,State,TaskPath | ConvertTo-Json -Compress
