/* Public, read-only OpenDKP data. No PC session, account, or credentials required.
 * Provenance rules mirror vantage.helpers.dkp_history; never derive a balance
 * from a filtered history or award a whole raid's points to one character. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.VantageDKP = api;
})(globalThis, function () {
  'use strict';
  const API_ROOT = 'https://api.opendkp.com';
  const object = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
  const text = value => String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
  const lower = value => text(value).toLowerCase();
  const first = (row, ...keys) => { for (const key of keys) if (row[key] != null && row[key] !== '') return row[key]; return null; };
  const id = value => { const result = text(value); return ['', '0', '-1', 'true', 'false'].includes(result.toLowerCase()) ? '' : result; };
  const rows = payload => {
    if (Array.isArray(payload)) return payload.filter(object);
    if (object(payload)) for (const key of ['Models', 'Data', 'data', 'Rows', 'rows', 'Items']) if (Array.isArray(payload[key])) return rows(payload[key]);
    return [];
  };
  const finite = value => {
    if (value == null || typeof value === 'boolean' || typeof value === 'object' || (typeof value === 'string' && !value.trim())) return null;
    if (typeof value === 'string' && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  };
  // Partial summation retains small awards next to large ones, like math.fsum.
  function sum(values) {
    const partials = [];
    for (let value of values) {
      if (finite(value) == null) return null;
      let index = 0;
      for (let other of partials) {
        if (Math.abs(value) < Math.abs(other)) [value, other] = [other, value];
        const high = value + other;
        if (!Number.isFinite(high)) return null;
        const low = other - (high - value);
        if (low) partials[index++] = low;
        value = high;
      }
      partials.length = index;
      partials.push(value);
    }
    return finite(partials.reduce((total, value) => total + value, 0));
  }
  function identity(row, characterId, characterName, member = false) {
    const rowId = id(first(row, 'CharacterId', 'CharacterID', 'characterId'));
    const keys = ['CharacterName', 'PlayerName', 'MemberName', 'ToonName', 'characterName'];
    if (member) keys.push('Name');
    const name = lower(first(row, ...keys));
    if (rowId && characterId && rowId !== characterId) return false;
    if (name && characterName && name !== characterName) return false;
    return (rowId && characterId) || (name && characterName) ? true : null;
  }
  function poolParts(row) {
    const nested = object(row.Pool) ? row.Pool : {};
    return [id(first(row, 'PoolId', 'PoolID', 'DkpPoolId') || first(nested, 'PoolId', 'PoolID', 'Id')),
      text(first(row, 'PoolName', 'DkpPoolName') || first(nested, 'Name', 'PoolName') || (typeof row.Pool === 'string' ? row.Pool : ''))];
  }
  function poolResolver(allRows) {
    const names = new Map();
    for (const row of allRows) {
      const [poolId, name] = poolParts(row);
      if (poolId && name) { const key = lower(name); if (!names.has(key)) names.set(key, new Set()); names.get(key).add(poolId); }
    }
    return (row, fallback = ['', 'Unknown pool']) => {
      let [poolId, name] = poolParts(row);
      const ids = names.get(lower(name)) || new Set();
      if (!poolId && name && ids.size === 1) poolId = [...ids][0];
      if (poolId) return ['id:' + poolId, name || 'Pool ' + poolId];
      if (name) return ids.size > 1 ? ['', name + ' (pool unclear)'] : ['name:' + lower(name), name];
      return fallback;
    };
  }
  const timestamp = row => text(first(row, 'Timestamp', 'Date', 'RaidDate', 'StartTimestamp', 'StartTime', 'CreatedAt'));
  const raidId = row => id(first(row, 'RaidId', 'RaidID', 'raid_id', 'Id', 'id'));
  function attendance(tick, characterId, characterName) {
    const evidence = [];
    if ('Attended' in tick) {
      const value = lower(tick.Attended);
      if (!['0', '1', 'false', 'true'].includes(value)) return null;
      evidence.push(['1', 'true'].includes(value));
    }
    const members = first(tick, 'Characters', 'characters');
    if (Array.isArray(members)) {
      const identities = members.filter(object).map(member => identity(member, characterId, characterName, true));
      if (identities.includes(true)) evidence.push(true);
      else if (identities.length !== members.length || identities.includes(null)) return null;
      else evidence.push(false);
    }
    return evidence.length && new Set(evidence).size === 1 ? evidence[0] : null;
  }
  const entry = (kind, row, pool, source, description, amount, raid = '', ticks = []) => ({
    kind, timestamp: timestamp(row), source, description, amount, pool_key: pool[0], pool: pool[1], raid_id: raid, raw: row, ticks,
  });
  function deduplicate(entries, identityOf) {
    const result = [], seen = new Map();
    for (const value of entries) {
      const eventId = identityOf(value.raw), key = JSON.stringify([value.pool_key, eventId]);
      if (!eventId || !value.pool_key || !seen.has(key)) { result.push(value); if (eventId && value.pool_key) seen.set(key, value); }
      else if (seen.get(key).amount !== value.amount) { seen.get(key).amount = null; seen.get(key).description += ' · Conflicting source amounts'; }
    }
    return result;
  }
  function buildHistory({raids = [], adjustments = [], items = [], dkp = [], raidDetails = {}, characterId, characterName}) {
    characterId = id(characterId); characterName = lower(characterName);
    if (!characterId && !characterName) return [];
    const matches = row => identity(row, characterId, characterName);
    raids = rows(raids).filter(row => matches(row) !== false);
    adjustments = rows(adjustments).filter(row => matches(row) !== false);
    items = rows(items).filter(row => matches(row) !== false);
    const ledger = rows(dkp).filter(row => matches(row) === true), details = new Map();
    for (const [key, detail] of Object.entries(raidDetails || {})) {
      if (object(detail) && matches(detail) !== false && (!raidId(detail) || raidId(detail) === id(key))) details.set(id(key), detail);
    }
    const allRows = [...raids, ...adjustments, ...items, ...ledger, ...details.values()];
    for (const row of [...raids, ...details.values()]) allRows.push(...rows(row.Ticks));
    const poolFor = poolResolver(allRows), raidPools = new Map();
    for (const row of [...raids, ...details.values()]) {
      const rid = raidId(row), pool = poolFor(row);
      if (rid && pool[0]) { if (!raidPools.has(rid)) raidPools.set(rid, new Map()); raidPools.get(rid).set(pool[0], pool); }
    }
    const relatedPool = (row, rid = '') => {
      const pools = raidPools.get(rid) || new Map();
      return poolFor(row, pools.size === 1 ? [...pools.values()][0] : ['', 'Unknown pool']);
    };
    const ledgerTicks = new Map();
    for (const row of ledger) {
      if (lower(row.SourceType) !== 'raid') continue;
      const rid = id(row.SourceId), tid = id(row.TickId), key = JSON.stringify([rid, tid]);
      if (rid && tid) { if (!ledgerTicks.has(key)) ledgerTicks.set(key, []); ledgerTicks.get(key).push(row); }
    }
    const raidGroups = [], groupIndex = new Map();
    for (const row of raids) {
      const rid = raidId(row), pool = relatedPool(row, rid), key = JSON.stringify([rid, pool[0]]);
      if (rid && pool[0] && groupIndex.has(key)) groupIndex.get(key).copies.push(row);
      else { const group = {row, detail: details.get(rid) || {}, copies: [row], pool}; raidGroups.push(group); if (rid && pool[0]) groupIndex.set(key, group); }
    }
    const result = [];
    for (const group of raidGroups) {
      const {row, copies, pool: raidPool} = group, rid = raidId(row);
      const detail = poolFor(group.detail, raidPool)[0] === raidPool[0] ? group.detail : {};
      const source = text(first(row, 'RaidName', 'Name', 'EventName')) || 'Raid', detailTicks = rows(detail.Ticks);
      const tickGroups = [], tickIndex = new Map();
      const addTick = tick => {
        const tid = id(tick.TickId), pool = poolFor(tick, raidPool), key = JSON.stringify([pool[0], tid]);
        if (tid && tickIndex.has(key)) tickIndex.get(key).ticks.push(tick);
        else { const item = {ticks: [tick], pool}; tickGroups.push(item); if (tid) tickIndex.set(key, item); }
      };
      for (const copy of copies) for (const tick of rows(copy.Ticks)) addTick(tick);
      if (!tickGroups.length) detailTicks.forEach(addTick);
      const grouped = new Map();
      for (const {ticks, pool} of tickGroups) {
        const tick = ticks[0], tid = id(tick.TickId), evidence = [...ticks];
        if (tid) for (const candidate of detailTicks) {
          if (id(candidate.TickId) === tid && poolFor(candidate, raidPool)[0] === pool[0] && !evidence.some(item => JSON.stringify(item) === JSON.stringify(candidate))) evidence.push(candidate);
        }
        const knownAttendance = new Set(evidence.map(item => attendance(item, characterId, characterName)).filter(value => value !== null));
        const malformed = evidence.some(item => 'Attended' in item && !['0', '1', 'false', 'true'].includes(lower(item.Attended)));
        let attended = knownAttendance.size === 1 && !malformed ? [...knownAttendance][0] : null;
        if (evidence.some(item => ('Characters' in item || 'characters' in item) && attendance(item, characterId, characterName) === null)) attended = null;
        const awards = (ledgerTicks.get(JSON.stringify([rid, tid])) || []).filter(award => relatedPool(award, rid)[0] === pool[0]);
        const values = [...evidence, ...awards].filter(item => 'Value' in item).map(item => finite(item.Value));
        let amount = values.length && !values.includes(null) && new Set(values).size === 1 && attended === true ? values[0] : null;
        if (attended === false) amount = 0;
        const description = text(first(tick, 'Description', 'Name')) || text(evidence.find(item => item.Description)?.Description);
        const awardSource = text(awards.find(item => item.Source)?.Source);
        const normalized = {tick_id: tid, attended, amount, description: description || awardSource || 'Raid tick', source: awardSource || source,
          timestamp: awards.length ? timestamp(awards[0]) : timestamp(row), raw: tick, evidence: [...evidence, ...awards], pool: pool[1], pool_key: pool[0]};
        const key = JSON.stringify(pool);
        if (!grouped.has(key)) grouped.set(key, {pool, ticks: []});
        grouped.get(key).ticks.push(normalized);
      }
      if (!grouped.size) grouped.set(JSON.stringify(raidPool), {pool: raidPool, ticks: []});
      for (const {pool, ticks} of grouped.values()) {
        if (ticks.length && ticks.every(tick => tick.attended === false)) continue;
        const amounts = ticks.map(tick => tick.amount), amount = amounts.length && !amounts.includes(null) ? sum(amounts) : null;
        const count = ticks.filter(tick => tick.attended === true).length;
        const description = [text(first(row, 'Description', 'Notes') || first(detail, 'Description', 'Notes')),
          `${count} attended tick${count === 1 ? '' : 's'}`, amount === null ? 'Award unknown' : ''].filter(Boolean).join(' · ');
        result.push(entry('raid', row, pool, source, description, amount, rid, ticks));
      }
    }
    const ledgerAdjustments = ledger.filter(row => lower(row.SourceType) === 'adjustment'), adjustmentEntries = [];
    for (const row of ledgerAdjustments.length ? ledgerAdjustments : adjustments) {
      const fromLedger = ledgerAdjustments.includes(row), adjustmentId = id(fromLedger ? row.SourceId : row.AdjustmentId);
      const candidates = adjustments.filter(item => adjustmentId && id(item.AdjustmentId) === adjustmentId);
      const candidatePools = new Map(candidates.map(item => poolFor(item)).filter(pool => pool[0]).map(pool => [JSON.stringify(pool), pool]));
      const pool = poolFor(row, candidatePools.size === 1 ? [...candidatePools.values()][0] : ['', 'Unknown pool']);
      const supplemental = candidates.length === 1 ? candidates[0] : {}, source = text(first(row, 'Name', 'Source')) || 'Adjustment';
      const description = text(first(row, 'Description', 'Notes') || first(supplemental, 'Description', 'Notes', 'Name')) || source;
      adjustmentEntries.push(entry('adjustment', row, pool, source, description, finite(first(row, 'Value', 'Amount', 'DKP'))));
    }
    result.push(...deduplicate(adjustmentEntries, row => id(first(row, 'AdjustmentId', 'SourceId'))));
    const ledgerItems = ledger.filter(row => ['item', 'loot'].includes(lower(row.SourceType))), lootEntries = [];
    for (const row of ledgerItems.length ? ledgerItems : items) {
      const fromLedger = ledgerItems.includes(row), rid = id(fromLedger ? row.SourceId : first(row, 'RaidId', 'RaidID'));
      const amount = finite(fromLedger ? row.Value : first(row, 'DkpValue', 'DKPValue', 'DKP', 'Cost', 'Value', 'Amount'));
      const source = text(first(row, 'ItemName', 'Source', 'Name')) || 'Loot';
      const description = [text(first(row, 'Raid', 'RaidName')), text(first(row, 'Notes', 'Description'))].filter(Boolean).join(' · ') || source;
      const value = entry('loot', row, relatedPool(row, rid), source, description, amount === null ? null : fromLedger ? amount : -amount, rid);
      let itemName = text(row.ItemName);
      if (!itemName && fromLedger) {
        const names = new Set(items.filter(item => rid && id(first(item, 'RaidId', 'RaidID')) === rid && text(item.ItemName) &&
          (lower(source) === lower(item.ItemName) || lower(source).endsWith(' - ' + lower(item.ItemName)))).map(item => text(item.ItemName)));
        if (names.size === 1) itemName = [...names][0];
      }
      value.item_name = itemName; lootEntries.push(value);
    }
    result.push(...deduplicate(lootEntries, row => id(first(row, 'PurchaseId', 'CharacterItemId', 'LootId', 'TransactionId'))));
    const date = value => Number.isFinite(Date.parse(value)) ? Date.parse(value) : -Infinity;
    return result.sort((a, b) => date(b.timestamp) - date(a.timestamp));
  }
  function summarizeHistory(entries) {
    entries = rows(entries); const groups = new Map();
    for (const entry of entries) { const key = text(entry.pool_key); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(entry); }
    const summaries = [];
    for (const [key, values] of groups) {
      const amounts = values.map(row => finite(row.amount)), credits = sum(amounts.filter(value => value !== null && value > 0)), debits = sum(amounts.filter(value => value !== null && value < 0).map(value => -value));
      summaries.push({pool_key: key, pool: values[0].pool || 'Unknown pool', count: values.length, unknown_count: amounts.filter(value => value === null).length,
        credits: key ? credits : null, debits: key ? debits : null, net: key && credits !== null && debits !== null ? sum([credits, -debits]) : null});
    }
    const single = summaries.length === 1 && summaries[0].pool_key ? summaries[0] : {};
    return {count: entries.length, credits: single.credits ?? null, debits: single.debits ?? null, net: single.net ?? null,
      unknown_count: summaries.reduce((total, row) => total + row.unknown_count, 0), unknown_pool_count: (groups.get('') || []).length, by_pool: summaries};
  }
  function parseGuild(value) {
    value = text(value);
    if (value.length > 300) throw new Error('Enter a guild name or its OpenDKP website.');
    if (value.includes('.') || value.includes('://')) {
      let url;
      try { url = new URL(value.includes('://') ? value : 'https://' + value); } catch (_) { throw new Error('Enter a valid OpenDKP website.'); }
      if (url.protocol !== 'https:' || url.username || url.password || url.port) throw new Error('Use the guild’s HTTPS OpenDKP website.');
      const match = /^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)\.opendkp\.com$/i.exec(url.hostname);
      if (!match) throw new Error('Use a guild.opendkp.com address, or just the guild name.');
      value = match[1];
    }
    value = value.toLowerCase();
    if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(value) || ['api', 'www', 'admin'].includes(value)) throw new Error('Enter the guild’s OpenDKP name, such as castle.');
    return value;
  }
  function mergeCharacters(roster, standings) {
    const merged = new Map();
    for (const row of [...rows(roster), ...rows(standings)]) {
      const charId = id(first(row, 'CharacterId', 'CharacterID', 'Id')), name = text(first(row, 'CharacterName', 'Name'));
      if (!/^\d+$/.test(charId) || !name || name.length > 200) continue;
      const existing = merged.get(charId) || {};
      merged.set(charId, {id: charId, name, class: text(first(row, 'CharacterClass', 'Class')) || existing.class || '',
        level: finite(first(row, 'CharacterLevel', 'Level')) ?? existing.level ?? null, rank: text(first(row, 'CharacterRank', 'Rank')) || existing.rank || ''});
    }
    return [...merged.values()].sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
  }
  function currentBalances(standings, character) {
    const charId = id(character?.id), name = lower(character?.name), all = rows(standings), poolFor = poolResolver(all), grouped = new Map();
    const personal = all.filter(row => identity(row, charId, name) === true), unidentified = [];
    for (const row of personal) {
      const [key, label] = poolFor(row, ['', personal.length === 1 ? 'Guild balance' : 'Unspecified pool']);
      // More than one unidentified row may conceal distinct pools. Preserve
      // each reported balance instead of collapsing or adding those values.
      if (!key) { unidentified.push({pool_key: '', pool: label, amount: finite(row.CurrentDKP)}); continue; }
      const amount = finite(row.CurrentDKP), existing = grouped.get(key);
      if (existing) { if (existing.amount !== amount) existing.amount = null; }
      else grouped.set(key, {pool_key: key, pool: label, amount});
    }
    return [...grouped.values(), ...unidentified];
  }
  function createClient({fetch: fetcher = globalThis.fetch?.bind(globalThis), timeoutMs = 15000, maxBytes = 16 * 1024 * 1024, maxRows = 50000, maxPages = 40, now = () => new Date()} = {}) {
    if (typeof fetcher !== 'function') throw new Error('Online requests are unavailable.');
    const timeLimit = Math.max(1, Math.min(30000, timeoutMs)), byteLimit = Math.min(16 * 1024 * 1024, Math.max(128, maxBytes));
    const rowLimit = Math.min(50000, Math.max(1, maxRows)), pageLimit = Math.min(40, Math.max(1, maxPages));
    const fetchedAt = () => now().toISOString();
    const guildSlug = guild => parseGuild(typeof guild === 'string' ? guild : guild?.slug);
    const numericId = value => { const clean = id(value); if (!/^[1-9]\d{0,15}$/.test(clean)) throw new Error('Choose a valid character or raid.'); return clean; };
    async function request(path, signal) {
      if (!/^\/clients\/[a-z0-9-]+(?:\/[a-z0-9/?=&]+)?$/i.test(path)) throw new Error('Invalid OpenDKP request.');
      if (signal?.aborted) throw new DOMException('Request cancelled.', 'AbortError');
      const controller = new AbortController(), abort = () => controller.abort(), timeout = setTimeout(abort, timeLimit);
      signal?.addEventListener('abort', abort, {once: true});
      try {
        const response = await fetcher(API_ROOT + path, {method: 'GET', credentials: 'omit', mode: 'cors', redirect: 'error', referrerPolicy: 'no-referrer', cache: 'no-store', headers: {Accept: 'application/json'}, signal: controller.signal});
        if (!response.ok) {
          const error = new Error(response.status === 401 || response.status === 403 ? 'This guild restricts public OpenDKP data.' : `OpenDKP returned ${response.status}. Try again shortly.`);
          if (response.status === 401 || response.status === 403) error.code = 'public-restricted';
          throw error;
        }
        const length = Number(response.headers?.get('content-length'));
        if (length > byteLimit) throw new Error('OpenDKP returned too much data. Choose a shorter period.');
        let body = '';
        if (response.body?.getReader) {
          const reader = response.body.getReader(), decoder = new TextDecoder(); let size = 0;
          try { while (true) { const part = await reader.read(); if (part.done) break; size += part.value.byteLength; if (size > byteLimit) { await reader.cancel(); throw new Error('OpenDKP returned too much data. Choose a shorter period.'); } body += decoder.decode(part.value, {stream: true}); } body += decoder.decode(); }
          finally { reader.releaseLock(); }
        } else { body = await response.text(); if (new TextEncoder().encode(body).byteLength > byteLimit) throw new Error('OpenDKP returned too much data. Choose a shorter period.'); }
        if (controller.signal.aborted) throw new DOMException('Request cancelled.', 'AbortError');
        let payload; try { payload = JSON.parse(body); } catch (_) { throw new Error('OpenDKP returned an unreadable response. Try again.'); }
        if (!object(payload) && !Array.isArray(payload)) throw new Error('OpenDKP returned an unexpected response.');
        // Bounds also prevent deeply nested hostile data from reaching a cache.
        const pending = [[payload, 0]]; let count = 0;
        while (pending.length) {
          const [value, depth] = pending.pop();
          if (++count > 600000 || depth > 30) throw new Error('OpenDKP returned an unsupported data structure.');
          if (object(value) || Array.isArray(value)) for (const item of Object.values(value)) if (typeof item === 'object' && item !== null) pending.push([item, depth + 1]);
        }
        return payload;
      } catch (error) {
        if (controller.signal.aborted && !signal?.aborted) throw new Error('OpenDKP took too long to respond. Try again.');
        if (signal?.aborted) throw new DOMException('Request cancelled.', 'AbortError');
        throw error;
      } finally { clearTimeout(timeout); signal?.removeEventListener('abort', abort); }
    }
    function pageInfo(payload) {
      if (Array.isArray(payload)) return {rows: payload, total: null, pages: null, more: false};
      const key = ['Models', 'Data', 'data', 'Rows', 'rows', 'Items'].find(key => Array.isArray(payload[key]));
      if (!key) throw new Error('OpenDKP did not return a record list.');
      const metadata = object(payload.Pagination) ? {...payload, ...payload.Pagination} : payload;
      return {rows: payload[key], total: finite(first(metadata, 'TotalCount', 'TotalRecords', 'TotalItems', 'totalCount', 'total')),
        pages: finite(first(metadata, 'TotalPages', 'PageCount', 'totalPages')), more: first(metadata, 'HasNextPage', 'HasMore', 'hasMore') === true};
    }
    async function list(path, signal) {
      let result = [], partial = false, asOf = '', size = 0, code = ''; const warnings = [], seenPages = new Set();
      for (let page = 1; page <= pageLimit; page++) {
        // Use the same requested page size from page one; changing it mid-list
        // skips records when a guild's default first page is smaller.
        const pagePath = path + (path.includes('?') ? '&' : '?') + `page=${page}&ItemsPerPage=500`;
        let payload, info;
        try { payload = await request(pagePath, signal); info = pageInfo(payload); }
        catch (error) {
          if (page === 1 || signal?.aborted) throw error;
          partial = true; code = error.code || ''; warnings.push(error.message || 'A later OpenDKP page could not be loaded.'); break;
        }
        if (info.rows.some(row => !object(row))) throw new Error('OpenDKP returned invalid records.');
        asOf = asOf || text(payload.AsOfDate);
        const signature = JSON.stringify(info.rows);
        if (seenPages.has(signature) && info.rows.length) { partial = true; warnings.push('OpenDKP repeated a page. Showing the records received so far.'); break; }
        seenPages.add(signature);
        size += new TextEncoder().encode(signature).byteLength;
        if (size > byteLimit * 2) { partial = true; warnings.push('The downloaded history reached its safety limit. Choose a shorter period.'); break; }
        const room = rowLimit - result.length; result.push(...info.rows.slice(0, room));
        const more = info.more || (info.total !== null && result.length < info.total) || (info.pages !== null && page < info.pages);
        if (info.rows.length > room || (more && result.length >= rowLimit)) { partial = true; warnings.push('The record safety limit was reached. Choose a shorter period.'); break; }
        if (!more) break;
        if (!info.rows.length || page === pageLimit) { partial = true; warnings.push('OpenDKP has more records than this response. Showing a partial history.'); break; }
      }
      return {rows: result, complete: !partial, warnings, asOf, code};
    }
    async function collect(paths, signal) {
      const names = Object.keys(paths), results = await Promise.allSettled(names.map(key => list(paths[key], signal)));
      if (signal?.aborted) throw new DOMException('Request cancelled.', 'AbortError');
      const datasets = {}, sources = {}, warnings = []; let successes = 0;
      results.forEach((result, index) => {
        const name = names[index];
        if (result.status === 'fulfilled') { successes++; datasets[name] = result.value.rows; sources[name] = {complete: result.value.complete, count: result.value.rows.length, error: '', asOf: result.value.asOf, code: result.value.code}; warnings.push(...result.value.warnings.map(warning => `${name}: ${warning}`)); }
        else { datasets[name] = []; const error = result.reason?.message || 'Data could not be loaded.'; sources[name] = {complete: false, count: 0, error, code: result.reason?.code || ''}; warnings.push(`${name}: ${error}`); }
      });
      if (!successes) { const error = new Error(warnings.join(' ')); if (Object.values(sources).some(source => source.code === 'public-restricted')) error.code = 'public-restricted'; throw error; }
      return {...datasets, sources, warnings, partial: Object.values(sources).some(source => !source.complete), fetchedAt: fetchedAt()};
    }
    return Object.freeze({
      async resolveGuild(value, {signal} = {}) {
        const slug = parseGuild(value), payload = await request('/clients/' + slug, signal);
        if (!object(payload) || !text(payload.Name) || !text(payload.ClientId) || (payload.Subdomain && lower(payload.Subdomain) !== slug)) throw new Error('That OpenDKP guild could not be found.');
        return {slug, name: text(payload.Name), id: text(payload.ClientId)};
      },
      async directory(guild, {signal} = {}) {
        const slug = guildSlug(guild), base = '/clients/' + slug, result = await collect({roster: base + '/characters', standings: base + '/dkp'}, signal);
        return {...result, guild, characters: mergeCharacters(result.roster, result.standings), asOf: result.sources.standings.asOf || ''};
      },
      async history(guild, character, {days = 90, signal} = {}) {
        const slug = guildSlug(guild), cid = numericId(character?.id), base = `/clients/${slug}/characters/${cid}`;
        days = Math.max(1, Math.min(3650, Math.trunc(Number(days) || 90)));
        const result = await collect({dkp: base + '/dkp', raids: base + '/raids?lookback=' + days, adjustments: base + '/adjustments', items: base + '/items'}, signal);
        const periodEnd = result.fetchedAt, periodStart = new Date(new Date(periodEnd).valueOf() - days * 86400000).toISOString();
        const entries = buildHistory({...result, characterId: cid, characterName: character.name}).filter(entry => !Number.isFinite(Date.parse(entry.timestamp)) || Date.parse(entry.timestamp) >= Date.parse(periodStart));
        return {...result, guild, character, days, periodStart, periodEnd, raidDetails: {}, entries, summary: summarizeHistory(entries)};
      },
      async raidDetail(guild, value, {signal} = {}) {
        const rid = numericId(value), payload = await request(`/clients/${guildSlug(guild)}/raids/${rid}`, signal);
        if (!object(payload) || raidId(payload) !== rid || !Array.isArray(payload.Ticks)) throw new Error('OpenDKP could not verify this raid’s original ticks.');
        return payload;
      },
    });
  }
  return Object.freeze({API_ROOT, parseGuild, mergeCharacters, currentBalances, buildHistory, summarizeHistory, createClient});
});
