/* Untrusted exports are projected to display-only fields before any save. */
(() => {
  'use strict';
  const MAX_BYTES = 8 * 1024 * 1024;
  // Even a blank projected purchase occupies these bytes. This bound admits
  // every valid export while preventing tiny untrusted objects from expanding
  // into millions of projected rows after the existing 8 MiB input check.
  const MIN_LOOT_BYTES = JSON.stringify({date:'',item:'',character:'',dkp:'',raid:'',wiki_url:''}).length + 1;
  const MAX_LOOT_ROWS = Math.floor(MAX_BYTES / MIN_LOOT_BYTES);
  const fail = () => { throw new Error('This is not a supported Vantage offline file. Export a fresh copy from Vantage.'); };
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  function text(value, max = 2000) {
    if (value === undefined || value === null) return '';
    if (typeof value !== 'string' || value.length > max) fail();
    return value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '');
  }
  function rows(value, max, project) {
    if (!Array.isArray(value) || value.length > max) fail();
    return value.map(project);
  }
  function fields(value, keys, max) {
    if (!object(value)) fail();
    return Object.fromEntries(keys.map(key => [key, text(value[key], max)]));
  }
  function safeURL(value, kind = 'wiki') {
    if (!value) return '';
    if (typeof value !== 'string' || value.length > 2048) fail();
    try {
      const url = new URL(value);
      if(url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443'))return '';
      if(kind === 'sheet'){
        const match=/^\/spreadsheets\/d\/([A-Za-z0-9_-]{10,180})(?:\/(?:edit|view|preview|htmlview))?\/?$/.exec(url.pathname);
        return url.hostname === 'docs.google.com' && match ? 'https://docs.google.com/spreadsheets/d/'+match[1]+'/edit' : '';
      }
      if (!['wiki.project1999.com', 'p99.funcamp.net'].includes(url.hostname)) return '';
      let path = url.pathname;
      if (path === '/api.php') return '';
      if (path === '/index.php' || path.startsWith('/index.php_title=')) {
        const title = path === '/index.php' ? url.searchParams.get('title') : decodeURIComponent(path.slice(17).split('&')[0]);
        if (!title || title.length > 300 || /[\u0000-\u001F]/.test(title)) return '';
        path = '/' + encodeURIComponent(title.replace(/ /g, '_'));
      }
      return 'https://p99.funcamp.net' + path + url.hash;
    } catch (_) { return ''; }
  }
  function snapshot(input) {
    let encoded;
    try { encoded = JSON.stringify(input); } catch (_) { fail(); }
    if (!encoded || new TextEncoder().encode(encoded).byteLength > MAX_BYTES) throw new Error('Offline files must be 8 MiB or smaller.');
    if (!object(input) || input.format !== 'vantage-offline' || input.schema !== 1) fail();
    const exported = text(input.exported_at, 80);
    if (!/^\d{4}-\d{2}-\d{2}T/.test(exported) || !Number.isFinite(Date.parse(exported))) fail();
    const result = {format: 'vantage-offline', schema: 1, exported_at: exported, source_version: text(input.source_version, 64), guild: null, zone: null, quest: null, truncated: rows(input.truncated ?? [], 32, value => text(value, 200))};
    if (input.guild != null) {
      const value = input.guild, guild = fields(value, ['name', 'slug'], 240);
      guild.standings = rows(value.standings, 10000, row => fields(row, ['name', 'class', 'level', 'rank', 'dkp', 'attendance'], 240));
      if (!Number.isSafeInteger(value.standings_total) || value.standings_total < 0) fail();
      guild.standings_total = value.standings_total;
      guild.loot = rows(value.loot, MAX_LOOT_ROWS, row => ({...fields(row, ['date', 'item', 'character', 'dkp', 'raid'], 500), wiki_url: safeURL(row.wiki_url)}));
      guild.raids = rows(value.raids, 300, row => fields(row, ['date', 'name', 'items', 'awarded', 'spent'], 500));
      guild.sheets = rows(value.sheets, 32, row => ({...fields(row, ['name'], 240), url: safeURL(row.url, 'sheet')}));
      result.guild = guild;
    }
    if (input.zone != null) {
      const value = input.zone;
      result.zone = {...fields(value, ['name', 'era', 'levels'], 500), summary: text(value.summary, 8000), wiki_url: safeURL(value.wiki_url),
        unique_items: rows(value.unique_items, 2000, row => text(row, 500)),
        mobs: rows(value.mobs, 2000, row => {
          const mob = fields(row, ['name', 'level', 'class', 'race', 'location', 'loot'], 4000);
          if (row.named !== undefined && typeof row.named !== 'boolean') fail();
          return {...mob, named: Boolean(row.named)};
        })};
    }
    if (input.quest != null) {
      const value = input.quest;
      const steps = rows(value.steps, 180, row => {
        const step = fields(row, ['text', 'kind'], 4000);
        if (!['action', 'group', ''].includes(step.kind)) fail();
        return step;
      });
      result.quest = {title: text(value.title, 500), summary: text(value.summary, 12000), wiki_url: safeURL(value.wiki_url),
        metadata: fields(value.metadata ?? {}, ['Start Zone', 'Quest Giver', 'Minimum Level', 'Classes'], 2000),
        rewards: rows(value.rewards, 200, row => text(row, 1000)), steps,
        checked: rows(value.checked, 180, row => { if (!Number.isSafeInteger(row) || row < 0 || row >= steps.length) fail(); return row; })};
    }
    if (!result.guild && !result.zone && !result.quest) throw new Error('This file has no guild, zone, or quest data to save.');
    return result;
  }
  function privateOrigin(value) {
    try {
      const url = new URL(value);
      if (url.origin !== value || url.protocol !== 'http:' || url.username || url.password) return '';
      const host = url.hostname.toLowerCase(), parts = host.split('.').map(Number);
      const ipv4 = /^\d{1,3}(\.\d{1,3}){3}$/.test(host) && parts.every(part => part >= 0 && part <= 255);
      const lan = ipv4 && (parts[0] === 10 || parts[0] === 127 || (parts[0] === 192 && parts[1] === 168) || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31));
      return lan || host === 'localhost' || /^[a-z0-9-]+\.local$/.test(host) ? url.origin : '';
    } catch (_) { return ''; }
  }
  function handoff(onSnapshot, onStatus) {
    if (!location.hash.startsWith('#import?')) return null;
    const parameters = new URLSearchParams(location.hash.slice(8));
    const nonce = parameters.get('nonce') || '', origin = privateOrigin(parameters.get('origin') || ''), source = window.opener;
    history.replaceState(null, '', '#offline');
    if (!source || !origin || !/^[a-f0-9]{64}$/.test(nonce)) { onStatus('Open your saved offline file here to import it.'); return null; }
    const deadline = Date.now() + 60000;
    let complete = false, received = false;
    const finish = accepted => {
      if (complete) return;
      complete = true; clearTimeout(expiry); window.removeEventListener('message', receive);
      if (Date.now() <= deadline) source.postMessage({type: 'vantage-offline-result', schema: 1, nonce, accepted: Boolean(accepted)}, origin);
    };
    const expiry = setTimeout(() => { finish(false); onStatus('Transfer expired. Use Import file, or send a new copy from the PC connection.'); }, 60000);
    function receive(event) {
      if (complete || received || Date.now() > deadline || event.source !== source || event.origin !== origin) return;
      const message = event.data;
      if (!object(message) || message.type !== 'vantage-offline-snapshot' || message.schema !== 1 || message.nonce !== nonce) return;
      received = true;
      try { onSnapshot(snapshot(message.snapshot), accepted => finish(accepted), () => !complete && Date.now() <= deadline); }
      catch (error) { onStatus(error.message); finish(false); }
    }
    window.addEventListener('message', receive);
    source.postMessage({type: 'vantage-offline-ready', schema: 1, nonce}, origin);
    onStatus('Waiting for the saved copy from your PC connection…');
    return {cancel: () => finish(false)};
  }
  window.VantageOffline = Object.freeze({MAX_BYTES, snapshot, safeURL, handoff});
})();
