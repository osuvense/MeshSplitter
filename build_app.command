#!/bin/bash
# Construye MeshSplitter.app y el .dmg — doble clic y esperar (5-15 min la primera vez).
set -e
cd "$(dirname "$0")"
VERSION=$(grep -m1 'APP_VERSION = ' mesh_splitter.py | cut -d'"' -f2)
echo "── MeshSplitter ${VERSION}: construyendo la app de macOS ──"

if [ ! -d venv ]; then
  echo "Creando entorno virtual…"
  python3 -m venv venv
fi
source venv/bin/activate

echo "Instalando dependencias (la primera vez tarda: VTK es pesado)…"
pip install --upgrade pip --quiet
pip install --no-compile -r requirements.txt --quiet
pip install pyinstaller --quiet

echo "Smoke test de la GUI…"
python tests/smoke_gui.py

echo "Empaquetando con PyInstaller…"
rm -rf build dist
pyinstaller MeshSplitter.spec --noconfirm

echo "Creando DMG…"
hdiutil create -volname MeshSplitter -srcfolder dist/MeshSplitter.app -ov -format UDZO "dist/MeshSplitter-${VERSION}-macOS.dmg"

echo
echo "Hecho:"
echo "  dist/MeshSplitter.app"
echo "  dist/MeshSplitter-${VERSION}-macOS.dmg"
echo "Al no estar firmada, la PRIMERA vez macOS la bloqueará:"
echo "Ajustes del Sistema → Privacidad y seguridad → 'Abrir de todos modos'."
open dist
