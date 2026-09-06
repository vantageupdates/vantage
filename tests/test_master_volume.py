import pytest

from vantage.helpers import config


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [(None, 100), ('bad', 100), (-1, 0), (0, 0), (37, 37), (101, 100)])
def test_master_volume_config_is_defaulted_and_clamped(
        monkeypatch, raw, expected):
    general = {} if raw is None else {'master_volume': raw}
    monkeypatch.setattr(config, 'data', {'general': general})

    config.verify_settings()

    assert config.data['general']['master_volume'] == expected
