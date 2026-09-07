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


def test_live_embedded_window_forwards_explicit_opt_in(window, monkeypatch):
    window.allow_game_running = True
    window.release = SimpleNamespace(version='1.44.51')
    prompts = []
    monkeypatch.setattr(
        window, '_confirm',
        lambda title, text: prompts.append((title, text)) or True)
    calls = []
    monkeypatch.setattr(
        gui.updater, 'install_release',
        lambda *args, **kwargs: calls.append((args, kwargs)) or
        SimpleNamespace(version='1.44.51'))
    def immediate(action, callback):
        assert action == 'install'
        callback()
    monkeypatch.setattr(window, '_work', immediate)
    window.install()
    assert calls[0][1]['allow_game_running'] is True
    assert calls[0][1]['progress'] == window.worker_progress
    assert '/loadskin VantageUI-v1.44.51 1' in prompts[0][1]
    assert 'No recargues' in prompts[0][1]


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


def test_check_error_does_not_start_auto_or_raise_unbound_local(window, monkeypatch):
    window.busy = True
    window.automatic.set(True)
    starts = []
    monkeypatch.setattr(window, 'install', lambda *args, **kwargs: starts.append(
        (args, kwargs)))
    window.events.put(('error', 'check', OSError('network unavailable')))
    window._pump()
    assert not window.busy
    assert starts == []
    assert window.progress_value.get() < 100
    assert 'No se completó' in window.status.get()


def test_automatic_update_starts_live_install_without_waiting(window,monkeypatch):
    window.busy=True
    window.automatic.set(True)
    calls=[]
    monkeypatch.setattr(window,'_work',lambda *args:calls.append(args))
    release=SimpleNamespace(version='1.44.51')
    window.events.put(('done','check',(release,('1.44.50','VantageUI-v1.44.50'))))
    window._pump()
    assert calls and calls[0][0] == 'install'
    assert not window.pending


def test_switching_auto_off_cancels_pending(window,monkeypatch):
    window.pending=True
    window.automatic.set(False)
    calls=[]
    monkeypatch.setattr(window,'_work',lambda *args:calls.append(args))
    window.toggle_auto()
    window._pump()
    assert not window.pending and not calls


def test_local_selection_uses_one_folder_read(monkeypatch):
    reads = []
    monkeypatch.setattr(gui.updater, 'installed_folder', lambda eq: reads.append(eq) or 'VantageUI-v1.44.52')
    monkeypatch.setattr(gui.updater, 'installed_version', lambda eq: pytest.fail('Second, racy selection read'))
    assert gui.local_selection('fixture') == ('1.44.52', 'VantageUI-v1.44.52')
    assert reads == ['fixture']


def test_unknown_selection_has_no_copyable_command(window, monkeypatch):
    monkeypatch.setattr(gui.updater, 'installed_folder', lambda eq: '')
    assert gui.local_selection('fixture') == ('', '')
    assert str(window.copy_button['state']) == 'disabled'
    copied = []
    monkeypatch.setattr(window.root, 'clipboard_append', copied.append)
    window.copy_command()
    assert copied == []


def test_copy_uses_installed_folder_not_available_release(window, monkeypatch):
    window.events.put(('done', 'check', (SimpleNamespace(version='1.44.53'), ('1.44.52', 'VantageUI-v1.44.52'))))
    window._pump()
    copied = []
    monkeypatch.setattr(window.root, 'clipboard_clear', lambda: None)
    monkeypatch.setattr(window.root, 'clipboard_append', copied.append)
    window.copy_button.invoke()
    assert copied == ['/loadskin VantageUI-v1.44.52 1']
    assert 'VantageUI-v1.44.53' in window.destination.get()


def test_rollback_command_uses_previous_folder(window, monkeypatch):
    window.release = SimpleNamespace(version='1.44.54')
    window.events.put(('done', 'restore', gui.updater.InstallResult('1.44.52', 0, 'restored', 'VantageUI-v1.44.52')))
    window._pump()
    assert window.command.get() == '/loadskin VantageUI-v1.44.52 1'
    assert str(window.copy_button['state']) == 'normal'


def test_path_edit_immediately_invalidates_release_and_command(window):
    window.events.put(('done', 'local', ('1.44.52', 'VantageUI-v1.44.52')))
    window._pump()
    window.release = SimpleNamespace(version='1.44.53')
    window.eq.set('C:/different-EverQuest')
    assert window.folder == window.installed == ''
    assert window.release is None
    assert str(window.copy_button['state']) == 'disabled'
    assert str(window.install_button['state']) == 'disabled'
    assert '/loadskin' not in window.command.get()


def test_completion_for_old_path_does_not_publish_stale_command(window):
    window.operation_eq = window.eq.get()
    window.busy = True
    window.eq.set('C:/another-EverQuest')
    window.events.put(('done', 'install', gui.updater.InstallResult('1.44.52', 10, 'installed', 'VantageUI-v1.44.52')))
    window._pump()
    assert not window.busy and not window.folder
    assert str(window.copy_button['state']) == 'disabled'
    assert 'carpeta anterior' in window.status.get()


def test_operation_and_error_disable_copy(window, monkeypatch):
    window.events.put(('done', 'local', ('1.44.52', 'VantageUI-v1.44.52')))
    window._pump()
    window.busy = True
    window._controls()
    assert str(window.copy_button['state']) == 'disabled'
    window.events.put(('error', 'check', OSError('fixture network failure')))
    window._pump()
    assert not window.folder and str(window.copy_button['state']) == 'disabled'


def test_retention_warning_does_not_report_install_failure(window):
    warning = 'Modified older folder preserved.'
    window.events.put(('done', 'install', gui.updater.InstallResult('1.44.52', 10, 'installed', 'VantageUI-v1.44.52', (warning,))))
    window._pump()
    assert warning in window.logbox.get('1.0', 'end')
    assert 'pendiente' in window.status.get()
    assert window.command.get() == '/loadskin VantageUI-v1.44.52 1'
    assert window.progress_value.get() == 100


def test_auto_hint_matches_game_running_policy(window, tk_master, tmp_path):
    assert 'Cierra EverQuest' in window.auto_hint.cget('text')
    root = tk.Toplevel(tk_master)
    root.withdraw()
    try:
        app = gui.SkinWindow(root, settings_dir=tmp_path, test_mode=True, allow_game_running=True)
        assert 'Puede instalar con EQ abierto' in app.auto_hint.cget('text')
        assert 'limpieza espera' in app.auto_hint.cget('text')
    finally:
        root.destroy()


def test_minimum_window_keeps_versions_wrapped_status_and_log_visible(tk_master, tmp_path):
    root = tk.Toplevel(tk_master)
    root.withdraw()
    root.attributes('-alpha', 0.0)
    try:
        app = gui.SkinWindow(root, settings_dir=tmp_path, test_mode=True)
        app.folder = 'VantageUI-v1.44.52'
        app.installed = '1.44.52'
        app.release = SimpleNamespace(version='1.44.53')
        app._version_text()
        app.status.set(
            'Estado detallado: la carpeta seleccionada permanece intacta mientras '
            'se verifica la próxima versión disponible en el servidor oficial.')
        log_line = 'Registro esencial visible en el tamaño mínimo.'
        app._log(log_line)
        root.geometry('720x650+10000+10000')
        root.deiconify()
        root.update_idletasks()
        root.update()

        outer = root.winfo_children()[0]
        labels = [widget for widget in outer.winfo_children()
                  if widget.winfo_class() == 'TLabel']
        destination_label = next(
            widget for widget in labels
            if str(widget.cget('textvariable')) == str(app.destination))
        status_label = next(
            widget for widget in labels
            if str(widget.cget('textvariable')) == str(app.status))
        log_index = app.logbox.search(log_line, '1.0', 'end')

        assert (root.winfo_width(), root.winfo_height()) == (720, 650)
        assert 'Seleccionada: VantageUI-v1.44.52' in app.destination.get()
        assert 'Próxima instalación: uifiles\\VantageUI-v1.44.53' in app.destination.get()
        assert destination_label.winfo_ismapped()
        assert status_label.winfo_ismapped() and status_label.winfo_height() > 24
        assert log_index and app.logbox.dlineinfo(log_index) is not None
    finally:
        root.destroy()
