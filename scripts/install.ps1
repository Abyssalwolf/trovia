# Trovia installer for Windows (PowerShell).
#
#   irm https://abyssalwolf.github.io/trovia/install.ps1 | iex
#
# What it does (no administrator rights needed):
#   1. installs uv (a Python tool installer from astral.sh) if you don't have it
#   2. installs the `trovia` command with uv, in its own isolated environment
#   3. runs `trovia setup`, which walks you through API keys and defaults
#
# Options (environment variables):
#   TROVIA_PACKAGE=<spec>     package to install (default: trovia). Example: trovia==0.1.0
#   TROVIA_NO_SETUP=1         install only; don't run the setup wizard
#   TROVIA_NO_MODIFY_PATH=1   don't edit your user PATH to include the trovia command

# Native tools such as uv write progress to stderr. In Windows PowerShell 5.1 that would abort the
# script under "Stop", so we keep "Continue" and check exit codes ourselves.
$ErrorActionPreference = "Continue"

function Fail($message) {
    Write-Host "Error: $message" -ForegroundColor Red
    throw $message
}

$package = if ($env:TROVIA_PACKAGE) { $env:TROVIA_PACKAGE } else { "trovia" }
Write-Host "Installing Trovia ($package)"

# 1. uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv was not found; installing it from astral.sh ..."
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 -ErrorAction Stop | Invoke-Expression
    } catch {
        Fail "could not install uv: $_"
    }
    # uv's installer puts it here (or in UV_INSTALL_DIR); make it visible to this session.
    $uvDir = if ($env:UV_INSTALL_DIR) { $env:UV_INSTALL_DIR } else { Join-Path $env:USERPROFILE ".local\bin" }
    $env:Path = "$uvDir;$env:Path"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv is still not on PATH after installing it; open a new terminal and run this again"
}

# 2. trovia (uv fetches a suitable Python itself if you have none)
uv tool install --upgrade --python ">=3.11,<3.15" $package
if ($LASTEXITCODE -ne 0) { Fail "could not install $package" }
$binDir = (uv tool dir --bin | Out-String).Trim()

# 3. PATH
if (-not $env:TROVIA_NO_MODIFY_PATH) {
    uv tool update-shell *> $null
}

Write-Host ""
Write-Host "Trovia is installed: $binDir\trovia.exe"

# 4. setup wizard (call it by full path: this session's PATH may not include the new folder yet)
if (-not $env:TROVIA_NO_SETUP) {
    & (Join-Path $binDir "trovia.exe") setup
}

Write-Host ""
Write-Host "Start it with:  trovia"
if (($env:Path -split ";") -notcontains $binDir) {
    Write-Host "(Open a new terminal first so your PATH picks up the trovia command.)"
}
