from __future__ import annotations

import time
from dataclasses import dataclass
from threading import RLock
from typing import Callable, Hashable, Iterable, Sequence


Score = tuple[int, ...]
SessionKey = Hashable


@dataclass(frozen=True, slots=True)
class MemoryCandidateHint:
    """Dirección candidata conocida por un adaptador.

    ``priority`` solo desempata fuentes igualmente válidas. La validez real la
    decide siempre ``validate`` leyendo bytes vivos; una dirección fija jamás se
    considera correcta por el mero hecho de ser histórica.
    """

    address: int
    source: str = "candidate"
    priority: int = 0


@dataclass(frozen=True, slots=True)
class MemoryResolution:
    block_key: str
    session_key: str
    address: int | None
    source: str
    cache_hit: bool
    score: Score | None
    candidate_count: int
    elapsed_ms: float
    success: bool
    message: str = ""


class LiveBlockResolver:
    """Localizador/caché común de bloques de RAM para todos los juegos.

    El patrón aprendido en ORAS queda encapsulado aquí:

    1. validar una dirección ya cacheada;
    2. probar candidatos baratos/conocidos;
    3. solo entonces ejecutar un descubrimiento caro;
    4. elegir el candidato mejor puntuado;
    5. cachearlo mientras siga validando;
    6. aplicar cooldown tras un barrido fallido.

    El resolver no sabe nada de Pokémon, offsets ni emuladores. Cada adaptador
    aporta ``read_at``, ``validate`` y, si hace falta, ``discover``.
    """

    def __init__(self, *, default_failure_cooldown: float = 8.0) -> None:
        self.default_failure_cooldown = max(0.0, float(default_failure_cooldown))
        self._cache: dict[tuple[SessionKey, str], int] = {}
        self._failed_at: dict[tuple[SessionKey, str], float] = {}
        self._last: dict[tuple[SessionKey, str], MemoryResolution] = {}
        self._lock = RLock()

    @staticmethod
    def _session_label(session_key: SessionKey) -> str:
        if isinstance(session_key, tuple):
            return " · ".join(str(value) for value in session_key)
        return str(session_key)

    def cached_address(self, session_key: SessionKey, block_key: str) -> int | None:
        with self._lock:
            value = self._cache.get((session_key, str(block_key)))
        return int(value) if value is not None else None

    def prime(self, session_key: SessionKey, block_key: str, address: int) -> None:
        """Importa una dirección conocida (p. ej. caché legacy) sin confiar en ella.

        La siguiente resolución volverá a validarla antes de utilizarla.
        """
        with self._lock:
            self._cache[(session_key, str(block_key))] = int(address)

    def invalidate(self, session_key: SessionKey, block_key: str) -> None:
        key = (session_key, str(block_key))
        with self._lock:
            self._cache.pop(key, None)
            self._failed_at.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._cache.clear()
            self._failed_at.clear()
            self._last.clear()

    @property
    def last_resolutions(self) -> tuple[MemoryResolution, ...]:
        with self._lock:
            values = tuple(self._last.values())
        return tuple(sorted(values, key=lambda item: (item.block_key, item.session_key)))

    def _remember(self, key: tuple[SessionKey, str], resolution: MemoryResolution) -> MemoryResolution:
        with self._lock:
            self._last[key] = resolution
        return resolution

    def resolve(
        self,
        block_key: str,
        session_key: SessionKey,
        *,
        read_at: Callable[[int], bytes | None],
        validate: Callable[[bytes], Score | None],
        preferred: Sequence[MemoryCandidateHint] = (),
        discover: Callable[[], Iterable[MemoryCandidateHint | int]] | None = None,
        failure_cooldown: float | None = None,
    ) -> MemoryResolution:
        block_key = str(block_key)
        state_key = (session_key, block_key)
        started = time.perf_counter()
        cooldown = self.default_failure_cooldown if failure_cooldown is None else max(0.0, float(failure_cooldown))

        # La dirección cacheada tiene prioridad absoluta mientras siga siendo una
        # estructura válida. Esto es crucial para que un state-load 8 -> 5 no haga
        # saltar a otra copia de RAM simplemente porque tenga "más progreso".
        cached = self.cached_address(session_key, block_key)
        if cached is not None:
            raw = read_at(cached)
            score = validate(raw) if raw is not None else None
            if score is not None:
                return self._remember(state_key, MemoryResolution(
                    block_key, self._session_label(session_key), cached, "cache", True,
                    tuple(score), 1, (time.perf_counter() - started) * 1000, True,
                    "Dirección cacheada validada.",
                ))
            with self._lock:
                self._cache.pop(state_key, None)

        hints: list[MemoryCandidateHint] = []
        seen: set[int] = set()
        for hint in preferred:
            address = int(hint.address)
            if address in seen:
                continue
            seen.add(address)
            hints.append(MemoryCandidateHint(address, str(hint.source), int(hint.priority)))

        ranked: list[tuple[tuple[int, ...], MemoryCandidateHint, Score]] = []
        for hint in hints:
            raw = read_at(hint.address)
            score = validate(raw) if raw is not None else None
            if score is None:
                continue
            normalized = tuple(int(value) for value in score)
            ranked.append(((int(hint.priority), *normalized), hint, normalized))

        if ranked:
            ranked.sort(key=lambda row: row[0], reverse=True)
            _rank, hint, score = ranked[0]
            with self._lock:
                self._cache[state_key] = int(hint.address)
                self._failed_at.pop(state_key, None)
            return self._remember(state_key, MemoryResolution(
                block_key, self._session_label(session_key), int(hint.address), hint.source,
                False, score, len(ranked), (time.perf_counter() - started) * 1000, True,
                "Candidato directo validado.",
            ))

        if discover is None:
            return self._remember(state_key, MemoryResolution(
                block_key, self._session_label(session_key), None, "none", False,
                None, 0, (time.perf_counter() - started) * 1000, False,
                "No hay candidatos válidos y este bloque no define barrido.",
            ))

        with self._lock:
            failed_at = self._failed_at.get(state_key)
        if failed_at is not None and cooldown and (time.monotonic() - failed_at) < cooldown:
            return self._remember(state_key, MemoryResolution(
                block_key, self._session_label(session_key), None, "cooldown", False,
                None, 0, (time.perf_counter() - started) * 1000, False,
                "Barrido omitido temporalmente tras un fallo reciente.",
            ))

        discovered: list[MemoryCandidateHint] = []
        try:
            iterable = discover()
            for item in iterable:
                hint = item if isinstance(item, MemoryCandidateHint) else MemoryCandidateHint(int(item), "scan", 0)
                address = int(hint.address)
                if address in seen:
                    continue
                seen.add(address)
                discovered.append(hint)
        except Exception as exc:
            with self._lock:
                self._failed_at[state_key] = time.monotonic()
            return self._remember(state_key, MemoryResolution(
                block_key, self._session_label(session_key), None, "scan-error", False,
                None, 0, (time.perf_counter() - started) * 1000, False,
                str(exc) or "Falló el barrido de memoria.",
            ))

        ranked_scan: list[tuple[tuple[int, ...], MemoryCandidateHint, Score]] = []
        for hint in discovered:
            raw = read_at(hint.address)
            score = validate(raw) if raw is not None else None
            if score is None:
                continue
            normalized = tuple(int(value) for value in score)
            ranked_scan.append(((int(hint.priority), *normalized), hint, normalized))

        if not ranked_scan:
            with self._lock:
                self._failed_at[state_key] = time.monotonic()
            return self._remember(state_key, MemoryResolution(
                block_key, self._session_label(session_key), None, "scan", False,
                None, len(discovered), (time.perf_counter() - started) * 1000, False,
                "El barrido no encontró ningún candidato válido.",
            ))

        ranked_scan.sort(key=lambda row: row[0], reverse=True)
        _rank, hint, score = ranked_scan[0]
        with self._lock:
            self._cache[state_key] = int(hint.address)
            self._failed_at.pop(state_key, None)
        return self._remember(state_key, MemoryResolution(
            block_key, self._session_label(session_key), int(hint.address), hint.source,
            False, score, len(ranked_scan), (time.perf_counter() - started) * 1000, True,
            "Bloque localizado mediante barrido y cacheado.",
        ))
