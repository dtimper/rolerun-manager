from __future__ import annotations

"""Recuerda qué tours de bienvenida ya vio el jugador.

Mismo patrón que ``update_checker.DismissedVersionStore``: un JSON pequeño en
``CONFIG_DIR``, reemplazo atómico, y cualquier fallo de lectura o escritura se
traga en vez de impedir que el tour -o el resto del programa- funcione.
"""

import json
import os
from pathlib import Path


class OnboardingTourStore:
    def __init__(self, store_path: str | Path) -> None:
        self.store_path = Path(store_path)
        self._seen: set[str] = set()
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.store_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            return
        if isinstance(raw, dict):
            seen = raw.get("seen_tours")
            if isinstance(seen, list):
                self._seen = {str(item) for item in seen}

    def is_seen(self, tour_id: str) -> bool:
        return tour_id in self._seen

    def mark_seen(self, tour_id: str) -> None:
        if tour_id in self._seen:
            return
        self._seen.add(tour_id)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.store_path.with_name(self.store_path.name + ".tmp")
        payload = {"seen_tours": sorted(self._seen)}
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.store_path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
