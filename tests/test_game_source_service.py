from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.game_source_service import GameSourceProfileService


class GameSourceProfileServiceTests(unittest.TestCase):
    def test_persists_each_games_save_and_game_file_across_restarts(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            rom = root / "Zafiro Alfa.cxi"
            save.write_bytes(b"save")
            rom.write_bytes(b"rom")
            config = root / "Config" / "game_sources.json"

            service = GameSourceProfileService(config)
            stored = service.set("ORAS", save, rom, start_new_run=True)
            reopened = GameSourceProfileService(config).get("oras")
            self.assertTrue(stored.is_available)
            self.assertEqual(reopened.save_path, str(save.resolve()))
            self.assertEqual(reopened.game_path, str(rom.resolve()))
            self.assertTrue(reopened.is_available)
            self.assertTrue(reopened.start_new_run)

    def test_missing_or_corrupt_config_never_blocks_game_selection(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(directory) / "game_sources.json"
            config.write_text("{not json", encoding="utf-8")
            profile = GameSourceProfileService(config).get("bdsp")

        self.assertFalse(profile.has_paths)
        self.assertFalse(profile.is_available)

    def test_profile_status_changes_when_a_remembered_file_is_moved(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            rom = root / "ORAS.cxi"
            save.write_bytes(b"save")
            rom.write_bytes(b"rom")
            config = root / "game_sources.json"
            service = GameSourceProfileService(config)
            service.set("oras", save, rom)
            rom.unlink()
            profile = GameSourceProfileService(config).get("oras")

        self.assertTrue(profile.has_paths)
        self.assertFalse(profile.is_available)

    def test_serialized_file_keeps_only_local_paths_and_no_save_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "main"
            rom = root / "ORAS.cxi"
            save.write_bytes(b"save-content")
            rom.write_bytes(b"rom-content")
            config = root / "game_sources.json"
            GameSourceProfileService(config).set("oras", save, rom)
            raw = json.loads(config.read_text(encoding="utf-8"))
            serialized = config.read_text(encoding="utf-8")
            self.assertEqual(raw["games"]["oras"]["save_path"], str(save.resolve()))
            self.assertEqual(raw["games"]["oras"]["game_path"], str(rom.resolve()))
            self.assertNotIn("save-content", serialized)
            self.assertNotIn("rom-content", serialized)


if __name__ == "__main__":
    unittest.main()
