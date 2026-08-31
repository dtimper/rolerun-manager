from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.azahar_rpc import AzaharProcess
from app.models import PendingChange, PendingInventoryChange, PendingPCRoleChange, PendingRoleChange, PendingTMTeach, PendingTeamChange
from app.oras_tm_service import ORASPersonalStats

with patch("pathlib.Path.home", return_value=Path(tempfile.gettempdir()) / "rolerun-tests"):
    from app.oras_live import (
        ORAS_PARTY_ADDRESS,
        ORAS_PARTY_COUNT_ADDRESS,
        ORAS_PARTY_STATS_OFFSET,
        ORAS_PARTY_STATS_SIZE,
        ORAS_PARTY_STRIDE,
        ORAS_PC_ADDRESS,
        ORAS_PC_SCAN_BLOCK_SIZE,
        ORAS_PC_SCAN_START,
        ORAS_ITEMS_POUCH_ADDRESS,
        ORAS_ITEMS_POUCH_SIZE,
        ORAS_MEDICINE_POUCH_ADDRESS,
        ORAS_MEDICINE_POUCH_SIZE,
        ORAS_MONEY_ADDRESS,
        ORAS_BADGES_ADDRESS,
        ORAS_SAVE_MISC_OFFSET,
        ORAS_SAVE_MISC_SIZE,
        ORAS_SAVE_EVENTWORK_OFFSET,
        ORAS_SAVE_EVENTWORK_SIZE,
        ORAS_EVENTWORK_FLAG_OFFSET,
        ORAS_BADGE_RECEIVED_FLAGS,
        ORAS_GYM_LEADER_FLAGS,
        ORAS_SAVE_SUBEVENT_OFFSET,
        ORAS_SAVE_SUBEVENT_SIZE,
        ORAS_SUBEVENT_BADGE_VICTORY_OFFSET,
        ORAS_SUBEVENT_BADGE_SLOT_COUNT,
        ORAS_SUBEVENT_MAGIC_OFFSETS,
        ORAS_MISC_BADGES_OFFSET,
        ORAS_MISC_MONEY_OFFSET,
        ORAS_TM_POUCH_ADDRESS,
        ORAS_TM_POUCH_SIZE,
        ORAS_GYM_REWARD_ITEM_IDS,
        ORAS_HM05_ITEM_ID,
        ORAS_HM07_ITEM_ID,
        ORASLiveError,
        ORASLiveReader,
        ORASLiveWriter,
        PK6_PARTY_SIZE,
        PK6_STORED_SIZE,
        _checksum,
        decrypt_pk6,
        decrypt_pk6_stored,
        encrypt_pk6,
        encrypt_pk6_stored,
        live_party_fingerprint,
        es_hueco_pc_canonico,
        oras_empty_party_slot,
        load_oras_move_pp,
        parse_pk6_boxed,
        parse_pk6_party,
        parse_oras_event_flag,
        count_oras_received_badges,
        count_oras_gym_leader_flags,
        parse_oras_badge_victory_records,
        count_oras_badge_victories,
        count_oras_gym_reward_items,
        parse_oras_tm_hm_pocket,
    )
    from app.save_engine_client import SaveGameData


def make_encrypted_pk6(
    *,
    moves: tuple[int, int, int, int] = (33, 44, 45, 0),
    pps: tuple[int, int, int, int] = (35, 25, 15, 0),
    pp_ups: tuple[int, int, int, int] = (2, 1, 0, 0),
    marking: int = 0,
    species_id: int = 261,
    tid: int = 12345,
    sid: int = 54321,
    pid: int = 0x89ABCDEF,
    nickname: str = "Poochyena",
    experience: int = 5_832,
    level: int = 18,
    nature: int = 0,
    evs: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0),
    iv32: int = 0x3FFFFFFF,
) -> bytes:
    data = bytearray(PK6_PARTY_SIZE)
    struct.pack_into("<I", data, 0, 0x12345678)
    struct.pack_into("<H", data, 4, 0)
    struct.pack_into("<H", data, 8, species_id)
    struct.pack_into("<H", data, 0x0C, tid)
    struct.pack_into("<H", data, 0x0E, sid)
    struct.pack_into("<I", data, 0x10, experience)
    struct.pack_into("<I", data, 0x18, pid)
    data[0x1C] = nature
    data[0x1E:0x24] = bytes(evs)
    data[0x2A] = 1 << marking
    encoded_nickname = nickname.encode("utf-16le")
    data[0x40:0x40 + len(encoded_nickname)] = encoded_nickname
    struct.pack_into("<4H", data, 0x5A, *moves)
    data[0x62:0x66] = bytes(pps)
    data[0x66:0x6A] = bytes(pp_ups)
    struct.pack_into("<I", data, 0x74, iv32)
    data[0xEC] = level
    struct.pack_into("<H", data, 6, _checksum(data))
    return encrypt_pk6(bytes(data))


def make_oras_misc(*, badges: int = 8, money: int = 996_999) -> bytearray:
    misc = bytearray(ORAS_SAVE_MISC_SIZE)
    struct.pack_into("<I", misc, ORAS_MISC_MONEY_OFFSET, money)
    misc[ORAS_MISC_BADGES_OFFSET] = badges
    struct.pack_into("<H", misc, 0x30, 0)
    misc[0x44] = 12
    misc[0x60:0x70] = bytes(range(1, 17))
    misc[0x90:0xA0] = b"RoleRun-Misc-123"
    return misc


class _WritableFakeClient:
    def __init__(self, slots: tuple[bytes, ...], *, ignore_first_write: bool = False) -> None:
        self.slots = list(slots)
        self.selected = 0
        self.ignore_first_write = ignore_first_write
        self.writes: list[tuple[int, bytes]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [AzaharProcess(77, 0x000400000011C500, "sango-2")]

    def set_process(self, process_id: int):
        self.selected = process_id

    def read_memory(self, address: int, size: int):
        index = (address - ORAS_PARTY_ADDRESS) // ORAS_PARTY_STRIDE
        relative = address - (ORAS_PARTY_ADDRESS + index * ORAS_PARTY_STRIDE)
        raw = self.slots[index]
        if relative == 0:
            if size != PK6_STORED_SIZE:
                raise AssertionError("Lectura de PK6 almacenado de tamaño inesperado.")
            return raw[:size]
        if relative == ORAS_PARTY_STATS_OFFSET:
            if size != ORAS_PARTY_STATS_SIZE:
                raise AssertionError("Lectura de estadísticas de tamaño inesperado.")
            return raw[PK6_STORED_SIZE:PK6_STORED_SIZE + size]
        raise AssertionError(f"Lectura inesperada: +0x{relative:X}")

    def write_memory(self, address: int, data: bytes):
        index = (address - ORAS_PARTY_ADDRESS) // ORAS_PARTY_STRIDE
        relative = address - (ORAS_PARTY_ADDRESS + index * ORAS_PARTY_STRIDE)
        if relative == 0 and len(data) == PK6_STORED_SIZE:
            replacement = bytes(data) + self.slots[index][PK6_STORED_SIZE:]
        elif relative == ORAS_PARTY_STATS_OFFSET and len(data) == ORAS_PARTY_STATS_SIZE:
            replacement = (
                self.slots[index][:PK6_STORED_SIZE]
                + bytes(data)
                + self.slots[index][PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE:]
            )
        else:
            raise AssertionError("El escritor intentó actualizar una región de party inesperada.")
        self.writes.append((address, bytes(data)))
        if self.ignore_first_write and len(self.writes) == 1:
            return
        self.slots[index] = replacement


class _ExtendedFakeClient(_WritableFakeClient):
    def __init__(
        self, slots: tuple[bytes, ...], *, pc_slot: bytes, pc_base: int = ORAS_PC_ADDRESS,
    ) -> None:
        super().__init__(slots)
        misc_base = ORAS_MONEY_ADDRESS - ORAS_MISC_MONEY_OFFSET
        self.pc_base = int(pc_base)
        self.memory: dict[int, bytearray] = {
            self.pc_base: bytearray(pc_slot),
            ORAS_ITEMS_POUCH_ADDRESS: bytearray(ORAS_ITEMS_POUCH_SIZE),
            ORAS_MEDICINE_POUCH_ADDRESS: bytearray(ORAS_MEDICINE_POUCH_SIZE),
            misc_base: make_oras_misc(money=1_234),
            ORAS_TM_POUCH_ADDRESS: bytearray(ORAS_TM_POUCH_SIZE),
        }
        # Una Poción normal demuestra que el bolsillo es una lista de registros
        # reales, pero deja un hueco libre para el Caramelo Raro.
        struct.pack_into("<HH", self.memory[ORAS_ITEMS_POUCH_ADDRESS], 0, 4, 8)
        struct.pack_into("<HH", self.memory[ORAS_ITEMS_POUCH_ADDRESS], 4, 5, 3)
        struct.pack_into("<HH", self.memory[ORAS_MEDICINE_POUCH_ADDRESS], 0, 17, 5)
        self.ignore_first_at: set[int] = set()
        self._ignored_at: set[int] = set()

    def _memory_range(self, address: int, size: int):
        for base, data in self.memory.items():
            if base <= address and address + size <= base + len(data):
                return base, data, address - base
        return None

    def read_memory(self, address: int, size: int):
        memory = self._memory_range(address, size)
        if memory is not None:
            _base, data, offset = memory
            return bytes(data[offset:offset + size])
        # Las calibraciones dinámicas inspeccionan distintas zonas del heap de
        # ORAS. Para el fake, toda RAM no mapeada se comporta como cero, pero
        # conservamos las lecturas directas de los seis slots de party.
        party_span_end = ORAS_PARTY_ADDRESS + 6 * ORAS_PARTY_STRIDE
        direct_party_read = (
            ORAS_PARTY_ADDRESS <= address < party_span_end
            and size <= max(PK6_STORED_SIZE, ORAS_PARTY_STATS_SIZE)
        )
        if 0x08A00000 <= address < 0x09000000 and not direct_party_read:
            result = bytearray(size)
            end = address + size
            for base, data in self.memory.items():
                overlap_start = max(address, base)
                overlap_end = min(end, base + len(data))
                if overlap_start < overlap_end:
                    result[overlap_start - address:overlap_end - address] = data[
                        overlap_start - base:overlap_end - base
                    ]
            return bytes(result)
        return super().read_memory(address, size)

    def write_memory(self, address: int, data: bytes):
        if address in self.ignore_first_at and address not in self._ignored_at:
            self._ignored_at.add(address)
            self.writes.append((address, bytes(data)))
            return
        memory = self._memory_range(address, len(data))
        if memory is not None:
            _base, target, offset = memory
            target[offset:offset + len(data)] = data
            self.writes.append((address, bytes(data)))
            return
        return super().write_memory(address, data)


class ORASLiveWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.initial = make_encrypted_pk6()
        self.empty_slots = (bytes(PK6_PARTY_SIZE),) * 5
        self.current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})

    def _writer(self, fake: _WritableFakeClient) -> ORASLiveWriter:
        reader = ORASLiveReader(
            Path("does-not-exist.json"),
            client_factory=lambda: fake,
            stable_delay=0,
        )
        return ORASLiveWriter(
            reader,
            move_pp_for=lambda move_id: {33: 35, 44: 25, 45: 15, 99: 10, 468: 15, 528: 15}[move_id],
            personal_for=lambda species_id, _form: {
                261: ORASPersonalStats((35, 55, 35, 35, 30, 30), 0),
                263: ORASPersonalStats((38, 30, 41, 60, 30, 41), 0),
            }.get(species_id),
        )

    def _live_consistent_slot(
        self,
        *,
        marking: int = 0,
        evs: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0),
    ) -> bytes:
        """PK6 de party cuya extensión coincide con el bloque almacenado."""
        raw = make_encrypted_pk6(marking=marking, evs=evs)
        plain = bytearray(decrypt_pk6(raw))
        personal = ORASPersonalStats((35, 55, 35, 35, 30, 30), 0)
        plain[PK6_STORED_SIZE:] = ORASLiveWriter._party_extension(
            bytes(plain[:PK6_STORED_SIZE]), personal,
        )
        return encrypt_pk6(bytes(plain))

    def test_oras_14_pc_base_uses_the_shifted_address(self) -> None:
        # 0x08C9E134 es la base de cajas de ORAS 1.0. El resto del perfil de
        # este lector es 1.4, cuyo bloque de PC está +0x3FF0 bytes.
        self.assertEqual(ORAS_PC_ADDRESS, 0x08CA2124)

    @staticmethod
    def _identity() -> str:
        return "261:2309737967:12345:54321"

    @staticmethod
    def _inventory_witnesses(*, rare_candy: int = 0, tm: int | None = None, tm_item_id: int = 328):
        rare_candy_witness = (
            ("medicine", 1, 50, rare_candy)
            if rare_candy else ("medicine", -50, 50, 0)
        )
        values = (
            ("items", 0, 4, 8),
            ("items", 1, 5, 3),
            ("medicine", 0, 17, 5),
            rare_candy_witness,
        )
        if tm is None:
            return values
        return (*values, ("tms", 0, tm_item_id, tm))


    @staticmethod
    def _make_save_with_misc(*, badges: int = 8, money: int = 996_999) -> Path:
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.close()
        path = Path(handle.name)
        data = bytearray(0x76000)
        misc = make_oras_misc(badges=badges, money=money)
        data[ORAS_SAVE_MISC_OFFSET:ORAS_SAVE_MISC_OFFSET + ORAS_SAVE_MISC_SIZE] = misc
        path.write_bytes(data)
        return path

    @staticmethod
    def _eventwork_with_badges(count: int) -> bytearray:
        raw = bytearray(ORAS_SAVE_EVENTWORK_SIZE)
        # Huella repartida por EventWork que no toca el clúster de líderes.
        for offset in range(0x20, 0x2D0, 0x17):
            raw[offset] = ((offset // 0x17) * 13 + 7) & 0xFF or 1
        raw[0x80:0x90] = b"RoleRun-Evt-1234"
        for flag in ORAS_BADGE_RECEIVED_FLAGS[:count]:
            byte_offset = ORAS_EVENTWORK_FLAG_OFFSET + (flag >> 3)
            raw[byte_offset] |= 1 << (flag & 7)
        return raw

    def _make_save_with_eventwork(self, *, saved_badges: int = 0, misc_badges: int = 0) -> Path:
        path = self._make_save_with_misc(badges=misc_badges, money=996_999)
        data = bytearray(path.read_bytes())
        eventwork = self._eventwork_with_badges(saved_badges)
        data[ORAS_SAVE_EVENTWORK_OFFSET:ORAS_SAVE_EVENTWORK_OFFSET + ORAS_SAVE_EVENTWORK_SIZE] = eventwork
        path.write_bytes(data)
        return path

    @staticmethod
    def _subevent_with_badges(count: int) -> bytearray:
        raw = bytearray(ORAS_SAVE_SUBEVENT_SIZE)
        for offset in ORAS_SUBEVENT_MAGIC_OFFSETS:
            raw[offset:offset + 4] = b"SUBE"
        # Datos estables fuera de las zonas dinámicas para que también exista
        # una huella secundaria realista.
        raw[0x210:0x220] = b"RoleRun-SUBE-123"
        teams = (
            (261, 263, 265, 0, 0, 0),
            (280, 304, 0, 0, 0, 0),
            (359, 272, 503, 0, 0, 0),
            (248, 609, 214, 159, 0, 0),
            (18, 237, 235, 687, 0, 0),
            (560, 567, 125, 191, 0, 0),
            (635, 526, 564, 398, 390, 0),
            (17, 503, 248, 609, 272, 687),
        )
        for badge_index, team in enumerate(teams[:count]):
            offset = ORAS_SUBEVENT_BADGE_VICTORY_OFFSET + (
                badge_index * ORAS_SUBEVENT_BADGE_SLOT_COUNT * 2
            )
            struct.pack_into(f"<{ORAS_SUBEVENT_BADGE_SLOT_COUNT}H", raw, offset, *team)
        return raw

    def _make_save_with_subevent(
        self,
        *,
        subevent_badges: int = 0,
        event_badges: int = 0,
        misc_badges: int = 0,
    ) -> Path:
        path = self._make_save_with_eventwork(
            saved_badges=event_badges, misc_badges=misc_badges,
        )
        data = bytearray(path.read_bytes())
        subevent = self._subevent_with_badges(subevent_badges)
        data[ORAS_SAVE_SUBEVENT_OFFSET:ORAS_SAVE_SUBEVENT_OFFSET + ORAS_SAVE_SUBEVENT_SIZE] = subevent
        path.write_bytes(data)
        return path

    @staticmethod
    def _set_gym_reward_pouch(
        fake: _ExtendedFakeClient,
        count: int,
        *,
        base: int = ORAS_TM_POUCH_ADDRESS,
        include_dive: bool = False,
    ) -> None:
        raw = bytearray(ORAS_TM_POUCH_SIZE)
        # Incluimos un par de MT normales para que el bolsillo se parezca a una
        # partida real y luego los premios de gimnasio en slots consecutivos.
        records = [(328, 1), (329, 1)]
        records.extend((int(item_id), 1) for item_id in ORAS_GYM_REWARD_ITEM_IDS[:count])
        # En ORAS Buceo es la máquina #737. Se obtiene durante la progresión
        # avanzada y debe coexistir con 7/8 medallas sin invalidar el bolsillo.
        if include_dive:
            records.append((ORAS_HM07_ITEM_ID, 1))
        for slot, (item_id, quantity) in enumerate(records):
            struct.pack_into("<HH", raw, slot * 4, item_id, quantity)
        fake.memory[base] = raw

    def test_gym_reward_items_count_exact_progress(self) -> None:
        for count in range(1, 9):
            items = {int(item_id): 1 for item_id in ORAS_GYM_REWARD_ITEM_IDS[:count]}
            self.assertEqual(count_oras_gym_reward_items(items), count)
        self.assertEqual(ORAS_HM05_ITEM_ID, 424)

    def test_gym_reward_items_reject_empty_or_non_prefix(self) -> None:
        self.assertIsNone(count_oras_gym_reward_items({}))
        # Tener un premio posterior sin el anterior no se interpreta como una
        # medalla: protege frente a MTs encontradas por randomización de objetos.
        items = {int(ORAS_GYM_REWARD_ITEM_IDS[0]): 1, int(ORAS_GYM_REWARD_ITEM_IDS[2]): 1}
        self.assertIsNone(count_oras_gym_reward_items(items))

    def test_tm_hm_pocket_rejects_non_tm_items(self) -> None:
        raw = bytearray(ORAS_TM_POUCH_SIZE)
        struct.pack_into("<HH", raw, 0, 4, 1)  # Poké Ball, no TM/MO
        with self.assertRaises(ORASLiveError):
            parse_oras_tm_hm_pocket(bytes(raw))

    def test_tm_hm_pocket_accepts_oras_dive_item_737(self) -> None:
        raw = bytearray(ORAS_TM_POUCH_SIZE)
        struct.pack_into("<HH", raw, 0, ORAS_HM07_ITEM_ID, 1)
        parsed = parse_oras_tm_hm_pocket(bytes(raw))
        self.assertEqual(parsed[ORAS_HM07_ITEM_ID], 1)
        self.assertEqual(ORAS_HM07_ITEM_ID, 737)

    def test_gym_reward_detector_tracks_seven_to_eight_with_dive_present(self) -> None:
        """Regresión del caso real de alpha.40: 7/8 medallas + MO Buceo."""
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_subevent(
            subevent_badges=0, event_badges=0, misc_badges=0,
        )
        try:
            self._set_gym_reward_pouch(fake, 7, include_dive=True)
            self.assertEqual(writer.read_badges(save_path), 7)
            self.assertEqual(writer.last_badge_source, "Premios líderes · MT/MO")

            # Wallace añade HM05. La dirección ya está cacheada y el siguiente
            # tick debe reflejar 7 -> 8 sin recalibración ni guardado manual.
            self._set_gym_reward_pouch(fake, 8, include_dive=True)
            self.assertEqual(writer.read_badges(save_path), 8)
            self.assertEqual(writer.last_badge_source, "Premios líderes · MT/MO")
        finally:
            save_path.unlink(missing_ok=True)

    def test_badges_prefer_live_gym_reward_items_over_zero_legacy_sources(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_subevent(
            subevent_badges=0, event_badges=0, misc_badges=0,
        )
        try:
            self._set_gym_reward_pouch(fake, 8, include_dive=True)
            self.assertEqual(writer.read_badges(save_path), 8)
            self.assertEqual(writer.last_badge_source, "Premios líderes · MT/MO")
        finally:
            save_path.unlink(missing_ok=True)

    def test_gym_reward_detector_tracks_state_load_backwards(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_subevent(
            subevent_badges=0, event_badges=0, misc_badges=0,
        )
        try:
            self._set_gym_reward_pouch(fake, 8)
            self.assertEqual(writer.read_badges(save_path), 8)
            self._set_gym_reward_pouch(fake, 5)
            self.assertEqual(writer.read_badges(save_path), 5)
            self.assertEqual(writer.last_badge_source, "Premios líderes · MT/MO")
        finally:
            save_path.unlink(missing_ok=True)

    def test_gym_reward_detector_can_find_shifted_tm_pouch(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_subevent(
            subevent_badges=0, event_badges=0, misc_badges=0,
        )
        try:
            # La dirección nominal queda vacía; la copia viva está desplazada.
            fake.memory[ORAS_TM_POUCH_ADDRESS] = bytearray(ORAS_TM_POUCH_SIZE)
            shifted = 0x08C7A400
            self._set_gym_reward_pouch(fake, 8, base=shifted)
            self.assertEqual(writer.read_badges(save_path), 8)
            self.assertEqual(writer.last_badge_source, "Premios líderes · MT/MO")
            key = (0x000400000011C500, "sango-2")
            self.assertEqual(writer._tm_badge_bases_by_process[key], shifted)
        finally:
            save_path.unlink(missing_ok=True)

    def test_tm_inventory_reuses_shifted_pouch_discovered_by_badges(self) -> None:
        """Alpha.45: selector MT y medallas deben mirar la misma mochila viva."""
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_subevent(
            subevent_badges=0, event_badges=0, misc_badges=0,
        )
        try:
            # La dirección histórica está vacía, exactamente el caso que hacía
            # que alpha.44 mostrara 0 MT aunque medallas ya hubiese encontrado
            # una copia desplazada válida.
            fake.memory[ORAS_TM_POUCH_ADDRESS] = bytearray(ORAS_TM_POUCH_SIZE)
            shifted = 0x08C7A400
            self._set_gym_reward_pouch(fake, 8, base=shifted, include_dive=True)
            # Añadimos una MT que no forma parte de los premios para demostrar
            # que el selector recibe el bolsillo completo, no solo las medallas.
            struct.pack_into("<HH", fake.memory[shifted], 12 * 4, 618, 1)  # MT93

            self.assertEqual(writer.read_badges(save_path), 8)
            inventory, process, attempt = writer.read_tm_inventory({328: 1, 329: 1})
            self.assertEqual(process.name, "sango-2")
            self.assertGreaterEqual(attempt, 1)
            self.assertEqual(inventory[618], 1)
            self.assertEqual(inventory[ORAS_HM07_ITEM_ID], 1)
            key = (0x000400000011C500, "sango-2")
            self.assertEqual(writer._tm_inventory_bases_by_process[key], shifted)
        finally:
            save_path.unlink(missing_ok=True)

    def test_tm_inventory_does_not_fall_back_to_nominal_after_live_pouch_is_cached(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        shifted = 0x08C7A400
        self._set_gym_reward_pouch(fake, 8, base=shifted, include_dive=True)
        key = (0x000400000011C500, "sango-2")
        writer._tm_badge_bases_by_process[key] = shifted

        # La dirección nominal contiene una copia perfectamente parseable pero
        # antigua. Alpha.44 la habría usado; alpha.45 debe preferir la cacheada.
        self._set_gym_reward_pouch(fake, 1, base=ORAS_TM_POUCH_ADDRESS)
        struct.pack_into("<HH", fake.memory[shifted], 12 * 4, 618, 1)
        inventory, _process, _attempt = writer.read_tm_inventory({328: 1})
        self.assertIn(618, inventory)
        self.assertEqual(writer._tm_inventory_bases_by_process[key], shifted)

    def test_subevent_badge_victory_count_zero_three_and_eight(self) -> None:
        for count in (0, 3, 8):
            raw = self._subevent_with_badges(count)
            self.assertEqual(count_oras_badge_victories(raw), count)
            records = parse_oras_badge_victory_records(raw)
            self.assertIsNotNone(records)
            assert records is not None
            for index, record in enumerate(records):
                self.assertEqual(any(record), index < count)

    def test_subevent_rejects_non_prefix_progress(self) -> None:
        raw = self._subevent_with_badges(2)
        first = ORAS_SUBEVENT_BADGE_VICTORY_OFFSET
        raw[first:first + (ORAS_SUBEVENT_BADGE_SLOT_COUNT * 2)] = bytes(ORAS_SUBEVENT_BADGE_SLOT_COUNT * 2)
        self.assertIsNone(count_oras_badge_victories(raw))

    def test_badges_prefer_live_subevent_history_over_zero_eventwork_and_misc(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_subevent(
            subevent_badges=0, event_badges=0, misc_badges=0,
        )
        try:
            active_base = 0x08C7B000
            fake.memory[active_base] = self._subevent_with_badges(8)
            self.assertEqual(writer.read_badges(save_path), 8)
            self.assertEqual(writer._last_badge_source, "SUBE vivo · equipos de gimnasio")
            process_key = (0x000400000011C500, "sango-2")
            self.assertEqual(writer._subevent_bases_by_process[process_key], active_base)
        finally:
            save_path.unlink(missing_ok=True)

    def test_live_subevent_does_not_require_a_valid_disk_subevent_signature(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_eventwork(saved_badges=0, misc_badges=0)
        try:
            # Simula un main viejo/no útil para esta estructura: la zona SUBE en
            # disco no aporta firmas, pero la RAM viva sí contiene la tabla real.
            data = bytearray(save_path.read_bytes())
            data[ORAS_SAVE_SUBEVENT_OFFSET:ORAS_SAVE_SUBEVENT_OFFSET + ORAS_SAVE_SUBEVENT_SIZE] = bytes(ORAS_SAVE_SUBEVENT_SIZE)
            save_path.write_bytes(data)
            active_base = 0x08C7B000
            fake.memory[active_base] = self._subevent_with_badges(4)
            self.assertEqual(writer.read_badges(save_path), 4)
            self.assertEqual(writer.last_badge_source, "SUBE vivo · equipos de gimnasio")
        finally:
            save_path.unlink(missing_ok=True)

    def test_subevent_can_be_found_outside_primary_heap_window(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_subevent(
            subevent_badges=0, event_badges=0, misc_badges=0,
        )
        try:
            # Fuerza la segunda banda de escaneo. Esto protege frente a builds de
            # Azahar que no coloquen SubEventLog junto a mochila/PC.
            active_base = 0x08A54000
            fake.memory[active_base] = self._subevent_with_badges(6)
            self.assertEqual(writer.read_badges(save_path), 6)
            self.assertEqual(writer.last_badge_source, "SUBE vivo · equipos de gimnasio")
            process_key = (0x000400000011C500, "sango-2")
            self.assertEqual(writer._subevent_bases_by_process[process_key], active_base)
        finally:
            save_path.unlink(missing_ok=True)

    def test_subevent_calibration_prefers_live_progress_over_stale_exact_copy(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_subevent(
            subevent_badges=0, event_badges=0, misc_badges=0,
        )
        try:
            stale_base = 0x08C7B000
            active_base = 0x08C7D000
            saved = bytearray(save_path.read_bytes()[
                ORAS_SAVE_SUBEVENT_OFFSET:ORAS_SAVE_SUBEVENT_OFFSET + ORAS_SAVE_SUBEVENT_SIZE
            ])
            fake.memory[stale_base] = bytearray(saved)
            active = self._subevent_with_badges(8)
            active[0x214] ^= 0x01  # menos parecido a main, pero más avanzado
            fake.memory[active_base] = active

            self.assertEqual(writer.read_badges(save_path), 8)
            process_key = (0x000400000011C500, "sango-2")
            self.assertEqual(writer._subevent_bases_by_process[process_key], active_base)
        finally:
            save_path.unlink(missing_ok=True)

    def test_cached_subevent_tracks_state_load_backwards_without_rescan(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_subevent(
            subevent_badges=5, event_badges=0, misc_badges=0,
        )
        try:
            active_base = 0x08C7B000
            fake.memory[active_base] = self._subevent_with_badges(8)
            self.assertEqual(writer.read_badges(save_path), 8)
            # Simula cargar un state anterior: la MISMA estructura viva vuelve a 5.
            fake.memory[active_base][:] = self._subevent_with_badges(5)
            self.assertEqual(writer.read_badges(save_path), 5)
            process_key = (0x000400000011C500, "sango-2")
            self.assertEqual(writer._subevent_bases_by_process[process_key], active_base)
        finally:
            save_path.unlink(missing_ok=True)

    def test_saved_subevent_history_is_stronger_fallback_than_zero_legacy_sources(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_subevent(
            subevent_badges=8, event_badges=0, misc_badges=0,
        )
        try:
            # No añadimos ninguna copia SUBE viva al fake. La lectura histórica
            # del main debe seguir evitando el falso 0 de las fuentes antiguas.
            with patch.object(writer, "_locate_misc_base", return_value=None):
                self.assertEqual(writer.read_badges(save_path), 8)
            self.assertEqual(writer._last_badge_source, "main · equipos de gimnasio")
        finally:
            save_path.unlink(missing_ok=True)

    def test_eventwork_received_badges_count_zero_three_and_eight(self) -> None:
        self.assertEqual(ORAS_GYM_LEADER_FLAGS, ORAS_BADGE_RECEIVED_FLAGS)
        self.assertEqual(ORAS_BADGE_RECEIVED_FLAGS, tuple(range(0x807, 0x80F)))
        for count in (0, 3, 8):
            raw = self._eventwork_with_badges(count)
            self.assertEqual(count_oras_received_badges(raw), count)
            self.assertEqual(count_oras_gym_leader_flags(raw), count)
            for index, flag in enumerate(ORAS_BADGE_RECEIVED_FLAGS):
                self.assertEqual(parse_oras_event_flag(raw, flag), index < count)

    def test_alpha37_trainer_battle_flags_are_not_badges(self) -> None:
        # Regresión del fallo raíz de alpha.37: estos eran los flags que se
        # estaban interpretando como medallas, pero no son Received Badge.
        raw = self._eventwork_with_badges(0)
        old_alpha37_flags = (0x8FD, 0x8FF, 0x903, 0x905, 0x906, 0x907, 0x8F4, 0x908)
        for flag in old_alpha37_flags:
            byte_offset = ORAS_EVENTWORK_FLAG_OFFSET + (flag >> 3)
            raw[byte_offset] |= 1 << (flag & 7)
        self.assertEqual(count_oras_received_badges(raw), 0)

    def test_badges_prefer_live_received_badge_flags_over_stale_misc(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_eventwork(saved_badges=0, misc_badges=0)
        try:
            active_base = 0x08C7B000
            fake.memory[active_base] = self._eventwork_with_badges(8)
            self.assertEqual(writer.read_badges(save_path), 8)
        finally:
            save_path.unlink(missing_ok=True)

    def test_eventwork_calibration_prefers_live_progress_over_stale_exact_copy(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_eventwork(saved_badges=0, misc_badges=0)
        try:
            saved = bytearray(save_path.read_bytes()[
                ORAS_SAVE_EVENTWORK_OFFSET:ORAS_SAVE_EVENTWORK_OFFSET + ORAS_SAVE_EVENTWORK_SIZE
            ])
            stale_base = 0x08C7B000
            active_base = 0x08C7D000
            fake.memory[stale_base] = bytearray(saved)

            active = self._eventwork_with_badges(8)
            # Simula avance de historia adicional respecto a main: pierde una
            # coincidencia de huella, pero conserva anchors suficientes.
            anchor_ranges = {
                i
                for offset, pattern in writer._eventwork_anchors(bytes(saved))
                for i in range(offset, offset + len(pattern))
            }
            mutable = next(
                pos for pos in writer._eventwork_fingerprint_positions(bytes(saved))
                if pos not in anchor_ranges
            )
            active[mutable] ^= 0x01
            fake.memory[active_base] = active

            # Alpha.37 elegía la copia stale porque tenía más matches con main.
            # Alpha.38 debe priorizar la progresión viva (8 medallas).
            self.assertEqual(writer.read_badges(save_path), 8)
            process_key = (0x000400000011C500, "sango-2")
            self.assertEqual(writer._eventwork_bases_by_process[process_key], active_base)
        finally:
            save_path.unlink(missing_ok=True)

    def test_cached_eventwork_tracks_new_badge_without_rescanning(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_eventwork(saved_badges=6, misc_badges=0)
        try:
            active_base = 0x08C7B000
            live = self._eventwork_with_badges(7)
            fake.memory[active_base] = live
            self.assertEqual(writer.read_badges(save_path), 7)
            flag = ORAS_BADGE_RECEIVED_FLAGS[7]
            byte_offset = ORAS_EVENTWORK_FLAG_OFFSET + (flag >> 3)
            fake.memory[active_base][byte_offset] |= 1 << (flag & 7)
            self.assertEqual(writer.read_badges(save_path), 8)
        finally:
            save_path.unlink(missing_ok=True)

    def test_badges_are_read_from_independent_live_misc_copy(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_misc(badges=7)
        try:
            saved_misc = bytearray(save_path.read_bytes()[ORAS_SAVE_MISC_OFFSET:ORAS_SAVE_MISC_OFFSET + ORAS_SAVE_MISC_SIZE])

            # La copia histórica está obsoleta (0), mientras que Misc vive en
            # una dirección independiente que NO comparte el delta de mochila.
            static_base = ORAS_BADGES_ADDRESS - ORAS_MISC_BADGES_OFFSET
            stale_misc = bytearray(saved_misc)
            stale_misc[ORAS_MISC_BADGES_OFFSET] = 0
            fake.memory[static_base] = stale_misc

            active_base = 0x08C7A000
            fake.memory[active_base] = bytearray(saved_misc)
            self.assertEqual(writer.read_badges(save_path, self._inventory_witnesses()), 7)

            # Tras calibrar la copia viva, una medalla nueva se observa aunque
            # ``main`` todavía siga en 7.
            fake.memory[active_base][ORAS_MISC_BADGES_OFFSET] = 8
            self.assertEqual(writer.read_badges(save_path, self._inventory_witnesses()), 8)
        finally:
            save_path.unlink(missing_ok=True)


    def test_badges_choose_live_eight_when_main_and_static_copy_still_say_zero(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_misc(badges=0, money=996_999)
        try:
            saved_misc = bytearray(save_path.read_bytes()[ORAS_SAVE_MISC_OFFSET:ORAS_SAVE_MISC_OFFSET + ORAS_SAVE_MISC_SIZE])
            static_base = ORAS_BADGES_ADDRESS - ORAS_MISC_BADGES_OFFSET
            stale_misc = bytearray(saved_misc)
            struct.pack_into("<I", stale_misc, ORAS_MISC_MONEY_OFFSET, 1_234)
            stale_misc[ORAS_MISC_BADGES_OFFSET] = 0
            fake.memory[static_base] = stale_misc

            active_base = 0x08C7A000
            active_misc = bytearray(saved_misc)
            struct.pack_into("<I", active_misc, ORAS_MISC_MONEY_OFFSET, 1_234)
            active_misc[ORAS_MISC_BADGES_OFFSET] = 8
            fake.memory[active_base] = active_misc

            self.assertEqual(writer.read_badges(save_path), 8)
        finally:
            save_path.unlink(missing_ok=True)

    def test_badges_fall_back_to_main_when_live_misc_is_not_locatable(self) -> None:
        boxed = make_encrypted_pk6()[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial, *self.empty_slots), pc_slot=boxed)
        writer = self._writer(fake)
        save_path = self._make_save_with_misc(badges=8)
        try:
            # No existe ninguna copia Misc compatible en la RAM falsa: aun así
            # el contador automático debe mostrar el valor real del guardado.
            with patch.object(writer, "_locate_misc_base", return_value=None):
                self.assertEqual(writer.read_badges(save_path, self._inventory_witnesses()), 8)
        finally:
            save_path.unlink(missing_ok=True)

    def test_encrypt_roundtrip_preserves_plain_pk6(self) -> None:
        plain = decrypt_pk6(self.initial)
        self.assertEqual(decrypt_pk6(encrypt_pk6(plain)), plain)

    def test_oras_pp_table_covers_every_gen6_move_id(self) -> None:
        table = load_oras_move_pp(Path("data/oras_move_pp.json"))
        self.assertEqual(len(table), 621)
        self.assertEqual((table[33], table[44], table[564]), (35, 25, 20))

    def test_live_level_is_read_from_party_extension_not_recalculated_from_exp(self) -> None:
        raw = make_encrypted_pk6(experience=1, level=71)
        pokemon = parse_pk6_party(raw, 1, {})
        self.assertIsNotNone(pokemon)
        assert pokemon is not None
        # EXP=1 sería incompatible con nivel 71 en una tabla estándar; conservar
        # 71 demuestra que RoleRun usa el byte vivo que mantiene ORAS.
        self.assertEqual(pokemon.level, 71)

    def test_live_party_fingerprint_only_tracks_role_moves_and_identity(self) -> None:
        base = parse_pk6_party(make_encrypted_pk6(), 1, {})
        same_identity_new_level = parse_pk6_party(make_encrypted_pk6(), 1, {})
        role_changed = parse_pk6_party(make_encrypted_pk6(marking=1), 1, {})
        move_changed = parse_pk6_party(make_encrypted_pk6(moves=(99, 44, 45, 0)), 1, {})
        assert base is not None and same_identity_new_level is not None
        assert role_changed is not None and move_changed is not None
        same_identity_new_level.level = 19

        def game(pokemon):
            return SaveGameData("AS", "SAV6AO", 6, "Diego", [pokemon], {})

        baseline = live_party_fingerprint(game(base))
        self.assertEqual(baseline, live_party_fingerprint(game(same_identity_new_level)))
        self.assertNotEqual(baseline, live_party_fingerprint(game(role_changed)))
        self.assertNotEqual(baseline, live_party_fingerprint(game(move_changed)))

    def test_live_writer_updates_role_move_pp_and_checksum(self) -> None:
        fake = _WritableFakeClient((self.initial,) + self.empty_slots)
        writer = self._writer(fake)
        result = writer.apply(self.current, [
            PendingRoleChange(1, "Poochyena", "Poochyena", "Líbero", "Tanque", self._identity()),
            PendingChange("Tanque", 1, "Poochyena", "Poochyena", 1, "Placaje", 33, "Movimiento #99", 99, self._identity()),
        ])
        self.assertEqual(result.applied_count, 2)
        self.assertEqual(result.game.party[0].role, "Tanque")
        self.assertEqual(result.game.party[0].move_ids, [99, 44, 45, 0])
        plain = decrypt_pk6(fake.slots[0])
        self.assertEqual(struct.unpack_from("<H", plain, 6)[0], _checksum(plain))
        self.assertEqual(plain[0x2A] & 0x3F, 0b1000)  # Tanque = marcador 4
        # El primer movimiento tenía dos PP Ups: 10 × (5 + 2) / 5 = 14.
        self.assertEqual(plain[0x62], 14)
        self.assertEqual(plain[0x66], 2)

    def test_live_writer_applies_role_evs_and_recalculates_runtime_stats(self) -> None:
        initial = self._live_consistent_slot()
        fake = _WritableFakeClient((initial,) + self.empty_slots)
        result = self._writer(fake).apply(self.current, [
            PendingRoleChange(
                1, "Poochyena", "Poochyena", "Líbero", "Tanque", self._identity(),
                old_evs=(0, 0, 0, 0, 0, 0),
                new_evs=(252, 0, 252, 0, 0, 0),
            ),
        ])

        pokemon = result.game.party[0]
        self.assertEqual(pokemon.role, "Tanque")
        self.assertEqual(
            tuple(pokemon.evs[key] for key in (
                "hp", "attack", "defense", "sp_attack", "sp_defense", "speed",
            )),
            (252, 0, 252, 0, 0, 0),
        )
        before = parse_pk6_party(initial, 1, {})
        self.assertIsNotNone(before)
        assert before is not None
        self.assertGreater(pokemon.max_hp, before.max_hp)
        self.assertGreater(pokemon.stats["defense"], before.stats["defense"])
        self.assertEqual(len(fake.writes), 2)

    def test_live_writer_rejects_stale_role_evs_without_writing(self) -> None:
        initial = self._live_consistent_slot()
        fake = _WritableFakeClient((initial,) + self.empty_slots)

        with self.assertRaisesRegex(ORASLiveError, "cambió sus EV"):
            self._writer(fake).apply(self.current, [
                PendingRoleChange(
                    1, "Poochyena", "Poochyena", "Líbero", "Tanque", self._identity(),
                    old_evs=(1, 0, 0, 0, 0, 0),
                    new_evs=(252, 0, 252, 0, 0, 0),
                ),
            ])

        self.assertEqual(fake.writes, [])
        self.assertEqual(fake.slots[0], initial)

    def test_live_writer_rolls_back_role_evs_when_readback_fails(self) -> None:
        initial = self._live_consistent_slot()
        fake = _WritableFakeClient((initial,) + self.empty_slots, ignore_first_write=True)

        with self.assertRaisesRegex(ORASLiveError, "no confirmó"):
            self._writer(fake).apply(self.current, [
                PendingRoleChange(
                    1, "Poochyena", "Poochyena", "Líbero", "Tanque", self._identity(),
                    old_evs=(0, 0, 0, 0, 0, 0),
                    new_evs=(252, 0, 252, 0, 0, 0),
                ),
            ])

        self.assertEqual(fake.slots[0], initial)

    def test_live_writer_applies_role_transfer_in_one_batch(self) -> None:
        second = make_encrypted_pk6(marking=3)  # Tanque = marcador 4
        fake = _WritableFakeClient((self.initial, second) + (bytes(PK6_PARTY_SIZE),) * 4)
        result = self._writer(fake).apply(self.current, [
            PendingRoleChange(1, "Poochyena", "Poochyena", "Líbero", "Tanque"),
            PendingRoleChange(2, "Poochyena", "Poochyena", "Tanque", "SIN ROL"),
        ])
        self.assertEqual(result.applied_count, 2)
        self.assertEqual([pokemon.role for pokemon in result.game.party], ["Tanque", "SIN ROL"])
        self.assertEqual(len(fake.writes), 2)

    def test_live_writer_updates_pc_role_inventory_and_money_with_verification(self) -> None:
        pc_slot = make_encrypted_pk6(marking=0)[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial,) + self.empty_slots, pc_slot=pc_slot)
        result = self._writer(fake).apply(self.current, [
            PendingPCRoleChange(
                box=1, box_slot=1, pokemon="Poochyena", species="Poochyena",
                pokemon_identity=self._identity(), old_role="SIN ROL", new_role="Mago",
            ),
            PendingInventoryChange("rare-candy", "Caramelo Raro", 999, self._inventory_witnesses()),
            PendingInventoryChange(
                "money-max", "Dinero", 9_999_999,
                save_misc_witness=bytes(make_oras_misc(money=1_234)),
            ),
        ])
        self.assertEqual(result.applied_count, 3)
        self.assertEqual(len(result.memory_watches), 3)
        boxed = parse_pk6_boxed(bytes(fake.memory[ORAS_PC_ADDRESS]), 1, 1, {})
        self.assertIsNotNone(boxed)
        assert boxed is not None
        self.assertEqual(boxed.role, "Mago")
        plain = decrypt_pk6_stored(bytes(fake.memory[ORAS_PC_ADDRESS]))
        self.assertEqual(struct.unpack_from("<H", plain, 6)[0], _checksum(plain))
        medicine = fake.memory[ORAS_MEDICINE_POUCH_ADDRESS]
        self.assertEqual(struct.unpack_from("<HH", medicine, 4), (50, 999))
        misc_base = ORAS_MONEY_ADDRESS - ORAS_MISC_MONEY_OFFSET
        self.assertEqual(
            struct.unpack_from("<I", fake.memory[misc_base], ORAS_MISC_MONEY_OFFSET)[0],
            9_999_999,
        )

    def test_live_writer_accepts_an_inventory_value_already_present_in_ram(self) -> None:
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        # Simula que un intento anterior ya dejó el Caramelo Raro en RAM.
        struct.pack_into("<HH", fake.memory[ORAS_MEDICINE_POUCH_ADDRESS], 4, 50, 999)

        result = self._writer(fake).apply(self.current, [
            PendingInventoryChange("rare-candy", "Caramelo Raro", 999, self._inventory_witnesses(rare_candy=999)),
        ])

        self.assertTrue(result.already_applied)
        self.assertEqual(result.applied_count, 1)
        self.assertEqual(fake.writes, [])
        self.assertEqual(len(result.memory_watches), 1)
        watch = result.memory_watches[0]
        self.assertEqual(watch.address, ORAS_MEDICINE_POUCH_ADDRESS + 4)
        self.assertEqual(watch.expected, struct.pack("<HH", 50, 999))

    def test_live_writer_calibrates_the_active_inventory_not_a_stale_copy(self) -> None:
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        # Reproduce el fallo visto en Azahar: la dirección antigua contiene una
        # copia que ya marca Caramelo Raro x999, mientras la mochila activa está
        # desplazada y aún no lo tiene.
        struct.pack_into("<HH", fake.memory[ORAS_MEDICINE_POUCH_ADDRESS], 4, 50, 999)
        delta = 0x5000
        active_items = bytearray(ORAS_ITEMS_POUCH_SIZE)
        active_medicine = bytearray(ORAS_MEDICINE_POUCH_SIZE)
        struct.pack_into("<HH", active_items, 0, 4, 8)
        struct.pack_into("<HH", active_items, 4, 5, 3)
        struct.pack_into("<HH", active_medicine, 0, 17, 5)
        fake.memory[ORAS_ITEMS_POUCH_ADDRESS + delta] = active_items
        fake.memory[ORAS_MEDICINE_POUCH_ADDRESS + delta] = active_medicine

        result = self._writer(fake).apply(self.current, [
            PendingInventoryChange("rare-candy", "Caramelo Raro", 999, self._inventory_witnesses()),
        ])

        self.assertEqual(
            struct.unpack_from("<HH", fake.memory[ORAS_MEDICINE_POUCH_ADDRESS], 4),
            (50, 999),
        )
        self.assertEqual(
            struct.unpack_from("<HH", fake.memory[ORAS_MEDICINE_POUCH_ADDRESS + delta], 4),
            (50, 999),
        )
        self.assertIn(
            (ORAS_MEDICINE_POUCH_ADDRESS + delta + 4, struct.pack("<HH", 50, 999)),
            fake.writes,
        )
        self.assertEqual(result.memory_watches[0].address, ORAS_MEDICINE_POUCH_ADDRESS + delta + 4)

    def test_live_writer_resolves_money_from_misc_independently_of_inventory(self) -> None:
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        delta = 0x5000
        active_items = bytearray(ORAS_ITEMS_POUCH_SIZE)
        active_medicine = bytearray(ORAS_MEDICINE_POUCH_SIZE)
        struct.pack_into("<HH", active_items, 0, 4, 8)
        struct.pack_into("<HH", active_items, 4, 5, 3)
        struct.pack_into("<HH", active_medicine, 0, 17, 5)
        fake.memory[ORAS_ITEMS_POUCH_ADDRESS + delta] = active_items
        fake.memory[ORAS_MEDICINE_POUCH_ADDRESS + delta] = active_medicine
        misc_base = ORAS_MONEY_ADDRESS - ORAS_MISC_MONEY_OFFSET
        saved_misc = bytes(make_oras_misc(money=1_234))

        result = self._writer(fake).apply(self.current, [
            PendingInventoryChange(
                "money-max", "Dinero", 9_999_999,
                save_misc_witness=saved_misc,
            ),
        ])

        self.assertEqual(
            struct.unpack_from("<I", fake.memory[misc_base], ORAS_MISC_MONEY_OFFSET)[0],
            9_999_999,
        )
        self.assertIn(
            (ORAS_MONEY_ADDRESS, struct.pack("<I", 9_999_999)),
            fake.writes,
        )
        self.assertEqual(result.memory_watches[0].address, ORAS_MONEY_ADDRESS)

    def test_live_writer_rejects_zero_nominal_misc_and_uses_valid_live_copy(self) -> None:
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        static_base = ORAS_MONEY_ADDRESS - ORAS_MISC_MONEY_OFFSET
        fake.memory[static_base] = bytearray(ORAS_SAVE_MISC_SIZE)
        live_base = static_base - 0x3FF0
        saved_misc = bytes(make_oras_misc(money=3_792, badges=1))
        fake.memory[live_base] = bytearray(saved_misc)

        result = self._writer(fake).apply(self.current, [
            PendingInventoryChange(
                "money-max", "Dinero", 9_999_999,
                save_misc_witness=saved_misc,
            ),
        ])

        self.assertEqual(
            struct.unpack_from("<I", fake.memory[live_base], ORAS_MISC_MONEY_OFFSET)[0],
            9_999_999,
        )
        self.assertEqual(bytes(fake.memory[static_base]), bytes(ORAS_SAVE_MISC_SIZE))
        self.assertIn(
            (live_base + ORAS_MISC_MONEY_OFFSET, struct.pack("<I", 9_999_999)),
            fake.writes,
        )
        self.assertEqual(
            result.memory_watches[0].address,
            live_base + ORAS_MISC_MONEY_OFFSET,
        )

    def test_live_writer_refuses_money_without_a_saved_misc_fingerprint(self) -> None:
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        with self.assertRaisesRegex(ORASLiveError, "huella Misc"):
            self._writer(fake).apply(self.current, [
                PendingInventoryChange("money-max", "Dinero", 9_999_999),
            ])
        self.assertEqual(fake.writes, [])

    def test_live_writer_refuses_inventory_without_a_saved_fingerprint(self) -> None:
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        with self.assertRaisesRegex(ORASLiveError, "No hay suficientes objetos"):
            self._writer(fake).apply(self.current, [
                PendingInventoryChange("rare-candy", "Caramelo Raro", 999),
            ])
        self.assertEqual(fake.writes, [])

    def test_live_writer_discovers_pc_base_with_two_box_witnesses(self) -> None:
        target = make_encrypted_pk6(marking=0)[:PK6_STORED_SIZE]
        companion_pid = 0x10203040
        companion = make_encrypted_pk6(pid=companion_pid, nickname="Companion")[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial,) + self.empty_slots, pc_slot=target)
        fake.memory.pop(ORAS_PC_ADDRESS)

        scan_block = (ORAS_PC_SCAN_START + 3) & ~3
        discovered_base = scan_block + 0x3000
        block = bytearray(ORAS_PC_SCAN_BLOCK_SIZE + PK6_STORED_SIZE)
        block[0x3000:0x3000 + PK6_STORED_SIZE] = target
        block[0x3000 + PK6_STORED_SIZE:0x3000 + PK6_STORED_SIZE * 2] = companion
        fake.memory[scan_block] = block

        result = self._writer(fake).apply(self.current, [
            PendingPCRoleChange(
                box=1, box_slot=1, pokemon="Poochyena", species="Poochyena",
                pokemon_identity=self._identity(), old_role="SIN ROL", new_role="Mago",
                box_witnesses=(
                    (1, self._identity()),
                    (2, f"261:{companion_pid}:12345:54321"),
                ),
            ),
        ])
        self.assertEqual(result.applied_count, 1)
        boxed = parse_pk6_boxed(
            bytes(fake.memory[scan_block][0x3000:0x3000 + PK6_STORED_SIZE]), 1, 1, {},
        )
        self.assertIsNotNone(boxed)
        assert boxed is not None
        self.assertEqual(boxed.role, "Mago")
        self.assertEqual(result.memory_watches[0].box, 1)
        self.assertEqual(result.memory_watches[0].box_slot, 1)
        self.assertEqual(
            result.memory_watches[0].address,
            discovered_base,
        )

    def test_live_writer_teaches_owned_oras_tm_without_consuming_it(self) -> None:
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        struct.pack_into("<HH", fake.memory[ORAS_TM_POUCH_ADDRESS], 0, 328, 1)
        result = self._writer(fake).apply(self.current, [
            PendingTMTeach(
                role="Líbero", pokemon_slot=1, pokemon="Poochyena", species="Poochyena",
                move_slot=4, old_move="—", old_move_id=0, new_move="Afilagarras", new_move_id=468,
                pokemon_identity=self._identity(), item_id=328, tm_number=1,
                item_name="MT01", quantity_before=1,
                inventory_witnesses=self._inventory_witnesses(tm=1),
            ),
        ])
        self.assertEqual(result.applied_count, 1)
        self.assertEqual(result.game.party[0].move_ids, [33, 44, 45, 468])
        self.assertEqual(struct.unpack_from("<HH", fake.memory[ORAS_TM_POUCH_ADDRESS], 0), (328, 1))


    def test_live_writer_teaches_oras_tm_without_any_inventory_calibration(self) -> None:
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        # Ni siquiera existe un bolsillo de MT accesible: una MT reutilizable no
        # debe necesitarlo para modificar el moveset vivo del Pokémon.
        fake.memory.pop(ORAS_TM_POUCH_ADDRESS, None)
        result = self._writer(fake).apply(self.current, [
            PendingTMTeach(
                role="Líbero", pokemon_slot=1, pokemon="Poochyena", species="Poochyena",
                move_slot=4, old_move="—", old_move_id=0, new_move="Afilagarras", new_move_id=468,
                pokemon_identity=self._identity(), item_id=328, tm_number=1,
                item_name="MT01", quantity_before=1, inventory_witnesses=(),
            ),
        ])
        self.assertEqual(result.applied_count, 1)
        self.assertEqual(result.game.party[0].move_ids, [33, 44, 45, 468])
        self.assertFalse(any(kind.startswith("pocket") for kind in [watch.kind for watch in result.memory_watches]))

    def test_live_writer_accepts_the_real_non_contiguous_mt93_item_id(self) -> None:
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        struct.pack_into("<HH", fake.memory[ORAS_TM_POUCH_ADDRESS], 0, 618, 1)
        result = self._writer(fake).apply(self.current, [
            PendingTMTeach(
                role="Líbero", pokemon_slot=1, pokemon="Poochyena", species="Poochyena",
                move_slot=4, old_move="—", old_move_id=0, new_move="Voltio Cruel", new_move_id=528,
                pokemon_identity=self._identity(), item_id=618, tm_number=93,
                item_name="MT93", quantity_before=1,
                inventory_witnesses=self._inventory_witnesses(tm=1, tm_item_id=618),
            ),
        ])
        self.assertEqual(result.applied_count, 1)
        self.assertEqual(result.game.party[0].move_ids, [33, 44, 45, 528])
        self.assertEqual(struct.unpack_from("<HH", fake.memory[ORAS_TM_POUCH_ADDRESS], 0), (618, 1))

    def test_auxiliary_verification_failure_rolls_back_inventory_before_returning_error(self) -> None:
        initial_pc = make_encrypted_pk6(marking=0)[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient((self.initial,) + self.empty_slots, pc_slot=initial_pc)
        fake.ignore_first_at.add(ORAS_PC_ADDRESS)
        with self.assertRaisesRegex(ORASLiveError, "restauró los bytes originales"):
            self._writer(fake).apply(self.current, [
                PendingInventoryChange("rare-candy", "Caramelo Raro", 999, self._inventory_witnesses()),
                PendingPCRoleChange(
                    box=1, box_slot=1, pokemon="Poochyena", species="Poochyena",
                    pokemon_identity=self._identity(), old_role="SIN ROL", new_role="Mago",
                ),
            ])
        medicine = fake.memory[ORAS_MEDICINE_POUCH_ADDRESS]
        self.assertEqual(struct.unpack_from("<HH", medicine, 4), (0, 0))
        self.assertEqual(bytes(fake.memory[ORAS_PC_ADDRESS]), initial_pc)

    def test_live_writer_swaps_party_and_pc_with_rebuilt_party_stats(self) -> None:
        incoming_pid = 0x10203040
        incoming = make_encrypted_pk6(
            species_id=263, pid=incoming_pid, nickname="Zigzagoon",
            experience=8_000, level=20, marking=0,
        )
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=incoming[:PK6_STORED_SIZE],
        )
        incoming_identity = f"263:{incoming_pid}:12345:54321"
        result = self._writer(fake).apply(self.current, [
            PendingTeamChange(
                operation="swap-party-box", party_slot=1, box=1, box_slot=1,
                outgoing_pokemon="Poochyena", outgoing_species="Poochyena",
                incoming_pokemon="Zigzagoon", incoming_species="Zigzagoon",
                incoming_role="Mago", incoming_identity=incoming_identity,
                outgoing_identity=self._identity(),
                incoming_snapshot={
                    "evs": {
                        "hp": 0, "attack": 0, "defense": 0,
                        "sp_attack": 252, "sp_defense": 0, "speed": 252,
                    },
                },
                box_witnesses=((1, incoming_identity),),
            ),
        ])

        self.assertEqual(result.applied_count, 1)
        self.assertEqual(len(fake.writes), 3)
        self.assertEqual(result.game.party[0].species_id, 263)
        self.assertEqual(result.game.party[0].role, "Mago")
        self.assertEqual(result.game.party[0].level, 20)
        boxed = parse_pk6_boxed(bytes(fake.memory[ORAS_PC_ADDRESS]), 1, 1, {})
        self.assertIsNotNone(boxed)
        assert boxed is not None
        self.assertEqual(ORASLiveWriter._pokemon_identity(boxed), self._identity())

        plain_party = decrypt_pk6(fake.slots[0])
        self.assertEqual(plain_party[0xEC], 20)
        self.assertEqual(bytes(plain_party[0x1E:0x24]), bytes((0, 0, 0, 252, 252, 0)))
        # Zigzagoon, IV 31, EV 252 en At. Esp. y Vel., naturaleza neutra, nivel 20.
        self.assertEqual(struct.unpack_from("<7H", plain_party, 0xF0), (51, 51, 23, 27, 47, 35, 27))
        self.assertEqual(len(result.memory_watches), 1)
        self.assertEqual(result.memory_watches[0].kind, "pc-team")
        self.assertEqual(result.memory_watches[0].pokemon_identity, self._identity())

    def test_live_writer_replaces_fainted_and_moves_it_to_cemetery_box(self) -> None:
        incoming_pid = 0x10203040
        incoming = make_encrypted_pk6(
            species_id=263, pid=incoming_pid, nickname="Zigzagoon",
            experience=8_000, level=20, marking=0,
        )
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=incoming[:PK6_STORED_SIZE],
        )
        graveyard_address = ORASLiveWriter._box_slot_address(4, 1)
        fake.memory[graveyard_address] = bytearray(PK6_STORED_SIZE)
        incoming_identity = f"263:{incoming_pid}:12345:54321"

        result = self._writer(fake).apply(self.current, [
            PendingTeamChange(
                operation="replace-fainted", party_slot=1, box=1, box_slot=1,
                outgoing_pokemon="Poochyena", outgoing_species="Poochyena",
                incoming_pokemon="Zigzagoon", incoming_species="Zigzagoon",
                incoming_role="Mago", incoming_identity=incoming_identity,
                outgoing_identity=self._identity(),
                box_witnesses=((1, incoming_identity),),
                graveyard_box=4, graveyard_box_slot=1,
            ),
        ])

        self.assertEqual(result.game.party[0].species_id, 263)
        self.assertEqual(result.game.party[0].role, "Mago")
        self.assertEqual(bytes(fake.memory[ORAS_PC_ADDRESS]), bytes(PK6_STORED_SIZE))
        grave = parse_pk6_boxed(bytes(fake.memory[graveyard_address]), 4, 1, {})
        self.assertIsNotNone(grave)
        assert grave is not None
        self.assertEqual(ORASLiveWriter._pokemon_identity(grave), self._identity())
        self.assertEqual({watch.kind for watch in result.memory_watches}, {"pc-empty", "pc-graveyard"})

    def test_faint_replacement_is_not_published_if_oras_reverts_after_first_confirmation(self) -> None:
        incoming_pid = 0x10203040
        incoming = make_encrypted_pk6(
            species_id=263, pid=incoming_pid, nickname="Zigzagoon",
            experience=8_000, level=20, marking=0,
        )
        initial_pc = incoming[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=initial_pc,
        )
        graveyard_address = ORASLiveWriter._box_slot_address(31, 1)
        fake.memory[graveyard_address] = bytearray(PK6_STORED_SIZE)
        incoming_identity = f"263:{incoming_pid}:12345:54321"

        def emulate_game_rebuild(_seconds: float) -> None:
            # La primera verificación ya vio la escritura. Antes de la segunda,
            # simulamos que ORAS recompone su party desde el estado interno viejo.
            fake.slots[0] = self.initial
            fake.memory[ORAS_PC_ADDRESS][:] = initial_pc
            fake.memory[graveyard_address][:] = bytes(PK6_STORED_SIZE)

        with patch("app.oras_live.time.sleep", side_effect=emulate_game_rebuild):
            with self.assertRaisesRegex(ORASLiveError, "restauró los bytes originales"):
                self._writer(fake).apply(self.current, [
                    PendingTeamChange(
                        operation="replace-fainted", party_slot=1, box=1, box_slot=1,
                        outgoing_pokemon="Poochyena", outgoing_species="Poochyena",
                        incoming_pokemon="Zigzagoon", incoming_species="Zigzagoon",
                        incoming_role="Mago", incoming_identity=incoming_identity,
                        outgoing_identity=self._identity(),
                        box_witnesses=((1, incoming_identity),),
                        graveyard_box=31, graveyard_box_slot=1,
                    ),
                ])

        self.assertEqual(fake.slots[0], self.initial)
        self.assertEqual(bytes(fake.memory[ORAS_PC_ADDRESS]), initial_pc)
        self.assertEqual(bytes(fake.memory[graveyard_address]), bytes(PK6_STORED_SIZE))

    def test_faint_replacement_refuses_occupied_graveyard_slot_without_writing(self) -> None:
        incoming_pid = 0x10203040
        incoming = make_encrypted_pk6(
            species_id=263, pid=incoming_pid, nickname="Zigzagoon", experience=8_000, level=20,
        )
        fake = _ExtendedFakeClient((self.initial,) + self.empty_slots, pc_slot=incoming[:PK6_STORED_SIZE])
        graveyard_address = ORASLiveWriter._box_slot_address(31, 1)
        fake.memory[graveyard_address] = bytearray(make_encrypted_pk6(
            species_id=261, pid=0x11111111, nickname="Occupied",
        )[:PK6_STORED_SIZE])
        incoming_identity = f"263:{incoming_pid}:12345:54321"
        with self.assertRaisesRegex(ORASLiveError, "Cementerio ya no está libre"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="replace-fainted", party_slot=1, box=1, box_slot=1,
                    outgoing_pokemon="Poochyena", incoming_pokemon="Zigzagoon",
                    incoming_role="Mago", incoming_identity=incoming_identity,
                    outgoing_identity=self._identity(), box_witnesses=((1, incoming_identity),),
                    graveyard_box=31, graveyard_box_slot=1,
                ),
            ])
        self.assertEqual(fake.writes, [])

    def test_live_team_swap_rolls_back_all_three_regions_if_stats_are_not_confirmed(self) -> None:
        incoming_pid = 0x10203040
        incoming = make_encrypted_pk6(
            species_id=263, pid=incoming_pid, nickname="Zigzagoon",
            experience=8_000, level=20,
        )
        initial_pc = incoming[:PK6_STORED_SIZE]
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=initial_pc,
        )
        fake.ignore_first_at.add(ORAS_PARTY_ADDRESS + ORAS_PARTY_STATS_OFFSET)
        incoming_identity = f"263:{incoming_pid}:12345:54321"
        with self.assertRaisesRegex(ORASLiveError, "restauró los bytes originales"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="swap-party-box", party_slot=1, box=1, box_slot=1,
                    outgoing_pokemon="Poochyena", incoming_pokemon="Zigzagoon",
                    incoming_role="Mago", incoming_identity=incoming_identity,
                    outgoing_identity=self._identity(),
                    box_witnesses=((1, incoming_identity),),
                ),
            ])
        self.assertEqual(fake.slots[0], self.initial)
        self.assertEqual(bytes(fake.memory[ORAS_PC_ADDRESS]), initial_pc)

    def test_live_team_swap_refuses_to_guess_stats_without_effective_rom_profile(self) -> None:
        incoming_pid = 0x10203040
        incoming = make_encrypted_pk6(
            species_id=263, pid=incoming_pid, nickname="Zigzagoon",
            experience=8_000, level=20,
        )
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=incoming[:PK6_STORED_SIZE],
        )
        reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: fake, stable_delay=0,
        )
        writer = ORASLiveWriter(reader, move_pp_for=lambda _move_id: 10)
        incoming_identity = f"263:{incoming_pid}:12345:54321"
        with self.assertRaisesRegex(ORASLiveError, "no aportó estadísticas personales"):
            writer.apply(self.current, [
                PendingTeamChange(
                    operation="swap-party-box", party_slot=1, box=1, box_slot=1,
                    outgoing_pokemon="Poochyena", incoming_pokemon="Zigzagoon",
                    incoming_role="Mago", incoming_identity=incoming_identity,
                    outgoing_identity=self._identity(),
                    box_witnesses=((1, incoming_identity),),
                ),
            ])
        self.assertEqual(fake.writes, [])

    def test_pc_to_pc_moves_are_a_transaction_of_their_own(self) -> None:
        """``move-box-slot`` ya tiene writer (ver ``ORASPCMoveTests``), pero
        sigue confirmándose solo: mezclarlo con otro cambio no escribe nada.
        """
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        with self.assertRaisesRegex(ORASLiveError, "transacción independiente"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="move-box-slot", party_slot=0,
                    box=1, box_slot=1, destination_box=1, destination_box_slot=5,
                    incoming_identity="261:1:12345:54321",
                ),
                PendingTeamChange(
                    operation="move-box-slot", party_slot=0,
                    box=1, box_slot=2, destination_box=1, destination_box_slot=6,
                    incoming_identity="263:2:12345:54321",
                ),
            ])
        self.assertEqual(fake.writes, [])

    def test_pc_to_pc_move_without_a_stable_identity_writes_nothing(self) -> None:
        fake = _ExtendedFakeClient(
            (self.initial,) + self.empty_slots,
            pc_slot=make_encrypted_pk6()[:PK6_STORED_SIZE],
        )
        with self.assertRaisesRegex(ORASLiveError, "identidad estable"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="move-box-slot", party_slot=0,
                    box=1, box_slot=1, destination_box=1, destination_box_slot=5,
                ),
            ])
        self.assertEqual(fake.writes, [])

    def test_experience_curves_and_nature_are_used_for_party_stats(self) -> None:
        self.assertEqual(ORASLiveWriter._level_for_experience(8_000, 0), 20)
        self.assertEqual(ORASLiveWriter._experience_for_level(50, 4), 100_000)
        self.assertEqual(ORASLiveWriter._experience_for_level(50, 5), 156_250)
        stored = bytearray(decrypt_pk6(self.initial)[:PK6_STORED_SIZE])
        struct.pack_into("<I", stored, 0x10, 8_000)
        stored[0x1C] = 3  # Firme: Ataque sube, Ataque Especial baja.
        extension = ORASLiveWriter._party_extension(
            stored, ORASPersonalStats((35, 55, 35, 35, 30, 30), 0),
        )
        self.assertEqual(extension[4], 20)
        self.assertEqual(struct.unpack_from("<7H", extension, 8), (50, 50, 36, 25, 25, 20, 23))

    def test_live_writer_compacts_pp_and_pp_ups_when_removing_move(self) -> None:
        fake = _WritableFakeClient((self.initial,) + self.empty_slots)
        result = self._writer(fake).apply(self.current, [
            PendingChange("Líbero", 1, "Poochyena", "Poochyena", 2, "Mordisco", 44, "—", 0, self._identity()),
        ])
        self.assertEqual(result.game.party[0].move_ids, [33, 45, 0, 0])
        plain = decrypt_pk6(fake.slots[0])
        self.assertEqual(list(plain[0x62:0x66]), [35, 15, 0, 0])
        self.assertEqual(list(plain[0x66:0x6A]), [2, 0, 0, 0])

    def test_stale_move_is_rejected_before_any_write(self) -> None:
        fake = _WritableFakeClient((self.initial,) + self.empty_slots)
        with self.assertRaisesRegex(ORASLiveError, "cambió ese movimiento"):
            self._writer(fake).apply(self.current, [
                PendingChange("Líbero", 1, "Poochyena", "Poochyena", 1, "Placaje", 777, "Movimiento #99", 99, self._identity()),
            ])
        self.assertEqual(fake.writes, [])

    def test_verification_failure_restores_original_pk6(self) -> None:
        fake = _WritableFakeClient((self.initial,) + self.empty_slots, ignore_first_write=True)
        with self.assertRaisesRegex(ORASLiveError, "restauró el contenido PK6 original"):
            self._writer(fake).apply(self.current, [
                PendingRoleChange(1, "Poochyena", "Poochyena", "Líbero", "Tanque", self._identity()),
            ])
        self.assertEqual(fake.slots[0], self.initial)
        self.assertEqual(len(fake.writes), 2)


class _ResizeFakeClient(_ExtendedFakeClient):
    """``_ExtendedFakeClient`` más el contador de tamaño de party de ORAS."""

    def __init__(
        self,
        slots: tuple[bytes, ...],
        *,
        count: int,
        pc_slot: bytes,
        pc_base: int = ORAS_PC_ADDRESS,
    ) -> None:
        super().__init__(slots, pc_slot=pc_slot, pc_base=pc_base)
        self.count = int(count)

    def read_memory(self, address: int, size: int):
        if address == ORAS_PARTY_COUNT_ADDRESS and size == 4:
            return struct.pack("<I", self.count)
        return super().read_memory(address, size)

    def write_memory(self, address: int, data: bytes):
        if address == ORAS_PARTY_COUNT_ADDRESS:
            if len(data) != 4:
                raise AssertionError("Escritura del contador de tamaño con longitud inesperada.")
            if address in self.ignore_first_at and address not in self._ignored_at:
                self._ignored_at.add(address)
                self.writes.append((address, bytes(data)))
                return
            self.writes.append((address, bytes(data)))
            self.count = struct.unpack("<I", data)[0]
            return
        return super().write_memory(address, data)


class ORASPartyResizeTests(unittest.TestCase):
    """``party-to-box``/``box-to-party``: el equipo cambia de tamaño de verdad.

    Hallazgo físico del 30-08-2026 (ver ``docs/CURRENT_STATE.md`` y
    ``diagnostics/manual/oras_party_size_transition_AUTO_20260830_*.json``):
    ``ORAS_PARTY_COUNT_ADDRESS`` es el contador real, pero ORAS NO compacta la
    party al depositar (a diferencia de X/Y) — el hueco se queda en su sitio.
    Estos tests usan la misma reconstrucción que ``ORASLiveReader._read_party``
    (0xE8 almacenados + 0x16 del espejo en ``ORAS_PARTY_STATS_OFFSET``): un
    slot cuenta como hueco cuando esos dos bloques están a cero.
    """

    def setUp(self) -> None:
        self.current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})
        self.personal_for = lambda species_id, _form: {
            261: ORASPersonalStats((35, 55, 35, 35, 30, 30), 0),
            263: ORASPersonalStats((38, 30, 41, 60, 30, 41), 0),
        }.get(species_id)

    def _writer(self, fake: _ResizeFakeClient) -> ORASLiveWriter:
        reader = ORASLiveReader(
            Path("does-not-exist.json"),
            client_factory=lambda: fake,
            stable_delay=0,
        )
        return ORASLiveWriter(
            reader,
            move_pp_for=lambda move_id: {33: 35, 44: 25, 45: 15}[move_id],
            personal_for=self.personal_for,
        )

    def _slot(self, *, species_id: int = 261, pid: int = 0x89ABCDEF, marking: int = 0) -> bytes:
        raw = make_encrypted_pk6(species_id=species_id, pid=pid, marking=marking)
        plain = bytearray(decrypt_pk6(raw))
        personal = self.personal_for(species_id, 0)
        plain[PK6_STORED_SIZE:] = ORASLiveWriter._party_extension(
            bytes(plain[:PK6_STORED_SIZE]), personal,
        )
        return encrypt_pk6(bytes(plain))

    @staticmethod
    def _identity(species_id: int, pid: int) -> str:
        return f"{species_id}:{pid}:12345:54321"

    def _six_full_slots(self) -> tuple[bytes, ...]:
        return tuple(self._slot(pid=0x89ABCDEF + index) for index in range(6))

    def test_party_to_box_deposits_and_decrements_count_last(self) -> None:
        slots = list(self._six_full_slots())
        outgoing_identity = self._identity(261, 0x89ABCDEF + 2)  # slot 3
        witness = make_encrypted_pk6(species_id=263, pid=0xAAAA0001)[:PK6_STORED_SIZE]
        empty_pc = bytes(PK6_STORED_SIZE)
        pc_buffer = empty_pc + witness  # box 1: slot 1 vacío, slot 2 = testigo
        fake = _ResizeFakeClient(tuple(slots), count=6, pc_slot=pc_buffer)

        result = self._writer(fake).apply(self.current, [
            PendingTeamChange(
                operation="party-to-box", party_slot=3,
                box=1, box_slot=1,
                outgoing_pokemon="Poochyena", outgoing_species="Poochyena",
                outgoing_identity=outgoing_identity,
                box_witnesses=((2, self._identity(263, 0xAAAA0001)),),
            ),
        ])

        self.assertEqual(fake.count, 5)
        self.assertEqual(len(result.game.party), 5)
        # El contador es el punto de compromiso: la última escritura.
        self.assertEqual(fake.writes[-1], (ORAS_PARTY_COUNT_ADDRESS, struct.pack("<I", 5)))
        # La party queda COMPACTA: los posteriores suben un puesto y el
        # hueco queda al FINAL, como el PK6 vacío CIFRADO canónico (idéntico
        # byte a byte al que deja el propio juego; ceros en claro se dibujan
        # como un Huevo). No es estética: con contador=5 y un hueco a mitad
        # de equipo, el visor de party del PC del juego solo pinta los
        # primeros 5 slots físicos y el sexto miembro desaparece de esa
        # vista — hallazgo físico del 31-08-2026 (Gardevoir).
        vacio = oras_empty_party_slot()
        self.assertEqual(fake.slots[0], slots[0])
        self.assertEqual(fake.slots[1], slots[1])
        for destino, origen in ((2, 3), (3, 4), (4, 5)):
            self.assertEqual(
                fake.slots[destino][:PK6_STORED_SIZE],
                slots[origen][:PK6_STORED_SIZE],
            )
            self.assertEqual(
                fake.slots[destino][PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE],
                slots[origen][PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE],
            )
        self.assertEqual(fake.slots[5][:PK6_STORED_SIZE], vacio[:PK6_STORED_SIZE])
        self.assertEqual(
            fake.slots[5][PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE],
            vacio[PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE],
        )
        # Y el propio escritor reconoce el hueco final, con la misma
        # comprobación tolerante que ya usa el resto del sistema.
        self.assertFalse(
            self._writer(fake)._party_slot_occupied(fake.slots[5], 6)
        )
        # El PC recibió al Pokémon depositado en el hueco exacto elegido.
        deposited = parse_pk6_boxed(bytes(fake.memory[ORAS_PC_ADDRESS][:PK6_STORED_SIZE]), 1, 1, {})
        self.assertEqual(deposited.species_id, 261)

    def test_party_to_box_accepts_a_pc_slot_the_game_never_touched(self) -> None:
        """El bug real del 30-08-2026: un hueco del PC que la revisión de
        ORAS/emulador nunca ha tocado puede no ser cero puro (memoria del
        emulador sin inicializar), sin ser por eso un Pokémon real.
        `parse_pk6_boxed` lo rechazaba levantando `ORASLiveError` en vez de
        devolver `None`, y eso tiraba el depósito entero con "El Pokémon del
        PC 1:1 no superó checksum/especie" — aunque el destino elegido
        estuviera perfectamente disponible para escribir.
        """
        slots = list(self._six_full_slots())
        outgoing_identity = self._identity(261, 0x89ABCDEF + 2)  # slot 3
        witness = make_encrypted_pk6(species_id=263, pid=0xAAAA0007)[:PK6_STORED_SIZE]
        untouched_pc_slot = bytes([0xAB]) * PK6_STORED_SIZE
        pc_buffer = untouched_pc_slot + witness  # box 1: slot 1 sin tocar, slot 2 = testigo
        fake = _ResizeFakeClient(tuple(slots), count=6, pc_slot=pc_buffer)

        result = self._writer(fake).apply(self.current, [
            PendingTeamChange(
                operation="party-to-box", party_slot=3,
                box=1, box_slot=1,
                outgoing_pokemon="Poochyena", outgoing_species="Poochyena",
                outgoing_identity=outgoing_identity,
                box_witnesses=((2, self._identity(263, 0xAAAA0007)),),
            ),
        ])

        self.assertEqual(fake.count, 5)
        deposited = parse_pk6_boxed(bytes(fake.memory[ORAS_PC_ADDRESS][:PK6_STORED_SIZE]), 1, 1, {})
        self.assertEqual(deposited.species_id, 261)
        self.assertEqual(len(result.game.party), 5)

    def test_party_to_box_calibra_la_matriz_desconocida_con_un_testigo(self) -> None:
        """El depósito ya no depende de que otra operación calibrara antes.

        La matriz del PC de esta partida no está en ninguna dirección conocida
        y el escritor arranca sin caché (el lector calibra la suya por su
        cuenta al pintar las cajas, pero esa no era consultada). Antes, el
        depósito abortaba SIEMPRE con «No se pudo confirmar el hueco vacío del
        PC de ORAS». Ahora se ancla en un testigo ocupado —nunca en el hueco—
        y el Pokémon cae en la casilla exacta que eligió el usuario.
        """
        unknown_base = 0x08C50000
        self.assertNotIn(unknown_base, (ORAS_PC_ADDRESS,))
        slots = list(self._six_full_slots())
        outgoing_identity = self._identity(261, 0x89ABCDEF)  # slot 1
        witness_one = make_encrypted_pk6(species_id=263, pid=0xAAAA0011)[:PK6_STORED_SIZE]
        witness_two = make_encrypted_pk6(species_id=263, pid=0xAAAA0012)[:PK6_STORED_SIZE]
        pc_buffer = bytearray(30 * PK6_STORED_SIZE)  # caja 1 completa
        pc_buffer[0:PK6_STORED_SIZE] = witness_one
        pc_buffer[PK6_STORED_SIZE:2 * PK6_STORED_SIZE] = witness_two
        fake = _ResizeFakeClient(
            tuple(slots), count=6, pc_slot=bytes(pc_buffer), pc_base=unknown_base,
        )

        result = self._writer(fake).apply(self.current, [
            PendingTeamChange(
                operation="party-to-box", party_slot=1,
                box=1, box_slot=9,
                outgoing_pokemon="Poochyena", outgoing_species="Poochyena",
                outgoing_identity=outgoing_identity,
                # Mismo orden que envía la UI: vecinos ordenados por cercanía
                # al hueco elegido, así que el ancla no es el slot 1.
                box_witnesses=(
                    (2, self._identity(263, 0xAAAA0012)),
                    (1, self._identity(263, 0xAAAA0011)),
                ),
            ),
        ])

        self.assertEqual(fake.count, 5)
        self.assertEqual(len(result.game.party), 5)
        stored = bytes(fake.memory[unknown_base])
        deposited = parse_pk6_boxed(stored[8 * PK6_STORED_SIZE:9 * PK6_STORED_SIZE], 1, 9, {})
        self.assertEqual(deposited.species_id, 261)
        # Los huecos intermedios siguen vacíos: nada se "compactó" al primero.
        for index in range(2, 8):
            self.assertEqual(
                stored[index * PK6_STORED_SIZE:(index + 1) * PK6_STORED_SIZE],
                bytes(PK6_STORED_SIZE),
            )

    def test_party_to_box_deposita_en_una_caja_completamente_vacia(self) -> None:
        """Soltar en una caja vacía: los testigos vienen de otra caja.

        Las 31 cajas son una sola tabla contigua, así que un Pokémon real de la
        caja 1 demuestra la dirección base igual de bien que un vecino. Antes,
        una caja de destino vacía no aportaba ni un testigo (``box_witnesses``
        es siempre de la misma caja) y el depósito se rechazaba sin escribir.
        El hueco vacío sigue sin servir de ancla en ningún momento.
        """
        unknown_base = 0x08C50000
        slots = list(self._six_full_slots())
        outgoing_identity = self._identity(261, 0x89ABCDEF + 5)  # slot 6
        witness_one = make_encrypted_pk6(species_id=263, pid=0xAAAA0021)[:PK6_STORED_SIZE]
        witness_two = make_encrypted_pk6(species_id=263, pid=0xAAAA0022)[:PK6_STORED_SIZE]
        # Caja 5, hueco 4 → índice 123 en la tabla contigua.
        target_index = (5 - 1) * 30 + (4 - 1)
        pc_buffer = bytearray((target_index + 1) * PK6_STORED_SIZE)
        pc_buffer[0:PK6_STORED_SIZE] = witness_one           # caja 1, hueco 1
        pc_buffer[PK6_STORED_SIZE:2 * PK6_STORED_SIZE] = witness_two  # caja 1, hueco 2
        fake = _ResizeFakeClient(
            tuple(slots), count=6, pc_slot=bytes(pc_buffer), pc_base=unknown_base,
        )

        result = self._writer(fake).apply(self.current, [
            PendingTeamChange(
                operation="party-to-box", party_slot=6,
                box=5, box_slot=4,
                outgoing_pokemon="Poochyena", outgoing_species="Poochyena",
                outgoing_identity=outgoing_identity,
                # La caja 5 está vacía: cero vecinos que aportar.
                box_witnesses=(),
                pc_anchor_witnesses=(
                    (1, 1, self._identity(263, 0xAAAA0021)),
                    (1, 2, self._identity(263, 0xAAAA0022)),
                ),
            ),
        ])

        self.assertEqual(fake.count, 5)
        self.assertEqual(len(result.game.party), 5)
        stored = bytes(fake.memory[unknown_base])
        deposited = parse_pk6_boxed(
            stored[target_index * PK6_STORED_SIZE:(target_index + 1) * PK6_STORED_SIZE], 5, 4, {},
        )
        self.assertEqual(deposited.species_id, 261)
        # Los testigos de la caja 1 siguen exactamente donde estaban.
        self.assertEqual(stored[0:PK6_STORED_SIZE], witness_one)
        self.assertEqual(stored[PK6_STORED_SIZE:2 * PK6_STORED_SIZE], witness_two)

    def test_box_to_party_incorporates_and_increments_count_last(self) -> None:
        slots = list(self._six_full_slots())
        slots[3] = bytes(PK6_PARTY_SIZE)  # slot 4 vacío
        incoming = make_encrypted_pk6(species_id=263, pid=0xAAAA0002)[:PK6_STORED_SIZE]
        fake = _ResizeFakeClient(tuple(slots), count=5, pc_slot=incoming)

        result = self._writer(fake).apply(self.current, [
            PendingTeamChange(
                operation="box-to-party", party_slot=5,
                box=1, box_slot=1,
                incoming_pokemon="Pikachu", incoming_species="Pikachu",
                incoming_identity=self._identity(263, 0xAAAA0002),
                incoming_role="Mago",
            ),
        ])

        self.assertEqual(fake.count, 6)
        self.assertEqual(len(result.game.party), 6)
        self.assertEqual(fake.writes[-1], (ORAS_PARTY_COUNT_ADDRESS, struct.pack("<I", 6)))
        incorporated = parse_pk6_party(fake.slots[3], 4, {})
        self.assertIsNotNone(incorporated)
        self.assertEqual(incorporated.species_id, 263)
        self.assertEqual(incorporated.role, "Mago")
        # El origen en el PC quedó vacío.
        self.assertEqual(fake.memory[ORAS_PC_ADDRESS][:PK6_STORED_SIZE], bytes(PK6_STORED_SIZE))
        for index in (0, 1, 2, 4, 5):
            self.assertEqual(fake.slots[index], slots[index])

    def test_a_hole_left_by_the_game_itself_still_counts_as_empty(self) -> None:
        """El bug real, encontrado el 30-08-2026 contra una partida real: al
        depositar desde el propio menú del juego (no desde RoleRun), ORAS solo
        pone a cero la cabecera del slot (constante de cifrado, centinela,
        checksum) — el resto de bytes se queda tal cual, con la especie/nivel
        de quien ocupara antes ese slot. `any(raw)` contaba ese hueco como
        "ocupado" (checksum roto pero bytes no-cero), y la precondición
        rechazaba una incorporación perfectamente válida con "El equipo vivo
        tiene 6 slot(s) ocupado(s), pero el contador de ORAS dice 5" — aunque
        la RAM real solo tuviera 5 Pokémon de verdad.
        """
        slots = list(self._six_full_slots())
        stale = bytearray(slots[2])
        stale[0:10] = bytes(10)  # cabecera a cero; el resto, basura sin limpiar
        slots[2] = bytes(stale)
        incoming = make_encrypted_pk6(species_id=263, pid=0xAAAA0006)[:PK6_STORED_SIZE]
        fake = _ResizeFakeClient(tuple(slots), count=5, pc_slot=incoming)

        result = self._writer(fake).apply(self.current, [
            PendingTeamChange(
                operation="box-to-party", party_slot=3,
                box=1, box_slot=1,
                incoming_pokemon="Pikachu", incoming_species="Pikachu",
                incoming_identity=self._identity(263, 0xAAAA0006),
                incoming_role="Mago",
            ),
        ])

        self.assertEqual(fake.count, 6)
        incorporated = parse_pk6_party(fake.slots[2], 3, {})
        self.assertIsNotNone(incorporated)
        self.assertEqual(incorporated.species_id, 263)
        self.assertEqual(len(result.game.party), 6)

    def test_party_to_box_refuses_the_last_member(self) -> None:
        slots = [self._slot()] + [bytes(PK6_PARTY_SIZE)] * 5
        fake = _ResizeFakeClient(tuple(slots), count=1, pc_slot=bytes(PK6_STORED_SIZE))

        with self.assertRaisesRegex(ORASLiveError, "al menos un Pokémon"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="party-to-box", party_slot=1, box=1, box_slot=1,
                    outgoing_identity=self._identity(261, 0x89ABCDEF),
                    box_witnesses=((2, "no-importa"),),
                ),
            ])
        self.assertEqual(fake.writes, [])
        self.assertEqual(fake.count, 1)

    def test_box_to_party_refuses_a_full_team(self) -> None:
        slots = self._six_full_slots()
        incoming = make_encrypted_pk6(species_id=263, pid=0xAAAA0003)[:PK6_STORED_SIZE]
        fake = _ResizeFakeClient(slots, count=6, pc_slot=incoming)

        with self.assertRaisesRegex(ORASLiveError, "ya tiene seis Pokémon"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="box-to-party", party_slot=7, box=1, box_slot=1,
                    incoming_identity=self._identity(263, 0xAAAA0003),
                ),
            ])
        self.assertEqual(fake.writes, [])
        self.assertEqual(fake.count, 6)

    def test_party_resize_rejects_when_count_disagrees_with_occupied_slots(self) -> None:
        """El contador dice 6, pero solo 5 slots están realmente ocupados."""
        slots = list(self._six_full_slots())
        slots[5] = bytes(PK6_PARTY_SIZE)
        fake = _ResizeFakeClient(tuple(slots), count=6, pc_slot=bytes(PK6_STORED_SIZE))

        with self.assertRaisesRegex(ORASLiveError, "contador de ORAS dice"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="party-to-box", party_slot=1, box=1, box_slot=1,
                    outgoing_identity=self._identity(261, 0x89ABCDEF),
                    box_witnesses=((2, "no-importa"),),
                ),
            ])
        self.assertEqual(fake.writes, [])

    def test_party_resize_must_be_a_solo_transaction(self) -> None:
        """Igual que X/Y: un cambio de tamaño nunca se mezcla con otra operación."""
        slots = self._six_full_slots()
        fake = _ResizeFakeClient(slots, count=6, pc_slot=bytes(PK6_STORED_SIZE))

        with self.assertRaisesRegex(ORASLiveError, "transacción independiente"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="party-to-box", party_slot=1, box=1, box_slot=1,
                    outgoing_identity=self._identity(261, 0x89ABCDEF),
                    box_witnesses=((2, "no-importa"),),
                ),
                PendingTeamChange(operation="swap-party-box", party_slot=2, box=1, box_slot=3),
            ])
        self.assertEqual(fake.writes, [])

    def test_party_to_box_without_witnesses_refuses_a_blind_write(self) -> None:
        slots = self._six_full_slots()
        fake = _ResizeFakeClient(slots, count=6, pc_slot=bytes(PK6_STORED_SIZE))

        with self.assertRaisesRegex(ORASLiveError, "testigos"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="party-to-box", party_slot=1, box=1, box_slot=1,
                    outgoing_identity=self._identity(261, 0x89ABCDEF),
                ),
            ])
        self.assertEqual(fake.writes, [])

    def test_party_to_box_rolls_back_party_pc_and_count_on_commit_failure(self) -> None:
        slots = list(self._six_full_slots())
        witness = make_encrypted_pk6(species_id=263, pid=0xAAAA0004)[:PK6_STORED_SIZE]
        pc_buffer = bytes(PK6_STORED_SIZE) + witness
        fake = _ResizeFakeClient(tuple(slots), count=6, pc_slot=pc_buffer)
        # El propio contador se "revierte" tras el primer intento: simula que
        # Azahar aceptó el byte pero el estado real no cambió.
        fake.ignore_first_at.add(ORAS_PARTY_COUNT_ADDRESS)

        with self.assertRaisesRegex(ORASLiveError, "no confirmó el nuevo contador"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="party-to-box", party_slot=1, box=1, box_slot=1,
                    outgoing_identity=self._identity(261, 0x89ABCDEF),
                    box_witnesses=((2, self._identity(263, 0xAAAA0004)),),
                ),
            ])

        self.assertEqual(fake.count, 6)
        self.assertEqual(fake.slots[0], slots[0])
        self.assertEqual(fake.memory[ORAS_PC_ADDRESS][:PK6_STORED_SIZE], bytes(PK6_STORED_SIZE))

    def test_party_to_box_rejects_if_the_game_reverts_after_the_first_confirmation(self) -> None:
        """Mismo hallazgo que motivó el segundo readback diferido de X/Y: un
        commit inmediato no basta si el juego reconstruye su propio estado
        una fracción de segundo después."""
        slots = list(self._six_full_slots())
        witness = make_encrypted_pk6(species_id=263, pid=0xAAAA0005)[:PK6_STORED_SIZE]
        pc_buffer = bytes(PK6_STORED_SIZE) + witness
        fake = _ResizeFakeClient(tuple(slots), count=6, pc_slot=pc_buffer)
        original_slot = fake.slots[0]
        original_count = fake.count
        change = PendingTeamChange(
            operation="party-to-box", party_slot=1, box=1, box_slot=1,
            outgoing_identity=self._identity(261, 0x89ABCDEF),
            box_witnesses=((2, self._identity(263, 0xAAAA0005)),),
        )

        writer = self._writer(fake)
        real_capture = writer._capture_stable_party_and_count
        calls = {"n": 0}

        def flaky_capture(client):
            calls["n"] += 1
            if calls["n"] == 3:
                # El juego "revirtió" la escritura justo antes del readback
                # diferido de asentamiento.
                client.slots[0] = original_slot
                client.count = original_count
            return real_capture(client)

        with patch.object(writer, "_capture_stable_party_and_count", flaky_capture), \
             patch("app.oras_live.time.sleep", lambda _seconds: None):
            with self.assertRaisesRegex(ORASLiveError, "contador distinto al esperado"):
                writer.apply(self.current, [change])

        self.assertEqual(fake.slots[0], original_slot)
        self.assertEqual(fake.count, original_count)


class ORASPCMoveTests(unittest.TestCase):
    """``move-box-slot``: mover un Pokémon entre dos casillas del PC de ORAS.

    Las 31 cajas son una tabla contigua de PK6 almacenados, así que origen y
    destino solo se diferencian en su índice: la caja 3 no es un caso distinto
    de la caja 1. El origen ocupado es el ancla, el destino se exige vacío, se
    escribe el destino antes de vaciar el origen y todo se verifica dos veces
    (inmediata y tras el asentamiento) con rollback.

    El "vacío" que queda en el origen NO son ceros: es el blank canónico del
    juego, cosechado del propio destino (bug físico del 31-08-2026: los ceros
    se dibujaban como un Huevo). Si no hay ningún blank legítimo a la vista
    —como en estos fixtures de ceros— se conserva el fallback histórico.
    """

    def setUp(self) -> None:
        self.current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})

    def _writer(self, fake: _ResizeFakeClient) -> ORASLiveWriter:
        reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: fake, stable_delay=0,
        )
        return ORASLiveWriter(reader, move_pp_for=lambda move_id: 35)

    @staticmethod
    def _identity(species_id: int, pid: int) -> str:
        return f"{species_id}:{pid}:12345:54321"

    @staticmethod
    def _index(box: int, slot: int) -> int:
        return (int(box) - 1) * 30 + (int(slot) - 1)

    def _party(self) -> tuple[bytes, ...]:
        return (make_encrypted_pk6(),) + (bytes(PK6_PARTY_SIZE),) * 5

    def _pc(self, occupied: dict[tuple[int, int], bytes], *, last: tuple[int, int]) -> bytearray:
        buffer = bytearray((self._index(*last) + 1) * PK6_STORED_SIZE)
        for position, raw in occupied.items():
            start = self._index(*position) * PK6_STORED_SIZE
            buffer[start:start + PK6_STORED_SIZE] = raw
        return buffer

    def _stored(self, position: bytes | bytearray, box: int, slot: int) -> bytes:
        start = self._index(box, slot) * PK6_STORED_SIZE
        return bytes(position[start:start + PK6_STORED_SIZE])

    def test_pc_move_within_a_box_copies_first_and_empties_the_source(self) -> None:
        moving = make_encrypted_pk6(species_id=261, pid=0xBBBB0001)[:PK6_STORED_SIZE]
        companion = make_encrypted_pk6(species_id=263, pid=0xBBBB0002)[:PK6_STORED_SIZE]
        pc_buffer = self._pc(
            {(2, 1): moving, (2, 2): companion}, last=(2, 15),
        )
        fake = _ResizeFakeClient(self._party(), count=1, pc_slot=bytes(pc_buffer))

        with patch("app.oras_live.time.sleep", lambda _seconds: None):
            result = self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="move-box-slot", party_slot=0,
                    box=2, box_slot=1,
                    destination_box=2, destination_box_slot=15,
                    incoming_pokemon="Poochyena", incoming_species="Poochyena",
                    incoming_identity=self._identity(261, 0xBBBB0001),
                    box_witnesses=((2, self._identity(263, 0xBBBB0002)),),
                ),
            ])

        stored = bytes(fake.memory[ORAS_PC_ADDRESS])
        self.assertEqual(self._stored(stored, 2, 15), moving)
        self.assertEqual(self._stored(stored, 2, 1), bytes(PK6_STORED_SIZE))
        self.assertEqual(self._stored(stored, 2, 2), companion)
        self.assertEqual(result.applied_count, 1)
        # El destino se escribe ANTES de vaciar el origen: ningún fallo
        # intermedio puede hacer desaparecer al Pokémon.
        written = [address for address, _data in fake.writes]
        destination_address = ORAS_PC_ADDRESS + self._index(2, 15) * PK6_STORED_SIZE
        source_address = ORAS_PC_ADDRESS + self._index(2, 1) * PK6_STORED_SIZE
        self.assertEqual(written, [destination_address, source_address])
        # La party no se toca en un movimiento PC→PC.
        self.assertEqual(fake.slots[0], self._party()[0])

    def test_pc_move_crosses_boxes(self) -> None:
        moving = make_encrypted_pk6(species_id=261, pid=0xCCCC0001)[:PK6_STORED_SIZE]
        companion = make_encrypted_pk6(species_id=263, pid=0xCCCC0002)[:PK6_STORED_SIZE]
        pc_buffer = self._pc(
            {(1, 1): moving, (1, 2): companion}, last=(3, 5),
        )
        fake = _ResizeFakeClient(self._party(), count=1, pc_slot=bytes(pc_buffer))

        with patch("app.oras_live.time.sleep", lambda _seconds: None):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="move-box-slot", party_slot=0,
                    box=1, box_slot=1,
                    destination_box=3, destination_box_slot=5,
                    incoming_pokemon="Poochyena", incoming_species="Poochyena",
                    incoming_identity=self._identity(261, 0xCCCC0001),
                    box_witnesses=((2, self._identity(263, 0xCCCC0002)),),
                ),
            ])

        stored = bytes(fake.memory[ORAS_PC_ADDRESS])
        self.assertEqual(self._stored(stored, 3, 5), moving)
        self.assertEqual(self._stored(stored, 1, 1), bytes(PK6_STORED_SIZE))
        self.assertEqual(self._stored(stored, 1, 2), companion)

    def test_pc_move_refuses_an_occupied_destination(self) -> None:
        moving = make_encrypted_pk6(species_id=261, pid=0xDDDD0001)[:PK6_STORED_SIZE]
        occupied = make_encrypted_pk6(species_id=263, pid=0xDDDD0002)[:PK6_STORED_SIZE]
        pc_buffer = self._pc({(2, 1): moving, (2, 4): occupied}, last=(2, 4))
        fake = _ResizeFakeClient(self._party(), count=1, pc_slot=bytes(pc_buffer))

        with patch("app.oras_live.time.sleep", lambda _seconds: None):
            with self.assertRaisesRegex(ORASLiveError, "ya está ocupada"):
                self._writer(fake).apply(self.current, [
                    PendingTeamChange(
                        operation="move-box-slot", party_slot=0,
                        box=2, box_slot=1,
                        destination_box=2, destination_box_slot=4,
                        incoming_pokemon="Poochyena", incoming_species="Poochyena",
                        incoming_identity=self._identity(261, 0xDDDD0001),
                        box_witnesses=((4, self._identity(263, 0xDDDD0002)),),
                    ),
                ])

        self.assertEqual(fake.writes, [])
        stored = bytes(fake.memory[ORAS_PC_ADDRESS])
        self.assertEqual(self._stored(stored, 2, 1), moving)
        self.assertEqual(self._stored(stored, 2, 4), occupied)

    def test_pc_move_restores_both_slots_when_the_game_reverts_the_write(self) -> None:
        moving = make_encrypted_pk6(species_id=261, pid=0xEEEE0001)[:PK6_STORED_SIZE]
        companion = make_encrypted_pk6(species_id=263, pid=0xEEEE0002)[:PK6_STORED_SIZE]
        pc_buffer = self._pc({(2, 1): moving, (2, 2): companion}, last=(2, 9))
        fake = _ResizeFakeClient(self._party(), count=1, pc_slot=bytes(pc_buffer))
        writer = self._writer(fake)
        source_start = self._index(2, 1) * PK6_STORED_SIZE
        destination_start = self._index(2, 9) * PK6_STORED_SIZE
        matrix = fake.memory[ORAS_PC_ADDRESS]
        reverted = {"done": False}

        def revert_during_settle(_seconds: float) -> None:
            # El asentamiento es justo donde ORAS podía reconstruir sus cajas y
            # deshacer una escritura que Azahar ya había confirmado. Ambas
            # casillas están escritas en este punto: el rollback tiene que
            # restaurar las dos.
            if reverted["done"]:
                return
            reverted["done"] = True
            matrix[destination_start:destination_start + PK6_STORED_SIZE] = bytes(PK6_STORED_SIZE)

        with patch("app.oras_live.time.sleep", revert_during_settle):
            with self.assertRaisesRegex(ORASLiveError, "restauraron"):
                writer.apply(self.current, [
                    PendingTeamChange(
                        operation="move-box-slot", party_slot=0,
                        box=2, box_slot=1,
                        destination_box=2, destination_box_slot=9,
                        incoming_pokemon="Poochyena", incoming_species="Poochyena",
                        incoming_identity=self._identity(261, 0xEEEE0001),
                        box_witnesses=((2, self._identity(263, 0xEEEE0002)),),
                    ),
                ])

        self.assertTrue(reverted["done"])
        stored = bytes(fake.memory[ORAS_PC_ADDRESS])
        self.assertEqual(self._stored(stored, 2, 1), moving)
        self.assertEqual(self._stored(stored, 2, 9), bytes(PK6_STORED_SIZE))
        self.assertEqual(self._stored(stored, 2, 2), companion)


class ORASPCSwapTests(unittest.TestCase):
    """``swap-box-slots``: intercambiar dos casillas OCUPADAS del PC.

    ``_apply_pc_move`` no cubre este caso: allí el destino tiene que estar
    libre. Aquí las dos casillas están ocupadas y las dos identidades se
    conocen, así que ambas son ancla y ninguna casilla vacía interviene en la
    calibración. Origen y destino pueden estar en cajas distintas.
    """

    def setUp(self) -> None:
        self.current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})

    def _writer(self, fake: _ResizeFakeClient) -> ORASLiveWriter:
        reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: fake, stable_delay=0,
        )
        return ORASLiveWriter(reader, move_pp_for=lambda move_id: 35)

    @staticmethod
    def _identity(species_id: int, pid: int) -> str:
        return f"{species_id}:{pid}:12345:54321"

    @staticmethod
    def _index(box: int, slot: int) -> int:
        return (int(box) - 1) * 30 + (int(slot) - 1)

    def _party(self) -> tuple[bytes, ...]:
        return (make_encrypted_pk6(),) + (bytes(PK6_PARTY_SIZE),) * 5

    def _pc(self, occupied: dict[tuple[int, int], bytes], *, last: tuple[int, int]) -> bytes:
        buffer = bytearray((self._index(*last) + 1) * PK6_STORED_SIZE)
        for position, raw in occupied.items():
            start = self._index(*position) * PK6_STORED_SIZE
            buffer[start:start + PK6_STORED_SIZE] = raw
        return bytes(buffer)

    def _stored(self, matrix, box: int, slot: int) -> bytes:
        start = self._index(box, slot) * PK6_STORED_SIZE
        return bytes(matrix[start:start + PK6_STORED_SIZE])

    def test_swap_exchanges_two_occupied_slots_of_the_same_box(self) -> None:
        first = make_encrypted_pk6(species_id=261, pid=0x11110001)[:PK6_STORED_SIZE]
        second = make_encrypted_pk6(species_id=263, pid=0x11110002)[:PK6_STORED_SIZE]
        fake = _ResizeFakeClient(
            self._party(), count=1,
            pc_slot=self._pc({(1, 1): first, (1, 2): second}, last=(1, 2)),
        )

        with patch("app.oras_live.time.sleep", lambda _seconds: None):
            result = self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="swap-box-slots", party_slot=0,
                    box=1, box_slot=2,
                    destination_box=1, destination_box_slot=1,
                    incoming_pokemon="Whismur", incoming_species="Whismur",
                    incoming_identity=self._identity(263, 0x11110002),
                    outgoing_pokemon="Poochyena", outgoing_species="Poochyena",
                    outgoing_identity=self._identity(261, 0x11110001),
                ),
            ])

        matrix = fake.memory[ORAS_PC_ADDRESS]
        self.assertEqual(self._stored(matrix, 1, 1), second)
        self.assertEqual(self._stored(matrix, 1, 2), first)
        self.assertEqual(result.applied_count, 1)
        # Ninguna casilla queda vacía en ningún momento del plan de escritura.
        self.assertNotIn(bytes(PK6_STORED_SIZE), [data for _address, data in fake.writes])

    def test_swap_crosses_boxes(self) -> None:
        first = make_encrypted_pk6(species_id=261, pid=0x22220001)[:PK6_STORED_SIZE]
        second = make_encrypted_pk6(species_id=263, pid=0x22220002)[:PK6_STORED_SIZE]
        fake = _ResizeFakeClient(
            self._party(), count=1,
            pc_slot=self._pc({(2, 3): first, (5, 20): second}, last=(5, 20)),
        )

        with patch("app.oras_live.time.sleep", lambda _seconds: None):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="swap-box-slots", party_slot=0,
                    box=2, box_slot=3,
                    destination_box=5, destination_box_slot=20,
                    incoming_pokemon="Poochyena", incoming_species="Poochyena",
                    incoming_identity=self._identity(261, 0x22220001),
                    outgoing_pokemon="Whismur", outgoing_species="Whismur",
                    outgoing_identity=self._identity(263, 0x22220002),
                ),
            ])

        matrix = fake.memory[ORAS_PC_ADDRESS]
        self.assertEqual(self._stored(matrix, 5, 20), first)
        self.assertEqual(self._stored(matrix, 2, 3), second)

    def test_swap_refuses_when_a_slot_no_longer_holds_the_dragged_pokemon(self) -> None:
        """Las dos identidades son testigos, así que una obsoleta corta antes.

        No se llega ni a leer la pareja: ninguna base candidata confirma un PC
        donde el Pokémon del destino ya no está donde decía la interfaz, y sin
        base confirmada no se escribe un solo byte.
        """
        first = make_encrypted_pk6(species_id=261, pid=0x33330001)[:PK6_STORED_SIZE]
        other = make_encrypted_pk6(species_id=263, pid=0x33339999)[:PK6_STORED_SIZE]
        fake = _ResizeFakeClient(
            self._party(), count=1,
            pc_slot=self._pc({(1, 1): first, (1, 2): other}, last=(1, 2)),
        )

        with patch("app.oras_live.time.sleep", lambda _seconds: None):
            with self.assertRaisesRegex(ORASLiveError, "No se pudo confirmar la matriz"):
                self._writer(fake).apply(self.current, [
                    PendingTeamChange(
                        operation="swap-box-slots", party_slot=0,
                        box=1, box_slot=1,
                        destination_box=1, destination_box_slot=2,
                        incoming_identity=self._identity(261, 0x33330001),
                        # El PC ya no contiene a este Pokémon en el destino.
                        outgoing_identity=self._identity(263, 0x33330002),
                    ),
                ])

        self.assertEqual(fake.writes, [])
        matrix = fake.memory[ORAS_PC_ADDRESS]
        self.assertEqual(self._stored(matrix, 1, 1), first)
        self.assertEqual(self._stored(matrix, 1, 2), other)

    def test_swap_restores_both_slots_when_the_game_reverts_the_write(self) -> None:
        first = make_encrypted_pk6(species_id=261, pid=0x44440001)[:PK6_STORED_SIZE]
        second = make_encrypted_pk6(species_id=263, pid=0x44440002)[:PK6_STORED_SIZE]
        fake = _ResizeFakeClient(
            self._party(), count=1,
            pc_slot=self._pc({(1, 1): first, (1, 2): second}, last=(1, 2)),
        )
        matrix = fake.memory[ORAS_PC_ADDRESS]
        reverted = {"done": False}

        def revert_during_settle(_seconds: float) -> None:
            # El asentamiento es donde ORAS podía reconstruir sus cajas y
            # deshacer una escritura que Azahar ya había confirmado.
            if reverted["done"]:
                return
            reverted["done"] = True
            matrix[0:PK6_STORED_SIZE] = first
            matrix[PK6_STORED_SIZE:2 * PK6_STORED_SIZE] = second

        with patch("app.oras_live.time.sleep", revert_during_settle):
            with self.assertRaisesRegex(ORASLiveError, "restauraron"):
                self._writer(fake).apply(self.current, [
                    PendingTeamChange(
                        operation="swap-box-slots", party_slot=0,
                        box=1, box_slot=1,
                        destination_box=1, destination_box_slot=2,
                        incoming_identity=self._identity(261, 0x44440001),
                        outgoing_identity=self._identity(263, 0x44440002),
                    ),
                ])

        self.assertTrue(reverted["done"])
        self.assertEqual(self._stored(matrix, 1, 1), first)
        self.assertEqual(self._stored(matrix, 1, 2), second)

    def test_swap_needs_both_identities(self) -> None:
        first = make_encrypted_pk6(species_id=261, pid=0x55550001)[:PK6_STORED_SIZE]
        second = make_encrypted_pk6(species_id=263, pid=0x55550002)[:PK6_STORED_SIZE]
        fake = _ResizeFakeClient(
            self._party(), count=1,
            pc_slot=self._pc({(1, 1): first, (1, 2): second}, last=(1, 2)),
        )

        with self.assertRaisesRegex(ORASLiveError, "identidad estable de los DOS"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="swap-box-slots", party_slot=0,
                    box=1, box_slot=1,
                    destination_box=1, destination_box_slot=2,
                    incoming_identity=self._identity(261, 0x55550001),
                ),
            ])
        self.assertEqual(fake.writes, [])

    def test_swap_is_a_transaction_of_its_own(self) -> None:
        first = make_encrypted_pk6(species_id=261, pid=0x66660001)[:PK6_STORED_SIZE]
        second = make_encrypted_pk6(species_id=263, pid=0x66660002)[:PK6_STORED_SIZE]
        fake = _ResizeFakeClient(
            self._party(), count=1,
            pc_slot=self._pc({(1, 1): first, (1, 2): second}, last=(1, 2)),
        )

        with self.assertRaisesRegex(ORASLiveError, "transacción independiente"):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="swap-box-slots", party_slot=0,
                    box=1, box_slot=1, destination_box=1, destination_box_slot=2,
                    incoming_identity=self._identity(261, 0x66660001),
                    outgoing_identity=self._identity(263, 0x66660002),
                ),
                PendingTeamChange(
                    operation="move-box-slot", party_slot=0,
                    box=1, box_slot=1, destination_box=1, destination_box_slot=5,
                    incoming_identity=self._identity(261, 0x66660001),
                ),
            ])
        self.assertEqual(fake.writes, [])


if __name__ == "__main__":
    unittest.main()


def _blank_canonico_de_pc() -> bytes:
    """Reproduce el blank con el que ORAS rellena sus huecos del PC.

    Leído de la matriz viva el 31-08-2026: cuerpo a cero salvo el mote de
    huevo localizado ("Huevo", UTF-16LE, offset 0x40) y el byte de idioma
    (0xE3 = 7, español), con su checksum coherente, todo cifrado con
    constante 0. En el juego real del usuario el checksum resultante es
    0x0B39; aquí se recalcula, no se fija, porque depende del idioma.
    """
    plain = bytearray(PK6_STORED_SIZE)
    mote = "Huevo".encode("utf-16le")
    plain[0x40:0x40 + len(mote)] = mote
    plain[0xE3] = 7
    struct.pack_into("<H", plain, 6, sum(struct.unpack_from("<112H", plain, 8)) & 0xFFFF)
    return encrypt_pk6_stored(bytes(plain))


class ORASHuecoCanonicoTests(unittest.TestCase):
    """Un hueco no son ceros: es el vacío canónico que escribe el propio juego.

    Hallazgo físico del 31-08-2026, en tres actos. (1) RoleRun dejaba ceros al
    vaciar un slot y el juego los "reparaba" al abrir cualquier menú,
    dibujando un Huevo. (2) Un depósito hecho desde el menú del juego dejó en
    la party EXACTAMENTE ``encrypt_pk6(ceros)`` —verificado byte a byte contra
    ``diagnostics/manual/oras_egg_bug_AUTO_20260831_160527.json``. (3) Los
    huecos vírgenes del PC no son ceros sino un PK6 en blanco con el mote de
    huevo localizado, así que su forma exacta depende del idioma y se cosecha
    de la matriz viva en vez de fabricarse.
    """

    def setUp(self) -> None:
        self.current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})

    # ---------- las dos formas canónicas ----------

    def test_el_vacio_de_party_es_el_pk6_cifrado_canonico(self) -> None:
        vacio = oras_empty_party_slot()
        self.assertEqual(vacio, encrypt_pk6(bytes(PK6_PARTY_SIZE)))
        reconstruido = (
            vacio[:PK6_STORED_SIZE]
            + vacio[PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE]
            + bytes(PK6_PARTY_SIZE - PK6_STORED_SIZE - ORAS_PARTY_STATS_SIZE)
        )
        self.assertIsNone(parse_pk6_party(reconstruido, 3, {}))

    def test_el_reconocedor_acepta_el_blank_y_rechaza_lo_demas(self) -> None:
        self.assertTrue(es_hueco_pc_canonico(_blank_canonico_de_pc()))
        self.assertFalse(es_hueco_pc_canonico(bytes(PK6_STORED_SIZE)))
        mon = make_encrypted_pk6(species_id=263, pid=0xAAAA0001)[:PK6_STORED_SIZE]
        self.assertFalse(es_hueco_pc_canonico(mon))
        self.assertFalse(es_hueco_pc_canonico(bytes(range(232))))

    # ---------- los vaciadores lo usan ----------

    def _writer(self, fake: _ResizeFakeClient) -> ORASLiveWriter:
        reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: fake, stable_delay=0,
        )
        return ORASLiveWriter(
            reader,
            move_pp_for=lambda move_id: 35,
            personal_for=lambda species_id, _form: {
                261: ORASPersonalStats((35, 55, 35, 35, 30, 30), 0),
                263: ORASPersonalStats((38, 30, 41, 60, 30, 41), 0),
            }.get(species_id),
        )

    @staticmethod
    def _identity(species_id: int, pid: int) -> str:
        return f"{species_id}:{pid}:12345:54321"

    def test_pc_move_devuelve_el_blank_del_destino_al_origen(self) -> None:
        """El juego no borra al mover: intercambia. RoleRun ahora también."""
        blank = _blank_canonico_de_pc()
        moving = make_encrypted_pk6(species_id=261, pid=0xBBBB0001)[:PK6_STORED_SIZE]
        companion = make_encrypted_pk6(species_id=263, pid=0xBBBB0002)[:PK6_STORED_SIZE]
        buffer = bytearray(15 * PK6_STORED_SIZE)
        buffer[0:PK6_STORED_SIZE] = moving                                   # 1:1
        buffer[PK6_STORED_SIZE:2 * PK6_STORED_SIZE] = companion              # 1:2
        buffer[14 * PK6_STORED_SIZE:] = blank                                # 1:15
        party = (make_encrypted_pk6(),) + (bytes(PK6_PARTY_SIZE),) * 5
        fake = _ResizeFakeClient(party, count=1, pc_slot=bytes(buffer))

        with patch("app.oras_live.time.sleep", lambda _seconds: None):
            self._writer(fake).apply(self.current, [
                PendingTeamChange(
                    operation="move-box-slot", party_slot=0,
                    box=1, box_slot=1,
                    destination_box=1, destination_box_slot=15,
                    incoming_pokemon="Poochyena", incoming_species="Poochyena",
                    incoming_identity=self._identity(261, 0xBBBB0001),
                    box_witnesses=((2, self._identity(263, 0xBBBB0002)),),
                ),
            ])

        stored = bytes(fake.memory[ORAS_PC_ADDRESS])
        self.assertEqual(stored[14 * PK6_STORED_SIZE:], moving)
        self.assertEqual(stored[0:PK6_STORED_SIZE], blank)

    def test_box_to_party_rellena_el_origen_con_un_blank_cosechado(self) -> None:
        blank = _blank_canonico_de_pc()
        incoming = make_encrypted_pk6(species_id=263, pid=0xAAAA0002)[:PK6_STORED_SIZE]
        buffer = bytearray(3 * PK6_STORED_SIZE)
        buffer[0:PK6_STORED_SIZE] = incoming                                 # 1:1
        buffer[2 * PK6_STORED_SIZE:] = blank                                 # 1:3
        personal = ORASPersonalStats((35, 55, 35, 35, 30, 30), 0)
        completos = []
        for index in range(6):
            raw = make_encrypted_pk6(species_id=261, pid=0x89ABCDEF + index)
            plain = bytearray(decrypt_pk6(raw))
            plain[PK6_STORED_SIZE:] = ORASLiveWriter._party_extension(
                bytes(plain[:PK6_STORED_SIZE]), personal,
            )
            completos.append(encrypt_pk6(bytes(plain)))
        completos[3] = bytes(PK6_PARTY_SIZE)  # slot 4 libre
        fake = _ResizeFakeClient(tuple(completos), count=5, pc_slot=bytes(buffer))

        self._writer(fake).apply(self.current, [
            PendingTeamChange(
                operation="box-to-party", party_slot=5,
                box=1, box_slot=1,
                incoming_pokemon="Pikachu", incoming_species="Pikachu",
                incoming_identity=self._identity(263, 0xAAAA0002),
                incoming_role="Mago",
            ),
        ])

        stored = bytes(fake.memory[ORAS_PC_ADDRESS])
        # El origen no quedó a cero: recibió el blank cosechado de la caja.
        self.assertEqual(stored[0:PK6_STORED_SIZE], blank)

    def test_los_tres_vaciadores_del_pc_cosechan_el_blank(self) -> None:
        import inspect
        for metodo in (
            ORASLiveWriter._apply_pc_move,
            ORASLiveWriter._apply_party_resize,
            ORASLiveWriter._apply_extended,
        ):
            self.assertIn(
                "_plantilla_de_hueco_pc", inspect.getsource(metodo), metodo.__name__,
            )
