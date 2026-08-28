"""Guardar un fallo de una pulsación, para revisarlo después.

Durante un directo no se puede parar a escribir lo que ha pasado, y contarlo de
memoria al terminar pierde justo lo que hace falta: la hora exacta, qué había en
pantalla y qué estaba leyendo o escribiendo RoleRun en ese momento.

Por eso esto no abre ningún diálogo ni pregunta nada. Una pulsación deja una
carpeta con todo lo que había alrededor de ese instante:

===================  ==============================================
``contexto.json``    versión, juego, página, equipo, cambios pendientes
``pantalla.png``     lo que se veía, si se pudo capturar
``bdsp_trace.jsonl`` la cola de la traza del juego en vivo
``tiempos.jsonl``    la cola de la medición de tiempos
``nota.txt``         para escribir después, si apetece
===================  ==============================================

Las colas se recortan a lo reciente: un directo largo deja trazas de megabytes y
lo que importa son los segundos anteriores al fallo.

Nada de esto puede tumbar lo que el usuario estaba haciendo. Si falla una parte,
se anota dentro del propio informe y las demás se guardan igual: un informe
incompleto sirve; perder la partida por intentar guardarlo, no.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import APP_VERSION, LOG_DIR, USER_DATA_DIR

#: Dónde se acumulan. El usuario entrega esta carpeta entera al terminar.
BUGS_DIR = USER_DATA_DIR / "Bugs"

#: Cuánta cola de cada registro se copia. Con esto sobran varios minutos.
LINEAS_DE_COLA = 400

#: Registros que acompañan a cada informe.
REGISTROS = (
    ("bdsp_trace.jsonl", "bdsp_realtime_trace_latest.jsonl"),
    ("usum_battle_health.jsonl", "usum_battle_health_trace_latest.jsonl"),
)


def _cola(origen: Path, destino: Path, lineas: int = LINEAS_DE_COLA) -> str | None:
    """Copia las últimas líneas de un registro. Devuelve el fallo, si lo hubo."""
    try:
        if not origen.is_file():
            return f"{origen.name}: no existe"
        contenido = origen.read_text(encoding="utf-8", errors="replace").splitlines()
        destino.write_text(
            "\n".join(contenido[-lineas:]) + "\n", encoding="utf-8",
        )
    except Exception as error:
        return f"{origen.name}: {type(error).__name__}: {error}"
    return None


def _tiempos_de_hoy(carpeta: Path) -> str | None:
    nombre = f"perf_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    return _cola(LOG_DIR / nombre, carpeta / "tiempos.jsonl")


def _pantalla(carpeta: Path) -> str | None:
    """Captura la pantalla. Es lo primero que se mira y lo que menos se explica."""
    try:
        from PIL import ImageGrab

        imagen = ImageGrab.grab(all_screens=True)
        imagen.save(carpeta / "pantalla.png")
    except Exception as error:
        return f"pantalla: {type(error).__name__}: {error}"
    return None


def guardar_reporte(
    contexto: Callable[[], dict[str, Any]] | dict[str, Any] | None = None,
    *,
    nota: str = "",
    carpeta_base: Path | None = None,
    con_pantalla: bool = True,
) -> Path:
    """Deja un informe y devuelve su carpeta. No propaga nunca.

    ``contexto`` puede ser un diccionario o algo que lo devuelva; si al pedirlo
    falla, el informe se guarda igual con el fallo anotado dentro. Perder el
    informe entero porque una de sus partes no se pudo leer sería lo peor.
    """
    base = Path(carpeta_base) if carpeta_base is not None else BUGS_DIR
    marca = datetime.now()
    carpeta = base / f"bug_{marca.strftime('%Y-%m-%d_%H-%M-%S')}"
    problemas: list[str] = []
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Sin carpeta no hay informe. Se intenta al lado del ejecutable antes de
        # rendirse, porque durante un directo no habrá una segunda oportunidad.
        carpeta = Path.cwd() / f"bug_{marca.strftime('%Y-%m-%d_%H-%M-%S')}"
        carpeta.mkdir(parents=True, exist_ok=True)

    datos: dict[str, Any] = {}
    try:
        datos = dict(contexto() if callable(contexto) else (contexto or {}))
    except Exception as error:
        problemas.append(f"contexto: {type(error).__name__}: {error}")

    if con_pantalla:
        fallo = _pantalla(carpeta)
        if fallo:
            problemas.append(fallo)

    for nombre, origen in REGISTROS:
        fallo = _cola(LOG_DIR / origen, carpeta / nombre)
        if fallo:
            problemas.append(fallo)
    fallo = _tiempos_de_hoy(carpeta)
    if fallo:
        problemas.append(fallo)

    cuerpo = {
        "cuando": marca.isoformat(timespec="seconds"),
        "version": APP_VERSION,
        "nota": str(nota or ""),
        **datos,
    }
    if problemas:
        cuerpo["no_se_pudo_recoger"] = problemas
    try:
        (carpeta / "contexto.json").write_text(
            json.dumps(cuerpo, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass
    try:
        (carpeta / "nota.txt").write_text(
            "Escribe aquí lo que pasó, si te apetece. Con la hora y la captura\n"
            "suele bastar, así que no hace falta parar el directo por esto.\n\n"
            f"{nota or ''}\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    return carpeta


def informes(carpeta_base: Path | None = None) -> list[Path]:
    """Los informes guardados, del más reciente al más antiguo."""
    base = Path(carpeta_base) if carpeta_base is not None else BUGS_DIR
    if not base.is_dir():
        return []
    return sorted(
        (hijo for hijo in base.iterdir() if hijo.is_dir() and hijo.name.startswith("bug_")),
        reverse=True,
    )


def empaquetar(carpeta_base: Path | None = None, destino: Path | None = None) -> Path | None:
    """Mete todos los informes en un zip, para entregarlos de una vez.

    El zip se deja **fuera** de la carpeta de informes: dentro se incluiría a sí
    mismo, y cada empaquetado sería más grande que el anterior.
    """
    base = Path(carpeta_base) if carpeta_base is not None else BUGS_DIR
    if not informes(base):
        return None
    nombre = destino or (
        base.parent / f"bugs_{datetime.now().strftime('%Y-%m-%d_%H-%M')}"
    )
    try:
        ruta = shutil.make_archive(str(nombre), "zip", root_dir=str(base))
    except Exception:
        return None
    return Path(ruta)
