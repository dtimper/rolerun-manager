from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

with patch("pathlib.Path.home", return_value=Path(tempfile.gettempdir()) / "rolerun-tests"):
    from app.live_party_watch import (
        detect_fainted_transitions,
        diff_live_party,
        infer_incoming_role_assignments,
        infer_unassigned_role_assignments,
    )
    from app.save_engine_client import SaveGameData, SavePokemon


def pokemon(
    slot: int, species_id: int, *, role: str = "SIN ROL", moves=(1, 2, 3, 4),
    level: int = 20, current_hp: int = 30, max_hp: int = 30,
):
    return SavePokemon(
        slot=slot,
        species_id=species_id,
        species=f"Species {species_id}",
        nickname=f"Mon {species_id}",
        level=level,
        held_item="Ninguno",
        ability="Ability",
        moves=[str(value) for value in moves],
        move_ids=list(moves),
        is_egg=False,
        markings=[False] * 6,
        role=role,
        role_symbol="",
        pid=1000 + species_id,
        tid=1,
        sid=2,
        current_hp=current_hp,
        max_hp=max_hp,
    )


def game(*party):
    return SaveGameData("AS", "SAV6AO", 6, "Diego", list(party), {})


class LivePartyWatchTests(unittest.TestCase):
    def test_detects_level_only_changes_from_live_party(self) -> None:
        before = game(pokemon(1, 261, level=20))
        after = game(pokemon(1, 261, level=21))
        diff = diff_live_party(before, after)
        self.assertTrue(diff.changed)
        self.assertTrue(diff.levels_changed)
        self.assertEqual(diff.label(), "nivel")

    def test_detects_alive_to_fainted_transition_once(self) -> None:
        before = game(pokemon(1, 261, role="Mago", current_hp=12))
        after = game(pokemon(1, 261, role="Mago", current_hp=0))
        events = detect_fainted_transitions(before, after)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].pokemon, "Mon 261")
        self.assertEqual(events[0].role, "Mago")
        self.assertEqual(events[0].previous_hp, 12)

    def test_does_not_count_already_fainted_or_merely_damaged(self) -> None:
        already = detect_fainted_transitions(
            game(pokemon(1, 261, current_hp=0)),
            game(pokemon(1, 261, current_hp=0)),
        )
        damaged = detect_fainted_transitions(
            game(pokemon(1, 261, current_hp=30)),
            game(pokemon(1, 261, current_hp=8)),
        )
        self.assertEqual(already, ())
        self.assertEqual(damaged, ())

    def test_detects_move_change(self) -> None:
        before = game(pokemon(1, 261, moves=(1, 2, 3, 4)))
        after = game(pokemon(1, 261, moves=(1, 2, 99, 4)))
        diff = diff_live_party(before, after)
        self.assertTrue(diff.moves_changed)
        self.assertEqual(diff.label(), "movimientos")

    def test_detects_role_change(self) -> None:
        before = game(pokemon(1, 261, role="Mago"))
        after = game(pokemon(1, 261, role="Tanque"))
        diff = diff_live_party(before, after)
        self.assertTrue(diff.roles_changed)

    def test_detects_order_without_treating_it_as_replacement(self) -> None:
        before = game(pokemon(1, 261), pokemon(2, 359))
        after = game(pokemon(1, 359), pokemon(2, 261))
        diff = diff_live_party(before, after)
        self.assertTrue(diff.order_changed)
        self.assertFalse(diff.party_changed)
        self.assertEqual(diff.label(), "orden")

    def test_detects_party_member_replacement(self) -> None:
        before = game(pokemon(1, 261), pokemon(2, 359))
        after = game(pokemon(1, 261), pokemon(2, 282))
        diff = diff_live_party(before, after)
        self.assertTrue(diff.party_changed)
        self.assertEqual(diff.label(), "equipo")

    def test_direct_replacement_inherits_outgoing_role(self) -> None:
        before = game(
            pokemon(1, 261, role="Líbero"),
            pokemon(2, 396, role="Tanque"),
            pokemon(3, 398, role="Asesino"),
        )
        after = game(
            pokemon(1, 261, role="Líbero"),
            pokemon(2, 210, role="SIN ROL"),
            pokemon(3, 398, role="Asesino"),
        )
        assignments = infer_incoming_role_assignments(
            before, after, ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support"),
        )
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].slot, 2)
        self.assertEqual(assignments[0].current_role, "SIN ROL")
        self.assertEqual(assignments[0].new_role, "Tanque")
        self.assertEqual(assignments[0].reason, "direct-replacement")

    def test_direct_replacement_overrides_previous_pc_role(self) -> None:
        before = game(pokemon(1, 396, role="Mago"), pokemon(2, 261, role="Tanque"))
        after = game(pokemon(1, 210, role="Support"), pokemon(2, 261, role="Tanque"))
        assignments = infer_incoming_role_assignments(
            before, after, ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support"),
        )
        self.assertEqual(assignments[0].current_role, "Support")
        self.assertEqual(assignments[0].new_role, "Mago")

    def test_new_fifth_member_uses_first_free_role_from_left(self) -> None:
        before = game(
            pokemon(1, 1, role="Tanque"),
            pokemon(2, 2, role="Asesino"),
            pokemon(3, 3, role="Mago"),
            pokemon(4, 4, role="Support"),
        )
        after = game(
            pokemon(1, 1, role="Tanque"),
            pokemon(2, 2, role="Asesino"),
            pokemon(3, 3, role="Mago"),
            pokemon(4, 4, role="Support"),
            pokemon(5, 5, role="Prisma"),
        )
        assignments = infer_incoming_role_assignments(
            before, after, ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support"),
        )
        self.assertEqual(assignments[0].new_role, "Líbero")
        self.assertEqual(assignments[0].reason, "first-free")

    def test_existing_unassigned_member_uses_first_free_role(self) -> None:
        current = game(
            pokemon(1, 1, role="Tanque"),
            pokemon(2, 2, role="Asesino"),
            pokemon(3, 3, role="Mago"),
            pokemon(4, 4, role="Support"),
            pokemon(5, 5, role="SIN ROL"),
        )
        assignments = infer_unassigned_role_assignments(
            current, ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support"),
        )
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].slot, 5)
        self.assertEqual(assignments[0].new_role, "Líbero")
        self.assertEqual(assignments[0].reason, "unassigned-first-free")

    def test_existing_unassigned_member_uses_only_remaining_role(self) -> None:
        current = game(
            pokemon(1, 1, role="Líbero"),
            pokemon(2, 2, role="Tanque"),
            pokemon(3, 3, role="Asesino"),
            pokemon(4, 4, role="Mago"),
            pokemon(5, 5, role="Support"),
            pokemon(6, 6, role="SIN ROL"),
        )
        assignments = infer_unassigned_role_assignments(
            current, ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support"),
        )
        self.assertEqual([assignment.new_role for assignment in assignments], ["Prisma"])

    def test_unassigned_fallback_respects_reserved_replacement_role(self) -> None:
        before = game(
            pokemon(1, 1, role="Mago"),
            pokemon(2, 2, role="Tanque"),
            pokemon(3, 3, role="SIN ROL"),
        )
        after = game(
            pokemon(1, 10, role="SIN ROL"),
            pokemon(2, 2, role="Tanque"),
            pokemon(3, 3, role="SIN ROL"),
        )
        order = ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support")
        incoming = infer_incoming_role_assignments(before, after, order)
        fallback = infer_unassigned_role_assignments(after, order, incoming)
        self.assertEqual(incoming[0].new_role, "Mago")
        self.assertEqual(fallback[0].slot, 3)
        self.assertEqual(fallback[0].new_role, "Líbero")

    def test_new_member_uses_only_remaining_role(self) -> None:
        before = game(
            pokemon(1, 1, role="Líbero"),
            pokemon(2, 2, role="Tanque"),
            pokemon(3, 3, role="Asesino"),
            pokemon(4, 4, role="Mago"),
            pokemon(5, 5, role="Support"),
        )
        after = game(
            pokemon(1, 1, role="Líbero"),
            pokemon(2, 2, role="Tanque"),
            pokemon(3, 3, role="Asesino"),
            pokemon(4, 4, role="Mago"),
            pokemon(5, 5, role="Support"),
            pokemon(6, 6, role="SIN ROL"),
        )
        assignments = infer_incoming_role_assignments(
            before, after, ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support"),
        )
        self.assertEqual(assignments[0].new_role, "Prisma")


if __name__ == "__main__":
    unittest.main()
