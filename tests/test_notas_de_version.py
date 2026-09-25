"""Las notas de cada Release salen de la cabecera «# vX.Y.Z» del CHANGELOG.

GitHub las publica solo (.github/workflows/publicar.yml) y son lo que el
jugador lee en el aviso de versión nueva: sin cabecera no se publica.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_RUTA = Path(__file__).resolve().parent.parent / "tools" / "notas_de_version.py"
_spec = importlib.util.spec_from_file_location("notas_de_version", _RUTA)
notas_de_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notas_de_version)

CHANGELOG = """> cabecera del archivo

# v0.5.0 — publicada el 01-10-2026

- Instalador sin requisitos.
- Página web.

## Detalle técnico de algo (01-10-2026)

Texto técnico que no va a las notas.

# v0.4.1 — publicada el 25-09-2026

- Icono de las ventanas.
"""


def test_toma_solo_el_resumen_de_esa_version() -> None:
    assert notas_de_version.resumen(CHANGELOG, "v0.5.0") == "- Instalador sin requisitos.\n- Página web."
    assert notas_de_version.resumen(CHANGELOG, "0.4.1") == "- Icono de las ventanas."


def test_las_notas_explican_como_instalar() -> None:
    notas = notas_de_version.notas(CHANGELOG, "v0.5.0")
    assert notas.startswith("## Novedades\n\n- Instalador sin requisitos.")
    assert "RoleRunManager-Setup.exe" in notas and "Ejecutar de todas formas" in notas
    assert "Texto técnico" not in notas


@pytest.mark.parametrize("version", ["v0.6.0", "0.5"])
def test_sin_cabecera_de_esa_version_no_hay_notas(version: str) -> None:
    with pytest.raises(ValueError):
        notas_de_version.resumen(CHANGELOG, version)


def test_la_version_publicada_tiene_su_cabecera_en_el_changelog_real() -> None:
    from app.config import APP_VERSION

    texto = (_RUTA.parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert notas_de_version.resumen(texto, APP_VERSION)
