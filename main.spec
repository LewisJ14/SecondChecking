# -*- mode: python ; coding: utf-8 -*-

import os
import sys

here = os.path.abspath(os.path.dirname(sys.argv[0]))
manifest_file = os.path.join(here, "app.manifest")

a = Analysis(
    ['src\\main.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/assets', 'assets')],
    hiddenimports=['requests'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest=manifest_file,
    uac_admin=True,
)
