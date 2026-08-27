from __future__ import annotations

"""Lectura validada de los datos de juego de Pokémon Negro 2 y Blanco 2.

POR QUÉ HACE FALTA LEER LA ROM

RoleRun se juega en randomizers. Un randomizer no solo cambia qué enseña cada
MT: puede cambiar las **estadísticas base** de cada especie y los datos de cada
movimiento (tipo, categoría, potencia, precisión, PP). Con tablas estáticas,
RoleRun mostraría datos falsos y —mucho peor— al aplicar un rol recalcularía
las estadísticas del Pokémon con valores equivocados y **las escribiría en la
partida**.

Es exactamente lo que ya hacen los juegos terminados: ORAS y X/Y leen su ROM,
y Perla Reluciente su masterdata. Este módulo hace lo mismo con el archivo
`.nds` que melonDS tiene cargado.

CÓMO SE LOCALIZA CADA COSA, Y CÓMO SE COMPRUEBA

Nada se supone. El 27-08-2026 se contrastó la ROM real del usuario contra
oráculos independientes:

* Tabla personal (`a/0/1/6`): 709 registros de 76 bytes. Comparada byte a byte
  con `data/pkhex_personal_b2w2.bin`, coincide en **todo** salvo dos bytes por
  registro —las habilidades 2 y oculta—, donde PKHeX rellena con la habilidad 1
  los huecos que la ROM deja a cero. Las **estadísticas base coinciden en los
  709 registros**.
* Tabla de movimientos (`a/0/2/1`): 560 registros de 36 bytes.
  - Tipo en `0x00`: **559/559** coinciden con `MoveInfo.GetTypeTable(Gen5)`.
  - PP en `0x05`: **559/559** coinciden con `MoveInfo.GetPPTable(Gen5)`.
  - Categoría en `0x02`: separa limpiamente las tres categorías conocidas
    (0 estado, 1 físico, 2 especial) sobre los 826 movimientos catalogados.
  - Potencia en `0x03` y precisión en `0x04`: coinciden con la tabla de sexta
    generación **salvo donde quinta y sexta difieren de verdad** (Lanzallamas
    95→90, Hidrobomba 120→110, Píncers 14/85→25/95…). O sea: la ROM corrige
    datos que la tabla estática tenía mal para quinta.

No escribe nunca la ROM, el guardado ni la RAM del emulador.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import struct

_NDS_HEADER_SIZE = 0x200
_TITLE_OFFSET = 0x00
_GAME_CODE_OFFSET = 0x0C
_FNT_OFFSET = 0x40
# Los dos títulos de la pareja, tal y como los graba el cartucho. No dependen
# del idioma; el código de juego sí.
_B2W2_TITLES = {b"POKEMON B2\x00\x00", b"POKEMON W2\x00\x00"}

PERSONAL_PATH = "a/0/1/6"
MOVE_PATH = "a/0/2/1"
PERSONAL_RECORD_SIZE = 0x4C
PERSONAL_COUNT = 709
MOVE_RECORD_SIZE = 0x24
MOVE_COUNT = 560

# Desplazamientos dentro del registro de movimiento, demostrados uno a uno.
_MOVE_TYPE = 0x00
_MOVE_CATEGORY = 0x02
_MOVE_POWER = 0x03
_MOVE_ACCURACY = 0x04
_MOVE_PP = 0x05

_CATEGORIES = {0: "status", 1: "physical", 2: "special"}

# Ningún bloque legítimo de los que se leen se acerca a esto. Un valor mayor
# significa que la ROM está corrupta, no que haya que reservar 3 GiB.
_MAX_BLOCK = 64 * 1024 * 1024

_NARC_MAGIC = b"NARC"
_FATB_MAGICS = {b"BTAF", b"FATB"}
_GMIF_MAGICS = {b"GMIF", b"FIMG"}


class B2W2RomError(ValueError):
    """El archivo no permite obtener datos de juego demostrados."""


@dataclass(frozen=True, slots=True)
class B2W2Move:
    type_id: int
    category: str
    power: int
    accuracy: int
    pp: int


@dataclass(frozen=True, slots=True)
class B2W2RomProfile:
    source: Path
    game_code: str
    title: str
    # El bloque personal crudo, en el mismo formato que
    # `data/pkhex_personal_b2w2.bin`, para que pueda sustituirlo tal cual.
    personal: bytes
    moves: tuple[B2W2Move, ...]

    @property
    def name(self) -> str:
        return self.source.name

    def __str__(self) -> str:
        return self.source.name

    def move(self, move_id: int) -> B2W2Move | None:
        move_id = int(move_id)
        if not 0 <= move_id < len(self.moves):
            return None
        return self.moves[move_id]

    def damage_class(self, move_id: int) -> str:
        move = self.move(move_id)
        return move.category if move is not None else "unknown"

    def base_pp(self, move_id: int) -> int:
        move = self.move(move_id)
        return int(move.pp) if move is not None else 0

    def power(self, move_id: int) -> int:
        move = self.move(move_id)
        return int(move.power) if move is not None else 0

    def accuracy(self, move_id: int) -> int:
        move = self.move(move_id)
        return int(move.accuracy) if move is not None else 0


# --------------------------------------------------------------------------
# Sistema de archivos de una ROM de Nintendo DS
# --------------------------------------------------------------------------

def _read_paths(fnt: bytes, fat_raw: bytes) -> dict[str, tuple[int, int]]:
    """Resuelve nombre → (inicio, fin) recorriendo la FNT y la FAT.

    Recibe los dos bloques ya leídos, no la ROM entera: una ROM de B2/W2 son
    512 MiB, y leerlos todos para consultar unos kilobytes congelaría la
    interfaz la primera vez —justo lo contrario del objetivo de instantaneidad.
    """
    if not fat_raw or len(fat_raw) % 8:
        raise B2W2RomError("La tabla de archivos de la ROM no es válida.")
    total = len(fat_raw) // 8
    fat = [struct.unpack_from("<II", fat_raw, index * 8) for index in range(total)]

    rutas: dict[str, tuple[int, int]] = {}
    visitados: set[int] = set()

    def recorrer(directorio: int, prefijo: str) -> None:
        if directorio in visitados:
            raise B2W2RomError("El árbol de directorios de la ROM se repite.")
        visitados.add(directorio)
        entrada = directorio * 8
        if entrada + 8 > len(fnt):
            raise B2W2RomError("La FNT de la ROM apunta fuera de la tabla.")
        sub_offset, primer_id, _padre = struct.unpack_from("<IHH", fnt, entrada)
        puntero = sub_offset
        file_id = primer_id
        while True:
            if puntero >= len(fnt):
                raise B2W2RomError("La FNT de la ROM quedó truncada.")
            tipo = fnt[puntero]
            puntero += 1
            if tipo == 0:
                return
            longitud = tipo & 0x7F
            nombre = fnt[puntero:puntero + longitud].decode("ascii", "replace")
            puntero += longitud
            if tipo & 0x80:
                sub_id = struct.unpack_from("<H", fnt, puntero)[0] & 0x0FFF
                puntero += 2
                recorrer(sub_id, f"{prefijo}{nombre}/")
                continue
            if file_id < total:
                rutas[f"{prefijo}{nombre}"] = fat[file_id]
            file_id += 1

    recorrer(0, "")
    if not rutas:
        raise B2W2RomError("La ROM no declara ningún archivo con nombre.")
    return rutas


def _read_narc(blob: bytes) -> list[bytes]:
    """Extrae los archivos de un contenedor NARC."""
    if blob[:4] != _NARC_MAGIC:
        raise B2W2RomError("El contenedor no empieza por NARC.")
    header_size, bloques = struct.unpack_from("<HH", blob, 0x0C)
    puntero = header_size
    fatb = gmif = None
    for _ in range(bloques):
        if puntero + 8 > len(blob):
            raise B2W2RomError("Un bloque del NARC queda fuera del contenedor.")
        magic = blob[puntero:puntero + 4]
        tamano = struct.unpack_from("<I", blob, puntero + 4)[0]
        if tamano <= 0:
            raise B2W2RomError("Un bloque del NARC declara tamaño cero.")
        if magic in _FATB_MAGICS:
            fatb = puntero
        elif magic in _GMIF_MAGICS:
            gmif = puntero
        puntero += tamano
    if fatb is None or gmif is None:
        raise B2W2RomError("Al NARC le falta la tabla de archivos o los datos.")

    total = struct.unpack_from("<I", blob, fatb + 8)[0]
    base = gmif + 8
    archivos: list[bytes] = []
    for index in range(total):
        inicio, fin = struct.unpack_from("<II", blob, fatb + 12 + index * 8)
        if base + fin > len(blob) or fin < inicio:
            raise B2W2RomError("El NARC apunta a datos fuera del contenedor.")
        archivos.append(blob[base + inicio:base + fin])
    return archivos


# --------------------------------------------------------------------------
# El perfil
# --------------------------------------------------------------------------

def _parse_personal(archivos: list[bytes]) -> bytes:
    registros = [f for f in archivos if len(f) == PERSONAL_RECORD_SIZE]
    if len(registros) != PERSONAL_COUNT:
        raise B2W2RomError(
            f"La tabla personal declara {len(registros)} especies y no {PERSONAL_COUNT}."
        )
    bloque = b"".join(registros)
    # Una tabla con estadísticas base imposibles no es una tabla personal.
    for indice in range(1, PERSONAL_COUNT):
        crudo = bloque[indice * PERSONAL_RECORD_SIZE:(indice + 1) * PERSONAL_RECORD_SIZE]
        if any(not 1 <= valor <= 255 for valor in crudo[:6]):
            raise B2W2RomError(
                f"La tabla personal declara estadísticas imposibles en la especie #{indice}."
            )
    return bloque


def _parse_moves(archivos: list[bytes]) -> tuple[B2W2Move, ...]:
    if len(archivos) != MOVE_COUNT:
        raise B2W2RomError(
            f"La tabla de movimientos declara {len(archivos)} entradas y no {MOVE_COUNT}."
        )
    movimientos: list[B2W2Move] = []
    for indice, crudo in enumerate(archivos):
        if len(crudo) != MOVE_RECORD_SIZE:
            raise B2W2RomError(
                f"El movimiento #{indice} no mide {MOVE_RECORD_SIZE} bytes."
            )
        categoria = _CATEGORIES.get(crudo[_MOVE_CATEGORY])
        if categoria is None:
            raise B2W2RomError(
                f"El movimiento #{indice} declara una categoría desconocida "
                f"({crudo[_MOVE_CATEGORY]})."
            )
        pp = crudo[_MOVE_PP]
        if indice and pp <= 0:
            raise B2W2RomError(f"El movimiento #{indice} declara cero PP.")
        # Quinta generación marca «infalible» con 101 (148 movimientos lo usan:
        # Danza Espada, Rayo Confuso, Paz Mental…). El resto de RoleRun trata el
        # cero como «no aplicable», así que se traduce aquí en lugar de enseñar
        # una precisión del 101 %.
        precision = crudo[_MOVE_ACCURACY]
        if precision > 100:
            precision = 0
        movimientos.append(B2W2Move(
            type_id=crudo[_MOVE_TYPE],
            category=categoria,
            power=crudo[_MOVE_POWER],
            accuracy=precision,
            pp=pp,
        ))
    return tuple(movimientos)


def load_b2w2_rom_profile(path) -> B2W2RomProfile:
    """Lee la ROM y publica sus datos de juego, o falla sin publicar nada.

    Solo toca lo que necesita: cabecera, FNT, FAT y los dos contenedores. De los
    512 MiB de una ROM de B2/W2 se leen unos cientos de kilobytes, así que la
    primera consulta no se nota aunque el archivo esté en un disco lento.
    """
    ruta = Path(path)
    try:
        with ruta.open("rb") as archivo:
            def leer(desplazamiento: int, tamano: int) -> bytes:
                if tamano <= 0 or tamano > _MAX_BLOCK:
                    raise B2W2RomError("La ROM declara un bloque de tamaño imposible.")
                archivo.seek(int(desplazamiento))
                crudo = archivo.read(int(tamano))
                if len(crudo) != tamano:
                    raise B2W2RomError(f"{ruta.name} quedó truncada.")
                return crudo

            cabecera = leer(0, _NDS_HEADER_SIZE)
            titulo = cabecera[_TITLE_OFFSET:_TITLE_OFFSET + 12]
            if titulo not in _B2W2_TITLES:
                legible = titulo.decode("ascii", "replace").rstrip("\x00")
                raise B2W2RomError(
                    f"{ruta.name} no es una ROM de Negro 2/Blanco 2 (dice «{legible}»)."
                )

            fnt_offset, fnt_size, fat_offset, fat_size = struct.unpack_from(
                "<4I", cabecera, _FNT_OFFSET,
            )
            rutas = _read_paths(leer(fnt_offset, fnt_size), leer(fat_offset, fat_size))
            for nombre in (PERSONAL_PATH, MOVE_PATH):
                if nombre not in rutas:
                    raise B2W2RomError(f"La ROM no contiene {nombre}.")

            inicio, fin = rutas[PERSONAL_PATH]
            personal = _parse_personal(_read_narc(leer(inicio, fin - inicio)))
            inicio, fin = rutas[MOVE_PATH]
            movimientos = _parse_moves(_read_narc(leer(inicio, fin - inicio)))
    except OSError as exc:
        raise B2W2RomError(f"No se pudo leer {ruta.name}.") from exc

    return B2W2RomProfile(
        source=ruta,
        game_code=cabecera[_GAME_CODE_OFFSET:_GAME_CODE_OFFSET + 4].decode("ascii", "replace"),
        title=titulo.decode("ascii", "replace").rstrip("\x00"),
        personal=personal,
        moves=movimientos,
    )


@lru_cache(maxsize=4)
def _cached_profile(ruta: str, mtime: int, tamano: int) -> B2W2RomProfile:
    del mtime, tamano       # forman parte de la clave: una ROM nueva se relee
    return load_b2w2_rom_profile(ruta)


def load_b2w2_rom_profile_cached(path) -> B2W2RomProfile:
    """Igual que ``load_b2w2_rom_profile``, cacheando por ruta y contenido.

    La ROM son cientos de MiB. Releerla en cada apertura de la pantalla de MT
    sería una pausa perceptible, y la instantaneidad es un objetivo del
    proyecto. Si el archivo cambia —otra randomización sobre el mismo nombre—,
    la fecha o el tamaño cambian con él y se relee.
    """
    ruta = Path(path)
    try:
        info = ruta.stat()
    except OSError as exc:
        raise B2W2RomError(f"No se pudo leer {ruta.name}.") from exc
    return _cached_profile(str(ruta.resolve()), int(info.st_mtime), int(info.st_size))


def discover_b2w2_rom(save_path) -> Path | None:
    """Busca la ROM a partir del guardado que la Run tiene abierto.

    melonDS guarda la partida junto a la ROM y con el mismo nombre, así que el
    caso normal se resuelve sin preguntarle nada al usuario. Si ese archivo no
    está o no es Negro 2/Blanco 2, se prueban las demás ROM de la carpeta.
    """
    if not save_path:
        return None
    guardado = Path(save_path)
    try:
        carpeta = guardado.parent
        candidatos = [guardado.with_suffix(".nds")]
        candidatos.extend(
            sorted(p for p in carpeta.glob("*.nds") if p not in candidatos)
        )
    except OSError:
        return None
    for candidato in candidatos:
        try:
            with candidato.open("rb") as archivo:
                titulo = archivo.read(12)
        except OSError:
            continue
        if titulo in _B2W2_TITLES:
            return candidato
    return None
