"""Independent phone Guild DKP cache/state and shared-LAN integration."""

import json
from pathlib import Path
import shutil
import subprocess
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_js(source):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the phone state contract')
    result = subprocess.run([node, '-'], input=source, text=True,
                            capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


SESSION_FIXTURE = r'''
const assert=require('assert/strict');
const model=require('./companion-web/dkp.js');
const {createSession,historyKey,directoryKey}=require('./companion-web/guild-dkp.js');
const records=new Map(),writes=[];
let offline=false,partial=false,failSave=false,stamp=0,revision=0;
const storage={
 get:async key=>structuredClone(records.get(key)||null),
 put:async(key,payload)=>{if(failSave)throw Error('quota'); const record={key,payload:structuredClone(payload),savedAt:'2026-10-17T12:00:00Z'};records.set(key,record);writes.push(key);return record},
 guildRevision:async()=>revision,
 putGuildRecord:async(key,payload,expected)=>expected===revision?storage.put(key,payload):null,
 removePrefix:async prefix=>{revision++;for(const key of records.keys())if(key.startsWith(prefix))records.delete(key)}
};
const guild=slug=>({slug,name:slug+' guild',id:slug});
const character={id:'1',name:'Mindflux'};
const client={
 resolveGuild:async value=>{if(offline)throw Error('offline');return guild(model.parseGuild(value))},
 directory:async group=>{if(offline)throw Error('offline');return {guild:group,characters:[character,{id:'2',name:'Other'}],standings:[{CharacterId:1,Name:'Mindflux',CurrentDKP:321}],fetchedAt:'2026-10-17T12:00:00Z',asOf:'2026-10-17T11:00:00Z',partial,warnings:partial?['Standings unavailable']:[]}},
 history:async(group,person,{days})=>{if(offline)throw Error('offline');return {guild:group,character:person,days,fetchedAt:'2026-10-17T12:00:00Z',periodStart:'2026-07-19T12:00:00Z',periodEnd:'2026-10-17T12:00:00Z',entries:[{kind:'adjustment',timestamp:'2026-10-15',amount:++stamp,source:'Award'}],partial,warnings:partial?['Loot unavailable']:[],raidDetails:{},raids:[],adjustments:[],items:[],dkp:[]}},
};
'''


def test_url_alias_reopens_offline_and_partial_failures_preserve_complete_copy():
    run_js(SESSION_FIXTURE + r'''
(async()=>{
 const first=createSession({client,storage,model});
 await first.loadGuild('https://castle.opendkp.com/');await first.selectCharacter('1',90);
 const key=historyKey(first.state.guild,character,90),saved=structuredClone(records.get(key));
 assert.equal(first.state.history.entries[0].amount,1);assert(first.state.historySavedAt);
 offline=true;
 const restored=createSession({client,storage,model});await restored.restore();
 assert.equal(restored.state.guild.slug,'castle');assert.equal(restored.state.character.id,'1');
 assert.deepEqual(restored.state.history,saved.payload);assert(restored.state.historyStale);
 await restored.loadGuild('castle.opendkp.com');assert.equal(restored.state.guild.slug,'castle');
 offline=false;partial=true;await restored.selectCharacter('1',90);
 assert.deepEqual(restored.state.history,saved.payload);assert.deepEqual(records.get(key),saved);
 assert.match(restored.state.message,/Some history sources/);
 partial=false;failSave=true;await restored.selectCharacter('1',90);
 assert.equal(restored.state.historySavedAt,'');assert.match(restored.state.message,/could not be saved/);
 assert.deepEqual(records.get(key),saved);
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_out_of_order_history_cannot_change_selection_or_write_wrong_cache_key():
    run_js(SESSION_FIXTURE + r'''
(async()=>{
 const pending=[];client.history=(group,person,{days})=>new Promise(resolve=>pending.push({group,person,days,resolve}));
 const session=createSession({client,storage,model});await session.loadGuild('castle');
 const old=session.selectCharacter('1',30);await new Promise(setImmediate);
 const latest=session.selectCharacter('2',90);await new Promise(setImmediate);
 const finish=request=>request.resolve({guild:request.group,character:request.person,days:request.days,entries:[],partial:false,fetchedAt:'2026-10-17'});
 finish(pending[1]);await latest;finish(pending[0]);await old;
 assert.equal(session.state.character.id,'2');assert.equal(session.state.days,90);
 assert.equal(session.state.history.character.id,'2');
 assert(!records.has(historyKey(guild('castle'),character,30)));
 assert(records.has(historyKey(guild('castle'),{id:'2'},90)));
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_restricted_public_sources_have_actionable_safe_feedback_and_keep_saved_data():
    run_js(SESSION_FIXTURE + r'''
(async()=>{
 const session=createSession({client,storage,model});await session.loadGuild('castle');await session.selectCharacter('1');
 const saved=structuredClone(session.state.history),restricted=Object.assign(Error('Untrusted response body'),{code:'public-restricted'});
 client.history=async()=>{throw restricted};await session.selectCharacter('1');
 assert.deepEqual(session.state.history,saved);assert(session.state.historyStale);
 assert.match(session.state.message,/restricts some public OpenDKP data/);assert.match(session.state.message,/does not sign in/);
 assert(!session.state.message.includes('Untrusted response body'));
 client.directory=async()=>({guild:guild('castle'),characters:[character],standings:[],partial:true,sources:{standings:{code:'public-restricted'}}});
 await session.loadGuild('castle');assert.match(session.state.message,/restricts some public OpenDKP data/);assert(session.state.directorySavedAt);
 client.resolveGuild=async()=>{throw restricted};await session.loadGuild('restricted');
 assert.match(session.state.message,/OpenDKP website/);assert(!session.state.message.includes('Untrusted response body'));
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_forget_waits_for_inflight_saves_and_preserves_import_and_catalogs():
    run_js(SESSION_FIXTURE + r'''
(async()=>{
 records.set('pc-copy',{payload:'private snapshot'});records.set('catalog:items',{payload:'catalog'});
 const session=createSession({client,storage,model});await session.loadGuild('castle');await session.selectCharacter('1');
 await session.forget();assert.equal(session.state.guild,null);
 assert.deepEqual([...records.keys()].sort(),['catalog:items','pc-copy']);
 assert.match(session.state.message,/Imported PC copies/);
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_raid_detail_response_is_discarded_after_character_change():
    run_js(SESSION_FIXTURE + r'''
(async()=>{
 let finish;client.raidDetail=()=>new Promise(resolve=>finish=resolve);
 const session=createSession({client,storage,model});await session.loadGuild('castle');await session.selectCharacter('1');
 const old=structuredClone(records.get(historyKey(guild('castle'),character,90)));
 const request=session.loadRaid('42');await new Promise(setImmediate);
 await session.selectCharacter('2');
 finish({RaidId:42,Ticks:[{TickId:1,Value:10,Characters:[{CharacterId:1,Name:'Mindflux'}]}]});
 assert.equal(await request,undefined);assert.equal(session.state.character.id,'2');
 assert.equal(session.state.history.character.id,'2');
 assert.deepEqual(records.get(historyKey(guild('castle'),character,90)),old);
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_raid_details_are_saved_only_after_success_and_preserve_unknown_pool():
    run_js(SESSION_FIXTURE + r'''
(async()=>{
 client.history=async(group,person,{days})=>({guild:group,character:person,days,
  fetchedAt:'2026-10-17T12:00:00Z',periodStart:'2026-07-19T12:00:00Z',periodEnd:'2026-10-17T12:00:00Z',
  entries:[],partial:false,raidDetails:{},raids:[{RaidId:42,Name:'Test raid',Timestamp:'2026-10-15T12:00:00Z'}],adjustments:[],items:[],dkp:[]});
 client.raidDetail=async()=>({RaidId:42,Name:'Test raid',Timestamp:'2026-10-15T12:00:00Z',Ticks:[{TickId:1,Value:10,Characters:[{CharacterId:1,Name:'Mindflux'}]}]});
 const session=createSession({client,storage,model});await session.loadGuild('castle');await session.selectCharacter('1');
 assert.equal(await session.loadRaid('42'),true);
 const key=historyKey(guild('castle'),character,90),saved=structuredClone(records.get(key));
 assert.equal(saved.payload.raidDetails['42'].Ticks[0].Value,10);
 client.raidDetail=async()=>{throw Error('offline')};assert.equal(await session.loadRaid('42'),false);
 assert.deepEqual(records.get(key),saved);assert.match(session.state.message,/unchanged/);
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_storage_clear_prefix_is_scoped_and_transactional():
    run_js(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
(async()=>{
 const rows=['pc-copy','catalog:items','guild-dkp:v1:directory:castle','guild-dkp:v1:history:castle:1:90'];
 const deleted=[],put=[];let tx;
 const db={transaction:()=>{tx={objectStore:()=>({
 get:()=>{const request={result:{payload:7}};setImmediate(()=>request.onsuccess());return request},
 put:record=>put.push(record),openCursor:()=>{
  const request={};let index=0;const next=()=>setImmediate(()=>{
    if(index===rows.length){request.result=null;request.onsuccess();tx.oncomplete();return}
    const key=rows[index++];request.result={key,delete:()=>deleted.push(key),continue:next};request.onsuccess();
  });next();return request;
 }}),abort:()=>tx.onabort()};return tx}};
 const indexedDB={open:()=>{const request={result:db};setImmediate(()=>request.onsuccess());return request}};
 const context={window:{},indexedDB,globalThis:{indexedDB},setTimeout,clearTimeout};vm.createContext(context);
 vm.runInContext(fs.readFileSync('companion-web/storage.js','utf8'),context);
 await assert.rejects(context.window.VantageStorage.removePrefix(''));
 await context.window.VantageStorage.removePrefix('guild-dkp:v1:');
 assert.deepEqual(deleted,rows.slice(2));
 assert.equal(put[0].key,'guild-dkp:revision');assert.equal(put[0].payload,8);
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_other_tab_inflight_request_cannot_recreate_cleared_records():
    run_js(SESSION_FIXTURE + r'''
(async()=>{
 const a=createSession({client,storage,model}),b=createSession({client,storage,model});
 await a.loadGuild('castle');await b.loadGuild('castle');
 let finish;client.history=(group,person,{days})=>new Promise(resolve=>finish=()=>resolve({guild:group,character:person,days,entries:[],partial:false}));
 const loading=b.selectCharacter('1');await new Promise(setImmediate);await a.forget();
 assert.equal(records.size,0);finish();await loading;assert.equal(records.size,0);
 assert.equal(b.state.historySavedAt,'');
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_clear_invalidates_automatic_character_refresh_after_directory_save():
    run_js(SESSION_FIXTURE + r'''
(async()=>{
 const a=createSession({client,storage,model}),b=createSession({client,storage,model});
 await a.loadGuild('castle');
 const original=client.directory;let finish,historyCalls=0;
 client.directory=group=>new Promise(resolve=>finish=async()=>resolve(await original(group)));
 client.history=async()=>{historyCalls++;throw Error('Must not start after clear')};
 const loading=b.loadGuild('castle','1');await new Promise(setImmediate);await a.forget();
 await finish();await loading;
 assert.equal(records.size,0);assert.equal(historyCalls,0);assert.equal(b.state.guild,null);
 assert.match(b.state.message,/cleared in another view/);
})().catch(error=>{console.error(error);process.exitCode=1});
''')


@pytest.mark.parametrize('mode', ['partial_no_cache', 'partial_cached', 'failed_cached'])
def test_clear_invalidates_automatic_character_refresh_when_directory_cannot_save(mode):
    run_js(SESSION_FIXTURE + 'const mode=' + json.dumps(mode) + ';' + r'''
(async()=>{
 const a=createSession({client,storage,model}),b=createSession({client,storage,model});
 await a.loadGuild('castle');
 const originalDirectory=client.directory,originalHistory=client.history;let finish,historyCalls=0;
 client.directory=group=>new Promise((resolve,reject)=>finish=async()=>{
   if(mode==='failed_cached')reject(Error('Unavailable'));
   else resolve({...await originalDirectory(group),partial:true});
 });
 client.history=async(...args)=>{historyCalls++;return originalHistory(...args)};
 const loading=b.loadGuild(mode==='partial_no_cache'?'other':'castle','1');
 await new Promise(setImmediate);assert(finish);await a.forget();assert.equal(records.size,0);
 await finish();await loading;
 assert.equal(records.size,0);assert.equal(historyCalls,0);assert.equal(b.state.guild,null);
 assert.match(b.state.message,/cleared in another view/);
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_clear_invalidates_automatic_restore_from_a_pending_selection_read():
    run_js(SESSION_FIXTURE + r'''
(async()=>{
 const a=createSession({client,storage,model});await a.loadGuild('castle');await a.selectCharacter('1');
 const originalGet=storage.get;let finish,resolveCalls=0;
 storage.get=async key=>{const saved=await originalGet(key);return key==='guild-dkp:v1:selection'?new Promise(resolve=>finish=()=>resolve(saved)):saved};
 const b=createSession({client,storage,model}),loading=b.restore();await new Promise(setImmediate);assert(finish);
 await a.forget();client.resolveGuild=async()=>{resolveCalls++;return guild('castle')};
 finish();await loading;
 assert.equal(records.size,0);assert.equal(resolveCalls,0);assert.equal(b.state.guild,null);
 assert.match(b.state.message,/cleared in another view/);
})().catch(error=>{console.error(error);process.exitCode=1});
''')


DOM_FIXTURE = r'''
const {mount}=require('./companion-web/guild-dkp.js');
class Element {
 constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.dataset={};this.attributes={};this.handlers={};this.value='';this.hidden=false;this.open=false;this.classList={add:()=>{}}}
 append(...items){for(const item of items){item.parentElement=this;this.children.push(item)}}
 replaceChildren(...items){if(this.contains(this.ownerDocument.activeElement))this.ownerDocument.activeElement=this.ownerDocument.body;for(const item of this.children)item.parentElement=null;this.children=[];this.append(...items)}
 set textContent(value){this._text=String(value);this.children=[]}get textContent(){return this._text||this.children.map(row=>row.textContent).join('')}
 setAttribute(key,value){this.attributes[key]=String(value)}getAttribute(key){return this.attributes[key]}removeAttribute(key){delete this.attributes[key]}
 addEventListener(type,handler){(this.handlers[type]??=[]).push(handler)}
 fire(type){for(const handler of this.handlers[type]||[])handler({preventDefault(){}})}
 focus(){this.ownerDocument.activeElement=this}
 contains(target){return target===this||this.children.some(row=>row.contains(target))}
 closest(selector){let row=this;while(row){if(selector==='[hidden]'?row.hidden:row.tagName.toLowerCase()===selector)return row;row=row.parentElement}return null}
 querySelectorAll(selector){const tags=selector.split(',').map(value=>value.toUpperCase()),result=[];const visit=row=>{for(const child of row.children){if(tags.includes(child.tagName))result.push(child);visit(child)}};visit(this);return result}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null}
 get isConnected(){return this.ownerDocument.body.contains(this)}
 setCustomValidity(){}reportValidity(){}
}
'''


def test_panel_announces_roster_before_selection_and_preserves_focus_on_updates():
    run_js(SESSION_FIXTURE + DOM_FIXTURE + r'''
(async()=>{
 const doc={createElement:tag=>new Element(tag,doc),createTextNode:value=>{const node=new Element('#text',doc);node.textContent=value;return node}};
 doc.body=new Element('body',doc);doc.activeElement=doc.body;
 const host=new Element('div',doc);host.id='guild-dkp';doc.body.append(host);
 const outside=new Element('button',doc);doc.body.append(outside);
 const entries=[1,2].map(id=>({kind:'raid',raid_id:String(id),source:'Raid '+id,description:'Raid',timestamp:'2026-10-15T12:00:00Z',amount:id,pool_key:'1',pool:'Main',ticks:[]}));
 entries.push({...entries[0],pool_key:'2',pool:'Second'});
 entries.push(...Array.from({length:60},(_,index)=>({...entries[0],raid_id:String(index+100),source:'Extra raid '+index})));
 client.history=async(group,person,{days})=>({guild:group,character:person,days,entries,partial:false,fetchedAt:'2026-10-17',raidDetails:{},raids:[],adjustments:[],items:[],dkp:[]});
 let finish;client.raidDetail=(_guild,id)=>new Promise(resolve=>finish=()=>resolve({RaidId:id,Ticks:[]}));
 const api={...model,createClient:()=>client,buildHistory:()=>entries};
 const mounted=mount(host,{api,storage});await mounted.session.loadGuild('castle');
 const field=name=>host.querySelectorAll('input,select').find(row=>row.id==='guild-dkp-dkp-'+name);
 field('roster-search').value='Mind';field('roster-search').fire('input');
 await new Promise(resolve=>setTimeout(resolve,580));
 const announcement=host.querySelectorAll('p').find(row=>row.getAttribute('role')==='status'&&row.textContent==='1 of 2 characters match.');
 assert(announcement&&!announcement.closest('[hidden]'),'Roster announcement must be exposed before character selection');
 await mounted.session.selectCharacter('1');
 const row=(id,pool='1')=>host.querySelectorAll('details').find(item=>item.dataset.raidId===id&&item.dataset.poolKey===pool);
 const settle=async()=>{for(let count=0;count<15&&mounted.session.state.busy;count++)await new Promise(setImmediate);assert.equal(mounted.session.state.busy,false)};
 row('1').open=true;row('1').querySelector('button').focus();row('1').querySelector('button').fire('click');
 field('history-search').focus();finish();await settle();
 assert.equal(doc.activeElement,field('history-search'),'Response must not steal focus from filters');assert(row('1').open);
 row('1').querySelector('button').focus();row('1').querySelector('button').fire('click');
 row('2').open=true;row('2').querySelector('summary').focus();finish();await settle();
 assert.equal(doc.activeElement,row('2').querySelector('summary'),'Another disclosure retains focus');assert(row('2').open);
 row('1').querySelector('button').focus();row('1').querySelector('button').fire('click');
 row('1','2').open=true;row('1','2').querySelector('summary').focus();finish();await settle();
 assert.equal(doc.activeElement,row('1','2').querySelector('summary'),'Pool-specific raid disclosure retains focus');assert(row('1','2').open);
 host.querySelectorAll('button').find(control=>control.textContent==='Show more history').fire('click');
 assert(row('159'),'The final page of history is visible');row('159').open=true;
 row('159').querySelector('button').focus();row('159').querySelector('button').fire('click');finish();await settle();
 assert(row('159').open,'Enriching a raid must not collapse pagination');
 assert.equal(doc.activeElement,row('159').querySelector('button'),'A later page retains its initiating focus');
 row('1').querySelector('button').focus();row('1').querySelector('button').fire('click');
 host.hidden=true;outside.focus();finish();await settle();assert.equal(doc.activeElement,outside);
 host.hidden=false;globalThis.confirm=()=>true;
 const forget=host.querySelectorAll('button').find(control=>control.textContent==='Forget saved OpenDKP data');
 const originalRemove=storage.removePrefix;let finishClear;
 storage.removePrefix=prefix=>new Promise(resolve=>finishClear=async()=>{await originalRemove(prefix);resolve()});
 forget.focus();forget.fire('click');await new Promise(setImmediate);
 field('guild').focus();finishClear();await settle();assert.equal(doc.activeElement,field('guild'),'Clear completion must retain intervening input focus');
 forget.focus();forget.fire('click');await new Promise(setImmediate);
 host.hidden=true;outside.focus();finishClear();await settle();assert.equal(doc.activeElement,outside,'Clear completion must not leave another page');
 host.hidden=false;forget.focus();forget.fire('click');await new Promise(setImmediate);finishClear();await settle();
 assert.equal(doc.activeElement,field('guild'),'Uninterrupted clear returns focus to guild entry');
 mounted.destroy();
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_empty_history_finishes_loading_online_offline_and_when_restricted():
    run_js(SESSION_FIXTURE + DOM_FIXTURE + r'''
(async()=>{
 const doc={createElement:tag=>new Element(tag,doc),createTextNode:value=>{const node=new Element('#text',doc);node.textContent=value;return node}};
 doc.body=new Element('body',doc);doc.activeElement=doc.body;
 const host=new Element('div',doc);host.id='guild-dkp';doc.body.append(host);
 const originalDirectory=client.directory;
 client.directory=async group=>{const value=await originalDirectory(group);value.standings[0].CurrentDKP=0;return value};
 client.history=async(group,person,{days})=>{if(offline)throw Error('offline');return {guild:group,character:person,days,entries:[],partial:false,fetchedAt:'2026-10-17',raidDetails:{},raids:[],adjustments:[],items:[],dkp:[]}};
 const api={...model,createClient:()=>client};
 const empty=()=>host.querySelectorAll('p').find(row=>row.className==='vdkp-empty');
 const first=mount(host,{api,storage});await first.session.loadGuild('castle');await first.session.selectCharacter('1');
 assert.equal(empty().textContent,'No records match this period and these filters.');
 assert.equal(first.session.state.history.partial,false);assert.deepEqual(first.session.state.history.entries,[]);
 assert(host.querySelectorAll('dd').some(row=>row.textContent==='0 DKP'),'Explicit zero current balance is legitimate');
 const saved=structuredClone(records.get(historyKey(guild('castle'),character,90)));assert(saved);
 first.destroy();offline=true;
 const restored=mount(host,{api,storage});
 for(let count=0;count<30&&(!restored.session.state.character||restored.session.state.busy);count++)await new Promise(setImmediate);
 assert.equal(restored.session.state.busy,false);assert(restored.session.state.historyStale);
 assert.equal(empty().textContent,'No records match this period and these filters.','Saved empty history finishes its offline check');
 assert.deepEqual(records.get(historyKey(guild('castle'),character,90)),saved);
 offline=false;client.history=async()=>{throw Object.assign(Error('Restricted'),{code:'public-restricted'})};
 await restored.session.selectCharacter('1');
 assert.match(restored.session.state.message,/restricts some public OpenDKP data/);
 assert.equal(empty().textContent,'No records match this period and these filters.','Restricted refresh retains the complete empty copy without a spinner');
 await restored.session.selectCharacter('1',30);
 assert.equal(restored.session.state.history,null);assert.equal(restored.session.state.busy,false);
 assert.equal(empty().textContent,'No history available yet. Choose Refresh to retry.','Restricted history without a copy does not load forever');
 assert(!records.has(historyKey(guild('castle'),character,30)));
 restored.destroy();
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_indexeddb_guard_checks_revision_inside_record_write_transaction():
    run_js(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
(async()=>{
 const written=[];let revision=2;
 const db={transaction:()=>{const tx={objectStore:()=>({
  get:()=>{const request={};setImmediate(()=>{request.result={payload:revision};request.onsuccess();setImmediate(()=>tx.oncomplete())});return request},
  put:record=>written.push(record)
 }),abort:()=>tx.onabort()};return tx}};
 const indexedDB={open:()=>{const request={result:db};setImmediate(()=>request.onsuccess());return request}};
 const context={window:{},indexedDB,globalThis:{indexedDB},setTimeout,clearTimeout};vm.createContext(context);
 vm.runInContext(fs.readFileSync('companion-web/storage.js','utf8'),context);
 const storage=context.window.VantageStorage;
 assert.equal(await storage.putGuildRecord('guild-dkp:v1:history:castle:1:90',{name:'old'},1),null);
 assert.equal(written.length,0);
 const saved=await storage.putGuildRecord('guild-dkp:v1:history:castle:1:90',{name:'fresh'},2);
 assert.equal(saved.payload.name,'fresh');assert.equal(written.length,1);
 await assert.rejects(storage.putGuildRecord('pc-copy',{},2));
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_shared_assets_ship_on_lan_without_opening_private_api_or_arbitrary_files():
    from vantage.helpers.mobile_share import _MOBILE_PAGE, _ShareHTTPServer
    server = _ShareHTTPServer(('127.0.0.1', 0), 'private-token', lambda: {})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        for name in ('storage.js', 'dkp.js', 'guild-dkp.js', 'guild-dkp.css'):
            with urlopen(base + '/companion/' + name, timeout=3) as response:
                assert response.read() == (ROOT / 'companion-web' / name).read_bytes()
                assert "connect-src 'self' https://api.opendkp.com;" in response.headers['Content-Security-Policy']
        for path, code in (('/companion/../pyproject.toml', 404), ('/companion/app.js', 404), ('/api/guild', 403)):
            with pytest.raises(HTTPError) as error:
                urlopen(base + path, timeout=3)
            assert error.value.code == code
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
    assert 'id="guild-dkp"' in _MOBILE_PAGE
    assert 'PC-loaded guild snapshot and controls' in _MOBILE_PAGE
    assert 'Your selection here does not change' in (ROOT / 'companion-web/guild-dkp.js').read_text(encoding='utf-8')


def test_both_shells_and_publish_workflow_include_the_shared_panel():
    from vantage.helpers.mobile_share import _MOBILE_SERVICE_WORKER
    html = (ROOT / 'companion-web/index.html').read_text(encoding='utf-8')
    worker = (ROOT / 'companion-web/sw.js').read_text(encoding='utf-8')
    publish = (ROOT / '.github/workflows/refresh-companion.yml').read_text(encoding='utf-8')
    spec = (ROOT / 'vantage.spec').read_text(encoding='utf-8')
    for name in ('dkp.js', 'guild-dkp.js', 'guild-dkp.css'):
        assert name in html and name in worker and name in publish and name in spec
        assert '/companion/' + name in _MOBILE_SERVICE_WORKER
    assert '/companion/storage.js' in _MOBILE_SERVICE_WORKER
    assert "url.pathname.startsWith('/api/')" in _MOBILE_SERVICE_WORKER
    assert 'vantage-mobile-shell-v2' in _MOBILE_SERVICE_WORKER
    assert "connect-src 'self' https://api.opendkp.com;" in html
    assert 'innerHTML' not in (ROOT / 'companion-web/guild-dkp.js').read_text(encoding='utf-8')
