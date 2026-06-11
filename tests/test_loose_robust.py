#!/usr/bin/env python3
"""Tests: espigas sueltas (agujeros en ambas caras) y booleanas robustas
con mallas 'sucias' (no-volumen para trimesh, soldables por manifold)."""
import os, sys, types

class _FakeMeta(type):
    def __getattr__(cls, name): return _Fake
class _Fake(metaclass=_FakeMeta):
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Fake()
    def __getattr__(self, name): return _Fake()
def fake_module(name):
    m = types.ModuleType(name); m.__getattr__ = lambda attr: _Fake; sys.modules[name] = m
for mod in ["PySide6", "PySide6.QtWidgets", "PySide6.QtCore", "PySide6.QtGui",
            "pyvista", "pyvistaqt"]:
    fake_module(mod)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mesh_splitter as ms
import numpy as np
import trimesh

FAILS = []
def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not cond: FAILS.append(name)

E = ms.CuttingEngine
R, TOL, H, N = 5.0, 0.3, 12.0, 3

# ---------- 1. MODO SUELTO: agujeros en ambas caras, sin salientes ----------
A = trimesh.creation.box(extents=[100, 100, 100]); A.apply_translation([0, 0, 50])
B = trimesh.creation.box(extents=[100, 100, 100]); B.apply_translation([0, 0, 150])
va, vb = abs(A.volume), abs(B.volume)
na, nb, placed = E.add_dowels_between(A, B, axis=2, position=100.0,
                                      n_dowels=N, radius=R, height=H,
                                      tolerance=TOL, loose=True)
check("Suelto: N espigas contadas", placed == N, f"{placed}/{N}")
check("Suelto: A pierde volumen (agujero)", abs(na.volume) < va)
check("Suelto: B pierde volumen (agujero)", abs(nb.volume) < vb)
# Ningún saliente: ningún vértice de A por encima del plano ni de B por debajo
check("Suelto: A sin salientes sobre el plano", float(na.vertices[:, 2].max()) <= 100.01,
      f"max z={na.vertices[:,2].max():.2f}")
check("Suelto: B sin salientes bajo el plano", float(nb.vertices[:, 2].min()) >= 99.99,
      f"min z={nb.vertices[:,2].min():.2f}")
check("Suelto: watertight", na.is_watertight and nb.is_watertight)
# Volumen del agujero esperable por pieza: N × pi×(R+TOL)²×(H/2) (±boca)
v_hole_teor = N * np.pi * (R + TOL) ** 2 * (H / 2)
check("Suelto: profundidad de agujero ~H/2 por pieza",
      abs((va - abs(na.volume)) - v_hole_teor) < v_hole_teor * 0.25,
      f"quitado {(va-abs(na.volume))/1000:.2f} vs teor {v_hole_teor/1000:.2f} cm3")

# La espiga suelta (cilindro R×H) cabe en los agujeros: holgura radial TOL
pin = trimesh.creation.cylinder(radius=R, height=H, sections=32)
check("Suelto: espiga generable", abs(pin.volume) > 0)

# ---------- 2. BOOLEANA ROBUSTA: vertex soup (is_volume=False) ----------
# Caja geométricamente cerrada pero con caras desoldadas (como STL sucio real)
box = trimesh.creation.box(extents=[80, 80, 80])
soup = trimesh.Trimesh(vertices=box.triangles.reshape(-1, 3),
                       faces=np.arange(len(box.faces) * 3).reshape(-1, 3),
                       process=False)
check("Setup: soup NO es volumen para trimesh", not soup.is_volume)
other = trimesh.creation.box(extents=[80, 80, 80]); other.apply_translation([40, 0, 0])

failed_strict = False
try:
    trimesh.boolean.union([soup, other], engine="manifold")
except Exception:
    failed_strict = True
check("Setup: union estricta rechaza la soup", failed_strict)

u = ms.robust_union(soup, other)
check("robust_union: une la soup", abs(u.volume) > 80**3,
      f"vol {abs(u.volume)/1000:.0f} cm3 (>{80**3/1000:.0f})")
check("robust_union: un solo cuerpo", u.body_count == 1)

d = ms.robust_difference(other, soup)
check("robust_difference: resta la soup", 0 < abs(d.volume) < 80**3,
      f"vol {abs(d.volume)/1000:.0f} cm3")

# ---------- 2b. REPARACIÓN MANIFOLD: el caso real del Buddha ----------
rep = ms.manifold_repair(soup)
check("manifold_repair: soup reparada", rep is not None and rep.is_volume)
check("manifold_repair: volumen exacto", rep is not None and abs(abs(rep.volume) - 80**3) < 1)
ev = ms.ensure_volume(soup)
check("ensure_volume: ahora repara la soup", ev.is_volume)

# Modo suelto sobre PIEZAS SUCIAS (lo que fallaba 564 veces en el log real):
A3 = trimesh.creation.box(extents=[100, 100, 100]); A3.apply_translation([0, 0, 50])
A3s = trimesh.Trimesh(vertices=A3.triangles.reshape(-1, 3),
                      faces=np.arange(len(A3.faces) * 3).reshape(-1, 3), process=False)
B3 = trimesh.creation.box(extents=[100, 100, 100]); B3.apply_translation([0, 0, 150])
B3s = trimesh.Trimesh(vertices=B3.triangles.reshape(-1, 3),
                      faces=np.arange(len(B3.faces) * 3).reshape(-1, 3), process=False)
check("Setup: piezas sucias no-volumen", not A3s.is_volume and not B3s.is_volume)
na3, nb3, p3 = E.add_dowels_between(A3s, B3s, axis=2, position=100.0,
                                    n_dowels=N, radius=R, height=H,
                                    tolerance=TOL, loose=True)
check("Suelto sobre sucias: N espigas", p3 == N, f"{p3}/{N}")
check("Suelto sobre sucias: agujeros reales en A", abs(na3.volume) < 100**3 - 100)
check("Suelto sobre sucias: agujeros reales en B", abs(nb3.volume) < 100**3 - 100)

# ---------- 2c. Límite documentado del saneado interno ----------
sph = trimesh.creation.icosphere(subdivisions=4, radius=50)
holed = trimesh.Trimesh(vertices=sph.vertices, faces=sph.faces[200:], process=False)
check("Setup: boquete real no-volumen", not holed.is_volume)
check("Saneado interno NO repara boquetes (por diseño: reparar es del slicer)",
      ms.manifold_repair(holed) is None)

# ---------- 3. Espigas adheridas siguen funcionando (regresión) ----------
A2 = trimesh.creation.box(extents=[100, 100, 100]); A2.apply_translation([0, 0, 50])
B2 = trimesh.creation.box(extents=[100, 100, 100]); B2.apply_translation([0, 0, 150])
na2, nb2, p2 = E.add_dowels_between(A2, B2, axis=2, position=100.0,
                                    n_dowels=N, radius=R, height=H,
                                    tolerance=TOL, loose=False)
check("Adherido: N espigas", p2 == N)
check("Adherido: A gana volumen (pins)", abs(na2.volume) > 100**3)
check("Adherido: pins sobresalen H", abs(float(na2.vertices[:, 2].max()) - (100 + H)) < 0.1)

print("\n" + "=" * 60)
if FAILS:
    print(f"{len(FAILS)} FALLOS: {FAILS}"); sys.exit(1)
print("OK TODOS LOS TESTS DE SUELTAS+ROBUSTAS PASAN")
