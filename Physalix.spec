# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata
from pathlib import Path
import runpy
import sys
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct,
)

root = Path(SPECPATH)
version = runpy.run_path(str(root / 'physalix/_version.py'))['__version__']
version_tuple = tuple(map(int, version.split('.'))) + (0,)
datas = [(str(root / 'physalix/ui/resources'), 'physalix/ui/resources')]
datas += [(str(root / 'LICENSE'), '.')]
datas += [(str(root / 'THIRD_PARTY_NOTICES.md'), '.')]
datas += [(str(root / 'third_party'), 'third_party')]
binaries = []
hiddenimports = []
datas += copy_metadata('PySide6')
datas += copy_metadata('PySide6_Essentials')
datas += copy_metadata('PySide6_Addons')
datas += [(str(Path(sys.base_prefix) / 'LICENSE.txt'), 'licenses/python')]
datas += [(str(root / 'packaging/LISEZ-MOI.txt'), '.')]
datas += copy_metadata('shiboken6')
datas += copy_metadata('pyqtgraph')
datas += copy_metadata('numpy')
datas += copy_metadata('scipy')
datas += copy_metadata('av')
tmp_ret = collect_all('av', include_py_files=False)
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
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
# Some developer installations contain compiled caches even inside dist-info.
# Preserve notices but never distribute those generated caches.
a.datas = [entry for entry in a.datas
           if '__pycache__' not in Path(entry[0]).parts
           and not (any(part.endswith('.dist-info') for part in Path(entry[0]).parts)
                    and Path(entry[0]).suffix in {'.py', '.pyc'})]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Physalix',
    icon=str(root / 'physalix/ui/resources/branding/icon_physalix.ico'),
    version=VSVersionInfo(
        ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple),
        kids=[
            StringFileInfo([StringTable('040C04B0', [
                StringStruct('FileDescription', 'Physalix'),
                StringStruct('ProductName', 'Physalix'),
                StringStruct('InternalName', 'Physalix'),
                StringStruct('OriginalFilename', 'Physalix.exe'),
                StringStruct('FileVersion', version),
                StringStruct('ProductVersion', version),
            ])]),
            VarFileInfo([VarStruct('Translation', [0x040c, 1200])]),
        ],
    ),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name='Physalix',
)
