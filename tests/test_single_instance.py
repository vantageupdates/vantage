import os
import uuid

import pytest

from vantage.helpers.single_instance import SingleInstanceGuard


@pytest.mark.skipif(os.name != "nt", reason="Vantage is a Windows app")
def test_named_mutex_allows_only_one_live_vantage_instance():
    name = rf"Local\Vantage.Test.{uuid.uuid4()}"
    first = SingleInstanceGuard(name)
    second = SingleInstanceGuard(name)
    try:
        assert first.acquired is True
        assert second.acquired is False
    finally:
        second.close()
        first.close()

    replacement = SingleInstanceGuard(name)
    try:
        assert replacement.acquired is True
    finally:
        replacement.close()
