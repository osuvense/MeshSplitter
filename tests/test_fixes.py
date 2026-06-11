#!/usr/bin/env python3
"""Tests de los fixes v7.1: espigas en zona de contacto real + fusión por contacto."""
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
import shapely.geometry as sg

FAILS = []
def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond: FAILS.append(name)

E = ms.CuttingEngine

# ---------- A. ESPIGAS: contacto parcial (forma de L) ----------
# Pieza A: caja 200×200 de base, abajo. Pieza B: caja 60×60 arriba, en la ESQUINA.
# Contacto real = solo 60×60 en la esquina. El método viejo (anillo en el
# centroide del cap de A) habría puesto espigas fuera de B.
A = trimesh.creation.box(extents=[200, 200, 50]); A.apply_translation([100, 100, 25])
B = trimesh.creation.box(extents=[60, 60, 50]);  B.apply_translation([30, 30, 75])

region, to_2d = E.contact_region(A, B, axis=2, position=50.0)
check("Contacto L: región detectada", region is not None)
if region is not None:
    check("Contacto L: área ≈ 60×60", abs(region.area - 3600) < 100, f"{region.area:.0f} mm²")

va, vb = abs(A.volume), abs(B.volume)
na, nb, placed = E.add_dowels_between(A, B, axis=2, position=50.0,
                                      n_dowels=3, radius=5, height=12, tolerance=0.3)
check("Contacto L: ≥1 espiga colocada", placed >= 1, f"{placed} (puede no caber 3 en 60×60 erosionado)")
check("Contacto L: A gana volumen", abs(na.volume) > va)
check("Contacto L: B pierde volumen", abs(nb.volume) < vb)
check("Contacto L: A sigue siendo 1 cuerpo", na.body_count == 1, f"{na.body_count}")
check("Contacto L: watertight", na.is_watertight and nb.is_watertight)

# Verificar que TODOS los pins caen dentro del contacto: los vértices nuevos de A
# (los del pin) deben estar en x,y dentro de [0,60]±radio
new_verts = na.vertices[na.vertices[:, 2] > 50.5]   # por encima del plano = pins
if len(new_verts):
    inside = np.all((new_verts[:, 0] > -6) & (new_verts[:, 0] < 66) &
                    (new_verts[:, 1] > -6) & (new_verts[:, 1] < 66))
    check("Contacto L: pins SOLO sobre la zona de contacto", bool(inside),
          f"x∈[{new_verts[:,0].min():.0f},{new_verts[:,0].max():.0f}] y∈[{new_verts[:,1].min():.0f},{new_verts[:,1].max():.0f}]")
else:
    check("Contacto L: pins SOLO sobre la zona de contacto", placed == 0)

# ---------- B. ESPIGAS: sección anular (pieza hueca, caso Moai/Vader) ----------
outer = trimesh.creation.cylinder(radius=80, height=100, sections=48)
inner = trimesh.creation.cylinder(radius=60, height=120, sections=48)
tube = trimesh.boolean.difference([outer, inner], engine="manifold")  # pared 20 mm
T1 = tube.copy(); T1.apply_translation([0, 0, 50])    # de 0 a 100
T2 = tube.copy(); T2.apply_translation([0, 0, 150])   # de 100 a 200

region2, _ = E.contact_region(T1, T2, axis=2, position=100.0)
check("Anillo: región detectada", region2 is not None)
if region2 is not None:
    ring_area = np.pi * (80**2 - 60**2)
    check("Anillo: área ≈ anular", abs(region2.area - ring_area) / ring_area < 0.05,
          f"{region2.area:.0f} vs {ring_area:.0f} mm²")
    # el centro (hueco) NO debe estar en la región
    check("Anillo: centro hueco excluido", not region2.contains(sg.Point(0, 0)))

t1, t2, placed2 = E.add_dowels_between(T1, T2, axis=2, position=100.0,
                                       n_dowels=4, radius=4, height=10, tolerance=0.3)
check("Anillo: espigas colocadas", placed2 >= 2, f"{placed2}/4")
pin_verts = t1.vertices[t1.vertices[:, 2] > 100.5]
if len(pin_verts):
    r_pins = np.linalg.norm(pin_verts[:, :2], axis=1)
    check("Anillo: pins dentro de la pared (60<r<80 ±radio)",
          bool(np.all((r_pins > 53) & (r_pins < 87))),
          f"r∈[{r_pins.min():.0f},{r_pins.max():.0f}]")
check("Anillo: piezas watertight", t1.is_watertight and t2.is_watertight)

# ---------- C. FUSIÓN: pequeña SIN contacto no se finge fusionar ----------
big = trimesh.creation.box(extents=[100, 100, 100])
floater = trimesh.creation.box(extents=[15, 15, 15])
floater.apply_translation([200, 200, 200])   # lejos, sin tocar
mp, mf, uf = E.merge_small_pieces([big, floater], 25.0)
check("Sin contacto: siguen siendo 2 piezas", len(mp) == 2, f"{len(mp)}")
check("Sin contacto: flag unmerged en la pequeña", uf == [False, True], f"{uf}")
check("Sin contacto: ninguna marcada como fusionada", not any(mf))

# ---------- D. FUSIÓN: bboxes tocan pero cuerpos NO → rechazo por body_count ----------
# L grande y cubito en el hueco de la L: bboxes solapan, sin contacto físico.
Lbase = trimesh.creation.box(extents=[100, 100, 20]); Lbase.apply_translation([50, 50, 10])
Lcol  = trimesh.creation.box(extents=[20, 100, 80]);  Lcol.apply_translation([10, 50, 60])
Lpiece = trimesh.boolean.union([Lbase, Lcol], engine="manifold")
cubito = trimesh.creation.box(extents=[15, 15, 15])
cubito.apply_translation([70, 50, 60])   # dentro del bbox de L, flotando sin tocar
check("Setup D: bboxes se tocan", ms.bboxes_touch(Lpiece, cubito))
mp2, mf2, uf2 = E.merge_small_pieces([Lpiece, cubito], 25.0)
check("Bbox-sin-contacto: no se fusiona (body_count)", len(mp2) == 2, f"{len(mp2)} piezas")
check("Bbox-sin-contacto: marcada unmerged", uf2[1] is True if len(uf2) > 1 else False, f"{uf2}")

# ---------- E. FUSIÓN: con contacto real sigue funcionando (regresión) ----------
box = trimesh.creation.box(extents=[200, 100, 100])
p = E.cut_mesh_multiaxis(box, [ms.CutDef(axis=0, position=90.0)])
mp3, mf3, uf3 = E.merge_small_pieces(p, 25.0)
check("Contacto real: fusiona a 1 pieza", len(mp3) == 1)
check("Contacto real: flag merged True", mf3 == [True], f"{mf3}")
check("Contacto real: volumen exacto", abs(abs(mp3[0].volume)/1000.0 - 2000.0) < 5)
check("Contacto real: 1 cuerpo", mp3[0].body_count == 1)

# ---------- F. Cadena: pequeña + pequeña adyacentes → ambas acaban unidas ----------
b1 = trimesh.creation.box(extents=[100, 100, 100]); b1.apply_translation([50, 50, 50])
s1 = trimesh.creation.box(extents=[10, 100, 100]);  s1.apply_translation([105, 50, 50])
s2 = trimesh.creation.box(extents=[10, 100, 100]);  s2.apply_translation([115, 50, 50])
mp4, mf4, uf4 = E.merge_small_pieces([b1, s1, s2], 25.0)
check("Cadena: todo en 1 pieza", len(mp4) == 1, f"{len(mp4)}")
check("Cadena: volumen 100³+2×(10×100×100)", abs(abs(mp4[0].volume)/1000.0 - 1200.0) < 5,
      f"{abs(mp4[0].volume)/1000.0:.0f} cm³")

print("\n" + "=" * 60)
if FAILS:
    print(f"❌ {len(FAILS)} FALLOS: {FAILS}"); sys.exit(1)
print("✅ TODOS LOS TESTS DE LOS FIXES PASAN")
