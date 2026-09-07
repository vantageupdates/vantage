from pathlib import Path


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


def test_release_build_self_tests_both_ui_updater_entrypoints():
    source = (ROOT / "scripts" / "build_ui_release.ps1").read_text(
        encoding="utf-8")

    assert "--vantage-ui-updater --self-test" in source
    assert "Embedded VantageUI updater self-test failed." in source
    assert "dist\\VantageUI-Updater.exe" in source
