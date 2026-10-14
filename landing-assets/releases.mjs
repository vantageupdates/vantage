// Public, read-only release discovery. No account, token, storage or API server.
export const REPOSITORY = 'https://github.com/vantageupdates/vantage';
export const API = 'https://api.github.com/repos/vantageupdates/vantage/releases';
export const PAGE_SIZE = 100;
export const MAX_PAGES = 5;
export const TIMEOUT_MS = 12000;

export const snapshot = Object.freeze({
  companion: Object.freeze({
    version: '1.44.133',
    url: `${REPOSITORY}/releases/tag/v1.44.133`,
    download: `${REPOSITORY}/releases/download/v1.44.133/Vantage.exe`,
  }),
  ui: Object.freeze({
    version: '1.44.110',
    url: `${REPOSITORY}/releases/tag/vantage-ui-v1.44.110`,
    download: `${REPOSITORY}/releases/download/vantage-ui-v1.44.110/VantageUI-Updater.exe`,
  }),
  checkedAt: '2026-10-14T05:09:48Z',
});

const isRecord = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);

export function compareVersions(left, right) {
  const a = left.split('.').map(Number);
  const b = right.split('.').map(Number);
  return a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
}

export function selectReleases(rows) {
  if (!Array.isArray(rows)) return null;
  const products = {};
  for (const row of rows) {
    if (!isRecord(row) || row.draft !== false || row.prerelease !== false || typeof row.tag_name !== 'string') continue;
    const match = /^(v|vantage-ui-v)(\d+\.\d+\.\d+)$/.exec(row.tag_name);
    if (!match || !match[2].split('.').every((part) => Number.isSafeInteger(Number(part)))) continue;
    const product = match[1] === 'v' ? 'companion' : 'ui';
    const assetName = product === 'companion' ? 'Vantage.exe' : 'VantageUI-Updater.exe';
    // Require exact official HTTPS links; never trust a redirect, mirror or query string.
    const url = `${REPOSITORY}/releases/tag/${row.tag_name}`;
    const download = `${REPOSITORY}/releases/download/${row.tag_name}/${assetName}`;
    const asset = Array.isArray(row.assets) && row.assets.find((value) =>
      isRecord(value) && value.name === assetName && value.state === 'uploaded' && value.browser_download_url === download);
    if (!asset || row.html_url !== url) continue;
    if (!products[product] || compareVersions(match[2], products[product].version) > 0) {
      products[product] = { version: match[2], url, download };
    }
  }
  return products.companion && products.ui ? products : null;
}

export async function fetchReleases({ fetchImpl = globalThis.fetch, timeoutMs = TIMEOUT_MS, now = () => new Date() } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const rows = [];
  try {
    for (let page = 1; page <= MAX_PAGES; page += 1) {
      const response = await fetchImpl(`${API}?per_page=${PAGE_SIZE}&page=${page}`, {
        headers: { Accept: 'application/vnd.github+json' },
        credentials: 'omit',
        mode: 'cors',
        cache: 'no-store',
        redirect: 'error',
        signal: controller.signal,
      });
      if (!response.ok) throw new Error('GitHub release check unavailable');
      const batch = await response.json();
      if (!Array.isArray(batch) || batch.length > PAGE_SIZE) throw new Error('Invalid release response');
      rows.push(...batch);
      // Inspect the complete bounded listing. The API orders by date, not version.
      if (batch.length < PAGE_SIZE) {
        const releases = selectReleases(rows);
        if (!releases) throw new Error('Both stable downloads could not be verified');
        return { ...releases, checkedAt: now().toISOString() };
      }
    }
    throw new Error('Release listing exceeds the check limit');
  } finally {
    clearTimeout(timeout);
  }
}

// Retain the last confirmed links on errors, including a failed retry after success.
export async function checkReleases(previous = snapshot, options) {
  try {
    return { state: 'ready', releases: await fetchReleases(options) };
  } catch {
    return { state: 'error', releases: previous };
  }
}
