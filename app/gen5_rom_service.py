from __future__ import annotations

"""Datos de juego de quinta generación, leídos de la ROM.

POR QUÉ HACE FALTA LEER LA ROM

RoleRun se juega en randomizers. Un randomizer puede cambiar las estadísticas
base de cada especie y los datos de cada movimiento. Con tablas estáticas,
RoleRun mostraría datos falsos y —mucho peor— al aplicar un rol recalcularía
las estadísticas del Pokémon con valores equivocados y **las escribiría en la
partida**.

QUÉ COMPARTEN BLANCO/NEGRO Y BLANCO 2/NEGRO 2, Y QUÉ NO

Comprobado contra las ROM reales del usuario el 27-08-2026, no supuesto:

* La **tabla de movimientos** (`a/0/2/1`) es **idéntica byte a byte** en los dos
  juegos: 560 registros de 36 bytes. Tipo y PP coinciden 559/559 con
  `MoveInfo.GetTypeTable/GetPPTable(Gen5)` de PKHeX.
* La **tabla personal** (`a/0/1/6`) **no**: B2/W2 usa registros de 0x4C y 709
  especies; B/W usa registros de 0x3C y 668. Por eso hay un descriptor por
  juego en lugar de una constante compartida.

En ambos, comparada con la copia de PKHeX, la tabla coincide en **todo** salvo
las habilidades 2 y oculta, donde PKHeX rellena con la habilidad 1 los ceros que
la ROM deja. Las **estadísticas base coinciden en todas las especies**.

No escribe nunca la ROM, el guardado ni la RAM del emulador.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .nds_rom import NdsRomError, open_nds, read_title

MOVE_PATH = "a/0/2/1"
MOVE_RECORD_SIZE = 0x24
MOVE_COUNT = 560

# Desplazamientos dentro del registro de movimiento, demostrados uno a uno
# contra PKHeX y contra la tabla de sexta generación.
_MOVE_TYPE = 0x00
_MOVE_CATEGORY = 0x02
_MOVE_POWER = 0x03
_MOVE_ACCURACY = 0x04
_MOVE_PP = 0x05

_CATEGORIES = {0: "status", 1: "physical", 2: "special"}


class Gen5RomError(ValueError):
    """El archivo no permite obtener datos de juego demostrados."""


@dataclass(frozen=True, slots=True)
class Gen5Game:
    """Lo que distingue a un juego de quinta de su pareja.

    Todo lo demás —sistema de archivos, NARC, formato del registro de
    movimiento— es común y vive fuera de aquí.
    """

    key: str
    label: str
    titles: frozenset[bytes]
    personal_path: str
    personal_record_size: int
    personal_count: int


GEN5_GAMES: dict[str, Gen5Game] = {
    "b2w2": Gen5Game(
        key="b2w2",
        label="Negro 2/Blanco 2",
        titles=frozenset({b"POKEMON B2\x00\x00", b"POKEMON W2\x00\x00"}),
        personal_path="a/0/1/6",
        personal_record_size=0x4C,
        personal_count=709,
    ),
    "bw": Gen5Game(
        key="bw",
        label="Negro/Blanco",
        # El título del cartucho rellena hasta doce bytes; Blanco y Negro dejan
        # más ceros que sus segundas partes porque su nombre es más corto.
        titles=frozenset({b"POKEMON B\x00\x00\x00", b"POKEMON W\x00\x00\x00"}),
        personal_path="a/0/1/6",
        personal_record_size=0x3C,
        personal_count=668,
    ),
}


@dataclass(frozen=True, slots=True)
class Gen5Move:
    type_id: int
    category: str
    power: int
    accuracy: int
    pp: int


@dataclass(frozen=True, slots=True)
class Gen5RomProfile:
    source: Path
    game: Gen5Game
    game_code: str
    title: str
    # El bloque personal crudo, en el mismo formato que las copias de
    # `data/pkhex_personal_*.bin`, para poder sustituirlas tal cual.
    personal: bytes
    moves: tuple[Gen5Move, ...]

    @property
    def name(self) -> str:
        return self.source.name

    def __str__(self) -> str:
        return self.source.name

    def move(self, move_id: int) -> Gen5Move | None:
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


def _parse_personal(archivos: list[bytes], juego: Gen5Game) -> bytes:
    tamano = juego.personal_record_size
    # El primer registro es un hueco y algunas ROM lo graban más corto que los
    # demás. Se rellena en vez de descartarlo: si no, todas las especies se
    # desplazarían una posición.
    registros = [a.ljust(tamano, b"\x00") for a in archivos if len(a) <= tamano]
    if len(registros) != juego.personal_count:
        raise Gen5RomError(
            f"La tabla personal de {juego.label} declara {len(registros)} especies "
            f"y no {juego.personal_count}."
        )
    bloque = b"".join(registros)
    # Una tabla con estadísticas base imposibles no es una tabla personal. El
    # registro cero es el hueco y va a propósito a ceros.
    for indice in range(1, juego.personal_count):
        crudo = bloque[indice * tamano:(indice + 1) * tamano]
        if any(not 1 <= valor <= 255 for valor in crudo[:6]):
            raise Gen5RomError(
                f"La tabla personal de {juego.label} declara estadísticas "
                f"imposibles en la especie #{indice}."
            )
    return bloque


def _parse_moves(archivos: list[bytes], juego: Gen5Game) -> tuple[Gen5Move, ...]:
    if len(archivos) != MOVE_COUNT:
        raise Gen5RomError(
            f"La tabla de movimientos de {juego.label} declara {len(archivos)} "
            f"entradas y no {MOVE_COUNT}."
        )
    movimientos: list[Gen5Move] = []
    for indice, crudo in enumerate(archivos):
        if len(crudo) != MOVE_RECORD_SIZE:
            raise Gen5RomError(
                f"El movimiento #{indice} no mide {MOVE_RECORD_SIZE} bytes."
            )
        categoria = _CATEGORIES.get(crudo[_MOVE_CATEGORY])
        if categoria is None:
            raise Gen5RomError(
                f"El movimiento #{indice} declara una categoría desconocida "
                f"({crudo[_MOVE_CATEGORY]})."
            )
        pp = crudo[_MOVE_PP]
        if indice and pp <= 0:
            raise Gen5RomError(f"El movimiento #{indice} declara cero PP.")
        # Quinta marca «infalible» con 101 (148 movimientos lo usan). El resto
        # de RoleRun trata el cero como «no aplicable», así que se traduce aquí
        # en lugar de enseñar una precisión del 101 %.
        precision = crudo[_MOVE_ACCURACY]
        if precision > 100:
            precision = 0
        movimientos.append(Gen5Move(
            type_id=crudo[_MOVE_TYPE],
            category=categoria,
            power=crudo[_MOVE_POWER],
            accuracy=precision,
            pp=pp,
        ))
    return tuple(movimientos)


def game_for_title(titulo: bytes) -> Gen5Game | None:
    """Qué juego de quinta es este cartucho, si lo es."""
    for juego in GEN5_GAMES.values():
        if titulo in juego.titles:
            return juego
    return None


def load_gen5_rom_profile(path, game_key: str | None = None) -> Gen5RomProfile:
    """Lee la ROM y publica sus datos de juego, o falla sin publicar nada.

    Sin ``game_key`` se acepta cualquier juego de quinta; con él, solo ese.
    """
    ruta = Path(path)
    try:
        rom = open_nds(ruta)
    except NdsRomError as exc:
        raise Gen5RomError(str(exc)) from exc

    juego = game_for_title(rom.title)
    legible = rom.title.decode("ascii", "replace").rstrip("\x00")
    if juego is None:
        raise Gen5RomError(
            f"{ruta.name} no es una ROM de quinta generación (dice «{legible}»)."
        )
    if game_key is not None and juego.key != game_key:
        esperado = GEN5_GAMES[game_key].label
        raise Gen5RomError(
            f"{ruta.name} es {juego.label} y aquí hace falta {esperado}."
        )

    try:
        personal = _parse_personal(rom.narc(juego.personal_path), juego)
        movimientos = _parse_moves(rom.narc(MOVE_PATH), juego)
    except NdsRomError as exc:
        raise Gen5RomError(str(exc)) from exc

    return Gen5RomProfile(
        source=ruta,
        game=juego,
        game_code=rom.game_code,
        title=legible,
        personal=personal,
        moves=movimientos,
    )


@lru_cache(maxsize=8)
def _cached_profile(ruta: str, game_key: str | None, mtime: int, tamano: int) -> Gen5RomProfile:
    del mtime, tamano       # forman parte de la clave: una ROM nueva se relee
    return load_gen5_rom_profile(ruta, game_key)


def load_gen5_rom_profile_cached(path, game_key: str | None = None) -> Gen5RomProfile:
    """Igual que ``load_gen5_rom_profile``, cacheando por ruta y contenido.

    Si el archivo cambia —otra randomización sobre el mismo nombre—, la fecha o
    el tamaño cambian con él y se relee.
    """
    ruta = Path(path)
    try:
        info = ruta.stat()
    except OSError as exc:
        raise Gen5RomError(f"No se pudo leer {ruta.name}.") from exc
    return _cached_profile(
        str(ruta.resolve()), game_key, int(info.st_mtime), int(info.st_size),
    )


def discover_gen5_rom(save_path, game_key: str | None = None) -> Path | None:
    """Busca la ROM a partir del guardado que la Run tiene abierto.

    melonDS guarda la partida junto a la ROM y con el mismo nombre, así que el
    caso normal se resuelve sin preguntarle nada al usuario. Si ese archivo no
    está o no es del juego que toca, se prueban las demás ROM de la carpeta.
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
            juego = game_for_title(read_title(candidato))
        except NdsRomError:
            continue
        if juego is not None and (game_key is None or juego.key == game_key):
            return candidato
    return None
