import test from 'node:test';
import assert from 'node:assert/strict';
import { snapshot } from '../landing-assets/releases.mjs';

test('checking preserves a focusable button, ignores duplicate activation, then enables retry', async () => {
  const nodes = new Map();
  const label = { textContent: '' };
  const button = {
    hidden: true, attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    querySelector: () => label,
    addEventListener(_type, listener) { this.activate = listener; },
    set disabled(_value) { throw new Error('Native disabled drops keyboard focus'); },
  };
  nodes.set('#check-versions', button);
  nodes.set('#release-status', { textContent: '', classList: { toggle() {} } });
  for (const product of ['companion', 'ui']) {
    for (const field of ['version', 'download', 'notes', 'confirmation']) nodes.set(`#${product}-${field}`, {});
  }
  nodes.set('#recent-release-notes', {});
  const originalDocument = globalThis.document;
  const originalFetch = globalThis.fetch;
  let pending;
  let requests = 0;
  try {
    globalThis.document = { querySelector: (selector) => nodes.get(selector) };
    globalThis.fetch = () => { requests += 1; return new Promise((resolve) => { pending = resolve; }); };
    await import(`../landing-assets/downloads.mjs?test=${Date.now()}`);
    assert.equal(button.hidden, false);
    assert.equal(button.attributes['aria-disabled'], 'true');
    assert.equal(label.textContent, 'Checking…');
    await button.activate();
    assert.equal(requests, 1);
    pending({ ok: false });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(button.attributes['aria-disabled'], 'false');
    assert.equal(label.textContent, 'Retry version check');
    assert.equal(nodes.get('#companion-download').href, snapshot.companion.download);
    assert.equal(nodes.get('#ui-download').href, snapshot.ui.download);
    assert.match(nodes.get('#companion-confirmation').textContent, /^Last confirmed/);
    assert.match(nodes.get('#release-status').textContent, /Could not check GitHub/);
    const retry = button.activate();
    assert.equal(requests, 2);
    assert.equal(button.attributes['aria-disabled'], 'true');
    pending({ ok: false });
    await retry;
    assert.equal(button.attributes['aria-disabled'], 'false');
  } finally {
    globalThis.document = originalDocument;
    globalThis.fetch = originalFetch;
  }
});
