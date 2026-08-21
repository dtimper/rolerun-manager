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



if __name__ == "__main__":
    unittest.main()

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
