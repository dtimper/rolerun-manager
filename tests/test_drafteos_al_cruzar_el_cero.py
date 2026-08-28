"""Sumar el primer drafteo con la pestaña abierta tiene que encender los botones.

Cada tarjeta de Drafteos decide **al construirse** si su botón está encendido:

    eligible = role != "SIN ROL" and self.draft_count > 0

Así que cruzar el cero obliga a rehacer la página. Refrescar solo los botones
dejaba seis tarjetas diciendo «EN PREPARACIÓN» con drafteos ya disponibles.

Lo que había antes era peor que eso: dibujaba el paso de rol del **diseño
antiguo** dentro del body actual, encima del flujo visual. Salía un panel «Elige
el rol del drafteo» flotando sobre unas tarjetas que seguían apagadas.

Y vale en las dos direcciones: gastar el último drafteo tiene que volver a
apagarlas.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402
from app.ui_views.draft_flow import IntegratedDraftFlow  # noqa: E402


def _rama_de_drafteos() -> str:
    fuente = inspect.getsource(RoleRunManager.adjust_run_counter)
    inicio = fuente.index('elif self.active_page == "drafts"')
    return fuente[inicio:inicio + 1400]


def test_el_boton_se_decide_al_construir_la_tarjeta() -> None:
    """Es la razon por la que hace falta repintar, y no solo refrescar."""
    fuente = inspect.getsource(IntegratedDraftFlow)

    assert 'eligible = role != "SIN ROL" and self.draft_count > 0' in fuente
    assert 'text="ELEGIR" if eligible else "EN PREPARACIÓN"' in fuente


def test_cruzar_el_cero_repinta_la_pagina() -> None:
    rama = _rama_de_drafteos()

    assert "(previous_value <= 0) != (current_value <= 0)" in rama, (
        "tiene que valer en las dos direcciones, no solo al llegar el primero"
    )
    assert "_smooth_render_page" in rama


def test_ya_no_se_dibuja_el_paso_del_diseno_antiguo() -> None:
    """Salia flotando sobre las tarjetas, que seguian apagadas."""
    rama = _rama_de_drafteos()

    assert "_render_role_step" not in rama
    assert "self.step_widgets.pop(1" not in rama


def test_sin_cruzar_el_cero_no_se_repinta_la_pagina() -> None:
    """De 3 a 4 drafteos no cambia nada de la forma: repintar sobraria."""
    rama = _rama_de_drafteos()
    despues = rama[rama.index("else:"):]

    assert "_refresh_draft_role_buttons" in despues
    assert "_smooth_render_page" not in despues


def test_el_paso_de_rol_antiguo_ya_no_lo_llama_nadie() -> None:
    """Queda como codigo muerto: cualquier llamada nueva reviviria el fallo."""
    raiz = Path(__file__).resolve().parent.parent
    llamadas = []
    for ruta in sorted((raiz / "app").rglob("*.py")):
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            if "_render_role_step(" in linea and "def _render_role_step" not in linea:
                llamadas.append(f"{ruta.relative_to(raiz)}:{numero}")

    assert not llamadas, (
        "dibuja el diseno antiguo dentro del body actual:\n  " + "\n  ".join(llamadas)
    )
