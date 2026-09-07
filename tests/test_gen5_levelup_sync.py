"""``_sync_gen5_levelup_moves`` y el historial de RECUERDA MOVIMIENTOS.

Quinta es el único juego donde basta UNA capa: el parche de la tabla en la RAM
de melonDS. No hay red de seguridad reactiva ni parcheo del cartel porque el
juego relee la tabla en cada aprendizaje — demostrado físicamente el
06-09-2026 cambiando el aprendizaje de nivel 5 de Lillipup y viendo al juego
anunciar y enseñar el movimiento cambiado.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.ui import RoleRunManager

BULBASAUR, IVYSAUR, VENUSAUR = 1, 2, 3
VOZARRON, DANZA_DRAGON = 304, 349


class _ImagenFalsa:
    """La imagen de la ROM, sin tocar memoria de verdad."""

    def __init__(self, base: int = 0x1000) -> None:
        self.base_address = base
        self.process_id = 77
        self.aplicados: list[dict[int, int]] = []

    def apply(self, patch, *, expected_levels):
        self.aplicados.append(dict(patch))
        return len(patch)


def _fake(*, role: str = "Mago", entradas=None, imagen=None) -> SimpleNamespace:
    imagen = imagen if imagen is not None else _ImagenFalsa()
    fake = SimpleNamespace(
        save_engine=SimpleNamespace(key="b2w2"),
        project=SimpleNamespace(oras_levelup_move_history={}),
        project_service=SimpleNamespace(save=lambda _p: None),
        engine=SimpleNamespace(
            pools={
                "mago_subir_ataque_esp": [VOZARRON],
                "asesino_subir_ataque": [DANZA_DRAGON],
                "mago_bajar_defensa_esp": [], "asesino_bajar_defensa": [],
            },
            damage_classes={VOZARRON: "special", DANZA_DRAGON: "status"},
            speed_status_moves=set(), self_healing_damage_moves=set(),
            allowed_move_ids=None,
        ),
        current_game=None,
        _gen5_levelup_entries=(
            entradas if entradas is not None
            else {BULBASAUR: ((DANZA_DRAGON, 5, 1000),)}
        ),
        _gen5_levelup_rom_path="falsa.nds",
        _gen5_levelup_image=imagen,
        _gen5_levelup_last_roles_key=None,
        _gen5_levelup_written={},
        _gen5_levelup_history_last_levels={},
        _effective_role=lambda pokemon: (role, ""),
        _registrar_intento_vivo=lambda *a, **k: None,
        _gen5_levelup_locate_image=lambda: imagen,
    )
    for nombre in (
        "_sync_gen5_levelup_moves", "_gen5_levelup_usable_move_ids",
        "_gen5_levelup_levels", "_gen5_levelup_vanilla_moves",
        "_revert_gen5_levelup_moves", "_record_gen5_levelup_move_history",
        "_append_gen5_levelup_history_entries",
        "_purge_gen5_levelup_history_above_level",
    ):
        setattr(fake, nombre, getattr(RoleRunManager, nombre).__get__(fake))
    fake._imagen = imagen
    return fake


def _mon(species_id: int = BULBASAUR, *, level: int = 10, pid: int = 1):
    return SimpleNamespace(
        species_id=species_id, level=level, pid=pid, tid=2, sid=3,
        nickname="", species="Bulbasaur",
    )


class SyncTests(unittest.TestCase):
    def test_parchea_la_entrada_que_no_encaja_con_el_rol(self) -> None:
        fake = _fake(role="Mago")
        fake._sync_gen5_levelup_moves(SimpleNamespace(party=[_mon()]))

        self.assertEqual(len(fake._imagen.aplicados), 1)
        self.assertEqual(list(fake._imagen.aplicados[0]), [1000])
        # Y queda apuntado el valor vainilla para poder revertirlo.
        self.assertEqual(fake._gen5_levelup_written, {1000: DANZA_DRAGON})

    def test_dos_sondeos_con_los_mismos_roles_no_reescriben(self) -> None:
        """El sondeo pasivo repite cada pocos cientos de ms."""
        fake = _fake(role="Mago")
        game = SimpleNamespace(party=[_mon()])
        fake._sync_gen5_levelup_moves(game)
        fake._sync_gen5_levelup_moves(game)
        self.assertEqual(len(fake._imagen.aplicados), 1)

    def test_un_cambio_de_rol_si_vuelve_a_escribir(self) -> None:
        fake = _fake(role="Mago")
        game = SimpleNamespace(party=[_mon()])
        fake._sync_gen5_levelup_moves(game)
        fake._effective_role = lambda pokemon: ("Asesino", "")
        fake._sync_gen5_levelup_moves(game)
        self.assertEqual(len(fake._imagen.aplicados), 2)

    def test_al_retirar_el_rol_se_devuelve_el_movimiento_vainilla(self) -> None:
        """Si no, el sustituto de un rol ya retirado se quedaría puesto."""
        fake = _fake(role="Mago")
        game = SimpleNamespace(party=[_mon()])
        fake._sync_gen5_levelup_moves(game)
        fake._effective_role = lambda pokemon: ("SIN ROL", "")
        fake._sync_gen5_levelup_moves(game)

        self.assertEqual(fake._imagen.aplicados[-1], {1000: DANZA_DRAGON})
        self.assertEqual(fake._gen5_levelup_written, {})

    def test_adelanta_el_mismo_rol_a_las_evoluciones_futuras(self) -> None:
        """Igual que X/Y: cuando evolucione, su fila ya lleva rato correcta."""
        entradas = {
            BULBASAUR: ((DANZA_DRAGON, 5, 1000),),
            IVYSAUR: ((DANZA_DRAGON, 5, 2000),),
            VENUSAUR: ((DANZA_DRAGON, 5, 3000),),
        }
        fake = _fake(role="Mago", entradas=entradas)
        fake._sync_gen5_levelup_moves(SimpleNamespace(party=[_mon()]))
        self.assertEqual(set(fake._imagen.aplicados[0]), {1000, 2000, 3000})

    def test_otro_juego_no_hace_nada(self) -> None:
        fake = _fake()
        fake.save_engine = SimpleNamespace(key="oras")
        fake._sync_gen5_levelup_moves(SimpleNamespace(party=[_mon()]))
        self.assertEqual(fake._imagen.aplicados, [])

    def test_sin_tabla_decodificada_no_escribe(self) -> None:
        fake = _fake()
        fake._gen5_levelup_entries = None
        fake._sync_gen5_levelup_moves(SimpleNamespace(party=[_mon()]))
        self.assertEqual(fake._imagen.aplicados, [])


class RevertTests(unittest.TestCase):
    def test_al_cerrar_se_devuelve_todo_lo_escrito(self) -> None:
        fake = _fake(role="Mago")
        fake._sync_gen5_levelup_moves(SimpleNamespace(party=[_mon()]))
        fake._imagen.aplicados.clear()

        fake._revert_gen5_levelup_moves()

        self.assertEqual(fake._imagen.aplicados, [{1000: DANZA_DRAGON}])
        self.assertEqual(fake._gen5_levelup_written, {})

    def test_sin_nada_escrito_no_toca_la_memoria(self) -> None:
        fake = _fake()
        fake._revert_gen5_levelup_moves()
        self.assertEqual(fake._imagen.aplicados, [])


class HistorialTests(unittest.TestCase):
    """RECUERDA MOVIMIENTOS: lo que le tocaba por su rol en cada cruce."""

    def test_se_anota_en_el_instante_del_cruce_de_nivel(self) -> None:
        entradas = {BULBASAUR: ((DANZA_DRAGON, 5, 1000), (VOZARRON, 19, 1004))}
        fake = _fake(role="Mago", entradas=entradas)
        pokemon = _mon(level=10)
        game = SimpleNamespace(party=[pokemon])
        fake._record_gen5_levelup_move_history(game)   # primera vez: pre-captura
        pokemon.level = 20                              # cruza el nivel 19
        fake._record_gen5_levelup_move_history(game)

        historial = fake.project.oras_levelup_move_history["1:2:3"]
        niveles = [item["level"] for item in historial]
        self.assertIn(19, niveles)

    def test_reiniciar_sin_guardar_descarta_lo_de_niveles_superiores(self) -> None:
        entradas = {BULBASAUR: ((DANZA_DRAGON, 5, 1000), (VOZARRON, 19, 1004))}
        fake = _fake(role="Mago", entradas=entradas)
        fake.project.oras_levelup_move_history["1:2:3"] = [
            {"level": 5, "move_id": DANZA_DRAGON},
            {"level": 19, "move_id": VOZARRON},
        ]
        fake._gen5_levelup_history_last_levels["1:2:3"] = 20
        pokemon = _mon(level=12)                        # bajó de 20 a 12
        fake._record_gen5_levelup_move_history(SimpleNamespace(party=[pokemon]))

        historial = fake.project.oras_levelup_move_history["1:2:3"]
        self.assertEqual([item["level"] for item in historial], [5])


class HistorialCoincideConElParcheTests(unittest.TestCase):
    """Bug real reportado por el usuario el 06-09-2026.

    Patrat aprendió **Llama Fusión** y RECUERDA-MOVIMIENTOS registró **Onda
    Certera**: los dos compatibles con su rol, pero distintos.

    `compute_species_patch` excluye los movimientos que la especie YA tiene en
    su tabla. Calcular sobre el subconjunto recién cruzado da un conjunto de
    exclusiones distinto al de la tabla completa, así que elige otro
    sustituto. Medido sobre la ROM real: 13 de las 14 entradas de Patrat
    discrepaban. El historial debe calcular sobre la tabla COMPLETA, igual que
    el parche.
    """

    ESPECIE = 7
    # Los tres únicos sustitutos que admite Mago en este doble.
    A, B, C = 401, 402, 403
    ESTADO_DE_ASESINO = 349

    def _fake_con_tabla(self):
        entradas = {
            self.ESPECIE: (
                (self.ESTADO_DE_ASESINO, 5, 1000),   # esta es la que se sustituye
                (self.A, 9, 1004),                    # ya la tiene: queda excluida
                (self.B, 12, 1008),                   # ya la tiene: queda excluida
            ),
        }
        fake = _fake(role="Mago", entradas=entradas)
        fake.engine.pools = {
            "mago_subir_ataque_esp": [self.A, self.B, self.C],
            "asesino_subir_ataque": [self.ESTADO_DE_ASESINO],
            "mago_bajar_defensa_esp": [], "asesino_bajar_defensa": [],
        }
        fake.engine.damage_classes = {
            self.A: "special", self.B: "special", self.C: "special",
            self.ESTADO_DE_ASESINO: "status",
        }
        return fake, entradas

    def test_el_historial_registra_lo_mismo_que_escribe_el_parche(self) -> None:
        from app.gen5_levelup_moves import compute_species_patch

        fake, entradas = self._fake_con_tabla()
        completa = entradas[self.ESPECIE]
        comun = dict(
            pools=fake.engine.pools, damage_classes=fake.engine.damage_classes,
            speed_status_moves=set(), self_healing_damage_moves=set(),
            usable_move_ids=None,
        )
        del_parche = compute_species_patch(
            completa, "Mago", species_id=self.ESPECIE, **comun,
        )[1000]

        # Solo la entrada recién cruzada, que es lo que recibe el historial.
        cruzada = (completa[0],)
        fake._append_gen5_levelup_history_entries(
            "id", SimpleNamespace(nickname="X", species="X"),
            self.ESPECIE, cruzada, "Mago", pre_capture=False,
        )
        registrado = fake.project.oras_levelup_move_history["id"][0]["move_id"]
        self.assertEqual(registrado, del_parche)

        # Con dientes: calcular sobre el subconjunto -lo que hacía antes- SÍ
        # da otro resultado, así que esta prueba no pasa por casualidad.
        ingenuo = compute_species_patch(
            cruzada, "Mago", species_id=self.ESPECIE, **comun,
        )[1000]
        self.assertNotEqual(
            ingenuo, del_parche,
            "el doble ya no reproduce la divergencia; la prueba perdería sentido",
        )


class CompuertaDeLaPantallaTests(unittest.TestCase):
    def test_quinta_puede_abrir_recuerda_movimientos(self) -> None:
        import inspect

        from app.ui import MELONDS_GEN5_REALTIME_GAME_KEYS

        fuente = inspect.getsource(RoleRunManager._open_oras_levelup_history)
        self.assertIn("MELONDS_GEN5_REALTIME_GAME_KEYS", fuente)
        self.assertEqual(MELONDS_GEN5_REALTIME_GAME_KEYS, {"b2w2", "bw"})


if __name__ == "__main__":
    unittest.main()
