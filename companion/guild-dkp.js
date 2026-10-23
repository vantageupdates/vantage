/* Public OpenDKP browsing is independent of the PC's selected guild/character. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.VantageGuildDKP = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const PREFIX = 'guild-dkp:v1:';
  const text = value => String(value ?? '');
  const norm = value => text(value).toLocaleLowerCase().trim();
  const validDate = value => Number.isFinite(Date.parse(value));
  const stamp = value => validDate(value) ? new Date(value).toLocaleString() : 'Date unavailable';
  const amount = value => value === null || value === undefined || !Number.isFinite(Number(value)) ? 'Unknown' : Number(value).toLocaleString(undefined, {maximumFractionDigits: 2});
  const historyKey = (guild, character, days) => PREFIX + 'history:' + encodeURIComponent(guild.slug) + ':' + encodeURIComponent(character.id) + ':' + days;
  const directoryKey = guild => PREFIX + 'directory:' + encodeURIComponent(guild.slug);
  const RESTRICTED = 'This guild restricts some public OpenDKP data. View its OpenDKP website for access requirements, or choose a public guild. This phone panel does not sign in.';
  const errorMessage = (error, fallback) => error?.code === 'public-restricted' ? RESTRICTED : fallback;
  const hasRestrictedSource = result => Object.values(result.sources || {}).some(source => source.code === 'public-restricted');

  function createSession({client, storage, model = globalThis.VantageDKP, onChange = () => {}}) {
    const state = {guild: null, directory: null, character: null, history: null, days: 90,
      busy: false, message: 'Choose your OpenDKP guild to begin. No PC connection is needed.',
      directorySavedAt: '', historySavedAt: '', directoryStale: false, historyStale: false};
    let generation = 0, controller, destroyed = false, clearing = false;
    const writes = new Map();
    const revisions = new Map();
    const emit = () => { if (!destroyed) onChange({...state}); };
    function begin() { controller?.abort(); controller = new AbortController(); return ++generation; }
    const active = gen => !destroyed && gen === generation;
    async function prepare(gen, inheritedRevision) {
      let revision;
      try { revision = storage.guildRevision ? await storage.guildRevision() : 0; }
      catch (_) { revision = -1; }
      if (!active(gen)) return false;
      // Automatic descendants retain their initiating revision even if a
      // partial/failed parent did not attempt a guarded cache write.
      if (inheritedRevision !== undefined && revision !== inheritedRevision) { resetAfterClear(); return false; }
      revisions.set(gen, revision); return true;
    }
    function resetAfterClear() {
      begin(); Object.assign(state, {guild: null, directory: null, character: null, history: null, busy: false,
        directorySavedAt: '', historySavedAt: '', directoryStale: false, historyStale: false,
        message: 'Saved OpenDKP data was cleared in another view. Choose a guild to load a new copy.'}); emit();
    }
    const unsubscribeReset = storage.onGuildReset?.(() => {
      if (clearing || destroyed) return;
      resetAfterClear();
    });
    async function read(key, gen, check) {
      try { const record = await storage.get(key); return active(gen) && record?.key === key && check(record.payload) ? record : null; }
      catch (_) { return null; }
    }
    async function save(key, payload, gen) {
      const operation = (writes.get(key) || Promise.resolve()).catch(() => {}).then(async () => {
        if (!active(gen)) return null;
        const record = storage.putGuildRecord ? await storage.putGuildRecord(key, payload, revisions.get(gen)) : await storage.put(key, payload);
        if (!record && active(gen)) {
          // Invalidate the entire request chain, not just this write: an
          // automatic character refresh must not adopt the post-clear revision.
          resetAfterClear();
          throw new Error('Saved OpenDKP data was cleared in another view.');
        }
        return active(gen) && record?.key === key ? record : null;
      });
      writes.set(key, operation);
      return operation;
    }
    async function selectCharacter(id, days = state.days, inheritedRevision) {
      if (clearing) return;
      const character = state.directory?.characters.find(row => text(row.id) === text(id));
      const prior = state.character?.id === character?.id && state.days === days ? {payload: state.history, savedAt: state.historySavedAt} : null;
      const gen = begin();
      if (!await prepare(gen, inheritedRevision)) return;
      state.character = character || null; state.days = days; state.history = null;
      state.historySavedAt = ''; state.historyStale = false;
      if (!character || !state.guild) { state.busy = false; state.message = 'Choose a character to view their DKP history.'; emit(); return; }
      const guild = state.guild, key = historyKey(guild, character, days);
      state.busy = true; state.message = 'Checking ' + character.name + '’s history…'; emit();
      const saved = await read(key, gen, value => value?.guild?.slug === guild.slug && text(value.character?.id) === text(character.id) && value.days === days && Array.isArray(value.entries) && !value.partial) || (prior?.payload && !prior.payload.partial ? prior : null);
      if (!active(gen)) return;
      if (saved) { state.history = saved.payload; state.historySavedAt = saved.savedAt; state.historyStale = true; emit(); }
      try {
        const result = await client.history(guild, character, {days, signal: controller.signal});
        if (!active(gen)) return;
        if (result.partial) {
          if (!saved) state.history = result;
          state.historyStale = true;
          state.message = 'Some history sources could not be checked. ' + (saved ? 'Keeping the last complete saved history.' : 'Showing incomplete results; they are not saved as a complete copy.');
          if (hasRestrictedSource(result)) state.message = RESTRICTED + ' ' + state.message;
        } else {
          state.history = result; state.historyStale = false;
          try { const record = await save(key, result, gen); if (!active(gen)) return; state.historySavedAt = record?.savedAt || ''; await save(PREFIX + 'selection', {slug: guild.slug, characterId: character.id, days}, gen); if (!active(gen)) return; state.message = record ? 'History updated and saved on this device.' : 'History updated for this visit.'; }
          catch (_) { if (!active(gen)) return; state.historySavedAt = ''; state.message = 'History updated, but could not be saved. The previous saved copy is unchanged.'; }
        }
      } catch (error) { if (!active(gen)) return; state.historyStale = true; state.message = errorMessage(error, saved ? 'Refresh unavailable. Showing the last complete saved history; reconnect and retry.' : 'History could not be loaded. Check your connection and retry.'); }
      if (active(gen)) { state.busy = false; emit(); }
    }
    async function loadGuild(value, preferredId = '', inheritedRevision) {
      if (clearing) return;
      const previousCharacter = state.character, previousHistory = state.history, previousHistorySavedAt = state.historySavedAt;
      const gen = begin();
      if (!await prepare(gen, inheritedRevision)) return;
      const previous = state.guild?.slug;
      state.busy = true; state.message = 'Finding your OpenDKP guild…'; emit();
      try {
        const slug = model.parseGuild(value);
        const cachedKey = PREFIX + 'guild:' + encodeURIComponent(text(slug));
        const cachedGuild = await read(cachedKey, gen, data => data?.slug === slug && data?.id);
        if (!active(gen)) return;
        if (cachedGuild) {
          const cachedDirectory = await read(directoryKey(cachedGuild.payload), gen, data => data?.guild?.slug === slug && Array.isArray(data.characters) && Array.isArray(data.standings) && !data.partial);
          if (!active(gen)) return;
          if (cachedDirectory) {
            Object.assign(state, {guild: cachedGuild.payload, directory: cachedDirectory.payload,
              directorySavedAt: cachedDirectory.savedAt, directoryStale: true,
              character: null, history: null, historySavedAt: '',
              message: 'Showing the saved roster while checking OpenDKP…'}); emit();
          }
        }
        let guild;
        try { guild = await client.resolveGuild(value, {signal: controller.signal}); }
        catch (error) { if (!cachedGuild) throw error; guild = cachedGuild.payload; }
        if (!active(gen)) return;
        state.guild = guild; state.character = null; state.history = null; state.historySavedAt = '';
        if (state.directory?.guild?.slug !== guild.slug) { state.directory = null; state.directorySavedAt = ''; }
        state.message = 'Loading the complete guild roster…'; emit();
        const key = directoryKey(guild);
        const saved = await read(key, gen, data => data?.guild?.slug === guild.slug && Array.isArray(data.characters) && Array.isArray(data.standings) && !data.partial) || (state.directory && !state.directory.partial ? {payload: state.directory, savedAt: state.directorySavedAt} : null);
        if (!active(gen)) return;
        if (saved) { state.directory = saved.payload; state.directorySavedAt = saved.savedAt; state.directoryStale = true; emit(); }
        try {
          const result = await client.directory(guild, {signal: controller.signal});
          if (!active(gen)) return;
          if (result.partial) {
            if (!saved) state.directory = result;
            state.directoryStale = true;
            state.message = 'Some guild sources are unavailable. ' + (saved ? 'Keeping the saved roster and balances.' : 'Available records are incomplete; retry to check the full roster.');
            if (hasRestrictedSource(result)) state.message = RESTRICTED + ' ' + state.message;
          } else {
            state.directory = result; state.directoryStale = false; state.directorySavedAt = '';
            try {
              const record = await save(key, result, gen); if (!active(gen)) return;
              state.directorySavedAt = record?.savedAt || '';
              await save(cachedKey, guild, gen); if (!active(gen)) return;
              await save(PREFIX + 'selection', {slug: guild.slug, characterId: preferredId, days: state.days}, gen); if (!active(gen)) return;
              state.message = 'Choose your character. Current balances come directly from OpenDKP.';
            } catch (_) { if (!active(gen)) return; state.message = 'Roster loaded, but could not be saved. The previous saved copy is unchanged.'; }
          }
        } catch (error) { if (!active(gen)) return; state.directoryStale = true; state.message = errorMessage(error, saved ? 'Guild refresh unavailable. Showing the saved roster and balances.' : 'Guild records could not be loaded. Check your connection and retry.'); }
        if (!active(gen)) return;
        state.busy = false; emit();
        if (preferredId && state.directory?.characters.some(row => text(row.id) === text(preferredId))) {
          if (previous === guild.slug && text(previousCharacter?.id) === text(preferredId)) { state.character = previousCharacter; state.history = previousHistory; state.historySavedAt = previousHistorySavedAt; }
          await selectCharacter(preferredId, state.days, revisions.get(gen));
        }
      } catch (error) { if (active(gen)) { state.busy = false; state.message = errorMessage(error, 'Guild not available. Enter its OpenDKP name or address, then retry.'); emit(); } }
    }
    async function restore() {
      const gen = generation;
      if (!await prepare(gen)) return;
      const saved = await read(PREFIX + 'selection', gen, value => typeof value?.slug === 'string');
      if (!saved || !active(gen)) return;
      state.days = [30, 90, 180, 365, 3650].includes(saved.payload.days) ? saved.payload.days : 90;
      await loadGuild(saved.payload.slug, saved.payload.characterId, revisions.get(gen));
    }
    async function loadRaid(id) {
      const gen = generation, original = state.history, guild = state.guild, character = state.character;
      if (!original || !id || state.busy) return;
      let completed = false;
      state.busy = true; state.message = 'Checking individual raid ticks…'; emit();
      try {
        const detail = await client.raidDetail(guild, id, {signal: controller.signal});
        if (!active(gen) || state.history !== original) return;
        const updated = {...original, raidDetails: {...original.raidDetails, [id]: detail}};
        const start = Date.parse(original.periodStart), end = Date.parse(original.periodEnd);
        updated.entries = model.buildHistory({...updated, characterId: character.id, characterName: character.name}).filter(row => !validDate(row.timestamp) || ((!Number.isFinite(start) || Date.parse(row.timestamp) >= start) && (!Number.isFinite(end) || Date.parse(row.timestamp) <= end)));
        updated.summary = model.summarizeHistory(updated.entries); state.history = updated;
        state.message = 'Raid tick details updated.';
        completed = true;
        if (!updated.partial && !state.historyStale) {
          try { const record = await save(historyKey(guild, character, state.days), updated, gen); if (!active(gen)) return; state.historySavedAt = record?.savedAt || ''; }
          catch (_) { if (!active(gen)) return; state.historySavedAt = ''; state.message += ' Could not save these new details; the previous saved copy is unchanged.'; }
        }
      } catch (error) { if (!active(gen)) return; state.message = errorMessage(error, 'Raid details could not be checked. Existing history is unchanged; retry when connected.'); }
      if (active(gen)) { state.busy = false; emit(); }
      return completed;
    }
    async function forget() {
      if (clearing) return;
      clearing = true; begin(); state.busy = true; state.message = 'Removing saved OpenDKP data…'; emit();
      try {
        await Promise.allSettled([...writes.values()]); await storage.removePrefix(PREFIX);
        Object.assign(state, {guild: null, directory: null, character: null, history: null,
          directorySavedAt: '', historySavedAt: '', directoryStale: false, historyStale: false,
          message: 'Saved OpenDKP data removed. Imported PC copies and public catalogs are unchanged.'});
      } finally { clearing = false; state.busy = false; emit(); }
    }
    return {state, loadGuild, selectCharacter, loadRaid, restore, forget,
      refresh: () => state.guild ? loadGuild(state.guild.slug, state.character?.id) : Promise.resolve(),
      destroy: () => { destroyed = true; begin(); unsubscribeReset?.(); }};
  }

  function mount(container, {api = globalThis.VantageDKP, storage = globalThis.VantageStorage, headingLevel = 2, onStateChange = () => {}} = {}) {
    if (!container || !api || !storage) return null;
    const doc = container.ownerDocument, prefix = container.id + '-dkp-';
    const element = (tag, className = '', content = '') => { const item = doc.createElement(tag); item.className = className; item.textContent = content; return item; };
    const button = label => { const item = element('button', '', label); item.type = 'button'; return item; };
    function field(parent, name, label, tag = 'input') {
      const wrap = element('div', 'vdkp-field'), control = element(tag); control.id = prefix + name;
      const caption = element('label', '', label); caption.htmlFor = control.id; wrap.append(caption, control); parent.append(wrap); return control;
    }
    const options = (select, rows) => select.replaceChildren(...rows.map(([value, label]) => { const item = element('option', '', label); item.value = text(value); return item; }));
    container.classList.add('vdkp');
    const intro = element('p', 'vdkp-meta', 'Public OpenDKP records · works without the PC. Your selection here does not change Vantage on the PC.');
    const form = element('form', 'vdkp-controls'), guildInput = field(form, 'guild', 'OpenDKP guild');
    guildInput.required = true; guildInput.autocomplete = 'off'; guildInput.placeholder = 'Guild name or guild.opendkp.com';
    const open = button('Open guild'); open.type = 'submit'; form.append(open);
    const status = element('p', 'vdkp-status'); status.id = prefix + 'status'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); status.setAttribute('aria-atomic', 'true'); guildInput.setAttribute('aria-describedby', status.id);
    const identity = element('p', 'vdkp-meta');
    const choice = element('fieldset', 'vdkp-controls'); choice.append(element('legend', '', 'Character and history period'));
    const rosterSearch = field(choice, 'roster-search', 'Find character'); rosterSearch.type = 'search'; rosterSearch.autocomplete = 'off';
    const roster = field(choice, 'character', 'Character', 'select');
    const period = field(choice, 'period', 'History period', 'select'); options(period, [[30, 'Last 30 days'], [90, 'Last 90 days'], [180, 'Last 180 days'], [365, 'Last 365 days'], [3650, 'All available (up to 10 years)']]); period.value = '90';
    const refresh = button('Refresh guild and history'); choice.append(refresh);
    const rosterCount = element('p', 'vdkp-meta'), balance = element('section', 'vdkp-balance');
    const rosterAnnouncement = element('p', 'vdkp-sr'); rosterAnnouncement.setAttribute('role', 'status'); rosterAnnouncement.setAttribute('aria-live', 'polite');
    const headingTag = 'h' + Math.min(5, Math.max(2, headingLevel));
    const historySection = element('section', 'vdkp-history'); historySection.append(element(headingTag, '', 'DKP history'));
    const historyMeta = element('p', 'vdkp-meta'), filters = element('div', 'vdkp-controls');
    const search = field(filters, 'history-search', 'Search history'); search.type = 'search'; search.autocomplete = 'off'; search.placeholder = 'Raid, item, note or source';
    const type = field(filters, 'kind', 'Record type', 'select'); options(type, [['', 'All record types'], ['raid', 'Raid awards'], ['adjustment', 'Adjustments'], ['loot', 'Loot']]);
    const pool = field(filters, 'pool', 'DKP pool', 'select'); options(pool, [['', 'All pools']]);
    const sort = field(filters, 'sort', 'Sort history', 'select'); options(sort, [['newest', 'Newest first'], ['oldest', 'Oldest first'], ['highest', 'Largest amount first'], ['lowest', 'Smallest amount first']]);
    const totals = element('div', 'vdkp-history-totals');
    const count = element('p', 'vdkp-meta'), announcement = element('p', 'vdkp-sr'); announcement.setAttribute('role', 'status'); announcement.setAttribute('aria-live', 'polite');
    const rows = element('div', 'vdkp-rows'), more = button('Show more history');
    historySection.append(historyMeta, filters, totals, count, announcement, rows, more);
    const forget = button('Forget saved OpenDKP data');
    const storageNote = element('p', 'vdkp-meta', 'Only successful public guild copies are saved here. Imported PC snapshots and their export controls remain separate.');
    container.replaceChildren(intro, form, status, identity, choice, rosterCount, rosterAnnouncement, balance, historySection, storageNote, forget);
    let current, lastDirectory, lastHistory, lastRowHistory, emptyState, lastRowContext = '', limit = 60, announceTimer;
    let renderedRecords = [];
    const client = api.createClient();
    const session = createSession({client, storage, model: api, onChange: render});
    function rosterOptions() {
      const wanted = text(current.character?.id), query = norm(rosterSearch.value);
      const all = current.directory?.characters || [], matches = all.filter(row => !query || norm(row.name).includes(query));
      const selected = all.find(row => text(row.id) === wanted);
      const visible = selected && !matches.includes(selected) ? [selected, ...matches] : matches;
      options(roster, [['', 'Choose a character…'], ...visible.map(row => [row.id, row.name])]); roster.value = wanted;
      rosterCount.textContent = matches.length + ' of ' + all.length + ' characters match.';
    }
    function render(next) {
      current = next; status.textContent = next.message;
      onStateChange(next);
      if (next.guild && !guildInput.value) guildInput.value = next.guild.slug;
      rows.setAttribute('aria-busy', text(next.busy));
      open.disabled = next.busy; refresh.disabled = next.busy || !next.guild; forget.setAttribute('aria-disabled', text(next.busy));
      choice.hidden = !next.directory; balance.hidden = !next.character; historySection.hidden = !next.character;
      identity.textContent = next.guild ? next.guild.name + ' · OpenDKP · ' + (next.directoryStale ? (next.directorySavedAt ? 'Saved / refresh unavailable · ' : 'Incomplete check · ') : '') + 'checked ' + stamp(next.directory?.fetchedAt) + (next.directorySavedAt ? ' · saved ' + stamp(next.directorySavedAt) : ' · not saved on this device') : '';
      if (next.directory !== lastDirectory) { lastDirectory = next.directory; rosterSearch.value = ''; }
      rosterOptions(); period.value = text(next.days);
      balance.replaceChildren(element(headingTag, '', (next.character?.name || 'Character') + ' · Current balance'));
      const balances = next.character ? api.currentBalances(next.directory?.standings || [], next.character) : [];
      if (balances.length) {
        const list = element('dl', 'vdkp-balances');
        balances.forEach(row => { const pair = element('div'); pair.append(element('dt', '', row.pool || 'Unspecified pool'), element('dd', '', amount(row.amount) + ' DKP')); list.append(pair); }); balance.append(list);
      } else balance.append(element('p', '', 'Current balance unavailable for this character.'));
      balance.append(element('p', 'vdkp-meta', 'OpenDKP current balance' + (next.directory?.asOf ? ' · source date ' + stamp(next.directory.asOf) : ' · source date unavailable') + '. Not calculated from the history period below.'));
      if (next.directoryStale) balance.append(element('p', 'vdkp-warning', next.directorySavedAt ? 'Saved balance — it may have changed since this copy was checked.' : 'Guild data could not be fully checked. Retry to verify these available balances.'));
      const context = [next.guild?.slug, next.character?.id, next.days].join(':');
      if (next.history !== lastHistory) {
        lastHistory = next.history;
        if (context !== lastRowContext) limit = 60;
        const selectedPool = pool.value, pools = new Map((next.history?.entries || []).map(entry => [text(entry.pool_key) || '__unknown', entry.pool || 'Unspecified pool']));
        options(pool, [['', 'All pools'], ...pools]); if (pools.has(selectedPool)) pool.value = selectedPool;
      }
      historyMeta.textContent = next.history ? (next.days === 3650 ? 'All available, up to 10 years' : 'Last ' + next.days + ' days') + ' · ' + (next.history.partial ? 'Incomplete results · ' : next.historyStale ? 'Saved results / refresh unavailable · ' : '') + 'checked ' + stamp(next.history.fetchedAt) + (next.historySavedAt ? ' · saved ' + stamp(next.historySavedAt) : ' · not saved as a complete offline copy') : 'Choose a character to load dated records.';
      if (next.history !== lastRowHistory || context !== lastRowContext) {
        lastRowHistory = next.history; lastRowContext = context; renderRows();
      } else {
        rows.querySelectorAll('button').forEach(control => { control.setAttribute('aria-disabled', text(next.busy)); });
        updateEmptyState();
      }
    }
    function updateEmptyState() {
      if (emptyState) emptyState.textContent = current.busy ? 'Loading history…' : current.history ? 'No records match this period and these filters.' : 'No history available yet. Choose Refresh to retry.';
    }
    function addDetail(parent, label, value) { if (value === null || value === undefined || value === '') return; const row = element('p'); row.append(element('strong', '', label + ': '), doc.createTextNode(text(value))); parent.append(row); }
    function historyRow(entry) {
      const details = element('details', 'vdkp-entry'), summary = element('summary');
      const title = (entry.kind === 'loot' && entry.item_name) || entry.source || entry.description || 'DKP record';
      summary.append(element('span', 'vdkp-entry-title', title), element('span', 'vdkp-entry-amount', amount(entry.amount) + ' DKP'), element('span', 'vdkp-meta', stamp(entry.timestamp) + ' · ' + (entry.kind || 'Record') + ' · ' + (entry.pool || 'Unspecified pool')));
      const body = element('div', 'vdkp-entry-body');
      addDetail(body, 'Description', entry.description); addDetail(body, 'Source', entry.ledger_source || entry.source); addDetail(body, 'Date', stamp(entry.timestamp)); addDetail(body, 'Pool', entry.pool || 'Unspecified pool'); addDetail(body, 'Amount', amount(entry.amount) + ' DKP');
      if (entry.item_name) { const link = element('a', '', entry.item_name + ' on Project 1999 Wiki (new tab)'); link.href = 'https://wiki.project1999.com/' + encodeURIComponent(text(entry.item_name).replace(/ /g, '_')); link.target = '_blank'; link.rel = 'noopener noreferrer'; body.append(link); }
      if (entry.kind === 'raid') {
        const ticks = entry.ticks || []; body.append(element('h' + Math.min(6, headingLevel + 1), '', 'Raid ticks'));
        if (!ticks.length) body.append(element('p', '', 'No individual tick records were returned for this raid.'));
        for (const tick of ticks) {
          const line = element('p', 'vdkp-tick'); line.textContent = [tick.description || tick.source || 'Raid tick', stamp(tick.timestamp), tick.attended === true ? 'Attended' : tick.attended === false ? 'Not attended' : 'Attendance unknown', amount(tick.amount) + ' DKP', tick.pool || 'Unspecified pool'].join(' · '); body.append(line);
        }
        if (entry.raid_id) { const load = button('Check raid tick details'); load.setAttribute('aria-disabled', text(current.busy)); load.addEventListener('click', () => { if (!current.busy) session.loadRaid(entry.raid_id); }); body.append(load); }
      }
      details.dataset.raidId = text(entry.raid_id);
      details.dataset.poolKey = text(entry.pool_key);
      details.append(summary, body); return details;
    }
    function recordKeys(entry) {
      const scope = [current.guild?.slug, current.character?.id];
      if (entry.history_id) return [...new Set([entry.history_id, ...(entry.history_aliases || [])])].map(id => JSON.stringify([...scope, entry.kind, id]));
      const identity = entry.kind === 'raid' && entry.raid_id ? ['raid', entry.raid_id, entry.pool_key] : [entry.kind, entry.timestamp, entry.source, entry.description, entry.item_name, entry.pool_key];
      return [JSON.stringify([...scope, ...identity])];
    }
    function recordIndex(records) {
      const index = new Map();
      for (const record of records) for (const key of record.keys) {
        if (!index.has(key)) index.set(key, new Set());
        index.get(key).add(record);
      }
      return index;
    }
    function matches(record, index) {
      return new Set(record.keys.flatMap(key => [...(index.get(key) || [])]));
    }
    function renderRows(announce = false) {
      // Preserve disclosure state and only the focus that this update replaces.
      // A response must never pull focus back from filters or another page.
      const existing = recordIndex(renderedRecords);
      const focused = doc.activeElement, focusedRow = focused?.closest('details');
      const focusOwner = rows.contains(focused) && !container.closest('[hidden]') ? focusedRow : null;
      const focusIndex = focusOwner ? [...focusedRow.querySelectorAll('summary,button,a')].indexOf(focused) : -1;
      const query = norm(search.value);
      const all = current.history?.entries || [];
      const filtered = all.filter(row => (!type.value || row.kind === type.value) && (!pool.value || (text(row.pool_key) || '__unknown') === pool.value) && (!query || norm([row.source, row.description, row.ledger_source, row.item_name, row.pool, row.timestamp, ...(row.ticks || []).map(tick => tick.description)].join(' ')).includes(query)));
      filtered.sort((a, b) => {
        if (sort.value === 'highest' || sort.value === 'lowest') {
          if (a.amount == null) return b.amount == null ? 0 : 1; if (b.amount == null) return -1;
          return (Number(a.amount) - Number(b.amount)) * (sort.value === 'highest' ? -1 : 1);
        }
        const left = Date.parse(a.timestamp), right = Date.parse(b.timestamp);
        if (!Number.isFinite(left)) return Number.isFinite(right) ? 1 : 0; if (!Number.isFinite(right)) return -1;
        return (left - right) * (sort.value === 'newest' ? -1 : 1);
      });
      count.textContent = filtered.length + ' matching records · showing ' + Math.min(limit, filtered.length);
      const summary = api.summarizeHistory(filtered);
      totals.replaceChildren(element('p', 'vdkp-meta', 'In the selected history and filters — not your current balance:'));
      for (const bucket of summary.by_pool || []) totals.append(element('p', '', (bucket.pool || 'Unspecified pool') + ' · credited ' + amount(bucket.credits) + ' · spent ' + amount(bucket.debits) + ' · net ' + amount(bucket.net) + ' DKP' + (bucket.unknown_count ? ' · ' + bucket.unknown_count + ' unknown amounts excluded' : '')));
      if (summary.unknown_pool_count) totals.append(element('p', 'vdkp-warning', summary.unknown_pool_count + ' records have an unspecified pool; they are not combined with a named balance.'));
      const updated = filtered.slice(0, limit).map(entry => ({row: historyRow(entry), keys: recordKeys(entry)}));
      const updatedIndex = recordIndex(updated);
      let focusTarget;
      for (const record of updated) {
        record.row.dataset.recordKey = record.keys[0];
        const candidates = matches(record, existing), previous = candidates.size === 1 ? [...candidates][0] : null;
        // Both directions must be unique; a shared item name or ambiguous alias
        // cannot move disclosure state or focus to another purchase.
        if (previous && matches(previous, updatedIndex).size === 1) {
          record.row.open = previous.row.open;
          if (previous.row === focusOwner) focusTarget = record.row;
        }
      }
      renderedRecords = updated;
      rows.replaceChildren(...updated.map(record => record.row));
      if (focusIndex >= 0) focusTarget?.querySelectorAll('summary,button,a')[focusIndex]?.focus();
      emptyState = null;
      if (!filtered.length) { emptyState = element('p', 'vdkp-empty'); rows.append(emptyState); updateEmptyState(); }
      more.hidden = filtered.length <= limit;
      if (announce) { clearTimeout(announceTimer); announceTimer = setTimeout(() => { announcement.textContent = count.textContent; }, 550); }
    }
    guildInput.addEventListener('input', () => { guildInput.setCustomValidity(''); guildInput.removeAttribute('aria-invalid'); });
    form.addEventListener('submit', event => {
      event.preventDefault();
      try { api.parseGuild(guildInput.value.trim()); }
      catch (error) { guildInput.setCustomValidity(error.message); guildInput.setAttribute('aria-invalid', 'true'); status.textContent = error.message; guildInput.reportValidity(); return; }
      session.loadGuild(guildInput.value.trim());
    });
    rosterSearch.addEventListener('input', () => { rosterOptions(); clearTimeout(announceTimer); announceTimer = setTimeout(() => { rosterAnnouncement.textContent = rosterCount.textContent; }, 550); });
    roster.addEventListener('change', () => session.selectCharacter(roster.value));
    period.addEventListener('change', () => session.selectCharacter(roster.value, Number(period.value)));
    refresh.addEventListener('click', () => session.refresh());
    search.addEventListener('input', () => { limit = 60; renderRows(true); });
    for (const control of [type, pool, sort]) control.addEventListener('change', () => { limit = 60; renderRows(true); });
    more.addEventListener('click', () => { const previous = limit; limit += 60; renderRows(true); rows.children[previous]?.querySelector('summary')?.focus(); });
    forget.addEventListener('click', async () => {
      if (current.busy) return;
      if (!globalThis.confirm('Forget all saved OpenDKP guilds, balances and character history on this device? Imported PC snapshots and catalogs will stay saved.')) return;
      const owner = doc.activeElement;
      forget.setAttribute('aria-disabled', 'true');
      try { await session.forget(); guildInput.value = ''; if (owner === forget && doc.activeElement === forget && !container.closest('[hidden]')) guildInput.focus(); }
      catch (_) { status.textContent = 'Saved OpenDKP data could not be removed. Retry with device storage available.'; }
      finally { forget.setAttribute('aria-disabled', 'false'); }
    });
    render(session.state);
    session.restore();
    return {session, suggestGuild(value) { if (!guildInput.value && !session.state.guild) guildInput.value = text(value); }, destroy() { clearTimeout(announceTimer); session.destroy(); }};
  }
  return Object.freeze({createSession, mount, historyKey, directoryKey});
});
