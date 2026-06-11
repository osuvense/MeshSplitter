#!/bin/bash
# Lanzador simple de MeshSplitter (alternativa a la .app).
# Doble clic: activa el venv (creándolo si hace falta) y arranca la app.
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "Primera vez: creando entorno…"
  python3 -m venv venv
fi
source venv/bin/activate

# Verificar que las dependencias del requirements actual están instaladas
# (cubre venvs antiguos, p. ej. la migración PyQt5 → PySide6)
if ! python -c "import PySide6, pyvista, pyvistaqt, trimesh, manifold3d, shapely" 2>/dev/null; then
  echo "Instalando/actualizando dependencias (puede tardar unos minutos)…"
  pip install --upgrade pip --quiet
  pip install -r requirements.txt --quiet
fi

exec python mesh_splitter.py
