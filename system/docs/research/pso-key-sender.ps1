# A persistent keyboard sender: reads one SendKeys combo per line from stdin, focuses the game window, sends it.
# Started once by the Python driver so each press costs a pipe write instead of a process spawn.
param([long]$Hwnd = 0)
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class KeySend {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@
[Console]::Out.WriteLine('ready')
[Console]::Out.Flush()
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    if ($line -eq 'QUIT') { break }
    if ($Hwnd -ne 0) {
        $h = [IntPtr]$Hwnd
        [KeySend]::ShowWindow($h, 9) | Out-Null
        [KeySend]::SetForegroundWindow($h) | Out-Null
        Start-Sleep -Milliseconds 40
    }
    try {
        [System.Windows.Forms.SendKeys]::SendWait($line)
        [Console]::Out.WriteLine('ok')
    } catch {
        [Console]::Out.WriteLine('err ' + $_.Exception.Message)
    }
    [Console]::Out.Flush()
}
