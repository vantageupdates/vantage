import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

const root = new URL('../', import.meta.url);
const html = readFileSync(new URL('index.html', root), 'utf8');
const css = readFileSync(new URL('landing-assets/site.css', root), 'utf8');
const manifestText = readFileSync(new URL('landing-assets/screenshots/provenance.json', root), 'utf8');
const manifest = JSON.parse(manifestText);
const gallery = html.match(/<section id="screenshots"[\s\S]*?<\/section>/)?.[0];

test('nine real screenshot assets retain recorded PNG dimensions and checksums', () => {
  assert.equal(manifest.images.length, 9);
  assert.equal(new Set(manifest.images.map((entry) => entry.file)).size, 9);
  for (const entry of manifest.images) {
    assert.match(entry.file, /^[a-z-]+\.png$/);
    const bytes = readFileSync(new URL(`landing-assets/screenshots/${entry.file}`, root));
    assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', entry.file);
    assert.equal(bytes.readUInt32BE(16), entry.width, entry.file);
    assert.equal(bytes.readUInt32BE(20), entry.height, entry.file);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), entry.sha256, entry.file);
    assert.ok(entry.caption.length > 20);
    assert.match(entry.date, /^2026-10-\d{2}$/);
    assert.ok(['native-qt-window', 'in-game-screenshot', 'in-game-screenshot-crop'].includes(entry.sourceKind));
  }
  assert.equal(manifest.images.filter((entry) => entry.dataKind === 'demo').length, 6);
  assert.equal(manifest.images.filter((entry) => entry.dataKind === 'gameplay').length, 3);
  assert.doesNotMatch(manifestText, /C:\\|C:\/|AppData|OneDrive|Users\//i);
});

test('static gallery gives every screenshot a descriptive same-tab full-size link and caption', () => {
  assert.ok(gallery);
  const figures = [...gallery.matchAll(/<figure\b[\s\S]*?<\/figure>/g)].map(([figure]) => figure);
  assert.equal(figures.length, 9);
  for (const entry of manifest.images) {
    const src = `./landing-assets/screenshots/${entry.file}`;
    const figure = figures.find((markup) => markup.includes(`src="${src}"`));
    assert.ok(figure, entry.file);
    assert.ok(figure.includes(`href="${src}"`));
    assert.ok(figure.includes(`width="${entry.width}" height="${entry.height}"`));
    assert.match(figure, /alt="Open full-size [^"]{20,}"/);
    assert.match(figure, /loading="lazy"/);
    assert.match(figure, /<figcaption><strong>[^<]+<\/strong><p>[^<]+<\/p><small>[^<]+<\/small><\/figcaption>/);
    assert.doesNotMatch(figure, /target=|onclick=|role="button"|tabindex=|<button/);
    assert.match(figure, entry.dataKind === 'demo' ? /Real app · demo data/ : /In-game (?:capture|crop)/);
    if (entry.version) assert.ok(figure.includes(`v${entry.version}`));
    else assert.match(figure, /version unconfirmed/);
  }
  assert.match(gallery, /browser’s Back button/);
  assert.match(gallery, /current download may look different/);
});

test('screenshots navigation and real hero replace the illustrative timer mockup', () => {
  assert.match(html, /<nav[^>]*>[\s\S]*href="#screenshots">Screenshots<\/a>/);
  assert.match(gallery, /<h2 id="screenshots-heading">/);
  assert.equal([...gallery.matchAll(/<h3>/g)].length, 2);
  assert.ok(html.indexOf('id="downloads"') < html.indexOf('id="screenshots"'));
  assert.ok(html.indexOf('id="screenshots"') < html.indexOf('class="changes-section'));
  const hero = html.match(/<section id="top"[\s\S]*?<\/section>/)?.[0];
  assert.ok(hero);
  assert.match(hero, /src="\.\/landing-assets\/screenshots\/companion-map\.png"/);
  assert.match(hero, /A real Companion window/);
  assert.match(hero, /demo session/);
  assert.doesNotMatch(html + css, /preview-buff|buff-gold|buff-blue|Illustrative buff timer preview/);
  assert.match(css, /\.screenshot-image img\s*\{[^}]*object-fit:\s*contain/);
  assert.doesNotMatch(css, /object-fit:\s*cover/);
  assert.match(css, /\.screenshot-grid\s*\{[^}]*grid-template-columns:\s*1fr/);
});
