# gBox standalone (a decanted package): "Install gBox.cmd" and "Start gBox.cmd" call this.
#   install  get a Python 3.11+ (one already here, else uv from astral.sh's GitHub releases + its managed Python), open the wizard
#   start    the desktop app (Electron in .tools\electron) on this PC's control plane, else the control plane + the browser UI
# Everything lives inside the package / install folder (.tools, .venv): nothing goes into %LOCALAPPDATA%\gbox.
param([Parameter(Position = 0)][string]$Mode = "install", [int]$Port = 8770, [int]$ApiPort = 0, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$Sys = Split-Path -Parent $PSScriptRoot                 # ...\system
$Pkg = Split-Path -Parent $Sys                          # the package / install root
$Tools = Join-Path $Pkg ".tools"
New-Item -ItemType Directory -Force $Tools | Out-Null
$env:UV_CACHE_DIR = Join-Path $Tools "uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
$env:PYTHONPATH = $Sys
$env:PYTHONUTF8 = "1"

function Test-Py([string]$exe, [string[]]$pre = @()) {
    try { $v = & $exe @pre -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')" 2>$null; if ($LASTEXITCODE -eq 0 -and $v) { return "$v".Trim() } } catch {}
    return $null
}

function Find-OwnPython {                                # a Python that belongs to this folder (uv-managed in .tools\python)
    $own = Get-ChildItem (Join-Path $Tools "python") -Filter python.exe -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($own) { return Test-Py $own.FullName }
    return $null
}

function Find-SystemPython {                             # offline fallback: a Python 3.11+ already on this PC
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in "-3.13", "-3.12", "-3.11") { if ($p = Test-Py "py" @($v)) { return $p } }
    }
    foreach ($c in Get-Command python, python3 -All -ErrorAction SilentlyContinue) {
        if ($c.Source -like "*WindowsApps*") { continue }      # the Microsoft Store stub, not a Python
        if ($p = Test-Py $c.Source) { return $p }
    }
    return $null
}

function Find-Uv {
    $own = Join-Path $Tools "uv\uv.exe"
    if (Test-Path $own) { return $own }
    $c = Get-Command uv -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

if ($Mode -eq "install") {
    Write-Host "gBox setup" -ForegroundColor Cyan
    # gBox brings its own Python (uv-managed, inside .tools\python) so every install is the same; a Python already on
    # this PC is only used when there is no network to fetch one.
    $py = Find-OwnPython
    if (-not $py) {
        $uv = Find-Uv
        if (-not (Test-Path (Join-Path $Tools "uv\uv.exe"))) {
            Write-Host "Getting uv (astral.sh, official GitHub release) to install Python inside this folder..."
            $zip = Join-Path $Tools "uv.zip"
            try {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip -UseBasicParsing
                Expand-Archive $zip (Join-Path $Tools "uv") -Force
                Remove-Item $zip
                $uv = Join-Path $Tools "uv\uv.exe"
            } catch { Write-Host "  (no network: $($_.Exception.Message))" }
        }
        if ($uv) {
            Write-Host "Installing Python 3.12 (uv-managed, inside $Tools\python)..."
            & $uv python install 3.12 --no-bin --no-registry      # nothing outside this folder: no shims, no registry entries
            if ($LASTEXITCODE -eq 0) { $py = Find-OwnPython }
        }
        if (-not $py) { $py = Find-SystemPython }
        if (-not $py) {
            Write-Host ""
            Write-Host "No network and no Python 3.11+ on this PC." -ForegroundColor Yellow
            Write-Host "Offline: put uv.exe into $Tools\uv\ (github.com/astral-sh/uv releases) with a network once, or install Python 3.11+, then run Install gBox.cmd again."
            exit 1
        }
    }
    Write-Host "Python: $py"
    $a = @("-m", "gbox.wizard", "--port", "$Port")
    if ($ApiPort) { $a += @("--api-port", "$ApiPort") }
    if ($NoBrowser) { $a += "--no-browser" }
    Set-Location $Sys
    Write-Host "Opening the setup wizard: http://127.0.0.1:$Port/  (keep this window open while you set up)"
    & $py @a
    exit $LASTEXITCODE
}

if ($Mode -eq "start") {
    $py = Join-Path $Pkg ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { Write-Host "gBox isn't installed in this folder yet: running the setup first."; & (Join-Path $Pkg "Install gBox.cmd"); exit $LASTEXITCODE }
    $cfg = Join-Path $Sys "gbox.toml"
    $env:GBOX_CONFIG = $cfg
    $apiPort = "$(& $py -P -c "from gbox import config; print(config.load(r'$cfg').api_port)")".Trim()
    $url = "http://127.0.0.1:$apiPort"
    $electron = Get-ChildItem (Join-Path $Tools "electron") -Filter "electron.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($electron) {
        $env:GBOX_STANDALONE_HOME = $Pkg
        $env:GBOX_API_URL = $url
        Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
        Start-Process $electron.FullName -ArgumentList "`"$(Join-Path $Sys 'clients\desktop')`"" -WorkingDirectory $electron.DirectoryName
        exit 0
    }
    $up = $false
    try { Invoke-WebRequest "$url/api/health" -UseBasicParsing -TimeoutSec 3 | Out-Null; $up = $true } catch {}
    if (-not $up) {
        $log = Join-Path $Sys "gbox-data\serve.log"
        New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
        Start-Process $py -ArgumentList @("-P", "-m", "gbox", "--config", "`"$cfg`"", "serve", "--worker") -WorkingDirectory $Sys -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError "$log.err"
        foreach ($i in 1..60) { Start-Sleep 1; try { Invoke-WebRequest "$url/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; $up = $true; break } catch {} }
        if (-not $up) { Write-Host "gBox did not start: see $log" -ForegroundColor Red; exit 1 }
    }
    $tok = (Get-Content (Join-Path $Sys "gbox-data\api_token") -Raw).Trim()
    Start-Process "$url/#token=$tok"
    exit 0
}
Write-Host "usage: standalone.ps1 install|start"
exit 1
