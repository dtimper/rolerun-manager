"""Instrumentación de tiempos de RoleRun Manager.

Fase 1 de la auditoría técnica del 27-08-2026. Este módulo **no cambia ninguna
conducta del programa**: mide y registra, nada más.

Reglas de diseño que justifican cada decisión:

- **Apagada por defecto.** Solo se activa con la variable de entorno
  ``ROLERUN_PERF=1``. Con la instrumentación apagada, ``timed`` devuelve la
  función original sin envolverla, así que el coste en producción es
  exactamente cero (ni una llamada extra, ni un ``perf_counter``).
- **La escritura nunca ocurre en el hilo medido.** Los registros se encolan y
  los vuelca un hilo demonio propio. Medimos en un Windows con NTFS y
  antivirus: si escribiéramos el JSONL desde el hilo Tk estaríamos midiendo
  nuestra propia instrumentación.
- **Jamás propaga una excepción.** Un fallo al instrumentar no puede tumbar una
  operación real del usuario, así que todo el camino de registro está
  protegido y falla en silencio.
- **``functools.wraps``** conserva ``__wrapped__``, de modo que los tests que
  inspeccionan el código fuente con ``inspect.getsource`` siguen viendo la
  función original aunque la instrumentación esté activa.

El resultado es un JSONL por día en ``LOG_DIR/perf_<AAAA-MM-DD>.jsonl`` con una
línea por operación: ``{"t", "op", "ms", "thread", ...campos extra}``.
"""

from __future__ import annotations

import atexit
import functools
import json
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

from .config import LOG_DIR

F = TypeVar("F", bound=Callable[..., Any])

_TRUE_VALUES = {"1", "true", "yes", "on", "si", "sí"}


def _read_enabled_flag() -> bool:
    return os.environ.get("ROLERUN_PERF", "").strip().casefold() in _TRUE_VALUES


#: Estado congelado al importar. Cambiarlo en caliente no está soportado: el
#: objetivo es que una sesión entera se mida o no se mida, sin mezclas.
ENABLED = _read_enabled_flag()

#: Cada cuánto vuelca el escritor lo acumulado, en segundos.
_FLUSH_INTERVAL = 1.0

#: Ventana de agregación para operaciones de alta frecuencia (``aggregate``).
_AGGREGATE_WINDOW = 1.0

#: Cota del buffer en memoria por si el disco no acompaña. Perder muestras es
#: preferible a crecer sin límite.
_MAX_PENDING = 20000


class _PerfWriter:
    """Cola + hilo demonio que serializa los registros a disco."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._queue: queue.SimpleQueue[dict[str, Any] | None] = queue.SimpleQueue()
        self._pending = 0
        self._pending_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, name="RoleRunPerfWriter", daemon=True
        )
        self._thread.start()

    def submit(self, record: dict[str, Any]) -> None:
        with self._pending_lock:
            if self._pending >= _MAX_PENDING:
                return
            self._pending += 1
        self._queue.put(record)

    def _drain(self, first: dict[str, Any] | None) -> tuple[list[dict[str, Any]], bool]:
        batch: list[dict[str, Any]] = []
        stop = first is None
        if first is not None:
            batch.append(first)
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                stop = True
                continue
            batch.append(item)
        return batch, stop

    def _write(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                for record in batch:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # Medir nunca puede romper nada; si el disco falla, se pierde la muestra.
            pass
        finally:
            with self._pending_lock:
                self._pending = max(0, self._pending - len(batch))

    def _run(self) -> None:
        while True:
            try:
                first = self._queue.get(timeout=_FLUSH_INTERVAL)
            except queue.Empty:
                continue
            batch, stop = self._drain(first)
            self._write(batch)
            if stop:
                return

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=2.0)


_writer: _PerfWriter | None = None
_writer_lock = threading.Lock()


def session_path() -> Path:
    """Ruta del JSONL de la sesión actual (un archivo por día)."""
    return LOG_DIR / f"perf_{datetime.now().strftime('%Y-%m-%d')}.jsonl"


def _get_writer() -> _PerfWriter | None:
    global _writer
    if not ENABLED:
        return None
    writer = _writer
    if writer is not None:
        return writer
    with _writer_lock:
        if _writer is None:
            try:
                _writer = _PerfWriter(session_path())
                atexit.register(_writer.close)
            except Exception:
                return None
        return _writer


def _thread_label() -> str:
    current = threading.current_thread()
    if current is threading.main_thread():
        # main.py arranca el ``mainloop`` de Tk en el hilo principal, así que
        # "tk" identifica exactamente el hilo que no debe bloquearse.
        return "tk"
    return current.name


def record(op: str, ms: float, **fields: Any) -> None:
    """Anota una operación ya medida. No hace nada si la medición está apagada.

    Todo el cuerpo está protegido, incluida la obtención del escritor: ``record``
    se invoca desde bloques ``finally``, así que una excepción aquí saldría por
    encima de la operación real del usuario.
    """
    try:
        writer = _get_writer()
        if writer is None:
            return
        entry: dict[str, Any] = {
            "t": datetime.now().isoformat(timespec="milliseconds"),
            "op": str(op),
            "ms": round(float(ms), 3),
            "thread": _thread_label(),
        }
        for key, value in fields.items():
            if value is not None:
                entry[key] = value
        writer.submit(entry)
    except Exception:
        pass


def mark(op: str, **fields: Any) -> None:
    """Marca un instante sin duración, para trazar cadenas de eventos."""
    record(op, 0.0, kind="mark", **fields)


class _Span:
    """Contexto que mide su propio bloque y admite campos añadidos al vuelo."""

    __slots__ = ("op", "fields", "_start")

    def __init__(self, op: str, fields: dict[str, Any]) -> None:
        self.op = op
        self.fields = fields
        self._start = 0.0

    def add(self, **fields: Any) -> None:
        """Añade contexto conocido solo a mitad del bloque (p. ej. nº de widgets)."""
        try:
            self.fields.update(fields)
        except Exception:
            pass

    def __enter__(self) -> "_Span":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        if exc_type is not None:
            self.fields["error"] = exc_type.__name__
        record(self.op, elapsed_ms, **self.fields)
        return False


class _NullSpan:
    """Sustituto sin coste cuando la medición está apagada."""

    __slots__ = ()

    def add(self, **fields: Any) -> None:
        return None

    def __enter__(self) -> "_NullSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


_NULL_SPAN = _NullSpan()


def span(op: str, **fields: Any) -> Any:
    """Mide un bloque concreto: ``with perf.span("ui.render", page=…) as s:``."""
    if not ENABLED:
        return _NULL_SPAN
    return _Span(op, dict(fields))


def timed(op: str, **fields: Any) -> Callable[[F], F]:
    """Decorador que mide una función completa.

    Con la medición apagada devuelve la función **tal cual**, sin envolverla:
    así el programa en producción no paga absolutamente nada.
    """

    def decorate(func: F) -> F:
        if not ENABLED:
            return func

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            error: str | None = None
            try:
                return func(*args, **kwargs)
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                record(op, (time.perf_counter() - start) * 1000.0, error=error, **fields)

        return wrapper  # type: ignore[return-value]

    return decorate


class _Aggregator:
    """Acumula operaciones de alta frecuencia y emite un resumen por ventana.

    ``_poll_gamepad`` corre a 60 Hz: una línea por tick generaría 3.600 líneas
    por minuto y la propia medición pasaría a ser el problema. Aquí se guarda
    conteo, total, máximo y media por ventana de un segundo.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, float]] = {}

    def add(self, op: str, ms: float) -> None:
        now = time.perf_counter()
        flush: dict[str, float] | None = None
        with self._lock:
            entry = self._state.get(op)
            if entry is None:
                entry = {"start": now, "count": 0.0, "total": 0.0, "max": 0.0}
                self._state[op] = entry
            entry["count"] += 1.0
            entry["total"] += ms
            entry["max"] = max(entry["max"], ms)
            if now - entry["start"] >= _AGGREGATE_WINDOW:
                flush = entry
                self._state[op] = {"start": now, "count": 0.0, "total": 0.0, "max": 0.0}
        if flush is not None:
            self._emit(op, flush, now)

    @staticmethod
    def _emit(op: str, entry: dict[str, float], now: float) -> None:
        count = int(entry["count"])
        if count <= 0:
            return
        window = max(now - entry["start"], 1e-9)
        record(
            op,
            entry["total"],
            kind="aggregate",
            count=count,
            window_s=round(window, 3),
            avg_ms=round(entry["total"] / count, 3),
            max_ms=round(entry["max"], 3),
            calls_per_s=round(count / window, 1),
        )

    def flush(self) -> None:
        now = time.perf_counter()
        with self._lock:
            pending = list(self._state.items())
            self._state = {}
        for op, entry in pending:
            self._emit(op, entry, now)


_aggregator = _Aggregator()


def aggregate(op: str, ms: float) -> None:
    """Acumula una muestra de alta frecuencia en lugar de escribir una línea."""
    if not ENABLED:
        return
    try:
        _aggregator.add(op, ms)
    except Exception:
        pass


def timed_aggregate(op: str) -> Callable[[F], F]:
    """Como ``timed``, pero resumiendo por ventana en vez de línea por llamada."""

    def decorate(func: F) -> F:
        if not ENABLED:
            return func

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                aggregate(op, (time.perf_counter() - start) * 1000.0)

        return wrapper  # type: ignore[return-value]

    return decorate


if ENABLED:
    atexit.register(_aggregator.flush)
