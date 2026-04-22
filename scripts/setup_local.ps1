<#
.SYNOPSIS
    Donna - one-shot local dev setup on Windows.

.DESCRIPTION
    Idempotent. Safe to re-run. Does everything from Python venv creation
    through running the test suite. Exits cleanly with actionable errors if
    prereqs are missing.

    Prereqs (install first if missing):
      - Python 3.14  (python.org/downloads - NOT the Microsoft Store version)
      - Git          (git-scm.com/download/win)

    Run from the repo root:
        .\scripts\setup_local.ps1

.NOTES
    Does NOT create API keys - those accounts live in the cloud. See
    docs/LIVE_RUN_SETUP.md for account provisioning and .env filling.
#>

#Requires -Version 5.1

# Do NOT set $ErrorActionPreference = "Stop" globally: Windows PowerShell 5.1
# wraps every stderr line from a native EXE as an ErrorRecord. Tools like
# alembic, pip, and pytest write informational output to stderr, so "Stop"
# would abort on benign output. We check $LASTEXITCODE explicitly after each
# native invocation instead.
$script:hadError = $false

function Write-Step    { param($m) Write-Host "[setup] $m" -ForegroundColor Cyan }
function Write-Ok      { param($m) Write-Host "  [ok] $m" -ForegroundColor Green }
function Write-Warn    { param($m) Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host "  [error] $m" -ForegroundColor Red; $script:hadError = $true }

# ---------------------------------------------------------------------------
# 0. Repo root sanity check
# ---------------------------------------------------------------------------
Write-Step "Checking you're running from the repo root..."
if (-not (Test-Path ".\pyproject.toml")) {
    Write-Err "pyproject.toml not found. cd into the repo root before running this script."
    exit 1
}
if (-not (Test-Path ".\src\donna")) {
    Write-Err "src\donna not found. Is this the donna repo?"
    exit 1
}
Write-Ok "in repo root"

# ---------------------------------------------------------------------------
# 1. Python 3.14
# ---------------------------------------------------------------------------
Write-Step "Checking Python 3.14..."
$pythonCheck = & py -3.14 -c "import sys; print(sys.version)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Python 3.14 not available via the 'py' launcher."
    Write-Host ""
    Write-Host "  Install Python 3.14 from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  Critical install options:" -ForegroundColor Yellow
    Write-Host "    [x] Add python.exe to PATH" -ForegroundColor Yellow
    Write-Host "    [x] Install launcher for all users" -ForegroundColor Yellow
    Write-Host "  Do NOT use the Microsoft Store Python - it has sandboxing issues." -ForegroundColor Yellow
    exit 1
}
Write-Ok "py -3.14 works ($($pythonCheck -split "`n" | Select-Object -First 1))"

# ---------------------------------------------------------------------------
# 2. Git
# ---------------------------------------------------------------------------
Write-Step "Checking Git..."
$gitCheck = & git --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "git not found."
    Write-Host "  Install from https://git-scm.com/download/win" -ForegroundColor Yellow
    exit 1
}
Write-Ok "$gitCheck"

# ---------------------------------------------------------------------------
# 3. Virtual environment
# ---------------------------------------------------------------------------
$venvPy = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Step "Creating Python 3.14 venv at .venv..."
    & py -3.14 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Err "venv creation failed"
        exit 1
    }
    Write-Ok "created"
} else {
    # Avoid PowerShell 5.1 native-EXE quote mangling: read pyvenv.cfg directly.
    # Every venv has this file with a `version = X.Y.Z` line.
    $cfgPath = ".\.venv\pyvenv.cfg"
    $isPy314 = $false
    if (Test-Path $cfgPath) {
        $cfg = Get-Content $cfgPath -Raw
        if ($cfg -match "version\s*=\s*3\.14") {
            $isPy314 = $true
        }
    }
    if ($isPy314) {
        Write-Ok "existing .venv is Python 3.14"
    } else {
        Write-Warn "existing .venv is not Python 3.14 - recreating"
        Remove-Item .venv -Recurse -Force
        & py -3.14 -m venv .venv
    }
}

# ---------------------------------------------------------------------------
# 4. Upgrade pip + install
# ---------------------------------------------------------------------------
Write-Step "Upgrading pip/setuptools/wheel..."
& $venvPy -m pip install --upgrade pip setuptools wheel --quiet
if ($LASTEXITCODE -ne 0) { Write-Err "pip upgrade failed"; exit 1 }
Write-Ok "pip upgraded"

Write-Step "Installing donna + dev deps (2-3 min on first run, cached after)..."
& $venvPy -m pip install -e ".[dev]" --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Err "dep install failed - paste the output above to get unblocked"
    exit 1
}
Write-Ok "deps installed"

# ---------------------------------------------------------------------------
# 5. Alembic migrations
# ---------------------------------------------------------------------------
Write-Step "Applying database migrations..."
& $venvPy -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Err "alembic upgrade failed"
    exit 1
}
Write-Ok "schema at head"

# ---------------------------------------------------------------------------
# 6. Run tests
# ---------------------------------------------------------------------------
Write-Step "Running test suite..."
& $venvPy -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Err "tests failed - this should not happen on a clean clone. Paste output."
    exit 1
}
Write-Ok "all tests passing"

# ---------------------------------------------------------------------------
# 7. .env reminder
# ---------------------------------------------------------------------------
# We deliberately do NOT auto-copy .env.example to .env here. Pydantic-settings
# will read a placeholder .env and fail validation on empty required fields,
# which makes pytest fail on subsequent runs. Let the user create .env only
# when they're ready to fill in real values.
if (Test-Path ".\.env") {
    Write-Step ".env already exists - edit it with real values before running the bot"
} else {
    Write-Step ".env not present yet - create it when you have your API keys:"
    Write-Host "     Copy-Item .env.example .env" -ForegroundColor Yellow
    Write-Host "     notepad .env" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "====================================================" -ForegroundColor Green
Write-Host "  Donna local setup complete." -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps (see docs\LIVE_RUN_SETUP.md for details):" -ForegroundColor White
Write-Host ""
Write-Host "  1. Edit .env with real API keys:"
Write-Host "     - ANTHROPIC_API_KEY  (from console.anthropic.com)"
Write-Host "     - DISCORD_BOT_TOKEN  (from discord.com/developers)"
Write-Host "     - DISCORD_ALLOWED_USER_ID  (your Discord user ID)"
Write-Host "     - DISCORD_GUILD_ID  (your test server ID, optional)"
Write-Host "     - TAVILY_API_KEY    (from tavily.com)"
Write-Host "     - VOYAGE_API_KEY    (from voyageai.com)"
Write-Host ""
Write-Host "  2. Verify .env loads:"
Write-Host "     .\.venv\Scripts\Activate.ps1"
Write-Host "     python -c `"from donna.config import settings; settings()`""
Write-Host ""
Write-Host "  3. Run the bot in two terminals:"
Write-Host "     Terminal 1:   python -m donna.main"
Write-Host "     Terminal 2:   python -m donna.worker"
Write-Host ""
Write-Host "  4. DM your bot on Discord. First message takes ~10s."
Write-Host ""
