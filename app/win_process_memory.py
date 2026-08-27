from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence


class WindowsProcessMemoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WindowsProcessInfo:
    pid: int
    exe_name: str


@dataclass(frozen=True, slots=True)
class HostPartyTarget:
    pid: int
    exe_name: str
    host_party_base: int


# Win32 constants. Kept local so importing this module is harmless on non-Windows.
_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_OPERATION = 0x0008
_PROCESS_VM_READ = 0x0010
_PROCESS_VM_WRITE = 0x0020
_MEM_COMMIT = 0x1000
_PAGE_NOACCESS = 0x01
_PAGE_GUARD = 0x100
_PAGE_READWRITE = 0x04
_PAGE_WRITECOPY = 0x08
_PAGE_EXECUTE_READWRITE = 0x40
_PAGE_EXECUTE_WRITECOPY = 0x80
_INVALID_HANDLE_VALUE = -1


class WindowsProcessMemory:
    """Minimal Win32 Read/WriteProcessMemory helper.

    This transport is only used as a *validated fallback* when Azahar's own RPC
    deliberately refuses NEW_LINEAR_HEAP writes. It never trusts a host address:
    callers must calibrate it against exact live party bytes first.
    """

    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsProcessMemoryError("La escritura directa de memoria de Azahar solo está disponible en Windows.")
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD),
                ("Type", wintypes.DWORD),
            ]

        self.PROCESSENTRY32W = PROCESSENTRY32W
        self.MEMORY_BASIC_INFORMATION = MEMORY_BASIC_INFORMATION

        k32 = self.kernel32
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32FirstW.restype = wintypes.BOOL
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32NextW.restype = wintypes.BOOL
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        k32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
        k32.VirtualQueryEx.restype = ctypes.c_size_t
        k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k32.ReadProcessMemory.restype = wintypes.BOOL
        k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k32.WriteProcessMemory.restype = wintypes.BOOL

    def _last_error(self, prefix: str) -> WindowsProcessMemoryError:
        code = int(self.ctypes.get_last_error())
        return WindowsProcessMemoryError(f"{prefix} (Win32 error {code}).")

    def list_azahar_processes(self) -> list[WindowsProcessInfo]:
        c = self.ctypes
        snap = self.kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if int(c.cast(snap, c.c_void_p).value or 0) == c.c_void_p(_INVALID_HANDLE_VALUE).value:
            raise self._last_error("No se pudo enumerar los procesos de Windows")
        result: list[WindowsProcessInfo] = []
        try:
            entry = self.PROCESSENTRY32W()
            entry.dwSize = c.sizeof(entry)
            ok = bool(self.kernel32.Process32FirstW(snap, c.byref(entry)))
            while ok:
                name = str(entry.szExeFile)
                if "azahar" in name.casefold():
                    result.append(WindowsProcessInfo(int(entry.th32ProcessID), name))
                ok = bool(self.kernel32.Process32NextW(snap, c.byref(entry)))
        finally:
            self.kernel32.CloseHandle(snap)
        return result

    def open_process(self, pid: int):
        rights = _PROCESS_QUERY_INFORMATION | _PROCESS_VM_OPERATION | _PROCESS_VM_READ | _PROCESS_VM_WRITE
        handle = self.kernel32.OpenProcess(rights, False, int(pid))
        if not handle:
            raise self._last_error(f"No se pudo abrir el proceso de Azahar PID {pid}")
        return handle

    def close_process(self, handle) -> None:
        if handle:
            self.kernel32.CloseHandle(handle)

    def read(self, handle, address: int, size: int) -> bytes:
        if size <= 0:
            return b""
        c = self.ctypes
        buf = (c.c_ubyte * int(size))()
        got = c.c_size_t(0)
        ok = bool(self.kernel32.ReadProcessMemory(handle, c.c_void_p(int(address)), buf, int(size), c.byref(got)))
        if not ok or int(got.value) != int(size):
            raise self._last_error(f"ReadProcessMemory falló en 0x{int(address):X}")
        return bytes(buf)

    def write(self, handle, address: int, data: bytes) -> None:
        if not data:
            return
        c = self.ctypes
        raw = bytes(data)
        buf = (c.c_ubyte * len(raw)).from_buffer_copy(raw)
        wrote = c.c_size_t(0)
        ok = bool(self.kernel32.WriteProcessMemory(handle, c.c_void_p(int(address)), buf, len(raw), c.byref(wrote)))
        if not ok or int(wrote.value) != len(raw):
            raise self._last_error(f"WriteProcessMemory falló en 0x{int(address):X}")

    @staticmethod
    def _is_writable(protect: int) -> bool:
        if protect & _PAGE_GUARD or protect & _PAGE_NOACCESS:
            return False
        base = protect & 0xFF
        return base in {_PAGE_READWRITE, _PAGE_WRITECOPY, _PAGE_EXECUTE_READWRITE, _PAGE_EXECUTE_WRITECOPY}

    def iter_writable_regions(self, handle) -> Iterable[tuple[int, int]]:
        c = self.ctypes
        mbi = self.MEMORY_BASIC_INFORMATION()
        addr = 0x10000
        max_addr = 0x00007FFFFFFFFFFF if c.sizeof(c.c_void_p) == 8 else 0x7FFF0000
        while addr < max_addr:
            queried = int(self.kernel32.VirtualQueryEx(handle, c.c_void_p(addr), c.byref(mbi), c.sizeof(mbi)))
            if queried == 0:
                break
            base = int(c.cast(mbi.BaseAddress, c.c_void_p).value or 0)
            size = int(mbi.RegionSize or 0)
            if size <= 0:
                break
            if int(mbi.State) == _MEM_COMMIT and self._is_writable(int(mbi.Protect)):
                yield base, size
            nxt = base + size
            if nxt <= addr:
                break
            addr = nxt

    def _scan_region(self, handle, base: int, size: int, pattern: bytes, *, chunk_size: int = 8 * 1024 * 1024) -> Iterable[int]:
        if not pattern or size < len(pattern):
            return
        overlap = max(0, len(pattern) - 1)
        offset = 0
        tail = b""
        while offset < size:
            amount = min(chunk_size, size - offset)
            try:
                block = self.read(handle, base + offset, amount)
            except WindowsProcessMemoryError:
                return
            hay = tail + block
            search_from = 0
            while True:
                pos = hay.find(pattern, search_from)
                if pos < 0:
                    break
                absolute = base + offset - len(tail) + pos
                if base <= absolute and absolute + len(pattern) <= base + size:
                    yield absolute
                search_from = pos + 1
            tail = hay[-overlap:] if overlap else b""
            offset += amount


    def find_exact_block_in_anchor_region(
        self, *, pid: int, anchor_address: int, pattern: bytes, max_matches: int = 8,
    ) -> list[int]:
        """Busca un bloque exacto solo dentro de la región RW que contiene el ancla.

        El ancla debe haber sido demostrada previamente (para SM usamos la party
        host calibrada). Así evitamos aceptar copias de guardado, buffers RPC u
        otras coincidencias fuera del backing FCRAM que ya sabemos que es vivo.
        """
        raw = bytes(pattern)
        if not raw:
            raise WindowsProcessMemoryError("No hay una huella de bloque con la que calibrar la RAM.")
        handle = self.open_process(int(pid))
        try:
            region = next(
                ((base, size) for base, size in self.iter_writable_regions(handle)
                 if int(base) <= int(anchor_address) < int(base) + int(size)),
                None,
            )
            if region is None:
                raise WindowsProcessMemoryError(
                    f"La party host 0x{int(anchor_address):X} no pertenece a una región RW demostrable de Azahar."
                )
            base, size = region
            matches: list[int] = []
            for hit in self._scan_region(handle, int(base), int(size), raw):
                matches.append(int(hit))
                if len(matches) >= int(max_matches):
                    break
            return matches
        finally:
            self.close_process(handle)

    @staticmethod
    def _structural_windows(
        pattern: bytes, *, excluded_ranges: Sequence[tuple[int, int]] = (),
        window_size: int = 16, windows_per_quartile: int = 4,
    ) -> list[tuple[int, bytes]]:
        """Selects deterministic, information-rich exact witnesses from a block.

        This does not assume any RAM offset. Windows are derived only from the
        save block supplied by the caller and exclude fields known to be mutable
        for the requested operation (for SM money, the four Money bytes).
        """
        raw = bytes(pattern)
        size = int(window_size)
        if size < 8 or len(raw) < size:
            return []

        def overlaps_excluded(start: int, end: int) -> bool:
            return any(start < int(stop) and end > int(begin) for begin, stop in excluded_ranges)

        candidates: list[tuple[tuple[int, int, int], int, bytes]] = []
        step = max(4, size // 2)
        for offset in range(0, len(raw) - size + 1, step):
            end = offset + size
            if overlaps_excluded(offset, end):
                continue
            chunk = raw[offset:end]
            distinct = len(set(chunk))
            nonzero = sum(1 for value in chunk if value not in (0x00, 0xFF))
            transitions = sum(1 for a, b in zip(chunk, chunk[1:]) if a != b)
            # Extremely repetitive/blank windows are weak witnesses and create
            # many false hits in FCRAM, so they are not useful evidence.
            if distinct < 4 or nonzero < max(4, size // 4):
                continue
            candidates.append(((distinct, transitions, nonzero), offset, chunk))

        if not candidates:
            return []

        quartiles: list[list[tuple[tuple[int, int, int], int, bytes]]] = [[], [], [], []]
        span = max(1, len(raw))
        for candidate in candidates:
            _score, offset, _chunk = candidate
            quartile = min(3, (offset * 4) // span)
            quartiles[quartile].append(candidate)

        selected: list[tuple[int, bytes]] = []
        for group in quartiles:
            group.sort(key=lambda item: (item[0], -item[1]), reverse=True)
            selected.extend((offset, chunk) for _score, offset, chunk in group[:int(windows_per_quartile)])

        # If some quartiles had no usable data, fill from the strongest remaining
        # witnesses so the caller still gets a deterministic best-effort proof.
        target = max(4, int(windows_per_quartile) * 4)
        if len(selected) < target:
            existing = {offset for offset, _chunk in selected}
            for _score, offset, chunk in sorted(candidates, key=lambda item: (item[0], -item[1]), reverse=True):
                if offset in existing:
                    continue
                selected.append((offset, chunk))
                existing.add(offset)
                if len(selected) >= target:
                    break
        return sorted(selected, key=lambda item: item[0])

    def find_structural_block_candidates_in_anchor_region(
        self, *, pid: int, anchor_address: int, pattern: bytes,
        excluded_ranges: Sequence[tuple[int, int]] = (), window_size: int = 16,
        windows_per_quartile: int = 4, max_candidates: int = 32,
    ) -> tuple[list[tuple[int, tuple[int, ...]]], tuple[int, ...]]:
        """Finds candidate block bases by consensus of exact sub-block witnesses.

        The scan is restricted to the same writable host allocation that already
        contains the independently-proven party anchor. Each hit is converted back
        to a possible block base using the witness' relative offset; no guest/host
        address or save-block placement is assumed.

        Returns ``[(host_base, matching_window_offsets), ...]`` plus the complete
        set of selected witness offsets. The caller must still prove guest mapping
        and decide whether a candidate is strong/unique enough to write.
        """
        raw = bytes(pattern)
        if not raw:
            raise WindowsProcessMemoryError("No hay una huella estructural con la que calibrar la RAM.")
        witnesses = self._structural_windows(
            raw, excluded_ranges=excluded_ranges, window_size=window_size,
            windows_per_quartile=windows_per_quartile,
        )
        if len(witnesses) < 4:
            raise WindowsProcessMemoryError(
                "El bloque testigo no contiene suficientes fragmentos informativos para una calibración estructural segura."
            )

        handle = self.open_process(int(pid))
        try:
            region = next(
                ((base, size) for base, size in self.iter_writable_regions(handle)
                 if int(base) <= int(anchor_address) < int(base) + int(size)),
                None,
            )
            if region is None:
                raise WindowsProcessMemoryError(
                    f"La party host 0x{int(anchor_address):X} no pertenece a una región RW demostrable de Azahar."
                )
            region_base, region_size = (int(region[0]), int(region[1]))
            support: dict[int, set[int]] = {}

            # One pass over FCRAM. Calling _scan_region once per witness would
            # reread the same large allocation many times and make the button
            # unnecessarily slow. We read each chunk once and search every exact
            # witness inside that in-memory chunk.
            overlap = max(len(witness) for _offset, witness in witnesses) - 1
            chunk_size = 8 * 1024 * 1024
            offset = 0
            tail = b""
            while offset < region_size:
                amount = min(chunk_size, region_size - offset)
                try:
                    block = self.read(handle, region_base + offset, amount)
                except WindowsProcessMemoryError:
                    break
                hay = tail + block
                hay_base = region_base + offset - len(tail)
                for witness_offset, witness in witnesses:
                    search_from = 0
                    while True:
                        pos = hay.find(witness, search_from)
                        if pos < 0:
                            break
                        hit = hay_base + pos
                        candidate_base = int(hit) - int(witness_offset)
                        if (
                            region_base <= candidate_base
                            and candidate_base + len(raw) <= region_base + region_size
                        ):
                            support.setdefault(candidate_base, set()).add(int(witness_offset))
                            if len(support) > 4096:
                                raise WindowsProcessMemoryError(
                                    "La huella estructural produjo demasiadas candidaturas en FCRAM; por seguridad no se calibró Money."
                                )
                        search_from = pos + 1
                tail = hay[-overlap:] if overlap else b""
                offset += amount

            ranked = sorted(
                ((base, tuple(sorted(offsets))) for base, offsets in support.items()),
                key=lambda item: (-len(item[1]), item[0]),
            )[:int(max_candidates)]
            return ranked, tuple(offset for offset, _chunk in witnesses)
        finally:
            self.close_process(handle)


    def writable_region_for_address(self, *, pid: int, address: int) -> tuple[int, int]:
        """Devuelve la región RW que contiene una dirección host ya demostrada.

        No descubre ni adivina una región: el caller aporta un ancla host que ya
        ha sido validada por contenido (en SM, una copia completa de la party).
        Sirve para agrupar varias copias de esa party y evitar barrer el mismo
        backing FCRAM varias veces durante la calibración del PC.
        """
        handle = self.open_process(int(pid))
        try:
            region = next(
                ((int(base), int(size)) for base, size in self.iter_writable_regions(handle)
                 if int(base) <= int(address) < int(base) + int(size)),
                None,
            )
            if region is None:
                raise WindowsProcessMemoryError(
                    f"La dirección host 0x{int(address):X} no pertenece a una región RW demostrable de Azahar."
                )
            return region
        finally:
            self.close_process(handle)

    def find_indexed_patterns_in_anchor_region(
        self, *, pid: int, anchor_address: int, patterns: Sequence[tuple[int, bytes]],
        max_candidates: int = 32,
    ) -> list[tuple[int, tuple[int, ...]]]:
        """Localiza una matriz por PK7 exactos en posiciones relativas conocidas.

        Alpha.20 no barre FCRAM una vez POR testigo. Elige el PK7 completo más
        informativo como ancla de búsqueda, recorre la región RW una sola vez y
        después comprueba los demás PK7 con lecturas directas en cada base
        derivada. El caller aún debe demostrar host==guest y parsear la matriz
        completa antes de aceptar una candidatura.
        """
        usable: list[tuple[int, bytes]] = []
        seen: set[tuple[int, bytes]] = set()
        for relative_offset, pattern in patterns:
            raw = bytes(pattern)
            key = (int(relative_offset), raw)
            if not raw or key in seen:
                continue
            seen.add(key)
            usable.append(key)
        if not usable:
            raise WindowsProcessMemoryError("No hay PK7 testigo con el que localizar la matriz del PC.")

        # Todos los testigos actuales son PK7 de 0xE8; aun así el criterio no
        # depende de ese tamaño. Priorizamos mayor longitud/entropía y después
        # el offset para que la elección sea determinista.
        primary_offset, primary = max(
            usable, key=lambda item: (len(item[1]), len(set(item[1])), -int(item[0]))
        )

        handle = self.open_process(int(pid))
        try:
            region = next(
                ((int(base), int(size)) for base, size in self.iter_writable_regions(handle)
                 if int(base) <= int(anchor_address) < int(base) + int(size)),
                None,
            )
            if region is None:
                raise WindowsProcessMemoryError(
                    f"La party host 0x{int(anchor_address):X} no pertenece a una región RW demostrable de Azahar."
                )
            region_base, region_size = region
            support: dict[int, set[int]] = {}
            hit_count = 0
            for hit in self._scan_region(handle, region_base, region_size, primary):
                hit_count += 1
                if hit_count > 4096:
                    raise WindowsProcessMemoryError(
                        "El PK7 ancla produjo demasiadas candidaturas de PC en FCRAM; no se calibró ninguna."
                    )
                candidate_base = int(hit) - int(primary_offset)
                if not (region_base <= candidate_base < region_base + region_size):
                    continue
                offsets = {int(primary_offset)}
                for relative_offset, pattern in usable:
                    if int(relative_offset) == int(primary_offset) and pattern == primary:
                        continue
                    address = candidate_base + int(relative_offset)
                    if address < region_base or address + len(pattern) > region_base + region_size:
                        continue
                    try:
                        if bytes(self.read(handle, address, len(pattern))) == pattern:
                            offsets.add(int(relative_offset))
                    except WindowsProcessMemoryError:
                        continue
                support[candidate_base] = offsets

            return sorted(
                ((base, tuple(sorted(offsets))) for base, offsets in support.items()),
                key=lambda item: (-len(item[1]), item[0]),
            )[:int(max_candidates)]
        finally:
            self.close_process(handle)

    def find_strided_u16_lanes_in_anchor_region(
        self, *, pid: int, anchor_address: int, expected_values: Sequence[int],
        stride: int, displayed_delta: int, actual_delta: int,
        max_candidates: int = 8, max_primary_hits: int = 262_144,
        chunk_size: int = 8 * 1024 * 1024,
    ) -> list[int]:
        """Localiza una tabla de HP solo dentro de la FCRAM ya anclada.

        La búsqueda no convierte una coincidencia aislada en una dirección RAM.
        Exige el multiconjunto completo de Max HP con el stride indicado y,
        además, que Displayed/Actual HP de todas las filas estén en rango. El
        orden no participa en la prueba: USUM reordena físicamente las filas al
        cambiar el Pokémon inicial. El caller todavía debe demostrar la
        traducción host↔guest, la unicidad, la identidad de cada fila y hacer
        readback por el transporte del emulador antes de usar un resultado.
        """
        values = tuple(int(value) for value in expected_values)
        if not values or any(value <= 0 or value > 0xFFFF for value in values):
            raise WindowsProcessMemoryError("El vector Max HP no es una prueba estructural válida.")
        if int(stride) <= 0 or int(displayed_delta) < 0 or int(actual_delta) < 0:
            raise WindowsProcessMemoryError("La geometría de la tabla de HP no es válida.")

        row_tail = (len(values) - 1) * int(stride)
        extent = max(row_tail + 2, int(displayed_delta) + row_tail + 2,
                     int(actual_delta) + row_tail + 2)
        expected_multiset = tuple(sorted(values))
        # El Max HP más alto suele ser el testigo de dos bytes menos frecuente.
        # Como su fila puede estar permutada, cada hit se prueba en todas las
        # posiciones posibles. El multiconjunto completo se valida después.
        primary = int(max(values)).to_bytes(2, "little")

        handle = self.open_process(int(pid))
        try:
            region = next(
                ((int(base), int(size)) for base, size in self.iter_writable_regions(handle)
                 if int(base) <= int(anchor_address) < int(base) + int(size)),
                None,
            )
            if region is None:
                raise WindowsProcessMemoryError(
                    f"La party host 0x{int(anchor_address):X} no pertenece a una región RW demostrable de Azahar."
                )
            region_base, region_size = region
            overlap = max(1, extent - 1)
            offset = 0
            tail = b""
            seen: set[int] = set()
            candidates: list[int] = []
            primary_hits = 0

            while offset < region_size:
                amount = min(int(chunk_size), region_size - offset)
                try:
                    block = self.read(handle, region_base + offset, amount)
                except WindowsProcessMemoryError:
                    break
                hay = tail + block
                hay_base = region_base + offset - len(tail)
                search_from = 0
                while True:
                    pos = hay.find(primary, search_from)
                    if pos < 0:
                        break
                    search_from = pos + 1
                    primary_hits += 1
                    if primary_hits > int(max_primary_hits):
                        raise WindowsProcessMemoryError(
                            "El testigo Max HP produjo demasiadas coincidencias; no se aceptó ninguna dirección."
                        )
                    for primary_index in range(len(values)):
                        candidate = hay_base + pos - primary_index * int(stride)
                        if candidate in seen:
                            continue
                        seen.add(candidate)
                        if candidate < region_base or candidate + extent > region_base + region_size:
                            continue
                        relative = candidate - hay_base
                        if relative < 0 or relative + extent > len(hay):
                            # La superposición conserva la candidatura para el
                            # siguiente bloque, donde podrá validarse completa.
                            seen.discard(candidate)
                            continue

                        valid = True
                        has_live_hp = False
                        observed_maxes: list[int] = []
                        for index in range(len(values)):
                            row = relative + index * int(stride)
                            max_hp = int.from_bytes(hay[row:row + 2], "little")
                            displayed_row = relative + int(displayed_delta) + index * int(stride)
                            actual_row = relative + int(actual_delta) + index * int(stride)
                            displayed_hp = int.from_bytes(hay[displayed_row:displayed_row + 2], "little")
                            actual_hp = int.from_bytes(hay[actual_row:actual_row + 2], "little")
                            if max_hp <= 0 or displayed_hp > max_hp or actual_hp > max_hp:
                                valid = False
                                break
                            observed_maxes.append(max_hp)
                            if displayed_hp > 0 or actual_hp > 0:
                                has_live_hp = True
                        if valid and tuple(sorted(observed_maxes)) != expected_multiset:
                            valid = False
                        # Una fila desplazada +2 o +actual_delta puede repetir el
                        # vector cuando todos están a PS máximos, pero sus campos
                        # acompañantes caen sobre padding/campos ajenos y pueden ser
                        # todos cero. Un combate utilizable siempre conserva al
                        # menos un miembro con HP mientras puede continuar.
                        if valid and has_live_hp:
                            candidates.append(candidate)
                            if len(candidates) > int(max_candidates):
                                raise WindowsProcessMemoryError(
                                    "La FCRAM contiene demasiadas tablas de HP compatibles; no se eligió ninguna."
                                )

                tail = hay[-overlap:] if len(hay) > overlap else hay
                offset += amount

            return sorted(candidates)
        finally:
            self.close_process(handle)



    @staticmethod
    def _candidate_zero_sanity_records(
        data: bytes, *, absolute_base: int, record_size: int, sanity_offset: int = 4,
        max_candidates: int = 32768,
        candidate_validator: Callable[[bytes], bool] | None = None,
        scan_stats: dict[str, int] | None = None,
    ) -> list[tuple[int, bytes]]:
        """Find non-zero fixed-size records whose 2-byte sanity field is zero.

        ``sanity == 0`` is only a CHEAP PREFILTER. Since alpha.24 the candidate
        limit is applied *after* an optional semantic validator. This matters for
        emulated FCRAM: arbitrary memory contains many ``00 00`` pairs and they
        must never count as PK7 merely because those two bytes happen to be zero.

        The transport stays format-agnostic: callers may provide a validator
        (SM supplies decrypt+checksum+species validation) and still must prove the
        enclosing matrix and host<->guest equality before trusting an address.
        """
        raw = bytes(data)
        size = int(record_size)
        sanity = int(sanity_offset)
        stats = scan_stats if scan_stats is not None else {}
        if size <= 0 or sanity < 0 or sanity + 2 > size or len(raw) < size:
            return []
        zero_record = b"\0" * size
        next_nonzero = re.compile(rb"[^\x00]")
        results: list[tuple[int, bytes]] = []
        seen: set[int] = set()
        pos = sanity
        while True:
            hit = raw.find(b"\0\0", pos)
            if hit < 0:
                break
            stats["sanity_hits"] = int(stats.get("sanity_hits", 0)) + 1
            start = int(hit) - sanity
            if start < 0:
                pos = hit + 1
                continue
            end = start + size
            if end > len(raw):
                break
            record = raw[start:end]
            # Huge zero runs are common in emulated RAM. A completely empty
            # record can be skipped safely, but we resume up to one full record
            # before the next non-zero byte so we cannot miss a legitimate PK7
            # whose early header/checksum bytes happen to be zero.
            if record == zero_record:
                stats["empty_records_skipped"] = int(stats.get("empty_records_skipped", 0)) + 1
                match = next_nonzero.search(raw, end)
                if match is None:
                    break
                pos = max(hit + 2, int(match.start()) - size + sanity)
                continue

            stats["nonempty_sanity_candidates"] = int(stats.get("nonempty_sanity_candidates", 0)) + 1
            if candidate_validator is not None:
                try:
                    accepted = bool(candidate_validator(record))
                except Exception:
                    accepted = False
                if not accepted:
                    stats["semantic_rejections"] = int(stats.get("semantic_rejections", 0)) + 1
                    pos = hit + 1
                    continue

            absolute = int(absolute_base) + start
            if absolute not in seen:
                results.append((absolute, record))
                seen.add(absolute)
                stats["accepted_candidates"] = int(stats.get("accepted_candidates", 0)) + 1
                if len(results) > int(max_candidates):
                    raise WindowsProcessMemoryError(
                        "La región FCRAM produjo demasiados registros que ya superaron la validación "
                        "estructural solicitada; no se intentó demostrar BoxPokemon."
                    )
            pos = hit + 1
        return results

    def find_zero_sanity_records_in_anchor_region(
        self, *, pid: int, anchor_address: int, record_size: int, sanity_offset: int = 4,
        max_candidates: int = 32768, chunk_size: int = 8 * 1024 * 1024,
        candidate_validator: Callable[[bytes], bool] | None = None,
        scan_stats: dict[str, int] | None = None,
    ) -> list[tuple[int, bytes]]:
        """Scan only the RW allocation containing an already-proven host anchor.

        If ``candidate_validator`` is supplied, raw sanity hits are validated
        immediately while each chunk is in memory and only validated records are
        retained/count toward ``max_candidates``. This avoids both the alpha.23
        false abort and materializing tens of thousands of meaningless windows.
        """
        stats = scan_stats if scan_stats is not None else {}
        handle = self.open_process(int(pid))
        try:
            region = next(
                ((int(base), int(size)) for base, size in self.iter_writable_regions(handle)
                 if int(base) <= int(anchor_address) < int(base) + int(size)),
                None,
            )
            if region is None:
                raise WindowsProcessMemoryError(
                    f"La party host 0x{int(anchor_address):X} no pertenece a una región RW demostrable de Azahar."
                )
            region_base, region_size = region
            stats["region_size"] = int(region_size)
            overlap = max(int(record_size) + int(sanity_offset) + 2, 512)
            offset = 0
            tail = b""
            results: list[tuple[int, bytes]] = []
            seen: set[int] = set()
            while offset < region_size:
                amount = min(int(chunk_size), region_size - offset)
                try:
                    block = self.read(handle, region_base + offset, amount)
                except WindowsProcessMemoryError:
                    break
                stats["chunks_read"] = int(stats.get("chunks_read", 0)) + 1
                hay = tail + block
                hay_base = region_base + offset - len(tail)
                # Per-chunk helper can see overlap duplicates. Global ``seen``
                # below removes them before the final count/address set.
                local = self._candidate_zero_sanity_records(
                    hay, absolute_base=hay_base, record_size=int(record_size),
                    sanity_offset=int(sanity_offset), max_candidates=int(max_candidates),
                    candidate_validator=candidate_validator, scan_stats=stats,
                )
                for address, record in local:
                    if not (region_base <= int(address) and int(address) + int(record_size) <= region_base + region_size):
                        continue
                    if int(address) in seen:
                        continue
                    seen.add(int(address))
                    results.append((int(address), bytes(record)))
                    if len(results) > int(max_candidates):
                        raise WindowsProcessMemoryError(
                            "La región FCRAM produjo demasiados registros que ya superaron la validación "
                            "estructural solicitada; no se intentó demostrar BoxPokemon."
                        )
                tail = hay[-overlap:] if overlap else b""
                offset += amount
            stats["unique_accepted_candidates"] = len(results)
            return results
        finally:
            self.close_process(handle)

    def find_party_targets(
        self,
        *,
        slot_raws: Sequence[bytes],
        stored_size: int,
        stats_offset: int,
        stats_size: int,
        stride: int,
    ) -> list[HostPartyTarget]:
        """Finds a host-memory party copy proven by all non-empty live slots.

        Search key is the full encrypted stored block of the first non-empty slot.
        A hit is accepted only when every non-empty slot's stored bytes *and* sparse
        stats match at the exact party stride. This rejects RPC packet buffers,
        save copies and unrelated duplicate Pokémon data.
        """
        raws = [bytes(x) for x in slot_raws]
        nonempty = [i for i, raw in enumerate(raws) if len(raw) >= stored_size and any(raw[:stored_size])]
        if not nonempty:
            raise WindowsProcessMemoryError("No hay ningún PK7 vivo con el que calibrar la memoria de Azahar.")
        first_index = nonempty[0]
        pattern = raws[first_index][:stored_size]
        first_offset = first_index * int(stride)
        targets: list[HostPartyTarget] = []

        processes = self.list_azahar_processes()
        if not processes:
            raise WindowsProcessMemoryError("No se encontró ningún proceso Windows de Azahar/AzaharPlus.")

        # Large writable regions first: Azahar's FCRAM backing is a large RW allocation.
        for proc in processes:
            try:
                handle = self.open_process(proc.pid)
            except WindowsProcessMemoryError:
                continue
            try:
                regions = list(self.iter_writable_regions(handle))
                tiers = [
                    [r for r in regions if r[1] >= 64 * 1024 * 1024],
                    [r for r in regions if 4 * 1024 * 1024 <= r[1] < 64 * 1024 * 1024],
                ]
                seen_regions: set[tuple[int, int]] = set()
                for tier in tiers:
                    for base, size in tier:
                        if (base, size) in seen_regions:
                            continue
                        seen_regions.add((base, size))
                        for hit in self._scan_region(handle, base, size, pattern):
                            party_base = int(hit) - first_offset
                            if party_base < base or party_base + (len(raws) - 1) * stride + stats_offset + stats_size > base + size:
                                continue
                            valid = True
                            for index in nonempty:
                                raw = raws[index]
                                slot_addr = party_base + index * stride
                                try:
                                    if self.read(handle, slot_addr, stored_size) != raw[:stored_size]:
                                        valid = False
                                        break
                                    expected_stats = raw[stored_size:stored_size + stats_size]
                                    if len(expected_stats) == stats_size and self.read(handle, slot_addr + stats_offset, stats_size) != expected_stats:
                                        valid = False
                                        break
                                except WindowsProcessMemoryError:
                                    valid = False
                                    break
                            if valid:
                                candidate = HostPartyTarget(proc.pid, proc.exe_name, party_base)
                                if candidate not in targets:
                                    targets.append(candidate)
                    if targets:
                        # Do not scan smaller regions if a large-region target was proven.
                        break
            finally:
                self.close_process(handle)
        return targets
