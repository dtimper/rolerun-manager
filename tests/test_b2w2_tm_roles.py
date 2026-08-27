"""La pantalla de MT de B2/W2: qué se ofrece, según el rol y según la partida.

Dos cosas distintas, que estas pruebas separan a propósito:

1. **Qué MT tienes** sale de la mochila viva, y **qué enseña cada una** de la
   tabla que el juego tiene cargada. En una partida randomizada la MT26 puede
   enseñar cualquier cosa, y lo que se ofrece —y lo que se acaba escribiendo—
   tiene que ser ese movimiento, no el de la quinta generación original.

2. **Quién puede aprenderla** lo decide el **rol**, no la compatibilidad de
   especie del juego. Es una decisión deliberada de RoleRun, la misma que ya
   aplican Perla Reluciente, X/Y, ORAS y Gen 7, y aquí se comprueba con el
   motor de reglas real, no con un doble.

Se usa `DraftEngine` de verdad y el perfil de MT real: si las reglas cambiaran,
estas pruebas tienen que enterarse.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:                                  # pragma: no cover
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.b2w2_tm_service import (  # noqa: E402
    TM_TABLE_ITEM_IDS,
    build_tm_profile,
    reference_move_ids,
)
from app.draft_engine import DraftEngine  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "data"

TERREMOTO = 89          # físico
LANZALLAMAS = 53        # especial
DANZA_ESPADA = 14       # estado, sube Ataque


class _Pantalla:
    """La parte de la interfaz que decide qué MT se ofrecen, sin Tk."""

    _build_tm_candidates = RoleRunManager._build_tm_candidates
    _tm_flow_candidates = RoleRunManager._tm_flow_candidates
    _tm_move_compatible_with_role = RoleRunManager._tm_move_compatible_with_role
    _damage_class_for_move = RoleRunManager._damage_class_for_move
    _allowed_move_ids_for_role = RoleRunManager._allowed_move_ids_for_role
    _tm_pp_for_profile = RoleRunManager._tm_pp_for_profile

    def __init__(self, rol: str, movimientos=(0, 0, 0, 0)) -> None:
        self.engine = DraftEngine(
            DATOS / "moves.json", DATOS / "roles.json", DATOS / "move_catalog.json",
        )
        self.save_engine = SimpleNamespace(key="b2w2")
        self.rol = rol
        self.movimientos = [int(valor) for valor in movimientos]
        # Quinta generación llega hasta el movimiento 559, que es justo lo que
        # `save_engine.valid_moves` devolvería para esta partida.
        self.engine.set_allowed_moves(set(range(1, 560)))

    # --- lo que la pantalla real le pregunta a la Run ---------------------
    def _effective_moves_for_review(self, pokemon):
        return (["—"] * 4, list(self.movimientos))

    def _effective_role(self, pokemon):
        return self.rol, ""

    def _get_bdsp_tm_profile(self, prompt: bool = False):
        return None                      # no es Perla Reluciente

    def _draft_move_metadata(self, move_id: int):
        return {}

    def _pokemon_identity(self, pokemon):
        return "pk-b2w2"

    def _support_damage_excess(self, pokemon, role):
        return False, ()


def _perfil(randomizado: dict[int, int] | None = None):
    """Perfil de MT. ``randomizado`` fija qué enseña cada MT indicada.

    Un randomizer **permuta** la lista: no duplica movimientos ni pierde
    ninguno. Por eso aquí se intercambia con la MT que tuviera ese movimiento
    en vez de escribir encima, que dejaría un repetido y el perfil lo
    rechazaría —con razón— como lectura desalineada.
    """
    movimientos = list(reference_move_ids())
    for numero, move_id in (randomizado or {}).items():
        destino = TM_TABLE_ITEM_IDS.index(327 + numero)
        origen = movimientos.index(int(move_id))
        movimientos[destino], movimientos[origen] = (
            movimientos[origen], movimientos[destino],
        )
    return build_tm_profile(movimientos, source="prueba")


def _mochila(*numeros_mt: int) -> dict[int, int]:
    perfil = _perfil()
    return {perfil.tm(numero).item_id: 1 for numero in numeros_mt}


def _ofrecidas(pantalla: _Pantalla, perfil, mochila, hueco: int = 4) -> set[int]:
    candidatas = pantalla._build_tm_candidates(object(), hueco, perfil, mochila)
    return {int(c["move_id"]) for c in candidatas}


# --------------------------------------------------------------------------
# Solo se ofrece lo que hay en la mochila
# --------------------------------------------------------------------------

def test_una_mt_que_no_tienes_no_se_ofrece() -> None:
    perfil = _perfil()
    pantalla = _Pantalla("SIN ROL")

    ofrecidas = _ofrecidas(pantalla, perfil, _mochila(26))

    assert ofrecidas == {perfil.tm(26).move_id}


def test_sin_mochila_no_se_ofrece_nada() -> None:
    assert _ofrecidas(_Pantalla("SIN ROL"), _perfil(), {}) == set()


def test_un_movimiento_que_ya_conoce_no_se_ofrece() -> None:
    perfil = _perfil()
    pantalla = _Pantalla("SIN ROL", movimientos=(perfil.tm(26).move_id, 0, 0, 0))

    assert _ofrecidas(pantalla, perfil, _mochila(26)) == set()


# --------------------------------------------------------------------------
# El rol filtra: mismas reglas que en los demás juegos
# --------------------------------------------------------------------------

def test_sin_rol_no_se_filtra_nada() -> None:
    """SIN ROL y Líbero no imponen restricciones de movimiento."""
    perfil = _perfil(randomizado={26: TERREMOTO, 35: LANZALLAMAS})
    pantalla = _Pantalla("SIN ROL")

    assert _ofrecidas(pantalla, perfil, _mochila(26, 35)) == {TERREMOTO, LANZALLAMAS}


def test_un_mago_no_recibe_ataques_fisicos() -> None:
    """El Mago es el rol especial: un ataque físico no le sirve."""
    perfil = _perfil(randomizado={26: TERREMOTO, 35: LANZALLAMAS})
    pantalla = _Pantalla("Mago")

    ofrecidas = _ofrecidas(pantalla, perfil, _mochila(26, 35))

    assert LANZALLAMAS in ofrecidas
    assert TERREMOTO not in ofrecidas


def test_un_asesino_no_recibe_ataques_especiales() -> None:
    perfil = _perfil(randomizado={26: TERREMOTO, 35: LANZALLAMAS})
    pantalla = _Pantalla("Asesino")

    ofrecidas = _ofrecidas(pantalla, perfil, _mochila(26, 35))

    assert TERREMOTO in ofrecidas
    assert LANZALLAMAS not in ofrecidas


def test_a_un_support_con_dos_ataques_solo_se_le_ofrecen_estados() -> None:
    """El límite de Support es de conjunto, no de movimiento suelto."""
    perfil = _perfil(randomizado={26: TERREMOTO, 35: LANZALLAMAS, 75: DANZA_ESPADA})
    lleno = _Pantalla("Support", movimientos=(TERREMOTO, LANZALLAMAS, 0, 0))

    ofrecidas = _ofrecidas(lleno, perfil, _mochila(26, 35, 75))

    assert TERREMOTO not in ofrecidas and LANZALLAMAS not in ofrecidas


def test_el_mismo_support_con_un_solo_ataque_si_admite_otro() -> None:
    perfil = _perfil(randomizado={26: TERREMOTO})
    holgado = _Pantalla("Support", movimientos=(LANZALLAMAS, 0, 0, 0))

    assert TERREMOTO in _ofrecidas(holgado, perfil, _mochila(26))


def test_el_filtro_por_rol_es_el_mismo_de_los_demas_juegos() -> None:
    """No hay una regla propia de B2/W2: es `_tm_move_compatible_with_role`.

    Si algún día se bifurcara por juego, esta prueba dejaría de tener sentido y
    habría que replantear la decisión, no parchear el test.
    """
    pantalla = _Pantalla("Mago")

    assert pantalla._tm_move_compatible_with_role(object(), "Mago", LANZALLAMAS, 4)
    assert not pantalla._tm_move_compatible_with_role(object(), "Mago", TERREMOTO, 4)


def test_la_compatibilidad_de_especie_se_sigue_ignorando() -> None:
    """Decisión deliberada de RoleRun: manda el rol, no la tabla del juego.

    Magikarp no aprende ninguna MT en quinta generación. RoleRun se la ofrece
    igual, porque quien decide es el rol.
    """
    perfil = _perfil(randomizado={26: TERREMOTO})
    pantalla = _Pantalla("Asesino")

    assert TERREMOTO in _ofrecidas(pantalla, perfil, _mochila(26))
    assert not hasattr(perfil, "can_learn"), "el perfil B2/W2 no expone compatibilidad"


# --------------------------------------------------------------------------
# Randomizada: se ofrece y se enseña el movimiento de ESTA partida
# --------------------------------------------------------------------------

def test_una_mt_randomizada_ofrece_su_movimiento_real() -> None:
    vanilla = _perfil()
    perfil = _perfil(randomizado={26: LANZALLAMAS})
    pantalla = _Pantalla("SIN ROL")

    ofrecidas = _ofrecidas(pantalla, perfil, _mochila(26))

    assert ofrecidas == {LANZALLAMAS}
    assert vanilla.tm(26).move_id != LANZALLAMAS, "en vanilla la MT26 es Terremoto"


def test_el_rol_filtra_por_el_movimiento_randomizado_no_por_el_original() -> None:
    """Es el caso que más fácil se rompería: MT26 es Terremoto en vanilla.

    A un Mago la MT26 vanilla no se le ofrece, por física. Si la partida la
    randomiza a un ataque especial, sí; y al revés con una MT vanilla especial
    randomizada a física.
    """
    mago = _Pantalla("Mago")

    fisica_a_especial = _perfil(randomizado={26: LANZALLAMAS})
    assert _ofrecidas(mago, fisica_a_especial, _mochila(26)) == {LANZALLAMAS}

    especial_a_fisica = _perfil(randomizado={35: TERREMOTO})
    assert _ofrecidas(mago, especial_a_fisica, _mochila(35)) == set()


def test_el_numero_de_mt_no_cambia_aunque_cambie_lo_que_ensena() -> None:
    """En la mochila sigue siendo el mismo objeto: MT26 = objeto 353."""
    perfil = _perfil(randomizado={26: LANZALLAMAS})
    pantalla = _Pantalla("SIN ROL")

    candidatas = pantalla._build_tm_candidates(object(), 4, perfil, _mochila(26))

    assert len(candidatas) == 1
    assert int(candidatas[0]["number"]) == 26
    assert int(candidatas[0]["item_id"]) == 353
    assert int(candidatas[0]["move_id"]) == LANZALLAMAS


def test_lo_que_se_encola_es_el_movimiento_de_la_partida_viva() -> None:
    """El writer recibe el movimiento randomizado, no el de la tabla vanilla."""
    perfil = _perfil(randomizado={26: LANZALLAMAS})
    pantalla = _Pantalla("SIN ROL")

    candidata = pantalla._build_tm_candidates(object(), 4, perfil, _mochila(26))[0]

    # `_queue_tm_teach` construye el PendingTMTeach con estos dos campos, y el
    # adaptador escribe `new_move_id` tal cual.
    assert int(candidata["move_id"]) == LANZALLAMAS
    assert int(candidata["item_id"]) == perfil.tm(26).item_id


def test_los_pp_ofrecidos_son_los_del_movimiento_randomizado() -> None:
    perfil = _perfil(randomizado={26: LANZALLAMAS})
    pantalla = _Pantalla("SIN ROL")

    assert pantalla._tm_pp_for_profile(perfil, LANZALLAMAS) == perfil.base_pp(LANZALLAMAS)
    assert perfil.base_pp(LANZALLAMAS) == 15


# --------------------------------------------------------------------------
# La vista agregada de la pantalla MT
# --------------------------------------------------------------------------

def test_la_pantalla_agrupa_los_huecos_validos_de_cada_mt() -> None:
    """La pantalla deja elegir la MT antes que el movimiento a olvidar."""
    perfil = _perfil(randomizado={26: TERREMOTO})
    pantalla = _Pantalla("Asesino", movimientos=(33, 0, 0, 0))

    candidatas = pantalla._tm_flow_candidates(
        object(), perfil, _mochila(26), [33, 0, 0, 0],
    )

    assert len(candidatas) == 1
    assert int(candidatas[0]["move_id"]) == TERREMOTO
    assert candidatas[0]["valid_slots"] == (1, 2, 3, 4)


def test_una_mt_incompatible_no_aparece_en_ningun_hueco() -> None:
    perfil = _perfil(randomizado={26: TERREMOTO})
    pantalla = _Pantalla("Mago")

    candidatas = pantalla._tm_flow_candidates(
        object(), perfil, _mochila(26), [0, 0, 0, 0],
    )

    assert candidatas == ()


def test_en_b2w2_la_mt_nunca_se_marca_como_consumible() -> None:
    """En quinta son reutilizables: solo Perla Reluciente gasta la máquina."""
    perfil = _perfil(randomizado={26: TERREMOTO})
    pantalla = _Pantalla("Asesino")

    candidatas = pantalla._tm_flow_candidates(
        object(), perfil, _mochila(26), [0, 0, 0, 0],
    )

    assert candidatas[0]["consumes_item"] is False


# --------------------------------------------------------------------------
# De la pantalla al juego, sin que el movimiento cambie por el camino
# --------------------------------------------------------------------------

class _Cola:
    """La parte que convierte una MT elegida en un cambio pendiente."""

    _queue_tm_teach = RoleRunManager._queue_tm_teach

    def __init__(self) -> None:
        self.run = SimpleNamespace(pending_changes=[])
        self.save_engine = SimpleNamespace(key="b2w2")
        self._oras_live_active = True

    def _effective_moves_for_review(self, pokemon):
        return (["Placaje", "—", "—", "—"], [33, 0, 0, 0])

    def _effective_role(self, pokemon):
        return "SIN ROL", ""

    def _pokemon_identity(self, pokemon):
        return "504:111:1:2"

    def _capture_body_scroll_px(self):
        return 0

    def _capture_body_scroll_fraction(self):
        return 0.0

    def _update_top_status(self):
        pass

    def _smooth_render_page(self, preserve_scroll=False):
        pass

    def after(self, _delay, callback):
        callback()

    def _show_change_toast(self):
        pass

    def _request_oras_live_auto_apply_since(self, _antes):
        pass


def test_la_mt_randomizada_llega_al_writer_con_su_movimiento() -> None:
    """El recorrido entero: mochila → tabla viva → rol → cola → writer.

    La MT26 en quinta original enseña Terremoto. En esta partida enseña
    Lanzallamas, y eso es lo que tiene que acabar escribiéndose en el PK5.
    """
    perfil = _perfil(randomizado={26: LANZALLAMAS})
    pantalla = _Pantalla("SIN ROL", movimientos=(33, 0, 0, 0))
    candidata = pantalla._build_tm_candidates(object(), 4, perfil, _mochila(26))[0]

    cola = _Cola()
    cola._queue_tm_teach(
        SimpleNamespace(slot=0, nickname="Tepig", species="Tepig"), 4, candidata,
    )

    pendiente = cola.run.pending_changes[0]
    assert pendiente.new_move_id == LANZALLAMAS
    assert pendiente.tm_number == 26
    assert pendiente.item_name == "MT26"
    assert pendiente.consumes_item is False, "en quinta la MT no se gasta"

    # Y el adaptador escribe exactamente ese movimiento, sin volver a mirar
    # ninguna tabla.
    from test_b2w2_tm_teach import _clave, _identidad, _lector
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    lector = _lector()
    adaptador = B2W2RealTimeAdapter(reader=lector)
    primero = lector.read_party().pokemon[0]
    pendiente.pokemon_identity = _clave(primero)

    objetivo = adaptador._teach_target_for(lector.read_party(), pendiente)

    assert objetivo == (0, _identidad(primero), 4, LANZALLAMAS)


def test_la_procedencia_del_perfil_se_puede_mostrar() -> None:
    """La pantalla muestra `profile.source.name`, como en los demás juegos."""
    perfil = _perfil()

    assert perfil.source.name == "prueba"
    assert str(perfil.source) == "prueba"
