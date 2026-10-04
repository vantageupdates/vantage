"""Offline JS state and semantic markup checks for the opaque share page."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'companion-web' / 'share.html'
SHARE_URL = 'https://vantageupdates.github.io/vantage/companion/share.html'

NODE_HARNESS = r'''
const fs = require('fs');
const vm = require('vm');
const options = JSON.parse(fs.readFileSync(0, 'utf8'));
const html = fs.readFileSync(process.argv[1], 'utf8');
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const nodes = {};
let focusCalls = 0;
for (const id of ['share-code', 'copy-code', 'copy-link', 'share-status', 'link-fallback', 'share-link']) {
  nodes[id] = {value: '', disabled: true, hidden: id === 'link-fallback', textContent: '', handlers: {},
    addEventListener(event, callback) { this.handlers[event] = callback; },
    focus() { focusCalls++; }, select() { focusCalls++; }};
}
const writes = [];
const handlers = {};
const navigator = options.clipboard === 'unavailable' ? {} : {
  clipboard: {async writeText(value) {
    if (options.clipboard === 'rejected') throw Error('Clipboard denied');
    writes.push(value);
  }}
};
const window = {location: {hash: options.hash},
  addEventListener(event, callback) { handlers[event] = callback; }};
vm.runInNewContext(script, {document: {getElementById(id) {return nodes[id];}}, window, navigator});
function state() {
  return {code: nodes['share-code'].value, disabled: nodes['share-code'].disabled,
    codeDisabled: nodes['copy-code'].disabled, linkDisabled: nodes['copy-link'].disabled,
    status: nodes['share-status'].textContent, fallbackHidden: nodes['link-fallback'].hidden,
    fallbackLink: nodes['share-link'].value, focusCalls};
}
(async () => {
  const initial = state();
  if (options.click) await nodes[options.click].handlers.click();
  const afterClick = state();
  if (options.nextHash !== undefined) {
    window.location.hash = options.nextHash;
    handlers.hashchange();
  }
  console.log(JSON.stringify({initial, afterClick, final: state(), writes}));
})().catch(error => {console.error(error); process.exit(1);});
'''


def run_page(hash_value, **options):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed for the offline JavaScript state checks')
    result = subprocess.run(
        [node, '-e', NODE_HARNESS, str(PAGE)],
        input=json.dumps({'hash': hash_value, **options}),
        check=True, capture_output=True, text=True, timeout=10)
    return json.loads(result.stdout)


@pytest.mark.parametrize('code', ['VT1:AA', 'VT1:AAA', 'VT1:AAAA', 'VT1:eJw', 'VT1:AA-_'])
def test_share_page_recognizes_only_format_and_preserves_exact_opaque_code(code):
    result = run_page('#' + code)
    assert result['initial']['code'] == code
    assert not result['initial']['codeDisabled']
    assert not result['initial']['linkDisabled']
    assert not result['initial']['disabled']
    assert result['initial']['status'] == 'Share code format recognized. Review it in Vantage.'
    assert result['writes'] == []
    assert result['initial']['focusCalls'] == 0


@pytest.mark.parametrize('fragment', [
    '', '#', '#VT1:', '#vt1:AA', '#VT1:A', '#VT1:AB', '#VT1:AAF',
    '#VT1:AA_', '#VT1:AA=', '#VT1:AA/', '#VT1:AA+', '#VT1:AAA\n',
    '#VT1:AAA\r', '#VT1:AAA\u2028', '#VT1%3AAA', '# VT1:AA',
    '#VT1:AA ', '#VT1:AA\u200b', '#VT1:<img>', '#VT1:AA#AAAA'])
def test_share_page_rejects_empty_malformed_and_noncanonical_fragments(fragment):
    result = run_page(fragment, click='copy-code')
    assert result['final']['code'] == ''
    assert result['final']['disabled']
    assert result['final']['codeDisabled'] and result['final']['linkDisabled']
    assert result['final']['fallbackHidden']
    assert result['writes'] == []
    assert 'recognized' not in result['final']['status']
    assert result['final']['focusCalls'] == 0


def test_share_page_enforces_total_code_size_and_clears_invalid_hashchange():
    exact = 'VT1:' + 'A' * (49152 - 4)
    result = run_page('#' + exact, nextHash='#' + exact + 'AAAA')
    assert result['initial']['code'] == exact
    assert not result['initial']['codeDisabled']
    assert result['final']['codeDisabled'] and result['final']['disabled']
    assert result['final']['code'] == ''
    assert 'too long' in result['final']['status']
    assert result['final']['focusCalls'] == 0


@pytest.mark.parametrize('control', ['copy-code', 'copy-link'])
def test_share_page_copies_code_or_permanent_link_without_changing_focus(control):
    code = 'VT1:eJw'
    result = run_page('#' + code, click=control)
    assert result['writes'] == [code if control == 'copy-code' else SHARE_URL + '#' + code]
    assert 'copied' in result['afterClick']['status']
    assert result['afterClick']['fallbackHidden']
    assert result['afterClick']['focusCalls'] == 0


@pytest.mark.parametrize('clipboard', ['unavailable', 'rejected'])
@pytest.mark.parametrize('control', ['copy-code', 'copy-link'])
def test_share_page_clipboard_fallback_is_manual_and_never_steals_focus(clipboard, control):
    result = run_page('#VT1:eJw', clipboard=clipboard, click=control, nextHash='#bad')
    state = result['afterClick']
    assert 'copy it manually' in state['status']
    assert state['focusCalls'] == 0
    assert state['fallbackHidden'] is (control == 'copy-code')
    assert state['fallbackLink'] == ('' if control == 'copy-code' else SHARE_URL + '#VT1:eJw')
    assert result['final']['fallbackHidden'] and result['final']['fallbackLink'] == ''
    assert result['writes'] == []


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_share_page_uses_native_labeled_controls_and_logical_structure():
    html = PAGE.read_text(encoding='utf-8')
    elements = Markup(html).elements
    by_id = {attrs['id']: (tag, attrs) for tag, attrs in elements if 'id' in attrs}
    ids = [attrs['id'] for _tag, attrs in elements if 'id' in attrs]
    assert len(ids) == len(set(ids))
    assert ('html', {'lang': 'en'}) in elements
    assert [tag for tag, _attrs in elements if re.fullmatch('h[1-6]', tag)] == ['h1', 'h2', 'h2']
    assert by_id['main'][0] == 'main' and by_id['main'][1]['tabindex'] == '-1'
    assert any(tag == 'a' and attrs.get('href') == '#main' for tag, attrs in elements)
    for name in ('share-code', 'share-link'):
        tag, attrs = by_id[name]
        assert tag == 'textarea' and 'readonly' in attrs
        assert any(tag == 'label' and attrs.get('for') == name for tag, attrs in elements)
    for name in ('copy-code', 'copy-link'):
        tag, attrs = by_id[name]
        assert tag == 'button' and attrs['type'] == 'button' and 'disabled' in attrs
    assert by_id['share-status'][1]['role'] == 'status'
    assert by_id['share-status'][1]['aria-live'] == 'polite'
    assert by_id['share-status'][1]['aria-atomic'] == 'true'
    for _tag, attrs in elements:
        for reference in attrs.get('aria-describedby', '').split():
            assert reference in by_id
        assert int(attrs.get('tabindex', '0')) <= 0
    viewport = next(attrs['content'] for tag, attrs in elements
                    if tag == 'meta' and attrs.get('name') == 'viewport')
    assert 'maximum-scale' not in viewport and 'user-scalable=no' not in viewport
    assert '<title>Shared Triggers - Vantage Companion</title>' in html
    assert 'Imported copies remain Off.' in html
    assert 'Quick Bar → Triggers' in html and 'Paste code or link…' in html
    assert 'Import selected' in html


def test_share_page_does_not_decode_interpret_render_or_request_pack_content():
    html = PAGE.read_text(encoding='utf-8')
    script = re.search(r'<script>\s*([\s\S]*?)</script>', html).group(1)
    for forbidden in ('atob', 'JSON.parse', 'DecompressionStream', 'decodeURIComponent',
                      'innerHTML', 'fetch(', 'XMLHttpRequest', 'WebSocket', 'sendBeacon',
                      'localStorage', 'sessionStorage', 'serviceWorker', '.focus(', '.select('):
        assert forbidden not in script
    assert 'connect-src \'none\'' in html
    assert not any(tag in {'img', 'iframe', 'link', 'form'} or 'src' in attrs
                   for tag, attrs in Markup(html).elements)
    workflow = (ROOT / '.github/workflows/refresh-companion.yml').read_text(encoding='utf-8')
    assert workflow.count('cp source/companion-web/share.html site/companion/') == 1
    assert ('cp source/companion-web/index.html site/companion/\n'
            '          cp source/companion-web/share.html site/companion/\n'
            '          cp source/companion-web/app.css site/companion/') in workflow


def luminance(color):
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
              for value in channels]
    return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))

def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


def test_share_page_text_controls_and_focus_tokens_meet_contrast_thresholds():
    html = PAGE.read_text(encoding='utf-8')
    colors = dict(re.findall(r'--([a-z-]+):\s*(#[0-9a-f]{6})', html))
    for background in ('bg', 'surface', 'field-bg', 'button-bg', 'button-hover'):
        for foreground in ('text', 'muted'):
            assert contrast(colors[foreground], colors[background]) >= 4.5
        for foreground in ('line', 'focus'):
            assert contrast(colors[foreground], colors[background]) >= 3
    assert contrast(colors['primary-text'], colors['primary-bg']) >= 4.5
    assert contrast(colors['gold'], colors['primary-bg']) >= 3
    assert contrast(colors['focus'], colors['primary-bg']) >= 3
    assert '--target-size: 44px' in html
    assert ':focus-visible' in html and 'outline-offset:' in html
    assert '@media (forced-colors: active)' in html
    assert '@media (prefers-contrast: more)' in html
