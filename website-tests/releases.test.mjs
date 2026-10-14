import test from 'node:test';
import assert from 'node:assert/strict';
import { REPOSITORY, API, PAGE_SIZE, MAX_PAGES, snapshot, compareVersions, selectReleases, fetchReleases, checkReleases } from '../landing-assets/releases.mjs';

function release(product, version, overrides = {}) {
  const tag = `${product === 'companion' ? 'v' : 'vantage-ui-v'}${version}`;
  const name = product === 'companion' ? 'Vantage.exe' : 'VantageUI-Updater.exe';
  return {
    tag_name: tag, draft: false, prerelease: false,
    html_url: `${REPOSITORY}/releases/tag/${tag}`,
    assets: [{ name, state: 'uploaded', browser_download_url: `${REPOSITORY}/releases/download/${tag}/${name}` }],
    ...overrides,
  };
}
const companion = release('companion', '1.44.133');
const ui = release('ui', '1.44.110');
const response = (body) => ({ ok: true, json: async () => body });

test('selects each product independently by numeric version, regardless of date or list order', () => {
  const result = selectReleases([
    release('ui', '1.44.9'), companion, release('companion', '1.44.99'),
    release('ui', '1.44.109'), release('companion', '1.44.134'), ui,
  ]);
  assert.equal(result.companion.version, '1.44.134');
  assert.equal(result.ui.version, '1.44.110');
  assert.ok(compareVersions('2.0.0', '1.999.999') > 0);
  assert.ok(compareVersions('1.45.0', '1.44.999') > 0);
});

test('rejects drafts, prereleases, malformed tags, missing flags and unsafe numeric versions', () => {
  const invalid = [
    release('companion', '9.0.0', { draft: true }),
    release('companion', '9.0.0', { prerelease: true }),
    release('companion', '9.0.0', { draft: undefined }),
    release('companion', '9.0.0', { prerelease: undefined }),
    release('companion', '9.0.0-beta'), release('companion', '9.0'),
    release('companion', '9007199254740992.0.0'),
    release('companion', '9.0.0', { tag_name: 'other-v9.0.0' }),
    null, [], 'release', 42,
  ];
  assert.deepEqual(selectReleases([...invalid, companion, ui]), { companion: snapshot.companion, ui: snapshot.ui });
  assert.equal(selectReleases(invalid), null);
  assert.equal(selectReleases({}), null);
});

test('requires the exact uploaded product asset and exact official HTTPS release links', () => {
  for (const badUrl of [
    'https://github.com.evil.example/vantageupdates/vantage/releases/download/v9.0.0/Vantage.exe',
    'https://github.com/other/repo/releases/download/v9.0.0/Vantage.exe',
    'http://github.com/vantageupdates/vantage/releases/download/v9.0.0/Vantage.exe',
    `${REPOSITORY}/releases/download/v9.0.0/Vantage.exe?redirect=elsewhere`,
    `${REPOSITORY}/releases/download/v9.0.0/Vantage.exe#fragment`,
    'javascript:alert(1)',
  ]) {
    const bad = release('companion', '9.0.0');
    bad.assets[0].browser_download_url = badUrl;
    assert.equal(selectReleases([bad, companion, ui]).companion.version, '1.44.133');
  }
  for (const changes of [
    { html_url: 'https://example.com/release' },
    { assets: [] },
    { assets: [{ ...companion.assets[0], state: 'new' }] },
    { assets: [{ ...companion.assets[0], name: 'VantageUI-Updater.exe' }] },
    { assets: [{ ...companion.assets[0], browser_download_url: ui.assets[0].browser_download_url }] },
  ]) assert.equal(selectReleases([{ ...companion, ...changes }, ui]), null);
});

test('missing either product produces no verified latest pair', () => {
  assert.equal(selectReleases([companion]), null);
  assert.equal(selectReleases([ui]), null);
  assert.equal(selectReleases([]), null);
});

test('checks subsequent pages even after finding both products and omits credentials', async () => {
  const requests = [];
  const result = await fetchReleases({
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return response(requests.length === 1
        ? [companion, ui, ...Array(PAGE_SIZE - 2).fill(null)]
        : [release('companion', '1.44.134')]);
    },
    now: () => new Date('2026-10-14T06:00:00Z'),
  });
  assert.equal(result.companion.version, '1.44.134');
  assert.equal(result.checkedAt, '2026-10-14T06:00:00.000Z');
  assert.equal(requests.length, 2);
  requests.forEach(({ url, options }, i) => {
    assert.equal(url, `${API}?per_page=100&page=${i + 1}`);
    assert.equal(options.credentials, 'omit');
    assert.equal(options.mode, 'cors');
    assert.equal(options.redirect, 'error');
    assert.equal(options.cache, 'no-store');
    assert.deepEqual(options.headers, { Accept: 'application/vnd.github+json' });
    assert.ok(options.signal instanceof AbortSignal);
  });
});

test('bounded pagination fails safely rather than labeling a partial list latest', async () => {
  let requests = 0;
  const result = await checkReleases(snapshot, { fetchImpl: async () => {
    requests += 1;
    return response([companion, ui, ...Array(PAGE_SIZE - 2).fill(null)]);
  } });
  assert.equal(requests, MAX_PAGES);
  assert.equal(result.state, 'error');
  assert.equal(result.releases, snapshot);
});

test('HTTP, rate limit, network, JSON, partial product and later-page errors retain confirmed links', async () => {
  for (const fetchImpl of [
    async () => ({ ok: false, status: 403 }),
    async () => ({ ok: false, status: 429 }),
    async () => { throw new TypeError('Network unavailable'); },
    async () => ({ ok: true, json: async () => { throw new SyntaxError('Invalid JSON'); } }),
    async () => response({ message: 'Invalid response' }),
    async () => response(Array(101).fill(companion)),
    async () => response([companion]),
    async (url) => url.endsWith('page=1') ? response([companion, ui, ...Array(98).fill(null)]) : { ok: false },
  ]) {
    const result = await checkReleases(snapshot, { fetchImpl });
    assert.equal(result.state, 'error');
    assert.equal(result.releases, snapshot);
  }
});

test('timeout aborts the request and keeps downloads usable', async () => {
  const result = await checkReleases(snapshot, {
    timeoutMs: 10,
    fetchImpl: (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new Error('Aborted')), { once: true });
    }),
  });
  assert.equal(result.state, 'error');
  assert.equal(result.releases, snapshot);
});

test('success followed by failed retry retains the newest confirmation', async () => {
  const successful = await checkReleases(snapshot, { fetchImpl: async () => response([release('companion', '1.44.134'), ui]) });
  assert.equal(successful.state, 'ready');
  const failed = await checkReleases(successful.releases, { fetchImpl: async () => { throw new Error('Offline'); } });
  assert.equal(failed.state, 'error');
  assert.equal(failed.releases.companion.version, '1.44.134');
  assert.equal(failed.releases.checkedAt, successful.releases.checkedAt);
});
