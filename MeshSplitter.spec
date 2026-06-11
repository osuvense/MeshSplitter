# -*- mode: python ; coding: utf-8 -*-
# Spec multiplataforma de PyInstaller para MeshSplitter.
#   macOS   → dist/MeshSplitter.app (bundle onedir)
#   Windows → dist/MeshSplitter.exe (portable, onefile)
# hiddenimports de VTK según la doc oficial de pyvista:
# https://docs.pyvista.org/extras/pyinstaller
import sys
from PyInstaller.utils.hooks import collect_data_files

APP_VERSION = "0.9.0"   # mantener en sync con APP_VERSION de mesh_splitter.py

datas = collect_data_files("pyvista")
hidden = [
    "vtkmodules",
    "vtkmodules.all",
    "vtkmodules.qt.QVTKRenderWindowInteractor",
    "vtkmodules.util",
    "vtkmodules.util.numpy_support",
    "vtkmodules.numpy_interface.dataset_adapter",
]

a = Analysis(
    ["mesh_splitter.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter"],   # solo PySide6
    noarchive=False,
)

pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="MeshSplitter",
        debug=False, strip=False, upx=False,
        console=False,
        target_arch=None,          # nativo (arm64 en Apple Silicon)
        codesign_identity=None,    # sin firma: 1ª vez → Ajustes → Privacidad y seguridad → Abrir de todos modos
        entitlements_file=None,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MeshSplitter")
    app = BUNDLE(
        coll,
        name="MeshSplitter.app",
        icon=None,
        bundle_identifier="com.osuvense.meshsplitter",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHumanReadableCopyright": "MIT License — Osuvense, 2026",
        },
    )
else:
    # Windows (y Linux): ejecutable portable de un solo archivo
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="MeshSplitter",
        debug=False, strip=False, upx=False,
        console=False,
        disable_windowed_traceback=False,
    )
