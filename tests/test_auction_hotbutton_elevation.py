import json
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from vantage.helpers.auction_hotbutton import (
    elevated_hotbutton_command, process_elevated_hotbutton_request)
from vantage.helpers import config
import vantage.parsers.market as market_module
from vantage.parsers.market import AuctionComposer, GearItem


def _app():
    return QApplication.instance() or QApplication([])


def test_elevated_helper_installs_and_reports_hotbutton(tmp_path):
    request_dir = tmp_path / "hotbutton-requests"
    request_dir.mkdir()
    ini = tmp_path / "Etsy_P1999Green.ini"
    ini.write_text("[Socials]\n", encoding="cp1252")
    original = ini.read_bytes()
    nonce = "verified-nonce"
    request = request_dir / ("hotbutton-" + "a" * 32 + ".json")
    request.write_text(json.dumps({
        "schema": 1,
        "nonce": nonce,
        "ini_path": str(ini),
        "trade_type": "WTS",
        "lines": ["WTS Manastone 80k PST"],
        "hotbar_page": 3,
        "hotbar_button": 6,
    }), encoding="utf-8")

    assert process_elevated_hotbutton_request(request, nonce) == 0

    result = json.loads(
        request.with_suffix(".result.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["slots"] == ["Page2Button1"]
    assert result["hotbar_slots"] == ["Page3Button6"]
    assert Path(result["backup"]).read_bytes() == original
    assert "Page2Button1Line1=/auction WTS Manastone 80k PST" in (
        ini.read_text(encoding="cp1252"))
    assert "Page3Button6=E10" in ini.read_text(encoding="cp1252")
    assert not request.exists()


def test_elevated_command_uses_one_shot_mode_before_single_instance(tmp_path):
    executable = tmp_path / "Vantage.exe"
    executable.write_bytes(b"candidate")
    request = tmp_path / ("hotbutton-" + "b" * 32 + ".json")

    program, arguments = elevated_hotbutton_command(
        request, "nonce", current_executable=executable, frozen=True)

    assert program == str(executable.resolve())
    assert "--install-auction-hotbuttons" in arguments
    assert str(request.resolve()) in arguments
    assert "nonce" in arguments


def test_composer_retries_permission_denial_through_uac(monkeypatch, tmp_path):
    _app()
    eq_root = tmp_path / "EverQuest"
    logs = eq_root / "Logs"
    logs.mkdir(parents=True)
    ini = eq_root / "Etsy_P1999Green.ini"
    ini.write_text("[Socials]\n", encoding="cp1252")
    request = tmp_path / "hotbutton-request.json"
    result = tmp_path / "hotbutton-result.json"
    pending = SimpleNamespace(
        request_path=request, result_path=result, nonce="nonce")
    previous_logs = config.data.setdefault("general", {}).get("eq_log_dir", "")
    previous_page = config.data.setdefault("market", {}).get(
        "auction_hotbar_page", 1)
    previous_button = config.data["market"].get("auction_hotbar_button", 1)
    try:
        monkeypatch.setattr(config, "save", lambda: None)
        monkeypatch.setattr(market_module, "everquest_running", lambda: False)
        config.data["general"]["eq_log_dir"] = str(logs)
        composer = AuctionComposer()
        composer.set_catalog([GearItem("Manastone", id=6040, peqId=13401)])
        composer.item_search.setText("Manastone")
        assert composer.add_search_item()
        composer.hotbar_page.setCurrentIndex(3)
        composer.hotbar_button_number.setCurrentIndex(6)
        composer.camped_out.setChecked(True)
        monkeypatch.setattr(
            market_module, "install_auction_hotbuttons",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                PermissionError(13, "Permission denied", str(ini))))
        monkeypatch.setattr(
            market_module, "request_elevated_hotbutton_install",
            lambda *_args, **_kwargs: pending)
        monkeypatch.setattr(
            market_module, "read_elevated_hotbutton_result",
            lambda _pending: {
                "ok": True,
                "trade_type": "WTS",
                "slots": ["Page2Button1"],
                "hotbar_slots": ["Page1Button1"],
                "backup": str(ini) + ".vantage-backup",
            })

        assert composer.install_hotbuttons() is True
        assert "approve the UAC prompt" in composer.preview_status.text()
        assert not composer.hotbutton_button.isEnabled()

        composer._poll_elevated_hotbutton_install()

        assert "Installed WTS" in composer.preview_status.text()
        assert not composer.camped_out.isChecked()
        composer.close()
    finally:
        config.data["general"]["eq_log_dir"] = previous_logs
        config.data["market"]["auction_hotbar_page"] = previous_page
        config.data["market"]["auction_hotbar_button"] = previous_button


def test_composer_queues_until_everquest_fully_closes(monkeypatch, tmp_path):
    _app()
    eq_root = tmp_path / "EverQuest"
    logs = eq_root / "Logs"
    logs.mkdir(parents=True)
    ini = eq_root / "Etsy_P1999Green.ini"
    ini.write_text("[HotButtons]\n\n[Socials]\n", encoding="cp1252")
    states = iter((True, False))
    calls = []
    previous_logs = config.data.setdefault("general", {}).get("eq_log_dir", "")
    previous_page = config.data.setdefault("market", {}).get(
        "auction_hotbar_page", 1)
    previous_button = config.data["market"].get("auction_hotbar_button", 1)
    try:
        monkeypatch.setattr(config, "save", lambda: None)
        config.data["general"]["eq_log_dir"] = str(logs)
        monkeypatch.setattr(
            market_module, "everquest_running", lambda: next(states))
        monkeypatch.setattr(
            market_module, "install_auction_hotbuttons",
            lambda *args: calls.append(args) or (
                ("Page2Button1",), ("Page1Button1",),
                Path(str(ini) + ".vantage-backup")))
        composer = AuctionComposer()
        composer.set_catalog([GearItem("Manastone", id=6040, peqId=13401)])
        composer.item_search.setText("Manastone")
        assert composer.add_search_item()
        composer.hotbar_page.setCurrentIndex(3)
        composer.hotbar_button_number.setCurrentIndex(6)
        composer.camped_out.setChecked(True)

        assert composer.install_hotbuttons() is True
        assert not calls
        assert "Queued WTS" in composer.preview_status.text()
        assert not composer.hotbutton_button.isEnabled()

        composer._install_queued_hotbutton_when_game_closes()

        assert len(calls) == 1
        assert calls[0][0] == str(ini)
        assert calls[0][3:] == (4, 7)
        assert "Installed WTS" in composer.preview_status.text()
        assert not composer.camped_out.isChecked()
        composer.close()
    finally:
        config.data["general"]["eq_log_dir"] = previous_logs
        config.data["market"]["auction_hotbar_page"] = previous_page
        config.data["market"]["auction_hotbar_button"] = previous_button
