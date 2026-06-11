#!/bin/bash
# Lanzador simple de MeshSplitter (alternativa a la .app).
# Doble clic: comprueba el entorno, lo recrea limpio si está roto, y arranca.
cd "$(dirname "$0")"

# ¿Entorno sano? (importa todo y PySide6 es < 6.10)
ENV_OK=0
if [ -d venv ]; then
  if venv/bin/python -c "
import PySide6, pyvista, pyvistaqt, trimesh, manifold3d, shapely
v = tuple(map(int, PySide6.__version__.split('.')[:2]))
assert v < (6, 10), 'PySide6 6.10+ cuelga con pyvistaqt en macOS'
" 2>/dev/null; then
    ENV_OK=1
  fi
fi

if [ "$ENV_OK" = "0" ]; then
  if [ -d venv ]; then
    echo "El entorno virtual actual está roto o tiene versiones incompatibles."
    echo "Lo más fiable es recrearlo desde cero (tarda unos minutos)."
    read -p "¿Recrear ahora? [S/n]: " R
    if [[ "$R" =~ ^[nN] ]]; then echo "Cancelado."; exit 1; fi
    rm -rf venv
    echo "Entorno antiguo eliminado."
  fi
  echo "Creando entorno limpio…"
  python3 -m venv venv
  source venv/bin/activate
  echo "Instalando dependencias (verás el progreso; varios minutos la primera vez)…"
  pip install --upgrade pip
  # --no-compile: evita un crash de pip al byte-compilar plantillas internas
  # de PySide6 (visto con Python 3.9 el 11/06/2026)
  pip install --no-compile -r requirements.txt
else
  source venv/bin/activate
fi

echo "Lanzando MeshSplitter…"
exec python mesh_splitter.py