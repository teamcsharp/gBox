Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class GBoxPipCapture {
[StructLayout(LayoutKind.Sequential)] public struct Rect {public int Left,Top,Right,Bottom;}
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out Rect r);
[DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h,IntPtr dc,uint flags);
}
"@
$client=Get-Process -Id 13132 -ErrorAction Stop
$rect=New-Object GBoxPipCapture+Rect
if(-not [GBoxPipCapture]::GetWindowRect($client.MainWindowHandle,[ref]$rect)){throw 'Cannot read gBox window'}
$bmp=New-Object Drawing.Bitmap ($rect.Right-$rect.Left),($rect.Bottom-$rect.Top)
$graphics=[Drawing.Graphics]::FromImage($bmp)
$dc=$graphics.GetHdc()
try {$captured=[GBoxPipCapture]::PrintWindow($client.MainWindowHandle,$dc,2)} finally {$graphics.ReleaseHdc($dc)}
if($captured){$bmp.Save('C:\_tools\gBox\.work\re5-live\pip-client.png',[Drawing.Imaging.ImageFormat]::Png)}
$graphics.Dispose();$bmp.Dispose()
Write-Output "gBox capture=$captured bounds=$($rect.Right-$rect.Left)x$($rect.Bottom-$rect.Top)"
