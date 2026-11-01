$ErrorActionPreference = 'Stop'
$taskName = 'GBox Owned Renderer Refresh 20261030'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Refresh task already exists; inspect before replacing' }
$python = 'C:\Users\maste\AppData\Local\gbox\venv\Scripts\pythonw.exe'
$action = New-ScheduledTaskAction -Execute $python -Argument '-I C:\_tools\gBox\.scratch-i9-renderer-refresh-20261030.py' -WorkingDirectory 'C:\_tools\gBox'
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Description 'One-shot owned GBox F5 to activate the PiP renderer fix' | Out-Null
try {
 Start-ScheduledTask -TaskName $taskName
 Start-Sleep -Seconds 3
 $deadline = [DateTime]::UtcNow.AddSeconds(10)
 while ((Get-ScheduledTask -TaskName $taskName).State -eq 'Running' -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 250 }
 Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastTaskResult,LastRunTime | ConvertTo-Json -Compress
 Get-Content -LiteralPath 'C:\_tools\gBox\.scratch-i9-renderer-refresh-20261030.receipt.json'
} finally {
 if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Running') { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
}
