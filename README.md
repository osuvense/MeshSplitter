# MeshSplitter

**Corta modelos STL grandes en bloques imprimibles, con espigas de alineación y cortes de aspecto natural.**

Pensado para imprimir esculturas y modelos a gran escala en impresoras FDM domésticas (desarrollado sobre Bambu Lab H2D y X1C, válido para cualquier impresora). Cargas un STL — incluso de varios metros, como los que generan las IAs de mesh tipo Hunyuan — lo escalas, lo partes en bloques que quepan en tu cama, y exportas cada pieza como STL individual con su informe de dimensiones y peso.

> 🇬🇧 *English: desktop tool to split large STL models into printable blocks, with alignment dowel pins, natural-looking cut surfaces (stone effect), per-piece weight estimation and individual STL export. UI currently in Spanish — English version on the roadmap if there's interest. See [Quick start](#english-quick-start).*

---

## Características

- **Corte en 3 ejes** con planos manuales o generados automáticamente según el tamaño máximo de pieza (presets para volúmenes *prácticos* de Bambu Lab H2D 315³ y X1C 245³ — los reales, no los de marketing).
- **Espigas de alineación (dowel pins)**: cada junta recibe espigas y agujeros con tolerancia configurable, colocadas automáticamente dentro de la zona de contacto real entre piezas (funciona con piezas huecas: nunca caen en el vacío).
- **Irregularidad de corte**: ondulación configurable de las superficies de corte para un acabado tipo piedra/megalítico; las caras enfrentadas usan el mismo mapa de ruido y encajan.
- **Fusión inteligente de piezas pequeñas**: los fragmentos finos (dedos, salientes) se fusionan con su vecina en contacto físico verificado, nunca se pierden. Lo que no toca nada se marca para decisión humana.
- **Peso estimado por pieza** según material (PLA/PETG/ABS/ASA/TPU/PC), % de relleno y espesor de pared, con total del proyecto. Volumen real de malla, no bounding box.
- **Previsualización**: planos de corte sobre el modelo, piezas coloreadas, vista explosionada con slider.
- **Tabla ordenable** con dimensiones, volumen, peso y compatibilidad por impresora; export de STLs numerados + informe de texto.
- **Drag & drop** de STL, detección automática de unidades (metros/cm/mm) con factor de escala sugerido.

## Descargas

En [Releases](../../releases) hay binarios listos para usar:

| Plataforma | Archivo | Nota |
|---|---|---|
| **macOS** (Apple Silicon) | `MeshSplitter-x.y.z-macOS.dmg` | Sin firmar: la **primera** vez, clic derecho sobre la app → **Abrir** |
| **Windows** 10/11 | `MeshSplitter-x.y.z-Windows-portable.exe` | Portable, sin instalación. Si SmartScreen avisa: **Más información → Ejecutar de todas formas**. El primer arranque tarda unos segundos (se descomprime en temporal) |

Los avisos de macOS/Windows aparecen porque los binarios no están firmados con certificado de pago, no porque haya nada raro: el código es abierto y los binarios los construye GitHub Actions directamente desde este repositorio (puedes ver cada build en la pestaña Actions).

## Uso

1. **Carga un STL** (botón o arrastrándolo a la ventana).
2. **Aplica escala** — para mallas de IA tipo Hunyuan (en metros), el ×1000 viene sugerido.
3. **Genera cortes**: por tamaño máximo de pieza (presets H2D/X1C) o a mano por eje. Los planos se previsualizan sobre el modelo.
4. Ajusta **fusión de piezas pequeñas** (grosor mínimo aceptable), **irregularidad** y **espigas** si las quieres.
5. **Previsualizar** → revisa la tabla (dimensiones, peso, qué cabe en qué impresora).
6. **Cortar** → genera la versión final con espigas.
7. **Exportar** → un STL por pieza + informe de texto con dimensiones, pesos y total.

### El peso es una estimación

Modelo estándar de calculadora FDM: paredes macizas (área superficial × espesor de pared) + interior al % de relleno × densidad nominal del material. No incluye soportes ni ajustes finos del slicer; el dato definitivo lo da tu slicer. Las piezas no-watertight se marcan con `~`.

## Ejecutar desde código

Requiere Python 3.10+.

```bash
git clone <este-repo>
cd MeshSplitter
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt   # la primera vez tarda: VTK es pesado
python mesh_splitter.py
```

En macOS también puedes usar `MeshSplitter.command` (doble clic: crea el venv y lanza) y `build_app.command` (construye la .app y el .dmg localmente).

## Limitaciones conocidas

- Mallas muy densas (>1M triángulos): el corte va rápido (~15 s para 1,3M), pero las operaciones booleanas de espigas en muchas juntas pueden tardar varios minutos. Si es excesivo, decima antes el STL (Blender, Decimate ~0.3-0.5).
- Irregularidad alta + espigas: ambas conviven, pero revisa las juntas en el slicer.
- Cortes solo ortogonales (X/Y/Z); planos inclinados están en la lista de deseos.
- La UI está en español.

## Licencia y créditos

Código bajo [licencia MIT](LICENSE). Construido sobre estos proyectos open source:

| Dependencia | Licencia |
|---|---|
| [PySide6 / Qt](https://doc.qt.io/qtforpython-6/) | LGPL-3.0 |
| [pyvista](https://pyvista.org) + [pyvistaqt](https://qtdocs.pyvista.org) | MIT |
| [trimesh](https://trimesh.org) | MIT |
| [VTK](https://vtk.org) | BSD-3 |
| [numpy](https://numpy.org) / [scipy](https://scipy.org) / [shapely](https://shapely.readthedocs.io) / [networkx](https://networkx.org) | BSD-3 |
| [manifold3d](https://github.com/elalish/manifold) | Apache-2.0 |
| [rtree](https://github.com/Toblerity/rtree) | MIT |

**Transparencia:** esta aplicación se ha desarrollado con asistencia de IA (Claude, de Anthropic), con dirección, decisiones de diseño y pruebas en impresoras reales por parte del autor.

## Feedback

¿Bugs, ideas, resultados con tus impresiones? Abre un [issue](../../issues) o comenta en el hilo donde lo compartí. Esto es una beta: el feedback es exactamente lo que busco.

---

## English quick start

Desktop tool to split large STL models (even meters-sized AI-generated meshes) into printer-sized blocks. Load STL → scale (×1000 suggested for meter-based meshes) → auto-generate cuts from max piece size → optional small-piece merging, stone-effect cut irregularity and alignment dowel pins → preview pieces/weights table → export numbered STLs + report. Downloads for macOS (.dmg, unsigned: right-click → Open on first launch) and Windows (portable .exe, SmartScreen: More info → Run anyway) in [Releases](../../releases). Run from source: `pip install -r requirements.txt && python mesh_splitter.py` (Python 3.10+). MIT licensed. UI in Spanish for now — open an issue if you'd use an English version.
