param(
  [string]$Config = "$PSScriptRoot\config.yaml"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = "$root\src"

if (-not (Get-Command openssl -ErrorAction SilentlyContinue)) {
  $git = Get-Command git -ErrorAction SilentlyContinue
  if ($git) {
    $gitRoot = Split-Path -Parent (Split-Path -Parent $git.Source)
    foreach ($candidate in @("$gitRoot\usr\bin", "$gitRoot\mingw64\bin")) {
      if (Test-Path "$candidate\openssl.exe") {
        $env:PATH = "$candidate;$env:PATH"
        break
      }
    }
  }
}
if (-not (Get-Command openssl -ErrorAction SilentlyContinue)) {
  throw "OpenSSL is required to verify signed update packages. Install OpenSSL or Git for Windows."
}

if (-not (Test-Path $Config)) {
  Copy-Item "$PSScriptRoot\config.example.yaml" $Config
  Write-Host "Created $Config. Set the administrator password and TLS certificate paths before starting."
  exit 1
}
py -3.14 -m update_center.run --config $Config
