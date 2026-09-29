"""Global safety boundary for the Vantage test suite.

This module is imported by pytest before test modules, including modules that
import ``vantage.helpers.application`` at collection time.  Application import
loads and may normalize its profile, so the override must exist this early to
ensure a developer's real Vantage profile is never a test fixture.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile


_PYTEST_PROFILE_ROOT = Path(tempfile.mkdtemp(prefix="vantage-pytest-profile-"))
_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))
# Child-process tests must inherit the same import boundary as pytest itself.
# Replacing rather than merely relying on ``sys.path`` keeps portable
# self-tests isolated and importable without a developer-installed package.
_inherited_pythonpath = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, (
    str(_SOURCE_ROOT), _inherited_pythonpath)))

# Always replace an inherited value.  A shell or IDE may otherwise pass the
# user's live profile explicitly and make a seemingly isolated test mutate it.
os.environ["VANTAGE_DATA_DIR"] = str(_PYTEST_PROFILE_ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
