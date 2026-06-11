#!/bin/bash
# Publica MeshSplitter en GitHub — doble clic.
# REQUISITO previo (1 minuto): crea el repo vacío en https://github.com/new
#   · Repository name: MeshSplitter
#   · Public
#   · NO marques "Add a README" ni .gitignore ni licencia (ya van en el commit)
set -e
cd "$(dirname "$0")"
echo "── Publicar MeshSplitter en GitHub ──"
echo

# Repo git local: crearlo (o recrearlo si quedó a medias, sin commits)
if ! git rev-parse HEAD >/dev/null 2>&1; then
  rm -rf .git
  git init -b main
  git config user.name "Osuvense"
  git config user.email "260680682+osuvense@users.noreply.github.com"
  git add -A
  git commit -m "MeshSplitter 0.9.0-beta — primera versión pública

Corte de STL en bloques imprimibles (3 ejes), espigas en zona de contacto
real, fusión por contacto físico verificado, efecto piedra, peso estimado,
export individual + informe. PySide6/MIT. Builds automáticos macOS+Windows
vía GitHub Actions. Historial interno v1-v7 (mar-jun 2026)."
  echo "Commit inicial creado."
fi

echo
echo "Antes de seguir, asegúrate de haber creado el repo vacío en:"
echo "  https://github.com/new   (nombre: MeshSplitter, público, sin README)"
echo
read -p "Tu usuario de GitHub: " GHUSER
[ -z "$GHUSER" ] && { echo "Sin usuario, salgo."; exit 1; }

git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${GHUSER}/MeshSplitter.git"

echo
echo "Subiendo código (si pide credenciales: usuario + Personal Access Token,"
echo "o se abrirá el navegador si tienes Git Credential Manager)…"
git push -u origin main

echo "Creando tag v0.9.0 (dispara la construcción automática de .dmg y .exe)…"
git tag -f v0.9.0
git push -f origin v0.9.0

echo
echo "✅ Publicado:"
echo "   Repo:     https://github.com/${GHUSER}/MeshSplitter"
echo "   Builds:   https://github.com/${GHUSER}/MeshSplitter/actions  (~15-25 min)"
echo "   Releases: https://github.com/${GHUSER}/MeshSplitter/releases (los binarios aparecen ahí al terminar)"
