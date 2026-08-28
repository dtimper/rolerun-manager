"""Una tarjeta del equipo se actualiza sin dejar nada viejo en pantalla.

Medido con customtkinter en el equipo del usuario:

    construir una tarjeta ......... 34,71 ms   (las seis: 208 ms)
    destruirla .................... 16,11 ms   (las seis:  97 ms)
    reconfigurarla entera .........  4,69 ms   (las seis:  28 ms)

La ganancia no es lo delicado. Lo delicado es que quede un dato del Pokémon
anterior, que es peor que ir lento, y hay dos formas de que pase:

  - un ``configure`` olvidado: aquí se actualiza con otro Pokémon distinto en
    todo y se exige que TODOS los textos registrados cambien;
  - una referencia vieja invisible: el clic, el arrastre y el destino de soltar
    llevaban el Pokémon metido en el cierre, así que soltar sobre una tarjeta
    actualizada habría movido al de antes.
"""

from __future__ import annotations

import inspect
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pokemon_stats import STAT_KEYS  # noqa: E402
from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402


class _Etiqueta:
    """Lo mínimo que `update_team_card` le pide a un CTkLabel o CTkFrame."""

    def __init__(self, **opciones) -> None:
        self.opciones = dict(opciones)
        self.veces = 0

    def configure(self, **kwargs) -> None:
        self.opciones.update(kwargs)
        self.veces += 1

    def cget(self, clave):
        return self.opciones[clave]

    def winfo_exists(self) -> bool:
        return True


class _Mono:
    def __init__(self, **campos) -> None:
        self.__dict__.update(campos)


ANTES = _Mono(
    nickname="WOOPER", species="Wooper", level=17,
    current_hp=40, max_hp=52,
    stats={"hp": 52, "attack": 24, "defense": 26,
           "sp_attack": 18, "sp_defense": 20, "speed": 12},
    nature_increased="attack", nature_decreased="sp_attack",
    ability="Absorbe Agua", held_item="Ninguno",
    moves=["Placaje", "Bofetón Lodo", "Amnesia", "Danza Lluvia"],
    slot=1,
)
DESPUES = _Mono(
    nickname="QUAGSIRE", species="Quagsire", level=28,
    current_hp=71, max_hp=90,
    stats={"hp": 90, "attack": 55, "defense": 50,
           "sp_attack": 37, "sp_defense": 41, "speed": 29},
    nature_increased="speed", nature_decreased="defense",
    ability="Humedad", held_item="Mineral Suave",
    moves=["Terremoto", "Cascada", "Bostezo", "Recuperación"],
    slot=1,
)


def _registro() -> dict:
    return {
        "sprite": _Etiqueta(image=None),
        "imagen": None,
        "titulo": _Etiqueta(text=""),
        "stats_nombre": [_Etiqueta(text="", text_color="") for _ in STAT_KEYS],
        "stats_valor": [_Etiqueta(text="") for _ in STAT_KEYS],
        "meta": [_Etiqueta(text=""), _Etiqueta(text="")],
        "celdas_mov": [_Etiqueta() for _ in range(4)],
        "textos_mov": [_Etiqueta(text="", text_color="") for _ in range(4)],
    }


def _vista():
    destino = {"slot_role": "TANQUE", "pokemon": ANTES}
    yo = types.SimpleNamespace(
        _team_card_widgets={"id-1": _registro()},
        _team_card_pokemon={"id-1": ANTES},
        _team_card_targets={"id-1": destino},
        move_issues_for=None,
        support_damage_for=None,
        sprite_for=lambda pokemon, size: f"sprite:{pokemon.species}:{size}",
        update_team_health=lambda ident, actual, maximo, slot=None: True,
        _configurar_si_cambia=UnifiedTeamPCView._configurar_si_cambia,
    )
    return yo, destino


def _actualizar(yo, pokemon):
    return UnifiedTeamPCView.update_team_card(yo, "id-1", pokemon, "TANQUE")


def test_todo_lo_que_la_tarjeta_ensena_cambia() -> None:
    yo, _destino = _vista()
    assert _actualizar(yo, ANTES) is True
    registro = yo._team_card_widgets["id-1"]
    viejo = {
        "sprite": registro["sprite"].opciones["image"],
        "titulo": registro["titulo"].opciones["text"],
        "stats_nombre": [e.opciones["text_color"] for e in registro["stats_nombre"]],
        "stats_valor": [e.opciones["text"] for e in registro["stats_valor"]],
        "meta": [e.opciones["text"] for e in registro["meta"]],
        "movs": [e.opciones["text"] for e in registro["textos_mov"]],
    }

    assert _actualizar(yo, DESPUES) is True

    assert registro["sprite"].opciones["image"] != viejo["sprite"], "el sprite es el de antes"
    assert registro["titulo"].opciones["text"] != viejo["titulo"], "el mote o el nivel son los de antes"
    assert "QUAGSIRE" in registro["titulo"].opciones["text"]
    assert "Nv. 28" in registro["titulo"].opciones["text"]

    # La naturaleza cambia de sitio: los seis rótulos deben repintarse.
    nuevos = [e.opciones["text_color"] for e in registro["stats_nombre"]]
    assert sum(1 for a, b in zip(viejo["stats_nombre"], nuevos) if a != b) == 4, (
        "los colores de naturaleza no siguieron al Pokémon nuevo"
    )
    assert [e.opciones["text"] for e in registro["stats_valor"]] != viejo["stats_valor"]
    for clave, etiqueta in zip(STAT_KEYS, registro["stats_valor"]):
        assert etiqueta.opciones["text"] == str(DESPUES.stats[clave])

    assert registro["meta"][0].opciones["text"] == "HABILIDAD · Humedad"
    assert registro["meta"][1].opciones["text"] == "OBJETO · Mineral Suave"

    assert [e.opciones["text"] for e in registro["textos_mov"]] == DESPUES.moves
    for celda in registro["celdas_mov"]:
        assert celda.veces >= 1, "una celda de movimiento se quedó sin repintar"


def test_quien_ocupa_la_tarjeta_se_reapunta() -> None:
    """Si no, soltar sobre la tarjeta movería al Pokémon de antes."""
    yo, destino = _vista()

    assert _actualizar(yo, DESPUES) is True

    assert yo._team_card_pokemon["id-1"] is DESPUES
    assert destino["pokemon"] is DESPUES


def test_una_tarjeta_sin_registrar_manda_reconstruir() -> None:
    yo, _destino = _vista()
    assert UnifiedTeamPCView.update_team_card(yo, "id-9", DESPUES, "TANQUE") is False


def test_si_la_actualizacion_falla_no_se_reapunta_a_medias() -> None:
    """Enseñar a uno y arrastrar a otro sería peor que no acelerar nada."""
    yo, destino = _vista()

    def _revienta(**_kwargs):
        raise RuntimeError("widget destruido")

    yo._team_card_widgets["id-1"]["meta"][1].configure = _revienta

    assert _actualizar(yo, DESPUES) is False
    assert yo._team_card_pokemon["id-1"] is ANTES
    assert destino["pokemon"] is ANTES


def test_todo_lo_registrado_se_actualiza() -> None:
    """Una clave que se guarda y nunca se toca es un dato viejo esperando."""
    registro_fuente = inspect.getsource(UnifiedTeamPCView._render_team_card)
    bloque = registro_fuente.split("self._team_card_widgets[str(identity)] = {")[1]
    bloque = bloque.split("}")[0]
    claves = set(re.findall(r'"([a-z_]+)":', bloque))
    assert claves, "no se pudo leer el registro de la tarjeta"

    actualiza = inspect.getsource(UnifiedTeamPCView.update_team_card)
    for clave in claves:
        assert f'"{clave}"' in actualiza, (
            f'la tarjeta registra "{clave}" y `update_team_card` no lo toca'
        )


def test_la_firma_de_forma_distingue_rol_estado_y_ocupante() -> None:
    yo = types.SimpleNamespace(
        identity_for=lambda p: p.nickname,
        team_slots=[
            {"slot_role": "TANQUE", "state": "", "pokemon": ANTES},
            {"slot_role": "APOYO", "state": "preparation", "pokemon": None},
        ],
    )
    base = UnifiedTeamPCView.team_structure(yo)
    assert base == (("TANQUE", "", "WOOPER"), ("APOYO", "preparation", None))

    yo.team_slots[0]["state"] = "preparation"
    assert UnifiedTeamPCView.team_structure(yo) != base

    yo.team_slots[0]["state"] = ""
    yo.team_slots[0]["pokemon"] = DESPUES
    assert UnifiedTeamPCView.team_structure(yo) != base
