const CLASS_BITS=[['Any class',0],['Warrior',1],['Cleric',2],['Paladin',4],['Ranger',8],['Shadow Knight',16],['Druid',32],['Monk',64],['Bard',128],['Rogue',256],['Shaman',512],['Necromancer',1024],['Wizard',2048],['Magician',4096],['Enchanter',8192]];
const RACE_BITS=[['Human',1],['Barbarian',2],['Erudite',4],['Wood Elf',8],['High Elf',16],['Dark Elf',32],['Half Elf',64],['Dwarf',128],['Troll',256],['Ogre',512],['Halfling',1024],['Gnome',2048],['Iksar',4096]];
const SLOT_BITS=[['Any slot',0],['Charm',1],['Ear',18],['Head',4],['Face',8],['Neck',32],['Shoulders',64],['Arms',128],['Back',256],['Wrist',1536],['Range',2048],['Hands',4096],['Primary',8192],['Secondary',16384],['Finger',98304],['Chest',131072],['Legs',262144],['Feet',524288],['Waist',1048576],['Ammo',2097152]];
const STAT_LABELS={ac:'AC',hp:'HP',mana:'Mana',astr:'STR',asta:'STA',adex:'DEX',aagi:'AGI',aint:'INT',awis:'WIS',acha:'CHA',mr:'MR',fr:'FR',cr:'CR',dr:'DR',pr:'PR',attack:'ATK',haste:'Haste',regen:'Regen',manaregen:'Mana regen'};
const state={items:[],spells:[],meta:null,installPrompt:null};
const $=id=>document.getElementById(id);
const node=(tag,className='',text='')=>{const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el};
const norm=value=>String(value||'').toLocaleLowerCase().replace(/[’'`]/g,'').trim();
const number=value=>Number(value||0).toLocaleString();
const namesForMask=(mask,rows)=>rows.filter(row=>row[1]&&((Number(mask)||0)&row[1])).map(row=>row[0]);
const debounce=(fn,delay=90)=>{let timer;return(...args)=>{clearTimeout(timer);timer=setTimeout(()=>fn(...args),delay)}};

function fillSelect(select,rows){select.replaceChildren(...rows.map(([label,value])=>{const option=node('option','',label);option.value=String(value);return option}))}
function setConnection(){const offline=!navigator.onLine;$('connection').textContent=offline?'OFFLINE READY':'ONLINE';$('connection').classList.toggle('offline',offline)}
function showPage(name,{focusHeading=true}={}){document.querySelectorAll('.page').forEach(page=>page.hidden=page.id!==name);document.querySelectorAll('.tab').forEach(tab=>{const active=tab.dataset.page===name;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1});history.replaceState(null,'','#'+name);if(focusHeading)document.querySelector(`#${name} h1`)?.focus({preventScroll:true})}

async function getJSON(path,force=false){const response=await fetch(path,{cache:force?'reload':'default'});if(!response.ok)throw new Error(`${path} returned ${response.status}`);return response.json()}
async function loadData(force=false){
  $('market-results').setAttribute('aria-busy','true');$('spell-results').setAttribute('aria-busy','true');
  try{
    const [itemData,spellData,meta]=await Promise.all([getJSON('data/items.json',force),getJSON('data/spells.json',force),getJSON('data/meta.json',force)]);
    state.items=Array.isArray(itemData.items)?itemData.items:[];state.spells=Array.isArray(spellData.spells)?spellData.spells:[];state.meta=meta;
    const stamp=new Date(meta.generatedAt);const when=Number.isNaN(stamp.valueOf())?'unknown':stamp.toLocaleString();
    $('market-meta').textContent=`Source · ${meta.priceSource} · snapshot ${when} · ${number(meta.pricedItemCount)} priced items. Offline keeps the last successful snapshot.`;
    $('spell-meta').textContent=`Source · ${meta.spellSource} · ${number(meta.spellCount)} spells cached for offline use.`;
    updateSpellLevels();renderMarket();renderSpells();
  }catch(error){
    const message='Catalog unavailable. Connect once and tap Refresh Data so this device can save the offline copy.';
    $('market-meta').textContent=message;$('spell-meta').textContent=message;
    $('market-results').replaceChildren(node('p','empty',message));$('spell-results').replaceChildren(node('p','empty',message));
  }finally{$('market-results').setAttribute('aria-busy','false');$('spell-results').setAttribute('aria-busy','false')}
}

function itemSearchText(item){if(item._search)return item._search;const effects=(item.effects||[]).map(effect=>`${effect.type} ${effect.name}`).join(' ');const stats=Object.entries(item.stats||{}).map(([key,value])=>`${STAT_LABELS[key]||key} ${value}`).join(' ');item._search=norm(`${item.name} ${effects} ${stats} ${item.era||''} ${item.nodrop?'no drop':'droppable'}`);return item._search}
function renderMarket(){
  const query=norm($('market-search').value),classBit=Number($('market-class').value),slotBit=Number($('market-slot').value),binding=$('market-binding').value,sort=$('market-sort').value;
  let rows=state.items.filter(item=>(!query||itemSearchText(item).includes(query))&&(!classBit||(Number(item.classes)&classBit))&&(!slotBit||(Number(item.slots)&slotBit))&&(!binding||(binding==='nodrop')===Boolean(item.nodrop)));
  rows.sort((a,b)=>sort==='name'?String(a.name).localeCompare(String(b.name)):((Number(b[sort]??b.stats?.[sort])||0)-(Number(a[sort]??a.stats?.[sort])||0)||String(a.name).localeCompare(String(b.name))));
  $('market-count').textContent=`Showing ${number(Math.min(rows.length,160))} of ${number(rows.length)} matching items`;
  const cards=rows.slice(0,160).map(item=>{
    const card=node('button','result-card');card.type='button';card.setAttribute('aria-label',`Open item details for ${item.name}`);
    const top=node('span','card-top');top.append(node('span','card-name',item.name),node('span','price',item.price?`${number(item.price)} pp`:'—'));
    const chips=node('span','chips');chips.append(node('span',`chip ${item.nodrop?'warn':''}`,item.nodrop?'NO DROP':'DROPPABLE'));if(item.era)chips.append(node('span','chip',String(item.era).toUpperCase()));
    const statline=Object.entries(item.stats||{}).slice(0,6).map(([key,value])=>`${STAT_LABELS[key]||key.toUpperCase()} ${value>0?'+':''}${value}`).join(' · ')||'No indexed stats';
    card.append(top,chips,node('span','statline',statline));card.addEventListener('click',()=>openItem(item));return card;
  });
  $('market-results').replaceChildren(...(cards.length?cards:[node('p','empty','No items match these filters.')]))
}

function openItem(item){
  const body=$('detail-body');body.replaceChildren();body.append(node('p','eyebrow','PROJECT 1999 ITEM'),node('h2','detail-title',item.name));
  const chips=node('div','chips');chips.append(node('span',`chip ${item.nodrop?'warn':''}`,item.nodrop?'NO DROP':'DROPPABLE'));if(item.era)chips.append(node('span','chip',String(item.era).toUpperCase()));body.append(chips,node('p','price',item.price?`${number(item.price)} pp · PigParse 30d`:'No recent PigParse price'),node('p','meta',`${number(item.posts)} observations · cached snapshot ${state.meta?new Date(state.meta.generatedAt).toLocaleString():'unknown'}`));
  const identity=[['Classes',namesForMask(item.classes,CLASS_BITS).join(', ')||'Any / not indexed'],['Races',namesForMask(item.races,RACE_BITS).join(', ')||'Any / not indexed'],['Slots',namesForMask(item.slots,SLOT_BITS).join(', ')||'Not indexed']];
  identity.forEach(([label,value])=>{body.append(node('h3','',label),node('p','summary',value))});
  const entries=Object.entries(item.stats||{});if(entries.length){body.append(node('h3','','Stats'));const grid=node('div','detail-grid');entries.forEach(([key,value])=>{const cell=node('div','detail-stat');cell.append(node('b','',STAT_LABELS[key]||key.toUpperCase()),node('span','',`${value>0?'+':''}${value}`));grid.append(cell)});body.append(grid)}
  if(item.effects?.length){body.append(node('h3','','Click / Proc / Worn effects'));item.effects.forEach(effect=>body.append(node('div','effect',`${effect.type} · ${effect.name}`)))}
  const link=node('a','source-link','Open Project 1999 Wiki source');link.href=item.wiki;link.target='_blank';link.rel='noreferrer noopener';body.append(link);$('detail').showModal()
}

function updateSpellLevels(){const wanted=$('spell-class').value;const levels=[...new Set(state.spells.flatMap(spell=>(spell.levels||[]).filter(row=>!wanted||row[0]===wanted).map(row=>row[1])))].sort((a,b)=>a-b);const current=$('spell-level').value;fillSelect($('spell-level'),[['Any available level',''],...levels.map(level=>[`Level ${level}`,level])]);if(levels.includes(Number(current)))$('spell-level').value=current}
function spellSearchText(spell){if(spell._search)return spell._search;spell._search=norm(`${spell.name} ${spell.summary} ${(spell.levels||[]).flat().join(' ')}`);return spell._search}
function renderSpells(){
  const query=norm($('spell-search').value),className=$('spell-class').value,level=Number($('spell-level').value);
  const rows=state.spells.filter(spell=>(!query||spellSearchText(spell).includes(query))&&(spell.levels||[]).some(row=>(!className||row[0]===className)&&(!level||Number(row[1])===level)));
  rows.sort((a,b)=>String(a.name).localeCompare(String(b.name)));$('spell-count').textContent=`Showing ${number(Math.min(rows.length,180))} of ${number(rows.length)} matching spells`;
  const cards=rows.slice(0,180).map(spell=>{const card=node('button','result-card');card.type='button';card.setAttribute('aria-label',`Open spell details for ${spell.name}`);const top=node('span','card-top');top.append(node('span','card-name',spell.name),node('span','price',`ID ${spell.id}`));const chips=node('span','chips');(spell.levels||[]).slice(0,4).forEach(row=>chips.append(node('span','chip',`${row[0]} ${row[1]}`)));card.append(top,chips,node('span','statline',spell.summary||'Bundled P99 spell data'));card.addEventListener('click',()=>openSpell(spell));return card});
  $('spell-results').replaceChildren(...(cards.length?cards:[node('p','empty','No spells match this class, level, and search.')]))
}
function openSpell(spell){const body=$('detail-body');body.replaceChildren();body.append(node('p','eyebrow','P99 CLASSIC SPELL'),node('h2','detail-title',spell.name),node('p','summary',spell.summary||'Bundled P99 spell data'),node('h3','','Classes and available levels'));(spell.levels||[]).forEach(row=>body.append(node('div','effect',`${row[0]} · Level ${row[1]}`)));const link=node('a','source-link','Open Project 1999 Wiki spell page');link.href=spell.wiki;link.target='_blank';link.rel='noreferrer noopener';body.append(link);$('detail').showModal()}

function installHelp(){const ios=/iphone|ipad|ipod/i.test(navigator.userAgent);$('install-copy').textContent=ios?'Open this address in Safari, tap Share, choose Add to Home Screen, enable Open as Web App, and tap Add.':'Open your browser menu and choose Install app or Add to Home screen. Once the catalogs load successfully, Market and Spells remain available offline.';$('install-help').showModal()}
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();state.installPrompt=event;$('install').hidden=false});
$('install').addEventListener('click',async()=>{if(!state.installPrompt){installHelp();return}state.installPrompt.prompt();await state.installPrompt.userChoice;state.installPrompt=null});
const tabs=[...document.querySelectorAll('.tab')];
tabs.forEach((tab,index)=>{tab.addEventListener('click',()=>showPage(tab.dataset.page));tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();showPage(tabs[next].dataset.page,{focusHeading:false})})});
$('open-market').addEventListener('click',()=>showPage('market'));
$('refresh').addEventListener('click',async()=>{$('refresh').disabled=true;await loadData(true);$('refresh').disabled=false});
['market-search','market-class','market-slot','market-binding','market-sort'].forEach(id=>$(id).addEventListener(id==='market-search'?'input':'change',debounce(renderMarket)));
$('spell-search').addEventListener('input',debounce(renderSpells));$('spell-class').addEventListener('change',()=>{updateSpellLevels();renderSpells()});$('spell-level').addEventListener('change',renderSpells);
window.addEventListener('online',setConnection);window.addEventListener('offline',setConnection);
fillSelect($('market-class'),CLASS_BITS);fillSelect($('market-slot'),SLOT_BITS);fillSelect($('spell-class'),[['Any class',''],...CLASS_BITS.slice(1).filter(row=>!['Warrior','Monk','Rogue'].includes(row[0])).map(row=>[row[0],row[0]])]);
setConnection();showPage(location.hash.slice(1)&&$(location.hash.slice(1))?location.hash.slice(1):'market',{focusHeading:false});loadData();
if('serviceWorker'in navigator)navigator.serviceWorker.register('sw.js',{scope:'./'}).catch(()=>{});
