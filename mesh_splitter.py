#!/usr/bin/env python3
"""
MeshSplitter — Corte de mallas STL en bloques imprimibles (3 ejes).
- Separación de componentes conectados post-corte
- Unidades inteligentes + detección nativa
- Fusión de piezas pequeñas por contacto físico real
- Irregularidad (efecto piedra)
- Espigas + agujeros en la zona de contacto real
- Tabla ordenable, peso estimado, drag & drop, preview de planos

Desarrollado por Osuvense con asistencia de IA (Claude, Anthropic).
Licencia MIT. Historial interno: v1-v7 (mar-jun 2026) → público 0.9.0.
"""

APP_NAME = "MeshSplitter"
APP_VERSION = "0.9.0-beta"

import sys, os, math
import numpy as np
import trimesh
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Forzar PySide6 en qtpy (pyvistaqt) aunque conviva otro binding en el venv
os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QPushButton, QSlider, QSpinBox,
    QDoubleSpinBox, QTableWidget, QTableWidgetItem, QFileDialog,
    QSplitter, QHeaderView, QMessageBox, QCheckBox,
    QFrame, QScrollArea, QComboBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

import pyvista as pv
from pyvistaqt import QtInteractor

from scipy.ndimage import gaussian_filter
from scipy.interpolate import RegularGridInterpolator

import shapely.geometry as sg
from shapely.ops import unary_union


PIECE_COLORS = [
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2",
    "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7",
    "#9C755F", "#BAB0AC", "#86BCB6", "#D4A6C8",
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4",
    "#FFEAA7", "#DDA0DD", "#98D8C8", "#F7DC6F",
]

H2D_VOLUME = (315.0, 315.0, 315.0)
X1C_VOLUME = (245.0, 245.0, 245.0)
AXIS_NAMES = ["X", "Y", "Z"]
AXIS_COLORS = {"X": "#E15759", "Y": "#59A14F", "Z": "#4E79A7"}

# Densidades nominales de filamento (g/cm³), valores típicos de datasheet
MATERIAL_DENSITY = {
    "PLA": 1.24, "PETG": 1.27, "ABS": 1.04,
    "ASA": 1.07, "TPU": 1.21, "PC": 1.20,
}


def smart_weight_str(grams):
    if grams >= 1000: return f"{grams/1000:.2f} kg"
    return f"{grams:.0f} g"


def estimate_piece_weight(piece, density_g_cm3, infill_pct, wall_mm):
    """Estimación FDM estándar: paredes macizas (área superficial × espesor)
    + interior al % de relleno. Devuelve (gramos, volumen_real_cm3, watertight)."""
    watertight = bool(piece.is_watertight)
    vol_mm3 = abs(float(piece.volume))
    area_mm2 = float(piece.area)
    shell_mm3 = min(area_mm2 * wall_mm, vol_mm3)
    interior_mm3 = max(vol_mm3 - shell_mm3, 0.0)
    solid_mm3 = shell_mm3 + interior_mm3 * (infill_pct / 100.0)
    grams = (solid_mm3 / 1000.0) * density_g_cm3
    return grams, vol_mm3 / 1000.0, watertight


def smart_dims_str(dims_mm):
    mx = max(dims_mm)
    if mx >= 10000:
        return f"{dims_mm[0]/1000:.2f} × {dims_mm[1]/1000:.2f} × {dims_mm[2]/1000:.2f} m"
    elif mx >= 1000:
        return f"{dims_mm[0]/10:.1f} × {dims_mm[1]/10:.1f} × {dims_mm[2]/10:.1f} cm"
    return f"{dims_mm[0]:.1f} × {dims_mm[1]:.1f} × {dims_mm[2]:.1f} mm"


def guess_native_units(dims):
    mx = max(dims)
    if mx < 0.01: return "km (¿?)", "Modelo extremadamente pequeño"
    elif mx < 5: return "metros", "Típico de IA (Hunyuan). Escala ×1000 para mm."
    elif mx < 100: return "centímetros", "Escala ×10 para mm."
    elif mx < 5000: return "milímetros", "Probablemente ya en mm. Escala ×1."
    return "milímetros (grande)", "Modelo grande. Escala ×1 si correcto."


def min_dimension(piece): return float(np.min(piece.bounds[1] - piece.bounds[0]))


def bboxes_touch(a, b, tol=1.0):
    """True si las bounding boxes de a y b se tocan o solapan (con tolerancia).
    Condición necesaria (no suficiente) de contacto físico real."""
    return all(a.bounds[0][k] <= b.bounds[1][k] + tol and
               b.bounds[0][k] <= a.bounds[1][k] + tol for k in range(3))


def manifold_repair(mesh):
    """Reparación profunda vía manifold3d: suelda vértices duplicados y
    reconstruye un sólido manifold (lo que hace tragables las mallas STL
    'sucias' reales). Devuelve la malla reparada o None si no se pudo."""
    try:
        import manifold3d as m3
        mgl = m3.Mesh(vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
                      tri_verts=np.asarray(mesh.faces, dtype=np.uint32))
        mgl.merge()
        man = m3.Manifold(mgl)
        if man.status() != m3.Error.NoError:
            return None
        out = man.to_mesh()
        rep = trimesh.Trimesh(vertices=np.asarray(out.vert_properties)[:, :3],
                              faces=np.asarray(out.tri_verts), process=False)
        if rep.is_volume and len(rep.faces) > 0 and abs(rep.volume) > 1e-6:
            return rep
        return None
    except Exception:
        return None


def ensure_volume(mesh):
    """Reparación para que las booleanas manifold acepten la malla (exigen
    volúmenes cerrados): primero arreglos ligeros de trimesh, después la
    reconstrucción manifold. Si nada funciona, devuelve la original."""
    if getattr(mesh, "is_volume", False): return mesh
    m = mesh.copy()
    try:
        m.update_faces(m.nondegenerate_faces())
        m.remove_unreferenced_vertices()
        m.merge_vertices()
        trimesh.repair.fix_winding(m)
        trimesh.repair.fix_inversion(m)
        m.fill_holes()
    except Exception:
        m = None
    if m is not None and getattr(m, "is_volume", False):
        return m
    rep = manifold_repair(mesh)
    return rep if rep is not None else mesh


def _robust_boolean(op, a, b):
    """Booleana manifold en escalera: estricta → reparar y reintentar →
    sin pre-check (manifold tolera defectos menores). El resultado del último
    escalón se valida: si sale vacío, se lanza (el caller decide/avisa) en vez
    de devolver una pieza fantasma."""
    try:
        return op([a, b], engine="manifold")
    except Exception:
        pass
    a2, b2 = ensure_volume(a), ensure_volume(b)
    try:
        return op([a2, b2], engine="manifold")
    except Exception:
        pass
    r = op([a2, b2], engine="manifold", check_volume=False)
    if r is None or len(r.faces) == 0 or abs(getattr(r, "volume", 0.0)) < 1e-6:
        raise ValueError("resultado booleano vacío (malla irreparable)")
    return r


def robust_union(a, b):
    return _robust_boolean(trimesh.boolean.union, a, b)


def robust_difference(a, b):
    return _robust_boolean(trimesh.boolean.difference, a, b)


def is_degenerate_sliver(piece, thickness_mm=0.2, volume_mm3=1.0):
    """Esquirla de ruido numérico del corte: espesor ~0 y volumen ~0.
    No es geometría real (no es un dedo ni una nariz): se puede descartar."""
    try:
        return (min_dimension(piece) < thickness_mm
                and abs(float(piece.volume)) < volume_mm3)
    except Exception:
        return False


def split_connected_components(mesh):
    """Separa una malla en sus componentes conectados.
    Devuelve lista de mallas, cada una un cuerpo sólido independiente."""
    try:
        # body_count nos da cuántos cuerpos hay
        components = mesh.split(only_watertight=False)
        if components is None or len(components) == 0:
            return [mesh]
        # Filtrar componentes vacíos
        result = [c for c in components if len(c.faces) > 0]
        return result if result else [mesh]
    except Exception:
        return [mesh]


def position_outside_bounds(axis, position, bounds, margin=0.01):
    return position <= bounds[0][axis] + margin or position >= bounds[1][axis] - margin


@dataclass
class CutDef:
    axis: int
    position: float

@dataclass
class PieceInfo:
    index: int
    width: float
    depth: float
    height: float
    min_dim: float
    x_min: float; x_max: float
    y_min: float; y_max: float
    z_min: float; z_max: float
    triangles: int
    volume_cm3: float          # volumen real de la malla (no bounding box)
    weight_g: float            # peso estimado según material/relleno/pared
    watertight: bool           # False → volumen y peso menos fiables
    fits_h2d: bool
    fits_x1c: bool
    merged: bool
    unmerged_small: bool = False   # pequeña sin contacto: no se pudo fusionar


class CuttingEngine:

    @staticmethod
    def slice_at_plane(mesh, axis, position):
        try:
            origin = [0.0, 0.0, 0.0]; origin[axis] = position
            nn = [0.0, 0.0, 0.0]; nn[axis] = -1.0
            np_ = [0.0, 0.0, 0.0]; np_[axis] = 1.0

            neg = trimesh.intersections.slice_mesh_plane(mesh, plane_normal=nn, plane_origin=origin, cap=True)
            pos = trimesh.intersections.slice_mesh_plane(mesh, plane_normal=np_, plane_origin=origin, cap=True)

            if neg is not None and len(neg.faces) == 0: neg = None
            if pos is not None and len(pos.faces) == 0: pos = None
            return neg, pos
        except Exception as e:
            print(f"Error cortando {AXIS_NAMES[axis]} en {position:.1f}: {e}")
            return None, None

    @staticmethod
    def generate_noise_2d(size=40, amplitude=2.0, seed=0):
        rng = np.random.RandomState(seed)
        raw = rng.randn(size, size)
        smooth = gaussian_filter(raw, sigma=size / 6.0)
        if smooth.max() != smooth.min():
            smooth = 2.0 * (smooth - smooth.min()) / (smooth.max() - smooth.min()) - 1.0
        return smooth * amplitude

    @staticmethod
    def apply_irregularity(piece, axis, position, noise_grid, mesh_bounds):
        verts = piece.vertices.copy()
        cap_mask = np.abs(verts[:, axis] - position) < 0.1
        if not np.any(cap_mask): return piece

        uv = [i for i in range(3) if i != axis]
        res = noise_grid.shape[0]; m = 5.0
        us = np.linspace(mesh_bounds[0][uv[0]]-m, mesh_bounds[1][uv[0]]+m, res)
        vs = np.linspace(mesh_bounds[0][uv[1]]-m, mesh_bounds[1][uv[1]]+m, res)

        interp = RegularGridInterpolator((us, vs), noise_grid, method="linear",
                                          bounds_error=False, fill_value=0.0)
        cap_uv = np.column_stack([verts[cap_mask, uv[0]], verts[cap_mask, uv[1]]])
        verts[cap_mask, axis] += interp(cap_uv)
        return trimesh.Trimesh(vertices=verts, faces=piece.faces, process=False)

    @staticmethod
    def compute_auto_cuts(mesh_bounds, max_size):
        cuts = []
        for axis in range(3):
            lo, hi = mesh_bounds[0][axis], mesh_bounds[1][axis]
            span = hi - lo
            if span <= max_size[axis]: continue
            nd = math.ceil(span / max_size[axis])
            step = span / nd; mg = step * 0.01
            for i in range(1, nd):
                pos = lo + step * i
                if lo + mg < pos < hi - mg:
                    cuts.append(CutDef(axis=axis, position=pos))
        return cuts

    @staticmethod
    def cut_mesh_multiaxis(mesh, cuts, irregularity=0.0, seed_base=42):
        if not cuts: return [mesh.copy()]

        pieces = [mesh.copy()]
        mesh_bounds = mesh.bounds.copy()

        for ci, cut in enumerate(cuts):
            new_pieces = []
            noise = None
            if irregularity > 0.01:
                noise = CuttingEngine.generate_noise_2d(amplitude=irregularity, seed=seed_base+ci)

            for piece in pieces:
                if position_outside_bounds(cut.axis, cut.position, piece.bounds):
                    new_pieces.append(piece); continue

                neg, pos = CuttingEngine.slice_at_plane(piece, cut.axis, cut.position)
                if neg is None and pos is None:
                    new_pieces.append(piece); continue

                if noise is not None:
                    if neg is not None:
                        neg = CuttingEngine.apply_irregularity(neg, cut.axis, cut.position, noise, mesh_bounds)
                    if pos is not None:
                        pos = CuttingEngine.apply_irregularity(pos, cut.axis, cut.position, noise, mesh_bounds)

                if neg is not None: new_pieces.append(neg)
                if pos is not None: new_pieces.append(pos)

            pieces = new_pieces

        # ── CLAVE: separar componentes conectados ──
        # Un corte puede generar fragmentos desconectados dentro de la misma pieza.
        # Los separamos para que la fusión pueda detectarlos individualmente.
        all_pieces = []
        slivers = 0
        for piece in pieces:
            for c in split_connected_components(piece):
                if is_degenerate_sliver(c):
                    slivers += 1; continue
                all_pieces.append(c)
        if slivers:
            print(f"  AVISO {slivers} esquirla(s) degenerada(s) del corte descartada(s) "
                  f"(espesor y volumen ~0: ruido numérico, no geometría)")

        return all_pieces

    @staticmethod
    def merge_small_pieces(pieces, min_dim_mm, status_callback=None):
        """Fusiona piezas pequeñas SOLO con vecinas en contacto físico real.

        Candidatas = piezas cuya bounding box toca la de la pequeña; se intenta
        la unión por orden de cercanía (prefiriendo no-pequeñas) y se acepta
        únicamente si el resultado es UN solo cuerpo conectado (body_count==1).
        Una unión que deja dos cuerpos sueltos en la misma malla NO es una
        fusión: era el bug que dejaba fragmentos pequeños vivos.

        Devuelve (pieces, merged_flags, unmerged_flags):
        - merged_flags[i]: la pieza i absorbió al menos una pequeña.
        - unmerged_flags[i]: pieza pequeña sin contacto con nada → queda viva
          y marcada para decisión humana (no se descarta ni se finge fusión).
        """
        n0 = len(pieces)
        if min_dim_mm <= 0 or n0 <= 1:
            return list(pieces), [False] * n0, [False] * n0

        pieces = list(pieces)
        merged_flags = [False] * n0
        unmerged = [False] * n0

        for iteration in range(500):
            small = [i for i, p in enumerate(pieces)
                     if not unmerged[i] and min_dimension(p) < min_dim_mm]
            if not small: break

            if status_callback:
                status_callback(f"Fusionando: quedan {len(small)} pieza(s) pequeña(s)…")

            si = small[0]
            sp = pieces[si]
            sc = (sp.bounds[0] + sp.bounds[1]) / 2
            small_set = set(small)

            cands = []
            for j, p in enumerate(pieces):
                if j == si or not bboxes_touch(sp, p): continue
                dist = float(np.linalg.norm((p.bounds[0] + p.bounds[1]) / 2 - sc))
                cands.append((j in small_set, dist, j))
            cands.sort()

            merged_into = None
            sp_v = ensure_volume(sp)
            for _, _, j in cands:
                try:
                    u = robust_union(ensure_volume(pieces[j]), sp_v)
                except Exception as e:
                    print(f"  AVISO Fusión fallida con vecina {j}: {e}")
                    continue
                if u.body_count == 1:
                    pieces[j] = u
                    merged_into = j
                    break
                # body_count > 1: tocaban por bbox pero no hay contacto real

            if merged_into is not None:
                merged_flags[merged_into] = True
                del pieces[si]; del merged_flags[si]; del unmerged[si]
            else:
                unmerged[si] = True
                print(f"  AVISO Pieza pequeña sin contacto real con ninguna vecina: "
                      f"queda sin fusionar (min {min_dimension(sp):.1f} mm)")

        return pieces, merged_flags, unmerged

    @staticmethod
    def find_adjacencies(pieces, cuts, tolerance=5.0):
        """Parejas (lado_negativo, lado_positivo) por plano de corte.
        Cada pareja se devuelve UNA sola vez aunque haya cortes colineales a
        menos de `tolerance` (evita rondas duplicadas de espigas montadas)."""
        adjs = []
        seen = set()
        for cut in cuts:
            ax, pos = cut.axis, cut.position
            negs = [i for i, p in enumerate(pieces) if abs(p.bounds[1][ax] - pos) < tolerance]
            poss = [i for i, p in enumerate(pieces) if abs(p.bounds[0][ax] - pos) < tolerance]
            uv = [a for a in range(3) if a != ax]
            for ni in negs:
                for pi in poss:
                    if ni == pi or (ni, pi) in seen: continue
                    ok = all(
                        not (pieces[ni].bounds[1][a] < pieces[pi].bounds[0][a] - tolerance or
                             pieces[pi].bounds[1][a] < pieces[ni].bounds[0][a] - tolerance)
                        for a in uv)
                    if ok:
                        seen.add((ni, pi))
                        adjs.append((ni, pi, ax, pos))
        return adjs

    @staticmethod
    def _section_polygon(piece, axis, position, to_2d):
        """Sección 2D de la pieza en el plano (shapely, agujeros incluidos)."""
        origin = [0.0, 0.0, 0.0]; origin[axis] = position
        normal = [0.0, 0.0, 0.0]; normal[axis] = 1.0
        try:
            sec = piece.section(plane_origin=origin, plane_normal=normal)
            if sec is None: return None
            # trimesh ≥4.x renombró to_planar → to_2D (mismo kwarg)
            conv = getattr(sec, "to_2D", None) or sec.to_planar
            p2d, _ = conv(to_2D=to_2d)
            polys = [p for p in p2d.polygons_full if p is not None]
            if not polys: return None
            poly = unary_union([sg.Polygon(p.exterior, p.interiors).buffer(0) for p in polys])
            return None if poly.is_empty else poly
        except Exception as e:
            print(f"  AVISO sección en {AXIS_NAMES[axis]}={position:.1f}: {e}")
            return None

    @staticmethod
    def contact_region(piece_a, piece_b, axis, position, offset=0.5):
        """Zona de contacto real entre las dos piezas en el plano de corte:
        intersección de la sección de A (un poco dentro de A) con la de B (un
        poco dentro de B). offset esquiva la zona ondulada por irregularidad.
        Devuelve (polígono shapely en el frame del plano, matriz to_2d 4×4)."""
        origin = [0.0, 0.0, 0.0]; origin[axis] = position
        normal = [0.0, 0.0, 0.0]; normal[axis] = 1.0
        to_2d = trimesh.geometry.plane_transform(origin, normal)
        pa = CuttingEngine._section_polygon(piece_a, axis, position - offset, to_2d)
        pb = CuttingEngine._section_polygon(piece_b, axis, position + offset, to_2d)
        if pa is None or pb is None: return None, to_2d
        contact = pa.intersection(pb)
        return (None if contact.is_empty else contact), to_2d

    @staticmethod
    def _pick_points_inside(region, n, clearance):
        """Hasta n puntos dentro de la región erosionada por clearance,
        bien repartidos (greedy farthest-point sobre un grid adaptativo).
        El grid se refina hasta encontrar candidatos: regiones delgadas
        (anillos de piezas huecas) necesitan paso fino aunque el bbox sea grande."""
        inner = region.buffer(-clearance)
        if inner.is_empty: return []
        try:
            from shapely.prepared import prep
            contains = prep(inner).contains
        except Exception:
            contains = inner.contains
        minx, miny, maxx, maxy = inner.bounds
        step = max(maxx - minx, maxy - miny, 10.0) / 10.0
        min_step = max(1.0, clearance / 2.0)
        cand = []
        while True:
            cand = [sg.Point(x, y)
                    for x in np.arange(minx, maxx + step, step)
                    for y in np.arange(miny, maxy + step, step)
                    if contains(sg.Point(x, y))]
            if len(cand) >= max(n * 3, 8) or step <= min_step: break
            step /= 2.0
        if not cand:
            cand = [inner.representative_point()]
        # primero: el punto más interior; siguientes: máx. distancia a los ya elegidos
        chosen = [max(cand, key=lambda p: p.distance(inner.boundary))]
        while len(chosen) < n and len(chosen) < len(cand):
            best = max(cand, key=lambda p: min(p.distance(c) for c in chosen))
            if best in chosen: break
            chosen.append(best)
        return chosen[:n]

    @staticmethod
    def _axis_cylinder(radius, length, axis, sections=24):
        cyl = trimesh.creation.cylinder(radius=radius, height=length, sections=sections)
        if axis == 0:
            cyl.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0, 1, 0]))
        elif axis == 1:
            cyl.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [1, 0, 0]))
        return cyl

    @staticmethod
    def add_dowels_between(piece_a, piece_b, axis, position,
                           n_dowels, radius, height, tolerance,
                           section_offset=0.5, loose=False):
        """Espigas SOLO dentro de la zona de contacto real entre ambas piezas.

        Dos modos:
        - loose=False (adheridas): pin embebido en A sobresaliendo hacia B,
          agujero en B. Unión verificada por body_count.
        - loose=True (sueltas): agujero en AMBAS caras (profundidad height/2
          + holgura); las espigas se imprimen aparte (export genera su STL).
          Ventaja: ninguna pieza tiene salientes → impresión sin soportes.
        Devuelve (piece_a, piece_b, n_colocadas)."""
        if n_dowels <= 0: return piece_a, piece_b, 0

        piece_a = ensure_volume(piece_a)
        piece_b = ensure_volume(piece_b)
        region, to_2d = CuttingEngine.contact_region(
            piece_a, piece_b, axis, position, offset=section_offset)
        if region is None:
            return piece_a, piece_b, 0

        clearance = radius + tolerance + 2.0
        points = CuttingEngine._pick_points_inside(region, n_dowels, clearance)
        if not points:
            return piece_a, piece_b, 0

        embed = max(5.0, section_offset + 2.0)   # penetración del pin en A (modo adherido)
        to_3d = np.linalg.inv(to_2d)
        placed = 0
        half = height / 2.0

        for pt in points:
            p3 = (to_3d @ np.array([pt.x, pt.y, 0.0, 1.0]))[:3]

            if loose:
                # ── Agujero en A: de position-(half+0.5) a position+0.5 ──
                hole_a = CuttingEngine._axis_cylinder(radius + tolerance, half + 1.0, axis)
                ca = p3.copy(); ca[axis] = position - half / 2.0
                hole_a.apply_translation(ca)
                # ── Agujero en B: de position-0.5 a position+(half+0.5) ──
                hole_b = CuttingEngine._axis_cylinder(radius + tolerance, half + 1.0, axis)
                cb = p3.copy(); cb[axis] = position + half / 2.0
                hole_b.apply_translation(cb)
                try:
                    va = abs(piece_a.volume)
                    new_a = robust_difference(piece_a, hole_a)
                    new_b = robust_difference(piece_b, hole_b)
                    if abs(new_a.volume) >= va:   # el agujero no restó nada
                        print(f"  AVISO Agujero sin efecto en {np.round(p3,1)}, descartado")
                        continue
                    piece_a, piece_b = new_a, new_b
                    placed += 1
                except Exception as e:
                    print(f"  AVISO Agujeros (modo suelto): {e}")
                continue

            # ── Modo adherido: pin de position-embed a position+height ──
            pin = CuttingEngine._axis_cylinder(radius, height + embed, axis)
            center = p3.copy(); center[axis] = position + (height - embed) / 2.0
            pin.apply_translation(center)
            try:
                bodies_before = piece_a.body_count
                result = robust_union(piece_a, pin)
                if result.body_count > bodies_before:
                    print(f"  AVISO Espiga en {np.round(p3,1)}: sin soldadura real, descartada")
                    continue
                piece_a = result
            except Exception as e:
                print(f"  AVISO Espiga: {e}")
                continue

            # ── Agujero: radio+tolerancia, algo más profundo ──
            hole = CuttingEngine._axis_cylinder(radius + tolerance, height + embed + 0.5, axis)
            center_h = p3.copy(); center_h[axis] = position + (height - embed + 0.5) / 2.0
            hole.apply_translation(center_h)
            try:
                piece_b = robust_difference(piece_b, hole)
                placed += 1
            except Exception as e:
                print(f"  AVISO Agujero: {e}")

        return piece_a, piece_b, placed

    @staticmethod
    def get_piece_info(piece, index, merged=False, weight_params=None, unmerged_small=False):
        """weight_params: (densidad g/cm³, infill %, pared mm) o None."""
        b = piece.bounds; d = b[1] - b[0]
        if weight_params is not None:
            grams, vol_cm3, wt = estimate_piece_weight(piece, *weight_params)
        else:
            vol_cm3 = abs(float(piece.volume)) / 1000.0
            grams, wt = 0.0, bool(piece.is_watertight)
        return PieceInfo(
            index=index, width=d[0], depth=d[1], height=d[2],
            min_dim=float(np.min(d)),
            x_min=b[0][0], x_max=b[1][0],
            y_min=b[0][1], y_max=b[1][1],
            z_min=b[0][2], z_max=b[1][2],
            triangles=len(piece.faces),
            volume_cm3=vol_cm3,
            weight_g=grams,
            watertight=wt,
            fits_h2d=all(d[i] <= H2D_VOLUME[i] for i in range(3)),
            fits_x1c=all(d[i] <= X1C_VOLUME[i] for i in range(3)),
            merged=merged,
            unmerged_small=unmerged_small
        )


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class CutPlaneWidget(QFrame):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, index, axis=2, value=0.0, bounds=None, parent=None):
        super().__init__(parent)
        self.index = index; self.setFrameShape(QFrame.StyledPanel)
        layout = QHBoxLayout(self); layout.setContentsMargins(4, 2, 4, 2)

        self.label = QLabel(f"#{index+1}"); self.label.setFixedWidth(28)
        self.axis_combo = QComboBox(); self.axis_combo.addItems(["X","Y","Z"])
        self.axis_combo.setCurrentIndex(axis); self.axis_combo.setFixedWidth(50)
        self.axis_combo.currentIndexChanged.connect(self._uc)
        self.axis_combo.currentIndexChanged.connect(lambda: self.changed.emit())

        self.pos_spin = QDoubleSpinBox(); self.pos_spin.setDecimals(1)
        self.pos_spin.setSingleStep(5.0); self.pos_spin.setSuffix(" mm")
        if bounds is not None: self.pos_spin.setRange(bounds[0][axis]-10, bounds[1][axis]+10)
        else: self.pos_spin.setRange(-100000, 100000)
        self.pos_spin.setValue(value); self.pos_spin.valueChanged.connect(self.changed.emit)

        self.remove_btn = QPushButton("✕"); self.remove_btn.setFixedWidth(30)
        self.remove_btn.clicked.connect(lambda: self.removed.emit(self))

        layout.addWidget(self.label); layout.addWidget(self.axis_combo)
        layout.addWidget(self.pos_spin, 1); layout.addWidget(self.remove_btn)
        self._uc()

    def _uc(self):
        c = AXIS_COLORS[AXIS_NAMES[self.axis_combo.currentIndex()]]
        self.label.setStyleSheet(f"color: {c}; font-weight: bold;")

    @property
    def cut_def(self): return CutDef(axis=self.axis_combo.currentIndex(), position=self.pos_spin.value())
    def set_index(self, i): self.index = i; self.label.setText(f"#{i+1}")
    def update_bounds(self, b):
        a = self.axis_combo.currentIndex(); self.pos_spin.setRange(b[0][a]-10, b[1][a]+10)


class NumericTableItem(QTableWidgetItem):
    def __init__(self, text, sort_value=None):
        super().__init__(text); self._sv = sort_value if sort_value is not None else 0.0
    def __lt__(self, other):
        if isinstance(other, NumericTableItem): return self._sv < other._sv
        return super().__lt__(other)


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------

class MeshSplitterApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — Corte de STL en bloques imprimibles")
        self.setMinimumSize(1400, 900)
        self.original_mesh = None; self.scaled_mesh = None
        self.pieces = []; self.piece_infos = []; self.cut_widgets = []; self.stl_path = None
        self.plane_actors = []
        self._build_ui(); self._connect_signals()
        self.setAcceptDrops(True)
        self.statusBar().showMessage("Listo. Carga un STL para empezar (o arrástralo a la ventana).")

    # ── Drag & drop de STL ──
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".stl"):
                    event.acceptProposedAction(); return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".stl"):
                self._load_path(url.toLocalFile()); return

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        ml = QHBoxLayout(central); ml.setContentsMargins(6,6,6,6)

        # Panel lateral: ancho ajustable vía splitter (antes fijo a 370 px, que
        # con las métricas de Qt 6 quedaba corto y forzaba scroll horizontal)
        ls = QScrollArea(); ls.setWidgetResizable(True)
        ls.setMinimumWidth(340)
        ls.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lw = QWidget(); self.left_layout = QVBoxLayout(lw); self.left_layout.setAlignment(Qt.AlignTop)
        ls.setWidget(lw)

        self._build_file_group(); self._build_scale_group(); self._build_autosize_group()
        self._build_cuts_group(); self._build_merge_group()
        self._build_irregularity_group(); self._build_dowels_group()
        self._build_weight_group()
        self._build_actions_group(); self.left_layout.addStretch()

        rs = QSplitter(Qt.Vertical)
        pf = QFrame(); pl = QVBoxLayout(pf); pl.setContentsMargins(0,0,0,0)
        self.plotter = QtInteractor(pf); pl.addWidget(self.plotter.interactor)
        # pyvistaqt acepta drops y pinta la malla por su cuenta SIN cargarla en
        # la app (add_mesh directo). Lo desactivamos: el drop sube a la ventana,
        # que sí hace la carga real (_load_path).
        self.plotter.setAcceptDrops(False)
        rs.addWidget(pf)

        vb = QHBoxLayout(); vb.addWidget(QLabel("Separación:"))
        self.explode_slider = QSlider(Qt.Horizontal); self.explode_slider.setRange(0,100); self.explode_slider.setValue(0)
        self.explode_value = QLabel("0%"); vb.addWidget(self.explode_slider,1); vb.addWidget(self.explode_value)
        vw = QWidget(); vw.setLayout(vb); vw.setFixedHeight(36)

        self.table = QTableWidget(); self.table.setColumnCount(13)
        self.table.setHorizontalHeaderLabels(["#","X","Y","Z","Mín","X rng","Y rng","Z rng","Vol(cm³)","Peso","H2D","X1C","Notas"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True); self.table.setMaximumHeight(300)

        tc = QWidget(); tcl = QVBoxLayout(tc); tcl.setContentsMargins(0,0,0,0)
        tcl.addWidget(vw); tcl.addWidget(self.table)
        rs.addWidget(tc); rs.setSizes([600,300])

        hs = QSplitter(Qt.Horizontal)
        hs.addWidget(ls); hs.addWidget(rs)
        hs.setStretchFactor(0, 0)   # el panel mantiene su ancho al redimensionar
        hs.setStretchFactor(1, 1)   # el viewport absorbe el espacio extra
        hs.setSizes([420, 1000])
        ml.addWidget(hs)

    def _build_file_group(self):
        g = QGroupBox("Archivo"); l = QVBoxLayout(g)
        self.btn_load = QPushButton("Cargar STL…")
        self.lbl_file = QLabel("Ningún archivo cargado"); self.lbl_file.setWordWrap(True)
        self.lbl_mesh_info = QLabel(""); self.lbl_mesh_info.setWordWrap(True)
        l.addWidget(self.btn_load); l.addWidget(self.lbl_file); l.addWidget(self.lbl_mesh_info)
        self.left_layout.addWidget(g)

    def _build_scale_group(self):
        g = QGroupBox("Escala"); l = QVBoxLayout(g)
        r = QHBoxLayout(); r.addWidget(QLabel("Uniforme:"))
        self.scale_uniform = QDoubleSpinBox(); self.scale_uniform.setRange(0.001,100000)
        self.scale_uniform.setDecimals(3); self.scale_uniform.setValue(1000.0)
        r.addWidget(self.scale_uniform,1); l.addLayout(r)
        self.chk_xyz = QCheckBox("Escala independiente por eje"); l.addWidget(self.chk_xyz)
        self.xyz_container = QWidget(); xl = QVBoxLayout(self.xyz_container); xl.setContentsMargins(0,0,0,0)
        self.scale_x = QDoubleSpinBox(); self.scale_y = QDoubleSpinBox(); self.scale_z = QDoubleSpinBox()
        for sb, lb in [(self.scale_x,"X:"),(self.scale_y,"Y:"),(self.scale_z,"Z:")]:
            sb.setRange(0.001,100000); sb.setDecimals(3); sb.setValue(1000.0)
            rr = QHBoxLayout(); rr.addWidget(QLabel(lb)); rr.addWidget(sb,1); xl.addLayout(rr)
        self.xyz_container.setVisible(False); l.addWidget(self.xyz_container)
        self.btn_apply_scale = QPushButton("Aplicar escala"); l.addWidget(self.btn_apply_scale)
        self.lbl_scaled_dims = QLabel(""); self.lbl_scaled_dims.setWordWrap(True); l.addWidget(self.lbl_scaled_dims)
        self.left_layout.addWidget(g)

    def _build_autosize_group(self):
        g = QGroupBox("Tamaño máximo de pieza"); l = QVBoxLayout(g)
        pr = QHBoxLayout()
        self.btn_preset_h2d = QPushButton("Preset H2D (315³)")
        self.btn_preset_x1c = QPushButton("Preset X1C (245³)")
        pr.addWidget(self.btn_preset_h2d); pr.addWidget(self.btn_preset_x1c); l.addLayout(pr)
        self.max_x=QDoubleSpinBox(); self.max_y=QDoubleSpinBox(); self.max_z=QDoubleSpinBox()
        for sb,lb,dv in [(self.max_x,"Máx X:",245),(self.max_y,"Máx Y:",245),(self.max_z,"Máx Z:",245)]:
            sb.setRange(10,10000); sb.setDecimals(1); sb.setSingleStep(10); sb.setSuffix(" mm"); sb.setValue(dv)
            r=QHBoxLayout(); r.addWidget(QLabel(lb)); r.addWidget(sb,1); l.addLayout(r)
        self.btn_auto_size = QPushButton("Generar cortes por tamaño"); self.btn_auto_size.setMinimumHeight(32)
        l.addWidget(self.btn_auto_size)
        self.lbl_auto_info = QLabel(""); l.addWidget(self.lbl_auto_info)
        self.left_layout.addWidget(g)

    def _build_cuts_group(self):
        g = QGroupBox("Cortes manuales"); l = QVBoxLayout(g)
        ar = QHBoxLayout()
        self.btn_add_x=QPushButton("+ X"); self.btn_add_y=QPushButton("+ Y"); self.btn_add_z=QPushButton("+ Z")
        self.btn_clear_cuts = QPushButton("Borrar todos")
        for b,c in [(self.btn_add_x,AXIS_COLORS["X"]),(self.btn_add_y,AXIS_COLORS["Y"]),(self.btn_add_z,AXIS_COLORS["Z"])]:
            b.setStyleSheet(f"color:{c};font-weight:bold;"); ar.addWidget(b)
        ar.addWidget(self.btn_clear_cuts); l.addLayout(ar)
        self.cuts_container = QWidget(); self.cuts_layout = QVBoxLayout(self.cuts_container)
        self.cuts_layout.setContentsMargins(0,0,0,0); self.cuts_layout.setAlignment(Qt.AlignTop)
        cs = QScrollArea(); cs.setWidgetResizable(True); cs.setMaximumHeight(180); cs.setWidget(self.cuts_container)
        l.addWidget(cs)
        self.chk_show_planes = QCheckBox("Mostrar planos sobre el modelo")
        self.chk_show_planes.setChecked(True)
        self.chk_show_planes.setToolTip("Dibuja cada plano de corte sobre el modelo sin cortar,\ncon el color de su eje. Se actualiza al editar cortes.")
        l.addWidget(self.chk_show_planes)
        ag = QHBoxLayout(); ag.addWidget(QLabel("Distribuir:"))
        self.auto_axis=QComboBox(); self.auto_axis.addItems(["X","Y","Z"]); self.auto_axis.setCurrentIndex(2); self.auto_axis.setFixedWidth(50)
        ag.addWidget(self.auto_axis)
        self.auto_n_cuts=QSpinBox(); self.auto_n_cuts.setRange(1,20); self.auto_n_cuts.setValue(3); self.auto_n_cuts.setFixedWidth(50)
        ag.addWidget(self.auto_n_cuts)
        self.btn_auto_cuts=QPushButton("Auto"); ag.addWidget(self.btn_auto_cuts); l.addLayout(ag)
        self.left_layout.addWidget(g)

    def _build_merge_group(self):
        g = QGroupBox("Fusión de piezas pequeñas"); l = QVBoxLayout(g)
        self.chk_merge = QCheckBox("Fusionar piezas pequeñas con su vecina"); self.chk_merge.setChecked(True)
        self.chk_merge.setToolTip("Si la dimensión más pequeña < umbral,\nfusiona con la pieza más cercana.")
        l.addWidget(self.chk_merge)
        r = QHBoxLayout(); r.addWidget(QLabel("Grosor mínimo:"))
        self.min_dim_spin = QDoubleSpinBox(); self.min_dim_spin.setRange(0,500)
        self.min_dim_spin.setDecimals(1); self.min_dim_spin.setSingleStep(5); self.min_dim_spin.setSuffix(" mm")
        self.min_dim_spin.setValue(30.0); self.min_dim_spin.setToolTip("No quiero piezas más finas de X mm")
        r.addWidget(self.min_dim_spin,1); l.addLayout(r)
        self.lbl_merge_info = QLabel(""); l.addWidget(self.lbl_merge_info)
        self.left_layout.addWidget(g)

    def _build_irregularity_group(self):
        g = QGroupBox("Irregularidad"); l = QVBoxLayout(g)
        r = QHBoxLayout(); self.irreg_slider = QSlider(Qt.Horizontal)
        self.irreg_slider.setRange(0,50); self.irreg_slider.setValue(0)
        self.irreg_value = QLabel("0.0 mm"); r.addWidget(self.irreg_slider,1); r.addWidget(self.irreg_value)
        l.addLayout(r); l.addWidget(QLabel("0 = plano perfecto. Máx = ±5 mm."))
        self.left_layout.addWidget(g)

    def _build_dowels_group(self):
        g = QGroupBox("Espigas"); l = QVBoxLayout(g)
        self.chk_dowels = QCheckBox("Generar espigas y agujeros"); l.addWidget(self.chk_dowels)
        self.dowels_container = QWidget(); dl = QVBoxLayout(self.dowels_container); dl.setContentsMargins(0,0,0,0)

        rm = QHBoxLayout(); rm.addWidget(QLabel("Modo:"))
        self.dowel_mode = QComboBox()
        self.dowel_mode.addItem("Sueltas: agujeros + espigas aparte", userData=True)
        self.dowel_mode.addItem("Adheridas a la pieza", userData=False)
        self.dowel_mode.setToolTip(
            "Sueltas: agujero en ambas caras y un STL de espiga para imprimir\n"
            "aparte (N copias, ver informe). Ninguna pieza tiene salientes →\n"
            "impresión sin soportes. Recomendado.\n\n"
            "Adheridas: la espiga sobresale de una pieza y encaja en la otra.")
        rm.addWidget(self.dowel_mode, 1); dl.addLayout(rm)
        for lt,attr,dv,mn,mx,st,sf in [
            ("Cantidad/junta:","dowel_count",3,1,8,1,""),
            ("Radio (mm):","dowel_radius",5.0,1,20,0.5," mm"),
            ("Altura (mm):","dowel_height",15.0,5,50,1," mm"),
            ("Tolerancia (mm):","dowel_tol",0.3,0.05,2,0.05," mm")]:
            r=QHBoxLayout(); r.addWidget(QLabel(lt))
            if isinstance(dv,int): sb=QSpinBox(); sb.setRange(mn,mx); sb.setValue(dv)
            else: sb=QDoubleSpinBox(); sb.setRange(mn,mx); sb.setDecimals(2); sb.setSingleStep(st); sb.setSuffix(sf); sb.setValue(dv)
            setattr(self,attr,sb); r.addWidget(sb,1); dl.addLayout(r)
        self.dowels_container.setVisible(False); l.addWidget(self.dowels_container)
        self.left_layout.addWidget(g)

    def _build_weight_group(self):
        g = QGroupBox("Peso estimado"); l = QVBoxLayout(g)
        r = QHBoxLayout(); r.addWidget(QLabel("Material:"))
        self.material_combo = QComboBox()
        for name, dens in MATERIAL_DENSITY.items():
            self.material_combo.addItem(f"{name} ({dens} g/cm³)", userData=dens)
        r.addWidget(self.material_combo, 1); l.addLayout(r)

        r = QHBoxLayout(); r.addWidget(QLabel("Relleno:"))
        self.infill_spin = QSpinBox(); self.infill_spin.setRange(0, 100)
        self.infill_spin.setValue(15); self.infill_spin.setSuffix(" %")
        r.addWidget(self.infill_spin, 1); l.addLayout(r)

        r = QHBoxLayout(); r.addWidget(QLabel("Pared total:"))
        self.wall_spin = QDoubleSpinBox(); self.wall_spin.setRange(0.4, 10.0)
        self.wall_spin.setDecimals(1); self.wall_spin.setSingleStep(0.4)
        self.wall_spin.setValue(1.6); self.wall_spin.setSuffix(" mm")
        self.wall_spin.setToolTip("Espesor combinado de perímetros\n(p. ej. 4 paredes × 0.4 mm = 1.6 mm)")
        r.addWidget(self.wall_spin, 1); l.addLayout(r)

        self.lbl_weight_total = QLabel(""); l.addWidget(self.lbl_weight_total)
        self.left_layout.addWidget(g)

    def _weight_params(self):
        return (self.material_combo.currentData(),
                self.infill_spin.value(), self.wall_spin.value())

    def _build_actions_group(self):
        g = QGroupBox("Acciones"); l = QVBoxLayout(g)
        self.btn_preview = QPushButton("Previsualizar cortes")
        self.btn_cut = QPushButton("Cortar (con espigas si activadas)")
        self.btn_export = QPushButton("Exportar piezas STL…"); self.btn_export.setEnabled(False)
        for b in [self.btn_preview, self.btn_cut, self.btn_export]:
            b.setMinimumHeight(36); l.addWidget(b)
        self.left_layout.addWidget(g)

    def _connect_signals(self):
        self.btn_load.clicked.connect(self._on_load)
        self.btn_apply_scale.clicked.connect(self._on_apply_scale)
        self.chk_xyz.toggled.connect(self.xyz_container.setVisible)
        self.chk_xyz.toggled.connect(lambda c: self.scale_uniform.setEnabled(not c))
        self.btn_preset_h2d.clicked.connect(lambda: self._sm(*H2D_VOLUME))
        self.btn_preset_x1c.clicked.connect(lambda: self._sm(*X1C_VOLUME))
        self.btn_auto_size.clicked.connect(self._on_auto_size)
        self.btn_add_x.clicked.connect(lambda: self._on_add_cut(0))
        self.btn_add_y.clicked.connect(lambda: self._on_add_cut(1))
        self.btn_add_z.clicked.connect(lambda: self._on_add_cut(2))
        self.btn_clear_cuts.clicked.connect(self._on_clear_cuts)
        self.btn_auto_cuts.clicked.connect(self._on_auto_cuts)
        self.irreg_slider.valueChanged.connect(lambda v: self.irreg_value.setText(f"{v/10:.1f} mm"))
        self.chk_dowels.toggled.connect(self.dowels_container.setVisible)
        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_cut.clicked.connect(self._on_cut)
        self.btn_export.clicked.connect(self._on_export)
        self.explode_slider.valueChanged.connect(self._on_explode)
        self.material_combo.currentIndexChanged.connect(self._recompute_weights)
        self.infill_spin.valueChanged.connect(self._recompute_weights)
        self.wall_spin.valueChanged.connect(self._recompute_weights)
        self.chk_show_planes.toggled.connect(self._refresh_cut_planes)

    def _sm(self, x, y, z):
        self.max_x.setValue(x); self.max_y.setValue(y); self.max_z.setValue(z)

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cargar STL", "", "STL (*.stl);;Todos (*)")
        if not path: return
        self._load_path(path)

    def _load_path(self, path):
        self.statusBar().showMessage("Cargando…"); QApplication.processEvents()
        try: mesh = trimesh.load(path, force="mesh")
        except Exception as e: QMessageBox.critical(self, "Error", str(e)); return

        # STL reales muchas veces no son watertight: repararlos AQUÍ hace que
        # cortes, fusiones y espigas trabajen sobre geometría limpia.
        repair_note = ""
        if not mesh.is_volume:
            self.statusBar().showMessage("Malla no watertight: reparando…"); QApplication.processEvents()
            rep = manifold_repair(mesh)
            if rep is not None:
                mesh = rep
                repair_note = "\nMalla no watertight: REPARADA al cargar."
            else:
                repair_note = ("\nAVISO: malla no watertight y no reparable; "
                               "fusiones y espigas pueden fallar en algunas piezas.")

        self.original_mesh = mesh; self.scaled_mesh = None; self.pieces = []; self.stl_path = path
        d = mesh.bounds[1] - mesh.bounds[0]
        ug, uh = guess_native_units(d)

        self.lbl_file.setText(os.path.basename(path))
        self.lbl_mesh_info.setText(
            f"Triángulos: {len(mesh.faces):,}\n"
            f"Dims nativas: {d[0]:.4f} × {d[1]:.4f} × {d[2]:.4f}\n"
            f"Unidades probables: {ug}\n{uh}{repair_note}")

        mx = max(d)
        if mx < 5: self.scale_uniform.setValue(1000.0)
        elif mx < 100: self.scale_uniform.setValue(10.0)
        else: self.scale_uniform.setValue(1.0)

        self._show_mesh(mesh)
        self.statusBar().showMessage(f"Cargado: {len(mesh.faces):,} triángulos.")

    def _on_apply_scale(self):
        if not self.original_mesh: QMessageBox.warning(self, "Aviso", "Carga un STL primero."); return
        mesh = self.original_mesh.copy()
        if self.chk_xyz.isChecked():
            mesh.apply_scale([self.scale_x.value(), self.scale_y.value(), self.scale_z.value()])
        else: mesh.apply_scale(self.scale_uniform.value())

        self.scaled_mesh = mesh; d = mesh.bounds[1] - mesh.bounds[0]
        self.lbl_scaled_dims.setText(f"Escalado: {smart_dims_str(d)}\n({d[0]:.1f} × {d[1]:.1f} × {d[2]:.1f} mm)")
        for cw in self.cut_widgets: cw.update_bounds(mesh.bounds)
        self._show_mesh(mesh); self.pieces = []; self.btn_export.setEnabled(False); self._update_table([])
        self._refresh_cut_planes()
        self.statusBar().showMessage(f"Escala: {smart_dims_str(d)}")

    def _add_cut_widget(self, axis, value, bounds):
        i = len(self.cut_widgets)
        w = CutPlaneWidget(i, axis=axis, value=value, bounds=bounds)
        w.removed.connect(self._on_remove_cut)
        w.changed.connect(self._refresh_cut_planes)
        self.cuts_layout.addWidget(w); self.cut_widgets.append(w)
        return w

    def _on_auto_size(self):
        if not self.scaled_mesh: QMessageBox.warning(self, "Aviso", "Aplica escala primero."); return
        ms = (self.max_x.value(), self.max_y.value(), self.max_z.value())
        cuts = CuttingEngine.compute_auto_cuts(self.scaled_mesh.bounds, ms)
        if not cuts: self.lbl_auto_info.setText("Ya cabe sin cortes."); return
        self._on_clear_cuts(); b = self.scaled_mesh.bounds
        cx=sum(1 for c in cuts if c.axis==0); cy=sum(1 for c in cuts if c.axis==1); cz=sum(1 for c in cuts if c.axis==2)
        for cut in cuts: self._add_cut_widget(cut.axis, cut.position, b)
        self.lbl_auto_info.setText(f"{cx} en X, {cy} en Y, {cz} en Z → ~{(cx+1)*(cy+1)*(cz+1)} piezas máx.")
        self._refresh_cut_planes()

    def _on_add_cut(self, axis=2):
        b=None; dv=0.0
        if self.scaled_mesh is not None: b=self.scaled_mesh.bounds; dv=(b[0][axis]+b[1][axis])/2
        self._add_cut_widget(axis, dv, b)
        self._refresh_cut_planes()

    def _on_remove_cut(self, w):
        if w in self.cut_widgets:
            self.cut_widgets.remove(w); self.cuts_layout.removeWidget(w); w.deleteLater()
            for i,cw in enumerate(self.cut_widgets): cw.set_index(i)
            self._refresh_cut_planes()

    def _on_clear_cuts(self):
        for cw in list(self.cut_widgets): self.cuts_layout.removeWidget(cw); cw.deleteLater()
        self.cut_widgets.clear()
        self._refresh_cut_planes()

    def _on_auto_cuts(self):
        if not self.scaled_mesh: QMessageBox.warning(self, "Aviso", "Aplica escala primero."); return
        ax=self.auto_axis.currentIndex(); n=self.auto_n_cuts.value(); b=self.scaled_mesh.bounds
        lo,hi=b[0][ax],b[1][ax]; m=(hi-lo)*0.02
        for z in np.linspace(lo+m, hi-m, n+2)[1:-1]:
            self._add_cut_widget(ax, float(z), b)
        self._refresh_cut_planes()

    def _execute_cut(self, with_dowels=False):
        if not self.scaled_mesh: QMessageBox.warning(self, "Aviso", "Aplica escala primero."); return False
        cuts = [cw.cut_def for cw in self.cut_widgets]
        if not cuts: QMessageBox.warning(self, "Aviso", "Añade al menos un corte."); return False

        self.statusBar().showMessage("Cortando…"); QApplication.processEvents()
        pieces = CuttingEngine.cut_mesh_multiaxis(
            self.scaled_mesh, cuts, irregularity=self.irreg_slider.value()/10.0)
        if not pieces: QMessageBox.warning(self, "Aviso", "Sin piezas."); return False

        nb = len(pieces)
        self.statusBar().showMessage(f"Corte: {nb} piezas (incl. componentes separados).")
        QApplication.processEvents()

        mf = [False] * len(pieces); uf = [False] * len(pieces)
        if self.chk_merge.isChecked():
            md = self.min_dim_spin.value()
            pieces, mf, uf = CuttingEngine.merge_small_pieces(
                pieces, md,
                status_callback=lambda msg: (self.statusBar().showMessage(msg), QApplication.processEvents()))
            nm = nb - len(pieces)
            txt = f"Fusionadas {nm} → {len(pieces)} piezas." if nm > 0 else "Sin piezas bajo umbral."
            if any(uf): txt += f" {sum(uf)} sin contacto (ver Notas)."
            self.lbl_merge_info.setText(txt)

        self._dowel_summary = ""
        self._dowel_export = None
        if with_dowels and self.chk_dowels.isChecked() and len(pieces) > 1:
            self.statusBar().showMessage("Espigas…"); QApplication.processEvents()
            irreg = self.irreg_slider.value() / 10.0
            loose = bool(self.dowel_mode.currentData())
            adjs = CuttingEngine.find_adjacencies(pieces, cuts, tolerance=max(5.0, irreg + 1.0))
            n,r,h,t = self.dowel_count.value(), self.dowel_radius.value(), self.dowel_height.value(), self.dowel_tol.value()
            total_pins = 0; no_room = 0
            for ai,(ia,ib,ax,po) in enumerate(adjs):
                if ia < len(pieces) and ib < len(pieces):
                    self.statusBar().showMessage(f"Espigas {ai+1}/{len(adjs)}…"); QApplication.processEvents()
                    pieces[ia], pieces[ib], placed = CuttingEngine.add_dowels_between(
                        pieces[ia], pieces[ib], ax, po, n, r, h, t,
                        section_offset=max(0.5, irreg + 0.5), loose=loose)
                    total_pins += placed
                    if placed == 0: no_room += 1
            modo = "sueltas" if loose else "adheridas"
            self._dowel_summary = f" Espigas ({modo}): {total_pins} en {len(adjs)-no_room}/{len(adjs)} juntas."
            if loose and total_pins > 0:
                self._dowel_export = {"count": total_pins, "radius": r, "height": h}

        self.pieces = pieces
        wp = self._weight_params()
        self.piece_infos = [
            CuttingEngine.get_piece_info(
                p, i, merged=mf[i] if i < len(mf) else False, weight_params=wp,
                unmerged_small=uf[i] if i < len(uf) else False)
            for i, p in enumerate(pieces)]
        self._show_pieces(pieces); self._update_table(self.piece_infos)
        return True

    def _recompute_weights(self):
        """Recalcula peso/volumen de las piezas ya cortadas al cambiar material, relleno o pared."""
        if not self.pieces: return
        wp = self._weight_params()
        old = self.piece_infos
        self.piece_infos = [
            CuttingEngine.get_piece_info(
                p, i,
                merged=old[i].merged if i < len(old) else False,
                weight_params=wp,
                unmerged_small=old[i].unmerged_small if i < len(old) else False)
            for i, p in enumerate(self.pieces)]
        self._update_table(self.piece_infos)

    def _on_preview(self):
        if self._execute_cut(False):
            nx=sum(1 for p in self.piece_infos if p.fits_x1c)
            nh=sum(1 for p in self.piece_infos if p.fits_h2d and not p.fits_x1c)
            nb=sum(1 for p in self.piece_infos if not p.fits_h2d)
            self.btn_export.setEnabled(False)
            self.statusBar().showMessage(f"Preview: {len(self.pieces)} pzas | X1C: {nx} | Solo H2D: {nh} | No cabe: {nb}")

    def _on_cut(self):
        if self._execute_cut(True):
            self.btn_export.setEnabled(True)
            self.statusBar().showMessage(
                f"Final: {len(self.pieces)} piezas.{getattr(self, '_dowel_summary', '')} Listo para exportar.")

    def _on_export(self):
        if not self.pieces: return
        od = QFileDialog.getExistingDirectory(self, "Carpeta de exportación")
        if not od: return
        bn = Path(self.stl_path).stem if self.stl_path else "pieza"
        self.statusBar().showMessage("Exportando…"); QApplication.processEvents()
        exp = []
        for i, p in enumerate(self.pieces):
            fn = f"{bn}_bloque_{i+1:02d}.stl"; p.export(os.path.join(od, fn)); exp.append(fn)

        mat = self.material_combo.currentText().split(" ")[0]
        lines = [f"# Informe — {bn}", f"# Piezas: {len(self.pieces)}",
                 f"# H2D {H2D_VOLUME[0]:.0f}³, X1C {X1C_VOLUME[0]:.0f}³",
                 f"# Peso estimado: {mat}, {self.infill_spin.value()} % relleno, "
                 f"pared {self.wall_spin.value():.1f} mm (~ = pieza no watertight, estimación menos fiable)", "",
                 f"{'#':<4} {'X':<10} {'Y':<10} {'Z':<10} {'Mín':<8} {'Peso':<10} {'H2D':<6} {'X1C':<6} {'Notas':<20} {'Archivo':<40}",
                 "-"*120]
        for info, fn in zip(self.piece_infos, exp):
            notes = ""
            if info.merged: notes = "FUSIONADA "
            if info.unmerged_small: notes += "SIN-CONTACTO "
            if info.fits_h2d and not info.fits_x1c: notes += "→H2D"
            elif not info.fits_h2d: notes += "GRANDE"
            w = ("" if info.watertight else "~") + smart_weight_str(info.weight_g)
            lines.append(f"{info.index+1:<4} {info.width:<10.1f} {info.depth:<10.1f} {info.height:<10.1f} "
                         f"{info.min_dim:<8.1f} {w:<10} {'SI' if info.fits_h2d else 'NO':<6} {'SI' if info.fits_x1c else 'NO':<6} "
                         f"{notes:<20} {fn:<40}")
        total = sum(i.weight_g for i in self.piece_infos)
        lines += ["-"*120, f"TOTAL estimado: {smart_weight_str(total)} de {mat}"]

        # ── Espigas sueltas: STL único + instrucciones ──
        de = getattr(self, "_dowel_export", None)
        if de:
            pin_fn = f"{bn}_espiga.stl"
            pin = trimesh.creation.cylinder(radius=de["radius"], height=de["height"], sections=32)
            pin.export(os.path.join(od, pin_fn))
            lines += ["",
                      f"ESPIGAS SUELTAS: imprime {de['count']} copias de {pin_fn}",
                      f"  (cilindro de {de['radius']*2:.1f} mm de diámetro × {de['height']:.1f} mm de largo;",
                      f"   cada espiga entra hasta la mitad en el agujero de cada pieza)"]
        with open(os.path.join(od, f"{bn}_informe.txt"), "w", encoding="utf-8") as f: f.write("\n".join(lines))
        msg = f"{len(exp)} STLs + informe en:\n{od}"
        if de:
            msg += f"\n\nEspigas sueltas: imprime {de['count']} copias de {bn}_espiga.stl (ver informe)."
        QMessageBox.information(self, "OK", msg)

    def _refresh_cut_planes(self):
        """Pinta los planos de corte como superficies semitransparentes sobre el
        modelo sin cortar. Solo actores de plano: el modelo no se repinta."""
        for a in self.plane_actors:
            try: self.plotter.remove_actor(a)
            except Exception: pass
        self.plane_actors = []
        if (not self.chk_show_planes.isChecked() or self.scaled_mesh is None
                or self.pieces):
            self.plotter.render(); return
        b = self.scaled_mesh.bounds
        for cw in self.cut_widgets:
            cut = cw.cut_def
            uv = [i for i in range(3) if i != cut.axis]
            center = [(b[0][i] + b[1][i]) / 2 for i in range(3)]
            center[cut.axis] = cut.position
            direction = [0.0, 0.0, 0.0]; direction[cut.axis] = 1.0
            plane = pv.Plane(center=center, direction=direction,
                             i_size=(b[1][uv[0]] - b[0][uv[0]]) * 1.15,
                             j_size=(b[1][uv[1]] - b[0][uv[1]]) * 1.15)
            a = self.plotter.add_mesh(plane, color=AXIS_COLORS[AXIS_NAMES[cut.axis]],
                                      opacity=0.30)
            self.plane_actors.append(a)
        self.plotter.render()

    def _show_mesh(self, mesh):
        self.plotter.clear(); self.plane_actors = []
        self.plotter.add_mesh(pv.wrap(mesh), color="#AAAAAA", show_edges=False)
        self.plotter.reset_camera(); self.plotter.add_axes()

    def _show_pieces(self, pieces, ef=None):
        self.plotter.clear(); self.plane_actors = []
        if ef is None: ef = self.explode_slider.value() / 100.0
        if not pieces: return
        centers = [(p.bounds[0]+p.bounds[1])/2 for p in pieces]
        gc = np.mean(centers, axis=0)
        for i, p in enumerate(pieces):
            pm = pv.wrap(p)
            if ef > 0: pm = pm.translate((centers[i]-gc)*ef*1.2, inplace=False)
            self.plotter.add_mesh(pm, color=PIECE_COLORS[i%len(PIECE_COLORS)], show_edges=False, opacity=0.95)
        self.plotter.reset_camera(); self.plotter.add_axes()

    def _on_explode(self, v):
        self.explode_value.setText(f"{v}%")
        if self.pieces: self._show_pieces(self.pieces, v/100.0)

    def _update_table(self, infos):
        self.table.setSortingEnabled(False); self.table.setRowCount(len(infos))
        for row, info in enumerate(infos):
            notes = ""
            if info.merged: notes = "Fusionada"
            if info.unmerged_small: notes = (notes + " SIN CONTACTO").strip()
            if info.fits_h2d and not info.fits_x1c: notes += " → H2D"
            elif not info.fits_h2d: notes += " GRANDE"

            data = [
                (str(info.index+1), info.index+1), (f"{info.width:.1f}", info.width),
                (f"{info.depth:.1f}", info.depth), (f"{info.height:.1f}", info.height),
                (f"{info.min_dim:.1f}", info.min_dim),
                (f"{info.x_min:.0f}–{info.x_max:.0f}", info.x_min),
                (f"{info.y_min:.0f}–{info.y_max:.0f}", info.y_min),
                (f"{info.z_min:.0f}–{info.z_max:.0f}", info.z_min),
                (f"{info.volume_cm3:.1f}", info.volume_cm3),
                (("" if info.watertight else "~") + smart_weight_str(info.weight_g), info.weight_g),
                ("Sí" if info.fits_h2d else "No", 1 if info.fits_h2d else 0),
                ("Sí" if info.fits_x1c else "No", 1 if info.fits_x1c else 0),
                (notes, 0 if not notes else 1)]
            c = QColor(PIECE_COLORS[row%len(PIECE_COLORS)]); c.setAlpha(40)
            for col, (text, sv) in enumerate(data):
                it = NumericTableItem(text, sv); it.setTextAlignment(Qt.AlignCenter); it.setBackground(c)
                self.table.setItem(row, col, it)
        self.table.setSortingEnabled(True)
        if infos:
            total = sum(i.weight_g for i in infos)
            approx = "" if all(i.watertight for i in infos) else "~"
            mat = self.material_combo.currentText().split(" ")[0]
            self.lbl_weight_total.setText(
                f"Total: {approx}{smart_weight_str(total)} de {mat} "
                f"({self.infill_spin.value()} % relleno)")
        else:
            self.lbl_weight_total.setText("")

    def closeEvent(self, event): self.plotter.close(); super().closeEvent(event)


def main():
    app = QApplication(sys.argv); app.setStyle("Fusion")
    f = app.font(); f.setPointSize(13); app.setFont(f)
    w = MeshSplitterApp(); w.show(); sys.exit(app.exec())

if __name__ == "__main__": main()
