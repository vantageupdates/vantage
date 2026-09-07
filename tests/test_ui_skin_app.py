import json
import subprocess
import sys
from types import SimpleNamespace
import tkinter as tk
import pytest
from vantage import ui_skin_app as gui
from vantage.ui_skin_app import load_settings, update_available, version_key


def test_automatic_updates_are_opt_in(tmp_path):
    assert load_settings(tmp_path/'none.json')['automatic'] is False


def test_settings_validate_types(tmp_path):
    path=tmp_path/'settings.json'
    path.write_text(json.dumps({'eq_dir':42,'automatic':'true'}))
    assert load_settings(path)['automatic'] is False
    assert isinstance(load_settings(path)['eq_dir'], str)


def test_update_version_order():
    assert update_available('', '1.44.51')
    assert update_available('1.9.9', '1.10.0')
    assert not update_available('1.44.51', '1.44.49')
    assert not update_available('1.44.51', '1.44.51')
    assert not update_available('', '')
    assert version_key('invalid') == (0,0,0)


def test_portable_ui_contract_is_offline():
    completed=subprocess.run([sys.executable,'-m','vantage.ui_skin_app','--self-test'],
                             check=True,capture_output=True,text=True,timeout=30)
    result=json.loads(completed.stdout.strip())
    assert result['status']=='PASS'
    assert result['network'] is result['live_skin_writes'] is False


def test_main_accepts_embedded_entrypoint_arguments(monkeypatch, capsys):
    monkeypatch.setattr(
        gui, 'self_test',
        lambda: {'status': 'PASS', 'version': '1.44.51', 'network': False,
                 'live_skin_writes': False})
    assert gui.main(['--self-test']) == 0
    assert json.loads(capsys.readouterr().out)['version'] == '1.44.51'


def test_frozen_companion_uses_bundled_release_metadata(tmp_path, monkeypatch):
    (tmp_path / 'release.json').write_text(
        json.dumps({'version': '1.44.51'}), encoding='utf-8')
    monkeypatch.setattr(gui.sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setattr(gui.sys, 'frozen', True, raising=False)
    assert gui.app_version() == '1.44.51'


@pytest.fixture(scope='module')
def tk_master():
    root=tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def window(tmp_path,tk_master):
    root=tk.Toplevel(tk_master)
    root.withdraw()
    app=gui.SkinWindow(root,settings_dir=tmp_path,test_mode=True)
    yield app
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_unwritable_settings_pause_auto_and_do_not_prevent_close(window, monkeypatch):
    window.automatic.set(True)
    window.pending=True
    def fail(*args,**kwargs):
        raise PermissionError('fixture denied')
    monkeypatch.setattr(gui.os,'replace',fail)
    assert window._save() is False
    assert not window.automatic.get() and not window.pending
    assert 'configuración' in window.status.get()
    window.close()


def test_cancel_dialog_suspends_automatic_work(window,monkeypatch):
    window.release=SimpleNamespace(version='1.44.51')
    window.automatic.set(True)
    window.pending=True
    window.next_check=0
    calls=[]
    monkeypatch.setattr(window,'_work',lambda *args: calls.append(args))
    def cancel(*args,**kwargs):
        assert window.confirming
        window._pump()
        assert not calls
        return False
    monkeypatch.setattr(gui.messagebox,'askokcancel',cancel)
    window.install()
    assert not calls and not window.confirming
    assert not window.automatic.get() and not window.pending


def test_restore_confirmation_does_not_lose_action_to_auto_tick(window,monkeypatch):
    window.automatic.set(True)
    window.pending=True
    calls=[]
    monkeypatch.setattr(window,'_work',lambda *args: calls.append(args))
    def accept(*args,**kwargs):
        window._pump()
        assert not calls
        return True
    monkeypatch.setattr(gui.messagebox,'askokcancel',accept)
    window.restore()
    assert [c[0] for c in calls] == ['restore']
    assert not window.automatic.get()


def test_error_reenables_controls_and_clears_pending(window):
    window.busy=True
    window.pending=True
    window.events.put(('error','install',PermissionError('fixture denied')))
    window._pump()
    assert not window.busy and not window.pending
    assert str(window.check_button['state'])=='normal'
    assert 'administrador' in window.logbox.get('1.0','end')


def test_running_game_defers_automatic_install(window,monkeypatch):
    window.busy=True
    window.pending=True
    window.automatic.set(True)
    calls=[]
    monkeypatch.setattr(window,'_work',lambda *args:calls.append(args))
    window.events.put(('done','wait',True))
    window._pump()
    assert window.pending and not calls
    assert 'esperando' in window.status.get()


def test_switching_auto_off_cancels_pending(window,monkeypatch):
    window.pending=True
    window.automatic.set(False)
    calls=[]
    monkeypatch.setattr(window,'_work',lambda *args:calls.append(args))
    window.toggle_auto()
    window._pump()
    assert not window.pending and not calls
