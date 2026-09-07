$ErrorActionPreference = 'Stop'
$checks = @(
    @('-m', 'ruff', 'format', '--check', 'src', 'tests', 'tools'),
    @('-m', 'ruff', 'check', 'src', 'tests', 'tools'),
    @('-m', 'mypy'),
    @('-m', 'pytest', '-q')
)
foreach ($check in $checks) {
    & python @check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if ($env:LMS_VERIFY_DOCKER -eq '1') {
    docker build --target test -t gepruft-lms200:test .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker build --target runtime -t gepruft-lms200:local .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
