import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_spec_includes_src_layout_package_root():
    """Do not silently ship an EXE that cannot import ``vantage``."""
    source = (ROOT / "vantage.spec").read_text(encoding="utf-8")

    assert "source_root = Path('src').resolve()" in source
    assert "source_root / 'vantage' / 'helpers' / 'application.py'" in source
    assert "pathex=[str(source_root)]" in source


def test_portable_self_test_imports_the_complete_application_graph():
    source = (ROOT / "vantage_app.py").read_text(encoding="utf-8")

    assert "from vantage.helpers.application import CURRENT_VERSION" in source
    assert 'f"{CURRENT_VERSION}\\n{data_dir()}"' in source


def test_embedded_ui_updater_runs_before_single_instance_and_is_bundled():
    entrypoint = (ROOT / "vantage_app.py").read_text(encoding="utf-8")
    spec = (ROOT / "vantage.spec").read_text(encoding="utf-8")

    assert entrypoint.index('"--vantage-ui-updater"') < entrypoint.index(
        "SingleInstanceGuard")
    assert "vantage_ui_updater_main(updater_args)" in entrypoint
    assert "data.append(('ui/release.json', '.'))" in spec


def test_elevated_character_ui_manager_runs_before_single_instance():
    entrypoint = (ROOT / "vantage_app.py").read_text(encoding="utf-8")

    assert entrypoint.index('"--manage-ui-profiles"') < entrypoint.index(
        "SingleInstanceGuard")
    assert "process_elevated_profile_request(*arguments)" in entrypoint


def test_ui_release_build_self_tests_only_standalone_with_a_fresh_report():
    source = (ROOT / "scripts" / "build_ui_release.ps1").read_text(
        encoding="utf-8")

    build_commands = re.findall(r"(?m)^\s*& \$Python -m PyInstaller (.+)$", source)
    assert build_commands == ["--noconfirm vantage_ui_updater.spec"]
    process_commands = re.findall(r"(?m)^\s*\$\w+ = Start-Process (.+)$", source)
    assert len(process_commands) == 1
    assert "dist\\VantageUI-Updater.exe" in process_commands[0]
    assert "--self-test --report" in process_commands[0]
    assert "$uiReport" in process_commands[0]
    assert "-WindowStyle Hidden -PassThru -Wait" in process_commands[0]
    assert "'dist\\ui-updater-self-test-' + [Guid]::NewGuid().ToString('N')" in source
    assert "$uiTest.ExitCode -ne 0" in source
    assert "Get-Content -LiteralPath $uiReport -Raw | ConvertFrom-Json" in source
    assert "$uiResult.status -cne 'PASS'" in source
    assert source.index("[Guid]::NewGuid()") < source.index("Start-Process")
    assert source.index("$uiTest.ExitCode -ne 0") < source.index("Get-FileHash")
    assert "--vantage-ui-updater" not in source
    assert "Vantage.exe" not in source
    assert "vantage.spec" not in source


def test_ui_release_build_validates_metadata_manifest_and_candidate_versions():
    source = (ROOT / "scripts" / "build_ui_release.ps1").read_text(
        encoding="utf-8")
    release = json.loads((ROOT / "ui" / "release.json").read_text(encoding="utf-8"))

    assert type(release["schema"]) is int and release["schema"] == 2
    assert re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", release["version"])
    assert release["skin_folder"] == f"VantageUI-v{release['version']}"
    assert "Get-Content -LiteralPath 'ui\\release.json' -Raw | ConvertFrom-Json" in source
    assert "$expectedUiVersion = $release.version" in source
    assert "$release.schema -ne 2" in source
    assert '$release.skin_folder -cne "VantageUI-v$expectedUiVersion"' in source
    assert "Get-Content -LiteralPath 'dist\\ui\\VantageUI-manifest.json' -Raw | ConvertFrom-Json" in source
    assert "$manifest.schema -ne 2" in source
    assert '$manifest.skin_folder -cne "VantageUI-v$expectedUiVersion"' in source
    assert "$manifest.version -cne $expectedUiVersion" in source
    assert "$uiResult.version -cne $expectedUiVersion" in source
    assert source.index("$manifest.version -cne $expectedUiVersion") < source.index("-m PyInstaller")
    assert source.index("$uiResult.version -cne $expectedUiVersion") < source.index("Get-FileHash")
    assert "expectedCompanionVersion" not in source
    assert "pyproject.toml" not in source
    # The UI version must come from its metadata, not a release-specific literal.
    assert release["version"] not in source


def test_ui_release_reports_only_three_verified_assets_without_publish_or_install():
    source = (ROOT / "scripts" / "build_ui_release.ps1").read_text(
        encoding="utf-8")

    assert "publish all four assets together" not in source
    assert "VantageUI $expectedUiVersion candidates built and self-tested." in source
    assert "This script does not publish or install." in source
    assert "Self-test report: $uiReport" in source
    hash_commands = re.findall(r"(?m)^\s*Get-FileHash (.+)$", source)
    assert hash_commands == [
        "-LiteralPath 'dist\\VantageUI-Updater.exe','dist\\ui\\VantageUI-manifest.json',"
        "'dist\\ui\\VantageUI-payload.zip' -Algorithm SHA256"
    ]
    assert not re.search(r"(?i)\b(?:gh\s+release|git\s+push|Stop-Process|taskkill)\b", source)
    assert "install_release" not in source
    assert "Vantage.exe" not in source
