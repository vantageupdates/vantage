# Vantage Companion UI for EverQuest

A dark graphite, restrained-gold EverQuest skin, maintained alongside Vantage.
This is a source snapshot of the user-provided `rustle2` derivative, not a copy
of the game, a new layout profile, or a replacement for the client default UI.
Read [the asset notices](THIRD-PARTY-NOTICES.md) before redistribution.

## Source skin and versioned installations

Until an explicit source migration is approved, the canonical editing location
remains the existing legacy folder:

`C:\Program Files (x86)\Sony\EverQuest\uifiles\VantageUI`

Make visual changes there and export the reviewed files to `ui/skin`. The legacy
`VantageUI` folder is preserved in place; the updater must never rename, replace,
prune, or adopt it. Every delivered version must be exported to this repository
and published through the independent UI update channel. Install the same
verified release locally; do not hand off a separate unmanaged local-only copy.
New releases install beside the source as
`VantageUI-v<major.minor.patch>`, for example `VantageUI-v1.44.66`. All XML and
image files remain directly inside each skin folder, without another nested skin
directory. Neither packaging nor updating changes character INIs or another
skin. The matching Titanium/Project 1999 client default skin is still required
for inherited resources; this is not a modern Live-client UI.

The current polished live source was exported byte for byte into `ui/skin`:
176 flat XML/image assets, with private updater state, cursors, and historical
notes excluded. The export does not modify the live source. Its reviewed changes
include darker opaque surfaces, consistent fine gold slot/control borders,
softly raised spell gems and buttons, native40px equipment/bag columns in a
306x302 HotButton panel, separated Camp/Sit/Walk buttons, segmented LED-green
health bars with yellow/orange/red thresholds, and restored native containers.
Keep future exports explicit and review
their asset diffs before packaging or publication.

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
independent UI patch version in `ui/release.json`; update the canonical
`EQUI_HotButtonWnd.xml` label `HB_VantageVersionLabel` to exactly
`VantageUI  v<version>` before exporting. Packaging rejects an absent, duplicate,
or mismatched visible version tab. Never reuse a published UI
version or tag. A UI-only release does not increment Companion and does not build
or publish `Vantage.exe`. After focused and complete tests, coordinate publication
of the updater and both transport assets on a reviewed
`vantage-ui-v<major.minor.patch>` tag in `vantageupdates/vantage`. For this
candidate the tag is `vantage-ui-v1.44.66`. Verify public asset sizes and
SHA-256 digests against the tested artifacts. An arbitrary source push must not
automatically publish an unreviewed UI update. The repository
[release policy](../AGENTS.md) records the separation between Companion and UI
releases.

Companion's VantageUI integration consumes this independent release channel.
This source-level integration does not authorize or require publishing a new
`Vantage.exe` with an independent UI release. The UI build script builds only
the UI updater; it must not rebuild Companion or change its Latest release.

The generated files in ignored `dist/ui` are internal updater transport, not
an additional user-facing ZIP delivery:

- `VantageUI-manifest.json`: schema 2, stable UI version, the exact matching
  `VantageUI-v<version>` folder, and each flat file's name, byte size, and SHA-256.
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
the updater window remains open. By default EverQuest must be closed; an update
attempt reports the block and can be retried after the game closes. The explicit
`--allow-game-running` mode may publish a new version folder while EverQuest is
open, but cleanup is always deferred until the game closes. Close the updater to
stop polling. Administrator rights may be needed for a Program Files
installation; use Windows' normal Run as administrator action after a permission
error. The updater never changes parent folder permissions.

Source launch and independent build:

```powershell
$env:PYTHONPATH = "$PWD/src"
python vantage_ui_updater.py
python -m PyInstaller --noconfirm vantage_ui_updater.spec
.\dist\VantageUI-Updater.exe --self-test --report "$PWD/dist/ui-updater-self-test.json"
```

For an independent UI release, publish `VantageUI-Updater.exe`, the UI manifest,
and the transport payload without publishing `Vantage.exe`. The frontend uses
only Python's standard library and Tk, without bundling another Qt runtime.
Settings and external download state belong in
`%LOCALAPPDATA%\Vantage\UIUpdater`; released skins live in sibling folders such
as `uifiles\VantageUI-v1.44.66`. Shared managed-version state is stored beside
them in `uifiles\.vantage-ui-registry.json`, with the namespace lock
`uifiles\.vantage-ui-update.lock`. The legacy `uifiles\VantageUI` folder remains
untouched.

The updater records one active managed version and one previous managed version;
both selections are retained even when a user later edits their files. “Active”
means the updater's selection; it does not mean EverQuest has loaded that folder.
Only older registered cleanup candidates whose complete contents still match
their recorded release may be deleted. A modified registered candidate is
retained with a warning. Unmanaged directories are not adopted, inspected, or
pruned. Links, junctions and other reparse points are never adopted or pruned.
Pruning is deferred while EverQuest is open. Rollback first verifies that the
previous target is pristine, then selects it without overwriting either version's
files; if verification fails, rollback refuses safely. Recovery checks for later
edits and stops rather than overwriting them. Never delete shared registry state
while an operation is pending.

For integration, reuse `vantage.helpers.ui_skin_updater` and call its blocking
operations on a worker thread, keeping the host UI responsive:

- `check_release()` returns the verified release selection.
- `installed_folder(eq_dir)` returns the folder in the shared, verified updater
  selection.
- `installed_version(eq_dir)` derives the UI version from that shared, verified
  selection, not from a skin marker or the Companion version.
- `loadskin_command(eq_dir)` returns the manual command for the selected folder.
- `install_release(release, eq_dir, state_dir, log=...)` stages and verifies a
  new versioned sibling folder first.
- `rollback_last(eq_dir, state_dir, log=...)` selects the retained previous
  version without rewriting its files, or refuses if that target was modified.
- `recover_pending(eq_dir, state_dir, log=...)` handles interrupted operations.
- `game_running()` is a read-only process check; failure refuses installation.

Discovery can look past main-app-only releases to find the newest stable,
independently tagged UI release (at most 40 recent releases). A release
advertising an incomplete or invalid UI payload is an error, not silently
skipped. Keep publishing both UI assets together whenever the skin changes.

Standalone and integrated callers coordinate through the shared registry and
namespace lock in `uifiles`, even when their settings and external-download state
directories differ. Respect that lock and pending-recovery ownership. Do not
bypass checks or add a second updater engine. A process probe cannot prevent
somebody from launching EQ immediately after the check; keep the game closed
through installation and pruning unless using the explicit game-running mode,
which always defers pruning. The downloaded EXE itself is not self-replaced by
this UI asset updater. Host integration can reuse the core without ever executing
the skin payload.

## In-game check

After installation, the updater shows the exact folder name and provides a
copyable command. Load the new version manually, for example:

```text
/loadskin VantageUI-v1.44.66 1
```

The updater never writes character INIs or changes EverQuest's selected skin.
Loading the new folder and returning to an older one are explicit in-game user
actions.

Check opaque chat/player/group/target backgrounds on bright terrain, all eight
spell names/icons, hover/casting/cooldown, buff slots, spellbook page turning and
memorizing, and bag interactions. Record actual `UIErrors.txt` from that client
only when troubleshooting; never commit that log or character settings. The
updater must preserve other skins, character layouts, and running applications,
and must not assume file validation alone proves the visual result.

Known client limits for this polish: the attack rim has corrected geometry and
transparent rounded edges, but Titanium controls its final red tint; forcing a
green source texture could make it invisible. Casting-bar color cannot be bound
to the active spell's school with the verified XML interface. It now uses the
health palette in countdown order: red at cast start, through orange/yellow,
then green during the final fifth. The compact inventory stays fixed-size because SIDL has no
minimum-size constraint to prevent clipping its native item controls. The known
pre-existing `IW_Stats` reference remains; this pass adds no missing references.

Version 1.44.54 fixes Windows publish-folder creation after elevation. New
published folders inherit the parent directory's normal access permissions;
the updater does not edit parent ACLs or permissions of existing versions.
This avoids Python 3.13's private Windows ACL for `mkdir(mode=0o700)` persisting
after staging is renamed. Private download directories remain private. Verify
the installed files and selected version from the normal user's session after
an elevated install, not only from the administrator's session. Existing
1.44.53 folders remain unchanged; load the latest published folder instead.
