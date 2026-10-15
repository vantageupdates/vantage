/* Durable data is deliberately separate from the replaceable app shell. */
(() => {
  'use strict';
  let opening;
  function database() {
    if (opening) return opening;
    opening = new Promise((resolve, reject) => {
      if (!globalThis.indexedDB) { reject(new Error('Device storage is unavailable.')); return; }
      const request = indexedDB.open('vantage-companion-data', 1);
      const timeout = setTimeout(() => reject(new Error('Device storage did not open. Close other Vantage tabs and retry.')), 8000);
      request.onupgradeneeded = () => request.result.createObjectStore('records', {keyPath: 'key'});
      request.onerror = () => { clearTimeout(timeout); reject(request.error); };
      request.onblocked = () => { clearTimeout(timeout); reject(new Error('Close other Vantage tabs, then retry saving.')); };
      request.onsuccess = () => {
        clearTimeout(timeout);
        const db = request.result;
        db.onversionchange = () => { db.close(); opening = null; };
        resolve(db);
      };
    }).catch(error => { opening = null; throw error; });
    return opening;
  }
  async function transaction(mode, action) {
    const db = await database();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('records', mode);
      let result;
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error || new Error('Device storage could not save this data.'));
      tx.onabort = () => reject(tx.error || new Error('The save was interrupted. The previous copy is unchanged.'));
      try { action(tx.objectStore('records'), value => { result = value; }); }
      catch (error) { tx.abort(); reject(error); }
    });
  }
  const get = key => transaction('readonly', (store, done) => {
    const request = store.get(key);
    request.onsuccess = () => done(request.result || null);
  });
  const put = (key, payload, savedAt = new Date().toISOString()) => transaction('readwrite', (store, done) => {
    const record = {key, payload, savedAt}; store.put(record); done(record);
  });
  const remove = key => transaction('readwrite', store => store.delete(key));
  // v2 kept catalogs with its app shell. Migrate them before claiming readiness.
  async function legacy(path) {
    if (!globalThis.caches) return null;
    for (const key of await caches.keys()) {
      if (!/^vantage-companion-v\d+$/.test(key)) continue;
      const response = await (await caches.open(key)).match(new URL(path, location.href).href);
      if (response?.ok) { try { return await response.json(); } catch (_) {} }
    }
    return null;
  }
  window.VantageStorage = Object.freeze({get, put, remove, legacy});
})();
