"""Comparación de versiones y recuerdo de "no avisar" del aviso de actualización.

RoleRun versiona como SemVer con preestrenos con guion (``0.3.1-alpha.26``),
no como PEP 440 (``0.3.1a26``). Estas pruebas fijan esa precedencia -un
preestreno nunca es "más nuevo" que la versión estable del mismo número base-
para que un futuro cambio en el formato de ``APP_VERSION`` no rompa en
silencio la comparación real usada al avisar de una Release nueva.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.update_checker import DismissedVersionStore, is_newer, notas_legibles


@pytest.mark.parametrize(
    "remote, local",
    [
        ("0.3.2", "0.3.1"),
        ("1.0.0", "0.3.1-alpha.26"),
        ("0.3.1-alpha.27", "0.3.1-alpha.26"),
        ("0.3.1-beta.1", "0.3.1-alpha.99"),
        ("0.3.1-rc.1", "0.3.1-beta.9"),
        ("0.10.0", "0.9.0"),
        ("v0.3.2", "0.3.1"),
    ],
)
def test_version_remota_mas_nueva(remote: str, local: str) -> None:
    assert is_newer(remote, local) is True


@pytest.mark.parametrize(
    "remote, local",
    [
        ("0.3.1", "0.3.1"),
        ("0.3.1-alpha.26", "0.3.1-alpha.26"),
        ("0.3.0", "0.3.1"),
        ("0.3.1-alpha.25", "0.3.1-alpha.26"),
        ("0.3.1-alpha.99", "0.3.1"),
    ],
)
def test_version_remota_no_es_mas_nueva(remote: str, local: str) -> None:
    assert is_newer(remote, local) is False


def test_version_ilegible_nunca_dispara_un_aviso_falso() -> None:
    assert is_newer("no-es-una-version", "0.3.1-alpha.26") is False


def test_no_avisar_de_esta_version_persiste_solo_esa_version(tmp_path: Path) -> None:
    store_path = tmp_path / "update_prefs.json"
    store = DismissedVersionStore(store_path)
    assert store.is_dismissed("0.3.2") is False

    store.dismiss("0.3.2")
    assert store.is_dismissed("0.3.2") is True
    assert store.is_dismissed("0.3.3") is False

    # Un reinicio del programa vuelve a leer del disco, no de memoria.
    reloaded = DismissedVersionStore(store_path)
    assert reloaded.is_dismissed("0.3.2") is True


def test_las_notas_en_markdown_se_leen_sin_simbolos() -> None:
    notas = (
        "## Novedades\r\n"
        "- **Combate de seis**: vida y drafteo automáticos.\r\n"
        "* Nuevo botón `REPORTAR FALLO`.\r\n"
        "Más detalles en el [historial](https://example.com/CHANGELOG.md)."
    )
    assert notas_legibles(notas) == (
        "NOVEDADES\n"
        "• Combate de seis: vida y drafteo automáticos.\n"
        "• Nuevo botón REPORTAR FALLO.\n"
        "Más detalles en el historial."
    )


def test_unas_notas_sin_markdown_no_cambian() -> None:
    notas = "Primera versión publicada en GitHub. Avisará de las siguientes."
    assert notas_legibles(notas) == notas
    assert notas_legibles("") == ""


def test_con_instalador_descargar_lo_baja_y_los_pasos_lo_explican(monkeypatch) -> None:
    import io
    import json as json_

    from app import update_checker

    respuesta = {
        "tag_name": "v0.5.0",
        "html_url": "https://github.com/x/y/releases/tag/v0.5.0",
        "body": "## Novedades",
        "assets": [
            {"name": "otro.zip", "browser_download_url": "https://ejemplo/otro.zip"},
            {"name": update_checker.NOMBRE_INSTALADOR,
             "browser_download_url": "https://ejemplo/RoleRunManager-Setup.exe"},
        ],
    }

    class _Respuesta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(
        update_checker.urllib.request, "urlopen",
        lambda *_a, **_k: _Respuesta(json_.dumps(respuesta).encode("utf-8")),
    )
    info = update_checker.check_for_update("0.4.1", "x", "y")

    assert info.installer_url == "https://ejemplo/RoleRunManager-Setup.exe"
    pasos = update_checker.pasos_para_actualizar(info, "C:/Docs/RoleRun Manager")
    assert "RoleRunManager-Setup.exe" in pasos
    assert "Ejecutar de todas formas" in pasos
    assert "instalar_y_abrir.bat" not in pasos
    assert "C:/Docs/RoleRun Manager" in pasos


def test_sin_instalador_se_explica_el_zip_como_hasta_ahora() -> None:
    from app.update_checker import UpdateInfo, pasos_para_actualizar

    info = UpdateInfo(version="0.4.1", url="https://github.com/x/y/releases/tag/v0.4.1", notes="")
    assert info.installer_url == ""
    pasos = pasos_para_actualizar(info, "C:/Docs/RoleRun Manager")
    assert "Source code (zip)" in pasos and "instalar_y_abrir.bat" in pasos
