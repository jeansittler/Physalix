# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

datas = [('physlab/ui/resources', 'physlab/ui/resources')]
binaries = []
hiddenimports = []
datas += copy_metadata('PySide6')
datas += copy_metadata('shiboken6')
datas += copy_metadata('pyqtgraph')
datas += copy_metadata('numpy')
datas += copy_metadata('scipy')
datas += copy_metadata('av')
tmp_ret = collect_all('av')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Qt uses the Windows ICU API. The bundled development Python also ships
# an incompatible ICU with versioned symbols under the same DLL name.
# Resolve icuuc.dll from Windows instead (Windows 10/11 distribution).
a.binaries = [entry for entry in a.binaries
              if entry[0].lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Physalyx',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Physalyx',
)
