"""La ficha no puede quedarse en «—» porque nada haya cambiado de sitio.

Fallo reportado el 27-08-2026 con captura: los seis miembros aparecían sin
estadísticas, sin IV, sin EV y sin naturaleza, y solo aparecían al asignarle un
rol a uno de ellos.

``diff_live_party`` compara composición, orden, roles, movimientos y nivel, e
**ignora a propósito** estadísticas, IV, EV y PS. La rama B2/W2 del monitor solo
publicaba la captura viva cuando ese diff detectaba algo, así que en cuanto algo
reponía ``current_game`` desde el guardado —recargar tras guardar dentro del
juego, o simplemente abrir la Run— esos datos se perdían para siempre. Asignar un
rol cambiaba el rol, el diff se activaba, y por eso «al elegir el rol ya aparecen
los stats».

El segundo fallo del mismo reporte: los EV no cambiaban nunca. El cálculo del
reparto de EV de un rol estaba condicionado a una lista de juegos escrita como
literal en siete sitios distintos, y B2/W2 no estaba en ninguno.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.save_engine_client import SaveGameData, SavePokemon  # noqa: E402
from app.ui import ROLE_EV_WRITER_GAME_KEYS, RoleRunManager  # noqa: E402


def _mon(**campos) -> SavePokemon:
    base = dict(
        slot=0, species_id=504, species="Patrat", nickname="Patrat", level=3,
        held_item="Ninguno", ability="Vista Lince", moves=["Placaje"],
        move_ids=[33], is_egg=False, markings=[False] * 6, role="SIN ROL",
        role_symbol="", pid=4242, tid=1, sid=2, current_hp=12, max_hp=16,
    )
    base.update(campos)
    return SavePokemon(**base)


def _game(*pokemon) -> SaveGameData:
    return SaveGameData("B2W2", "SAV5B2W2", 5, "Diego", list(pokemon), {})


_RICO = dict(
    stats={"hp": 16, "attack": 10, "defense": 9, "sp_attack": 8, "sp_defense": 8, "speed": 11},
    ivs={"hp": 31, "attack": 30, "defense": 29, "sp_attack": 28, "sp_defense": 27, "speed": 26},
    evs={"hp": 4, "attack": 8, "defense": 12, "sp_attack": 20, "sp_defense": 16, "speed": 24},
    base_stats={"hp": 45, "attack": 55, "defense": 39, "sp_attack": 35, "sp_defense": 39, "speed": 42},
    nature="Firme",
)


# --------------------------------------------------------------------------
# El predicado
# --------------------------------------------------------------------------

@pytest.mark.parametrize("campo", ["stats", "ivs", "evs", "base_stats"])
def test_falta_cualquier_bloque_de_datos_y_hay_que_publicar(campo: str) -> None:
    vivo = _game(_mon(**_RICO))
    actual = _game(_mon(**{**_RICO, campo: {}}))

    assert RoleRunManager._live_metadata_is_missing(actual, vivo) is True


def test_falta_la_naturaleza_y_hay_que_publicar() -> None:
    vivo = _game(_mon(**_RICO))
    actual = _game(_mon(**{**_RICO, "nature": ""}))

    assert RoleRunManager._live_metadata_is_missing(actual, vivo) is True


def test_con_todo_presente_no_se_republica() -> None:
    """Una vez publicado, deja de hacer falta: no puede repetirse cada ciclo."""
    vivo = _game(_mon(**_RICO))
    actual = _game(_mon(**_RICO))

    assert RoleRunManager._live_metadata_is_missing(actual, vivo) is False


def test_es_una_comprobacion_en_un_solo_sentido() -> None:
    """Que la vista tenga algo que la captura no trae no obliga a publicar."""
    vivo = _game(_mon(**{**_RICO, "evs": {}}))
    actual = _game(_mon(**_RICO))

    assert RoleRunManager._live_metadata_is_missing(actual, vivo) is False


def test_un_pokemon_que_no_esta_en_la_vista_no_cuenta() -> None:
    """Eso es un cambio de composición y ya lo detecta ``diff_live_party``."""
    vivo = _game(_mon(pid=99, **_RICO))
    actual = _game(_mon(pid=4242, **_RICO))

    assert RoleRunManager._live_metadata_is_missing(actual, vivo) is False


def test_sin_capturas_no_se_afirma_nada() -> None:
    assert RoleRunManager._live_metadata_is_missing(None, _game(_mon(**_RICO))) is False
    assert RoleRunManager._live_metadata_is_missing(_game(_mon(**_RICO)), None) is False


def test_se_compara_por_identidad_fuerte_no_por_posicion() -> None:
    vivo = _game(_mon(slot=0, pid=1, **_RICO), _mon(slot=1, pid=2, **_RICO))
    actual = _game(
        _mon(slot=0, pid=2, **_RICO),
        _mon(slot=1, pid=1, **{**_RICO, "evs": {}}),
    )

    assert RoleRunManager._live_metadata_is_missing(actual, vivo) is True


# --------------------------------------------------------------------------
# Los EV del rol
# --------------------------------------------------------------------------

def test_b2w2_ya_reparte_los_ev_de_su_rol() -> None:
    assert "b2w2" in ROLE_EV_WRITER_GAME_KEYS


def test_ningun_backend_pierde_su_reparto_de_ev() -> None:
    assert {"bdsp", "oras", "xy", "sm", "usum"} <= ROLE_EV_WRITER_GAME_KEYS


def test_la_lista_de_ev_ya_no_esta_repetida_como_literal() -> None:
    """Siete copias del mismo literal fueron la causa de que B2/W2 se quedara
    fuera sin que nadie lo notara. La constante evita repetir el olvido."""
    import inspect

    import app.ui as ui

    fuente = inspect.getsource(ui)
    literal = '{"bdsp", "oras", "xy", "sm", "usum"}'
    # Quedan solo los usos de MT/ROM, que son otra capacidad distinta.
    assert fuente.count(literal) <= 3
