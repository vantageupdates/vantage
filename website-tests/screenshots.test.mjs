import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
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
    assert.match(figure, entry.dataKind === 'demo' ? /Real app · demo data/ : /In-game (?:capture|crop|detail)/);
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

test('VantageUI showcase only links the direct-pixel privacy copy, never its unredacted source', () => {
  const entry = manifest.images.find((image) => image.file === 'vantageui-in-game-private.png');
  assert.ok(entry);
  assert.equal(entry.version, '1.44.109');
  assert.equal(entry.width, 2875);
  assert.equal(entry.height, 1766);
  assert.match(entry.sourceSha256, /^[a-f0-9]{64}$/);
  assert.notEqual(entry.sha256, entry.sourceSha256);
  assert.equal(entry.privacyRedaction.method, 'direct-pixel-solid-fill');
  assert.equal(entry.privacyRedaction.aiGenerated, false);
  assert.equal(entry.privacyRedaction.pixelsOutsideRectanglesPreserved, true);
  assert.ok(entry.privacyRedaction.rectangles.length >= 5);
  for (const rectangle of entry.privacyRedaction.rectangles) {
    const { x, y, width, height } = rectangle;
    for (const value of [x, y, width, height]) assert.ok(Number.isInteger(value));
    assert.ok(x >= 0 && y >= 0 && width > 0 && height > 0);
    assert.ok(x + width <= entry.width && y + height <= entry.height);
  }
  const screenshotRoot = new URL('landing-assets/screenshots/', root);
  for (const file of readdirSync(screenshotRoot).filter((name) => name.endsWith('.png'))) {
    assert.notEqual(createHash('sha256').update(readFileSync(new URL(file, screenshotRoot))).digest('hex'), entry.sourceSha256, `${file} must not contain the unredacted source`);
  }
  assert.match(manifest.policy, /direct-pixel/i);
  assert.match(html, /id="vantageui-screenshots"/);
  assert.match(gallery, /In-game capture · VantageUI v1\.44\.109 · Chat text hidden for privacy/);
  assert.match(gallery, /alt="Open full-size VantageUI in-game screenshot[^"\n]*chat text hidden"/);
  assert.doesNotMatch(gallery, /vantageui-in-game\.png|codex-clipboard-/);
  for (const name of ['vantageui-inventory-current.png', 'vantageui-bags-current.png']) {
    const detail = manifest.images.find((image) => image.file === name);
    assert.ok(detail);
    assert.equal(detail.version, entry.version);
    assert.equal(detail.sourceKind, 'in-game-screenshot-crop');
    assert.equal(detail.dataKind, 'gameplay');
    assert.equal(detail.source, entry.file);
    assert.equal(detail.sourceSha256, entry.sha256);
    assert.equal(detail.crop.method, 'direct-pixel-crop');
    assert.equal(detail.crop.aiGenerated, false);
    assert.equal(detail.crop.resampled, false);
    assert.equal(detail.crop.mismatchedPixelsVersusSourceRegion, 0);
    assert.equal(detail.crop.rectangle.width, detail.width);
    assert.equal(detail.crop.rectangle.height, detail.height);
  }
  assert.doesNotMatch(gallery, /vantageui-inventory\.png|vantageui-bags\.png|version unconfirmed|enlarged 3×/);
});
