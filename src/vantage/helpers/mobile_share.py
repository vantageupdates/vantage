"""Private mobile companion; only Vantage timers accept phone-side actions."""

from __future__ import annotations

import hmac
import hashlib
import html as html_module
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import platform
import re
import secrets
import socket
import subprocess
import threading
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, quote, urlsplit

import segno
from PySide6.QtCore import QObject, QProcess, QSize, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
    QWidget)

from vantage.helpers import config
from vantage.helpers.game_capture import GameWindowCapture
from vantage.helpers.icons import game_icon
from vantage.helpers.portable import data_dir
from vantage.helpers.responsive import ResponsiveActionBar, scrollable
from vantage.helpers.scaled_dialog import UniformScaleDialog
from vantage.helpers.spell_catalog import p99_spell_entries


CLOUDFLARED_DOWNLOAD = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe")
CLOUDFLARE_QUICK_TUNNEL_DOCS = (
    "https://developers.cloudflare.com/cloudflare-one/networks/connectors/"
    "cloudflare-tunnel/do-more-with-tunnels/trycloudflare/")
COMPANION_URL = "https://vantageupdates.github.io/vantage/companion/"
TUNNEL_URL_RX = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)
P99_SPELL_DETAIL_API = (
    "https://wiki.project1999.com/api.php?action=parse&page={slug}"
    "&prop=wikitext&format=json")


def parse_mobile_spell_detail(wikitext):
    """Extract the factual description and slot effects from a P99 spell page."""
    source = str(wikitext or "")
    match = re.search(
        r"(?ims)^\|\s*description\s*=\s*(.*?)"
        r"(?=^\|\s*[a-z_][\w ]*\s*=|^\}\}\s*$)", source)
    description = match.group(1) if match else ""

    def plain(value):
        value = re.sub(r"<br\s*/?>", "\n", str(value), flags=re.IGNORECASE)
        value = re.sub(
            r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", value)
        value = re.sub(r"\[https?://[^\]\s]+(?:\s+([^\]]+))?\]", r"\1", value)
        value = re.sub(r"\{\{[^{}]*\}\}", "", value)
        value = re.sub(r"<[^>]+>", "", value)
        value = html_module.unescape(value).replace("'''", "").replace("''", "")
        return " ".join(value.split())

    effects = []
    for raw_effect in re.findall(
            r"(?is)\{\{SpellSlotRow\s*\|\s*\d+\s*\|\s*(.*?)\}\}",
            source):
        effect = plain(raw_effect)
        if effect and effect not in effects:
            effects.append(effect)
    return {
        "description": plain(description)[:1800],
        "effects": effects[:12],
        "source": "Project 1999 Wiki",
    }


def _mobile_spell_detail_path(name):
    digest = hashlib.sha256(
        str(name).strip().casefold().encode("utf-8")).hexdigest()[:20]
    return data_dir("cache", "mobile-spell-details") / f"{digest}.json"


def load_mobile_spell_detail(name):
    """Load one cached Wiki description, fetching only on an explicit tap."""
    cache_path = _mobile_spell_detail_path(name)
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("description") or cached.get("effects"):
            return cached
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    request = Request(
        P99_SPELL_DETAIL_API.format(
            slug=quote(str(name).strip().replace(" ", "_"), safe="")),
        headers={"User-Agent": "Vantage/1.44.47"})
    with urlopen(request, timeout=8) as response:
        payload_bytes = response.read(2_000_001)
    if len(payload_bytes) > 2_000_000:
        raise ValueError("Wiki response is larger than the safe limit")
    payload = json.loads(payload_bytes.decode("utf-8"))
    parsed = payload.get("parse")
    if not isinstance(parsed, dict):
        raise ValueError("Project 1999 Wiki does not have this spell page")
    wikitext = parsed.get("wikitext", {})
    if isinstance(wikitext, dict):
        wikitext = wikitext.get("*", "")
    detail = parse_mobile_spell_detail(wikitext)
    if not detail["description"] and not detail["effects"]:
        raise ValueError("No spell description was found")
    try:
        cache_path.write_text(
            json.dumps(detail, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return detail


def _mobile_market_identity(market):
    """Return a safe, internally consistent PC-selected market identity."""
    server = str(market.get("server") or "Green").strip().title()
    if server not in ("Green", "Blue"):
        server = "Green"
    return server, str(
        market.get("source") or f"PigParse API · {server}")


_MOBILE_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta id="viewport" name="viewport" content="width=device-width,initial-scale=1,maximum-scale=5,user-scalable=yes">
<meta name="referrer" content="no-referrer">
<title>Vantage · P99 Companion</title>
<style>
:root{color-scheme:dark;--void:#090b0e;--surface:#11161b;--raised:#171d23;--line:#343c43;--line2:#525b62;--text:#eeeae2;--muted:#aba79e;--accent:#d0b675;--gold:#9d8050;--ok:#51c79b;--warn:#e0ad54;--bad:#f06e78}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -30%,#1b2427 0,#090b0e 45%);color:var(--text);font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;min-height:100vh}
button,input,select{font:inherit}.skip-link{position:fixed;top:7px;left:8px;z-index:20;padding:9px 12px;background:var(--raised);color:var(--text);border:2px solid var(--accent);border-radius:8px;transform:translateY(-150%)}.skip-link:focus-visible{transform:translateY(0)}
.sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
header{position:sticky;top:0;z-index:5;background:rgba(9,11,14,.96);border-bottom:1px solid var(--line);backdrop-filter:blur(12px)}.head{padding:9px 13px 6px}.brand-row{display:flex;align-items:center;gap:8px}.brand{display:flex;align-items:center;gap:8px;margin:0;font-size:14px;font-weight:850;letter-spacing:.13em}.mark{display:grid;place-items:center;width:20px;height:20px;border:1px solid #806a42;border-radius:6px;background:linear-gradient(145deg,#272d2d,#101418);color:var(--accent);font:900 13px Georgia}.sub{color:var(--muted);font-size:10px;margin-top:2px}
.tabs{display:flex;gap:2px;padding:0 8px;overflow-x:auto;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}.tabs button{flex:1 0 auto;min-width:72px;background:none;color:var(--muted);border:0;border-bottom:2px solid transparent;padding:7px 8px;font-size:10px;font-weight:800;letter-spacing:.04em}.tabs button.on{color:var(--accent);border-bottom-color:var(--gold)}
.wrap{max-width:760px;margin:auto;padding:9px;scroll-margin-top:92px}.page[hidden]{display:none}.panel-title{margin:1px 2px 8px;font-size:15px;letter-spacing:.04em}.section-tools{display:flex;align-items:end;gap:7px;flex-wrap:wrap;margin-bottom:8px}.section-tools .field{flex:1 1 180px}
.timer-list,.card-list{list-style:none;margin:0;padding:0}.timer,.card{background:linear-gradient(110deg,rgba(28,34,40,.95),rgba(15,19,23,.95));border:1px solid var(--line);border-radius:9px;margin:6px 0;box-shadow:inset 0 1px rgba(255,255,255,.025)}.timer{padding:9px 10px}.card-button{display:block;width:100%;padding:9px 10px;text-align:left;color:inherit;background:none;border:0;border-radius:8px;cursor:pointer}.card-button:hover{background:rgba(208,182,117,.05)}
.top{display:flex;align-items:flex-start;gap:7px;flex-wrap:wrap}.name{min-width:0;flex:1 1 170px;margin:0;overflow-wrap:anywhere;font-size:13px;font-weight:760;letter-spacing:.025em}.phase,.source,.quality,.chip{font-size:9px;font-weight:800;border:1px solid #4b535a;border-radius:6px;padding:2px 6px;color:var(--muted);flex:none}.phase.respawn{color:#e4d8ba;border-color:#6b5a3c;background:#282218}.phase.combat{color:#ffd17a;border-color:#85662f;background:#33260f}.phase.available{color:#a4f2ce;border-color:#397d62;background:#123026}.source{color:#e8d5a2;border-color:#73613f}.quality.High{color:var(--ok)}.quality.Medium{color:var(--warn)}.quality.Low{color:var(--bad)}
.time,.price{font:800 17px/1 ui-monospace,"Cascadia Mono",Consolas,monospace;flex:none}.price{color:var(--accent)}.track{height:8px;background:#191d21;border:1px solid #343940;border-radius:5px;margin:8px 0 6px;overflow:hidden}.fill{height:100%;background:var(--timer-color,#a88b57);transition:width .25s linear}.meta{color:var(--muted);font-size:10px;margin:5px 0 0}.timer-actions{display:flex;gap:5px;margin-top:7px}.timer-actions button,.tool-button,.dialog-close{min-height:34px;border:1px solid var(--line2);border-radius:7px;background:linear-gradient(#252b31,#171c21);color:var(--text);padding:6px 10px;font-size:11px;font-weight:750}.timer-actions button{flex:1}.timer-actions button:hover,.tool-button:hover{border-color:var(--accent)}button:disabled{opacity:.5}
.filters{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin:3px 0 9px}.field{min-width:0}.field-wide{grid-column:1/-1}.field label{display:block;color:var(--muted);font-size:10px;font-weight:700;margin:0 0 3px 2px}.filters input,.filters select,.section-tools select{width:100%;background:#101419;color:var(--text);border:1px solid #596169;border-radius:7px;padding:8px 7px;font-size:12px}.market-note{color:var(--muted);font-size:10px;margin:7px 2px}.empty{text-align:center;color:var(--muted);padding:48px 18px;border:1px dashed var(--line);border-radius:9px;margin-top:10px}.summary{color:#d9d3c7;font-size:11px;margin:6px 0 0}.stat-line{color:var(--accent);font:700 10px/1.5 ui-monospace,"Cascadia Mono",monospace;margin-top:5px}
.game-tools{display:flex;gap:6px;margin:0 0 7px}.game-tools button{flex:1}.game-shell{background:#050607;border:1px solid var(--line);border-radius:9px;overflow:hidden;min-height:220px;display:grid;place-items:center}.game-shell img{display:block;width:100%;height:auto;background:#000;image-rendering:auto}.game-shell.native{display:block;overflow:auto;max-height:76vh}.game-shell.native img{width:auto;max-width:none}.game-shell.zoom-locked{touch-action:pan-x pan-y;overscroll-behavior:contain}.game-state{margin:7px 2px;color:var(--muted);font-size:11px}.game-badge{display:inline-block;margin-left:5px;padding:2px 5px;border:1px solid #397d62;border-radius:5px;color:var(--ok);font-size:8px;font-weight:800}.game-help{padding:48px 18px;text-align:center;color:var(--muted);max-width:440px}.wifi-note{color:var(--warn);font-size:10px;margin:7px 2px}
dialog{width:min(92vw,620px);max-height:84vh;overflow:auto;border:1px solid #6e6248;border-radius:12px;background:#11161b;color:var(--text);padding:0;box-shadow:0 20px 70px #000}dialog::backdrop{background:rgba(0,0,0,.72);backdrop-filter:blur(3px)}.dialog-head{position:sticky;top:0;display:flex;align-items:center;gap:8px;padding:10px 12px;background:rgba(17,22,27,.97);border-bottom:1px solid var(--line)}.dialog-head h2{flex:1;margin:0;font-size:15px;color:var(--accent)}.dialog-body{padding:12px}.detail-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;margin:8px 0}.detail-cell{padding:6px;border:1px solid var(--line);border-radius:6px;background:#0d1115}.detail-cell b{display:block;color:var(--muted);font-size:9px}.detail-section{margin:12px 0 4px;color:var(--accent);font-size:11px;letter-spacing:.07em}.effect{padding:6px 0;border-bottom:1px solid var(--line)}.source-link{display:inline-block;color:var(--accent);margin-top:10px}
#state{color:var(--muted);font-size:9px;margin-left:auto;flex:none}.offline{color:var(--bad)!important}:where(a,button,input,select,[tabindex]):focus-visible{outline:3px solid var(--accent);outline-offset:2px;box-shadow:0 0 0 1px var(--void)}
@media(max-width:430px){.head{padding:8px 9px 5px}.wrap{padding:5px}.timer,.card-button{padding:8px}.time,.price{font-size:15px}.name{font-size:12px}.filters{grid-template-columns:1fr}.field-wide{grid-column:auto}.detail-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
</style>
</head>
<body>
<a id="skipLink" class="skip-link" href="#main-content">Skip to content</a>
<header><div class="head"><div class="brand-row"><h1 class="brand"><span class="mark" aria-hidden="true">V</span><span>VANTAGE<span class="sr-only"> P99 Companion</span></span></h1><span id="state">Connecting…</span></div><div class="sub">P99 companion · personal session</div></div>
<div class="tabs" role="tablist" aria-label="Mobile companion views">
<button id="tabTimers" class="on" type="button" role="tab" aria-selected="true" aria-controls="timers" tabindex="0">TIMERS</button>
<button id="tabMarket" type="button" role="tab" aria-selected="false" aria-controls="marketPage" tabindex="-1">MARKET</button>
<button id="tabSpells" type="button" role="tab" aria-selected="false" aria-controls="spellsPage" tabindex="-1">SPELLS</button>
<button id="tabGame" type="button" role="tab" aria-selected="false" aria-controls="gamePage" tabindex="-1">EQ LIVE</button>
</div></header>
<div id="connectionStatus" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div><div id="connectionAlert" class="sr-only" role="alert" aria-atomic="true"></div><div id="timerStatus" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>
<main id="main-content" class="wrap" tabindex="-1">
<section id="timers" class="page" role="tabpanel" aria-labelledby="tabTimers" tabindex="0"><h2 class="panel-title">Spawn timers</h2><div class="section-tools"><div class="field"><label for="timerZone">Zone shown on PC and phone</label><select id="timerZone"><option value="">All zones</option></select></div></div><p id="timerEmpty" class="empty" hidden>No saved timers in this zone.</p><ul id="timerRows" class="timer-list" aria-label="Configured timers" aria-busy="false"></ul></section>
<section id="marketPage" class="page" role="tabpanel" aria-labelledby="tabMarket" tabindex="0" hidden><h2 id="marketHeading" class="panel-title">PIGPARSE MARKET · ITEM STATS</h2><search aria-label="Search market and item stats"><form id="marketFilters" class="filters">
<div class="field field-wide"><label for="mq">Item or effect</label><input id="mq" name="q" type="search" placeholder="Search item, click, proc or worn effect…" autocomplete="off"></div>
<div class="field"><label for="mc">Class</label><select id="mc"><option value="0">Any class</option><option value="1">Warrior</option><option value="2">Cleric</option><option value="4">Paladin</option><option value="8">Ranger</option><option value="16">Shadow Knight</option><option value="32">Druid</option><option value="64">Monk</option><option value="128">Bard</option><option value="256">Rogue</option><option value="512">Shaman</option><option value="1024">Necromancer</option><option value="2048">Wizard</option><option value="4096">Magician</option><option value="8192">Enchanter</option></select></div>
<div class="field"><label for="mr">Race</label><select id="mr"><option value="0">Any race</option><option value="1">Human</option><option value="2">Barbarian</option><option value="4">Erudite</option><option value="8">Wood Elf</option><option value="16">High Elf</option><option value="32">Dark Elf</option><option value="64">Half Elf</option><option value="128">Dwarf</option><option value="256">Troll</option><option value="512">Ogre</option><option value="1024">Halfling</option><option value="2048">Gnome</option><option value="4096">Iksar</option></select></div>
<div class="field"><label for="ms">Slot</label><select id="ms"><option value="0">Any slot</option><option value="1">Charm</option><option value="18">Ear</option><option value="4">Head</option><option value="8">Face</option><option value="32">Neck</option><option value="64">Shoulders</option><option value="128">Arms</option><option value="256">Back</option><option value="1536">Wrist</option><option value="2048">Range</option><option value="4096">Hands</option><option value="8192">Primary</option><option value="16384">Secondary</option><option value="98304">Finger</option><option value="131072">Chest</option><option value="262144">Legs</option><option value="524288">Feet</option><option value="1048576">Waist</option><option value="2097152">Ammo</option></select></div>
<div class="field"><label for="me">Effect</label><select id="me"><option value="">Any effect</option><option value="click">Click</option><option value="proc">Proc</option><option value="worn">Worn</option><option value="focus">Focus</option><option value="bard">Bard</option></select></div>
<div class="field"><label for="md">Tradeability</label><select id="md"><option value="">Droppable + NO DROP</option><option value="drop">Droppable</option><option value="nodrop">NO DROP</option></select></div>
<div class="field"><label for="mera">Era</label><select id="mera"><option value="">Any era</option><option value="classic">Classic</option><option value="kunark">Kunark</option><option value="velious">Velious</option></select></div>
<div class="field"><label for="mso">Sort</label><select id="mso"><option value="posts">Most market data</option><option value="price">Highest price</option><option value="ac">Best AC</option><option value="hp">Best HP</option><option value="mana">Best Mana</option><option value="astr">Best STR</option><option value="asta">Best STA</option><option value="adex">Best DEX</option><option value="aagi">Best AGI</option><option value="aint">Best INT</option><option value="awis">Best WIS</option><option value="acha">Best CHA</option><option value="mr">Best MR</option><option value="haste">Best Haste</option></select></div>
</form></search><div class="market-note" id="marketNote">PigParse prices · P99 item stats and effects</div><div id="marketStatus" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div><ul id="marketRows" class="card-list" aria-labelledby="marketHeading" aria-busy="false"></ul></section>
<section id="spellsPage" class="page" role="tabpanel" aria-labelledby="tabSpells" tabindex="0" hidden><h2 id="spellsHeading" class="panel-title">P99 SPELL LIBRARY</h2><search aria-label="Search P99 spells"><form id="spellFilters" class="filters"><div class="field field-wide"><label for="sq">Spell</label><input id="sq" type="search" placeholder="Search spell…" autocomplete="off"></div><div class="field"><label for="sc">Class</label><select id="sc"><option value="">Any class</option><option>Bard</option><option>Cleric</option><option>Druid</option><option>Enchanter</option><option>Magician</option><option>Necromancer</option><option>Paladin</option><option>Ranger</option><option>Shadow Knight</option><option>Shaman</option><option>Wizard</option></select></div><div class="field"><label for="sl">Level</label><select id="sl"><option value="0">Any level</option></select></div></form></search><div class="market-note" id="spellNote">Bundled classic spell index · levels 1–60</div><div id="spellStatus" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div><ul id="spellRows" class="card-list" aria-labelledby="spellsHeading" aria-busy="false"></ul></section>
<section id="gamePage" class="page" role="tabpanel" aria-labelledby="tabGame" tabindex="0" hidden><h2 class="panel-title">EVERQUEST LIVE <span class="game-badge">READ ONLY</span></h2><p id="gameState" class="game-state" role="status" aria-live="polite">Waiting for the local view…</p><div class="game-tools"><button id="gameSize" class="tool-button" type="button" title="Switch between screen fit and exact image pixels">FIT TO SCREEN</button><button id="zoomLock" class="tool-button" type="button" aria-pressed="true" title="Prevent accidental pinch zoom while viewing EverQuest">ZOOM LOCKED</button></div><div id="gameShell" class="game-shell zoom-locked"><p id="gameHelp" class="game-help">Enable “EverQuest Live” in Vantage and keep your phone on the same Wi-Fi network.</p><img id="gameFrame" alt="Live read-only view of the EverQuest window" hidden></div><p class="wifi-note">Privacy: the live image works only on your local Wi-Fi. It cannot control EverQuest.</p></section>
</main>
<dialog id="detailDialog" aria-labelledby="detailTitle"><div class="dialog-head"><h2 id="detailTitle">Details</h2><button id="detailClose" class="dialog-close" type="button" aria-label="Close details">Close</button></div><div id="detailBody" class="dialog-body"></div></dialog>
<script>
const token=location.hash.slice(1),byId=id=>document.getElementById(id);
const mainContent=byId('main-content'),skipLink=byId('skipLink'),timersPanel=byId('timers'),timersRoot=byId('timerRows'),timerEmpty=byId('timerEmpty'),timerStatus=byId('timerStatus'),timerZone=byId('timerZone');
const marketPanel=byId('marketPage'),marketHeading=byId('marketHeading'),marketRoot=byId('marketRows'),marketNote=byId('marketNote'),marketStatus=byId('marketStatus'),spellsPanel=byId('spellsPage'),spellRoot=byId('spellRows'),spellNote=byId('spellNote'),spellStatus=byId('spellStatus');
const gamePanel=byId('gamePage'),gameState=byId('gameState'),gameHelp=byId('gameHelp'),gameFrame=byId('gameFrame'),gameShell=byId('gameShell'),gameSize=byId('gameSize'),zoomLock=byId('zoomLock');
const state=byId('state'),connectionStatus=byId('connectionStatus'),connectionAlert=byId('connectionAlert'),detailDialog=byId('detailDialog'),detailTitle=byId('detailTitle'),detailBody=byId('detailBody');
const tabTimers=byId('tabTimers'),tabMarket=byId('tabMarket'),tabSpells=byId('tabSpells'),tabGame=byId('tabGame'),tabs=[tabTimers,tabMarket,tabSpells,tabGame];
const phases={idle:'READY',respawn:'RESPAWN',combat:'COMBAT',available:'AVAILABLE'},statLabels={ac:'AC',hp:'HP',mana:'Mana',astr:'STR',asta:'STA',adex:'DEX',aagi:'AGI',aint:'INT',awis:'WIS',acha:'CHA',mr:'MR',fr:'FR',cr:'CR',dr:'DR',pr:'PR',attack:'ATK',haste:'Haste',regen:'Regen',manaregen:'Mana regen'};
let timerUid=0,lastConnection='',polling=false,marketDelay,marketRequest=0,spellDelay,spellRequest=0,gameLoading=false,gameObjectUrl='',gameDelay,timerListWasEmpty=null,syncingZone=false;let timerStates=new Map();
function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}function announce(root,text){if(root.textContent!==text)root.textContent=text}
async function get(path){const r=await fetch(path,{cache:'no-store',headers:{Authorization:'Bearer '+token}});if(!r.ok)throw Error(String(r.status));return r.json()}
async function post(path,data){const r=await fetch(path,{method:'POST',cache:'no-store',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(data)});if(!r.ok)throw Error(String(r.status));return r.json()}
function saved(key,fallback){try{const value=localStorage.getItem(key);return value===null?fallback:value==='true'}catch(_){return fallback}}function save(key,value){try{localStorage.setItem(key,String(value))}catch(_){}}
let zoomLocked=saved('vantageZoomLock',true),nativeSize=saved('vantageNativeSize',false);function applyGameView(){gameShell.classList.toggle('zoom-locked',zoomLocked);gameShell.classList.toggle('native',nativeSize);zoomLock.textContent=zoomLocked?'EQ VIEW LOCKED':'EQ VIEW FREE';zoomLock.setAttribute('aria-pressed',String(zoomLocked));zoomLock.setAttribute('aria-label',zoomLocked?'Unlock pinch gestures inside the EverQuest live image':'Lock pinch gestures inside the EverQuest live image');gameSize.textContent=nativeSize?'1:1 PIXELS':'FIT TO SCREEN'}applyGameView();
zoomLock.addEventListener('click',()=>{zoomLocked=!zoomLocked;save('vantageZoomLock',zoomLocked);applyGameView()});gameSize.addEventListener('click',()=>{nativeSize=!nativeSize;save('vantageNativeSize',nativeSize);applyGameView()});gameShell.addEventListener('touchmove',event=>{if(zoomLocked&&event.touches.length>1)event.preventDefault()},{passive:false});for(const eventName of ['gesturestart','gesturechange','gestureend'])gameShell.addEventListener(eventName,event=>{if(zoomLocked)event.preventDefault()},{passive:false});
async function loadGame(){clearTimeout(gameDelay);if(gamePanel.hidden||document.hidden)return;if(gameLoading){gameDelay=setTimeout(loadGame,180);return}gameLoading=true;let delay=500;try{const status=await get('/api/game/status');delay=Math.max(100,Math.round(1000/(Number(status.fps)||5)));announce(gameState,(status.title?status.title+' · ':'')+String(status.message||'')+(status.image_quality_label?' · '+status.image_quality_label:''));if(!status.enabled||!status.available){gameFrame.hidden=true;gameHelp.hidden=false;gameHelp.textContent=String(status.message||'View unavailable.');return}const response=await fetch('/api/game/frame',{cache:'no-store',headers:{Authorization:'Bearer '+token}});if(!response.ok){let failure={};try{failure=await response.json()}catch(_){}const message=String(failure.message||(response.status===403?'EverQuest Live is available only through the local Wi-Fi link.':'The EverQuest window could not be captured.'));gameFrame.hidden=true;gameHelp.hidden=false;gameHelp.textContent=message;announce(gameState,(failure.title?String(failure.title)+' · ':'')+message);delay=1000;return}const blob=await response.blob(),next=URL.createObjectURL(blob),old=gameObjectUrl;gameObjectUrl=next;gameFrame.onload=()=>{if(old)URL.revokeObjectURL(old)};gameFrame.src=next;gameFrame.hidden=false;gameHelp.hidden=true}catch(_){gameFrame.hidden=true;gameHelp.hidden=false;gameHelp.textContent='Local connection to Vantage was lost. Retrying…';announce(gameState,gameHelp.textContent);delay=1000}finally{gameLoading=false;if(!gamePanel.hidden&&!document.hidden)gameDelay=setTimeout(loadGame,delay)}}
function setConnection(text,offline=false,urgent=''){if(text===lastConnection)return;lastConnection=text;state.textContent=text;state.classList.toggle('offline',offline);if(urgent){connectionStatus.textContent='';announce(connectionAlert,urgent)}else{connectionAlert.textContent='';announce(connectionStatus,text)}}
function actionButton(label,action,title){const button=node('button','',label);button.type='button';button.dataset.action=action;button.title=title;button.setAttribute('aria-label',title);return button}
function createTimerRow(key){const row=node('li','timer');row.dataset.key=key;const top=node('div','top'),name=node('h3','name'),phase=node('span','phase idle'),time=node('span','time');name.id='timer-name-'+(++timerUid);time.setAttribute('role','timer');top.append(name,phase,time);row.append(top);const track=node('div','track'),fill=node('div','fill');track.setAttribute('role','progressbar');track.setAttribute('aria-valuemin','0');track.setAttribute('aria-valuemax','100');track.setAttribute('aria-labelledby',name.id);fill.setAttribute('aria-hidden','true');track.append(fill);row.append(track);const meta=node('p','meta');row.append(meta);const actions=node('div','timer-actions'),toggle=actionButton('Pause','toggle','Pause or resume this timer'),restart=actionButton('Restart','restart','Restart this timer from the beginning'),clear=actionButton('Stop','clear','Stop and clear this countdown to READY');actions.append(toggle,restart,clear);row.append(actions);for(const button of actions.children)button.addEventListener('click',()=>runTimerAction(row,button.dataset.action));row._parts={name,phase,time,track,fill,meta,actions,toggle};return row}
async function runTimerAction(row,action){for(const button of row._parts.actions.children)button.disabled=true;try{await post('/api/timers/action',{action,target:row.dataset.key});announce(timerStatus,row._parts.name.textContent+' action sent to Vantage.');setTimeout(poll,160);setTimeout(poll,700)}catch(error){announce(timerStatus,String(error.message)==='403'?'Timer controls require the local Wi-Fi QR link.':'Timer action failed.')}finally{setTimeout(()=>{for(const button of row._parts.actions.children)button.disabled=false},450)}}
function updateTimerRow(row,t){const p=row._parts,name=String(t.name||'Spawn'),remaining=String(t.remaining||'--:--'),pn=['idle','respawn','combat','available'].includes(t.phase)?t.phase:'idle',progress=Math.max(0,Math.min(100,Number(t.progress)||0));row.style.setProperty('--timer-color',/^#[0-9a-f]{6}$/i.test(t.color)?t.color:'#a88b57');p.name.textContent=name;p.phase.className='phase '+pn;p.phase.textContent=t.running===false&&pn!=='idle'?'PAUSED':phases[pn];p.time.textContent=remaining;p.track.setAttribute('aria-valuenow',String(progress));p.track.setAttribute('aria-valuetext',progress+'% · '+remaining+' remaining');p.fill.style.width=progress+'%';const toggleAction=t.running?'Pause':pn==='idle'?'Start':'Resume';p.toggle.textContent=toggleAction;p.toggle.setAttribute('aria-label',toggleAction+' '+name+' timer');p.actions.children[1].setAttribute('aria-label','Restart '+name+' timer from the beginning');p.actions.children[2].setAttribute('aria-label','Stop and clear '+name+' timer');const bits=[];if(t.zone)bits.push('ZONE · '+String(t.zone));bits.push(t.smart?'AUTO':'MANUAL','kill '+String(t.kill||'--:--'),'cycle '+String(Number(t.cycles)||0));p.meta.textContent=bits.join(' · ')}
function syncTimerZone(data){const zones=Array.isArray(data.timer_zones)?data.timer_zones:[''],selected=String(data.timer_zone||'');syncingZone=true;const current=Array.from(timerZone.options).map(option=>option.value);if(JSON.stringify(current)!==JSON.stringify(zones)){timerZone.replaceChildren(...zones.map(zone=>{const option=node('option','',zone||'All zones');option.value=zone;return option}))}timerZone.value=selected;syncingZone=false}
function drawTimers(data){syncTimerZone(data);const rows=Array.isArray(data.timers)?data.timers:[],existing=new Map(Array.from(timersRoot.children).map(row=>[row.dataset.key,row])),used=new Set(),nextStates=new Map(),milestones=[];let anchor=timersRoot.firstElementChild;for(const t of rows){const key=String(t.timer_id||[t.name,t.zone,t.kill].join('\u241f'));let row=existing.get(key);if(!row)row=createTimerRow(key);used.add(key);updateTimerRow(row,t);const name=String(t.name||'Spawn'),phase=['idle','respawn','combat','available'].includes(t.phase)?t.phase:'idle',running=t.running!==false,previous=timerStates.get(key);if(previous){if(previous.running!==running)milestones.push(name+(running?' resumed.':' paused.'));if(previous.phase!==phase)milestones.push(name+': '+phases[phase].toLowerCase()+'.')}nextStates.set(key,{phase,running});if(row!==anchor)timersRoot.insertBefore(row,anchor);anchor=row.nextElementSibling}for(const row of Array.from(timersRoot.children))if(!used.has(row.dataset.key))row.remove();const empty=rows.length===0;if(timerListWasEmpty!==null&&timerListWasEmpty!==empty)milestones.push(empty?'No timers in this zone.':rows.length+' timer'+(rows.length===1?' is':'s are')+' visible.');if(milestones.length)announce(timerStatus,milestones.slice(0,3).join(' '));timerStates=nextStates;timerListWasEmpty=empty;timerEmpty.hidden=!empty;timersRoot.hidden=empty}
timerZone.addEventListener('change',async()=>{if(syncingZone)return;timerZone.disabled=true;try{await post('/api/timers/action',{action:'zone',target:timerZone.value});setTimeout(poll,120)}catch(error){announce(timerStatus,String(error.message)==='403'?'Zone sync requires the local Wi-Fi QR link.':'Zone could not be changed.')}finally{setTimeout(()=>timerZone.disabled=false,350)}});
function statSummary(item){const stats=item.stats||{},values=Object.entries(stats).slice(0,7).map(([key,value])=>(statLabels[key]||key.toUpperCase())+' '+(Number(value)>0?'+':'')+String(value));return values.join(' · ')}
function openMarketDetail(item){detailTitle.textContent=String(item.name||'Item');detailBody.replaceChildren();const top=node('div','top');top.append(node('span','source','PIGPARSE PRICE REFERENCE'),node('span','chip',item.nodrop?'NO DROP':'DROPPABLE'),node('span','chip',item.era?String(item.era).toUpperCase():'ERA UNKNOWN'));detailBody.append(top,node('p','price',item.price?Number(item.price).toLocaleString()+' pp':'No current price'),node('p','meta',String(Number(item.posts)||0)+' price observations in 30 days'));const stats=item.stats||{},keys=Object.keys(stats);if(keys.length){detailBody.append(node('h3','detail-section','ITEM STATS'));const grid=node('div','detail-grid');for(const key of keys){const cell=node('div','detail-cell');cell.append(node('b','',statLabels[key]||key.toUpperCase()),node('span','',((Number(stats[key])>0)?'+':'')+String(stats[key])));grid.append(cell)}detailBody.append(grid)}const effects=Array.isArray(item.effects)?item.effects:[];if(effects.length){detailBody.append(node('h3','detail-section','CLICK / PROC / WORN EFFECTS'));for(const effect of effects)detailBody.append(node('div','effect',String(effect.type||'Effect')+' · '+String(effect.name||'')))}const link=node('a','source-link','Open Project 1999 Wiki source');link.setAttribute('aria-label','Open Project 1999 Wiki source in a new tab');link.href=String(item.wiki_url||'#');link.target='_blank';link.rel='noreferrer noopener';detailBody.append(link);detailDialog.showModal()}
function createMarketRow(key){const row=node('li','card');row.dataset.key=key;const button=node('button','card-button');button.type='button';const top=node('div','top'),name=node('h3','name'),source=node('span','source','PIGPARSE');top.append(name,source);const priceLine=node('div','top'),price=node('span','price'),quality=node('span','quality');priceLine.append(price,quality);const meta=node('p','meta'),summary=node('p','stat-line');button.append(top,priceLine,meta,summary);button.addEventListener('click',()=>openMarketDetail(button._item));row.append(button);row._parts={button,name,price,quality,meta,summary};return row}
function updateMarketRow(row,item){const p=row._parts,quality=String(item.quality||'Low'),summary=statSummary(item);p.button._item=item;p.name.textContent=String(item.name||'Item');p.price.textContent=item.price?Number(item.price).toLocaleString()+' pp':'—';p.quality.className='quality '+quality;p.quality.textContent=quality;p.meta.textContent=String(Number(item.posts)||0)+' price observations · '+(item.nodrop?'NO DROP':'Droppable')+(item.era?' · '+String(item.era).toUpperCase():'');p.summary.textContent=summary;p.summary.hidden=!summary}
function showListMessage(root,text){root.replaceChildren(node('li','empty',text))}
function reconcileMarketRows(items){const existing=new Map(Array.from(marketRoot.children).map(row=>[row.dataset.key,row])),used=new Set();let anchor=marketRoot.firstElementChild;for(const item of items){const key='item:'+String(item.id??item.name);let row=existing.get(key);if(!row||!row._parts)row=createMarketRow(key);updateMarketRow(row,item);used.add(key);if(row!==anchor)marketRoot.insertBefore(row,anchor);anchor=row.nextElementSibling}for(const row of Array.from(marketRoot.children))if(!used.has(row.dataset.key))row.remove()}
function drawMarket(data){const rows=Array.isArray(data.items)?data.items:[],total=Number(data.total)||0,server=String(data.server||'Green');marketHeading.textContent='PIGPARSE '+server.toUpperCase()+' · ITEM STATS';marketNote.textContent=(data.source||('PigParse API · '+server))+' · '+String(total)+' matches · tap an item for full stats';if(!rows.length){showListMessage(marketRoot,'No items match these filters.');return}reconcileMarketRows(rows)}
async function poll(){if(polling)return;if(!token){setConnection('INVALID QR',true,'Invalid QR code. Open a new link from Vantage.');return}polling=true;timersRoot.setAttribute('aria-busy','true');try{drawTimers(await get('/api/state'));setConnection('LIVE',false,'')}catch(_){setConnection('OFFLINE',true,'Connection lost. Timers may be out of date.')}finally{timersRoot.setAttribute('aria-busy','false');polling=false}}
function params(ids){const p=new URLSearchParams();for(const [key,id] of Object.entries(ids))p.set(key,byId(id).value);return p}
async function loadMarket(announceLoading=true){const request=++marketRequest,p=params({q:'mq',class:'mc',race:'mr',slot:'ms',effect:'me',drop:'md',era:'mera',sort:'mso'});marketRoot.setAttribute('aria-busy','true');if(announceLoading)announce(marketStatus,'Loading market and item stats.');try{const data=await get('/api/market?'+p);if(request!==marketRequest)return;drawMarket(data);announce(marketStatus,(Number(data.total)||0)+' matches')}catch(_){if(request!==marketRequest)return;showListMessage(marketRoot,'Market data could not be loaded.');announce(marketStatus,'Market data could not be loaded.')}finally{if(request===marketRequest)marketRoot.setAttribute('aria-busy','false')}}
function marketChanged(){clearTimeout(marketDelay);marketDelay=setTimeout(()=>loadMarket(true),220)}for(const id of ['mq','mc','mr','ms','me','md','mera','mso'])byId(id).addEventListener(id==='mq'?'input':'change',marketChanged);byId('marketFilters').addEventListener('submit',event=>{event.preventDefault();clearTimeout(marketDelay);loadMarket(true)});
async function openSpellDetail(spell){detailTitle.textContent=String(spell.name||'Spell');detailBody.replaceChildren();const top=node('div','top');top.append(node('span','source','P99 CLASSIC DATA'),node('span','chip','SPELL ID '+String(spell.spell_id||'—')));const effectBox=node('div','');effectBox.append(node('h3','detail-section','WHAT IT DOES'),node('p','summary',String(spell.effect_hint||'Loading the exact Project 1999 Wiki description…')));detailBody.append(top,effectBox,node('h3','detail-section','CLASSES AND LEVELS'));for(const profile of spell.class_levels||[])detailBody.append(node('div','effect',String(profile[0])+' · Level '+String(profile[1])));if(spell.price)detailBody.append(node('h3','detail-section','PIGPARSE GREEN PRICE'),node('p','price',Number(spell.price).toLocaleString()+' pp'),node('p','meta',String(Number(spell.posts)||0)+' price observations in 30 days · '+String(spell.quality||'Low')+' confidence'));const link=node('a','source-link','Open complete Project 1999 Wiki spell page');link.setAttribute('aria-label','Open complete Project 1999 Wiki spell page in a new tab');link.href=String(spell.wiki_url||'#');link.target='_blank';link.rel='noreferrer noopener';detailBody.append(link);detailDialog.showModal();try{const detail=await get('/api/spell-detail?name='+encodeURIComponent(String(spell.name||'')));effectBox.replaceChildren(node('h3','detail-section','WHAT IT DOES'));effectBox.append(node('p','summary',String(detail.description||spell.effect_hint||'No description available.')));for(const effect of detail.effects||[])effectBox.append(node('div','effect',String(effect)));effectBox.append(node('p','meta','Source · '+String(detail.source||'Project 1999 Wiki')))}catch(_){effectBox.append(node('p','meta','Exact Wiki description is unavailable; showing bundled spell text.'))}}
function drawSpells(data){const items=Array.isArray(data.items)?data.items:[];spellNote.textContent=String(Number(data.total)||0)+' matches · local class/level index · tap for exact effects';if(!items.length){showListMessage(spellRoot,'No spells match these filters.');return}spellRoot.replaceChildren(...items.map(spell=>{const row=node('li','card'),button=node('button','card-button');button.type='button';const top=node('div','top'),name=node('h3','name',String(spell.name)),level=node('span','chip',String(spell.selected_class||'ALL')+' '+String(spell.selected_level||''));top.append(name,level);button.append(top,node('p','summary',String(spell.effect_hint||(spell.class_levels||[]).map(profile=>profile[0]+' '+profile[1]).join(' · '))));if(spell.price)button.append(node('p','stat-line','PigParse · '+Number(spell.price).toLocaleString()+' pp'));button.addEventListener('click',()=>openSpellDetail(spell));row.append(button);return row}))}
function syncSpellLevels(levels){const select=byId('sl'),current=select.value,available=(Array.isArray(levels)?levels:[]).map(Number).filter(level=>level>=1&&level<=60);select.replaceChildren();const any=node('option','','Any level');any.value='0';select.append(any,...available.map(level=>{const option=node('option','',`Level ${level}`);option.value=String(level);return option}));select.value=available.includes(Number(current))?current:'0'}
async function loadSpells(announceLoading=true){const request=++spellRequest,p=params({q:'sq',class:'sc',level:'sl'});spellRoot.setAttribute('aria-busy','true');if(announceLoading)announce(spellStatus,'Loading spells.');try{const data=await get('/api/spells?'+p);if(request!==spellRequest)return;syncSpellLevels(data.available_levels);drawSpells(data);announce(spellStatus,(Number(data.total)||0)+' spell matches')}catch(_){if(request!==spellRequest)return;showListMessage(spellRoot,'Spell library could not be loaded.');announce(spellStatus,'Spell library could not be loaded.')}finally{if(request===spellRequest)spellRoot.setAttribute('aria-busy','false')}}
function spellChanged(){clearTimeout(spellDelay);spellDelay=setTimeout(()=>loadSpells(true),180)}for(const id of ['sq','sc','sl'])byId(id).addEventListener(id==='sq'?'input':'change',()=>{if(id==='sc')byId('sl').value='0';spellChanged()});byId('spellFilters').addEventListener('submit',event=>{event.preventDefault();clearTimeout(spellDelay);loadSpells(true)});
function selectTab(selected,focus=false){const market=selected===tabMarket,spells=selected===tabSpells,game=selected===tabGame;for(const tab of tabs){const active=tab===selected;tab.classList.toggle('on',active);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1}marketPanel.hidden=!market;spellsPanel.hidden=!spells;gamePanel.hidden=!game;timersPanel.hidden=market||spells||game;if(focus)selected.focus();if(market)loadMarket(true);if(spells)loadSpells(true);if(game)loadGame();else clearTimeout(gameDelay)}
for(const tab of tabs){tab.addEventListener('click',()=>selectTab(tab));tab.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=tabs[(tabs.indexOf(tab)+1)%tabs.length];else if(event.key==='ArrowLeft')next=tabs[(tabs.indexOf(tab)-1+tabs.length)%tabs.length];else if(event.key==='Home')next=tabs[0];else if(event.key==='End')next=tabs[tabs.length-1];else return;event.preventDefault();selectTab(next,true)})}
byId('detailClose').addEventListener('click',()=>detailDialog.close());detailDialog.addEventListener('click',event=>{if(event.target===detailDialog)detailDialog.close()});skipLink.addEventListener('click',event=>{event.preventDefault();mainContent.focus({preventScroll:true});mainContent.scrollIntoView({block:'start',behavior:'auto'})});document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!gamePanel.hidden)loadGame();else clearTimeout(gameDelay)});
poll();setInterval(poll,2000);setInterval(()=>{if(!marketPanel.hidden)loadMarket(false)},10000);
</script>
</body>
</html>"""


class _ShareHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
            self, address, token, snapshot_provider, game_capture=None,
            lan_token=None, timer_action=None, spells=()):
        super().__init__(address, _ShareHandler)
        self.token = token
        self.lan_token = lan_token or token
        self.snapshot_provider = snapshot_provider
        self.game_capture = game_capture
        self.timer_action = timer_action
        self.spells = tuple(spells)


class _ShareHandler(BaseHTTPRequestHandler):
    server_version = "VantageMobile/1.44.47"

    def log_message(self, *_):
        # Do not write access paths or the user's network details to disk.
        return

    def _send(self, status, payload, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' blob:; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_HEAD(self):
        self.do_GET()

    def _authorized(self, lan_only=False):
        supplied = self.headers.get("Authorization", "")
        tokens = {self.server.lan_token} if lan_only else {
            self.server.token, self.server.lan_token}
        return any(hmac.compare_digest(
            supplied, f"Bearer {token}") for token in tokens)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path != "/api/timers/action":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        if not self._authorized(lan_only=True):
            self._send(403, b'{"error":"wifi_only"}', "application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            length = 0
        if not 0 < length <= 2048:
            self._send(400, b'{"error":"invalid_body"}', "application/json")
            return
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            action = str(request.get("action") or "").strip().casefold()
            target = str(request.get("target") or "").strip()
        except (UnicodeError, TypeError, ValueError, json.JSONDecodeError):
            self._send(400, b'{"error":"invalid_json"}', "application/json")
            return
        if action not in {"toggle", "restart", "clear", "zone"} or (
                action != "zone" and not target):
            self._send(400, b'{"error":"invalid_action"}', "application/json")
            return
        if self.server.timer_action is None:
            self._send(503, b'{"error":"unavailable"}', "application/json")
            return
        self.server.timer_action(action, target)
        self._send(202, b'{"accepted":true}', "application/json")

    def do_GET(self):
        request_url = urlsplit(self.path)
        path = request_url.path
        if path == "/":
            self._send(200, _MOBILE_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        if path.startswith("/api/"):
            if not self._authorized():
                self._send(403, b'{"error":"forbidden"}', "application/json")
                return
        if path.startswith("/api/game/"):
            if not self._authorized(lan_only=True):
                self._send(
                    403, b'{"error":"wifi_only"}',
                    "application/json; charset=utf-8")
                return
            capture = self.server.game_capture
            if capture is None:
                self._send(
                    503, b'{"error":"unavailable"}',
                    "application/json; charset=utf-8")
                return
            if path == "/api/game/status":
                payload = json.dumps(
                    capture.status(), ensure_ascii=False,
                    separators=(",", ":")).encode("utf-8")
                self._send(200, payload, "application/json; charset=utf-8")
                return
            if path == "/api/game/frame":
                status, frame = capture.frame()
                if not frame:
                    payload = json.dumps(
                        status, ensure_ascii=False,
                        separators=(",", ":")).encode("utf-8")
                    self._send(503, payload, "application/json; charset=utf-8")
                    return
                self._send(200, frame, "image/jpeg")
                return
        if path == "/api/state":
            snapshot = self.server.snapshot_provider()
            market = snapshot.get("market", {})
            market_server, market_source = _mobile_market_identity(market)
            state = {
                "version": snapshot.get("version", 1),
                "timers": snapshot.get("timers", []),
                "timer_zone": snapshot.get("timer_zone", ""),
                "timer_zones": snapshot.get("timer_zones", [""]),
                "generated_at": snapshot.get("generated_at"),
                "market": {
                    "server": market_server,
                    "source": market_source,
                    "revision": market.get("revision", 0),
                },
            }
            payload = json.dumps(
                state, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")
            self._send(200, payload, "application/json; charset=utf-8")
            return
        if path == "/api/market":
            snapshot = self.server.snapshot_provider()
            market = snapshot.get("market", {})
            market_server, market_source = _mobile_market_identity(market)
            query = parse_qs(request_url.query, keep_blank_values=True)
            text = query.get("q", [""])[0].strip().casefold()

            def number(name):
                try:
                    return int(query.get(name, ["0"])[0] or 0)
                except (TypeError, ValueError):
                    return 0

            class_bit, race_bit, slot_bit = (
                number("class"), number("race"), number("slot"))
            effect = query.get("effect", [""])[0].strip().casefold()
            drop = query.get("drop", [""])[0].strip().casefold()
            era = query.get("era", [""])[0].strip().casefold()
            sort_key = query.get("sort", ["posts"])[0].strip().casefold()
            found = []
            for item in market.get("items", ()):
                effects = item.get("effects", ())
                search_text = " ".join([
                    str(item.get("name", "")),
                    *(str(value) for pair in effects
                      for value in (pair.get("type", ""), pair.get("name", "")))
                ]).casefold()
                if text and text not in search_text:
                    continue
                if class_bit and not int(item.get("classes", 0)) & class_bit:
                    continue
                if race_bit and not int(item.get("races", 0)) & race_bit:
                    continue
                if slot_bit and not int(item.get("slots", 0)) & slot_bit:
                    continue
                if effect and not any(
                        str(pair.get("type", "")).casefold() == effect
                        for pair in effects):
                    continue
                if drop == "nodrop" and not bool(item.get("nodrop")):
                    continue
                if drop == "drop" and bool(item.get("nodrop")):
                    continue
                if era and str(item.get("era", "")).casefold() != era:
                    continue
                found.append(item)
            if sort_key == "price":
                value = lambda item: int(item.get("price", 0))
            elif sort_key in {
                    "ac", "hp", "mana", "astr", "asta", "adex", "aagi",
                    "aint", "awis", "acha", "mr", "fr", "cr", "dr",
                    "pr", "attack", "haste", "regen", "manaregen"}:
                value = lambda item: int(item.get("stats", {}).get(sort_key, 0))
            else:
                value = lambda item: int(item.get("posts", 0))
            found.sort(key=lambda item: (
                -value(item), str(item.get("name", "")).casefold()))
            response = {
                "server": market_server,
                "source": market_source,
                "metadata_source": market.get("metadata_source", "P99 Wiki"),
                "total": len(found),
                "items": found[:100],
            }
            payload = json.dumps(
                response, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")
            self._send(200, payload, "application/json; charset=utf-8")
            return
        if path == "/api/spell-detail":
            query = parse_qs(request_url.query, keep_blank_values=True)
            requested_name = query.get("name", [""])[0].strip()
            spell = next((
                item for item in self.server.spells
                if str(item.get("name", "")).casefold() ==
                requested_name.casefold()), None)
            if spell is None:
                self._send(
                    404, b'{"error":"unknown_spell"}',
                    "application/json; charset=utf-8")
                return
            try:
                detail = load_mobile_spell_detail(spell["name"])
            except (OSError, UnicodeError, ValueError,
                    json.JSONDecodeError) as error:
                detail = {
                    "description": str(spell.get("effect_hint") or
                                       "No effect description is available offline."),
                    "effects": [],
                    "source": f"Bundled spell data · Wiki unavailable ({error})",
                }
            payload = json.dumps(
                detail, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")
            self._send(200, payload, "application/json; charset=utf-8")
            return
        if path == "/api/spells":
            query = parse_qs(request_url.query, keep_blank_values=True)
            text = query.get("q", [""])[0].strip().casefold()
            class_name = query.get("class", [""])[0].strip()
            try:
                level = int(query.get("level", ["0"])[0] or 0)
            except (TypeError, ValueError):
                level = 0
            snapshot = self.server.snapshot_provider()
            price_index = {}
            for item in snapshot.get("market", {}).get("items", ()):
                name = re.sub(
                    r"^spell\s*:\s*", "", str(item.get("name", "")),
                    flags=re.IGNORECASE).casefold()
                price_index[name] = item
            available_levels = sorted({
                int(profile[1])
                for spell in self.server.spells
                for profile in spell.get("class_levels", ())
                if not class_name or str(profile[0]) == class_name})
            found = []
            for spell in self.server.spells:
                name = str(spell.get("name", ""))
                if text and text not in name.casefold():
                    continue
                profiles = spell.get("class_levels", ())
                selected = [profile for profile in profiles if (
                    (not class_name or str(profile[0]) == class_name) and
                    (not level or int(profile[1]) == level))]
                if (class_name or level) and not selected:
                    continue
                row = dict(spell)
                chosen = selected[0] if selected else min(
                    profiles, key=lambda profile: int(profile[1]))
                row["selected_class"] = chosen[0]
                row["selected_level"] = int(chosen[1])
                market_row = price_index.get(name.casefold(), {})
                row["price"] = int(market_row.get("price", 0) or 0)
                row["posts"] = int(market_row.get("posts", 0) or 0)
                row["quality"] = str(market_row.get("quality", ""))
                found.append(row)
            found.sort(key=lambda item: (
                int(item.get("selected_level", 0)),
                str(item.get("name", "")).casefold()))
            payload = json.dumps({
                "source": "Bundled classic spells_us.txt · P99 Wiki links",
                "available_levels": available_levels,
                "total": len(found), "items": found[:250],
            }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send(200, payload, "application/json; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")


def _lan_address():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class MobileShareController(QObject):
    status_changed = Signal(str)
    link_changed = Signal(str, bool)
    running_changed = Signal(bool)
    binary_required = Signal()
    download_progress = Signal(int)
    game_status_changed = Signal(str)
    game_enabled_changed = Signal(bool)
    game_executable_changed = Signal(str)
    timer_action_requested = Signal(str, str)

    def __init__(
            self, snapshot_provider, timer_action_handler=None, parent=None):
        super().__init__(parent)
        self.snapshot_provider = snapshot_provider
        self._timer_action_handler = timer_action_handler
        self._server = None
        self._server_thread = None
        self._token = ""
        self._lan_token = ""
        self._process = None
        self._process_buffer = ""
        self._public_url = ""
        self._local_url = ""
        self._download_stream = None
        self._download_pending = ""
        self._snapshot_lock = threading.Lock()
        self._snapshot_cache = {}
        mobile_settings = config.data.get("mobile", {})
        self.game_capture = GameWindowCapture(
            mobile_settings.get("eq_executable", ""),
            fps=mobile_settings.get("game_fps", 5),
            profile=mobile_settings.get("game_image_quality", "hd"))
        self._spell_items = tuple({
            "spell_id": entry.spell_id,
            "name": entry.name,
            "class_levels": entry.class_levels,
            "icon_id": entry.icon_id,
            "effect_hint": entry.effect_hint,
            "wiki_url": "https://wiki.project1999.com/" + quote(
                entry.name.replace(" ", "_"), safe=""),
        } for entry in p99_spell_entries())
        self.timer_action_requested.connect(self._dispatch_timer_action)
        self._network = QNetworkAccessManager(self)
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setInterval(1000)
        self._snapshot_timer.timeout.connect(self._refresh_snapshot)
        self._snapshot_timer.start()
        self._refresh_snapshot()

    @property
    def active(self):
        return self._server is not None

    @property
    def public_url(self):
        return self._public_url

    @property
    def local_url(self):
        return self._local_url

    def _snapshot(self):
        with self._snapshot_lock:
            return self._snapshot_cache

    def _refresh_snapshot(self):
        snapshot = self.snapshot_provider()
        with self._snapshot_lock:
            self._snapshot_cache = snapshot

    def start(self):
        if self.active:
            if self._public_url:
                self.link_changed.emit(self._public_url, True)
            else:
                self.link_changed.emit(self._local_url, False)
            return
        self._token = secrets.token_urlsafe(32)
        self._lan_token = secrets.token_urlsafe(32)
        self._process_buffer = ""
        try:
            self._server = _ShareHTTPServer(
                ("0.0.0.0", 0), self._token, self._snapshot,
                self.game_capture, self._lan_token,
                self._queue_timer_action, self._spell_items)
        except OSError as error:
            self.status_changed.emit(f"The mobile view could not be opened: {error}")
            return
        port = self._server.server_address[1]
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.2}, daemon=True)
        self._server_thread.start()
        self._local_url = f"http://{_lan_address()}:{port}/#{self._lan_token}"
        self.link_changed.emit(self._local_url, False)
        self.running_changed.emit(True)
        binary = self._cloudflared_path()
        if binary:
            self._start_tunnel(binary, port)
        else:
            self.status_changed.emit(
                "Wi-Fi ready. To open it away from home, install the free official component.")
            self.binary_required.emit()

    def stop(self):
        if self._process:
            process = self._process
            self._process = None
            process.terminate()
            if not process.waitForFinished(1500):
                process.kill()
                process.waitForFinished(1000)
            process.deleteLater()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._server_thread = None
        self._token = ""
        self._lan_token = ""
        self._public_url = ""
        self._local_url = ""
        self._process_buffer = ""
        self.game_capture.set_enabled(False)
        self.game_enabled_changed.emit(False)
        self.status_changed.emit("Session stopped. The previous link no longer works.")
        self.link_changed.emit("", False)
        self.running_changed.emit(False)

    def set_game_enabled(self, enabled):
        self.game_capture.set_enabled(enabled)
        self.game_enabled_changed.emit(bool(enabled))
        status = self.game_capture.status()
        self.game_status_changed.emit(status["message"])
        if self.active:
            if enabled:
                self.link_changed.emit(self._local_url, False)
                self.status_changed.emit(
                    "EverQuest Live ready over local Wi-Fi · read-only view.")
            elif self._public_url:
                self.link_changed.emit(self._public_url, True)
            else:
                self.link_changed.emit(self._local_url, False)

    def set_game_fps(self, fps):
        self.game_capture.set_fps(fps)
        config.data["mobile"]["game_fps"] = int(fps)
        config.save()

    def set_game_image_quality(self, profile):
        profile = self.game_capture.set_image_profile(profile)
        config.data["mobile"]["game_image_quality"] = profile
        config.save()
        self.game_status_changed.emit(
            f"Image quality: {self.game_capture.status()['image_quality_label']}")

    def _queue_timer_action(self, action, target):
        """Bridge the isolated HTTP thread into Qt's main UI thread."""
        self.timer_action_requested.emit(str(action), str(target))

    def _dispatch_timer_action(self, action, target):
        if callable(self._timer_action_handler):
            self._timer_action_handler(action, target)
            QTimer.singleShot(0, self._refresh_snapshot)

    def set_game_executable(self, path):
        self.game_capture.set_executable(path)
        config.data["mobile"]["eq_executable"] = path
        config.save()
        self.game_executable_changed.emit(path)
        label = os.path.basename(path) if path else "automatic detection"
        self.game_status_changed.emit(f"Linked: {label}")

    def auto_detect_game(self):
        matches = self.game_capture.discover_executables()
        if matches:
            self.set_game_executable(matches[0])
            self.game_status_changed.emit(
                f"EverQuest detected automatically: {matches[0]}")
            return matches[0]
        self.game_status_changed.emit(
            "eqgame.exe was not found. Open EverQuest and try again, or select it manually.")
        return ""

    def _tool_dir(self):
        return str(data_dir("tools"))

    def _cloudflared_path(self):
        bundled = os.path.join(self._tool_dir(), "cloudflared.exe")
        return bundled if os.path.isfile(bundled) else None

    def download_cloudflared(self):
        if platform.system() != "Windows" or platform.machine().lower() not in {
                "amd64", "x86_64"}:
            self.status_changed.emit("Automatic download is available only on 64-bit Windows.")
            return
        self.status_changed.emit("Downloading the official Cloudflare component…")
        os.makedirs(self._tool_dir(), exist_ok=True)
        self._download_pending = os.path.join(
            self._tool_dir(), "cloudflared.exe.part")
        try:
            self._download_stream = open(self._download_pending, "wb")
        except OSError as error:
            self.status_changed.emit(f"The download could not be prepared: {error}")
            return
        request = QNetworkRequest(QUrl(CLOUDFLARED_DOWNLOAD))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        reply = self._network.get(request)
        reply.readyRead.connect(lambda: self._download_ready(reply))
        reply.downloadProgress.connect(self._download_progress)
        reply.finished.connect(lambda: self._download_finished(reply))

    def _download_ready(self, reply):
        if self._download_stream:
            self._download_stream.write(bytes(reply.readAll()))

    def _download_progress(self, received, total):
        self.download_progress.emit(
            int(received * 100 / total) if total and total > 0 else 0)

    def _download_finished(self, reply):
        try:
            self._download_ready(reply)
            if self._download_stream:
                self._download_stream.close()
                self._download_stream = None
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.status_changed.emit(f"Download failed: {reply.errorString()}")
                try:
                    os.remove(self._download_pending)
                except OSError:
                    pass
                return
            target = os.path.join(self._tool_dir(), "cloudflared.exe")
            if not self._valid_cloudflare_signature(self._download_pending):
                try:
                    os.remove(self._download_pending)
                except OSError:
                    pass
                self.status_changed.emit(
                    "Windows could not validate Cloudflare's official signature; nothing was installed.")
                return
            os.replace(self._download_pending, target)
            self.download_progress.emit(100)
            self.status_changed.emit("Component validated. Creating an ephemeral link…")
            if self.active:
                self._start_tunnel(target, self._server.server_address[1])
        finally:
            reply.deleteLater()

    @staticmethod
    def _valid_cloudflare_signature(path):
        safe_path = path.replace("'", "''")
        script = (
            "$s=Get-AuthenticodeSignature -LiteralPath '" + safe_path + "';"
            "if($s.Status -eq 'Valid' -and "
            "$s.SignerCertificate.Subject -match 'Cloudflare'){exit 0}else{exit 2}")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                check=False, capture_output=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _start_tunnel(self, binary, port):
        if self._process:
            return
        self.status_changed.emit("Creating a private temporary link…")
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.setProgram(binary)
        process.setArguments([
            "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"])
        process.readyReadStandardOutput.connect(self._read_tunnel_output)
        process.errorOccurred.connect(
            lambda _: self.status_changed.emit(
                "The tunnel could not start; the Wi-Fi link remains available."))
        process.finished.connect(self._tunnel_finished)
        self._process = process
        process.start()

    def _read_tunnel_output(self):
        if not self._process:
            return
        self._process_buffer += bytes(
            self._process.readAllStandardOutput()).decode("utf-8", "replace")
        match = TUNNEL_URL_RX.search(self._process_buffer)
        if match and not self._public_url:
            self._public_url = f"{match.group(0)}/#{self._token}"
            self.status_changed.emit(
                "Live · free individual link. It shuts down when the session stops.")
            if not self.game_capture.enabled:
                self.link_changed.emit(self._public_url, True)

    def _tunnel_finished(self, *_):
        if self.active and not self._public_url:
            self.status_changed.emit(
                "Cloudflare did not respond; use the Wi-Fi link or try again.")
        self._process = None


def _qr_pixmap(text, size=250):
    qr = segno.make(text, error="q")
    output = io.BytesIO()
    qr.save(output, kind="png", scale=7, border=2, dark="#071014", light="#F4FBFC")
    pixmap = QPixmap()
    pixmap.loadFromData(output.getvalue(), "PNG")
    return pixmap.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)


class EverQuestLiveSetupDialog(UniformScaleDialog):
    """Dedicated, explicit setup flow for the read-only game view."""

    def __init__(self, controller, parent=None):
        super().__init__(
            QSize(560, 540), parent, minimum_size=QSize(196, 189),
            initial_size=QSize(448, 432))
        self.controller = controller
        self.setWindowTitle("Vantage · Set Up EverQuest Live")
        outer = QVBoxLayout(self.scaled_surface)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(9)
        outer.addWidget(scrollable(body, "EverQuestLiveSetupScroll"), 1)

        title = QLabel("EVERQUEST LIVE · READ ONLY")
        title.setObjectName("MobileShareTitle")
        layout.addWidget(title)
        intro = QLabel(
            "This feature sends only the EverQuest window image to your phone "
            "over the same Wi-Fi network. It does not send clicks or keystrokes to the game.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        step1 = QLabel("1 · FIND EVERQUEST")
        step1.setObjectName("SettingsHeader")
        layout.addWidget(step1)
        detection_note = QLabel(
            "Vantage first checks the running game, the Windows Registry, "
            "and common folders. It does not scan the entire drive.")
        detection_note.setWordWrap(True)
        layout.addWidget(detection_note)
        self.game_path = QLineEdit()
        self.game_path.setReadOnly(True)
        self.game_path.setPlaceholderText("eqgame.exe has not been found yet")
        self.game_path.setAccessibleName("Detected EverQuest executable")
        self.game_path.setToolTip(
            "Path to eqgame.exe, used only to identify the correct window")
        self.game_path.setText(controller.game_capture.executable)
        layout.addWidget(self.game_path)
        detection_actions = ResponsiveActionBar(155)
        detect = QPushButton("Detect Automatically")
        detect.setIcon(game_icon("follow"))
        detect.setToolTip(
            "Search the running game, Windows Registry, and common locations")
        detect.clicked.connect(self._detect)
        detection_actions.addWidget(detect)
        browse = QPushButton("Choose Manually…")
        browse.setIcon(game_icon("copy"))
        browse.setToolTip(
            "Select eqgame.exe if EverQuest is installed in another folder")
        browse.clicked.connect(self._choose_game_executable)
        detection_actions.addWidget(browse)
        layout.addWidget(detection_actions)

        step2 = QLabel("2 · VIEW QUALITY")
        step2.setObjectName("SettingsHeader")
        layout.addWidget(step2)
        self.game_fps = QComboBox()
        self.game_fps.setAccessibleName("EverQuest Live frame rate")
        self.game_fps.setToolTip(
            "More FPS looks smoother but uses more network bandwidth and slightly more CPU")
        self.game_fps.addItem("Economy · 2 FPS", 2)
        self.game_fps.addItem("Balanced · 5 FPS", 5)
        self.game_fps.addItem("Smooth · 10 FPS", 10)
        selected_fps = config.data.get("mobile", {}).get("game_fps", 5)
        self.game_fps.setCurrentIndex(max(
            0, self.game_fps.findData(selected_fps)))
        self.game_fps.currentIndexChanged.connect(
            lambda: controller.set_game_fps(self.game_fps.currentData()))
        layout.addWidget(self.game_fps)

        self.game_quality = QComboBox()
        self.game_quality.setAccessibleName("EverQuest Live image quality")
        self.game_quality.setToolTip(
            "Sharp HD preserves interface text at up to 1920 pixels; Native "
            "detail uses more Wi-Fi bandwidth and CPU")
        self.game_quality.addItem("Efficient HD · 1280 px", "efficient")
        self.game_quality.addItem("Sharp HD · 1920 px", "hd")
        self.game_quality.addItem("Native detail · 2560 px", "native")
        selected_quality = config.data.get(
            "mobile", {}).get("game_image_quality", "hd")
        self.game_quality.setCurrentIndex(max(
            0, self.game_quality.findData(selected_quality)))
        self.game_quality.currentIndexChanged.connect(
            lambda: controller.set_game_image_quality(
                self.game_quality.currentData()))
        layout.addWidget(self.game_quality)

        step3 = QLabel("3 · ENABLE AND OPEN THE QR")
        step3.setObjectName("SettingsHeader")
        layout.addWidget(step3)
        self.game_enabled = QCheckBox(
            "Include EverQuest Live in the Wi-Fi session")
        self.game_enabled.setToolTip(
            "Add an EverQuest Live tab to the phone's local link")
        self.game_enabled.toggled.connect(controller.set_game_enabled)
        layout.addWidget(self.game_enabled)
        finish = QLabel(
            "Then return to “Vantage on Your Phone,” create the link, and scan "
            "the QR code. The game view works only over local Wi-Fi; Timers and "
            "Market and Spells can also use the temporary external link. Timer "
            "controls and zone sync require the local Wi-Fi link.")
        finish.setWordWrap(True)
        layout.addWidget(finish)

        self.status = QLabel("Ready to detect EverQuest")
        self.status.setObjectName("MobileShareStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QPushButton("Done")
        close.setObjectName("PrimaryAction")
        close.setToolTip("Save this setup and return to the mobile link")
        close.clicked.connect(self.close)
        layout.addWidget(close)

        controller.game_status_changed.connect(self.status.setText)
        controller.game_enabled_changed.connect(self._set_game_enabled)
        controller.game_executable_changed.connect(self.game_path.setText)
        self.refresh()

    def refresh(self):
        self.game_path.setText(self.controller.game_capture.executable)
        self._set_game_enabled(self.controller.game_capture.enabled)

    def _detect(self):
        self.status.setText("Looking for EverQuest without scanning the entire drive…")
        QTimer.singleShot(0, self.controller.auto_detect_game)

    def _choose_game_executable(self):
        current = self.game_path.text() or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Link the EverQuest Executable", current,
            "EverQuest (eqgame.exe EverQuest.exe);;Executables (*.exe)")
        if path:
            self.controller.set_game_executable(path)

    def _set_game_enabled(self, enabled):
        self.game_enabled.blockSignals(True)
        self.game_enabled.setChecked(enabled)
        self.game_enabled.blockSignals(False)


class MobileShareDialog(UniformScaleDialog):
    def __init__(self, controller, parent=None):
        super().__init__(
            QSize(520, 610), parent, minimum_size=QSize(182, 214),
            initial_size=QSize(390, 458))
        self.controller = controller
        self._current_link = ""
        self.setWindowTitle("Vantage on Your Phone")
        outer = QVBoxLayout(self.scaled_surface)
        body = QWidget()
        layout = QVBoxLayout(body)
        outer.addWidget(scrollable(body, "MobileShareScroll"), 1)
        heading = QLabel("VANTAGE ON YOUR PHONE")
        heading.setObjectName("MobileShareTitle")
        layout.addWidget(heading)
        note = QLabel(
            "One private QR opens your Timers, Market, Spells, and optional "
            "EverQuest Live view. Keep Vantage running while you use it.")
        note.setWordWrap(True)
        note.setAccessibleName(
            "The private QR includes Timers, Market, Spells, and EverQuest Live")
        layout.addWidget(note)

        steps = QLabel(
            "1 · START PHONE QR    2 · SCAN IT    3 · OPEN A TAB")
        steps.setObjectName("SettingsHeader")
        steps.setWordWrap(True)
        steps.setAccessibleName(
            "Step 1 start the phone QR. Step 2 scan it. Step 3 open a tab.")
        layout.addWidget(steps)

        actions = ResponsiveActionBar(180)
        self.toggle = QPushButton("Start Phone QR")
        self.toggle.setObjectName("PrimaryAction")
        self.toggle.setIcon(game_icon("mobile"))
        self.toggle.setToolTip(
            "Start one private phone session and display its QR code")
        self.toggle.clicked.connect(self._toggle)
        actions.addWidget(self.toggle)
        self.download = QPushButton("Enable Remote Link")
        self.download.setIcon(game_icon("refresh"))
        self.download.setVisible(False)
        self.download.setToolTip(
            "Download the official signed Cloudflare component for use away from home")
        self.download.clicked.connect(self._confirm_download)
        actions.addWidget(self.download)
        layout.addWidget(actions)

        self.status = QLabel("Stopped · click Start Phone QR")
        self.status.setObjectName("MobileShareStatus")
        self.status.setWordWrap(True)
        self.status.setToolTip(
            "Current phone session, Wi-Fi link, remote link, or download state")
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.progress.setToolTip(
            "Download progress for the official Cloudflare component")
        layout.addWidget(self.progress)

        self.qr = QLabel("1 · Click Start Phone QR")
        self.qr.setObjectName("MobileShareQR")
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setMinimumHeight(180)
        self.qr.setAccessibleName("Private mobile session QR code")
        self.qr.setAccessibleDescription(
            "Start the phone session to generate the QR code")
        self.qr.setToolTip(
            "Scan this private companion link with your phone camera")
        layout.addWidget(self.qr)

        included = QLabel(
            "QR INCLUDES · TIMERS · MARKET · SPELLS · EQ LIVE (OPTIONAL)")
        included.setObjectName("MobileShareTerms")
        included.setWordWrap(True)
        included.setAccessibleName(
            "The QR includes Timers, Market, Spells, and optional EverQuest Live")
        layout.addWidget(included)

        link_row = QHBoxLayout()
        self.link = QLineEdit()
        self.link.setReadOnly(True)
        self.link.setPlaceholderText("The QR address will appear here")
        self.link.setAccessibleName("Current private mobile link")
        self.link.setToolTip(
            "Private companion address; scan the QR or copy this link")
        link_row.addWidget(self.link, 1)
        copy = QPushButton("Copy Link")
        copy.setIcon(game_icon("copy"))
        copy.setToolTip("Copy the current private mobile link")
        copy.clicked.connect(self._copy)
        link_row.addWidget(copy)
        layout.addLayout(link_row)

        live_box = QWidget()
        live_layout = QVBoxLayout(live_box)
        live_layout.setContentsMargins(8, 8, 8, 8)
        live_title = QLabel("OPTIONAL · EVERQUEST LIVE")
        live_title.setObjectName("SettingsHeader")
        live_layout.addWidget(live_title)
        self.game_summary = QLabel(
            "Optional · local read-only view · sends no controls")
        self.game_summary.setWordWrap(True)
        self.game_summary.setToolTip(
            "Open the setup guide to detect eqgame.exe and configure quality")
        live_layout.addWidget(self.game_summary)
        configure_live = QPushButton("Set Up EQ Live…")
        configure_live.setIcon(game_icon("follow"))
        configure_live.setToolTip(
            "Open the separate detection and setup guide")
        configure_live.clicked.connect(self._show_live_setup)
        live_layout.addWidget(configure_live)
        layout.addWidget(live_box)
        self._live_setup = EverQuestLiveSetupDialog(controller, self)

        self.terms = QLabel(
            "Remote access uses <a href='" + CLOUDFLARE_QUICK_TUNNEL_DOCS +
            "'>Cloudflare Quick Tunnels</a>. It is free and temporary, with no SLA. "
            "The first use may require downloading its official Windows component.")
        self.terms.setWordWrap(True)
        self.terms.setOpenExternalLinks(True)
        self.terms.setTextFormat(Qt.TextFormat.RichText)
        self.terms.setObjectName("MobileShareTerms")
        self.terms.setToolTip(
            "Open the official documentation for free temporary Quick Tunnels")
        layout.addWidget(self.terms)


        controller.status_changed.connect(self.status.setText)
        controller.link_changed.connect(self._set_link)
        controller.running_changed.connect(self._set_running)
        controller.binary_required.connect(lambda: self.download.setVisible(True))
        controller.download_progress.connect(self._set_progress)
        controller.game_status_changed.connect(self.game_summary.setText)
        controller.game_enabled_changed.connect(self._set_game_enabled)

    def refresh(self):
        self._live_setup.refresh()
        self._set_running(self.controller.active)
        if self.controller.game_capture.enabled and self.controller.local_url:
            self._set_link(self.controller.local_url, False)
        elif self.controller.public_url:
            self._set_link(self.controller.public_url, True)
        elif self.controller.local_url:
            self._set_link(self.controller.local_url, False)

    def _toggle(self):
        if self.controller.active:
            self.controller.stop()
        else:
            self.controller.start()

    def _set_running(self, running):
        self.toggle.setText("Stop Phone QR" if running else "Start Phone QR")
        self.toggle.setIcon(game_icon("stop" if running else "mobile"))
        self.toggle.setToolTip(
            "Stop this private phone session and invalidate its QR" if running
            else "Start one private phone session and display its QR code")
        self.toggle.setObjectName("DangerAction" if running else "PrimaryAction")
        self.toggle.style().unpolish(self.toggle)
        self.toggle.style().polish(self.toggle)
        self.download.setVisible(False if not running else self.download.isVisible())

    def _set_game_enabled(self, enabled):
        state = "ACTIVE" if enabled else "OFF"
        target = self.controller.game_capture.executable
        detail = os.path.basename(target) if target else "detection pending"
        self.game_summary.setText(
            f"EverQuest Live · {state} · {detail} · local Wi-Fi only")

    def _show_live_setup(self):
        self._live_setup.refresh()
        self._live_setup.show()
        self._live_setup.raise_()
        self._live_setup.activateWindow()

    def _set_link(self, link, public):
        self._current_link = link
        self.link.setText(link)
        if not link:
            self.qr.clear()
            self.qr.setText("1 · Click Start Phone QR")
            self.qr.setAccessibleDescription(
                "The phone session is stopped; start it to generate a QR code")
            return
        self._update_qr()
        link_kind = "temporary remote" if public else "same Wi-Fi"
        self.qr.setAccessibleDescription(
            f"QR code ready for the {link_kind} phone link")
        self.qr.setToolTip(
            "Temporary remote link" if public else "Link available on the same Wi-Fi network")

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def _update_qr(self):
        size = 250
        self.qr.setMinimumHeight(size + 18)
        self.qr.setPixmap(_qr_pixmap(self._current_link, size))

    def _copy(self):
        if self.link.text():
            QApplication.clipboard().setText(self.link.text())
            self.status.setText("Link copied.")

    def _confirm_download(self):
        answer = QMessageBox.question(
            self, "Official Cloudflare Component",
            "cloudflared will be downloaded from the official repository, and Windows "
            "will verify its digital signature before use. Installing it means "
            "accepting Cloudflare's license, terms, and privacy policy.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.download.setEnabled(False)
            self.progress.setVisible(True)
            self.controller.download_cloudflared()

    def _set_progress(self, value):
        self.progress.setVisible(value < 100)
        self.progress.setValue(value)
        if value >= 100:
            self.download.setVisible(False)
            self.download.setEnabled(True)
