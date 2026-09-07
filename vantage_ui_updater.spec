# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

source_root = Path('src').resolve()
sys.path.insert(0, str(source_root))

a = Analysis(
    ['vantage_ui_updater.py'], pathex=[str(source_root)], binaries=[],
    datas=[('ui/release.json', '.'), ('LICENSE', 'legal'),
           ('ui/THIRD-PARTY-NOTICES.md', 'legal')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6', 'pytest', 'PIL'], noarchive=False,
)
# Name the embedded metadata explicitly without duplicating version constants.
a.datas = [('ui-release.json' if dest == 'release.json' else dest, src, kind)
           for dest, src, kind in a.datas]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='VantageUI-Updater',
          debug=False, strip=False, upx=False, console=False,
          icon='data/ui/icon.ico', version='data/ui/ui_updater_version_info.txt')
