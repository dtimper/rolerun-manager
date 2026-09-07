"""Recuerda-movimientos de ORAS: qué ha aprendido de verdad cada Pokémon por nivel.

Pedido por el usuario el 2026-09-03, justo después de confirmar que los roles
ya aprenden movimientos coherentes: quería una pantalla que mostrara todos los
ataques que un Pokémon ha intentado aprender en el pasado. Decisiones tomadas
con el usuario: se guarda solo el movimiento ya ajustado al rol (el que de
verdad se ofreció, no el vainilla), solo para ORAS por ahora, y se identifica
al Pokémon por PID/TID/SID —sin la especie— para que sobreviva a una
evolución.
"""

from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app import oras_levelup_moves as mod
from app.ui import RoleRunManager

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

THUNDER, EARTHQUAKE = 87, 89


def _make_levelup_garc(species_entries: dict[int, list[tuple[int, int]]], count: int = 722) -> bytes:
    records: list[bytes] = []
    for species_id in range(count):
        pairs = species_entries.get(species_id, [])
        body = b"".join(struct.pack("<hh", move, level) for move, level in pairs)
        body += struct.pack("<hh", -1, -1)
        records.append(body)
    garc_header_size = 0x1C
    fato_size = 12 + count * 4
    fatb_size = 12 + count * 16
    fimb_size = 12
    data_offset = garc_header_size + fato_size + fatb_size + fimb_size
    data = b"".join(records)
    blob = bytearray(data_offset + len(data))
    blob[:4] = b"GARC"
    struct.pack_into("<IHHIII", blob, 4, garc_header_size, 0xFEFF, 0x0400, 4, data_offset, len(blob))
    pos = garc_header_size
    blob[pos:pos + 4] = b"FATO"
    struct.pack_into("<IHH", blob, pos + 4, fato_size, count, 0)
    pos += fato_size
    blob[pos:pos + 4] = b"FATB"
    struct.pack_into("<II", blob, pos + 4, fatb_size, count)
    pos += 12
    running = 0
    for record in records:
        start = running
        end = start + len(record)
        struct.pack_into("<IIII", blob, pos, 1, start, end, len(record))
        pos += 16
        running = end
    blob[pos:pos + 4] = b"FIMB"
    struct.pack_into("<II", blob, pos + 4, fimb_size, len(data))
    blob[data_offset:data_offset + len(data)] = data
    return bytes(blob)


class RecordHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pools = json.loads((DATA / "moves.json").read_text(encoding="utf-8-sig"))
        metadata = json.loads((DATA / "move_rules_metadata.json").read_text(encoding="utf-8-sig"))
        cls.damage_classes = {int(k): str(v) for k, v in metadata["damage_classes"].items()}
        cls.speed_status_moves = {int(v) for v in metadata["speed_status_moves"]}
        cls.self_healing_damage_moves = {int(v) for v in metadata["self_healing_damage_moves"]}

    def _fake(self, *, project=None, last_levels=None) -> SimpleNamespace:
        vanilla = _make_levelup_garc({229: [(THUNDER, 4), (EARTHQUAKE, 8)]})
        entries = mod.parse_levelup_garc(vanilla)
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="oras"),
            project=project if project is not None else SimpleNamespace(oras_levelup_move_history={}),
            project_service=SimpleNamespace(save=lambda _project: None),
            engine=SimpleNamespace(
                pools=self.pools, damage_classes=self.damage_classes,
                speed_status_moves=self.speed_status_moves,
                self_healing_damage_moves=self.self_healing_damage_moves,
                allowed_move_ids=None,
            ),
            _oras_levelup_moves_vanilla_entries=entries,
            _oras_levelup_history_last_levels=dict(last_levels or {}),
            _effective_role=lambda pokemon: ("Mago", ""),
            _registrar_intento_vivo=lambda *a, **k: None,
        )
        # Estos dos son métodos reales de RoleRunManager llamados vía
        # ``self.`` desde _record_oras_levelup_move_history; hay que
        # enlazarlos al fake para que se resuelvan, igual que si fuera una
        # instancia real.
        fake._oras_levelup_usable_move_ids = RoleRunManager._oras_levelup_usable_move_ids.__get__(fake)
        fake._append_oras_levelup_history_entries = RoleRunManager._append_oras_levelup_history_entries.__get__(fake)
        fake._purge_oras_levelup_history_above_level = (
            RoleRunManager._purge_oras_levelup_history_above_level.__get__(fake)
        )
        return fake

    def _houndoom(self, level: int) -> SimpleNamespace:
        return SimpleNamespace(
            species_id=229, level=level, pid=111, tid=222, sid=333,
            nickname="", species="Houndoom",
        )

    def test_la_primera_vez_que_ve_un_pokemon_solo_fija_la_base(self) -> None:
        fake = self._fake()
        game = SimpleNamespace(party=[self._houndoom(2)])
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        self.assertEqual(fake.project.oras_levelup_move_history, {})
        self.assertEqual(fake._oras_levelup_history_last_levels["111:222:333"], 2)

    def test_ver_por_primera_vez_a_un_pokemon_ya_crecido_retro_rellena_sin_rol(self) -> None:
        """Pedido por el usuario el 2026-09-03: los movimientos de antes de ser gestionado.

        La primera vez que RoleRun ve a un Pokémon EN TODA LA RUN (no solo
        esta sesión) y ya viene con nivel, se asume que aprendió sus
        movimientos vainilla sin ningún rol —tal como el juego se los habría
        dado— hasta ese nivel. Sirven de punto de partida para el
        recuerda-movimientos; la pantalla decide luego si "ENSEÑAR" tiene
        sentido comparando contra el rol actual.
        """
        fake = self._fake()  # sin last_levels: primera vez esta sesión
        game = SimpleNamespace(party=[self._houndoom(10)])  # ya pasó los niveles 4 y 8
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        history = fake.project.oras_levelup_move_history["111:222:333"]
        self.assertEqual({(item["level"], item["move_id"]) for item in history}, {(4, THUNDER), (8, EARTHQUAKE)})
        self.assertTrue(all(item["role"] == "SIN ROL" for item in history))
        self.assertTrue(all(item["pre_capture"] for item in history))

    def test_el_retro_relleno_solo_pasa_una_vez_en_toda_la_run(self) -> None:
        """Si ya hay historial persistido, una sesión nueva no debe re-rellenar."""
        project = SimpleNamespace(oras_levelup_move_history={
            "111:222:333": [{"level": 4, "move_id": THUNDER, "role": "SIN ROL",
                              "species_id": 229, "nickname": "Houndoom",
                              "recorded_at": "", "pre_capture": True}],
        })
        fake = self._fake(project=project)  # sesión nueva: last_levels vacío
        game = SimpleNamespace(party=[self._houndoom(10)])
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        # Solo la entrada que ya existía: no se duplica ni se añade la de
        # nivel 8 por una "primera vez" que en realidad no lo es.
        self.assertEqual(len(fake.project.oras_levelup_move_history["111:222:333"]), 1)

    def test_subir_de_nivel_registra_el_movimiento_ya_ajustado_al_rol(self) -> None:
        fake = self._fake(last_levels={"111:222:333": 2})
        game = SimpleNamespace(party=[self._houndoom(5)])
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        history = fake.project.oras_levelup_move_history["111:222:333"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["level"], 4)
        # Mago exige daño especial: Trueno (especial) se queda, no se sustituye.
        self.assertEqual(history[0]["move_id"], THUNDER)
        self.assertEqual(history[0]["role"], "Mago")

    def test_subir_varios_niveles_de_golpe_registra_cada_entrada_cruzada(self) -> None:
        fake = self._fake(last_levels={"111:222:333": 2})
        game = SimpleNamespace(party=[self._houndoom(9)])
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        history = fake.project.oras_levelup_move_history["111:222:333"]
        self.assertEqual({item["level"] for item in history}, {4, 8})

    def test_reiniciar_sin_guardar_y_repetir_con_otro_rol_no_duplica_pero_anade_lo_distinto(self) -> None:
        fake = self._fake(last_levels={"111:222:333": 2})
        game = SimpleNamespace(party=[self._houndoom(5)])
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        primer_conteo = len(fake.project.oras_levelup_move_history["111:222:333"])

        # Reinicio sin guardar: el nivel vuelve a 2 en la lectura siguiente.
        fake._oras_levelup_history_last_levels["111:222:333"] = 2
        # Con el mismo rol y el mismo nivel, no debe duplicar la entrada.
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        self.assertEqual(len(fake.project.oras_levelup_move_history["111:222:333"]), primer_conteo)

        # Ahora con un rol que sustituye distinto: Asesino exige físico, así
        # que Trueno (especial) se cambia por otra cosa.
        fake._oras_levelup_history_last_levels["111:222:333"] = 2
        fake._effective_role = lambda pokemon: ("Asesino", "")
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        history = fake.project.oras_levelup_move_history["111:222:333"]
        self.assertGreater(len(history), primer_conteo)
        nivel_4 = [item for item in history if item["level"] == 4]
        self.assertEqual({item["role"] for item in nivel_4}, {"Mago", "Asesino"})

    def test_bajar_de_nivel_no_registra_nada_solo_baja_la_base(self) -> None:
        fake = self._fake(last_levels={"111:222:333": 9})
        game = SimpleNamespace(party=[self._houndoom(5)])
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        self.assertEqual(fake.project.oras_levelup_move_history, {})
        self.assertEqual(fake._oras_levelup_history_last_levels["111:222:333"], 5)

    def test_reiniciar_sin_guardar_dentro_de_la_sesion_descarta_lo_de_por_encima(self) -> None:
        """Pedido por el usuario el 2026-09-03 tras probarlo con Scyther a nivel 70.

        Si el Pokémon subió de nivel en RAM sin guardar y la partida se
        reinicia, el nivel real vuelve a bajar. Lo que se había registrado
        por encima de ese nivel nunca llegó a persistir en el juego, así que
        no puede seguir ofreciéndose como ENSEÑAR.
        """
        project = SimpleNamespace(oras_levelup_move_history={
            "111:222:333": [
                {"level": 4, "move_id": THUNDER, "role": "Mago", "species_id": 229,
                 "nickname": "Houndoom", "recorded_at": "", "pre_capture": False},
                {"level": 8, "move_id": EARTHQUAKE, "role": "Mago", "species_id": 229,
                 "nickname": "Houndoom", "recorded_at": "", "pre_capture": False},
            ],
        })
        fake = self._fake(project=project, last_levels={"111:222:333": 9})
        game = SimpleNamespace(party=[self._houndoom(5)])
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        history = fake.project.oras_levelup_move_history["111:222:333"]
        self.assertEqual({item["level"] for item in history}, {4})
        self.assertEqual(fake._oras_levelup_history_last_levels["111:222:333"], 5)

    def test_reiniciar_sin_guardar_entre_sesiones_tambien_descarta_lo_de_por_encima(self) -> None:
        """Mismo caso pero detectado al reabrir RoleRun, no dentro de la misma sesión.

        ``_oras_levelup_history_last_levels`` no sobrevive a cerrar y volver
        a abrir RoleRun, así que ``previous`` llega vacío aunque el
        historial persistido en la Run ya tuviera niveles más altos.
        """
        project = SimpleNamespace(oras_levelup_move_history={
            "111:222:333": [
                {"level": 4, "move_id": THUNDER, "role": "Mago", "species_id": 229,
                 "nickname": "Houndoom", "recorded_at": "", "pre_capture": False},
                {"level": 8, "move_id": EARTHQUAKE, "role": "Mago", "species_id": 229,
                 "nickname": "Houndoom", "recorded_at": "", "pre_capture": False},
            ],
        })
        fake = self._fake(project=project)  # sesión nueva: last_levels vacío
        game = SimpleNamespace(party=[self._houndoom(5)])
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        history = fake.project.oras_levelup_move_history["111:222:333"]
        self.assertEqual({item["level"] for item in history}, {4})

    def test_no_ora_no_hace_nada(self) -> None:
        fake = self._fake(last_levels={"111:222:333": 2})
        fake.save_engine = SimpleNamespace(key="bdsp")
        game = SimpleNamespace(party=[self._houndoom(5)])
        RoleRunManager._record_oras_levelup_move_history(fake, game)
        self.assertEqual(fake.project.oras_levelup_move_history, {})


class NavigationWiringTests(unittest.TestCase):
    """El recuerda-movimientos vive dentro de MOVIMIENTOS, no en una pestaña propia.

    Rediseño del usuario del 2026-09-03: sustituye a la pantalla independiente
    que se había construido antes, con un botón por Pokémon en la vista de
    equipo de MOVIMIENTOS que abre un popover con su historial.
    """

    def test_global_tm_view_recibe_el_enganche_del_recuerda_movimientos(self) -> None:
        import inspect

        fuente = inspect.getsource(RoleRunManager._render_global_tm_page)
        assert "on_open_levelup_history=self._open_oras_levelup_history" in fuente

    def test_abrir_el_recuerda_movimientos_usa_el_componente_dedicado(self) -> None:
        import inspect

        fuente = inspect.getsource(RoleRunManager._open_oras_levelup_history)
        assert "LevelupMoveHistoryPopover(" in fuente


class OpenPopoverDisplayEntriesTests(unittest.TestCase):
    """Lo que ve el usuario en la ventana: ya-lo-conoce, motivo concreto y descripción.

    Pedido por el usuario el 2026-09-03, después de ver el popover en vivo:
    un movimiento que el Pokémon ya tiene en su set no debe poder elegirse
    para enseñar, y el botón deshabilitado debe explicar el motivo concreto
    en vez de un genérico "no compatible".
    """

    def _fake(self) -> SimpleNamespace:
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="oras"),
            project=SimpleNamespace(oras_levelup_move_history={
                "111:222:333": [
                    {"level": 4, "move_id": THUNDER, "role": "Mago",
                     "species_id": 229, "nickname": "Houndoom",
                     "recorded_at": "", "pre_capture": False},
                    {"level": 8, "move_id": EARTHQUAKE, "role": "Mago",
                     "species_id": 229, "nickname": "Houndoom",
                     "recorded_at": "", "pre_capture": False},
                ],
            }),
            engine=SimpleNamespace(move=lambda move_id: {"name_es": f"Movimiento {move_id}"}),
            content=SimpleNamespace(),
            _levelup_history_popover=None,
            _effective_role=lambda pokemon: ("Mago", ""),
            _effective_moves_for_review=lambda pokemon: (["Trueno", "—", "—", "—"], [THUNDER, 0, 0, 0]),
            _draft_move_metadata=lambda move_id: {
                "category": "special" if move_id == THUNDER else "physical",
                "power": 90, "accuracy": 100, "pp": 15, "type_id": 12,
                "description": f"Descripción de {move_id}.",
            },
            _move_browser_role_compatibility=lambda role, move_id: (
                (True, "Compatible") if move_id == THUNDER
                else (False, "Motivo concreto de incompatibilidad")
            ),
        )
        return fake

    def _scyther(self) -> SimpleNamespace:
        return SimpleNamespace(pid=111, tid=222, sid=333, nickname="", species="Scyther")

    def test_un_movimiento_ya_conocido_no_se_puede_volver_a_elegir(self) -> None:
        from unittest.mock import patch

        fake = self._fake()
        with patch("app.ui.LevelupMoveHistoryPopover") as popover_cls:
            RoleRunManager._open_oras_levelup_history(fake, self._scyther())
            entries = popover_cls.call_args.args[3]
        by_move = {entry["move_id"]: entry for entry in entries}
        self.assertTrue(by_move[THUNDER]["already_known"])
        self.assertFalse(by_move[THUNDER]["teachable"])

    def test_un_movimiento_incompatible_lleva_su_motivo_concreto(self) -> None:
        from unittest.mock import patch

        fake = self._fake()
        with patch("app.ui.LevelupMoveHistoryPopover") as popover_cls:
            RoleRunManager._open_oras_levelup_history(fake, self._scyther())
            entries = popover_cls.call_args.args[3]
        by_move = {entry["move_id"]: entry for entry in entries}
        self.assertFalse(by_move[EARTHQUAKE]["already_known"])
        self.assertFalse(by_move[EARTHQUAKE]["teachable"])
        self.assertEqual(by_move[EARTHQUAKE]["reason"], "Motivo concreto de incompatibilidad")

    def test_la_descripcion_del_movimiento_llega_a_la_tarjeta(self) -> None:
        from unittest.mock import patch

        fake = self._fake()
        with patch("app.ui.LevelupMoveHistoryPopover") as popover_cls:
            RoleRunManager._open_oras_levelup_history(fake, self._scyther())
            entries = popover_cls.call_args.args[3]
        by_move = {entry["move_id"]: entry for entry in entries}
        self.assertEqual(by_move[THUNDER]["description"], f"Descripción de {THUNDER}.")


if __name__ == "__main__":
    unittest.main()
