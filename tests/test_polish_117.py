"""Focused runtime regressions for the bounded 1.44.117 polish pass."""

import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers.mobile_share import (
    _MOBILE_PAGE,
    _merge_mobile_item_detail,
    _mobile_wiki_item_identity,
)


ROOT = Path(__file__).resolve().parents[1]


def _run(script, tmp_path, *, timeout=45, webengine=False):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    if webengine:
        env["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
        env["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, check=True, timeout=timeout)
    return json.loads(completed.stdout.strip().splitlines()[-1])


TABLE_FOCUS_SCRIPT = r"""
import json
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu, QTableWidget, QTableWidgetItem
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['eq_log_dir'] = ''
app = VantageApp([])
panel = app._parsers_dict['log_searcher']
table = panel.table
table.setRowCount(3)
for row in range(3):
    for column in range(6):
        table.setItem(row, column, QTableWidgetItem(f'{row}:{column}'))
panel._toggled = True
panel.show()
QTest.qWait(120)
app._column_widths._configure(table)
dynamic = QTableWidget(0, 0)
dynamic.setTabKeyNavigation(True)
app._column_widths._configure(dynamic)
dynamic_initial = dynamic.tabKeyNavigation()
dynamic.setColumnCount(2)
dynamic.setRowCount(1)
dynamic.setItem(0, 0, QTableWidgetItem('later'))
dynamic_after = dynamic.tabKeyNavigation()

def in_table(widget):
    return widget is table or (widget is not None and table.isAncestorOf(widget))

def focus_name(widget):
    return ((widget.accessibleName() or widget.objectName())
            if widget is not None else '')

# Negative control proves that the pre-fix policy keeps focus inside the grid
# and changes cells instead of leaving for the authored neighboring control.
table.setTabKeyNavigation(True)
table.setCurrentCell(1, 2)
table.setFocus(Qt.FocusReason.OtherFocusReason)
QTest.keyClick(table, Qt.Key.Key_Tab)
negative_forward = [table.currentRow(), table.currentColumn()]
negative_forward_inside = in_table(panel._surface.focusWidget())
table.setCurrentCell(1, 2)
table.setFocus(Qt.FocusReason.OtherFocusReason)
QTest.keyClick(table, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
negative_reverse = [table.currentRow(), table.currentColumn()]
negative_reverse_inside = in_table(panel._surface.focusWidget())
table.setTabKeyNavigation(False)

table.setCurrentCell(1, 2)
table.setFocus(Qt.FocusReason.OtherFocusReason)
QTest.keyClick(table, Qt.Key.Key_Tab)
QTest.qWait(20)
forward = panel._surface.focusWidget()
forward_cell = [table.currentRow(), table.currentColumn()]

table.setCurrentCell(1, 2)
table.setFocus(Qt.FocusReason.OtherFocusReason)
QTest.keyClick(
    table, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
QTest.qWait(20)
reverse = panel._surface.focusWidget()
reverse_cell = [table.currentRow(), table.currentColumn()]

table.setCurrentCell(1, 2)
table.setFocus(Qt.FocusReason.OtherFocusReason)
QTest.keyClick(
    table, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
QTest.qWait(20)
menus = [widget for widget in app.topLevelWidgets()
         if isinstance(widget, QMenu) and widget.isVisible()]
print(json.dumps({
    'tab_navigation': table.tabKeyNavigation(),
    'dynamic_initial': dynamic_initial,
    'dynamic_after': dynamic_after,
    'forward_left': forward is not table,
    'reverse_left': reverse is not table,
    'forward_name': focus_name(forward),
    'reverse_name': focus_name(reverse),
    'forward_cell': forward_cell,
    'reverse_cell': reverse_cell,
    'negative_forward': negative_forward,
    'negative_reverse': negative_reverse,
    'negative_forward_inside': negative_forward_inside,
    'negative_reverse_inside': negative_reverse_inside,
    'menu_actions': [action.text() for action in menus[-1].actions()
                     if action.text()] if menus else [],
}))
for menu in menus:
    menu.close()
app.quit()
"""


def test_proxy_hosted_table_tab_and_backtab_leave_grid(tmp_path):
    result = _run(TABLE_FOCUS_SCRIPT, tmp_path)
    assert result["tab_navigation"] is False
    assert result["dynamic_initial"] is False
    assert result["dynamic_after"] is False
    assert result["forward_left"] is True
    assert result["forward_name"] == "Scroll the visible content"
    assert result["reverse_left"] is True
    assert result["reverse_name"] == "Copy selected log search rows"
    assert result["forward_cell"] == [1, 2]
    assert result["reverse_cell"] == [1, 2]
    assert result["negative_forward"] == [1, 3]
    assert result["negative_reverse"] == [1, 1]
    assert result["negative_forward_inside"] is True
    assert result["negative_reverse_inside"] is True
    assert result["menu_actions"][:3] == [
        "Widen Server", "Narrow Server", "Auto-fit Server"]


EMPTY_STATES_SCRIPT = r"""
import gzip
import json
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers.market import _gear_cache_file

config.data['general']['eq_log_dir'] = ''
app = VantageApp([])
timers = app._parsers_dict['timers']
zones = app._parsers_dict['zones']
market = app._parsers_dict['market']
market._refresh_timer.stop()
for panel in (timers, zones, market):
    panel._toggled = True
    panel.show()
QTest.qWait(120)
timers._selected_zone = 'Chardok'
timers._apply_zone_filter()
timers._sync_timer_canvas()

zones.mob_table.clearSelection()
zones._selection_changed()
zone_initial = zones.zone_drop_selector.currentText()
zones._set_zone_data({
    'name': 'South Karana',
    'mobs': [{'name': 'Quillmane', 'named': True, 'drops': []}],
})
zones.tabs.setCurrentIndex(1)
zones.mob_table.selectRow(0)
zones._selection_changed()
zone_no_drops = zones.zone_drop_selector.currentText()

class MismatchedReply:
    deleted = False
    def error(self):
        return QNetworkReply.NetworkError.NoError
    def errorString(self):
        return ''
    def readAll(self):
        return gzip.compress(b'SQLite format 3\x00synthetic unverified data')
    def property(self, name):
        return '0' * 64 if name == 'expected_sha256' else None
    def deleteLater(self):
        self.deleted = True

mismatch = MismatchedReply()
market._gear_model.items = []
market._gear_db_finished(mismatch)
cache_written = _gear_cache_file().exists()
calls = []
market._refresh_gear_index = lambda: calls.append('gear')
market.refresh = lambda: calls.append('prices')
market._refresh_button.setEnabled(True)
market._refresh_button.click()
refresh_calls = list(calls)

timer_sizes = []
for width, height in ((520, 360), (302, 281)):
    timers.resize(width, height)
    QTest.qWait(40)
    timers._sync_timer_canvas()
    QTest.qWait(20)
    timer_sizes.append({
        'window': [width, height],
        'label': [timers.empty_message.width(), timers.empty_message.height()],
        'needed': timers.empty_message.heightForWidth(
            timers.empty_message.width()),
    })

print(json.dumps({
    'timer_visible': timers.empty_state.isVisibleTo(timers._surface),
    'timer_text': timers.empty_message.text(),
    'timer_name': timers.empty_state.accessibleName(),
    'timer_button': timers.empty_add_button.text(),
    'timer_button_name': timers.empty_add_button.accessibleName(),
    'timer_label_height': timers.empty_message.height(),
    'timer_label_needed': timers.empty_message.heightForWidth(
        timers.empty_message.width()),
    'zone_initial': zone_initial,
    'zone_no_drops': zone_no_drops,
    'zone_enabled': zones.zone_drop_selector.isEnabled(),
    'market_text': market.gear_status.text(),
    'market_name': market.gear_status.accessibleName(),
    'market_description': market.gear_status.accessibleDescription(),
    'market_reply_deleted': mismatch.deleted,
    'market_cache_written': cache_written,
    'refresh_name': market._refresh_button.accessibleName(),
    'refresh_calls': refresh_calls,
    'timer_sizes': timer_sizes,
}))
app.quit()
"""


def test_actionable_timer_zone_and_market_states(tmp_path):
    result = _run(EMPTY_STATES_SCRIPT, tmp_path)
    assert result["timer_visible"] is True
    assert result["timer_text"] == (
        "No timers in Chardok.\n"
        "Add one here, choose another zone, or watch an existing timer.")
    assert result["timer_name"] == "No timers in Chardok"
    assert result["timer_button"] == "Add timer…"
    assert result["timer_button_name"] == "Add a Smart Timer"
    assert result["timer_label_height"] >= result["timer_label_needed"]
    assert all(sample["label"][1] >= sample["needed"]
               for sample in result["timer_sizes"])
    assert result["zone_initial"] == "Select an NPC to see its drops"
    assert result["zone_no_drops"] == "No known drops"
    assert result["zone_enabled"] is False
    assert result["market_text"] == result["market_name"]
    assert "signature did not match" in result["market_description"]
    assert result["market_reply_deleted"] is True
    assert result["market_cache_written"] is False
    assert result["refresh_name"] == (
        "Refresh market prices and verified item stats")
    assert result["refresh_calls"] == ["gear", "prices"]


MOBILE_DETAIL_SCRIPT = r"""
import json
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from vantage.helpers.mobile_share import _MOBILE_PAGE

app = QApplication([])
view = QWebEngineView()
view.resize(390, 844)
loaded = QEventLoop()
view.loadFinished.connect(loaded.quit)
view.setHtml(_MOBILE_PAGE, QUrl('http://fixture.invalid/'))
QTimer.singleShot(10000, loaded.quit)
loaded.exec()

def run(script, wait=0):
    loop = QEventLoop()
    box = []
    view.page().runJavaScript(script, lambda value: (box.append(value), loop.quit()))
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    if wait:
        pause = QEventLoop()
        QTimer.singleShot(wait, pause.quit)
        pause.exec()
    return box[0] if box else None

run(r'''
window.__details={};
window.get=(path)=>new Promise((resolve,reject)=>{
  const name=new URL(path,'http://fixture.invalid').searchParams.get('name');
  window.__details[name]={resolve,reject};
});
''')

# A resolves after B: A must not replace B.
run("openMarketDetail({name:'A',price:1,posts:1});openMarketDetail({name:'B',price:2,posts:2});")
run("__details.B.resolve({name:'B detail',source:'fixture',price:2,posts:2,status:'complete',restrictions:{}})", 40)
run("__details.A.resolve({name:'A detail',source:'fixture',price:1,posts:1,status:'complete',restrictions:{}})", 40)
ab = json.loads(run("JSON.stringify({title:detailTitle.textContent,body:detailBody.textContent,status:detailStatus.textContent})"))

# A fails after B succeeds: stale error must not replace or announce.
run("detailDialog.close();openMarketDetail({name:'Error A'});openMarketDetail({name:'Safe B'});")
run("__details['Safe B'].resolve({name:'Safe B detail',source:'fixture',status:'complete',restrictions:{}})", 40)
run("__details['Error A'].reject(new Error('late A'))", 40)
error = json.loads(run("JSON.stringify({title:detailTitle.textContent,body:detailBody.textContent,status:detailStatus.textContent})"))

# Closing A invalidates it before B opens in a later task.
run("detailDialog.close();openMarketDetail({name:'Closed A'});detailDialog.close();")
run("openMarketDetail({name:'Open B'});")
run("__details['Open B'].resolve({name:'Open B detail',source:'fixture',status:'complete',restrictions:{}})", 40)
run("__details['Closed A'].resolve({name:'Closed A detail',source:'fixture',status:'complete',restrictions:{}})", 40)
closed = json.loads(run("JSON.stringify({title:detailTitle.textContent,body:detailBody.textContent,status:detailStatus.textContent})"))

# Opening another detail kind invalidates the pending item request.
run("detailDialog.close();openMarketDetail({name:'Cross-kind A'});showInstallHelp();")
run("__details['Cross-kind A'].resolve({name:'Late item',source:'fixture',status:'complete',restrictions:{}})", 40)
cross_kind = json.loads(run("JSON.stringify({title:detailTitle.textContent,body:detailBody.textContent,status:detailStatus.textContent})"))

print(json.dumps({'ab': ab, 'error': error, 'closed': closed, 'cross_kind': cross_kind}))
view.close()
app.quit()
"""


def test_mobile_detail_generation_rejects_late_success_error_and_close(tmp_path):
    result = _run(MOBILE_DETAIL_SCRIPT, tmp_path, timeout=55, webengine=True)
    assert result["ab"]["title"] == "B detail"
    assert "A detail" not in result["ab"]["body"]
    assert result["error"]["title"] == "Safe B detail"
    assert "unavailable" not in result["error"]["body"].casefold()
    assert result["closed"]["title"] == "Open B detail"
    assert "Closed A detail" not in result["closed"]["body"]
    assert result["cross_kind"]["title"] == "Save Vantage to your Home Screen"
    assert "Late item" not in result["cross_kind"]["body"]


def test_mobile_page_has_generation_guards_on_every_detail_exit():
    assert "detailRequest=0" in _MOBILE_PAGE
    assert "const request=++detailRequest" in _MOBILE_PAGE
    assert _MOBILE_PAGE.count(
        "request!==detailRequest||!detailDialog.open") >= 4
    assert "detailRequest+=1;detailDialog.setAttribute('aria-busy','false')" in (
        _MOBILE_PAGE)
    assert "request===detailRequest&&detailDialog.open" in _MOBILE_PAGE


def test_wiki_identity_overrides_only_explicit_snapshot_restrictions():
    text = (
        "MAGIC ITEM LORE ITEM NO DROP Skill: 1H Blunt DMG: 9 DLY: 18 "
        "WT: 4.0 Size: MEDIUM Class: SHM Race: IKS Slot: PRIMARY")
    flags, properties, restrictions = _mobile_wiki_item_identity(text)
    assert flags == ["MAGIC ITEM", "LORE ITEM", "NO DROP"]
    assert properties == {
        "skill": "1H Blunt", "weight": "4.0", "size": "MEDIUM"}
    assert restrictions == {
        "binding": "NO DROP", "classes": ["SHM"],
        "races": ["IKS"], "slots": ["PRIMARY"]}

    merged = _merge_mobile_item_detail({
        "name": "Jade Mace", "nodrop": False,
        "class_names": ["ALL"], "race_names": ["ALL"],
        "slot_names": ["SECONDARY"],
    }, {"name": "Jade Mace", "stats": text})
    assert merged["restrictions"]["binding"] == "NO DROP"
    assert merged["restrictions"]["classes"] == ["SHM"]
    assert merged["restrictions"]["races"] == ["IKS"]
    assert merged["restrictions"]["slots"] == ["PRIMARY"]

    raw_only = _merge_mobile_item_detail(
        {"name": "Raw-only item"},
        {"name": "Raw-only item", "stats": (
            "DMG: 0 DLY: 30 AC: +12 HP: +50 Mana: 0 "
            "STR: +5 STA: -2 DEX: 0 AGI: +1 INT: +3 WIS: +4 CHA: -5 "
            "MR: +6 FR: -7 CR: 0 DR: +8 PR: -9")})
    assert raw_only["stats"] == {
        "dmg": 0, "dly": 30, "ac": 12, "hp": 50, "mana": 0,
        "astr": 5, "asta": -2, "adex": 0, "aagi": 1,
        "aint": 3, "awis": 4, "acha": -5, "mr": 6, "fr": -7,
        "cr": 0, "dr": 8, "pr": -9,
    }


MOBILE_ITEM_SHEET_SCRIPT = r"""
import json
from PySide6.QtCore import QEventLoop, QTimer, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from vantage.helpers.mobile_share import _MOBILE_PAGE

app = QApplication([])
view = QWebEngineView()
view.resize(390, 844)
view.show()
loaded = QEventLoop()
view.loadFinished.connect(loaded.quit)
view.setHtml(_MOBILE_PAGE, QUrl('http://fixture.invalid/'))
QTimer.singleShot(10000, loaded.quit)
loaded.exec()

def run(script, wait=0):
    loop = QEventLoop()
    box = []
    view.page().runJavaScript(script, lambda value: (box.append(value), loop.quit()))
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    if wait:
        pause = QEventLoop()
        QTimer.singleShot(wait, pause.quit)
        pause.exec()
    return box[0] if box else None

detail = {
  'name': 'A Very Long Synthetic Classic EverQuest Item Name That Wraps',
  'status': 'complete', 'source': 'Synthetic fixture',
  'price': 6916, 'posts': 50,
  'flags': ['MAGIC ITEM', 'LORE ITEM', 'NO DROP'],
  'stats': {'dmg': 11, 'dly': 24, 'ac': 15, 'hp': 75, 'mana': 25,
            'astr': 5, 'awis': 10, 'mr': 8, 'fr': -2},
  'properties': {'skill': '1H Blunt', 'weight': '4.0', 'size': 'MEDIUM'},
  'restrictions': {'binding': 'NO DROP', 'era': 'Kunark',
                   'classes': ['SHAMAN', 'CLERIC'], 'races': ['IKSAR'],
                   'slots': ['PRIMARY', 'SECONDARY']},
  'effects': [{'type': 'Proc', 'name': 'Light Strike'}],
  'drops': [{'npc': 'Synthetic golem', 'zone': 'Synthetic ruins'}],
  'related_quests': [{'name': 'Synthetic relic quest'}],
  'stats_text': 'MAGIC ITEM LORE ITEM NO DROP Skill: 1H Blunt DMG: 11 DLY: 24',
  'wiki_url': 'https://wiki.project1999.com/Jade_Mace'
}
run(r'''window.__resolve=null;window.get=()=>new Promise(resolve=>window.__resolve=resolve);
const opener=document.createElement('button');opener.id='fixtureOpener';opener.textContent='Open fixture item';
opener.addEventListener('click',()=>openMarketDetail({name:'Fixture item'}));document.body.append(opener);
opener.focus();opener.click();''')
run('window.__resolve('+json.dumps(detail)+')', 60)

def snapshot():
    return json.loads(run(r'''JSON.stringify({
      first:detailBody.firstElementChild.className,
      second:detailBody.children[1].className,
      terms:Array.from(detailBody.querySelectorAll('dt')).map(e=>e.textContent),
      values:Array.from(detailBody.querySelectorAll('dd')).map(e=>e.textContent),
      flags:Array.from(detailBody.querySelectorAll('.item-flags .chip')).map(e=>e.textContent),
      originalOpen:detailBody.querySelector('.item-original').open,
      details:Array.from(detailBody.querySelectorAll('a')).map(a=>({text:a.textContent,href:a.href})),
      closeHeight:parseFloat(getComputedStyle(detailClose).height),
      docOverflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
      dialogOverflow:detailDialog.scrollWidth>detailDialog.clientWidth,
      bodyOverflow:getComputedStyle(document.body).overflow,
      htmlOverflow:getComputedStyle(document.documentElement).overflow,
      title:detailTitle.textContent,
      status:detailStatus.textContent
    })'''))

sizes = {}
for width, height in ((319, 700), (390, 844), (768, 900)):
    view.resize(width, height)
    QTest.qWait(30)
    sizes[str(width)] = snapshot()

# Missing metadata must not create guessed flags/restrictions.
missing = json.loads(run(r'''detailBody.replaceChildren();
const status=document.createElement('p');appendItemDetail({name:'Plain item',stats:{dmg:2,dly:30},restrictions:{}},status);
JSON.stringify({flags:detailBody.querySelectorAll('.item-flags .chip').length,text:detailBody.textContent})'''))

# Restore the full card and exercise the native Escape close/focus-return path.
run('detailDialog.close();detailBody.replaceChildren();const status=document.createElement("p");appendItemDetail('+json.dumps(detail)+',status);fixtureOpener.focus();detailDialog.showModal();detailClose.focus();')
view.setFocus()
QTest.keyClick(view.focusProxy() or view, Qt.Key.Key_Escape)
QTest.qWait(60)
escape = json.loads(run("JSON.stringify({open:detailDialog.open,active:document.activeElement.id,bodyOverflow:getComputedStyle(document.body).overflow,htmlOverflow:getComputedStyle(document.documentElement).overflow})"))

urls = json.loads(run(r'''JSON.stringify({
  empty:safeWikiUrl('', 'Light Strike'),
  whitespace:safeWikiUrl('   ', 'Light Strike'),
  nullValue:safeWikiUrl(null, 'Light Strike'),
  evil:safeWikiUrl('https://evil.example/x', 'Light Strike'),
  userinfo:safeWikiUrl('https://bad@wiki.project1999.com/x', 'Light Strike'),
  http:safeWikiUrl('http://wiki.project1999.com/x', 'Light Strike'),
  javascript:safeWikiUrl('javascript:alert(1)', 'Light Strike'),
  valid:safeWikiUrl('https://wiki.project1999.com/Light_Strike', 'ignored')
})'''))
print(json.dumps({'sizes': sizes, 'missing': missing, 'escape': escape, 'urls': urls}))
view.close()
app.quit()
"""


def test_mobile_item_sheet_semantics_responsive_links_and_keyboard(tmp_path):
    result = _run(
        MOBILE_ITEM_SHEET_SCRIPT, tmp_path, timeout=55, webengine=True)
    for width in ("319", "390", "768"):
        card = result["sizes"][width]
        assert card["first"] == "item-sheet"
        assert card["second"] == "market-reference"
        assert card["docOverflow"] is False
        assert card["dialogOverflow"] is False
        assert card["bodyOverflow"] == "hidden"
        assert card["htmlOverflow"] == "hidden"
        assert card["closeHeight"] >= 44
        assert card["flags"] == ["MAGIC ITEM", "LORE ITEM", "NO DROP"]
        assert card["originalOpen"] is False
        values = dict(zip(card["terms"], card["values"]))
        assert values["DMG"] == "11"
        assert values["DLY"] == "24"
        assert values["AC"] == "+15"
        assert values["FR"] == "-2"
        links = {row["text"]: row["href"] for row in card["details"]}
        assert links["Light Strike"].endswith("/Light_Strike")
        assert links["Synthetic golem"].endswith("/Synthetic_golem")
        assert links["Synthetic ruins"].endswith("/Synthetic_ruins")
        assert links["Synthetic relic quest"].endswith(
            "/Synthetic_relic_quest")
    assert result["missing"]["flags"] == 0
    assert "NO DROP" not in result["missing"]["text"]
    assert result["escape"]["open"] is False
    assert result["escape"]["active"] == "fixtureOpener"
    assert result["escape"]["bodyOverflow"] != "hidden"
    assert result["escape"]["htmlOverflow"] != "hidden"
    fallback = "https://wiki.project1999.com/Light_Strike"
    for key in ("empty", "whitespace", "nullValue", "evil", "userinfo",
                "http", "javascript"):
        assert result["urls"][key] == fallback
    assert result["urls"]["valid"] == fallback
