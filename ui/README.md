# Vantage Companion UI for EverQuest

A dark graphite, restrained-gold EverQuest skin, maintained alongside Vantage.
This is a source snapshot of the user-provided `rustle2` derivative, not a copy
of the game, a new layout profile, or a replacement for the client default UI.
Read [the asset notices](THIRD-PARTY-NOTICES.md) before redistribution.

## One live skin

The canonical editing and installation location remains:

`C:\Program Files (x86)\Sony\EverQuest\uifiles\VantageUI`

Make visual changes there and export the reviewed files to `ui/skin`. Do not
create another numbered skin, change character INIs, or modify another skin.
All XML and image files belong directly in the skin folder, without another
nested skin directory. The matching Titanium/Project 1999 client default skin
is still required for inherited resources; this is not a modern Live-client UI.

The latest conservative pass restores opaque native window backgrounds after
the transparent-background experiment failed in game. Spell spacing, subdued
outlines, inset icons, and dark surfaces are retained where compatible. Offline
checks are not a game-rendering certification: this snapshot still needs an
in-game reload and visual/interaction verification.

## Reviewed export and release

From the repository root, explicitly export the live source and build the
transport assets:

```powershell
python scripts/package_ui_skin.py --sync-from "C:\Program Files (x86)\Sony\EverQuest\uifiles\VantageUI"
```

Without `--sync-from`, packaging only reads the repository snapshot:

```powershell
python scripts/package_ui_skin.py
python -m pytest tests/test_ui_skin_package.py
python -m pytest
```

The exporter preserves filename case and exact file bytes. It only selects flat
`.xml`, `.tga`, `.png`, `.bmp`, `.jpg`, `.jpeg`, and `.dds` assets. It never exports
INIs, logs, account settings, saved positions, executables, or nested directories.
The source's cursor `.cur` files and historical install notes are excluded;
none of the exported XML directly references a `.cur` filename. The curated
repository folder rejects unexpected files rather than silently publishing them.

Review the resulting Git diff and asset changes before publishing. Increment the
patch version in `ui/release.json` together with every other embedded Vantage
version; never reuse a published version/tag. Follow the repository's
[release policy](../AGENTS.md): complete tests, portable build and self-test,
then publish the tested Vantage executable and these companion assets on the
same reviewed stable `vX.Y.Z` GitHub Release in `vantageupdates/vantage`. Verify
the public asset sizes and GitHub SHA-256 digests against the tested artifacts.
An arbitrary source push must not automatically publish unreviewed UI updates.

The generated files in ignored `dist/ui` are internal updater transport, not
an additional user-facing ZIP delivery:

- `VantageUI-manifest.json`: schema 1, stable version, canonical skin folder, and
  each flat file's exact name, byte size, and SHA-256.
- `VantageUI-payload.zip`: deterministic entries, timestamps and permissions;
  its entries exactly match the manifest, with no nested skin or self-manifest.

Limits: 2,000 files, 32 MiB per file, 256 MiB total. XML is checked for basic
well-formedness; DTD/entity declarations are rejected. This does not claim all
client references resolve independently of the installed default UI or that the
game accepts the rendering. Hashes establish byte integrity, not publisher
identity: the updater must also trust only the reviewed official release source.

## Standalone updater and later Vantage integration

`VantageUI-Updater.exe` is a separate, small Windows application. It does not
replace or launch Vantage, install a startup service, or close the game. Select
the folder containing `eqgame.exe`, check for an official UI release, then update
or restore. Automatic updates are opt-in and run every five minutes only while
the updater window remains open. A running `eqgame.exe` defers automatic updates.
Close the updater to stop polling. Administrator rights may be needed for a
Program Files installation; use Windows' normal Run as administrator action
after a permission error. The updater never changes parent folder permissions.

Source launch and independent build:

```powershell
$env:PYTHONPATH = "$PWD/src"
python vantage_ui_updater.py
python -m PyInstaller --noconfirm vantage_ui_updater.spec
.\dist\VantageUI-Updater.exe --self-test --report "$PWD/dist/ui-updater-self-test.json"
```

Publish `VantageUI-Updater.exe`, the UI manifest and transport payload alongside
the required `Vantage.exe`. The frontend uses only Python's standard library and
Tk, without bundling another Qt runtime. Settings, logs/backup metadata belong in
`%LOCALAPPDATA%\Vantage\UIUpdater`; the skin remains `uifiles\VantageUI`.
Backups are retained outside the game so a failed/interrupted transaction can
be recovered. Recovery checks for later edits and stops rather than overwriting
them. Never delete recovery metadata while an operation is pending.

For integration, reuse `vantage.helpers.ui_skin_updater` and call its blocking
operations on a worker thread, keeping the host UI responsive:

- `check_release()` returns the verified release selection.
- `installed_version(eq_dir)` reads the skin marker, not the Vantage version.
- `install_release(release, eq_dir, state_dir, log=...)` stages and verifies first.
- `rollback_last(eq_dir, state_dir, log=...)` restores the previous transaction.
- `recover_pending(eq_dir, state_dir, log=...)` handles interrupted operations.
- `game_running()` is a read-only process check; failure refuses installation.

Discovery can look past a newer main-app-only release to find the newest stable
UI release (at most 40 recent releases). A release advertising an incomplete or
invalid UI payload is an error, not silently skipped. Keep publishing both UI
assets together whenever the skin changes.

Use the same state directory for the standalone and integrated updater. Respect
its per-target lock and pending-recovery ownership. Do not bypass checks or add
a second updater engine. Filesystem recovery is not a whole-folder atomic swap,
and a process probe cannot prevent somebody from launching EQ immediately after
the check; keep the game closed through completion. The downloaded EXE itself
is not self-replaced by this UI asset updater. A future host integration can
reuse the core without ever executing the skin payload.

## In-game check

After applying an update to the same skin, reload:

```text
/loadskin VantageUI 1
```

Check opaque chat/player/group/target backgrounds on bright terrain, all eight
spell names/icons, hover/casting/cooldown, buff slots, spellbook page turning and
memorizing, and bag interactions. Record actual `UIErrors.txt` from that client
only when troubleshooting; never commit that log or character settings. The
updater must preserve other skins, character layouts, and running applications,
and must not assume file validation alone proves the visual result.
