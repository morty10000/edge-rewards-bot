# Launch Edge with remote debugging port (dedicated profile) for CDP takeover.
# Usage: powershell -ExecutionPolicy Bypass -File launch_edge.ps1
# NOTE: keep this file ASCII-only; Windows PowerShell 5.1 reads .ps1 as ANSI(GBK)
#       and non-ASCII comments can corrupt string parsing.
$ErrorActionPreference = "Stop"

$edgeCandidates = @(
  "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
  "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)
$edge = $edgeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { Write-Error "msedge.exe not found"; exit 1 }

$profileDir = Join-Path $PSScriptRoot ".edge-profile"
$port = 9222

$edgeArgs = @(
  "--remote-debugging-port=$port",
  "--user-data-dir=`"$profileDir`"",
  "--remote-allow-origins=*",
  "--no-first-run",
  "--no-default-browser-check",
  "https://cn.bing.com"
)

Start-Process $edge -ArgumentList $edgeArgs
Write-Host "Edge launched with remote debugging"
Write-Host "  exe    : $edge"
Write-Host "  profile: $profileDir"
Write-Host "  debug  : http://127.0.0.1:$port/json/version"
