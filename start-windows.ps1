$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if (-not $pythonCommand) { $pythonCommand = Get-Command python -ErrorAction SilentlyContinue }
if (-not $pythonCommand) { throw 'Python 3 was not found. Install Python 3.11 or later, then rerun this script.' }
$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
  $portableNode = Get-ChildItem -LiteralPath $projectRoot -Directory -Filter 'node-v*-win-x64' -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($portableNode -and (Test-Path (Join-Path $portableNode.FullName 'node.exe'))) {
    $env:PATH = "$($portableNode.FullName);$env:PATH"
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
  }
}
if (-not $nodeCommand) { throw 'Node.js was not found. Install Node.js 20 or later, or extract its Windows ZIP folder into this project, then rerun this script.' }
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) { throw 'npm.cmd was not found beside Node.js. Install a complete Node.js distribution, then rerun this script.' }
$backendPath = Join-Path $projectRoot 'backend'
$frontendPath = Join-Path $projectRoot 'frontend'
$venvPython = Join-Path $backendPath '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { & $pythonCommand.Source -m venv (Join-Path $backendPath '.venv') }
if (-not (Test-Path (Join-Path $backendPath '.env'))) { Copy-Item (Join-Path $backendPath '.env.example') (Join-Path $backendPath '.env'); Write-Host 'Created backend\.env. Edit APP_PASSWORD and APP_SECRET before sharing this app.' }
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $backendPath 'requirements.txt')
Push-Location $frontendPath
try { if (-not (Test-Path (Join-Path $frontendPath 'node_modules'))) { & $npmCommand.Source install }; & $npmCommand.Source run build } finally { Pop-Location }
Push-Location $backendPath
try {
  $venvResolved = (Resolve-Path $venvPython).Path
  $previousServers = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ExecutablePath -ieq $venvResolved -and $_.CommandLine -match 'uvicorn\s+app\.main:app' }
  foreach ($previousServer in $previousServers) { Stop-Process -Id $previousServer.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Process -FilePath $venvPython -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $backendPath -WindowStyle Hidden
}
finally { Pop-Location }
Start-Sleep -Seconds 2
Start-Process 'http://127.0.0.1:8000'
Write-Host 'Personal Options Trader is opening at http://127.0.0.1:8000'
