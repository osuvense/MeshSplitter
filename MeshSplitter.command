#!/bin/bash
# Lanzador simple de MeshSplitter (alternativa a la .app).
# Doble clic: prepara el entorno si hace falta y arranca la app.
cd "$(dirname "$0")"

# Venv de la era PyQt5 (anterior a jun-2026): mejor recrearlo limpio para
# evitar conflictos entre bindings de Qt conviviendo en el mismo entorno.
if [ -d venv ] && venv/bin/python -c "import PyQt5" 2>/dev/null; then
  echo "Tu entorno virtual es de la versión antigua (PyQt5) y conviene recrearlo."
  read -p "¿Recrear ahora? Tarda unos minutos. [S/n]: " R
  if [[ ! "$R" =~ ^[nN] ]]; then
    rm -rf venv
    echo "Entorno antiguo eliminado."
  fi
fi

if [ ! -d venv ]; then
  echo "Creando entorno virtual…"
  python3 -m venv venv
fi
source venv/bin/activate

if ! python -c "import PySide6, pyvista, pyvistaqt, trimesh, manifold3d, shapely" 2>/dev/null; then
  echo "Instalando dependencias — VERÁS el progreso, VTK y PySide6 son pesados (3-10 min)…"
  pip install --upgrade pip
  pip install -r requirements.txt
fi

echo "Lanzando MeshSplitter…"
exec python mesh_splitter.py