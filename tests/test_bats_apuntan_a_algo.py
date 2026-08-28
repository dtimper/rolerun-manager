"""Todo `.bat` tiene que apuntar a un archivo que exista.

El usuario no usa la línea de comandos: cada diagnóstico se le entrega como un
`.bat` de doble clic, y si el `.bat` está roto se pierde el viaje entero —hay que
pedirle que vuelva a reproducir lo lento y a medirlo—.

`ver_lentitud.bat` se generó con `printf` y el `\\v` de `tools\\ver_lentitud.py`
se convirtió en un tabulador vertical: quedó `toolser_lentitud.py`, un archivo
que no existe. La consola no dijo nada útil y la medición no salió.

De ahí las dos comprobaciones: que la ruta exista, y que en el `.bat` no haya
quedado ningún carácter de control de una expansión mal hecha.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

#: Lo que un `.bat` puede llevar además de texto imprimible.
PERMITIDOS = {"\r", "\n", "\t"}

#: `py -3 x.py`, `python x.py`, con o sin comillas.
INVOCACION = re.compile(
    r"""(?:^|\s)(?:py\s+-3|python)\s+"?([^\s"<>|&]+\.py)"?""",
    re.MULTILINE,
)


def _bats() -> list[Path]:
    encontrados = sorted(RAIZ.glob("*.bat"))
    assert encontrados, "no se encontró ningún .bat"
    return encontrados


def test_ningun_bat_lleva_caracteres_de_control() -> None:
    """Un tabulador vertical dentro de una ruta la parte en dos sin avisar."""
    sucios = []
    for bat in _bats():
        crudo = bat.read_bytes().decode("ascii", errors="replace")
        for numero, linea in enumerate(crudo.splitlines(), 1):
            raros = {c for c in linea if ord(c) < 32 and c not in PERMITIDOS}
            if raros:
                sucios.append(
                    f"{bat.name}:{numero} lleva {sorted(hex(ord(c)) for c in raros)}"
                )
    assert not sucios, "\n  ".join(["caracteres de control en un .bat:"] + sucios)


def test_todo_script_invocado_por_un_bat_existe() -> None:
    perdidos = []
    for bat in _bats():
        texto = bat.read_text(encoding="ascii", errors="replace")
        for ruta in INVOCACION.findall(texto):
            if ruta.startswith("%"):
                continue                       # se compone en tiempo de ejecución
            destino = RAIZ / ruta.replace("\\", "/")
            if not destino.is_file():
                perdidos.append(f"{bat.name} llama a {ruta!r}, que no existe")
    assert not perdidos, "\n  ".join(["un .bat apunta a la nada:"] + perdidos)
