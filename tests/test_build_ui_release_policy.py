"""UI-only release orchestration, with no real build/process/game operations."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_ui_release.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


def test_ui_build_script_never_builds_or_starts_companion():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "vantage.spec" not in source
    assert "Vantage.exe" not in source
    assert "pyproject.toml" not in source
    assert "--vantage-ui-updater" not in source
    assert source.count("-m PyInstaller") == 1
    assert "-m PyInstaller --noconfirm vantage_ui_updater.spec" in source
    assert "[Guid]::NewGuid()" in source
    assert not re.search(r"(?i)\b(?:Stop-Process|taskkill|gh\s+release|git\s+push)\b", source)


def _run_mocked(tmp_path, mode="pass", release_changes=None):
    """Execute only the script's orchestration in a disposable fake checkout."""
    if not POWERSHELL:
        pytest.skip("PowerShell not available for the mocked orchestration test")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / SCRIPT.name).write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "ui").mkdir()
    (tmp_path / "dist" / "ui").mkdir(parents=True)
    release = {"schema": 2, "version": "1.2.3", "skin_folder": "VantageUI-v1.2.3"}
    release.update(release_changes or {})
    (tmp_path / "ui" / "release.json").write_text(json.dumps(release), encoding="utf-8")
    manifest = dict(release)
    if mode == "manifest-version":
        manifest["version"] = "1.2.4"
    (tmp_path / "dist" / "ui" / "VantageUI-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    # Even a stale fixed-name success must not satisfy a missing fresh report.
    (tmp_path / "dist" / "ui-updater-self-test.json").write_text(
        json.dumps({"version": "1.2.3", "status": "PASS"}), encoding="utf-8")
    wrapper = tmp_path / "mock-build.ps1"
    wrapper.write_text(r'''
param([string]$Root, [string]$Mode)
$ErrorActionPreference = 'Stop'
# Windows PowerShell exports Get-FileHash from a module as a function. Load
# the real utility/management commands before installing spies so lazy module
# imports cannot replace them during the nested build script. This preference
# is confined to this disposable PowerShell test process.
Import-Module Microsoft.PowerShell.Management -ErrorAction Stop
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
$PSModuleAutoLoadingPreference = 'None'
$events = [System.Collections.Generic.List[object]]::new()
$global:MockPythonCount = 0
function Invoke-MockPython {
    $global:MockPythonCount += 1
    $events.Add(@{kind='python'; argv=@($args)})
    $global:LASTEXITCODE = 0
    if (($Mode -eq 'focused-fail' -and $global:MockPythonCount -eq 1) -or
        ($Mode -eq 'suite-fail' -and $global:MockPythonCount -eq 2) -or
        ($Mode -eq 'package-fail' -and $global:MockPythonCount -eq 3) -or
        ($Mode -eq 'build-fail' -and $global:MockPythonCount -eq 4)) {
        $global:LASTEXITCODE = 1
    }
}
function Start-Process {
    param($FilePath, $ArgumentList, $WindowStyle, [switch]$PassThru, [switch]$Wait)
    $events.Add(@{kind='process'; file=$FilePath; argv=$ArgumentList; hidden=($WindowStyle -eq 'Hidden'); wait=[bool]$Wait})
    if ($Mode -ne 'missing-report') {
        $reportPath = [regex]::Match($ArgumentList, '--report "([^"]+)"').Groups[1].Value
        $version = if ($Mode -eq 'report-version') {'1.2.4'} else {'1.2.3'}
        $status = if ($Mode -eq 'report-status') {'FAIL'} else {'PASS'}
        @{version=$version; status=$status} | ConvertTo-Json | Set-Content -LiteralPath $reportPath
    }
    return [pscustomobject]@{ExitCode=$(if ($Mode -eq 'self-test-exit') {1} else {0})}
}
function Get-FileHash {
    param([string[]]$LiteralPath, $Algorithm)
    $events.Add(@{kind='hash'; files=$LiteralPath; algorithm=$Algorithm})
}
$failed = $false
$failure = ''
try { & (Join-Path $Root 'scripts\build_ui_release.ps1') -Python Invoke-MockPython }
catch { $failed = $true; $failure = $_.Exception.Message }
$mockCommands = @{}
foreach ($name in @('Start-Process', 'Get-FileHash')) {
    $command = Get-Command -Name $name -ErrorAction Stop
    $mockCommands[$name] = @{type=[string]$command.CommandType; source=$command.Source}
}
Write-Output ('TEST_RESULT=' + (@{failed=$failed; failure=$failure; events=@($events.ToArray()); mock_commands=$mockCommands} | ConvertTo-Json -Compress -Depth 8))
''', encoding="utf-8")
    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(wrapper), "-Root", str(tmp_path), "-Mode", mode],
        text=True, capture_output=True, timeout=30, check=True,
    )
    marker = next(line for line in completed.stdout.splitlines() if line.startswith("TEST_RESULT="))
    result = json.loads(marker.partition("=")[2])
    assert result["mock_commands"] == {
        "Start-Process": {"type": "Function", "source": ""},
        "Get-FileHash": {"type": "Function", "source": ""},
    }, result
    return result


def test_ui_only_orchestration_runs_tests_packages_builds_and_hashes_only_three_assets(tmp_path):
    result = _run_mocked(tmp_path)
    assert not result["failed"], result
    events = result["events"]
    assert [e["kind"] for e in events] == ["python"] * 4 + ["process", "hash"]
    assert events[0]["argv"][:3] == ["-m", "pytest", "-q"]
    assert {"tests/test_ui_skin_updater.py", "tests/test_ui_skin_versioned.py",
            "tests/test_ui_skin_package.py", "tests/test_ui_skin_app.py"} <= set(events[0]["argv"])
    assert events[1]["argv"] == ["-m", "pytest", "-q"]
    assert events[2]["argv"] == ["scripts/package_ui_skin.py"]
    assert events[3]["argv"] == ["-m", "PyInstaller", "--noconfirm", "vantage_ui_updater.spec"]
    assert events[4]["file"].endswith("VantageUI-Updater.exe")
    assert events[4]["hidden"] and events[4]["wait"]
    assert events[4]["argv"].startswith("--self-test --report ")
    assert events[5]["algorithm"] == "SHA256"
    assert events[5]["files"] == ["dist\\VantageUI-Updater.exe", "dist\\ui\\VantageUI-manifest.json", "dist\\ui\\VantageUI-payload.zip"]


@pytest.mark.parametrize("mode", ["focused-fail", "suite-fail", "package-fail", "manifest-version",
                                  "build-fail", "self-test-exit", "missing-report",
                                  "report-version", "report-status"])
def test_ui_release_failure_never_reports_deliverable_hashes(tmp_path, mode):
    result = _run_mocked(tmp_path, mode)
    assert result["failed"], result
    assert not any(e["kind"] == "hash" for e in result["events"])


@pytest.mark.parametrize("change", [{"schema": True}, {"schema": 1}, {"version": "01.2.3"},
                                    {"version": "1.2.3-beta"}, {"skin_folder": "VantageUI"},
                                    {"skin_folder": "vantageui-v1.2.3"}])
def test_bad_release_metadata_stops_before_tests_or_builds(tmp_path, change):
    result = _run_mocked(tmp_path, release_changes=change)
    assert result["failed"]
    assert result["events"] == []
