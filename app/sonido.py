"""Los sonidos de la interfaz. Se sintetizan aquí y se pueden sustituir.

RoleRun no trae archivos de audio: los genera la primera vez en
``Documentos\\RoleRun Manager\\Sonidos``. Eso resuelve dos cosas a la vez —no
hay que buscar efectos ni cargar con licencias, y suenan desde el primer
arranque— y deja la puerta abierta a lo importante: **si dejas ahí un WAV con el
mismo nombre, se usa el tuyo**. Los generados no se vuelven a escribir si el
archivo ya existe.

Se sintetiza con `wave` y `math` a pelo. En esta máquina no hay numpy ni pygame,
y añadir una dependencia para seis pitidos de treinta milisegundos no compensa.

## Por qué suenan en un hilo aparte

`winsound.PlaySound` bloquea al llamante mientras Windows arranca el sonido,
aunque sea con ``SND_ASYNC``. Hacerlo en el hilo de Tk metería un tirón en cada
paso del ratón por la caja del PC, que es justo donde más se notaría.

## Por qué el ratón tiene freno

Recorrer una caja del PC pasa por treinta casillas en menos de un segundo.
Sin un mínimo entre sonidos eso es una ametralladora, no una interfaz.
"""

from __future__ import annotations

import math
import struct
import threading
import time
import wave
from pathlib import Path

from .config import USER_DATA_DIR

#: Donde viven. El usuario puede sustituir cualquiera por el suyo.
SONIDOS_DIR = USER_DATA_DIR / "Sonidos"

_FRECUENCIA = 22050
_AMPLITUD = 20000

#: Mínimo entre dos sonidos del ratón, en segundos. Una caja del PC son treinta
#: casillas y se recorren en menos de un segundo.
FRENO_DEL_RATON = 0.06


def _envolvente(posicion: float, ataque: float = 0.08, caida: float = 0.55) -> float:
    """Sube rápido y baja suave. Sin esto, cada sonido empieza con un chasquido."""
    if posicion < ataque:
        return posicion / ataque
    if posicion > 1.0 - caida:
        return max(0.0, (1.0 - posicion) / caida)
    return 1.0


def _tono(muestras: list[float], hercios: float, desde: float, hasta: float,
          volumen: float = 1.0, armonico: float = 0.0) -> None:
    """Añade un tono entre dos instantes, en segundos, sobre lo ya escrito."""
    inicio = int(desde * _FRECUENCIA)
    fin = min(len(muestras), int(hasta * _FRECUENCIA))
    largo = max(1, fin - inicio)
    for indice in range(inicio, fin):
        t = (indice - inicio) / _FRECUENCIA
        forma = math.sin(2 * math.pi * hercios * t)
        if armonico:
            forma += armonico * math.sin(4 * math.pi * hercios * t)
        muestras[indice] += (
            forma * volumen * _envolvente((indice - inicio) / largo)
        )


def _escribir(ruta: Path, muestras: list[float], volumen: float) -> None:
    pico = max((abs(v) for v in muestras), default=1.0) or 1.0
    escala = (_AMPLITUD * max(0.0, min(1.0, volumen))) / pico
    crudo = b"".join(
        struct.pack("<h", int(max(-32767, min(32767, valor * escala))))
        for valor in muestras
    )
    with wave.open(str(ruta), "wb") as salida:
        salida.setnchannels(1)
        salida.setsampwidth(2)
        salida.setframerate(_FRECUENCIA)
        salida.writeframes(crudo)


def _lienzo(segundos: float) -> list[float]:
    return [0.0] * int(segundos * _FRECUENCIA)


def _raton() -> list[float]:
    """Un roce. Tiene que poder oírse treinta veces seguidas sin cansar."""
    muestras = _lienzo(0.035)
    _tono(muestras, 1180, 0.0, 0.035, volumen=0.45)
    return muestras


def _seleccion() -> list[float]:
    muestras = _lienzo(0.07)
    _tono(muestras, 760, 0.0, 0.035, volumen=0.7)
    _tono(muestras, 1140, 0.028, 0.07, volumen=0.8)
    return muestras


def _confirmacion() -> list[float]:
    """Tres notas que suben. Es el «hecho» de mover un Pokémon o aplicar algo."""
    muestras = _lienzo(0.34)
    for indice, hercios in enumerate((523.25, 659.25, 783.99)):
        arranque = indice * 0.075
        _tono(muestras, hercios, arranque, arranque + 0.19,
              volumen=0.75, armonico=0.18)
    return muestras


def _error() -> list[float]:
    muestras = _lienzo(0.3)
    _tono(muestras, 330, 0.0, 0.16, volumen=0.8, armonico=0.25)
    _tono(muestras, 233, 0.12, 0.3, volumen=0.8, armonico=0.25)
    return muestras


def _giro_de_drafteo() -> list[float]:
    """El tic de cada vuelta del randomizador. Corto y seco."""
    muestras = _lienzo(0.045)
    _tono(muestras, 1560, 0.0, 0.02, volumen=0.55)
    _tono(muestras, 900, 0.012, 0.045, volumen=0.4)
    return muestras


def _revelado_de_drafteo() -> list[float]:
    """Lo que suena al abrirse. Es el momento característico de RoleRun."""
    muestras = _lienzo(0.6)
    for indice, hercios in enumerate((659.25, 987.77, 1318.51, 1567.98)):
        arranque = indice * 0.055
        _tono(muestras, hercios, arranque, arranque + 0.42,
              volumen=0.55 + indice * 0.1, armonico=0.22)
    return muestras


#: Cada sonido y cómo se sintetiza si no existe ya un archivo del usuario.
CATALOGO = {
    "raton": _raton,
    "seleccion": _seleccion,
    "confirmacion": _confirmacion,
    "error": _error,
    "drafteo_giro": _giro_de_drafteo,
    "drafteo_revelado": _revelado_de_drafteo,
}


def preparar(carpeta: Path | None = None, volumen: float = 0.6) -> dict[str, Path]:
    """Deja los sonidos en disco y devuelve dónde está cada uno.

    Nunca sobrescribe: un archivo que ya está es el que el usuario ha querido
    poner, aunque lo hubiéramos generado nosotros.
    """
    base = Path(carpeta) if carpeta is not None else SONIDOS_DIR
    rutas: dict[str, Path] = {}
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        return rutas
    for nombre, sintetizar in CATALOGO.items():
        ruta = base / f"{nombre}.wav"
        if not ruta.is_file():
            try:
                _escribir(ruta, sintetizar(), volumen)
            except Exception:
                continue
        rutas[nombre] = ruta
    return rutas


class Sonidos:
    """Reproduce los efectos sin bloquear la interfaz.

    Apagarlo lo apaga de verdad: no se abre ningún hilo ni se toca el disco.
    """

    def __init__(
        self,
        carpeta: Path | None = None,
        *,
        activo: bool = True,
        volumen: float = 0.6,
        reproductor=None,
    ) -> None:
        self.activo = bool(activo)
        self._reproductor = reproductor or self._reproducir_con_windows
        self._rutas = preparar(carpeta, volumen) if self.activo else {}
        self._ultimo_raton = 0.0

    @staticmethod
    def _reproducir_con_windows(ruta: Path) -> None:
        import winsound

        winsound.PlaySound(
            str(ruta), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )

    def reproducir(self, nombre: str) -> bool:
        """Suena, si está activo y existe. Devuelve si llegó a lanzarse.

        Un sonido que no se puede reproducir no puede tumbar lo que el usuario
        estaba haciendo: se traga en silencio y se sigue.
        """
        if not self.activo:
            return False
        ruta = self._rutas.get(str(nombre))
        if ruta is None or not ruta.is_file():
            return False
        if nombre == "raton":
            ahora = time.monotonic()
            if ahora - self._ultimo_raton < FRENO_DEL_RATON:
                return False
            self._ultimo_raton = ahora
        try:
            hilo = threading.Thread(
                target=self._lanzar, args=(ruta,),
                name="RoleRunSonido", daemon=True,
            )
            hilo.start()
        except Exception:
            return False
        return True

    def _lanzar(self, ruta: Path) -> None:
        try:
            self._reproductor(ruta)
        except Exception:
            pass
