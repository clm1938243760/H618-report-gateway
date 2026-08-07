param(
  [string]$Config = "$PSScriptRoot\config.yaml"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = "$root\src"
if (-not (Test-Path $Config)) {
  Copy-Item "$PSScriptRoot\config.example.yaml" $Config
  Write-Host "Created $Config. Set the administrator password and TLS certificate paths before starting."
  exit 1
}
py -3.14 -m update_center.run --config $Config
