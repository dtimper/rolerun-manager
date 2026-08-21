from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

with patch("pathlib.Path.home", return_value=Path(tempfile.gettempdir()) / "rolerun-tests"):
    from app.models import PendingRoleChange
    from app.oras_live import ORASLiveError, ORASLiveReader, ORASLiveWriter, PK6_PARTY_SIZE


class LiveRoleGuardTests(unittest.TestCase):
    def test_role_write_refuses_to_overwrite_game_side_change(self) -> None:
        reader = ORASLiveReader(Path("does-not-exist.json"), stable_delay=0)
        writer = ORASLiveWriter(reader, move_pp_for=lambda _move_id: 10)
        data = bytearray(PK6_PARTY_SIZE)
        data[0x2A] = 1 << 0  # Líbero
        change = PendingRoleChange(
            pokemon_slot=1,
            pokemon="Absol",
            species="Absol",
            old_role="Mago",
            new_role="Tanque",
        )
        with self.assertRaises(ORASLiveError):
            writer._replace_role(data, change)

    def test_role_write_accepts_expected_previous_role(self) -> None:
        reader = ORASLiveReader(Path("does-not-exist.json"), stable_delay=0)
        writer = ORASLiveWriter(reader, move_pp_for=lambda _move_id: 10)
        data = bytearray(PK6_PARTY_SIZE)
        data[0x2A] = 1 << 2  # Mago (marcador 3)
        change = PendingRoleChange(
            pokemon_slot=1,
            pokemon="Absol",
            species="Absol",
            old_role="Mago",
            new_role="Tanque",
        )
        writer._replace_role(data, change)
        self.assertEqual(writer._current_role(data), "Tanque")


if __name__ == "__main__":
    unittest.main()
