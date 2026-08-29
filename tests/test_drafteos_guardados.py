"""Un drafteo tirado ahora tiene dos finales: enseñarlo o quedárselo.

*«al elegir un rol, se generarían ataques como se hace ahora, pero que, en vez
de enseñarlo directamente, te dé la opción de enseñarlo al Pokémon directamente
o guardar. Al darle a Guardar, se añadiría a una lista a la cual se puede
acceder desde MTs.»*

Dos reglas quedan fijadas aquí, y ninguna es estética:

1. **Guardar cuesta un drafteo, igual que enseñarlo.** Repetir la tirada es
   gratis y siempre lo fue; lo que cuesta es quedarse con un resultado. Si
   guardar fuera gratis, la jugada obvia sería tirar, guardarse las cuatro
   opciones y volver a tirar: el contador dejaría de significar nada.
2. **Enseñarlo después no vuelve a cobrar.** Ya se pagó. Cobrarlo dos veces por
   el mismo movimiento sería un robo silencioso, del peor tipo: el usuario ve
   bajar el contador y no sabe por qué.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import drafteos_guardados as guardados  # noqa: E402
from app.models import PendingDraft  # noqa: E402
from app.run_service import RunProject  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402


def _drafteo(move_id: int = 53, move: str = "Lanzallamas", role: str = "Mago") -> dict:
    return guardados.nuevo_drafteo(
        move_id=move_id, move=move, role=role, pool_key=f"{role.lower()}-especial",
        categoria="OPCIÓN A", origen_identidad="abc", origen_nombre="Delphox",
        cuando="2026-08-29T01:00:00",
    )


# ------------------------------------------------------------------ las reglas

def test_un_drafteo_guardado_sabe_de_donde_salio() -> None:
    d = _drafteo()

    assert d["move_id"] == 53
    assert d["role"] == "Mago"
    assert d["origen_nombre"] == "Delphox"


def test_se_puede_enseñar_a_cualquiera_de_ese_rol() -> None:
    """Al rol, no a la especie: es la regla del formato."""
    d = _drafteo(role="Mago")

    assert guardados.puede_aprenderlo(d, "Mago") is True
    assert guardados.puede_aprenderlo(d, "mago") is True, "no distingue mayúsculas"
    assert guardados.puede_aprenderlo(d, "Tanque") is False


def test_un_guardado_antiguo_sin_rol_no_reclama_ninguno() -> None:
    """Antes que inventárselo, se ofrece a todos y decide quien enseña."""
    d = _drafteo(); d["role"] = ""

    assert guardados.puede_aprenderlo(d, "Tanque") is True


def test_dos_tiradas_iguales_son_dos_drafteos() -> None:
    """Cada una costó lo suyo: enseñar una no puede llevarse la otra."""
    d = _drafteo()
    lista = guardados.anadir(guardados.anadir([], d), d)

    assert guardados.cuantos(lista) == 2
    assert guardados.cuantos(guardados.quitar_uno(lista, d)) == 1


def test_quitar_uno_que_no_esta_no_borra_nada() -> None:
    lista = guardados.anadir([], _drafteo(move_id=53))

    assert guardados.cuantos(guardados.quitar_uno(lista, _drafteo(move_id=99))) == 1


def test_un_config_corrupto_no_impide_abrir_la_run() -> None:
    """`config.json` lo pudo escribir una versión anterior o una mano ajena."""
    crudos = [
        "no soy un dict",
        {"move_id": 0, "move": "Nada"},
        {"move_id": 53, "move": ""},
        {"move_id": "no es un numero", "move": "Rayo"},
        _drafteo(),
    ]

    assert guardados.cuantos(crudos) == 1


def test_se_ordenan_por_rol_y_por_nombre() -> None:
    lista = [
        _drafteo(move_id=1, move="Zumbido", role="Tanque"),
        _drafteo(move_id=2, move="Alud", role="Tanque"),
        _drafteo(move_id=3, move="Rayo", role="Mago"),
    ]
    orden = [(d["role"], d["move"]) for d in guardados.ordenados(lista)]

    assert orden == [("Mago", "Rayo"), ("Tanque", "Alud"), ("Tanque", "Zumbido")]


# ------------------------------------------------------------- la persistencia

def test_una_run_nace_sin_drafteos_guardados() -> None:
    project = RunProject(
        slug="x", name="X", game="bdsp", trainer="Diego", save_path="",
        created_at="", updated_at="",
    )

    assert project.saved_drafts == []


def test_una_run_antigua_se_abre_sin_ese_campo() -> None:
    """`RunProject(**raw)` lee `config.json` tal cual: sin defecto, reventaría."""
    crudo = {
        "slug": "x", "name": "X", "game": "bdsp", "trainer": "Diego",
        "save_path": "", "created_at": "", "updated_at": "",
    }

    assert RunProject(**crudo).saved_drafts == []


# ------------------------------------------------------------------ el cobro

def test_guardar_cobra_el_drafteo() -> None:
    fuente = inspect.getsource(RoleRunManager.guardar_drafteo)

    assert 'self.adjust_run_counter(\n            "drafteos", -1' in fuente
    assert "drafteos_guardados.anadir" in fuente


def test_se_escribe_el_proyecto_antes_de_tocar_el_contador() -> None:
    """`adjust_run_counter` relee el proyecto del disco.

    Lo que no esté escrito en ese momento se pierde ahí, sin avisar.
    """
    fuente = inspect.getsource(RoleRunManager.guardar_drafteo)

    assert fuente.index("self.project_service.save(self.project)") < fuente.index(
        "self.adjust_run_counter"
    )


def test_sin_drafteos_no_se_puede_guardar() -> None:
    fuente = inspect.getsource(RoleRunManager.guardar_drafteo)

    assert 'counters.get("drafteos", 0)' in fuente
    assert "SIN DRAFTEOS DISPONIBLES" in fuente


def test_un_drafteo_recuperado_viene_marcado_como_pagado() -> None:
    fuente = inspect.getsource(RoleRunManager.ensenar_drafteo_guardado)

    assert "ya_pagado=True" in fuente


def test_ensenar_uno_pagado_no_vuelve_a_cobrar_y_lo_saca_de_la_lista() -> None:
    fuente = inspect.getsource(RoleRunManager.queue_draft_change)
    rama = fuente[fuente.index("if ya_pagado:"):]

    assert "drafteos_guardados.quitar_uno" in rama
    assert rama.index("quitar_uno") < rama.index('self.adjust_run_counter("drafteos", -1')


def test_un_drafteo_pagado_no_tropieza_con_el_contador_a_cero() -> None:
    """Si no, un guardado quedaría inservible justo cuando más falta hace."""
    fuente = inspect.getsource(RoleRunManager.queue_draft_change)

    assert "if not ya_pagado and draft_count <= 0:" in fuente


def test_por_defecto_un_drafteo_nuevo_no_esta_pagado() -> None:
    d = PendingDraft(role="Mago", category="A", pool_key="k", move_id=53, move="Lanzallamas")

    assert d.ya_pagado is False
