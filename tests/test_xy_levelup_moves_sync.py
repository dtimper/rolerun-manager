"""``_sync_xy_levelup_moves_mod``/``_record_xy_levelup_move_history``.

Mirror de ``tests/test_usum_levelup_moves_sync.py``/``test_sm_levelup_moves_sync.py``,
pero sin indirección por ``personal_id``: X/Y comparte el mismo motor/generación
que ORAS y su GARC de aprendizajes indexa 1:1 por ``species_id`` (confirmado
el 2026-09-05 leyendo la ROM real del usuario, ``a/2/1/4`` — especie 1
aprende Látigo Cepa a nivel 9, especie 25 aprende Nuzzle a nivel 7).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ui import RoleRunManager

BULBASAUR_ID = 1


class SyncCacheTests(unittest.TestCase):
    def _fake(self) -> SimpleNamespace:
        announcement_cache_calls: list[tuple] = []
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="xy"),
            project=SimpleNamespace(oras_levelup_move_history={}),
            project_service=SimpleNamespace(save=lambda _project: None),
            engine=SimpleNamespace(
                pools={}, damage_classes={}, speed_status_moves=set(),
                self_healing_damage_moves=set(), allowed_move_ids=None,
            ),
            # None: _ensure_xy_levelup_moves_registered ahora resincroniza
            # de inmediato tras registrar, y sin partida abierta debe
            # limitarse a saltarse esa llamada, no romper.
            current_game=None,
            _xy_levelup_moves_vanilla=b"VANILLA",
            _xy_levelup_moves_title_id=1,
            _xy_levelup_moves_azahar_root=SimpleNamespace(),
            _xy_levelup_moves_vanilla_entries={},
            _xy_levelup_moves_last_written=None,
            _xy_levelup_moves_last_roles_key=None,
            _xy_levelup_history_last_levels={},
            _effective_role=lambda pokemon: ("Mago", ""),
            _registrar_intento_vivo=lambda *a, **k: None,
            _sync_xy_levelup_announcement_cache=(
                lambda game, roles, blob: announcement_cache_calls.append((game, roles, blob))
            ),
            _announcement_cache_calls=announcement_cache_calls,
        )
        fake._xy_levelup_usable_move_ids = RoleRunManager._xy_levelup_usable_move_ids.__get__(fake)
        fake._append_xy_levelup_history_entries = (
            RoleRunManager._append_xy_levelup_history_entries.__get__(fake)
        )
        fake._purge_xy_levelup_history_above_level = (
            RoleRunManager._purge_xy_levelup_history_above_level.__get__(fake)
        )
        fake._record_xy_levelup_move_history = (
            RoleRunManager._record_xy_levelup_move_history.__get__(fake)
        )
        fake._sync_xy_levelup_moves_mod = (
            RoleRunManager._sync_xy_levelup_moves_mod.__get__(fake)
        )
        fake._sync_xy_levelup_moves_backup = (
            RoleRunManager._sync_xy_levelup_moves_backup.__get__(fake)
        )
        return fake

    def _bulbasaur(self, *, level: int = 10, pid: int = 1) -> SimpleNamespace:
        return SimpleNamespace(
            species_id=BULBASAUR_ID, level=level, pid=pid, tid=2, sid=3,
            nickname="", species="Bulbasaur",
        )

    def test_dos_sondeos_seguidos_con_los_mismos_roles_no_recalculan_el_parche(self) -> None:
        fake = self._fake()
        game = SimpleNamespace(party=[self._bulbasaur()])
        with (
            patch("app.ui.xy_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.xy_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
        self.assertEqual(build.call_count, 1)

    def test_un_cambio_de_rol_si_fuerza_recalcular(self) -> None:
        fake = self._fake()
        game = SimpleNamespace(party=[self._bulbasaur()])
        with (
            patch("app.ui.xy_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.xy_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
            fake._effective_role = lambda pokemon: ("Asesino", "")
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
        self.assertEqual(build.call_count, 2)

    def test_las_especies_del_equipo_se_indexan_directamente_por_species_id(self) -> None:
        """Sin traducción a personal_id: el mapa que recibe
        build_party_patched_blob usa el species_id tal cual -incluidas sus
        evoluciones futuras conocidas, adelantadas con el mismo rol (ver
        test_adelanta_el_mismo_rol_a_las_evoluciones_futuras)."""
        fake = self._fake()
        game = SimpleNamespace(party=[self._bulbasaur(pid=1)])
        with (
            patch("app.ui.xy_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.xy_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
        self.assertEqual(build.call_args.args[1], {BULBASAUR_ID: "Mago", 2: "Mago", 3: "Mago"})

    def test_adelanta_el_mismo_rol_a_las_evoluciones_futuras(self) -> None:
        """Bug real, 2026-09-05: Flabébé (rol ya asignado) evolucionó a
        Floette y aprendió un movimiento sin sustituir, porque la fila de
        Floette en el mod seguía vainilla -RoleRun solo se entera de la
        evolución por su propio sondeo, y ese hueco de tiempo es
        suficiente para perder la carrera-. La solución: adelantar el
        mismo parche a las evoluciones conocidas ANTES de que ocurran de
        verdad, para que no haya ninguna carrera que perder.
        """
        fake = self._fake()
        game = SimpleNamespace(party=[self._bulbasaur(pid=1)])
        with (
            patch("app.ui.xy_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.xy_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
        roles_by_species = build.call_args.args[1]
        # Ivysaur (2) y Venusaur (3): toda la cadena, no solo el siguiente escalón.
        self.assertEqual(roles_by_species.get(2), "Mago")
        self.assertEqual(roles_by_species.get(3), "Mago")

    def test_la_cache_de_anuncio_en_ram_nunca_recibe_evoluciones_adelantadas(self) -> None:
        """Bug real, 2026-09-05: el emulador crasheó justo después de que
        el parcheo de RAM del cartel tocara 8 especies -las 4 de la party
        más sus 4 evoluciones futuras adelantadas, ninguna con un búfer de
        anuncio real asignado todavía-. Buscar ese búfer para una especie
        que no existe de verdad en la party arriesga una coincidencia de
        bytes falsa en otra estructura de memoria. La cache de RAM solo
        debe recibir los roles de la party real, nunca los adelantados,
        incluso cuando lo que la dispara es un cruce de nivel real.
        """
        fake = self._fake()
        fake._xy_levelup_moves_vanilla_entries = {BULBASAUR_ID: ((22, 9, 0),)}
        pokemon = self._bulbasaur(level=5, pid=1)
        game = SimpleNamespace(party=[pokemon])
        with (
            patch("app.ui.xy_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO"),
            patch("app.ui.xy_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)  # asigna el rol, sin cruzar nivel
            pokemon.level = 10  # cruza el nivel 9
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
        self.assertEqual(len(fake._announcement_cache_calls), 1)
        _game, roles_sent_to_ram, _blob = fake._announcement_cache_calls[0]
        self.assertEqual(roles_sent_to_ram, {BULBASAUR_ID: "Mago"})

    def test_cruzar_un_nivel_dispara_la_cache_de_anuncio_aunque_el_rol_no_haya_cambiado(self) -> None:
        """Bug real, 2026-09-05: Zigzagoon, ya Mago desde antes -sin ningún
        cambio de rol en esta sesión de sondeos-, subió a nivel 11 y el
        cartel anunció "Afilar" en vez del sustituto correcto. La cache de
        RAM solo se disparaba cuando el ARCHIVO cambiaba (un cambio de
        rol); un cruce de nivel sin cambio de rol nunca la activaba. Debe
        dispararse también cuando alguien cruza un nivel de aprendizaje,
        aunque el archivo ya estuviera al día.
        """
        fake = self._fake()
        fake._xy_levelup_moves_vanilla_entries = {BULBASAUR_ID: ((22, 9, 0),)}
        pokemon = self._bulbasaur(level=5, pid=1)
        game = SimpleNamespace(party=[pokemon])
        with (
            patch("app.ui.xy_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO"),
            patch("app.ui.xy_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)  # asigna el rol, sin cruzar nivel
            self.assertEqual(len(fake._announcement_cache_calls), 0)

            pokemon.level = 10  # cruza el nivel 9, mismo rol de antes
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)

        self.assertEqual(len(fake._announcement_cache_calls), 1)
        _game, roles_sent_to_ram, blob_sent = fake._announcement_cache_calls[0]
        self.assertEqual(roles_sent_to_ram, {BULBASAUR_ID: "Mago"})
        self.assertEqual(blob_sent, b"PARCHEADO")

    def test_un_cambio_de_rol_sin_cruzar_nivel_no_dispara_la_cache_de_anuncio(self) -> None:
        """Bug real, 2026-09-05: un barrido preventivo de 5-6 especies por
        cambio de rol podía tardar 10+ segundos y, aunque ya no se pierde
        (ver ``_sync_xy_levelup_announcement_cache``, cola de espera),
        SEGUÍA retrasando 10 segundos el aviso urgente de un cruce de
        nivel real llegado justo después -encolado detrás suyo-. El
        barrido preventivo no aporta nada que el cartel vaya a mostrar
        antes de un aprendizaje real, así que no debe dispararse solo por
        cambiar de rol: el aviso urgente nunca debe tener nada delante en
        la cola.
        """
        fake = self._fake()
        game = SimpleNamespace(party=[self._bulbasaur(pid=1)])
        with (
            patch("app.ui.xy_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO"),
            patch("app.ui.xy_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
            fake._effective_role = lambda pokemon: ("Asesino", "")
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
        self.assertEqual(fake._announcement_cache_calls, [])

    def test_una_evolucion_que_ya_esta_en_el_equipo_conserva_su_propio_rol(self) -> None:
        """El adelanto nunca debe pisar el rol real de un miembro de la
        party solo porque otro miembro podría evolucionar hasta esa misma
        especie."""
        fake = self._fake()
        ivysaur = self._bulbasaur(pid=2)
        ivysaur.species_id = 2
        game = SimpleNamespace(party=[self._bulbasaur(pid=1)])
        fake._effective_role = lambda pokemon: (
            ("Mago", "") if pokemon.species_id == 1 else ("Asesino", "")
        )
        game = SimpleNamespace(party=[self._bulbasaur(pid=1), ivysaur])
        with (
            patch("app.ui.xy_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.xy_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
        roles_by_species = build.call_args.args[1]
        self.assertEqual(roles_by_species[1], "Mago")
        self.assertEqual(roles_by_species[2], "Asesino")

    def test_sin_rol_o_libero_no_restringe_el_aprendizaje(self) -> None:
        fake = self._fake()
        fake._effective_role = lambda pokemon: ("SIN ROL", "")
        game = SimpleNamespace(party=[self._bulbasaur()])
        with (
            patch("app.ui.xy_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.xy_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_xy_levelup_moves_mod(fake, game)
        self.assertEqual(build.call_args.args[1], {})

    def test_registrar_de_nuevo_el_mod_reinicia_la_cache_de_roles(self) -> None:
        """Un cambio de ROM/proceso invalida el parche calculado antes."""
        fake = self._fake()
        fake._xy_levelup_moves_last_roles_key = (frozenset({(BULBASAUR_ID, "Mago")}), False)
        fake._xy_levelup_moves_last_written = b"ALGO-DE-UNA-SESION-ANTERIOR"

        with (
            patch(
                "app.ui.load_xy_levelup_moves_blob",
                return_value=(b"VANILLA-NUEVO", 42),
            ),
            patch("app.ui.xy_levelup_moves_mod.ensure_registered", return_value="kept"),
            patch("app.ui.xy_levelup_moves_mod.parse_levelup_garc", return_value={}),
        ):
            RoleRunManager._ensure_xy_levelup_moves_registered(fake, Path("rom.3ds"), Path("azahar"), None)
        self.assertIsNone(fake._xy_levelup_moves_last_roles_key)
        self.assertIsNone(fake._xy_levelup_moves_last_written)
        self.assertEqual(fake._xy_levelup_moves_vanilla, b"VANILLA-NUEVO")
        self.assertEqual(fake._xy_levelup_moves_title_id, 42)

    def test_registrar_de_nuevo_resincroniza_de_inmediato_con_la_partida_abierta(self) -> None:
        """Bug real, 2026-09-05: cada reenganche de la conexión deja el mod
        en vainilla (registrar_de_nuevo lo confirma arriba). Antes, nadie
        volvía a parchearlo hasta el siguiente sondeo o cambio de rol —
        Pidgey cruzó un nivel entero justo en ese hueco y aprendió el
        movimiento vainilla sin sustituir. Registrar debe dejar el archivo
        ya correcto para la partida abierta, sin esperar a nadie más.
        """
        fake = self._fake()
        fake.current_game = SimpleNamespace(party=[self._bulbasaur(pid=1)])

        with (
            patch(
                "app.ui.load_xy_levelup_moves_blob",
                return_value=(b"VANILLA-NUEVO", 42),
            ),
            patch("app.ui.xy_levelup_moves_mod.ensure_registered", return_value="kept"),
            patch("app.ui.xy_levelup_moves_mod.parse_levelup_garc", return_value={}),
            patch("app.ui.xy_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.xy_levelup_moves_mod.write_blob") as write,
        ):
            RoleRunManager._ensure_xy_levelup_moves_registered(fake, Path("rom.3ds"), Path("azahar"), None)

        build.assert_called_once()
        write.assert_called_once()
        self.assertEqual(fake._xy_levelup_moves_last_written, b"PARCHEADO")


class HistoryTests(unittest.TestCase):
    def _fake(self) -> SimpleNamespace:
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="xy"),
            project=SimpleNamespace(oras_levelup_move_history={}),
            project_service=SimpleNamespace(save=lambda _project: None),
            engine=SimpleNamespace(
                pools={}, damage_classes={}, speed_status_moves=set(),
                self_healing_damage_moves=set(), allowed_move_ids=None,
            ),
            _xy_levelup_moves_vanilla_entries={
                BULBASAUR_ID: ((22, 9, 0), (75, 19, 4)),
            },
            _xy_levelup_history_last_levels={},
            _effective_role=lambda pokemon: ("Mago", ""),
            _registrar_intento_vivo=lambda *a, **k: None,
        )
        fake._xy_levelup_usable_move_ids = RoleRunManager._xy_levelup_usable_move_ids.__get__(fake)
        fake._append_xy_levelup_history_entries = (
            RoleRunManager._append_xy_levelup_history_entries.__get__(fake)
        )
        fake._purge_xy_levelup_history_above_level = (
            RoleRunManager._purge_xy_levelup_history_above_level.__get__(fake)
        )
        fake._record_xy_levelup_move_history = (
            RoleRunManager._record_xy_levelup_move_history.__get__(fake)
        )
        return fake

    def test_se_registra_en_el_instante_del_cruce_de_nivel(self) -> None:
        fake = self._fake()
        pokemon = SimpleNamespace(
            species_id=BULBASAUR_ID, level=10, pid=1, tid=2, sid=3,
            nickname="Bulba", species="Bulbasaur",
        )
        game = SimpleNamespace(party=[pokemon])
        fake._xy_levelup_history_last_levels["1:2:3"] = 10
        pokemon.level = 20  # cruza el nivel 19 (Látigo Cepa)
        fake._record_xy_levelup_move_history(game)

        historial = fake.project.oras_levelup_move_history["1:2:3"]
        self.assertEqual(len(historial), 1)
        self.assertEqual(historial[0]["level"], 19)
        self.assertFalse(historial[0]["pre_capture"])

    def test_una_partida_reiniciada_sin_guardar_descarta_lo_aprendido_por_encima(self) -> None:
        fake = self._fake()
        pokemon = SimpleNamespace(
            species_id=BULBASAUR_ID, level=20, pid=1, tid=2, sid=3,
            nickname="Bulba", species="Bulbasaur",
        )
        game = SimpleNamespace(party=[pokemon])
        fake._xy_levelup_history_last_levels["1:2:3"] = 20
        fake.project.oras_levelup_move_history["1:2:3"] = [
            {"level": 9, "move_id": 22}, {"level": 19, "move_id": 75},
        ]
        pokemon.level = 12  # bajó de 20 a 12: nunca llegó a guardarse
        fake._record_xy_levelup_move_history(game)

        historial = fake.project.oras_levelup_move_history["1:2:3"]
        self.assertEqual([entry["level"] for entry in historial], [9])


if __name__ == "__main__":
    unittest.main()
