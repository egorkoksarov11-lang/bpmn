param([switch]$SetupOnly)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$runtime = Join-Path $root '.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
# Runtimes stay inside the unpacked package. No PATH or registry changes.
$env:UV_PYTHON_INSTALL_DIR = Join-Path $runtime 'python'
$env:UV_CACHE_DIR = Join-Path $runtime 'cache'
$env:npm_config_cache = Join-Path $runtime 'npm-cache'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
$uv = Join-Path $runtime 'uv.exe'
if (!(Test-Path -LiteralPath $uv)) {
    Write-Host '[1/4] Downloading local Python manager...'
    $asset = "uv-$arch-pc-windows-msvc.zip"
    $url = "https://github.com/astral-sh/uv/releases/download/0.9.7/$asset"
    $archive = Join-Path $runtime 'uv.zip'
    Invoke-WebRequest -UseBasicParsing $url -OutFile $archive
    $uvHash = if ($arch -eq 'aarch64') { '4482ad2544544e1966b6d933d38e27368ce0307739d293322c10459f698a1629' } else { '5d250c32d3604e28dbe18dc65c668ff628c53e00dde2c642576e831e4a60da64' }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $uvHash) { throw 'Python manager checksum mismatch' }
    $unpack = Join-Path $runtime 'uv-unpack'
    Expand-Archive -LiteralPath $archive -DestinationPath $unpack -Force
    $found = Get-ChildItem -LiteralPath $unpack -Filter uv.exe -Recurse | Select-Object -First 1
    if (!$found) { throw 'uv.exe missing from downloaded archive' }
    Copy-Item -LiteralPath $found.FullName -Destination $uv
    Remove-Item -LiteralPath $archive, $unpack -Recurse -Force
}
$python = Join-Path $root '.venv-desktop\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    Write-Host '[2/4] Installing local Python 3.12.10...'
    & $uv venv --python 3.12.10 --managed-python (Join-Path $root '.venv-desktop')
    if ($LASTEXITCODE -ne 0) { throw 'Python setup failed. Check Internet access and retry.' }
}
$nodeArch = if ($arch -eq 'aarch64') { 'arm64' } else { 'x64' }
$nodeName = "node-v22.14.0-win-$nodeArch"
$nodeDir = Join-Path $runtime $nodeName
if (!(Test-Path -LiteralPath (Join-Path $nodeDir 'node.exe'))) {
    Write-Host '[3/4] Downloading local Node.js...'
    $base = 'https://nodejs.org/dist/v22.14.0'
    $nodeZip = "$nodeName.zip"
    $archive = Join-Path $runtime $nodeZip
    Invoke-WebRequest -UseBasicParsing "$base/$nodeZip" -OutFile $archive
    $sums = (Invoke-WebRequest -UseBasicParsing "$base/SHASUMS256.txt").Content
    $line = ($sums -split "`n" | Where-Object { $_.Trim().EndsWith(" $nodeZip") }) | Select-Object -First 1
    if (!$line) { throw 'Node.js checksum missing' }
    $expected = ($line.Trim() -split '\s+')[0]
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw 'Node.js checksum mismatch' }
    Expand-Archive -LiteralPath $archive -DestinationPath $runtime -Force
    Remove-Item -LiteralPath $archive
}
$env:PATH = "$nodeDir;$env:PATH"
Write-Host '[4/4] Checking application dependencies...'
& $uv pip sync --python $python (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed. Check Internet access and retry.' }
$lockHash = (Get-FileHash -LiteralPath (Join-Path $root 'package-lock.json') -Algorithm SHA256).Hash
$stamp = Join-Path $runtime 'npm-lock.sha256'
if (!(Test-Path -LiteralPath (Join-Path $root 'node_modules\elkjs\lib\elk.bundled.js')) -or !(Test-Path -LiteralPath $stamp) -or (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $lockHash) {
    & (Join-Path $nodeDir 'npm.cmd') ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Node dependencies failed. Check Internet access and retry.' }
    Set-Content -LiteralPath $stamp -Value $lockHash
}
if ($SetupOnly) { Write-Host 'Setup complete.'; exit 0 }
Write-Host 'Opening BPMN Generator. Keep this window open. Ctrl+C stops the application.'
& $python (Join-Path $PSScriptRoot 'app.py')
if ($LASTEXITCODE -ne 0) { throw "Application exited with code $LASTEXITCODE" }
