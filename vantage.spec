# -*- mode: python -*-

from pathlib import Path
import sys

block_cipher = None

# Package every non-map asset, but only map files reachable through the P99
# zone index. Brewall's *_2 vector-font sheets and unrelated modern zones add
# weight and create no usable Vantage screen.
map_root = Path('data/maps/map_files')
map_keys = Path('data/maps/map_keys.ini')
zone_files = {
    line.split('=', 1)[1].strip().casefold()
    for line in map_keys.read_text(encoding='utf-8').splitlines()
    if '=' in line
}
data = []
for source in Path('data').rglob('*'):
    if not source.is_file():
        continue
    if source.parent == map_root:
        stem = source.stem.casefold()
        if not any(
                stem == zone or
                (stem.startswith(zone + '_') and
                 stem[len(zone) + 1:].isdigit() and
                 not stem.endswith('_2'))
                for zone in zone_files):
            continue
    data.append((str(source), str(source.parent)))

# Keep mandatory legal notices discoverable inside the one-file executable.
for legal_file in ('LICENSE', 'SOURCE-NOTICE.md', 'THIRD-PARTY-NOTICES.md'):
    data.append((legal_file, 'legal'))

from PyInstaller.utils.hooks import copy_metadata
data += copy_metadata('colorhash')

a = Analysis(
    ['vantage_app.py'],
    pathex=[],
    binaries=[],
    datas=data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Codex desktop exposes document/media helper DLLs on PATH. They are unrelated
# to Vantage and some have the same names as Windows/Qt dependencies. Never
# freeze those accidental binaries into the standalone executable.
clean_binaries = []
python_dlls = Path(sys.base_prefix) / 'DLLs'
for destination, source, kind in a.binaries:
    if 'codex-runtimes' not in source.casefold():
        clean_binaries.append((destination, source, kind))
        continue
    filename = Path(destination).name.casefold()
    if filename in {'libssl-3-x64.dll', 'libcrypto-3-x64.dll'}:
        replacement = python_dlls / Path(destination).name
        if replacement.is_file():
            clean_binaries.append((destination, str(replacement), kind))
a.binaries = clean_binaries


pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='Vantage',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='data/ui/icon.ico',
    version='data/ui/version_info.txt'
)
