from __future__ import annotations

"""Rutas persistentes de los archivos que abren cada juego.

Una Run conserva sus reglas y su historial. Esta pequeña configuración, en
cambio, representa la pareja que el jugador quiere abrir la próxima vez para
cada juego: guardado + archivo de juego/ROM. Está fuera de la Run para que el
selector inicial pueda abrirla antes de leer el save y sobrevive al cierre de
la aplicación.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class GameSourceProfile:
    game_key: str
    save_path: str = ""
    game_path: str = ""
    # Se activa al sustituir archivos porque el jugador inicia una partida
    # diferente. Se consume únicamente cuando esa partida termina de abrirse.
    start_new_run: bool = False
    updated_at: str = ""

    @property
    def has_paths(self) -> bool:
        return bool(self.save_path and self.game_path)

    @property
    def is_available(self) -> bool:
        if not self.has_paths:
            return False
        try:
            return Path(self.save_path).is_file() and Path(self.game_path).is_file()
        except OSError:
            return False

    @property
    def save_name(self) -> str:
        return Path(self.save_path).name if self.save_path else "Sin partida"

    @property
    def game_name(self) -> str:
        return Path(self.game_path).name if self.game_path else "Sin archivo de juego"


class GameSourceProfileService:
    """Lee y escribe la configuración activa por juego de forma atómica."""

    FORMAT_VERSION = 1

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self._profiles: dict[str, GameSourceProfile] = {}
        self._load()

    @staticmethod
    def _normalise_path(value: str | Path) -> str:
        return str(Path(value).expanduser().resolve())

    @staticmethod
    def _clean_key(value: object) -> str:
        return str(value or "").strip().casefold()

    def _load(self) -> None:
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        entries = raw.get("games", {}) if isinstance(raw, dict) else {}
        if not isinstance(entries, Mapping):
            return
        for raw_key, raw_profile in entries.items():
            key = self._clean_key(raw_key)
            if not key or not isinstance(raw_profile, Mapping):
                continue
            save_path = raw_profile.get("save_path", "")
            game_path = raw_profile.get("game_path", "")
            if not isinstance(save_path, str) or not isinstance(game_path, str):
                continue
            self._profiles[key] = GameSourceProfile(
                game_key=key,
                save_path=save_path.strip(),
                game_path=game_path.strip(),
                start_new_run=bool(raw_profile.get("start_new_run", False)),
                updated_at=str(raw_profile.get("updated_at", "") or ""),
            )

    def get(self, game_key: str) -> GameSourceProfile:
        key = self._clean_key(game_key)
        return self._profiles.get(key, GameSourceProfile(key))

    def set(
        self,
        game_key: str,
        save_path: str | Path,
        game_path: str | Path,
        *,
        start_new_run: bool = False,
    ) -> GameSourceProfile:
        key = self._clean_key(game_key)
        if not key:
            raise ValueError("Falta la clave del juego para guardar sus archivos.")
        profile = GameSourceProfile(
            game_key=key,
            save_path=self._normalise_path(save_path),
            game_path=self._normalise_path(game_path),
            start_new_run=bool(start_new_run),
            updated_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._profiles[key] = profile
        self._write()
        return profile

    def _write(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": self.FORMAT_VERSION,
            "games": {
                key: asdict(profile)
                for key, profile in sorted(self._profiles.items())
            },
        }
        temporary = self.config_path.with_name(self.config_path.name + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.config_path)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
