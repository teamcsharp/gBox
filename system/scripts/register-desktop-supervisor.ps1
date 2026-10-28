param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Config,
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$Installation
)
$ErrorActionPreference = 'Stop'
foreach ($value in @($Python, $Config, $Root)) {
    if ($value.Contains('"') -or $value.Contains("`r") -or $value.Contains("`n")) { throw 'Invalid fixed recovery path' }
    if (-not [IO.Path]::IsPathRooted($value) -or $value.StartsWith('\\')) { throw 'Recovery paths must be local absolute paths' }
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or -not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    throw 'Installed GBox interpreter or config is missing'
}
$taskName = 'GBox Recovery ' + $Installation.Substring(0, 16)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script = Join-Path $Root 'gbox\desktop_supervisor.py'
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw 'Fixed GBox recovery script is missing' }
$arguments = '-P "' + $script + '" --config "' + $Config + '"'
$action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'Opt-in outbound GBox recovery for this user and installation; no listener or arbitrary commands.' -Force | Out-Null
# Refresh its code on rebuild too; this task owns no game or desktop processes.
if ((Get-ScheduledTask -TaskName $taskName).State -eq 'Running') {
    Stop-ScheduledTask -TaskName $taskName
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ((Get-ScheduledTask -TaskName $taskName).State -eq 'Running') {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'The previous recovery supervisor did not stop' }
        Start-Sleep -Milliseconds 250
    }
}
Start-ScheduledTask -TaskName $taskName
Write-Output 'GBox recovery task registered and started.'
