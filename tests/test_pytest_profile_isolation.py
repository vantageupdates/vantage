import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_pytest_session_uses_an_isolated_profile_before_app_import():
    from vantage.helpers import config
    from vantage.helpers.portable import data_dir

    session_root = Path(os.environ["VANTAGE_DATA_DIR"]).resolve()
    assert session_root.name.startswith("vantage-pytest-profile-")
    assert data_dir(create=False).resolve() == session_root
    if config._filename:
        assert Path(config._filename).resolve().is_relative_to(session_root)


def test_conftest_overrides_inherited_profile_without_touching_it(tmp_path):
    protected = tmp_path / "protected-live-profile"
    protected.mkdir()
    sentinel = protected / "vantage.config.json"
    sentinel.write_text('{"sentinel":"do not normalize"}\n', encoding="utf-8")
    before_bytes = sentinel.read_bytes()
    before_mtime = sentinel.stat().st_mtime_ns

    script = """
import json
import os
from pathlib import Path
import runpy
runpy.run_path('tests/conftest.py')
from vantage.helpers import application, config
print(json.dumps({
    'profile': os.environ['VANTAGE_DATA_DIR'],
    'config': config._filename,
}))
"""
    env = os.environ.copy()
    env["VANTAGE_DATA_DIR"] = str(protected)
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    isolated = Path(result["profile"]).resolve()
    assert isolated != protected.resolve()
    assert isolated.name.startswith("vantage-pytest-profile-")
    assert Path(result["config"]).resolve().is_relative_to(isolated)
    assert sentinel.read_bytes() == before_bytes
    assert sentinel.stat().st_mtime_ns == before_mtime
