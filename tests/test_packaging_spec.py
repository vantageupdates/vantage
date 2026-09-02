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
