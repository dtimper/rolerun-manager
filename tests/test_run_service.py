from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.run_service import RunProjectService


class RunProjectServiceTests(unittest.TestCase):
    def test_force_new_preserves_an_older_run_with_the_same_game_and_trainer(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            first = service.open_or_create("AS", "Timper", save)
            first.counters["vidas"] = 3
            service.save(first)

            second = service.open_or_create("AS", "Timper", save, force_new=True)
            reloaded_first = service.load(first.slug)

            self.assertNotEqual(first.slug, second.slug)
            self.assertTrue(second.slug.endswith("-run-2"))
            self.assertIsNotNone(reloaded_first)
            assert reloaded_first is not None
            self.assertEqual(reloaded_first.counters["vidas"], 3)
            self.assertEqual(second.counters["vidas"], 0)

    def test_detected_faint_decrements_life_once_and_persists_until_resolved(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            project.counters["vidas"] = 3
            service.save(project)

            event = {
                "identity": "261:1:2:3", "pokemon": "Chompo", "species": "Granbull",
                "slot": 2, "role": "Tanque",
            }
            self.assertTrue(service.register_detected_faint(project, event))
            self.assertFalse(service.register_detected_faint(project, event))
            self.assertEqual(project.counters["vidas"], 2)
            self.assertEqual(len(project.pending_faints), 1)

            self.assertTrue(service.resolve_detected_faint(
                project, "261:1:2:3", box=31, box_slot=1, substitute="Rickyeit",
            ))
            reloaded = service.load(project.slug)
            assert reloaded is not None
            self.assertEqual(reloaded.pending_faints, [])
            self.assertIn("261:1:2:3", reloaded.graveyard_pokemon)
            self.assertEqual(reloaded.counters["vidas"], 2)

    def test_faint_picker_waits_for_two_overworld_samples_after_observed_battle(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            project.counters["vidas"] = 3
            service.save(project)
            event = {
                "identity": "398:1:2:3", "pokemon": "Ornita", "species": "Staraptor",
                "slot": 1, "role": "Líbero",
            }
            self.assertTrue(service.register_detected_faint(project, event))
            pending = project.pending_faints[0]

            self.assertFalse(service.update_detected_faint_battle_state(project, event["identity"], in_battle=True))
            self.assertTrue(pending["battle_seen"])
            self.assertEqual(pending["battle_exit_samples"], 0)
            self.assertFalse(service.update_detected_faint_battle_state(project, event["identity"], in_battle=False))
            self.assertEqual(pending["battle_exit_samples"], 1)
            self.assertTrue(service.update_detected_faint_battle_state(project, event["identity"], in_battle=False))
            self.assertTrue(pending["battle_ended"])
            self.assertFalse(pending.get("battle_ended_inferred", False))

    def test_faint_picker_can_infer_battle_end_when_hp_zero_is_first_seen_in_overworld(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            event = {
                "identity": "398:1:2:3", "pokemon": "Ornita", "species": "Staraptor",
                "slot": 1, "role": "Líbero",
            }
            self.assertTrue(service.register_detected_faint(project, event))
            pending = project.pending_faints[0]

            # En la sesión real de ORAS el 0 HP puede hacerse visible en la copia
            # de party cuando ya hemos vuelto al overworld. Dos muestras estables
            # fuera de batalla deben abrir entonces la compuerta sin exigir una
            # muestra histórica de batalla que ya no podemos recuperar.
            self.assertFalse(service.update_detected_faint_battle_state(project, event["identity"], in_battle=False))
            self.assertFalse(pending["battle_seen"])
            self.assertEqual(pending["battle_exit_samples"], 1)
            self.assertTrue(service.update_detected_faint_battle_state(project, event["identity"], in_battle=False))
            self.assertTrue(pending["battle_ended"])
            self.assertTrue(pending.get("battle_ended_inferred", False))

    def test_faint_prompt_is_persisted_as_one_shot_and_external_swap_resolves_it(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            project.counters["vidas"] = 3
            service.save(project)

            event = {
                "identity": "261:1:2:3", "pokemon": "Chompo", "species": "Granbull",
                "slot": 2, "role": "Tanque",
            }
            self.assertTrue(service.register_detected_faint(project, event))
            self.assertFalse(project.pending_faints[0]["prompt_shown"])
            self.assertTrue(service.mark_detected_faint_prompt_shown(project, "261:1:2:3"))

            reloaded = service.load(project.slug)
            assert reloaded is not None
            self.assertTrue(reloaded.pending_faints[0]["prompt_shown"])
            self.assertEqual(reloaded.counters["vidas"], 2)

            self.assertTrue(service.resolve_detected_faint_external(reloaded, "261:1:2:3"))
            final = service.load(project.slug)
            assert final is not None
            self.assertEqual(final.pending_faints, [])
            self.assertIn("261:1:2:3", final.graveyard_pokemon)
            self.assertEqual(final.counters["vidas"], 2)

    def test_declining_replacement_keeps_death_and_life_but_clears_reminder(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("X", "Timper", save)
            project.counters["vidas"] = 3
            service.save(project)
            event = {
                "identity": "664:1:2:3", "pokemon": "Scatterbug",
                "species": "Scatterbug", "slot": 2, "role": "Tanque",
                "source_label": "X/Y en vivo",
            }
            self.assertTrue(service.register_detected_faint(project, event))
            self.assertEqual(project.counters["vidas"], 2)

            self.assertTrue(service.decline_detected_faint_replacement(project, event["identity"]))

            reloaded = service.load(project.slug)
            assert reloaded is not None
            self.assertEqual(reloaded.pending_faints, [])
            self.assertEqual(reloaded.counters["vidas"], 2)
            self.assertIn(event["identity"], reloaded.graveyard_pokemon)
            history = service.history(reloaded)
            self.assertEqual(history[-1]["type"], "pokemon_faint_replacement_declined")
            self.assertEqual(history[-1]["reason"], "sustitución descartada por el usuario")

    def test_six_mon_battle_without_deaths_grants_a_life_and_a_draft(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            project.counters["vidas"] = 3
            project.counters["drafteos"] = 0
            service.save(project)

            service.note_trainer_battle_seen(project, opponent_team_size=6)
            # Un tick repetido con el mismo tamaño de roster no reinicia nada.
            service.note_trainer_battle_seen(project, opponent_team_size=6)
            self.assertTrue(project.six_mon_battle_active)

            outcome = service.resolve_six_mon_battle_end(project)
            assert outcome is not None
            self.assertEqual(outcome["deaths"], 0)
            self.assertEqual(outcome["vidas"], 4)
            self.assertEqual(outcome["drafteos"], 1)
            self.assertEqual(project.counters["vidas"], 4)
            self.assertEqual(project.counters["drafteos"], 1)
            self.assertFalse(project.six_mon_battle_active)

            reloaded = service.load(project.slug)
            assert reloaded is not None
            self.assertEqual(reloaded.counters["vidas"], 4)
            self.assertEqual(reloaded.counters["drafteos"], 1)

    def test_six_mon_battle_via_accumulated_opponents_without_deaths(self) -> None:
        # Vía X/Y (14-09-2026): el puntero de rival sí sigue las sustituciones
        # reales, así que hay que acumular cada rival distinto conforme sale,
        # a diferencia de ORAS (`note_trainer_battle_seen`, que ya conoce el
        # tamaño del roster desde el primer instante).
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("X", "Timper", save)
            project.counters["vidas"] = 3
            project.counters["drafteos"] = 0
            service.save(project)

            for species_id in range(1, 7):
                service.note_trainer_battle_opponent_seen(project, species_id, instance_key=species_id * 111)
            # Un rival repetido (misma especie+instancia) no cuenta dos veces.
            service.note_trainer_battle_opponent_seen(project, 1, instance_key=111)
            self.assertEqual(len(project.six_mon_battle_opponents), 6)

            outcome = service.resolve_six_mon_battle_end(project)
            assert outcome is not None
            self.assertEqual(outcome["deaths"], 0)
            self.assertEqual(outcome["vidas"], 4)
            self.assertEqual(outcome["drafteos"], 1)
            self.assertFalse(project.six_mon_battle_active)
            self.assertEqual(project.six_mon_battle_opponents, [])

    def test_accumulated_battle_with_fewer_than_six_opponents_grants_nothing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("X", "Timper", save)
            project.counters["vidas"] = 3
            project.counters["drafteos"] = 0
            service.save(project)

            for species_id in range(1, 4):
                service.note_trainer_battle_opponent_seen(project, species_id, instance_key=1)

            self.assertIsNone(service.resolve_six_mon_battle_end(project))
            self.assertEqual(project.counters["vidas"], 3)
            self.assertEqual(project.counters["drafteos"], 0)
            self.assertFalse(project.six_mon_battle_active)

    def test_six_mon_battle_with_a_death_only_grants_a_draft(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            project.counters["vidas"] = 3
            project.counters["drafteos"] = 0
            service.save(project)

            service.note_trainer_battle_seen(project, opponent_team_size=6)
            event = {
                "identity": "261:1:2:3", "pokemon": "Chompo", "species": "Granbull",
                "slot": 2, "role": "Tanque",
            }
            self.assertTrue(service.register_detected_faint(project, event))
            # La vida ya se descontó al detectar la baja, no al cerrar el combate.
            self.assertEqual(project.counters["vidas"], 2)

            outcome = service.resolve_six_mon_battle_end(project)
            assert outcome is not None
            self.assertEqual(outcome["deaths"], 1)
            self.assertIsNone(outcome["vidas"])
            self.assertEqual(outcome["drafteos"], 1)
            # Ninguna vida extra por haber perdido un Pokémon en este combate.
            self.assertEqual(project.counters["vidas"], 2)
            self.assertEqual(project.counters["drafteos"], 1)

    def test_a_smaller_trainer_roster_never_starts_tracking(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            project.counters["vidas"] = 3
            project.counters["drafteos"] = 0
            service.save(project)

            service.note_trainer_battle_seen(project, opponent_team_size=3)
            self.assertFalse(project.six_mon_battle_active)

            self.assertIsNone(service.resolve_six_mon_battle_end(project))
            self.assertEqual(project.counters["vidas"], 3)
            self.assertEqual(project.counters["drafteos"], 0)

    def test_an_unknown_roster_size_never_starts_tracking(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            service.note_trainer_battle_seen(project, opponent_team_size=None)
            self.assertFalse(project.six_mon_battle_active)

    def test_resolving_without_an_active_battle_is_a_noop(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            self.assertIsNone(service.resolve_six_mon_battle_end(project))



if __name__ == "__main__":
    unittest.main()

class RunProjectControllerHotkeyBackfillTests(unittest.TestCase):
    """Una Run guardada antes del 31-08-2026 recibe "open_full_app" sola.

    ``raw.setdefault("controller_hotkeys", {"floating_menu": "guide"})`` no
    tocaba una Run que YA tenía ``controller_hotkeys`` (aunque le faltara la
    acción nueva): setdefault del diccionario completo no entra si la clave
    ya existe. El backfill tiene que ser por CLAVE dentro del diccionario.
    """

    def test_una_run_vieja_recibe_open_full_app_sin_perder_su_boton_personalizado(self) -> None:
        import json

        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)

            # Simula una Run guardada ANTES de que "open_full_app" existiera,
            # con el botón de "floating_menu" ya personalizado por el usuario.
            config_path = root / "Runs" / project.slug / "config.json"
            raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
            raw["controller_hotkeys"] = {"floating_menu": "start"}
            config_path.write_text(json.dumps(raw), encoding="utf-8")

            reloaded = service.load(project.slug)

            assert reloaded is not None
            self.assertEqual(reloaded.controller_hotkeys["floating_menu"], "start")
            self.assertEqual(reloaded.controller_hotkeys["open_full_app"], "back")


class RunProjectGlobalHotkeySettingsTests(unittest.TestCase):
    """Pedido del usuario 14-09-2026: los atajos deben ser los mismos en todas
    las Runs, no un ajuste independiente por juego."""

    def test_changing_a_hotkey_in_one_run_propagates_to_a_run_created_afterwards(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            first = service.open_or_create("AS", "Timper", save)

            new_hotkeys = dict(first.hotkeys)
            new_hotkeys["vidas_mas"] = "num 9"
            service.set_hotkeys(first, new_hotkeys)

            second = service.open_or_create("X", "Timper", save)
            self.assertEqual(second.hotkeys["vidas_mas"], "num 9")

    def test_changing_a_hotkey_propagates_to_an_already_existing_run_on_reload(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            first = service.open_or_create("AS", "Timper", save)
            second = service.open_or_create("X", "Timper", save)

            new_hotkeys = dict(first.hotkeys)
            new_hotkeys["drafteos_mas"] = "f9"
            service.set_hotkeys(first, new_hotkeys)

            reloaded_second = service.load(second.slug)
            assert reloaded_second is not None
            self.assertEqual(reloaded_second.hotkeys["drafteos_mas"], "f9")

    def test_first_run_opened_seeds_the_shared_settings_instead_of_losing_a_customization(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            first = service.open_or_create("AS", "Timper", save)
            first.hotkeys["heal_party"] = "f6"
            service.save(first)
            # Sin llamar a set_hotkeys todavía: nada compartido existe aún.
            self.assertFalse((root / "global_settings.json").exists())

            reloaded_first = service.load(first.slug)
            assert reloaded_first is not None
            second = service.open_or_create("X", "Timper", save)

            self.assertEqual(reloaded_first.hotkeys["heal_party"], "f6")
            self.assertEqual(second.hotkeys["heal_party"], "f6")

    def test_controller_hotkeys_and_menu_controls_are_also_shared(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            first = service.open_or_create("AS", "Timper", save)

            service.set_controller_hotkeys(first, {**first.controller_hotkeys, "floating_menu": "x"})
            service.set_menu_controls(first, {"accept": "e", "back": "q"}, {"accept": "y", "back": "b"})

            second = service.open_or_create("X", "Timper", save)
            self.assertEqual(second.controller_hotkeys["floating_menu"], "x")
            self.assertEqual(second.menu_keys, {"accept": "e", "back": "q"})
            self.assertEqual(second.controller_menu_buttons, {"accept": "y", "back": "b"})

    def test_list_projects_also_applies_the_shared_hotkeys(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            first = service.open_or_create("AS", "Timper", save)
            service.open_or_create("X", "Timper", save)

            new_hotkeys = dict(first.hotkeys)
            new_hotkeys["sync_live_game"] = "f6"
            service.set_hotkeys(first, new_hotkeys)

            listed = {project.slug: project for project in service.list_projects()}
            self.assertEqual(listed[first.slug].hotkeys["sync_live_game"], "f6")


class RunProjectFaintRearmTests(unittest.TestCase):
    def test_graveyard_history_does_not_block_a_later_real_faint_occurrence(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            project.counters["vidas"] = 4
            service.save(project)
            event = {
                "identity": "261:1:2:3", "pokemon": "Chompo", "species": "Granbull",
                "slot": 2, "role": "Support", "detected_source": "overworld",
            }
            self.assertTrue(service.register_detected_faint(project, event))
            self.assertTrue(service.resolve_detected_faint(
                project, event["identity"], box=4, box_slot=1, substitute="Golem",
            ))
            self.assertIn(event["identity"], project.graveyard_pokemon)

            # Si una carga de estado/prueba devuelve físicamente ese Pokémon vivo
            # al equipo, una nueva transición PS>0→0 debe volver a poder registrarse.
            self.assertTrue(service.register_detected_faint(project, event))
            self.assertEqual(project.counters["vidas"], 2)
            self.assertEqual(len(project.pending_faints), 1)

    def test_old_shown_pending_faint_can_be_rearmed_after_alive_reappearance(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            save.write_bytes(b"save")
            service = RunProjectService(root / "Runs", root / "OBS")
            project = service.open_or_create("AS", "Timper", save)
            project.counters["vidas"] = 3
            service.save(project)
            event = {
                "identity": "398:1:2:3", "pokemon": "Ornita", "species": "Staraptor",
                "slot": 1, "role": "Líbero", "detected_source": "overworld",
            }
            self.assertTrue(service.register_detected_faint(project, event))
            self.assertTrue(service.mark_detected_faint_prompt_shown(project, event["identity"]))
            self.assertTrue(service.clear_stale_detected_faint_for_alive_party(project, event["identity"]))
            self.assertEqual(project.pending_faints, [])

            self.assertTrue(service.register_detected_faint(project, event))
            self.assertEqual(project.counters["vidas"], 1)
            self.assertEqual(len(project.pending_faints), 1)
