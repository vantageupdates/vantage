param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$releaseRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Push-Location -LiteralPath $releaseRoot
try {
    $env:PYTHONPATH = Join-Path $releaseRoot 'src'
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:VANTAGE_DATA_DIR = Join-Path $releaseRoot 'work\ui-release-self-test-profile'
    $release = Get-Content -LiteralPath 'ui\release.json' -Raw | ConvertFrom-Json
    $expectedUiVersion = $release.version
    if ($release.schema -ne 2 -or $release.schema -is [bool] -or $expectedUiVersion -isnot [string] -or $expectedUiVersion -cnotmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' -or $release.skin_folder -cne "VantageUI-v$expectedUiVersion") {
        throw 'Expected schema 2 and an exact versioned VantageUI folder.'
    }
    & $Python -m pytest -q tests/test_ui_skin_updater.py tests/test_ui_skin_versioned.py tests/test_ui_skin_package.py tests/test_ui_skin_app.py tests/test_ui_skin_layout.py tests/test_build_ui_release_policy.py
    if ($LASTEXITCODE -ne 0) { throw 'Focused UI tests failed.' }
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $Python scripts/package_ui_skin.py
    if ($LASTEXITCODE -ne 0) { throw 'Skin packaging failed.' }
    $manifest = Get-Content -LiteralPath 'dist\ui\VantageUI-manifest.json' -Raw | ConvertFrom-Json
    if ($manifest.schema -ne 2 -or $manifest.schema -is [bool] -or $manifest.version -cne $expectedUiVersion -or $manifest.skin_folder -cne "VantageUI-v$expectedUiVersion") {
        throw 'Packaged UI manifest/version mismatch.'
    }
    & $Python -m PyInstaller --noconfirm vantage_ui_updater.spec
    if ($LASTEXITCODE -ne 0) { throw 'UI updater build failed.' }
    # A unique report prevents an old PASS from satisfying this candidate run.
    $uiReport = Join-Path $releaseRoot ('dist\ui-updater-self-test-' + [Guid]::NewGuid().ToString('N') + '.json')
    $uiTest = Start-Process -FilePath (Join-Path $releaseRoot 'dist\VantageUI-Updater.exe') -ArgumentList ('--self-test --report "' + $uiReport + '"') -WindowStyle Hidden -PassThru -Wait
    if ($uiTest.ExitCode -ne 0) { throw 'UI updater portable self-test failed.' }
    $uiResult = Get-Content -LiteralPath $uiReport -Raw | ConvertFrom-Json
    if ($uiResult.version -cne $expectedUiVersion -or $uiResult.status -cne 'PASS') { throw 'UI candidate version/self-test mismatch.' }
    Write-Output "VantageUI $expectedUiVersion candidates built and self-tested. This script does not publish or install. Self-test report: $uiReport"
    Get-FileHash -LiteralPath 'dist\VantageUI-Updater.exe','dist\ui\VantageUI-manifest.json','dist\ui\VantageUI-payload.zip' -Algorithm SHA256
} finally { Pop-Location }
