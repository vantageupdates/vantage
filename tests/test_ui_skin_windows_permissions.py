"""Publication permissions: only disposable fixtures, never a real game/ACL."""

import ctypes
import os
import stat

import pytest

from vantage.helpers import ui_skin_updater as updater
from tests.test_ui_skin_updater import _release, fixture


@pytest.mark.parametrize("platform_name, expected_mode", [("nt", 0o777), ("posix", 0o700)])
def test_publish_stage_creation_mode_is_platform_specific(platform_name, expected_mode):
    class NewDirectory:
        def __init__(self):
            self.calls = []

        def mkdir(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    path = NewDirectory()
    updater._create_publish_stage(path, platform_name=platform_name)
    # No parents/exist_ok, permission changes, or follow-up mutation is allowed.
    assert path.calls == [((), {"mode": expected_mode})]


def test_install_uses_new_stage_permission_policy(fixture, tmp_path, monkeypatch):
    game, legacy, state = fixture
    seen = []
    real_create = updater._create_publish_stage

    def create(path):
        assert path.parent == game / "uifiles"
        assert path.name.startswith(".vantage-ui-publish-")
        assert not path.exists()
        seen.append(path)
        real_create(path)

    monkeypatch.setattr(updater, "_create_publish_stage", create)
    release = _release(tmp_path, monkeypatch, schema=2)
    updater.install_release(release, game, state, log=lambda _: None)
    assert len(seen) == 1 and not seen[0].exists()
    assert updater.installed_folder(game) == "VantageUI-v1.2.3"
    assert legacy.is_dir()
    # Idempotent reuse must not change creation permissions on the existing UI.
    updater.install_release(release, game, state, log=lambda _: None)
    assert len(seen) == 1


@pytest.mark.parametrize("collision_kind", ["file", "directory"])
def test_publish_stage_collision_is_not_adopted_or_repermissioned(tmp_path, collision_kind):
    path = tmp_path / "existing"
    if collision_kind == "directory":
        path.mkdir()
        content = path / "private.xml"
    else:
        content = path
    content.write_bytes(b"private unchanged data")
    before = (path.stat().st_mode, content.read_bytes(), content.stat().st_mode)
    with pytest.raises(FileExistsError):
        updater._create_publish_stage(path)
    assert (path.stat().st_mode, content.read_bytes(), content.stat().st_mode) == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not Windows DACLs")
def test_real_posix_stage_keeps_private_mode_after_publication(tmp_path):
    stage = tmp_path / "new-stage"
    updater._create_publish_stage(stage)
    assert stat.S_IMODE(stage.stat().st_mode) & 0o077 == 0
    destination = tmp_path / "VantageUI-v1.2.3"
    updater._rename_no_replace(stage, destination)
    assert stat.S_IMODE(destination.stat().st_mode) & 0o077 == 0


class _WindowsSecurity:
    """Create a fresh test directory with an ACL; otherwise read security only."""

    def __init__(self):
        from ctypes import wintypes as wt

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p
        self.kernel.CreateDirectoryW.argtypes = [wt.LPCWSTR, ctypes.c_void_p]
        self.kernel.CreateDirectoryW.restype = wt.BOOL
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wt.LPCWSTR, wt.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wt.BOOL
        self.advapi.GetNamedSecurityInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.advapi.GetNamedSecurityInfoW.restype = wt.DWORD
        self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wt.BOOL
        self.advapi.GetAce.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.POINTER(ctypes.c_void_p)]
        self.advapi.GetAce.restype = wt.BOOL
        self.advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.advapi.ConvertSidToStringSidW.restype = wt.BOOL

    @staticmethod
    def _check(success):
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())

    def create_fixture_directory(self, path):
        # Set permissions only at atomic creation of this new fixture, never on
        # an existing directory. Owner, SYSTEM and admins retain full control;
        # Builtin Users get inheritable read/execute, deliberately not write.
        class SecurityAttributes(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("descriptor", ctypes.c_void_p),
                        ("inherit_handle", ctypes.c_int)]

        assert not path.exists()
        descriptor = ctypes.c_void_p()
        sddl = "D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)"
        self._check(self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None))
        try:
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, 0)
            self._check(self.kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)))
        finally:
            self.kernel.LocalFree(descriptor)

    def read(self, path):
        descriptor, dacl = ctypes.c_void_p(), ctypes.c_void_p()
        error = self.advapi.GetNamedSecurityInfoW(
            str(path), 1, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
        if error:
            raise ctypes.WinError(error)
        try:
            assert dacl.value, "A null DACL would grant unrestricted access"
            sddl = ctypes.c_void_p()
            self._check(self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, 4, ctypes.byref(sddl), None))
            try:
                text = ctypes.wstring_at(sddl)
            finally:
                self.kernel.LocalFree(sddl)
            # ACL header AceCount is a WORD at offset 4. These test ACLs contain
            # ordinary ACCESS_ALLOWED_ACE entries (header, DWORD mask, SID).
            count = ctypes.c_uint16.from_address(dacl.value + 4).value
            entries = []
            for index in range(count):
                ace = ctypes.c_void_p()
                self._check(self.advapi.GetAce(dacl, index, ctypes.byref(ace)))
                ace_type, flags = ctypes.string_at(ace, 2)
                assert ace_type == 0, "Unexpected ACE type in controlled fixture"
                mask = ctypes.c_uint32.from_address(ace.value + 4).value
                sid = ctypes.c_void_p()
                self._check(self.advapi.ConvertSidToStringSidW(ace.value + 8, ctypes.byref(sid)))
                try:
                    entries.append((ctypes.wstring_at(sid), flags, mask))
                finally:
                    self.kernel.LocalFree(sid)
            return text, entries
        finally:
            self.kernel.LocalFree(descriptor)


@pytest.mark.skipif(os.name != "nt", reason="Real Windows DACL inheritance")
@pytest.mark.parametrize("old_folder_mode", [0o700, 0o777])
def test_windows_install_inherits_users_read_execute_without_changing_existing_acls(
        tmp_path, monkeypatch, old_folder_mode):
    security = _WindowsSecurity()
    game = tmp_path / "EverQuest"
    game.mkdir()
    (game / "eqgame.exe").write_bytes(b"fixture, not executable")
    target = game / "uifiles"
    security.create_fixture_directory(target)
    legacy = target / "VantageUI"
    # A legacy/private 0700 ACL (including the old Windows regression) must
    # never be "repaired" as a side effect of creating the new published skin.
    legacy.mkdir(mode=old_folder_mode)
    private_file = legacy / "private.xml"
    private_file.write_bytes(b"unpublished user edits")
    before = {path: security.read(path) for path in (target, legacy, private_file)}
    monkeypatch.setattr(updater, "game_running", lambda: False)
    real_rename = updater._rename_no_replace
    published = []

    def assert_users_rx(path):
        _, entries = security.read(path)
        user_entries = [(flags, mask) for sid, flags, mask in entries if sid == "S-1-5-32-545"]
        assert user_entries, f"Builtin Users read/execute was not inherited by {path.name}"
        assert all(flags & 0x10 for flags, _ in user_entries), "Users ACE must be inherited"
        assert all(mask == 0x1200a9 for _, mask in user_entries), "Users must not gain write access"

    def rename(source, destination):
        if source.name.startswith(".vantage-ui-publish-"):
            assert_users_rx(source)
            before_move = security.read(source)
            real_rename(source, destination)
            assert security.read(destination) == before_move
            published.append(destination)
        else:
            real_rename(source, destination)

    monkeypatch.setattr(updater, "_rename_no_replace", rename)
    for version in ("1.2.3", "1.2.4"):
        release = _release(tmp_path, monkeypatch, version=version, schema=2)
        result = updater.install_release(release, game, tmp_path / "state", log=lambda _: None)
        installed = target / result.folder
        assert_users_rx(installed)
        for filename in ("EQUI_Test.xml", "button.tga", updater.VERSION_MARKER):
            assert_users_rx(installed / filename)
        assert updater.installed_version(game) == version
        assert {path: security.read(path) for path in before} == before
        assert private_file.read_bytes() == b"unpublished user edits"
    assert len(published) == 2
    previous = target / "VantageUI-v1.2.3"
    previous_acl = security.read(previous)
    collision = target / "VantageUI-v1.2.5"
    collision.mkdir(mode=old_folder_mode)
    (collision / "private.xml").write_bytes(b"unmanaged collision")
    collision_acl = security.read(collision)
    release = _release(tmp_path, monkeypatch, version="1.2.5", schema=2)
    with pytest.raises(updater.SkinUpdateError, match="collision"):
        updater.install_release(release, game, tmp_path / "state", log=lambda _: None)
    assert security.read(collision) == collision_acl
    assert (collision / "private.xml").read_bytes() == b"unmanaged collision"
    assert security.read(previous) == previous_acl
    assert {path: security.read(path) for path in before} == before
    assert len(published) == 2
