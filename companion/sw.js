const SHELL_PREFIX = 'vantage-companion-shell-';
const CACHE = SHELL_PREFIX + 'v1.44.139';
const SHELL = ['./', 'index.html', 'app.css', 'guild-dkp.css', 'storage.js', 'offline.js', 'dkp.js', 'guild-dkp.js', 'app.js', 'manifest.webmanifest', 'icon-256.png', 'icon-1254.png'];
const shellURLs = SHELL.map(path => new URL(path, self.registration.scope).href);
self.addEventListener('install', event => event.waitUntil((async () => {
  const cache = await caches.open(CACHE);
  await cache.addAll(SHELL.map(path => new Request(new URL(path, self.registration.scope), {cache: 'reload'})));
  await self.skipWaiting();
})()));
self.addEventListener('activate', event => event.waitUntil((async () => {
  // Other apps, legacy catalog caches, and IndexedDB are untouched.
  await Promise.all((await caches.keys()).filter(key => key.startsWith(SHELL_PREFIX) && key !== CACHE).map(key => caches.delete(key)));
  await self.clients.claim();
})()));
self.addEventListener('message', event => {
  if (event.data?.type !== 'vantage-shell-ready' || !event.ports[0]) return;
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    const entries = await Promise.all(shellURLs.map(url => cache.match(url)));
    event.ports[0].postMessage({ready: entries.every(response => response?.ok), cache: CACHE});
  })());
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  const canonical = new URL(url.href); canonical.hash = ''; canonical.search = '';
  const root = new URL('./', self.registration.scope).href;
  const navigation = event.request.mode === 'navigate' && [root, new URL('index.html', root).href].includes(canonical.href);
  if (!navigation && !shellURLs.includes(canonical.href)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(navigation ? root : canonical.href);
    if (cached) return cached;
    // Missing scripts/images never receive an HTML navigation fallback.
    try { return await fetch(event.request); } catch (_) { return Response.error(); }
  })());
});
