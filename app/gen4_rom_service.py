from __future__ import annotations

"""Datos de juego de cuarta generación, leídos de la ROM.

POR QUÉ HACE FALTA LEER LA ROM

Lo mismo que en quinta: RoleRun se juega en randomizers, y con tablas estáticas
recalcularía las estadísticas al aplicar un rol con valores falsos y **las
escribiría en la partida**. La ROM es la única fuente que dice la verdad sobre
la partida que se está jugando.

QUÉ CAMBIA RESPECTO A QUINTA — comprobado contra las ROM del usuario el
27-08-2026, no supuesto:

* La tabla personal mide **0x2C** (44 bytes) en vez de 0x4C/0x3C, y cada juego
  la guarda en una ruta distinta: HGSS en ``pbr/personal.narc`` (501 especies),
  Platino en ``poketool/personal/pl_personal.narc`` (508) y Perla en
  ``poketool/personal_pearl/personal.narc``.
* La tabla de movimientos mide **0x10** (16 bytes) y trae 471 entradas en los
  tres juegos: HGSS en ``pbr/waza_tbl.narc``, Perla y Platino en
  ``poketool/waza/waza_tbl.narc``.
* **El orden de los campos del movimiento es otro.** En quinta el tipo abre el
  registro; en cuarta lo abre el efecto, y el tipo va en 0x04.
* **La categoría está invertida.** Quinta usa 0=estado, 1=físico, 2=especial;
  cuarta usa 0=físico, 1=especial, 2=estado. Demostrado sin lugar a dudas: de
  los 467 movimientos, los 170 de categoría 2 tienen potencia cero y los 297
  de categoría 0 y 1 tienen potencia mayor que cero, sin una sola excepción.
* **Los identificadores de tipo llevan un hueco.** Cuarta conserva el tipo
  «???» en el índice 9, así que de Fuego en adelante todo va desplazado uno
  respecto al esquema que usa el resto de RoleRun. Se traduce al leer.
* **La precisión cero ya significa «no falla nunca»** (126 movimientos), sin el
  rodeo del 101 que usa quinta.

CONTRA QUÉ SE VALIDÓ EL PARSE

La tabla personal de HeartGold, comparada registro a registro con la copia de
PKHeX (``data/pkhex_personal_hgss.bin``), coincide en **las 501 especies** en
estadísticas base, ritmo de crecimiento y habilidad 1. Las diferencias que
quedan están todas explicadas y se comprobaron una a una, sin ninguna excepción
en 501 registros:

* los tipos, por el hueco del «???» descrito arriba;
* la habilidad 2, porque PKHeX rellena con la 1 los ceros que la ROM deja
  —exactamente la misma normalización que ya se documentó en quinta—;
* y unos pocos bytes de la cola, donde PKHeX anota datos de forma que la ROM
  guarda en otro sitio.

PKHeX publica 508 registros y la ROM 501: los siete de más son entradas de
forma que PKHeX añade por su cuenta. Los 501 primeros están alineados.

No escribe nunca la ROM, el guardado ni la RAM del emulador.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .nds_rom import NdsRomError, open_nds, read_title

PERSONAL_RECORD_SIZE = 0x2C
MOVE_RECORD_SIZE = 0x10
MOVE_COUNT = 471

# Desplazamientos dentro del registro de movimiento de cuarta, demostrados uno
# a uno contra movimientos de datos conocidos (Placaje, Puño Fuego, Ascuas,
# Rayo, Psíquico, Ataque Rápido) y confirmados después sobre los 467.
_MOVE_CATEGORY = 0x02
_MOVE_POWER = 0x03
_MOVE_TYPE = 0x04
_MOVE_ACCURACY = 0x05
_MOVE_PP = 0x06

_CATEGORIES = {0: "physical", 1: "special", 2: "status"}

# Cuarta guarda el tipo «???» en el índice 9. El resto de RoleRun usa el
# esquema de quinta en adelante, que ya no lo tiene.
GEN4_UNKNOWN_TYPE = 9


def normalize_type(type_id: int) -> int:
    """Traduce un identificador de tipo de cuarta al esquema de RoleRun.

    El «???» del índice 9 lo usa un solo movimiento —Maldición— y no lo usa
    ninguna especie de las 501.
    """
    type_id = int(type_id)
    if type_id < GEN4_UNKNOWN_TYPE:
        return type_id
    if type_id == GEN4_UNKNOWN_TYPE:
        return 0
    return type_id - 1


class Gen4RomError(ValueError):
    """El archivo no permite obtener datos de juego demostrados."""


@dataclass(frozen=True, slots=True)
class Gen4Game:
    """Lo que distingue a un juego de cuarta de los otros dos."""

    key: str
    label: str
    titles: frozenset[bytes]
    # Más de una porque los cartuchos cambian de sitio la tabla; se prueban en
    # orden y manda la primera que exista.
    personal_paths: tuple[str, ...]
    personal_count: int
    move_paths: tuple[str, ...]


GEN4_GAMES: dict[str, Gen4Game] = {
    "hgss": Gen4Game(
        key="hgss",
        label="Oro HeartGold/Plata SoulSilver",
        titles=frozenset({b"POKEMON HG\x00\x00", b"POKEMON SS\x00\x00"}),
        personal_paths=("pbr/personal.narc",),
        personal_count=501,
        move_paths=("pbr/waza_tbl.narc", "poketool/waza/waza_tbl.narc"),
    ),
    "pt": Gen4Game(
        key="pt",
        label="Platino",
        titles=frozenset({b"POKEMON PL\x00\x00"}),
        # Platino conserva además la tabla vieja de Diamante y Perla en
        # `poketool/personal/personal.narc`, que NO es la que usa el juego.
        personal_paths=("poketool/personal/pl_personal.narc",),
        personal_count=508,
        move_paths=("poketool/waza/waza_tbl.narc",),
    ),
    "dp": Gen4Game(
        key="dp",
        label="Diamante/Perla",
        titles=frozenset({b"POKEMON D\x00\x00\x00", b"POKEMON P\x00\x00\x00"}),
        personal_paths=(
            "poketool/personal_pearl/personal.narc",
            "poketool/personal_diamond/personal.narc",
            "poketool/personal/personal.narc",
        ),
        personal_count=501,
        move_paths=("poketool/waza/waza_tbl.narc",),
    ),
}


@dataclass(frozen=True, slots=True)
class Gen4Move:
    type_id: int
    category: str
    power: int
    accuracy: int
    pp: int


@dataclass(frozen=True, slots=True)
class Gen4RomProfile:
    source: Path
    game: Gen4Game
    game_code: str
    title: str
    # El bloque personal crudo, tal cual lo guarda la ROM.
    personal: bytes
    moves: tuple[Gen4Move, ...]

    @property
    def name(self) -> str:
        return self.source.name

    def __str__(self) -> str:
        return self.source.name

    def move(self, move_id: int) -> Gen4Move | None:
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

    def type_id(self, move_id: int) -> int | None:
        """Tipo ya normalizado al esquema de quinta en adelante (0=normal…16=siniestro)."""
        move = self.move(move_id)
        return int(move.type_id) if move is not None else None


def _narc_alguno(rom, rutas: tuple[str, ...], que: str, juego: Gen4Game) -> list[bytes]:
    for ruta in rutas:
        try:
            return rom.narc(ruta)
        except NdsRomError:
            continue
    raise Gen4RomError(
        f"{juego.label} no trae {que} en ninguna de sus rutas conocidas."
    )


def _parse_personal(archivos: list[bytes], juego: Gen4Game) -> bytes:
    tamano = PERSONAL_RECORD_SIZE
    # El primer registro es un hueco y algunas ROM lo graban más corto. Se
    # rellena en vez de descartarlo: si no, todas las especies se desplazarían.
    registros = [a.ljust(tamano, b"\x00") for a in archivos if len(a) <= tamano]
    if len(registros) != juego.personal_count:
        raise Gen4RomError(
            f"La tabla personal de {juego.label} declara {len(registros)} especies "
            f"y no {juego.personal_count}."
        )
    bloque = b"".join(registros)
    # Una tabla con estadísticas base imposibles no es una tabla personal. El
    # registro cero es el hueco y va a propósito a ceros.
    for indice in range(1, juego.personal_count):
        crudo = bloque[indice * tamano:(indice + 1) * tamano]
        if any(not 1 <= valor <= 255 for valor in crudo[:6]):
            raise Gen4RomError(
                f"La tabla personal de {juego.label} declara estadísticas "
                f"imposibles en la especie #{indice}."
            )
    return bloque


def _parse_moves(archivos: list[bytes], juego: Gen4Game) -> tuple[Gen4Move, ...]:
    if len(archivos) != MOVE_COUNT:
        raise Gen4RomError(
            f"La tabla de movimientos de {juego.label} declara {len(archivos)} "
            f"entradas y no {MOVE_COUNT}."
        )
    movimientos: list[Gen4Move] = []
    for indice, crudo in enumerate(archivos):
        if len(crudo) != MOVE_RECORD_SIZE:
            raise Gen4RomError(
                f"El movimiento #{indice} no mide {MOVE_RECORD_SIZE} bytes."
            )
        categoria = _CATEGORIES.get(crudo[_MOVE_CATEGORY])
        if categoria is None:
            raise Gen4RomError(
                f"El movimiento #{indice} declara una categoría desconocida "
                f"({crudo[_MOVE_CATEGORY]})."
            )
        pp = crudo[_MOVE_PP]
        # Las últimas entradas del contenedor son relleno a ceros; solo se
        # exige PP a los movimientos de verdad.
        if indice and pp <= 0 and any(crudo):
            raise Gen4RomError(f"El movimiento #{indice} declara cero PP.")
        precision = crudo[_MOVE_ACCURACY]
        if precision > 100:
            precision = 0
        movimientos.append(Gen4Move(
            type_id=normalize_type(crudo[_MOVE_TYPE]),
            category=categoria,
            power=crudo[_MOVE_POWER],
            accuracy=precision,
            pp=pp,
        ))
    return tuple(movimientos)


def game_for_title(titulo: bytes) -> Gen4Game | None:
    """Qué juego de cuarta es este cartucho, si lo es."""
    for juego in GEN4_GAMES.values():
        if titulo in juego.titles:
            return juego
    return None


def load_gen4_rom_profile(path, game_key: str | None = None) -> Gen4RomProfile:
    """Lee la ROM y publica sus datos de juego, o falla sin publicar nada."""
    ruta = Path(path)
    try:
        rom = open_nds(ruta)
    except NdsRomError as exc:
        raise Gen4RomError(str(exc)) from exc

    juego = game_for_title(rom.title)
    legible = rom.title.decode("ascii", "replace").rstrip("\x00")
    if juego is None:
        raise Gen4RomError(
            f"{ruta.name} no es una ROM de cuarta generación (dice «{legible}»)."
        )
    if game_key is not None and juego.key != game_key:
        esperado = GEN4_GAMES[game_key].label
        raise Gen4RomError(
            f"{ruta.name} es {juego.label} y aquí hace falta {esperado}."
        )

    try:
        personal = _parse_personal(
            _narc_alguno(rom, juego.personal_paths, "la tabla personal", juego), juego,
        )
        movimientos = _parse_moves(
            _narc_alguno(rom, juego.move_paths, "la tabla de movimientos", juego), juego,
        )
    except NdsRomError as exc:
        raise Gen4RomError(str(exc)) from exc

    return Gen4RomProfile(
        source=ruta,
        game=juego,
        game_code=rom.game_code,
        title=legible,
        personal=personal,
        moves=movimientos,
    )


@lru_cache(maxsize=8)
def _cached_profile(ruta: str, game_key: str | None, mtime: int, tamano: int) -> Gen4RomProfile:
    del mtime, tamano       # forman parte de la clave: una ROM nueva se relee
    return load_gen4_rom_profile(ruta, game_key)


def load_gen4_rom_profile_cached(path, game_key: str | None = None) -> Gen4RomProfile:
    """Igual que ``load_gen4_rom_profile``, cacheando por ruta y contenido."""
    ruta = Path(path)
    try:
        info = ruta.stat()
    except OSError as exc:
        raise Gen4RomError(f"No se pudo leer {ruta.name}.") from exc
    return _cached_profile(
        str(ruta.resolve()), game_key, int(info.st_mtime), int(info.st_size),
    )


def discover_gen4_rom(save_path, game_key: str | None = None) -> Path | None:
    """Busca la ROM a partir del guardado que la Run tiene abierto."""
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
