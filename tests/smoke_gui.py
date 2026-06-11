#!/usr/bin/env python3
"""Smoke test de la GUI con Qt REAL (offscreen). Corre en CI antes de empaquetar.
Stub solo de pyvista/pyvistaqt (no necesita VTK ni GPU): valida la construcción
completa de la ventana, señales, enums de PySide6 y poblado de la tabla."""
import os, sys, types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PySide6
from PySide6.QtWidgets import QApplication, QWidget

# ── stubs de pyvista / pyvistaqt ANTES de importar la app ──
pv_stub = types.ModuleType("pyvista")
pv_stub.wrap = lambda m: m
pv_stub.Plane = lambda **k: object()
sys.modules["pyvista"] = pv_stub

pvqt_stub = types.ModuleType("pyvistaqt")
class QtInteractor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.interactor = self
    def clear(self): pass
    def add_mesh(self, *a, **k): return object()
    def remove_actor(self, *a, **k): pass
    def reset_camera(self): pass
    def add_axes(self): pass
    def render(self): pass
pvqt_stub.QtInteractor = QtInteractor
sys.modules["pyvistaqt"] = pvqt_stub

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mesh_splitter as ms

app = QApplication.instance() or QApplication([])
w = ms.MeshSplitterApp()
w.show()

# Cortes: añadir, editar, quitar, limpiar (señales conectadas de verdad)
w._on_add_cut(2); w._on_add_cut(0)
assert len(w.cut_widgets) == 2
w.cut_widgets[0].pos_spin.setValue(33.0)
w.cut_widgets[1].axis_combo.setCurrentIndex(1)
w._on_remove_cut(w.cut_widgets[0])
assert len(w.cut_widgets) == 1
w._on_clear_cuts()
assert len(w.cut_widgets) == 0

# Tabla con PieceInfo sintético (todos los campos actuales)
info = ms.PieceInfo(index=0, width=100, depth=100, height=100, min_dim=100,
                    x_min=0, x_max=100, y_min=0, y_max=100, z_min=0, z_max=100,
                    triangles=12, volume_cm3=1000.0, weight_g=287.2,
                    watertight=True, fits_h2d=True, fits_x1c=True,
                    merged=True, unmerged_small=False)
w._update_table([info])
assert w.table.rowCount() == 1
assert "287" in w.table.item(0, 9).text()
assert "Fusionada" in w.table.item(0, 12).text()
assert "Total:" in w.lbl_weight_total.text()

# Parámetros de peso reaccionan
assert w._weight_params()[0] == ms.MATERIAL_DENSITY["PLA"]
w.material_combo.setCurrentIndex(1)
assert w._weight_params()[0] == ms.MATERIAL_DENSITY["PETG"]

w.close()
print(f"SMOKE GUI OK — PySide6 {PySide6.__version__} en {sys.platform}")
