$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
    $service = Get-CimInstance Win32_Service -Filter "Name='sshd'"
    $expected = Join-Path $env:SystemRoot 'System32\OpenSSH\sshd.exe'
    $builtin = $false
    if ($service) {
        $command = [Environment]::ExpandEnvironmentVariables($service.PathName).Trim()
        $builtin = $command -eq $expected -or $command -eq ('"' + $expected + '"')
    }
    $listening = $false
    $reachable = $false
    if ($service -and $service.State -eq 'Running') {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 22 -ErrorAction SilentlyContinue |
            Where-Object OwningProcess -eq $service.ProcessId)
        $listening = $listeners.Count -gt 0
        if ($listening) {
            $client = New-Object System.Net.Sockets.TcpClient
            try { $reachable = $client.ConnectAsync('127.0.0.1', 22).Wait(1000) -and $client.Connected }
            catch { $reachable = $false }
            finally { $client.Dispose() }
        }
    }
    $firewall = 'unknown'
    try {
        $rule = Get-NetFirewallRule -Name 'gBox-OpenSSH-LAN' -ErrorAction SilentlyContinue
        if (!$rule) { $firewall = 'missing' }
        elseif ($rule.Group -ne 'gBox.OpenSSH') { $firewall = 'name_conflict' }
        else {
            $address = @($rule | Get-NetFirewallAddressFilter).RemoteAddress
            $port = $rule | Get-NetFirewallPortFilter
            $application = $rule | Get-NetFirewallApplicationFilter
            $profile = [int]$rule.Profile
            if ($rule.Enabled -eq 'True' -and $rule.Direction -eq 'Inbound' -and $rule.Action -eq 'Allow' -and
                $profile -eq 3 -and @($address).Count -eq 1 -and $address -eq 'LocalSubnet' -and
                $port.Protocol -eq 'TCP' -and $port.LocalPort -eq '22' -and
                [Environment]::ExpandEnvironmentVariables($application.Program) -eq $expected) { $firewall = 'scoped' }
            else { $firewall = 'needs_setup' }
        }
    } catch { $firewall = 'unknown' }
    @{ installed = [bool]$service; builtin = [bool]$builtin; running = [bool]($service -and $service.State -eq 'Running');
       listening = $listening; reachable = [bool]$reachable; firewall = $firewall;
       startup_type = $(if ($service) { [string]$service.StartMode } else { '' }) } | ConvertTo-Json -Compress
} catch { exit 1 }
