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

from app.update_checker import DismissedVersionStore, is_newer


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
