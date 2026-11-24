<#
  Start the Credit Pack Workbench with one command:

      .\start.ps1                       # Mistral (default), http://127.0.0.1:8000
      .\start.ps1 -Model gemini-2.5-flash
      .\start.ps1 -Port 8080

  What it does, in order: checks the Python venv, starts Docker Desktop and the cpa-postgres
  database, builds the React UI if it is missing or out of date, keeps a session secret in .env,
  offers to create the first user if there is none, then starts the server.
#>
param(
  [string]$Model = "mistral/mistral-large-latest",
  [int]$Port = 8000,
  [string]$HostName = "127.0.0.1"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "`nERROR: $t" -ForegroundColor Red; exit 1 }

# 1. Python venv
Step "Python environment"
$py = Join-Path $PSScriptRoot "..\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Fail "No venv at ..\venv. Create it: python -m venv ..\venv; ..\venv\Scripts\python -m pip install -r requirements.txt" }
& $py -c "import fastapi, google.adk, sqlalchemy" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "Installing Python packages..."; & $py -m pip install -q -r requirements.txt }
Write-Host "ok"

# 2. Already running?
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
  Write-Host "`nSomething is already listening on port $Port - the workbench may already be running." -ForegroundColor Yellow
  Write-Host "Open http://${HostName}:$Port  (or stop it, or use -Port 8080)"; exit 0
}

# 3. .env: session secret so sign-ins survive restarts
Step "Configuration (.env)"
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example - add your model key to it." -ForegroundColor Yellow }
$envText = Get-Content .env -Raw
if ($envText -notmatch "(?m)^\s*CPA_WORKBENCH_SECRET\s*=") {
  $secret = -join ((1..48) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
  Add-Content .env "`n# Signs workbench sign-in cookies (added by start.ps1)`nCPA_WORKBENCH_SECRET=$secret"
  Write-Host "Added CPA_WORKBENCH_SECRET to .env"
}
if ($Model -like "mistral/*" -and $envText -notmatch "(?m)^\s*MISTRAL_API_KEY\s*=\s*\S") { Fail "MISTRAL_API_KEY is missing in .env" }
if ($Model -notlike "*/*" -and $envText -notmatch "(?m)^\s*GOOGLE_API_KEY\s*=\s*\S") { Fail "GOOGLE_API_KEY is missing in .env" }
Write-Host "ok (model: $Model)"

# 4. Database (Postgres in Docker) - only if .env points at Postgres
if ($envText -match "(?m)^\s*DATABASE_URL\s*=\s*postgresql") {
  Step "Database (Docker: cpa-postgres)"
  $docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
  if (-not $docker) { $docker = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe" }
  if (-not (Test-Path $docker)) { Fail "Docker is not installed. Install Docker Desktop, or remove DATABASE_URL from .env to use SQLite." }
  $env:PATH = "$(Split-Path $docker);$env:PATH"
  & $docker info *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Starting Docker Desktop..."
    $dd = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\frontend\Docker Desktop.exe"
    if (-not (Test-Path $dd)) { $dd = "C:\Program Files\Docker\Docker\Docker Desktop.exe" }
    Start-Process $dd
    for ($i = 0; $i -lt 60; $i++) { Start-Sleep 2; & $docker info *> $null; if ($LASTEXITCODE -eq 0) { break } }
    if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop did not start within 2 minutes." }
  }
  & $docker start cpa-postgres *> $null
  if ($LASTEXITCODE -ne 0) { Fail "Container cpa-postgres not found. See README 'Database setup (first time only)'." }
  for ($i = 0; $i -lt 30; $i++) { & $docker exec cpa-postgres pg_isready -U postgres -q; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 1 }
  if ($LASTEXITCODE -ne 0) { Fail "Postgres did not become ready." }
  Write-Host "ok"
} else {
  Step "Database"; Write-Host "Using the local SQLite file (no DATABASE_URL in .env)"
}

# 5. Front end (React) - build when missing or out of date
Step "User interface"
$fe = Join-Path $PSScriptRoot "workbench\frontend"
$index = Join-Path $fe "dist\index.html"
$stale = -not (Test-Path $index)
if (-not $stale) {
  $built = (Get-Item $index).LastWriteTime
  $newest = Get-ChildItem (Join-Path $fe "src"), (Join-Path $fe "package.json") -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  $stale = $newest.LastWriteTime -gt $built
}
if ($stale) {
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "Node.js is needed to build the UI the first time: https://nodejs.org" }
  Push-Location $fe
  if (-not (Test-Path node_modules)) { Write-Host "Installing UI packages (first time only)..."; npm install --no-audit --no-fund }
  Write-Host "Building the UI..."; npm run build
  if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "UI build failed (see above)." }
  Pop-Location
}
Write-Host "ok"

# 6. First user
Step "Users"
$users = & $py -W ignore -m workbench.users list 2>$null
if (-not $users) {
  Write-Host "No users yet. Create the first account (an Account Manager):" -ForegroundColor Yellow
  $u = Read-Host "  username"; $n = Read-Host "  full name"
  & $py -W ignore -m workbench.users add $u --name $n --role account_manager
  Write-Host "Add more people later:  ..\venv\Scripts\python -m workbench.users add <username> --name ""Full Name"" --role <role>"
} else { Write-Host "$(@($users).Count) user(s)" }

# 7. Start
Step "Starting the workbench"
Write-Host "Open  http://${HostName}:$Port   (Ctrl+C to stop)" -ForegroundColor Green
& $py -W ignore -m workbench --model $Model --host $HostName --port $Port
