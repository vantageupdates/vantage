"""The phone uses the same conservative provenance rules as the desktop.

Run the desktop regression corpus to collect shared inputs/expected outputs,
then execute the shipped JavaScript module in Node, not a Python translation.
All network cases use synthetic fixtures and never need an OpenDKP account.
"""

import copy
import importlib.util
import inspect
import itertools
import json
import math
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "companion-web" / "dkp.js"


def node(source, data=None):
    executable = shutil.which("node")
    assert executable, "Node is required to verify the shipped mobile DKP adapter"
    script = "const d = require(process.argv[1]);\n" + source
    result = subprocess.run([executable, "-e", script, str(MODULE)],
                            input=json.dumps(data), text=True, encoding="utf-8", capture_output=True,
                            cwd=ROOT, timeout=40)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def portable(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(key): portable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [portable(item) for item in value]
    return value


def display_fields(value):
    if isinstance(value, dict):
        return {key: display_fields(item) for key, item in value.items()
                if key not in ("raw", "evidence")}
    if isinstance(value, list):
        return [display_fields(item) for item in value]
    return value


def test_mobile_normalizer_matches_every_desktop_history_regression(monkeypatch):
    spec = importlib.util.spec_from_file_location("dkp_shared_fixtures", ROOT / "tests/test_dkp_history.py")
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    original_build, original_summary = corpus.build_dkp_history, corpus.summarize_dkp_history
    fixtures = []

    def build(raids, adjustments, items, **options):
        result = original_build(raids, adjustments, items, **options)
        fixtures.append({"operation": "buildHistory", "input": {
            "raids": copy.deepcopy(raids), "adjustments": copy.deepcopy(adjustments),
            "items": copy.deepcopy(items), "characterId": options["character_id"],
            "characterName": options["character_name"], "dkp": options.get("dkp"),
            "raidDetails": options.get("raid_details")}, "expected": display_fields(result)})
        return result

    def summary(entries):
        result = original_summary(entries)
        fixtures.append({"operation": "summarizeHistory", "input": copy.deepcopy(entries), "expected": result})
        return result

    monkeypatch.setattr(corpus, "build_dkp_history", build)
    monkeypatch.setattr(corpus, "summarize_dkp_history", summary)
    tests = [(name, func) for name, func in vars(corpus).items()
             if name.startswith("test_") and inspect.isfunction(func)]
    assert len(tests) >= 29
    for name, func in tests:
        parameter_marks = [mark for mark in getattr(func, "pytestmark", []) if mark.name == "parametrize"]
        if parameter_marks:
            for values in itertools.product(*(mark.args[1] for mark in parameter_marks)):
                arguments = {}
                for mark, value in zip(parameter_marks, values):
                    arguments[mark.args[0]] = value
                func(**arguments)
        else:
            func()
    actual = node("""
const fs = require('node:fs');
const fixtures = JSON.parse(fs.readFileSync(0, 'utf8'));
const clean = value => Array.isArray(value) ? value.map(clean) : value && typeof value === 'object'
  ? Object.fromEntries(Object.entries(value).filter(([key]) => !['raw','evidence'].includes(key)).map(([key,item]) => [key, clean(item)])) : value;
console.log(JSON.stringify(fixtures.map(test => clean(d[test.operation](test.input)))));
""", portable(fixtures))
    assert len(fixtures) >= 70
    for index, (test, observed) in enumerate(zip(fixtures, actual)):
        assert observed == test["expected"], (index, test)


def test_guild_addresses_are_allowlisted_and_balance_is_not_history_net():
    result = node("""
const rejected = ['http://castle.opendkp.com','https://castle.opendkp.com.evil.test','https://evil.test','https://user:pass@castle.opendkp.com','https://castle.opendkp.com:8443','https://api.opendkp.com','castle/../../evil','//evil.test'];
const roster = [{CharacterId:1,Name:'Zero'},{CharacterId:2,Name:'No award'}];
const standings = [{CharacterId:1,CharacterName:'Zero',CurrentDKP:0,PoolId:1,PoolName:'Main'},
{CharacterId:1,CharacterName:'Zero',CurrentDKP:15,PoolId:2,PoolName:'Other'},
{CharacterId:3,CharacterName:'Extra',CurrentDKP:10}];
console.log(JSON.stringify({slug:d.parseGuild('https://CASTLE.opendkp.com/#/'), bare:d.parseGuild('castle'),
 rejected:rejected.map(url=>{try{d.parseGuild(url);return false}catch(_){return true}}),
 characters:d.mergeCharacters(roster,standings), balances:d.currentBalances(standings,{id:'1',name:'Zero'}),
 missing:d.currentBalances(standings,{id:'2',name:'No award'}),
 conflict:d.currentBalances([{CharacterId:1,CharacterName:'Zero',CurrentDKP:2},{CharacterId:1,CharacterName:'Zero',CurrentDKP:5}],{id:'1',name:'Zero'})}));
""")
    assert result["slug"] == result["bare"] == "castle"
    assert all(result["rejected"])
    assert {row["id"] for row in result["characters"]} == {"1", "2", "3"}
    assert [row["amount"] for row in result["balances"]] == [0, 15]
    assert result["missing"] == []
    assert [row["amount"] for row in result["conflict"]] == [2, 5]
    assert all(row["pool_key"] == "" for row in result["conflict"])


def test_direct_fetch_security_complete_roster_metadata_and_personal_history():
    result = node("""
(async()=>{
 const calls=[]; const response = value => new Response(JSON.stringify(value), {headers:{'Content-Type':'application/json'}});
 const characters=Array.from({length:1201},(_,i)=>({CharacterId:i+1,Name:'Toon'+(i+1)}));
 const fixtures={
 '/clients/example':{Name:'Example',ClientId:'guild1',Subdomain:'example'},
 '/clients/example/characters':characters,
 '/clients/example/dkp':{Models:[{CharacterId:1201,CharacterName:'Toon1201',CurrentDKP:0}],AsOfDate:'2026-10-17T09:00:00Z'},
 '/clients/example/characters/1201/dkp':[{CharacterId:1201,CharacterName:'Toon1201',SourceType:'Raid',SourceId:7,TickId:9,Value:3,Date:'2026-10-16T09:00:00Z'}],
 '/clients/example/characters/1201/raids?lookback=30':[{RaidId:7,RaidName:'Raid night',PoolName:'Main',Timestamp:'2026-10-16T08:00:00Z',Ticks:[{TickId:9,Attended:1}]}],
 '/clients/example/characters/1201/items':[], '/clients/example/characters/1201/adjustments':[]};
 const client=d.createClient({now:()=>new Date('2026-10-17T10:00:00Z'),fetch:async(url,options)=>{
 calls.push({url,options:{...options,signal:undefined}});const key=url.replace(d.API_ROOT,'').replace(/[?&]page=1&ItemsPerPage=500$/,'');if(!(key in fixtures))throw new Error('Unexpected URL');return response(fixtures[key]);}});
 const guild=await client.resolveGuild('example'); const directory=await client.directory(guild);
 const history=await client.history(guild,{id:'1201',name:'Toon1201'},{days:30});
 console.log(JSON.stringify({calls,guild,directory,history}));
})().catch(error=>{console.error(error);process.exit(1)});
""")
    assert len(result["directory"]["characters"]) == 1201
    assert result["directory"]["asOf"] == "2026-10-17T09:00:00Z"
    assert not result["directory"]["partial"]
    assert result["history"]["entries"][0]["amount"] == 3
    assert result["history"]["entries"][0]["ticks"][0]["amount"] == 3
    assert result["history"]["summary"]["net"] == 3
    assert not result["history"]["partial"]
    assert result["history"]["periodStart"] == "2026-09-17T10:00:00.000Z"
    for call in result["calls"]:
        assert call["url"].startswith("https://api.opendkp.com/clients/example")
        assert call["options"]["method"] == "GET"
        assert call["options"]["credentials"] == "omit"
        assert call["options"]["redirect"] == "error"
        assert call["options"]["referrerPolicy"] == "no-referrer"
        assert "Authorization" not in call["options"]["headers"]


def test_pagination_partial_failures_limits_repeats_and_cancellation():
    result = node("""
(async()=>{
 const response=value=>new Response(JSON.stringify(value)); const guild={slug:'example'};
 const first={Models:[{CharacterId:1,Name:'First'}],TotalCount:2,TotalPages:2};
 let calls=[];let mode='pages';
 const fetch=async(url)=>{calls.push(url);if(url.includes('/dkp?'))return response([]);
 if(mode==='failure')return new Response('Restricted',{status:403});
 if(mode==='large')return response(Array.from({length:4},(_,i)=>({CharacterId:i+1,Name:'Toon'+i})));
 if(mode==='bad')return response({Unexpected:true});
 if(url.includes('page=2')&&mode==='pages')return response({Models:[{CharacterId:2,Name:'Last'}],TotalCount:2,TotalPages:2});
 return response(first);};
 const client=d.createClient({fetch});
 const paged=await client.directory(guild);mode='repeat';const repeated=await client.directory(guild);
 mode='failure';const failed=await client.directory(guild);mode='large';const bounded=await d.createClient({fetch,maxRows:2}).directory(guild);
 mode='bad';const invalid=await client.directory(guild);
 const controller=new AbortController();controller.abort();let cancelled=false;try{await client.directory(guild,{signal:controller.signal})}catch(e){cancelled=e.name==='AbortError'};
 console.log(JSON.stringify({paged,repeated,failed,bounded,invalid,cancelled,calls}));
})().catch(error=>{console.error(error);process.exit(1)});
""")
    assert len(result["paged"]["characters"]) == 2
    assert not result["paged"]["partial"]
    assert result["repeated"]["partial"]
    assert result["failed"]["partial"]
    assert result["failed"]["sources"]["roster"]["error"]
    assert result["bounded"]["partial"]
    assert len(result["bounded"]["characters"]) == 2
    assert result["invalid"]["partial"]
    assert result["cancelled"]
    assert all("ItemsPerPage=500" in url for url in result["calls"])


def test_timeout_and_oversized_response_do_not_report_success():
    result = node("""
(async()=>{
 const errors=[];
 for(const client of [
 d.createClient({timeoutMs:5,fetch:async(_url,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}))}),
 d.createClient({maxBytes:128,fetch:async()=>new Response(JSON.stringify({Name:'x'.repeat(200),ClientId:'1'}))}),
 d.createClient({fetch:async()=>new Response('<html>Oops</html>')})]){
 try{await client.resolveGuild('example');errors.push('unexpected success')}catch(error){errors.push(error.message)}}
 console.log(JSON.stringify(errors));
})().catch(error=>{console.error(error);process.exit(1)});
""")
    assert "too long" in result[0]
    assert "too much data" in result[1]
    assert "unreadable" in result[2]


def test_restricted_public_sources_expose_a_safe_structured_reason():
    result = node("""
(async()=>{
 const codes=[];
 for(const status of [401,403]){
 const client=d.createClient({fetch:async()=>new Response('Private response text',{status})});
 for(const operation of [()=>client.resolveGuild('example'),()=>client.directory('example'),()=>client.history('example',{id:'1',name:'One'})]){
 try{await operation();codes.push('unexpected success')}catch(error){codes.push(error.code);if(error.message.includes('Private response text'))throw Error('Leaked server body')}}}
 const partialClient=d.createClient({fetch:async address=>{
 const url=new URL(address);if(url.pathname.endsWith('/dkp'))return new Response('[]');
 if(url.searchParams.get('page')==='2')return new Response('Private',{status:403});
 return new Response(JSON.stringify({Models:[{CharacterId:1,Name:'One'}],TotalPages:2,TotalCount:2}));}});
 const partial=await partialClient.directory('example');
 console.log(JSON.stringify({codes,partial}));
})().catch(error=>{console.error(error);process.exit(1)});
""")
    assert result["codes"] == ["public-restricted"] * 6
    assert result["partial"]["partial"]
    assert result["partial"]["sources"]["roster"]["code"] == "public-restricted"
    assert len(result["partial"]["characters"]) == 1


def test_consistent_pagination_does_not_skip_default_first_page_or_lose_partial_records():
    result = node("""
(async()=>{
 const full=Array.from({length:1100},(_,i)=>({CharacterId:i+1,Name:'Toon'+(i+1)}));
 let fail=false;
 const fetch=async address=>{const url=new URL(address);if(url.pathname.endsWith('/dkp'))return new Response('[]');
 const page=Number(url.searchParams.get('page')||1),size=Number(url.searchParams.get('ItemsPerPage')||10);
 if(fail&&page===2)throw new Error('Temporary disconnect');
 return new Response(JSON.stringify({Models:full.slice((page-1)*size,page*size),TotalCount:full.length,TotalPages:Math.ceil(full.length/size)}));};
 const client=d.createClient({fetch});const complete=await client.directory('example');fail=true;const partial=await client.directory('example');
 console.log(JSON.stringify({completeCount:complete.characters.length,complete:!complete.partial,ids:complete.characters.map(c=>c.id),partial}));
})().catch(error=>{console.error(error);process.exit(1)});
""")
    assert result["completeCount"] == 1100
    assert result["complete"]
    assert set(result["ids"]) == {str(value) for value in range(1, 1101)}
    assert result["partial"]["partial"]
    assert len(result["partial"]["characters"]) == 500
    assert "Temporary disconnect" in " ".join(result["partial"]["warnings"])


def test_invalid_and_unknown_balances_and_raid_detail_identity_are_not_guessed():
    result = node("""
(async()=>{
 const values=[null,'',true,'0x10','Infinity',{},0,-2,'2.5'];
 const amounts=values.map(CurrentDKP=>d.currentBalances([{CharacterId:1,CharacterName:'Toon',CurrentDKP}],{id:'1',name:'Toon'})[0].amount);
 const balances=d.currentBalances([{CharacterId:1,CharacterName:'Other',CurrentDKP:20},{CharacterId:2,CharacterName:'Toon',CurrentDKP:50}],{id:'1',name:'Toon'});
 let mismatch=false;try{await d.createClient({fetch:async()=>new Response(JSON.stringify({RaidId:99,Ticks:[]}))}).raidDetail('example',12)}catch(_){mismatch=true}
 let rejected=0;const client=d.createClient({fetch:async()=>{throw new Error('Must not reach network')}});
 for(const value of ['1/../../other','https://evil.test',0,-1,true])try{await client.raidDetail('example',value)}catch(error){if(error.message==='Choose a valid character or raid.')rejected++}
 console.log(JSON.stringify({amounts,balances,mismatch,rejected}));
})().catch(error=>{console.error(error);process.exit(1)});
""")
    assert result["amounts"] == [None, None, None, None, None, None, 0, -2, 2.5]
    assert result["balances"] == []
    assert result["mismatch"]
    assert result["rejected"] == 5
