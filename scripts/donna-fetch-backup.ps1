# Donna backup fetch — pulls the latest droplet snapshot to the laptop.
#
# Default destination is %USERPROFILE%\OneDrive\Donna-Backups, which gives
# a third copy in OneDrive cloud automatically. Override with -LocalDir.
#
# Wire up via Windows Task Scheduler (cmd.exe, one line):
#   schtasks /Create /SC DAILY /ST 06:00 /TN "Donna Backup Fetch" ^
#     /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\dev\donna\scripts\donna-fetch-backup.ps1" /F
#
# Manual run (cmd.exe):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\donna-fetch-backup.ps1

[CmdletBinding()]
param(
    [string]$Droplet  = '159.203.34.165',
    [string]$KeyPath  = "$env:USERPROFILE\.ssh\id_ed25519_droplet",
    [string]$Remote   = '/home/bot/backups/donna-latest.tar.gz',
    [string]$LocalDir = "$env:USERPROFILE\OneDrive\Donna-Backups",
    [int]   $RetainDays = 30
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $KeyPath)) {
    throw "SSH key not found at $KeyPath. Set -KeyPath or place the droplet key there."
}

New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss' -AsUTC
$localFile = Join-Path $LocalDir "donna-$stamp.tar.gz"

Write-Host "[$(Get-Date -Format o)] pulling $Remote -> $localFile"

# scp follows the symlink and writes the underlying tarball.
& scp -i $KeyPath -o StrictHostKeyChecking=accept-new "bot@${Droplet}:${Remote}" $localFile
if ($LASTEXITCODE -ne 0) { throw "scp failed with exit code $LASTEXITCODE" }

$sizeKB = [math]::Round((Get-Item $localFile).Length / 1KB, 1)
Write-Host "[$(Get-Date -Format o)] ok size=${sizeKB}KB"

# Retention: prune local tarballs older than RetainDays.
Get-ChildItem $LocalDir -Filter 'donna-*.tar.gz' |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetainDays) } |
    ForEach-Object {
        Write-Host "[$(Get-Date -Format o)] pruning $($_.Name) ($([math]::Round($_.Length/1KB,1))KB)"
        Remove-Item $_.FullName -Force
    }
