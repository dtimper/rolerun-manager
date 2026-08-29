"""Tanque y Prisma admiten recuperación pasiva, pero no curación directa.

La regla de los dos roles defensivos no es «no puede curarse»: es que **no puede
recuperar PS con movimientos de daño ni con curación directa**. La recuperación
que llega sola, turno a turno, sí entra.

Hasta ahora ese hueco lo llenaban dos movimientos escritos a mano. El usuario
pidió revisar la familia entera, se listó contra el catálogo y decidió: entran
Acua Aro, Arraigo y **Drenadoras**, y no entran ni Deseo ni Campo de Hierba.

Estas pruebas fijan la decisión y, sobre todo, **la frontera**: lo que quedó
fuera no puede colarse por un cambio de pool sin que alguien se entere.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DATA_DIR  # noqa: E402
from app.role_content import ROLE_GUIDE  # noqa: E402
from app.role_rules import allowed_status_move_ids  # noqa: E402

ACUA_ARO, ARRAIGO, DRENADORAS = 392, 275, 73
DESEO, CAMPO_DE_HIERBA = 273, 580
TRAGAR, ABSORBEFUERZA = 256, 668
RECUPERACION, FOTOSINTESIS, RESPIRO = 105, 235, 355

ROLES_DEFENSIVOS = ("Tanque", "Prisma")


def pools() -> dict:
    return json.loads((Path(DATA_DIR) / "moves.json").read_text(encoding="utf-8"))


def clases() -> dict[int, str]:
    crudo = json.loads(
        (Path(DATA_DIR) / "move_rules_metadata.json").read_text(encoding="utf-8-sig")
    )
    return {int(k): v for k, v in crudo["damage_classes"].items()}


def permitidos(rol: str) -> set[int]:
    return allowed_status_move_ids(rol, pools(), clases(), set()) or set()


def test_el_pool_pasivo_es_exactamente_el_decidido() -> None:
    assert sorted(pools()["defensa_recuperacion_pasiva"]) == sorted(
        [ACUA_ARO, ARRAIGO, DRENADORAS]
    )


def test_los_tres_son_legales_para_tanque_y_prisma() -> None:
    for rol in ROLES_DEFENSIVOS:
        legales = permitidos(rol)
        for move_id in (ACUA_ARO, ARRAIGO, DRENADORAS):
            assert move_id in legales, f"{rol} rechaza {move_id}"


def test_la_curacion_directa_sigue_prohibida() -> None:
    """Es la mitad de la regla, y la que distingue a estos dos roles."""
    for rol in ROLES_DEFENSIVOS:
        legales = permitidos(rol)
        for move_id in (RECUPERACION, FOTOSINTESIS, RESPIRO, TRAGAR, ABSORBEFUERZA):
            assert move_id not in legales, f"{rol} acepta curación directa: {move_id}"


def test_lo_que_se_dejo_fuera_sigue_fuera() -> None:
    """Deseo cura diferido y Campo de Hierba cura a todo el campo.

    Se listaron como candidatos y se descartaron a propósito. Sin esta prueba,
    entrarían el día que alguien amplíe el pool sin releer la decisión.
    """
    for rol in ROLES_DEFENSIVOS:
        legales = permitidos(rol)
        assert DESEO not in legales
        assert CAMPO_DE_HIERBA not in legales


def test_ningun_otro_rol_hereda_la_recuperacion_pasiva() -> None:
    """El pool cuelga solo de Tanque y Prisma."""
    for rol in ("Asesino", "Mago"):
        legales = permitidos(rol)
        for move_id in (ACUA_ARO, ARRAIGO, DRENADORAS):
            assert move_id not in legales, f"{rol} no debería tener {move_id}"


def test_el_libero_no_tiene_restricciones() -> None:
    assert allowed_status_move_ids("Líbero", pools(), clases(), set()) is None


def test_la_ficha_de_rol_nombra_los_tres() -> None:
    """La ficha y el pool no pueden decir cosas distintas."""
    for rol in ROLES_DEFENSIVOS:
        texto = ROLE_GUIDE[rol]["allowed"]
        assert "Acua Aro, Arraigo y Drenadoras" in texto, rol


def test_drenadoras_es_un_movimiento_de_estado() -> None:
    """Si fuera de daño, entraría por otra puerta y con otra regla."""
    assert clases()[DRENADORAS] == "status"


# ------------------------------------------- los boosts que faltaban en los datos

TAMBOR, LUMINICOLA, ACUPRESION = 187, 294, 367
DESLOME = 868


def test_tambor_es_legal_para_asesino_y_luminicola_para_mago() -> None:
    """No estaban en ningún pool, así que RoleRun proponía borrarlos.

    Tambor sube solo el Ataque y Luminicola solo el Ataque Especial: es
    literalmente lo que la ficha de cada rol permite («boosts que aumenten al
    menos el Ataque»). Un Snorlax con Tambor al que se asignaba Asesino veía el
    movimiento en rojo, se quedaba en preparación, y el diálogo ofrecía
    eliminarlo — con el juego conectado, eso puede acabar en una escritura real
    que borra un movimiento legal.
    """
    assert TAMBOR in permitidos("Asesino")
    assert LUMINICOLA in permitidos("Mago")


def test_no_se_cruzan_de_rol() -> None:
    assert TAMBOR not in permitidos("Mago")
    assert LUMINICOLA not in permitidos("Asesino")


def test_que_era_un_olvido_lo_demuestra_deslome() -> None:
    """Deslome hace lo mismo que Tambor pagando PS, y sí estaba en los pools."""
    assert DESLOME in pools()["asesino_subir_ataque"]
    assert DESLOME in pools()["global_self_boosts"]
    assert TAMBOR in pools()["global_self_boosts"]


def test_un_support_no_puede_subirse_las_estadisticas() -> None:
    """El Support se valida por RESTA sobre `global_self_boosts`.

    Lo que no esté en esa lista pasa en verde. Sin estos tres, un Support podía
    llevar Tambor, Luminicola o Acupresión pese a que su ficha lo prohíbe, y
    RoleRun podía además OFRECÉRSELOS como MT compatible.
    """
    legales = permitidos("Support")
    for move_id in (TAMBOR, LUMINICOLA, ACUPRESION):
        assert move_id not in legales, move_id


def test_acupresion_no_entra_en_asesino_ni_mago() -> None:
    """Sube una estadística al azar: no garantiza Ataque ni Ataque Especial."""
    assert ACUPRESION not in permitidos("Asesino")
    assert ACUPRESION not in permitidos("Mago")
    assert ACUPRESION in pools()["global_self_boosts"]


def test_los_roles_defensivos_siguen_sin_boosts_ofensivos() -> None:
    for rol in ROLES_DEFENSIVOS:
        legales = permitidos(rol)
        assert TAMBOR not in legales
        assert LUMINICOLA not in legales
