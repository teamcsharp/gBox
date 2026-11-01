# Fixed app-owned operation. No renderer-supplied command, path, address, user or key.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$stage = 20
$owned = $false
$mutex = New-Object System.Threading.Mutex($false, 'Global\gBox.OpenSSH.Setup')
try {
    try { $owned = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
    if (!$owned) { exit 25 }
    $expected = Join-Path $env:SystemRoot 'System32\OpenSSH\sshd.exe'
    $service = Get-CimInstance Win32_Service -Filter "Name='sshd'"
    if ($service) {
        $command = [Environment]::ExpandEnvironmentVariables($service.PathName).Trim()
        if ($command -ne $expected -and $command -ne ('"' + $expected + '"')) { exit 26 }
    } else {
        $stage = 21
        $defaultExisted = [bool](Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)
        try {
            $capability = Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
        } finally {
            # Windows may create a broad default rule while installing. Narrow only the
            # newly created rule before starting sshd; leave pre-existing operator rules alone.
            if (!$defaultExisted -and (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
                Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -Profile Private,Domain -RemoteAddress LocalSubnet -Program $expected | Out-Null
            }
        }
        if ($capability.RestartNeeded) { exit 27 }
        $service = Get-CimInstance Win32_Service -Filter "Name='sshd'"
        if (!$service) { exit 21 }
        $command = [Environment]::ExpandEnvironmentVariables($service.PathName).Trim()
        if ($command -ne $expected -and $command -ne ('"' + $expected + '"')) { exit 26 }
    }
    $stage = 22
    $rule = Get-NetFirewallRule -Name 'gBox-OpenSSH-LAN' -ErrorAction SilentlyContinue
    if ($rule -and $rule.Group -ne 'gBox.OpenSSH') { exit 28 }
    if ($rule) {
        Set-NetFirewallRule -Name 'gBox-OpenSSH-LAN' -Enabled True -Direction Inbound -Action Allow -Profile Private,Domain -RemoteAddress LocalSubnet -Protocol TCP -LocalPort 22 -Program $expected | Out-Null
    } else {
        New-NetFirewallRule -Name 'gBox-OpenSSH-LAN' -DisplayName 'gBox OpenSSH (local subnet)' -Group 'gBox.OpenSSH' -Enabled True -Direction Inbound -Action Allow -Profile Private,Domain -RemoteAddress LocalSubnet -Protocol TCP -LocalPort 22 -Program $expected | Out-Null
    }
    $stage = 23
    if ($service.StartMode -eq 'Disabled') { Set-Service -Name sshd -StartupType Manual }
    Start-Service -Name sshd
    (Get-Service -Name sshd).WaitForStatus('Running', [TimeSpan]::FromSeconds(15))
    exit 0
} catch { exit $stage }
finally { if ($owned) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
