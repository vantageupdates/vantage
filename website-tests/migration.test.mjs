import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { snapshot } from '../landing-assets/releases.mjs';

const root = new URL('../', import.meta.url);
const html = readFileSync(new URL('index.html', root), 'utf8');
const css = readFileSync(new URL('landing-assets/site.css', root), 'utf8');
const app = readFileSync(new URL('landing-assets/downloads.mjs', root), 'utf8');

test('all local assets resolve under the public /vantage/ base path', () => {
  const localLinks = [...html.matchAll(/(?:src|href)="(\.[^"]+)"/g)].map((match) => match[1]);
  assert.ok(localLinks.length >= 7);
  for (const path of localLinks) {
    assert.ok(existsSync(new URL(path, root)), path);
    assert.ok(new URL(path, 'https://vantageupdates.github.io/vantage/').pathname.startsWith('/vantage/landing-assets/'));
  }
  for (const [, path] of css.matchAll(/url\(['"]?([^)'"\s]+)['"]?\)/g)) {
    assert.ok(existsSync(new URL(path, new URL('landing-assets/', root))), path);
  }
  assert.doesNotMatch(html, /(?:src|href)="\/(?!\/)/);
  assert.doesNotMatch(html, /_next\/|\/api\/|\.chatgpt\.site|__next/);
  assert.doesNotMatch(app, /localStorage|sessionStorage|document\.cookie|innerHTML/);
});

test('static content gives both confirmed executable downloads without JavaScript', () => {
  for (const product of ['companion', 'ui']) {
    const release = snapshot[product];
    assert.ok(html.includes(`id="${product}-download"`));
    assert.ok(html.includes(`href="${release.download}"`));
    assert.ok(html.includes(`href="${release.url}"`));
    assert.ok(html.includes(`>v${release.version}</span>`));
    assert.match(html, new RegExp(`id="${product}-confirmation">Last confirmed · October 14, 2026, 05:09 UTC`));
  }
  assert.doesNotMatch(html, /Latest stable/);
  assert.match(html, /<button[^>]+id="check-versions"[^>]+hidden>/);
  assert.match(html, /<noscript>/);
  assert.doesNotMatch(html, /1\.44\.121|1\.44\.99/);
});

test('migration retains complete feature groups, creator and independent support details', () => {
  assert.equal([...html.matchAll(/class="feature-group"/g)].length, 5);
  assert.equal([...html.matchAll(/<dt>/g)].length, 22);
  for (const content of ['Mindflux / Harmflux', 'mindflux99', 'mailto:vantagecompanion@gmail.com', 'https://buymeacoffee.com/vantagecompanion', 'VantageUI is optional.', 'Mobile companion', 'Recorded attendance', 'OpenDKP for your guild']) {
    assert.ok(html.includes(content), content);
  }
});

test('semantic structure, skip target and all fragment/ARIA references remain valid', () => {
  assert.match(html, /<html lang="en">/);
  assert.equal([...html.matchAll(/<h1\b/g)].length, 1);
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length);
  for (const [, id] of html.matchAll(/href="#([^"]+)"|aria-labelledby="([^"]+)"/g)) {
    if (id) assert.ok(ids.includes(id), id);
  }
  for (const [, id] of html.matchAll(/aria-labelledby="([^"]+)"/g)) assert.ok(ids.includes(id), id);
  assert.match(html, /<main id="main-content" tabindex="-1">/);
  assert.match(html, /id="release-status"[^>]+role="status"[^>]+aria-live="polite"[^>]+aria-atomic="true"/);
  assert.doesNotMatch(html, /tabindex="[1-9]/);
  for (const [tag] of html.matchAll(/<img\b[^>]*>/g)) assert.match(tag, /\balt="[^"]*"/);
  for (const [tag] of html.matchAll(/<svg\b[^>]*>/g)) assert.match(tag, /aria-hidden="true"/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /:focus-visible/);
});
