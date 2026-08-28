"""La firma de PS de la vista no puede quedarse con el orden de antes.

Arrancando BDSP, RoleRun se quedó para siempre en «Preparando Equipo y PC…».
El trazado de la barrera lo dijo exacto:

    esperado    [67,67] [66,66] [58,58] [58,58] [70,70] [74,74]
    renderizado [74,74] [67,67] [66,66] [58,58] [58,58] [70,70]

No era un dato viejo: era la **misma lista rotada una posición**.

`rendered_team_health_signature` ordena por el slot físico, porque las tarjetas
se presentan por rol y el reader publica por posición. `update_team_health`
reescribía los PS conservando el slot de cuando se construyó la tarjeta, que era
correcto mientras solo refrescaba PS de una vista recién hecha. Desde que la
tarjeta se actualiza entera sin reconstruirse, ese slot se queda obsoleto en
cuanto la party llega reordenada.

La barrera de arranque no publica por timeout a propósito —«el fallo no se
disfraza como una UI utilizable»—, así que la permutación la dejaba colgada.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402
from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402


class _Barra:
    def __init__(self) -> None:
        self.fraccion = 0.0

    def winfo_exists(self) -> bool:
        return True

    def cget(self, clave):
        return None

    def configure(self, **kwargs) -> None:
        pass

    def get(self) -> float:
        return self.fraccion

    def set(self, valor) -> None:
        self.fraccion = float(valor)


class _Etiqueta:
    def __init__(self) -> None:
        self.texto = ""

    def winfo_exists(self) -> bool:
        return True

    def cget(self, clave):
        return self.texto

    def configure(self, **kwargs) -> None:
        if "text" in kwargs:
            self.texto = kwargs["text"]


class _Mono:
    def __init__(self, slot: int, actual: int, maximo: int) -> None:
        self.slot = slot
        self.current_hp = actual
        self.max_hp = maximo


def _vista(equipo: list[_Mono]):
    """Una vista ya construida con el equipo en el orden en que llegó."""
    yo = types.SimpleNamespace(
        _team_health_widgets={},
        _rendered_team_health=[],
        _health_presentation=UnifiedTeamPCView._health_presentation,
        _configurar_si_cambia=UnifiedTeamPCView._configurar_si_cambia,
    )
    for indice, mono in enumerate(equipo):
        yo._rendered_team_health.append((mono.slot, mono.current_hp, mono.max_hp))
        yo._team_health_widgets[f"id{indice}"] = {
            "bar": _Barra(), "label": _Etiqueta(), "health_index": indice,
        }
    return yo


def _firma(yo) -> tuple:
    return UnifiedTeamPCView.rendered_team_health_signature.fget(yo)


# Los seis del trazado real. Cada tarjeta enseña siempre a la misma identidad
# -esa es la condición para actualizar en sitio-, pero la posición física que
# ocupa cada uno cambia: el que iba primero pasa al final.
CONSTRUIDO = [(1, 74), (2, 67), (3, 66), (4, 58), (5, 58), (6, 70)]
REORDENADO = [(6, 74), (1, 67), (2, 66), (3, 58), (4, 58), (5, 70)]


def _reordenar(yo, con_slot: bool) -> None:
    for indice, (slot, ps) in enumerate(REORDENADO):
        if con_slot:
            UnifiedTeamPCView.update_team_health(
                yo, f"id{indice}", ps, ps, slot=slot,
            )
        else:
            UnifiedTeamPCView.update_team_health(yo, f"id{indice}", ps, ps)


def _equipo(filas) -> list[_Mono]:
    return [_Mono(slot, ps, ps) for slot, ps in filas]


def test_un_equipo_que_llega_reordenado_no_deja_la_firma_permutada() -> None:
    yo = _vista(_equipo(CONSTRUIDO))

    _reordenar(yo, con_slot=True)

    esperado = RoleRunManager._party_health_signature(
        _equipo(sorted(REORDENADO))
    )
    assert _firma(yo) == esperado, (
        "la firma quedó permutada: la barrera de arranque no publicaría nunca"
    )
    assert _firma(yo) == ((67, 67), (66, 66), (58, 58), (58, 58), (70, 70), (74, 74))


def test_asi_era_el_fallo_exacto_que_colgo_el_arranque() -> None:
    """Sin el slot de ahora sale la rotación que dejó el arranque colgado."""
    yo = _vista(_equipo(CONSTRUIDO))

    _reordenar(yo, con_slot=False)

    # Literalmente las dos filas del trazado de BDSP.
    assert _firma(yo) == ((74, 74), (67, 67), (66, 66), (58, 58), (58, 58), (70, 70))
    assert _firma(yo) != ((67, 67), (66, 66), (58, 58), (58, 58), (70, 70), (74, 74))


def test_sin_decir_el_slot_se_conserva_el_de_antes() -> None:
    """El refresco de PS en vivo no conoce la posición y no debe inventarla."""
    yo = _vista([_Mono(4, 30, 60), _Mono(9, 40, 80)])

    UnifiedTeamPCView.update_team_health(yo, "id0", 25, 60)

    assert yo._rendered_team_health[0] == (4, 25, 60)


def test_la_tarjeta_apunta_el_slot_del_pokemon_que_esta_enseñando() -> None:
    import inspect

    fuente = inspect.getsource(UnifiedTeamPCView.update_team_card)
    assert 'slot=int(getattr(pokemon, "slot", 0) or 0)' in fuente, (
        "la tarjeta actualiza los PS sin decir de qué posición física son"
    )


def test_si_los_ps_no_se_pueden_poner_la_tarjeta_no_dice_que_si() -> None:
    """Es lo único que la tarjeta no pinta por sí misma."""
    import inspect

    fuente = inspect.getsource(UnifiedTeamPCView.update_team_card)
    indice = fuente.index("update_team_health(")
    assert "return False" in fuente[indice:indice + 500], (
        "un fallo al poner los PS dejaría en pantalla los del Pokémon anterior"
    )
