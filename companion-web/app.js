const CLASS_BITS=[['Any class',0],['Warrior',1],['Cleric',2],['Paladin',4],['Ranger',8],['Shadow Knight',16],['Druid',32],['Monk',64],['Bard',128],['Rogue',256],['Shaman',512],['Necromancer',1024],['Wizard',2048],['Magician',4096],['Enchanter',8192]];
const RACE_BITS=[['Human',1],['Barbarian',2],['Erudite',4],['Wood Elf',8],['High Elf',16],['Dark Elf',32],['Half Elf',64],['Dwarf',128],['Troll',256],['Ogre',512],['Halfling',1024],['Gnome',2048],['Iksar',4096]];
const SLOT_BITS=[['Any slot',0],['Charm',1],['Ear',18],['Head',4],['Face',8],['Neck',32],['Shoulders',64],['Arms',128],['Back',256],['Wrist',1536],['Range',2048],['Hands',4096],['Primary',8192],['Secondary',16384],['Finger',98304],['Chest',131072],['Legs',262144],['Feet',524288],['Waist',1048576],['Ammo',2097152]];
const STAT_LABELS={ac:'AC',hp:'HP',mana:'Mana',astr:'STR',asta:'STA',adex:'DEX',aagi:'AGI',aint:'INT',awis:'WIS',acha:'CHA',mr:'MR',fr:'FR',cr:'CR',dr:'DR',pr:'PR',attack:'ATK',haste:'Haste',regen:'Regen',manaregen:'Mana regen'};
const state={items:[],spells:[],zones:[],quests:[],meta:null,snapshot:null,snapshotSavedAt:'',installPrompt:null,shellReady:false,shellError:'',catalogs:{},guildLimit:100,questLimit:120};
const CATALOGS={items:{label:'Market',meta:'market-meta',results:'market-results'},spells:{label:'Spells',meta:'spell-meta',results:'spell-results'},zones:{label:'Zones',meta:'zones-meta',results:'zones-results'},quests:{label:'Quests',meta:'quests-meta',results:'quests-results'}};
const $=id=>document.getElementById(id);
const node=(tag,className='',text='')=>{const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el};
const norm=value=>String(value||'').toLocaleLowerCase().replace(/[’'`]/g,'').trim();
const number=value=>Number(value||0).toLocaleString();
const namesForMask=(mask,rows)=>rows.filter(row=>row[1]&&((Number(mask)||0)&row[1])).map(row=>row[0]);
const debounce=(fn,delay=90)=>{let timer;return(...args)=>{clearTimeout(timer);timer=setTimeout(()=>fn(...args),delay)}};
const announceResults=debounce((section,text)=>{if(!$(section).hidden)$('search-announcement').textContent=text},550);
const guildDKP=VantageGuildDKP.mount($('guild-dkp'),{onStateChange:next=>{state.guildSaved=Boolean(next.directorySavedAt);state.guildHistorySaved=Boolean(next.historySavedAt);updateReadiness()}});
function resultCount(id,section,text){$(id).textContent=text;if(!$(section).hidden)announceResults(section,text)}

function fillSelect(select,rows){select.replaceChildren(...rows.map(([label,value])=>{const option=node('option','',label);option.value=String(value);return option}))}
function stamp(value){const date=new Date(value);return Number.isFinite(date.valueOf())?date.toLocaleString():'date unavailable'}
function setConnection(){$('connection').textContent=navigator.onLine?'Online':'Offline';$('connection').classList.toggle('offline',!navigator.onLine);updateReadiness()}
function showPage(name,{focusHeading=true}={}){
  if(!['guild','spells','market','zones','quests','offline'].includes(name))name='guild';
  document.querySelectorAll('.page').forEach(page=>page.hidden=page.id!==name);
  document.querySelectorAll('.tab').forEach(tab=>{const active=tab.dataset.page===name;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1});
  history.replaceState(null,'','#'+name);try{localStorage.setItem('vantageCompanionSection',name)}catch(_){}
  document.title=($(`${name}-title`)?.textContent||'Saved data')+' · Vantage Companion';
  if(focusHeading)$(`${name}-title`)?.focus({preventScroll:true});
}
async function getJSON(path){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
  try{const response=await fetch(path,{cache:'no-store',signal:controller.signal});if(!response.ok)throw new Error(`Request returned ${response.status}`);return await response.json()}
  finally{clearTimeout(timeout)}
}
function validateCatalog(key,payload){
  const rows=payload?.[key];
  if(!Array.isArray(rows)||!rows.length||rows.length>100000||rows.some(row=>!row||typeof row.name!=='string'||!row.name.trim()||row.name.length>1000))throw new Error('The downloaded catalog is incomplete.');
  if(key==='spells'&&rows.some(row=>!Array.isArray(row.levels)||row.levels.some(level=>!Array.isArray(level)||typeof level[0]!=='string'||!Number.isFinite(level[1]))))throw new Error('The spell catalog is incomplete.');
  if(key==='items'&&rows.some(row=>!row.stats||typeof row.stats!=='object'||Array.isArray(row.stats)||!Array.isArray(row.effects)))throw new Error('The item catalog is incomplete.');
  const generatedAt=typeof payload.generatedAt==='string'&&Number.isFinite(Date.parse(payload.generatedAt))?payload.generatedAt:'';
  return {[key]:rows,generatedAt};
}
function renderCatalog(key){if(key==='items')renderMarket();else if(key==='spells'){updateSpellLevels();renderSpells()}else renderReference(key)}
function updateReadiness(){
  const saved=Object.entries(CATALOGS).filter(([key])=>state.catalogs[key]?.durable).map(([,value])=>value.label);
  if(state.guildSaved)saved.unshift(state.guildHistorySaved?'Guild roster & selected history':'Guild roster & balances');
  if(state.snapshot)saved.unshift('PC copy');
  const available=saved.length?saved.join(', '):'No sections saved yet';
  $('offline-status').textContent=state.shellReady?(saved.length?`Ready offline: ${available}.`:'App saved. Connect to save catalogs, or import your PC copy.'):(state.shellError||'Saving the app for offline reopening…')+(saved.length?` Saved data: ${available}.`:'');
  for(const [key,config]of Object.entries(CATALOGS)){
    const status=state.catalogs[key]||{},count=state[key].length;
    const base=status.durable?`${number(count)} records · ${state.shellReady?'Ready offline':'Data saved'} · saved ${stamp(status.savedAt)}.`:count?`${number(count)} records available while this page is open. Not saved offline.`:'No saved catalog yet. Connect and choose Refresh.';
    $(config.meta).textContent=base+(status.loading?' Checking for an update…':'')+(status.error?' '+status.error:'')+(key==='items'&&count?' PigParse Green price snapshot · published '+(status.generatedAt?stamp(status.generatedAt):'date unavailable')+'.':'');
    $(config.results).setAttribute('aria-busy',String(Boolean(status.loading&&!count)));
    document.querySelectorAll(`[data-refresh="${key}"]`).forEach(button=>button.disabled=Boolean(status.loading));
  }
  if(state.snapshot){$('guild-meta').textContent=`${state.snapshot.guild?.name||'No guild in this copy'} · saved from PC ${stamp(state.snapshot.exported_at)}. ${state.shellReady?'Ready offline.':'Data saved; app setup still pending.'} Records are a saved copy, not live.`}
  else $('guild-meta').textContent='No guild copy saved on this device yet. Import a copy from your PC QR session.';
  $('saved-summary').textContent=state.snapshot?`Copy saved on this device ${stamp(state.snapshotSavedAt)}. Source PC export ${stamp(state.snapshot.exported_at)}.`:'No PC copy saved on this device.';
  $('backup').disabled=!state.snapshot;$('forget').disabled=!state.snapshot;
}
async function loadCatalog(key,{restore=false}={}){
  if(state.catalogs[key]?.loading)return;
  const status=state.catalogs[key]||{durable:false,savedAt:'',error:''};state.catalogs[key]=status;status.loading=true;status.error='';updateReadiness();
  try{
    if(restore){
      try{let saved=await VantageStorage.get('catalog:'+key);if(!saved){const old=await VantageStorage.legacy('data/'+key+'.json');if(old)saved=await VantageStorage.put('catalog:'+key,validateCatalog(key,old))}
        if(saved){const payload=validateCatalog(key,saved.payload);state[key]=payload[key];status.generatedAt=payload.generatedAt;status.durable=true;status.savedAt=saved.savedAt;renderCatalog(key);updateReadiness()}}
      catch(_){status.error='Saved storage could not be read. Retry saving with device storage available.'}
    }
    if(!navigator.onLine&&state[key].length)return;
    const payload=validateCatalog(key,await getJSON('data/'+key+'.json'));
    try{const saved=await VantageStorage.put('catalog:'+key,payload);state[key]=payload[key];status.generatedAt=payload.generatedAt;status.durable=true;status.savedAt=saved.savedAt;status.error=''}
    catch(_){if(!status.durable)state[key]=payload[key];status.error='Could not save the update. Free device storage and retry. '+(status.durable?'Your previous saved catalog is unchanged.':'This catalog is not ready offline.')}
  }catch(_){status.error=state[key].length?'Refresh unavailable; keeping the saved catalog.':'Download unavailable. Connect and choose Refresh to retry.'}
  finally{status.loading=false;renderCatalog(key);updateReadiness()}
}
async function loadData(){await Promise.allSettled(Object.keys(CATALOGS).map(key=>loadCatalog(key)))}
function withTimeout(promise,milliseconds){return new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Offline app setup timed out.')),milliseconds);promise.then(value=>{clearTimeout(timer);resolve(value)},error=>{clearTimeout(timer);reject(error)})})}
async function setupShell(){
  if(!('serviceWorker'in navigator)){state.shellError='Offline reopening is unavailable in this browser. Use Safari or Chrome at the permanent HTTPS address.';updateReadiness();return}
  try{
    let registration;
    try{registration=await withTimeout(navigator.serviceWorker.register('sw.js',{scope:'./',updateViaCache:'none'}),10000)}catch(_){registration=await navigator.serviceWorker.getRegistration('./')}
    if(!registration)throw Error('No offline app');
    if(registration.installing)await withTimeout(new Promise((resolve,reject)=>{const worker=registration.installing;worker.addEventListener('statechange',()=>{if(worker.state==='activated')resolve();if(worker.state==='redundant')reject(Error('App install failed'))})}),10000);
    const ready=await withTimeout(navigator.serviceWorker.ready,10000),worker=ready.active;
    state.shellReady=await withTimeout(new Promise(resolve=>{const channel=new MessageChannel();channel.port1.onmessage=event=>{channel.port1.close();resolve(event.data?.ready===true)};worker.postMessage({type:'vantage-shell-ready'},[channel.port2])}),3000);
    if(!state.shellReady)throw Error('App shell incomplete');state.shellError='';
  }catch(_){state.shellError='App is not ready to reopen offline. Connect and choose Refresh public catalogs to finish setup.'}
  updateReadiness();
}

function itemSearchText(item){if(item._search)return item._search;const effects=(item.effects||[]).map(effect=>`${effect.type} ${effect.name}`).join(' ');const stats=Object.entries(item.stats||{}).map(([key,value])=>`${STAT_LABELS[key]||key} ${value}`).join(' ');item._search=norm(`${item.name} ${effects} ${stats} ${item.era||''} ${item.nodrop?'no drop':'droppable'}`);return item._search}
function renderMarket(){
  const query=norm($('market-search').value),classBit=Number($('market-class').value),slotBit=Number($('market-slot').value),binding=$('market-binding').value,sort=$('market-sort').value;
  let rows=state.items.filter(item=>(!query||itemSearchText(item).includes(query))&&(!classBit||(Number(item.classes)&classBit))&&(!slotBit||(Number(item.slots)&slotBit))&&(!binding||(binding==='nodrop')===Boolean(item.nodrop)));
  rows.sort((a,b)=>sort==='name'?String(a.name).localeCompare(String(b.name)):((Number(b[sort]??b.stats?.[sort])||0)-(Number(a[sort]??a.stats?.[sort])||0)||String(a.name).localeCompare(String(b.name))));
  resultCount('market-count','market',`Showing ${number(Math.min(rows.length,160))} of ${number(rows.length)} matching items`);
  const cards=rows.slice(0,160).map(item=>{
    const card=node('button','result-card');card.type='button';card.setAttribute('aria-label',`Open item details for ${item.name}`);
    const top=node('span','card-top');top.append(node('span','card-name',item.name),node('span','price',item.price?`${number(item.price)} pp`:'—'));
    const chips=node('span','chips');chips.append(node('span',`chip ${item.nodrop?'warn':''}`,item.nodrop?'NO DROP':'DROPPABLE'));if(item.era)chips.append(node('span','chip',String(item.era).toUpperCase()));
    const statline=Object.entries(item.stats||{}).slice(0,6).map(([key,value])=>`${STAT_LABELS[key]||key.toUpperCase()} ${value>0?'+':''}${value}`).join(' · ')||'No indexed stats';
    card.append(top,chips,node('span','statline',statline));card.addEventListener('click',()=>openItem(item));return card;
  });
  $('market-results').replaceChildren(...(cards.length?cards:[node('p','empty',state.items.length?'No items match these filters.':'No item catalog saved yet. Connect and choose Refresh Market.')]))
}

function openItem(item){
  const body=$('detail-body'),title=node('h2','detail-title',item.name);title.id='detail-title';body.replaceChildren();body.append(node('p','eyebrow','PROJECT 1999 ITEM'),title);
  const chips=node('div','chips');chips.append(node('span',`chip ${item.nodrop?'warn':''}`,item.nodrop?'NO DROP':'DROPPABLE'));if(item.era)chips.append(node('span','chip',String(item.era).toUpperCase()));body.append(chips,node('p','price',item.price?`${number(item.price)} pp · PigParse 30d`:'No recent PigParse price'),node('p','meta',`${number(item.posts)} observations · price snapshot published ${state.catalogs.items?.generatedAt?stamp(state.catalogs.items.generatedAt):'date unavailable'}`));
  const identity=[['Classes',namesForMask(item.classes,CLASS_BITS).join(', ')||'Any / not indexed'],['Races',namesForMask(item.races,RACE_BITS).join(', ')||'Any / not indexed'],['Slots',namesForMask(item.slots,SLOT_BITS).join(', ')||'Not indexed']];
  identity.forEach(([label,value])=>{body.append(node('h3','',label),node('p','summary',value))});
  const entries=Object.entries(item.stats||{});if(entries.length){body.append(node('h3','','Stats'));const grid=node('div','detail-grid');entries.forEach(([key,value])=>{const cell=node('div','detail-stat');cell.append(node('b','',STAT_LABELS[key]||key.toUpperCase()),node('span','',`${value>0?'+':''}${value}`));grid.append(cell)});body.append(grid)}
  if(item.effects?.length){body.append(node('h3','','Click / Proc / Worn effects'));item.effects.forEach(effect=>body.append(node('div','effect',`${effect.type} · ${effect.name}`)))}
  appendLink(body,'Open Project 1999 Wiki source (new tab)',item.wiki);showDialog('detail')
}

function updateSpellLevels(){const wanted=$('spell-class').value;const levels=[...new Set(state.spells.flatMap(spell=>(spell.levels||[]).filter(row=>!wanted||row[0]===wanted).map(row=>row[1])))].sort((a,b)=>a-b);const current=$('spell-level').value;fillSelect($('spell-level'),[['Any available level',''],...levels.map(level=>[`Level ${level}`,level])]);if(levels.includes(Number(current)))$('spell-level').value=current}
function spellSearchText(spell){if(spell._search)return spell._search;spell._search=norm(`${spell.name} ${spell.summary} ${(spell.levels||[]).flat().join(' ')}`);return spell._search}
function renderSpells(){
  const query=norm($('spell-search').value),className=$('spell-class').value,level=Number($('spell-level').value);
  const rows=state.spells.filter(spell=>(!query||spellSearchText(spell).includes(query))&&(spell.levels||[]).some(row=>(!className||row[0]===className)&&(!level||Number(row[1])===level)));
  rows.sort((a,b)=>String(a.name).localeCompare(String(b.name)));resultCount('spell-count','spells',`Showing ${number(Math.min(rows.length,180))} of ${number(rows.length)} matching spells`);
  const cards=rows.slice(0,180).map(spell=>{const card=node('button','result-card');card.type='button';card.setAttribute('aria-label',`Open spell details for ${spell.name}`);const top=node('span','card-top');top.append(node('span','card-name',spell.name),node('span','price',`ID ${spell.id}`));const chips=node('span','chips');(spell.levels||[]).slice(0,4).forEach(row=>chips.append(node('span','chip',`${row[0]} ${row[1]}`)));card.append(top,chips,node('span','statline',spell.summary||'Bundled P99 spell data'));card.addEventListener('click',()=>openSpell(spell));return card});
  $('spell-results').replaceChildren(...(cards.length?cards:[node('p','empty',state.spells.length?'No spells match this class, level, and search.':'No spell catalog saved yet. Connect and choose Refresh Spells.')]))
}
function openSpell(spell){const body=$('detail-body'),title=node('h2','detail-title',spell.name);title.id='detail-title';body.replaceChildren();body.append(node('p','eyebrow','P99 CLASSIC SPELL'),title,node('p','summary',spell.summary||'Bundled P99 spell data'),node('h3','','Classes and available levels'));(spell.levels||[]).forEach(row=>body.append(node('div','effect',`${row[0]} · Level ${row[1]}`)));appendLink(body,'Open Project 1999 Wiki spell page (new tab)',spell.wiki);showDialog('detail')}

function appendLink(parent,label,value,kind='wiki'){
  const href=VantageOffline.safeURL(value,kind);if(!href)return;
  const link=node('a','source-link',label);link.href=href;link.target='_blank';link.rel='noreferrer noopener';parent.append(link);
}
const dialogFocus=new WeakMap();
function showDialog(id){const dialog=$(id);dialogFocus.set(dialog,document.activeElement);dialog.showModal();dialog.querySelector('button')?.focus()}
function renderGuild(reset=false){
  if(reset)state.guildLimit=100;
  const guild=state.snapshot?.guild,root=$('guild-results'),view=$('guild-view').value,query=norm($('guild-search').value);
  if(!guild){root.replaceChildren(node('p','empty','Import your selected guild from the PC QR session to search DKP, loot and raids here without the PC.'));$('guild-count').textContent='';$('guild-more').hidden=true;return}
  const rows=(guild[view]||[]).filter(row=>!query||norm(Object.values(row).join(' ')).includes(query));
  const incomplete=view==='loot'&&(state.snapshot.truncated||[]).some(section=>section.startsWith('guild.loot'));
  const warning=incomplete?' · This saved loot history is incomplete. Refresh the guild on the PC and import a new copy.':'';
  resultCount('guild-count','guild',`${number(rows.length)} matching saved records · showing ${number(Math.min(rows.length,state.guildLimit))}${warning}`);
  $('guild-more').hidden=rows.length<=state.guildLimit;
  const cards=rows.slice(0,state.guildLimit).map(row=>{
    const card=node('article','result-card'),title=view==='standings'?row.name:view==='loot'?row.item:row.name;
    card.append(node('h2','card-name',title||'Saved record'));
    if(view==='standings'){card.append(node('p','price',`${row.dkp||'—'} DKP`),node('p','summary',[row.class,row.level?'Level '+row.level:'',row.rank].filter(Boolean).join(' · ')),node('p','summary','30-day attendance · '+(row.attendance||'—')))}
    else if(view==='loot'){card.append(node('p','summary',[row.character,row.date,row.raid].filter(Boolean).join(' · ')),node('p','price',(row.dkp||'—')+' DKP'));appendLink(card,`${row.item} on Wiki (new tab)`,row.wiki_url)}
    else if(view==='raids')card.append(node('p','summary',row.date),node('p','summary',`${row.items||'—'} items · ${row.awarded||'—'} DKP awarded · ${row.spent||'—'} spent`));
    else{card.append(node('p','summary','Sheet contents need internet; only this link is saved.'));appendLink(card,`Open ${row.name||'guild sheet'} (new tab)`,row.url,'sheet')}
    return card;
  });
  root.replaceChildren(...(cards.length?cards:[node('p','empty','No saved records match this search.')]))
}
function referenceRows(key){
  const rows=[...state[key]],saved=key==='zones'?state.snapshot?.zone:state.snapshot?.quest,name=saved&&(saved.name||saved.title);
  if(name&&!rows.some(row=>norm(row.name)===norm(name)))rows.unshift({name,wiki:saved.wiki_url});return rows;
}
function renderReference(key,reset=false){
  if(reset&&key==='quests')state.questLimit=120;
  const query=norm($(key+'-search').value),rows=referenceRows(key).filter(row=>!query||norm(row.name).includes(query)),limit=key==='quests'?state.questLimit:2000;
  resultCount(key+'-count',key,`${number(rows.length)} matching names · showing ${number(Math.min(rows.length,limit))}`);
  if(key==='quests')$('quests-more').hidden=rows.length<=limit;
  const saved=key==='zones'?state.snapshot?.zone:state.snapshot?.quest,savedName=saved&&(saved.name||saved.title);
  const cards=rows.slice(0,limit).map(row=>{
    const card=node('button','result-card reference-card');card.type='button';card.setAttribute('aria-haspopup','dialog');card.append(node('span','card-name',row.name),node('span','summary',norm(row.name)===norm(savedName)?'Saved PC details available':'Name saved · Wiki details need internet'));card.addEventListener('click',()=>openReference(key,row));return card;
  });
  $(key+'-results').replaceChildren(...(cards.length?cards:[node('p','empty',state[key].length?'No names match this search.':'No catalog saved yet. Connect and choose Refresh, or import a PC copy.')]))
}
function revealMore(section){
  const previous=section==='guild'?state.guildLimit:state.questLimit;
  if(section==='guild'){state.guildLimit+=100;renderGuild()}else{state.questLimit+=120;renderReference('quests')}
  const next=$(section+'-results').children[previous];
  if(next){const target=next.tagName==='BUTTON'?next:next.querySelector('h2')||next;if(target.tagName!=='BUTTON')target.tabIndex=-1;target.focus()}
  else $(section+'-title').focus();
}
function openReference(key,row){
  const body=$('detail-body'),title=node('h2','detail-title',row.name);title.id='detail-title';body.replaceChildren(node('p','eyebrow',key==='zones'?'ZONE REFERENCE':'QUEST REFERENCE'),title);
  const saved=key==='zones'?state.snapshot?.zone:state.snapshot?.quest,detail=saved&&norm(saved.name||saved.title)===norm(row.name)?saved:null;
  if(detail){
    body.append(node('p','meta','Saved from PC '+stamp(state.snapshot.exported_at)),node('p','summary readable-copy',detail.summary||'No summary was included in this copy.'));
    if(key==='zones'){
      if(detail.era||detail.levels)body.append(node('p','meta',[detail.era,detail.levels].filter(Boolean).join(' · ')));
      if(detail.unique_items.length){body.append(node('h3','','Saved items'));const list=node('ul');detail.unique_items.forEach(name=>list.append(node('li','',name)));body.append(list)}
      if(detail.mobs.length){body.append(node('h3','','Saved mobs'));detail.mobs.forEach(mob=>body.append(node('p','effect',[mob.name,mob.named?'Named':'',mob.level?'Level '+mob.level:'',mob.class,mob.race,mob.location,mob.loot].filter(Boolean).join(' · '))))}
      if(!detail.mobs.length&&!detail.unique_items.length)body.append(node('p','meta','Mob and item details were not included. Open the Wiki online for more.'));
    }else{
      Object.entries(detail.metadata).filter(([,value])=>value).forEach(([label,value])=>body.append(node('p','meta',label+' · '+value)));
      if(detail.rewards.length)body.append(node('h3','','Saved rewards'),node('p','summary',detail.rewards.join(' · ')));
      if(detail.steps.length){body.append(node('h3','','Saved checklist'));const list=node('ol','quest-steps');detail.steps.forEach((step,index)=>list.append(node('li',step.kind==='group'?'step-group':'',(detail.checked.includes(index)?'Completed in saved copy · ':'')+step.text)));body.append(list)}
      else body.append(node('p','meta','No walkthrough was included in this copy. Open the Wiki online for details.'));
    }
  }else body.append(node('p','summary','This name is available offline. Detailed content has not been saved on this device. Open the Wiki with internet, or select it in Vantage and import a fresh PC copy.'));
  appendLink(body,`Open ${row.name} on Wiki (new tab)`,detail?.wiki_url||row.wiki);showDialog('detail');
}
let pendingImport=null;
function importStatus(message){$('import-status').textContent=message}
function previewImport(snapshot,finish=()=>{},isActive=()=>true){
  if(pendingImport){finish(false);return}
  pendingImport={snapshot,finish,isActive};const root=$('import-preview');root.replaceChildren(node('p','meta','Saved from PC '+stamp(snapshot.exported_at)));
  const list=node('ul');list.append(node('li','',snapshot.guild?`${snapshot.guild.name} · ${number(snapshot.guild.standings.length)} standings, ${number(snapshot.guild.loot.length)} loot records, ${number(snapshot.guild.raids.length)} raids`:'No guild records in this copy.'));
  list.append(node('li','',snapshot.zone?'Current zone · '+snapshot.zone.name:'No current zone details.'),node('li','',snapshot.quest?'Current quest · '+snapshot.quest.title:'No current quest details.'));root.append(list);
  if(snapshot.truncated.length)root.append(node('p','meta','The PC limited these sections: '+snapshot.truncated.join(', ')));
  root.append(node('p','meta','Only the selected guild and current zone/quest details are included. No live timers, auctions, game images or credentials are saved.'));
  $('import-review-status').textContent='';$('import-confirm').disabled=false;showDialog('import-review');
}
async function importFile(file){
  if(!file)return;
  try{
    if(file.size>VantageOffline.MAX_BYTES)throw Error('Offline files must be 8 MiB or smaller.');
    if(file.type&&!['application/json','text/plain','application/octet-stream'].includes(file.type))throw Error('Choose a Vantage JSON offline file.');
    const data=VantageOffline.snapshot(JSON.parse(await file.text()));previewImport(data);
  }catch(error){importStatus(error instanceof SyntaxError?'This file is not valid JSON. Choose a Vantage offline export.':error.message)}
  finally{$('import-file').value=''}
}
async function saveImport(){
  const pending=pendingImport;if(!pending)return;
  if(!pending.isActive()){$('import-review-status').textContent='This transfer expired. Close this review and import the file, or send a new copy.';return}
  $('import-confirm').disabled=true;
  try{
    const saved=await VantageStorage.put('pc-copy',pending.snapshot);
    state.snapshot=saved.payload;state.snapshotSavedAt=saved.savedAt;pendingImport=null;pending.finish(true);$('import-review').close();renderGuild(true);renderReference('zones');renderReference('quests');updateReadiness();$('guild-snapshot').open=true;guildDKP?.suggestGuild(state.snapshot.guild?.slug);
    importStatus('Copy saved on this device. '+(state.shellReady?'Ready offline.':'Finish app setup online before closing it.'));showPage(state.snapshot.guild?'guild':'offline');
    if(navigator.storage?.persist)navigator.storage.persist().catch(()=>{});
  }catch(_){$('import-review-status').textContent='Could not save this copy. Your previous copy is unchanged. Free device storage, then retry.';$('import-confirm').disabled=false}
}
async function restoreSnapshot(){
  try{const saved=await VantageStorage.get('pc-copy');if(saved){state.snapshot=VantageOffline.snapshot(saved.payload);state.snapshotSavedAt=saved.savedAt}}
  catch(_){importStatus('Saved PC data could not be read. Your stored copy has not been replaced. Import a backup or retry with device storage available.')}
  renderGuild();renderReference('zones');renderReference('quests');updateReadiness();guildDKP?.suggestGuild(state.snapshot?.guild?.slug);
}
function exportSnapshot(){
  if(!state.snapshot)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(state.snapshot)],{type:'application/json'})),link=node('a');link.href=url;link.download='vantage-offline-backup.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);importStatus('Saved copy exported. Keep it somewhere you can access from the installed app.');
}
function installHelp(){const ios=/iphone|ipad|ipod/i.test(navigator.userAgent);$('install-copy').textContent=(ios?'Open this permanent HTTPS address in Safari, tap Share, choose Add to Home Screen, enable Open as Web App, and tap Add. ':'Open the browser menu and choose Install app or Add to Home screen. ')+'Replace an old local-PC shortcut once. Open the new icon online, wait for Ready offline, then import your PC file inside the installed app. Safari and the installed app can keep separate saved data.';showDialog('install-help')}
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();state.installPrompt=event;$('install').hidden=false});
$('install').addEventListener('click',async()=>{if(!state.installPrompt){installHelp();return}state.installPrompt.prompt();await state.installPrompt.userChoice;state.installPrompt=null});
const tabs=[...document.querySelectorAll('.tab')];
tabs.forEach((tab,index)=>{tab.addEventListener('click',()=>showPage(tab.dataset.page));tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();showPage(tabs[next].dataset.page,{focusHeading:false})})});
$('open-market').addEventListener('click',()=>showPage('market'));
document.querySelectorAll('[data-refresh]').forEach(button=>button.addEventListener('click',()=>{loadCatalog(button.dataset.refresh);if(!state.shellReady)setupShell()}));
$('refresh-all').addEventListener('click',async()=>{$('refresh-all').disabled=true;await Promise.allSettled([loadData(),setupShell()]);$('refresh-all').disabled=false});
['market-search','market-class','market-slot','market-binding','market-sort'].forEach(id=>$(id).addEventListener(id==='market-search'?'input':'change',debounce(renderMarket)));
$('spell-search').addEventListener('input',debounce(renderSpells));$('spell-class').addEventListener('change',()=>{updateSpellLevels();renderSpells()});$('spell-level').addEventListener('change',renderSpells);
window.addEventListener('online',setConnection);window.addEventListener('offline',setConnection);
document.querySelector('.skip').addEventListener('click',event=>{event.preventDefault();$('main').focus()});
window.addEventListener('hashchange',()=>{if(location.hash==='#main'){$('main').focus();return}showPage(location.hash.slice(1),{focusHeading:false})});
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('close',()=>{const previous=dialogFocus.get(dialog);if(previous?.isConnected&&!previous.closest('[hidden]'))previous.focus()}));
$('guild-search').addEventListener('input',debounce(()=>renderGuild(true)));$('guild-view').addEventListener('change',()=>renderGuild(true));$('guild-more').addEventListener('click',()=>revealMore('guild'));
for(const key of ['zones','quests'])$(key+'-search').addEventListener('input',debounce(()=>renderReference(key,true)));
$('quests-more').addEventListener('click',()=>revealMore('quests'));
document.querySelectorAll('.import-shortcut').forEach(button=>button.addEventListener('click',()=>{showPage('offline');$('import-file').focus()}));
$('import-file').addEventListener('change',event=>importFile(event.target.files[0]));$('import-confirm').addEventListener('click',saveImport);$('import-cancel').addEventListener('click',()=>$('import-review').close());
$('import-review').addEventListener('close',()=>{if(pendingImport){pendingImport.finish(false);pendingImport=null}});
$('backup').addEventListener('click',exportSnapshot);$('forget').addEventListener('click',()=>{$('forget-status').textContent='';showDialog('forget-review')});
$('forget-confirm').addEventListener('click',async()=>{try{await VantageStorage.remove('pc-copy');state.snapshot=null;state.snapshotSavedAt='';dialogFocus.set($('forget-review'),$('import-file'));$('forget-review').close();renderGuild();renderReference('zones');renderReference('quests');updateReadiness();importStatus('Imported PC copy removed from this device. Restore it by importing your exported backup.');$('import-file').focus()}catch(_){$('forget-status').textContent='Could not remove the copy. Your saved data is unchanged.'}});
fillSelect($('market-class'),CLASS_BITS);fillSelect($('market-slot'),SLOT_BITS);fillSelect($('spell-class'),[['Any class',''],...CLASS_BITS.slice(1).filter(row=>!['Warrior','Monk','Rogue'].includes(row[0])).map(row=>[row[0],row[0]])]);
const receiving=location.hash.startsWith('#import?');
if(receiving)VantageOffline.handoff(previewImport,importStatus);
let initialPage=location.hash.slice(1);try{initialPage=initialPage||localStorage.getItem('vantageCompanionSection')}catch(_){}
setConnection();showPage(receiving?'offline':initialPage||'guild',{focusHeading:false});
restoreSnapshot();Object.keys(CATALOGS).forEach(key=>loadCatalog(key,{restore:true}));setupShell();
getJSON('data/meta.json').then(meta=>{if(meta&&typeof meta.generatedAt==='string')state.meta=meta}).catch(()=>{});
