from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .azahar_rpc import AzaharProcess, AzaharRPCClient, AzaharRPCError
from .models import (
    PendingChange,
    PendingRoleChange,
    PendingPCRoleChange,
    PendingInventoryChange,
    PendingPartyHeal,
    PendingTMTeach,
    PendingTeamChange,
)
from .oras_live import (
    ORASLiveError,
    ORASLiveSnapshot,
    ORASLiveWriter,
    ORASBattleProbe,
    ORASLiveMemoryWatch,
    ORASLiveWriteResult,
    PK6_PARTY_SIZE,
    PK6_STORED_SIZE,
    ORAS_PARTY_STRIDE,
    ORAS_PARTY_STATS_OFFSET,
    ORAS_PARTY_STATS_SIZE,
    parse_pk6_party,
    parse_pk6_boxed as _parse_pk6_boxed_gen6,
    parse_oras_item_pocket,
    ORAS_ITEM_RECORD_SIZE,
    _MOVE_OFFSETS,
    _MOVE_PP_OFFSETS,
    _MOVE_PP_UPS_OFFSETS,
    _plain_pk6,
    _plain_stored_pk6,
    encrypt_pk6,
)
from .oras_tm_service import oras_tm_item_id
from .realtime_memory import LiveBlockResolver, MemoryCandidateHint
from .save_engine_client import SaveGameData, SavePokemon
from .win_process_memory import WindowsProcessMemory


# Primer perfil vivo de X/Y sobre Azahar. X/Y utiliza el mismo formato PK6 de
# party de sexta generación que ORAS, pero su matriz runtime parte de otra base.


def load_xy_move_metadata(path: Path) -> dict[int, dict[str, object]]:
    """Carga datos de movimientos fijados al version-group de X/Y.

    El encabezado de la tabla forma parte del contrato: una tabla de otra
    generación o version-group se rechaza en vez de publicar valores que solo
    coincidan por compartir el mismo ID de movimiento.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    if (
        int(raw.get("generation", 0) or 0) != 6
        or str(raw.get("target_version_group", "") or "") != "x-y"
    ):
        return {}
    result: dict[int, dict[str, object]] = {}
    for move_raw, entry in dict(raw.get("moves", {})).items():
        try:
            move_id = int(move_raw)
        except (TypeError, ValueError):
            continue
        if move_id <= 0 or not isinstance(entry, dict):
            continue
        values: dict[str, object] = {}
        for field in ("power", "accuracy", "pp"):
            value = entry.get(field)
            if value is None:
                values[field] = None
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                parsed = 0
            values[field] = parsed if parsed > 0 else None
        values["description_es"] = str(entry.get("description_es", "") or "").strip()
        type_id = entry.get("type_id")
        values["type_id"] = int(type_id) if isinstance(type_id, int) else None
        result[move_id] = values
    return result


def parse_pk6_boxed(
    raw: bytes, box: int, box_slot: int, move_names: dict[int, str],
):
    """Parser PK6 de caja usando la tabla Personal específica de X/Y."""
    return _parse_pk6_boxed_gen6(
        raw, box, box_slot, move_names, family="xy",
    )

XY_PARTY_ADDRESS = 0x08CE1CE8
# X/Y v1.5 sobre Azahar: la prueba física controlada del 25-08-2026
# demostró que este u32 little-endian pasa 6→5 al depositar un miembro,
# mientras la party se compacta a la izquierda. Las seis palabras anteriores
# son punteros/campos ajenos y quedan expresamente fuera de toda escritura.
XY_PARTY_COUNT_ADDRESS = 0x08CE1C74
XY_PARTY_COUNT_SIZE = 4
XY_PARTY_STRIDE = ORAS_PARTY_STRIDE
XY_PARTY_STATS_OFFSET = ORAS_PARTY_STATS_OFFSET
XY_PARTY_STATS_SIZE = ORAS_PARTY_STATS_SIZE
XY_PARTY_SPAN = (5 * XY_PARTY_STRIDE) + XY_PARTY_STATS_OFFSET + XY_PARTY_STATS_SIZE
# 2026-09-05: el búfer de anuncio de aprendizajes (ver
# ``usum_levelup_announcement_cache.py``) vive a ~13 MiB de
# ``XY_PARTY_ADDRESS`` -confirmado leyendo la partida real: 0 coincidencias
# con una ventana de 8 o 16 MiB, 2 coincidencias estables con 32 MiB o más-,
# muy lejos de la cercanía ya validada para USUM/SM. 40 MiB (±20 MiB) deja
# margen sobre el desplazamiento medido (~12.74 MiB) sin tener que escanear
# toda la RAM.
XY_ANNOUNCEMENT_CACHE_SCAN_SPAN = 40 * 1024 * 1024
# El writer necesita preservar también las regiones runtime que el lector no
# publica. La captura física X/Y/Azahar del 25-08-2026 demostró seis strides
# estables de 0x1E4, con bytes no nulos y específicos fuera del PK6+stats.
XY_PARTY_RUNTIME_SPAN = 6 * XY_PARTY_STRIDE
# 2026-09-05: leyendo la party en reposo, sin ninguna acción del jugador,
# el byte relativo 427 de cada slot runtime cambia por sí solo con el paso
# del tiempo (confirmado varias veces, incrementando de forma continua).
# No tiene relación con el contenido del Pokémon: es ajeno a la party y
# debe excluirse de cualquier comparación de "¿cambió algo?", o un depósito
# con éxito real se declara revertido por esta deriva. Los bytes reales,
# sin enmascarar, se siguen leyendo y escribiendo tal cual siempre.
XY_PARTY_RUNTIME_VOLATILE_OFFSET = 427


def _mask_xy_runtime_volatile_slot(slot: bytes) -> bytes:
    offset = XY_PARTY_RUNTIME_VOLATILE_OFFSET
    if len(slot) <= offset:
        return slot
    return slot[:offset] + b"\0" + slot[offset + 1:]


def _mask_xy_runtime_volatile_region(region: bytes) -> bytes:
    return b"".join(
        _mask_xy_runtime_volatile_slot(region[index:index + XY_PARTY_STRIDE])
        for index in range(0, len(region), XY_PARTY_STRIDE)
    )


def _mask_xy_runtime_volatile_tuple(runtime: tuple) -> tuple:
    return tuple(_mask_xy_runtime_volatile_slot(slot) for slot in runtime)

# Identidad del proceso. Se prioriza Title ID; los nombres sirven únicamente de
# fallback para forks de Citra/Azahar que no expongan el TID esperado.
XY_TITLE_IDS = {
    0x0004000000055D00,  # Pokémon X
    0x0004000000055E00,  # Pokémon Y
}
XY_PROCESS_NAMES = {"kujira-1", "kujira-2"}

# SAV6XY: bloque Misc de PKHeX. Money +0x08, Badges +0x0C, BP +0x3C.
XY_SAVE_MISC_OFFSET = 0x04200
XY_SAVE_MISC_SIZE = 0x140
XY_MISC_MONEY_OFFSET = 0x08
XY_MISC_BADGES_OFFSET = 0x0C
XY_MISC_BP_OFFSET = 0x3C

# X/Y desplaza este bloque 0x10 bytes entre el juego base (v1.0) y la
# actualización v1.5. Las referencias de RAM conocidas sitúan Money en
# 0x08C6A69C (v1.0) / 0x08C6A6AC (v1.5); PKHeX sitúa Money en Misc+0x08.
# Por tanto las dos bases documentadas de Misc son 0x08C6A694 / 0x08C6A6A4.
# Alpha.14 solo prefería la segunda y podía validar una ventana desplazada +0x10
# en partidas sin update. Alpha.15 prueba ambas y exige además que el ancla de
# alta entropía del bloque coincida exactamente antes de aceptar una base.
XY_MISC_KNOWN_ADDRESS_V10 = 0x08C6A694
XY_MISC_KNOWN_ADDRESS_V15 = 0x08C6A6A4
# Alias histórico para no romper imports/tests externos de builds anteriores.
XY_MISC_KNOWN_ADDRESS = XY_MISC_KNOWN_ADDRESS_V15

# Acotamos la búsqueda de Misc al MiB inmediatamente anterior a la party. El
# bloque solo se acepta si conserva una huella fuerte del guardado de esta Run.
XY_MISC_SCAN_START = XY_PARTY_ADDRESS - 0x00100000
XY_MISC_SCAN_END = XY_PARTY_ADDRESS - 0x00001000
XY_MISC_SCAN_BLOCK_SIZE = 0x00010000

# Segunda fuente de medallas, independiente de Misc. PKHeX define para X/Y el
# bloque 42 SubEventLog (SUBE) en 0x1D800, tamaño 0x308. Dentro, +0x2C guarda
# 8 x 6 IDs de especie (u16): el equipo con el que se ganó cada gimnasio.
#
# IMPORTANTE alpha.16: la cabecera está documentada conceptualmente como u32
# "SUBE", pero en el main real los bytes en disco son 45 42 55 53 ("EBUS") por
# el orden little-endian. Alpha.14/15 buscaban literalmente b"SUBE", por lo que
# el localizador vivo nunca podía encontrar una copia real de este bloque.
XY_SAVE_SUBEVENT_OFFSET = 0x1D800
XY_SAVE_SUBEVENT_SIZE = 0x308
XY_SUBEVENT_BADGE_VICTORY_OFFSET = 0x2C
XY_SUBEVENT_BADGE_COUNT = 8
XY_SUBEVENT_BADGE_SLOT_COUNT = 6
XY_SUBEVENT_BADGE_RECORD_SIZE = XY_SUBEVENT_BADGE_SLOT_COUNT * 2
XY_SUBEVENT_BADGE_VICTORY_SIZE = XY_SUBEVENT_BADGE_COUNT * XY_SUBEVENT_BADGE_RECORD_SIZE
XY_SUBEVENT_MAGIC = b"EBUS"
XY_SUBEVENT_MAGIC_OFFSETS = (0x28, 0x8C, 0x178, 0x264)
XY_MAX_SPECIES_ID = 721
# Todas las estructuras X/Y ya validadas en esta rama (MT/Misc/PC/party) viven
# en el MiB 0x08C00000..0x08CFFFFF. SUBE se busca ahí por firma y estructura,
# nunca por una dirección fija. Si no aparece, se prueba el rango histórico
# previo a la party que ya usa el resolver Misc.
XY_SUBEVENT_SCAN_RANGES = (
    (0x08C00000, 0x08D00000),
    (XY_MISC_SCAN_START, XY_MISC_SCAN_END),
)
XY_SUBEVENT_SCAN_BLOCK_SIZE = 0x00010000

# X/Y conserva el mismo formato PK6 almacenado (0xE8) y 31 cajas de 30
# huecos que ORAS. La captura física del 25-08-2026 en Pokémon X + Azahar
# 263745c demostró la base invitada 0x08C861B8: al depositar Budew desde el
# propio juego, la identidad apareció exactamente en Caja 1 / Slot 11 desde
# esa base y la party invitada se compactó a la vez. 0x08C861C8 era una copia
# desplazada 0x10 bytes que podía aceptar readback sin gobernar el juego.
# La dirección sigue siendo candidata y se valida con testigos antes de escribir.
XY_PC_KNOWN_ADDRESS = 0x08C861B8
# El rango total es menor que un stride PK6 (0xE8). Por ello una misma casilla
# física no puede encajar como dos índices diferentes dentro de las candidatas.
# El barrido es conservador: si ninguna candidata contiene al testigo exacto,
# aborta y conserva la última vista en vez de inventar una base.
XY_PC_KNOWN_SEARCH_RADIUS = 0x70
XY_PC_BOX_COUNT = 31
XY_PC_BOX_SLOT_COUNT = 30
XY_PC_SIZE = XY_PC_BOX_COUNT * XY_PC_BOX_SLOT_COUNT * PK6_STORED_SIZE
XY_PC_SCAN_START = XY_PARTY_ADDRESS - 0x00100000
XY_PC_SCAN_END = XY_PARTY_ADDRESS - 0x00001000
XY_PC_SCAN_BLOCK_SIZE = 0x00010000

# El bolsillo MT/MO de X/Y está formado por 105 registros u16 item_id/u16 qty:
# 420 bytes (0x1A4). La dirección conocida se usa solo como candidata validada;
# si no coincide en una build/fork, el resolver conserva el barrido dinámico.
XY_TM_POUCH_ADDRESS = 0x08C67D24  # X/Y v1.5
XY_TM_POUCH_ADDRESS_V10 = 0x08C67D14  # X/Y v1.0
# 100 MT + 5 MO = 105 registros de 4 bytes = 0x1A4.
# Alpha.7 usaba 0x1A8 y terminaba validando 4 bytes del bolsillo siguiente.
XY_TM_POUCH_SIZE = 0x1A4

# SAV6XY / PlayerBag6XY: el bloque completo de objetos ocupa 0xB88 bytes.
# Los offsets son relativos al INICIO de ese bloque; las direcciones de RAM se
# descubren y validan con testigos del ``main`` antes de escribir. El lector de
# MT existente conserva 0x1A4 porque solo necesita las 100 MT + 5 MO reales.
XY_SAVE_ITEMS_OFFSET = 0x00400
XY_SAVE_ITEMS_SIZE = 0x0B88
XY_BAG_POUCH_LAYOUT = {
    "items": (0x000, 0x640),
    "keyitems": (0x640, 0x180),
    "tms": (0x7C0, 0x1A8),
    "medicine": (0x968, 0x100),
    "berries": (0xA68, 0x120),
}
XY_INVENTORY_TARGETS = {
    "rare-candy": (50, "medicine"),
    "max-repel": (77, "items"),
}
XY_MAX_MONEY = 9_999_999

# Alpha.20: el dinero se ancla a la mochila viva que ya hemos validado en
# AzaharPlus. Las referencias históricas de X/Y mantienen exactamente el mismo
# delta entre el inicio de MyItem y Money tanto en v1.0 como en v1.5:
#   v1.0 bag 0x08C67554 -> money 0x08C6A69C
#   v1.5 bag 0x08C67564 -> money 0x08C6A6AC
# Por seguridad NO extrapolamos ese delta a una base desconocida: solo se acepta
# cuando la mochila calibrada coincide con uno de esos dos layouts documentados.
XY_BAG_KNOWN_BASE_V10 = XY_TM_POUCH_ADDRESS_V10 - XY_BAG_POUCH_LAYOUT["tms"][0]
XY_BAG_KNOWN_BASE_V15 = XY_TM_POUCH_ADDRESS - XY_BAG_POUCH_LAYOUT["tms"][0]
XY_MONEY_KNOWN_ADDRESS_V10 = XY_MISC_KNOWN_ADDRESS_V10 + XY_MISC_MONEY_OFFSET
XY_MONEY_KNOWN_ADDRESS_V15 = XY_MISC_KNOWN_ADDRESS_V15 + XY_MISC_MONEY_OFFSET
XY_MONEY_FROM_BAG_DELTA = XY_MONEY_KNOWN_ADDRESS_V10 - XY_BAG_KNOWN_BASE_V10
assert XY_MONEY_KNOWN_ADDRESS_V15 - XY_BAG_KNOWN_BASE_V15 == XY_MONEY_FROM_BAG_DELTA

XY_INVENTORY_SCAN_START = XY_PARTY_ADDRESS - 0x00180000
XY_INVENTORY_SCAN_END = XY_PARTY_ADDRESS - 0x00001000
XY_INVENTORY_SCAN_BLOCK_SIZE = 0x00010000
XY_MAX_BAG_QUANTITY = 999
XY_TM_HM_ITEM_IDS = frozenset(
    {int(oras_tm_item_id(number)) for number in range(1, 101) if oras_tm_item_id(number) is not None}
    | set(range(420, 425))  # HM01-HM05 en X/Y
)

# Sonda de batalla X/Y. IMPORTANTE: estas cuatro direcciones NO son una tabla
# de seis miembros. PARTY_1/PARTY_2 son dos punteros redundantes al battler
# ACTIVO del jugador; OPPONENT_1/OPPONENT_2 hacen lo mismo para el rival.
# Alpha.8 interpretó erróneamente PARTY_1 + n*4 como seis slots y eso produjo
# falsas muertes al cambiar de Pokémon o al debilitarse el rival.
XY_BATTLE_PARTY_PTR_1 = 0x081FB284
XY_BATTLE_PARTY_PTR_2 = 0x081FB624
XY_BATTLE_OPPONENT_PTR_1 = 0x081FB2A0
XY_BATTLE_OPPONENT_PTR_2 = 0x081FB640
XY_BATTLE_POINTER_MIN = 0x08000000
XY_BATTLE_POINTER_MAX = 0x08DF0000
XY_BATTLE_HP_OFFSET = 0x0E
XY_BATTLE_HP_PAIR_SIZE = 4
# A diferencia de ORAS (donde la dirección "opponent" resultó ser el slot 0
# de un roster ESTÁTICO de seis que nunca cambia entre sustituciones, ver
# `oras_live.ORAS_BATTLE_OPPONENT_TEAM_STRIDE`), en X/Y este puntero SÍ sigue
# al battler rival ACTIVO: comprobado en vivo el 14-09-2026 leyendo la misma
# RPC en paralelo durante una sustitución real -la dirección apuntada cambió
# de sitio y la especie/PS reflejaron al nuevo Pokémon-. Por eso aquí la
# regla de "combate de seis" sí necesita acumular cada rival distinto que
# vaya saliendo, en vez de leer el roster completo de una vez.
XY_BATTLE_SPECIES_OFFSET = 0x0C


def parse_xy_tm_hm_pocket(raw: bytes) -> dict[int, int]:
    items = parse_oras_item_pocket(raw, label="MT/MO X/Y")
    if any(int(item_id) not in XY_TM_HM_ITEM_IDS for item_id in items):
        raise XYLiveError("La región candidata contiene objetos que no son MT/MO de X/Y.")
    return items


class XYLiveError(ORASLiveError):
    pass


@dataclass(frozen=True, slots=True)
class XYLiveMemoryBlock:
    address: int
    data: bytes


@dataclass(frozen=True, slots=True)
class XYLiveSnapshot:
    game: SaveGameData
    process: AzaharProcess
    attempts: int
    memory_blocks: tuple[XYLiveMemoryBlock, ...] = ()


def read_xy_saved_misc(save_path: Path | str | None) -> bytes | None:
    if save_path is None:
        return None
    try:
        path = Path(save_path)
        with path.open("rb") as handle:
            handle.seek(XY_SAVE_MISC_OFFSET)
            raw = handle.read(XY_SAVE_MISC_SIZE)
    except (OSError, TypeError, ValueError):
        return None
    return raw if len(raw) == XY_SAVE_MISC_SIZE else None


def parse_xy_badges(raw: bytes) -> int | None:
    """Lee el contador de insignias X/Y (0..8) del bloque Misc.

    PKHeX expone este campo directamente como ``Data[0x0C]`` y la comparación
    binaria real pre/post gimnasio de esta rama confirma 0x00 -> 0x01 para la
    primera medalla. No es una máscara de bits.
    """
    if len(raw) != 1:
        return None
    value = int(raw[0])
    return value if 0 <= value <= 8 else None


def parse_xy_saved_badges(save_path: Path | str | None) -> int | None:
    misc = read_xy_saved_misc(save_path)
    if misc is None:
        return None
    return parse_xy_badges(misc[XY_MISC_BADGES_OFFSET:XY_MISC_BADGES_OFFSET + 1])


def read_xy_saved_subevent(save_path: Path | str | None) -> bytes | None:
    if save_path is None:
        return None
    try:
        path = Path(save_path)
        with path.open("rb") as handle:
            handle.seek(XY_SAVE_SUBEVENT_OFFSET)
            raw = handle.read(XY_SAVE_SUBEVENT_SIZE)
    except (OSError, TypeError, ValueError):
        return None
    return raw if len(raw) == XY_SAVE_SUBEVENT_SIZE else None


def parse_xy_badge_victory_records(subevent: bytes) -> tuple[tuple[int, ...], ...] | None:
    if len(subevent) != XY_SAVE_SUBEVENT_SIZE:
        return None
    start = XY_SUBEVENT_BADGE_VICTORY_OFFSET
    end = start + XY_SUBEVENT_BADGE_VICTORY_SIZE
    payload = subevent[start:end]
    if len(payload) != XY_SUBEVENT_BADGE_VICTORY_SIZE:
        return None
    values = struct.unpack(
        f"<{XY_SUBEVENT_BADGE_COUNT * XY_SUBEVENT_BADGE_SLOT_COUNT}H", payload,
    )
    result: list[tuple[int, ...]] = []
    for badge in range(XY_SUBEVENT_BADGE_COUNT):
        offset = badge * XY_SUBEVENT_BADGE_SLOT_COUNT
        record = tuple(int(value) for value in values[offset:offset + XY_SUBEVENT_BADGE_SLOT_COUNT])
        if any(value < 0 or value > XY_MAX_SPECIES_ID for value in record):
            return None
        result.append(record)
    return tuple(result)


def count_xy_badge_victories(subevent: bytes, *, require_prefix: bool = True) -> int | None:
    records = parse_xy_badge_victory_records(subevent)
    if records is None:
        return None
    present = [any(value != 0 for value in record) for record in records]
    if require_prefix:
        seen_empty = False
        for value in present:
            if not value:
                seen_empty = True
            elif seen_empty:
                return None
    return sum(present)


def parse_xy_saved_badge_victories(save_path: Path | str | None) -> int | None:
    raw = read_xy_saved_subevent(save_path)
    return count_xy_badge_victories(raw) if raw is not None else None


class XYLiveReader:
    """Lector mínimo pero real de Pokémon X/Y sobre Azahar RPC.

    Alpha.3 conecta primero el carril más importante y mejor conocido: party.
    El formato, la doble lectura estable y el parser PK6 se comparten con ORAS;
    la dirección y la identidad del proceso pertenecen al adaptador X/Y.
    """

    def __init__(
        self,
        move_catalog_path: Path,
        client_factory: Callable[[], AzaharRPCClient] = AzaharRPCClient,
        stable_delay: float = 0.045,
        snapshot_attempts: int = 4,
        transport_label: str = "Azahar RPC",
        live_profile: str = "XY-Azahar",
    ) -> None:
        self.client_factory = client_factory
        self.transport_label = str(transport_label)
        self.live_profile = str(live_profile)
        self.stable_delay = max(0.0, float(stable_delay))
        self.snapshot_attempts = max(1, int(snapshot_attempts))
        # Reutilizamos el cargador probado del lector Gen6 de ORAS sin acoplar
        # el transporte ni las direcciones.
        from .oras_live import ORASLiveReader
        self.move_names = ORASLiveReader._load_move_names(move_catalog_path)
        self._pc_bases_by_process: dict[tuple[int, str, str], int] = {}
        # Identidad conservadora del battler activo. Solo se actualiza cuando la
        # pareja redundante de PS puede asociarse de forma inequívoca a la party.
        # Si hay ambigüedad preferimos perder feedback inmediato y dejar que el
        # fallback post-combate confirme la baja, antes que restar una vida falsa.
        self._battle_active_identity: tuple[int, int, int, int] | None = None
        self._battle_last_player_hp: tuple[int, int] | None = None
        # PS de cada miembro tal como se leyeron, ya verificados por partida
        # doble, en el instante en que SÍ estaba en el campo esta batalla. Un
        # Pokémon en el banquillo no puede perder ni ganar PS por ningún medio
        # en los juegos principales -sin veneno, quemadura ni nada que le
        # afecte fuera de combate-, así que este valor sigue siendo exacto
        # mientras siga fuera. Hallazgo físico del 06-09-2026: el bloque de
        # equipo (`current.party`) NO seguía el daño de un miembro que ya
        # había sido benqueado -se quedaba congelado en su valor de antes de
        # esta pelea-, y usarlo como respaldo "curaba" en la barra a un
        # Pokémon que seguía dañado de verdad. Se reinicia al terminar el
        # combate (`opponent is None`).
        self._battle_confirmed_hp: dict[tuple[int, int, int, int], tuple[int, int]] = {}
        # Cuántas veces SEGUIDAS ha salido inválido el puntero del rival
        # mientras creíamos seguir en combate. El puntero del rival pasa por
        # la misma indirección que el del jugador -no es una dirección fija
        # como en ORAS-, así que puede leerse inválido durante un instante de
        # transición (medido en la partida real el 06-09-2026: justo al caer
        # el Pokémon del jugador) sin que el combate haya terminado de
        # verdad. Un solo tick así NO basta para declarar el combate
        # terminado: hacerlo publicaba el bloque de equipo crudo -sin el daño
        # de esta pelea- como si fuera la verdad, "curando" en pantalla a
        # todo el que seguía tocado.
        self._battle_opponent_absent_streak = 0

    @staticmethod
    def _find_xy_process(processes: list[AzaharProcess]) -> AzaharProcess:
        by_tid = [process for process in processes if int(process.title_id) in XY_TITLE_IDS]
        if len(by_tid) == 1:
            return by_tid[0]
        if len(by_tid) > 1:
            raise XYLiveError("Azahar expone más de un proceso Pokémon X/Y y no se puede elegir con seguridad.")
        by_name = [process for process in processes if process.name.casefold() in XY_PROCESS_NAMES]
        if len(by_name) == 1:
            return by_name[0]
        running = ", ".join(process.name for process in processes) or "ninguno"
        if not by_name:
            raise XYLiveError(
                "Azahar responde, pero no aparece Pokémon X/Y "
                f"(procesos visibles: {running})."
            )
        raise XYLiveError("Azahar expone más de un proceso X/Y y no se puede elegir con seguridad.")

    # El escritor Gen6 probado llama históricamente a este nombre. Mantener el
    # alias permite reutilizar su ruta segura de roles/movimientos sin copiarla.
    _find_oras_process = _find_xy_process

    @staticmethod
    def _read_party(client: AzaharRPCClient) -> tuple[bytes, ...]:
        slots: list[bytes] = []
        tail_padding = PK6_PARTY_SIZE - PK6_STORED_SIZE - XY_PARTY_STATS_SIZE
        for index in range(6):
            slot_address = XY_PARTY_ADDRESS + index * XY_PARTY_STRIDE
            stored = client.read_memory(slot_address, PK6_STORED_SIZE)
            stats = client.read_memory(slot_address + XY_PARTY_STATS_OFFSET, XY_PARTY_STATS_SIZE)
            slots.append(stored + stats + (b"\0" * tail_padding))
        return tuple(slots)

    @staticmethod
    def _read_party_compact(client: AzaharRPCClient) -> tuple[bytes, ...]:
        region = client.read_memory(XY_PARTY_ADDRESS, XY_PARTY_SPAN)
        if len(region) != XY_PARTY_SPAN:
            raise XYLiveError(f"{self.transport_label} devolvió un bloque de Equipo X/Y incompleto.")
        tail_padding = PK6_PARTY_SIZE - PK6_STORED_SIZE - XY_PARTY_STATS_SIZE
        slots: list[bytes] = []
        for index in range(6):
            base = index * XY_PARTY_STRIDE
            stored = region[base:base + PK6_STORED_SIZE]
            stats_start = base + XY_PARTY_STATS_OFFSET
            stats = region[stats_start:stats_start + XY_PARTY_STATS_SIZE]
            if len(stored) != PK6_STORED_SIZE or len(stats) != XY_PARTY_STATS_SIZE:
                raise XYLiveError(f"La captura compacta del Equipo X/Y quedó truncada ({self.transport_label}).")
            slots.append(stored + stats + (b"\0" * tail_padding))
        return tuple(slots)

    @staticmethod
    def _normalize_memory_requests(
        memory_blocks: Sequence[tuple[int, int]],
    ) -> tuple[tuple[int, int], ...]:
        result: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for address, size in memory_blocks:
            key = (int(address), int(size))
            if key[0] <= 0 or key[1] <= 0:
                raise XYLiveError("Se solicitó un bloque auxiliar de RAM inválido.")
            if key not in seen:
                seen.add(key)
                result.append(key)
        return tuple(result)

    @staticmethod
    def _read_memory_blocks(
        client: AzaharRPCClient,
        memory_blocks: Sequence[tuple[int, int]],
    ) -> tuple[XYLiveMemoryBlock, ...]:
        return tuple(
            XYLiveMemoryBlock(address, client.read_memory(address, size))
            for address, size in memory_blocks
        )

    @staticmethod
    def _preserve_known_labels(pokemon: SavePokemon, current: SaveGameData) -> SavePokemon:
        previous = next((
            item for item in current.party
            if item.species_id == pokemon.species_id
            and item.pid == pokemon.pid
            and item.tid == pokemon.tid
            and item.sid == pokemon.sid
        ), None)
        if previous is not None:
            pokemon.species = previous.species
            pokemon.nickname = previous.nickname
            pokemon.held_item = previous.held_item
            pokemon.ability = previous.ability
        return pokemon

    def _build_game(
        self,
        slots: Sequence[bytes],
        current: SaveGameData,
        process: AzaharProcess,
        *,
        live_write: bool = False,
    ) -> SaveGameData:
        party: list[SavePokemon] = []
        for index, raw in enumerate(slots, start=1):
            pokemon = parse_pk6_party(raw, index, self.move_names)
            if pokemon is not None:
                party.append(self._preserve_known_labels(pokemon, current))
        if not party:
            raise XYLiveError("La captura estable de X/Y no contiene ningún Pokémon en el equipo.")
        return SaveGameData(
            game=current.game,
            save_type=f"{current.save_type} + {self.transport_label}",
            generation=current.generation,
            trainer=current.trainer,
            party=party,
            raw={
                **current.raw,
                "liveSync": True,
                "liveWrite": bool(live_write),
                "liveProcess": process.name,
                "liveTitleId": f"{process.title_id:016X}",
                "liveProfile": self.live_profile,
            },
        )

    def _capture(
        self,
        current: SaveGameData,
        *,
        memory_blocks: Sequence[tuple[int, int]],
        compact: bool,
    ) -> XYLiveSnapshot:
        """Captura la party en vivo para la lectura pasiva habitual (dashboard,
        equipo, barra flotante...), no para una transacción de cambio de tamaño.

        2026-09-05: esta captura leía los seis slots físicos y dejaba que
        ``_build_game`` se quedara con cualquiera que decodificase como un
        Pokémon válido, sin mirar nunca el contador real. La investigación en
        vivo de esta misma fecha (ver ``_capture_stable_runtime_party_and_count``)
        demostró que el slot que el contador excluye NO se borra -sigue
        pasando el checksum PK6 como un Pokémon válido, es lo último que hubo
        ahí-. Sin truncar por el contador, en cuanto se libera un hueco esta
        lectura colaba ese sobrante como un miembro fantasma: el equipo
        mostrado parecía correcto (la UI no siempre repinta el sobrante), pero
        ``current_game.party`` tenía uno de más, y por eso "el equipo ya tiene
        seis Pokémon" al intentar añadir uno nuevo con solo cinco visibles.
        """
        requests = self._normalize_memory_requests(memory_blocks)
        try:
            with self.client_factory() as client:
                process = self._find_xy_process(client.process_list())
                client.set_process(process.process_id)
                for attempt in range(1, self.snapshot_attempts + 1):
                    first_party = self._read_party_compact(client) if compact else self._read_party(client)
                    first_count = bytes(client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
                    first_blocks = self._read_memory_blocks(client, requests)
                    if self.stable_delay:
                        time.sleep(self.stable_delay)
                    second_party = self._read_party_compact(client) if compact else self._read_party(client)
                    second_count = bytes(client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
                    second_blocks = self._read_memory_blocks(client, requests)
                    if (
                        first_party != second_party
                        or first_count[0] != second_count[0]
                        or first_blocks != second_blocks
                    ):
                        continue
                    # Solo el byte bajo es el contador real (ver el mismo
                    # hallazgo en _capture_stable_runtime_party_and_count).
                    count = int(second_count[0])
                    if not 1 <= count <= 6:
                        continue
                    return XYLiveSnapshot(
                        game=self._build_game(second_party[:count], current, process),
                        process=process,
                        attempts=attempt,
                        memory_blocks=second_blocks,
                    )
        except AzaharRPCError as exc:
            raise XYLiveError(str(exc)) from exc
        raise XYLiveError(
            "El equipo de X/Y cambió durante todas las lecturas; se reintentará automáticamente."
        )

    @staticmethod
    def _stable_pc_identity(pokemon: SavePokemon | None) -> tuple[int, int, int, int] | None:
        if pokemon is None:
            return None
        return (
            int(pokemon.species_id), int(pokemon.pid or 0),
            int(pokemon.tid or 0), int(pokemon.sid or 0),
        )

    @staticmethod
    def _pc_slot_address(box: int, box_slot: int, *, base_address: int) -> int:
        if not 1 <= int(box) <= XY_PC_BOX_COUNT or not 1 <= int(box_slot) <= XY_PC_BOX_SLOT_COUNT:
            raise XYLiveError("Caja/slot de PC fuera de rango en X/Y.")
        index = (int(box) - 1) * XY_PC_BOX_SLOT_COUNT + (int(box_slot) - 1)
        return int(base_address) + index * PK6_STORED_SIZE

    def _pc_anchor_score(
        self, client, base_address: int, anchors: Sequence[SavePokemon],
    ) -> tuple[int, int] | None:
        usable = [
            p for p in anchors
            if p.box is not None and p.box_slot is not None and int(p.species_id) > 0
        ][:20]
        if not usable:
            return None
        matched = 0
        checked = 0
        for pokemon in usable:
            try:
                raw = client.read_memory(
                    self._pc_slot_address(int(pokemon.box), int(pokemon.box_slot), base_address=base_address),
                    PK6_STORED_SIZE,
                )
                live = parse_pk6_boxed(raw, int(pokemon.box), int(pokemon.box_slot), self.move_names)
            except Exception:
                continue
            checked += 1
            if self._stable_pc_identity(live) == self._stable_pc_identity(pokemon):
                matched += 1
        required = 1 if len(usable) == 1 else 2
        if matched < required:
            return None
        return int(matched), int(checked)

    @staticmethod
    def _pc_presence_witnesses(anchors: Sequence[SavePokemon]) -> tuple[SavePokemon, ...]:
        """Pokémon cuya identidad debe existir en PC pero cuya casilla se desconoce.

        La UI añade estos testigos únicamente al observar una transición real
        party -> PC. No se usan para escribir ni para adivinar una posición: su
        único propósito es rechazar una base que aparenta estar vacía y localizar
        una candidata que contenga exactamente el mismo PK6.
        """
        result: list[SavePokemon] = []
        seen: set[tuple[int, int, int, int]] = set()
        for pokemon in anchors:
            if int(getattr(pokemon, "species_id", 0) or 0) <= 0:
                continue
            if pokemon.box is not None and pokemon.box_slot is not None:
                continue
            identity = XYLiveReader._stable_pc_identity(pokemon)
            if identity is None or identity in seen:
                continue
            seen.add(identity)
            result.append(pokemon)
        return tuple(result[:4])

    def _discover_pc_base_near_known_from_witnesses(
        self, client, witnesses: Sequence[SavePokemon],
    ) -> tuple[MemoryCandidateHint, ...]:
        """Calibra la base X/Y alrededor de la candidata documentada.

        Leemos una única ventana que contiene toda la matriz para todas las
        alineaciones del vecindario. Cada candidata se puntúa únicamente si una
        casilla PK6 válida coincide en especie+PID+TID+SID con un Pokémon que la
        party acaba de perder. Un bloque a cero jamás obtiene puntuación.
        """
        usable = self._pc_presence_witnesses(witnesses)
        target_ids = {
            identity for identity in (self._stable_pc_identity(p) for p in usable)
            if identity is not None
        }
        if not target_ids:
            return ()

        radius = int(XY_PC_KNOWN_SEARCH_RADIUS)
        scan_start = int(XY_PC_KNOWN_ADDRESS - radius)
        scan_size = int(XY_PC_SIZE + radius * 2)
        try:
            region = bytes(client.read_memory(scan_start, scan_size))
        except Exception:
            return ()
        if len(region) != scan_size:
            return ()

        hints: list[MemoryCandidateHint] = []
        # El intervalo completo mide menos que 0xE8, así que una misma dirección
        # de PK6 no puede convertirse en dos slots distintos por una delta de stride.
        for delta in range(-radius, radius + 1, 4):
            base = int(XY_PC_KNOWN_ADDRESS + delta)
            offset0 = base - scan_start
            matched: set[tuple[int, int, int, int]] = set()
            valid_occupied = 0
            for index in range(XY_PC_BOX_COUNT * XY_PC_BOX_SLOT_COUNT):
                start = offset0 + index * PK6_STORED_SIZE
                raw = region[start:start + PK6_STORED_SIZE]
                if len(raw) != PK6_STORED_SIZE or not any(raw):
                    continue
                # Los primeros 8 bytes no se cifran en PK6. Sanity != 0 permite
                # descartar casi todas las alineaciones falsas sin descifrar.
                if raw[4] or raw[5]:
                    continue
                box, slot_index = divmod(index, XY_PC_BOX_SLOT_COUNT)
                try:
                    live = parse_pk6_boxed(raw, box + 1, slot_index + 1, self.move_names)
                except Exception:
                    continue
                identity = self._stable_pc_identity(live)
                if identity is None:
                    continue
                valid_occupied += 1
                if identity in target_ids:
                    matched.add(identity)
            if matched:
                # ``score`` prioriza número de testigos y, a igualdad, cantidad
                # de PK6 válidos alineados. La selección final exige unicidad.
                hints.append(MemoryCandidateHint(
                    base,
                    f"testigo PC X/Y ({len(matched)}/{len(target_ids)})",
                    len(matched) * 1000 + min(valid_occupied, 999),
                ))
        return tuple(hints)

    def _discover_pc_base_near_known_from_structure(
        self, client,
    ) -> tuple[MemoryCandidateHint, ...]:
        """Localiza una matriz X/Y poblada sin depender del ``main`` guardado.

        Esta ruta solo produce evidencia cuando una alineación contiene al menos
        dos PK6 completos que superan descifrado, checksum y especie. Una única
        coincidencia no basta para calibrar una dirección sin identidad testigo.
        El vecindario es el mismo rango acotado y documentado que usa la
        calibración party->PC; nunca se amplía a un escaneo de FCRAM.
        """
        radius = int(XY_PC_KNOWN_SEARCH_RADIUS)
        scan_start = int(XY_PC_KNOWN_ADDRESS - radius)
        scan_size = int(XY_PC_SIZE + radius * 2)
        try:
            region = bytes(client.read_memory(scan_start, scan_size))
        except Exception:
            return ()
        if len(region) != scan_size:
            return ()

        hints: list[MemoryCandidateHint] = []
        for delta in range(-radius, radius + 1, 4):
            base = int(XY_PC_KNOWN_ADDRESS + delta)
            offset0 = base - scan_start
            valid_occupied = 0
            for index in range(XY_PC_BOX_COUNT * XY_PC_BOX_SLOT_COUNT):
                start = offset0 + index * PK6_STORED_SIZE
                raw = region[start:start + PK6_STORED_SIZE]
                if len(raw) != PK6_STORED_SIZE or not any(raw):
                    continue
                # Sanity debe ser cero en un PK6 almacenado válido. Este filtro
                # evita descifrar alineaciones obviamente imposibles.
                if raw[4] or raw[5]:
                    continue
                box, slot_index = divmod(index, XY_PC_BOX_SLOT_COUNT)
                try:
                    pokemon = parse_pk6_boxed(
                        raw, box + 1, slot_index + 1, self.move_names,
                    )
                except Exception:
                    continue
                if pokemon is not None and self._stable_pc_identity(pokemon) is not None:
                    valid_occupied += 1
            if valid_occupied >= 2:
                hints.append(MemoryCandidateHint(
                    base,
                    f"estructura PC X/Y ({valid_occupied} PK6 válidos)",
                    valid_occupied,
                ))
        return tuple(hints)

    def _discover_pc_bases(self, client, anchors: Sequence[SavePokemon]) -> tuple[MemoryCandidateHint, ...]:
        usable = [
            p for p in anchors
            if p.box is not None and p.box_slot is not None and int(p.species_id) > 0
        ]
        if not usable:
            return ()
        target = usable[0]
        target_identity = self._stable_pc_identity(target)
        target_index = ((int(target.box) - 1) * XY_PC_BOX_SLOT_COUNT + (int(target.box_slot) - 1))
        hints: dict[int, MemoryCandidateHint] = {}
        scan_start = (XY_PC_SCAN_START + 3) & ~3
        overlap = PK6_STORED_SIZE
        for block_address in range(scan_start, XY_PC_SCAN_END, XY_PC_SCAN_BLOCK_SIZE):
            candidate_size = min(XY_PC_SCAN_BLOCK_SIZE, XY_PC_SCAN_END - block_address)
            try:
                raw_block = bytes(client.read_memory(block_address, candidate_size + overlap))
            except Exception:
                continue
            for offset in range(0, candidate_size, 4):
                if offset + PK6_STORED_SIZE > len(raw_block):
                    break
                if not any(raw_block[offset:offset + 4]) or any(raw_block[offset + 4:offset + 6]):
                    continue
                raw = raw_block[offset:offset + PK6_STORED_SIZE]
                try:
                    live = parse_pk6_boxed(raw, int(target.box), int(target.box_slot), self.move_names)
                except Exception:
                    continue
                if self._stable_pc_identity(live) != target_identity:
                    continue
                base = int(block_address + offset - target_index * PK6_STORED_SIZE)
                if 0x08000000 <= base < 0x0A000000 and base % 4 == 0:
                    hints.setdefault(base, MemoryCandidateHint(base, "scan identidad PC X/Y", 0))
        return tuple(hints.values())

    def _locate_pc_base_for_read(self, client, process: AzaharProcess, anchors: Sequence[SavePokemon]) -> int:
        process_key = (int(process.title_id), str(process.name), self.transport_label)
        positioned = tuple(
            p for p in anchors
            if p.box is not None and p.box_slot is not None and int(p.species_id) > 0
        )
        witnesses = self._pc_presence_witnesses(anchors)

        # El lector conserva una caché pequeña propia para que abrir/actualizar el
        # PC no vuelva a barrer memoria. Siempre que tengamos una evidencia actual
        # (posición conocida o testigo party->PC), la caché debe volver a validarse.
        cached = self._pc_bases_by_process.get(process_key)
        structural_hints: tuple[MemoryCandidateHint, ...] | None = None
        if cached is not None:
            if positioned:
                if self._pc_anchor_score(client, cached, positioned) is not None:
                    return int(cached)
            elif not witnesses:
                # Sin anchors, una caché nominal no demuestra que siga apuntando
                # al inicio real. Si la matriz viva está poblada, recalibramos
                # únicamente con evidencia estructural múltiple y unívoca.
                structural_hints = self._discover_pc_base_near_known_from_structure(client)
                if len(structural_hints) == 1:
                    resolved = int(structural_hints[0].address)
                    self._pc_bases_by_process[process_key] = resolved
                    return resolved
                return int(cached)

        # 1) Con posiciones conocidas, la dirección documentada sigue siendo una
        # candidata barata, pero solo se acepta si coincide con las identidades.
        if positioned and self._pc_anchor_score(client, XY_PC_KNOWN_ADDRESS, positioned) is not None:
            self._pc_bases_by_process[process_key] = XY_PC_KNOWN_ADDRESS
            return XY_PC_KNOWN_ADDRESS

        # 2) Si un Pokémon acaba de abandonar la party, ese PK6 es una evidencia
        # mucho más fuerte que una región de ceros. Calibramos alrededor de la base
        # documentada y exigimos una única candidata con la mejor puntuación.
        if witnesses:
            hints = self._discover_pc_base_near_known_from_witnesses(client, witnesses)
            if hints:
                best_score = max(int(hint.priority or 0) for hint in hints)
                best = [hint for hint in hints if int(hint.priority or 0) == best_score]
                if len(best) == 1:
                    resolved = int(best[0].address)
                    self._pc_bases_by_process[process_key] = resolved
                    return resolved

        # 3) Con anchors posicionados mantenemos el descubrimiento amplio ya
        # existente. Requiere identidades completas y nunca acepta varias bases.
        candidates = self._discover_pc_bases(client, positioned)
        scored: list[tuple[tuple[int, int], int]] = []
        for hint in candidates:
            score = self._pc_anchor_score(client, int(hint.address), positioned)
            if score is not None:
                scored.append((score, int(hint.address)))
        if scored:
            scored.sort(reverse=True)
            best_score = scored[0][0]
            best = [address for score, address in scored if score == best_score]
            if len(best) == 1:
                self._pc_bases_by_process[process_key] = int(best[0])
                return int(best[0])

        # 4) Si el main no aporta anchors pero la matriz viva contiene varios PK6
        # válidos, su estructura completa permite calibrar el pequeño desplazamiento
        # observado entre revisiones de Citra/Azahar. Se exige una única candidata
        # estructural en todo el rango; una aparición aislada nunca se acepta.
        if not positioned and not witnesses:
            if structural_hints is None:
                structural_hints = self._discover_pc_base_near_known_from_structure(client)
            if len(structural_hints) == 1:
                resolved = int(structural_hints[0].address)
                self._pc_bases_by_process[process_key] = resolved
                return resolved

        # 5) Solo cuando literalmente no existe ninguna evidencia de que haya un
        # Pokémon en PC podemos usar la base documentada para representar un PC
        # posiblemente vacío. En cuanto haya un testigo, jamás confundimos ceros
        # de otra región con "0 Pokémon".
        if not positioned and not witnesses:
            self._pc_bases_by_process[process_key] = XY_PC_KNOWN_ADDRESS
            return XY_PC_KNOWN_ADDRESS

        raise XYLiveError(
            "No se pudo localizar de forma segura la matriz viva del PC de X/Y. "
            "RoleRun encontró evidencia de un cambio Equipo -> PC, pero ninguna "
            "candidata contenía ese mismo PK6; no se publicó una caja vacía falsa."
        )

    def read_pc(
        self, anchors: Sequence[SavePokemon],
    ) -> tuple[AzaharProcess, int, dict[tuple[int, int], SavePokemon | None]]:
        try:
            with self.client_factory() as client:
                process = self._find_xy_process(client.process_list())
                client.set_process(process.process_id)
                base = self._locate_pc_base_for_read(client, process, anchors)
                stable: bytes | None = None
                for _attempt in range(1, self.snapshot_attempts + 1):
                    first = bytes(client.read_memory(base, XY_PC_SIZE))
                    if self.stable_delay:
                        time.sleep(self.stable_delay)
                    second = bytes(client.read_memory(base, XY_PC_SIZE))
                    if first == second:
                        stable = second
                        break
                if stable is None:
                    raise XYLiveError("Las cajas X/Y cambiaron durante todas las lecturas; se reintentará después.")
                slots: dict[tuple[int, int], SavePokemon | None] = {}
                for index in range(XY_PC_BOX_COUNT * XY_PC_BOX_SLOT_COUNT):
                    start = index * PK6_STORED_SIZE
                    box, slot_index = divmod(index, XY_PC_BOX_SLOT_COUNT)
                    box += 1
                    box_slot = slot_index + 1
                    raw = stable[start:start + PK6_STORED_SIZE]
                    try:
                        pokemon = parse_pk6_boxed(raw, box, box_slot, self.move_names)
                    except ORASLiveError as exc:
                        raise XYLiveError(
                            f"La lectura viva del PC X/Y falló en Caja {box}, hueco {box_slot}: {exc}"
                        ) from exc
                    slots[(box, box_slot)] = pokemon
                return process, int(base), slots
        except AzaharRPCError as exc:
            raise XYLiveError(str(exc)) from exc

    def reset_runtime_state(self) -> None:
        self._pc_bases_by_process.clear()
        self._battle_active_identity = None
        self._battle_last_player_hp = None
        self._battle_confirmed_hp.clear()
        self._battle_opponent_absent_streak = 0

    @staticmethod
    def _battle_redundant_hp_pair(client, first_slot: int, second_slot: int) -> tuple[int, int] | None:
        """Lee el battler solo si las dos copias redundantes coinciden.

        La herramienta 3DS de referencia escribe PS únicamente cuando ambos
        punteros son válidos y el DWORD de HP coincide. Reproducimos esa misma
        condición: una sola copia nunca es suficiente para declarar una baja.
        """
        try:
            first_ptr = struct.unpack("<I", client.read_memory(int(first_slot), 4))[0]
            second_ptr = struct.unpack("<I", client.read_memory(int(second_slot), 4))[0]
        except Exception:
            return None
        if not (
            XY_BATTLE_POINTER_MIN < int(first_ptr) < XY_BATTLE_POINTER_MAX
            and XY_BATTLE_POINTER_MIN < int(second_ptr) < XY_BATTLE_POINTER_MAX
        ):
            return None
        try:
            first = bytes(client.read_memory(int(first_ptr) + XY_BATTLE_HP_OFFSET, XY_BATTLE_HP_PAIR_SIZE))
            second = bytes(client.read_memory(int(second_ptr) + XY_BATTLE_HP_OFFSET, XY_BATTLE_HP_PAIR_SIZE))
        except Exception:
            return None
        if len(first) != XY_BATTLE_HP_PAIR_SIZE or first != second:
            return None
        max_hp, current_hp = struct.unpack("<HH", first)
        if not (1 <= int(max_hp) <= 9999 and 0 <= int(current_hp) <= int(max_hp)):
            return None
        return int(current_hp), int(max_hp)

    @staticmethod
    def _battle_redundant_opponent_identity(
        client, first_slot: int, second_slot: int,
    ) -> tuple[int, int] | None:
        """Identidad del rival activo para la regla de "combate de seis".

        Misma comprobación redundante que ``_battle_redundant_hp_pair``
        -las dos copias del puntero deben coincidir-, pero leyendo la especie
        en vez de los PS. Devuelve ``(species_id, dirección del objeto)``: la
        dirección cambia con cada sustitución real (ver el comentario de
        ``XY_BATTLE_SPECIES_OFFSET``), así que sirve como identidad de
        "individuo distinto" incluso cuando dos rivales comparten especie.
        """
        try:
            first_ptr = struct.unpack("<I", client.read_memory(int(first_slot), 4))[0]
            second_ptr = struct.unpack("<I", client.read_memory(int(second_slot), 4))[0]
        except Exception:
            return None
        if not (
            XY_BATTLE_POINTER_MIN < int(first_ptr) < XY_BATTLE_POINTER_MAX
            and XY_BATTLE_POINTER_MIN < int(second_ptr) < XY_BATTLE_POINTER_MAX
        ):
            return None
        try:
            first = bytes(client.read_memory(int(first_ptr) + XY_BATTLE_SPECIES_OFFSET, 2))
            second = bytes(client.read_memory(int(second_ptr) + XY_BATTLE_SPECIES_OFFSET, 2))
        except Exception:
            return None
        if len(first) != 2 or first != second:
            return None
        species_id = struct.unpack("<H", first)[0]
        if not (1 <= int(species_id) <= XY_MAX_SPECIES_ID):
            return None
        return int(species_id), int(first_ptr)

    @staticmethod
    def _battle_identity(pokemon: SavePokemon) -> tuple[int, int, int, int]:
        return (
            int(pokemon.species_id), int(pokemon.pid or 0),
            int(pokemon.tid or 0), int(pokemon.sid or 0),
        )

    def _map_active_battler(
        self, current: SaveGameData, player_hp: tuple[int, int],
    ) -> SavePokemon | None:
        """Asocia la pareja de PS del battler activo a un único PK6 de party.

        Se privilegia coincidencia exacta current/max del snapshot principal.
        La identidad previa se conserva durante daño/curación y durante el frame
        de 0 PS. Tras 0->>0 sabemos que hubo cambio de battler y obligamos a
        remapear. Nunca se reparte un mismo HP a seis slots.
        """
        current_hp, max_hp = map(int, player_hp)
        by_identity = {self._battle_identity(mon): mon for mon in current.party}
        previous_pair = self._battle_last_player_hp
        active = by_identity.get(self._battle_active_identity) if self._battle_active_identity else None

        # Tras un faint confirmado, cualquier vuelta a PS positivos corresponde
        # necesariamente a otro battler (o a una reentrada ya resuelta).
        if previous_pair is not None and int(previous_pair[0]) == 0 and current_hp > 0:
            active = None
            self._battle_active_identity = None

        # Un máximo distinto también demuestra un cambio. Si coincide, no basta
        # por sí solo para identificar: dos Pokémon pueden compartir max HP.
        if active is not None and int(getattr(active, "max_hp", 0) or 0) != max_hp:
            active = None
            self._battle_active_identity = None

        exact = [
            mon for mon in current.party
            if int(getattr(mon, "max_hp", 0) or 0) == max_hp
            and int(getattr(mon, "current_hp", 0) or 0) == current_hp
        ]
        if len(exact) == 1:
            candidate = exact[0]
            candidate_id = self._battle_identity(candidate)
            # Una coincidencia exacta única es una señal más fuerte que una
            # identidad histórica; permite detectar cambios voluntarios.
            if active is None or candidate_id != self._battle_active_identity:
                active = candidate
                self._battle_active_identity = candidate_id
        elif active is None and current_hp > 0:
            same_max = [
                mon for mon in current.party
                if int(getattr(mon, "max_hp", 0) or 0) == max_hp
                and int(getattr(mon, "current_hp", 0) or 0) > 0
            ]
            if len(same_max) == 1:
                active = same_max[0]
                self._battle_active_identity = self._battle_identity(active)

        self._battle_last_player_hp = (current_hp, max_hp)
        return active

    def read_battle_probe(self, current: SaveGameData) -> ORASBattleProbe | None:
        """Sonda conservadora del battler activo de X/Y.

        PARTY_1/PARTY_2 y OPPONENT_1/OPPONENT_2 son pares redundantes. Solo los
        primeros describen al jugador. La muerte del rival por tanto jamás puede
        convertirse en una transición de PS de nuestra party.
        """
        try:
            with self.client_factory() as client:
                process = self._find_xy_process(client.process_list())
                client.set_process(process.process_id)
                opponent = self._battle_redundant_hp_pair(
                    client, XY_BATTLE_OPPONENT_PTR_1, XY_BATTLE_OPPONENT_PTR_2,
                )
                player = self._battle_redundant_hp_pair(
                    client, XY_BATTLE_PARTY_PTR_1, XY_BATTLE_PARTY_PTR_2,
                )
                # Regla de "combate de seis" (dictada 09-09-2026): a diferencia
                # de ORAS, aquí el puntero del rival SÍ sigue al battler activo
                # en cada sustitución (comprobado en vivo el 14-09-2026), así
                # que se puede leer directamente en vez de perseguir un roster
                # estático. Solo tiene sentido si ya hay un oponente válido.
                opponent_identity = (
                    self._battle_redundant_opponent_identity(
                        client, XY_BATTLE_OPPONENT_PTR_1, XY_BATTLE_OPPONENT_PTR_2,
                    )
                    if opponent is not None else None
                )
        except Exception:
            return None

        if opponent is None:
            # Un solo tick sin oponente válido, en mitad de un combate que ya
            # dábamos por confirmado, puede ser el instante de transición de
            # una caída -no una prueba de que el combate terminó de verdad.
            # Se exige que se repita antes de creérnoslo.
            if self._battle_active_identity is not None and self._battle_opponent_absent_streak < 1:
                self._battle_opponent_absent_streak += 1
                return ORASBattleProbe(state="trainer")
            self._battle_active_identity = None
            self._battle_last_player_hp = None
            self._battle_confirmed_hp.clear()
            self._battle_opponent_absent_streak = 0
            return ORASBattleProbe(state="none")
        self._battle_opponent_absent_streak = 0
        if player is None:
            return ORASBattleProbe(state="trainer", opponent_identity=opponent_identity)

        active = self._map_active_battler(current, player)
        if active is None:
            # Combate confirmado, atribución no segura. El fallback post-combate
            # seguirá detectando cualquier Pokémon que realmente haya quedado a 0.
            return ORASBattleProbe(
                state="trainer", hp_pairs=(player,), opponent_identity=opponent_identity,
            )

        active_id = self._battle_identity(active)
        if not self._battle_confirmed_hp:
            # Primer instante resuelto de este combate: fuera de combate el
            # bloque de equipo SÍ es la verdad (nadie puede haber perdido ni
            # ganado PS sin que quedara ahí reflejado), así que sirve de línea
            # base para los seis. Sin esto, cada pelea nueva arrancaba con
            # cinco miembros en gris hasta que les tocara salir uno a uno —
            # reportado en la partida real el 06-09-2026 justo tras una baja.
            for pokemon in current.party:
                self._battle_confirmed_hp[self._battle_identity(pokemon)] = (
                    int(pokemon.current_hp or 0), int(pokemon.max_hp or 0),
                )
        self._battle_confirmed_hp[active_id] = player
        party: list[SavePokemon] = []
        current_hp, max_hp = player
        for pokemon in current.party:
            clone = replace(
                pokemon,
                moves=list(pokemon.moves),
                move_ids=list(pokemon.move_ids),
                markings=list(pokemon.markings),
            )
            identity = self._battle_identity(pokemon)
            if identity == active_id:
                clone.max_hp = int(max_hp)
                clone.current_hp = int(current_hp)
            else:
                confirmado = self._battle_confirmed_hp.get(identity)
                if confirmado is not None:
                    # Ya estuvo en el campo esta pelea: un banquillo no pierde
                    # ni gana PS por nada fuera de combate, así que ese valor
                    # sigue siendo exacto.
                    clone.current_hp, clone.max_hp = confirmado
                    clone.hp_is_live = True
                else:
                    # Nunca ha salido esta pelea: el bloque de equipo previo a
                    # entrar en combate sigue siendo su verdad, pero no se ha
                    # confirmado dentro de ESTA pelea, así que no se pinta como
                    # cierto.
                    clone.hp_is_live = False
            party.append(clone)

        health = SaveGameData(
            game=current.game,
            save_type=f"{current.save_type} + PS batalla {self.transport_label}",
            generation=current.generation,
            trainer=current.trainer,
            party=party,
            raw={
                **current.raw, "liveBattleHealth": True, "liveBattleState": "trainer",
                "liveBattleActive": active_id,
            },
        )
        return ORASBattleProbe(
            state="trainer", health_game=health, hp_pairs=(player,),
            opponent_identity=opponent_identity,
        )

    def read(
        self,
        current: SaveGameData,
        memory_blocks: Sequence[tuple[int, int]] = (),
    ) -> XYLiveSnapshot:
        return self._capture(current, memory_blocks=memory_blocks, compact=False)

    def read_monitor(
        self,
        current: SaveGameData,
        memory_blocks: Sequence[tuple[int, int]] = (),
    ) -> XYLiveSnapshot:
        return self._capture(current, memory_blocks=memory_blocks, compact=True)


class XYLiveWriter(ORASLiveWriter):
    """Escritura Gen6 transaccional para la superficie X/Y ya calibrada.

    Mantiene roles de PC, intercambio 1↔1, MT y sustitución de bajas hacia
    Cementerio usando escritura Gen6 verificada. Alpha.17 añade las utilidades
    de inventario X/Y con localización dinámica por testigos, relectura y rollback.
    Solo siguen protegidas las operaciones que cambian arbitrariamente el tamaño
    de la party.
    """

    def __init__(
        self, reader: XYLiveReader, move_pp_for: Callable[[int], int], personal_for=None,
        party_commit_settle_delay: float = 0.35,
        host_memory_factory: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(reader, move_pp_for=move_pp_for, personal_for=personal_for)
        # Resolver independiente para el bloque Misc de X/Y.
        self.block_resolver = LiveBlockResolver(default_failure_cooldown=8.0)
        self._last_badge_source: str | None = None
        self._last_process_key: tuple[int, str] | None = None
        self._tm_inventory_bases_by_process: dict[tuple[int, str, str], int] = {}
        self._bag_bases_by_process: dict[tuple[int, str, str], int] = {}
        self._subevent_bases_by_process: dict[tuple[int, str], int] = {}
        self._subevent_failed_scan_at: dict[tuple[int, str], float] = {}
        # X/Y puede aceptar momentáneamente una escritura de party y reconstruir
        # después la estructura desde sus bytes runtime. El segundo readback se
        # retrasa para no confundir eco inmediato del RPC con consumo del juego.
        self.party_commit_settle_delay = max(0.0, float(party_commit_settle_delay))
        self.host_memory_factory = host_memory_factory or WindowsProcessMemory

    @staticmethod
    def _slot_address(slot: int) -> int:
        return XY_PARTY_ADDRESS + (int(slot) - 1) * XY_PARTY_STRIDE

    def _build_game(
        self,
        slots: Sequence[bytes],
        current: SaveGameData,
        process: AzaharProcess,
        *,
        live_write: bool,
    ) -> SaveGameData:
        return self.reader._build_game(slots, current, process, live_write=live_write)

    def _capture_stable_party(self, client) -> tuple[tuple[bytes, ...], int]:
        """Sobrescribe la captura genérica de ORAS para recortar por el
        contador real de X/Y.

        2026-09-05, investigado en vivo con el usuario: esta captura la
        reutilizan sin cambios los cambios de rol, MT y sustitución de
        movimiento heredados de ORAS. Como no mira el contador, el slot
        que X/Y excluye -que conserva lo último que hubo ahí, válido según
        el checksum PK6- se colaba como un séptimo... como un miembro más.
        Si por casualidad compartía identidad con un miembro real (el caso
        real observado: dos Flabébé con el mismo PID, una vez dentro del
        contador y la otra ya excluida tras un depósito), cualquier cambio
        de rol se rechazaba en bucle con "la identidad de X aparece más de
        una vez en el equipo vivo" y jamás llegaba a escribirse nada.
        """
        for attempt in range(1, self.reader.snapshot_attempts + 1):
            first = self.reader._read_party(client)
            first_count = bytes(client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = self.reader._read_party(client)
            second_count = bytes(client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
            if first != second or first_count[0] != second_count[0]:
                continue
            count = int(second_count[0])
            if not 1 <= count <= 6:
                continue
            return second[:count], attempt
        raise XYLiveError(
            "El equipo X/Y cambió durante todas las lecturas. Sal de la animación o combate y vuelve a intentarlo."
        )

    def _capture_stable_state(
        self, client, extras: Sequence[tuple[str, int, int]],
    ) -> tuple[tuple[bytes, ...], dict[str, bytes], int]:
        """Mismo recorte por contador que ``_capture_stable_party``, para la
        ruta combinada (roles + PC + inventario + dinero) heredada de ORAS.
        """
        for attempt in range(1, self.reader.snapshot_attempts + 1):
            first_party = self.reader._read_party(client)
            first_count = bytes(client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
            first_extra = {key: client.read_memory(address, size) for key, address, size in extras}
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second_party = self.reader._read_party(client)
            second_count = bytes(client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
            second_extra = {key: client.read_memory(address, size) for key, address, size in extras}
            if (
                first_party != second_party
                or first_count[0] != second_count[0]
                or first_extra != second_extra
            ):
                continue
            count = int(second_count[0])
            if not 1 <= count <= 6:
                continue
            return second_party[:count], second_extra, attempt
        raise XYLiveError(
            "X/Y cambió durante todas las lecturas. Sal de combates, mochila o cajas y vuelve a intentarlo."
        )

    @staticmethod
    def _unsupported_changes(changes: Sequence[object]) -> list[str]:
        labels: list[str] = []
        for change in changes:
            if isinstance(change, (
                PendingChange, PendingRoleChange, PendingPCRoleChange,
                PendingPartyHeal, PendingTMTeach,
            )):
                continue
            # X/Y permite además cambiar el tamaño de la party: contador,
            # compactación y slot vacío se demostraron físicamente en v1.5.
            if isinstance(change, PendingTeamChange) and change.operation in {
                "swap-party-box", "replace-fainted", "move-box-slot",
                "party-to-box", "box-to-party", "swap-box-slots",
            }:
                continue
            if isinstance(change, PendingTeamChange):
                label = "operación Equipo ↔ PC no soportada por X/Y"
            elif isinstance(change, PendingInventoryChange):
                # alpha.17: Caramelo Raro, Repelente Máximo y dinero tienen una
                # ruta X/Y propia, localizada por testigos y verificada.
                continue
            else:
                label = type(change).__name__
            if label not in labels:
                labels.append(label)
        return labels

    def _healed_party_bytes(self, raw: bytes) -> bytes:
        """Construye un PK6 curado conservando identidad y datos ajenos.

        X/Y almacena el PK6 y su extensión runtime en dos regiones separadas.
        Este método opera sobre la captura sintética que ya valida el reader;
        la ruta de escritura separa después ambos fragmentos y nunca escribe
        los seis bytes de relleno que no existen en la RAM del juego.
        """
        plain, was_encrypted = _plain_pk6(raw)
        data = bytearray(plain)
        maximum_hp = int(struct.unpack_from("<H", data, 0xF2)[0])
        if maximum_hp <= 0:
            raise XYLiveError("X/Y devolvió PS máximos inválidos; no se curó el equipo.")
        struct.pack_into("<I", data, 0xE8, 0)
        struct.pack_into("<H", data, 0xF0, maximum_hp)
        for move_offset, pp_offset, pp_ups_offset in zip(
            _MOVE_OFFSETS, _MOVE_PP_OFFSETS, _MOVE_PP_UPS_OFFSETS,
        ):
            move_id = int(struct.unpack_from("<H", data, move_offset)[0])
            if move_id == 0:
                data[pp_offset] = 0
                continue
            base_pp = int(self.move_pp_for(move_id) or 0)
            pp_ups = int(data[pp_ups_offset])
            if base_pp <= 0 or not 0 <= pp_ups <= 3:
                raise XYLiveError(
                    f"No se pudo demostrar el PP completo del movimiento #{move_id}; "
                    "no se curó el equipo."
                )
            maximum_pp = base_pp * (5 + pp_ups) // 5
            if maximum_pp > 0xFF:
                raise XYLiveError(f"El PP calculado para el movimiento #{move_id} no cabe en PK6.")
            data[pp_offset] = maximum_pp
        self._refresh_checksum(data)
        return encrypt_pk6(bytes(data)) if was_encrypted else bytes(data)

    def _apply_party_heal(
        self,
        current: SaveGameData,
        changes: Sequence[PendingPartyHeal],
    ) -> ORASLiveWriteResult:
        """Cura la party X/Y con precondición, readback y rollback verificados."""
        if not changes:
            raise XYLiveError("No hay miembros del equipo que curar en X/Y.")
        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                original_capture, capture_attempt = self._capture_stable_party(client)
                live_party = self._read_party_members(original_capture, current)
                if not live_party:
                    raise XYLiveError("La captura estable de X/Y no contiene ningún Pokémon en el equipo.")

                targets = {id(change): self._resolve_target(change, live_party) for change in changes}
                if len(set(targets.values())) != len(targets):
                    raise XYLiveError("La petición de curación repite un mismo Pokémon; no se escribió nada.")
                expected_slots = {
                    slot: self._healed_party_bytes(original_capture[slot - 1])
                    for slot in sorted(set(targets.values()))
                }
                if all(
                    expected_slots[slot][:PK6_STORED_SIZE]
                    == original_capture[slot - 1][:PK6_STORED_SIZE]
                    and expected_slots[slot][PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]
                    == original_capture[slot - 1][PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]
                    for slot in expected_slots
                ):
                    return ORASLiveWriteResult(
                        game=self._build_game(original_capture, current, process, live_write=True),
                        process=process,
                        attempts=capture_attempt,
                        applied_count=len(changes),
                        already_applied=True,
                    )

                original_parts: dict[int, bytes] = {}
                planned: dict[int, bytes] = {}
                for slot, expected in expected_slots.items():
                    base = self._slot_address(slot)
                    parts = (
                        (base, original_capture[slot - 1][:PK6_STORED_SIZE], expected[:PK6_STORED_SIZE]),
                        (
                            base + XY_PARTY_STATS_OFFSET,
                            original_capture[slot - 1][PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE],
                            expected[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE],
                        ),
                    )
                    for address, original, replacement in parts:
                        # Testigo inmediato: no se escribe si el juego cambió
                        # desde la doble captura estable.
                        if bytes(client.read_memory(address, len(original))) != original:
                            raise XYLiveError(
                                f"El slot {slot} cambió antes de curarse; no se escribió ningún byte."
                            )
                        original_parts[address] = original
                        if replacement != original:
                            planned[address] = replacement

                attempted: list[tuple[int, bytes]] = []
                try:
                    for address in sorted(planned):
                        attempted.append((address, original_parts[address]))
                        client.write_memory(address, planned[address])

                    verified_capture, verified_attempt = self._capture_stable_party(client)
                    verified_party = self._read_party_members(verified_capture, current)
                    for slot, expected_raw in expected_slots.items():
                        actual_raw = verified_capture[slot - 1]
                        if (
                            actual_raw[:PK6_STORED_SIZE] != expected_raw[:PK6_STORED_SIZE]
                            or actual_raw[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]
                            != expected_raw[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]
                        ):
                            raise XYLiveError(
                                f"Azahar no confirmó todos los bytes curados del slot {slot}."
                            )
                        actual = verified_party.get(slot)
                        if actual is None or int(actual.current_hp or 0) != int(actual.max_hp or 0):
                            raise XYLiveError(f"X/Y no confirmó los PS restaurados del slot {slot}.")
                        if int(actual.status_condition or 0) != 0:
                            raise XYLiveError(f"X/Y no confirmó la eliminación del estado del slot {slot}.")

                    return ORASLiveWriteResult(
                        game=self._build_game(verified_capture, current, process, live_write=True),
                        process=process,
                        attempts=max(capture_attempt, verified_attempt),
                        applied_count=len(changes),
                    )
                except Exception as exc:
                    rollback_errors = self._rollback(client, attempted)
                    for address, original in dict(attempted).items():
                        try:
                            if bytes(client.read_memory(address, len(original))) != original:
                                rollback_errors.append(f"0x{address:08X}: readback distinto tras rollback")
                        except Exception as readback_exc:
                            rollback_errors.append(f"0x{address:08X}: {readback_exc}")
                    if rollback_errors:
                        raise XYLiveError(
                            f"La curación X/Y falló: {exc}. No se pudo confirmar toda la restauración: "
                            + "; ".join(rollback_errors)
                        ) from exc
                    if attempted:
                        raise XYLiveError(
                            f"La curación X/Y falló: {exc}. RoleRun restauró y verificó los bytes "
                            "originales en RAM."
                        ) from exc
                    raise
        except AzaharRPCError as exc:
            raise XYLiveError(str(exc)) from exc

    @staticmethod
    def _canonical_evs(data: bytes | bytearray) -> tuple[int, int, int, int, int, int]:
        """Devuelve EV en el contrato UI: PS, Atq, Def, At. Esp., Def. Esp., Vel."""
        native = tuple(int(data[0x1E + index]) for index in range(6))
        return native[0], native[1], native[2], native[4], native[5], native[3]

    @staticmethod
    def _native_evs(values: Sequence[int]) -> tuple[int, int, int, int, int, int]:
        canonical = tuple(int(value) for value in values)
        if len(canonical) != 6:
            raise XYLiveError("La distribución de EV de X/Y no contiene las seis estadísticas.")
        if any(not 0 <= value <= 252 for value in canonical) or sum(canonical) > 510:
            raise XYLiveError("La distribución de EV pedida no es válida en X/Y.")
        return canonical[0], canonical[1], canonical[2], canonical[5], canonical[3], canonical[4]

    def _set_party_evs_and_stats(
        self,
        data: bytearray,
        change: PendingRoleChange,
    ) -> None:
        """Normaliza EV y recalcula la extensión viva completa de un PK6 X/Y.

        La extensión separada conserva estado y daño relativo. Antes de
        prepararla se demuestra que las estadísticas actuales corresponden al
        PK6 y a los EV que la UI leyó; una muestra stale nunca llega a RAM.
        """
        expected_evs = tuple(int(value) for value in tuple(change.old_evs or ()))
        desired_evs = tuple(int(value) for value in tuple(change.new_evs or ()))
        if len(expected_evs) != 6 or len(desired_evs) != 6:
            raise XYLiveError("X/Y necesita los EV anteriores y nuevos completos para cambiar el rol.")
        self._native_evs(expected_evs)
        desired_native = self._native_evs(desired_evs)
        actual_evs = self._canonical_evs(data)
        if actual_evs != expected_evs:
            name = str(getattr(change, "pokemon", "") or "El Pokémon")
            raise XYLiveError(
                f"{name} cambió sus EV dentro del juego. RoleRun esperaba {expected_evs} "
                f"y encontró {actual_evs}; no se escribió ningún byte."
            )

        species = int(struct.unpack_from("<H", data, 0x08)[0])
        form = (int(data[0x1D]) >> 3) & 0x1F
        if self.personal_for is None:
            raise XYLiveError("No está disponible la tabla Personal X/Y necesaria para recalcular estadísticas.")
        personal = self.personal_for(species, form)
        if personal is None:
            raise XYLiveError(
                f"La ROM activa no contiene datos Personal exactos para especie {species}, forma {form}."
            )

        stored_before = bytes(data[:PK6_STORED_SIZE])
        calculated_before = self._party_extension(stored_before, personal)
        live_level = int(data[0xEC])
        calculated_level = int(calculated_before[4])
        if live_level != calculated_level:
            raise XYLiveError(
                f"El nivel vivo X/Y ({live_level}) no coincide con la experiencia del PK6 "
                f"({calculated_level}); no se escribió nada."
            )
        live_stats = bytes(data[0xF2:0xFE])
        calculated_stats = bytes(calculated_before[10:22])
        if expected_evs != desired_evs and live_stats != calculated_stats:
            raise XYLiveError(
                "Las estadísticas vivas de X/Y no corresponden al PK6 capturado; "
                "no se aplicaron EV sobre una muestra incompatible."
            )

        old_current_hp = int(struct.unpack_from("<H", data, 0xF0)[0])
        old_max_hp = int(struct.unpack_from("<H", data, 0xF2)[0])
        if old_max_hp <= 0 or not 0 <= old_current_hp <= old_max_hp:
            raise XYLiveError("X/Y devolvió una relación de PS inválida; no se cambiaron los EV.")
        missing_hp = old_max_hp - old_current_hp

        data[0x1E:0x24] = bytes(desired_native)
        calculated_after = self._party_extension(bytes(data[:PK6_STORED_SIZE]), personal)
        new_max_hp = int(struct.unpack_from("<H", calculated_after, 10)[0])
        if old_current_hp == 0:
            new_current_hp = 0
        else:
            new_current_hp = min(new_max_hp, max(1, new_max_hp - missing_hp))
        struct.pack_into("<H", data, 0xF0, new_current_hp)
        data[0xF2:0xFE] = calculated_after[10:22]

    def _apply_party_role_evs(
        self,
        current: SaveGameData,
        changes: Sequence[PendingChange | PendingRoleChange],
    ) -> ORASLiveWriteResult:
        """Aplica rol+EV+stats X/Y como una sola transacción recuperable."""
        if not changes:
            raise XYLiveError("No hay cambios de rol o movimientos que aplicar en X/Y.")
        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                original_capture, capture_attempt = self._capture_stable_party(client)
                live_party = self._read_party_members(original_capture, current)
                if not live_party:
                    raise XYLiveError("La captura estable de X/Y no contiene ningún Pokémon en el equipo.")
                targets = {id(change): self._resolve_target(change, live_party) for change in changes}

                original_slots: dict[int, bytes] = {}
                plain_slots: dict[int, bytearray] = {}
                encrypted_slots: dict[int, bool] = {}
                for slot in sorted(set(targets.values())):
                    original = original_capture[slot - 1]
                    plain, encrypted = _plain_pk6(original)
                    original_slots[slot] = original
                    plain_slots[slot] = bytearray(plain)
                    encrypted_slots[slot] = encrypted

                for change in changes:
                    slot = targets[id(change)]
                    if isinstance(change, PendingRoleChange):
                        self._replace_role(plain_slots[slot], change)
                        if change.new_evs is not None:
                            self._set_party_evs_and_stats(plain_slots[slot], change)
                    else:
                        self._replace_move(plain_slots[slot], change)

                encoded_slots: dict[int, bytes] = {}
                expected_party: dict[int, SavePokemon] = {}
                for slot, plain in plain_slots.items():
                    self._refresh_checksum(plain)
                    encoded = encrypt_pk6(bytes(plain)) if encrypted_slots[slot] else bytes(plain)
                    expected = parse_pk6_party(encoded, slot, self.reader.move_names)
                    if expected is None:
                        raise XYLiveError(f"El slot {slot} quedó vacío durante la preparación.")
                    encoded_slots[slot] = encoded
                    expected_party[slot] = expected

                original_parts: dict[int, bytes] = {}
                planned: dict[int, bytes] = {}
                for slot, expected in encoded_slots.items():
                    base = self._slot_address(slot)
                    for address, original, replacement in (
                        (base, original_slots[slot][:PK6_STORED_SIZE], expected[:PK6_STORED_SIZE]),
                        (
                            base + XY_PARTY_STATS_OFFSET,
                            original_slots[slot][PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE],
                            expected[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE],
                        ),
                    ):
                        if bytes(client.read_memory(address, len(original))) != original:
                            raise XYLiveError(
                                f"El slot {slot} cambió justo antes de aplicar su rol; no se escribió ningún byte."
                            )
                        original_parts[address] = original
                        if replacement != original:
                            planned[address] = replacement

                if not planned:
                    return ORASLiveWriteResult(
                        game=self._build_game(original_capture, current, process, live_write=True),
                        process=process,
                        attempts=capture_attempt,
                        applied_count=len(changes),
                        already_applied=True,
                    )

                attempted: list[tuple[int, bytes]] = []
                try:
                    for address in sorted(planned):
                        attempted.append((address, original_parts[address]))
                        client.write_memory(address, planned[address])

                    verified_capture, verified_attempt = self._capture_stable_party(client)
                    verified_party = self._read_party_members(verified_capture, current)
                    for slot, expected_raw in encoded_slots.items():
                        actual_raw = verified_capture[slot - 1]
                        if (
                            actual_raw[:PK6_STORED_SIZE] != expected_raw[:PK6_STORED_SIZE]
                            or actual_raw[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]
                            != expected_raw[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]
                        ):
                            raise XYLiveError(f"Azahar no confirmó el rol, EV y estadísticas del slot {slot}.")
                        actual = verified_party.get(slot)
                        expected = expected_party[slot]
                        if actual is None or self._pokemon_identity(actual) != self._pokemon_identity(expected):
                            raise XYLiveError(f"La identidad del slot {slot} cambió durante el readback.")
                        if tuple(int(actual.evs.get(key, 0)) for key in (
                            "hp", "attack", "defense", "sp_attack", "sp_defense", "speed",
                        )) != tuple(int(expected.evs.get(key, 0)) for key in (
                            "hp", "attack", "defense", "sp_attack", "sp_defense", "speed",
                        )):
                            raise XYLiveError(f"X/Y no confirmó los EV del slot {slot}.")
                        if actual.role != expected.role:
                            raise XYLiveError(f"X/Y no confirmó el rol del slot {slot}.")

                    return ORASLiveWriteResult(
                        game=self._build_game(verified_capture, current, process, live_write=True),
                        process=process,
                        attempts=max(capture_attempt, verified_attempt),
                        applied_count=len(changes),
                    )
                except Exception as exc:
                    rollback_errors = self._rollback(client, attempted)
                    for address, original in dict(attempted).items():
                        try:
                            if bytes(client.read_memory(address, len(original))) != original:
                                rollback_errors.append(f"0x{address:08X}: readback distinto tras rollback")
                        except Exception as readback_exc:
                            rollback_errors.append(f"0x{address:08X}: {readback_exc}")
                    if rollback_errors:
                        raise XYLiveError(
                            f"El cambio de rol X/Y falló: {exc}. No se pudo confirmar toda la restauración: "
                            + "; ".join(rollback_errors)
                        ) from exc
                    if attempted:
                        raise XYLiveError(
                            f"El cambio de rol X/Y falló: {exc}. RoleRun restauró y verificó los bytes originales."
                        ) from exc
                    raise
        except AzaharRPCError as exc:
            raise XYLiveError(str(exc)) from exc

    @staticmethod
    def _box_slot_address(box: int, box_slot: int, *, base_address: int = 0) -> int:
        if not 1 <= int(box) <= XY_PC_BOX_COUNT or not 1 <= int(box_slot) <= XY_PC_BOX_SLOT_COUNT:
            raise XYLiveError("La posición de PC indicada no existe en X/Y.")
        index = (int(box) - 1) * XY_PC_BOX_SLOT_COUNT + (int(box_slot) - 1)
        return int(base_address) + index * PK6_STORED_SIZE

    def _scan_pc_base(self, client, changes: Sequence[PendingPCRoleChange | PendingTeamChange]) -> int | None:
        """Fallback X/Y para localizar una matriz de cajas antes de escribir.

        Reutiliza las identidades/testigos ya probados del escritor Gen6, pero
        con la ventana X/Y. Una coincidencia aislada nunca basta para escribir.
        """
        change = next((item for item in changes if len(self._pc_witnesses(item)) >= 2), None)
        if change is None:
            return None
        target_identity = self._pc_target_identity(change)
        target_index = ((int(change.box) - 1) * XY_PC_BOX_SLOT_COUNT + (int(change.box_slot) - 1))
        scan_start = (XY_PC_SCAN_START + 3) & ~3
        for block_address in range(scan_start, XY_PC_SCAN_END, XY_PC_SCAN_BLOCK_SIZE):
            candidate_size = min(XY_PC_SCAN_BLOCK_SIZE, XY_PC_SCAN_END - block_address)
            try:
                raw_block = bytes(client.read_memory(block_address, candidate_size + PK6_STORED_SIZE))
            except Exception:
                continue
            for offset in range(0, candidate_size, 4):
                if not any(raw_block[offset:offset + 4]) or any(raw_block[offset + 4:offset + 6]):
                    continue
                candidate = raw_block[offset:offset + PK6_STORED_SIZE]
                try:
                    pokemon = parse_pk6_boxed(candidate, int(change.box), int(change.box_slot), self.reader.move_names)
                except ORASLiveError:
                    continue
                if pokemon is None or self._pokemon_identity(pokemon) != target_identity:
                    continue
                base_address = int(block_address + offset - target_index * PK6_STORED_SIZE)
                if 0x08000000 <= base_address < 0x0A000000 and self._pc_base_matches(
                    client, base_address, changes, require_companion=True,
                ):
                    return base_address
        return None

    def _locate_pc_base(self, client, process: AzaharProcess, changes: Sequence[PendingPCRoleChange | PendingTeamChange]) -> int:
        if not changes:
            raise XYLiveError("X/Y no necesita localizar el PC para esta operación.")
        process_key = (int(process.title_id), str(process.name), self.reader.transport_label)
        candidates: list[int] = []
        cached = self._pc_bases_by_process.get(process_key)
        if cached is not None:
            candidates.append(int(cached))
        # Si la lectura del PC ya calibró la matriz, compartimos esa dirección.
        reader_cached = self.reader._pc_bases_by_process.get(process_key)
        if reader_cached is not None and int(reader_cached) not in candidates:
            candidates.append(int(reader_cached))
        if XY_PC_KNOWN_ADDRESS not in candidates:
            candidates.append(XY_PC_KNOWN_ADDRESS)
        for base_address in candidates:
            if self._pc_base_matches(client, base_address, changes, require_companion=False):
                self._pc_bases_by_process[process_key] = int(base_address)
                self.reader._pc_bases_by_process[process_key] = int(base_address)
                return int(base_address)
        discovered = self._scan_pc_base(client, changes)
        if discovered is not None:
            self._pc_bases_by_process[process_key] = int(discovered)
            self.reader._pc_bases_by_process[process_key] = int(discovered)
            return int(discovered)
        raise XYLiveError(
            "No se pudo localizar y validar la caja viva de X/Y con sus testigos. "
            "No se escribió ningún byte. Pulsa F5 y vuelve a intentarlo fuera de una transición del PC."
        )

    def _capture_stable_party_and_count(
        self, client,
    ) -> tuple[tuple[bytes, ...], int, int]:
        """Captura party y contador como una sola precondición estable.

        El contrato físico de X/Y exige un prefijo compacto: los ``count``
        primeros slots están ocupados. Una muestra que no cumpla esto se
        rechaza antes de escribir.

        2026-09-05: solo el byte bajo de ``XY_PARTY_COUNT_ADDRESS`` es el
        contador real -confirmado leyendo antes/después de un cambio de
        orden del equipo ajeno a RoleRun-. Los tres bytes altos son otro
        campo (probablemente ligado a la pantalla de Almacenamiento) que
        puede quedarse en un valor no nulo durante varios minutos; leerlos
        con ``struct.unpack("<I", ...)`` convertía un contador válido (5) en
        uno disparatado (261) y rechazaba la operación sin motivo real.

        2026-09-05, misma investigación: dejó de exigirse que los slots
        DESPUÉS del contador estén vacíos. Decodificando con las funciones
        reales del proyecto el propio slot 6 de la party real del usuario
        (con el contador en 5), seguía pasando el checksum PK6 como un
        Pokémon válido -es lo último que hubo ahí, el juego no lo borra al
        excluirlo del contador, solo dejó de contarlo-. Exigir que estuviera
        vacío rechazaba una party perfectamente sana. El contrato real de
        X/Y es "los primeros ``count`` están completos", no "el resto está
        vacío".
        """
        for attempt in range(1, self.reader.snapshot_attempts + 1):
            first_party = self.reader._read_party(client)
            first_count = bytes(client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second_party = self.reader._read_party(client)
            second_count = bytes(client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
            if first_party != second_party or first_count[0] != second_count[0]:
                continue
            count = int(second_count[0])
            if not 1 <= count <= 6:
                raise XYLiveError(f"X/Y declaró un contador de equipo inválido ({count}).")
            parsed = [
                parse_pk6_party(raw, index, self.reader.move_names)
                for index, raw in enumerate(second_party, start=1)
            ]
            if any(pokemon is None for pokemon in parsed[:count]):
                raise XYLiveError(
                    "El contador X/Y incluye un slot vacío; no se escribió ningún byte."
                )
            return second_party, count, attempt
        raise XYLiveError(
            "El equipo o su contador cambiaron durante todas las lecturas; "
            "sal del menú del juego y vuelve a intentarlo."
        )

    def _capture_stable_runtime_party_and_count(
        self, client,
    ) -> tuple[tuple[bytes, ...], tuple[bytes, ...], int, int]:
        """Captura los seis slots runtime completos y su vista PK6 publicada.

        El stride vivo de X/Y mide ``0x1E4``. Leer solo PK6 almacenado y stats
        dejaba fuera dos regiones no nulas y específicas de cada miembro; una
        escritura parcial podía superar su propio readback y ser deshecha por
        el juego. Esta captura convierte el stride completo en precondición y
        autoridad de verificación.

        2026-09-05: mismo criterio que ``_capture_stable_party_and_count``
        -solo el byte bajo del contador es real, los tres altos son otro
        campo que puede quedar en un valor no nulo mucho después de salir
        de la pantalla de Almacenamiento-, y tampoco se exige que los slots
        después del contador estén vacíos: el propio slot que el juego
        excluye sigue conteniendo lo último que hubo ahí, no se borra.
        """
        for attempt in range(1, self.reader.snapshot_attempts + 1):
            first_region = bytes(client.read_memory(XY_PARTY_ADDRESS, XY_PARTY_RUNTIME_SPAN))
            first_count = bytes(client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second_region = bytes(client.read_memory(XY_PARTY_ADDRESS, XY_PARTY_RUNTIME_SPAN))
            second_count = bytes(client.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
            if (
                _mask_xy_runtime_volatile_region(first_region)
                != _mask_xy_runtime_volatile_region(second_region)
                or first_count[0] != second_count[0]
            ):
                continue
            if len(second_region) != XY_PARTY_RUNTIME_SPAN:
                raise XYLiveError("Azahar devolvió una party runtime X/Y incompleta.")
            count = int(second_count[0])
            if not 1 <= count <= 6:
                raise XYLiveError(f"X/Y declaró un contador de equipo inválido ({count}).")
            runtime_slots = tuple(
                second_region[index * XY_PARTY_STRIDE:(index + 1) * XY_PARTY_STRIDE]
                for index in range(6)
            )
            tail_padding = PK6_PARTY_SIZE - PK6_STORED_SIZE - XY_PARTY_STATS_SIZE
            party_slots = tuple(
                slot[:PK6_STORED_SIZE]
                + slot[XY_PARTY_STATS_OFFSET:XY_PARTY_STATS_OFFSET + XY_PARTY_STATS_SIZE]
                + (b"\0" * tail_padding)
                for slot in runtime_slots
            )
            parsed = [
                parse_pk6_party(raw, index, self.reader.move_names)
                for index, raw in enumerate(party_slots, start=1)
            ]
            if any(pokemon is None for pokemon in parsed[:count]):
                raise XYLiveError("El contador X/Y incluye un slot vacío; no se escribió ningún byte.")
            return runtime_slots, party_slots, count, attempt
        raise XYLiveError(
            "La party runtime X/Y o su contador cambiaron durante todas las lecturas; "
            "sal del menú del juego y vuelve a intentarlo."
        )

    def _locate_empty_pc_destination(
        self, client, process: AzaharProcess, change: PendingTeamChange,
    ) -> int:
        """Resuelve una matriz PC cuyo destino debe estar vacío.

        Un hueco cero no identifica una matriz. Por ello se aceptan solamente
        bases ya conocidas/caché y al menos un Pokémon acompañante de la misma
        caja en su offset exacto. Nunca se escanea RAM tomando el vacío como
        ancla.
        """
        if change.box is None or change.box_slot is None:
            raise XYLiveError("El depósito X/Y no declara una casilla PC exacta.")
        companions = tuple(change.box_witnesses or ())
        if not companions:
            raise XYLiveError(
                "No hay un testigo ocupado de la caja destino X/Y. Pulsa F5 y "
                "vuelve a intentarlo; no se escribió ningún byte."
            )
        process_key = (int(process.title_id), str(process.name), self.reader.transport_label)
        candidates: list[int] = []
        for candidate in (
            self._pc_bases_by_process.get(process_key),
            self.reader._pc_bases_by_process.get(process_key),
            XY_PC_KNOWN_ADDRESS,
        ):
            if candidate is not None and int(candidate) not in candidates:
                candidates.append(int(candidate))
        for base_address in candidates:
            if not 0x08000000 <= base_address < 0x0A000000:
                continue
            target_address = self._box_slot_address(
                int(change.box), int(change.box_slot), base_address=base_address,
            )
            try:
                target_raw = bytes(client.read_memory(target_address, PK6_STORED_SIZE))
                if parse_pk6_boxed(
                    target_raw, int(change.box), int(change.box_slot), self.reader.move_names,
                ) is not None:
                    continue
                valid = True
                for witness_slot, expected_identity in companions:
                    witness_slot = int(witness_slot)
                    if witness_slot == int(change.box_slot):
                        valid = False
                        break
                    raw = bytes(client.read_memory(
                        self._box_slot_address(
                            int(change.box), witness_slot, base_address=base_address,
                        ),
                        PK6_STORED_SIZE,
                    ))
                    pokemon = parse_pk6_boxed(
                        raw, int(change.box), witness_slot, self.reader.move_names,
                    )
                    if pokemon is None or self._pokemon_identity(pokemon) != str(expected_identity):
                        valid = False
                        break
                if not valid:
                    continue
            except (ORASLiveError, ValueError, TypeError):
                continue
            self._pc_bases_by_process[process_key] = base_address
            self.reader._pc_bases_by_process[process_key] = base_address
            return base_address
        raise XYLiveError(
            "No se demostró la matriz PC X/Y con el destino vacío y sus testigos. "
            "No se escribió ningún byte."
        )

    def _validated_empty_pc_slot(
        self, client, *, base_address: int, excluded_addresses: Sequence[int] = (),
    ) -> bytes:
        """Obtiene el vacío real repetido de la matriz PC del mismo instante.

        X/Y materializa un BoxPokemon vacío como un PK6 cifrado no nulo. Los
        0xE8 ceros también parecen vacíos al parser conservador, pero el juego
        los muestra como un Huevo corrupto. Nunca inventamos la plantilla: se
        exige una matriz completa estable y al menos dos slots no nulos,
        semánticamente vacíos e idénticos.
        """
        first = bytes(client.read_memory(int(base_address), XY_PC_SIZE))
        if self.reader.stable_delay:
            time.sleep(self.reader.stable_delay)
        second = bytes(client.read_memory(int(base_address), XY_PC_SIZE))
        if first != second:
            raise XYLiveError(
                "La matriz PC X/Y cambió al demostrar su slot vacío; no se escribió ningún byte."
            )
        excluded = {int(address) for address in excluded_addresses}
        counts: dict[bytes, int] = {}
        for index in range(XY_PC_BOX_COUNT * XY_PC_BOX_SLOT_COUNT):
            address = int(base_address) + index * PK6_STORED_SIZE
            if address in excluded:
                continue
            raw = second[index * PK6_STORED_SIZE:(index + 1) * PK6_STORED_SIZE]
            if not any(raw):
                continue
            box, slot_index = divmod(index, XY_PC_BOX_SLOT_COUNT)
            try:
                pokemon = parse_pk6_boxed(raw, box + 1, slot_index + 1, self.reader.move_names)
            except ORASLiveError:
                continue
            if pokemon is None:
                counts[raw] = counts.get(raw, 0) + 1
        if not counts:
            raise XYLiveError(
                "No se encontró una representación vacía válida y no nula en el PC X/Y; "
                "no se escribió ningún byte."
            )
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        template, occurrences = ranked[0]
        if occurrences < 2 or (len(ranked) > 1 and ranked[1][1] == occurrences):
            raise XYLiveError(
                "La representación vacía del PC X/Y no quedó demostrada de forma única; "
                "no se escribió ningún byte."
            )
        return bytes(template)

    @staticmethod
    def _party_split_writes(slot_address: int, raw: bytes) -> tuple[tuple[int, bytes], ...]:
        if len(raw) != PK6_PARTY_SIZE:
            raise XYLiveError("El PK6 de equipo X/Y tiene un tamaño inesperado.")
        return (
            (int(slot_address), bytes(raw[:PK6_STORED_SIZE])),
            (
                int(slot_address) + XY_PARTY_STATS_OFFSET,
                bytes(raw[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]),
            ),
        )

    @staticmethod
    def _rollback_resize(client, attempted: Sequence[tuple[int, bytes]]) -> list[str]:
        """Restaura bloques y deja siempre el contador para el final."""
        originals: dict[int, bytes] = {}
        order: list[int] = []
        for address, original in attempted:
            address = int(address)
            if address not in originals:
                originals[address] = bytes(original)
                order.append(address)
        errors: list[str] = []
        restore_order = [
            address for address in reversed(order)
            if address != XY_PARTY_COUNT_ADDRESS
        ]
        if XY_PARTY_COUNT_ADDRESS in originals:
            restore_order.append(XY_PARTY_COUNT_ADDRESS)
        for address in restore_order:
            original = originals[address]
            try:
                client.write_memory(address, original)
                if bytes(client.read_memory(address, len(original))) != original:
                    errors.append(f"0x{address:08X}: readback distinto tras rollback")
            except Exception as exc:
                errors.append(f"0x{address:08X}: {exc}")
        return errors

    def _apply_party_resize(
        self, current: SaveGameData, change: PendingTeamChange,
    ) -> ORASLiveWriteResult:
        """Aplica Equipo↔PC X/Y con contador final y rollback verificado."""
        operation = str(change.operation)
        if operation not in {"party-to-box", "box-to-party"}:
            raise XYLiveError("La operación no cambia el tamaño de la party X/Y.")
        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                original_runtime, original_party, count, party_attempt = (
                    self._capture_stable_runtime_party_and_count(client)
                )
                members = self._read_party_members(original_party, current)
                original_identities = [self._pokemon_identity(members[index]) for index in range(1, count + 1)]

                if operation == "party-to-box":
                    if count <= 1:
                        raise XYLiveError("X/Y no permite depositar el último miembro del equipo.")
                    # Hasta 2026-09-05 esto rechazaba depositar con la party
                    # llena (count == 6): el compactado necesitaba
                    # ``original_runtime[count]`` como "plantilla" del nuevo
                    # slot sobrante, y con seis miembros no hay un séptimo
                    # slot que leer. Investigado en vivo con el usuario: el
                    # slot que queda fuera del contador NO es una plantilla
                    # vacía deliberada -al decodificarlo con las funciones
                    # reales del proyecto, sigue pasando el checksum PK6 como
                    # un Pokémon válido-, es simplemente lo que ya hubiera ahí
                    # antes; el juego nunca vuelve a leer esa posición
                    # mientras el contador la excluya. Por eso compactar
                    # SIEMPRE puede dejar el último slot físico exactamente
                    # como estaba -sin escribirlo- en vez de necesitar verlo
                    # vacío de antemano.
                    identity = str(change.outgoing_identity or "")
                    matches = [
                        slot for slot, pokemon in members.items()
                        if slot <= count and self._pokemon_identity(pokemon) == identity
                    ]
                    if identity and len(matches) != 1:
                        raise XYLiveError(
                            "La identidad del Pokémon que iba a salir ya no es única en la party X/Y."
                        )
                    source_slot = matches[0] if matches else int(change.party_slot)
                    if not 1 <= source_slot <= count or source_slot not in members:
                        raise XYLiveError("El slot saliente X/Y ya no contiene el Pokémon previsto.")
                    pc_base = self._locate_empty_pc_destination(client, process, change)
                else:
                    if count >= 6:
                        raise XYLiveError("El equipo X/Y ya contiene seis Pokémon.")
                    if change.box is None or change.box_slot is None:
                        raise XYLiveError("La incorporación X/Y no declara un origen PC exacto.")
                    source_slot = count + 1
                    pc_base = self._locate_pc_base(client, process, [change])

                pc_address = self._box_slot_address(
                    int(change.box), int(change.box_slot), base_address=pc_base,
                )
                empty_pc_stored = self._validated_empty_pc_slot(
                    client, base_address=pc_base, excluded_addresses=(pc_address,),
                )
                pc_original = bytes(client.read_memory(pc_address, PK6_STORED_SIZE))
                if self.reader.stable_delay:
                    time.sleep(self.reader.stable_delay)
                if bytes(client.read_memory(pc_address, PK6_STORED_SIZE)) != pc_original:
                    raise XYLiveError("La casilla PC X/Y cambió durante la precondición.")

                # La operación nativa de depósito demostró que la superficie
                # invitada leída por RPC es la autoridad que consume Pokémon X.
                # Una copia anfitriona encontrada por contenido puede aceptar
                # el mismo write/readback y, aun así, no gobernar el juego.
                # Por eso la transacción y su rollback se realizan sobre el
                # cliente invitado ya validado, nunca sobre una coincidencia host.
                authority = client

                attempted: list[tuple[int, bytes]] = []
                try:
                    # Relectura inmediata de todos los testigos antes del primer byte.
                    fresh_runtime, fresh_party, fresh_count, _ = (
                        self._capture_stable_runtime_party_and_count(client)
                    )
                    if (
                        _mask_xy_runtime_volatile_tuple(fresh_runtime)
                        != _mask_xy_runtime_volatile_tuple(original_runtime)
                        or fresh_party != original_party
                        or fresh_count != count
                    ):
                        raise XYLiveError("La party X/Y cambió antes de escribir; no se escribió ningún byte.")
                    if bytes(client.read_memory(pc_address, PK6_STORED_SIZE)) != pc_original:
                        raise XYLiveError("La casilla PC X/Y cambió antes de escribir.")

                    def write(address: int, payload: bytes) -> None:
                        original = bytes(authority.read_memory(address, len(payload)))
                        attempted.append((int(address), original))
                        authority.write_memory(int(address), bytes(payload))
                        if bytes(authority.read_memory(address, len(payload))) != bytes(payload):
                            raise XYLiveError(
                                f"Azahar no confirmó la escritura invitada X/Y en 0x{address:08X}."
                            )

                    if operation == "party-to-box":
                        if parse_pk6_boxed(
                            pc_original, int(change.box), int(change.box_slot), self.reader.move_names,
                        ) is not None:
                            raise XYLiveError("La casilla destino X/Y dejó de estar vacía.")
                        outgoing_full = original_party[source_slot - 1]
                        outgoing = members[source_slot]
                        if change.outgoing_identity and self._pokemon_identity(outgoing) != change.outgoing_identity:
                            raise XYLiveError("El miembro saliente X/Y cambió antes de escribir.")
                        write(pc_address, outgoing_full[:PK6_STORED_SIZE])
                        # X/Y mantiene 0x1E4 bytes por miembro. Las regiones
                        # omitidas por el PK6 publicado son no nulas y cambian
                        # con el slot; por ello la compactación mueve la unidad
                        # runtime completa, no solo stored+stats.
                        for slot in range(source_slot, count):
                            write(self._slot_address(slot), original_runtime[slot])
                        # Con menos de seis miembros, el slot que queda fuera
                        # del nuevo contador recibe lo que ya había en el
                        # siguiente -no es una plantilla vacía deliberada,
                        # solo contenido observado que el juego nunca vuelve
                        # a leer una vez excluido por el contador-. Con la
                        # party llena (count == 6) no hay un séptimo slot que
                        # copiar: el último slot físico se deja tal cual
                        # está -ya es, como mucho, un duplicado de lo que
                        # acaba de entrar en el slot anterior- sin escribirlo.
                        if count < 6:
                            write(self._slot_address(count), original_runtime[count])
                        expected_count = count - 1
                    else:
                        incoming = parse_pk6_boxed(
                            pc_original, int(change.box), int(change.box_slot), self.reader.move_names,
                        )
                        if incoming is None or (
                            change.incoming_identity
                            and self._pokemon_identity(incoming) != change.incoming_identity
                        ):
                            raise XYLiveError("El Pokémon origen del PC X/Y ya no coincide.")
                        stored, was_encrypted = _plain_stored_pk6(pc_original)
                        data = bytearray(stored)
                        role = str(change.incoming_role or incoming.role or "SIN ROL")
                        self._set_role(data, role)
                        ev_map = dict(change.incoming_snapshot.get("evs", {}) or {})
                        stat_keys = ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")
                        if ev_map:
                            desired = tuple(int(ev_map[key]) for key in stat_keys)
                            data[0x1E:0x24] = bytes(self._native_evs(desired))
                        self._remove_move_slots(data, change.remove_move_slots)
                        self._refresh_checksum(data)
                        species = int(struct.unpack_from("<H", data, 0x08)[0])
                        form = (int(data[0x1D]) >> 3) & 0x1F
                        personal = self.personal_for(species, form) if self.personal_for else None
                        if personal is None:
                            raise XYLiveError(
                                "Falta la tabla Personal X/Y exacta para construir el miembro de party."
                            )
                        plain_full = bytes(data) + self._party_extension(data, personal)
                        incoming_full = encrypt_pk6(plain_full) if was_encrypted else plain_full
                        destination_runtime = bytearray(original_runtime[count])
                        destination_runtime[:PK6_STORED_SIZE] = incoming_full[:PK6_STORED_SIZE]
                        destination_runtime[
                            XY_PARTY_STATS_OFFSET:XY_PARTY_STATS_OFFSET + XY_PARTY_STATS_SIZE
                        ] = incoming_full[
                            PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE
                        ]
                        write(self._slot_address(source_slot), bytes(destination_runtime))
                        write(pc_address, empty_pc_stored)
                        expected_count = count + 1

                    # El contador es el commit point y siempre se escribe al final.
                    # 2026-09-05, investigación en vivo con el usuario: los tres
                    # bytes altos de esta u32 NO son siempre cero -se demostró
                    # leyendo antes/después de un cambio de orden del equipo
                    # ajeno a RoleRun, que dejó el segundo byte en 0x01 durante
                    # varios minutos (probablemente ligado a haber visitado la
                    # pantalla de Almacenamiento) antes de volver a 0x00-.
                    # Escribir ``struct.pack("<I", expected_count)`` a ciegas
                    # pondría esos bytes a cero sin saber qué representan de
                    # verdad. Se conservan tal cual están justo antes de
                    # escribir, y solo se sustituye el byte bajo (el contador
                    # real, confirmado 1..6 en todas las lecturas).
                    current_count_bytes = bytes(authority.read_memory(XY_PARTY_COUNT_ADDRESS, XY_PARTY_COUNT_SIZE))
                    write(
                        XY_PARTY_COUNT_ADDRESS,
                        bytes([expected_count & 0xFF]) + current_count_bytes[1:],
                    )

                    verified_runtime, verified_party, verified_count, verified_attempt = (
                        self._capture_stable_runtime_party_and_count(client)
                    )
                    verified_members = self._read_party_members(verified_party, current)
                    verified_identities = [
                        self._pokemon_identity(verified_members[index])
                        for index in range(1, verified_count + 1)
                    ]
                    verified_pc = bytes(client.read_memory(pc_address, PK6_STORED_SIZE))
                    if operation == "party-to-box":
                        expected_ids = original_identities[:source_slot - 1] + original_identities[source_slot:]
                        moved = parse_pk6_boxed(
                            verified_pc, int(change.box), int(change.box_slot), self.reader.move_names,
                        )
                        if verified_count != count - 1 or verified_identities != expected_ids:
                            raise XYLiveError("X/Y no confirmó la compactación exacta de la party.")
                        if moved is None or self._pokemon_identity(moved) != original_identities[source_slot - 1]:
                            raise XYLiveError("X/Y no confirmó el Pokémon exacto en el destino PC.")
                        expected_runtime_list = list(original_runtime)
                        for slot in range(source_slot, count):
                            expected_runtime_list[slot - 1] = original_runtime[slot]
                        # Con la party llena no se tocó el último slot físico
                        # (ver el comentario junto a la escritura); sigue
                        # siendo ``original_runtime[count - 1]``, ya presente
                        # en ``expected_runtime_list`` sin modificar.
                        if count < 6:
                            expected_runtime_list[count - 1] = original_runtime[count]
                        expected_runtime = tuple(expected_runtime_list)
                        if (
                            _mask_xy_runtime_volatile_tuple(verified_runtime)
                            != _mask_xy_runtime_volatile_tuple(expected_runtime)
                        ):
                            raise XYLiveError("X/Y no confirmó la estructura runtime completa de la party.")
                    else:
                        added = verified_members.get(count + 1)
                        if (
                            verified_count != count + 1
                            or verified_identities[:count] != original_identities
                            or added is None
                            or self._pokemon_identity(added) != str(change.incoming_identity)
                            or added.role != str(change.incoming_role)
                        ):
                            raise XYLiveError("X/Y no confirmó la incorporación exacta al final de la party.")
                        if parse_pk6_boxed(
                            verified_pc, int(change.box), int(change.box_slot), self.reader.move_names,
                        ) is not None:
                            raise XYLiveError("X/Y no confirmó vacío el origen PC.")

                    # El readback inmediato de alpha.10 solo demostraba que
                    # Azahar aceptaba momentáneamente los bytes. Esperamos y
                    # volvemos a leer la autoridad completa para detectar si
                    # el juego restaura su propia estructura.
                    if self.party_commit_settle_delay:
                        time.sleep(self.party_commit_settle_delay)
                    settled_runtime, settled_party, settled_count, settled_attempt = (
                        self._capture_stable_runtime_party_and_count(client)
                    )
                    settled_pc = bytes(client.read_memory(pc_address, PK6_STORED_SIZE))
                    if (
                        _mask_xy_runtime_volatile_tuple(settled_runtime)
                        != _mask_xy_runtime_volatile_tuple(verified_runtime)
                        or settled_party != verified_party
                        or settled_count != verified_count
                        or settled_pc != verified_pc
                    ):
                        raise XYLiveError(
                            "El juego restauró la party o el PC después del readback inmediato; "
                            "la operación no quedó comprometida."
                        )
                    # ``_build_game`` no conoce el contador: incluye cualquier
                    # slot que decodifique como Pokémon válido. Como el slot
                    # que queda fuera del contador puede seguir teniendo lo
                    # último que hubo ahí (ver el comentario de
                    # ``_capture_stable_runtime_party_and_count``), hay que
                    # truncar explícitamente a los ``settled_count`` slots que
                    # el propio juego reconoce, o ese sobrante se colaría como
                    # un miembro duplicado.
                    return ORASLiveWriteResult(
                        game=self._build_game(
                            settled_party[:settled_count], current, process, live_write=True,
                        ),
                        process=process,
                        attempts=max(party_attempt, verified_attempt, settled_attempt),
                        applied_count=1,
                    )
                except Exception as exc:
                    rollback_errors = self._rollback_resize(authority, attempted)
                    if attempted:
                        try:
                            rolled_runtime, _rolled_party, rolled_count, _ = (
                                self._capture_stable_runtime_party_and_count(client)
                            )
                            rolled_pc = bytes(client.read_memory(pc_address, PK6_STORED_SIZE))
                            if (
                                _mask_xy_runtime_volatile_tuple(rolled_runtime)
                                != _mask_xy_runtime_volatile_tuple(original_runtime)
                            ):
                                rollback_errors.append("RPC: party distinta tras rollback invitado")
                            if rolled_count != count:
                                rollback_errors.append("RPC: contador distinto tras rollback invitado")
                            if rolled_pc != pc_original:
                                rollback_errors.append("RPC: casilla PC distinta tras rollback invitado")
                        except Exception as rollback_exc:
                            rollback_errors.append(f"RPC: readback de rollback falló: {rollback_exc}")
                    if rollback_errors:
                        raise XYLiveError(
                            f"El cambio de tamaño X/Y falló: {exc}. No se pudo confirmar toda "
                            "la restauración: " + "; ".join(rollback_errors)
                        ) from exc
                    if attempted:
                        raise XYLiveError(
                            f"El cambio de tamaño X/Y falló: {exc}. RoleRun restauró y "
                            "verificó party, PC y contador."
                        ) from exc
                    raise
        except AzaharRPCError as exc:
            raise XYLiveError(str(exc)) from exc

    def _apply_pc_move(
        self,
        current: SaveGameData,
        change: PendingTeamChange,
    ) -> ORASLiveWriteResult:
        """Mueve un PK6 entre dos casillas exactas sin alterar la party.

        La matriz X/Y y su stride de 0xE8 bytes ya son la misma superficie que
        usa el lector de cajas. El origen actúa como testigo de identidad; el
        destino debe ser una casilla vacía demostrada. Se copia primero el PK6
        exacto al destino y solo entonces se vacía el origen. Cualquier fallo
        restaura y verifica ambos bloques originales.
        """
        source_box = int(change.box or 0)
        source_slot = int(change.box_slot or 0)
        destination_box = int(change.destination_box or 0)
        destination_slot = int(change.destination_box_slot or 0)
        if min(source_box, source_slot, destination_box, destination_slot) <= 0:
            raise XYLiveError("El movimiento PC→PC de X/Y no contiene un origen y destino completos.")
        if (source_box, source_slot) == (destination_box, destination_slot):
            raise XYLiveError("El origen y el destino del movimiento PC→PC de X/Y son la misma casilla.")
        expected_identity = str(change.incoming_identity or "")
        if not expected_identity:
            raise XYLiveError("El movimiento PC→PC de X/Y no contiene una identidad estable.")

        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                party_capture, party_attempt = self._capture_stable_party(client)
                pc_base = self._locate_pc_base(client, process, [change])
                source_address = self._box_slot_address(
                    source_box, source_slot, base_address=pc_base,
                )
                destination_address = self._box_slot_address(
                    destination_box, destination_slot, base_address=pc_base,
                )

                def stable_pair() -> tuple[bytes, bytes, int]:
                    for attempt in range(1, self.reader.snapshot_attempts + 1):
                        first = (
                            bytes(client.read_memory(source_address, PK6_STORED_SIZE)),
                            bytes(client.read_memory(destination_address, PK6_STORED_SIZE)),
                        )
                        if self.reader.stable_delay:
                            time.sleep(self.reader.stable_delay)
                        second = (
                            bytes(client.read_memory(source_address, PK6_STORED_SIZE)),
                            bytes(client.read_memory(destination_address, PK6_STORED_SIZE)),
                        )
                        if first == second:
                            return second[0], second[1], attempt
                    raise XYLiveError(
                        "Las casillas del PC de X/Y cambiaron durante todas las lecturas; "
                        "no se escribió ningún byte."
                    )

                source_original, destination_original, pc_attempt = stable_pair()
                source_pokemon = parse_pk6_boxed(
                    source_original, source_box, source_slot, self.reader.move_names,
                )
                if source_pokemon is None or self._pokemon_identity(source_pokemon) != expected_identity:
                    raise XYLiveError(
                        "El Pokémon de origen ya no coincide con la identidad seleccionada; "
                        "no se escribió ningún byte."
                    )
                destination_pokemon = parse_pk6_boxed(
                    destination_original, destination_box, destination_slot, self.reader.move_names,
                )
                if destination_pokemon is not None:
                    raise XYLiveError(
                        "La casilla de destino de X/Y está ocupada; no se escribió ningún byte."
                    )

                # Precondición inmediata: no confiar en la captura anterior si
                # el usuario o el juego movieron algo mientras se preparaba.
                if bytes(client.read_memory(source_address, PK6_STORED_SIZE)) != source_original:
                    raise XYLiveError("La casilla de origen cambió antes de escribir; no se escribió ningún byte.")
                if bytes(client.read_memory(destination_address, PK6_STORED_SIZE)) != destination_original:
                    raise XYLiveError("La casilla de destino cambió antes de escribir; no se escribió ningún byte.")

                empty_stored = self._validated_empty_pc_slot(
                    client,
                    base_address=pc_base,
                    excluded_addresses=(source_address, destination_address),
                )
                attempted: list[tuple[int, bytes]] = []
                try:
                    attempted.append((destination_address, destination_original))
                    client.write_memory(destination_address, source_original)
                    if bytes(client.read_memory(destination_address, PK6_STORED_SIZE)) != source_original:
                        raise XYLiveError("Azahar no confirmó el PK6 exacto en la casilla de destino.")

                    attempted.append((source_address, source_original))
                    client.write_memory(source_address, empty_stored)
                    if bytes(client.read_memory(source_address, PK6_STORED_SIZE)) != empty_stored:
                        raise XYLiveError("Azahar no confirmó la casilla de origen vacía.")

                    verified_source, verified_destination, verified_attempt = stable_pair()
                    if verified_source != empty_stored or parse_pk6_boxed(
                        verified_source, source_box, source_slot, self.reader.move_names,
                    ) is not None:
                        raise XYLiveError("X/Y no confirmó semánticamente el origen vacío.")
                    moved = parse_pk6_boxed(
                        verified_destination, destination_box, destination_slot, self.reader.move_names,
                    )
                    if (
                        verified_destination != source_original
                        or moved is None
                        or self._pokemon_identity(moved) != expected_identity
                    ):
                        raise XYLiveError("X/Y no confirmó el Pokémon exacto en el destino solicitado.")

                    # El RPC puede devolver durante unos milisegundos los bytes
                    # recién escritos aunque Pokémon X todavía no los haya
                    # adoptado. La captura física que descubrió la base real del
                    # PC demostró precisamente ese falso positivo. Exigimos una
                    # segunda pareja estable después del mismo tiempo de
                    # asentamiento que usa Equipo↔PC.
                    if self.party_commit_settle_delay:
                        time.sleep(self.party_commit_settle_delay)
                    settled_source, settled_destination, settled_attempt = stable_pair()
                    if (
                        settled_source != verified_source
                        or settled_destination != verified_destination
                    ):
                        raise XYLiveError(
                            "El juego restauró las casillas del PC después del readback "
                            "inmediato; el movimiento no quedó comprometido."
                        )

                    return ORASLiveWriteResult(
                        game=self._build_game(party_capture, current, process, live_write=True),
                        process=process,
                        attempts=max(
                            party_attempt, pc_attempt, verified_attempt, settled_attempt,
                        ),
                        applied_count=1,
                    )
                except Exception as exc:
                    rollback_errors = self._rollback(client, attempted)
                    for address, original in dict(attempted).items():
                        try:
                            if bytes(client.read_memory(address, len(original))) != original:
                                rollback_errors.append(f"0x{address:08X}: readback distinto tras rollback")
                        except Exception as readback_exc:
                            rollback_errors.append(f"0x{address:08X}: {readback_exc}")
                    if rollback_errors:
                        raise XYLiveError(
                            f"El movimiento PC→PC de X/Y falló: {exc}. No se pudo confirmar toda "
                            "la restauración: " + "; ".join(rollback_errors)
                        ) from exc
                    if attempted:
                        raise XYLiveError(
                            f"El movimiento PC→PC de X/Y falló: {exc}. RoleRun restauró y "
                            "verificó ambas casillas originales."
                        ) from exc
                    raise
        except AzaharRPCError as exc:
            raise XYLiveError(str(exc)) from exc

    def _apply_pc_swap(
        self,
        current: SaveGameData,
        change: PendingTeamChange,
    ) -> ORASLiveWriteResult:
        """Intercambia dos casillas ocupadas del PC de X/Y, sin tocar el equipo.

        2026-09-05: mismo caso que ``_apply_pc_move`` no cubre -allí el destino
        tiene que estar libre-, aquí las dos casillas están ocupadas y las dos
        identidades se conocen de antemano. Reutiliza la misma localización de
        caja por testigos (``_locate_pc_base``) y el mismo patrón de
        lectura-doble/escritura/verificación/asentamiento ya validado en
        ``_apply_pc_move``, sin necesitar ningún vacío como plantilla.
        """
        source_box = int(change.box or 0)
        source_slot = int(change.box_slot or 0)
        destination_box = int(change.destination_box or 0)
        destination_slot = int(change.destination_box_slot or 0)
        if min(source_box, source_slot, destination_box, destination_slot) <= 0:
            raise XYLiveError("El intercambio PC→PC de X/Y no contiene un origen y un destino completos.")
        if (source_box, source_slot) == (destination_box, destination_slot):
            raise XYLiveError("El origen y el destino del intercambio PC→PC de X/Y son la misma casilla.")
        source_identity = str(change.incoming_identity or "")
        destination_identity = str(change.outgoing_identity or "")
        if not source_identity or not destination_identity:
            raise XYLiveError(
                "El intercambio PC→PC de X/Y necesita la identidad estable de los DOS "
                "Pokémon implicados. No se escribió ningún byte."
            )
        if source_identity == destination_identity:
            raise XYLiveError(
                "Las dos casillas del intercambio PC→PC de X/Y declaran el mismo Pokémon. "
                "No se escribió ningún byte."
            )

        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                party_capture, party_attempt = self._capture_stable_party(client)
                pc_base = self._locate_pc_base(client, process, [change])
                source_address = self._box_slot_address(
                    source_box, source_slot, base_address=pc_base,
                )
                destination_address = self._box_slot_address(
                    destination_box, destination_slot, base_address=pc_base,
                )

                def stable_pair() -> tuple[bytes, bytes, int]:
                    for attempt in range(1, self.reader.snapshot_attempts + 1):
                        first = (
                            bytes(client.read_memory(source_address, PK6_STORED_SIZE)),
                            bytes(client.read_memory(destination_address, PK6_STORED_SIZE)),
                        )
                        if self.reader.stable_delay:
                            time.sleep(self.reader.stable_delay)
                        second = (
                            bytes(client.read_memory(source_address, PK6_STORED_SIZE)),
                            bytes(client.read_memory(destination_address, PK6_STORED_SIZE)),
                        )
                        if first == second:
                            return second[0], second[1], attempt
                    raise XYLiveError(
                        "Las casillas del PC de X/Y cambiaron durante todas las lecturas; "
                        "no se escribió ningún byte."
                    )

                source_original, destination_original, pc_attempt = stable_pair()
                for raw, box, slot, identity, label in (
                    (source_original, source_box, source_slot, source_identity, "origen"),
                    (
                        destination_original, destination_box, destination_slot,
                        destination_identity, "destino",
                    ),
                ):
                    pokemon = parse_pk6_boxed(raw, box, slot, self.reader.move_names)
                    if pokemon is None or self._pokemon_identity(pokemon) != identity:
                        raise XYLiveError(
                            f"El Pokémon de {label} ({box}:{slot}) ya no coincide con el que se "
                            "arrastró; no se escribió ningún byte. Pulsa F5 y vuelve a intentarlo."
                        )

                # Precondición inmediata: la captura anterior no vale si el
                # juego o el usuario movieron algo mientras se preparaba.
                if bytes(client.read_memory(source_address, PK6_STORED_SIZE)) != source_original:
                    raise XYLiveError(
                        "La casilla de origen cambió antes de escribir; no se escribió ningún byte."
                    )
                if bytes(client.read_memory(destination_address, PK6_STORED_SIZE)) != destination_original:
                    raise XYLiveError(
                        "La casilla de destino cambió antes de escribir; no se escribió ningún byte."
                    )

                attempted: list[tuple[int, bytes]] = []
                try:
                    for address, replacement, original in (
                        (destination_address, source_original, destination_original),
                        (source_address, destination_original, source_original),
                    ):
                        attempted.append((address, original))
                        client.write_memory(address, replacement)
                        if bytes(client.read_memory(address, PK6_STORED_SIZE)) != replacement:
                            raise XYLiveError(
                                f"Azahar no confirmó el PK6 exacto en 0x{address:08X}."
                            )

                    def verify_once() -> tuple[bytes, bytes, int]:
                        verified_source, verified_destination, attempt = stable_pair()
                        for raw, expected, box, slot, identity in (
                            (
                                verified_source, destination_original,
                                source_box, source_slot, destination_identity,
                            ),
                            (
                                verified_destination, source_original,
                                destination_box, destination_slot, source_identity,
                            ),
                        ):
                            pokemon = parse_pk6_boxed(raw, box, slot, self.reader.move_names)
                            if (
                                raw != expected
                                or pokemon is None
                                or self._pokemon_identity(pokemon) != identity
                            ):
                                raise XYLiveError(
                                    f"X/Y no confirmó el Pokémon esperado en la casilla "
                                    f"{box}:{slot} tras el intercambio."
                                )
                        return verified_source, verified_destination, attempt

                    verified_source, verified_destination, verified_attempt = verify_once()

                    # Mismo hallazgo que en Equipo↔PC y en _apply_pc_move: Azahar
                    # puede confirmar bytes que el juego todavía no ha adoptado.
                    if self.party_commit_settle_delay:
                        time.sleep(self.party_commit_settle_delay)
                    settled_source, settled_destination, settled_attempt = verify_once()
                    if (
                        settled_source != verified_source
                        or settled_destination != verified_destination
                    ):
                        raise XYLiveError(
                            "El juego restauró las casillas del PC después del readback "
                            "inmediato; el intercambio no quedó comprometido."
                        )

                    return ORASLiveWriteResult(
                        game=self._build_game(party_capture, current, process, live_write=True),
                        process=process,
                        attempts=max(
                            party_attempt, pc_attempt, verified_attempt, settled_attempt,
                        ),
                        applied_count=1,
                    )
                except Exception as exc:
                    rollback_errors = self._rollback(client, attempted)
                    for address, original in dict(attempted).items():
                        try:
                            if bytes(client.read_memory(address, len(original))) != original:
                                rollback_errors.append(f"0x{address:08X}: readback distinto tras rollback")
                        except Exception as readback_exc:
                            rollback_errors.append(f"0x{address:08X}: {readback_exc}")
                    if rollback_errors:
                        raise XYLiveError(
                            f"El intercambio PC→PC de X/Y falló: {exc}. No se pudo confirmar toda "
                            "la restauración: " + "; ".join(rollback_errors)
                        ) from exc
                    if attempted:
                        raise XYLiveError(
                            f"El intercambio PC→PC de X/Y falló: {exc}. RoleRun restauró y "
                            "verificó ambas casillas originales."
                        ) from exc
                    raise
        except AzaharRPCError as exc:
            raise XYLiveError(str(exc)) from exc

    @staticmethod
    def _xy_inventory_witness_map(
        changes: Sequence[PendingInventoryChange],
    ) -> dict[str, dict[int, tuple[int, int]]]:
        """Normaliza testigos del ``main`` para localizar la bolsa completa X/Y.

        Un testigo positivo exige item+cantidad en el MISMO slot. Un slot
        negativo ``-item_id`` expresa ausencia del objeto en ese bolsillo. La
        escritura solo se habilita con varios testigos independientes.
        """
        result: dict[str, dict[int, tuple[int, int]]] = {}
        for change in changes:
            for entry in tuple(getattr(change, "inventory_witnesses", ()) or ()):
                try:
                    label, slot, item_id, quantity = entry
                    label = str(label or "").casefold()
                    slot = int(slot)
                    item_id = int(item_id)
                    quantity = int(quantity)
                except (TypeError, ValueError):
                    continue
                if label not in XY_BAG_POUCH_LAYOUT or label not in {"items", "medicine", "tms"}:
                    continue
                _offset, size = XY_BAG_POUCH_LAYOUT[label]
                slot_count = size // ORAS_ITEM_RECORD_SIZE
                if not 1 <= item_id <= 1500:
                    continue
                if slot >= 0:
                    if slot >= slot_count or not 1 <= quantity <= XY_MAX_BAG_QUANTITY:
                        continue
                elif slot == -item_id:
                    if quantity != 0:
                        continue
                else:
                    continue
                entries = result.setdefault(label, {})
                value = (item_id, quantity)
                previous = entries.get(slot)
                if previous is not None and previous != value:
                    raise XYLiveError(
                        "La mochila X/Y cambió entre operaciones pendientes. Pulsa F5 y vuelve a preparar la utilidad."
                    )
                entries[slot] = value

        positives_by_label = {
            label: sum(
                1 for slot, (_item_id, quantity) in entries.items()
                if slot >= 0 and quantity > 0
            )
            for label, entries in result.items()
        }
        positive_total = sum(positives_by_label.values())
        if positive_total < 2 or max(positives_by_label.values(), default=0) < 2:
            raise XYLiveError(
                "No hay suficientes objetos del último guardado para localizar con seguridad la mochila viva de X/Y. "
                "Guarda normalmente dentro del juego, pulsa F5 y vuelve a intentarlo. No se escribió ningún byte."
            )
        return result

    @staticmethod
    def _prepare_xy_inventory_value(
        pocket: bytearray, item_id: int, quantity: int, *, label: str,
    ) -> list[int]:
        if not 1 <= int(item_id) <= 1500 or not 1 <= int(quantity) <= XY_MAX_BAG_QUANTITY:
            raise XYLiveError(f"El valor pedido para {label} no es válido en X/Y.")
        matching: list[int] = []
        empty: list[int] = []
        for offset in range(0, len(pocket), ORAS_ITEM_RECORD_SIZE):
            existing_id, existing_quantity = struct.unpack_from("<HH", pocket, offset)
            if int(existing_id) == int(item_id):
                matching.append(offset)
            elif int(existing_id) == 0 and int(existing_quantity) == 0:
                empty.append(offset)
        if len(matching) > 1:
            raise XYLiveError(f"El objeto {label} aparece dos veces en la mochila X/Y; no se escribió nada.")
        if matching:
            offset = matching[0]
        elif empty:
            offset = empty[0]
        else:
            raise XYLiveError(f"No hay hueco libre para {label} en la mochila de X/Y.")
        struct.pack_into("<HH", pocket, offset, int(item_id), int(quantity))
        return [int(offset)]

    @staticmethod
    def _generic_pocket_records(raw: bytes) -> tuple[tuple[int, int], ...] | None:
        if len(raw) % ORAS_ITEM_RECORD_SIZE:
            return None
        rows: list[tuple[int, int]] = []
        for offset in range(0, len(raw), ORAS_ITEM_RECORD_SIZE):
            item_id, quantity = struct.unpack_from("<HH", raw, offset)
            if item_id == 0 and quantity == 0:
                rows.append((0, 0))
                continue
            if not 1 <= int(item_id) <= 1500 or not 1 <= int(quantity) <= XY_MAX_BAG_QUANTITY:
                return None
            rows.append((int(item_id), int(quantity)))
        return tuple(rows)

    @classmethod
    def _bag_structure_score(cls, raw: bytes) -> tuple[int, int] | None:
        """Valida el layout completo MyItem de X/Y sin depender de cantidades guardadas.

        Las cantidades de una mochila viva pueden cambiar legítimamente después del
        último guardado (usar un repelente/caramelo, comprar, etc.). Para decidir si
        una base de RAM es estructuralmente una mochila exigimos que TODOS los
        bolsillos tengan registros u16 item/u16 cantidad válidos. La identidad de la
        copia se demuestra aparte con la MT viva calibrada o con varios IDs testigo.
        """
        if len(raw) != XY_SAVE_ITEMS_SIZE:
            return None
        occupied = 0
        nonempty_pockets = 0
        for pocket_offset, pocket_size in XY_BAG_POUCH_LAYOUT.values():
            pocket = bytes(raw[pocket_offset:pocket_offset + pocket_size])
            rows = cls._generic_pocket_records(pocket)
            if rows is None:
                return None
            count = sum(1 for item_id, quantity in rows if item_id and quantity)
            occupied += count
            nonempty_pockets += int(count > 0)
        if occupied <= 0:
            return None
        return int(nonempty_pockets), int(occupied)

    @classmethod
    def _bag_candidate_score(
        cls,
        raw: bytes,
        witnesses: Mapping[str, Mapping[int, tuple[int, int]]],
        volatile_item_ids: Sequence[int] = (),
    ) -> tuple[int, int, int, int, int] | None:
        """Puntúa una mochila por identidad de slots, no por cantidades congeladas.

        Alpha.17/18 requería que *todas* las cantidades siguieran idénticas al
        último ``main``. Eso invalida precisamente la mochila correcta cuando el
        jugador usa/compra un objeto entre guardados. Alpha.19 trata las cantidades
        como señal adicional: el ID en el mismo slot es la prueba primaria. El
        objeto que vamos a modificar se excluye por completo de la huella para que
        su cantidad/presencia actual nunca impida localizar la mochila.
        """
        structural = cls._bag_structure_score(raw)
        if structural is None:
            return None
        volatile = {int(value) for value in volatile_item_ids}
        id_matches = 0
        exact = 0
        absences = 0
        matched_pockets: set[str] = set()
        usable_positive = 0
        for label, entries in witnesses.items():
            if label not in XY_BAG_POUCH_LAYOUT:
                return None
            pocket_offset, pocket_size = XY_BAG_POUCH_LAYOUT[label]
            pocket = bytes(raw[pocket_offset:pocket_offset + pocket_size])
            rows = cls._generic_pocket_records(pocket)
            if rows is None:
                return None
            present_ids = {item_id for item_id, quantity in rows if item_id and quantity}
            for slot, (item_id, quantity) in entries.items():
                item_id = int(item_id)
                quantity = int(quantity)
                if item_id in volatile:
                    continue
                if int(slot) >= 0:
                    usable_positive += 1
                    if int(slot) < len(rows) and int(rows[int(slot)][0]) == item_id and int(rows[int(slot)][1]) > 0:
                        id_matches += 1
                        matched_pockets.add(label)
                        exact += int(int(rows[int(slot)][1]) == quantity)
                elif item_id not in present_ids:
                    # La ausencia es solo un refuerzo: obtener un objeto nuevo desde
                    # el último save no puede convertir una mochila real en inválida.
                    absences += 1

        # Dos IDs independientes en sus slots exactos son necesarios para aceptar
        # una base encontrada por dirección histórica/barrido. Si disponemos de la
        # MT viva calibrada, _locate_bag_base usa una prueba todavía más fuerte:
        # igualdad byte a byte de todo el bolsillo MT (0x1A4 bytes).
        required = 2 if usable_positive >= 2 else usable_positive
        if required <= 0 or id_matches < required:
            return None
        nonempty_pockets, occupied = structural
        return int(id_matches), int(exact), len(matched_pockets), int(nonempty_pockets), int(occupied)

    def _read_stable_bag_at(self, client, address: int) -> bytes | None:
        try:
            first = bytes(client.read_memory(int(address), XY_SAVE_ITEMS_SIZE))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = bytes(client.read_memory(int(address), XY_SAVE_ITEMS_SIZE))
        except Exception:
            return None
        return second if first == second else None

    def _discover_bag(
        self,
        client,
        witnesses: Mapping[str, Mapping[int, tuple[int, int]]],
        volatile_item_ids: Sequence[int] = (),
    ) -> tuple[MemoryCandidateHint, ...]:
        # La cantidad puede haber cambiado desde el último guardado, así que el
        # barrido deriva candidatas a partir del item_id alineado en su slot y deja
        # que _bag_candidate_score exija varias identidades independientes.
        volatile = {int(value) for value in volatile_item_ids}
        positives: dict[str, list[tuple[int, int, int]]] = {}
        for label, entries in witnesses.items():
            rows = [
                (int(slot), int(item_id), int(quantity))
                for slot, (item_id, quantity) in entries.items()
                if int(slot) >= 0 and int(quantity) > 0 and int(item_id) not in volatile
            ]
            if rows:
                positives[label] = rows
        if not positives:
            return ()
        label = max(positives, key=lambda key: (len(positives[key]), key))
        pocket_offset, _pocket_size = XY_BAG_POUCH_LAYOUT[label]
        selected = sorted(positives[label], key=lambda row: (row[1], row[0]))[:3]
        hints: dict[int, MemoryCandidateHint] = {}
        scan_start = (XY_INVENTORY_SCAN_START + 3) & ~3
        overlap = XY_SAVE_ITEMS_SIZE + 16
        for block_address in range(scan_start, XY_INVENTORY_SCAN_END, XY_INVENTORY_SCAN_BLOCK_SIZE):
            block_size = min(XY_INVENTORY_SCAN_BLOCK_SIZE, XY_INVENTORY_SCAN_END - block_address)
            try:
                raw_block = bytes(client.read_memory(block_address, block_size + overlap))
            except Exception:
                continue
            for slot, item_id, _quantity in selected:
                pattern = struct.pack("<H", item_id)
                position = raw_block.find(pattern)
                while position >= 0:
                    # block_address está alineado a 4 y el ID ocupa los primeros
                    # dos bytes de cada registro <HH>; descarta coincidencias en qty.
                    if position < block_size and position % ORAS_ITEM_RECORD_SIZE == 0:
                        candidate = int(
                            block_address + position - pocket_offset - slot * ORAS_ITEM_RECORD_SIZE
                        )
                        if 0x08000000 <= candidate < 0x0A000000 and candidate % 4 == 0:
                            hints[candidate] = MemoryCandidateHint(candidate, "scan IDs bolsa X/Y", 0)
                    position = raw_block.find(pattern, position + 1)
        return tuple(hints.values())

    def _locate_bag_base(
        self,
        client,
        process: AzaharProcess,
        witnesses: Mapping[str, Mapping[int, tuple[int, int]]],
        volatile_item_ids: Sequence[int] = (),
    ) -> int:
        session_key = (int(process.title_id), str(process.name), self.reader.transport_label)
        block_key = "xy.inventory.bag"
        legacy = self._bag_bases_by_process.get(session_key)
        if legacy is not None and self.block_resolver.cached_address(session_key, block_key) is None:
            self.block_resolver.prime(session_key, block_key, int(legacy))

        tm_offset = XY_BAG_POUCH_LAYOUT["tms"][0]
        saved_tm_items: dict[int, int] = {}
        for slot, (item_id, quantity) in witnesses.get("tms", {}).items():
            if int(slot) >= 0 and int(quantity) > 0 and int(item_id) in XY_TM_HM_ITEM_IDS:
                saved_tm_items[int(item_id)] = int(quantity)

        # Ancla principal alpha.19: el lector de MT ya sabe demostrar cuál es el
        # bolsillo MT vivo. Si podemos localizarlo, la base de MyItem se deriva por
        # el offset documentado y se confirma comparando BYTE A BYTE los 0x1A4
        # bytes de ese mismo bolsillo dentro del bloque completo. Esto no depende
        # de que las cantidades del último guardado sigan congeladas.
        try:
            tm_base = self._locate_tm_inventory_base(client, process, saved_tm_items)
        except Exception:
            tm_base = None
        if tm_base is not None:
            candidate = int(tm_base) - tm_offset
            raw_bag = self._read_stable_bag_at(client, candidate)
            raw_tm = self._read_stable_tm_pouch_at(client, int(tm_base))
            if (
                raw_bag is not None
                and raw_tm is not None
                and self._bag_structure_score(raw_bag) is not None
                and raw_bag[tm_offset:tm_offset + XY_TM_POUCH_SIZE] == raw_tm
            ):
                self.block_resolver.prime(session_key, block_key, candidate)
                self._bag_bases_by_process[session_key] = candidate
                return candidate

        preferred = (
            MemoryCandidateHint(XY_TM_POUCH_ADDRESS - tm_offset, "bolsa completa X/Y v1.5 conocida y validada", 55),
            MemoryCandidateHint(XY_TM_POUCH_ADDRESS_V10 - tm_offset, "bolsa completa X/Y v1.0 conocida y validada", 50),
        )

        def read_at(address: int) -> bytes | None:
            return self._read_stable_bag_at(client, int(address))

        resolution = self.block_resolver.resolve(
            block_key,
            session_key,
            read_at=read_at,
            validate=lambda raw: self._bag_candidate_score(raw, witnesses, volatile_item_ids) if raw is not None else None,
            preferred=preferred,
            discover=lambda: self._discover_bag(client, witnesses, volatile_item_ids),
            failure_cooldown=5.0,
        )
        if not resolution.success or resolution.address is None:
            raise XYLiveError(
                "No se pudo localizar y validar la mochila viva de X/Y. "
                "No se escribió ningún byte. Si acabas de cambiar la mochila, guarda dentro del juego, pulsa F5 y vuelve a intentarlo."
            )
        base = int(resolution.address)
        self._bag_bases_by_process[session_key] = base
        return base

    @classmethod
    def _misc_write_local_score(cls, raw: bytes, saved_misc: bytes) -> tuple[int, int, int] | None:
        """Validación local y conservadora para la escritura de dinero X/Y.

        El bloque Misc vivo puede cambiar en campos ajenos al dinero entre dos
        guardados, por lo que la huella estadística usada para lectura de medallas
        puede resultar demasiado estricta para esta operación. Para escribir solo
        aceptamos una candidata que coincida con el último save en dinero, medallas
        y una firma estable del nombre del entrenador. Si no coincide, se aborta.
        """
        if len(raw) != XY_SAVE_MISC_SIZE or len(saved_misc) != XY_SAVE_MISC_SIZE:
            return None
        live_money = struct.unpack_from("<I", raw, XY_MISC_MONEY_OFFSET)[0]
        saved_money = struct.unpack_from("<I", saved_misc, XY_MISC_MONEY_OFFSET)[0]
        live_badges = int(raw[XY_MISC_BADGES_OFFSET])
        saved_badges = int(saved_misc[XY_MISC_BADGES_OFFSET])
        if live_money > XY_MAX_MONEY or not 0 <= live_badges <= 8:
            return None
        if live_money != saved_money or live_badges != saved_badges:
            return None

        # En SAV6XY el nombre del entrenador vive al principio de Misc y no cambia
        # al gastar/ganar dinero. Lo usamos como segunda identidad independiente.
        name_slice = bytes(saved_misc[0x10:0x20])
        name_match = int(bool(any(name_slice)) and bytes(raw[0x10:0x20]) == name_slice)
        if any(name_slice) and not name_match:
            return None
        bp_match = int(
            bytes(raw[XY_MISC_BP_OFFSET:XY_MISC_BP_OFFSET + 2])
            == bytes(saved_misc[XY_MISC_BP_OFFSET:XY_MISC_BP_OFFSET + 2])
        )
        return int(name_match), int(bp_match), int(live_badges)

    def _discover_misc_for_write_local(
        self, client, saved_misc: bytes,
    ) -> tuple[MemoryCandidateHint, ...]:
        if len(saved_misc) != XY_SAVE_MISC_SIZE:
            return ()
        saved_money = struct.unpack_from("<I", saved_misc, XY_MISC_MONEY_OFFSET)[0]
        saved_badges = int(saved_misc[XY_MISC_BADGES_OFFSET])
        pattern = struct.pack("<I", int(saved_money)) + bytes((saved_badges,))
        hints: dict[int, MemoryCandidateHint] = {}
        scan_start = (XY_MISC_SCAN_START + 3) & ~3
        overlap = XY_SAVE_MISC_SIZE + len(pattern)
        for block_address in range(scan_start, XY_MISC_SCAN_END, XY_MISC_SCAN_BLOCK_SIZE):
            block_size = min(XY_MISC_SCAN_BLOCK_SIZE, XY_MISC_SCAN_END - block_address)
            try:
                raw_block = bytes(client.read_memory(block_address, block_size + overlap))
            except Exception:
                continue
            position = raw_block.find(pattern)
            while position >= 0:
                if position < block_size:
                    candidate = int(block_address + position - XY_MISC_MONEY_OFFSET)
                    if 0x08000000 <= candidate < 0x0A000000 and candidate % 4 == 0:
                        hints[candidate] = MemoryCandidateHint(candidate, "scan dinero+medallas Misc X/Y", 0)
                position = raw_block.find(pattern, position + 1)
        return tuple(hints.values())

    def _locate_money_address_from_live_bag(
        self,
        client,
        process: AzaharProcess,
    ) -> int:
        """Localiza Money a partir de la mochila viva ya demostrada.

        Alpha.19 todavía dependía de que el bloque Misc de ``main`` siguiera
        siendo una huella suficientemente fresca. En AzaharPlus eso puede no ser
        cierto aunque la propia mochila viva esté perfectamente calibrada. Para
        X/Y tenemos dos layouts de RAM documentados (v1.0 y v1.5) y, en ambos, la
        relación entre ``MyItem`` y ``Money`` es idéntica. Reutilizamos por tanto
        la prueba fuerte de la mochila (incluida la MT viva) y solo aceptamos una
        de esas dos bases conocidas. Antes de devolver la dirección se relee el
        u32 de dinero de forma estable y se exige que esté dentro del rango real.
        """
        bag_base = self._locate_bag_base(client, process, {}, ())
        mapping = {
            int(XY_BAG_KNOWN_BASE_V10): int(XY_MONEY_KNOWN_ADDRESS_V10),
            int(XY_BAG_KNOWN_BASE_V15): int(XY_MONEY_KNOWN_ADDRESS_V15),
        }
        money_address = mapping.get(int(bag_base))
        if money_address is None:
            raise XYLiveError(
                "La mochila viva de X/Y se localizó, pero no corresponde a uno de los layouts "
                "v1.0/v1.5 cuyo dinero está documentado. No se escribió ningún byte."
            )
        try:
            first = bytes(client.read_memory(int(money_address), 4))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = bytes(client.read_memory(int(money_address), 4))
        except Exception as exc:
            raise XYLiveError(
                "No se pudo releer de forma estable el dinero vivo de X/Y. No se escribió ningún byte."
            ) from exc
        if len(first) != 4 or first != second:
            raise XYLiveError(
                "El dinero vivo de X/Y cambió durante la calibración. No se escribió ningún byte."
            )
        value = struct.unpack_from("<I", second)[0]
        if value > XY_MAX_MONEY:
            raise XYLiveError(
                "La dirección derivada desde la mochila no contiene un dinero válido de X/Y. "
                "No se escribió ningún byte."
            )
        return int(money_address)

    def _locate_misc_base_for_write(
        self,
        client,
        process: AzaharProcess,
        saved_misc: bytes,
    ) -> int:
        if len(saved_misc) != XY_SAVE_MISC_SIZE:
            raise XYLiveError(
                "Falta una huella válida de Misc del último guardado para escribir el dinero en X/Y. "
                "No se escribió ningún byte. Guarda dentro del juego, pulsa F5 y vuelve a intentarlo."
            )
        session_key = (int(process.title_id), str(process.name))

        def read_at(address: int) -> bytes | None:
            try:
                return bytes(client.read_memory(int(address), XY_SAVE_MISC_SIZE))
            except Exception:
                return None

        # Conservamos primero el localizador fuerte existente.
        resolution = self.block_resolver.resolve(
            "xy.misc",
            session_key,
            read_at=read_at,
            validate=lambda raw: self._misc_score(raw, saved_misc) if raw is not None else None,
            preferred=(
                MemoryCandidateHint(XY_MISC_KNOWN_ADDRESS_V10, "Misc X/Y v1.0 conocido y validado", 50),
                MemoryCandidateHint(XY_MISC_KNOWN_ADDRESS_V15, "Misc X/Y v1.5 conocido y validado", 50),
            ),
            discover=lambda: self._discover_misc(client, saved_misc),
        )
        if resolution.success and resolution.address is not None:
            return int(resolution.address)

        # Fallback alpha.19: valida solo los campos que deben seguir iguales tras
        # un guardado reciente. No acepta una dirección histórica por sí sola.
        local = self.block_resolver.resolve(
            "xy.misc.write",
            session_key,
            read_at=read_at,
            validate=lambda raw: self._misc_write_local_score(raw, saved_misc) if raw is not None else None,
            preferred=(
                MemoryCandidateHint(XY_MISC_KNOWN_ADDRESS_V10, "Misc dinero X/Y v1.0 validado localmente", 50),
                MemoryCandidateHint(XY_MISC_KNOWN_ADDRESS_V15, "Misc dinero X/Y v1.5 validado localmente", 50),
            ),
            discover=lambda: self._discover_misc_for_write_local(client, saved_misc),
            failure_cooldown=5.0,
        )
        if not local.success or local.address is None:
            raise XYLiveError(
                "No se pudo demostrar con seguridad dónde está el dinero vivo de X/Y. "
                "No se escribió ningún byte. Guarda dentro del juego, pulsa F5 y vuelve a intentarlo."
            )
        return int(local.address)

    def _apply_xy_inventory(
        self,
        current: SaveGameData,
        changes: Sequence[PendingInventoryChange],
    ) -> ORASLiveWriteResult:
        if not changes:
            raise XYLiveError("No hay ninguna utilidad X/Y que aplicar.")
        if len(changes) != 1:
            raise XYLiveError(
                "Las utilidades X/Y se aplican de una en una para poder verificar cada objetivo. "
                "No se escribió ningún byte."
            )
        change = changes[0]
        if change.item_key not in {*XY_INVENTORY_TARGETS, "money-max"}:
            raise XYLiveError(
                f"La utilidad '{change.item_name}' no tiene un objetivo X/Y validado. No se escribió ningún byte."
            )

        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_xy_process(client.process_list())
                client.set_process(process.process_id)

                bag_base: int | None = None
                misc_base: int | None = None
                money_address: int | None = None
                witnesses: dict[str, dict[int, tuple[int, int]]] = {}
                saved_misc = bytes(getattr(change, "save_misc_witness", b"") or b"")
                requests: list[tuple[str, int, int]] = []

                if change.item_key == "money-max":
                    # Alpha.20: la ruta primaria ya no depende del main configurado.
                    # La mochila/MT viva acaba de ser validada en esta misma sesión
                    # y discrimina inequívocamente v1.0 frente a v1.5.
                    try:
                        money_address = self._locate_money_address_from_live_bag(client, process)
                        requests.append(("money", money_address, 4))
                    except XYLiveError:
                        # Conservamos el localizador Misc de alpha.19 como fallback
                        # únicamente cuando existe una huella de save utilizable.
                        if not saved_misc:
                            raise
                        misc_base = self._locate_misc_base_for_write(client, process, saved_misc)
                        money_address = int(misc_base) + XY_MISC_MONEY_OFFSET
                        requests.append(("misc", misc_base, XY_SAVE_MISC_SIZE))
                else:
                    witnesses = self._xy_inventory_witness_map(changes)
                    target_item_id = int(XY_INVENTORY_TARGETS[change.item_key][0])
                    volatile_item_ids = (target_item_id,)
                    # El objeto que se va a modificar no puede formar parte de la
                    # identidad de la mochila: su cantidad/presencia es precisamente
                    # el dato que puede haber cambiado desde el último guardado.
                    locator_witnesses = {
                        label: {
                            slot: value for slot, value in entries.items()
                            if int(value[0]) != target_item_id
                        }
                        for label, entries in witnesses.items()
                    }
                    locator_witnesses = {label: entries for label, entries in locator_witnesses.items() if entries}
                    bag_base = self._locate_bag_base(client, process, locator_witnesses)
                    requests.append(("bag", bag_base, XY_SAVE_ITEMS_SIZE))

                original_capture, original_extra, capture_attempt = self._capture_stable_state(client, requests)
                if not any(original_capture):
                    raise XYLiveError("La captura estable de X/Y no contiene un equipo válido; no se escribió ningún byte.")

                planned: dict[int, tuple[bytes, bytes, str]] = {}
                watch_specs: list[tuple[int, bytes, str]] = []

                def plan(address: int, original: bytes, replacement: bytes, kind: str) -> None:
                    address = int(address)
                    original = bytes(original)
                    replacement = bytes(replacement)
                    watch_specs.append((address, replacement, kind))
                    if original == replacement:
                        return
                    previous = planned.get(address)
                    if previous is not None and previous[0] != replacement:
                        raise XYLiveError("Dos utilidades intentan modificar el mismo byte de X/Y de forma incompatible.")
                    planned[address] = (replacement, original, kind)

                if change.item_key == "money-max":
                    if money_address is None:
                        raise XYLiveError("No se resolvió la dirección de dinero X/Y; no se escribió ningún byte.")
                    if "money" in original_extra:
                        raw_money = bytes(original_extra["money"])
                    else:
                        raw_misc = bytes(original_extra["misc"])
                        if (
                            self._misc_score(raw_misc, saved_misc) is None
                            and self._misc_write_local_score(raw_misc, saved_misc) is None
                        ):
                            raise XYLiveError(
                                "El bloque Misc de X/Y dejó de coincidir con la huella validada antes de escribir. "
                                "No se escribió ningún byte; pulsa F5."
                            )
                        raw_money = raw_misc[XY_MISC_MONEY_OFFSET:XY_MISC_MONEY_OFFSET + 4]
                    if len(raw_money) != 4:
                        raise XYLiveError("El dinero leído en X/Y tiene un tamaño inesperado; no se escribió ningún byte.")
                    current_money = struct.unpack_from("<I", raw_money, 0)[0]
                    if current_money > XY_MAX_MONEY:
                        raise XYLiveError("El dinero leído en X/Y no es válido; no se escribió ningún byte.")
                    replacement = struct.pack("<I", XY_MAX_MONEY)
                    plan(
                        int(money_address),
                        raw_money,
                        replacement,
                        "money",
                    )
                else:
                    raw_bag = bytes(original_extra["bag"])
                    if self._bag_structure_score(raw_bag) is None:
                        raise XYLiveError(
                            "La mochila X/Y dejó de tener una estructura válida después de calibrarla. "
                            "No se escribió ningún byte; pulsa F5."
                        )
                    # Si la base se obtuvo por testigos, vuelve a exigir identidad;
                    # si se obtuvo por la MT viva, la igualdad byte-a-byte del
                    # bolsillo MT ya demostró la base y las cantidades pueden haber
                    # variado legítimamente desde el último guardado.
                    cached_bag = self._bag_bases_by_process.get(
                        (int(process.title_id), str(process.name), self.reader.transport_label)
                    )
                    if cached_bag != int(bag_base) and self._bag_candidate_score(
                        raw_bag, witnesses, volatile_item_ids
                    ) is None:
                        raise XYLiveError(
                            "La identidad de la mochila X/Y cambió después de calibrarla. "
                            "No se escribió ningún byte; pulsa F5."
                        )
                    item_id, label = XY_INVENTORY_TARGETS[change.item_key]
                    pocket_offset, pocket_size = XY_BAG_POUCH_LAYOUT[label]
                    pocket_original = raw_bag[pocket_offset:pocket_offset + pocket_size]
                    if self._generic_pocket_records(pocket_original) is None:
                        raise XYLiveError(f"El bolsillo {label} de X/Y no tiene una estructura válida.")
                    pocket = bytearray(pocket_original)
                    offsets = self._prepare_xy_inventory_value(
                        pocket, int(item_id), int(change.quantity), label=change.item_name,
                    )
                    for offset in offsets:
                        plan(
                            int(bag_base) + pocket_offset + int(offset),
                            pocket_original[offset:offset + ORAS_ITEM_RECORD_SIZE],
                            bytes(pocket[offset:offset + ORAS_ITEM_RECORD_SIZE]),
                            "inventory",
                        )

                if not planned:
                    watches = tuple(
                        ORASLiveMemoryWatch(address, expected, kind)
                        for address, expected, kind in sorted(watch_specs)
                    )
                    return ORASLiveWriteResult(
                        game=self._build_game(original_capture, current, process, live_write=True),
                        process=process,
                        attempts=capture_attempt,
                        applied_count=1,
                        memory_watches=watches,
                        already_applied=True,
                    )

                attempted: list[tuple[int, bytes]] = []
                try:
                    for address in sorted(planned):
                        replacement, original, _kind = planned[address]
                        attempted.append((address, original))
                        client.write_memory(address, replacement)

                    verified_capture, verified_extra, verified_attempt = self._capture_stable_state(client, requests)
                    for address, (replacement, _original, _kind) in planned.items():
                        actual = self._captured_subblock(verified_extra, requests, address, len(replacement))
                        if actual != replacement:
                            raise XYLiveError(
                                f"AzaharPlus no confirmó la utilidad X/Y en 0x{address:08X}."
                            )

                    watches = tuple(
                        ORASLiveMemoryWatch(address, replacement, kind)
                        for address, (replacement, _original, kind) in sorted(planned.items())
                    )
                    return ORASLiveWriteResult(
                        game=self._build_game(verified_capture, current, process, live_write=True),
                        process=process,
                        attempts=max(capture_attempt, verified_attempt),
                        applied_count=1,
                        memory_watches=watches,
                    )
                except Exception as exc:
                    rollback_errors = self._rollback(client, attempted)
                    if rollback_errors:
                        raise XYLiveError(
                            f"La utilidad X/Y falló: {exc}. No se pudo confirmar toda la restauración: "
                            + "; ".join(rollback_errors)
                        ) from exc
                    if attempted:
                        raise XYLiveError(
                            f"La utilidad X/Y falló: {exc}. RoleRun restauró los bytes originales en RAM "
                            "y no tocó el archivo main."
                        ) from exc
                    raise
        except AzaharRPCError as exc:
            raise XYLiveError(str(exc)) from exc

    def apply(self, current: SaveGameData, changes):
        unsupported = self._unsupported_changes(changes)
        if unsupported:
            raise XYLiveError(
                "X/Y contiene cambios todavía no validados en vivo: "
                + ", ".join(unsupported) + ". No se escribió nada."
            )
        inventory_changes = [change for change in changes if isinstance(change, PendingInventoryChange)]
        if inventory_changes:
            if len(inventory_changes) != len(changes):
                raise XYLiveError(
                    "Las utilidades X/Y se confirman de una en una y no se mezclan con cambios de Pokémon. "
                    "No se escribió ningún byte; pulsa F5 y repite la utilidad."
                )
            return self._apply_xy_inventory(current, inventory_changes)
        heal_changes = [change for change in changes if isinstance(change, PendingPartyHeal)]
        if heal_changes:
            if len(heal_changes) != len(changes):
                raise XYLiveError(
                    "La curación X/Y se confirma como una transacción independiente. "
                    "No se mezcló con otros cambios ni se escribió ningún byte."
                )
            return self._apply_party_heal(current, heal_changes)
        pc_swap_changes = [
            change for change in changes
            if isinstance(change, PendingTeamChange) and change.operation == "swap-box-slots"
        ]
        if pc_swap_changes:
            if len(pc_swap_changes) != 1 or len(changes) != 1:
                raise XYLiveError(
                    "Cada intercambio PC→PC de X/Y se confirma como una transacción independiente. "
                    "No se escribió ningún byte."
                )
            return self._apply_pc_swap(current, pc_swap_changes[0])
        pc_move_changes = [
            change for change in changes
            if isinstance(change, PendingTeamChange) and change.operation == "move-box-slot"
        ]
        if pc_move_changes:
            if len(pc_move_changes) != 1 or len(changes) != 1:
                raise XYLiveError(
                    "Cada movimiento PC→PC de X/Y se confirma como una transacción independiente. "
                    "No se escribió ningún byte."
                )
            return self._apply_pc_move(current, pc_move_changes[0])
        party_resize_changes = [
            change for change in changes
            if isinstance(change, PendingTeamChange)
            and change.operation in {"party-to-box", "box-to-party"}
        ]
        if party_resize_changes:
            if len(party_resize_changes) != 1 or len(changes) != 1:
                raise XYLiveError(
                    "Cada cambio de tamaño Equipo↔PC de X/Y se confirma como una "
                    "transacción independiente. No se escribió ningún byte."
                )
            return self._apply_party_resize(current, party_resize_changes[0])
        role_ev_changes = [
            change for change in changes
            if isinstance(change, PendingRoleChange) and change.new_evs is not None
        ]
        if role_ev_changes:
            if not all(isinstance(change, (PendingChange, PendingRoleChange)) for change in changes):
                raise XYLiveError(
                    "El cambio de rol con EV X/Y no se mezcla con operaciones de PC o inventario. "
                    "No se escribió ningún byte."
                )
            return self._apply_party_role_evs(current, changes)
        return super().apply(current, changes)

    @property
    def last_badge_source(self) -> str | None:
        return self._last_badge_source

    @staticmethod
    def _misc_fingerprint_positions(saved_misc: bytes) -> tuple[int, ...]:
        dynamic = set(range(XY_MISC_MONEY_OFFSET, XY_MISC_BADGES_OFFSET + 1))
        dynamic.update(range(XY_MISC_BP_OFFSET, XY_MISC_BP_OFFSET + 2))
        candidates = [
            i for i, value in enumerate(saved_misc)
            if i not in dynamic and value != 0
        ]
        if len(candidates) <= 28:
            return tuple(candidates)
        step = max(1, len(candidates) // 28)
        return tuple(candidates[::step][:28])

    @classmethod
    def _misc_score(cls, raw: bytes, saved_misc: bytes) -> tuple[int, int] | None:
        if len(raw) != XY_SAVE_MISC_SIZE or len(saved_misc) != XY_SAVE_MISC_SIZE:
            return None
        badges = parse_xy_badges(raw[XY_MISC_BADGES_OFFSET:XY_MISC_BADGES_OFFSET + 1])
        if badges is None:
            return None

        # La regresión real de alpha.14 reveló un caso peligroso: v1.0 y v1.5
        # separan Misc exactamente 0x10 bytes. Una validación estadística demasiado
        # permisiva puede aceptar la misma región corrida y leer otro byte como
        # medallas. El mismo ancla exacta que usa el descubridor dinámico elimina
        # esa ambigüedad sin confiar ciegamente en ninguna dirección fija.
        anchor = cls._misc_anchor(saved_misc)
        if anchor is None:
            return None
        anchor_offset, pattern = anchor
        if bytes(raw[anchor_offset:anchor_offset + len(pattern)]) != pattern:
            return None

        positions = cls._misc_fingerprint_positions(saved_misc)
        if not positions:
            return None
        matches = sum(raw[pos] == saved_misc[pos] for pos in positions)
        required = max(5, (len(positions) * 2 + 2) // 3)
        if matches < required:
            return None
        # Primero gana la alineación estructural (matches); solo después el
        # progreso. La dirección cacheada sigue teniendo prioridad absoluta en
        # lecturas posteriores, conservando el comportamiento ante save-states.
        return int(matches), int(badges)

    @staticmethod
    def _misc_anchor(saved_misc: bytes) -> tuple[int, bytes] | None:
        dynamic = set(range(XY_MISC_MONEY_OFFSET, XY_MISC_BADGES_OFFSET + 1))
        dynamic.update(range(XY_MISC_BP_OFFSET, XY_MISC_BP_OFFSET + 2))
        best: tuple[int, int, bytes] | None = None
        width = 12
        for offset in range(0, len(saved_misc) - width + 1):
            if any(i in dynamic for i in range(offset, offset + width)):
                continue
            window = bytes(saved_misc[offset:offset + width])
            nonzero = sum(value != 0 for value in window)
            if nonzero < 5:
                continue
            score = nonzero * 4 + len(set(window))
            if best is None or score > best[0]:
                best = (score, offset, window)
        return None if best is None else (best[1], best[2])

    def _discover_misc(
        self,
        client: AzaharRPCClient,
        saved_misc: bytes,
    ) -> tuple[MemoryCandidateHint, ...]:
        anchor = self._misc_anchor(saved_misc)
        if anchor is None:
            return ()
        anchor_offset, pattern = anchor
        hints: dict[int, MemoryCandidateHint] = {}
        scan_start = (XY_MISC_SCAN_START + 3) & ~3
        overlap = XY_SAVE_MISC_SIZE + len(pattern)
        for block_address in range(scan_start, XY_MISC_SCAN_END, XY_MISC_SCAN_BLOCK_SIZE):
            block_size = min(XY_MISC_SCAN_BLOCK_SIZE, XY_MISC_SCAN_END - block_address)
            try:
                raw_block = bytes(client.read_memory(block_address, block_size + overlap))
            except Exception:
                continue
            position = raw_block.find(pattern)
            while position >= 0:
                if position < block_size:
                    candidate = block_address + position - anchor_offset
                    if 0x08000000 <= candidate < 0x0A000000 and candidate % 4 == 0:
                        hints[candidate] = MemoryCandidateHint(candidate, "scan huella Misc X/Y", 0)
                position = raw_block.find(pattern, position + 1)
        return tuple(hints.values())

    @staticmethod
    def _machine_saved_items(saved_items: Mapping[int, int] | None) -> dict[int, int]:
        return {
            int(item_id): int(quantity)
            for item_id, quantity in dict(saved_items or {}).items()
            if int(item_id) in XY_TM_HM_ITEM_IDS and int(quantity) > 0
        }

    @staticmethod
    def _tm_candidate_score(raw: bytes, saved_items: Mapping[int, int] | None) -> tuple[int, int, int] | None:
        try:
            items = parse_xy_tm_hm_pocket(raw)
        except ORASLiveError:
            return None
        saved = XYLiveWriter._machine_saved_items(saved_items)
        overlap = sum(1 for item_id in saved if item_id in items)
        exact = sum(1 for item_id, qty in saved.items() if int(items.get(item_id, -1)) == int(qty))
        if saved and overlap <= 0:
            return None
        # Sin testigos del último main (p. ej. acabas de recibir tu primera MT
        # y aún no has guardado) una región totalmente a cero no demuestra nada.
        if not saved and not items:
            return None
        return int(exact), int(overlap), len(items)

    def _read_stable_tm_pouch_at(self, client, address: int) -> bytes | None:
        try:
            first = bytes(client.read_memory(int(address), XY_TM_POUCH_SIZE))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = bytes(client.read_memory(int(address), XY_TM_POUCH_SIZE))
        except Exception:
            return None
        return second if first == second else None

    def _discover_tm_pouch(
        self, client, saved_items: Mapping[int, int] | None,
    ) -> tuple[MemoryCandidateHint, ...]:
        saved = self._machine_saved_items(saved_items)
        # Elegimos hasta tres testigos poco ambiguos. Cada uno puede aparecer en
        # cualquier slot del bolsillo; derivamos todas las bases posibles y las
        # valida después el resolver con el conjunto completo.
        witnesses = sorted(saved.items(), key=lambda item: (item[1], item[0]))[:3]
        hints: dict[int, MemoryCandidateHint] = {}
        scan_start = (XY_INVENTORY_SCAN_START + 3) & ~3
        overlap = XY_TM_POUCH_SIZE + ORAS_ITEM_RECORD_SIZE
        slot_count = XY_TM_POUCH_SIZE // ORAS_ITEM_RECORD_SIZE
        for block_address in range(scan_start, XY_INVENTORY_SCAN_END, XY_INVENTORY_SCAN_BLOCK_SIZE):
            block_size = min(XY_INVENTORY_SCAN_BLOCK_SIZE, XY_INVENTORY_SCAN_END - block_address)
            try:
                raw_block = bytes(client.read_memory(block_address, block_size + overlap))
            except Exception:
                continue

            positions: set[int] = set()
            if witnesses:
                # Cuando main ya contiene alguna máquina, esos registros son la
                # huella más barata y discriminante.
                for item_id, quantity in witnesses:
                    pattern = struct.pack("<HH", int(item_id), int(quantity))
                    position = raw_block.find(pattern)
                    while position >= 0:
                        if position < block_size:
                            positions.add(position)
                        position = raw_block.find(pattern, position + 1)
            else:
                # Caso crítico alpha.8: primera medalla/primera MT obtenida en
                # vivo sin guardar. No hay testigos en main. Buscamos registros
                # alineados de máquinas con cantidad 1 y validamos después TODO
                # el bolsillo; nunca aceptamos una región a cero.
                for position in range(0, block_size, ORAS_ITEM_RECORD_SIZE):
                    item_id, quantity = struct.unpack_from("<HH", raw_block, position)
                    if int(quantity) == 1 and int(item_id) in XY_TM_HM_ITEM_IDS:
                        positions.add(position)

            for position in positions:
                for slot in range(slot_count):
                    start = position - slot * ORAS_ITEM_RECORD_SIZE
                    if start < 0 or start + XY_TM_POUCH_SIZE > len(raw_block):
                        continue
                    base = int(block_address + start)
                    if not (0x08000000 <= base < 0x0A000000 and base % 4 == 0):
                        continue
                    if base in hints:
                        continue
                    candidate = raw_block[start:start + XY_TM_POUCH_SIZE]
                    if self._tm_candidate_score(candidate, saved_items) is not None:
                        source = "scan testigos MT X/Y" if witnesses else "scan primera MT viva X/Y"
                        hints[base] = MemoryCandidateHint(base, source, 0)
        return tuple(hints.values())

    def _locate_tm_inventory_base(self, client, process: AzaharProcess, saved_items: Mapping[int, int] | None) -> int:
        session_key = (int(process.title_id), str(process.name), self.reader.transport_label)
        block_key = "xy.inventory.tm_hm"
        legacy = self._tm_inventory_bases_by_process.get(session_key)
        if legacy is not None and self.block_resolver.cached_address(session_key, block_key) is None:
            self.block_resolver.prime(session_key, block_key, int(legacy))

        def read_at(address: int) -> bytes | None:
            return self._read_stable_tm_pouch_at(client, int(address))

        resolution = self.block_resolver.resolve(
            block_key, session_key,
            read_at=read_at,
            validate=lambda raw: self._tm_candidate_score(raw, saved_items) if raw is not None else None,
            preferred=(
                MemoryCandidateHint(
                    XY_TM_POUCH_ADDRESS, "bolsa MT/MO X/Y v1.5 conocida y validada", 55,
                ),
                MemoryCandidateHint(
                    XY_TM_POUCH_ADDRESS_V10, "bolsa MT/MO X/Y v1.0 conocida y validada", 50,
                ),
            ),
            discover=lambda: self._discover_tm_pouch(client, saved_items),
            failure_cooldown=5.0,
        )
        if not resolution.success or resolution.address is None:
            raise XYLiveError(
                "No se pudo localizar la mochila MT/MO viva de X/Y. "
                "RoleRun no usará una copia antigua o vacía de RAM."
            )
        base = int(resolution.address)
        self._tm_inventory_bases_by_process[session_key] = base
        return base

    def read_tm_inventory(
        self, saved_items: Mapping[int, int] | None = None,
    ) -> tuple[dict[int, int], AzaharProcess, int]:
        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_xy_process(client.process_list())
                client.set_process(process.process_id)
                base = self._locate_tm_inventory_base(client, process, saved_items)
                for attempt in range(1, self.reader.snapshot_attempts + 1):
                    raw = self._read_stable_tm_pouch_at(client, base)
                    if raw is None:
                        continue
                    return parse_xy_tm_hm_pocket(raw), process, attempt
        except AzaharRPCError as exc:
            raise XYLiveError(str(exc)) from exc
        raise XYLiveError(
            "Las MT/MO de X/Y cambiaron durante todas las lecturas; cierra la mochila y vuelve a intentarlo."
        )

    @staticmethod
    def _subevent_candidate_score(raw: bytes) -> tuple[int] | None:
        if len(raw) != XY_SAVE_SUBEVENT_SIZE:
            return None
        if any(
            bytes(raw[offset:offset + 4]) != XY_SUBEVENT_MAGIC
            for offset in XY_SUBEVENT_MAGIC_OFFSETS
        ):
            return None
        badges = count_xy_badge_victories(raw)
        if badges is None:
            return None
        return (int(badges),)

    def _locate_subevent_base(
        self, client: AzaharRPCClient, process: AzaharProcess, saved_subevent: bytes,
    ) -> int | None:
        process_key = (int(process.title_id), str(process.name))
        cached = self._subevent_bases_by_process.get(process_key)
        if cached is not None:
            try:
                raw = bytes(client.read_memory(cached, XY_SAVE_SUBEVENT_SIZE))
            except Exception:
                raw = b""
            # Una base ya demostrada se conserva aunque un save-state haga bajar
            # el número de medallas; solo exigimos que siga siendo un SUBE válido.
            if self._subevent_candidate_score(raw) is not None:
                return int(cached)
            self._subevent_bases_by_process.pop(process_key, None)

        last_failed = self._subevent_failed_scan_at.get(process_key)
        if last_failed is not None and (time.monotonic() - last_failed) < 8.0:
            return None

        first_magic_offset = XY_SUBEVENT_MAGIC_OFFSETS[0]
        for range_start, range_end in XY_SUBEVENT_SCAN_RANGES:
            candidates: dict[int, tuple[int]] = {}
            overlap = XY_SAVE_SUBEVENT_SIZE + 8
            for block_address in range(range_start, range_end, XY_SUBEVENT_SCAN_BLOCK_SIZE):
                block_size = min(XY_SUBEVENT_SCAN_BLOCK_SIZE, range_end - block_address)
                try:
                    raw_block = bytes(client.read_memory(block_address, block_size + overlap))
                except Exception:
                    continue
                position = raw_block.find(XY_SUBEVENT_MAGIC)
                while position >= 0:
                    if position < block_size:
                        candidate_base = block_address + position - first_magic_offset
                        if candidate_base % 4 == 0 and 0x08000000 <= candidate_base < 0x0A000000:
                            start = candidate_base - block_address
                            if 0 <= start and start + XY_SAVE_SUBEVENT_SIZE <= len(raw_block):
                                candidate = bytes(raw_block[start:start + XY_SAVE_SUBEVENT_SIZE])
                            else:
                                try:
                                    candidate = bytes(client.read_memory(candidate_base, XY_SAVE_SUBEVENT_SIZE))
                                except Exception:
                                    candidate = b""
                            score = self._subevent_candidate_score(candidate)
                            if score is not None:
                                candidates[int(candidate_base)] = score
                    position = raw_block.find(XY_SUBEVENT_MAGIC, position + 1)

            if candidates:
                # La progresión gana frente a copias antiguas: si conviven una
                # copia SUBE con 0 y otra con 1, se calibra la de 1. Tras cachear
                # la base, un state-load puede bajar sin provocar un salto.
                best_base = max(candidates, key=lambda base: (candidates[base], -abs(base - XY_PARTY_ADDRESS)))
                self._subevent_bases_by_process[process_key] = int(best_base)
                self._subevent_failed_scan_at.pop(process_key, None)
                return int(best_base)

        self._subevent_failed_scan_at[process_key] = time.monotonic()
        return None

    def _read_badges_from_subevent(
        self, client: AzaharRPCClient, process: AzaharProcess, saved_subevent: bytes,
    ) -> int | None:
        base = self._locate_subevent_base(client, process, saved_subevent)
        if base is None:
            return None
        try:
            first = bytes(client.read_memory(base, XY_SAVE_SUBEVENT_SIZE))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = bytes(client.read_memory(base, XY_SAVE_SUBEVENT_SIZE))
        except Exception:
            return None
        if first != second:
            return None
        return count_xy_badge_victories(second)

    def read_badges(self, save_path: Path | str | None) -> int | None:
        saved_subevent = read_xy_saved_subevent(save_path)
        saved_subevent_badges = (
            count_xy_badge_victories(saved_subevent)
            if saved_subevent is not None else None
        )
        saved_misc = read_xy_saved_misc(save_path)
        saved_badges = parse_xy_saved_badges(save_path)
        saved_values = [value for value in (saved_subevent_badges, saved_badges) if value is not None]
        saved_fallback = max(saved_values) if saved_values else None
        self._last_badge_source = None
        if saved_misc is None and saved_subevent is None:
            if saved_fallback is not None:
                self._last_badge_source = "main X/Y"
            return saved_fallback
        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_xy_process(client.process_list())
                client.set_process(process.process_id)
                session_key = (int(process.title_id), str(process.name))
                self._last_process_key = session_key

                if saved_subevent is not None:
                    live_subevent_badges = self._read_badges_from_subevent(
                        client, process, saved_subevent,
                    )
                    if live_subevent_badges is not None:
                        self._last_badge_source = "SUBE vivo X/Y · equipos de gimnasio"
                        return int(live_subevent_badges)

                def read_at(address: int) -> bytes | None:
                    try:
                        return bytes(client.read_memory(int(address), XY_SAVE_MISC_SIZE))
                    except Exception:
                        return None

                resolution = self.block_resolver.resolve(
                    "xy.misc",
                    session_key,
                    read_at=read_at,
                    validate=lambda raw: self._misc_score(raw, saved_misc) if raw is not None else None,
                    preferred=(
                        MemoryCandidateHint(
                            XY_MISC_KNOWN_ADDRESS_V10, "Misc X/Y v1.0 conocido y validado", 50,
                        ),
                        MemoryCandidateHint(
                            XY_MISC_KNOWN_ADDRESS_V15, "Misc X/Y v1.5 conocido y validado", 50,
                        ),
                    ),
                    discover=lambda: self._discover_misc(client, saved_misc),
                )
                if resolution.success and resolution.address is not None:
                    first = read_at(resolution.address)
                    if self.reader.stable_delay:
                        time.sleep(self.reader.stable_delay)
                    second = read_at(resolution.address)
                    if first is not None and first == second:
                        value = parse_xy_badges(second[XY_MISC_BADGES_OFFSET:XY_MISC_BADGES_OFFSET + 1])
                        if value is not None:
                            self._last_badge_source = "Misc vivo X/Y"
                            return value
        except Exception:
            pass
        if saved_fallback is not None:
            if saved_subevent_badges is not None and int(saved_subevent_badges) == int(saved_fallback):
                self._last_badge_source = "main X/Y · SUBE (fallback)"
            else:
                self._last_badge_source = "main X/Y (fallback)"
        return saved_fallback

    def runtime_memory_requests(self) -> tuple[tuple[int, int], ...]:
        requests: list[tuple[int, int]] = []
        key = self._last_process_key
        if key is not None:
            address = self.block_resolver.cached_address(key, "xy.misc")
            if address is not None:
                requests.append((int(address), XY_SAVE_MISC_SIZE))
        for session_key, address in self._tm_inventory_bases_by_process.items():
            if address is not None:
                requests.append((int(address), XY_TM_POUCH_SIZE))
        for _session_key, address in self._bag_bases_by_process.items():
            if address is not None:
                requests.append((int(address), XY_SAVE_ITEMS_SIZE))
        for _session_key, address in self._subevent_bases_by_process.items():
            if address is not None:
                requests.append((int(address), XY_SAVE_SUBEVENT_SIZE))
        return tuple(dict.fromkeys(requests))

    def reset_runtime_state(self) -> None:
        self.block_resolver.reset()
        self._tm_inventory_bases_by_process.clear()
        self._bag_bases_by_process.clear()
        self._subevent_bases_by_process.clear()
        self._subevent_failed_scan_at.clear()
        self._last_process_key = None
        self._last_badge_source = None
        reset_reader = getattr(self.reader, "reset_runtime_state", None)
        if callable(reset_reader):
            reset_reader()
