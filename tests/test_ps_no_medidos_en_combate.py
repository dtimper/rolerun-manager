"""La barra no puede pintar como ciertos unos PS que no ha medido.

Planteado por el usuario el 06-09-2026: «si la barra puede dejar de mostrar la
vida correcta, eso hay que cambiarlo inmediatamente».

Durante un combate, varios juegos solo miden los PS del Pokémon que está en el
campo. Los demás arrastraban los del bloque de equipo —que en quinta está
DEMOSTRADO que no se actualiza hasta que el combate acaba— y la barra los
pintaba con el mismo verde que los medidos, porque `current_hp` era un número
suelto sin procedencia.

Afectaba a: Negro 2 (cinco de seis, siempre), X/Y (cinco de seis), HeartGold
(los seis, no tiene carril de combate), y de forma acotada a Blanco, USUM y
ORAS (solo las filas que no se validan). Sol/Luna y BDSP no estaban afectados:
congelan la última lectura publicada en vez de mezclar fuentes.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from app.save_engine_client import SavePokemon
from app.ui import RoleRunManager


def _mon(pid: int = 1, *, hp: int = 20, max_hp: int = 20, live: bool = True) -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=25, species="Pikachu", nickname="Pika", level=10,
        held_item="Ninguno", ability="Estática", moves=["Placaje"], move_ids=[33],
        is_egg=False, markings=[False] * 6, role="Mago", role_symbol="",
        pid=pid, tid=2, sid=3, current_hp=hp, max_hp=max_hp, hp_is_live=live,
    )


class ModeloTests(unittest.TestCase):
    def test_por_defecto_los_ps_se_consideran_medidos(self) -> None:
        """Fuera de combate el bloque de equipo SÍ es la verdad.

        El valor por defecto tiene que ser `True` o cambiaría el
        comportamiento de todas las lecturas normales.
        """
        self.assertTrue(_mon().hp_is_live)


class BarraFlotanteTests(unittest.TestCase):
    def _manager(self, snapshot_party=None) -> SimpleNamespace:
        fake = SimpleNamespace(
            _oras_live_health_snapshot=(
                SimpleNamespace(party=snapshot_party)
                if snapshot_party is not None else None
            ),
            _pokemon_identity=lambda p: f"{p.pid}:{p.tid}:{p.sid}",
        )
        fake._floating_hp_is_live = RoleRunManager._floating_hp_is_live.__get__(fake)
        return fake

    def test_unos_ps_medidos_se_dan_por_ciertos(self) -> None:
        fake = self._manager()
        self.assertTrue(fake._floating_hp_is_live(_mon(live=True)))

    def test_unos_ps_no_medidos_no_se_dan_por_ciertos(self) -> None:
        fake = self._manager()
        self.assertFalse(fake._floating_hp_is_live(_mon(live=False)))

    def test_manda_la_misma_autoridad_que_elige_el_numero(self) -> None:
        """La marca y el número los decide el MISMO candidato.

        Si no, la barra podría pintar el número de la sonda viva con la marca
        del proyectado, o al revés: exactamente la incoherencia que se quiere
        evitar.
        """
        proyectado = _mon(live=True)
        de_la_sonda = replace(_mon(live=False), current_hp=7)
        fake = self._manager(snapshot_party=[de_la_sonda])
        self.assertFalse(fake._floating_hp_is_live(proyectado))

    def test_sin_coincidencia_unica_manda_el_proyectado(self) -> None:
        gemelos = [_mon(live=True), _mon(live=True)]
        fake = self._manager(snapshot_party=gemelos)
        self.assertFalse(fake._floating_hp_is_live(_mon(live=False)))

    def test_un_hueco_vacio_no_rompe_nada(self) -> None:
        self.assertTrue(self._manager()._floating_hp_is_live(None))

    def test_un_pokemon_sin_el_campo_se_considera_medido(self) -> None:
        """Compatibilidad: cualquier objeto viejo sin `hp_is_live`."""
        fake = self._manager()
        self.assertTrue(fake._floating_hp_is_live(SimpleNamespace(pid=1, tid=2, sid=3)))


class ColorDeLaBarraTests(unittest.TestCase):
    def test_el_color_neutro_solo_aparece_cuando_no_hay_medida(self) -> None:
        """El color es la afirmación más fuerte: verde dice «este está bien»."""
        import inspect

        fuente = inspect.getsource(RoleRunManager._render_floating_bar)
        self.assertIn("hp_en_vivo = self._floating_hp_is_live(pokemon)", fuente)
        # El color de salud solo se usa si los PS están medidos.
        self.assertIn("if hp_en_vivo else", fuente)


class MarcadoPorJuegoTests(unittest.TestCase):
    """Cada backend afectado tiene que marcar lo que NO ha medido."""

    def test_xy_marca_a_los_que_no_estan_en_el_campo(self) -> None:
        import inspect

        from app.xy_live import XYLiveReader

        fuente = inspect.getsource(XYLiveReader)
        self.assertIn("clone.hp_is_live = False", fuente)

    def test_quinta_marca_a_los_que_no_tienen_fila_propia(self) -> None:
        import inspect

        from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

        fuente = inspect.getsource(B2W2RealTimeAdapter)
        self.assertIn("hp_is_live=member.slot in por_slot", fuente)

    def test_oras_marca_las_entradas_que_no_validan(self) -> None:
        import inspect

        from app.oras_live import ORASBattleProbe

        del ORASBattleProbe  # solo para fijar el import del módulo
        import app.oras_live as oras_live

        self.assertIn("clone.hp_is_live = medido", inspect.getsource(oras_live))

    def test_usum_marca_los_slots_sin_fila_unica(self) -> None:
        import inspect

        import app.usum_live as usum_live

        self.assertIn("hp_is_live=False", inspect.getsource(usum_live))


if __name__ == "__main__":
    unittest.main()
