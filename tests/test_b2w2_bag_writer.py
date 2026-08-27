"""Utilidades de la cabecera en B2/W2: mochila y dinero.

Las direcciones no se suponen. La mochila se fijó con la traza de dos estados
del 27-08-2026 y sus fronteras coinciden byte a byte con PKHeX (ver
`test_b2w2_bag_reader.py`). El dinero salió de la misma traza: de **dos**
candidatos iniciales, `0x022266A4` fue el único que pasó de 4524 a 4224 al
gastar dinero dentro del juego.

El identificador de cada utilidad tampoco se supone: sale de la misma tabla de
PKHeX que ya acertó con la mochila real del usuario (Poción 17, Poké Ball 4,
MT21 348), y el bolsillo sale del reparto extraído de `SAV5B2W2.Inventory`.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    BAG_BASE,
    BAG_SLOT_SIZE,
    DS_RAM_BASE,
    MONEY_ADDRESS,
    MONEY_MAX,
    MONEY_SIZE,
    B2W2BagRead,
    B2W2LiveError,
    B2W2MelonDSReader,
    B2W2PartyRead,
    bag_pocket_for,
    bag_pockets,
    bag_size,
    parse_bag,
    set_bag_quantity,
)
from app.boxed_metadata import item_name  # noqa: E402

CARAMELO_RARO = 50
REPELENTE_MAXIMO = 77
# La mochila real del usuario en la traza, la misma que valida el lector.
MOCHILA_REAL = {
    "Items": [(4, 3), (57, 1)],
    "KeyItems": [(621, 1), (437, 1), (442, 1)],
    "TMHMs": [(348, 1)],
    "Medicine": [(17, 3), (22, 2)],
    "Berries": [],
}


def _construir(contenido: dict[str, list[tuple[int, int]]]) -> bytes:
    crudo = bytearray(bag_size())
    for pocket in bag_pockets():
        for indice, (item_id, cantidad) in enumerate(contenido.get(pocket.tipo, [])):
            struct.pack_into(
                "<HH", crudo, pocket.offset + indice * BAG_SLOT_SIZE, item_id, cantidad,
            )
    return bytes(crudo)


# --------------------------------------------------------------------------
# Qué objeto es cada utilidad de la cabecera
# --------------------------------------------------------------------------

def test_las_utilidades_apuntan_a_los_objetos_que_dicen() -> None:
    """En BDSP una utilidad rotulada Repelente Máximo tocó el Repelente normal."""
    assert item_name(CARAMELO_RARO) == "Caramelo Raro"
    assert item_name(REPELENTE_MAXIMO) == "Repelente Máximo"


def test_cada_utilidad_cae_en_el_bolsillo_del_reparto_de_pkhex() -> None:
    assert bag_pocket_for(CARAMELO_RARO).tipo == "Medicine"
    assert bag_pocket_for(REPELENTE_MAXIMO).tipo == "Items"


def test_un_objeto_sin_bolsillo_no_se_escribe_a_ciegas() -> None:
    with pytest.raises(B2W2LiveError, match="no pertenece"):
        bag_pocket_for(60000)


# --------------------------------------------------------------------------
# La colocación dentro del bolsillo
# --------------------------------------------------------------------------

def test_un_objeto_nuevo_se_anade_detras_del_ultimo() -> None:
    """Un hueco por delante rompería el compactado que el juego espera."""
    resultado = set_bag_quantity(_construir(MOCHILA_REAL), CARAMELO_RARO, 999)

    medicinas = [e for e in parse_bag(resultado) if e.pocket == "Medicine"]
    assert [(e.slot, e.item_id, e.quantity) for e in medicinas] == [
        (0, 17, 3), (1, 22, 2), (2, CARAMELO_RARO, 999),
    ]


def test_un_objeto_que_ya_estaba_solo_cambia_de_cantidad() -> None:
    partida = _construir({**MOCHILA_REAL, "Medicine": [(17, 3), (CARAMELO_RARO, 4), (22, 2)]})

    resultado = set_bag_quantity(partida, CARAMELO_RARO, 999)

    medicinas = [e for e in parse_bag(resultado) if e.pocket == "Medicine"]
    assert [(e.slot, e.item_id, e.quantity) for e in medicinas] == [
        (0, 17, 3), (1, CARAMELO_RARO, 999), (2, 22, 2),
    ], "no se reordena la mochila del jugador para meter una utilidad"


def test_los_demas_bolsillos_no_se_tocan() -> None:
    partida = _construir(MOCHILA_REAL)
    resultado = set_bag_quantity(partida, CARAMELO_RARO, 999)

    medicinas = bag_pocket_for(CARAMELO_RARO)
    for pocket in bag_pockets():
        if pocket.tipo == medicinas.tipo:
            continue
        fin = pocket.offset + pocket.slots * BAG_SLOT_SIZE
        assert resultado[pocket.offset:fin] == partida[pocket.offset:fin], pocket.tipo


def test_el_repelente_maximo_entra_en_su_propio_bolsillo() -> None:
    resultado = set_bag_quantity(_construir(MOCHILA_REAL), REPELENTE_MAXIMO, 999)

    objetos = [e for e in parse_bag(resultado) if e.pocket == "Items"]
    assert [(e.slot, e.item_id, e.quantity) for e in objetos] == [
        (0, 4, 3), (1, 57, 1), (2, REPELENTE_MAXIMO, 999),
    ]


@pytest.mark.parametrize("cantidad", [0, 1000, -1])
def test_una_cantidad_imposible_no_llega_a_la_partida(cantidad: int) -> None:
    with pytest.raises(B2W2LiveError):
        set_bag_quantity(_construir(MOCHILA_REAL), CARAMELO_RARO, cantidad)


def test_ningun_bolsillo_real_puede_desbordarse() -> None:
    """Cada bolsillo tiene al menos tantos huecos como objetos legales.

    Como el juego agrupa cada objeto en un solo hueco, esto significa que
    ninguna mochila válida puede quedarse sin sitio. El desbordamiento del
    bolsillo siguiente no es un riesgo que dependa del writer.
    """
    for pocket in bag_pockets():
        assert pocket.slots >= len(pocket.legal), pocket.tipo


def test_aun_asi_un_bolsillo_sin_sitio_se_rechaza(monkeypatch) -> None:
    """La comprobación existe igualmente: nunca se escribe fuera del bolsillo."""
    import app.b2w2_live as vivo

    real = bag_pocket_for(CARAMELO_RARO)
    estrecho = type(real)(
        tipo=real.tipo, offset=real.offset, slots=2, legal=real.legal,
    )
    monkeypatch.setattr(vivo, "bag_pocket_for", lambda item_id: estrecho)

    # Las dos medicinas del jugador ya ocupan los dos únicos huecos.
    with pytest.raises(B2W2LiveError, match="lleno"):
        set_bag_quantity(_construir(MOCHILA_REAL), CARAMELO_RARO, 999)


def test_una_mochila_de_partida_incoherente_no_se_pisa() -> None:
    """Si no se está leyendo una mochila, tampoco se escribe una."""
    roto = bytearray(_construir(MOCHILA_REAL))
    medicinas = bag_pocket_for(CARAMELO_RARO)
    struct.pack_into("<HH", roto, medicinas.offset, 0, 0)   # descompactado

    with pytest.raises(B2W2LiveError, match="compactado"):
        set_bag_quantity(bytes(roto), CARAMELO_RARO, 999)


# --------------------------------------------------------------------------
# El contrato transaccional
# --------------------------------------------------------------------------

class _FakeMelonDS(B2W2MelonDSReader):
    """melonDS simulado: guarda la mochila y el dinero en memoria."""

    def __init__(self, mochila: bytes, dinero: int = 4224) -> None:
        super().__init__()
        self.memoria = bytearray(mochila)
        self.dinero = int(dinero).to_bytes(MONEY_SIZE, "little")
        self.escrituras: list[tuple[int, int]] = []
        # Cuántas escrituras seguidas pisa el juego. Con 1 se corrompe la
        # escritura pero el rollback llega limpio, que es el caso normal.
        self.pisadas_pendientes = 0

    party = B2W2PartyRead(
        process_id=42, process_name="melonDS.exe", allocation_base=0x10000000,
        count=1, raw=b"", pokemon=(),
    )

    def read_party(self) -> B2W2PartyRead:
        return self.party

    def read_bag(self, party_read=None) -> B2W2BagRead:
        crudo = bytes(self.memoria)
        return B2W2BagRead(
            self.party.process_id, self.party.process_name,
            self.party.allocation_base, BAG_BASE, crudo, parse_bag(crudo),
        )

    def _read_guest_twice(self, lectura, guest: int, tamano: int) -> bytes:
        assert guest == MONEY_ADDRESS and tamano == MONEY_SIZE
        return bytes(self.dinero)

    def _write_process_bytes(self, process_id: int, host_address: int, payload: bytes) -> None:
        self.escrituras.append((host_address, len(payload)))
        # Simula que el juego pisa la escritura entre escribir y releer.
        pisada = self.pisadas_pendientes > 0
        self.pisadas_pendientes = max(0, self.pisadas_pendientes - 1)
        base = self.party.allocation_base
        if host_address == base + (BAG_BASE - DS_RAM_BASE):
            self.memoria = bytearray(payload)
            if pisada:
                struct.pack_into("<HH", self.memoria, bag_pocket_for(CARAMELO_RARO).offset, 17, 1)
            return
        if host_address == base + (MONEY_ADDRESS - DS_RAM_BASE):
            self.dinero = (7).to_bytes(MONEY_SIZE, "little") if pisada else bytes(payload)
            return
        raise AssertionError(f"escritura en una direccion no prevista: 0x{host_address:X}")


def _lector(dinero: int = 4224) -> _FakeMelonDS:
    return _FakeMelonDS(_construir(MOCHILA_REAL), dinero)


def test_la_mochila_se_escribe_y_se_verifica() -> None:
    lector = _lector()

    despues = lector.write_bag_items(lector.party, [(CARAMELO_RARO, 999)])

    assert despues.quantity_of(CARAMELO_RARO) == 999
    assert despues.quantity_of(17) == 3, "las pociones del jugador siguen ahí"
    assert len(lector.escrituras) == 1


def test_dos_utilidades_entran_como_una_sola_transaccion() -> None:
    lector = _lector()

    despues = lector.write_bag_items(
        lector.party, [(CARAMELO_RARO, 999), (REPELENTE_MAXIMO, 999)],
    )

    assert despues.quantity_of(CARAMELO_RARO) == 999
    assert despues.quantity_of(REPELENTE_MAXIMO) == 999
    assert len(lector.escrituras) == 1, "un único bloque, no una escritura por objeto"


def test_si_ya_tenia_esa_cantidad_no_se_escribe_un_solo_byte() -> None:
    lector = _FakeMelonDS(
        set_bag_quantity(_construir(MOCHILA_REAL), CARAMELO_RARO, 999),
    )

    lector.write_bag_items(lector.party, [(CARAMELO_RARO, 999)])

    assert lector.escrituras == []


def test_un_readback_que_no_coincide_deja_la_mochila_como_estaba() -> None:
    lector = _lector()
    original = bytes(lector.memoria)
    lector.pisadas_pendientes = 1

    with pytest.raises(B2W2LiveError, match="readback"):
        lector.write_bag_items(lector.party, [(CARAMELO_RARO, 999)])

    assert bytes(lector.memoria) == original


def test_un_rollback_que_tampoco_se_confirma_avisa_de_no_guardar() -> None:
    """Si ni siquiera se puede restaurar, el usuario tiene que enterarse."""
    lector = _lector()
    lector.pisadas_pendientes = 2

    with pytest.raises(B2W2LiveError, match="no guardes"):
        lector.write_bag_items(lector.party, [(CARAMELO_RARO, 999)])


def test_dos_peticiones_del_mismo_objeto_se_rechazan() -> None:
    lector = _lector()

    with pytest.raises(B2W2LiveError, match="mismo objeto"):
        lector.write_bag_items(lector.party, [(CARAMELO_RARO, 5), (CARAMELO_RARO, 999)])

    assert lector.escrituras == []


def test_melonds_reiniciado_a_media_transaccion_se_detecta() -> None:
    lector = _lector()
    otra_party = B2W2PartyRead(
        process_id=99, process_name="melonDS.exe", allocation_base=0x10000000,
        count=1, raw=b"", pokemon=(),
    )

    with pytest.raises(B2W2LiveError, match="cambio antes"):
        lector.write_bag_items(otra_party, [(CARAMELO_RARO, 999)])

    assert lector.escrituras == []


# --------------------------------------------------------------------------
# El dinero
# --------------------------------------------------------------------------

def test_la_direccion_del_dinero_es_la_que_demostro_la_traza() -> None:
    """4524 -> 4224 en esta posición, de 2 candidatos iniciales."""
    assert MONEY_ADDRESS == 0x022266A4


def test_el_dinero_se_lee_como_entero_de_cuatro_bytes() -> None:
    assert _lector(4524).read_money() == 4524


def test_el_dinero_se_escribe_y_se_verifica() -> None:
    lector = _lector(4224)

    assert lector.write_money(lector.party, MONEY_MAX) == MONEY_MAX
    assert int.from_bytes(lector.dinero, "little") == MONEY_MAX


def test_si_ya_tenia_ese_dinero_no_se_escribe_un_solo_byte() -> None:
    lector = _lector(MONEY_MAX)

    lector.write_money(lector.party, MONEY_MAX)

    assert lector.escrituras == []


def test_un_readback_de_dinero_que_no_coincide_restaura_el_saldo() -> None:
    lector = _lector(4224)
    lector.pisadas_pendientes = 1

    with pytest.raises(B2W2LiveError, match="readback"):
        lector.write_money(lector.party, MONEY_MAX)

    assert int.from_bytes(lector.dinero, "little") == 4224


@pytest.mark.parametrize("cantidad", [MONEY_MAX + 1, 9_999_999, -1])
def test_un_saldo_sin_demostrar_no_se_escribe(cantidad: int) -> None:
    lector = _lector(4224)

    with pytest.raises(B2W2LiveError, match="maximo"):
        lector.write_money(lector.party, cantidad)

    assert lector.escrituras == []


# --------------------------------------------------------------------------
# El adaptador traduce las utilidades de la cabecera
# --------------------------------------------------------------------------

def _cambio(item_key: str, item_name_ui: str, cantidad: int):
    from app.models import PendingInventoryChange

    return PendingInventoryChange(
        item_key=item_key, item_name=item_name_ui, quantity=cantidad,
    )


def test_el_adaptador_traduce_cada_utilidad_a_su_objeto() -> None:
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    traducir = B2W2RealTimeAdapter._utility_item_for
    assert traducir(_cambio("rare-candy", "Caramelo Raro", 999)) == CARAMELO_RARO
    assert traducir(_cambio("max-repel", "Repelente Máximo", 999)) == REPELENTE_MAXIMO


def test_un_rotulo_que_no_case_con_el_objeto_no_se_escribe() -> None:
    """Exactamente el fallo de BDSP alpha.85: el rótulo decía otra cosa."""
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    with pytest.raises(B2W2LiveError, match="Repelente"):
        B2W2RealTimeAdapter._utility_item_for(_cambio("max-repel", "Repelente", 999))


def test_una_utilidad_sin_objeto_demostrado_se_rechaza() -> None:
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    with pytest.raises(B2W2LiveError, match="no tiene objeto demostrado"):
        B2W2RealTimeAdapter._utility_item_for(_cambio("master-ball", "Master Ball", 1))


def test_el_adaptador_aplica_objetos_y_dinero_en_la_misma_pasada() -> None:
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    lector = _lector(4224)
    adaptador = B2W2RealTimeAdapter(reader=lector)
    adaptador._capture = lambda current, sequence: type(  # type: ignore[method-assign]
        "Cap", (), {"game": type("G", (), {"raw": {}})(), "process": None},
    )()

    resultado = adaptador._apply_inventory(None, [
        _cambio("rare-candy", "Caramelo Raro", 999),
        _cambio("max-repel", "Repelente Máximo", 999),
        _cambio("money-max", "Dinero", MONEY_MAX),
    ])

    mochila = lector.read_bag()
    assert mochila.quantity_of(CARAMELO_RARO) == 999
    assert mochila.quantity_of(REPELENTE_MAXIMO) == 999
    assert int.from_bytes(lector.dinero, "little") == MONEY_MAX
    assert resultado.applied_count == 3


def test_un_saldo_por_encima_del_tope_no_pasa_por_el_adaptador() -> None:
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    lector = _lector(4224)
    adaptador = B2W2RealTimeAdapter(reader=lector)

    with pytest.raises(B2W2LiveError, match="máximo"):
        adaptador._apply_inventory(None, [_cambio("money-max", "Dinero", 9_999_999)])

    assert lector.escrituras == []


# --------------------------------------------------------------------------
# Las compuertas de la interfaz
# --------------------------------------------------------------------------

def test_la_compuerta_ya_admite_las_utilidades_en_b2w2() -> None:
    from types import SimpleNamespace

    from app.ui import RoleRunManager

    ui = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    utilidad = _cambio("rare-candy", "Caramelo Raro", 999)

    assert RoleRunManager._oras_live_unsupported_changes(ui, [utilidad]) == []


def test_una_utilidad_llega_a_la_auto_aplicacion() -> None:
    from types import SimpleNamespace

    from app.ui import RoleRunManager

    utilidad = _cambio("money-max", "Dinero", MONEY_MAX)
    manager = SimpleNamespace(
        _active_azahar_realtime_key=lambda: "b2w2",
        run=SimpleNamespace(pending_changes=[utilidad]),
        _oras_live_auto_apply_available=lambda: True,
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda *args, **kwargs: None,
        save_engine=SimpleNamespace(key="b2w2"),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [utilidad])

    assert manager._oras_live_auto_apply_ids == {id(utilidad)}


def test_sin_melonds_sincronizado_no_queda_nada_pendiente() -> None:
    """B2/W2 solo tiene writer vivo.

    Encolar sin él dejaría el cambio pendiente para siempre, y el monitor vivo
    exige la cola vacía para leer: es la congelación que cerró alpha.27.
    """
    from types import SimpleNamespace

    from app.ui import RoleRunManager

    avisos: list[tuple[str, bool]] = []
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="b2w2"),
        _oras_live_active=False,
        run=SimpleNamespace(pending_changes=[]),
        _show_live_sync_toast=lambda titulo, cuerpo, ok: avisos.append((titulo, ok)),
    )

    RoleRunManager.queue_inventory_change(manager, "rare-candy", "Caramelo Raro", 999)

    assert manager.run.pending_changes == []
    assert avisos and avisos[0][1] is False
    assert "MELONDS" in avisos[0][0]


def test_el_tope_de_dinero_que_ofrece_la_interfaz_es_el_demostrado() -> None:
    from app.ui import RoleRunManager

    assert RoleRunManager._inventory_money_max_for_engine("b2w2") == MONEY_MAX
