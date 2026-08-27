"""Las direcciones de Blanco/Negro, derivadas de un solo ancla.

CÓMO SE DEMOSTRÓ EL ANCLA (27-08-2026)

`buscar_ancla_blanco.bat` recorrió la RAM de melonDS buscando bloques PK5 de
party creíbles —checksum válido, especie, nivel y PS posibles—. En
`0x02234974` aparecieron **cuatro seguidos separados exactamente 220 bytes**,
que es el equipo de cuatro que el usuario declaró.

Y una segunda confirmación independiente de la primera: en la dirección que
predice la resta del guardado, el dinero leído era **1624**, exactamente el que
el usuario había apuntado antes de empezar. De los diez candidatos del volcado,
solo ese predijo el dinero correcto.

LO QUE ESTAS PRUEBAS PROTEGEN

Que nadie herede una dirección de Negro 2 por parecido. Los dos juegos usan la
misma regla y números distintos.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    BAG_BASE,
    BADGES_ADDRESS,
    MONEY_ADDRESS,
    PARTY_BASE,
    PARTY_COUNT,
    PC_BASE,
    PK5_PARTY_SIZE,
)
from app.gen5_memory import GEN5_MEMORY, SAVE_PARTY_DATA  # noqa: E402

B2W2 = GEN5_MEMORY["b2w2"]
BW = GEN5_MEMORY["bw"]


# --------------------------------------------------------------------------
# La regla, contrastada contra las direcciones ya demostradas de Negro 2
# --------------------------------------------------------------------------

def test_la_regla_reproduce_todas_las_direcciones_de_negro_2() -> None:
    """Cada una se demostró por separado antes de conocerse la regla.

    Que todas encajen después no es una comprobación circular: es la prueba de
    que el bloque vivo es un espejo del guardado.
    """
    assert B2W2.party_data == PARTY_BASE
    assert B2W2.party_count == PARTY_COUNT
    assert B2W2.pc == PC_BASE
    assert B2W2.bag == BAG_BASE
    assert B2W2.money == MONEY_ADDRESS
    assert B2W2.badges == BADGES_ADDRESS


def test_el_contador_va_cuatro_bytes_antes_del_equipo() -> None:
    """La herramienta de captura leía -8 y daba el byte de cabecera."""
    assert B2W2.party_data - B2W2.party_count == 4
    assert BW.party_data - BW.party_count == 4


# --------------------------------------------------------------------------
# El ancla de Blanco
# --------------------------------------------------------------------------

def test_el_ancla_de_blanco_es_la_medida() -> None:
    assert BW.party_data == 0x02234974


def test_blanco_no_hereda_ninguna_direccion_de_negro_2() -> None:
    """Misma regla, números distintos. Copiar una habría leído basura."""
    assert BW.party_data != B2W2.party_data
    assert BW.money != B2W2.money
    assert BW.badges != B2W2.badges
    assert BW.pc != B2W2.pc
    assert BW.bag != B2W2.bag


def test_el_dinero_de_blanco_esta_donde_dice_pkhex() -> None:
    """0x21200 en el guardado, no 0x21100 como su segunda parte."""
    assert BW.save_money == 0x21200
    assert BW.save_badges == BW.save_money + 4
    assert BW.money == 0x0223CD6C


def test_las_direcciones_derivadas_de_blanco() -> None:
    assert BW.block_base == 0x0221BB6C
    assert BW.party_count == 0x02234970
    assert BW.pc == 0x0221BF6C
    assert BW.bag == 0x02233F6C
    assert BW.badges == 0x0223CD70


def test_lo_que_todavia_no_se_ha_demostrado_de_blanco() -> None:
    """El carril de batalla, que no sale de la resta ni de una sola lectura.

    La tabla de MT sí se demostró: vive en el binario del juego y se encontró
    por forma y contenido. El carril de batalla está localizado pero sin
    ordenar, y hasta saber cuál de las dos filas manda vale None: declararlo a
    ojo sería inventarlo.
    """
    assert BW.battle_presentation is None
    assert BW.battle_logical is None
    assert B2W2.battle_presentation is not None, "Negro 2 sí lo tiene demostrado"


# --------------------------------------------------------------------------
# La captura, anclada al archivo real
# --------------------------------------------------------------------------

CAPTURA = Path(__file__).resolve().parent.parent / "diagnostics" / "manual" / (
    "bw_anchor_latest.json"
)


@pytest.fixture(scope="module")
def captura():
    import json

    if not CAPTURA.exists():
        pytest.skip("No hay captura del ancla de Blanco en este equipo.")
    return json.loads(CAPTURA.read_text(encoding="utf-8"))


def test_la_captura_encontro_el_equipo_declarado(captura) -> None:
    """Cuatro PK5 seguidos separados 220 bytes, y el usuario declaró cuatro."""
    declarado = int(captura["declarado"]["equipo"])
    direcciones = [int(c["direccion"], 16) for c in captura["candidatos"][:declarado]]

    assert direcciones[0] == BW.party_data
    assert all(b - a == PK5_PARTY_SIZE for a, b in zip(direcciones, direcciones[1:]))


def test_solo_ese_candidato_predijo_el_dinero(captura) -> None:
    """La segunda confirmación, independiente de la forma del bloque."""
    dinero = captura["declarado"]["dinero"]
    aciertan = [
        c for c in captura["candidatos"]
        if c.get("prediccion", {}).get("dinero", {}).get("valor") == dinero
    ]

    assert len(aciertan) == 1
    assert int(aciertan[0]["direccion"], 16) == BW.party_data


# --------------------------------------------------------------------------
# El lector deja de estar clavado a Negro 2
# --------------------------------------------------------------------------

def _lector(clave: str):
    from app.b2w2_live import B2W2MelonDSReader

    return B2W2MelonDSReader(GEN5_MEMORY[clave])


def test_el_lector_por_defecto_sigue_siendo_negro_2() -> None:
    """Todo el código que ya existía lo construye sin argumentos."""
    from app.b2w2_live import B2W2MelonDSReader

    assert B2W2MelonDSReader().memory.key == "b2w2"


def test_el_mismo_lector_sirve_para_blanco() -> None:
    lector = _lector("bw")

    assert lector.memory.party_data == BW.party_data
    assert lector.memory.bag == BW.bag
    assert lector.memory.money == BW.money


def test_las_constantes_del_modulo_salen_del_descriptor() -> None:
    """Antes eran números sueltos y podían divergir del descriptor.

    Ahora hay una sola fuente: si alguien corrige una dirección en
    `gen5_memory`, el módulo la sigue.
    """
    import app.b2w2_live as vivo

    assert vivo.PARTY_BASE == B2W2.party_data
    assert vivo.PC_BASE == B2W2.pc
    assert vivo.MONEY_ADDRESS == B2W2.money
    assert vivo.TM_TABLE_BASE == B2W2.tm_table


def test_lo_no_demostrado_se_niega_con_su_motivo() -> None:
    """Sin esto, la lectura fallaba luego con un error que no decía nada.

    Un juego puede tener ancla y todavía no tener batalla ni MT: esas dos no
    viven en el bloque del guardado, así que no salen de la resta.
    """
    from app.b2w2_live import B2W2LiveError

    lector = _lector("bw")
    with pytest.raises(B2W2LiveError, match="no esta demostrado en Negro/Blanco"):
        lector._read_battle_rows(object())


def test_negro_2_no_niega_nada_de_eso() -> None:
    """La negativa es por juego, no una regresión que apague a todos."""
    lector = _lector("b2w2")

    assert lector._demostrada(lector.memory.tm_table, "MT") == B2W2.tm_table
    assert lector._demostrada(
        lector.memory.battle_presentation, "batalla",
    ) == B2W2.battle_presentation
    # Y Blanco tampoco niega ya la tabla de MT, que se demostró en alpha.61.
    assert _lector("bw")._demostrada(BW.tm_table, "MT") == BW.tm_table


# --------------------------------------------------------------------------
# Blanco llega hasta la interfaz
# --------------------------------------------------------------------------

def test_el_adaptador_de_blanco_se_identifica_como_suyo() -> None:
    """Dos adaptadores del mismo tipo no pueden pisarse en el registro."""
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    b2w2 = B2W2RealTimeAdapter(memory=GEN5_MEMORY["b2w2"])
    bw = B2W2RealTimeAdapter(memory=GEN5_MEMORY["bw"])

    assert (b2w2.game_key, bw.game_key) == ("b2w2", "bw")
    assert b2w2.key != bw.key
    assert "Negro 2" in b2w2.display_name and "Negro 2" not in bw.display_name


def test_sin_descriptor_el_adaptador_sigue_siendo_negro_2() -> None:
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    assert B2W2RealTimeAdapter().game_key == "b2w2"


def test_los_dos_adaptadores_conviven_en_el_registro() -> None:
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter
    from app.realtime.registry import RealTimeRegistry

    registro = RealTimeRegistry()
    registro.register(B2W2RealTimeAdapter(memory=GEN5_MEMORY["b2w2"]))
    registro.register(B2W2RealTimeAdapter(memory=GEN5_MEMORY["bw"]))

    assert registro.require("b2w2").adapter.game_key == "b2w2"
    assert registro.require("bw").adapter.game_key == "bw"


def test_cada_adaptador_consulta_la_tabla_personal_de_su_juego() -> None:
    """Blanco tiene 668 especies y Negro 2 tiene 709.

    Consultar la tabla equivocada habría dado las estadísticas de otra especie
    a partir del índice 668.
    """
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    assert B2W2RealTimeAdapter(memory=GEN5_MEMORY["bw"]).game_key == "bw"
    from app.boxed_metadata import base_stats_for

    assert base_stats_for("bw", 495) == base_stats_for("b2w2", 495), "Snivy es Snivy"
    # 700 existe en Negro 2 y no en Blanco: la tabla es más corta de verdad.
    base_stats_for("b2w2", 700)
    with pytest.raises(Exception):
        base_stats_for("bw", 700)


def test_blanco_entra_en_las_listas_de_la_interfaz() -> None:
    """Sin esto el juego se abriría pero sin tiempo real."""
    from app.ui import (
        AUTOMATIC_BADGE_GAME_KEYS,
        INSTANT_REALTIME_UI_GAME_KEYS,
        LIVE_PC_READ_GAME_KEYS,
        MELONDS_REALTIME_GAME_KEYS,
        REALTIME_READ_GAME_KEYS,
        ROLE_EV_WRITER_GAME_KEYS,
    )

    assert MELONDS_REALTIME_GAME_KEYS == {"b2w2", "bw"}
    for conjunto in (
        REALTIME_READ_GAME_KEYS, LIVE_PC_READ_GAME_KEYS,
        INSTANT_REALTIME_UI_GAME_KEYS, AUTOMATIC_BADGE_GAME_KEYS,
        ROLE_EV_WRITER_GAME_KEYS,
    ):
        assert "bw" in conjunto


def test_la_ayuda_de_blanco_no_promete_lo_que_no_tiene() -> None:
    """El carril de combate y las MT no están demostrados en Blanco."""
    from app.ui import RoleRunManager

    texto = RoleRunManager._live_runtime_help_text("bw")

    assert "no están demostrados" in texto
    assert "medallas" in texto


# --------------------------------------------------------------------------
# La lectura del PC, que es donde se coló el fallo de alpha.58
# --------------------------------------------------------------------------

def test_ningun_metodo_usa_self_sin_tenerlo() -> None:
    """El fallo de alpha.58, convertido en regla.

    Al sustituir las direcciones por `self.memory.*` una de ellas cayó dentro
    de un `@staticmethod`, que no tiene `self`. El PC dejó de leerse en los dos
    juegos y ninguna prueba se enteró, porque los dobles de melonDS sustituyen
    `read_pc` y nunca llegan a ese método.

    Esta comprobación es estructural y cubre la clase entera de error, no solo
    el caso concreto que lo destapó.
    """
    import ast

    from app import b2w2_live

    fuente = Path(b2w2_live.__file__).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    culpables = []
    for clase in [n for n in ast.walk(arbol) if isinstance(n, ast.ClassDef)]:
        for funcion in [n for n in clase.body if isinstance(n, ast.FunctionDef)]:
            primero = funcion.args.args[0].arg if funcion.args.args else None
            usa_self = any(
                isinstance(nodo, ast.Name) and nodo.id == "self"
                for nodo in ast.walk(funcion)
            )
            if usa_self and primero != "self":
                culpables.append(f"{clase.name}.{funcion.name}")

    assert culpables == []


def test_el_pc_se_lee_de_la_direccion_de_su_juego() -> None:
    """Ejercita `_read_pc_rows` de verdad, que es lo que faltaba.

    Se sustituye solo la lectura de memoria: todo lo demás —la dirección que
    pide, la doble lectura y el parseo— es el código de producción.
    """
    import struct

    from app.b2w2_live import (
        DS_RAM_BASE,
        PC_MATRIX_SIZE,
        B2W2MelonDSReader,
        B2W2PartyRead,
    )

    for clave in ("b2w2", "bw"):
        memoria = GEN5_MEMORY[clave]
        lector = B2W2MelonDSReader(memoria)
        party = B2W2PartyRead(
            process_id=1, process_name="melonDS.exe", allocation_base=0x10000000,
            count=1, raw=b"", pokemon=(),
        )
        pedidas: list[int] = []

        # Un hueco vacío no son 136 ceros: es el cifrado de esos ceros, que es
        # lo que el juego deja de verdad y lo que el parser acepta.
        from test_b2w2_v026_foundation import _pc_matrix_fixture

        matriz = _pc_matrix_fixture()

        def leer(handle, direccion, buffer, tamano, recibido, _pedidas=pedidas):
            _pedidas.append(int(direccion.value))
            buffer.raw = matriz[:tamano]
            recibido._obj.value = tamano
            return 1

        import app.b2w2_live as vivo

        class _Kernel:
            @staticmethod
            def OpenProcess(*args):
                return 99

            ReadProcessMemory = staticmethod(leer)

            @staticmethod
            def CloseHandle(*args):
                return 1

        original = vivo._KERNEL32
        vivo._KERNEL32 = _Kernel
        try:
            lectura = lector._read_pc_rows(party)
        finally:
            vivo._KERNEL32 = original

        esperada = party.allocation_base + (memoria.pc - DS_RAM_BASE)
        assert pedidas == [esperada, esperada], clave
        assert lectura.guest_base == memoria.pc
        assert lectura.empty_slots == 24 * 30 - 1
        assert [p.nickname for p in lectura.pokemon] == ["Tepig"]


# --------------------------------------------------------------------------
# La tabla de MT de Blanco
# --------------------------------------------------------------------------

CAPTURA_MT = Path(__file__).resolve().parent.parent / "diagnostics" / "manual" / (
    "bw_tm_table_latest.json"
)


@pytest.fixture(scope="module")
def captura_mt():
    import json

    if not CAPTURA_MT.exists():
        pytest.skip("No hay captura de MT de Blanco en este equipo.")
    return json.loads(CAPTURA_MT.read_text(encoding="utf-8"))


def test_la_tabla_de_mt_de_blanco_esta_demostrada() -> None:
    assert BW.tm_table == 0x0209EA88
    assert BW.tm_table != B2W2.tm_table, "no se hereda de Negro 2"


def test_solo_un_tramo_coincidio_con_la_referencia(captura_mt) -> None:
    """381 tramos tenían la forma; uno solo tenía además el contenido."""
    assert captura_mt["identicas_a_pkhex"] == [f"0x{BW.tm_table:08X}"]
    assert len(captura_mt["candidatos"]) > 100, "la forma sola no bastaba"


def test_el_tramo_bueno_coincide_en_las_ciento_una(captura_mt) -> None:
    bueno = next(
        c for c in captura_mt["candidatos"]
        if c["direccion"] == f"0x{BW.tm_table:08X}"
    )

    assert bueno["coincidencias_con_pkhex"] == 101


def test_la_batalla_de_blanco_sigue_sin_ordenarse() -> None:
    """Localizada no es lo mismo que demostrada.

    La búsqueda por firma encontró exactamente dos filas, pero cuál manda en
    pantalla solo se ve con una traza temporal: fuera de la animación las dos
    dicen lo mismo. Equivocarse adelantaría el KO a la animación, así que
    mientras no se sepa, la capacidad sigue apagada.
    """
    assert BW.battle_presentation is None
    assert BW.battle_logical is None
