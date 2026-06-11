# Changelog

## 0.9.0-beta — 2026-06-11 (revisión final de la beta)

- **Espigas en dos modos:** sueltas (agujeros en ambas caras + STL de espiga para imprimir N copias aparte — sin salientes en las piezas, impresión sin soportes; recomendado y por defecto) o adheridas a la pieza.
- **Booleanas robustas para STL reales no-watertight:** escalera estricta → reparación → manifold sin pre-check con validación de resultado. Elimina la gran mayoría de los fallos "Not all meshes are volumes" con mallas sucias.
- Panel lateral redimensionable (splitter) — adiós a la barra de scroll horizontal fija.
- Silenciados ~7.000 avisos de deprecación de trimesh (`to_planar` → `to_2D`).
- Aviso de beta sin validación física en README.
- **Detección de STL no-watertight al cargar**, con aviso claro recomendando repararlos en una herramienta externa (Bambu Studio/Orca, Meshmixer…). Reparar mallas queda explícitamente fuera del alcance de la app (decisión de diseño: evita resultados sorpresa y dependencias GPL).

## 0.9.0-beta — 2026-06-10

Primera versión pública (beta). Consolida siete iteraciones internas de desarrollo (v1–v7, marzo–junio 2026).

### Funcionalidad

- Corte de STL en 3 ejes: planos manuales o auto-generados por tamaño máximo de pieza (presets de volumen práctico Bambu Lab H2D 315³ / X1C 245³).
- Espigas de alineación con agujeros tolerados, colocadas dentro de la zona de contacto real de cada junta (soporta piezas huecas; verificación de soldadura por cuerpo único).
- Irregularidad de corte (efecto piedra) con mapas de ruido coherentes entre caras enfrentadas.
- Fusión de piezas pequeñas solo con vecinas en contacto físico verificado; fragmentos sin contacto quedan marcados, nunca se descartan en silencio. Filtrado de esquirlas degeneradas del corte.
- Separación de componentes desconectados tras el corte.
- Peso estimado por pieza (material, % relleno, espesor de pared) con recálculo en vivo y total; volumen real de malla.
- Previsualización de planos de corte, vista explosionada, tabla ordenable, export de STLs numerados + informe.
- Drag & drop de STL; detección de unidades nativas con escala sugerida.

### Técnica

- Migración de PyQt5 a PySide6 (LGPL) para distribución de binarios bajo licencia MIT.
- Binarios de macOS (.dmg) y Windows (.exe portable) construidos automáticamente por GitHub Actions, con tests de motor de corte y smoke test de GUI previos al empaquetado.
