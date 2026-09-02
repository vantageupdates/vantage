from vantage.helpers.game_capture import GAME_IMAGE_PROFILES, GameWindowCapture


def test_window_scoring_accepts_only_eq_or_eq_labelled_wineq_surfaces():
    target = r"C:\Games\EverQuest\eqgame.exe"
    score = GameWindowCapture._window_match_score

    assert score(target, "eqgame.exe", "EverQuest", target, True) == 3_000_000
    assert score("", "eqgame.exe", "Mindflux", target, True) == 1_000_000
    assert score(
        r"C:\WinEQ2\WinEQ2.exe", "wineq2.exe",
        "EverQuest · Mindflux · WinEQ2", target, True) == 750_000
    assert score(
        r"C:\WinEQ2\WinEQ2.exe", "wineq2.exe",
        "EverQuest · Mindflux · WinEQ2", target, False) == 0
    assert score(
        r"C:\WinEQ2\WinEQ2.exe", "wineq2.exe",
        "WinEQ2 Control Panel", target, True) == 0
    assert score(
        r"C:\Windows\notepad.exe", "notepad.exe",
        "EverQuest notes", target, True) == 0


def test_wineq_foreground_title_pair_accepts_wrapper_on_either_side():
    pair = GameWindowCapture._wineq_title_pair_is_game
    assert pair("EverQuest", "EverQuest · WinEQ2") is True
    assert pair("EverQuest · WinEQ2", "EverQuest") is True
    assert pair("EverQuest", "EverQuest") is True
    assert pair("EverQuest", "Browser") is False
    assert pair("WinEQ2 Control Panel", "EverQuest · WinEQ2") is False


def test_public_focus_probe_uses_discovered_eq_or_wineq_surface():
    capture = object.__new__(GameWindowCapture)
    capture._supported = True
    capture._find_window = lambda: (123, "EverQuest · WinEQ2")
    capture._game_is_foreground = lambda hwnd: hwnd == 123
    assert capture.is_game_foreground() is True

    capture._find_window = lambda: (0, "")
    assert capture.is_game_foreground() is False


def test_live_view_quality_profiles_are_crisp_bounded_and_switchable():
    capture = GameWindowCapture(profile="hd")
    status = capture.status()
    assert status["image_quality"] == "hd"
    assert status["max_width"] == 1920
    assert status["jpeg_quality"] == 86

    assert capture.set_image_profile("native") == "native"
    status = capture.status()
    assert status["image_quality_label"] == "Native detail"
    assert status["max_width"] == 2560
    assert status["jpeg_quality"] == 91
    assert set(GAME_IMAGE_PROFILES) == {"efficient", "hd", "native"}
