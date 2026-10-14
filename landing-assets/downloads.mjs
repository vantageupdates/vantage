import { checkReleases, snapshot } from './releases.mjs';

const button = document.querySelector('#check-versions');
const status = document.querySelector('#release-status');
let releases = snapshot;
let checking = false;

function confirmedDate(value) {
  return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function render(state) {
  const date = confirmedDate(releases.checkedAt);
  for (const product of ['companion', 'ui']) {
    const release = releases[product];
    document.querySelector(`#${product}-version`).textContent = `v${release.version}`;
    document.querySelector(`#${product}-download`).href = release.download;
    document.querySelector(`#${product}-notes`).href = release.url;
    document.querySelector(`#${product}-confirmation`).textContent = `${state === 'ready' ? 'Latest stable' : 'Last confirmed'} · ${date}`;
  }
  const changesLink = document.querySelector('#recent-release-notes');
  changesLink.href = releases.companion.url;
  changesLink.textContent = `Read the ${releases.companion.version} Companion release notes`;
  status.classList.toggle('release-error', state === 'error');
  // Keep keyboard focus on the initiating button while ignoring duplicate checks.
  button.setAttribute('aria-disabled', String(state === 'checking'));
  button.querySelector('span').textContent = state === 'checking' ? 'Checking…' : state === 'error' ? 'Retry version check' : 'Check versions';
  if (state === 'checking') {
    status.textContent = 'Checking GitHub for the latest stable releases. Last confirmed downloads remain available.';
  } else if (state === 'ready') {
    status.textContent = `Companion ${releases.companion.version} · VantageUI ${releases.ui.version} · Checked on GitHub · ${date}`;
  } else {
    status.textContent = `Could not check GitHub right now. Last confirmed downloads are available below · ${date}. Retry the check or open the release notes.`;
  }
}

async function check() {
  if (checking) return;
  checking = true;
  render('checking');
  const result = await checkReleases(releases);
  releases = result.releases;
  checking = false;
  render(result.state);
}

button.hidden = false;
button.addEventListener('click', check);
void check();
