"""Un sprite que no llega no puede dejar RoleRun en la pantalla de carga.

La barrera inicial exige que todas las especies de la party estén en
``sprite_pil_cache`` antes de publicar la interfaz. Cuando la descarga fallaba
—sin Internet y sin la imagen ya en disco— el worker terminaba en silencio sin
publicar nada, así que esa condición no se cumplía nunca y el cargador se
quedaba indefinidamente.

Decisión del proyecto (27-08-2026): silueta local y aviso no bloqueante. La
ausencia de una imagen nunca puede impedir jugar.
"""

from __future__ import annotations

import queue
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import SPRITE_DOWNLOAD_TIMEOUT_SECONDS, RoleRunManager  # noqa: E402


class _SpriteHarness:
    """Solo el estado que tocan la cola de sprites y sus avisos."""

    def __init__(self) -> None:
        self.sprite_queue: queue.SimpleQueue = queue.SimpleQueue()
        self.sprite_pil_cache: dict[int, Image.Image] = {}
        self._sprite_placeholder_species: set[int] = set()
        self._sprite_requests_in_flight: set[int] = set()
        self.project = None
        self.current_game = None
        self.avisos: list[tuple[str, str, bool]] = []
        self.aplicados: list[tuple[int, Image.Image]] = []
        self.refrescos = 0

    def _apply_sprite(self, slot, image):
        self.aplicados.append((slot, image))

    def _schedule_sprite_page_refresh(self):
        self.refrescos += 1

    def _show_live_sync_toast(self, title, detail, success):
        self.avisos.append((title, detail, success))

    def winfo_exists(self):
        return False  # corta el reenganche de ``after`` sin Tk

    _placeholder_sprite_image = staticmethod(RoleRunManager._placeholder_sprite_image)
    _poll_sprite_queue = RoleRunManager._poll_sprite_queue
    _notify_missing_sprites = RoleRunManager._notify_missing_sprites
    _retry_placeholder_sprites = RoleRunManager._retry_placeholder_sprites


def test_la_silueta_local_se_dibuja_sin_red_ni_archivos() -> None:
    imagen = RoleRunManager._placeholder_sprite_image()
    assert imagen.size == (92, 92)
    assert imagen.mode == "RGBA"
    # No puede ser un cuadro transparente: tiene que verse algo.
    assert imagen.getchannel("A").getextrema()[1] > 0


def test_un_sprite_que_falla_deja_de_bloquear_la_barrera() -> None:
    harness = _SpriteHarness()
    harness.sprite_queue.put((0, 498, None))

    harness._poll_sprite_queue()

    # La condición que la barrera comprueba es exactamente esta pertenencia.
    assert 498 in harness.sprite_pil_cache
    assert 498 in harness._sprite_placeholder_species
    assert harness.aplicados and harness.aplicados[0][0] == 0


def test_el_aviso_es_uno_solo_y_no_bloqueante() -> None:
    harness = _SpriteHarness()
    for slot, species in ((0, 498), (1, 501)):
        harness.sprite_queue.put((slot, species, None))

    harness._poll_sprite_queue()

    assert len(harness.avisos) == 1
    titulo, detalle, exito = harness.avisos[0]
    assert exito is False
    assert "2 imágenes" in detalle
    # El aviso debe dejar claro que solo falta la imagen.
    assert "silueta" in detalle

    # Repetir la misma especie no vuelve a avisar.
    harness.sprite_queue.put((0, 498, None))
    harness._poll_sprite_queue()
    assert len(harness.avisos) == 1


def test_un_aviso_roto_no_impide_publicar_la_partida() -> None:
    harness = _SpriteHarness()

    def revienta(*args, **kwargs):
        raise RuntimeError("la shell aún no existe")

    harness._show_live_sync_toast = revienta
    harness.sprite_queue.put((0, 498, None))

    harness._poll_sprite_queue()

    assert 498 in harness.sprite_pil_cache


def test_un_sprite_correcto_no_se_marca_como_ausente() -> None:
    harness = _SpriteHarness()
    real = Image.new("RGBA", (92, 92), (10, 20, 30, 255))
    harness.sprite_queue.put((2, 498, real))

    harness._poll_sprite_queue()

    assert harness.sprite_pil_cache[498] is real
    assert harness._sprite_placeholder_species == set()
    assert harness.avisos == []


def test_recargar_la_partida_reintenta_solo_las_ausentes() -> None:
    harness = _SpriteHarness()
    real = Image.new("RGBA", (92, 92), (10, 20, 30, 255))
    harness.sprite_queue.put((0, 498, None))
    harness.sprite_queue.put((1, 501, real))
    harness._poll_sprite_queue()

    harness._retry_placeholder_sprites()

    assert 498 not in harness.sprite_pil_cache, "la ausente debe reintentarse"
    assert harness.sprite_pil_cache[501] is real, "la buena no se descarta"
    assert harness._sprite_placeholder_species == set()


def test_la_cola_libera_el_dedupe_para_permitir_reintentos() -> None:
    harness = _SpriteHarness()
    harness._sprite_requests_in_flight.add(498)
    harness.sprite_queue.put((0, 498, None))

    harness._poll_sprite_queue()

    assert harness._sprite_requests_in_flight == set()


def test_una_peticion_en_vuelo_no_se_duplica() -> None:
    lanzados: list[str] = []
    manager = SimpleNamespace(
        _sprite_requests_in_flight={498},
        sprite_queue=queue.SimpleQueue(),
    )
    pokemon = SimpleNamespace(species_id=498, slot=0)

    RoleRunManager._load_sprite_async(manager, pokemon)

    assert lanzados == []
    with pytest.raises(queue.Empty):
        manager.sprite_queue.get_nowait()


def test_la_descarga_tiene_un_limite_de_tiempo() -> None:
    """Sin timeout, una red no enrutada cuelga el hilo para siempre."""
    assert 0 < SPRITE_DOWNLOAD_TIMEOUT_SECONDS <= 30
