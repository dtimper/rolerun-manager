"""El sprite se redimensiona una vez, no una por tarjeta.

`sprite_pil_cache` guardaba el PNG decodificado, pero cada tarjeta hacía después
su propia copia y su propio LANCZOS. Medido con los sprites del proyecto, que
son PNG de 512x512:

    copy() + thumbnail LANCZOS a 118 px .... 3,77 ms por sprite
    devolver uno ya hecho .................. 0,00 ms

Una caja del PC son treinta tarjetas: 113 ms de repintado gastados en rehacer
exactamente lo mismo, más 23 del equipo. Y la página se repinta entera cada vez
que termina de bajar un sprite.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402


class _Mono:
    def __init__(self, species_id: int = 158) -> None:
        self.species_id = species_id


def _banco(monkeypatch, *, origen: Image.Image | None = None):
    """Un objeto mínimo con lo que `_sprite_image` necesita."""
    import app.ui as ui

    creadas: list[tuple[int, int]] = []

    class _ImagenFalsa:
        def __init__(self, light_image=None, dark_image=None, size=None) -> None:
            self.size = size
            creadas.append(tuple(size))

    monkeypatch.setattr(ui.ctk, "CTkImage", _ImagenFalsa)

    fuentes: list[int] = []

    def _fuente(self, pokemon):
        fuentes.append(pokemon.species_id)
        if origen is None:
            return None
        return origen.copy()

    yo = types.SimpleNamespace(_sprite_image_cache={})
    yo._sprite_source = lambda pokemon: _fuente(yo, pokemon)
    return yo, fuentes, creadas


def test_el_mismo_sprite_al_mismo_tamano_se_redimensiona_una_vez(monkeypatch) -> None:
    origen = Image.new("RGBA", (512, 512), (10, 20, 30, 255))
    yo, fuentes, creadas = _banco(monkeypatch, origen=origen)

    mono = _Mono()
    primera = RoleRunManager._sprite_image(yo, mono, (118, 118))
    for _ in range(29):                      # las treinta de una caja del PC
        otra = RoleRunManager._sprite_image(yo, _Mono(), (118, 118))
        assert otra is primera, "cada tarjeta volvió a redimensionar"

    assert len(fuentes) == 1, f"se leyó el sprite {len(fuentes)} veces"
    assert len(creadas) == 1


def test_cada_tamano_tiene_el_suyo(monkeypatch) -> None:
    origen = Image.new("RGBA", (512, 512), (10, 20, 30, 255))
    yo, _fuentes, creadas = _banco(monkeypatch, origen=origen)

    grande = RoleRunManager._sprite_image(yo, _Mono(), (118, 118))
    pequeno = RoleRunManager._sprite_image(yo, _Mono(), (31, 31))

    assert grande is not pequeno
    assert sorted(creadas) == [(31, 31), (118, 118)]


def test_sin_sprite_todavia_no_se_cachea_nada(monkeypatch) -> None:
    """Si se cacheara el hueco, el sprite que llega después no se vería nunca."""
    yo, _fuentes, _creadas = _banco(monkeypatch, origen=None)

    assert RoleRunManager._sprite_image(yo, _Mono(), (118, 118)) is None
    assert yo._sprite_image_cache == {}


def test_sin_pokemon_no_hay_imagen(monkeypatch) -> None:
    yo, _fuentes, _creadas = _banco(monkeypatch, origen=None)
    assert RoleRunManager._sprite_image(yo, None, (118, 118)) is None


def test_un_sprite_que_llega_tarde_invalida_lo_redimensionado() -> None:
    """La silueta de ausencia no puede quedarse cacheada para siempre."""
    import inspect

    fuente = inspect.getsource(RoleRunManager._drain_sprite_queue) if hasattr(
        RoleRunManager, "_drain_sprite_queue",
    ) else ""
    if not fuente:
        # El nombre del método cambió: se busca en el módulo entero.
        fuente = Path(
            Path(__file__).resolve().parent.parent / "app" / "ui.py"
        ).read_text(encoding="utf-8")
    assert "self.sprite_pil_cache[species_id] = image" in fuente
    indice = fuente.index("self.sprite_pil_cache[species_id] = image")
    despues = fuente[indice:indice + 400]
    assert "_sprite_image_cache" in despues, (
        "el sprite que llega no invalida lo que se hubiera redimensionado"
    )
