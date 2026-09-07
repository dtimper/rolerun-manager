"""Un banquillo no cura solo, y no arranca en gris si no hace falta.

Reproduce dos reportes seguidos de la partida real del usuario el 06-09-2026:

1. Zigzagoon recibe un golpe estando activo, se cambia a Combee, y la barra
   flotante lo muestra "curado" a su PS máximo. El bloque de equipo
   (`XY_PARTY_ADDRESS`) no sigue el daño de un miembro ya benqueado —queda
   congelado en su valor de antes de esta pelea—, así que usarlo como
   respaldo "cura" en pantalla a un Pokémon que sigue dañado de verdad.

2. Corregido (1) marcando cada miembro como confirmado SOLO cuando ya había
   estado en el campo esta pelea, apareció un segundo problema: nada más caer
   el primer Pokémon, los otros cinco -que nunca habían salido- se pintaban
   en gris hasta que les tocaba turno uno a uno. Eso ignoraba un hecho ya
   demostrado en este mismo proyecto: fuera de combate el bloque de equipo SÍ
   es la verdad. En el instante justo antes de esta pelea, los seis PS del
   bloque de equipo son exactos -nadie pudo perder ni ganar vida sin que
   quedara reflejado ahí-, así que sirven de línea base para todos, no solo
   para quien resulte activo primero.

En los juegos principales un Pokémon en el banquillo no puede perder ni ganar
PS por ningún medio ajeno al combate activo (sin veneno, quemadura ni nada
fuera de campo), así que el PS confirmado -de la línea base al empezar la
pelea, o de la última vez que SÍ estuvo en el campo- sigue siendo exacto
mientras siga fuera. Se cachea por identidad y se usa en vez del bloque de
equipo, que solo se ha demostrado desfasado DURANTE un combate ya en curso.
"""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.save_engine_client import SaveGameData, SavePokemon
from app.xy_live import (
    XY_BATTLE_HP_OFFSET,
    XY_BATTLE_OPPONENT_PTR_1,
    XY_BATTLE_OPPONENT_PTR_2,
    XY_BATTLE_PARTY_PTR_1,
    XY_BATTLE_PARTY_PTR_2,
    XY_TITLE_IDS,
    XYLiveReader,
)

OPP_STRUCT = 0x08300000
ZIGZAGOON_STRUCT = 0x08204000
COMBEE_STRUCT = 0x08205000


def _mon(slot: int, *, max_hp: int, hp: int) -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=100 + slot, species=f"Esp{slot}", nickname=f"Mon{slot}",
        level=10, held_item="Ninguno", ability="Nada", moves=["Placaje"], move_ids=[33],
        is_egg=False, markings=[False] * 6, role="Mago", role_symbol="",
        pid=1000 + slot, tid=2, sid=3, current_hp=hp, max_hp=max_hp,
    )


class _ClienteFalso:
    """Sirve punteros fijos y deja fijar libremente el PS del que está activo."""

    def __init__(self, activo_struct: int, activo_hp: tuple[int, int]):
        self.opp_hp = (29, 29)
        self.activo_struct = activo_struct
        self.activo_hp = activo_hp
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, _pid):
        return None

    def read_memory(self, address: int, size: int) -> bytes:
        if address == XY_BATTLE_OPPONENT_PTR_1 or address == XY_BATTLE_OPPONENT_PTR_2:
            return struct.pack("<I", OPP_STRUCT)
        if address == OPP_STRUCT + XY_BATTLE_HP_OFFSET:
            return struct.pack("<HH", *self.opp_hp)
        if address == XY_BATTLE_PARTY_PTR_1 or address == XY_BATTLE_PARTY_PTR_2:
            return struct.pack("<I", self.activo_struct)
        if address == self.activo_struct + XY_BATTLE_HP_OFFSET:
            return struct.pack("<HH", *self.activo_hp)
        raise AssertionError(f"lectura inesperada en 0x{address:08X}")


class _ClienteSinCombate:
    def __init__(self):
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, _pid):
        return None

    def read_memory(self, address: int, size: int) -> bytes:
        return struct.pack("<I", 0)


def _lector() -> XYLiveReader:
    return XYLiveReader(Path("data/moves.json"))


class BenquilloConservaSuUltimoPSConfirmadoTests(unittest.TestCase):
    def _partida(self, party) -> SaveGameData:
        return SaveGameData(
            game="X", save_type="RAM", generation=6, trainer=None, party=party, raw={},
        )

    def test_al_cambiar_de_activo_el_benqueado_conserva_su_golpe(self) -> None:
        """Reproduce exactamente el reporte: un único cambio ya lo curaba."""
        zigzagoon = _mon(1, max_hp=18, hp=18)  # bloque de equipo: valor previo a esta pelea
        combee = _mon(2, max_hp=29, hp=29)
        reader = _lector()

        # Turno 1: Zigzagoon activo, recibe un golpe (18 -> 7).
        reader.client_factory = lambda: _ClienteFalso(ZIGZAGOON_STRUCT, (18, 7))
        probe1 = reader.read_battle_probe(self._partida([zigzagoon, combee]))
        self.assertIsNotNone(probe1.health_game)
        self.assertEqual(probe1.health_game.party[0].current_hp, 7)
        self.assertTrue(probe1.health_game.party[0].hp_is_live)

        # Turno 2: se cambia a Combee. El bloque de equipo SIGUE diciendo que
        # Zigzagoon está a 18 (nunca se actualizó) -- eso es justo lo que no
        # hay que creerse.
        reader.client_factory = lambda: _ClienteFalso(COMBEE_STRUCT, (29, 29))
        probe2 = reader.read_battle_probe(self._partida([zigzagoon, combee]))
        self.assertIsNotNone(probe2.health_game)
        zig_after = next(m for m in probe2.health_game.party if m.nickname == "Mon1")
        self.assertEqual(zig_after.current_hp, 7)  # sigue con el golpe, no "curado"
        self.assertTrue(zig_after.hp_is_live)

    def test_todo_el_equipo_se_confirma_desde_el_primer_instante_de_la_pelea(self) -> None:
        """Reproduce el segundo reporte: no hace falta que cada uno salga al

        campo para confiar en su PS. En el instante justo antes de esta
        pelea el bloque de equipo YA era la verdad para los seis.
        """
        zigzagoon = _mon(1, max_hp=18, hp=18)
        scatterbug = _mon(3, max_hp=15, hp=15)  # nunca sale a este combate
        reader = _lector()
        reader.client_factory = lambda: _ClienteFalso(ZIGZAGOON_STRUCT, (18, 11))
        probe = reader.read_battle_probe(self._partida([zigzagoon, scatterbug]))
        self.assertIsNotNone(probe.health_game)
        bug = next(m for m in probe.health_game.party if m.nickname == "Mon3")
        self.assertEqual(bug.current_hp, 15)
        self.assertTrue(bug.hp_is_live)  # confirmado por la línea base de inicio

    def test_un_kfo_no_apaga_a_los_que_nunca_han_salido(self) -> None:
        """Reproduce el reporte exacto: al caer el activo, el resto del equipo

        NO debe volver a gris -ya estaban confirmados desde el inicio de la
        pelea- aunque nunca hayan pisado el campo.
        """
        zigzagoon = _mon(1, max_hp=18, hp=18)
        pidgey = _mon(2, max_hp=16, hp=16)
        combee = _mon(3, max_hp=29, hp=29)
        reader = _lector()

        # Turno 1: Zigzagoon activo. Pidgey y Combee, sin salir aún, YA están
        # confirmados por la línea base del inicio de combate.
        reader.client_factory = lambda: _ClienteFalso(ZIGZAGOON_STRUCT, (18, 9))
        probe1 = reader.read_battle_probe(self._partida([zigzagoon, pidgey, combee]))
        self.assertTrue(all(m.hp_is_live for m in probe1.health_game.party))

        # Turno 2: Zigzagoon cae a 0. Pidgey y Combee siguen confirmados.
        reader.client_factory = lambda: _ClienteFalso(ZIGZAGOON_STRUCT, (18, 0))
        probe2 = reader.read_battle_probe(self._partida([zigzagoon, pidgey, combee]))
        self.assertTrue(all(m.hp_is_live for m in probe2.health_game.party))
        pidgey_after = next(m for m in probe2.health_game.party if m.nickname == "Mon2")
        self.assertEqual(pidgey_after.current_hp, 16)

    def test_la_cache_se_limpia_al_terminar_el_combate(self) -> None:
        """Dos tics seguidos sin rival, no uno: ver `UnSoloTickSinRivalNoTerminaElCombateTests`."""
        zigzagoon = _mon(1, max_hp=18, hp=18)
        combee = _mon(2, max_hp=29, hp=29)
        reader = _lector()
        reader.client_factory = lambda: _ClienteFalso(ZIGZAGOON_STRUCT, (18, 7))
        reader.read_battle_probe(self._partida([zigzagoon, combee]))
        self.assertIn((101, 1001, 2, 3), reader._battle_confirmed_hp)

        reader.client_factory = _ClienteSinCombate
        reader.read_battle_probe(self._partida([zigzagoon, combee]))
        reader.read_battle_probe(self._partida([zigzagoon, combee]))
        self.assertEqual(reader._battle_confirmed_hp, {})


if __name__ == "__main__":
    unittest.main()


class _ClienteOponenteInvalido:
    """Igual que `_ClienteFalso`, pero el puntero del rival da basura."""

    def __init__(self, activo_struct: int, activo_hp: tuple[int, int]):
        self.activo_struct = activo_struct
        self.activo_hp = activo_hp
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, _pid):
        return None

    def read_memory(self, address: int, size: int) -> bytes:
        if address in (XY_BATTLE_OPPONENT_PTR_1, XY_BATTLE_OPPONENT_PTR_2):
            return struct.pack("<I", 0)  # puntero fuera de rango: instante de transición
        if address == XY_BATTLE_PARTY_PTR_1 or address == XY_BATTLE_PARTY_PTR_2:
            return struct.pack("<I", self.activo_struct)
        if address == self.activo_struct + XY_BATTLE_HP_OFFSET:
            return struct.pack("<HH", *self.activo_hp)
        raise AssertionError(f"lectura inesperada en 0x{address:08X}")


class UnSoloTickSinRivalNoTerminaElCombateTests(unittest.TestCase):
    """Reproduce el reporte: al caer un Pokémon, el resto "se restaura"."""

    def _partida(self, party) -> SaveGameData:
        return SaveGameData(
            game="X", save_type="RAM", generation=6, trainer=None, party=party, raw={},
        )

    def test_un_blip_del_rival_no_publica_el_bloque_de_equipo_crudo(self) -> None:
        zigzagoon = _mon(1, max_hp=18, hp=18)
        pidgey = _mon(2, max_hp=16, hp=16)
        reader = _lector()

        # Combate en curso, Zigzagoon activo y tocado. Pidgey ya confirmado
        # por la línea base del inicio de combate.
        reader.client_factory = lambda: _ClienteFalso(ZIGZAGOON_STRUCT, (18, 9))
        probe1 = reader.read_battle_probe(self._partida([zigzagoon, pidgey]))
        self.assertEqual(probe1.state, "trainer")
        self.assertTrue(all(m.hp_is_live for m in probe1.health_game.party))

        # Zigzagoon cae; el puntero del rival da basura durante ESTE tick.
        reader.client_factory = lambda: _ClienteOponenteInvalido(ZIGZAGOON_STRUCT, (18, 0))
        probe2 = reader.read_battle_probe(self._partida([zigzagoon, pidgey]))
        # Sigue "en combate" a ojos del llamador y, sobre todo, NO publica un
        # health_game nuevo: ui.py conserva el último bueno en vez de
        # sustituirlo por el bloque de equipo crudo.
        self.assertEqual(probe2.state, "trainer")
        self.assertIsNone(probe2.health_game)
        # La caché sigue intacta -no se ha dado el combate por terminado.
        self.assertIn((101, 1001, 2, 3), reader._battle_confirmed_hp)

    def test_dos_tics_seguidos_sin_rival_si_confirman_el_fin_del_combate(self) -> None:
        zigzagoon = _mon(1, max_hp=18, hp=18)
        reader = _lector()
        reader.client_factory = lambda: _ClienteFalso(ZIGZAGOON_STRUCT, (18, 9))
        reader.read_battle_probe(self._partida([zigzagoon]))

        reader.client_factory = _ClienteSinCombate
        probe_a = reader.read_battle_probe(self._partida([zigzagoon]))
        self.assertEqual(probe_a.state, "trainer")  # primer tick: solo un aviso

        probe_b = reader.read_battle_probe(self._partida([zigzagoon]))
        self.assertEqual(probe_b.state, "none")  # segundo tick seguido: sí termina
        self.assertEqual(reader._battle_confirmed_hp, {})


if __name__ == "__main__":
    unittest.main()
