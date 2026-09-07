"""``_sync_hgss_levelup_moves`` y el historial de RECUERDA MOVIMIENTOS.

Mirror de ``tests/test_gen5_levelup_sync.py``. La diferencia de formato entre
cuarta y quinta (un solo u16 empaquetado por entrada, no dos separados) vive
en ``gen4_levelup_moves``/``gen4_levelup_memory``, ya probados aparte
(``tests/test_gen4_levelup_moves.py``, ``tests/test_gen4_levelup_memory.py``);
aquí lo que se prueba es el pegamento con la interfaz -exactamente el mismo
que quinta, `compute_species_patch` no sabe ni le importa cómo se empaqueta-.

Si HeartGold cachea la tabla como X/Y o la relee como ORAS/quinta todavía no
se ha probado contra la partida real: eso exige un cambio de nivel real.
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
        save_engine=SimpleNamespace(key="hgss"),
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
        _hgss_levelup_entries=(
            entradas if entradas is not None
            else {BULBASAUR: ((DANZA_DRAGON, 5, 1000),)}
        ),
        _hgss_levelup_rom_path="falsa.nds",
        _hgss_levelup_image=imagen,
        _hgss_levelup_last_roles_key=None,
        _hgss_levelup_written={},
        _hgss_levelup_history_last_levels={},
        _effective_role=lambda pokemon: (role, ""),
        _registrar_intento_vivo=lambda *a, **k: None,
        _hgss_levelup_locate_image=lambda: imagen,
        # `_sync_hgss_levelup_moves` intenta registrar la tabla por sí sola
        # si todavía no la tiene -ver el fallo real de "nunca se activaba"-.
        # El doble no tiene ROM que cargar; se limita a no hacer nada, que es
        # justo lo que produciría un guardado sin ROM al lado.
        _get_gen4_rom_profile=lambda _key: None,
    )
    for nombre in (
        "_sync_hgss_levelup_moves", "_hgss_levelup_usable_move_ids",
        "_hgss_levelup_levels", "_hgss_levelup_vanilla_moves",
        "_revert_hgss_levelup_moves", "_record_hgss_levelup_move_history",
        "_append_hgss_levelup_history_entries",
        "_purge_hgss_levelup_history_above_level",
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
        fake._sync_hgss_levelup_moves(SimpleNamespace(party=[_mon()]))

        self.assertEqual(len(fake._imagen.aplicados), 1)
        self.assertEqual(list(fake._imagen.aplicados[0]), [1000])
        self.assertEqual(fake._hgss_levelup_written, {1000: DANZA_DRAGON})

    def test_dos_sondeos_con_los_mismos_roles_no_reescriben(self) -> None:
        fake = _fake(role="Mago")
        game = SimpleNamespace(party=[_mon()])
        fake._sync_hgss_levelup_moves(game)
        fake._sync_hgss_levelup_moves(game)
        self.assertEqual(len(fake._imagen.aplicados), 1)

    def test_un_cambio_de_rol_si_vuelve_a_escribir(self) -> None:
        fake = _fake(role="Mago")
        game = SimpleNamespace(party=[_mon()])
        fake._sync_hgss_levelup_moves(game)
        fake._effective_role = lambda pokemon: ("Asesino", "")
        fake._sync_hgss_levelup_moves(game)
        self.assertEqual(len(fake._imagen.aplicados), 2)

    def test_al_retirar_el_rol_se_devuelve_el_movimiento_vainilla(self) -> None:
        fake = _fake(role="Mago")
        game = SimpleNamespace(party=[_mon()])
        fake._sync_hgss_levelup_moves(game)
        fake._effective_role = lambda pokemon: ("SIN ROL", "")
        fake._sync_hgss_levelup_moves(game)

        self.assertEqual(fake._imagen.aplicados[-1], {1000: DANZA_DRAGON})
        self.assertEqual(fake._hgss_levelup_written, {})

    def test_adelanta_el_mismo_rol_a_las_evoluciones_futuras(self) -> None:
        entradas = {
            BULBASAUR: ((DANZA_DRAGON, 5, 1000),),
            IVYSAUR: ((DANZA_DRAGON, 5, 2000),),
            VENUSAUR: ((DANZA_DRAGON, 5, 3000),),
        }
        fake = _fake(role="Mago", entradas=entradas)
        fake._sync_hgss_levelup_moves(SimpleNamespace(party=[_mon()]))
        self.assertEqual(set(fake._imagen.aplicados[0]), {1000, 2000, 3000})

    def test_otro_juego_no_hace_nada(self) -> None:
        fake = _fake()
        fake.save_engine = SimpleNamespace(key="oras")
        fake._sync_hgss_levelup_moves(SimpleNamespace(party=[_mon()]))
        self.assertEqual(fake._imagen.aplicados, [])

    def test_sin_tabla_decodificada_no_escribe(self) -> None:
        fake = _fake()
        fake._hgss_levelup_entries = None
        fake._sync_hgss_levelup_moves(SimpleNamespace(party=[_mon()]))
        self.assertEqual(fake._imagen.aplicados, [])

    def test_sin_tabla_el_propio_sondeo_intenta_registrarla(self) -> None:
        """Reproduce el fallo real: nada más en la interfaz de HeartGold pide

        la ROM de forma rutinaria -Consulta de Movimientos y
        Recuerda-Movimientos no la tocan-, así que el registro nunca se
        disparaba y esta sincronización se quedaba sin tabla para siempre.
        """
        fake = _fake()
        fake._hgss_levelup_entries = None
        fake._hgss_levelup_rom_path = None
        llamadas = []
        fake._get_gen4_rom_profile = lambda key: llamadas.append(key)
        fake._sync_hgss_levelup_moves(SimpleNamespace(party=[_mon()]))
        self.assertEqual(llamadas, ["hgss"])

    def test_si_el_registro_tiene_exito_a_mitad_de_sondeo_sigue_adelante(self) -> None:
        """`_get_gen4_rom_profile` puebla las entradas por su cuenta al tener

        éxito -es lo que hace `_ensure_hgss_levelup_registered`-; el sondeo
        debe seguir y parchear en la MISMA pasada, no esperar a la siguiente.
        """
        fake = _fake(role="Mago")
        fake._hgss_levelup_entries = None
        fake._hgss_levelup_rom_path = None

        def _registra(_key):
            fake._hgss_levelup_entries = {BULBASAUR: ((DANZA_DRAGON, 5, 1000),)}
            fake._hgss_levelup_rom_path = "falsa.nds"

        fake._get_gen4_rom_profile = _registra
        fake._sync_hgss_levelup_moves(SimpleNamespace(party=[_mon()]))
        self.assertEqual(len(fake._imagen.aplicados), 1)


class RevertTests(unittest.TestCase):
    def test_al_cerrar_se_devuelve_todo_lo_escrito(self) -> None:
        fake = _fake(role="Mago")
        fake._sync_hgss_levelup_moves(SimpleNamespace(party=[_mon()]))
        fake._imagen.aplicados.clear()

        fake._revert_hgss_levelup_moves()

        self.assertEqual(fake._imagen.aplicados, [{1000: DANZA_DRAGON}])
        self.assertEqual(fake._hgss_levelup_written, {})

    def test_sin_nada_escrito_no_toca_la_memoria(self) -> None:
        fake = _fake()
        fake._revert_hgss_levelup_moves()
        self.assertEqual(fake._imagen.aplicados, [])


class HistorialTests(unittest.TestCase):
    def test_se_anota_en_el_instante_del_cruce_de_nivel(self) -> None:
        entradas = {BULBASAUR: ((DANZA_DRAGON, 5, 1000), (VOZARRON, 19, 1004))}
        fake = _fake(role="Mago", entradas=entradas)
        pokemon = _mon(level=10)
        game = SimpleNamespace(party=[pokemon])
        fake._record_hgss_levelup_move_history(game)
        pokemon.level = 20
        fake._record_hgss_levelup_move_history(game)

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
        fake._hgss_levelup_history_last_levels["1:2:3"] = 20
        pokemon = _mon(level=12)
        fake._record_hgss_levelup_move_history(SimpleNamespace(party=[pokemon]))

        historial = fake.project.oras_levelup_move_history["1:2:3"]
        self.assertEqual([item["level"] for item in historial], [5])


class HistorialCoincideConElParcheTests(unittest.TestCase):
    """Mismo bug de fondo ya corregido en los otros cinco juegos, cubierto aquí."""

    ESPECIE = 7
    A, B, C = 401, 402, 403
    ESTADO_DE_ASESINO = 349

    def _fake_con_tabla(self):
        entradas = {
            self.ESPECIE: (
                (self.ESTADO_DE_ASESINO, 5, 1000),
                (self.A, 9, 1004),
                (self.B, 12, 1008),
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
        from app.gen4_levelup_moves import compute_species_patch

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

        cruzada = (completa[0],)
        fake._append_hgss_levelup_history_entries(
            "id", SimpleNamespace(nickname="X", species="X"),
            self.ESPECIE, cruzada, "Mago", pre_capture=False,
        )
        registrado = fake.project.oras_levelup_move_history["id"][0]["move_id"]
        self.assertEqual(registrado, del_parche)

        ingenuo = compute_species_patch(
            cruzada, "Mago", species_id=self.ESPECIE, **comun,
        )[1000]
        self.assertNotEqual(
            ingenuo, del_parche,
            "el doble ya no reproduce la divergencia; la prueba perdería sentido",
        )


class CompuertaDeLaPantallaTests(unittest.TestCase):
    def test_hgss_puede_abrir_recuerda_movimientos(self) -> None:
        import inspect

        from app.ui import MELONDS_GEN4_REALTIME_GAME_KEYS

        fuente = inspect.getsource(RoleRunManager._open_oras_levelup_history)
        self.assertIn("MELONDS_GEN4_REALTIME_GAME_KEYS", fuente)
        self.assertEqual(MELONDS_GEN4_REALTIME_GAME_KEYS, {"hgss"})


if __name__ == "__main__":
    unittest.main()
