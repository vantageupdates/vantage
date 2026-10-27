"""Authored reference pages test the public HTML transport trust boundary."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkReply

from vantage.helpers import wiki_access as access
from vantage.helpers.wiki_source import (
    MAX_PAGE_BYTES, ORIGIN, SOURCE_NAME, image_url, page_url, parse_html,
    parse_page, reference_url, sanitize_html, section_html, title_from_url,
)


def article(content, title='Example Page'):
    return f'<h1 id="firstHeading">{title}</h1><div id="mw-content-text">{content}</div>'


@pytest.mark.parametrize('value', [
    'javascript:alert(1)', 'http://p99.funcamp.net/Example',
    'https://p99.funcamp.net.evil.test/Page', '//evil.test/Page',
    'https://user:secret@p99.funcamp.net/Page', 'https://p99.funcamp.net:8080/Page',
    'https://p99.funcamp.net:invalid/Page', 'https://[broken/Page',
])
def test_reference_links_reject_foreign_and_active_urls(value):
    assert title_from_url(value) == ''
    assert reference_url(value) == ''
    assert image_url(value) == ''


def test_canonical_links_become_mirror_articles_and_fragments_survive():
    assert title_from_url('https://wiki.project1999.com/Example_Spell') == 'Example Spell'
    assert reference_url('https://wiki.project1999.com/Example_Spell#Where_to_Obtain') == (
        ORIGIN + '/Example_Spell#Where_to_Obtain')
    assert page_url('Example Spell (Spell)') == ORIGIN + '/Example_Spell_(Spell)'
    assert image_url('/images/Item_1.png') == ORIGIN + '/images/Item_1.png'
    assert image_url('/admin/logo.png') == ''


def test_safe_passive_html_has_no_executable_or_foreign_resource_attributes():
    cleaned = sanitize_html('''<p onclick="bad()" style="background:url(https://evil.test)">Facts</p>
    <script>bad()</script><iframe src="https://evil.test">secret</iframe>
    <img src="/images/Item.png" onerror="bad()" alt="Example item">
    <img src="https://evil.test/track.png">
    <a href="javascript:bad()">Unsafe</a><a href="/Example_Spell">Example Spell</a>''', keep_images=True)
    assert 'script' not in cleaned and 'iframe' not in cleaned and 'secret' not in cleaned
    assert 'onclick' not in cleaned and 'onerror' not in cleaned and 'style=' not in cleaned
    assert 'evil.test' not in cleaned and 'javascript:' not in cleaned
    assert f'href="{ORIGIN}/Example_Spell"' in cleaned
    assert 'alt="Example item"' in cleaned


def test_static_category_continuation_is_preserved_without_extra_parameters():
    value = '/index.php_title=Category:Quests&pagefrom=Some+Quest&action=delete#mw-pages'
    assert reference_url(value) == ORIGIN + '/index.php_title=Category:Quests&pagefrom=Some+Quest'
    assert 'action=' not in sanitize_html(f'<a href="{value}">next 200</a>')
    archived = '/index.php_title=Category:Quests&pagefrom=Emil%27s+Report#mw-pages'
    assert reference_url(archived) == ORIGIN + archived.split('#')[0]


@pytest.mark.parametrize('body', [
    '', '<script>not an article</script>', '<div class="noarticletext">Missing</div>',
])
def test_missing_or_unreadable_articles_fail_instead_of_caching_success(body):
    with pytest.raises(ValueError):
        parse_page(article(body))


def test_page_shape_preserves_source_and_images_without_inventing_wikitext():
    payload = parse_page(article('<p>A factual description.</p><img src="/images/Item.png">'))
    assert payload['_source'] == SOURCE_NAME
    assert payload['_source_url'] == ORIGIN + '/Example_Page'
    assert payload['parse']['images'] == [ORIGIN + '/images/Item.png']
    assert payload['parse']['wikitext'] == {'*': ''}


def test_content_and_structure_limits_are_enforced():
    with pytest.raises(ValueError, match='safe limit'):
        parse_page(b'X' * (MAX_PAGE_BYTES + 1))
    with pytest.raises(ValueError, match='structure'):
        parse_html('<div>' * 130 + 'Facts' + '</div>' * 130)
    with pytest.raises(ValueError, match='unavailable'):
        parse_page('<title>Just a moment</title>' + article('<p>Challenge</p>'))


def test_sections_include_subsections_but_not_next_peer():
    body = '<h2>Details</h2><p>Facts</p><h3>Subsection</h3><p>More</p><h2>Other</h2><p>Excluded</p>'
    result = section_html(body, 'Details')
    assert 'Facts' in result and 'More' in result and 'Excluded' not in result


def reply(body, url=ORIGIN + '/Example_Page', status=200):
    return SimpleNamespace(readAll=lambda: body, attribute=lambda _: status,
        error=lambda: QNetworkReply.NetworkError.NoError,
        url=lambda: QUrl(url), rawHeader=lambda _: b'')


def test_transport_accepts_html_rejects_foreign_redirect_and_respects_pause(monkeypatch):
    gate = access.WikiAccess()
    monkeypatch.setattr(access, 'wiki_access', gate)
    body = article('<p>Example facts.</p>').encode()
    assert access.read_wiki_reply(reply(body), page=True)['_mirror']
    with pytest.raises(ValueError, match='outside'):
        access.read_wiki_reply(reply(body, 'https://evil.test/Page'), page=True)
    with pytest.raises(ValueError, match='restricted'):
        access.read_wiki_reply(reply(body, status=403), page=True)
    assert 'paused' in gate.status()
