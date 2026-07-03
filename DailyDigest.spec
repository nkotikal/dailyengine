# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Daily Digest app. Build on Windows:
#   pip install pyinstaller
#   pyinstaller DailyDigest.spec
# Produces dist/DailyDigest/DailyDigest.exe (+ dependencies). Bundles the web UI
# and read-only assets; writable data lives in %APPDATA%/DailyDigest at runtime.

import os
from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("web", "web"),
    ("samples", "samples"),
    ("RESUME_MANIFESTO.md", "."),
    (".env.example", "."),
]

hiddenimports = (
    collect_submodules("digest_pipeline")
    + collect_submodules("resume_pipeline")
    + ["user_context", "app_paths", "openai_compat", "server"]
)

icon = "assets/app.ico" if os.path.exists("assets/app.ico") else None

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DailyDigest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # windowed: no console flash; output is teed to app.log
    disable_windowed_traceback=False,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DailyDigest",
)
