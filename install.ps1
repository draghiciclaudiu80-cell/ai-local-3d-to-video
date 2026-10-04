# install.ps1 - AI Local (beta), from GitHub: sets everything up from the internet, IN THIS FOLDER.
#   Double-click INSTALL.cmd (it runs this). Downloads Python (via uv), the app's packages, the engines and the models
#   from their official sites - every file checked by its SHA-256 - builds the starter "Local AI.exe" with Windows' own
#   C# compiler, makes the shortcuts and starts the app. Nothing is installed into Windows except Microsoft's Visual
#   C++ runtime (if it's missing). About 8 GB for the basics. Run it again any time: it goes on where it stopped.
#   Options: -Optional "print,cad,sound" (or "none") instead of asking, -Quiet, -NoStart
param([switch]$Quiet, [string]$Optional = "ask", [switch]$NoStart, [switch]$SkipDownloads, [switch]$NoShortcuts)  # the last two: for tests
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # PowerShell's progress bar makes downloads ~10x slower
$App = $PSScriptRoot
$E = Join-Path $App "engines"
$Host.UI.RawUI.WindowTitle = "Setting up AI Local"
function Say($t, $c = "Gray") { Write-Host $t -ForegroundColor $c }
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Die($t) { Say "`nSTOPPED: $t" Red; Say "Run INSTALL.cmd again - it goes on where it stopped." Yellow; if (-not $Quiet) { Read-Host "Press Enter to close" | Out-Null }; exit 1 }
function Ask($q, $def) { if ($Quiet) { return $def }; $a = Read-Host $q; if ([string]::IsNullOrWhiteSpace($a)) { return $def }; return $a.Trim().ToLower() }
function Get-Checked($url, $out, $sha) {
    for ($i = 1; $i -le 3; $i++) {
        try { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing } catch { Say "  try $i failed: $($_.Exception.Message)" Yellow; Start-Sleep -Seconds (3 * $i); continue }
        if ((Get-FileHash $out -Algorithm SHA256).Hash.ToLower() -eq $sha) { return }
        Say "  the download didn't match its checksum - trying again" Yellow
    }
    Die "couldn't download $url"
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Say "`n=== AI Local (beta) - setup ===" Green
Say "Everything runs on this PC: chat, voice, pictures, videos, 3D designs. Nothing you type leaves it.`n"

# ---------------------------------------------------------------- this PC
if (-not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Version.Major -lt 10) { Die "AI Local needs 64-bit Windows 10 or 11." }
$drive = Get-PSDrive -Name $App.Substring(0, 1)
$freeGB = [math]::Floor($drive.Free / 1GB)
if ($freeGB -lt 12) { Die "only $freeGB GB free on this drive - AI Local needs about 12 GB (17 GB with the sound effects)." }
if ($App -like "*OneDrive*") { Say "Note: this folder is inside OneDrive, which would upload ~8 GB - a normal folder (e.g. C:\AI Local) is better." Yellow }
if ($App -match "[^\x20-\x7E]") { Say "Note: the folder's name has special letters - if something fails, use a plain one (e.g. C:\AI-Local)." Yellow }

$groups = @("core")
if ($Optional -eq "ask") {
    Say "The basics are about 8 GB. Optional parts (you can add them later by running INSTALL.cmd again):"
    if ((Ask "  3D printing - OrcaSlicer, G-code for your printer (0.2 GB)? [Y/n]" "y") -ne "n") { $groups += "print" }
    if ((Ask "  exact CAD parts - FreeCAD, STEP files (0.4 GB)? [y/N]" "n") -eq "y") { $groups += "cad" }
    if ((Ask "  sound effects for videos (4.3 GB)? [y/N]" "n") -eq "y") { $groups += "sound" }
} elseif ($Optional -ne "none") { $groups += $Optional.Split(",") | ForEach-Object { $_.Trim() } }

# ---------------------------------------------------------------- 1) Microsoft's Visual C++ runtime
Step "1/7  Windows parts (Microsoft Visual C++ runtime)"
$vc = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" -ErrorAction SilentlyContinue
if (-not $vc -or $vc.Installed -ne 1) {
    $f = Join-Path $env:TEMP "vc_redist.x64.exe"
    Invoke-WebRequest "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $f -UseBasicParsing
    if ((Get-AuthenticodeSignature $f).Status -ne "Valid") { Die "the Visual C++ runtime download isn't signed by Microsoft" }
    Say "  installing it - Windows asks for permission once"
    Start-Process $f -ArgumentList "/install", "/quiet", "/norestart" -Verb RunAs -Wait
} else { Say "  already on this PC" }

# ---------------------------------------------------------------- 2) uv + Python 3.11 (in engines\python)
Step "2/7  Python 3.11 (the app's own - the PC's Python, if any, is not touched)"
$dl = Join-Path $App "downloads"
New-Item -ItemType Directory -Force $dl, $E | Out-Null
$UV = Join-Path $dl "uv\uv.exe"
if (-not (Test-Path $UV)) {
    $z = Join-Path $dl "uv.zip"
    Get-Checked "https://github.com/astral-sh/uv/releases/download/0.11.29/uv-x86_64-pc-windows-msvc.zip" $z "a047d55651bc3e0ca24595b25ec4cfcb10f9dca9fb56514e661269b37d4fae68"
    Expand-Archive $z (Join-Path $dl "uv") -Force
    Remove-Item $z
}
$tmp = Join-Path ([IO.Path]::GetTempPath()) "ai-local-uv"   # SHORT paths: packages without a Windows build are compiled
$env:UV_CACHE_DIR = Join-Path $tmp "cache"                  # there, and a deep folder broke Windows' 260-character limit
$env:UV_PYTHON_INSTALL_DIR = Join-Path $tmp "python"
$PY = Join-Path $E "python\python.exe"
if (-not (Test-Path $PY)) {
    & $UV python install 3.11.15 --no-bin
    if ($LASTEXITCODE) { Die "Python 3.11 wasn't installed" }
    $src = Get-ChildItem $env:UV_PYTHON_INSTALL_DIR -Directory | Where-Object { $_.Name -like "cpython-3.11.15-windows-x86_64*" } | Select-Object -First 1
    if (-not $src) { Die "Python 3.11 wasn't found after installing it" }
    if (Test-Path (Join-Path $E "python")) { Remove-Item -Recurse -Force (Join-Path $E "python") }
    Move-Item $src.FullName (Join-Path $E "python")
}
& $PY -c "import sys, ssl, sqlite3, lzma; print('  Python', sys.version.split()[0])"
if ($LASTEXITCODE) { Die "the app's Python doesn't start" }

# ---------------------------------------------------------------- 3) Python packages (their own environments)
Step "3/7  Python packages: the app, Laya, the robot-arm tool$(if ($groups -contains 'sound') { ', the sound effects' }) (the longest step)"
function Venv($d) { if (-not (Test-Path "$d\Scripts\python.exe")) { & $UV venv --quiet --python $PY $d; if ($LASTEXITCODE) { Die "couldn't make $d" } } }
function Pip { $d = $args[0]; $rest = @($args | Select-Object -Skip 1); & $UV pip install --quiet --python "$d\Scripts\python.exe" @rest; if ($LASTEXITCODE) { Die "couldn't install the packages of $d" } }
$CPU = "https://download.pytorch.org/whl/cpu"   # the processor build of PyTorch: the normal one is 2+ GB of NVIDIA files
Venv "$App\.venv"; Pip "$App\.venv" -r "$App\requirements.txt"
Venv "$E\laya\venv"; Pip "$E\laya\venv" --index-url $CPU "torch==2.14.0+cpu"; Pip "$E\laya\venv" -r "$App\linux\requirements-laya.txt"
Venv "$E\robotics\venv"; Pip "$E\robotics\venv" -r "$App\linux\requirements-robotics.txt"
Pip "$E\robotics\venv" --no-deps "roboticstoolbox-python==1.4.4" "spatialmath-python==1.1.18" "spatialgeometry==1.4.1" "pgraph-python==0.6.5" "ansitable==1.1.1" "colored==2.3.2" "progress==1.6.1" "typing-extensions==4.16.0"
if ($groups -contains "sound") {
    Venv "$E\woosh\venv"; Pip "$E\woosh\venv" --index-url $CPU "torch==2.8.0+cpu" "torchaudio==2.8.0+cpu" "torchvision==0.23.0+cpu"
    Pip "$E\woosh\venv" -r "$App\linux\requirements-woosh.txt"; Pip "$E\woosh\venv" --no-deps "hear21passt==0.0.26"
}

# ---------------------------------------------------------------- 4) engines + models
Step "4/7  Engines and models from their official sites (each file checked) - $($groups -join ', ')"
if (-not $SkipDownloads) {
    & "$App\.venv\Scripts\python.exe" "$App\tools\get_downloads.py" --os win --groups ($groups -join ",")
    if ($LASTEXITCODE) { Die "a download didn't finish" }
}

# ---------------------------------------------------------------- 5) the starter + settings
Step "5/7  The starter (Local AI.exe) and a fresh settings file"
& cmd /c "`"$App\tools\launcher\build.cmd`"" | Out-Null
if (-not (Test-Path "$App\Local AI.exe")) { Die "the starter couldn't be built (tools\launcher\build.cmd)" }
Start-Process "$App\Local AI.exe" -ArgumentList "/fix" -WorkingDirectory $App -Wait   # the environments point at engines\python
$data = Join-Path $App "data"
New-Item -ItemType Directory -Force $data | Out-Null
if (-not (Test-Path "$data\settings.json")) {
    '{"active": {"transcription": "small", "voice": "kokoro-af_heart"}, "setup_pending": true}' | Set-Content "$data\settings.json" -Encoding ascii
}

# ---------------------------------------------------------------- 6) shortcuts
Step "6/7  Shortcuts (desktop + Start menu)"
$sh = New-Object -ComObject WScript.Shell
if (-not $NoShortcuts) { foreach ($lnk in @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("Programs")) ""))) {
    $s = $sh.CreateShortcut((Join-Path $lnk "AI Local.lnk"))
    $s.TargetPath = "$App\Local AI.exe"; $s.WorkingDirectory = $App; $s.IconLocation = "$App\icon.ico"
    $s.Description = "AI Local - a private AI on this PC"
    $s.Save()
} }

# ---------------------------------------------------------------- 7) check + start
Step "7/7  Checking"
& "$App\.venv\Scripts\python.exe" "$App\tools\check.py" | Select-Object -Last 1 | ForEach-Object { Say "  app self-check: $_" }
& "$E\laya\venv\Scripts\python.exe" -c "import torch, transformers, laya; print('  Laya packages OK')"
Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
Say "`nAI Local is ready. Start it with the AI Local icon on the desktop." Green
Say "The first start shows a check of this PC (Settings > This PC). Bigger models: Models page > download any GGUF."
if (-not $NoStart) { Start-Process "$App\Local AI.exe" -WorkingDirectory $App }
if (-not $Quiet) { Read-Host "`nPress Enter to close this window" | Out-Null }
