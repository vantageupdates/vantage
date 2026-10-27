"""The legacy Market zone entry point must use the same real article as Zones."""
from types import SimpleNamespace

import pytest

from vantage.parsers import market


@pytest.mark.parametrize('name,article', [
    ('Temple Of Veeshan', 'Temple_of_Veeshan'),
    ('The Nektulos Forest', 'Nektulos_Forest'),
    ('Castle Mistmoore', 'Mistmoore_Castle'),
])
def test_market_zone_selection_uses_mirror_article_url(tmp_path, monkeypatch, name, article):
    monkeypatch.setattr(market, '_wiki_zone_cache_path', lambda _: tmp_path/'absent.json')
    monkeypatch.setattr(market, 'wiki_access', SimpleNamespace(status=lambda: ''))
    requests = []
    reply = SimpleNamespace(finished=SimpleNamespace(connect=lambda callback: None))
    def get(request):
        requests.append(request)
        return reply
    control = SimpleNamespace(setEnabled=lambda _: None, setText=lambda _: None)
    host = SimpleNamespace(zone_selector=SimpleNamespace(currentText=lambda: name),
        zone_load_button=control, zone_summary=control, _network=SimpleNamespace(get=get))
    assert market.GreenMarket._load_zone_explorer(host)
    assert requests[0].url().toString() == 'https://p99.funcamp.net/' + article
    assert requests[0].transferTimeout() > 0
