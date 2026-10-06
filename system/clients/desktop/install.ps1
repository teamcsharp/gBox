# Install the G-Box desktop app on this PC.
# Electron is installed locally (%LOCALAPPDATA%\gbox\desktop); the app code runs from this checkout
# (the Spark share or a GitHub clone), so `git pull` updates are live on next launch.
# Creates Desktop + Start Menu shortcuts.
param([string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath)
$ErrorActionPreference = "Stop"
$Repo = [IO.Path]::GetFullPath($Repo)                                   # normalize ..\.. so the root (gBox.exe) resolves
$Home_ = Join-Path $env:LOCALAPPDATA "gbox\desktop"
New-Item -ItemType Directory -Force $Home_ | Out-Null

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
Push-Location $Home_
if (-not (Test-Path package.json)) { '{"name":"gbox-desktop-runtime","private":true}' | Out-File -Encoding ascii package.json }
npm install --no-audit --no-fund electron@38 | Out-Host
Pop-Location
$Dist = Join-Path $Home_ "node_modules\electron\dist"
if (-not (Test-Path (Join-Path $Dist "electron.exe"))) { throw "electron install failed: $Dist\electron.exe missing" }

# Branded runtime: a copy of Electron named gBox.exe with the G-Box icon + version strings, so Task Manager,
# the volume mixer, the taskbar and its right-click menu all say "G-Box" (not "Electron").
$AppDir = Join-Path $env:LOCALAPPDATA "gbox\app"
New-Item -ItemType Directory -Force $AppDir | Out-Null
robocopy $Dist $AppDir /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
Move-Item -Force (Join-Path $AppDir "electron.exe") (Join-Path $AppDir "gBox.exe")
$Rcedit = Join-Path $env:LOCALAPPDATA "gbox\tools\rcedit-x64.exe"
if (-not (Test-Path $Rcedit)) { New-Item -ItemType Directory -Force (Split-Path $Rcedit) | Out-Null
  Invoke-WebRequest "https://github.com/electron/rcedit/releases/latest/download/rcedit-x64.exe" -OutFile $Rcedit }
$Ico = Join-Path $Repo "assets\brand\gbox.ico"
& $Rcedit (Join-Path $AppDir "gBox.exe") --set-icon $Ico --set-version-string FileDescription "G-Box" --set-version-string ProductName "G-Box" `
  --set-version-string CompanyName "G-Box" --set-version-string InternalName "gBox" --set-version-string OriginalFilename "gBox.exe"
$Electron = Join-Path $AppDir "gBox.exe"

$App = Join-Path $Repo "clients\desktop"
$Exe = Join-Path (Split-Path $Repo -Parent) "gBox.exe"                 # root launcher (root = gBox.exe + system\)
$Shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    $lnk = $Shell.CreateShortcut((Join-Path $dir "G-Box.lnk"))
    if (Test-Path $Exe) { $lnk.TargetPath = $Exe; $lnk.Arguments = "" } else { $lnk.TargetPath = $Electron; $lnk.Arguments = "`"$App`"" }
    $lnk.WorkingDirectory = $Home_
    $lnk.Description = "G-Box"
    $lnk.IconLocation = (Join-Path $Repo "assets\brand\gbox.ico")
    $lnk.Save()
}
Write-Output "Installed. Electron: $Electron  App: $App"
