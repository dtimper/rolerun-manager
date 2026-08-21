from __future__ import annotations

from pathlib import Path
import json
import time
from datetime import datetime
from typing import Callable, Sequence

from ..models import PendingRoleChange
from ..config import APP_VERSION, LOG_DIR
from ..save_engine_client import SaveGameData
from ..usum_live import (
    PK7_STORED_SIZE, USUM_PARTY_STATS_OFFSET, USUM_PARTY_STATS_SIZE, USUM_PARTY_STRIDE,
    USUMLiveError, USUMLiveReader, USUMLiveWriter, USUMLiveWriteResult,
)
from .adapter import RealTimeGameAdapter
from .bridge import AzaharBridge
from .models import (
    BattleState,
    DiagnosticLevel,
    LiveDiagnostic,
    LiveMemoryBlock,
    LiveProcessInfo,
    RealTimeSnapshot,
)


class USUMRealTimeAdapter(RealTimeGameAdapter):
    """UltraSol/UltraLuna alpha.43: candidato de paridad con validación runtime."""

    key = "usum-azahar-rpc-roles"
    game_key = "usum"
    display_name = "Pokémon Ultra Sol / Ultra Luna"

    def __init__(
        self,
        reader: USUMLiveReader,
        bridge: AzaharBridge | None = None,
        *,
        move_pp_for: Callable[[int], int] | None = None,
        move_allowed: Callable[[int], bool] | None = None,
        personal_for: Callable[[int, int], object | None] | None = None,
    ) -> None:
        self.reader = reader
        self.writer = USUMLiveWriter(
            reader, move_pp_for=move_pp_for, move_allowed=move_allowed, personal_for=personal_for,
        )
        self.bridge = bridge or AzaharBridge(reader.client_factory)
        self._last_process_key: tuple[int, str] | None = None
        self._last_party_base: int | None = None
        self._last_game: SaveGameData | None = None
        self._last_save_path: Path | None = None
        self._last_runtime_party_region: bytes | None = None

    @staticmethod
    def _process(process) -> LiveProcessInfo:
        return LiveProcessInfo(
            emulator="azahar",
            process_id=int(process.process_id),
            title_id=int(process.title_id),
            name=str(process.name),
        )

    @staticmethod
    def _blocks(blocks) -> tuple[LiveMemoryBlock, ...]:
        return tuple(LiveMemoryBlock(int(block.address), bytes(block.data)) for block in tuple(blocks or ()))

    @staticmethod
    def _party_identity_map(game: SaveGameData | None) -> dict[int, tuple[int, int, int, int]]:
        if game is None:
            return {}
        return {
            int(p.slot): (int(p.species_id), int(p.pid or 0), int(p.tid or 0), int(p.sid or 0))
            for p in game.party if int(p.species_id) > 0
        }

    @staticmethod
    def _party_label_map(game: SaveGameData | None) -> dict[int, dict[str, object]]:
        if game is None:
            return {}
        return {
            int(p.slot): {
                "species_id": int(p.species_id),
                "species": str(p.species),
                "nickname": str(p.nickname),
                "pid": int(p.pid or 0),
                "tid": int(p.tid or 0),
                "sid": int(p.sid or 0),
                "role": str(p.role),
            }
            for p in game.party if int(p.species_id) > 0
        }

    @staticmethod
    def _diff_ranges(before: bytes, after: bytes) -> list[list[int]]:
        offsets = [i for i, (left, right) in enumerate(zip(before, after)) if left != right]
        if not offsets:
            return []
        ranges: list[list[int]] = []
        start = previous = offsets[0]
        for offset in offsets[1:]:
            if offset == previous + 1:
                previous = offset
                continue
            ranges.append([int(start), int(previous)])
            start = previous = offset
        ranges.append([int(start), int(previous)])
        return ranges

    @classmethod
    def _save_party_transition_diagnostic(
        cls, *, before_game: SaveGameData, after_game: SaveGameData,
        before_region: bytes, after_region: bytes, party_base: int, process,
    ) -> None:
        expected_size = 6 * USUM_PARTY_STRIDE
        if len(before_region) != expected_size or len(after_region) != expected_size:
            return
        before_ids = cls._party_identity_map(before_game)
        after_ids = cls._party_identity_map(after_game)
        changed_slots = [
            slot for slot in range(1, 7)
            if before_ids.get(slot) != after_ids.get(slot)
        ]
        if not changed_slots:
            return

        before_labels = cls._party_label_map(before_game)
        after_labels = cls._party_label_map(after_game)
        zones = (
            ("stored", 0, PK7_STORED_SIZE),
            ("runtime_gap", PK7_STORED_SIZE, USUM_PARTY_STATS_OFFSET),
            ("stats", USUM_PARTY_STATS_OFFSET, USUM_PARTY_STATS_OFFSET + USUM_PARTY_STATS_SIZE),
            ("runtime_tail", USUM_PARTY_STATS_OFFSET + USUM_PARTY_STATS_SIZE, USUM_PARTY_STRIDE),
        )
        slot_records: list[dict[str, object]] = []
        for slot in changed_slots:
            start = (slot - 1) * USUM_PARTY_STRIDE
            before = bytes(before_region[start:start + USUM_PARTY_STRIDE])
            after = bytes(after_region[start:start + USUM_PARTY_STRIDE])
            diff_offsets = [i for i, (left, right) in enumerate(zip(before, after)) if left != right]
            zone_diff_counts = {
                name: sum(1 for offset in diff_offsets if zone_start <= offset < zone_end)
                for name, zone_start, zone_end in zones
            }
            unknown_offsets = [
                int(offset) for offset in diff_offsets
                if PK7_STORED_SIZE <= offset < USUM_PARTY_STATS_OFFSET
                or USUM_PARTY_STATS_OFFSET + USUM_PARTY_STATS_SIZE <= offset < USUM_PARTY_STRIDE
            ]
            slot_records.append({
                "slot": int(slot),
                "address": f"0x{int(party_base) + (slot - 1) * USUM_PARTY_STRIDE:08X}",
                "before": before_labels.get(slot),
                "after": after_labels.get(slot),
                "diff_count": len(diff_offsets),
                "diff_ranges": cls._diff_ranges(before, after),
                "zone_diff_counts": zone_diff_counts,
                "unknown_runtime_diff_offsets": unknown_offsets,
                "before_runtime_hex": before.hex(),
                "after_runtime_hex": after.hex(),
            })

        payload = {
            "format": "rolerun-usum-party-runtime-transition-v1",
            "version": APP_VERSION,
            "created_at": datetime.now().isoformat(timespec="milliseconds"),
            "purpose": (
                "Comparar un swap REAL hecho dentro de Pokémon Ultra Sol/Ultra Luna contra el layout sparse de lectura. "
                "No demuestra por sí solo una regla de escritura; conserva los 0x1E4 bytes completos de cada slot cambiado."
            ),
            "process": {
                "pid": int(process.process_id),
                "title_id": f"{int(process.title_id):016X}",
                "name": str(process.name),
            },
            "party_base": f"0x{int(party_base):08X}",
            "party_stride": int(USUM_PARTY_STRIDE),
            "stored_size": int(PK7_STORED_SIZE),
            "stats_offset": int(USUM_PARTY_STATS_OFFSET),
            "stats_size": int(USUM_PARTY_STATS_SIZE),
            "changed_slots": slot_records,
        }
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            (LOG_DIR / "usum_party_runtime_transition_latest.json").write_text(text, encoding="utf-8")
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            (LOG_DIR / f"usum-party-runtime-{stamp}.json").write_text(text, encoding="utf-8")
        except OSError:
            pass

    def _convert(
        self, raw, *, sequence: int, battle: BattleState | None = None,
        battle_diagnostic: LiveDiagnostic | None = None,
        badges: int | None = None, badge_source: str | None = None,
        badge_diagnostic: LiveDiagnostic | None = None,
    ) -> RealTimeSnapshot:
        previous_game = self._last_game
        previous_runtime = self._last_runtime_party_region
        current_runtime = bytes(getattr(raw, "runtime_party_region", b"") or b"")
        if (
            previous_game is not None
            and previous_runtime is not None
            and current_runtime
            and self._party_identity_map(previous_game) != self._party_identity_map(raw.game)
        ):
            self._save_party_transition_diagnostic(
                before_game=previous_game, after_game=raw.game,
                before_region=previous_runtime, after_region=current_runtime,
                party_base=int(raw.party_base), process=raw.process,
            )
        self._last_process_key = (int(raw.process.title_id), str(raw.process.name))
        self._last_party_base = int(raw.party_base)
        self._last_game = raw.game
        self._last_runtime_party_region = current_runtime or None
        return RealTimeSnapshot(
            game=raw.game,
            process=self._process(raw.process),
            attempts=int(raw.attempts),
            adapter_key=self.key,
            profile="USUM-alpha.43-parity-candidate",
            memory_blocks=self._blocks(raw.memory_blocks),
            battle=battle or BattleState("unknown"),
            badges=badges,
            badge_source=badge_source,
            diagnostics=(
                LiveDiagnostic(
                    "party",
                    DiagnosticLevel.OK,
                    f"Party PK7 estable validada en 0x{int(raw.party_base):08X} tras {int(raw.attempts)} intento(s).",
                    "AzaharPlus RPC · lectura validada",
                ),
                LiveDiagnostic(
                    "roles",
                    DiagnosticLevel.OK,
                    "MarkingValue PK7 leído en vivo; escritura de roles verificada con rollback.",
                    "PK7 0x16 · 2 bits por símbolo",
                ),
                LiveDiagnostic(
                    "moves",
                    DiagnosticLevel.OK,
                    "Movimientos PK7 leídos y escritos en vivo con validación y rollback.",
                    "PK7 0x5A–0x69 · host FCRAM calibrado",
                ),
                LiveDiagnostic(
                    "writes",
                    DiagnosticLevel.OK,
                    "Equipo↔PC permite swap 1↔1, enviar al PC y ocupar hueco libre; usa PartyData 0x104 + mirror sparse + BoxPokemon 0xE8 con verificación y rollback.",
                    "USUM party 0x104 + mirror + BoxPokemon 0xE8 · rollback",
                ),
            )
            + ((battle_diagnostic,) if battle_diagnostic is not None else ())
            + ((badge_diagnostic,) if badge_diagnostic is not None else ()),
            sequence=int(sequence),
            metadata={
                "emulator": "AzaharPlus",
                "transport": "RPC UDP",
                "readonly": False,
                "roles_write": True,
                "moves_write": True,
                "inventory_write": True,
                "tm_live": True,
                "pc_read_live": True,
                "pc_write_live": True,
                "pc_write_modes": ("swap-party-box", "party-to-box", "box-to-party"),
                "pc_swap_diagnostic": False,
                "party_base": int(raw.party_base),
            },
        )

    def capture_monitor(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
        sequence: int = 0,
    ) -> RealTimeSnapshot:
        self._last_save_path = Path(save_path) if save_path is not None else self._last_save_path
        raw = self.reader.read_monitor(current, memory_blocks=memory_requests)

        # Alpha.41: la salud de batalla es un carril independiente. Nunca se
        # incluye en la doble captura estable de party porque cambia durante la
        # animación y no debe tumbar el monitor principal.
        started = time.perf_counter()
        try:
            probe = self.reader.read_battle_probe(raw.game)
        except Exception as exc:
            probe = None
            probe_error = str(exc) or "Fallo al leer PS de batalla USUM."
        else:
            probe_error = ""
        elapsed = (time.perf_counter() - started) * 1000

        if probe is None:
            battle = BattleState("unknown")
            diagnostic = LiveDiagnostic(
                "battle", DiagnosticLevel.WARNING,
                probe_error or "La sonda de batalla USUM no respondió; sigue activo el fallback post-combate.",
                "AzaharPlus RPC · carril independiente", elapsed,
            )
        else:
            state = str(getattr(probe, "state", "unknown") or "unknown")
            validated = bool(getattr(probe, "validated", False))
            battle = BattleState(
                state=state,
                health_game=getattr(probe, "health_game", None),
                hp_pairs=tuple(getattr(probe, "hp_pairs", ()) or ()),
            )
            if state == "battle" and not validated:
                level = DiagnosticLevel.WARNING
                message = (
                    "Combate detectado, pero los PS no superaron la validación contra la party PK7; "
                    "RoleRun no los usará. " + str(getattr(probe, "reason", "") or "")
                )
            else:
                level = DiagnosticLevel.OK
                message = (
                    "Combate activo · PS visibles validados contra la party PK7 live."
                    if state == "battle" else
                    "Fuera de combate · flag USUM validado."
                )
            diagnostic = LiveDiagnostic(
                "battle", level, message,
                "USUM battle flag + displayed/max/actual HP", elapsed,
            )

        # Alpha.42: MEDALLAS usa progreso persistente, no el final del combate.
        # Leemos un valor absoluto 0..4 desde los Z-Crystals de Gran Prueba.
        # Dentro de combate solo se permiten rutas rápidas ya demostradas: un
        # descubrimiento estructural FCRAM pesado nunca puede retrasar el carril
        # de PS que alpha.41 necesita a ~250 ms.
        badge_started = time.perf_counter()
        try:
            badges = self.writer.read_kahuna_badges_for_game(
                raw.game, self._last_save_path or save_path,
                party_base=int(raw.party_base),
                allow_full_scan=(str(getattr(battle, "state", "unknown")) != "battle"),
            )
            badge_source = self.writer.last_badge_source
            badge_error = ""
        except Exception as exc:
            badges = None
            badge_source = self.writer.last_badge_source
            badge_error = str(exc) or "Fallo al leer progreso de Kahunas."
        badge_elapsed = (time.perf_counter() - badge_started) * 1000
        badge_diagnostic = LiveDiagnostic(
            "badges",
            DiagnosticLevel.OK if badges is not None else DiagnosticLevel.WARNING,
            (
                f"Grandes Pruebas detectadas: {int(badges)}/4."
                if badges is not None else
                (badge_error or "No se obtuvo un progreso de Kahunas validado en esta muestra.")
            ),
            str(badge_source or "USUM · Z-Crystals"),
            badge_elapsed,
        )
        return self._convert(
            raw, sequence=sequence, battle=battle, battle_diagnostic=diagnostic,
            badges=badges, badge_source=badge_source, badge_diagnostic=badge_diagnostic,
        )

    def capture_full(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
        sequence: int = 0,
    ) -> RealTimeSnapshot:
        self._last_save_path = Path(save_path) if save_path is not None else self._last_save_path
        raw = self.reader.read(current, memory_blocks=memory_requests)

        # Alpha.57: la sincronización inicial también demuestra el estado de
        # combate. Antes capture_full dejaba BattleState=unknown y la UI esperaba
        # al primer monitor (~950 ms). Si la primera batalla/KO ocurría antes de
        # esa muestra, el primer HP de batalla se convertía en baseline y podía
        # tragarse la primera muerte. Leer aquí el mismo flag seguro permite
        # distinguir desde el arranque "fuera de combate" de "ya estaba dentro".
        started = time.perf_counter()
        try:
            probe = self.reader.read_battle_probe(raw.game)
        except Exception as exc:
            probe = None
            probe_error = str(exc) or "Fallo al leer PS de batalla USUM."
        else:
            probe_error = ""
        elapsed = (time.perf_counter() - started) * 1000

        if probe is None:
            battle = BattleState("unknown")
            diagnostic = LiveDiagnostic(
                "battle", DiagnosticLevel.WARNING,
                probe_error or "La sonda de batalla USUM no respondió durante la sincronización inicial.",
                "AzaharPlus RPC · baseline inicial", elapsed,
            )
        else:
            state = str(getattr(probe, "state", "unknown") or "unknown")
            validated = bool(getattr(probe, "validated", False))
            battle = BattleState(
                state=state,
                health_game=getattr(probe, "health_game", None),
                hp_pairs=tuple(getattr(probe, "hp_pairs", ()) or ()),
            )
            if state == "battle" and not validated:
                level = DiagnosticLevel.WARNING
                message = (
                    "RoleRun se conectó dentro de un combate, pero los PS iniciales no quedaron "
                    "demostrados; la primera muestra válida solo establecerá baseline. "
                    + str(getattr(probe, "reason", "") or "")
                )
            else:
                level = DiagnosticLevel.OK
                message = (
                    "Conexión inicial dentro de combate · baseline de PS demostrado."
                    if state == "battle" else
                    "Conexión inicial fuera de combate · baseline preparado."
                )
            diagnostic = LiveDiagnostic(
                "battle", level, message,
                "USUM battle flag · baseline inicial", elapsed,
            )

        return self._convert(
            raw, sequence=sequence, battle=battle, battle_diagnostic=diagnostic,
        )

    def read_pc(self, anchors, *, box_count: int | None = None, box_slot_count: int | None = None):
        if self._last_game is None:
            raise USUMLiveError("UltraSol/UltraLuna todavía no tiene una captura viva validada. Entra al overworld y pulsa F5.")
        if self._last_save_path is None:
            raise USUMLiveError("Falta el main testigo para demostrar el PC vivo de UltraSol/UltraLuna.")
        if box_count is None or box_slot_count is None:
            raise USUMLiveError("Faltan las dimensiones de cajas que PKHeX ha leído del guardado real.")
        return self.writer.read_pc_for_game(
            self._last_game, self._last_save_path, anchors,
            box_count=int(box_count), box_slot_count=int(box_slot_count),
        )

    def read_tm_inventory(self, saved_items=None, *, save_path: Path | str | None = None):
        if self._last_game is None:
            raise USUMLiveError("UltraSol/UltraLuna todavía no tiene una captura viva validada. Entra al overworld y pulsa F5.")
        if save_path is None:
            raise USUMLiveError("Falta el main testigo para demostrar la mochila viva de UltraSol/UltraLuna.")
        return self.writer.read_tm_inventory_for_game(self._last_game, save_path)

    @staticmethod
    def _inverse_role_change(change: PendingRoleChange) -> PendingRoleChange:
        return PendingRoleChange(
            pokemon_slot=int(change.pokemon_slot),
            pokemon=str(change.pokemon),
            species=str(change.species),
            old_role=str(change.new_role),
            new_role=str(change.old_role),
            pokemon_identity=str(change.pokemon_identity or ""),
        )

    def _apply_serialized_role_changes(
        self, current: SaveGameData, changes: Sequence[PendingRoleChange],
    ) -> USUMLiveWriteResult:
        """Aplica swaps de marcadores como escrituras unitarias ya validadas.

        En la prueba real de alpha.5, una escritura PK7 individual de rol quedó
        confirmada pero un intercambio de dos marcadores enviado como un único
        lote no fue estable en Azahar. No inventamos otro layout: reutilizamos la
        operación individual ya demostrada y recapturamos la party entre pasos.

        Si falla un paso posterior, se compensan en orden inverso todos los pasos
        que sí llegaron a confirmarse. Si esa compensación tampoco puede
        verificarse, se eleva un error explícito en vez de afirmar atomicidad.
        """
        game = current
        applied: list[PendingRoleChange] = []
        process = None
        attempts = 0
        already_applied = True
        try:
            for change in changes:
                result = self.writer.apply(game, [change])
                game = result.game
                process = result.process
                attempts = max(attempts, int(result.attempts))
                already_applied = already_applied and bool(result.already_applied)
                applied.append(change)
        except Exception as exc:
            compensation_errors: list[str] = []
            for previous in reversed(applied):
                inverse = self._inverse_role_change(previous)
                try:
                    rollback = self.writer.apply(game, [inverse])
                    game = rollback.game
                    process = rollback.process
                    attempts = max(attempts, int(rollback.attempts))
                except Exception as rollback_exc:
                    compensation_errors.append(
                        f"{previous.pokemon or previous.species}: {rollback_exc}"
                    )
            if compensation_errors:
                raise USUMLiveError(
                    "El intercambio de roles de UltraSol/UltraLuna falló y RoleRun no pudo "
                    "confirmar toda la compensación: " + "; ".join(compensation_errors)
                    + f". Error original: {exc}"
                ) from exc
            if applied:
                raise USUMLiveError(
                    f"El intercambio de roles de UltraSol/UltraLuna falló en el paso {len(applied) + 1}; "
                    "los cambios anteriores se revirtieron y verificaron. "
                    f"Error original: {exc}"
                ) from exc
            raise

        if process is None:
            raise USUMLiveError("No se llegó a aplicar ningún cambio de rol en UltraSol/UltraLuna.")
        return USUMLiveWriteResult(
            game=game, process=process, attempts=attempts,
            applied_count=len(changes), already_applied=already_applied,
        )

    def apply_changes(self, current: SaveGameData, changes):
        # alpha.12 conserva la semántica conjunta de alpha.4: un intercambio de
        # dos roles se prepara y verifica como UNA única transacción del writer.
        # La serialización introducida en alpha.7 creaba un estado intermedio que
        # no existía en la última build validada físicamente por el usuario.
        return self.writer.apply(current, list(changes))

    def runtime_state(self) -> dict[str, object]:
        return {
            "adapter": self.key,
            "game": self.game_key,
            "bridge": {
                "key": self.bridge.info.key,
                "display_name": self.bridge.info.display_name,
                "transport": self.bridge.info.transport,
            },
            "process_key": list(self._last_process_key) if self._last_process_key else None,
            "party_base": self._last_party_base,
            "reader": self.reader.runtime_state(),
            "pc_resolution": dict(getattr(self.writer, "_pc_last_resolution", {}) or {}),
            "capabilities": {
                "party": "candidate-usum-pk7-runtime-identity-validated",
                "roles": "candidate-usum-content-validated-host-fcram",
                "moves_write": "candidate-usum-content-validated-host-fcram",
                "battle": "candidate-usum-flag-displayed-hp-maxhp-runtime-validated",
                "progress": "candidate-usum-kahuna-zcrystals-runtime-validated",
                "pc": "candidate-usum-structural-pk7-host-guest-proof-before-write",
                "tm_inventory": "candidate-usum-rom-effective-plus-structural-bag",
                "tm_teach": "candidate-usum-pk7-reusable-verify-rollback",
                "inventory_utilities": "candidate-usum-pkhex-structural-witness-host-fcram",
            },
        }

    def reset_runtime_state(self) -> None:
        self._last_process_key = None
        self._last_party_base = None
        self._last_game = None
        self._last_save_path = None
        self._last_runtime_party_region = None
        self.reader.reset_runtime_state()
        self.writer.reset_runtime_state()
