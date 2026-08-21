from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, TextIO


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    path: Path
    frames: int
    first_sequence: int | None
    last_sequence: int | None
    badges_seen: tuple[int, ...]
    event_types: tuple[str, ...]
    adapters: tuple[str, ...]


class RealTimeReplay:
    """Lector offline de .ndjson o paquetes .zip del Real-Time Core."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _read_text(self) -> str:
        if self.path.suffix.casefold() == ".zip":
            with zipfile.ZipFile(self.path, "r") as archive:
                try:
                    return archive.read("session.ndjson").decode("utf-8")
                except KeyError as exc:
                    raise ValueError("El ZIP no contiene session.ndjson.") from exc
        return self.path.read_text(encoding="utf-8")

    def frames(self) -> Iterator[dict[str, object]]:
        text = self._read_text()
        for line_number, line in enumerate(io.StringIO(text), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Replay inválido en línea {line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Replay inválido en línea {line_number}: se esperaba un objeto JSON.")
            yield payload

    def summary(self) -> ReplaySummary:
        rows = list(self.frames())
        sequences = [int(row.get("sequence", 0) or 0) for row in rows]
        badges = sorted({int(row["badges"]) for row in rows if row.get("badges") is not None})
        event_types = sorted({
            str(event.get("type"))
            for row in rows
            for event in (row.get("events") or [])
            if isinstance(event, dict) and event.get("type")
        })
        adapters = sorted({str(row.get("adapter")) for row in rows if row.get("adapter")})
        return ReplaySummary(
            self.path,
            len(rows),
            sequences[0] if sequences else None,
            sequences[-1] if sequences else None,
            tuple(badges), tuple(event_types), tuple(adapters),
        )
