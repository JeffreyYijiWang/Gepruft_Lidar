param([string]$Distribution = 'Ubuntu-24.04')
$ErrorActionPreference = 'Stop'

# Verification only: no build, node launch, COM handle or USB attachment.
$verificationScript = Join-Path $PSScriptRoot 'verify-laviria-wsl.sh'
$wslVerificationScript = & wsl.exe --distribution $Distribution --exec wslpath -u $verificationScript
if ($LASTEXITCODE -ne 0) { throw 'Could not locate the verification script in WSL.' }
& wsl.exe --distribution $Distribution --exec bash $wslVerificationScript
if ($LASTEXITCODE -ne 0) { throw 'LaViRIA offline package verification failed; inspect the output above.' }
