import importlib.util
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess

import pytest

from vantage.helpers.mobile_share import COMPANION_URL


ROOT = Path(__file__).resolve().parents[1]
COMPANION = ROOT / "companion-web"


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "vantage_companion_builder", COMPANION / "build_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_companion_is_installable_at_the_permanent_github_pages_address():
    manifest = json.loads(
        (COMPANION / "manifest.webmanifest").read_text(encoding="utf-8"))
    html = (COMPANION / "index.html").read_text(encoding="utf-8")
    worker = (COMPANION / "sw.js").read_text(encoding="utf-8")

    assert COMPANION_URL == "https://vantageupdates.github.io/vantage/companion/"
    assert manifest["start_url"] == "/vantage/companion/"
    assert manifest["display"] == "standalone"
    assert len(manifest["icons"]) >= 2
    assert "icon-256.png" in html
    assert "vantage-companion-shell-" in worker
    assert 'id="install"' in html
    assert "Add to Home Screen" in html
    assert "Needs the PC QR session" in html
    assert "data/items.json" not in worker
    assert "key.startsWith(SHELL_PREFIX)" in worker
    assert "user-scalable=no" not in html
    assert 'src="storage.js"' in html and 'src="offline.js"' in html
    assert 'id="guild-tab"' in html and 'id="zones-tab"' in html
    assert 'id="quests-tab"' in html and 'id="import-review"' in html
    assert "Safari and the Home Screen app can keep separate data" in html
    assert "title.id='detail-title'" in (
        COMPANION / "app.js").read_text(encoding="utf-8")
    assert "(new tab)" in (
        COMPANION / "app.js").read_text(encoding="utf-8")


def test_static_item_builder_preserves_price_stats_and_correct_binding(tmp_path):
    builder = load_builder()
    fields = (
        "id", "peqId", "name", "classes", "races", "slots", "nodrop",
        *builder.STAT_FIELDS,
        *(field for _label, field in builder.EFFECT_FIELDS),
    )
    columns = ", ".join(
        f"`{field}` {'TEXT' if field in {'name', *[value for _label, value in builder.EFFECT_FIELDS]} else 'INTEGER'}"
        for field in fields)
    database_path = tmp_path / "items.sqlite"
    with sqlite3.connect(database_path) as database:
        database.execute(f"CREATE TABLE items ({columns})")
        values = {field: 0 for field in fields}
        values.update({
            "id": 770, "peqId": 14701,
            "name": "Black Sapphire Electrum Earring",
            "classes": 16383, "races": 8191, "slots": 18,
            "nodrop": 1, "ac": 2, "hp": 35, "mana": 25,
            "clickName": "Test Effect",
        })
        database.execute(
            f"INSERT INTO items ({', '.join(f'`{field}`' for field in fields)}) "
            f"VALUES ({', '.join('?' for _field in fields)})",
            [values[field] for field in fields])
    eras = tmp_path / "eras.json"
    eras.write_text(json.dumps({
        "items": {"black sapphire electrum earring": "classic"}}))
    rows = builder.load_items(database_path, [{
        "n": "Black Sapphire Electrum Earring", "a30": 599,
        "t30": 975, "l": "recent",
    }], eras)

    assert rows == [{
        "name": "Black Sapphire Electrum Earring",
        "price": 599, "posts": 975, "last": "recent",
        "classes": 16383, "races": 8191, "slots": 18,
        "nodrop": False, "era": "classic", "id": 770, "peqId": 14701,
        "stats": {"ac": 2, "hp": 35, "mana": 25},
        "effects": [{"type": "Click", "name": "Test Effect"}],
        "wiki": "https://p99.funcamp.net/Black_Sapphire_Electrum_Earring",
    }]


def run_javascript(source):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the offline JavaScript contract checks")
    result = subprocess.run(
        [node, "-"], input=source, text=True, capture_output=True,
        cwd=ROOT, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_offline_import_projects_display_data_and_rejects_bad_or_oversized_files():
    run_javascript(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const context={window:{},URL,TextEncoder};vm.createContext(context);
vm.runInContext(fs.readFileSync('companion-web/offline.js','utf8'),context);
const api=context.window.VantageOffline;
const fixture=JSON.parse(fs.readFileSync('tests/fixtures/companion-offline.json','utf8'));
fixture.token='secret';fixture.guild.password='secret';fixture.guild.standings[0].accessToken='secret';
fixture.guild.sheets[0].url='https://docs.google.com/spreadsheets/d/synthetic-fixture/edit?authkey=secret#gid=3';
fixture.zone.wiki_url='javascript:alert(1)';fixture.quest.steps[0].html='<script>bad</script>';
const cleaned=api.snapshot(fixture),encoded=JSON.stringify(cleaned);
assert(!encoded.includes('secret'));assert(!encoded.includes('<script>'));
assert.equal(cleaned.guild.standings[1].dkp,'-');assert.equal(cleaned.zone.wiki_url,'');
assert.equal(cleaned.guild.sheets[0].url,'https://docs.google.com/spreadsheets/d/synthetic-fixture/edit');
assert.equal(api.safeURL('https://docs.google.com/spreadsheets/d/e/published/pubhtml','sheet'),'');
assert.equal(api.safeURL('https://user:pass@wiki.project1999.com/Clarity'),'');
assert.equal(api.safeURL('https://wiki.project1999.com/Clarity'), 'https://p99.funcamp.net/Clarity');
assert.equal(api.safeURL('https://p99.funcamp.net/Clarity'), 'https://p99.funcamp.net/Clarity');
assert.equal(api.safeURL('https://p99.funcamp.net.evil.test/Clarity'), '');
assert.equal(api.safeURL('https://wiki.project1999.com/index.php?title=Bravery'), 'https://p99.funcamp.net/Bravery');
assert.equal(api.safeURL('https://p99.funcamp.net/index.php_title=Bravery'), 'https://p99.funcamp.net/Bravery');
assert.equal(api.safeURL('https://p99.funcamp.net/index.php'), '');
assert.equal(api.safeURL('https://p99.funcamp.net/api.php?action=parse'), '');
assert.throws(()=>api.snapshot({...fixture,schema:2}));
assert.throws(()=>api.snapshot({...fixture,exported_at:'yesterday'}));
assert.throws(()=>api.snapshot({...fixture,guild:{...fixture.guild,standings:{}}}));
assert.throws(()=>api.snapshot({...fixture,guild:{...fixture.guild,standings:Array(10001).fill(fixture.guild.standings[0])}}));
assert.throws(()=>api.snapshot({...fixture,quest:{...fixture.quest,checked:[-1]}}));
assert.throws(()=>api.snapshot({...fixture,extra:'x'.repeat(api.MAX_BYTES)}));
assert.throws(()=>api.snapshot({...fixture,guild:null,zone:null,quest:null}));
""")


def test_handoff_requires_exact_origin_window_nonce_and_expires_without_approval():
    run_javascript(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const fixture=JSON.parse(fs.readFileSync('tests/fixtures/companion-offline.json','utf8'));
let time=1000,listener,received=0,approval,expiry,posts=[];
const nonce='a'.repeat(64),origin='http://192.168.1.10:8765';
const opener={postMessage:(data,target)=>posts.push({data,target})};
const win={opener,addEventListener:(type,fn)=>listener=fn,removeEventListener:()=>{listener=null}};
const context={window:win,URL,URLSearchParams,TextEncoder,Date:{now:()=>time,parse:Date.parse},
 location:{hash:'#import?nonce='+nonce+'&origin='+encodeURIComponent(origin)},history:{replaceState:()=>{}},
 setTimeout:fn=>{expiry=fn;return 1},clearTimeout:()=>{}};
vm.createContext(context);vm.runInContext(fs.readFileSync('companion-web/offline.js','utf8'),context);
win.VantageOffline.handoff((data,confirm)=>{received++;approval=confirm},()=>{});
assert.equal(posts[0].target,origin);assert.equal(posts[0].data.type,'vantage-offline-ready');
const data={type:'vantage-offline-snapshot',schema:1,nonce,snapshot:fixture};
listener({data,source:{},origin});listener({data,source:opener,origin:'https://evil.invalid'});
listener({data:{...data,nonce:'b'.repeat(64)},source:opener,origin});assert.equal(received,0);
listener({data,source:opener,origin});assert.equal(received,1);assert.equal(posts.length,1);
listener({data,source:opener,origin});assert.equal(received,1);
approval(true);assert.equal(posts[1].data.accepted,true);assert.equal(posts[1].target,origin);
win.VantageOffline.handoff(()=>{received++},()=>{});time+=60001;expiry();
assert.equal(listener,null);assert.equal(received,1);
assert(posts.every(post=>post.target!=='*'));
""")


def test_service_worker_preserves_data_caches_and_never_returns_html_for_assets():
    run_javascript(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
(async()=>{
const handlers={},deleted=[],root='https://example.test/vantage/companion/';
const cache={addAll:async()=>{},match:async()=>undefined};
const context={URL,Request,Response,self:{registration:{scope:root},location:{origin:'https://example.test'},
 addEventListener:(name,fn)=>handlers[name]=fn,clients:{claim:async()=>{}},skipWaiting:async()=>{}},
 caches:{open:async()=>cache,keys:async()=>['another-app','vantage-companion-v2','vantage-companion-shell-old','vantage-companion-shell-v1.44.135'],delete:async key=>deleted.push(key)},
 fetch:async()=>{throw Error('offline')}};
vm.createContext(context);vm.runInContext(fs.readFileSync('companion-web/sw.js','utf8'),context);
let pending;handlers.activate({waitUntil:promise=>pending=promise});await pending;
assert.deepEqual(deleted,['vantage-companion-shell-old','vantage-companion-shell-v1.44.135']);
let response;handlers.fetch({request:{method:'GET',url:root+'app.js',mode:'cors'},respondWith:promise=>response=promise});
assert.equal((await response).type,'error');
let intercepted=false;handlers.fetch({request:{method:'GET',url:root+'data/items.json',mode:'cors'},respondWith:()=>intercepted=true});
assert.equal(intercepted,false);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_storage_write_resolves_only_after_transaction_commit_and_rejects_abort():
    run_javascript(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
(async()=>{
let tx,putCount=0;
const db={transaction:()=>{tx={objectStore:()=>({put:()=>putCount++}),abort:()=>tx.onabort()};return tx}};
const indexedDB={open:()=>{const request={result:db};setImmediate(()=>request.onsuccess());return request}};
const context={window:{},indexedDB,globalThis:{indexedDB},setTimeout,clearTimeout};vm.createContext(context);
vm.runInContext(fs.readFileSync('companion-web/storage.js','utf8'),context);
let resolved=false;const save=context.window.VantageStorage.put('pc-copy',{guild:'one'}).then(()=>resolved=true);
await new Promise(setImmediate);assert.equal(putCount,1);assert.equal(resolved,false);
tx.oncomplete();await save;assert.equal(resolved,true);
const failure=context.window.VantageStorage.put('pc-copy',{guild:'two'});await new Promise(setImmediate);
tx.onabort();await assert.rejects(failure,/interrupted/);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_exported_backup_near_size_limit_can_be_reimported():
    run_javascript(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
(async()=>{
let exportedBlob,clicked=false;
const context={window:{},URL,TextEncoder,Blob};vm.createContext(context);
vm.runInContext(fs.readFileSync('companion-web/offline.js','utf8'),context);
const api=context.window.VantageOffline;
const fixture=JSON.parse(fs.readFileSync('tests/fixtures/companion-offline.json','utf8'));
const row=Object.fromEntries(['name','class','level','rank','dkp','attendance'].map(key=>[key,'x'.repeat(120)]));
fixture.guild.standings=Array.from({length:10000},()=>({...row}));fixture.guild.standings_total=10000;
const saved=api.snapshot(fixture);
const compactBytes=Buffer.byteLength(JSON.stringify(saved));
assert(compactBytes>api.MAX_BYTES*.9,'Regression fixture must be near the file limit');
assert(compactBytes<=api.MAX_BYTES);
assert(Buffer.byteLength(JSON.stringify(saved,null,2))>api.MAX_BYTES,'Indented backup would exceed the import limit');
context.state={snapshot:saved};
context.URL=class extends URL {};
context.URL.createObjectURL=blob=>{exportedBlob=blob;return 'blob:fixture'};context.URL.revokeObjectURL=()=>{};
context.node=()=>({click:()=>{clicked=true},remove:()=>{}});
context.document={body:{append:()=>{}}};context.setTimeout=()=>{};context.importStatus=()=>{};
const source=fs.readFileSync('companion-web/app.js','utf8');
const start=source.indexOf('function exportSnapshot(){'),end=source.indexOf('function installHelp()',start);
assert(start>=0&&end>start);
vm.runInContext(source.slice(start,end),context);vm.runInContext('exportSnapshot()',context);
assert(clicked);assert(exportedBlob.size<=api.MAX_BYTES);
const restored=api.snapshot(JSON.parse(await exportedBlob.text()));
assert.equal(restored.guild.standings.length,10000);
assert(JSON.stringify(restored)===JSON.stringify(saved),'Every saved field must survive backup and re-import');
assert.equal(context.state.snapshot,saved,'Export must not replace the saved copy');
})().catch(error=>{console.error(error);process.exitCode=1});
""")
