param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$releaseRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Push-Location -LiteralPath $releaseRoot
try {
    $env:PYTHONPATH = Join-Path $releaseRoot 'src'
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:VANTAGE_DATA_DIR = Join-Path $releaseRoot 'work\ui-release-self-test-profile'
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $Python scripts/package_ui_skin.py
    if ($LASTEXITCODE -ne 0) { throw 'Skin packaging failed.' }
    & $Python -m PyInstaller --noconfirm vantage.spec
    if ($LASTEXITCODE -ne 0) { throw 'Vantage build failed.' }
    & $Python -m PyInstaller --noconfirm vantage_ui_updater.spec
    if ($LASTEXITCODE -ne 0) { throw 'UI updater build failed.' }
    $mainTest = Start-Process -FilePath (Join-Path $releaseRoot 'dist\Vantage.exe') -ArgumentList '--portable-self-test' -WindowStyle Hidden -PassThru -Wait
    if ($mainTest.ExitCode -ne 0) { throw 'Vantage portable self-test failed.' }
    $embeddedUiReport = Join-Path $releaseRoot 'dist\embedded-ui-updater-self-test.json'
    $embeddedUiTest = Start-Process -FilePath (Join-Path $releaseRoot 'dist\Vantage.exe') -ArgumentList ('--vantage-ui-updater --self-test --report "' + $embeddedUiReport + '"') -WindowStyle Hidden -PassThru -Wait
    if ($embeddedUiTest.ExitCode -ne 0) { throw 'Embedded VantageUI updater self-test failed.' }
    $uiReport = Join-Path $releaseRoot 'dist\ui-updater-self-test.json'
    $uiTest = Start-Process -FilePath (Join-Path $releaseRoot 'dist\VantageUI-Updater.exe') -ArgumentList ('--self-test --report "' + $uiReport + '"') -WindowStyle Hidden -PassThru -Wait
    if ($uiTest.ExitCode -ne 0) { throw 'UI updater portable self-test failed.' }
    $expectedCompanionVersion = (& $Python -c "import pathlib,tomllib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $expectedCompanionVersion) { throw 'Could not read Companion candidate version.' }
    $expectedUiVersion = (Get-Content -LiteralPath 'ui\release.json' -Raw | ConvertFrom-Json).version
    $mainVersion = (Get-Content -LiteralPath (Join-Path $env:VANTAGE_DATA_DIR 'portable-self-test.txt'))[0]
    $embeddedUiResult = Get-Content -LiteralPath $embeddedUiReport -Raw | ConvertFrom-Json
    $uiResult = Get-Content -LiteralPath $uiReport -Raw | ConvertFrom-Json
    if ($mainVersion -ne $expectedCompanionVersion -or $embeddedUiResult.version -ne $expectedUiVersion -or $embeddedUiResult.status -ne 'PASS' -or $uiResult.version -ne $expectedUiVersion -or $uiResult.status -ne 'PASS') { throw 'Candidate version/self-test mismatch.' }
    Write-Output 'Candidates built and self-tested. Companion and VantageUI assets are independently versioned; attach only assets whose embedded version matches the release tag. This script does not publish.'
    Get-FileHash -LiteralPath 'dist\Vantage.exe','dist\VantageUI-Updater.exe','dist\ui\VantageUI-manifest.json','dist\ui\VantageUI-payload.zip' -Algorithm SHA256
} finally { Pop-Location }
