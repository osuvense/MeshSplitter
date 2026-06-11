#!/usr/bin/env python3
"""Reproduce el caso de Osuvense: 1 pieza con 3 vecinas en el MISMO plano de corte.
En v6 → 3 anillos de espigas idénticos alrededor del mismo centroide (montadas).
En v7.1 → cada pareja en su zona disjunta + dedupe de parejas."""
import os, sys, types

class _FakeMeta(type):
    def __getattr__(cls, name): return _Fake
class _Fake(metaclass=_FakeMeta):
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Fake()
    def __getattr__(self, name): return _Fake()
def fake_module(name):
    m = types.ModuleType(name); m.__getattr__ = lambda attr: _Fake; sys.modules[name] = m
for mod in ["PySide6","PySide6.QtWidgets","PySide6.QtCore","PySide6.QtGui","pyvista","pyvistaqt"]:
    fake_module(mod)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mesh_splitter as ms
import numpy as np
import trimesh

FAILS = []
def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond: FAILS.append(name)

E = ms.CuttingEngine
RADIUS, TOL, HEIGHT, NDOW = 5.0, 0.3, 12.0, 3

# Base A (300×100) abajo; encima TRES vecinas B1,B2,B3 (100 de ancho cada una).
# Plano de corte: Z=50. Como el Vader: un nivel partido en varias piezas.
A  = trimesh.creation.box(extents=[300, 100, 50]); A.apply_translation([150, 50, 25])
B1 = trimesh.creation.box(extents=[100, 100, 50]); B1.apply_translation([50, 50, 75])
B2 = trimesh.creation.box(extents=[100, 100, 50]); B2.apply_translation([150, 50, 75])
B3 = trimesh.creation.box(extents=[100, 100, 50]); B3.apply_translation([250, 50, 75])
pieces = [A, B1, B2, B3]
cuts = [ms.CutDef(axis=2, position=50.0)]

# ---------- 1. Adyacencias: exactamente 3 parejas, sin duplicados ----------
adjs = E.find_adjacencies(pieces, cuts)
pairs = [(a, b) for a, b, _, _ in adjs]
check("3 parejas detectadas", len(adjs) == 3, f"{len(adjs)}: {pairs}")
check("Sin parejas duplicadas", len(set(pairs)) == len(pairs))

# Con cortes colineales casi solapados (manual+auto a <5 mm): sigue sin duplicar
cuts_dup = [ms.CutDef(axis=2, position=50.0), ms.CutDef(axis=2, position=52.0)]
adjs_dup = E.find_adjacencies(pieces, cuts_dup)
pairs_dup = [(a, b) for a, b, _, _ in adjs_dup]
check("Cortes colineales: sin parejas repetidas", len(set(pairs_dup)) == len(pairs_dup),
      f"{len(adjs_dup)} parejas con 2 cortes casi iguales")

# ---------- 2. Los puntos de espiga de cada pareja viven en su zona ----------
all_pts = []   # (x,y) de todas las espigas de todas las parejas
zonas = {1: (0, 100), 2: (100, 200), 3: (200, 300)}
ok_zona = True
for (ia, ib, ax, po) in adjs:
    region, to_2d = E.contact_region(pieces[ia], pieces[ib], ax, po)
    pts = E._pick_points_inside(region, NDOW, RADIUS + TOL + 2.0)
    to_3d = np.linalg.inv(to_2d)
    lo, hi = zonas[ib]
    for pt in pts:
        p3 = (to_3d @ np.array([pt.x, pt.y, 0.0, 1.0]))[:3]
        all_pts.append(p3)
        if not (lo - 1 < p3[0] < hi + 1): ok_zona = False
check("Cada espiga dentro de la zona de SU pareja", ok_zona)
check("Total de puntos = 3 parejas × 3 espigas", len(all_pts) == 9, f"{len(all_pts)}")

# Distancia mínima entre centros de espigas (entre TODAS las parejas):
# si fuera < 2×radio estarían montadas unas sobre otras (el bug de v6)
dmin = min(np.linalg.norm(p[:2] - q[:2])
           for i, p in enumerate(all_pts) for q in all_pts[i+1:])
check("Ninguna espiga montada sobre otra", dmin > 2 * RADIUS,
      f"separación mínima {dmin:.1f} mm (límite {2*RADIUS:.0f})")

# ---------- 3. End-to-end: aplicar espigas encadenadas y validar geometría ----------
total = 0
for (ia, ib, ax, po) in adjs:
    pieces[ia], pieces[ib], placed = E.add_dowels_between(
        pieces[ia], pieces[ib], ax, po, NDOW, RADIUS, HEIGHT, TOL)
    total += placed
check("9 espigas colocadas en total", total == 9, f"{total}")
check("A: un solo cuerpo (pins soldados)", pieces[0].body_count == 1)
check("Todas watertight", all(p.is_watertight for p in pieces))

# Volumen de A = base + 9 pins (que sobresalen height por encima de Z=50)
va = abs(pieces[0].volume) / 1000.0
v_teor = 1500.0 + 9 * (np.pi * RADIUS**2 * HEIGHT) / 1000.0
check("Volumen de A ≈ base + 9 pins", abs(va - v_teor) < v_teor * 0.02,
      f"{va:.1f} vs {v_teor:.1f} cm³")

print("\n" + "=" * 60)
if FAILS:
    print(f"❌ {len(FAILS)} FALLOS: {FAILS}"); sys.exit(1)
print("✅ CASO TRIPLICADO RESUELTO: zonas disjuntas, sin solapes, sin duplicados")
