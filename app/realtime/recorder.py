from __future__ import annotations

import base64
import json
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from .events import RealTimeEvent
from .models import RealTimeSnapshot


@dataclass(frozen=True, slots=True)
class RecordedFrame:
    sequence: int
    payload: dict[str, object]


def _pokemon_payload(pokemon) -> dict[str, object]:
    return {
        "slot": int(pokemon.slot),
        "species_id": int(pokemon.species_id),
        "species": str(pokemon.species),
        "nickname": str(pokemon.nickname or ""),
        "pid": int(pokemon.pid or 0),
        "tid": int(pokemon.tid or 0),
        "sid": int(pokemon.sid or 0),
        "role": str(pokemon.role or "SIN ROL"),
        "level": int(getattr(pokemon, "level", 0) or 0),
        "current_hp": int(getattr(pokemon, "current_hp", 0) or 0),
        "max_hp": int(getattr(pokemon, "max_hp", 0) or 0),
        "move_ids": [int(value or 0) for value in pokemon.move_ids],
    }


def snapshot_payload(snapshot: RealTimeSnapshot, *, include_memory: bool = True) -> dict[str, object]:
    return {
        "sequence": int(snapshot.sequence),
        "captured_at": float(snapshot.captured_at),
        "adapter": snapshot.adapter_key,
        "profile": snapshot.profile,
        "process": asdict(snapshot.process),
        "attempts": int(snapshot.attempts),
        "party": [_pokemon_payload(p) for p in snapshot.game.party],
        "badges": snapshot.badges,
        "badge_source": snapshot.badge_source,
        "battle": {
            "state": snapshot.battle.state,
            "hp_pairs": [list(pair) for pair in snapshot.battle.hp_pairs],
        },
        "diagnostics": [
            {
                "lane": item.lane,
                "level": item.level.value,
                "message": item.message,
                "source": item.source,
                "elapsed_ms": item.elapsed_ms,
            }
            for item in snapshot.diagnostics
        ],
        "memory_blocks": [
            {"address": int(block.address), "data_b64": base64.b64encode(block.data).decode("ascii")}
            for block in snapshot.memory_blocks
        ] if include_memory else [],
        "metadata": dict(snapshot.metadata),
    }


class RealTimeSessionRecorder:
    """Grabador NDJSON + empaquetador de diagnóstico reproducible."""

    def __init__(self, path: Path | str, *, include_memory: bool = True) -> None:
        self.path = Path(path)
        self.include_memory = bool(include_memory)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Cada sesión debe empezar limpia; nunca mezclamos una grabación anterior
        # por haber reutilizado accidentalmente el mismo nombre de archivo.
        self.path.write_text("", encoding="utf-8")
        self.started_at = time.time()
        self.frame_count = 0
        self.first_sequence: int | None = None
        self.last_sequence: int | None = None

    def append(
        self,
        snapshot: RealTimeSnapshot,
        events: Iterable[RealTimeEvent] = (),
        *,
        runtime_state: Mapping[str, object] | None = None,
    ) -> None:
        payload = snapshot_payload(snapshot, include_memory=self.include_memory)
        payload["events"] = [
            {
                "type": event.type.value,
                "message": event.message,
                "pokemon_identity": list(event.pokemon_identity) if event.pokemon_identity else None,
                "before": event.before,
                "after": event.after,
            }
            for event in events
        ]
        if runtime_state:
            payload["runtime_state"] = dict(runtime_state)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
            stream.write("\n")
        self.frame_count += 1
        sequence = int(snapshot.sequence)
        if self.first_sequence is None:
            self.first_sequence = sequence
        self.last_sequence = sequence

    def create_package(
        self,
        output_path: Path | str,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "format": "rolerun-realtime-diagnostic-v1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "started_at": datetime.fromtimestamp(self.started_at).isoformat(timespec="seconds"),
            "frames": int(self.frame_count),
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "include_memory": self.include_memory,
            **dict(metadata or {}),
        }
        readme = (
            "RoleRun Manager · paquete de diagnóstico de tiempo real\n\n"
            "session.ndjson contiene los snapshots/eventos reproducibles.\n"
            "manifest.json describe la versión y la sesión.\n"
            "No modifica el guardado ni la RAM; solo contiene datos capturados durante la grabación.\n"
        )
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(self.path, arcname="session.ndjson")
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
            archive.writestr("LEEME.txt", readme)
        return output
