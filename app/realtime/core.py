from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Mapping, Sequence

from ..save_engine_client import SaveGameData
from .adapter import RealTimeGameAdapter
from .events import RealTimeEvent, diff_realtime_snapshots
from .models import RealTimeSnapshot
from .recorder import RealTimeSessionRecorder


class RealTimeCore:
    """Coordinador común de las sesiones vivas.

    Responsabilidades independientes del juego:
    - secuenciar snapshots;
    - mantener la última captura válida;
    - generar eventos semánticos;
    - aislar lecturas/escrituras auxiliares detrás del adaptador;
    - grabar sesiones reproducibles de diagnóstico;
    - añadir a la grabación solo los bloques pequeños que el adaptador considera
      útiles para depuración, sin obligar a la UI a conocer direcciones.
    """

    def __init__(self, adapter: RealTimeGameAdapter) -> None:
        self.adapter = adapter
        self._sequence = 0
        self._last_snapshot: RealTimeSnapshot | None = None
        self._last_events: tuple[RealTimeEvent, ...] = ()
        self._recorder: RealTimeSessionRecorder | None = None
        self._lock = RLock()

    @property
    def last_snapshot(self) -> RealTimeSnapshot | None:
        with self._lock:
            return self._last_snapshot

    @property
    def last_events(self) -> tuple[RealTimeEvent, ...]:
        with self._lock:
            return self._last_events

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recorder is not None

    @property
    def recording_path(self) -> Path | None:
        with self._lock:
            recorder = self._recorder
        return recorder.path if recorder is not None else None

    def _next_sequence(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence

    @staticmethod
    def _merge_memory_requests(
        primary: Sequence[tuple[int, int]],
        extra: Sequence[tuple[int, int]],
    ) -> tuple[tuple[int, int], ...]:
        merged: dict[int, int] = {}
        for address, size in (*tuple(primary), *tuple(extra)):
            address, size = int(address), int(size)
            if size <= 0:
                continue
            merged[address] = max(size, merged.get(address, 0))
        return tuple((address, merged[address]) for address in sorted(merged))

    def _recording_requests(
        self, memory_requests: Sequence[tuple[int, int]],
    ) -> tuple[tuple[int, int], ...]:
        with self._lock:
            recording = self._recorder is not None
        if not recording:
            return tuple(memory_requests)
        try:
            extra = tuple(self.adapter.diagnostic_memory_requests())
        except Exception:
            extra = ()
        return self._merge_memory_requests(memory_requests, extra)

    def _accept(self, snapshot: RealTimeSnapshot) -> RealTimeSnapshot:
        with self._lock:
            events = diff_realtime_snapshots(self._last_snapshot, snapshot)
            self._last_snapshot = snapshot
            self._last_events = events
            recorder = self._recorder
        if recorder is not None:
            try:
                runtime_state = self.adapter.runtime_state()
            except Exception as exc:
                runtime_state = {"runtime_state_error": str(exc)}
            recorder.append(snapshot, events, runtime_state=runtime_state)
        return snapshot

    def prepare_connection(self) -> None:
        """Ejecuta el handshake previo que requiera el transporte activo/candidato."""
        self.adapter.prepare_connection()

    def capture_monitor(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
    ) -> RealTimeSnapshot:
        snapshot = self.adapter.capture_monitor(
            current,
            save_path=save_path,
            memory_requests=self._recording_requests(memory_requests),
            sequence=self._next_sequence(),
        )
        return self._accept(snapshot)

    def capture_full(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
    ) -> RealTimeSnapshot:
        snapshot = self.adapter.capture_full(
            current,
            save_path=save_path,
            memory_requests=self._recording_requests(memory_requests),
            sequence=self._next_sequence(),
        )
        return self._accept(snapshot)

    def read_tm_inventory(
        self, saved_items: Mapping[int, int] | None = None, *, save_path: Path | str | None = None,
    ):
        if save_path is None:
            return self.adapter.read_tm_inventory(saved_items)
        return self.adapter.read_tm_inventory(saved_items, save_path=save_path)

    def read_pc(self, anchors, *, box_count: int | None = None, box_slot_count: int | None = None):
        return self.adapter.read_pc(anchors, box_count=box_count, box_slot_count=box_slot_count)

    def apply_changes(self, current: SaveGameData, changes):
        return self.adapter.apply_changes(current, changes)

    def start_recording(self, path: Path | str, *, include_memory: bool = True) -> Path:
        recorder = RealTimeSessionRecorder(path, include_memory=include_memory)
        with self._lock:
            self._recorder = recorder
        return recorder.path

    def stop_recording(
        self,
        *,
        package_path: Path | str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Path | None:
        with self._lock:
            recorder = self._recorder
            self._recorder = None
        if recorder is None:
            return None
        if package_path is None:
            return recorder.path
        return recorder.create_package(package_path, metadata=metadata)

    def diagnostic_state(self) -> dict[str, object]:
        with self._lock:
            snapshot = self._last_snapshot
            events = self._last_events
            sequence = self._sequence
            recorder = self._recorder
        state: dict[str, object] = {
            "sequence": int(sequence),
            "recording": recorder is not None,
            "recording_path": str(recorder.path) if recorder is not None else "",
            "events": [event.type.value for event in events],
        }
        if snapshot is not None:
            state.update({
                "adapter": snapshot.adapter_key,
                "profile": snapshot.profile,
                "process": snapshot.process.name,
                "process_id": snapshot.process.process_id,
                "badges": snapshot.badges,
                "badge_source": snapshot.badge_source,
                "battle": snapshot.battle.state,
                "attempts": snapshot.attempts,
                "snapshot_healthy": snapshot.healthy,
                "lanes": [
                    {
                        "lane": diagnostic.lane,
                        "level": diagnostic.level.value,
                        "source": diagnostic.source,
                        "message": diagnostic.message,
                        "elapsed_ms": diagnostic.elapsed_ms,
                    }
                    for diagnostic in snapshot.diagnostics
                ],
            })
        try:
            state["adapter_state"] = self.adapter.runtime_state()
        except Exception as exc:
            state["adapter_state_error"] = str(exc)
        return state

    def diagnostic_report(self) -> str:
        state = self.diagnostic_state()
        lines = ["REAL-TIME CORE", "=" * 58]
        lines.append(f"Adaptador: {state.get('adapter', self.adapter.key)}")
        lines.append(f"Perfil: {state.get('profile', '—')}")
        lines.append(f"Proceso: {state.get('process', '—')} · PID {state.get('process_id', '—')}")
        lines.append(f"Secuencia: {state.get('sequence', 0)} · intentos {state.get('attempts', '—')}")
        lines.append(f"Batalla: {state.get('battle', '—')}")
        lines.append(f"Medallas: {state.get('badges', '—')} · {state.get('badge_source', '—')}")
        lines.append(f"Grabando: {'sí' if state.get('recording') else 'no'}")
        lines.append("")
        lines.append("CARRILES")
        for lane in state.get("lanes", []) or []:
            if not isinstance(lane, dict):
                continue
            elapsed = lane.get("elapsed_ms")
            elapsed_text = f" · {float(elapsed):.1f} ms" if isinstance(elapsed, (int, float)) else ""
            lines.append(
                f"- {lane.get('lane')}: {str(lane.get('level', '')).upper()} · "
                f"{lane.get('source') or '—'}{elapsed_text}\n  {lane.get('message') or ''}"
            )
        events = state.get("events") or []
        lines.append("")
        lines.append("ÚLTIMOS EVENTOS: " + (", ".join(str(item) for item in events) if events else "ninguno"))
        adapter_state = state.get("adapter_state")
        if isinstance(adapter_state, dict):
            resolutions = adapter_state.get("memory_resolutions") or []
            lines.append("")
            lines.append("BLOQUES DE RAM RESUELTOS")
            if not resolutions:
                lines.append("- ninguno todavía")
            for item in resolutions:
                if not isinstance(item, dict):
                    continue
                address = item.get("address")
                addr_text = f"0x{int(address):08X}" if isinstance(address, int) else "—"
                lines.append(
                    f"- {item.get('block')}: {addr_text} · {item.get('source')} · "
                    f"{'OK' if item.get('success') else 'NO'} · {item.get('elapsed_ms', 0):.1f} ms"
                )
        return "\n".join(lines)

    def reset_history(self) -> None:
        """Olvida la comparación anterior sin invalidar direcciones ya calibradas."""
        with self._lock:
            self._last_snapshot = None
            self._last_events = ()

    def reset(self) -> None:
        with self._lock:
            self._sequence = 0
            self._last_snapshot = None
            self._last_events = ()
            self._recorder = None
        self.adapter.reset_runtime_state()
