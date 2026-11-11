# Target ONE Dolphin window by PID: focus it, load the saved state (F1 = slot 1), capture that window only.
param([int]$TargetPid = 52376, [string]$Keys = '{F1}', [string]$Tag = 'live-f1')
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class Win5 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
$proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
if (-not $proc) { Write-Host "pid $TargetPid not running"; exit 1 }
$h = $proc.MainWindowHandle
Write-Host "pid $TargetPid hwnd $h title: $($proc.MainWindowTitle)"
[Win5]::ShowWindow($h, 9) | Out-Null
[Win5]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 600
if ([Win5]::GetForegroundWindow() -ne $h) { Write-Host 'not foreground; stopping'; exit 2 }
Write-Host "sending $Keys"
[System.Windows.Forms.SendKeys]::SendWait($Keys)
Start-Sleep -Seconds 5
$r = New-Object Win5+RECT
[Win5]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
if ($w -le 0) { Write-Host 'no window size'; exit 3 }
$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.Left, $r.Top, 0, 0, (New-Object System.Drawing.Size $w, $ht)); $g.Dispose()
$bmp.Save("D:\gBox\pso-ds\demo\$Tag.png", [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
Write-Host "captured $Tag.png"
