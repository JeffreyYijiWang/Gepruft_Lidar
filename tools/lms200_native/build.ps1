param([string]$Compiler = 'C:\msys64\ucrt64\bin\g++.exe')
$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$buildDirectory = Join-Path $repositoryRoot 'tmp\native-lms200'
New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null
$executable = Join-Path $buildDirectory 'lms200-native.exe'
$sourceNames = @('main.cpp', 'protocol.cpp', 'protocol_tests.cpp', 'sequence.cpp', 'sequence_tests.cpp', 'win_serial.cpp')
$sourcePaths = @($sourceNames | ForEach-Object { Join-Path $PSScriptRoot $_ })
$compilerPath = (Get-Command -Name $Compiler -ErrorAction Stop).Source
$arguments = @('-std=c++17', '-O2', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-static', '-pthread') + $sourcePaths + @('-o', $executable)
& $compilerPath @arguments
if ($LASTEXITCODE -ne 0) { throw "Native compilation failed: $LASTEXITCODE" }
& $executable --self-test
if ($LASTEXITCODE -ne 0) { throw "Offline checks failed: $LASTEXITCODE" }
$sourceHashes = @(@($sourceNames + @('protocol.hpp','sequence.hpp','win_serial.hpp','build.ps1')) | ForEach-Object {
    $sourceFile = Join-Path $PSScriptRoot $_
    [ordered]@{ file = $_; sha256 = (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash }
})
$manifest = [ordered]@{
    builtUtc = [DateTime]::UtcNow.ToString('o')
    compiler = $compilerPath
    compilerVersion = (& $compilerPath --version | Select-Object -First 1)
    target = (& $compilerPath -dumpmachine)
    options = @('-std=c++17','-O2','-Wall','-Wextra','-Wpedantic','-Werror','-static','-pthread')
    sources = $sourceHashes
    executable = $executable
    executableSha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash
    offlineChecksPassed = $true
    serialPortOpenedDuringBuild = $false
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $buildDirectory 'build-manifest.json') -Encoding utf8
$archiveDirectory = Join-Path $buildDirectory ('archive\' + $manifest.executableSha256)
if (-not (Test-Path -LiteralPath $archiveDirectory)) {
    New-Item -ItemType Directory -Path $archiveDirectory | Out-Null
    Copy-Item -LiteralPath $executable -Destination (Join-Path $archiveDirectory 'lms200-native.exe')
    Copy-Item -LiteralPath (Join-Path $buildDirectory 'build-manifest.json') -Destination (Join-Path $archiveDirectory 'build-manifest.json')
    $archiveSources = Join-Path $archiveDirectory 'sources'
    New-Item -ItemType Directory -Path $archiveSources | Out-Null
    foreach ($sourceHash in $sourceHashes) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $sourceHash.file) -Destination (Join-Path $archiveSources $sourceHash.file)
    }
}
Write-Output "Native executable: $executable"
