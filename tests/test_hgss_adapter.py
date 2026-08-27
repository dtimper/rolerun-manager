"""El adaptador de tiempo real de HeartGold.

Lo que aquí se fija, además de que lea bien:

* Que **no prometa escribir**. Cuarta entra en alpha.72 solo con lectura, y
  meterla en los conjuntos de writers de la interfaz le atribuiría curación,
  fijar roles y enseñanza de MT que no existen.
* Que un rol ya guardado en la Run **no se borre** porque el PK4 vivo todavía no
  tenga marcas: es el mismo cuidado que se tuvo en quinta antes de su writer.
* Que las estadísticas del PC se calculen —un PK4 almacenado no las trae— y las
  del equipo se publiquen tal cual, porque ahí sí las escribe el juego.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gen4_memory import GEN4_MEMORY  # noqa: E402
from app.hgss_live import (  # noqa: E402
    HgssLiveError, HgssPartyRead, HgssPCRead, HgssTrainerRead, parse_party_block,
)
from app.pk4 import PK4_STORED_SIZE, parse_pk4_boxed  # noqa: E402
from app.realtime.hgss_adapter import HgssRealTimeAdapter  # noqa: E402
from app.save_engine_client import SaveGameData, SavePokemon  # noqa: E402

_CASOS = json.loads(
    (Path(__file__).resolve().parent / "data" / "pk4_cases.json").read_text(encoding="utf-8")
)["cases"]
HGSS = GEN4_MEMORY["hgss"]


def _party(cuantos: int):
    crudo = b"".join(
        bytes.fromhex(_CASOS[indice]["party_hex"]) for indice in range(cuantos)
    )
    return crudo, parse_party_block(crudo, cuantos)


@dataclass
class _LectorFalso:
    """Un lector que no toca melonDS: devuelve lo que se le ponga."""

    cuantos: int = 3
    dinero: int = 12345
    johto: int = 0b00000111
    kanto: int = 0b00000001
    pc_slots: tuple = ()
    olvidos: int = 0

    def __post_init__(self):
        self.memory = HGSS

    def read_party(self):
        crudo, equipo = _party(self.cuantos)
        return HgssPartyRead(4242, "melonDS.exe", 0x1000, self.cuantos, crudo, equipo)

    def read_trainer(self, party_read=None):
        return HgssTrainerRead(self.dinero, self.johto, self.kanto)

    def read_pc(self, party_read=None):
        dentro = []
        for indice_caso, hueco_global in self.pc_slots:
            guardado = parse_pk4_boxed(
                bytes.fromhex(_CASOS[indice_caso]["boxed_hex"]), hueco_global,
            )
            dentro.append(guardado)
        return HgssPCRead(
            4242, "melonDS.exe", 0x1000, HGSS.pc, b"", 540 - len(dentro), tuple(dentro),
        )

    def forget_resolved_base(self):
        self.olvidos += 1


def _ancla(pokemon, *, role: str = "", markings=None) -> SavePokemon:
    return SavePokemon(
        slot=pokemon.slot, species_id=pokemon.species_id, species="",
        nickname=pokemon.nickname, level=pokemon.level, held_item="", ability="",
        moves=[], move_ids=[], is_egg=False,
        markings=list(markings or [False] * 6), role=role,
        role_symbol="◆" if role else "",
        pid=pokemon.pid, tid=pokemon.tid, sid=pokemon.sid,
    )


def _guardado(equipo, **kwargs) -> SaveGameData:
    return SaveGameData(
        "HG", "SAV4HGSS", 4, None, [_ancla(p, **kwargs) for p in equipo], {},
    )


@pytest.fixture
def adaptador():
    lector = _LectorFalso()
    return HgssRealTimeAdapter(reader=lector), lector


# --------------------------------------------------------------------------
# Lectura del equipo
# --------------------------------------------------------------------------

def test_el_equipo_se_publica_con_lo_que_el_jugador_ve(adaptador) -> None:
    adapter, lector = adaptador
    _crudo, equipo = _party(lector.cuantos)
    snapshot = adapter.capture_monitor(_guardado(equipo), save_path=None)

    assert len(snapshot.game.party) == lector.cuantos
    for publicado, vivo in zip(snapshot.game.party, equipo):
        assert publicado.nickname == vivo.nickname
        assert publicado.level == vivo.level
        assert publicado.current_hp == vivo.current_hp
        assert publicado.max_hp == vivo.max_hp
        # El PK4 de combate trae las estadísticas escritas por el juego: se
        # publican, no se recalculan.
        assert publicado.stats["hp"] == vivo.stats[0]
        assert publicado.stats["speed"] == vivo.stats[5]
        assert publicado.ivs["hp"] == vivo.ivs[0]


def test_el_guardado_publicado_dice_que_es_cuarta_y_que_no_escribe(adaptador) -> None:
    adapter, lector = adaptador
    _crudo, equipo = _party(lector.cuantos)
    snapshot = adapter.capture_monitor(_guardado(equipo), save_path=None)

    assert snapshot.game.generation == 4
    assert snapshot.game.save_type == "SAV4HGSS"
    assert snapshot.game.raw["writes_enabled"] is False


def test_sin_identidades_en_comun_no_se_publica_nada(adaptador) -> None:
    adapter, _lector = adaptador
    otro = SaveGameData("HG", "SAV4HGSS", 4, None, [], {})
    with pytest.raises(HgssLiveError, match="identidad fuerte"):
        adapter.capture_monitor(otro, save_path=None)


def test_un_rol_ya_guardado_no_se_borra_porque_el_pk4_no_tenga_marcas(adaptador) -> None:
    # Cuarta todavía no escribe las marcas; si el rol vivo mandara, abrir la Run
    # dejaría a todo el equipo SIN ROL.
    adapter, lector = adaptador
    _crudo, equipo = _party(lector.cuantos)
    snapshot = adapter.capture_monitor(
        _guardado(equipo, role="Muro"), save_path=None,
    )
    assert {p.role for p in snapshot.game.party} == {"Muro"}


def test_capture_full_y_capture_monitor_publican_lo_mismo(adaptador) -> None:
    adapter, lector = adaptador
    _crudo, equipo = _party(lector.cuantos)
    actual = _guardado(equipo)
    uno = adapter.capture_monitor(actual, save_path=None)
    otro = adapter.capture_full(actual, save_path=None)
    assert [p.nickname for p in uno.game.party] == [p.nickname for p in otro.game.party]


# --------------------------------------------------------------------------
# Medallas
# --------------------------------------------------------------------------

def test_las_medallas_suman_johto_y_kanto(adaptador) -> None:
    adapter, lector = adaptador
    lector.johto, lector.kanto = 0b00001111, 0b00000011
    _crudo, equipo = _party(lector.cuantos)
    snapshot = adapter.capture_monitor(_guardado(equipo), save_path=None)
    assert snapshot.badges == 6


def test_si_las_medallas_fallan_no_se_inventa_un_cero(adaptador) -> None:
    # Cero medallas y «no se pudieron leer» son cosas distintas, y publicar la
    # primera por la segunda mentiría en la cabecera.
    adapter, lector = adaptador

    def revienta(party_read=None):
        raise HgssLiveError("no se pudo leer")

    lector.read_trainer = revienta
    _crudo, equipo = _party(lector.cuantos)
    snapshot = adapter.capture_monitor(_guardado(equipo), save_path=None)
    assert snapshot.badges is None
    avisos = [d for d in snapshot.diagnostics if d.lane == "badges"]
    assert avisos and "no se pudo leer" in avisos[0].message


def test_se_avisa_de_que_el_combate_no_esta_demostrado(adaptador) -> None:
    adapter, lector = adaptador
    _crudo, equipo = _party(lector.cuantos)
    snapshot = adapter.capture_monitor(_guardado(equipo), save_path=None)
    combate = [d for d in snapshot.diagnostics if d.lane == "battle"]
    assert combate and "no está demostrada" in combate[0].message


# --------------------------------------------------------------------------
# El PC
# --------------------------------------------------------------------------

def test_el_pc_reparte_los_pokemon_en_su_caja_y_su_hueco(adaptador) -> None:
    adapter, lector = adaptador
    # (caso, hueco global) -> caja 1 hueco 1, caja 1 hueco 30, caja 2 hueco 1.
    lector.pc_slots = ((0, 0), (1, 29), (2, 30))
    _party_read, base, huecos = adapter.read_pc([])

    assert base == HGSS.pc
    assert set(huecos) == {(1, 1), (1, 30), (2, 1)}
    for (caja, hueco), publicado in huecos.items():
        assert publicado.box == caja
        assert publicado.box_slot == hueco


def test_el_pc_calcula_el_nivel_y_las_estadisticas_que_el_bloque_no_trae(adaptador) -> None:
    adapter, lector = adaptador
    lector.pc_slots = ((0, 0),)
    _party_read, _base, huecos = adapter.read_pc([])
    publicado = huecos[(1, 1)]

    # Un PK4 almacenado no lleva nivel ni estadísticas: salen de la experiencia
    # y de la tabla personal.
    assert publicado.level >= 1
    assert publicado.stats["hp"] > 0
    assert publicado.base_stats["hp"] > 0


def test_el_pc_rechaza_un_reparto_de_cajas_que_no_es_el_del_juego(adaptador) -> None:
    adapter, _lector = adaptador
    with pytest.raises(HgssLiveError, match="18 cajas"):
        adapter.read_pc([], box_count=24)
    with pytest.raises(HgssLiveError, match="30 huecos"):
        adapter.read_pc([], box_slot_count=20)


def test_un_pc_vacio_no_publica_huecos(adaptador) -> None:
    adapter, _lector = adaptador
    _party_read, _base, huecos = adapter.read_pc([])
    assert huecos == {}


# --------------------------------------------------------------------------
# Estado del adaptador
# --------------------------------------------------------------------------

def test_el_estado_publica_el_ancla_y_que_no_escribe(adaptador) -> None:
    adapter, _lector = adaptador
    estado = adapter.runtime_state()
    assert estado["game"] == "hgss"
    assert estado["anchor"] == "0x0227C304"
    assert estado["writes_enabled"] is False


def test_reiniciar_el_estado_olvida_la_base(adaptador) -> None:
    adapter, lector = adaptador
    adapter.reset_runtime_state()
    assert lector.olvidos == 1


def test_el_adaptador_no_ofrece_escritura_todavia(adaptador) -> None:
    from app.realtime.adapter import RealTimeAdapterError

    adapter, _lector = adaptador
    with pytest.raises(RealTimeAdapterError):
        adapter.apply_changes(SaveGameData("HG", "SAV4HGSS", 4, None, [], {}), [])
    with pytest.raises(RealTimeAdapterError):
        adapter.read_tm_inventory()


# --------------------------------------------------------------------------
# Cómo entra en la interfaz
# --------------------------------------------------------------------------

def test_heartgold_entra_en_las_listas_de_lectura_pero_no_en_las_de_escritura() -> None:
    from app.ui import (
        AUTOMATIC_BADGE_GAME_KEYS,
        INSTANT_REALTIME_UI_GAME_KEYS,
        LIVE_PC_READ_GAME_KEYS,
        MELONDS_GEN4_REALTIME_GAME_KEYS,
        MELONDS_GEN5_REALTIME_GAME_KEYS,
        MELONDS_REALTIME_GAME_KEYS,
        REALTIME_READ_GAME_KEYS,
        ROLE_EV_WRITER_GAME_KEYS,
    )

    assert MELONDS_GEN4_REALTIME_GAME_KEYS == {"hgss"}
    assert MELONDS_GEN5_REALTIME_GAME_KEYS == {"b2w2", "bw"}
    assert MELONDS_REALTIME_GAME_KEYS == {"b2w2", "bw", "hgss"}
    for conjunto in (
        REALTIME_READ_GAME_KEYS, LIVE_PC_READ_GAME_KEYS,
        INSTANT_REALTIME_UI_GAME_KEYS, AUTOMATIC_BADGE_GAME_KEYS,
    ):
        assert "hgss" in conjunto
    # Y no en la de writers: no existe ninguno todavía.
    assert "hgss" not in ROLE_EV_WRITER_GAME_KEYS


def test_la_ayuda_de_heartgold_no_promete_lo_que_no_tiene() -> None:
    from app.ui import RoleRunManager

    texto = RoleRunManager._live_runtime_help_text("hgss")
    assert "medallas" in texto
    assert "no están demostrados" in texto
    assert "escritura" in texto.lower()


def test_el_pc_de_cuarta_declara_dieciocho_cajas() -> None:
    from app.realtime.hgss_adapter import PC_BOX_COUNT_HGSS

    assert PC_BOX_COUNT_HGSS == 18
    assert PK4_STORED_SIZE == 136
