#!/usr/bin/env python3
"""Tests headless del engine de MeshSplitter v7 (sin GUI).
Stubs para PyQt5/pyvista/pyvistaqt; trimesh/numpy/scipy reales."""
import os, sys, time, types

# ---- Stubs de módulos GUI ----
class _FakeMeta(type):
    def __getattr__(cls, name): return _Fake

class _Fake(metaclass=_FakeMeta):
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Fake()
    def __getattr__(self, name): return _Fake()

def fake_module(name):
    m = types.ModuleType(name)
    m.__getattr__ = lambda attr: _Fake
    sys.modules[name] = m
    return m

for mod in ["PySide6", "PySide6.QtWidgets", "PySide6.QtCore", "PySide6.QtGui",
            "pyvista", "pyvistaqt"]:
    fake_module(mod)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mesh_splitter as ms
import numpy as np
import trimesh

FAILS = []
def check(name, cond, detail=""):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond: FAILS.append(name)

E = ms.CuttingEngine

# ---------- 1. Corte multi-eje básico + conservación de volumen ----------
box = trimesh.creation.box(extents=[600, 300, 200])
cuts = E.compute_auto_cuts(box.bounds, (245, 245, 245))
pieces = E.cut_mesh_multiaxis(box, cuts)
vol_orig = box.volume
vol_sum = sum(abs(p.volume) for p in pieces)
dims_ok = all(np.all(p.bounds[1] - p.bounds[0] <= 245 + 1.0) for p in pieces)
check("Auto-cuts caja 600×300×200 → nº piezas", len(pieces) == 6,
      f"{len(pieces)} piezas (esperadas 6: 3×2×1)")
check("Todas las piezas ≤ 245 mm", dims_ok)
check("Conservación de volumen", abs(vol_sum - vol_orig) / vol_orig < 0.01,
      f"orig {vol_orig/1000:.1f} cm³ vs suma {vol_sum/1000:.1f} cm³")

# ---------- 2. Componentes desconectados + fusión + flags merged ----------
# Mancuerna: dos esferas unidas por un cilindro fino; un corte central en X
# deja el cilindro partido → componentes pequeños que deben fusionarse.
s1 = trimesh.creation.icosphere(subdivisions=3, radius=60)
s1.apply_translation([-100, 0, 0])
s2 = trimesh.creation.icosphere(subdivisions=3, radius=60)
s2.apply_translation([100, 0, 0])
rod = trimesh.creation.cylinder(radius=10, height=120, sections=24)
rod.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0, 1, 0]))
dumbbell = trimesh.boolean.union([s1, s2, rod], engine="manifold")
cuts2 = [ms.CutDef(axis=0, position=0.0)]
p2 = E.cut_mesh_multiaxis(dumbbell, cuts2)
check("Mancuerna cortada → ≥2 piezas", len(p2) >= 2, f"{len(p2)} piezas")

merged_p, merged_f, _unm = E.merge_small_pieces(p2, 25.0)
check("Fusión devuelve flags del mismo tamaño", len(merged_p) == len(merged_f),
      f"{len(merged_p)} piezas, {len(merged_f)} flags")
small_left = [p for p in merged_p if ms.min_dimension(p) < 25.0]
check("Sin piezas bajo umbral tras fusión", len(small_left) == 0,
      f"{len(small_left)} pequeñas restantes")
# Bug v6: flags marcaban "no cabe en X1C" (aquí todo cabe → todas False aunque hubiera fusión)
if len(p2) > len(merged_p):
    check("Flag merged refleja fusiones reales (bug v6)", any(merged_f),
          f"flags: {merged_f}")
else:
    print("[SKIP] No hubo fusión en mancuerna (no se puede validar flag)")

# Control: flags False cuando no se fusiona nada
big = trimesh.creation.box(extents=[200, 200, 200])
bp, bf, _ = E.merge_small_pieces([big], 25.0)
check("Sin fusión → flags todas False", not any(bf))

# ---------- 3. Espigas: A gana volumen (pin), B pierde (agujero) ----------
ba = trimesh.creation.box(extents=[100, 100, 100]); ba.apply_translation([0, 0, 50])
bb = trimesh.creation.box(extents=[100, 100, 100]); bb.apply_translation([0, 0, 150])
va, vb = abs(ba.volume), abs(bb.volume)
na, nb, n_placed = E.add_dowels_between(ba, bb, axis=2, position=100.0,
                                        n_dowels=3, radius=5, height=15, tolerance=0.3)
check("Espigas: 3 colocadas", n_placed == 3, f"{n_placed} colocadas")
check("Espigas: pieza A gana volumen", abs(na.volume) > va + 100,
      f"{va/1000:.1f} → {abs(na.volume)/1000:.1f} cm³")
check("Espigas: pieza B pierde volumen", abs(nb.volume) < vb - 100,
      f"{vb/1000:.1f} → {abs(nb.volume)/1000:.1f} cm³")
check("Espigas: resultado watertight", na.is_watertight and nb.is_watertight)

# ---------- 4. Irregularidad: el cap deja de ser plano ----------
box3 = trimesh.creation.box(extents=[100, 100, 100])
flat = E.cut_mesh_multiaxis(box3, [ms.CutDef(axis=2, position=0.0)], irregularity=0.0)
irr = E.cut_mesh_multiaxis(box3, [ms.CutDef(axis=2, position=0.0)], irregularity=3.0)
def cap_spread(piece, pos=0.0):
    vz = piece.vertices[:, 2]
    capm = np.abs(vz - pos) < 4.0
    return vz[capm].max() - vz[capm].min() if np.any(capm) else 0.0
sp_flat = max(cap_spread(p) for p in flat)
sp_irr = max(cap_spread(p) for p in irr)
check("Irregularidad 0 → cap plano", sp_flat < 0.01, f"spread {sp_flat:.4f} mm")
check("Irregularidad 3 → cap ondulado", sp_irr > 0.5, f"spread {sp_irr:.2f} mm")

# ---------- 5. Peso estimado: caja 100³, PLA, 15 %, pared 1.6 ----------
boxw = trimesh.creation.box(extents=[100, 100, 100])
g, vol_cm3, wt = ms.estimate_piece_weight(boxw, 1.24, 15, 1.6)
# A mano: V=1000 cm³; A=60000 mm² → shell 96 cm³; interior 904×0.15=135.6; total 231.6×1.24=287.18 g
check("Peso caja 100³: volumen", abs(vol_cm3 - 1000.0) < 0.5, f"{vol_cm3:.1f} cm³")
check("Peso caja 100³: gramos", abs(g - 287.2) < 1.0, f"{g:.1f} g (esperado ≈287.2)")
check("Peso caja 100³: watertight", wt is True)
g0, _, _ = ms.estimate_piece_weight(boxw, 1.24, 0, 0.4)
g100, _, _ = ms.estimate_piece_weight(boxw, 1.24, 100, 0.4)
check("Peso 100 % relleno = macizo", abs(g100 - 1240.0) < 1.0, f"{g100:.1f} g")
check("Peso crece con relleno", g0 < g < g100)

# ---------- 6. get_piece_info integra peso y flags ----------
info = E.get_piece_info(boxw, 0, merged=True, weight_params=(1.24, 15, 1.6))
check("PieceInfo.weight_g poblado", abs(info.weight_g - 287.2) < 1.0)
check("PieceInfo.volume_cm3 = volumen real malla", abs(info.volume_cm3 - 1000.0) < 0.5)
check("PieceInfo.merged respetado", info.merged is True)
check("PieceInfo cabe en X1C/H2D", info.fits_x1c and info.fits_h2d)

# ---------- 7. Malla densa ~1.3M triángulos: rendimiento ----------
dense = trimesh.creation.icosphere(subdivisions=8, radius=900)  # 1.31M caras
print(f"\nMalla densa: {len(dense.faces):,} triángulos, Ø1.8 m")
t0 = time.time()
cuts_d = E.compute_auto_cuts(dense.bounds, (315, 315, 315))
pd = E.cut_mesh_multiaxis(dense, cuts_d)
t_cut = time.time() - t0
print(f"Corte {len(cuts_d)} planos → {len(pd)} piezas en {t_cut:.1f} s")
t0 = time.time()
pdm, fdm, udm = E.merge_small_pieces(pd, 30.0)
print(f"Densa: {sum(udm)} piezas sin contacto tras fusión")
t_merge = time.time() - t0
print(f"Fusión → {len(pdm)} piezas en {t_merge:.1f} s")
check("Malla densa: corte termina", len(pd) > 10, f"{len(pd)} piezas")
check("Malla densa: tiempos razonables", t_cut < 120 and t_merge < 300,
      f"corte {t_cut:.0f}s, fusión {t_merge:.0f}s")

print("\n" + "=" * 60)
if FAILS:
    print(f"❌ {len(FAILS)} FALLOS: {FAILS}"); sys.exit(1)
print("✅ TODOS LOS TESTS DEL ENGINE PASAN")
