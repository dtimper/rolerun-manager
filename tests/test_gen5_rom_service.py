"""Datos de juego de B2/W2 leídos de la ROM.

POR QUÉ EXISTE ESTE MÓDULO

RoleRun se juega en randomizers. Un randomizer puede cambiar las estadísticas
base de cada especie y los datos de cada movimiento. Con tablas estáticas,
aplicar un rol recalcularía las estadísticas con valores equivocados y **las
escribiría en la partida**. Es el mismo motivo por el que ORAS y X/Y leen su
ROM y Perla Reluciente su masterdata.

CÓMO SE DEMOSTRÓ EL FORMATO (27-08-2026)

Contra oráculos independientes, sobre la ROM real del usuario:

* `a/0/1/6`: 709 registros de 76 bytes. Comparados byte a byte con
  `data/pkhex_personal_b2w2.bin` coinciden en todo salvo las habilidades 2 y
  oculta, donde PKHeX rellena con la habilidad 1 los ceros de la ROM. Las
  **estadísticas base coinciden en los 709**.
* `a/0/2/1`: 560 registros de 36 bytes. Tipo (`0x00`) y PP (`0x05`) coinciden
  **559/559** con `MoveInfo.GetTypeTable/GetPPTable(Gen5)`. La categoría
  (`0x02`) separa limpiamente estado/físico/especial. Potencia (`0x03`) y
  precisión (`0x04`) coinciden con la tabla de sexta salvo donde quinta y sexta
  difieren de verdad.

Las pruebas que necesitan la ROM se saltan si no está: no se distribuye con el
proyecto. Las que fijan el contrato del formato funcionan siempre, con una ROM
sintética construida con la misma especificación.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gen5_rom_service import (  # noqa: E402
    GEN5_GAMES,
    MOVE_COUNT,
    MOVE_PATH,
    MOVE_RECORD_SIZE,
    Gen5RomError,
    discover_gen5_rom,
    load_gen5_rom_profile,
)

# El juego que estas pruebas usan como base. Blanco tiene su propia sección.
_B2W2 = GEN5_GAMES["b2w2"]
PERSONAL_PATH = _B2W2.personal_path
PERSONAL_RECORD_SIZE = _B2W2.personal_record_size
PERSONAL_COUNT = _B2W2.personal_count
B2W2RomError = Gen5RomError
discover_b2w2_rom = lambda ruta: discover_gen5_rom(ruta, "b2w2")  # noqa: E731
load_b2w2_rom_profile = load_gen5_rom_profile
from app.boxed_metadata import (  # noqa: E402
    base_stats_for,
    clear_personal_override,
    personal_override_is_active,
    set_personal_override,
)

RAIZ = Path(__file__).resolve().parent.parent
REFERENCIA_PKHEX = RAIZ / "data" / "pkhex_personal_b2w2.bin"


# --------------------------------------------------------------------------
# Una ROM sintética, construida con la misma especificación
# --------------------------------------------------------------------------

def _narc(archivos: list[bytes]) -> bytes:
    datos = b"".join(archivos)
    fatb = bytearray(b"BTAF")
    fatb += struct.pack("<II", 12 + len(archivos) * 8, len(archivos))
    posicion = 0
    for archivo in archivos:
        fatb += struct.pack("<II", posicion, posicion + len(archivo))
        posicion += len(archivo)
    btnf = b"BTNF" + struct.pack("<I", 16) + struct.pack("<IHH", 4, 0, 1)
    gmif = b"GMIF" + struct.pack("<I", 8 + len(datos)) + datos
    cuerpo = bytes(fatb) + btnf + gmif
    cabecera = b"NARC" + struct.pack("<HHIHH", 0xFFFE, 0x0100, 16 + len(cuerpo), 16, 3)
    return cabecera + cuerpo


def _rom(
    titulo: bytes = b"POKEMON B2\x00\x00",
    personal: list[bytes] | None = None,
    movimientos: list[bytes] | None = None,
) -> bytes:
    if personal is None:
        registro = bytearray(PERSONAL_RECORD_SIZE)
        registro[:6] = bytes((45, 49, 49, 45, 65, 65))
        personal = [bytes(registro)] * PERSONAL_COUNT + [b"\x00" * 1370]
    if movimientos is None:
        registro = bytearray(MOVE_RECORD_SIZE)
        registro[0x02] = 1        # físico
        registro[0x03] = 40       # potencia
        registro[0x04] = 100      # precisión
        registro[0x05] = 35       # PP
        movimientos = [bytes(registro)] * MOVE_COUNT

    contenedores = {PERSONAL_PATH: _narc(personal), MOVE_PATH: _narc(movimientos)}

    cuerpo = bytearray()
    fat = []
    for blob in contenedores.values():
        fat.append((len(cuerpo), len(cuerpo) + len(blob)))
        cuerpo += blob

    # FNT: raíz -> a -> 0 -> 1 -> 6 y a -> 0 -> 2 -> 1.
    def entrada(nombre: str, sub_id: int | None) -> bytes:
        crudo = bytes([len(nombre) | (0x80 if sub_id is not None else 0)])
        crudo += nombre.encode("ascii")
        if sub_id is not None:
            crudo += struct.pack("<H", 0xF000 | sub_id)
        return crudo

    # 0=raiz, 1=a, 2=a/0, 3=a/0/1, 4=a/0/2
    subtablas = [
        entrada("a", 1) + b"\x00",
        entrada("0", 2) + b"\x00",
        entrada("1", 3) + entrada("2", 4) + b"\x00",
        entrada("6", None) + b"\x00",
        entrada("1", None) + b"\x00",
    ]
    primer_id = [0, 0, 0, 0, 1]
    cabeceras = bytearray()
    desplazamiento = 5 * 8
    for indice, sub in enumerate(subtablas):
        cabeceras += struct.pack("<IHH", desplazamiento, primer_id[indice], 5 if indice == 0 else 0)
        desplazamiento += len(sub)
    fnt = bytes(cabeceras) + b"".join(subtablas)

    cabecera = bytearray(0x200)
    cabecera[0:12] = titulo
    cabecera[12:16] = b"IRES"
    inicio_datos = 0x200 + len(fnt) + len(fat) * 8
    struct.pack_into(
        "<4I", cabecera, 0x40,
        0x200, len(fnt), 0x200 + len(fnt), len(fat) * 8,
    )
    tabla = b"".join(
        struct.pack("<II", inicio_datos + a, inicio_datos + b) for a, b in fat
    )
    return bytes(cabecera) + fnt + tabla + bytes(cuerpo)


@pytest.fixture
def rom_sintetica(tmp_path) -> Path:
    ruta = tmp_path / "sintetica.nds"
    ruta.write_bytes(_rom())
    return ruta


# --------------------------------------------------------------------------
# El contrato del formato
# --------------------------------------------------------------------------

def test_se_lee_una_rom_bien_formada(rom_sintetica) -> None:
    perfil = load_b2w2_rom_profile(rom_sintetica)

    assert perfil.title == "POKEMON B2"
    assert perfil.game.key == "b2w2"
    assert len(perfil.personal) == PERSONAL_COUNT * PERSONAL_RECORD_SIZE
    assert len(perfil.moves) == MOVE_COUNT


def test_un_archivo_que_no_es_negro_2_se_rechaza(tmp_path) -> None:
    ruta = tmp_path / "otro.nds"
    ruta.write_bytes(_rom(titulo=b"POKEMON HG\x00\x00"))

    with pytest.raises(B2W2RomError, match="no es una ROM de quinta"):
        load_b2w2_rom_profile(ruta)


def test_un_archivo_que_no_es_una_rom_se_rechaza(tmp_path) -> None:
    ruta = tmp_path / "basura.nds"
    ruta.write_bytes(b"no soy una rom")

    with pytest.raises(B2W2RomError):
        load_b2w2_rom_profile(ruta)


def test_una_tabla_personal_con_otro_numero_de_especies_se_rechaza(tmp_path) -> None:
    registro = bytearray(PERSONAL_RECORD_SIZE)
    registro[:6] = bytes((45, 49, 49, 45, 65, 65))
    ruta = tmp_path / "corta.nds"
    ruta.write_bytes(_rom(personal=[bytes(registro)] * (PERSONAL_COUNT - 1)))

    with pytest.raises(B2W2RomError, match="709"):
        load_b2w2_rom_profile(ruta)


def test_unas_estadisticas_base_imposibles_se_rechazan(tmp_path) -> None:
    """Un cero en una estadística base significa que no es una tabla personal."""
    registro = bytearray(PERSONAL_RECORD_SIZE)
    registro[:6] = bytes((45, 49, 49, 45, 65, 65))
    roto = bytearray(registro)
    roto[1] = 0
    personal = [bytes(registro)] * PERSONAL_COUNT
    personal[7] = bytes(roto)
    ruta = tmp_path / "rota.nds"
    ruta.write_bytes(_rom(personal=personal))

    with pytest.raises(B2W2RomError, match="imposibles"):
        load_b2w2_rom_profile(ruta)


def test_una_categoria_desconocida_se_rechaza(tmp_path) -> None:
    registro = bytearray(MOVE_RECORD_SIZE)
    registro[0x02] = 7           # ni estado, ni físico, ni especial
    registro[0x05] = 10
    movimientos = [bytes(registro)] * MOVE_COUNT
    ruta = tmp_path / "rara.nds"
    ruta.write_bytes(_rom(movimientos=movimientos))

    with pytest.raises(B2W2RomError, match="categoría desconocida"):
        load_b2w2_rom_profile(ruta)


def test_la_precision_infalible_de_quinta_se_traduce_a_cero(tmp_path) -> None:
    """Quinta marca «nunca falla» con 101; RoleRun usa el cero para eso."""
    registro = bytearray(MOVE_RECORD_SIZE)
    registro[0x02] = 0
    registro[0x04] = 101
    registro[0x05] = 30
    ruta = tmp_path / "infalible.nds"
    ruta.write_bytes(_rom(movimientos=[bytes(registro)] * MOVE_COUNT))

    perfil = load_b2w2_rom_profile(ruta)

    assert perfil.accuracy(1) == 0


# --------------------------------------------------------------------------
# El descubrimiento sin preguntar
# --------------------------------------------------------------------------

def test_la_rom_se_encuentra_junto_al_guardado(tmp_path) -> None:
    """melonDS guarda la partida al lado de la ROM y con el mismo nombre."""
    (tmp_path / "partida.nds").write_bytes(_rom())
    guardado = tmp_path / "partida.sav"
    guardado.write_bytes(b"\x00" * 16)

    assert discover_b2w2_rom(guardado) == tmp_path / "partida.nds"


def test_si_el_nombre_no_coincide_se_miran_las_demas_de_la_carpeta(tmp_path) -> None:
    (tmp_path / "otra cosa.nds").write_bytes(_rom())
    guardado = tmp_path / "partida.sav"
    guardado.write_bytes(b"\x00" * 16)

    assert discover_b2w2_rom(guardado) == tmp_path / "otra cosa.nds"


def test_no_se_confunde_con_la_rom_de_otro_juego(tmp_path) -> None:
    (tmp_path / "partida.nds").write_bytes(_rom(titulo=b"POKEMON HG\x00\x00"))
    guardado = tmp_path / "partida.sav"
    guardado.write_bytes(b"\x00" * 16)

    assert discover_b2w2_rom(guardado) is None


def test_sin_guardado_no_se_busca_nada() -> None:
    assert discover_b2w2_rom("") is None
    assert discover_b2w2_rom(None) is None


# --------------------------------------------------------------------------
# La sustitución de la tabla personal
# --------------------------------------------------------------------------

def test_la_tabla_de_la_rom_sustituye_a_la_de_pkhex(rom_sintetica) -> None:
    """Es lo que impide escribir estadísticas de otra partida."""
    perfil = load_b2w2_rom_profile(rom_sintetica)
    original = base_stats_for("b2w2", 6)
    try:
        set_personal_override("b2w2", perfil.personal, PERSONAL_RECORD_SIZE)

        assert personal_override_is_active("b2w2")
        assert base_stats_for("b2w2", 6) == (45, 49, 49, 45, 65, 65)
    finally:
        clear_personal_override("b2w2")

    assert base_stats_for("b2w2", 6) == original
    assert not personal_override_is_active("b2w2")


def test_una_tabla_de_otro_tamano_de_registro_no_se_instala() -> None:
    with pytest.raises(Exception):
        set_personal_override("b2w2", b"\x00" * 100, 0x40)
    assert not personal_override_is_active("b2w2")


def test_una_tabla_truncada_no_se_instala() -> None:
    with pytest.raises(Exception):
        set_personal_override("b2w2", b"\x00" * 100, PERSONAL_RECORD_SIZE)
    assert not personal_override_is_active("b2w2")


def test_olvidar_la_tabla_no_falla_aunque_no_hubiera_ninguna() -> None:
    clear_personal_override("b2w2")
    clear_personal_override("b2w2")
    assert not personal_override_is_active("b2w2")


# --------------------------------------------------------------------------
# Contra la ROM real del usuario, si está en este equipo
# --------------------------------------------------------------------------


def _rom_real(clave: str) -> Path | None:
    base = Path("D:/Users/diego/Diego/Juegos/POKEMON ROLERUN")
    if not base.exists():
        return None
    juego = GEN5_GAMES[clave]
    for candidata in sorted(base.glob("*/*.nds")):
        try:
            if candidata.open("rb").read(12) in juego.titles:
                return candidata
        except OSError:
            continue
    return None


@pytest.fixture(scope="module")
def perfil_real():
    ruta = _rom_real("b2w2")
    if ruta is None:
        pytest.skip("La ROM de Negro 2/Blanco 2 no está en este equipo.")
    return load_b2w2_rom_profile(ruta)


def test_la_tabla_personal_real_coincide_con_pkhex(perfil_real) -> None:
    """Salvo las habilidades, que PKHeX normaliza rellenando los ceros."""
    referencia = REFERENCIA_PKHEX.read_bytes()
    assert len(perfil_real.personal) == len(referencia)

    distintas = {
        offset % PERSONAL_RECORD_SIZE
        for offset in range(len(referencia))
        if perfil_real.personal[offset] != referencia[offset]
    }
    assert distintas <= {0x19, 0x1A}, "solo pueden diferir habilidad 2 y oculta"


def test_las_estadisticas_base_reales_coinciden_en_las_709(perfil_real) -> None:
    referencia = REFERENCIA_PKHEX.read_bytes()
    for indice in range(PERSONAL_COUNT):
        inicio = indice * PERSONAL_RECORD_SIZE
        assert perfil_real.personal[inicio:inicio + 6] == referencia[inicio:inicio + 6]


def test_los_pp_reales_coinciden_con_pkhex_en_los_559(perfil_real) -> None:
    import json

    tabla = json.loads(
        (RAIZ / "data" / "b2w2_move_pp.json").read_text(encoding="utf-8-sig")
    )["pp"]
    for move_id in range(1, 560):
        assert perfil_real.base_pp(move_id) == int(tabla[str(move_id)]), move_id


@pytest.mark.parametrize(
    ("move_id", "categoria", "potencia", "precision"),
    [
        (53, "special", 95, 100),    # Lanzallamas: 95 en quinta, 90 desde sexta
        (56, "special", 120, 80),    # Hidrobomba: 120 en quinta, 110 desde sexta
        (89, "physical", 100, 100),  # Terremoto
        (14, "status", 0, 0),        # Danza Espada: infalible
    ],
)
def test_los_datos_reales_son_los_de_quinta(
    perfil_real, move_id, categoria, potencia, precision,
) -> None:
    """La ROM corrige valores que la tabla de sexta tenía mal para quinta."""
    assert perfil_real.damage_class(move_id) == categoria
    assert perfil_real.power(move_id) == potencia
    assert perfil_real.accuracy(move_id) == precision


# --------------------------------------------------------------------------
# Lo que cambia de verdad cuando hay ROM: curar, enseñar y filtrar por rol
# --------------------------------------------------------------------------

class _RomFalsa:
    """ROM randomizada de mentira, con la interfaz que consume RoleRun."""

    name = "randomizada.nds"

    def __init__(self, categorias=None, pps=None, potencias=None) -> None:
        self.categorias = dict(categorias or {})
        self.pps = dict(pps or {})
        self.potencias = dict(potencias or {})

    def damage_class(self, move_id: int) -> str:
        return self.categorias.get(int(move_id), "unknown")

    def base_pp(self, move_id: int) -> int:
        return int(self.pps.get(int(move_id), 0))

    def power(self, move_id: int) -> int:
        return int(self.potencias.get(int(move_id), 0))

    def accuracy(self, move_id: int) -> int:
        return 100


def test_los_pp_de_curar_y_ensenar_salen_de_la_rom() -> None:
    """Curar con el PP original dejaría el PP mal escrito en la partida."""
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    rom = _RomFalsa(pps={53: 3})
    adaptador = B2W2RealTimeAdapter(reader=object(), rom_getter=lambda: rom)

    assert adaptador.base_pp_for(53) == 3, "manda la ROM"
    assert adaptador.base_pp_for(89) == 10, "sin dato en la ROM, la tabla de quinta"


def test_sin_rom_los_pp_siguen_siendo_los_de_quinta() -> None:
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    adaptador = B2W2RealTimeAdapter(reader=object())

    assert adaptador.base_pp_for(53) == 15


def test_el_perfil_de_mt_incorpora_los_datos_de_la_rom() -> None:
    from app.b2w2_tm_service import build_tm_profile, reference_move_ids

    rom = _RomFalsa(categorias={53: "physical"}, pps={53: 3}, potencias={53: 250})
    perfil = build_tm_profile(reference_move_ids(), source="prueba", rom=rom)

    assert perfil.damage_class(53) == "physical", "randomizada a físico"
    assert perfil.base_pp(53) == 3
    assert perfil.power(53) == 250


def test_sin_rom_el_perfil_no_afirma_una_categoria() -> None:
    """Mejor «no lo sé» que una categoría de la quinta original.

    La interfaz ya sabe caer a su propio catálogo cuando recibe «unknown».
    """
    from app.b2w2_tm_service import build_tm_profile, reference_move_ids

    perfil = build_tm_profile(reference_move_ids(), source="prueba")

    assert perfil.damage_class(53) == "unknown"


def test_la_categoria_para_filtrar_por_rol_sale_de_la_rom() -> None:
    """Es lo que decide si una MT se le ofrece a un Mago o a un Asesino."""
    from types import SimpleNamespace

    from app.ui import RoleRunManager

    manager = SimpleNamespace(
        _get_bdsp_tm_profile=lambda prompt=False: None,
        _get_b2w2_rom_profile=lambda: _RomFalsa(categorias={53: "physical"}),
        engine=SimpleNamespace(damage_class=lambda mid: "special"),
    )

    assert RoleRunManager._damage_class_for_move(manager, 53) == "physical"


def test_sin_rom_la_categoria_cae_al_catalogo_de_siempre() -> None:
    from types import SimpleNamespace

    from app.ui import RoleRunManager

    manager = SimpleNamespace(
        _get_bdsp_tm_profile=lambda prompt=False: None,
        _get_b2w2_rom_profile=lambda: None,
        engine=SimpleNamespace(damage_class=lambda mid: "special"),
    )

    assert RoleRunManager._damage_class_for_move(manager, 53) == "special"


def test_no_se_lee_la_rom_entera(tmp_path, monkeypatch) -> None:
    """Una ROM de B2/W2 son 512 MiB y la instantaneidad es objetivo del proyecto.

    Leerla entera para consultar unos kilobytes congelaría la interfaz la
    primera vez, sobre todo en un disco lento. Se leen la cabecera, la FNT, la
    FAT y los dos contenedores, y nada más.
    """
    import pathlib

    ruta = tmp_path / "grande.nds"
    crudo = bytearray(_rom())
    crudo += b"\x00" * (8 * 1024 * 1024)     # relleno, como el resto del cartucho
    ruta.write_bytes(bytes(crudo))

    leidos = 0
    abrir_original = pathlib.Path.open

    class _Contador:
        def __init__(self, archivo):
            self._archivo = archivo

        def read(self, *args):
            nonlocal leidos
            datos = self._archivo.read(*args)
            leidos += len(datos)
            return datos

        def __getattr__(self, nombre):
            return getattr(self._archivo, nombre)

        def __enter__(self):
            self._archivo.__enter__()
            return self

        def __exit__(self, *args):
            return self._archivo.__exit__(*args)

    def abrir(self, *args, **kwargs):
        return _Contador(abrir_original(self, *args, **kwargs))

    monkeypatch.setattr(pathlib.Path, "open", abrir)

    perfil = load_b2w2_rom_profile(ruta)

    assert len(perfil.moves) == MOVE_COUNT
    assert leidos < len(crudo) // 4, f"se leyeron {leidos} de {len(crudo)} bytes"


# --------------------------------------------------------------------------
# Blanco/Negro: mismo lector, descriptor distinto
# --------------------------------------------------------------------------

_BW = GEN5_GAMES["bw"]


def test_blanco_y_negro_2_no_comparten_tabla_personal() -> None:
    """No es una copia con otro nombre: los registros son de otro tamaño.

    Comprobado contra las dos ROM reales: B2/W2 usa 709 especies de 0x4C y
    B/W 668 de 0x3C. Asumirlo igual habría dado estadísticas de otra especie.
    """
    assert _BW.personal_record_size == 0x3C
    assert _B2W2.personal_record_size == 0x4C
    assert _BW.personal_count == 668
    assert _B2W2.personal_count == 709


def test_la_tabla_de_movimientos_si_es_la_misma() -> None:
    """560 registros de 36 bytes en ambos, en la misma ruta."""
    assert MOVE_PATH == "a/0/2/1"
    assert (MOVE_COUNT, MOVE_RECORD_SIZE) == (560, 0x24)


def test_cada_juego_declara_sus_dos_titulos() -> None:
    """Un cartucho se identifica por su título, que no depende del idioma."""
    assert b"POKEMON B2\x00\x00" in _B2W2.titles
    assert b"POKEMON W2\x00\x00" in _B2W2.titles
    assert b"POKEMON B\x00\x00\x00" in _BW.titles
    assert b"POKEMON W\x00\x00\x00" in _BW.titles
    assert not (_BW.titles & _B2W2.titles), "ningún título puede valer para los dos"


@pytest.fixture(scope="module")
def perfil_bw():
    ruta = _rom_real("bw")
    if ruta is None:
        pytest.skip("La ROM de Blanco/Negro no está en este equipo.")
    return load_gen5_rom_profile(ruta, "bw")


def test_la_tabla_personal_de_blanco_coincide_con_pkhex(perfil_bw) -> None:
    """Salvo las habilidades, que PKHeX normaliza rellenando los ceros."""
    referencia = (RAIZ / "data" / "pkhex_personal_bw.bin").read_bytes()
    assert len(perfil_bw.personal) == len(referencia)

    tamano = _BW.personal_record_size
    distintas = {
        offset % tamano
        for offset in range(len(referencia))
        if perfil_bw.personal[offset] != referencia[offset]
        # El registro cero es un hueco que la ROM graba más corto.
        and offset >= tamano
    }
    assert distintas <= {0x19, 0x1A}, "solo pueden diferir habilidad 2 y oculta"


def test_las_estadisticas_base_de_blanco_coinciden_en_las_668(perfil_bw) -> None:
    referencia = (RAIZ / "data" / "pkhex_personal_bw.bin").read_bytes()
    tamano = _BW.personal_record_size
    for indice in range(_BW.personal_count):
        inicio = indice * tamano
        assert perfil_bw.personal[inicio:inicio + 6] == referencia[inicio:inicio + 6]


def test_los_movimientos_de_blanco_son_los_mismos_que_los_de_negro_2(perfil_bw) -> None:
    """Comprobado byte a byte: la tabla de movimientos no cambió entre ambos."""
    ruta = _rom_real("b2w2")
    if ruta is None:
        pytest.skip("La ROM de Negro 2 no está en este equipo.")
    perfil_b2w2 = load_gen5_rom_profile(ruta, "b2w2")

    assert perfil_bw.moves == perfil_b2w2.moves


def test_una_rom_del_juego_equivocado_se_rechaza() -> None:
    """Cargar Blanco donde toca Negro 2 daría estadísticas de otra tabla."""
    ruta = _rom_real("bw")
    if ruta is None:
        pytest.skip("La ROM de Blanco/Negro no está en este equipo.")

    with pytest.raises(Gen5RomError, match="hace falta"):
        load_gen5_rom_profile(ruta, "b2w2")


def test_el_descubrimiento_distingue_los_dos_juegos(tmp_path) -> None:
    (tmp_path / "partida.nds").write_bytes(_rom(titulo=b"POKEMON B2\x00\x00"))
    guardado = tmp_path / "partida.sav"
    guardado.write_bytes(b"\x00" * 16)

    assert discover_gen5_rom(guardado, "b2w2") == tmp_path / "partida.nds"
    assert discover_gen5_rom(guardado, "bw") is None
    assert discover_gen5_rom(guardado) == tmp_path / "partida.nds"
