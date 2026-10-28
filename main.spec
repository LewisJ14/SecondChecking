# -*- mode: python ; coding: utf-8 -*-

import os
import sys

here = SPECPATH
manifest_file = os.path.join(here, "app.manifest")
identity = os.environ.get('SECOND_CHECKING_BUILD_IDENTITY')
version_resource = os.environ.get('SECOND_CHECKING_VERSION_RESOURCE')
if not identity or not version_resource:
    raise RuntimeError('Build with compile.ps1 or scripts/release_package.py to record artifact identity.')

a = Analysis(
    ['src\\main.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/assets/AudioCheck.wav', 'assets'),
           ('src/assets/astro-login-hero.png', 'assets'),
           ('src/assets/BatteryInfoView/BatteryInfoView.exe', 'assets/BatteryInfoView'),
           ('src/Script.ps1', '.'), (identity, '.')],
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
    version=version_resource,
    uac_admin=False,
)
