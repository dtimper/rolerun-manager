"""Escribe las notas de una Release a partir de ``CHANGELOG.md``.

Uso:

    python tools/notas_de_version.py 0.4.2 notas.md

Sin el segundo argumento, las escribe en pantalla.

Toma el bloque que va justo debajo de la cabecera ``# vX.Y.Z`` (el resumen
para el jugador, hasta la siguiente cabecera) y le añade cómo instalar o
actualizar. Lo usa ``.github/workflows/publicar.yml``: si esa cabecera no
existe, falla, y así no se puede publicar una versión sin contar qué trae.

Esas notas son lo que ve el jugador en el aviso de versión nueva del
programa (limpiadas de Markdown por ``update_checker.notas_legibles``) y en
la página de la Release.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

COMO_INSTALAR = """## Cómo instalar o actualizar

1. Descarga **RoleRunManager-Setup.exe** (aquí abajo, en «Assets»).
2. Ábrelo. Si Windows avisa de que «protegió su PC», pulsa «Más información» y
   luego «Ejecutar de todas formas»: el programa no tiene firma digital de pago.
3. Sigue los pasos. Si ya tenías RoleRun Manager, se instala encima.

No hace falta instalar nada más: Python y .NET van dentro. Tus Runs no se
tocan: se guardan aparte, en Documentos\\RoleRun Manager."""


def resumen(texto_changelog: str, version: str) -> str:
    version = version.strip().lstrip("vV")
    cabecera = re.compile(rf"^# v{re.escape(version)}(?:\s|$).*$", re.MULTILINE)
    encontrada = cabecera.search(texto_changelog)
    if not encontrada:
        raise ValueError(f"CHANGELOG.md no tiene la cabecera «# v{version}».")
    resto = texto_changelog[encontrada.end():]
    siguiente = re.search(r"^#{1,2} ", resto, re.MULTILINE)
    bloque = (resto[: siguiente.start()] if siguiente else resto).strip()
    if not bloque:
        raise ValueError(f"La cabecera «# v{version}» no tiene resumen debajo.")
    return bloque


def notas(texto_changelog: str, version: str) -> str:
    return f"## Novedades\n\n{resumen(texto_changelog, version)}\n\n{COMO_INSTALAR}\n"


def main(argumentos: list[str]) -> int:
    if len(argumentos) not in (1, 2):
        print(__doc__, file=sys.stderr)
        return 1
    try:
        texto = notas(CHANGELOG.read_text(encoding="utf-8"), argumentos[0])
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if len(argumentos) == 2:
        # Directo a archivo: redirigir con «>» en PowerShell (GitHub) volvía
        # a codificar la salida y podía estropear los acentos.
        Path(argumentos[1]).write_bytes(texto.encode("utf-8"))
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
