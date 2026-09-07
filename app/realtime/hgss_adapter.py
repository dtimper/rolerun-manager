from __future__ import annotations

"""Adaptador de tiempo real de HeartGold/SoulSilver sobre melonDS.

De momento **solo lee**. Publica el equipo con sus PS, naturaleza,
estadísticas, IV, EV y marcas; el PC entero; y las medallas del entrenador.
Escribir en cuarta generación es un paso aparte, y hasta que su contrato esté
demostrado la Run sigue guardándose por el motor de siempre.

DOS COSAS PROPIAS DE CUARTA QUE ESTE ADAPTADOR TIENE QUE RESPETAR

* **La naturaleza sale del PID**, no de un byte. Ya la resuelve `pk4`, pero
  conviene recordarlo: no hay nada que escribir para cambiarla.
* **Los datos de juego se leen de la ROM** cuando melonDS tiene una cargada,
  porque RoleRun se juega en randomizers. Sin ROM se usa la copia de PKHeX, que
  es lo correcto en una partida sin randomizar.
"""

import json
import struct
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from ..boxed_metadata import (
    ability_name, base_stats_for, boxed_level, item_name, species_name,
)
from ..config import LOG_DIR
from ..gen4_memory import MONEY_MAX, PC_BOX_STRIDE
from ..gen4_memory import GEN4_MEMORY, Gen4Memory
from ..hgss_live import (
    FIRMA_LARGO, FIRMA_OFFSET, PC_BOX_SLOT_COUNT, HgssLiveError, HgssMelonDSReader,
)
from ..hgss_tm_service import build_tm_profile
from ..hgss_write import HgssMelonDSWriter, HgssRoleWrite
from ..models import (
    PendingChange, PendingInventoryChange, PendingPartyHeal, PendingRoleChange,
    PendingTeamChange, PendingTMTeach,
)
from ..pk4 import (
    PK4_SANITY, PK4_STORED_SIZE, STAT_ORDER_PERSONAL, parse_pk4_boxed, pk4_party_block,
)

# Bit 2 del campo de sanidad: bandera de HUEVO MALO (ver el comentario de
# `PK4_SANITY` en pk4.py). Vive en la cabecera, fuera del checksum.
_BIT_HUEVO_MALO = 0x0004
from ..pokemon_stats import nature_presentation, stat_dict
from ..role_rules import (
    ROLE_SYMBOLS, ROLE_TO_KEY, ROLE_TO_MARKING, canonical_role,
    role_from_markings,
)
from ..save_engine_client import SaveGameData, SavePokemon
from .adapter import RealTimeGameAdapter
from .models import (
    BattleState, DiagnosticLevel, LiveDiagnostic, LiveProcessInfo, RealTimeSnapshot,
)

PC_BOX_COUNT_HGSS = 18

# Las tres utilidades de la cabecera. El bolsillo no se supone por analogía con
# quinta: PKHeX dice que el Repelente Máximo vive en OBJETOS y el Caramelo Raro
# en MEDICINAS, y meterlos en el equivocado los dejaría invisibles.
HGSS_UTILITY_ITEMS = {
    "rare-candy": 50,
    "max-repel": 77,
}


def _anotar_diagnostico(etapa: str, **datos) -> None:
    """Registro autocontenido, sin depender de `_registrar_intento_vivo`.

    Este módulo (la capa de adaptador) no tiene acceso al registrador de la
    interfaz -vive en otra capa-, así que escribe directamente al mismo
    archivo con el mismo criterio: nunca puede tumbar la operación por
    fallar al escribir.
    """
    try:
        registro = {
            "cuando": datetime.now().isoformat(timespec="milliseconds"),
            "etapa": etapa,
            "juego": "hgss",
            **datos,
        }
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "escrituras_vivas.jsonl").open("a", encoding="utf-8") as salida:
            salida.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _anotar_diagnostico_box_to_party(**datos) -> None:
    """Registro para el cuarto incidente de "box-to-party" (06-09-2026)."""
    _anotar_diagnostico("hgss-diagnostico-box-to-party", **datos)


@dataclass(frozen=True, slots=True)
class HgssRealTimeWriteResult:
    game: SaveGameData
    process: object
    attempts: int
    applied_count: int
    memory_watches: tuple = ()
    already_applied: bool = False


class HgssRealTimeAdapter(RealTimeGameAdapter):
    """Lectura viva de HeartGold dentro de melonDS."""

    key = "hgss-melonds-v026"
    game_key = "hgss"
    display_name = "Pokémon Oro HeartGold / Plata SoulSilver"

    def __init__(
        self, reader=None, role_layout_getter=None, rom_getter=None,
        memory: Gen4Memory | None = None, save_path_getter=None,
    ) -> None:
        descriptor = memory or (
            getattr(reader, "memory", None) or GEN4_MEMORY["hgss"]
        )
        self.memory = descriptor
        # Con qué se reconoce el bloque del guardado dentro de la RAM: el
        # nombre del entrenador y sus identificadores, que no cambian jugando.
        # Sin esto no se puede localizar, y la dirección no es fija.
        self.save_path_getter = save_path_getter or (lambda: None)
        self.reader = reader or HgssMelonDSReader(
            descriptor, firma_getter=self._firma_del_entrenador,
        )
        self.writer = HgssMelonDSWriter(self.reader)
        self.role_layout_getter = role_layout_getter or (lambda: 2)
        # DIAGNÓSTICO TEMPORAL 06-09-2026: el usuario reportó que el daño y
        # el desmayo no se ven en vivo pese al arreglo de identidad
        # ambigua. Registra cada vez que CAMBIA el estado de la sonda de
        # combate -no en cada sondeo, para no inundar el log- para ver la
        # secuencia real de un combate.
        self._diag_ultimo_estado_batalla: object = object()
        # Datos de juego leídos de la ROM que melonDS tiene cargada.
        self.rom_getter = rom_getter or (lambda: None)
        ruta = Path(__file__).resolve().parents[2] / "data" / "move_catalog.json"
        try:
            crudo = json.loads(ruta.read_text(encoding="utf-8-sig"))
            self.move_names = {
                int(item["id"]): str(item.get("name_es") or item.get("name_en"))
                for item in crudo.get("moves", [])
            }
        except Exception:
            self.move_names = {}
        # PP base de cuarta, extraídos del mismo PKHeX.Core que usa el motor de
        # guardados. Comprobados contra la ROM real: coinciden en los 467.
        #
        # Sin esto, curar dependía de que la ROM estuviera cargada, y cuando no
        # lo estaba la curación fallaba entera con «no se conocen los PP base
        # del movimiento #44». Con la ROM delante manda ella —un randomizer
        # puede cambiarlos—; sin ella, esto es lo correcto.
        ruta_pp = Path(__file__).resolve().parents[2] / "data" / "gen4_move_pp.json"
        try:
            crudo_pp = json.loads(ruta_pp.read_text(encoding="utf-8-sig"))
            self.move_base_pp = {
                int(clave): int(valor)
                for clave, valor in dict(crudo_pp.get("pp", {})).items()
                if int(valor) > 0
            }
        except Exception:
            self.move_base_pp = {}

    def _firma_del_entrenador(self) -> bytes | None:
        """Los veinte bytes con los que se reconoce el bloque del guardado."""
        ruta = self.save_path_getter()
        if not ruta:
            return None
        try:
            with Path(ruta).open("rb") as archivo:
                archivo.seek(FIRMA_OFFSET)
                firma = archivo.read(FIRMA_LARGO)
        except OSError:
            return None
        return firma if len(firma) == FIRMA_LARGO else None

    # ------------------------------------------------------------------
    # Identidad
    # ------------------------------------------------------------------

    @staticmethod
    def _strong_identity(pokemon) -> tuple[int, int, int]:
        """La terna que identifica a un Pokémon dentro de la partida."""
        return int(pokemon.pid or 0), int(pokemon.tid or 0), int(pokemon.sid or 0)

    @staticmethod
    def _run_identity(miembro) -> str:
        """La misma identidad que usa ``RunProjectService.pokemon_identity_key``.

        No se reinventa el formato: si el adaptador usara otro, un cambio de rol
        no encontraría nunca a su Pokémon.
        """
        return (
            f"{int(miembro.species_id)}:{int(miembro.pid)}:"
            f"{int(miembro.tid)}:{int(miembro.sid)}"
        )

    def read_tm_profile(self):
        """Qué enseña cada MT **en esta partida**, leído del juego.

        No hay ROM que pedir ni archivo que cargar: la lista vive en la RAM, y
        es la única fuente correcta jugando en randomizers.
        """
        movimientos = self.reader.read_tm_table()
        rom = self.rom_getter()
        origen = f"melonDS · 0x{self.memory.tm_table:08X}"
        if rom is not None:
            origen = f"{rom.name} · {origen}"
        return build_tm_profile(movimientos, source=origen, rom=rom)

    def read_tm_inventory(self, saved_items=None, *, save_path=None):
        """La mochila viva completa, MT incluidas.

        ``saved_items`` es solo un testigo de diagnóstico: una diferencia con el
        guardado es lo normal en cuanto el jugador coge o gasta un objeto.
        """
        del save_path, saved_items      # la mochila vive en el proceso
        party_read = self.reader.read_party()
        mochila = self.reader.read_bag(party_read)
        return (
            dict(mochila.items),
            LiveProcessInfo(
                "melonDS", party_read.process_id, 0, party_read.process_name,
            ),
            1,
        )

    def _localizar(self, party_read, change, que: str):
        """El único miembro del equipo con la identidad que pide el cambio."""
        identidad = str(getattr(change, "pokemon_identity", "") or "")
        candidatos = [
            (indice, miembro) for indice, miembro in enumerate(party_read.pokemon)
            if self._run_identity(miembro) == identidad
        ]
        if len(candidatos) != 1:
            raise HgssLiveError(
                f"El Pokémon de {que} no está de forma única en el equipo de HeartGold."
            )
        return candidatos[0]

    def base_pp_for(self, move_id: int) -> int:
        """PP del movimiento en **esta** partida. Cero significa «no demostrado».

        Con la ROM delante manda ella: un randomizer puede cambiar los PP, y
        curar con el valor original dejaría el PP mal escrito. Sin ROM se usa la
        tabla de cuarta de PKHeX, que es lo correcto en una partida sin
        randomizar y evita que la curación falle entera por no tenerla.
        """
        rom = self.rom_getter()
        if rom is not None:
            desde_rom = int(rom.base_pp(int(move_id)))
            if desde_rom > 0:
                return desde_rom
        return int(self.move_base_pp.get(int(move_id), 0))

    def _move_names_for(self, move_ids) -> list[str]:
        return [
            self.move_names.get(
                move_id, "—" if move_id == 0 else f"Movimiento #{move_id}",
            )
            for move_id in move_ids
        ]

    def _presentar(
        self, pokemon, anterior, *, level: int, stats,
        slot: int | None = None, box: int | None = None, box_slot: int | None = None,
    ) -> SavePokemon:
        """Traduce un PK4 leído a lo que RoleRun enseña por pantalla."""
        marcas = list(pokemon.markings)
        rol, simbolo = role_from_markings(
            marcas, layout=int(self.role_layout_getter()),
        )
        # Cuarta sigue siendo de solo lectura: una Run existente puede tener
        # roles que todavía no se han podido grabar en las marcas del PK4. Una
        # marca única viva sí es evidencia; cero o varias no deben borrar el rol
        # que la Run ya tenía guardado.
        if rol == "SIN ROL" and anterior is not None and anterior.role:
            marcas = list(anterior.markings)
            rol, simbolo = anterior.role, anterior.role_symbol
        naturaleza = nature_presentation(pokemon.nature_id)
        especie = species_name(pokemon.species_id)
        if especie.startswith("Especie #") and pokemon.nickname:
            especie = pokemon.nickname
        base_binario = base_stats_for(self.game_key, pokemon.species_id, pokemon.form)
        base_visible = tuple(base_binario[indice] for indice in (0, 1, 2, 4, 5, 3))
        return SavePokemon(
            slot=pokemon.slot if slot is None else int(slot),
            box=box,
            box_slot=box_slot,
            species_id=pokemon.species_id,
            species=especie,
            nickname=pokemon.nickname or especie,
            level=level,
            held_item=item_name(pokemon.held_item_id),
            ability=ability_name(pokemon.ability_id),
            moves=self._move_names_for(pokemon.move_ids),
            move_ids=list(pokemon.move_ids),
            is_egg=pokemon.is_egg,
            markings=marcas,
            role=rol,
            role_symbol=simbolo,
            pid=pokemon.pid,
            tid=pokemon.tid,
            sid=pokemon.sid,
            form=pokemon.form,
            current_hp=pokemon.current_hp,
            max_hp=pokemon.max_hp,
            status_condition=pokemon.status_condition,
            nature_id=pokemon.nature_id,
            stat_nature_id=pokemon.nature_id,
            nature=naturaleza.name if naturaleza else "",
            stat_nature=naturaleza.name if naturaleza else "",
            nature_increased=naturaleza.increased if naturaleza else None,
            nature_decreased=naturaleza.decreased if naturaleza else None,
            base_stats=stat_dict(base_visible),
            stats=stat_dict(stats),
            ivs=stat_dict(pokemon.ivs),
            evs=stat_dict(pokemon.evs),
        )

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    def _capture(self, current: SaveGameData, sequence: int) -> RealTimeSnapshot:
        crudo = self.reader.read_party()
        anclas = {self._strong_identity(p): p for p in current.party}
        vivos = {(p.pid, p.tid, p.sid) for p in crudo.pokemon}
        if not anclas or anclas.keys().isdisjoint(vivos):
            raise HgssLiveError(
                "El equipo vivo de melonDS no coincide con ninguna identidad fuerte "
                "del guardado de HeartGold activo. No se publicó la lectura."
            )

        equipo = [
            self._presentar(
                pokemon,
                anclas.get((pokemon.pid, pokemon.tid, pokemon.sid)),
                # El PK4 de combate SÍ trae el nivel y las estadísticas ya
                # calculadas por el juego. No hay que recalcular nada: se
                # publica lo que el jugador ve.
                level=pokemon.level,
                stats=pokemon.stats,
            )
            for pokemon in crudo.pokemon
        ]

        juego = SaveGameData(
            "HG", "SAV4HGSS", 4, current.trainer, equipo,
            {
                **dict(current.raw or {}),
                "live_source": "melonDS host RAM · HeartGold party nominal",
                "writes_enabled": False,
            },
        )

        # Medallas: dos bytes, Johto y Kanto. Si no se pueden leer no se inventa
        # un cero, que sería indistinguible de no tener ninguna.
        medallas = None
        try:
            entrenador = self.reader.read_trainer(crudo)
            medallas = int(entrenador.badge_count)
            diagnostico_medallas = LiveDiagnostic(
                "badges", DiagnosticLevel.OK,
                f"Medallas detectadas: {medallas} "
                f"(Johto 0b{entrenador.badges_johto:08b}, "
                f"Kanto 0b{entrenador.badges_kanto:08b}).",
                f"0x{self.memory.badges:08X} + 0x{self.memory.badges_kanto:08X}",
            )
        except Exception as exc:
            diagnostico_medallas = LiveDiagnostic(
                "badges", DiagnosticLevel.WARNING,
                str(exc) or "Fallo al leer medallas.",
                f"0x{self.memory.badges:08X}",
            )

        # Carril de combate: solo el que está en el campo (localizado el
        # 06-09-2026, ver `HgssMelonDSReader.read_battle_probe`). Los demás
        # conservan los PS del bloque de equipo, marcados como no medidos.
        try:
            lectura_batalla = self.reader.read_battle_probe(crudo)
        except Exception as exc:
            lectura_batalla = None
            _resumen_diag = ("excepcion", str(exc))
        else:
            _resumen_diag = (
                None if lectura_batalla is None else lectura_batalla.state,
                None if lectura_batalla is None else lectura_batalla.party_slot,
                None if lectura_batalla is None else lectura_batalla.current_hp,
                None if lectura_batalla is None else lectura_batalla.max_hp,
            )
        # DIAGNÓSTICO TEMPORAL 07-09-2026: sin deduplicar. Vuelve a hacer
        # falta -la versión deduplicada de abajo no distingue "no hay
        # transiciones porque va todo bien" de "no hay transiciones porque
        # nunca llegó a resolverse nada"-. Quitar en cuanto se confirme el
        # arreglo de los dos ceros seguidos.
        self._diag_contador_sondeos = getattr(self, "_diag_contador_sondeos", 0) + 1
        _anotar_diagnostico(
            "hgss-sondeo-crudo", n=self._diag_contador_sondeos,
            resumen=list(_resumen_diag),
            barrido=getattr(self.reader, "_diag_ultimo_barrido", None),
            party_max_hp=[int(p.max_hp) for p in crudo.pokemon],
            confirmada=getattr(self.reader, "_battle_hp_ubicacion_confirmada", None),
            cero_desde=getattr(self.reader, "_battle_confirmada_cero_desde", None),
        )
        # DIAGNÓSTICO TEMPORAL 06-09-2026: solo cuando cambia, no en cada
        # sondeo -evita inundar el log durante un combate largo, pero deja
        # ver la secuencia completa de estados-.
        if _resumen_diag != self._diag_ultimo_estado_batalla:
            self._diag_ultimo_estado_batalla = _resumen_diag
            _anotar_diagnostico(
                "hgss-diagnostico-combate", resumen=list(_resumen_diag),
            )

        if lectura_batalla is None:
            battle = BattleState("unknown")
            diagnostico_batalla = LiveDiagnostic(
                "battle", DiagnosticLevel.WARNING,
                "La sonda de combate de HeartGold no respondió.",
                f"0x{self.memory.battle_hp_primary:08X} + 0x{self.memory.battle_hp_secondary:08X}",
            )
        elif lectura_batalla.state == "none":
            battle = BattleState("none")
            diagnostico_batalla = LiveDiagnostic(
                "battle", DiagnosticLevel.OK,
                "Fuera de combate; el carril de HeartGold está a cero.",
                f"0x{self.memory.battle_hp_primary:08X} + 0x{self.memory.battle_hp_secondary:08X}",
            )
        elif lectura_batalla.state == "battle" and lectura_batalla.party_slot is not None:
            health_party = [
                replace(
                    member,
                    current_hp=lectura_batalla.current_hp,
                    max_hp=lectura_batalla.max_hp,
                    hp_is_live=True,
                ) if member.slot == lectura_batalla.party_slot
                else replace(member, hp_is_live=False)
                for member in juego.party
            ]
            health_game = replace(juego, party=health_party)
            battle = BattleState(
                "battle", health_game=health_game,
                hp_pairs=((lectura_batalla.current_hp, lectura_batalla.max_hp),),
            )
            diagnostico_batalla = LiveDiagnostic(
                "battle", DiagnosticLevel.OK,
                f"PS en combate: {lectura_batalla.current_hp}/{lectura_batalla.max_hp} "
                f"(hueco {lectura_batalla.party_slot}). El resto conserva el bloque de "
                "equipo, no medido en vivo.",
                f"0x{self.memory.battle_hp_primary:08X} + 0x{self.memory.battle_hp_secondary:08X} redundantes",
            )
        else:
            # "unknown": instante de transición o PS máximo ambiguo entre dos
            # miembros. No se inventa nada; el llamador conserva lo anterior.
            battle = BattleState("unknown")
            diagnostico_batalla = LiveDiagnostic(
                "battle", DiagnosticLevel.WARNING,
                "Combate detectado pero el instante no se pudo confirmar.",
                f"0x{self.memory.battle_hp_primary:08X} + 0x{self.memory.battle_hp_secondary:08X}",
            )

        diagnosticos = (
            LiveDiagnostic(
                "party", DiagnosticLevel.OK,
                f"Equipo de HeartGold validado ({crudo.count}/6), con estado, "
                "naturaleza, estadísticas, IV, EV, PP y marcas.",
                "PK4 nominal · doble lectura + checksum + identidad · PKHeX PK4",
            ),
            diagnostico_batalla,
            diagnostico_medallas,
        )

        return RealTimeSnapshot(
            juego,
            LiveProcessInfo("melonDS", crudo.process_id, 0, crudo.process_name),
            1,
            self.key,
            "HeartGold España · melonDS",
            battle=battle,
            diagnostics=diagnosticos,
            sequence=sequence,
            badges=medallas,
            badge_source=f"melonDS vivo · 0x{self.memory.badges:08X}",
        )

    def capture_monitor(
        self, current, *, save_path, memory_requests=(), sequence=0,
    ):
        return self._capture(current, sequence)

    def capture_full(
        self, current, *, save_path, memory_requests=(), sequence=0,
    ):
        return self._capture(current, sequence)

    def read_pc(
        self, anchors, *, box_count: int | None = None,
        box_slot_count: int | None = None,
    ):
        if box_count is not None and int(box_count) != PC_BOX_COUNT_HGSS:
            raise HgssLiveError(
                f"HeartGold declara {PC_BOX_COUNT_HGSS} cajas, no {int(box_count)}."
            )
        if box_slot_count is not None and int(box_slot_count) != PC_BOX_SLOT_COUNT:
            raise HgssLiveError(
                f"HeartGold declara {PC_BOX_SLOT_COUNT} huecos por caja, "
                f"no {int(box_slot_count)}."
            )
        party_read = self.reader.read_party()
        crudo = self.reader.read_pc(party_read)

        por_identidad: dict[tuple[int, int, int], list[SavePokemon]] = {}
        for pokemon in anchors or ():
            por_identidad.setdefault(self._strong_identity(pokemon), []).append(pokemon)

        huecos: dict[tuple[int, int], SavePokemon] = {}
        for pokemon in crudo.pokemon:
            caja, hueco = divmod(pokemon.slot, PC_BOX_SLOT_COUNT)
            coincidencias = por_identidad.get((pokemon.pid, pokemon.tid, pokemon.sid), ())
            anterior = coincidencias[0] if len(coincidencias) == 1 else None
            # Un PK4 almacenado no lleva nivel: sale de la experiencia con la
            # curva que declara su especie.
            nivel = boxed_level(
                self.game_key, pokemon.species_id, pokemon.form, pokemon.experience,
            )
            base = base_stats_for(self.game_key, pokemon.species_id, pokemon.form)
            huecos[(caja + 1, hueco + 1)] = self._presentar(
                pokemon, anterior, level=nivel,
                stats=self._calculated_stats(
                    base, pokemon.ivs, pokemon.evs, nivel, pokemon.nature_id,
                ),
                slot=hueco + 1, box=caja + 1, box_slot=hueco + 1,
            )
        return party_read, crudo.guest_base, huecos

    @staticmethod
    def _calculated_stats(base, ivs, evs, level: int, nature_id: int) -> tuple[int, ...]:
        """Las seis estadísticas de un Pokémon del PC, que no las trae escritas.

        ``base`` viene en el orden de la tabla personal (PS/Atk/Def/Vel/AtEsp/
        DefEsp) y los IV/EV en el de RoleRun (PS/Atk/Def/AtEsp/DefEsp/Vel).
        """
        binario = tuple(int(valor) for valor in base)
        visible = tuple(binario[indice] for indice in (0, 1, 2, 4, 5, 3))
        ps = ((2 * visible[0] + ivs[0] + evs[0] // 4) * level) // 100 + level + 10
        naturaleza = nature_presentation(nature_id)
        salida = [ps]
        claves = ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")
        for indice in range(1, 6):
            valor = (
                (2 * visible[indice] + ivs[indice] + evs[indice] // 4) * level
            ) // 100 + 5
            if naturaleza is not None and naturaleza.increased == claves[indice]:
                valor = valor * 110 // 100
            elif naturaleza is not None and naturaleza.decreased == claves[indice]:
                valor = valor * 90 // 100
            salida.append(valor)
        return tuple(salida)

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------

    def _role_write_for(self, party_read, change: PendingRoleChange) -> HgssRoleWrite:
        """Traduce un cambio de rol de RoleRun a una escritura PK4 concreta."""
        hueco, miembro = self._localizar(party_read, change, "el cambio de rol")
        rol = canonical_role(change.new_role)
        marca = ROLE_TO_MARKING.get(rol)
        if marca is None:
            raise HgssLiveError(f"Rol de HeartGold no reconocido: {change.new_role!r}.")
        # Una sola marca gobierna el rol; «SIN ROL» las deja todas a cero. Es el
        # mismo contrato que `role_from_markings` usa al leer.
        marcas = tuple(indice == marca for indice in range(6))
        evs = tuple(int(valor) for valor in (change.new_evs or miembro.evs))
        base = dict(zip(
            STAT_ORDER_PERSONAL,
            base_stats_for(self.game_key, int(miembro.species_id), int(miembro.form)),
        ))
        return HgssRoleWrite(
            slot=hueco,
            identity=(int(miembro.pid), int(miembro.tid), int(miembro.sid)),
            markings=marcas, evs=evs, base_stats=base,
        )

    def _move_target_for(self, party_read, change):
        """Resuelve (miembro, identidad, hueco, movimiento) sin fiarse del slot.

        Sirve igual para un drafteo que para una MT: el índice de equipo que
        traía el cambio puede haber quedado obsoleto, así que se localiza al
        Pokémon por su identidad, como en roles y curación.

        Un movimiento cero significa borrar ese hueco; es lo que necesita un
        Support al perder los ataques de daño que le sobran.
        """
        hueco_equipo, miembro = self._localizar(
            party_read, change, "el cambio de movimiento",
        )
        hueco = int(change.move_slot)
        if not 1 <= hueco <= 4:
            raise HgssLiveError(
                "El hueco de movimiento tiene que estar entre 1 y 4."
            )
        return (
            hueco_equipo, (int(miembro.pid), int(miembro.tid), int(miembro.sid)),
            hueco, int(change.new_move_id),
        )

    def _heal_target_for(self, party_read, change: PendingPartyHeal):
        hueco, miembro = self._localizar(party_read, change, "la curación")
        return hueco, (int(miembro.pid), int(miembro.tid), int(miembro.sid))

    @staticmethod
    def _utility_item_for(change: PendingInventoryChange) -> int:
        """Traduce una utilidad de la cabecera a un objeto demostrado.

        El nombre se contrasta con la tabla de PKHeX antes de escribir: en BDSP
        una utilidad rotulada «Repelente Máximo» acabó modificando el Repelente
        normal, y esta comprobación es lo que impide repetirlo.
        """
        item_id = HGSS_UTILITY_ITEMS.get(str(change.item_key))
        if item_id is None:
            raise HgssLiveError(
                f"La utilidad «{change.item_key}» no tiene objeto demostrado "
                "en HeartGold."
            )
        if str(change.item_name).strip() != item_name(item_id):
            raise HgssLiveError(
                f"La utilidad «{change.item_key}» dice ser «{change.item_name}» "
                f"pero el objeto #{item_id} es «{item_name(item_id)}»."
            )
        return item_id

    def _apply_inventory(self, current: SaveGameData, changes):
        party_read = self.reader.read_party()
        dinero = [item for item in changes if str(item.item_key) == "money-max"]
        objetos = [item for item in changes if str(item.item_key) != "money-max"]
        if len(dinero) > 1:
            raise HgssLiveError(
                "Dos utilidades de dinero de HeartGold en la misma transacción."
            )
        if objetos:
            self.writer.write_bag_items(party_read, [
                (self._utility_item_for(item), int(item.quantity)) for item in objetos
            ])
        if dinero:
            cantidad = int(dinero[0].quantity)
            if not 0 <= cantidad <= MONEY_MAX:
                raise HgssLiveError(f"HeartGold admite como máximo {MONEY_MAX} ₽.")
            self.writer.write_money(party_read, cantidad)
        return self._resultado(current, len(list(changes)))

    def _resultado(self, current: SaveGameData, aplicados: int):
        vivo = self._capture(current, 0)
        vivo.game.raw["writes_enabled"] = True
        vivo.game.raw["live_write"] = True
        return HgssRealTimeWriteResult(vivo.game, vivo.process, 2, aplicados)

    def apply_changes(self, current: SaveGameData, changes):
        """Roles y curación. Lo demás sigue sin writer demostrado en cuarta."""
        cambios = list(changes)
        if not cambios:
            raise HgssLiveError("No hay ningún cambio de HeartGold que aplicar.")

        if all(isinstance(item, PendingInventoryChange) for item in cambios):
            return self._apply_inventory(current, cambios)

        if all(isinstance(item, PendingRoleChange) for item in cambios):
            party_read = self.reader.read_party()
            escrituras = [self._role_write_for(party_read, item) for item in cambios]
            self.writer.write_party_roles(party_read, escrituras)
            return self._resultado(current, len(escrituras))

        # Solo `PendingChange`, que es el drafteo y el borrado. Las MT quedan
        # fuera a propósito: **en cuarta generación se gastan al enseñarlas**,
        # al contrario que en quinta. Escribir el movimiento sin descontar el
        # objeto le regalaría la MT al jugador, y la mochila de HeartGold
        # todavía no está mapeada.
        if all(isinstance(item, PendingTMTeach) for item in cambios):
            party_read = self.reader.read_party()
            perfil = self.read_tm_profile()
            ensenanzas = []
            for item in cambios:
                hueco_equipo, identidad, hueco, move_id = self._move_target_for(
                    party_read, item,
                )
                tm = next(
                    (t for t in perfil.tms.values() if t.move_id == move_id), None,
                )
                if tm is None:
                    raise HgssLiveError(
                        f"Ninguna MT de esta partida enseña el movimiento "
                        f"#{move_id}."
                    )
                ensenanzas.append((hueco_equipo, identidad, hueco, move_id, tm.item_id))
            self.writer.write_tm_teach(
                party_read, ensenanzas, base_pp_for=self.base_pp_for,
            )
            return self._resultado(current, len(ensenanzas))

        if all(isinstance(item, PendingChange) for item in cambios):
            party_read = self.reader.read_party()
            ensenanzas = [self._move_target_for(party_read, item) for item in cambios]
            self.writer.write_party_moves(
                party_read, ensenanzas, base_pp_for=self.base_pp_for,
            )
            return self._resultado(current, len(ensenanzas))

        if all(isinstance(item, PendingPartyHeal) for item in cambios):
            party_read = self.reader.read_party()
            objetivos = [self._heal_target_for(party_read, item) for item in cambios]
            self.writer.write_party_heal(
                party_read, objetivos, base_pp_for=self.base_pp_for,
            )
            return self._resultado(current, len(objetivos))

        if len(cambios) == 1 and isinstance(cambios[0], PendingTeamChange):
            return self._aplicar_equipo_pc(current, cambios[0])

        raise HgssLiveError(
            "Esa operación todavía no tiene writer demostrado en HeartGold."
        )

    # ------------------------------------------------------------------
    # Equipo ↔ PC
    # ------------------------------------------------------------------

    def _party_block(self, stored: bytes, pokemon) -> bytes:
        """Construye el bloque de combate de un Pokémon que sale del PC.

        Un PK4 guardado no lleva nivel ni estadísticas: las calcula el juego al
        sacarlo, y aquí se calculan con la misma tabla personal que usa el resto
        de RoleRun —la de la ROM si la partida está randomizada—.
        """
        base = base_stats_for(self.game_key, pokemon.species_id, pokemon.form)
        nivel = boxed_level(
            self.game_key, pokemon.species_id, pokemon.form, pokemon.experience,
        )
        estadisticas = self._calculated_stats(
            base, pokemon.ivs, pokemon.evs, nivel, pokemon.nature_id,
        )
        construido = pk4_party_block(
            stored, pid=pokemon.pid, level=nivel, stats=estadisticas,
        )
        # DIAGNÓSTICO TEMPORAL 06-09-2026: cuarto incidente real, sin causa
        # encontrada por reproducción sintética -ver el comentario de
        # `_anotar_diagnostico_box_to_party`-. Captura los valores reales del
        # próximo intento en vivo para poder comparar contra lo que ya se
        # probó a mano.
        _anotar_diagnostico_box_to_party(
            especie=int(pokemon.species_id), forma=int(pokemon.form),
            pid=int(pokemon.pid), experiencia=int(pokemon.experience),
            nivel_calculado=nivel, base_stats=list(base),
            ivs=list(pokemon.ivs), evs=list(pokemon.evs),
            naturaleza=int(pokemon.nature_id), estadisticas_calculadas=list(estadisticas),
            stored_hex=stored.hex(), construido_hex=construido.hex(),
        )
        return construido

    @staticmethod
    def _identidad_de(instantanea) -> tuple[int, int, int]:
        datos = dict(instantanea or {})
        return tuple(int(datos.get(clave, 0) or 0) for clave in ("pid", "tid", "sid"))

    def _pc_en(self, pc_read, box: int, box_slot: int):
        """El Pokémon que hay en esa caja y ese hueco, con sus bytes."""
        offset = (
            (int(box) - 1) * PC_BOX_STRIDE
            + (int(box_slot) - 1) * PK4_STORED_SIZE
        )
        if not 0 <= offset <= len(pc_read.raw) - PK4_STORED_SIZE:
            raise HgssLiveError("Ese hueco del PC está fuera de rango.")
        guardado = pc_read.raw[offset:offset + PK4_STORED_SIZE]
        return parse_pk4_boxed(guardado, 0), guardado

    def _pc_en_confirmado(self, party_read, box: int, box_slot: int):
        """Como ``_pc_en``, pero exige dos lecturas independientes de acuerdo.

        06-09-2026, corrupción real: sacar un Pokémon del PC al equipo dejó
        un Huevo malo de verdad en la partida del usuario -no solo
        estadísticas raras, el propio juego lo marcó así-, con un solo
        intento y una sola lectura del PC de por medio, sin la protección
        que ya se le dio a los cambios de rol tras el incidente de Gastly
        (extensión de combate sin checksum propio, ver
        ``HgssMelonDSWriter._transaccion_de_equipo``). El PK4 guardado SÍ
        lleva checksum -``parse_pk4_boxed`` ya se niega ante uno roto-, pero
        eso no cubre una lectura que atrapó al juego a mitad de escribir algo
        ahí mismo y aun así dio un checksum válido para un contenido que ya
        no es el que se creía. Exigir que dos lecturas del PC, separadas en
        el tiempo, decodifiquen exactamente lo mismo cierra esa ventana con
        el mismo criterio, aunque no se haya podido demostrar que esta fuera
        la causa exacta de aquel Huevo malo.
        """
        primera, crudo1 = self._pc_en(self.reader.read_pc(party_read), box, box_slot)
        segunda, crudo2 = self._pc_en(self.reader.read_pc(party_read), box, box_slot)
        if primera != segunda:
            raise HgssLiveError(
                "Ese hueco del PC dio dos lecturas distintas seguidas; no se "
                "mueve nada sobre un dato que todavía no se ha demostrado estable."
            )
        # El bit de HUEVO MALO en sí (06-09-2026, sexto incidente: un Hoothoot
        # que se leía y mostraba perfectamente normal -checksum válido, nivel
        # y estadísticas coherentes- resultó ser un Huevo malo de verdad en la
        # partida guardada). `Pk4Pokemon` no expone este campo -vive en la
        # cabecera, fuera del checksum, y ninguna comparación de contenido lo
        # ve-, así que se mira aparte en los bytes crudos de las dos lecturas.
        if segunda is not None and (
            struct.unpack_from("<H", crudo1, PK4_SANITY)[0] & _BIT_HUEVO_MALO
            or struct.unpack_from("<H", crudo2, PK4_SANITY)[0] & _BIT_HUEVO_MALO
        ):
            raise HgssLiveError(
                "Ese hueco del PC ya lleva la marca de Huevo malo del propio "
                "juego; no se mueve nada desde ahí."
            )
        return segunda, crudo2

    def _aplicar_equipo_pc(self, current: SaveGameData, change: PendingTeamChange):
        operacion = str(change.operation)
        party_read = self.reader.read_party()
        box, box_slot = int(change.box or 0), int(change.box_slot or 0)

        if operacion == "move-box-slot":
            destino_box = int(change.destination_box or 0)
            destino_slot = int(change.destination_box_slot or 0)
            identidad = self._identidad_de(change.outgoing_snapshot) or ()
            if not any(identidad):
                identidad = self._identidad_de(change.incoming_snapshot)
            if not all(identidad):
                raise HgssLiveError("El traslado dentro del PC no trae identidad.")
            self.writer.move_pc_slot(
                party_read, (box, box_slot), (destino_box, destino_slot),
                expected_identity=identidad,
            )
            return self._resultado_equipo_pc(current, change, 1)

        if operacion == "swap-box-slots":
            destino_box = int(change.destination_box or 0)
            destino_slot = int(change.destination_box_slot or 0)
            # `incoming` es el que se arrastra y acaba en el destino;
            # `outgoing`, el que estaba allí y pasa al hueco de origen.
            identidad_origen = self._identidad_de(change.incoming_snapshot)
            identidad_destino = self._identidad_de(change.outgoing_snapshot)
            if not all(identidad_origen) or not all(identidad_destino):
                raise HgssLiveError(
                    "El intercambio dentro del PC necesita la identidad de los dos Pokémon."
                )
            self.writer.swap_pc_slots(
                party_read, (box, box_slot), (destino_box, destino_slot),
                source_identity=identidad_origen,
                destination_identity=identidad_destino,
            )
            return self._resultado_equipo_pc(current, change, 1)

        if operacion in {"party-to-box", "box-to-party"}:
            party_slot = int(change.party_slot or 0)
            if operacion == "party-to-box":
                identidad = self._identidad_de(change.outgoing_snapshot)
                construido = None
            else:
                entrante, guardado = self._pc_en_confirmado(party_read, box, box_slot)
                if entrante is None:
                    raise HgssLiveError("En ese hueco del PC no hay nadie.")
                if entrante.held_item_id != 0:
                    raise HgssLiveError(
                        "La retirada exige por ahora un entrante sin objeto."
                    )
                identidad = self._identidad_de(change.incoming_snapshot)
                if identidad != (entrante.pid, entrante.tid, entrante.sid):
                    raise HgssLiveError("La identidad del que entra no coincide.")
                construido = self._party_block(guardado, entrante)
            if not all(identidad):
                raise HgssLiveError("Falta la identidad del Pokémon que se mueve.")
            self.writer.resize_party_pc(
                party_read, operation=operacion, party_slot=party_slot,
                box=box, box_slot=box_slot, expected_identity=identidad,
                incoming_party=construido,
            )
            return self._resultado_equipo_pc(current, change, 1)

        if operacion == "swap-party-box":
            party_slot = int(change.party_slot or 0)
            entrante, guardado = self._pc_en_confirmado(party_read, box, box_slot)
            if entrante is None:
                raise HgssLiveError("En ese hueco del PC no hay nadie.")
            if entrante.held_item_id != 0:
                raise HgssLiveError(
                    "El intercambio exige por ahora un entrante sin objeto."
                )
            entra = self._identidad_de(change.incoming_snapshot)
            sale = self._identidad_de(change.outgoing_snapshot)
            if entra != (entrante.pid, entrante.tid, entrante.sid) or not all(sale):
                raise HgssLiveError("Los testigos del intercambio no coinciden.")
            self.writer.swap_party_box(
                party_read, party_slot=party_slot, box=box, box_slot=box_slot,
                outgoing_identity=sale, incoming_identity=entra,
                incoming_party=self._party_block(guardado, entrante),
            )
            return self._resultado_equipo_pc(current, change, 1)

        if operacion == "replace-fainted":
            party_slot = int(change.party_slot or 0)
            tumba_box = int(change.graveyard_box or 0)
            tumba_slot = int(change.graveyard_box_slot or 0)
            if not (tumba_box and tumba_slot):
                raise HgssLiveError(
                    "La sustitución no declara casilla de Cementerio."
                )
            entrante, guardado = self._pc_en_confirmado(party_read, box, box_slot)
            if entrante is None:
                raise HgssLiveError("En ese hueco del PC no hay nadie.")
            if entrante.held_item_id != 0:
                raise HgssLiveError(
                    "La sustitución exige por ahora un sustituto sin objeto."
                )
            entra = self._identidad_de(change.incoming_snapshot)
            sale = self._identidad_de(change.outgoing_snapshot)
            if entra != (entrante.pid, entrante.tid, entrante.sid) or not all(sale):
                raise HgssLiveError("Los testigos de la sustitución no coinciden.")
            self.writer.replace_fainted_party_pc(
                party_read, party_slot=party_slot, box=box, box_slot=box_slot,
                graveyard_box=tumba_box, graveyard_box_slot=tumba_slot,
                incoming_party=self._party_block(guardado, entrante),
                outgoing_identity=sale, incoming_identity=entra,
            )
            return self._resultado_equipo_pc(current, change, 1)

        raise HgssLiveError(
            f"La operación «{operacion}» todavía no tiene writer demostrado "
            "en HeartGold."
        )

    def _resultado_equipo_pc(
        self, current: SaveGameData, change: PendingTeamChange, aplicados: int,
    ):
        """Publica la lectura de después conservando los roles de la Run.

        El que entra hereda el rol de la casilla que deja libre el que sale: es
        la regla nuclear de RoleRun, y cuarta todavía no escribe las marcas, así
        que hay que conservarla aquí.
        """
        vivo = self._capture(current, 0)
        entra = self._identidad_de(change.incoming_snapshot)
        instantanea = dict(change.incoming_snapshot or {})
        miembro = next(
            (p for p in vivo.game.party if (p.pid, p.tid, p.sid) == entra), None,
        )
        if miembro is not None:
            heredado = str(instantanea.get("role", "") or change.incoming_role or "")
            if heredado in ROLE_TO_KEY:
                miembro.role = heredado
                miembro.role_symbol = ROLE_SYMBOLS.get(heredado, "")
        self._restaurar_roles(vivo.game, change.party_role_snapshot)
        vivo.game.raw["writes_enabled"] = True
        vivo.game.raw["live_write"] = True
        return HgssRealTimeWriteResult(vivo.game, vivo.process, 2, aplicados)

    @classmethod
    def _restaurar_roles(cls, game: SaveGameData, roles) -> None:
        """Devuelve a cada miembro el rol que la Run tenía guardado para él."""
        guardados = dict(roles or {})
        for pokemon in game.party:
            clave = (
                f"{int(pokemon.pid or 0)}:{int(pokemon.tid or 0)}:"
                f"{int(pokemon.sid or 0)}"
            )
            rol = str(guardados.get(clave, "") or "")
            if rol in ROLE_TO_KEY:
                pokemon.role = rol
                pokemon.role_symbol = ROLE_SYMBOLS.get(rol, "")

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    def runtime_state(self) -> dict[str, object]:
        return {
            "adapter": self.key,
            "game": self.game_key,
            "anchor": f"0x{self.memory.party_data:08X}",
            "block_base": f"0x{self.reader.memory.block_base:08X}",
            "block_is_live": bool(getattr(self.reader, "block_is_live", False)),
            "writes_enabled": True,
            "writers": ("roles", "heal", "moves", "tm", "bag", "party-pc"),
        }

    def reset_runtime_state(self) -> None:
        self.reader.forget_resolved_base()
